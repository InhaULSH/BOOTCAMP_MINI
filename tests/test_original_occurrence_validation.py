"""Malformed duplicate-source grades must use the normal repair/failure path."""
import copy
import unittest
from unittest.mock import patch
from dart_remote.original_document import choose_occurrence
from snapdart import llm


class OccurrenceValidationTests(unittest.TestCase):
    def test_typed_validation_and_score_selection(self):
        base=dict(assessments=[dict(id='o'+str(i),grades=dict(F=3+i,U=3+i,C=3+i,T=3+i),
              suitable=True,irrelevant_content='none',redundancy='none') for i in range(2)])
        def invoke(value):
            def fake(context,evidence,**kwargs):
                return dict(report=kwargs['validator'](value,evidence))
            with patch.object(llm,'request_report',side_effect=fake):
                return choose_occurrence.__wrapped__('실제 공시에서 추출한 자연어 근거 문장을 비교합니다.',
                    '사업 변화 설명','II. 사업의 내용','',('첫 번째 주변 문맥','두 번째 주변 문맥'))
        self.assertEqual(invoke(copy.deepcopy(base)),1)
        variants=[None,dict(assessments=None),dict(assessments=[None]),copy.deepcopy(base),copy.deepcopy(base)]
        variants[3]['assessments'][0]['grades']=None
        variants[4]['assessments'][0]['suitable']='true'
        for value in variants:
            with self.subTest(value=value),self.assertRaises(ValueError):invoke(value)
