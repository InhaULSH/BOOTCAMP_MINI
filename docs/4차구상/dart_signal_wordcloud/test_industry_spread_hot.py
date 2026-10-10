"""Regression tests for industry spread entropy and UI hot selection."""

import math
import unittest

import pandas as pd

from dart_signal_wordcloud.dart_signal_wordcloud import (
    SignalConfig,
    _result_from_counts,
    apply_industry_hot_flags,
    calculate_entropy_score,
)


class IndustrySpreadTests(unittest.TestCase):
    def test_normalized_entropy_edge_cases(self) -> None:
        totals = {code: 10 for code in "abcde"}
        self.assertAlmostEqual(
            calculate_entropy_score({code: 2 for code in totals}, totals), 100.0
        )
        self.assertAlmostEqual(calculate_entropy_score({"a": 2}, totals), 0.0)
        partial = calculate_entropy_score({"a": 2, "b": 2}, totals)
        self.assertAlmostEqual(partial, math.log(2) / math.log(5) * 100.0)
        self.assertTrue(math.isfinite(partial))
        self.assertEqual(calculate_entropy_score({}, totals), 0.0)
        self.assertEqual(
            calculate_entropy_score({"a": 2}, {code: 0 for code in totals}), 0.0
        )

    def test_spread_is_sixty_percent_coverage_and_forty_percent_entropy(self) -> None:
        config = SignalConfig("KRX_DUMMY", top_n=12)
        counts = {"산업 신호": {2023: 5, 2024: 5, 2025: 5}}
        company_counts = {"산업 신호": {code: 1 for code in "abcde"}}
        company_totals = {code: 10 for code in "abcde"}
        totals = pd.Series({2023: 50, 2024: 50, 2025: 50})
        row = _result_from_counts(
            counts, company_counts, company_totals, totals, config, 5
        ).iloc[0]
        self.assertAlmostEqual(row.company_coverage_score, 100.0)
        self.assertAlmostEqual(row.old_spread_score, 100.0)
        self.assertAlmostEqual(row.entropy_score, 100.0)
        self.assertAlmostEqual(
            row.spread_score,
            0.6 * row.company_coverage_score + 0.4 * row.entropy_score,
        )


class IndustryHotTests(unittest.TestCase):
    @staticmethod
    def frame() -> pd.DataFrame:
        return pd.DataFrame([
            {"keyword": "a", "final_rank": 1, "change_raw": 0.06,
             "change_score": 99.0, "final_signal_score": 90.0},
            {"keyword": "b", "final_rank": 2, "change_raw": 0.05,
             "change_score": 98.0, "final_signal_score": 89.0},
            {"keyword": "c", "final_rank": 3, "change_raw": 0.04,
             "change_score": 97.0, "final_signal_score": 88.0},
            {"keyword": "d", "final_rank": 4, "change_raw": 0.03,
             "change_score": 96.0, "final_signal_score": 87.0},
            {"keyword": "e", "final_rank": 5, "change_raw": 0.02,
             "change_score": 95.0, "final_signal_score": 86.0},
            {"keyword": "outside", "final_rank": 13, "change_raw": 1.0,
             "change_score": 100.0, "final_signal_score": 85.0},
        ])

    def test_only_top_three_qualifying_top12_keywords_are_hot(self) -> None:
        result = apply_industry_hot_flags(self.frame(), 12).set_index("keyword")
        self.assertEqual(set(result.index[result.is_hot]), {"a", "b", "c"})
        self.assertFalse(result.loc["outside", "is_hot"])

    def test_two_or_zero_eligible_keywords_are_not_padded(self) -> None:
        frame = self.frame().head(2)
        self.assertEqual(int(apply_industry_hot_flags(frame, 12).is_hot.sum()), 2)
        frame["change_raw"] = 0.0
        self.assertEqual(int(apply_industry_hot_flags(frame, 12).is_hot.sum()), 0)

    def test_change_raw_and_stable_tie_break_order(self) -> None:
        frame = self.frame().head(4)
        frame.loc[:, "change_raw"] = 0.05
        frame.loc[:, "change_score"] = 99.0
        frame.loc[:, "final_signal_score"] = 90.0
        result = apply_industry_hot_flags(frame, 12).set_index("keyword")
        self.assertEqual(set(result.index[result.is_hot]), {"a", "b", "c"})


if __name__ == "__main__":
    unittest.main()
