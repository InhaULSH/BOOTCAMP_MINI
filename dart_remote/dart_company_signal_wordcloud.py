"""Score company disclosure keywords for the detail-page word cloud.

Load eligible chunks, extract and canonicalize sector-configured candidates,
filter them, then score Current/Change/Context Diversity at 50/30/20 minus
the generic-business penalty. Rank by final score; add display weights only
after Top-N selection.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import pandas as pd

from .dart_signal_wordcloud import query, interval_weights
from .dart_signal_wordcloud import (
    CHANGE_WEIGHT,
    CURRENT_WEIGHT,
    DEFAULT_ANALYSIS_YEARS,
    DEFAULT_PAGE_SIZE,
    DEFAULT_WORDCLOUD_TOP_N,
    EARLIER_CHANGE_WEIGHT,
    GENERIC_BUSINESS_PENALTY,
    RECENT_CHANGE_WEIGHT,
    REPORT_TYPES,
    SPREAD_WEIGHT,
    _canonical,
    _is_candidate,
    _looks_like_structural_field,
    _percentile_score,
    add_display_weights,
    generic_noise_categories,
    is_generic_business,
)
from .signal_keyword_rules import (
    ALLOWED_SECTION_PREFIXES,
    ALLOWED_SUBSECTION_PHRASES,
    GENERIC_VOCABULARY,
    PRODUCTION_GENERIC_NOISE_CATEGORIES,
    SECTOR_VOCABULARIES,
    STOPWORDS,
    SectorVocabulary,
)


COMPANY_HOT_SCORE_THRESHOLD = 97.5


@dataclass(frozen=True)
class CompanySignalConfig:
    """Eligible company corpus and explicitly injected sector vocabulary."""

    corp_code: str
    sector_index_code: str | None = None
    years: tuple[int, ...] = DEFAULT_ANALYSIS_YEARS
    top_n: int = DEFAULT_WORDCLOUD_TOP_N
    report_types: tuple[str, ...] = REPORT_TYPES
    min_latest_chunk_count: int = 2
    extra_stopwords: frozenset[str] = field(default_factory=frozenset)
    vocabulary: SectorVocabulary | None = None

    def __post_init__(self) -> None:
        if not self.years or tuple(sorted(set(self.years))) != self.years:
            raise ValueError("years must contain distinct ascending years")
        if self.top_n < 1 or self.min_latest_chunk_count < 1:
            raise ValueError("top_n and min_latest_chunk_count must be positive")
        if not self.report_types:
            raise ValueError("report_types must not be empty")
        if self.vocabulary is None:
            if self.sector_index_code and self.sector_index_code not in SECTOR_VOCABULARIES:
                raise ValueError(f"No registered SectorVocabulary for {self.sector_index_code!r}")
            object.__setattr__(
                self,
                "vocabulary",
                SECTOR_VOCABULARIES.get(self.sector_index_code, GENERIC_VOCABULARY),
            )


def get_company(corp_code: str) -> pd.Series:
    """Look up the company name used to suppress self-mentions."""
    company = query(
        "SELECT corp_code, corp_name FROM companies WHERE corp_code = %s LIMIT 1",
        [corp_code],
    )
    if company.empty:
        raise ValueError(f"Company not found: {corp_code}")
    return company.iloc[0]


def _analysis_where(config: CompanySignalConfig) -> tuple[str, list[object]]:
    """Select the same report/section corpus as before consolidation."""
    year_marks = ", ".join(["%s"] * len(config.years))
    type_marks = ", ".join(["%s"] * len(config.report_types))
    section_marks = " OR ".join(["section_name LIKE %s"] * len(ALLOWED_SECTION_PREFIXES))
    subsection_marks = " OR ".join(["subsection_name LIKE %s"] * len(ALLOWED_SUBSECTION_PHRASES))
    where = (
        f"corp_code = %s AND year IN ({year_marks}) "
        f"AND report_type IN ({type_marks}) AND is_active = 1 AND is_searchable = 1 AND data_version IN (SELECT data_version FROM data_versions WHERE is_current=1 AND validated=1) "
        f"AND (({section_marks}) OR ({subsection_marks}))"
    )
    params: list[object] = [
        config.corp_code,
        *config.years,
        *config.report_types,
        *[f"{prefix}%" for prefix in ALLOWED_SECTION_PREFIXES],
        *[f"%{phrase}%" for phrase in ALLOWED_SUBSECTION_PHRASES],
    ]
    return where, params


def _result_from_counts(
    counts: dict[str, dict[int, int]],
    totals: pd.Series,
    config: CompanySignalConfig,
) -> pd.DataFrame:
    """Apply latest-year/generic filters and compute Current, Change, and hot."""
    available_years = {
        year: bool(year in totals.index and pd.notna(totals[year]) and totals[year] > 0)
        for year in config.years
    }
    rows = [
        {
            "keyword": word,
            **{
                f"count_{year}": year_counts.get(year, 0) if available_years[year] else pd.NA
                for year in config.years
            },
        }
        for word, year_counts in counts.items()
    ]
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    for year in config.years:
        result[f"total_chunks_{year}"] = int(totals[year])
        result[f"rate_{year}"] = (
            result[f"count_{year}"] / totals[year]
            if available_years[year] else float("nan")
        )
    latest = config.years[-1]
    if not available_years[latest]:
        raise ValueError(f"No searchable chunks available for latest year: {latest}")
    result = result[result[f"count_{latest}"] >= config.min_latest_chunk_count].copy()
    result["current_raw"] = result[f"rate_{latest}"]
    weighted_intervals = interval_weights(config.years)
    valid_intervals = [
        (start, end, weight)
        for start, end, weight in weighted_intervals
        if end == start + 1 and available_years[start] and available_years[end]
    ]
    valid_weight = sum(weight for _, _, weight in valid_intervals)
    result["change_raw"] = sum(
        (weight / valid_weight) * (result[f"rate_{end}"] - result[f"rate_{start}"])
        for start, end, weight in valid_intervals
    ) if valid_intervals else 0.0
    excluded_noise = result["keyword"].map(
        lambda keyword: bool(PRODUCTION_GENERIC_NOISE_CATEGORIES.intersection(generic_noise_categories(keyword)))
    )
    result = result.loc[~excluded_noise].copy()
    result["current_score"] = _percentile_score(result["current_raw"])
    result["change_score"] = _percentile_score(result["change_raw"])
    result["is_hot"] = (result["change_score"] >= COMPANY_HOT_SCORE_THRESHOLD) & (result["change_raw"] > 0)
    # Keep post-percentile component filtering in the same position.
    phrases = result.loc[result["keyword"].str.contains(" ", regex=False), "keyword"]
    qualified = {
        part for phrase in phrases for part in phrase.split()
        if part in config.vocabulary.context_required_components
    }
    if qualified:
        result = result[~result["keyword"].isin(qualified)].copy()
    result["generic_business"] = result["keyword"].map(is_generic_business)
    result["generic_business_penalty"] = result["generic_business"].astype(int) * GENERIC_BUSINESS_PENALTY
    return result


# Company scoring uses the shared 20% weight for context diversity, not report spread.
CONTEXT_NOVELTY_WEIGHT = 0.4
COOCCURRENCE_NOVELTY_WEIGHT = 0.6
DIVERSITY_FULL_SUPPORT_CHUNKS = 10
DIVERSITY_WEIGHT = SPREAD_WEIGHT


# These are semantic roles shared by industries, not complete keyword lists.
COMMON_OBJECT_HEADS = frozenset({
    "센터", "검사", "정밀도", "증착", "부품", "소자", "장비", "소재",
    "수율", "공정", "고객", "수요", "투자", "능력", "용량",
    "솔루션", "센서", "모니터",
})
COMMON_CONCRETE_SUBJECTS = frozenset({
    "수율", "생산", "공정", "설비", "고객", "고객사", "검사", "수요",
    "장비", "품질", "용량",
})
CHANGE_HEADS = frozenset({"향상", "확대", "전환", "다변화", "증설", "증가", "감소"})
ACTION_HEADS = frozenset({"투자", "전환", "확대", "다변화", "증설"})
RELATIONAL_HEADS = frozenset({"기반"})
VAGUE_MODIFIERS = frozenset({
    "규모", "최대", "주력", "필수", "기본", "일반", "최고", "업계",
    "전략", "경쟁력", "경험", "사용", "사용자", "서비스",
})
GENERIC_STANDALONE = frozenset({
    "공정", "장비", "소재", "기술", "제품", "사업", "투자", "수요",
    "생산", "시장", "고객",
})
STRUCTURAL_MODIFIERS = frozenset({"데이터", "신규"})

# Cross-sector semantic roles, not a blacklist of complete keywords.
GENERIC_PHRASE_MODIFIERS = frozenset({
    "제조", "공정", "생산", "운영", "관리", "용량", "규모", "전후",
    "설비", "투자", "수요",
})

# Semantic modifier roles used to reject low-information noun pairs.  These
# are token roles rather than complete-keyword blacklists, so the same rule is
# applied across every company and sector.
TABLE_OR_ACCOUNTING_MODIFIERS = frozenset({
    "당기손익", "손익", "적립금", "자산", "기간", "상기", "하기", "해당",
    "최대", "평균", "누적",
})
GENERIC_CUSTOMER_MODIFIERS = frozenset({
    "인식", "산업", "보유", "가입", "이용", "외부", "카드", "통장", "기반",
})
ABSTRACT_ABILITY_MODIFIERS = frozenset({"대응", "흡수", "개발"})
GENERIC_PROCESS_MODIFIERS = frozenset({"부가", "증대"})
GENERIC_MATERIAL_MODIFIERS = frozenset({"생산"})
BOUNDARY_FUNCTION_MODIFIERS = frozenset({
    "상기", "하기", "해당", "최대", "평균", "누적", "기간",
})
BROAD_SCOPE_MODIFIERS = frozenset({
    "국내", "해외", "국내외", "글로벌", "미국", "아시아",
    "정부", "공동", "대표", "기업",
})
BROAD_SCOPE_HEADS = frozenset({"소재", "부품", "투자"})
GENERIC_CENTER_MODIFIERS = frozenset({"설계", "시험", "연구"})
GENERIC_SOLUTION_MODIFIERS = frozenset({"모델", "설계", "토탈"})
GENERIC_INVESTMENT_MODIFIERS = frozenset({"신규", "기존", "건설"})

# Corporate/legal designators are structural name evidence, not individual
# companies.  Their use prevents organization names from being promoted as
# technical phrases without maintaining a company blacklist.
ENTITY_DESIGNATORS = frozenset({
    "ag", "bank", "corp", "corporation", "co", "company", "holdings",
    "industries", "inc", "jv", "llc", "ltd", "operations", "plc", "sa", "se",
})
ACCOUNTING_STANDARD_PATTERN = re.compile(r"(?i)^(?:[A-Z]-?)?(?:IFRS|GAAP)$")
GENERIC_MARKETING_ENGLISH = frozenset({
    "best", "better", "future", "global", "human", "life", "market",
    "overview", "top", "value",
})
ENGLISH_FUNCTION_BOUNDARIES = frozenset({
    "and", "by", "for", "of", "or", "the", "with",
})
ENGLISH_INCOMPLETE_SUFFIXES = frozenset({"human"})
COMPANY_NAME_SUFFIXES = ("금융지주", "지주", "홀딩스")
OWN_COMPANY_CUES = re.compile(r"당사|동사|자사|우리\s*회사|회사는")
CUSTOMER_CUES = re.compile(r"고객사|고객|거래처|패널\s*업체|발주처")
MARKET_CUES = re.compile(r"시장|산업|정부|각국|업계|글로벌|전방")
NON_ACTION_CUES = re.compile(r"비용\s*절감|절감|대응")


@dataclass(frozen=True)
class V2SectorRoles:
    """Optional v2-only semantic roles; no production vocabulary is changed."""

    object_heads: frozenset[str] = frozenset()
    concrete_subjects: frozenset[str] = frozenset()
    broad_singletons: frozenset[str] = frozenset()


V2_SECTOR_ROLES = {
    "KRX_SEMI": V2SectorRoles(
        object_heads=frozenset({"메모리", "반도체", "패키징", "서버"}),
        concrete_subjects=frozenset({"메모리", "반도체", "패키징", "웨이퍼"}),
        broad_singletons=frozenset({"메모리"}),
    ),
}

_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_HANGUL = re.compile(r"[가-힣]")

# Approval thresholds for unprotected English technical terms.
MIN_TECH_CONTEXTS = 8
MIN_CONTEXT_RATIO = 0.35
MIN_STANDALONE_RATIO = 0.30
MAX_MODEL_FRAGMENT_RATIO = 0.30
MIN_NEIGHBOUR_BREADTH = 4
MIN_NEIGHBOUR_CONTEXT_RATIO = 0.60
MAX_NEIGHBOUR_GENERIC_ENGLISH_RATIO = 0.95
MIN_SINGLE_SECTION_CONTEXTS = 25
MIN_SINGLE_SECTION_CONTEXT_RATIO = 0.85
MIN_DOMINANT_SECTION_RATIO = 0.90
MAX_SINGLE_SECTION_MODEL_RATIO = 0.20
MAX_SINGLE_SECTION_GENERIC_ENGLISH_RATIO = 0.90

# Phrase specificity and action-ownership gates.
MIN_LONGER_OCCURRENCES = 8
MIN_ENGLISH_LONGER_RATIO = 0.80
MIN_ENGLISH_TOP_TWO_RATIO = 0.75
MIN_GENERIC_PHRASE_LONGER_RATIO = 0.60
MIN_OWN_ACTION_CONTEXTS = 2
MIN_OWN_ACTION_RATIO = 0.50

# Evidence thresholds for promotion to a longer expression.
MIN_PROMOTION_OCCURRENCES = 4
MIN_PROMOTION_CHUNKS = 2
MIN_PROMOTION_LATEST_CHUNKS = 2
MIN_ENGLISH_PROMOTION_SHARE = 0.25
MIN_KOREAN_PROMOTION_SHARE = 0.10
MIN_CANONICAL_EXTENSION_SHARE = 0.75
MAX_PROMOTION_TOKENS = 5


@dataclass
class CandidateObservation:
    """Candidate paths observed in one source chunk, before corpus gating."""

    direct: dict[str, set[tuple[str, str, str]]] = field(default_factory=lambda: defaultdict(set))
    english: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    generations: dict[str, set[tuple[str, bool]]] = field(default_factory=lambda: defaultdict(set))
    phrase_spans: dict[str, list[tuple[int, int, str, str, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )


class CompanyCandidateExtractorV2:
    """Extract category evidence; corpus-wide English approval follows later."""

    def __init__(
        self,
        company_names: Iterable[str],
        vocabulary: SectorVocabulary,
        extra_stopwords: Iterable[str] = (),
        sector_roles: V2SectorRoles = V2SectorRoles(),
    ) -> None:
        from kiwipiepy import Kiwi

        self.kiwi = Kiwi(num_workers=1)
        self.vocabulary = vocabulary
        self.sector_roles = sector_roles
        canonical_company_names = {_canonical(name, vocabulary) for name in company_names}
        self.company_names = set(canonical_company_names)
        for name in canonical_company_names:
            self.company_names.update(
                match.group().upper() for match in re.finditer(r"[A-Za-z]{2,}", name)
            )
            for suffix in COMPANY_NAME_SUFFIXES:
                if name.endswith(suffix) and len(name) > len(suffix):
                    self.company_names.add(name[:-len(suffix)])
        self.stopwords = {
            _canonical(word, vocabulary)
            for word in STOPWORDS | vocabulary.stopwords | set(extra_stopwords)
        }
        self.configured_terms = (
            set(vocabulary.single_nouns)
            | set(vocabulary.industry_anchors)
            | set(vocabulary.compound_patterns.values())
            | {target for _, target in vocabulary.technology_patterns}
            | set(vocabulary.aliases.values())
        )
        self.explicit_tech = (
            set(vocabulary.compound_patterns.values())
            | {target for _, target in vocabulary.technology_patterns}
            | set(vocabulary.aliases.values())
        )
        self.object_heads = COMMON_OBJECT_HEADS | sector_roles.object_heads
        self.concrete_subjects = COMMON_CONCRETE_SUBJECTS | sector_roles.concrete_subjects
        self.broad_singletons = GENERIC_STANDALONE | sector_roles.broad_singletons
        context_terms = (
            set(vocabulary.industry_anchors)
            | set(vocabulary.broad_sector_terms)
            | set(vocabulary.single_nouns)
            | set(vocabulary.compound_patterns.values())
            | {target for _, target in vocabulary.technology_patterns}
        )
        self.sector_context_patterns = tuple(
            re.compile(
                (r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])")
                if re.fullmatch(r"[A-Za-z0-9-]+", term) else re.escape(term),
                re.IGNORECASE,
            )
            for term in sorted(context_terms, key=len, reverse=True)
            if term
        )

    def has_sector_context(self, text: str) -> bool:
        """Return whether a chunk contains an injected sector concept."""
        return any(pattern.search(text) for pattern in self.sector_context_patterns)

    def _accept(self, keyword: str) -> bool:
        return _is_candidate(
            keyword, self.stopwords, self.company_names, self.vocabulary
        ) and keyword not in self.vocabulary.excluded_phrases \
            and not ACCOUNTING_STANDARD_PATTERN.fullmatch(keyword) \
            and keyword.casefold() not in GENERIC_MARKETING_ENGLISH

    def _phrase_category(self, left: str, right: str) -> tuple[str, str] | None:
        if left in VAGUE_MODIFIERS or left in self.company_names:
            return None
        if (
            (right == "고객" and left in GENERIC_CUSTOMER_MODIFIERS)
            or (right == "능력" and left in ABSTRACT_ABILITY_MODIFIERS)
            or (right == "공정" and left in GENERIC_PROCESS_MODIFIERS)
            or (right == "소재" and left in GENERIC_MATERIAL_MODIFIERS)
            or (right in {"공정", "투자", "능력", "용량", "수요"}
                and left in TABLE_OR_ACCOUNTING_MODIFIERS)
            or (right in BROAD_SCOPE_HEADS and left in BROAD_SCOPE_MODIFIERS)
            or (right == "투자" and left in GENERIC_INVESTMENT_MODIFIERS)
            or (right == "센터" and left in GENERIC_CENTER_MODIFIERS)
            or (right == "솔루션" and left in GENERIC_SOLUTION_MODIFIERS)
        ):
            return None
        specific = (
            left in self.concrete_subjects or left in self.configured_terms
            or left in STRUCTURAL_MODIFIERS
            or (_HANGUL.search(left) and left not in self.stopwords and len(left) >= 2)
        )
        if not specific:
            return None
        if right in RELATIONAL_HEADS and left in self.configured_terms:
            return "concrete_phrase", "configured concept with relational head"
        if right in CHANGE_HEADS:
            if left not in self.concrete_subjects and left not in self.configured_terms:
                return None
            category = "company_action" if right in ACTION_HEADS else "performance_change"
            return category, "concrete subject with change/action head"
        if right in self.object_heads:
            category = "company_action" if right in ACTION_HEADS else "concrete_phrase"
            return category, "specific modifier with object/process head"
        return None

    def extract_many(self, texts: Iterable[str]) -> list[CandidateObservation]:
        """Return per-chunk evidence without admitting broad English tokens."""
        normalized = [unicodedata.normalize("NFKC", text or "") for text in texts]
        token_batches = self.kiwi.tokenize(normalized)
        output: list[CandidateObservation] = []
        for text, tokens in zip(normalized, token_batches):
            found = CandidateObservation()
            for pattern, keyword in self.vocabulary.compound_patterns.items():
                if re.search(pattern, text, flags=re.IGNORECASE):
                    canonical = _canonical(keyword, self.vocabulary)
                    if self._accept(canonical):
                        found.direct[canonical].add(("protected_tech", "configured compound", "sector_vocabulary.compound"))
            for pattern, keyword in self.vocabulary.technology_patterns:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    canonical = _canonical(keyword, self.vocabulary)
                    if self._accept(canonical):
                        found.direct[canonical].add(("protected_tech", "configured tech regex", "sector_vocabulary.tech_regex"))

            nouns: list[tuple[str, object]] = []
            for token in tokens:
                if token.tag not in {"NNG", "NNP", "SL"}:
                    continue
                word = _canonical(token.form, self.vocabulary)
                nouns.append((word, token))
                if not self._accept(word):
                    continue
                if word in self.explicit_tech:
                    found.direct[word].add(("protected_tech", "explicit configured concept", "sector_vocabulary"))
                elif word in self.vocabulary.single_nouns and word not in self.broad_singletons:
                    found.direct[word].add(("protected_tech", "configured informative singleton", "sector_vocabulary.single_nouns"))
                elif (word in self.vocabulary.industry_anchors and word.isupper()
                      and len(word) >= 3):
                    found.direct[word].add(("protected_tech", "configured technical acronym", "sector_vocabulary.anchor"))

            for index, ((left, a), (right, b)) in enumerate(zip(nouns, nouns[1:])):
                gap = text[a.start + a.len:b.start]
                if gap not in ("", " ") or left == right:
                    continue
                phrase = _canonical(f"{left} {right}", self.vocabulary)
                # Avoid promoting the middle two tokens of an attached 3+ noun
                # compound. Complete expressions remain available to the
                # existing longer-expression promotion path.
                embedded_in_attached_compound = False
                if gap == "" and phrase not in self.configured_terms:
                    if index:
                        previous_token = nouns[index - 1][1]
                        embedded_in_attached_compound = (
                            text[previous_token.start + previous_token.len:a.start] == ""
                        )
                    if index + 2 < len(nouns):
                        next_token = nouns[index + 2][1]
                        embedded_in_attached_compound = embedded_in_attached_compound or (
                            text[b.start + b.len:next_token.start] == ""
                        )
                if embedded_in_attached_compound:
                    continue
                category = self._phrase_category(left, right)
                if (category and _HANGUL.search(phrase) and self._accept(phrase)
                        and not ({left.casefold(), right.casefold()}
                                 & self.vocabulary.excluded_tokens)
                        and not _looks_like_structural_field(
                            text, a.start, b.start + b.len, phrase, self.vocabulary
                        )):
                    found.direct[phrase].add((category[0], category[1], "kiwi.role_pair"))
                    previous = ""
                    if index and a.start - (nouns[index - 1][1].start + nouns[index - 1][1].len) <= 1:
                        previous = nouns[index - 1][0]
                    found.phrase_spans[phrase].append(
                        (a.start, b.start + b.len, left, right, previous)
                    )

            for index, (word, token) in enumerate(nouns):
                if token.tag != "SL" or not _LATIN_WORD.fullmatch(word) or not self._accept(word):
                    continue
                before = text[token.start - 1] if token.start else ""
                after_pos = token.start + token.len
                after = text[after_pos] if after_pos < len(text) else ""
                if before.isdigit() or before == "+" or after == "+":
                    continue
                neighbours = [
                    other for j, (other, nearby) in enumerate(nouns)
                    if j != index and abs(nearby.start - token.start) <= 24
                    and (other in self.object_heads or other in self.concrete_subjects
                         or other in self.configured_terms)
                ]
                if after.isdigit():
                    # Kiwi commonly represents DDR5 as DDR/SL + 5/SN.
                    following = next((t for t in tokens if t.start == after_pos), None)
                    if (following is not None and following.tag == "SN"
                            and len(following.form) == 1 and following.form.isdigit()):
                        found.generations[word].add((following.form, bool(neighbours)))
                    continue
                if word.isupper():
                    found.english[word].update(neighbours)

            output.append(found)
        return output


def _english_longer_forms(left: str, keyword: str, right: str) -> set[str]:
    """Find adjacent named English components, not arbitrary nearby words."""
    forms: set[str] = set()
    before = re.search(r"([A-Za-z][A-Za-z0-9]*)[ -]$", left)
    after = re.match(r"^[ -]([A-Za-z][A-Za-z0-9]*)", right)
    if before and (before.group(1).isupper() or before.group(1).istitle()):
        forms.add(f"{before.group(1).upper()} {keyword}")
    if after and (after.group(1).isupper() or after.group(1).istitle()):
        forms.add(f"{keyword} {after.group(1).upper()}")
    return forms


def _action_subject(text: str, start: int, end: int) -> str:
    """Classify explicit local subject cues; unresolved cases stay unclear."""
    before = text[max(0, start - 90):start]
    after = text[end:end + 40]
    if NON_ACTION_CUES.search(after):
        return "generic/unclear"
    if CUSTOMER_CUES.search(before):
        return "customer"
    if OWN_COMPANY_CUES.search(before):
        return "own_company"
    if MARKET_CUES.search(before):
        return "market/industry"
    return "generic/unclear"


_ENGLISH_SPAN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*|[0-9]+")


def _looks_like_entity_name(value: str) -> bool:
    """Identify promoted organization names from general legal-name structure."""
    tokens = [token.casefold() for token in _ENGLISH_SPAN_TOKEN.findall(value)]
    return bool(set(tokens) & ENTITY_DESIGNATORS)


def _inside_person_name_list(text: str, start: int, end: int) -> bool:
    """Detect comma-separated author/inventor lists around a promotion span."""
    line_start = max(text.rfind("\n", 0, start), text.rfind(";", 0, start)) + 1
    line_end_candidates = [
        position for position in (text.find("\n", end), text.find(";", end))
        if position >= 0
    ]
    line_end = min(line_end_candidates) if line_end_candidates else len(text)
    clause = text[line_start:line_end]
    name_initial_pairs = re.findall(
        r"\b(?:[A-Z][a-z]+\s+[A-Z](?:-?[A-Z]){0,2}"
        r"|[A-Z](?:-?[A-Z]){0,2}\s+[A-Z][a-z]+)\b",
        clause,
    )
    selected = text[start:end]
    selected_is_name = bool(re.fullmatch(
        r"(?:[A-Z][a-z]+\s+[A-Z](?:-?[A-Z]){0,2}"
        r"|[A-Z](?:-?[A-Z]){0,2}\s+[A-Z][a-z]+)",
        selected,
    ))
    citation_follows = bool(re.match(r"\s*\((?:19|20)\d{2}", text[end:end + 12]))
    return (
        clause.count(",") >= 2 and len(name_initial_pairs) >= 2
    ) or (selected_is_name and citation_follows)


def _english_promotion_forms(text: str, start: int, end: int) -> set[str]:
    """Collect contiguous 2-5 token spans around an English occurrence."""
    if _inside_person_name_list(text, start, end):
        return set()
    window_start, window_end = max(0, start - 40), min(len(text), end + 50)
    window = text[window_start:window_end]
    tokens = [(m.group(), window_start + m.start(), window_start + m.end())
              for m in _ENGLISH_SPAN_TOKEN.finditer(window)]
    middle = next((i for i, (_, a, b) in enumerate(tokens) if a == start and b == end), None)
    if middle is None:
        return set()

    def connected(left: int, right: int) -> bool:
        gap = text[tokens[left][2]:tokens[right][1]]
        return bool(gap) and bool(re.fullmatch(r"[ -]+", gap))

    # Suppress partial spans when the occurrence belongs to a longer legal
    # entity name (for example, the prefix of a name ending in BANK PLC).
    entity_first = middle
    while entity_first > 0 and connected(entity_first - 1, entity_first):
        entity_first -= 1
    entity_last = middle
    while entity_last + 1 < len(tokens) and connected(entity_last, entity_last + 1):
        entity_last += 1
    entity_span = text[tokens[entity_first][1]:tokens[entity_last][2]]
    if _looks_like_entity_name(entity_span):
        return set()

    first = middle
    while first > 0 and middle - first < 2 and connected(first - 1, first):
        first -= 1
    last = middle
    while last + 1 < len(tokens) and last - middle < 3 and connected(last, last + 1):
        last += 1
    forms: set[str] = set()
    for left in range(first, middle + 1):
        for right in range(middle, last + 1):
            if left == right or right - left + 1 > MAX_PROMOTION_TOKENS:
                continue
            span = text[tokens[left][1]:tokens[right][2]]
            # A bare number joined by whitespace is usually a size/count;
            # retain numeric prefixes only when a hyphen binds the name.
            if tokens[left][0].isdigit() and not re.match(r"\d+-", span):
                continue
            if any(token[0].isdigit() and i != left
                   for i, token in enumerate(tokens[left:right + 1], start=left)):
                continue
            if any(not (token[0].isupper() or token[0].istitle())
                   for token in tokens[left:right + 1] if not token[0].isdigit()):
                continue
            if any(len(token[0]) == 1 for token in tokens[left:right + 1]
                   if not token[0].isdigit()):
                continue
            lexical_tokens = [
                token[0].casefold() for token in tokens[left:right + 1]
                if not token[0].isdigit()
            ]
            if (
                lexical_tokens
                and (
                    lexical_tokens[0] in ENGLISH_FUNCTION_BOUNDARIES
                    or lexical_tokens[-1] in (
                        ENGLISH_FUNCTION_BOUNDARIES | ENGLISH_INCOMPLETE_SUFFIXES
                    )
                )
            ):
                continue
            generic_count = sum(
                token in GENERIC_MARKETING_ENGLISH for token in lexical_tokens
            )
            if (
                len(lexical_tokens) >= 2
                and (
                    generic_count == len(lexical_tokens)
                    or (len(lexical_tokens) >= 3
                        and generic_count / len(lexical_tokens) >= 2 / 3)
                )
            ):
                continue
            if not _looks_like_entity_name(span):
                forms.add(span)
    return forms


def _korean_promotion_forms(
    text: str, start: int, end: int, kiwi: object, role_cache: dict[str, bool],
) -> set[str]:
    """Extend from whole source words, stopping at punctuation, rows and function words."""
    forms: set[str] = set()
    left = text[max(0, start - 50):start]
    preceding = re.search(r"([A-Za-z0-9가-힣]+)([ \t]*)\Z", left)
    if preceding is None:
        return forms

    def informative(word: str) -> bool:
        if word in role_cache:
            return role_cache[word]
        # A Hangul-to-Latin switch inside a source word commonly joins table
        # cells with no delimiter. English-to-Hangul is allowed for AI향-like
        # noun modifiers when Kiwi also recognizes the final noun role.
        if re.search(r"[가-힣][A-Za-z]", word):
            role_cache[word] = False
            return False
        parsed = kiwi.tokenize(word)
        role_cache[word] = bool(
            parsed and parsed[-1].tag in {"NNG", "NNP", "SL"}
            and any(token.tag in {"NNG", "NNP", "SL"} for token in parsed)
        )
        return role_cache[word]

    word, gap = preceding.groups()
    # Attached Korean derivational prefixes (e.g. a prefix joined to a noun)
    # need not be nouns alone. Keep them when the complete source word is a
    # noun; spaced modifiers still need independent noun evidence.
    first = re.match(r"[A-Za-z0-9가-힣]+", text[start:end])
    complete_word = word + (first.group() if first else "")
    if not (informative(word) or (not gap and informative(complete_word))):
        return forms
    suffix = text[start:end]
    forms.add(word + ("" if not gap else " ") + suffix)
    before = left[:preceding.start()]
    prior = re.search(r"([A-Za-z0-9가-힣]+)[ \t]+\Z", before)
    if prior and re.search(r"[가-힣][A-Za-z]", prior.group(1)):
        return set()
    if prior and informative(prior.group(1)):
        forms.add(prior.group(1) + " " + word + ("" if not gap else " ") + suffix)
    return forms


def _span_tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in
                 re.findall(r"[A-Za-z0-9가-힣]+", value))


def _promotion_key(value: str) -> str:
    """Match case and separator variants without changing production aliases."""
    return re.sub(r"[\s\-‐‑–—]+", "", unicodedata.normalize("NFKC", value).casefold())


def _normalized_context_text(value: str) -> str:
    """Normalize superficial text variants without discarding sentence content."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans({
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
        "‘": "'", "’": "'", "“": '"', "”": '"',
    }))
    # In technical names, a separator hyphen and a space are display variants.
    value = re.sub(r"(?<=[a-z0-9])-(?=[a-z])", " ", value)
    value = re.sub(r"(?<=[a-z])-(?=[a-z0-9])", " ", value)
    value = re.sub(r"\d+(?:[.,]\d+)*", "#", value)
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s*([,.:!?()\[\]{}+\-/])\s*", r"\1", value)


