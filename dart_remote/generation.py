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
            if not keyword:
                from .mvp_validation import enabled
                if not enabled():raise
                logging.getLogger(__name__).warning('MVP insight unavailable; company=%s error=%s',company and company['name'],error)
                return dict(sentences=[],insufficient_reason='현재 이 분석의 설명을 준비하지 못했습니다. 재무 그래프와 관련 공시를 먼저 확인해 주세요.',method='분석 설명 안내',validation_mode='mvp'),{}

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
            if job is not None:
                from .analysis_validation import submit as submit_analysis
                pending[submit_analysis(executor,run,job)]=job
        for _ in range(workers):submit()
        active_job=None
        try:
            while pending:
                done,_=wait(pending,timeout=30,return_when=FIRST_COMPLETED)
                if not done:
                    print(f'인사이트 응답 대기: {completed}/{len(jobs)} 완료 · {len(pending)}개 작업 처리 중',flush=True)
                    continue
                for future in done:
                    active_job=pending.pop(future)
                    scope,_,keyword=active_job
                    result,citations=future.result()
                    result=merge_citations(report,result,citations)
                    if keyword:scope['keyword_insights'][year][keyword]=result
                    else:scope['ai_insights'][year]=result
                    completed+=1
                    print(f'인사이트 진행 {completed}/{len(jobs)}',flush=True)
                for _ in done:submit()
        except BaseException as error:
            if active_job:
                scope,company,keyword=active_job
                label=company['name'] if company else report.get('sector_name','산업')
                print(f'분석 작업 실패: {label}'+(f' · 키워드 {keyword}' if keyword else '')+f' · {error}',flush=True)
            for future in pending:future.cancel()
            remaining={future for future in pending if not future.done()}
            if remaining:
                print(f'최종 실패 안내 전 종료 대기: 실행 중인 {len(remaining)}개 작업 · 추가 작업은 시작하지 않습니다. 기존 보고서는 보존됩니다.',flush=True)
            while remaining:
                _,remaining=wait(remaining,timeout=30,return_when=FIRST_COMPLETED)
                if remaining:print(f'종료 대기 중: 실행 중인 {len(remaining)}개 작업',flush=True)
            raise  # Completed caches survive; the caller never publishes a partial report.
