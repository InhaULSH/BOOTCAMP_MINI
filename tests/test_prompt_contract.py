"""Prompt fidelity and citation validation without calling a model API."""
import copy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from snapdart.data_access import pipeline, prompts


class PromptContractTests(unittest.TestCase):
    def generate(self, sentences, filing_count=2, financial_values=None, company_scope=False, keyword=None):
        captured = {}
        def request(context, evidence, **options):
            captured.update(options)
            captured['context']=context
            for sentence in sentences:
                old=sentence['refs']
                sentence['refs']=[('f'+str(int(i[1:])+filing_count-1)) if i.startswith('f') else i for i in old]
                if filing_count>=2:sentence['refs']=list(dict.fromkeys(sentence['refs']+['t1','t2']))
                sentence['assessments']=[dict(id=e['id'],grades=dict(F=4,U=4,C=4,T=4),suitable=True,reason='입력 근거',irrelevant_content='none',redundancy='none',passage_ids=[p['id'] for p in e['passages']]) for e in evidence if e['kind']=='filing']
            value = options['validator']({'sentences': sentences,'insufficient_reason':''}, evidence)
            return {'report': value}
        llm = types.SimpleNamespace(PROVIDER='test', MODEL='test', TEXT={'type': 'string'},
            object_schema=lambda props: {'type': 'object', 'properties': props}, request_report=request)
        package = types.ModuleType('snapdart')
        package.llm = llm
        row = dict(year=2025, basis='CFS', revenue=None, operating_income=None,
            capex=None, operating_cashflow=None, yoy={}, margin=None, fcf=None, financial_sources={})
        row.update(financial_values or {})
        companies = [dict(code=str(i), name=name, history=[copy.deepcopy(row)])
            for i, name in enumerate(('기업가', '기업나'))]
        report = dict(companies=companies, years=[2025], citations={},wordcloud={'2025':[dict(text='HBM',count=12,mention_rate=0.1,change_raw=0.02)]})
        repo = types.SimpleNamespace(sector=types.SimpleNamespace(id='test', name='테스트'),
            financial=lambda *a, **k: dict(row, report_type=a[2]))
        evidence = dict(sector_id='test', chunk_id='chunk1', receipt_no='receipt',
            company='기업가', year=2025, period='2025-12', report_name='사업보고서',
            section='사업', heading='현황', text='AI 서버의 수요 증가에 대응하여 생산능력 확대를 계획하고 있습니다.', anchor_start=0)
        repo.search=lambda *a,**k:([evidence],{})
        folder=Path(__file__).resolve().parent.parent/'unused-test-cache'
        with patch.object(pipeline,'atomic'), \
             patch.dict(sys.modules, {'snapdart': package}), \
             patch.object(pipeline, 'SERVICE', Path(folder)), \
             patch.object(pipeline, 'evidence_rows', return_value=[dict(evidence,chunk_id='chunk'+str(i)) for i in range(filing_count)]):
            result = pipeline.generate(report, report, repo, company=companies[0] if company_scope else None,force=True,keyword=keyword)
        if captured:captured['citations']=report['citations']
        return result, captured

    def test_no_company_name_or_two_company_evidence_requirement(self):
        result, captured = self.generate([
            {'text': '제공된 자료에서 제품 구성이 달라졌습니다.', 'refs': ['t1']},
            {'text': '산업 공통 흐름을 판단할 근거는 충분하지 않습니다.', 'refs': ['t1']},
        ])
        self.assertEqual(len(result['sentences']), 2)
        self.assertEqual(captured['instruction'], prompts.COMMON+'\n'+prompts.INSIGHT+'\n'+pipeline.selection.INSTRUCTION)
        self.assertEqual(captured['temperature'], 1.0)
        self.assertEqual(captured['max_output_tokens'], 8192)

    def test_no_added_character_limit_or_phrase_ban(self):
        text = '제공된 공시 내용을 바탕으로 변화를 설명합니다. ' * 12
        result, _ = self.generate([
            {'text': text+'공시에 확인된 개선에 힘입어 구성이 바뀌었습니다.', 'refs': ['t1']},
            {'text': text, 'refs': ['t1']},
        ])
        self.assertGreater(sum(len(s['text']) for s in result['sentences']), 400)

    def test_unknown_citation_still_rejected(self):
        with self.assertRaisesRegex(ValueError, '입력 근거 ID'):
            self.generate([{'text': '사업 변화입니다.', 'refs': ['missing']},
                {'text': '자료의 한계입니다.', 'refs': ['t1']}])

    def test_single_chunk_can_generate_single_industry_sentence(self):
        result,captured=self.generate([dict(text='공시에서 생산능력 확대 계획을 확인할 수 있습니다.',refs=['t1'])],filing_count=1)
        self.assertEqual(len(result['sentences']),1)
        self.assertEqual(len(result['sentences'][0]['source_refs']),1)
        self.assertIn('최소 1개',captured['instruction'])

    def test_industry_prompt_has_no_company_count_limit(self):
        self.assertIn('기업명을 나열하는 대신 사업의 방향',prompts.INSIGHT)
        self.assertIn('공통 산업 요인을 우선',prompts.INSIGHT)

    def test_shared_factor_analysis_allows_different_company_directions(self):
        self.assertIn('여러 기업의 변화가 다르더라도',prompts.COMMON)
        self.assertIn('기업의 주력 사업',prompts.INSIGHT)
        self.assertIn('공통 산업 요인',prompts.INSIGHT)

    def test_keyword_statistics_are_optional_and_preserved(self):
        stats={'count':12,'company_count':3}
        self.assertEqual(prompts.context('반도체',[],[],keyword='HBM',keyword_statistics=stats)['keyword_statistics'],stats)
        self.assertNotIn('keyword_statistics',prompts.context('반도체',[],[]))

    def test_keyword_generation_receives_calculated_signal_statistics(self):
        _,captured=self.generate([dict(text='공시에 나타난 제품의 수요 변화입니다.',refs=['t1'])],filing_count=1,keyword='HBM')
        self.assertEqual(captured['context']['keyword_statistics']['count'],12)
        self.assertEqual(captured['context']['keyword_statistics']['change_raw'],0.02)
        self.assertNotIn('final_signal_score',captured['context']['keyword_statistics'])

    def test_view_never_replaces_ai_report_with_offline_excerpt(self):
        from types import SimpleNamespace
        with patch('snapdart.data_access.pipeline.Repository',return_value=SimpleNamespace(sector=SimpleNamespace(id='test'),fingerprint=lambda:'new')),patch('dart_remote.artifacts.get_artifact',return_value=dict(source=dict(dataset_sha256='old'))),patch('snapdart.data_access.pipeline.build') as build:
            with self.assertRaisesRegex(RuntimeError,'다시 생성'):pipeline.load_report('test')
        build.assert_not_called()

    def test_industry_user_task_comes_from_definition(self):
        task = prompts.context('반도체', [], [])['task']
        self.assertIn('산업 반도체의 핵심 사업 현황·변화를', task)
        self.assertNotIn('최소 두', prompts.instruction())
        self.assertNotIn('400', prompts.instruction())

    def test_four_filing_references_need_no_financial_reference(self):
        result, captured = self.generate([
            {'text': '공시에서 공통 사업 변화를 확인했습니다.', 'refs': ['t1','t2','t3','t4']},
            {'text': '자료의 한계로 원인을 단정하지 않습니다.', 'refs': []},
        ],filing_count=4)
        self.assertEqual(len(result['sentences'][0]['source_refs']),4)
        refs_schema=captured['schema']['properties']['sentences']['items']['properties']['refs']
        self.assertNotIn('maxItems',refs_schema)
        self.assertNotIn('minItems',refs_schema)

    def test_financial_only_input_cannot_fake_two_filing_sources(self):
        result,captured=self.generate([],filing_count=0,financial_values={'revenue':10000})
        self.assertEqual(result['sentences'],[])
        self.assertIn('근거가 없습니다',result['insufficient_reason'])
        self.assertFalse(captured)

    def test_no_material_returns_pdf_data_limit_without_model_call(self):
        result, captured=self.generate([],filing_count=0)
        self.assertFalse(captured)
        self.assertEqual(result['sentences'],[])
        self.assertIn('부족',result['insufficient_reason'])

    def test_company_prompt_has_no_invented_sentence_count(self):
        result,captured=self.generate([{'text':'기업의 사업 현황입니다.','refs':['t1']}],company_scope=True)
        self.assertEqual(len(result['sentences']),1)
        self.assertEqual(captured['schema']['properties']['sentences']['maxItems'],3)

    def test_money_sign_and_arbitrary_amount_are_rejected(self):
        for text in ('영업이익은 1,234원입니다.','영업이익은 -1,200원입니다.'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError,'금액'):
                self.generate([{'text':text,'refs':['t1']}, {'text':'근거의 한계를 확인합니다.','refs':[]}],financial_values={'operating_income':-1234})

    def test_negative_money_preserves_the_input_sign(self):
        result,_=self.generate([{'text':'영업이익은 -1,234원입니다.','refs':['t1']}, {'text':'근거의 한계를 확인합니다.','refs':[]}],financial_values={'operating_income':-1234})
        self.assertEqual(len(result['sentences']),2)

    def test_financial_refs_are_not_exposed_as_prose_footnotes(self):
        with self.assertRaisesRegex(ValueError,'입력 근거 ID'):
            self.generate([{'text':'반기 재무자료에 변화가 있습니다.','refs':['f4']}, {'text':'원인은 공시 근거로 확인해야 합니다.','refs':[]}],financial_values={'revenue':10000})


