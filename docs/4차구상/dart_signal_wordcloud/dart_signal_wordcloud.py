"""Build a KRX-sector disclosure word cloud from searchable report chunks.

Extract and normalize chunk-level concepts, filter candidates, score the
three-year signals, then return final-score Top-N. Spread combines 60% company
coverage with 40% normalized company mention entropy. Final score is
0.50*Current + 0.30*Change + 0.20*Spread, less
min(15, max(0, (max_company_share - 0.50)*30)) and 2 for general-business
keywords. At most three rising Top-N keywords are marked hot. Sector
vocabulary comes from ``signal_keyword_rules.py``.
"""
from __future__ import annotations

import argparse
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from dart_db_client import query
from .signal_keyword_rules import (
    ABSTRACT_HEADS, ABSTRACT_MODIFIERS, ACCOUNTING_LABEL_HEADS,
    ACCOUNTING_LABEL_MODIFIERS, ALLOWED_SECTION_PREFIXES, ALLOWED_SUBSECTION_PHRASES,
    DOCUMENT_FIELD_HEADS, DOCUMENT_FIELD_MODIFIERS,
    GENERIC_NOISE_PATTERNS, GENERIC_VOCABULARY, LOW_INFORMATION_PHRASE_TERMS,
    MEASUREMENT_OR_TABLE_TOKENS, PRODUCTION_GENERIC_NOISE_CATEGORIES, SECTOR_VOCABULARIES,
    STOPWORDS, SectorVocabulary,
)


REPORT_TYPES = ("Q1", "H1", "Q3", "FY")
DEFAULT_ANALYSIS_YEARS = (2023, 2024, 2025)
DEFAULT_TOP_COMPANIES = 5
DEFAULT_WORDCLOUD_TOP_N = 12
DEFAULT_PAGE_SIZE = 64
NOUN_TAGS = {"NNG", "NNP", "SL"}
MIN_LATEST_COMPANIES = 2
EARLIER_CHANGE_WEIGHT = 0.4
RECENT_CHANGE_WEIGHT = 0.6
CURRENT_WEIGHT = 0.50
CHANGE_WEIGHT = 0.30
SPREAD_WEIGHT = 0.20
HOT_SCORE_THRESHOLD = 90.0
MAX_INDUSTRY_HOT_KEYWORDS = 3
GENERIC_BUSINESS_PENALTY = 2
CONCENTRATION_FREE_SHARE = 0.50
CONCENTRATION_SLOPE = 30.0
MAX_CONCENTRATION_PENALTY = 15.0
COVERAGE_SPREAD_WEIGHT = 0.60
ENTROPY_SPREAD_WEIGHT = 0.40


@dataclass(frozen=True)
class SignalConfig:
    """Reusable analysis settings for one KRX sector index."""

    index_code: str
    years: tuple[int, int, int] = DEFAULT_ANALYSIS_YEARS
    top_companies: int = DEFAULT_TOP_COMPANIES
    top_n: int = DEFAULT_WORDCLOUD_TOP_N
    report_types: tuple[str, ...] = REPORT_TYPES
    min_latest_chunk_count: int = 2
    tokenizer_batch_size: int = 128
    extra_stopwords: frozenset[str] = field(default_factory=frozenset)
    vocabulary: SectorVocabulary | None = None

    def __post_init__(self) -> None:
        if len(self.years) != 3 or tuple(sorted(self.years)) != self.years:
            raise ValueError("years must contain three ascending years, e.g. (2023, 2024, 2025)")
        if self.top_companies < 1 or self.top_n < 1 or self.tokenizer_batch_size < 1:
            raise ValueError("top_companies, top_n, and tokenizer_batch_size must be positive")
        if self.vocabulary is None:
            object.__setattr__(self, "vocabulary", SECTOR_VOCABULARIES.get(self.index_code, GENERIC_VOCABULARY))


def list_sector_indices() -> pd.DataFrame:
    """Return the active KRX indices available in the connected database."""
    return query(
        "SELECT index_code, index_name, display_name, source_as_of "
        "FROM krx_indices WHERE is_active = 1 ORDER BY index_code"
    )


