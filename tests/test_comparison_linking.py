from unittest.mock import patch
import os
"""Verified comparison linking and combined diagnostics; no DB/model calls."""
import copy
import unittest
from dart_remote import citation_selection_new2 as selection
from tests import test_new2_financial_evidence as fixtures

@patch.dict(os.environ, {'INSIGHT_VALIDATION_MODE': 'strict'})
class ComparisonLinkingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.FinancialEvidenceTests();self.fixture.setUp()
        self.evidence=self.fixture.evidence
        self.current=self.fixture.fact('revenue',2025)
        self.prior=self.fixture.fact('revenue',2024)

    def value(self,text='2025년 연간 매출액은 20% 증가했습니다.',refs=None):
        return self.fixture.value(text,[self.current['id']] if refs is None else refs)

    def validate(self,value):
        return selection.validate(value,self.evidence,1,3)

    def test_linking_is_atomic_and_idempotent(self):
        value=self.value();self.validate(value)
        self.assertEqual(value['sentences'][0]['llm_refs'],[self.current['id']])
        self.assertIn(self.prior['id'],value['sentences'][0]['refs'])
        before=copy.deepcopy(value);self.validate(value);self.assertEqual(value,before)

    def test_relative_previous_amount(self):
        value=self.value('2025년 연간 매출액은 120억원이며 전년 동기(100억원) 대비 20% 증가했습니다.')
        self.validate(value)
        self.assertEqual(len(value['sentences'][0]['auto_linked_financial_refs']),1)

    def test_percentage_point(self):
        fact=self.fixture.fact('margin',2025)
        value=self.value('2025년 연간 영업이익률이 2%p 상승했습니다.',[fact['id']])
        self.validate(value)
        self.assertIn(fact['comparison']['ref'],value['sentences'][0]['refs'])

    def test_amount_difference(self):
        value=self.value('2025년 연간 매출액의 증가액은 20억원입니다.')
        self.validate(value)
        self.assertIn(self.prior['id'],value['sentences'][0]['refs'])

    def test_absolute_value_does_not_acquire_previous_ref(self):
        value=self.value('2025년 연간 매출액은 120억원입니다.');self.validate(value)
        self.assertNotIn('auto_linked_financial_refs',value['sentences'][0])

    def test_incorrect_values_or_direction_are_not_repaired(self):
        for text in ('2025년 연간 매출액은 30% 증가했습니다.',
                     '2025년 연간 매출액은 20% 감소했습니다.',
                     '2025년 연간 매출액은 전분기 대비 20% 증가했습니다.',
                     '2025년 별도 매출액은 20% 증가했습니다.',
                     '2024년 매출액은 20% 증가했습니다.'):
            value=self.value(text);before=copy.deepcopy(value)
            with self.subTest(text=text),self.assertRaises(ValueError):self.validate(value)
            self.assertEqual(value,before)

    def test_corrupted_predecessor_scope_is_not_linked(self):
        for key,wrong in (('company','다른기업'),('metric','net_income'),('year',2023),
                          ('report_type','H1'),('value_type','quarterly')):
            original=copy.deepcopy(self.prior)
            self.prior[key]=wrong
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(self.value())
            self.prior.clear();self.prior.update(original)
        self.prior['values']['basis']='OFS'
        with self.assertRaises(ValueError):self.validate(self.value())

    def test_corrupted_comparison_calculation_is_not_linked(self):
        for key in ('value','difference','growth_pct','difference_pp'):
            original=copy.deepcopy(self.current['comparison'])
            self.current['comparison'][key]=999
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(self.value())
            self.current['comparison']=original

    def test_unknown_or_missing_current_reference(self):
        for refs in (['not-in-input'],[self.prior['id']],[]):
            with self.subTest(refs=refs),self.assertRaises(ValueError):self.validate(self.value(refs=refs))
        self.current['comparison']['ref']='missing'
        with self.assertRaises(ValueError):self.validate(self.value())

    def test_missing_assessment_and_numeric_error_collected_together(self):
        value=self.value('2025년 연간 매출액은 30% 증가했습니다.')
        value['sentences'][1]['assessments']=[];before=copy.deepcopy(value)
        with self.assertRaises(selection.base.CitationValidationError) as caught:self.validate(value)
        self.assertEqual({i['error_code'] for i in caught.exception.issues},
                         {'MISSING_ASSESSMENT','FINANCIAL_SCOPE_OR_VALUE_MISMATCH'})
        self.assertEqual(value,before)

    def test_bad_assessment_not_bypassed_by_valid_numeric_link(self):
        value=self.value();value['sentences'][1]['assessments'][0]['grades']['F']=1
        before=copy.deepcopy(value)
        with self.assertRaises(ValueError):self.validate(value)
        self.assertEqual(value,before)

    def test_multiple_financial_sentence_errors_collected(self):
        value=self.value('2025년 연간 매출액은 30% 증가했습니다.')
        value['sentences'].insert(1,dict(text='2025년 연간 영업이익은 99% 증가했습니다.',
            refs=[self.fixture.fact('operating_income',2025)['id']],assessments=[]))
        with self.assertRaises(selection.base.CitationValidationError) as caught:self.validate(value)
        self.assertEqual([i['sentence_index'] for i in caught.exception.issues],[1,2])

    def test_invalid_json_structure_returns_validation_error(self):
        for value in (None,dict(sentences=[None]),self.value(refs=[{}])):
            with self.subTest(value=value),self.assertRaises(ValueError):self.validate(value)

    def test_estimated_previous_requires_notice(self):
        self.prior['estimated']=True
        with self.assertRaises(ValueError):self.validate(self.value())
        value=self.value('2025년 연간 매출액은 추정 20% 증가했습니다.');self.validate(value)

    def test_nonpositive_base_does_not_create_growth(self):
        for prior in (0,-10000000000):
            self.prior['values']['revenue']=prior
            self.current['comparison'].update(value=prior,difference=12000000000-prior,growth_pct=None)
            with self.subTest(prior=prior),self.assertRaises(ValueError):self.validate(self.value())

    def test_predecessor_with_its_own_comparison_remains_an_input_on_recheck(self):
        earlier=copy.deepcopy(self.prior)
        earlier.update(id='earlier',year=2023)
        earlier['values']['revenue']=8000000000
        self.evidence.append(earlier)
        self.prior['comparison']=dict(ref='earlier',year=2023,value=8000000000,
            difference=2000000000,growth_pct=25.0,difference_pp=None,estimated=False)
        value=self.value('매출액은 20% 증가했습니다.')
        self.validate(value);before=copy.deepcopy(value);self.validate(value)
        self.assertEqual(value,before)
        self.assertNotIn('earlier',value['sentences'][0]['refs'])

    def test_saved_posco_correction_with_missing_previous_refs(self):
        for fact in self.evidence:
            fact['company']='POSCO홀딩스'
            fact['year']+=1
            fact['report_type']='H1'
            if 'comparison' in fact:fact['comparison']['year']+=1
        for metric,prior,current in (('revenue',35000000000000,37135000000000),
                                     ('operating_income',1150000000000,1492700000000)):
            old=self.fixture.fact(metric,2025);new=self.fixture.fact(metric,2026)
            old['values'][metric]=prior;new['values'][metric]=current
            new['comparison'].update(value=prior,difference=current-prior,growth_pct=(current-prior)/prior*100)
        income=self.fixture.fact('operating_income',2026)
        value=self.value('POSCO홀딩스는 2026년 상반기 연결 기준 매출액 37.1조 원과 영업이익 1.5조 원을 기록하며 전년 동기 대비 각각 6.1%, 29.8% 증가하는 실적 회복 흐름을 보였습니다.',[self.current['id'],income['id']])
        self.validate(value)
        self.assertEqual(len(value['sentences'][0]['auto_linked_financial_refs']),2)
        self.assertEqual(len(value['sentences'][0]['refs']),4)
