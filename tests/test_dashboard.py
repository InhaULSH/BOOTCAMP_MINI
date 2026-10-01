import unittest
from snapdart.dashboard import weighted, build_view, trend_summary
from snapdart.market import index_from_quotes, market_cap
from snapdart.config import COMPANIES

class DashboardTests(unittest.TestCase):
    def test_weighted_not_simple_average(self):
        self.assertAlmostEqual(weighted({'a':{'x':10},'b':{'x':30}}, {'a':.8,'b':.2}, 'x'),14)
    def test_missing_not_zero_or_reweighted(self):
        self.assertIsNone(weighted({'a':{'x':10},'b':{'x':None}}, {'a':.8,'b':.2}, 'x'))
        self.assertIsNone(weighted({'a':{'x':10}}, {}, 'x'))
    def test_index_base_and_dates(self):
        quotes={c['code']:dict(market_cap=100,history=[{'date':'1','value':20},{'date':'2','value':22}]) for c in COMPANIES}
        x=index_from_quotes(quotes)
        self.assertAlmostEqual(x['history'][0]['value'],100)
        self.assertAlmostEqual(x['change'],10)
        quotes.pop(COMPANIES[0]['code'])
        self.assertEqual(index_from_quotes(quotes)['history'],[])
    def test_cap_units(self):
        self.assertEqual(market_cap('1,234조 5,678억'),1234e12+5678e8)
        self.assertIsNone(market_cap('N/A'))
    def test_fcf_and_no_mutation(self):
        report={'years':[2025],'companies':[{'code':'a','history':[{'year':2025,'revenue':100,'fcf':-20}]}]}
        view=build_view(report,{'index':{'weights':{'a':1}}})
        self.assertEqual(view['weighted_history'][0]['fcf_margin'],-20)
        self.assertNotIn('fcf_margin',report['companies'][0]['history'][0])
    def test_basis_change(self):
        self.assertIn('생략',trend_summary([{'year':2024,'basis':'CFS','margin':10},{'year':2025,'basis':'OFS','margin':20}]))
