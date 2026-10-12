"""Company-only chart dates follow active filings, not missing financial values."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from snapdart.ui_project import company_periods,company_revenue_index


class CompanyPeriodTests(unittest.TestCase):
    def test_midyear_first_filing(self):
        repo=SimpleNamespace(documents=Mock(return_value=[
            dict(year=2025,report_type='FY'),dict(year=2024,report_type='H1')]))
        self.assertEqual(company_periods(repo,'295310',[2023,2024,2025]),
                         ['2024 Q2','2024 Q3','2024 Q4','2025 Q1','2025 Q2','2025 Q3','2025 Q4'])
        repo.documents.assert_called_once_with('295310')

    def test_no_filing_in_display_years_has_no_period(self):
        repo=SimpleNamespace(documents=lambda _: [dict(year=2022,report_type='FY')])
        self.assertEqual(company_periods(repo,'c',[2023]),[])

    def test_no_filing_does_not_guess_from_metrics(self):
        repo=SimpleNamespace(documents=lambda _: [])
        self.assertEqual(company_periods(repo,'c',[2023,2024]),[])

    def test_annual_first_filing_starts_at_q4(self):
        repo=SimpleNamespace(documents=lambda _: [dict(year=2024,report_type='FY')])
        self.assertEqual(company_periods(repo,'c',[2023,2024]),['2024 Q4'])

    def test_future_filing_does_not_extend_analysis_years(self):
        repo=SimpleNamespace(documents=lambda _: [dict(year=2026,report_type='Q1')])
        self.assertEqual(company_periods(repo,'c',[2023,2024,2025]),[])

    def test_latest_half_year_stops_at_q2(self):
        repo=SimpleNamespace(documents=lambda _: [dict(year=2023,report_type='Q1'),dict(year=2026,report_type='H1')])
        periods=company_periods(repo,'c',[2023,2024,2025,2026])
        self.assertEqual(periods[-1],'2026 Q2')
        self.assertNotIn('2026 Q3',periods)

    def test_company_index_uses_first_visible_positive_revenue_without_mutation(self):
        rows=[dict(period=p,basis='OFS',revenue=v,metrics=dict(revenue=None,operating=7))
              for p,v in [('2023 Q1',None),('2024 Q1',100),('2024 Q2',200),('2024 Q3',300)]]
        result=company_revenue_index(rows,['2024 Q2','2024 Q3'])
        self.assertEqual(result[2]['metrics']['revenue'],100)
        self.assertEqual(result[3]['metrics']['revenue'],150)
        self.assertEqual(result[3]['indexBasePeriod'],'2024 Q2')
        self.assertEqual(result[3]['metrics']['operating'],7)
        self.assertIsNone(rows[3]['metrics']['revenue'])
        self.assertEqual(result[3]['revenue'],300)

    def test_missing_zero_and_negative_cannot_be_index_base(self):
        rows=[dict(period=f'2024 Q{i+1}',basis='CFS',revenue=v) for i,v in enumerate([None,0,-10,50])]
        result=company_revenue_index(rows,[r['period'] for r in rows])
        self.assertEqual(result[-1]['indexBasePeriod'],'2024 Q4')
        self.assertEqual(result[-1]['metrics']['revenue'],100)
        self.assertEqual(company_revenue_index(rows,[])[-1]['metrics']['revenue'],None)
        self.assertIsNone(company_revenue_index(rows[:-1],[r['period'] for r in rows[:-1]])[0]['indexBasePeriod'])

    def test_basis_mismatch_and_estimated_baseline(self):
        rows=[dict(period='2024 Q1',basis='OFS',revenue=100,estimatedFields={'revenue':'notice'}),
              dict(period='2024 Q2',basis='OFS',revenue=200),dict(period='2024 Q3',basis='CFS',revenue=300)]
        result=company_revenue_index(rows,[r['period'] for r in rows])
        self.assertIn('revenue',result[1]['estimatedMetrics'])
        self.assertIsNone(result[2]['metrics']['revenue'])

    def test_bank_uses_net_interest_income_and_preserves_other_metrics(self):
        rows=[dict(period='2024 Q1',basis='CFS',netInterestIncome=50,metrics={'operating':4}),
              dict(period='2024 Q2',basis='CFS',netInterestIncome=75,metrics={'operating':5})]
        result=company_revenue_index(rows,[r['period'] for r in rows],bank=True)
        self.assertEqual(result[1]['metrics'],{'operating':5,'revenue':150})
