"""Regression checks for company corpus/config and percentile preparation."""

import unittest

import pandas as pd

from .dart_company_signal_wordcloud import (
    COMPANY_HOT_SCORE_THRESHOLD,
    MAX_COMPANY_HOT_KEYWORDS,
    ORGANIZATION_ROLE_CONTEXT,
    CompanyCandidateExtractorV2,
    CompanySignalConfig,
    apply_company_hot_flags,
    company_wordcloud_items,
    _english_promotion_forms,
    _inside_person_name_list,
    _looks_like_entity_name,
    _result_from_counts,
)
from .dart_signal_wordcloud import HOT_SCORE_THRESHOLD, generic_noise_categories
from .signal_keyword_rules import (
    GENERIC_VOCABULARY,
    PRODUCTION_GENERIC_NOISE_CATEGORIES,
    SEMICONDUCTOR_VOCABULARY,
)


class CompanySignalTests(unittest.TestCase):
    def test_company_hot_threshold_is_independent_of_sector_threshold(self) -> None:
        self.assertEqual(COMPANY_HOT_SCORE_THRESHOLD, 97.5)
        self.assertEqual(HOT_SCORE_THRESHOLD, 90.0)

    def test_company_hot_is_limited_to_three_top12_candidates(self) -> None:
        rows = pd.DataFrame([
            {
                "keyword": f"K{i}", "final_rank": i,
                "change_raw": float(20 - i), "change_score": 100.0,
                "final_signal_score": float(100 - i),
            }
            for i in range(1, 6)
        ])
        flagged = apply_company_hot_flags(rows, 12)
        self.assertEqual(int(flagged["is_hot"].sum()), MAX_COMPANY_HOT_KEYWORDS)
        self.assertEqual(flagged.loc[flagged["is_hot"], "keyword"].tolist(), ["K1", "K2", "K3"])

    def test_count_filter_and_percentile_stage(self) -> None:
        config = CompanySignalConfig(
            "00000000", years=(2023, 2024, 2025), vocabulary=GENERIC_VOCABULARY
        )
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

    def test_structural_missing_year_uses_only_available_consecutive_change(self) -> None:
        config = CompanySignalConfig(
            "00000000", years=(2023, 2024, 2025), vocabulary=GENERIC_VOCABULARY
        )
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

    def test_2026_change_uses_same_report_periods(self) -> None:
        config = CompanySignalConfig(
            "00000000", years=(2023, 2024, 2025, 2026),
            vocabulary=GENERIC_VOCABULARY,
        )
        counts = {"period signal": {2023: 1, 2024: 2, 2025: 3, 2026: 4}}
        totals = pd.Series({2023: 10, 2024: 10, 2025: 10, 2026: 10})
        period_counts = {
            "period signal": {
                (2025, "FY"): 100,
                (2025, "Q1"): 1, (2025, "H1"): 1,
                (2026, "Q1"): 2, (2026, "H1"): 2,
            }
        }
        period_totals = {
            (2025, "FY"): 100,
            (2025, "Q1"): 5, (2025, "H1"): 5,
            (2026, "Q1"): 5, (2026, "H1"): 5,
        }

        row = _result_from_counts(
            counts, totals, config, period_counts, period_totals, ("Q1", "H1")
        ).iloc[0]

        self.assertAlmostEqual(row.comparable_rate_2025, 0.2)
        self.assertAlmostEqual(row.comparable_rate_2026, 0.4)
        self.assertAlmostEqual(row.change_raw, 0.16)

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

        event = "2025 CEO Investor Day를 해외에서 개최하고 시장과 소통했다."
        start = event.index("CEO")
        self.assertEqual(
            _english_promotion_forms(event, start, start + len("CEO")), set()
        )

        subsidiary = "FUJIFILM Holdings의 자회사인 FUJIFILM Biotechnologies가 생산한다."
        start = subsidiary.index("FUJIFILM Biotechnologies")
        self.assertEqual(
            _english_promotion_forms(
                subsidiary, start, start + len("FUJIFILM Biotechnologies")
            ),
            set(),
        )
        legal_name = "Yingkou PFM Refractories,.Co.Ltd의 지분 51%를 보유한다."
        start = legal_name.index("Yingkou")
        self.assertEqual(
            _english_promotion_forms(legal_name, start, start + len("Yingkou")),
            set(),
        )

    def test_document_patent_and_location_noise_are_hard_exclusions(self) -> None:
        expected = {
            "서식 작성": "공시 메타",
            "기업공시 서식": "공시 메타",
            "기재 예정": "공시 메타",
            "분ㆍ반기": "공시 메타",
            "분석 의견": "공시 메타",
            "USE THEREOF": "특허 법률 문구",
            "COMPRISING SAME": "특허 법률 문구",
            "INHIBITORS AND METHODS": "특허 법률 문구",
            "서울특별시 소재": "문서성 표현",
            "기존 대비": "문서성 표현",
            "기저 효과": "문서성 표현",
        }
        for keyword, category in expected.items():
            self.assertIn(category, generic_noise_categories(keyword))
            self.assertIn(category, PRODUCTION_GENERIC_NOISE_CATEGORIES)

    def test_legal_name_aliases_are_learned_without_company_blacklists(self) -> None:
        extractor = CompanyCandidateExtractorV2(["Example Parent"], GENERIC_VOCABULARY)
        extractor.register_entity_aliases([
            "Immunomic Therapeutics, Inc.의 연구 현황",
            "Yingkou PFM Refractories,.Co.Ltd의 지분 현황",
        ])
        self.assertFalse(extractor._accept("IMMUNOMIC THERAPEUTICS"))
        self.assertFalse(extractor._accept("YINGKOU PFM REFRACTORIES"))
        self.assertTrue(extractor._accept("TC BONDER"))

    def test_generic_role_pairs_and_company_fragments_are_rejected(self) -> None:
        extractor = CompanyCandidateExtractorV2(["HL만도"], GENERIC_VOCABULARY)
        for left, right in (
            ("인식", "고객"), ("보유", "고객"), ("개발", "능력"),
            ("부가", "공정"), ("손익", "공정"), ("자산", "투자"),
            ("자산", "수요"), ("미국", "소재"), ("글로벌", "부품"),
            ("연구", "센터"), ("모델", "솔루션"),
            ("기반", "고객"), ("신규", "투자"), ("기존", "투자"),
            ("건설", "투자"), ("설계", "솔루션"), ("토탈", "솔루션"),
            ("기반", "서버"),
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
        self.assertIsNotNone(ORGANIZATION_ROLE_CONTEXT.search(" PM센터장"))
        self.assertIsNotNone(ORGANIZATION_ROLE_CONTEXT.search("설계센터장"))
        self.assertIsNotNone(ORGANIZATION_ROLE_CONTEXT.search("설계센터"))


if __name__ == "__main__":
    unittest.main()
