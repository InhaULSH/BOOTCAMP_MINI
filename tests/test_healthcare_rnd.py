"""R&D document totals must not mix with income-statement expense series."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dart_remote.graph_metrics import GraphData
from dart_remote.receipt_validation import Unverified


def note(report='Q1',kind='quarterly',value=10,**changes):
    return dict(dict(corp_code='corp',year=2025,report_type=report,value_type=kind,
        metric_code='RND_EXPENSE',fs_div='CFS',scope='consolidated',unit='KRW',
        review_status='approved',value=value,source_rcept_no='receipt',active_rcept_no='receipt',
        source_document_id='document',source_account_name='연구개발비용 합계'),**changes)


def legacy(report='Q1',kind='quarterly',value=999,**changes):
    return dict(dict(corp_code='corp',year=2025,report_type=report,value_type=kind,
        fs_div='CFS',value=value,account_id='dart_OrdinaryDevelopmentExpense',
        original_account_nm='연구개발비',rcept_no='receipt',active_rcept_no='receipt'),**changes)


class HealthcareRndTests(unittest.TestCase):
    def graph(self,primary,old=()):
        repo=SimpleNamespace(sector=SimpleNamespace(membership_code='KRX_HEALTH',data_version='v12:members'),
            _scope=lambda:('corp_code IN (:c0)',dict(c0='corp')),company=lambda _:dict(corp_code='corp'))
        graph=GraphData(repo)
        with patch('dart_remote.graph_metrics.db.rows',side_effect=[primary,list(old)]) as read:
            graph.extras
        self.assertIn("m.metric_code='RND_EXPENSE'",read.call_args_list[0].args[0])
        self.assertIn('HAVING COUNT(DISTINCT rcept_no)=1',read.call_args_list[0].args[0])
        self.assertEqual(read.call_args_list[0].args[1]['v'],'v12')
        return graph

    def test_document_total_priority_quarter_derivation_and_provenance(self):
        graph=self.graph([note(),note('H1','cumulative',25),note('Q3','cumulative',40),note('FY','annual',60)],
                         [legacy(),legacy('H1','quarterly',999)])
        quarters=[graph.flow('stock',2025,q,'CFS','RD') for q in range(1,5)]
        self.assertEqual([v for v,_ in quarters],[10,15,15,20])
        self.assertEqual(quarters[3][1][0]['derivation'],'누적값 차감')
        self.assertEqual({s['report_type'] for s in quarters[3][1]},{'FY','Q3'})
        self.assertTrue(all(s['source_document_id']=='document' for _,sources in quarters for s in sources))
        self.assertTrue(all(s['metric_code']=='RND_EXPENSE' for s in graph.extras))

    def test_missing_primary_period_never_uses_legacy_expense(self):
        graph=self.graph([note()], [legacy('H1',value=25),legacy(year=2024,value=8)])
        self.assertIsNone(graph.flow('stock',2025,2,'CFS','RD')[0])
        self.assertEqual(graph.flow('stock',2024,1,'CFS','RD')[0],8)

    def test_legacy_supported_when_document_total_absent(self):
        graph=self.graph([], [legacy(value=7)])
        value,sources=graph.flow('stock',2025,1,'CFS','RD')
        self.assertEqual(value,7)
        self.assertEqual(sources[0]['metric_code'],'RD')

    def test_invalid_primary_blocks_different_definition_fallback(self):
        for changes in [dict(review_status='pending'),dict(unit='USD'),dict(scope='unknown'),
                        dict(active_rcept_no=None),dict(value=float('nan')),dict(value=-1)]:
            with self.subTest(changes=changes):
                graph=self.graph([note(**changes)],[legacy(value=7)])
                self.assertIsNone(graph.flow('stock',2025,1,'CFS','RD')[0])

    def test_receipt_mismatch_cannot_revive_legacy_expense(self):
        with (patch('dart_remote.receipt_validation.replacement',side_effect=Unverified('unverified')),
              patch('dart_remote.receipt_validation.artifacts.put_artifact'),
              self.assertLogs('dart_remote.receipt_validation',level='WARNING')):
            graph=self.graph([note(source_rcept_no='old')],[legacy(value=7)])
        self.assertIsNone(graph.flow('stock',2025,1,'CFS','RD')[0])

    def test_conflicts_and_basis_are_kept_separate(self):
        graph=self.graph([note(),note(value=11),note(value=5,fs_div='OFS',scope='separate')])
        self.assertIsNone(graph.flow('stock',2025,1,'CFS','RD')[0])
        self.assertEqual(graph.flow('stock',2025,1,'OFS','RD')[0],5)

    def test_ratio_rows_cannot_be_used_as_currency_amounts(self):
        graph=self.graph([])
        graph.extras=[note(metric_code='RND_TO_REVENUE',value=500)]
        self.assertIsNone(graph.flow('stock',2025,1,'CFS','RD')[0])

    def test_negative_document_total_difference_is_not_a_valid_quarter(self):
        graph=self.graph([note('Q3','cumulative',342900000000),note('FY','annual',167400000000)])
        self.assertEqual(graph.flow('stock',2025,4,'CFS','RD'),(None,[]))
        graph=self.graph([note('Q3','cumulative',60),note('FY','annual',60)])
        self.assertEqual(graph.flow('stock',2025,4,'CFS','RD')[0],0)

    def test_graph_ratio_uses_quarter_amount_and_keeps_fcf_definition(self):
        graph=self.graph([note(),note('H1','cumulative',25),note('Q3','cumulative',40),note('FY','annual',60)])
        def ordinary(*_):
            return [dict(period=f'2025 Q{q}',basis='CFS',revenue=100,operatingProfit=20,
                         operatingCashFlow=10,capex=5) for q in range(1,5)]
        rows=graph.rows(dict(code='stock'),[2025],ordinary)
        self.assertEqual([r['metrics']['capex'] for r in rows],[10,15,15,20])
        self.assertTrue(all(r['metrics']['fcf']==5 for r in rows))
        self.assertTrue(all(s['source_document_id']=='document' for r in rows for s in r['rdSources']))
