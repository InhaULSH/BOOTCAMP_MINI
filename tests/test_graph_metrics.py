import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dart_remote.graph_metrics import calculate,catalog,GraphData,resolve_flow

class GraphMetricTests(unittest.TestCase):
    def test_nonbank_yoy_health_and_signed_fcf(self):
        rows=[dict(period='2024 Q2',basis='CFS',revenue=100),
              dict(period='2025 Q2',basis='CFS',revenue=125,operatingProfit=-10,capex=30,rd=15,operatingCashFlow=20)]
        calculate(rows,health=True)
        self.assertEqual(rows[-1]['metrics'],dict(revenue=125,operating=-8,capex=12,fcf=-8))
        calculate(rows)
        self.assertEqual(rows[-1]['metrics']['capex'],24)
    def test_bank_annualization_average_and_equity_ratio(self):
        rows=[dict(period='2024 Q1',basis='OFS',netInterestIncome=100),
              dict(period='2024 Q4',basis='OFS',equity=100,loans=1000),
              dict(period='2025 Q1',basis='OFS',netInterestIncome=120,netIncome=3,creditLoss=2,equity=140,loans=1200,assets=2000)]
        calculate(rows,bank=True)
        self.assertEqual(rows[-1]['metrics']['revenue'],120)
        self.assertEqual(rows[-1]['metrics']['operating'],10)
        self.assertAlmostEqual(rows[-1]['metrics']['capex'],8/1100*100)
        self.assertAlmostEqual(rows[-1]['metrics']['fcf'],7)
    def test_missing_and_changed_basis_not_imputed(self):
        rows=[dict(period='2024 Q1',basis='CFS',netInterestIncome=100),
              dict(period='2025 Q1',basis='OFS',netInterestIncome=120,netIncome=3,creditLoss=2,equity=140,assets=0)]
        calculate(rows,bank=True)
        self.assertTrue(all(v is None for v in rows[-1]['metrics'].values()))
    def test_four_slots_and_excluded_bank_metrics(self):
        for sector in ('KRX_AUTO','KRX_SEMI','KRX_STEEL','KRX_HEALTH','KRX_BANK'):
            c=catalog(sector);self.assertEqual(list(c),['revenue','operating','capex','fcf'])
            self.assertEqual(c['revenue']['unit'],'지수');self.assertTrue(all(c[k]['unit']=='%' for k in ('operating','capex','fcf')))
        self.assertEqual(catalog('KRX_HEALTH')['capex']['title'],'R&D / 매출액')
        self.assertEqual(catalog('KRX_BANK')['capex']['title'],'대손비용률 proxy')
    def graph(self):
        repo=SimpleNamespace(sector=SimpleNamespace(membership_code='KRX_BANK',data_version='v1:members'),
            _scope=lambda:('corp_code IN (:c0)',dict(c0='corp')),company=lambda _:dict(corp_code='corp'))
        graph=GraphData(repo);graph.profiles={'corp':dict(preferred_fs_div='OFS',comparison_scope='bank_separate')}
        return graph
    def test_bank_contract_requires_approved_receipt_and_currency(self):
        graph=self.graph()
        with patch('dart_remote.graph_metrics.db.rows',return_value=[]) as read:
            self.assertEqual(graph.extras,[])
        sql,params=read.call_args.args
        self.assertIn("review_status='approved'",sql);self.assertIn("unit='KRW'",sql)
        self.assertIn('active_rcept_no',sql);self.assertIn('HAVING COUNT(DISTINCT rcept_no)=1',sql);self.assertEqual(params['v'],'v1')
    def test_bank_scope_and_basis_not_mixed(self):
        graph=self.graph();base=dict(corp_code='corp',year=2025,report_type='Q1',metric_code='NET_INCOME',value_type='quarterly')
        graph.extras=[dict(base,fs_div='CFS',scope='holding_consolidated',value=99),dict(base,fs_div='OFS',scope='bank_separate',value=2)]
        self.assertEqual(graph.flow('code',2025,1,'OFS','NET_INCOME')[0],2)
    def test_missing_quarter_rebuilt_only_from_unambiguous_cumulative(self):
        graph=self.graph();base=dict(corp_code='corp',year=2025,metric_code='NET_INCOME',value_type='cumulative',fs_div='OFS',scope='bank_separate')
        graph.extras=[dict(base,report_type='Q1',value=2),dict(base,report_type='H1',value=5)]
        self.assertEqual(graph.flow('code',2025,2,'OFS','NET_INCOME')[0],3)
        graph.extras.append(dict(base,report_type='H1',value=7))
        self.assertIsNone(graph.flow('code',2025,2,'OFS','NET_INCOME')[0])

    def test_baseline_fixed_and_shared_period(self):
        for initial,current,wanted in [(1,1.2,120),(100,90,90),(1000,1100,110)]:
            rows=[dict(period='2022 Q1',basis='CFS',revenue=999),dict(period='2023 Q1',basis='CFS',revenue=initial),dict(period='2023 Q2',basis='CFS',revenue=current)]
            calculate(rows,baseline_period='2023 Q1')
            self.assertEqual(rows[1]['metrics']['revenue'],100)
            self.assertAlmostEqual(rows[2]['metrics']['revenue'],wanted)
        rows=[dict(period='2023 Q1',basis='CFS',revenue=None),dict(period='2023 Q2',basis='CFS',revenue=50)]
        calculate(rows);self.assertIsNone(rows[1]['metrics']['revenue'])
    def test_annual_reconstruction_preserves_inputs(self):
        entries={('FY','annual'):(119920030662,[{'id':'annual'}]),('Q3','cumulative'):(91626482558,[{'id':'q3'}])}
        read=lambda t,k:entries.get((t,k),(None,[]))
        value,sources,method=resolve_flow(read,4)
        self.assertEqual(value,28293548104);self.assertEqual(len(sources),2);self.assertIsNotNone(method)
    def test_annual_minus_three_quarters_and_direct_priority(self):
        entries={('FY','annual'):(100,[]),('Q1','quarterly'):(10,[]),('Q3','quarterly'):(30,[]),('FY','quarterly'):(40,[])}
        read=lambda t,k:entries.get((t,k),(None,[]))
        self.assertEqual(resolve_flow(read,2)[0],20)
        entries[('H1','quarterly')]=(25,[])
        self.assertEqual(resolve_flow(read,2),(25,[],None))
        del entries[('Q3','quarterly')];del entries[('H1','quarterly')]
        self.assertIsNone(resolve_flow(read,2)[0])

    def test_cumulative_subtracts_known_quarters_when_prior_total_missing(self):
        entries={('Q1','quarterly'):(10,[{'id':'q1'}]),('H1','cumulative'):(25,[{'id':'h1'}])}
        value,sources,method=resolve_flow(lambda t,k:entries.get((t,k),(None,[])),2)
        self.assertEqual(value,15);self.assertEqual(len(sources),2)
    def test_zero_baseline_never_rebased(self):
        rows=[dict(period='2023 Q1',basis='CFS',revenue=0),dict(period='2023 Q2',basis='CFS',revenue=10)]
        calculate(rows);self.assertTrue(all(r['metrics']['revenue'] is None for r in rows))
