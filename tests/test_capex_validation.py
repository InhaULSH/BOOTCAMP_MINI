import unittest
from dart_remote.capex_validation import resolve,verified_financial
from dart_remote.keyword_fallback import result
from dart_remote.generation import generate_all
from types import SimpleNamespace
from unittest.mock import patch

def fact(t,value,kind='cumulative',**extra):
    end={'Q1':'03-31','H1':'06-30','Q3':'09-30','FY':'12-31'}[t]
    row=dict(value=value,fs_div='CFS',currency='KRW',rcept_no=t,active_rcept_no=t,
        period_start='2023-01-01',period_end='2023-'+end,review_required=0,
        source_account_ids='["ppe_purchase"]',data_version='v1',is_calculated=0)
    row.update(extra)
    return (value,[row])

class CapexTests(unittest.TestCase):
    def resolve(self,entries,q=2):
        return resolve(lambda t,k:entries.get((t,k),(None,[])),2023,'CFS',q)
    def entries(self):
        return {('Q1','cumulative'):fact('Q1',10),('H1','cumulative'):fact('H1',25)}
    def test_valid_difference(self):
        value,sources,method,proof=self.resolve(self.entries())
        self.assertEqual(value,15);self.assertEqual(proof['status'],'verified');self.assertEqual(len(sources),2)
    def test_negative_hlb_difference_preserved(self):
        entries={('Q1','cumulative'):fact('Q1',6163192619),('H1','cumulative'):fact('H1',3576017207)}
        value,_,_,proof=self.resolve(entries)
        self.assertIsNone(value);self.assertEqual(proof['candidate'],-2587175412)
        self.assertIn('negative_difference',proof['reasons'])
    def test_calculated_positive_quarter_does_not_override_bad_inputs(self):
        entries=self.entries();entries[('H1','quarterly')]=fact('H1',999,is_calculated=1)
        entries[('H1','cumulative')]=fact('H1',25,review_required=1)
        self.assertIsNone(self.resolve(entries)[0])
    def test_period_receipt_definition_review_fail_closed(self):
        for change in [dict(period_start='2023-04-01'),dict(active_rcept_no='correction'),
                       dict(source_account_ids='["disposal"]'),dict(review_required=1),dict(currency='USD')]:
            with self.subTest(change=change):
                entries=self.entries();entries[('H1','cumulative')]=fact('H1',25,**change)
                self.assertIsNone(self.resolve(entries)[0])
    def test_cashflow_negative_sign_does_not_become_negative_outlay(self):
        entries=self.entries();entries[('Q1','cumulative')]=fact('Q1',10,signed_normalized_value=-10,sign_normalized=1)
        self.assertEqual(self.resolve(entries)[0],15)
    def test_direct_three_month_report_is_accepted(self):
        entries={('H1','quarterly'):fact('H1',7,period_start='2023-04-01')}
        self.assertEqual(self.resolve(entries)[0],7)
    def test_annual_reconstruction_requires_all_verified_quarters(self):
        entries={('FY','annual'):fact('FY',100),
            ('Q1','quarterly'):fact('Q1',10),
            ('Q3','quarterly'):fact('Q3',30,period_start='2023-07-01'),
            ('FY','quarterly'):fact('FY',40,period_start='2023-10-01')}
        self.assertEqual(self.resolve(entries)[0],20)
        entries[('Q3','quarterly')]=fact('Q3',30,period_start='2023-07-01',review_required=1)
        self.assertIsNone(self.resolve(entries)[0])
    def test_annual_evidence_rejects_unreviewed(self):
        value,sources=fact('FY',10,review_required=1)
        repo=SimpleNamespace(financial=lambda *a,**k:dict(capex=value,financial_sources={'capex':sources}))
        self.assertIsNone(verified_financial(repo,'c',2023)['capex'])
    def test_keyword_errors_are_not_exposed(self):
        for message,expected in [('Gemini HTTP 429 secret','rate_limit'),('Gemini HTTP 403 secret','configuration'),
                                 ('근거 ID 검증 실패 secret','verification'),('근거 부족 secret','insufficient_evidence')]:
            value=result(message);self.assertEqual(value['fallback_reason'],expected)
            self.assertNotIn('secret',value['insufficient_reason'])
    def test_keyword_failure_does_not_discard_valid_industry_insight(self):
        report=dict(years=[2023],companies=[],wordcloud={'2023':[dict(text='HBM')]},citations={},ai_insights={})
        def generate(*a,keyword=None,**k):
            if keyword:raise RuntimeError('Gemini HTTP 429 private')
            return dict(sentences=[dict(text='verified',source_refs=[])])
        with patch.dict('os.environ',{'GEMINI_CONCURRENCY':'1'}):generate_all(report,SimpleNamespace(),generate)
        self.assertTrue(report['ai_insights']['2023']['sentences'])
        self.assertEqual(report['keyword_insights']['2023']['HBM']['fallback_reason'],'rate_limit')

if __name__=='__main__':unittest.main()