def get_top_companies(index_code: str, limit: int = DEFAULT_TOP_COMPANIES) -> pd.DataFrame:
    """Get current index constituents, ranked by supplied KRX weight.

    Some indices have no stored weights.  In that case ``corp_code`` makes the
    selection deterministic; callers should then review the selected names.
    """
    return query(
        "SELECT c.corp_code, c.corp_name, c.stock_code, k.weight, k.effective_from "
        "FROM krx_index_constituents k JOIN companies c USING (corp_code) "
        "WHERE k.index_code = %s AND k.is_current = 1 AND c.is_operational = 1 "
        "ORDER BY (k.weight IS NULL), k.weight DESC, c.corp_code LIMIT %s",
        [index_code, int(limit)],
    )


def _analysis_where(config: SignalConfig, companies: pd.DataFrame) -> tuple[str, list[object]]:
    # TODO: validate other sectors' DB sections before making this policy injectable.
    codes = list(companies["corp_code"])
    code_marks = ", ".join(["%s"] * len(codes))
    year_marks = ", ".join(["%s"] * len(config.years))
    type_marks = ", ".join(["%s"] * len(config.report_types))
    section_marks = " OR ".join(["section_name LIKE %s"] * len(ALLOWED_SECTION_PREFIXES))
    subsection_marks = " OR ".join(["subsection_name LIKE %s"] * len(ALLOWED_SUBSECTION_PHRASES))
    where = (
        f"corp_code IN ({code_marks}) AND year IN ({year_marks}) "
        f"AND report_type IN ({type_marks}) AND is_active = 1 AND is_searchable = 1 "
        f"AND (({section_marks}) OR ({subsection_marks}))"
    )
    params: list[object] = [
        *codes, *config.years, *config.report_types,
        *[f"{prefix}%" for prefix in ALLOWED_SECTION_PREFIXES],
        *[f"%{phrase}%" for phrase in ALLOWED_SUBSECTION_PHRASES],
    ]
    return where, params


def calculate_entropy_score(
    keyword_company_counts: dict[str, int],
    company_chunk_totals: dict[str, int],
) -> float:
    """Return 0--100 normalized entropy of corpus-adjusted company mentions."""
    company_count = len(company_chunk_totals)
    if company_count <= 1:
        return 0.0
    mention_rates = [
        keyword_company_counts.get(code, 0) / total if total > 0 else 0.0
        for code, total in company_chunk_totals.items()
    ]
    rate_sum = sum(mention_rates)
    if rate_sum <= 0:
        return 0.0
    shares = [rate / rate_sum for rate in mention_rates]
    entropy = -sum(share * math.log(share) for share in shares if share > 0)
    normalized = entropy / math.log(company_count)
    return min(100.0, max(0.0, normalized * 100.0))


