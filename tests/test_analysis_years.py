import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dart_remote.repository import Repository


class AnalysisYearTests(unittest.TestCase):
    def setUp(self):
        self.repo=Repository(SimpleNamespace(membership_code='KRX_SEMI',name='반도체',data_version='latest:members'))

    def test_default_uses_all_available_years(self):
        with patch.object(self.repo,'years',return_value=[2022,2023,2024,2025]):
            self.assertEqual(self.repo.analysis_years(),[2022,2023,2024,2025])

    def test_missing_requested_year_explains_available_years(self):
        with patch.object(self.repo,'years',return_value=[2023,2024,2025]):
            with self.assertRaisesRegex(ValueError,'사용 가능한 연도'):
                self.repo.analysis_years([2022])

    def test_version_mismatch_does_not_fall_back_to_other_snapshot(self):
        with patch.object(self.repo,'years',return_value=[]),patch.object(self.repo,'_scope',return_value=('1=1',{})),patch('dart_remote.repository.db.rows',return_value=[dict(data_version='pending')]):
            with self.assertRaisesRegex(ValueError,'현재 버전 latest.*존재하는 버전: pending'):
                self.repo.analysis_years()
