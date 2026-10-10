"""Regression checks for company corpus/config and percentile preparation."""

import unittest

import pandas as pd

from dart_remote.dart_company_signal_wordcloud import (
    COMPANY_HOT_SCORE_THRESHOLD,
    CompanyCandidateExtractorV2,
    CompanySignalConfig,
    company_wordcloud_items,
    _inside_person_name_list,
    _looks_like_entity_name,
    _result_from_counts,
)
from dart_remote.dart_signal_wordcloud import HOT_SCORE_THRESHOLD
from dart_remote.signal_keyword_rules import GENERIC_VOCABULARY, SEMICONDUCTOR_VOCABULARY


class CompanySignalTests(unittest.TestCase):
    def test_company_hot_threshold_is_independent_of_sector_threshold(self) -> None:
        self.assertEqual(COMPANY_HOT_SCORE_THRESHOLD, 97.5)
        self.assertEqual(HOT_SCORE_THRESHOLD, 90.0)

    def test_count_filter_and_percentile_stage(self) -> None:
        config = CompanySignalConfig("00000000", vocabulary=GENERIC_VOCABULARY)
        counts = {
            "제품 수요": {2023: 1, 2024: 2, 2025: 3},
            "신규 기술": {2025: 2},
        }
        totals = pd.Series({2023: 10, 2024: 10, 2025: 10})
        result = _result_from_counts(counts, totals, config)
        by_keyword = result.set_index("keyword")

        self.assertEqual(set(by_keyword.index), set(counts))
        self.assertNotIn("report_spread_score", result)
        self.assertNotIn("signal_score", result)
        self.assertAlmostEqual(by_keyword.loc["제품 수요", "current_raw"], 0.3)
        self.assertAlmostEqual(by_keyword.loc["제품 수요", "change_raw"], 0.1)
        self.assertNotIn("company_count", result)
        self.assertNotIn("concentration_penalty", result)
        for row in result.itertuples(index=False):
            self.assertEqual(row.is_hot, row.change_score >= 97.5 and row.change_raw > 0)

    def test_missing_full_year_uses_only_available_consecutive_change(self) -> None:
        config = CompanySignalConfig("00000000", vocabulary=GENERIC_VOCABULARY)
        counts = {
            "제품 수요": {2024: 2, 2025: 5},
            "신규 기술": {2024: 1, 2025: 2},
        }
        totals = pd.Series({2023: 0, 2024: 10, 2025: 10})

        result = _result_from_counts(counts, totals, config).set_index("keyword")

        self.assertTrue(result["count_2023"].isna().all())
        self.assertTrue(result["rate_2023"].isna().all())
        self.assertAlmostEqual(result.loc["제품 수요", "change_raw"], 0.3)
        self.assertAlmostEqual(result.loc["신규 기술", "change_raw"], 0.1)

    def test_company_wordcloud_serializer_matches_ui_contract(self) -> None:
        top = pd.DataFrame([{
            "keyword": "HBM",
            "final_signal_score": 88.5,
            "display_weight": 100.0,
            "is_hot": True,
            "approval_reason": "configured technical acronym",
        }])

        items = company_wordcloud_items(
            top,
            disclosure_contexts={"HBM": "고대역폭 메모리 수요가 증가했습니다."},
            source_urls={"HBM": "https://dart.fss.or.kr/example"},
        )

        self.assertEqual(set(items[0]), {
            "keyword", "display_weight", "is_hot", "final_signal_score",
            "disclosureContext", "selectionReason", "sourceUrl",
        })
        self.assertEqual(items[0]["selectionReason"], "configured technical acronym")
        self.assertTrue(items[0]["is_hot"])

    def test_sector_vocabulary_is_explicitly_selected(self) -> None:
        self.assertIs(CompanySignalConfig("00000000").vocabulary, GENERIC_VOCABULARY)
        self.assertIs(
            CompanySignalConfig("00000000", sector_index_code="KRX_SEMI").vocabulary,
            SEMICONDUCTOR_VOCABULARY,
        )
        with self.assertRaises(ValueError):
            CompanySignalConfig("00000000", sector_index_code="KRX_UNKNOWN")

    def test_entity_and_person_list_promotions_are_structurally_rejected(self) -> None:
        for phrase in ("Example Holdings", "Example Bank USA", "Example JV LLC", "Brose SE"):
            self.assertTrue(_looks_like_entity_name(phrase))
        self.assertFalse(_looks_like_entity_name("Micro RGB"))
        names = "Fan C, Quyang P, Timur AA, He P, You SA, David DJ"
        start = names.index("Timur")
        self.assertTrue(_inside_person_name_list(names, start, start + len("Timur AA")))
        names = "Chung H-S, Lee S, Park SJ (2016)"
        start = names.index("Park")
        self.assertTrue(_inside_person_name_list(names, start, start + len("Park SJ")))
        names = "HJ Lee, KH Park, SJ Kim"
        start = names.index("HJ Lee")
        self.assertTrue(_inside_person_name_list(names, start, start + len("HJ Lee")))
        self.assertFalse(_inside_person_name_list("One UI platform", 0, len("One UI")))

    def test_generic_role_pairs_and_company_fragments_are_rejected(self) -> None:
        extractor = CompanyCandidateExtractorV2(["HL만도"], GENERIC_VOCABULARY)
        for left, right in (
            ("인식", "고객"), ("보유", "고객"), ("개발", "능력"),
            ("부가", "공정"), ("손익", "공정"), ("자산", "투자"),
            ("자산", "수요"), ("미국", "소재"), ("글로벌", "부품"),
            ("연구", "센터"), ("모델", "솔루션"),
            ("기반", "고객"), ("신규", "투자"), ("기존", "투자"),
            ("건설", "투자"), ("설계", "솔루션"), ("토탈", "솔루션"),
        ):
            self.assertIsNone(extractor._phrase_category(left, right))
        for left, right in (
            ("생산", "공정"), ("회수", "공정"), ("핵심", "부품"),
            ("전지", "소재"),
        ):
            self.assertIsNotNone(extractor._phrase_category(left, right))
        self.assertFalse(extractor._accept("HL"))
        self.assertFalse(extractor._accept("K-IFRS"))
        self.assertFalse(extractor._accept("TOP"))


if __name__ == "__main__":
    unittest.main()