def apply_industry_hot_flags(result: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Mark at most three strongest rising keywords inside final Top-N."""
    result = result.copy()
    result["is_hot"] = False
    if result.empty or top_n < 1:
        return result
    eligible = result.loc[
        (result["final_rank"] <= top_n)
        & (result["change_score"] >= HOT_SCORE_THRESHOLD)
        & (result["change_raw"] > 0)
    ].sort_values(
        ["change_raw", "change_score", "final_signal_score", "final_rank", "keyword"],
        ascending=[False, False, False, True, True],
        kind="mergesort",
    )
    hot_indices = eligible.head(MAX_INDUSTRY_HOT_KEYWORDS).index
    result.loc[hot_indices, "is_hot"] = True
    return result


def _result_from_counts(
    counts: dict[str, dict[int, int]],
    latest_company_counts: dict[str, dict[str, int]],
    latest_company_chunk_totals: dict[str, int],
    totals: pd.Series,
    config: SignalConfig,
    company_total: int,
) -> pd.DataFrame:
    """Filter chunk-level candidates and calculate the production scores."""
    rows = [{"keyword": word, **{f"count_{year}": year_counts.get(year, 0) for year in config.years}}
            for word, year_counts in counts.items()]
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    for year in config.years:
        result[f"total_chunks_{year}"] = int(totals[year])
        result[f"rate_{year}"] = result[f"count_{year}"] / totals[year]
    first, middle, latest = config.years
    result = result[result[f"count_{latest}"] >= config.min_latest_chunk_count].copy()
    result["current_raw"] = result[f"rate_{latest}"]
    result["change_raw"] = (
        EARLIER_CHANGE_WEIGHT * (result[f"rate_{middle}"] - result[f"rate_{first}"])
        + RECENT_CHANGE_WEIGHT * (result[f"rate_{latest}"] - result[f"rate_{middle}"])
    )
    result["company_count"] = result["keyword"].map(lambda word: len(latest_company_counts.get(word, {})))
    result = result[result["company_count"] >= MIN_LATEST_COMPANIES].copy()
    excluded_noise = result["keyword"].map(
        lambda keyword: bool(PRODUCTION_GENERIC_NOISE_CATEGORIES.intersection(generic_noise_categories(keyword)))
    )
    result = result.loc[~excluded_noise].copy()
    result["company_coverage_score"] = result["company_count"] / company_total * 100.0
    # Keep the former score for operational comparisons. Production scoring
    # uses the coverage/entropy combination below.
    result["old_spread_score"] = result["company_coverage_score"]
    result["entropy_score"] = result["keyword"].map(
        lambda word: calculate_entropy_score(
            latest_company_counts.get(word, {}), latest_company_chunk_totals
        )
    )
    result["spread_score"] = (
        COVERAGE_SPREAD_WEIGHT * result["company_coverage_score"]
        + ENTROPY_SPREAD_WEIGHT * result["entropy_score"]
    )
    result["current_score"] = _percentile_score(result["current_raw"])
    result["change_score"] = _percentile_score(result["change_raw"])
    result["signal_score"] = (
        CURRENT_WEIGHT * result["current_score"]
        + CHANGE_WEIGHT * result["change_score"]
        + SPREAD_WEIGHT * result["spread_score"]
    )
    # A concrete phrase takes precedence over a context-free component when
    # the sector vocabulary marks that component as requiring context.
    phrases = result.loc[result["keyword"].str.contains(" ", regex=False), "keyword"]
    qualified = {part for phrase in phrases for part in phrase.split()
                 if part in config.vocabulary.context_required_components}
    if qualified:
        result = result[~result["keyword"].isin(qualified)].copy()
    latest_company_totals = result["keyword"].map(
        lambda word: sum(latest_company_counts.get(word, {}).values())
    )
    if not latest_company_totals.eq(result[f"count_{latest}"]).all():
        raise ValueError("Latest-year company chunk counts do not match keyword chunk totals")
    result["max_company_share"] = result["keyword"].map(
        lambda word: max(latest_company_counts.get(word, {}).values(), default=0)
    ) / result[f"count_{latest}"]
    result["concentration_penalty"] = result["max_company_share"].map(calculate_concentration_penalty)
    result["generic_business"] = result["keyword"].map(is_generic_business)
    result["generic_business_penalty"] = result["generic_business"].astype(int) * GENERIC_BUSINESS_PENALTY
    result["final_signal_score"] = (
        result["signal_score"] - result["concentration_penalty"] - result["generic_business_penalty"]
    )
    result = result.sort_values(["final_signal_score", "keyword"], ascending=[False, True]).reset_index(drop=True)
    result["final_rank"] = result.index + 1
    return apply_industry_hot_flags(result, config.top_n)


def score_database_keywords(config: SignalConfig, companies: pd.DataFrame,
                            page_size: int = DEFAULT_PAGE_SIZE) -> pd.DataFrame:
    """Extract and score the configured DB corpus in bounded text pages."""
    where, params = _analysis_where(config, companies)
    totals_frame = query(
        f"SELECT year, COUNT(*) AS total_chunks FROM chunk_metadata WHERE {where} GROUP BY year", params
    )
    totals = totals_frame.set_index("year")["total_chunks"].reindex(config.years, fill_value=0)
    if (totals == 0).any():
        raise ValueError(f"No searchable chunks available for year(s): {list(totals[totals == 0].index)}")

    extractor = KeywordExtractor(companies["corp_name"], config.extra_stopwords, config.vocabulary)
    latest_year = config.years[-1]
    latest_company_frame = query(
        "SELECT corp_code, COUNT(*) AS total_chunks FROM chunk_metadata "
        f"WHERE {where} AND year = %s GROUP BY corp_code",
        [*params, latest_year],
    )
    latest_company_chunk_totals = {str(code): 0 for code in companies["corp_code"]}
    latest_company_chunk_totals.update({
        str(row.corp_code): int(row.total_chunks)
        for row in latest_company_frame.itertuples(index=False)
    })
    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    latest_company_counts: dict[str, Counter[str]] = defaultdict(Counter)
    last_vector_id = -1
    while True:
        page = query(
            "SELECT vector_id, corp_code, year, chunk_text FROM chunk_metadata "
            f"WHERE {where} AND vector_id > %s ORDER BY vector_id LIMIT %s",
            [*params, last_vector_id, int(page_size)],
        )
        if page.empty:
            break
        for row, keywords in zip(
            page.itertuples(index=False), extractor.extract_many(page["chunk_text"].fillna(""))
        ):
            for keyword in keywords:
                counts[keyword][int(row.year)] += 1
                if row.year == latest_year:
                    latest_company_counts[keyword][str(row.corp_code)] += 1
        last_vector_id = int(page["vector_id"].iloc[-1])
    return _result_from_counts(
        counts, latest_company_counts, latest_company_chunk_totals,
        totals, config, len(companies),
    )


def _canonical(value: str, vocabulary: SectorVocabulary = GENERIC_VOCABULARY) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value).strip()
    return vocabulary.aliases.get(value.casefold(), value)


def _is_candidate(value: str, stopwords: set[str], company_names: set[str],
                  vocabulary: SectorVocabulary = GENERIC_VOCABULARY) -> bool:
    canonical = _canonical(value, vocabulary)
    if not canonical or canonical in stopwords or canonical in company_names:
        return False
    if re.fullmatch(r"[\d.,%/()\-]+", canonical):
        return False
    if re.fullmatch(r"(?:°\s*)?[CFK]|℃|℉", canonical, flags=re.IGNORECASE):
        return False
    # One-character Korean fragments and unit-like tokens are not useful, while
    # short Latin acronyms are retained.
    if len(canonical) < 2 and not re.fullmatch(r"[A-Za-z]{2,}", canonical):
        return False
    return True


def _is_sector_protected(value: str, vocabulary: SectorVocabulary) -> bool:
    """Whether a candidate is explicitly supported by the injected sector config."""
    canonical = _canonical(value, vocabulary)
    protected = (
        set(vocabulary.industry_anchors)
        | set(vocabulary.single_nouns)
        | {_canonical(term, vocabulary) for term in vocabulary.compound_patterns.values()}
        | {_canonical(term, vocabulary) for _, term in vocabulary.technology_patterns}
    )
    return canonical in protected


def _looks_like_structural_field(
    text: str, start: int, end: int, phrase: str, vocabulary: SectorVocabulary,
) -> bool:
    """Identify a short table/header field without rejecting protected concepts."""
    if _is_sector_protected(phrase, vocabulary):
        return False
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    line = re.sub(r"\s+", " ", text[line_start:line_end]).strip()
    surface = re.sub(r"\s+", " ", text[start:end]).strip()
    compact_line = re.sub(r"[^0-9A-Za-z가-힣]", "", line).casefold()
    compact_surface = re.sub(r"[^0-9A-Za-z가-힣]", "", surface).casefold()
    if compact_line == compact_surface and len(line) <= 40:
        previous_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
        previous = text[previous_start:max(0, line_start - 1)].strip()
        next_end = text.find("\n", line_end + 1)
        if next_end < 0:
            next_end = len(text)
        following = text[line_end + 1:next_end].strip()
        short_neighbours = sum(bool(value) and len(value) <= 60 for value in (previous, following))
        if short_neighbours == 2:
            return True
    tail = text[end:line_end]
    if len(line) <= 80 and re.match(
        r"^\s*[:：]\s*(?:[-–—]|\d|\(?단위|백만|천|원|USD|KRW)", tail, flags=re.IGNORECASE
    ):
        return True
    return False


def _is_informative_phrase(phrase: str,
                           vocabulary: SectorVocabulary = GENERIC_VOCABULARY) -> bool:
    """Reject specification/table pairs and generic business boilerplate."""
    normalized = _canonical(phrase, vocabulary)
    if normalized in vocabulary.excluded_phrases:
        return False
    terms = normalized.split()
    lowered = {term.casefold() for term in terms}
    if lowered & (MEASUREMENT_OR_TABLE_TOKENS | vocabulary.excluded_tokens):
        return False
    if (lowered & vocabulary.excluded_theme_terms) and not (set(terms) & vocabulary.industry_anchors):
        return False
    if len(terms) == 2:
        left, right = terms
        if ((left in DOCUMENT_FIELD_MODIFIERS and right in DOCUMENT_FIELD_HEADS)
                or (left in ACCOUNTING_LABEL_MODIFIERS and right in ACCOUNTING_LABEL_HEADS)
                or (left in ABSTRACT_MODIFIERS and right in ABSTRACT_HEADS)
                or (left in vocabulary.broad_sector_terms and right == "산업")):
            return False
    # Generic action/status words at either end describe document boilerplate,
    # not a technology/product/capacity concept.  This catches classes such as
    # "개발 완료", "규모 투자", and "경쟁력 확보" without banning "설비 투자"
    # or "생산 능력".
    return terms[0] not in LOW_INFORMATION_PHRASE_TERMS and terms[-1] not in LOW_INFORMATION_PHRASE_TERMS


class KeywordExtractor:
    """Extract sector-configured concepts and neighbouring Kiwi noun phrases."""

    def __init__(self, company_names: Iterable[str], extra_stopwords: Iterable[str] = (),
                 vocabulary: SectorVocabulary = GENERIC_VOCABULARY) -> None:
        try:
            from kiwipiepy import Kiwi
        except ImportError as exc:  # pragma: no cover - clear setup error
            raise ImportError(
                "kiwipiepy is required. Run: python -m pip install -r requirements.txt"
            ) from exc
        # One worker keeps memory bounded when processing a large three-year
        # sector corpus.  This is an offline job, so predictability wins.
        self.kiwi = Kiwi(num_workers=1)
        self.vocabulary = vocabulary
        self.company_names = {_canonical(name, vocabulary) for name in company_names}
        self.stopwords = {_canonical(word, vocabulary) for word in
                          STOPWORDS | vocabulary.stopwords | set(extra_stopwords)}

    def extract_many(self, texts: Iterable[str]) -> list[set[str]]:
        """Extract one deduplicated keyword set per chunk in a Kiwi batch."""
        found_per_chunk: list[set[str]] = []
        source_texts: list[str] = []
        masked_texts: list[str] = []
        for text in texts:
            found: set[str] = set()
            source = unicodedata.normalize("NFKC", text)
            masked = source
            for pattern, keyword in self.vocabulary.compound_patterns.items():
                if re.search(pattern, masked, flags=re.IGNORECASE):
                    found.add(_canonical(keyword, self.vocabulary))
                masked = re.sub(
                    pattern, lambda match: " " * len(match.group(0)), masked, flags=re.IGNORECASE
                )
            # Preserve configured technology tokens before Kiwi can split mixed
            # letter/digit strings; normalization remains sector-configured.
            for pattern, keyword in self.vocabulary.technology_patterns:
                if re.search(pattern, masked, flags=re.IGNORECASE):
                    found.add(_canonical(keyword, self.vocabulary))
            found_per_chunk.append(found)
            source_texts.append(source)
            masked_texts.append(masked)

        for found, source, masked, tokens in zip(
            found_per_chunk, source_texts, masked_texts, self.kiwi.tokenize(masked_texts)
        ):
            nouns: list[tuple[str, int, int]] = []
            for token in tokens:
                if token.tag in NOUN_TAGS:
                    word = _canonical(token.form, self.vocabulary)
                    if _is_candidate(word, self.stopwords, self.company_names, self.vocabulary):
                        nouns.append((word, token.start, token.len))
                        if (token.tag == "SL" and word.isupper()
                                and (len(word) >= 4 or _is_sector_protected(word, self.vocabulary))):
                            found.add(word)
                        elif word in self.vocabulary.single_nouns:
                            found.add(word)
            # Join only neighbouring noun tokens.  This avoids accidental
            # pairs formed from nouns that happened to be far apart in a chunk.
            for (left, start, length), (right, next_start, right_length) in zip(nouns, nouns[1:]):
                phrase = _canonical(f"{left} {right}", self.vocabulary)
                # A newline, punctuation, or table-cell separator is not a
                # noun-phrase boundary, even when the two tokens are adjacent.
                gap = masked[start + length:next_start]
                if (left != right and re.search(r"[가-힣]", phrase)
                        and gap in ("", " ") and _is_candidate(
                    phrase, self.stopwords, self.company_names, self.vocabulary
                ) and _is_informative_phrase(phrase, self.vocabulary)
                        and not _looks_like_structural_field(
                            source, start, next_start + right_length, phrase, self.vocabulary
                        )):
                    found.add(phrase)
        return [
            {
                _canonical(word, self.vocabulary) for word in found
                if _is_candidate(word, self.stopwords, self.company_names, self.vocabulary)
            }
            for found in found_per_chunk
        ]


def _percentile_score(values: pd.Series) -> pd.Series:
    """Ascending percentile rank, represented on the requested 0--100 scale."""
    return values.rank(method="average", pct=True).mul(100.0)


def score_keywords(chunks: pd.DataFrame, config: SignalConfig, companies: pd.DataFrame) -> pd.DataFrame:
    """Score an in-memory chunk corpus with the same production rules."""
    required = {"chunk_id", "corp_code", "year", "chunk_text"}
    missing = required - set(chunks.columns)
    if missing:
        raise ValueError(f"chunks is missing columns: {sorted(missing)}")

    totals = chunks.groupby("year")["chunk_id"].nunique().reindex(config.years, fill_value=0)
    if (totals == 0).any():
        absent = list(totals[totals == 0].index)
        raise ValueError(f"No searchable chunks available for year(s): {absent}")

    extractor = KeywordExtractor(companies["corp_name"], config.extra_stopwords, config.vocabulary)
    appearances: list[tuple[int, str, str, str]] = []
    selected = chunks[["chunk_id", "corp_code", "year", "chunk_text"]]
    # Keep the Kiwi input bounded.  Sending every disclosure text to Kiwi in
    # one call can require more than a gigabyte of RAM for a three-year sector.
    for start in range(0, len(selected), config.tokenizer_batch_size):
        batch = selected.iloc[start:start + config.tokenizer_batch_size]
        extracted = extractor.extract_many(batch["chunk_text"].fillna(""))
        for row, keywords in zip(batch.itertuples(index=False), extracted):
            for keyword in keywords:
                appearances.append((row.year, row.corp_code, row.chunk_id, keyword))
    if not appearances:
        return pd.DataFrame()

    hit = pd.DataFrame(appearances, columns=["year", "corp_code", "chunk_id", "keyword"])
    hit = hit.drop_duplicates(["year", "corp_code", "chunk_id", "keyword"])
    grouped = hit.groupby(["keyword", "year"])["chunk_id"].nunique()
    counts = {word: {int(year): int(count) for year, count in grouped.loc[word].items()}
              for word in grouped.index.get_level_values("keyword").unique()}
    latest = config.years[-1]
    latest_company_counts: dict[str, dict[str, int]] = defaultdict(dict)
    for (word, code), count in hit[hit["year"] == latest].groupby(
        ["keyword", "corp_code"]
    )["chunk_id"].nunique().items():
        latest_company_counts[word][str(code)] = int(count)
    latest_company_chunk_totals = {
        str(code): int(count)
        for code, count in chunks.loc[chunks["year"] == latest]
        .groupby("corp_code")["chunk_id"].nunique().items()
    }
    for code in companies["corp_code"]:
        latest_company_chunk_totals.setdefault(str(code), 0)
    return _result_from_counts(
        counts, latest_company_counts, latest_company_chunk_totals,
        totals, config, len(companies),
    )


def build_sector_signal(config: SignalConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return ``(top_keywords, all_keywords, selected_companies)``.

    ``top_keywords`` contains final-score Top-N with visual-only display weights;
    a hot keyword outside Top-N is not returned.
    """
    companies = get_top_companies(config.index_code, config.top_companies)
    all_keywords = score_database_keywords(config, companies)
    top_keywords = add_display_weights(all_keywords.head(config.top_n))
    return top_keywords, all_keywords, companies


def add_display_weights(top_keywords: pd.DataFrame) -> pd.DataFrame:
    """Add visual-only weights after the final-score Top-N has been selected."""
    top_keywords = top_keywords.copy()
    if top_keywords.empty:
        top_keywords["display_weight"] = pd.Series(dtype=float)
        return top_keywords

    scores = top_keywords["final_signal_score"]
    rank_norm = pd.Series(
        [(len(top_keywords) - rank) / (len(top_keywords) - 1) for rank in range(1, len(top_keywords) + 1)],
        index=top_keywords.index,
    ) if len(top_keywords) > 1 else pd.Series([1.0], index=top_keywords.index)
    score_range = scores.max() - scores.min()
    if score_range == 0:
        top_keywords["display_weight"] = 30 + 70 * rank_norm
    else:
        score_component = ((scores - scores.min()) / score_range) ** 2
        top_keywords["display_weight"] = 30 + 70 * (0.7 * score_component + 0.3 * rank_norm)
    return top_keywords


def company_concentration_diagnostics(
    config: SignalConfig, selected_keywords: pd.DataFrame, companies: pd.DataFrame,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> pd.DataFrame:
    """Count latest-year distinct chunks by company for selected keywords.

    This optional read-only pass uses the same corpus and extraction rules.
    """
    if page_size < 1:
        raise ValueError("page_size must be positive")
    company_columns = {
        row.corp_code: f"{row.corp_name} ({row.corp_code})_chunk_count"
        for row in companies.itertuples(index=False)
    }
    columns = ["keyword", f"count_{config.years[-1]}", "company_count",
               *company_columns.values(), "max_company_share", "signal_score"]
    if selected_keywords.empty:
        return pd.DataFrame(columns=columns)

    tracked = set(selected_keywords["keyword"])
    hits: dict[str, dict[str, set[object]]] = defaultdict(lambda: defaultdict(set))
    extractor = KeywordExtractor(companies["corp_name"], config.extra_stopwords, config.vocabulary)
    where, params = _analysis_where(config, companies)
    latest_year = config.years[-1]
    last_vector_id = -1
    while True:
        page = query(
            "SELECT vector_id, chunk_id, corp_code, chunk_text FROM chunk_metadata "
            f"WHERE {where} AND year = %s AND vector_id > %s ORDER BY vector_id LIMIT %s",
            [*params, latest_year, last_vector_id, int(page_size)],
        )
        if page.empty:
            break
        for row, extracted in zip(page.itertuples(index=False), extractor.extract_many(page["chunk_text"].fillna(""))):
            for keyword in tracked.intersection(extracted):
                hits[keyword][row.corp_code].add(row.chunk_id)
        last_vector_id = int(page["vector_id"].iloc[-1])

    rows = []
    for row in selected_keywords.itertuples(index=False):
        company_counts = {code: len(hits[row.keyword].get(code, set())) for code in company_columns}
        total = sum(company_counts.values())
        expected = int(getattr(row, f"count_{latest_year}"))
        if total != expected or sum(count > 0 for count in company_counts.values()) != int(row.company_count):
            raise ValueError(f"Company-level chunk counts do not match scored totals for {row.keyword!r}")
        rows.append({
            "keyword": row.keyword,
            f"count_{latest_year}": expected,
            "company_count": int(row.company_count),
            **{column: company_counts[code] for code, column in company_columns.items()},
            "max_company_share": max(company_counts.values()) / expected,
            "signal_score": float(row.signal_score),
        })
    return pd.DataFrame(rows, columns=columns)


def calculate_concentration_penalty(max_company_share: float) -> float:
    """Apply the capped continuous concentration deduction."""
    return min(
        MAX_CONCENTRATION_PENALTY,
        max(0.0, (max_company_share - CONCENTRATION_FREE_SHARE) * CONCENTRATION_SLOPE),
    )


def generic_noise_categories(keyword: str) -> tuple[str, ...]:
    """Return matching sector-agnostic categories for a candidate keyword."""
    return tuple(
        category for category, patterns in GENERIC_NOISE_PATTERNS.items()
        if any(re.search(pattern, keyword, flags=re.IGNORECASE) for pattern in patterns)
    )


def is_generic_business(keyword: str) -> bool:
    """Whether the shared sector-agnostic diagnostic tags a general-business phrase."""
    return "일반 경영" in generic_noise_categories(keyword)


def wordcloud_items(top_keywords: pd.DataFrame) -> list[dict[str, object]]:
    """Return selected keywords with their visual-only display weights."""
    if "display_weight" not in top_keywords:
        top_keywords = add_display_weights(top_keywords)
    return [
        {
            "keyword": row.keyword,
            "label": row.keyword,
            "size": round(float(row.final_signal_score), 2),
            "display_weight": float(row.display_weight),
            "signal_score": float(row.signal_score),
            "max_company_share": float(row.max_company_share),
            "concentration_penalty": float(row.concentration_penalty),
            "generic_business": bool(row.generic_business),
            "generic_business_penalty": int(row.generic_business_penalty),
            "final_signal_score": float(row.final_signal_score),
            "final_rank": int(row.final_rank),
            "is_hot": bool(row.is_hot),
        }
        for row in top_keywords.itertuples(index=False)
    ]


def main() -> None:
    """Run the production word cloud and optionally inspect one keyword."""
    parser = argparse.ArgumentParser(description="Score KRX disclosure keyword signals")
    parser.add_argument("index_code", help="KRX index code, e.g. KRX_SEMI")
    parser.add_argument("--years", nargs=3, type=int, default=DEFAULT_ANALYSIS_YEARS)
    parser.add_argument("--top-n", type=int, default=DEFAULT_WORDCLOUD_TOP_N)
    parser.add_argument("--top-companies", type=int, default=DEFAULT_TOP_COMPANIES)
    parser.add_argument("--keyword", help="inspect an exact normalized keyword and its company chunk counts")
    args = parser.parse_args()

    config = SignalConfig(args.index_code, tuple(args.years), args.top_companies, args.top_n)
    top, all_keywords, companies = build_sector_signal(config)
    print("Selected companies:")
    print(companies.to_string(index=False))
    print(f"\nFinal candidates: {len(all_keywords):,}")
    print(f"\nTop {config.top_n} disclosure keywords:")
    columns = [
        "final_rank", "keyword", f"count_{config.years[-1]}", "company_count", "current_score",
        "change_score", "old_spread_score", "company_coverage_score", "entropy_score",
        "spread_score", "signal_score", "max_company_share",
        "concentration_penalty", "generic_business", "generic_business_penalty",
        "final_signal_score", "display_weight", "is_hot",
    ]
    print(top[columns].to_string(index=False))

    if args.keyword:
        selected = all_keywords.loc[all_keywords["keyword"] == args.keyword]
        if selected.empty:
            parser.error(f"Keyword not found among scored candidates: {args.keyword!r}")
        print(f"\nScore details for {args.keyword}:")
        print(selected.T.to_string(header=False))
        print("\nLatest-year company chunk counts:")
        print(company_concentration_diagnostics(config, selected, companies).to_string(index=False))


if __name__ == "__main__":
    main()
