"""Regression checks for the frozen company scorer's context-diversity axis."""

import unittest

import pandas as pd

from dart_remote.dart_company_signal_wordcloud import (
    _context_signature,
    _score_context_diversity,
)
from dart_remote.signal_keyword_rules import GENERIC_VOCABULARY


class CompanyContextDiversityTests(unittest.TestCase):
    def test_context_signature_normalizes_display_variants(self) -> None:
        left = _context_signature("HBM과 TC-BONDER 5 출시", "TC BONDER", GENERIC_VOCABULARY)
        right = _context_signature("hbm과 tc bonder 6 출시", "TC BONDER", GENERIC_VOCABULARY)
        self.assertEqual(left, right)

    def test_short_english_keyword_does_not_match_inside_another_word(self) -> None:
        signature = _context_signature(
            "CAPEX increased; AP processor launched", "AP", GENERIC_VOCABULARY,
        )
        self.assertEqual(signature, ("ap processor launched",))

    def test_supported_diversity_uses_unique_chunks_and_canonical_cooccurrence(self) -> None:
        frame = pd.DataFrame([
            {"keyword": "HBM", "count_2025": 2, "current_score": 80.0,
             "change_score": 60.0, "generic_business_penalty": 0.0},
            {"keyword": "TC BONDER", "count_2025": 1, "current_score": 40.0,
             "change_score": 50.0, "generic_business_penalty": 0.0},
            {"keyword": "TC-Bonder", "count_2025": 1, "current_score": 40.0,
             "change_score": 50.0, "generic_business_penalty": 0.0},
        ])
        candidate_chunks = {"HBM": {1, 2}, "TC BONDER": {1}, "TC-Bonder": {2}}
        chunk_candidates = {1: {"HBM", "TC BONDER"}, 2: {"HBM", "TC-Bonder"}}
        texts = {1: "HBM과 TC-BONDER 5 출시", 2: "hbm과 tc bonder 6 출시"}
        result = _score_context_diversity(
            frame, candidate_chunks, chunk_candidates, texts, GENERIC_VOCABULARY, 2025,
        ).set_index("keyword")
        row = result.loc["HBM"]
        self.assertEqual(row.context_count, 2)
        self.assertAlmostEqual(row.c2_context_novelty, 0.5)
        self.assertAlmostEqual(row.c3_cooccurrence_novelty, 0.5)
        self.assertAlmostEqual(row.diversity_raw, 0.5)
        self.assertAlmostEqual(row.diversity_support, 0.2)
        self.assertAlmostEqual(row.adjusted_diversity_raw, 0.1)
        self.assertAlmostEqual(
            row.final_signal_score,
            0.5 * row.current_score + 0.3 * row.change_score + 0.2 * row.diversity_score,
        )

    def test_count_mismatch_stops_scoring(self) -> None:
        frame = pd.DataFrame([{"keyword": "HBM", "count_2025": 3,
                               "current_score": 80.0, "change_score": 60.0,
                               "generic_business_penalty": 0.0}])
        with self.assertRaisesRegex(ValueError, "Context count mismatch"):
            _score_context_diversity(
                frame, {"HBM": {1, 2}}, {1: {"HBM"}, 2: {"HBM"}},
                {1: "HBM", 2: "HBM"}, GENERIC_VOCABULARY, 2025,
            )


if __name__ == "__main__":
    unittest.main()