def _context_signature(
    chunk_text: str, keyword: str, vocabulary: SectorVocabulary,
) -> tuple[str, ...]:
    """Return one deterministic signature per keyword-bearing chunk (C2)."""
    text = unicodedata.normalize("NFKC", chunk_text or "")
    search_keys = {_promotion_key(keyword)}
    search_keys.update(
        _promotion_key(alias)
        for alias, target in vocabulary.aliases.items()
        if _promotion_key(target) == _promotion_key(keyword)
    )
    # Keep strong line/clause boundaries; order of matching passages is meaningful.
    segments = re.split(r"[;\r\n。]+|(?<=[.!?])\s+", text)

    def contains_variant(segment: str, key: str) -> bool:
        if key.isascii() and key.isalnum() and len(key) <= 3:
            # An acronym such as AP must not match inside CAPEX.
            return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(key)
                                  + r"(?![A-Za-z0-9])", segment, re.I))
        return key in _promotion_key(segment)

    matching = [
        _normalized_context_text(segment) for segment in segments
        if any(contains_variant(segment, key) for key in search_keys)
    ]
    if matching:
        return tuple(matching)
    # An alias or generated phrase can be approved without literal display text.
    # Retain a stable chunk-local fallback rather than dropping that chunk.
    return (_normalized_context_text(text[:240]),)


