"""Exercise real orchestration with isolated DB/model doubles; no paid calls."""
import copy
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from snapdart.data_access import pipeline, prompts
from dart_remote import retrieval_context, citation_selection as selection


@patch.dict(os.environ, {'INSIGHT_VALIDATION_MODE': 'strict'})
class New2InsightTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.final_ref='t1'
        self.llm=types.SimpleNamespace(PROVIDER='offline-test',MODEL='offline-test',TEXT={'type':'string'},
            object_schema=lambda props:dict(type='object',properties=props,required=list(props)),request_report=self.request)
        text='AI 서버의 수요에 대응하여 생산능력 확대를 계획하고 있습니다.'
        self.rows=[dict(sector_id='test',chunk_id='chunk'+str(i),receipt_no='receipt'+str(i),company='기업가',
            year=2025,period='2025-12',report_name='사업보고서',section='사업',heading='생산',
            text=text,anchor_start=0) for i in (1,2)]
        self.financial=dict(year=2025,basis='CFS',revenue=None,operating_income=None,capex=None,
            operating_cashflow=None,yoy={},margin=None,fcf=None,financial_sources={})
        self.financial.update(revenue=12000000000,operating_income=1200000000,financial_sources={k:[dict(rcept_no='receipt2025',original_account_nm=k)] for k in ('revenue','operating_income')})
        self.company=dict(code='000001',name='기업가',history=[self.financial])
        self.repo=types.SimpleNamespace(sector=types.SimpleNamespace(id='test',name='테스트'),
            financial=lambda *a,**k:dict(self.financial,report_type=a[2]),search=lambda *a,**k:(self.rows,{}))

    def request(self,context,evidence,**options):
        self.calls.append(dict(context=copy.deepcopy(context),**options))
        eid=self.final_ref
        value=dict(sentences=[dict(text='생산능력 확대를 계획하고 있습니다.',refs=[eid],
            assessments=[dict(id=eid,grades=dict(F=4,U=4,C=4,T=4),suitable=True,reason='직접 원문',
                irrelevant_content='none',redundancy='none',passage_ids=[eid+'-p1'])])],insufficient_reason='')
        if any(str(e).startswith('f') for e in options['schema']['properties']['sentences']['items']['properties']['refs']['items']['enum']):
            f=next((e for e in evidence if e['kind']=='financial' and e.get('metric')=='revenue' and e['year']==2025 and e['report_type']=='FY'),None)
            if f:
                value['sentences'].insert(0,dict(text='2025년 연간 매출액은 120억원입니다.',refs=[f['id']],assessments=[]))
        return dict(report=options['validator'](copy.deepcopy(value),evidence),usage={},model='offline-test')

    def run_profile(self,profile,folder,company=False,keyword=None,force=False):
        report=dict(companies=[self.company],years=[2025],citations={},wordcloud={})
        self.last_report=report
        package=types.ModuleType('snapdart');package.llm=self.llm
        with patch.dict(os.environ,{'LLM_PROMPT_VERSION':profile}),patch.dict(sys.modules,{'snapdart':package}),\
             patch.object(pipeline,'SERVICE',Path(folder)),patch.object(pipeline,'evidence_rows',return_value=self.rows):
            return pipeline.generate(report,report,self.repo,company=self.company if company else None,
                keyword=keyword,force=force)

    def test_default_and_new_keep_existing_instruction_and_one_call(self):
        with patch.dict(os.environ,{},clear=True):self.assertIs(prompts.active(),prompts)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            result=self.run_profile('new',folder)
        self.assertEqual(len(self.calls),1)
        self.assertNotIn('evidence_plan',self.calls[0]['context'])
        self.assertNotIn('new2:',self.calls[0]['instruction'])
        self.assertEqual(set(result['sentences'][0]),{'text','source_refs'})

    def test_new2_is_single_stage_for_every_scope(self):
        from snapdart.data_access import prompts_new2
        for company,keyword in ((False,None),(True,None),(False,'HBM'),(True,'HBM')):
            with self.subTest(company=company,keyword=keyword),tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
                self.calls=[]
                result=self.run_profile('new2',folder,company=company,keyword=keyword)
                self.assertEqual(len(self.calls),1)
                call=self.calls[0]
                self.assertNotIn('evidence_plan',call['context'])
                self.assertNotIn('generation_stage',call['context'])
                self.assertNotIn('facts',call['schema']['properties'])
                self.assertNotIn('사실 정리',result['method'])
                self.assertEqual(result['prompt_version'],prompts_new2.VERSION)
                self.assertTrue(any(s['source_refs'] for s in result['sentences']))
                if not keyword:self.assertEqual(result['sentences'][0]['source_refs'],[])
                self.assertTrue(all(self.last_report['citations'][ref]['source_kind']=='filing'
                                    for sentence in result['sentences'] for ref in sentence['source_refs']))
                self.assertEqual(set(result['sentences'][0]),{'text','source_refs'})
                function='keyword' if keyword else 'company' if company else 'insight'
                instruction=prompts_new2.instruction(function)
                self.assertTrue(call['instruction'].startswith(instruction))
                if not keyword:
                    self.assertIn('재무',call['instruction'])
                    self.assertEqual(call['schema']['properties']['sentences']['maxItems'],3)
                    self.assertIn('실제',call['context']['task'])
                else:
                    self.assertEqual(instruction,prompts.instruction(function))

    def test_new2_profile_and_cache_do_not_reuse_discarded_plan(self):
        from snapdart.data_access import prompts_new2
        self.assertFalse(getattr(prompts_new2,'TWO_STAGE',False))
        self.assertNotEqual(prompts_new2.VERSION,'bigin-user-2026-10-10-new2-v1')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            self.run_profile('new',folder,company=True)
            result=self.run_profile('new2',folder,company=True)
            self.assertEqual(len(self.calls),2)
            self.assertEqual(result,self.run_profile('new2',folder,company=True))
            self.assertEqual(len(self.calls),2)
            self.assertEqual(len(list(Path(folder).rglob('*.json'))),2)
            self.assertFalse(list(Path(folder).rglob('*-plan.json')))

    def test_new2_context_changes_industry_and_company_only(self):
        from snapdart.data_access import prompts_new2
        for company,keyword in ((None,'HBM'),('기업가','HBM')):
            self.assertEqual(prompts_new2.context('테스트',[],[],company,keyword),
                prompts.context('테스트',[],[],company,keyword))
        original=prompts.context('테스트',[{'company':'기업가'}],[{'id':'t1'}],'기업가')
        updated=prompts_new2.context('테스트',[{'company':'기업가'}],[{'id':'t1'}],'기업가')
        self.assertEqual({k:v for k,v in original.items() if k!='task'},
            {k:v for k,v in updated.items() if k!='task'})
        self.assertIn('재무',updated['task'])
        self.assertNotEqual(prompts_new2.context('테스트',[],[])['task'],prompts.context('테스트',[],[])['task'])

    def test_old_stays_single_stage(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:result=self.run_profile('old',folder,company=True)
        self.assertEqual(len(self.calls),1)
        self.assertNotIn('근거 사실 정리',result['method'])
        self.assertNotIn('maxItems',self.calls[0]['schema']['properties']['sentences'])

    def test_definition_sections_are_embedded_without_numbered_list_truncation(self):
        import re
        from snapdart.data_access import prompts_new2
        from dart_remote import citation_selection_new2
        root=Path(__file__).resolve().parents[1]
        definition=(root/'docs/4차구상/프롬프트_정의서_new2.md').read_text(encoding='utf-8-sig')
        definition=definition.replace('<u>','').replace('</u>','')
        normalize=lambda text:re.sub(r'\s+',' ',text).strip()
        for name in ('COMMON','INSIGHT','COMPANY','NUMERIC_CLAIMS','RETRIEVAL'):
            with self.subTest(name=name):self.assertIn(normalize(getattr(prompts_new2,name)),normalize(definition))
        self.assertIn(normalize(citation_selection_new2.INSTRUCTION),normalize(definition))
        self.assertIn('고객 화면 각주는 자연어 공시만 표시',prompts_new2.instruction('company'))


@patch.dict(os.environ, {'INSIGHT_VALIDATION_MODE': 'strict'})
class RetrievalContextTests(unittest.TestCase):
    def row(self,year=2025,code='000001',report_type='Q3',suffix=''):
        month={'Q3':'09','FY':'12'}[report_type]
        return dict(year=year,stock_code=code,report_type=report_type,period=f'{year}-{month}',
            chunk_id=f'{code}-{year}-{report_type}-{suffix}',company=code,text='고성능 제품 수요에 대응한 생산능력 확대를 계획하고 있습니다.')

    def test_historical_search_preserves_company_period_and_budget(self):
        rows=[self.row(code=str(i)) for i in range(8)]
        repo=Mock();repo.search.side_effect=lambda query,code,year,report_type,**kw:([self.row(year,code,report_type)],{})
        result=retrieval_context.historical_anchors(repo,rows,[2023,2024,2025],'HBM')
        self.assertEqual(repo.search.call_count,4)
        self.assertEqual(len(result),12)
        self.assertTrue(all(r['year']==2024 and r['report_type']=='Q3' for r in result[8:]))
        self.assertTrue(all(c.kwargs==dict(top_k=1,business_only=True) for c in repo.search.call_args_list))

    def test_wrong_company_or_report_cannot_enter_comparison(self):
        row=self.row();repo=Mock()
        for hit in (self.row(2024,'other'),self.row(2024,report_type='FY'),self.row(2025)):
            repo.search.return_value=([hit],{})
            self.assertEqual(retrieval_context.historical_anchors(repo,[row],[2024,2025],'HBM'),[row])

    def test_context_preserves_original_ids_offsets_and_small_budget(self):
        text='매출액 | 100억원\n'+'고성능 제품 수요에 대응한 생산능력 확대를 계획하고 있습니다.'+'\n계획은 시장 상황에 따라 변경될 수 있습니다.'
        passages=[dict(p,id='t1-p'+str(i)) for i,p in enumerate(selection.passages(text),1)]
        evidence=[dict(id='t1',kind='filing',text=text,passages=passages)]
        original=[(p['id'],p['start'],p['end'],p['text']) for p in passages]
        with patch.dict(os.environ,{'CITATION_CONTEXT_CHAR_BUDGET':'30'}):retrieval_context.add_context(evidence)
        self.assertEqual(original,[(p['id'],p['start'],p['end'],p['text']) for p in passages])
        self.assertLessEqual(sum(len(p.get(k,'')) for p in passages for k in ('context_before','context_after')),30)
        self.assertNotIn('100억원',[p['text'] for p in passages])


if __name__=='__main__':unittest.main()
