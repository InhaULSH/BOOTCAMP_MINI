import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
from dart_remote.generation import CachedRepository,generate_all
from dart_remote.token_counts import cached_count
from snapdart import llm


class GenerationConcurrencyTests(unittest.TestCase):
    def report(self):
        company=dict(name='기업',code='A',ai_insights={},wordcloud={'2025':[dict(text='제품')]})
        return dict(companies=[company],years=[2025],citations={},ai_insights={},wordcloud={'2025':[dict(text='수요')]})

    def test_all_jobs_overlap_and_keep_claim_specific_citations(self):
        report=self.report();barrier=threading.Barrier(2);lock=threading.Lock();calls=[]
        def generate(scope,isolated,repo,company,force,keyword=None):
            with lock:calls.append((company is not None,keyword))
            barrier.wait(timeout=3)
            text=keyword or ('기업' if company else '산업')
            isolated['citations']['same']=dict(quote='원문',summary_text=text)
            return dict(sentences=[dict(text=text,source_refs=['same'])])
        with patch.dict('os.environ',{'GEMINI_CONCURRENCY':'2'}):generate_all(report,SimpleNamespace(),generate)
        self.assertEqual(len(calls),4)
        results=[report['ai_insights']['2025'],report['keyword_insights']['2025']['수요'],report['companies'][0]['ai_insights']['2025'],report['companies'][0]['keyword_insights']['2025']['제품']]
        for result in results:
            sentence=result['sentences'][0]
            self.assertEqual(report['citations'][sentence['source_refs'][0]]['summary_text'],sentence['text'])

    def test_failure_does_not_run_remaining_queued_work(self):
        report=self.report();calls=[]
        def generate(*args,**kwargs):calls.append(1);raise ValueError('validation failed')
        with patch.dict('os.environ',{'GEMINI_CONCURRENCY':'1'}),self.assertRaises(ValueError):
            generate_all(report,SimpleNamespace(),generate)
        self.assertEqual(len(calls),1)

    def test_reused_repository_results_are_independent(self):
        source=SimpleNamespace(financial=Mock(return_value={'value':1}))
        repo=CachedRepository(source)
        repo.financial('A',2025)['value']=99
        self.assertEqual(repo.financial('A',2025)['value'],1)
        self.assertEqual(source.financial.call_count,1)

    def test_exact_token_count_cache_keeps_model_and_payload_separate(self):
        fetch=Mock(return_value=123)
        payload={'unique_test':'concurrency','contents':[1]}
        self.assertEqual(cached_count(payload,'model1',fetch),123)
        self.assertEqual(cached_count(payload,'model1',fetch),123)
        cached_count(payload,'model2',fetch)
        cached_count(dict(payload,contents=[2]),'model1',fetch)
        self.assertEqual(fetch.call_count,3)

    def test_local_quota_reservations_are_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        limiter=llm.TokenBudget()
        with patch.dict('os.environ',{'GEMINI_RPM_BUDGET':'10','GEMINI_TPM_BUDGET':'225000'}):
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(limiter.reserve,[100]*10))
        self.assertEqual(len(limiter.events),10)

    def test_shared_sqlite_quota_reservations_are_atomic(self):
        import tempfile,sqlite3
        from contextlib import closing
        from pathlib import Path
        from concurrent.futures import ThreadPoolExecutor
        from dart_remote import artifacts
        with tempfile.TemporaryDirectory() as temp,patch.object(artifacts,'ROOT',Path(temp)),patch.dict('os.environ',{'GEMINI_RPM_BUDGET':'10','GEMINI_TPM_BUDGET':'225000','SERVICE_GCS_BUCKET':'','K_SERVICE':''}):
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(artifacts.reserve,[100]*10))
            with closing(sqlite3.connect(Path(temp)/'quota.sqlite3')) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],10)

    def test_default_runs_four_tasks_concurrently(self):
        import os
        report=self.report();barrier=threading.Barrier(4);calls=[];lock=threading.Lock()
        def generate(*args,**kwargs):
            with lock:calls.append(1)
            barrier.wait(timeout=3)
            return dict(sentences=[])
        with patch.dict('os.environ'):
            os.environ.pop('GEMINI_CONCURRENCY',None)
            generate_all(report,SimpleNamespace(),generate)
        self.assertEqual(len(calls),4)
