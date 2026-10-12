from unittest.mock import patch
import os
"""Banking ordered claims regression; no external requests or production writes."""
import unittest
from dart_remote.financial_evidence import _check_sentence, metric_mentions
from snapdart.data_access import prompts_new2

@patch.dict(os.environ, {'INSIGHT_VALIDATION_MODE': 'strict'})
class BankFinancialClaimsTests(unittest.TestCase):
    def setUp(self):
        self.evidence=[]
        for metric,prior,current in (
            ('operating_income',3958471000000,4630734000000),
            ('net_income',3094280000000,3495799000000),
            ('net_interest_income',1000000000000,1100000000000),
            ('credit_loss',100000000000,80000000000),
            ('capex_ratio',8.0,10.0)):
            for year,amount in ((2025,prior),(2026,current)):
                fact=dict(id=f'{metric}-{year}',kind='financial',company='신한지주',year=year,
                    report_type='H1',metric=metric,estimated=False,value_type='cumulative',
                    values={metric:amount,'basis':'CFS'})
                if year==2026:
                    fact['comparison']=dict(ref=f'{metric}-2025',year=2025,value=prior,
                        growth_pct=(current-prior)/prior*100 if metric!='capex_ratio' else None,
                        difference_pp=current-prior if metric=='capex_ratio' else None,
                        difference=current-prior,estimated=False)
                self.evidence.append(fact)
        self.refs=[e['id'] for e in self.evidence]

    def check(self,text,refs=None):
        _check_sentence(dict(text=text,refs=self.refs if refs is None else refs),self.evidence)

    def test_saved_shinhan_response(self):
        self.check('신한지주는 2026년 상반기 연결기준 영업이익 4조 6,307억 원(전년 동기 3조 9,585억 원)과 당기순이익 3조 4,958억 원(전년 동기 3조 943억 원)을 기록하며 전년 대비 각각 17.0%, 13.0%의 성장세를 보였습니다.')

    def test_named_claims(self):
        self.check('신한지주는 2026년 상반기 영업이익이 17.0% 증가했고, 당기순이익이 13.0% 증가했습니다.')

    def test_ordered_two_and_three_metrics(self):
        for text in ('신한지주는 2026년 상반기 영업이익과 당기순이익이 각각 17.0%, 13.0% 증가했습니다.',
                     '신한지주는 2026년 상반기 당기순이익과 영업이익이 각각 13.0%, 17.0% 증가했습니다.',
                     '신한지주는 2026년 상반기 순이자이익, 영업이익, 당기순이익이 각각 10.0%, 17.0%, 13.0% 증가했습니다.'):
            with self.subTest(text=text):self.check(text)

    def test_ordered_money(self):
        self.check('신한지주는 2026년 상반기 영업이익과 당기순이익이 각각 4조 6,307억 원, 3조 4,958억 원입니다.')

    def test_independent_direction(self):
        self.check('신한지주는 2026년 상반기 순이자이익이 10.0% 증가하고 신용손실비용이 20.0% 감소했습니다.')

    def test_aliases(self):
        for label in ('순이자이익','순이자 이익','순이자수익'):
            with self.subTest(label=label):self.check(f'신한지주는 2026년 상반기 {label}이 10.0% 증가했습니다.')
        self.check('신한지주는 2026년 상반기 대손 비용이 20.0% 감소했습니다.')

    def test_ratio_is_longest_label(self):
        self.assertEqual(metric_mentions('CAPEX / 매출액')[-1][2],'capex_ratio')
        self.check('신한지주는 2026년 상반기 CAPEX / 매출액이 10.0%이며 2.0%p 상승했습니다.')

    def test_wrong_order_value_count_and_direction(self):
        cases=(
            '영업이익과 당기순이익이 각각 13.0%, 17.0% 증가했습니다.',
            '영업이익과 당기순이익이 각각 17.0%, 99.0% 증가했습니다.',
            '영업이익과 당기순이익이 각각 17.0% 증가했습니다.',
            '영업이익이 각각 17.0%, 13.0% 증가했습니다.',
            '영업이익과 당기순이익이 각각 17.0%, 13.0% 감소했습니다.',
            '순이자이익과 신용손실비용이 각각 10.0%, 20.0% 증가했습니다.',
            '영업이익과 당기순이익이 각각 −17.0%, 13.0% 증가했습니다.')
        for clause in cases:
            with self.subTest(clause=clause),self.assertRaises(ValueError):
                self.check('신한지주는 2026년 상반기 '+clause)

    def test_missing_previous_ref(self):
        with self.assertRaises(ValueError):
            self.check('신한지주는 2026년 상반기 영업이익과 당기순이익이 각각 17.0%, 13.0% 증가했습니다.',
                       [r for r in self.refs if r!='operating_income-2025'])

    def test_unknown_distinct_bank_metrics(self):
        for label in ('순이자마진','NIM','ROE','ROA','CET1','보통주자본비율','지배주주 순이익','순이자이익률'):
            with self.subTest(label=label),self.assertRaises(ValueError):
                self.check(f'신한지주는 2026년 상반기 당기순이익이 개선되고 {label}이 13.0% 증가했습니다.')

    def test_scope_and_quarter_mismatch(self):
        for scope in ('2026년 연간','2026년 2분기','2026년 상반기 별도','2026년 상반기 전분기 대비'):
            with self.subTest(scope=scope),self.assertRaises(ValueError):
                self.check(f'신한지주는 {scope} 영업이익과 당기순이익이 각각 17.0%, 13.0% 증가했습니다.')

    def test_multiple_companies_or_scopes_are_not_guessed(self):
        self.evidence.append(dict(self.evidence[0],id='other',company='KB금융'))
        for scope in ('신한지주와 KB금융은 2026년 상반기',
                      '신한지주는 2025년 및 2026년 상반기',
                      '신한지주는 2026년 상반기 연결과 별도',
                      '신한지주는 2026년 상반기와 연간'):
            with self.subTest(scope=scope),self.assertRaises(ValueError):
                self.check(f'{scope} 영업이익과 당기순이익이 각각 17.0%, 13.0% 증가했습니다.')

    def test_prompt_names_each_numeric_metric(self):
        for function in ('company','insight'):
            self.assertIn('각 숫자에 재무 항목명을 직접',prompts_new2.instruction(function))
        self.assertNotIn('[수치 주장의 항목·기간 명시]',prompts_new2.instruction('keyword'))

    def test_non_numeric_each_does_not_block_business_prose(self):
        self.check('신한지주의 두 사업부는 각각 고객 기반을 확대했습니다.')
        self.check('신한지주의 두 사업부는 각각 고객 기반을 확대했고 2026년 상반기 영업이익이 17.0% 증가했습니다.')
