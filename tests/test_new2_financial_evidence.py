"""Financial claims are internally checked; UI citations stay filing-only."""
import os
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dart_remote import financial_evidence as facts, citation_selection_new2 as selection

@patch.dict(os.environ, {'INSIGHT_VALIDATION_MODE': 'strict'})
class FinancialEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence=[dict(id='t1',kind='filing',year=2025,company='기업가',passages=[
            dict(id='t1-p1',text='AI 서버의 수요에 대응하여 생산능력 확대를 계획하고 있습니다.',start=0,end=36)])]
        self.refs={};self.citations={}
        self.rows=[dict(year=y,basis='CFS',revenue=r,operating_income=p,capex=None,operating_cashflow=None,
            financial_sources={k:[dict(rcept_no=str(y),original_account_nm=k)] for k in ('revenue','operating_income')})
            for y,r,p in ((2024,10000000000,1000000000),(2025,12000000000,1440000000))]
        self.repo=SimpleNamespace(sector=SimpleNamespace(id='test'),financial=lambda code,y,t,**kw:
            dict(year=y,report_type=t,basis=None,revenue=None,operating_income=None,capex=None,operating_cashflow=None,financial_sources={}))
        self.prepare()
    def prepare(self):
        return facts.prepare(self.repo,[dict(code='000001',name='기업가',history=self.rows)],[2024,2025],self.evidence,self.refs,self.citations)
    def fact(self,metric,year):
        return next(e for e in self.evidence if e.get('metric')==metric and e['year']==year)
    def value(self,text,ids,filing=True):
        assessment=dict(id='t1',grades=dict(F=4,U=4,C=4,T=4),suitable=True,reason='공시 직접 근거',
            irrelevant_content='none',redundancy='none',passage_ids=['t1-p1'])
        sentences=[dict(text=text,refs=ids,assessments=[])]
        if filing:sentences.append(dict(text='생산능력 확대를 계획하고 있습니다.',refs=['t1'],assessments=[assessment]))
        return dict(sentences=sentences,insufficient_reason='')
    def validate(self,v):return selection.validate(copy.deepcopy(v),self.evidence,1,3)
    def test_absolute_money_and_separate_financial_sentence(self):
        f=self.fact('revenue',2025)
        v=self.validate(self.value('2025년 연간 매출액은 120억원입니다.',[f['id']]))
        self.assertEqual(v['sentences'][0]['assessments'],[])
    def test_comparison_and_percentage_point_are_calculated_by_code(self):
        for metric,text,expected in (('revenue','매출액은 전년 대비 20% 증가했습니다.',20),
                                     ('margin','영업이익률은 전년 대비 2%p 높아졌습니다.',2)):
            f=self.fact(metric,2025);previous=self.fact(metric,2024)
            self.validate(self.value(text,[f['id'],previous['id']]))
            self.assertAlmostEqual(f['comparison']['growth_pct' if metric=='revenue' else 'difference_pp'],expected)
    def test_wrong_money_percent_company_and_year_rejected(self):
        f=self.fact('revenue',2025);p=self.fact('revenue',2024)
        for text in ('2025년 매출액은 130억원입니다.','2024년 매출액은 120억원입니다.',
                     '매출액은 전년 대비 30% 증가했습니다.'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.validate(self.value(text,[f['id'],p['id']]))
        # Numeric filing text cannot substitute for the financial reference.
        with self.assertRaises(ValueError):self.validate(self.value('2025년 매출액은 120억원입니다.',[p['id']]))
    def test_missing_comparison_ref_is_linked_after_validation(self):
        f=self.fact('revenue',2025)
        result=self.validate(self.value('매출액은 20% 증가했습니다.',[f['id']]))
        sentence=result['sentences'][0]
        self.assertIn(f['comparison']['ref'],sentence['refs'])
        self.assertEqual(sentence['llm_refs'],[f['id']])
        self.assertEqual(sentence['auto_linked_financial_refs'][0]['current_ref'],f['id'])
    def test_no_fabricated_growth_from_negative_base(self):
        f=self.fact('operating_income',2025);p=self.fact('operating_income',2024)
        p['values']['operating_income']=-1000000000
        f['comparison']['growth_pct']=None
        with self.assertRaises(ValueError):self.validate(self.value('영업이익은 44% 증가했습니다.',[f['id'],p['id']]))
    def test_financial_reference_cannot_be_assessed_as_prose(self):
        f=self.fact('revenue',2025);v=self.value('2025년 매출액은 120억원입니다.',[f['id']])
        v['sentences'][0]['assessments']=[dict(v['sentences'][1]['assessments'][0],id=f['id'])]
        with self.assertRaisesRegex(ValueError,'assessments'):self.validate(v)
    def test_both_types_required_but_empty_reason_is_valid(self):
        f=self.fact('revenue',2025)
        with self.assertRaisesRegex(ValueError,'모두'):self.validate(self.value('2025년 매출액은 120억원입니다.',[f['id']],False))
        self.validate(dict(sentences=[],insufficient_reason='의미 있는 두 종류의 근거가 부족합니다.'))
    def test_estimation_label_required(self):
        f=self.fact('revenue',2025);f['estimated']=True
        with self.assertRaisesRegex(ValueError,'추정'):self.validate(self.value('2025년 매출액은 120억원입니다.',[f['id']]))
        self.validate(self.value('2025년 매출액은 (추정) 120억원입니다.',[f['id']]))
    def test_unproven_or_nonfinite_values_do_not_enter_input(self):
        self.evidence=self.evidence[:1];self.rows[1]['revenue']=float('inf');self.rows[0]['financial_sources']={}
        self.prepare()
        self.assertFalse(any(e.get('metric')=='revenue' for e in self.evidence))
    def test_wrong_basis_or_report_cannot_be_compared(self):
        self.rows[0]['basis']='OFS';self.evidence=self.evidence[:1];self.prepare()
        self.assertNotIn('comparison',self.fact('revenue',2025))
    def test_financial_provenance_and_internal_reference_are_preserved(self):
        f=self.fact('margin',2025);citation=self.citations[self.refs[f['id']]]
        self.assertEqual({i['metric'] for i in citation['source_inputs']},{'revenue','operating_income'})
        self.assertEqual(citation['financial_fact']['metric'],'margin')
    def test_health_and_bank_metrics_use_existing_approved_graph_reader(self):
        for membership,metric in (('KRX_HEALTH','rd'),('KRX_BANK','net_interest_income')):
            with self.subTest(membership=membership):
                self.repo.sector.membership_code=membership
                graph=SimpleNamespace(bank=membership=='KRX_BANK',value=lambda code,y,t,b,m,k:
                    (500000000,[dict(source_rcept_no=str(y),value_type=k,source_account_nm=m)]))
                self.evidence=self.evidence[:1]
                with patch('dart_remote.graph_metrics.GraphData',return_value=graph):self.prepare()
                self.assertTrue(any(e.get('metric')==metric for e in self.evidence))

if __name__=='__main__':unittest.main()
