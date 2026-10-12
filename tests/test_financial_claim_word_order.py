from unittest.mock import patch
import os
"""Saved HVM failures with verified DB amounts; isolates financial validation."""
import copy
import unittest
from dart_remote.financial_evidence import _check_sentence, validate_financial

@patch.dict(os.environ, {'INSIGHT_VALIDATION_MODE': 'strict'})
class FinancialClaimWordOrderTests(unittest.TestCase):
    def setUp(self):
        self.evidence=[dict(id='t1',kind='filing',company='에이치브이엠'),
                       dict(id='t10',kind='filing',company='에이치브이엠')]
        amounts={'revenue':(45140439641,66531544743),'operating_income':(-6789016613,5837442731),
                 'capex':(15303131430,21504976749),'operating_cashflow':(-14010320981,-8827636205)}
        amounts['capex_ratio']=(amounts['capex'][0]/amounts['revenue'][0]*100,
                                amounts['capex'][1]/amounts['revenue'][1]*100)
        amounts['rd']=(4000000000,6653154474.3)
        amounts['rd_ratio']=(4000000000/45140439641*100,10.0)
        for metric,(old,new) in amounts.items():
            for year,amount in ((2024,old),(2025,new)):
                fact=dict(id=f'{metric}-{year}',kind='financial',company='에이치브이엠',year=year,
                    report_type='FY',metric=metric,value_type='annual',estimated=False,
                    values={metric:amount,'basis':'OFS'})
                if year==2025:
                    ratio=metric.endswith('_ratio')
                    fact['comparison']=dict(ref=f'{metric}-2024',year=2024,value=old,
                        difference=new-old,growth_pct=(new-old)/old*100 if old>0 and not ratio else None,
                        difference_pp=new-old if ratio else None,estimated=False)
                self.evidence.append(fact)
        self.refs=[f['id'] for f in self.evidence]

    def check(self,text,refs=None):
        _check_sentence(dict(text=text,refs=self.refs if refs is None else refs),self.evidence)

    def test_saved_first_response_ratio_and_trailing_capex(self):
        self.check('지속적인 생산 설비 확충을 위해 2025년에도 매출액 대비 32.3% 규모인 215억 원을 CAPEX로 지출하면서 영업활동현금흐름은 여전히 마이너스를 유지하고 있습니다.')

    def test_saved_correction_trailing_capex_and_negative_cashflow(self):
        self.check('해외 수주 물량 확대에 대응하기 위해 제2공장 설비 투자를 지속하며 2025년 215억 원의 CAPEX를 집행함에 따라 영업활동현금흐름은 -88억 원을 기록했습니다.')

    def test_saved_correction_revenue_comparison(self):
        self.check('에이치브이엠은 고청정 합금 제조 기술을 바탕으로 2025년 매출액 665억 원을 기록하여 전년 451억 원 대비 47.4% 성장했으며, 영업이익은 58억 원으로 흑자 전환했습니다.')

    def test_trailing_amount_labels(self):
        for phrase in ('215억 원의 CAPEX','215억 원을 CAPEX로','215억 원 규모의 CAPEX',
                       '215억 원의 설비투자액','215억 원의 유형자산 취득액'):
            with self.subTest(phrase=phrase):self.check(f'에이치브이엠은 2025년 {phrase}를 집행했습니다.')
        self.check('에이치브이엠은 2025년 -88억 원의 영업활동현금흐름을 기록했습니다.')

    def test_trailing_percentage_label(self):
        self.check('에이치브이엠은 2025년 32.3%의 CAPEX / 매출액을 기록했습니다.')

    def test_explicit_ratio_numerator_before_or_after(self):
        for text in ('에이치브이엠은 2025년 CAPEX가 매출액 대비 32.3%입니다.',
                     '에이치브이엠은 2025년 매출액의 32.3%를 CAPEX로 지출했습니다.',
                     '에이치브이엠은 2025년 연구개발비가 매출액 대비 10.0%입니다.',
                     '에이치브이엠은 2025년 매출액 대비 10.0% 규모를 연구개발비로 지출했습니다.'):
            with self.subTest(text=text):self.check(text)

    def test_wrong_values_basis_period_and_direction_still_rejected(self):
        for text in ('2025년 매출액 대비 99.0% 규모인 215억 원을 CAPEX로 지출했습니다.',
                     '2025년 999억 원의 CAPEX를 집행했습니다.',
                     '2025년 연결 기준 215억 원의 CAPEX를 집행했습니다.',
                     '2025년 상반기 215억 원의 CAPEX를 집행했습니다.',
                     '2025년 영업활동현금흐름은 88억 원입니다.',
                     '2025년 매출액이 47.4% 감소했습니다.'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.check(text)

    def test_distant_label_is_not_guessed(self):
        for text in ('2025년 215억 원을 기록했으며 CAPEX를 확대했습니다.',
                     '2025년 매출액 대비 32.3%입니다. CAPEX를 늘렸습니다.',
                     '2025년 매출액 대비 32.3%이며 영업이익도 증가했습니다.'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.check(text)

    def test_cannot_borrow_uncited_metric(self):
        refs=[i for i in self.refs if not i.startswith('capex')]
        with self.assertRaises(ValueError):self.check('2025년 215억 원의 CAPEX를 집행했습니다.',refs)

    def test_two_metric_claims_do_not_bind_by_equal_value(self):
        with self.assertRaises(ValueError):
            self.check('2025년 영업이익 58억 원과 CAPEX 215억 원입니다. 영업이익은 215억 원입니다.')

    def test_both_saved_sentences_validate_and_keep_sources(self):
        value=dict(sentences=[dict(text='에이치브이엠은 2025년 매출액 665억 원을 기록하여 전년 451억 원 대비 47.4% 성장했으며, 영업이익은 58억 원입니다.',refs=['revenue-2025','revenue-2024','operating_income-2025','t1']),
          dict(text='2025년 215억 원의 CAPEX를 집행하며 영업활동현금흐름은 -88억 원을 기록했습니다.',refs=['capex-2025','operating_cashflow-2025','t10'])])
        before=copy.deepcopy(value);validate_financial(value,self.evidence)
        self.assertEqual(value,before)

    def test_scope_failure_diagnostic_identifies_actual_claim(self):
        value=dict(sentences=[dict(text='2025년 연결 기준 215억 원의 CAPEX를 집행했습니다.',refs=['capex-2025','t1'])])
        with self.assertRaises(ValueError) as caught:validate_financial(value,self.evidence)
        issue=caught.exception.issues[0]
        self.assertEqual(issue['metric'],'capex')
        self.assertEqual(issue['stated_basis'],'연결')
        self.assertEqual(issue['selected_metric_ids'],['capex-2025'])

    def test_ratio_does_not_borrow_numerator_from_an_independent_assertion(self):
        with self.assertRaises(ValueError):
            self.check('2025년 매출액 대비 32.3%이며 CAPEX를 지출했습니다.')
