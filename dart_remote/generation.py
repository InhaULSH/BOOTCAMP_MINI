"""Bounded generation concurrency and per-build reuse; output rules are unchanged."""
import copy
import hashlib
import json
import os
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED


class CachedRepository:
    """Serialize shared retrieval/model access, reuse reads only for this build."""
    METHODS={'financial','search','select_evidence'}
    def __init__(self, repository):
        self.repository=repository;self.cache={};self.lock=threading.RLock()
    def __getattr__(self, name):
        method=getattr(self.repository,name)
        if name not in self.METHODS:return method
        def call(*args,**kwargs):
            key=(name,repr((args,sorted(kwargs.items()))))
            with self.lock:
                if key not in self.cache:self.cache[key]=method(*args,**kwargs)
                return copy.deepcopy(self.cache[key])
        return call


def merge_citations(report,result,citations):
    """Keep claim-specific grades/summary separate when the same quote is reused."""
    mapping={}
    for key,entry in citations.items():
        target=key
        if key in report['citations'] and report['citations'][key]!=entry:
            target=key+'-'+hashlib.sha256(json.dumps(entry,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]
        report['citations'][target]=entry;mapping[key]=target
    for sentence in result.get('sentences',[]):
        sentence['source_refs']=[mapping.get(key,key) for key in sentence.get('source_refs',[])]
    return result


def generate_all(report,repository,generate,force=False):
    year=str(report['years'][-1]);repo=CachedRepository(repository);jobs=[]
    for scope,company in [(report,None)]+[(c,c) for c in report['companies']]:
        scope['keyword_insights']={year:{}}
        jobs.append((scope,company,None))
        jobs.extend((scope,company,item['text']) for item in scope.get('wordcloud',{}).get(year,[])[:30])
    workers=max(1,min(4,int(os.getenv('GEMINI_CONCURRENCY','4'))))
    print(f'인사이트 생성: {len(jobs)}개 작업 · 최대 {workers}개 동시 실행 · Gemini 공통 사용량 예산 적용',flush=True)
    def run(job):
        scope,company,keyword=job
        isolated=dict(report,citations={})
        try:result=generate(scope,isolated,repo,company,force,keyword=keyword)
        except (RuntimeError,ValueError,OSError) as error:
            if not keyword:raise
            logging.getLogger(__name__).warning('Keyword explanation unavailable: %s',error)
            from .keyword_fallback import result as fallback
            result=fallback(error)
        if keyword and not result.get('sentences'):
            from .keyword_fallback import result as fallback
            result=fallback(result.get('insufficient_reason','')) if not result.get('fallback_reason') else result
        return result,isolated['citations']
    iterator=iter(jobs);completed=0
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='insight') as executor:
        pending={}
        def submit():
            job=next(iterator,None)
            if job is not None:pending[executor.submit(run,job)]=job
        for _ in range(workers):submit()
        try:
            while pending:
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    scope,_,keyword=pending.pop(future)
                    result,citations=future.result()
                    result=merge_citations(report,result,citations)
                    if keyword:scope['keyword_insights'][year][keyword]=result
                    else:scope['ai_insights'][year]=result
                    completed+=1
                    print(f'인사이트 진행 {completed}/{len(jobs)}',flush=True)
                for _ in done:submit()
        except BaseException:
            for future in pending:future.cancel()
            raise  # Completed caches survive; the caller never publishes a partial report.
