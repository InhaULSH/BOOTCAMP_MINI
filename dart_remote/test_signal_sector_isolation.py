"""Regression checks for sector-neutral candidate extraction."""

import unittest
from types import SimpleNamespace

import pandas as pd

from .dart_signal_wordcloud import (
    KeywordExtractor,
    SignalConfig,
    _canonical,
    _is_candidate,
    _is_informative_phrase,
    score_keywords,
    wordcloud_items,
)
from .signal_keyword_rules import GENERIC_VOCABULARY, SEMICONDUCTOR_VOCABULARY, SectorVocabulary


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


if __name__ == "__main__":
    unittest.main()