def _score_context_diversity(
    result: pd.DataFrame,
    latest_candidate_chunks: dict[str, set[int]],
    latest_chunk_candidates: dict[int, set[str]],
    latest_chunk_texts: dict[int, str],
    vocabulary: SectorVocabulary,
    latest_year: int,
) -> pd.DataFrame:
    """Replace report spread with supported C2/C3 for the final candidate pool."""
    approved = set(result["keyword"])
    canonical_keys = {word: _promotion_key(word) for word in approved}
    stats: dict[str, dict[str, float | int]] = {}
    for row in result.itertuples(index=False):
        keyword = row.keyword
        chunk_ids = sorted(latest_candidate_chunks.get(keyword, set()))
        context_count = len(chunk_ids)
        expected = int(getattr(row, f"count_{latest_year}"))
        if context_count != expected:
            raise ValueError(
                f"Context count mismatch for {keyword!r}: "
                f"context_count={context_count}, count_{latest_year}={expected}"
            )
        if not context_count:
            raise ValueError(f"No latest-year context for {keyword!r}")
        contexts = {
            _context_signature(latest_chunk_texts[chunk_id], keyword, vocabulary)
            for chunk_id in chunk_ids
        }
        cooccurrences = {
            tuple(sorted({
                canonical_keys[other]
                for other in latest_chunk_candidates[chunk_id] & approved
                if canonical_keys[other] != canonical_keys[keyword]
            }))
            for chunk_id in chunk_ids
        }
        c2 = len(contexts) / context_count
        c3 = len(cooccurrences) / context_count
        raw = CONTEXT_NOVELTY_WEIGHT * c2 + COOCCURRENCE_NOVELTY_WEIGHT * c3
        support = min(1.0, context_count / DIVERSITY_FULL_SUPPORT_CHUNKS)
        stats[keyword] = {
            "context_count": context_count,
            "c2_context_novelty": c2,
            "c3_cooccurrence_novelty": c3,
            "diversity_raw": raw,
            "diversity_support": support,
            "adjusted_diversity_raw": raw * support,
        }
    result = result.join(pd.DataFrame.from_dict(stats, orient="index"), on="keyword")
    result["diversity_score"] = result["adjusted_diversity_raw"].rank(
        method="average", pct=True
    ) * 100.0
    result["signal_score"] = (
        CURRENT_WEIGHT * result["current_score"]
        + CHANGE_WEIGHT * result["change_score"]
        + DIVERSITY_WEIGHT * result["diversity_score"]
    )
    result["final_signal_score"] = result["signal_score"] - result["generic_business_penalty"]
    result = result.sort_values(
        ["final_signal_score", "keyword"], ascending=[False, True]
    ).reset_index(drop=True)
    result["final_rank"] = result.index + 1
    return result


