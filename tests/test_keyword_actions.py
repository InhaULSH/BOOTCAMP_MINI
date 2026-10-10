import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
from dart_remote import keyword_actions as actions
from dart_remote.keyword_fallback import result

class KeywordActionTests(unittest.TestCase):
    def setUp(self):
        actions._last_attempt=0
        self.company=dict(code='1',name='기업가',wordcloud={'2025':[dict(text='HBM')]},keyword_insights={'2025':{'HBM':result('HTTP 503')}})
        self.report=dict(years=[2023,2024,2025],companies=[self.company],wordcloud={'2025':[dict(text='HBM')]},
            keyword_insights={'2025':{'HBM':result('HTTP 503')}},source=dict(dataset_sha256='version'),citations={})
        self.repo=SimpleNamespace(sector=SimpleNamespace(id='sector',membership_code='KRX_SEMI'),fingerprint=lambda:'version')
        self.saved={}
        self.patches=[patch.object(actions,'Repository',return_value=self.repo),
            patch.object(actions.artifacts,'get_artifact',side_effect=lambda s,k,key:self.saved.get((k,key))),
            patch.object(actions.artifacts,'put_artifact',side_effect=lambda s,k,p,key:self.saved.__setitem__((k,key),p)),
            patch.object(actions.artifacts,'report_version',return_value='new')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.load=lambda sector:self.report
    def test_most_mentions_per_company_receipt_and_duplicate_chunk(self):
        other=dict(self.company,code='2',name='기업나');self.report['companies'].append(other)
        self.repo.documents=lambda code:[dict(rcept_no=r,year=2025,report_name='사업보고서',rcept_dt=r) for r in ('20250301000001','20250301000002')]
        def chunks(code,year):
            if year!=2025:return []
            a=dict(chunk_id=code+'a',rcept_no='20250301000001',chunk_text='HBM HBM3E 고대역폭 메모리')
            b=dict(chunk_id=code+'b',rcept_no='20250301000002',chunk_text='HBM')
            return [a,a,b]
        self.repo.chunks=chunks
        response=actions.related_filings('sector',None,'HBM',self.load)
        self.assertEqual(len(response['documents']),2)
        self.assertTrue(all(d['receipt_no']=='20250301000001' and d['mentions']==3 for d in response['documents']))
        self.assertEqual(len(actions.related_filings('sector','1','HBM',self.load)['documents']),1)
    def test_unlisted_keyword_rejected_before_chunk_read(self):
        with self.assertRaises(KeyError):actions.related_filings('sector',None,'password',self.load)
    def test_retry_only_for_transient_failure(self):
        generate=Mock()
        for message in ('근거 부족','응답 검증 실패','HTTP 403'):
            self.report['keyword_insights']['2025']['HBM']=result(message)
            response=actions.retry_keyword('sector',None,'HBM',self.load,generate)
            self.assertFalse(response['retry_allowed'])
        generate.assert_not_called()
    def test_success_keeps_citations_and_does_not_rewrite_report(self):
        def generate(scope,report,repo,company,force,keyword):
            self.assertTrue(force);self.assertEqual(keyword,'HBM')
            report['citations']['ref']=dict(quote='원문',chunk_id='c')
            return dict(sentences=[dict(text='설명',source_refs=['ref'])])
        response=actions.retry_keyword('sector',None,'HBM',self.load,generate)
        ref=response['insight']['sentences'][0]['source_refs'][0]
        self.assertTrue(ref.startswith('retry-'));self.assertIn(('keyword-source',ref),self.saved)
        self.assertEqual(self.report['citations'],{})
        self.assertEqual(actions.retry_keyword('sector',None,'HBM',self.load,Mock(side_effect=AssertionError())),response)
    def test_retry_failure_throttled_and_diagnostics_hidden(self):
        generate=Mock(side_effect=RuntimeError('HTTP 503 private'))
        first=actions.retry_keyword('sector',None,'HBM',self.load,generate)
        self.assertNotIn('private',json.dumps(first))
        second=actions.retry_keyword('sector',None,'HBM',self.load,generate)
        self.assertGreater(second['retry_after'],0);self.assertEqual(generate.call_count,1)
    def test_transient_vs_permanent_messages(self):
        self.assertTrue(result('HTTP 429')['retryable'])
        self.assertTrue(result('네트워크 연결 실패')['retryable'])
        self.assertFalse(result('HTTP 403')['retryable'])
        self.assertEqual(result('응답 검증 실패')['insufficient_reason'],'최근 공시에서 의미 있게 포착된 키워드이지만, 설명과 근거의 일치 여부를 충분히 확인하지 못했습니다.')
    def test_prompt_override_is_scoped_to_retry(self):
        from dart_remote.prompt_context import active_version,using_version
        from snapdart.data_access import prompts,prompts_new2
        with patch.dict('os.environ',{'LLM_PROMPT_VERSION':'new'}):
            with using_version('new2'):self.assertIs(prompts.active(),prompts_new2)
            self.assertIsNone(active_version());self.assertIs(prompts.active(),prompts)
    def test_local_keyword_routes(self):
        from app import Handler
        from io import BytesIO
        from email.message import Message
        handler=object.__new__(Handler);handler.path='/api/keyword-filings?sector=sector&keyword=HBM'
        handler.send_json=Mock();handler.send_error=Mock()
        with patch.object(actions,'related_filings',return_value={'documents':[]}) as related:handler.do_GET()
        related.assert_called_once();handler.send_json.assert_called_with({'documents':[]})
        body=json.dumps(dict(sector='sector',keyword='HBM')).encode()
        handler.path='/api/keyword-retry';handler.headers=Message();handler.headers['Content-Type']='application/json'
        handler.headers['Content-Length']=str(len(body));handler.headers['Host']='localhost:8501';handler.headers['Origin']='http://localhost:8501'
        handler.rfile=BytesIO(body)
        with patch.object(actions,'retry_keyword',return_value={'insight':{}}) as retry:handler.do_POST()
        retry.assert_called_once()
        handler.headers.replace_header('Origin','https://other.example')
        with patch.object(actions,'retry_keyword') as retry:handler.do_POST()
        retry.assert_not_called();handler.send_error.assert_called_with(403)
    def test_cloud_keyword_routes(self):
        import sys
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'));self.addCleanup(sys.path.pop,0)
        from cloudapp.main import app
        from fastapi.testclient import TestClient
        with patch.dict('os.environ',{'NO_MARKET_REFRESH':'1','UI_PREWARM':'0'}),TestClient(app) as client:
            with patch.object(actions,'related_filings',return_value={'documents':[]}):
                self.assertEqual(client.get('/api/keyword-filings?sector=sector&keyword=HBM').json(),{'documents':[]})
            with patch.object(actions,'retry_keyword',return_value={'insight':{}}) as retry:
                self.assertEqual(client.post('/api/keyword-retry',json={'sector':'sector','keyword':'HBM'}).status_code,200)
                self.assertEqual(client.post('/api/keyword-retry',json={'sector':'sector','keyword':'HBM'},headers={'Origin':'https://other.example'}).status_code,403)
                self.assertEqual(retry.call_count,1)

if __name__=='__main__':unittest.main()
