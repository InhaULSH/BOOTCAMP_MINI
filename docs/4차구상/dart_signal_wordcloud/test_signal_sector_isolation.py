"""Regression checks for sector-neutral candidate extraction."""

import unittest
from types import SimpleNamespace

import pandas as pd

from dart_signal_wordcloud.dart_signal_wordcloud import (
    KeywordExtractor,
    SignalConfig,
    _canonical,
    _is_candidate,
    _is_informative_phrase,
    score_keywords,
    wordcloud_items,
)
from dart_signal_wordcloud.signal_keyword_rules import (
    AUTOMOBILE_VOCABULARY, BANK_VOCABULARY, GENERIC_VOCABULARY,
    HEALTHCARE_VOCABULARY, SEMICONDUCTOR_VOCABULARY,
    SECTOR_VOCABULARIES, SectorVocabulary,
)


class SectorIsolationTests(unittest.TestCase):
    @staticmethod
    def dummy_vocabulary() -> SectorVocabulary:
        return SectorVocabulary(
            aliases={"ev2": "EV"},
            compound_patterns={r"배터리\s*셀": "배터리 셀"},
            single_nouns=frozenset({"배터리"}),
            technology_patterns=((r"\bEV2\b", "EV"),),
        )

    def test_neutral_defaults_and_semiconductor_profile(self) -> None:
        self.assertIs(SignalConfig("KRX_DUMMY").vocabulary, GENERIC_VOCABULARY)
        for callable_with_vocabulary in (
            _canonical, _is_candidate, _is_informative_phrase, KeywordExtractor.__init__
        ):
            self.assertIs(callable_with_vocabulary.__defaults__[-1], GENERIC_VOCABULARY)
        self.assertEqual(_canonical("hbm3"), "hbm3")
        self.assertEqual(_canonical("hbm3", SEMICONDUCTOR_VOCABULARY), "HBM")
        self.assertTrue(_is_informative_phrase("glass 소재"))
        self.assertFalse(_is_informative_phrase("glass 소재", SEMICONDUCTOR_VOCABULARY))
        self.assertNotIn("반도체", KeywordExtractor([]).stopwords)
        self.assertIn("반도체", KeywordExtractor([], vocabulary=SEMICONDUCTOR_VOCABULARY).stopwords)

    def test_dummy_vocabulary_does_not_inherit_semiconductor_rules(self) -> None:
        dummy = self.dummy_vocabulary()
        self.assertEqual(_canonical("hbm3", dummy), "hbm3")
        extractor = KeywordExtractor([], vocabulary=dummy)
        # Isolate configured regexes from ordinary Kiwi English-token output.
        extractor.kiwi = SimpleNamespace(tokenize=lambda texts: [[] for _ in texts])
        regex_only = extractor.extract_many(["HBM3 DRAM EV2 배터리 셀"])[0]
        self.assertIn("배터리 셀", regex_only)
        self.assertIn("EV", regex_only)
        self.assertNotIn("HBM", regex_only)
        self.assertNotIn("DRAM", regex_only)
        natural = KeywordExtractor([], vocabulary=dummy).extract_many(["glass 소재 배터리 셀"])[0]
        self.assertIn("glass 소재", natural)

    def test_dummy_vocabulary_reaches_scoring_pipeline(self) -> None:
        companies = pd.DataFrame([
            {"corp_code": "a", "corp_name": "Alpha"},
            {"corp_code": "b", "corp_name": "Beta"},
        ])
        chunks = pd.DataFrame([
            {
                "chunk_id": f"{year}-{code}",
                "corp_code": code,
                "year": year,
                "chunk_text": "EV2 glass 소재 배터리 셀",
            }
            for year in (2023, 2024, 2025)
            for code in ("a", "b")
        ])
        result = score_keywords(
            chunks, SignalConfig("KRX_DUMMY", vocabulary=self.dummy_vocabulary()), companies
        )
        self.assertIn("배터리 셀", set(result["keyword"]))
        self.assertIn("glass 소재", set(result["keyword"]))
        row = result.set_index("keyword").loc["배터리 셀"]
        self.assertEqual(int(row["company_count"]), 2)
        self.assertAlmostEqual(
            row["signal_score"],
            0.50 * row["current_score"] + 0.30 * row["change_score"] + 0.20 * row["spread_score"],
        )
        self.assertAlmostEqual(
            row["final_signal_score"],
            row["signal_score"] - row["concentration_penalty"] - row["generic_business_penalty"],
        )
        self.assertEqual(wordcloud_items(result)[0]["size"], round(result.iloc[0]["final_signal_score"], 2))

    def test_shared_field_roles_do_not_remove_technical_phrases(self) -> None:
        for phrase in ("계약 상대방", "진행 경과", "유동 자산", "공정 가치", "일정 수준"):
            self.assertFalse(_is_informative_phrase(phrase))
        for phrase in ("데이터 센터", "회생 제동", "품질 향상"):
            self.assertTrue(_is_informative_phrase(phrase))
        self.assertFalse(_is_informative_phrase("신용 위험"))
        self.assertTrue(_is_informative_phrase("신용 위험", BANK_VOCABULARY))

    def test_new_sector_vocabularies_are_isolated(self) -> None:
        self.assertEqual(set(SECTOR_VOCABULARIES), {
            "KRX_SEMI", "KRX_AUTO", "KRX_HEALTH", "KRX_STEEL", "KRX_BANK",
        })
        for code in ("KRX_AUTO", "KRX_HEALTH", "KRX_STEEL", "KRX_BANK"):
            vocabulary = SignalConfig(code).vocabulary
            self.assertIs(vocabulary, SECTOR_VOCABULARIES[code])
            self.assertEqual(_canonical("hbm3", vocabulary), "hbm3")

    def test_noun_phrase_does_not_cross_line_boundary(self) -> None:
        extractor = KeywordExtractor([])
        tokens = [
            SimpleNamespace(form="가나다", tag="NNG", start=0, len=3),
            SimpleNamespace(form="라마바", tag="NNG", start=4, len=3),
        ]
        extractor.kiwi = SimpleNamespace(tokenize=lambda texts: [tokens for _ in texts])
        separated, joined = extractor.extract_many(["가나다\n라마바", "가나다 라마바"])
        self.assertNotIn("가나다 라마바", separated)
        self.assertIn("가나다 라마바", joined)

    def test_short_english_requires_sector_protection(self) -> None:
        found = KeywordExtractor([], vocabulary=AUTOMOBILE_VOCABULARY).extract_many(
            ["IT EU US EV HEV PE"]
        )[0]
        self.assertTrue({"EV", "HEV", "PE"}.issubset(found))
        self.assertTrue({"IT", "EU", "US"}.isdisjoint(found))

    def test_phrase_aliases_are_recanonicalized(self) -> None:
        bank = KeywordExtractor([], vocabulary=BANK_VOCABULARY).extract_many(
            ["기업 금융과 신용 위험"]
        )[0]
        self.assertIn("기업금융", bank)
        self.assertIn("신용위험", bank)
        health = KeywordExtractor([], vocabulary=HEALTHCARE_VOCABULARY).extract_many(
            ["미국 FDA와 식품의약품안전처, 후보 물질 및 라이선스 계약"]
        )[0]
        self.assertIn("FDA", health)
        self.assertIn("식품의약품안전처", health)


if __name__ == "__main__":
    unittest.main()
