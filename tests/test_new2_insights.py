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
from dart_remote import insight_plan, retrieval_context, citation_selection as selection


class New2InsightTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.plan_override=None
        self.final_ref='t1'
        self.fact_count=1
        self.llm=types.SimpleNamespace(PROVIDER='offline-test',MODEL='offline-test',TEXT={'type':'string'},
            object_schema=lambda props:dict(type='object',properties=props,required=list(props)),request_report=self.request)
        text='AI 서버의 수요에 대응하여 생산능력 확대를 계획하고 있습니다.'
        self.rows=[dict(sector_id='test',chunk_id='chunk'+str(i),receipt_no='receipt'+str(i),company='기업가',
            year=2025,period='2025-12',report_name='사업보고서',section='사업',heading='생산',
            text=text,anchor_start=0) for i in (1,2)]
        self.financial=dict(year=2025,basis='CFS',revenue=None,operating_income=None,capex=None,
            operating_cashflow=None,yoy={},margin=None,fcf=None,financial_sources={})
        self.company=dict(code='000001',name='기업가',history=[self.financial])
        self.repo=types.SimpleNamespace(sector=types.SimpleNamespace(id='test',name='테스트'),
            financial=lambda *a,**k:dict(self.financial,report_type=a[2]),search=lambda *a,**k:(self.rows,{}))

    def request(self,context,evidence,**options):
        self.calls.append(dict(context=copy.deepcopy(context),**options))
        if 'facts' in options['schema']['properties']:
            value=self.plan_override if self.plan_override is not None else dict(facts=[
                dict(fact=f'생산능력 확대 계획의 근거 사실 {i}',state='planned',
                    support=[dict(id='t1',passage_ids=['t1-p1'])]) for i in range(self.fact_count)],insufficient_reason='')
        else:
            eid=self.final_ref
            value=dict(sentences=[dict(text='생산능력 확대를 계획하고 있습니다.',refs=[eid],
                assessments=[dict(id=eid,grades=dict(F=4,U=4,C=4,T=4),suitable=True,reason='직접 원문',
                    irrelevant_content='none',redundancy='none',passage_ids=[eid+'-p1'])])],insufficient_reason='')
        return dict(report=options['validator'](copy.deepcopy(value),evidence),usage={},model='offline-test')

    def run_profile(self,profile,folder,company=False,keyword=None,force=False):
        report=dict(companies=[self.company],years=[2025],citations={},wordcloud={})
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

    def test_two_stages_and_correct_limits_for_all_scopes(self):
        for company,keyword,limit in ((False,None,10),(True,None,5),(False,'HBM',5),(True,'HBM',5)):
            with self.subTest(company=company,keyword=keyword),tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
                self.calls=[];self.fact_count=limit
                result=self.run_profile('new2',folder,company=company,keyword=keyword)
                self.assertEqual(len(self.calls),2)
                self.assertEqual(self.calls[0]['context']['max_facts'],limit)
                self.assertEqual(self.calls[0]['schema']['properties']['facts']['maxItems'],limit)
                self.assertFalse(self.calls[0]['allow_repair'])
                self.assertEqual(len(self.calls[1]['context']['evidence_plan']['facts']),limit)
                self.assertEqual(self.calls[1]['context']['evidence_plan']['facts'][0]['support'][0]['company'],'기업가')
                self.assertEqual(len(result['sentences']),1)
                self.assertIn('중요',self.calls[1]['instruction'])
                self.assertEqual(set(result['sentences'][0]),{'text','source_refs'})

    def test_empty_plan_skips_writer_and_keeps_explicit_reason(self):
        self.plan_override=dict(facts=[],insufficient_reason='직접적인 사업 근거 부족')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:result=self.run_profile('new2',folder)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(result['sentences'],[])
        self.assertEqual(result['insufficient_reason'],'직접적인 사업 근거 부족')

    def test_bad_plan_never_reaches_writer(self):
        self.plan_override=dict(facts=[dict(fact='사업 계획',state='planned',support=[dict(id='missing',passage_ids=['x'])])],insufficient_reason='')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder,self.assertRaisesRegex(ValueError,'청크 ID'):
            self.run_profile('new2',folder)
        self.assertEqual(len(self.calls),1)

    def test_over_limit_is_rejected_not_silently_truncated(self):
        self.fact_count=6
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder,self.assertRaisesRegex(ValueError,'최대 5개'):
            self.run_profile('new2',folder,company=True)
        self.assertEqual(len(self.calls),1)

    def test_unplanned_final_citation_is_rejected(self):
        self.final_ref='t2'
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder,self.assertRaisesRegex(ValueError,'사실 정리에 없는'):
            self.run_profile('new2',folder)

    def test_profiles_have_separate_caches_and_cached_plan_is_revalidated(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            self.run_profile('new',folder)
            result=self.run_profile('new2',folder)
            self.assertEqual(len(self.calls),3)
            cached=self.run_profile('new2',folder)
            self.assertEqual(len(self.calls),3)
            self.assertEqual(result,cached)
            paths=list(Path(folder).rglob('*-plan.json'))
            self.assertEqual(len(paths),1)
            for sentence in cached['sentences']:
                self.assertTrue(sentence['source_refs'])
            final=next(p for p in Path(folder).rglob('*.json') if not p.name.endswith('-plan.json')
                and '_evidence_plan' in json.loads(p.read_text(encoding='utf-8')).get('report',{}))
            corrupted=json.loads(final.read_text(encoding='utf-8'))
            corrupted['report']['_evidence_plan']['facts'][0]['support'][0]['id']='missing'
            final.write_text(json.dumps(corrupted,ensure_ascii=False),encoding='utf-8')
            self.run_profile('new2',folder)
            # Regenerate only the final draft; the intact planning cache is reused.
            self.assertEqual(len(self.calls),4)

    def test_old_stays_single_stage(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:result=self.run_profile('old',folder,company=True)
        self.assertEqual(len(self.calls),1)
        self.assertNotIn('근거 사실 정리',result['method'])
        self.assertNotIn('maxItems',self.calls[0]['schema']['properties']['sentences'])


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