if __name__ == '__main__':
    unittest.main()

    def test_old_profile_reaches_request_and_keeps_company_limit(self):
        from snapdart.data_access import prompts_old
        from dart_remote import citation_selection_old
        import os
        with patch.dict(os.environ,{'LLM_PROMPT_VERSION':'old'}):
            result,captured=self.generate([{'text':'기업의 사업 현황입니다.','refs':['t1']}],company_scope=True)
        self.assertEqual(captured['instruction'],prompts_old.instruction('company')+'\n'+citation_selection_old.INSTRUCTION)
        self.assertNotIn('maxItems',captured['schema']['properties']['sentences'])
        self.assertEqual(result['prompt_version'],prompts_old.VERSION)
        self.assertEqual(result['selection_version'],citation_selection_old.VERSION)

    def test_definition_and_deploy_profiles_match(self):
        import runpy
        root=Path(__file__).resolve().parents[1]
        text=(root/'docs/4차구상/프롬프트_정의서_수정.txt').read_text(encoding='utf-8-sig')
        deployed=runpy.run_path(str(root/'deploy/cloudapp/prompts.py'))
        for key in ('COMMON','INSIGHT','COMPANY','KEYWORD'):
            self.assertIn(getattr(prompts,key),text)
            self.assertEqual(getattr(prompts,key),deployed[key])
        from dart_remote import citation_selection
        self.assertIn(citation_selection.INSTRUCTION,text)
        self.assertEqual(citation_selection.INSTRUCTION,runpy.run_path(str(root/'deploy/dart_remote/citation_selection.py'))['INSTRUCTION'])

    def test_new_and_old_scoring_are_separate(self):
        from dart_remote import citation_selection,citation_selection_old
        text='AI 서버의 수요 증가에 대응하여 생산능력 확대를 계획하고 있습니다.'
        evidence=[dict(id='t1',kind='filing',text=text,passages=[dict(id='t1-p1',text=text,start=0,end=len(text))])]
        value=dict(sentences=[dict(text='생산능력 확대를 계획하고 있습니다.',refs=['t1'],assessments=[dict(id='t1',grades=dict(F=4,U=3,C=4,T=4),suitable=True,reason='근거',irrelevant_content='none',redundancy='none',passage_ids=['t1-p1'])])],insufficient_reason='')
        self.assertEqual(citation_selection.validate(copy.deepcopy(value),evidence,1,3)['sentences'][0]['assessments'][0]['score'],92.5)
        self.assertEqual(citation_selection_old.validate(copy.deepcopy(value),evidence,1,3)['sentences'][0]['assessments'][0]['score'],95)
