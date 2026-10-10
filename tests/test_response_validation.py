import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from dart_remote import citation_selection as selection
from dart_remote.response_validation import cached_result,response_text,validate_money

class ResponseTests(unittest.TestCase):
    def setUp(self):
        prose='생산능력 확대를 위해 신규 설비 도입을 계획하고 있습니다.'
        self.evidence=[dict(id='t1',kind='filing',company='기업가',year=2025,period='2025-12',passages=[dict(id='t1-p1',text=prose,start=0,end=len(prose))]),
            dict(id='f1',kind='financial',company='기업가',year=2025,report_type='FY',values=dict(basis='CFS',revenue=1234,operating_income=-200)),
            dict(id='f2',kind='financial',company='기업가',year=2024,report_type='FY',values=dict(basis='CFS',revenue=9999))]
        self.assessment=dict(id='t1',grades=dict(F=4,U=4,C=4,T=4),suitable=True,reason='직접 근거',irrelevant_content='none',redundancy='none',passage_ids=['t1-p1'])
        self.value=dict(sentences=[dict(text='사업 현황을 설명합니다.',refs=['t1'],assessments=[self.assessment])],insufficient_reason='')
    def test_null_fields_are_validation_errors(self):
        variants=[dict(sentences=[None]),copy.deepcopy(self.value),copy.deepcopy(self.value),copy.deepcopy(self.value)]
        variants[1]['sentences'][0]['assessments']=[None]
        variants[2]['sentences'][0]['assessments'][0]['grades']=None
        variants[3]['sentences'][0]['refs']=[{}]
        for value in variants:
            with self.subTest(value=value),self.assertRaises(ValueError):selection.validate(value,self.evidence,1,3)
    def test_unselected_grade_is_not_published(self):
        self.value['sentences'][0]['assessments'].append(dict(id='t2',passage_ids=['wrong'],grades=None))
        result=selection.validate(self.value,self.evidence,1,3)
        self.assertEqual(len(result['sentences'][0]['assessments']),1)
    def test_dates_prose_and_numeric_table(self):
        for value in ('2025년에는 생산능력 확대를 위해 설비 도입을 계획하고 있습니다.',
                      '2025-10-01 현재 HBM3 제품 생산능력 확대를 계획하고 있습니다.'):
            self.assertTrue(selection.natural_passage(value))
        for value in ('매출액은 2025년 100억원으로 증가하였습니다.', '2025년 매출액 | 100억원', '영업이익률이 10% 증가하였습니다.'):
            self.assertFalse(selection.natural_passage(value))
    def test_money_scope(self):
        def check(text):return validate_money(dict(sentences=[dict(text=text,refs=['t1'])]),self.evidence)
        check('2025년 연결 매출액은 1,234원입니다.')
        check('2024년 연결 매출액은 9,999원입니다.')
        check('2025년 연결 영업손실은 200원입니다.')
        for text in ('2025년 매출액은 9,999원입니다.','2025년 영업이익은 1,234원입니다.',
                     '2025년 별도 매출액은 1,234원입니다.','2025년 반기 매출액은 1,234원입니다.'):
            with self.subTest(text=text),self.assertRaises(ValueError):check(text)
        self.evidence.append(dict(id='f3',kind='financial',company='기업나',year=2025,values=dict(basis='CFS',revenue=1234)))
        with self.assertRaisesRegex(ValueError,'기업이 인용 근거와 다릅니다'):check('기업나의 2025년 연결 매출액은 1,234원입니다.')
    def test_bad_cache_is_regenerated_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cache.json';path.write_text('{broken',encoding='utf-8')
            generate=Mock(return_value={'report':{'sentences':[]}})
            self.assertEqual(cached_result(path,Mock(),generate),generate.return_value)
            generate.assert_called_once()
            path.write_text(json.dumps({'report':{}}),encoding='utf-8')
            generate.reset_mock();cached_result(path,Mock(side_effect=ValueError('old validation')),generate)
            generate.assert_called_once()
    def test_nested_interim_report_type_matches_production_input(self):
        self.evidence.append(dict(id='f-q3',kind='financial',company='기업가',year=2025,
            values=dict(report_type='Q3',basis='CFS',revenue=123)))
        value=dict(sentences=[dict(text='2025년 3분기 연결 매출액은 123원입니다.',refs=['t1'])])
        validate_money(value,self.evidence)
        value['sentences'][0]['text']='2025년 반기 연결 매출액은 123원입니다.'
        with self.assertRaises(ValueError):validate_money(value,self.evidence)
    def test_transport_types_and_termination(self):
        for body in (None,{'candidates':[None]},{'candidates':[{'finishReason':'STOP','content':{'parts':[None]}}]}):
            with self.subTest(body=body),self.assertRaises(ValueError):response_text(body)
        self.assertEqual(response_text({'promptFeedback':{'blockReason':'SAFETY'}}),('','SAFETY'))
        self.assertEqual(response_text({'candidates':[{'finishReason':'MAX_TOKENS'}]}),('','MAX_TOKENS'))
        self.assertEqual(response_text({'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':None}}]}),('','MAX_TOKENS'))
