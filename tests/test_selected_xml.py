import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tests.test_receipt_validation import raw,metric
from tests.test_xml_financials import xml
from dart_remote.receipt_validation import reconcile,replacement,Unverified
from dart_remote.repository import Repository
from dart_remote.xml_financials import extract_facts
from dart_remote.graph_metrics import calculate

class SelectedXMLTests(unittest.TestCase):
    def documents(self,payload):return [(payload,dict(document_id='selected-doc',sha256='sha',origin='mysql'))]

    def test_bank_uses_changed_selected_value_without_old_receipt(self):
        row=metric();before=dict(row)
        with patch('dart_remote.receipt_validation.documents',return_value=self.documents(raw(value='1,100'))) as read,patch('dart_remote.receipt_validation.artifacts.put_artifact'):
            result=reconcile([row],'v')[0]
        self.assertEqual(result['value'],1100000000)
        self.assertTrue(result['estimated']);self.assertEqual(result['source_rcept_no'],row['active_rcept_no'])
        self.assertEqual(result['previous_receipt'],row['source_rcept_no']);self.assertEqual(row,before)
        read.assert_called_once_with(row['active_rcept_no'],'v')

    def test_wrong_identity_unit_and_conflicts_remain_missing(self):
        for payload in (raw(corp='00000000'),raw(unit='USD'),raw(context='CFY2024dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember')):
            with patch('dart_remote.receipt_validation.documents',return_value=self.documents(payload)),patch('dart_remote.receipt_validation.artifacts.put_artifact'):
                self.assertEqual(reconcile([metric()],'v'),[])
        with patch('dart_remote.receipt_validation.documents',return_value=self.documents(raw())+self.documents(raw(value='999'))):
            with self.assertRaises(Unverified):replacement(metric(),'v',[])

    def test_q4_recomputed_from_selected_annual_and_q3(self):
        row=metric(value_type='quarterly',value=1)
        prior=metric(report_type='Q3',value_type='cumulative',source_rcept_no='20251114000001',active_rcept_no='20251114000001')
        def docs(receipt,version):
            payload=raw(value='900',context='CFY2025dTQA_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember').replace(b'11011',b'11013') if receipt==prior['active_rcept_no'] else raw(value='1,100')
            return self.documents(payload)
        with patch('dart_remote.receipt_validation.documents',side_effect=docs):
            result=replacement(row,'v',[prior])
            self.assertEqual(result['value'],200000000);self.assertEqual(result['source_values'],{'FY':1100000000,'Q3':900000000})
            with self.assertRaises(Unverified):replacement(row,'v',[])

    def test_ordinary_report_replaces_wrong_receipt_but_never_reuses_failed_cell(self):
        repo=Repository(SimpleNamespace(membership_code='test'))
        old=dict(sj_div='IS',currency='KRW',standard_account_nm='매출액',value=999,rcept_no='old',active_rcept_no='selected')
        extracted=extract_facts(xml(),2024,'FY','CFS','annual','selected','doc')
        with patch.object(repo,'facts',return_value=[old]),patch('dart_remote.xml_financials.load',return_value=(extracted,'XML')):
            result=repo.financial('A',2024)
        self.assertEqual(result['revenue'],1200000000);self.assertTrue(result['financial_sources']['revenue'][0]['estimated'])
        with patch.object(repo,'facts',return_value=[old]),patch('dart_remote.xml_financials.load',return_value=([],'XML unavailable')):
            self.assertIsNone(repo.financial('A',2024)['revenue'])

    def test_estimation_propagates_from_previous_balance_and_baseline(self):
        rows=[dict(period='2024 Q4',basis='CFS',netIncome=10,netInterestIncome=20,equity=100,assets=200,loans=100,creditLoss=1,estimatedFields={'equity':'warning','netInterestIncome':'warning'}),
              dict(period='2025 Q1',basis='CFS',netIncome=10,netInterestIncome=25,equity=100,assets=200,loans=100,creditLoss=1)]
        output=calculate(rows,bank=True,baseline_period='2024 Q4')[1]
        self.assertIn('revenue',output['estimatedMetrics']);self.assertIn('operating',output['estimatedMetrics'])
        self.assertNotIn('capex',output['estimatedMetrics'])

if __name__=='__main__':unittest.main()
