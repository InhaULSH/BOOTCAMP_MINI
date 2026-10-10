import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from dart_remote import llm_diagnostics as d,citation_selection as selection

class DiagnosticTests(unittest.TestCase):
    def test_reference_failures_include_scores_and_each_sentence(self):
        text='AI 서버의 수요에 대응하여 생산능력 확대를 계획하고 있습니다.'
        evidence=[dict(id='t1',kind='filing',passages=[dict(id='t1-p1',text=text,start=0,end=len(text))])]
        def sentence(grades,penalty):
            return dict(text='생산능력 확대 계획입니다.',refs=['t1'],assessments=[dict(id='t1',grades=grades,
                suitable=True,reason='원문',irrelevant_content=penalty,redundancy='none',passage_ids=['t1-p1'])])
        value=dict(sentences=[sentence(dict(F=3,U=3,C=3,T=3),'some'),sentence(dict(F=2,U=4,C=4,T=4),'none')],insufficient_reason='')
        with self.assertRaises(selection.CitationValidationError) as captured:selection.validate(value,evidence,1,3)
        issues=captured.exception.issues
        self.assertEqual([i['sentence_index'] for i in issues],[1,2])
        self.assertEqual([i['computed_score'] for i in issues],[70,80])
        self.assertIn('FACT_SUPPORT_BELOW_MIN',issues[1]['failures'])
        with tempfile.TemporaryDirectory() as folder,patch.object(d.artifacts,'ROOT',Path(folder)):
            record=d.record_validation(captured.exception,'STOP',json.dumps(value),evidence,
                dict(generation_stage='insight_draft',prompt_version='new2'),{'properties':{}},repair=False)
        self.assertEqual(record['issues'],issues)
        self.assertEqual(record['stage'],'insight_draft')

    def test_missing_selected_assessment_is_named(self):
        value=dict(sentences=[dict(text='사업 현황입니다.',refs=['t1'],assessments=[])],insufficient_reason='')
        with self.assertRaises(selection.CitationValidationError) as captured:
            selection.validate(value,[dict(id='t1',kind='filing')],1,3)
        self.assertEqual(captured.exception.issues,[dict(error_code='MISSING_ASSESSMENT',sentence_index=1,ref='t1')])

    def test_diagnostic_scope_count_private_save(self):
        schema={'properties':{'sentences':{'maxItems':2,'anyOf':[{'maxItems':0},{'minItems':2,'maxItems':2}]}}}
        with tempfile.TemporaryDirectory() as folder,patch.object(d.artifacts,'ROOT',Path(folder)):
            with self.assertLogs(level='WARNING') as logs:
                record=d.record_validation(ValueError('문장 수 오류'),'STOP',json.dumps({'sentences':[{}]}),
                    [{'id':'t1','year':2024}],{'sector_name':'자동차','company':'기업가','keyword':'생산'},schema,repair=True)
            files=list(Path(folder).rglob('*.json'))
            self.assertEqual(len(files),1)
            self.assertEqual(json.loads(files[0].read_text(encoding='utf-8')),record)
            self.assertEqual(record['actual_sentence_count'],1);self.assertEqual(record['minimum_sentences'],2)
            self.assertEqual(record['attempt'],2);self.assertIn('keyword=생산',''.join(logs.output))
            self.assertNotIn('MYSQL_PASSWORD',record)

    def test_empty_reason_and_keyword_schema(self):
        llm=SimpleNamespace(object_schema=lambda props:{'properties':props},TEXT={'type':'string'})
        schema=selection.schema(llm,1,2,[dict(id='t1',kind='filing',passages=[{'id':'p1'}])])
        self.assertEqual(schema['properties']['sentences']['anyOf'],[{'maxItems':0},{'minItems':1,'maxItems':2}])
        self.assertEqual(selection.validate({'sentences':[],'insufficient_reason':'공시 근거 부족'},[],1,2)['sentences'],[])
        with self.assertRaisesRegex(ValueError,'근거 부족 이유'):
            selection.validate({'sentences':[],'insufficient_reason':'   '},[],1,2)
        with self.assertRaisesRegex(ValueError,'실제 3개, 허용 1-2개'):
            selection.validate({'sentences':[{}, {}, {}],'insufficient_reason':''},[],1,2)
