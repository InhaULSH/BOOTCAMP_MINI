"""Scoped disclosure browsing and bounded, explicit keyword-only retries."""
import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from . import artifacts
from .repository import Repository
from .signal_keyword_rules import GENERIC_VOCABULARY,SECTOR_VOCABULARIES
from .keyword_fallback import result as fallback

_retry_lock=threading.Lock()
_last_attempt=0.0
RETRY_SECONDS=60

def selection(sector,code,keyword,load_report):
    if not isinstance(keyword,str) or not 1<=len(keyword)<=100:raise ValueError('키워드를 확인하세요.')
    repo=Repository(sector);report=load_report(repo.sector.id)
    company=None
    if code:
        company=next((c for c in report['companies'] if c['code']==code),None)
        if company is None:raise KeyError('분석 대상 기업이 아닙니다.')
    scope=company or report;year=str(report['years'][-1])
    keywords={r.get('text',r.get('keyword')) for r in scope.get('wordcloud',{}).get(year,[])[:30]}
    if keyword not in keywords:raise KeyError('현재 워드클라우드에 없는 키워드입니다.')
    return repo,report,scope,company,year

def mention_pattern(keyword,index_code):
    vocabulary=SECTOR_VOCABULARIES.get(index_code,GENERIC_VOCABULARY)
    normalize=lambda s:re.sub(r'\s+',' ',unicodedata.normalize('NFKC',s)).strip().casefold()
    canonical=normalize(keyword)
    surfaces={keyword}|{alias for alias,target in vocabulary.aliases.items() if normalize(target)==canonical}
    patterns=[]
    for surface in sorted(surfaces,key=lambda s:(-len(s),s)):
        term=r'\s*'.join(re.escape(p) for p in surface.split())
        patterns.append(r'(?<![A-Za-z0-9])'+term+r'(?![A-Za-z0-9])')
    return re.compile('|'.join(patterns),re.IGNORECASE)

def related_filings(sector,code,keyword,load_report):
    repo,report,scope,company,year=selection(sector,code,keyword,load_report)
    pattern=mention_pattern(keyword,repo.sector.membership_code)
    selected=[company] if company else report['companies'];output=[]
    for c in selected:
        documents={d['rcept_no']:d for d in repo.documents(c['code']) if d['year'] in report['years']}
        counts={};seen=set()
        for y in report['years']:
            for row in repo.chunks(c['code'],y):
                if row['chunk_id'] in seen:continue
                seen.add(row['chunk_id']);receipt=row['rcept_no']
                if receipt not in documents:continue
                count=len(pattern.findall(unicodedata.normalize('NFKC',row['chunk_text'])))
                counts[receipt]=counts.get(receipt,0)+count
        candidates=[r for r,n in counts.items() if n>0]
        if not candidates:continue
        receipt=max(candidates,key=lambda r:(counts[r],str(documents[r].get('rcept_dt') or ''),r))
        d=documents[receipt]
        output.append(dict(company=c['name'],code=c['code'],receipt_no=receipt,year=d['year'],
            report_name=d['report_name'],mentions=counts[receipt],document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt))
    return dict(keyword=keyword,years=report['years'],documents=output,
        note='현재 분석 기간의 활성 공시 청크에서 키워드와 등록된 동의어를 집계했습니다. 기업마다 언급 횟수가 가장 많은 공시 하나를 표시합니다.')

def retry_keyword(sector,code,keyword,load_report,generate):
    global _last_attempt
    repo,report,scope,company,year=selection(sector,code,keyword,load_report)
    key=hashlib.sha256(json.dumps([repo.fingerprint(),artifacts.report_version(),code,keyword],ensure_ascii=False).encode()).hexdigest()
    previous=artifacts.get_artifact(repo.sector.id,'keyword-retry',key)
    if previous and previous.get('insight',{}).get('sentences'):return previous
    original=scope.get('keyword_insights',{}).get(year,{}).get(keyword,{})
    state=previous.get('insight',original) if previous else original
    if not state.get('retryable') or state.get('fallback_reason') not in ('unavailable','rate_limit'):
        return dict(insight=state,retry_allowed=False)
    if not _retry_lock.acquire(blocking=False):return dict(insight=state,retry_after=RETRY_SECONDS)
    try:
        now=time.time();elapsed=now-max(_last_attempt,previous.get('attempted_at',0) if previous else 0)
        if elapsed<RETRY_SECONDS:return dict(insight=state,retry_after=max(1,int(RETRY_SECONDS-elapsed)))
        _last_attempt=now
        # Persist the reservation before model execution, including across restarts.
        artifacts.put_artifact(repo.sector.id,'keyword-retry',dict(insight=state,attempted_at=now),key)
        isolated=dict(report,citations={})
        try:
            from .prompt_context import using_version
            with using_version(artifacts.report_version()):
                insight=generate(scope,isolated,repo,company,force=True,keyword=keyword)
            if not insight.get('sentences'):insight=fallback(insight.get('insufficient_reason',''))
            if repo.fingerprint()!=report['source']['dataset_sha256']:raise RuntimeError('생성 중 데이터가 변경되었습니다.')
        except (RuntimeError,ValueError,OSError) as error:
            logging.getLogger(__name__).warning('Keyword retry failed: %s',error);insight=fallback(error)
        # Independent references avoid rewriting a shared successful report.
        mapping={}
        for ref,citation in isolated['citations'].items():
            target='retry-'+hashlib.sha256(json.dumps([key,ref,citation],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
            artifacts.put_artifact(repo.sector.id,'keyword-source',dict(citation=citation,fingerprint=report['source']['dataset_sha256'],prompt_version=artifacts.report_version()),target)
            mapping[ref]=target
        for sentence in insight.get('sentences',[]):sentence['source_refs']=[mapping[r] for r in sentence.get('source_refs',[])]
        response=dict(insight=insight,attempted_at=now)
        artifacts.put_artifact(repo.sector.id,'keyword-retry',response,key)
        return response
    finally:_retry_lock.release()
