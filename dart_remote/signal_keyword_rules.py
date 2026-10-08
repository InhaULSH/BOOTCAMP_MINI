"""Shared disclosure filters and injectable sector vocabularies.

Register a new ``SectorVocabulary`` here without changing scoring code.
"""
from dataclasses import dataclass, field
from typing import Mapping

# Document/table, governance, and abstract words.  This is intentionally a
# compact category-based list, not a frequency-driven dump of every noun.
STOPWORDS = frozenset({
    "단위", "합계", "전체", "누적", "범주", "종류", "설명", "이외", "조건", "기준",
    "당분", "위원회", "결의", "보상", "기술", "기능", "체계", "성격", "결합",
    "구분", "항목", "내용", "사항", "기타", "해당", "경우", "관련", "주요", "기준일",
    "금액", "비율", "수량", "기말", "기초", "연결", "별도", "주석", "표", "계",
    "이사회", "감사", "주주", "임원", "직원", "보수", "의결", "외환", "거래",
    "회사", "당사", "사업", "시장", "제품", "계획", "실적", "매출", "이익", "비용",
    "증가", "감소", "변동", "영향", "추진", "개선", "관리", "운영", "보고서", "공시",
})

# A Korean single noun is retained only when it is a sector concept on its own.
# Other Korean nouns need to occur as a neighbouring-noun phrase.
INDUSTRY_SINGLE_NOUNS = frozenset({
    "반도체", "파운드리", "메모리", "웨이퍼", "패키징", "데이터센터", "후공정", "전공정",
})

# Generic table/specification tokens and low-information noun pairs are
# excluded as classes.  They are not technology/product/demand/capacity
# concepts even when a morphology analyser recognizes them as nouns.
MEASUREMENT_OR_TABLE_TOKENS = frozenset({
    "mm", "nm", "um", "μm", "size", "type", "model", "data", "test",
})
LOW_INFORMATION_PHRASE_TERMS = frozenset({
    "조사", "기관", "규모", "경쟁력", "확보", "완료", "개발", "계획", "현황", "대상",
    "제조", "생산", "글로벌", "국내", "해외", "일반", "기타", "관련", "주요",
    "확대", "증가", "감소", "개선", "강화", "추진", "수익", "구조", "판매", "전략",
    "경영", "시스템", "연구", "과제", "지속", "성장",
})
SECTOR_HEADER_PHRASES = frozenset({
    "반도체 제조", "반도체 생산", "글로벌 반도체", "반도체 산업", "반도체 시장",
})

# The values below were confirmed to occur in the KRX_SEMI corpus.
COMPOUND_PATTERNS = {
    r"\bAI\s*서버\b": "AI 서버",
    r"\bAI\s*반도체\b": "AI 반도체",
    r"\b첨단\s*패키징\b": "첨단 패키징",
    r"\b고대역폭\s*메모리\b": "HBM",
    r"\b메모리\s*반도체\b": "메모리 반도체",
    r"\b생산\s*능력\b": "생산 능력",
    r"\b설비\s*투자\b": "설비 투자",
    r"\bAI\s*수요\b": "AI 수요",
    r"\bHBM(?:3E?|4)?\s*수요\b": "HBM 수요",
}

ALIASES = {
    "고대역폭메모리": "HBM", "고대역폭 메모리": "HBM",
    "hbm": "HBM", "hbm3": "HBM", "hbm3e": "HBM", "hbm4": "HBM",
    "ai서버": "AI 서버", "ai 서버": "AI 서버",
}

# Actual DB section values.  Industry/strategy sections are included; the
# R&D detailed table is included as a special case.  Financial statements,
# governance, shareholder and table-of-contents chunks are excluded by design.
ALLOWED_SECTION_PREFIXES = (
    "II. 사업의 내용",
    "IV. 이사의 경영진단 및 분석의견",
)
ALLOWED_SUBSECTION_PHRASES = ("연구개발실적",)

CONTEXT_REQUIRED_COMPONENTS = frozenset({"AI", "수요", "투자", "수익", "판매", "경영", "연구"})

