from unittest.mock import patch
import os
"""Saved Kia failure and adversarial comparisons; no DB or Gemini calls."""
import unittest
from dart_remote.financial_evidence import _check_sentence, validate_financial


@patch.dict(os.environ, {'INSIGHT_VALIDATION_MODE': 'strict'})
class FinancialClaimPeriodTests(unittest.TestCase):
    def setUp(self):
        self.evidence=[dict(id='t1',kind='filing',company='기아',year=2026)]
        for metric,prior,current in (
            ('revenue',57367145000000,62538936000000),
            ('operating_income',5773354000000,4833650000000),
            ('margin',10.06386843898193,7.729025002919782)):
            old=metric+'-old';new=metric+'-new'
            for eid,year,amount in ((old,2025,prior),(new,2026,current)):
                fact=dict(id=eid,kind='financial',company='기아',year=year,
                    report_type='H1',metric=metric,estimated=False,
                    values={metric:amount,'basis':'CFS'})
                if eid==new:
                    fact['comparison']=dict(ref=old,year=2025,value=prior,
                        growth_pct=(current-prior)/prior*100 if metric!='margin' else None,
                        difference_pp=current-prior if metric=='margin' else None,
                        difference=current-prior,estimated=False)
                self.evidence.append(fact)
        self.refs=[f['id'] for f in self.evidence]

    def check(self,text,refs=None):
        return _check_sentence(dict(text=text,refs=self.refs if refs is None else refs),self.evidence)

    def test_saved_server_response(self):
        self.check('기아는 2026년 반기 연결기준 매출액이 62조 5,389억 원으로 전년 동기(57조 3,671억 원) 대비 9.0% 증가했으나, 영업이익은 4조 8,337억 원으로 16.3% 감소하며 영업이익률이 7.7%로 둔화되었습니다.')

    def test_explicit_parenthetical_year_does_not_leak(self):
        self.check('기아는 2026년 반기 연결 매출액이 62조 5,389억 원으로 전년 동기(2025년 57조 3,671억 원) 대비 9.0% 증가했습니다.')

    def test_relative_period_variants(self):
        for wording in ('전년 동기','전년','직전 연도','지난해'):
            with self.subTest(wording=wording):
                self.check(f'기아는 2026년 반기 연결 매출액이 62조 5,389억 원이며 {wording}(57조 3,671억 원)보다 늘었습니다.')

    def test_ratio_level_is_not_negated(self):
        self.check('기아는 2026년 반기 영업이익률이 7.7%로 하락했습니다.')

    def test_signed_and_unsigned_decline(self):
        for amount in ('16.3','-16.3','−16.3','－16.3','− 16.3'):
            self.check(f'기아는 2026년 반기 영업이익이 {amount}% 감소했습니다.')
        self.check('기아는 2026년 반기 영업이익률이 2.3%p 하락했습니다.')

    def test_unicode_negative_growth_is_not_read_as_positive(self):
        for sign in ('−','－','마이너스 '):
            with self.subTest(sign=sign),self.assertRaises(ValueError):
                self.check(f'기아는 2026년 반기 매출액이 {sign}9.0% 증가했습니다.')

    def test_half_year_or_annual_is_not_standalone_quarter(self):
        for text in ('기아는 2026년 2분기 매출액이 62조 5,389억 원입니다.',
                     '기아는 2026년 3분기 단일 매출액이 62조 5,389억 원입니다.',
                     '기아는 2026년 반기 당분기 매출액이 62조 5,389억 원입니다.'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.check(text)

    def test_year_on_year_is_not_quarter_on_quarter(self):
        for wording in ('전분기','직전 분기'):
            with self.subTest(wording=wording),self.assertRaises(ValueError):
                self.check(f'기아는 2026년 반기 영업이익이 {wording} 대비 16.3% 감소했습니다.')

    def test_wrong_direction_rejected(self):
        for text in ('기아는 2026년 반기 영업이익이 16.3% 증가했습니다.',
                     '기아는 2026년 반기 매출액이 9.0% 감소했습니다.'):
            with self.assertRaises(ValueError):self.check(text)

    def test_wrong_previous_value_rejected(self):
        with self.assertRaises(ValueError):
            self.check('기아는 2026년 반기 매출액이 62조 5,389억 원으로 전년 동기(62조 5,389억 원)보다 늘었습니다.')

    def test_missing_previous_ref_rejected(self):
        refs=[r for r in self.refs if r!='revenue-old']
        for text in ('기아는 2026년 반기 매출액이 전년 동기(57조 3,671억 원)보다 늘었습니다.',
                     '기아는 2026년 반기 매출액이 9.0% 증가했습니다.'):
            with self.assertRaises(ValueError):self.check(text,refs)

    def test_scope_mismatch_rejected(self):
        for text in ('기아는 2026년 연간 매출액이 62조 5,389억 원입니다.',
                     '기아는 2026년 반기 별도 매출액이 62조 5,389억 원입니다.'):
            with self.assertRaises(ValueError):self.check(text)

    def test_ratio_change_cannot_be_substituted_for_level(self):
        with self.assertRaises(ValueError):
            self.check('기아는 2026년 반기 영업이익률이 2.3%로 하락했습니다.')

    def test_diagnostics_show_claim_and_expected_value(self):
        value=dict(sentences=[dict(text='기아는 2026년 반기 매출액이 60조 원입니다.',refs=self.refs)])
        with self.assertRaises(ValueError) as caught:validate_financial(value,self.evidence)
        issue=caught.exception.issues[0]
        self.assertEqual(issue['metric'],'revenue')
        self.assertEqual(issue['candidate_ids'],['revenue-new'])
        self.assertEqual(issue['expected_values'],[62538936000000])
        self.assertEqual(issue['sentence_index'],1)


if __name__=='__main__':unittest.main()