def _is_contained_span(short: str, long: str) -> bool:
    """Compare token sequences, including Korean attached-prefix completion."""
    small, large = _span_tokens(short), _span_tokens(long)
    if len(small) < len(large):
        return any(large[i:i + len(small)] == small
                   for i in range(len(large) - len(small) + 1))
    return short.replace(" ", "").casefold() in long.replace(" ", "").casefold()


def _promotion_span_features(
    short: str, phrase: str, occurrences: int,
    stopwords: set[str],
) -> dict[str, object]:
    """Return only the span features used by promotion approval."""
    tokens = _span_tokens(phrase)
    generic_terms = {term.casefold() for term in stopwords | VAGUE_MODIFIERS}
    generic = sum(token in generic_terms for token in tokens)
    return {
        "occurrence_count": occurrences,
        "token_length": len(tokens),
        "generic_token_count": generic,
        "contains_short": _is_contained_span(short, phrase),
    }


def score_database_company_keywords_v2(
    config: CompanySignalConfig,
    company_name: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    chunks: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Score DB pages or an already version-scoped repository corpus."""
    if page_size < 1:
        raise ValueError("page_size must be positive")
    where, params = _analysis_where(config)
    summary = (chunks.groupby(["year","report_type"]).size().reset_index(name="total_chunks") if chunks is not None else query(
        f"SELECT year, report_type, COUNT(*) AS total_chunks FROM chunk_metadata WHERE {where} "
        "GROUP BY year, report_type", params))
    if summary.empty:
        raise ValueError(f"No searchable chunks available for {config.corp_code}")
    totals = summary.groupby("year")["total_chunks"].sum().reindex(config.years, fill_value=0)
    latest = config.years[-1]
    if totals[latest] == 0:
        raise ValueError(f"No searchable chunks available for latest year: {latest}")
    extractor = CompanyCandidateExtractorV2(
        [company_name], config.vocabulary, config.extra_stopwords,
        V2_SECTOR_ROLES.get(config.sector_index_code, V2SectorRoles()),
    )
    observed: list[tuple[int, int, str, CandidateObservation]] = []
    english_chunks: dict[str, set[int]] = defaultdict(set)
    english_sections: dict[str, set[str]] = defaultdict(set)
    english_contexts: dict[str, set[int]] = defaultdict(set)
    english_neighbours: dict[str, set[str]] = defaultdict(set)
    english_section_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    english_occurrences: dict[str, int] = defaultdict(int)
    english_standalone_occurrences: dict[str, int] = defaultdict(int)
    english_model_fragments: dict[str, int] = defaultdict(int)
    english_other_latin_contexts: dict[str, int] = defaultdict(int)
    english_longer_occurrences: dict[str, int] = defaultdict(int)
    english_longer_forms: dict[str, Counter[str]] = defaultdict(Counter)
    english_patterns: dict[str, re.Pattern[str]] = {}
    phrase_occurrences: dict[str, int] = defaultdict(int)
    phrase_longer_occurrences: dict[str, int] = defaultdict(int)
    action_subjects: dict[str, Counter[str]] = defaultdict(Counter)
    promotion_occurrences: dict[str, Counter[str]] = defaultdict(Counter)
    promotion_occurrence_ids: dict[str, dict[str, set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )
    promotion_serial: dict[str, int] = defaultdict(int)
    promotion_chunks: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    promotion_latest_chunks: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    promotion_by_chunk: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    promotion_category: dict[str, str] = {}
    prefix_role_cache: dict[str, bool] = {}
    generation_chunks: dict[str, set[int]] = defaultdict(set)
    generation_numbers: dict[str, set[str]] = defaultdict(set)
    generation_contexts: dict[str, set[int]] = defaultdict(set)
    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    latest_chunk_texts: dict[int, str] = {}
    sector_context_chunks: set[int] = set()
    last_vector_id = -1
    while True:
        page = (chunks.loc[chunks["vector_id"]>last_vector_id].sort_values("vector_id").head(page_size) if chunks is not None else query(
            "SELECT vector_id, year, section_name, chunk_text FROM chunk_metadata "
            f"WHERE {where} AND vector_id > %s ORDER BY vector_id LIMIT %s", [*params,last_vector_id,int(page_size)]))
        if page.empty:
            break
        for row, observation in zip(
            page.itertuples(index=False), extractor.extract_many(page["chunk_text"].fillna(""))
        ):
            chunk_id = int(row.vector_id)
            observed.append((chunk_id, int(row.year), row.section_name, observation))
            text = unicodedata.normalize("NFKC", row.chunk_text or "")
            if extractor.has_sector_context(text):
                sector_context_chunks.add(chunk_id)
            if int(row.year) == latest:
                latest_chunk_texts[chunk_id] = text
            for keyword, spans in observation.phrase_spans.items():
                for start, end, left_word, _, previous in spans:
                    phrase_occurrences[keyword] += 1
                    attached = re.search(r"[가-힣]+$", text[max(0, start - 12):start])
                    longer = (
                        f"{attached.group()}+{keyword}" if attached else
                        f"{previous} {keyword}" if previous else ""
                    )
                    if longer:
                        phrase_longer_occurrences[keyword] += 1
                    parts = keyword.split()
                    is_action = len(parts) == 2 and parts[1] in ACTION_HEADS
                    promotion_serial[keyword] += 1
                    occurrence_id = promotion_serial[keyword]
                    for raw_form in _korean_promotion_forms(
                        text, start, end, extractor.kiwi, prefix_role_cache
                    ):
                        completed = _canonical(raw_form, extractor.vocabulary)
                        prefix = completed.replace(keyword, "", 1).strip()
                        boundary_tokens = _span_tokens(completed)
                        if (completed == keyword or not extractor._accept(completed)
                                or (boundary_tokens and (
                                    boundary_tokens[0] in BOUNDARY_FUNCTION_MODIFIERS
                                    or boundary_tokens[-1] in BOUNDARY_FUNCTION_MODIFIERS
                                ))
                                or (is_action and prefix in (
                                    VAGUE_MODIFIERS | STRUCTURAL_MODIFIERS
                                    | GENERIC_PHRASE_MODIFIERS
                                ))):
                            continue
                        promotion_occurrences[keyword][completed] += 1
                        promotion_occurrence_ids[keyword][completed].add(occurrence_id)
                        promotion_chunks[keyword][completed].add(chunk_id)
                        if int(row.year) == latest:
                            promotion_latest_chunks[keyword][completed].add(chunk_id)
                        promotion_by_chunk[chunk_id][keyword].add(completed)
                        promotion_category[completed] = (
                            "market_signal" if is_action else "promoted_concrete_phrase"
                        )
                    if (len(parts) == 2 and parts[0] in GENERIC_PHRASE_MODIFIERS
                            and parts[1] in ACTION_HEADS):
                        action_subjects[keyword][_action_subject(text, start, end)] += 1
            # Configured compounds retain their extraction path. An action-like
            # compound without a Kiwi span still needs the same subject audit.
            for keyword in observation.direct:
                parts = keyword.split()
                if (keyword in observation.phrase_spans or len(parts) != 2
                        or parts[0] not in GENERIC_PHRASE_MODIFIERS
                        or parts[1] not in ACTION_HEADS):
                    continue
                pattern = re.compile(r"\s*".join(map(re.escape, parts)), re.I)
                for match in pattern.finditer(text):
                    action_subjects[keyword][
                        _action_subject(text, match.start(), match.end())
                    ] += 1
            for keyword, neighbours in observation.english.items():
                english_chunks[keyword].add(chunk_id)
                english_sections[keyword].add(row.section_name)
                english_section_counts[keyword][row.section_name] += 1
                english_neighbours[keyword].update(neighbours)
                if neighbours:
                    english_contexts[keyword].add(chunk_id)
                pattern = english_patterns.setdefault(
                    keyword,
                    re.compile(r"(?<![A-Za-z])" + re.escape(keyword) + r"(?![A-Za-z])", re.I),
                )
                for match in pattern.finditer(text):
                    left = text[max(0, match.start() - 12):match.start()]
                    right = text[match.end():match.end() + 12]
                    before = left[-1:] if left else ""
                    after = right[:1]
                    english_occurrences[keyword] += 1
                    english_standalone_occurrences[keyword] += not (
                        before.isdigit() or after.isdigit() or before == "+" or after == "+"
                    )
                    # Adjacent or one-space-separated numbers include versions
                    # and model fragments, not just measurement suffixes.
                    english_model_fragments[keyword] += bool(
                        re.search(r"\d\s?$", left) or re.match(r"^\s?\d", right)
                    )
                    # A nearby English component may be a generic modifier or a compound part.
                    english_other_latin_contexts[keyword] += bool(
                        re.search(r"[A-Za-z]{2,}\s?$", left)
                        or re.match(r"^\s?[A-Za-z]{2,}", right)
                    )
                    longer_forms = _english_longer_forms(left, keyword, right)
                    if longer_forms:
                        english_longer_occurrences[keyword] += 1
                        english_longer_forms[keyword].update(longer_forms)
                    promotion_serial[keyword] += 1
                    occurrence_id = promotion_serial[keyword]
                    for completed in _english_promotion_forms(text, match.start(), match.end()):
                        completed = _canonical(completed, extractor.vocabulary)
                        if (not extractor._accept(completed)
                                or any(
                                    part in extractor.company_names
                                    for part in completed.split()
                                )):
                            continue
                        promotion_occurrences[keyword][completed] += 1
                        promotion_occurrence_ids[keyword][completed].add(occurrence_id)
                        promotion_chunks[keyword][completed].add(chunk_id)
                        if int(row.year) == latest:
                            promotion_latest_chunks[keyword][completed].add(chunk_id)
                        promotion_by_chunk[chunk_id][keyword].add(completed)
                        promotion_category[completed] = "promoted_technical_phrase"
            for keyword, generations in observation.generations.items():
                generation_chunks[keyword].add(chunk_id)
                generation_numbers[keyword].update(number for number, _ in generations)
                if any(has_context for _, has_context in generations):
                    generation_contexts[keyword].add(chunk_id)
        last_vector_id = int(page["vector_id"].iloc[-1])

    # Canonicalize only the promoted expressions. Preserve the established
    # protected/independent/generation paths and all scoring inputs.
    spelling_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for forms in promotion_occurrences.values():
        for spelling, frequency in forms.items():
            spelling_counts[_promotion_key(spelling)][spelling] += frequency
    configured_spellings = {
        _promotion_key(term): term for term in extractor.configured_terms
    }
    display_by_key = {
        key: configured_spellings.get(key) or max(
            variants, key=lambda spelling: (
                variants[spelling],
                sum(part.isupper() for part in re.findall(r"[A-Za-z]+", spelling)),
                len(spelling),
            ),
        )
        for key, variants in spelling_counts.items()
    }
    merged_ids: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    merged_chunks: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    merged_latest: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    merged_categories: dict[str, str] = {}
    for short, forms in promotion_occurrences.items():
        for spelling in forms:
            canonical = display_by_key[_promotion_key(spelling)]
            merged_ids[short][canonical].update(promotion_occurrence_ids[short][spelling])
            merged_chunks[short][canonical].update(promotion_chunks[short][spelling])
            merged_latest[short][canonical].update(promotion_latest_chunks[short][spelling])
            merged_categories[canonical] = promotion_category[spelling]
    promotion_occurrence_ids = merged_ids
    promotion_occurrences = defaultdict(Counter, {
        short: Counter({form: len(ids) for form, ids in forms.items()})
        for short, forms in merged_ids.items()
    })
    promotion_chunks = merged_chunks
    promotion_latest_chunks = merged_latest
    promotion_category = merged_categories
    promotion_by_chunk = defaultdict(lambda: defaultdict(set), {
        chunk_id: defaultdict(set, {
            short: {display_by_key[_promotion_key(form)] for form in forms}
            for short, forms in short_forms.items()
        })
        for chunk_id, short_forms in promotion_by_chunk.items()
    })

    english_routes: dict[str, str] = {}
    approved_english: set[str] = set()
    for keyword, chunks in english_chunks.items():
        independent = len(chunks)
        technical = len(english_contexts[keyword])
        occurrences = max(1, english_occurrences[keyword])
        context_ratio = technical / independent
        dominant_ratio = max(english_section_counts[keyword].values()) / independent
        standalone_ratio = english_standalone_occurrences[keyword] / occurrences
        model_ratio = english_model_fragments[keyword] / occurrences
        generic_ratio = english_other_latin_contexts[keyword] / occurrences
        section_count = len(english_sections[keyword])
        neighbour_count = len(english_neighbours[keyword])
        safe_context = (
            technical >= MIN_TECH_CONTEXTS
            and context_ratio >= MIN_CONTEXT_RATIO
            and standalone_ratio >= MIN_STANDALONE_RATIO
            and model_ratio <= MAX_MODEL_FRAGMENT_RATIO
        )
        breadth_sections = safe_context and section_count >= 2
        breadth_neighbours = (
            safe_context and neighbour_count >= MIN_NEIGHBOUR_BREADTH
            and context_ratio >= MIN_NEIGHBOUR_CONTEXT_RATIO
            and generic_ratio <= MAX_NEIGHBOUR_GENERIC_ENGLISH_RATIO
        )
        single_section_depth = (
            section_count == 1
            and dominant_ratio >= MIN_DOMINANT_SECTION_RATIO
            and technical >= MIN_SINGLE_SECTION_CONTEXTS
            and context_ratio >= MIN_SINGLE_SECTION_CONTEXT_RATIO
            and standalone_ratio >= MIN_STANDALONE_RATIO
            and model_ratio <= MAX_SINGLE_SECTION_MODEL_RATIO
            and generic_ratio <= MAX_SINGLE_SECTION_GENERIC_ENGLISH_RATIO
        )
        if len(keyword) == 2 and keyword not in extractor.configured_terms:
            strong_short_english = (
                safe_context
                and technical >= 12
                and context_ratio >= 0.60
                and standalone_ratio >= 0.50
                and model_ratio <= 0.20
                and (section_count >= 2 or neighbour_count >= 5)
            )
            route = "strong_short_english" if strong_short_english else "rejected"
        else:
            route = (
                "section_breadth" if breadth_sections else
                "neighbour_breadth" if breadth_neighbours else
                "single_section_depth" if single_section_depth else "rejected"
            )
        if route != "rejected":
            approved_english.add(keyword)
        english_routes[keyword] = route
    approved_generations = {
        keyword for keyword, chunks in generation_chunks.items()
        if (keyword.isupper() and len(keyword) >= 3 and len(chunks) >= 8
            and len(generation_numbers[keyword]) >= 2
            and len(generation_contexts[keyword]) >= 2)
    }
    suppressed_english_longer: set[str] = set()
    for keyword in english_routes:
        total = english_occurrences[keyword]
        longer = english_longer_occurrences[keyword]
        top_two = sum(count for _, count in english_longer_forms[keyword].most_common(2))
        longer_ratio = longer / total if total else 0.0
        top_two_ratio = min(1.0, top_two / total) if total else 0.0
        if (keyword not in extractor.configured_terms
                and keyword not in approved_generations
                and total >= MIN_LONGER_OCCURRENCES
                and longer_ratio >= MIN_ENGLISH_LONGER_RATIO
                and top_two_ratio >= MIN_ENGLISH_TOP_TWO_RATIO):
            suppressed_english_longer.add(keyword)

    suppressed_generic_phrases: set[str] = set()
    for keyword, total in phrase_occurrences.items():
        parts = keyword.split()
        longer = phrase_longer_occurrences[keyword]
        longer_ratio = longer / total
        generic_pair = (
            len(parts) == 2 and parts[0] in GENERIC_PHRASE_MODIFIERS
            and parts[1] in (GENERIC_STANDALONE | extractor.object_heads)
            and parts[1] not in ACTION_HEADS
        )
        if (generic_pair and keyword not in extractor.explicit_tech
                and longer_ratio >= MIN_GENERIC_PHRASE_LONGER_RATIO):
            suppressed_generic_phrases.add(keyword)

    suppressed_actions: set[str] = set()
    for keyword, subjects in action_subjects.items():
        total = subjects.total()
        own = subjects["own_company"]
        if own < MIN_OWN_ACTION_CONTEXTS or own / total < MIN_OWN_ACTION_RATIO:
            suppressed_actions.add(keyword)

    promotion_reasons: dict[str, set[str]] = defaultdict(set)
    promoted_by_short: dict[str, set[str]] = defaultdict(set)
    for short in suppressed_english_longer | suppressed_generic_phrases | suppressed_actions:
        short_count = (
            english_occurrences[short] if short in suppressed_english_longer
            else phrase_occurrences[short]
        )
        if not short_count:
            continue
        minimum_share = (
            MIN_ENGLISH_PROMOTION_SHARE if short in suppressed_english_longer
            else MIN_KOREAN_PROMOTION_SHARE
        )
        eligible: dict[str, dict[str, object]] = {}
        for longer, occurrences in promotion_occurrences[short].items():
            chunks = promotion_chunks[short][longer]
            latest_chunks = promotion_latest_chunks[short][longer]
            features = _promotion_span_features(
                short, longer, occurrences,
                extractor.stopwords,
            )
            features["chunk_count"] = len(chunks)
            features["latest_year_chunk_count"] = len(latest_chunks)
            if (occurrences < MIN_PROMOTION_OCCURRENCES
                    or len(chunks) < MIN_PROMOTION_CHUNKS
                    or len(latest_chunks) < MIN_PROMOTION_LATEST_CHUNKS
                    or occurrences / short_count < minimum_share
                    or not features["contains_short"]
                    or features["generic_token_count"] > max(1, features["token_length"] // 3)):
                continue
            eligible[longer] = features
        for shorter, features in eligible.items():
            short_ids = promotion_occurrence_ids[short][shorter]
            extensions = [
                (longer, len(short_ids & promotion_occurrence_ids[short][longer]) / len(short_ids))
                for longer in eligible if longer != shorter
                and len(longer.replace(" ", "")) > len(shorter.replace(" ", ""))
                and _is_contained_span(shorter, longer)
            ]
            strongest = max(extensions, key=lambda item: item[1], default=("", 0.0))
            features["boundary_stability"] = 1.0 - strongest[1]
            features["subset_of"] = (
                strongest[0] if strongest[1] >= MIN_CANONICAL_EXTENSION_SHARE else None
            )
            if features["subset_of"]:
                continue
            promoted_by_short[short].add(shorter)
            promotion_reasons[shorter].add(
                f"v2.5 stable boundary from {short}: "
                f"{features['occurrence_count']} repeats, "
                f"{features['chunk_count']} chunks, "
                f"{features['boundary_stability']:.2f} boundary stability"
            )

    # A short technical/generic form is replaced only when an eligible longer
    # candidate exists. Ambiguous action phrases still require own-company
    # evidence even when no longer market signal can be promoted.
    suppressed = suppressed_actions | {
        short for short in suppressed_english_longer | suppressed_generic_phrases
        if promoted_by_short[short]
    }
    paths: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    all_candidate_chunks: dict[str, set[int]] = defaultdict(set)
    latest_candidate_chunks: dict[str, set[int]] = defaultdict(set)
    latest_chunk_candidates: dict[int, set[str]] = {}
    for chunk_id, year, _, observation in observed:
        chunk_keywords = set(observation.direct)
        chunk_keywords.update(set(observation.english) & approved_english)
        chunk_keywords.update(set(observation.generations) & approved_generations)
        chunk_keywords.difference_update(suppressed)
        for short, longer_forms in promotion_by_chunk.get(chunk_id, {}).items():
            for longer in longer_forms & promoted_by_short[short]:
                chunk_keywords.add(longer)
                paths[longer].add((
                    promotion_category[longer],
                    "; ".join(sorted(promotion_reasons[longer])),
                    "v2.5.stable_boundary",
                ))
        for keyword in chunk_keywords:
            all_candidate_chunks[keyword].add(chunk_id)
            counts[keyword][year] += 1
            if year == latest:
                latest_candidate_chunks[keyword].add(chunk_id)
            paths[keyword].update(observation.direct.get(keyword, ()))
            if keyword in observation.english and keyword in approved_english:
                paths[keyword].add((
                    "independent_tech",
                    f"v2.2 {english_routes[keyword]}: independent technical contexts",
                    "kiwi.english_context",
                ))
            if keyword in observation.generations and keyword in approved_generations:
                paths[keyword].add((
                    "technical_generation", "multiple observed SL+SN generations with technical context",
                    "kiwi.SL+SN",
                ))
        if year == latest:
            latest_chunk_candidates[chunk_id] = chunk_keywords

    protected_categories = {
        "protected_tech", "technical_generation", "independent_tech",
    }
    sector_unrelated = {
        keyword for keyword, chunks in all_candidate_chunks.items()
        if chunks.isdisjoint(sector_context_chunks)
        and not any(category in protected_categories for category, _, _ in paths[keyword])
    }
    for keyword in sector_unrelated:
        counts.pop(keyword, None)
        latest_candidate_chunks.pop(keyword, None)
    if sector_unrelated:
        for chunk_keywords in latest_chunk_candidates.values():
            chunk_keywords.difference_update(sector_unrelated)

    result = _result_from_counts(counts, totals, config)
    if result.empty:
        return result
    result = _score_context_diversity(
        result, latest_candidate_chunks, latest_chunk_candidates,
        latest_chunk_texts, config.vocabulary, latest,
    )
    category_order = (
        "protected_tech", "technical_generation", "independent_tech",
        "promoted_technical_phrase", "promoted_concrete_phrase", "market_signal",
        "concrete_phrase", "performance_change", "company_action",
    )
    def provenance(keyword: str) -> pd.Series:
        entries = paths[keyword]
        primary = next(category for category in category_order
                       if any(path[0] == category for path in entries))
        reasons = sorted({reason for category, reason, _ in entries if category == primary})
        sources = sorted({source for _, _, source in entries})
        return pd.Series({
            "candidate_category": primary,
            "approval_reason": "; ".join(reasons),
            "source": "; ".join(sources),
        })
    return pd.concat(
        [result, result["keyword"].apply(provenance).reset_index(drop=True)],
        axis=1,
    )


def build_company_signal_v2(
    config: CompanySignalConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Return visual Top-N, all scored candidates, and company metadata."""
    company = get_company(config.corp_code)
    all_keywords = score_database_company_keywords_v2(config, company["corp_name"])
    return add_display_weights(all_keywords.head(config.top_n)), all_keywords, company


def company_wordcloud_items(
    top_keywords: pd.DataFrame,
    disclosure_contexts: Mapping[str, str] | None = None,
    selection_reasons: Mapping[str, str] | None = None,
    source_urls: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Serialize company Top-N rows for the shared UI word-cloud contract.

    Scoring supplies the visual fields and a technical ``approval_reason``.
    Human-readable disclosure summaries and DART URLs can be injected by the
    backend without coupling retrieval or LLM enrichment to production scoring.
    """
    if "display_weight" not in top_keywords:
        top_keywords = add_display_weights(top_keywords)
    disclosure_contexts = disclosure_contexts or {}
    selection_reasons = selection_reasons or {}
    source_urls = source_urls or {}

    def optional_text(value: object) -> str | None:
        return None if value is None or pd.isna(value) else str(value)

    items: list[dict[str, object]] = []
    for row in top_keywords.itertuples(index=False):
        keyword = str(row.keyword)
        disclosure_context = disclosure_contexts.get(
            keyword, getattr(row, "disclosureContext", None)
        )
        selection_reason = selection_reasons.get(
            keyword,
            getattr(row, "selectionReason", getattr(row, "approval_reason", None)),
        )
        source_url = source_urls.get(keyword, getattr(row, "sourceUrl", None))
        items.append({
            "keyword": keyword,
            "display_weight": float(row.display_weight),
            "is_hot": bool(row.is_hot),
            "final_signal_score": float(row.final_signal_score),
            "disclosureContext": optional_text(disclosure_context),
            "selectionReason": optional_text(selection_reason),
            "sourceUrl": optional_text(source_url),
        })
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Company word cloud")
    parser.add_argument("corp_code")
    parser.add_argument("--sector-index")
    parser.add_argument("--years", nargs="+", type=int, help="생략 시 현재 DB 전체 연도")
    parser.add_argument("--top-n", type=int, default=12)
    args = parser.parse_args()
    from .repository import Repository
    repo=Repository(args.sector_index)
    config = CompanySignalConfig(args.corp_code, args.sector_index, tuple(repo.analysis_years(args.years)), args.top_n)
    top, all_keywords, company = build_company_signal_v2(config)
    print(f"Company: {company['corp_name']} ({company['corp_code']})")
    print(f"Final candidates: {len(all_keywords):,}")
    columns = ["final_rank", "keyword", "current_score", "change_score",
               "context_count", "c2_context_novelty", "c3_cooccurrence_novelty",
               "diversity_support", "diversity_score", "signal_score",
               "generic_business_penalty", "final_signal_score", "is_hot",
               "display_weight", "candidate_category", "approval_reason"]
    print(top[columns].to_string(index=False))


if __name__ == "__main__":
    main()