# ESG/legal/PR boilerplate is excluded only when the phrase itself has no
# product, technology, production, or market anchor. This retains concrete
# semiconductor concepts that happen to occur in the same disclosure section.
NON_INDUSTRY_THEME_TERMS = frozenset({
    "환경", "탄소", "녹색", "온실가스", "재생에너지", "배출", "지속가능", "화학", "물질",
    "정부", "보조금", "법", "법률", "법규", "기본법", "규제", "안전", "보건", "사회",
    "지배구조", "윤리", "준수", "인증", "최고", "수준",
})
INDUSTRY_ANCHOR_TERMS = frozenset({
    "HBM", "DRAM", "NAND", "SSD", "GDDR", "HPC", "AI", "CXL", "EUV", "파운드리",
    "패키징", "웨이퍼", "메모리", "서버", "데이터센터", "공정", "장비", "소재", "수요", "투자",
})


@dataclass(frozen=True)
class SectorVocabulary:
    """Optional vocabulary supplied to the common candidate extractor."""

    aliases: Mapping[str, str] = field(default_factory=dict)
    compound_patterns: Mapping[str, str] = field(default_factory=dict)
    single_nouns: frozenset[str] = frozenset()
    excluded_phrases: frozenset[str] = frozenset()
    industry_anchors: frozenset[str] = frozenset()
    excluded_theme_terms: frozenset[str] = frozenset()
    excluded_tokens: frozenset[str] = frozenset()
    context_required_components: frozenset[str] = frozenset()
    stopwords: frozenset[str] = frozenset()
    technology_patterns: tuple[tuple[str, str], ...] = ()


GENERIC_VOCABULARY = SectorVocabulary()

# Preserves the existing KRX_SEMI output. Other sectors can explicitly pass
# GENERIC_VOCABULARY or their own SectorVocabulary in SignalConfig.
SEMICONDUCTOR_VOCABULARY = SectorVocabulary(
    aliases=ALIASES,
    compound_patterns=COMPOUND_PATTERNS,
    single_nouns=INDUSTRY_SINGLE_NOUNS,
    excluded_phrases=SECTOR_HEADER_PHRASES,
    industry_anchors=INDUSTRY_ANCHOR_TERMS,
    excluded_theme_terms=NON_INDUSTRY_THEME_TERMS,
    excluded_tokens=frozenset({"glass"}),
    context_required_components=CONTEXT_REQUIRED_COMPONENTS,
    stopwords=frozenset({"반도체"}),
    technology_patterns=(
        (r"\bHBM(?:3E?|4)?\b", "HBM"), (r"\bDRAM\b", "DRAM"),
        (r"\bNAND\b", "NAND"), (r"\bEUV\b", "EUV"),
        (r"\bCXL\b", "CXL"), (r"\bAI\b", "AI"),
    ),
)
SECTOR_VOCABULARIES: Mapping[str, SectorVocabulary] = {
    "KRX_SEMI": SEMICONDUCTOR_VOCABULARY,
}


# Shared disclosure categories: three hard exclusions, a two-point general-
# business penalty, and promotional labels for inspection only.
GENERIC_NOISE_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "통화/환율": (
        r"^(?:USD|JPY|KRW|EUR|CNY|GBP|CHF|CAD|AUD|HKD|SGD)$",
        r"(?:환율|환산|외화|원화|통화위험)",
    ),
    "기간 비교": (r"(?:전년|전기|전분기|전월|당기|동기|전년도|기간 대비)",),
    "홍보·수식": (r"(?:업계 최초|세계 최초|국내 최초|최고 수준|업계 최고|경쟁 우위)",),
    "회계·보고서 관용": (
        r"(?:재고 자산|매출액|재무|회계|충당금|감가상각|장부가액|보고기간)",
    ),
    "일반 경영": (r"(?:부가 가치|자금 조달|수주 상황|경영 전략|사업 계획)",),
}
PRODUCTION_GENERIC_NOISE_CATEGORIES = frozenset({"통화/환율", "기간 비교", "회계·보고서 관용"})
