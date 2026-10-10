"""Application artifacts, independent of the read-only DART database."""
import hashlib
import json
import os
import sqlite3
import time
import uuid
import tempfile
from requests import HTTPError
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
from .runtime_cache import Cache
_json_cache=Cache(max_entries=64)
_home_cache=Cache(max_entries=32,max_bytes=2*1024*1024)

BASE=Path(__file__).resolve().parents[1]
DEFAULT_ROOT=BASE/'data/service/remote' if (BASE/'snapdart').is_dir() else BASE.parent/'data/service/remote' if (BASE.parent/'snapdart').is_dir() else Path(tempfile.gettempdir())/'dart-bigin-cache'
ROOT=Path(os.getenv('SERVICE_CACHE_DIR') or str(DEFAULT_ROOT)).resolve()

def _name(sector,kind,key):
    return '/'.join(quote(str(v),safe='') for v in (sector,kind,key))+'.json'

def _session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/devstorage.read_write'])
    return AuthorizedSession(credentials)

def read_versioned(sector,kind,key='current'):
    name=_name(sector,kind,key);bucket=os.getenv('SERVICE_GCS_BUCKET')
    if bucket:
        url='https://storage.googleapis.com/storage/v1/b/'+quote(bucket,safe='')+'/o/'+quote(name,safe='')
        with _session() as session:
            for _ in range(3):
                meta=session.get(url,timeout=30)
                if meta.status_code==404:return None,0
                meta.raise_for_status();generation=int(meta.json()['generation'])
                def download():
                    value=session.get(url,params={'alt':'media','ifGenerationMatch':generation},timeout=30)
                    value.raise_for_status();return value.json()
                try:
                    if sector=='_system':return download(),generation
                    payload=_json_cache.get((bucket,name),generation,download,size=lambda v:len(json.dumps(v).encode('utf-8')))
                    return payload,generation
                except HTTPError as error:
                    if error.response is not None and error.response.status_code in (404,412):continue
                    raise
        raise RuntimeError('공유 캐시가 갱신 중입니다. 다시 실행하세요.')
    path=ROOT/name
    for _ in range(3):
        try:before=path.stat()
        except FileNotFoundError:return None,0
        stamp=(before.st_mtime_ns,before.st_ctime_ns,before.st_size,before.st_ino)
        def read():return json.loads(path.read_text(encoding='utf-8'))
        try:
            payload=read() if sector=='_system' else _json_cache.get(str(path),stamp,read,size=before.st_size)
            after=path.stat()
        except FileNotFoundError:continue
        if stamp==(after.st_mtime_ns,after.st_ctime_ns,after.st_size,after.st_ino):return payload,after.st_mtime_ns
    raise RuntimeError('저장 파일이 갱신 중입니다. 다시 실행하세요.')

def get_artifact(sector,kind,key='current'):
    return read_versioned(sector,kind,key)[0]

def put_artifact(sector,kind,payload,key='current',generation=None):
    name=_name(sector,kind,key);content=json.dumps(payload,ensure_ascii=False,allow_nan=False)
    bucket=os.getenv('SERVICE_GCS_BUCKET')
    if bucket:
        params={'uploadType':'media','name':name}
        if generation is not None:params['ifGenerationMatch']=generation
        response=_session().post('https://storage.googleapis.com/upload/storage/v1/b/'+quote(bucket,safe='')+'/o',
            params=params,data=content.encode('utf-8'),headers={'Content-Type':'application/json'},timeout=30)
        if response.status_code==412:return False
        response.raise_for_status();return True
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:temporary.write_text(content,encoding='utf-8');temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    return True


def report_version():
    """Display selection is independent of the generation prompt selection."""
    version=os.getenv('REPORT_PROMPT_VERSION','new')
    if version not in ('new','new2','old'):
        raise ValueError('REPORT_PROMPT_VERSION은 new, new2 또는 old여야 합니다.')
    return version


def identify_report(report):
    if not report:return None
    explicit=report.get('report_prompt_version')
    if explicit in ('new','new2','old'):return explicit
    versions={insight.get('prompt_version') for scope in [report]+report.get('companies',[])
              for insight in list(scope.get('ai_insights',{}).values())+
              [item for entries in scope.get('keyword_insights',{}).values() for item in entries.values()]
              if insight.get('prompt_version')}
    profiles=set()
    for version in versions:
        if version.startswith('bigin-user-'):
            profiles.add('new2' if '-new2-' in version else 'new')
        elif version.startswith('bigin-pdf-'):profiles.add('old')
        else:return None
    return next(iter(profiles)) if len(profiles)==1 else None


def selected_report(sector):
    version=report_version()
    report=get_artifact(sector,'report','prompt-'+version)
    if report is not None:
        if identify_report(report)!=version:raise RuntimeError('보고서 캐시의 프롬프트 버전이 일치하지 않습니다.')
        return report
    # Only a positively identified legacy report may be used; never mix versions.
    legacy=get_artifact(sector,'report')
    return legacy if identify_report(legacy)==version else None


def publish_report(sector,report,version=None):
    """Called only after the entire build and dataset checks succeed."""
    previous=get_artifact(sector,'report')
    previous_version=identify_report(previous)
    if previous_version and get_artifact(sector,'report','prompt-'+previous_version) is None:
        put_artifact(sector,'report',previous,'prompt-'+previous_version)
    if version is not None:
        if version not in ('new','new2','old'):raise ValueError('잘못된 프롬프트 버전')
        report=dict(report,report_prompt_version=version)
        put_artifact(sector,'report',report,'prompt-'+version)
    put_artifact(sector,'report',report)
    return report

def reserve(tokens):
    reserved=int(tokens*1.05)+1024
    tpm=int(os.getenv('GEMINI_TPM_BUDGET','225000'));rpm=int(os.getenv('GEMINI_RPM_BUDGET','10'))
    if tpm<=0 or rpm<=0 or reserved>tpm:raise RuntimeError('단일 요청이 Gemini 안전 예산을 초과합니다. 입력을 줄이세요.')
    bucket=hashlib.sha256((os.getenv('GEMINI_QUOTA_BUCKET','snapdart')+os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite')).encode()).hexdigest()
    while True:
        now=time.time()
        if os.getenv('SERVICE_GCS_BUCKET'):
            value,generation=read_versioned('_system','quota',bucket)
            events=[r for r in (value or {}).get('events',[]) if r[0]>now-61]
            if len(events)<rpm and sum(r[1] for r in events)+reserved<=tpm:
                if put_artifact('_system','quota',{'events':events+[[now,reserved]]},bucket,generation):return
                continue
            delay=min(10,max(.1,events[0][0]+61-now))
        else:
            if os.getenv('K_SERVICE'):raise RuntimeError('Cloud Run의 Gemini 공유 사용량 제어를 위해 SERVICE_GCS_BUCKET을 설정하세요.')
            ROOT.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(ROOT/'quota.sqlite3',timeout=15)) as con, con:
                con.execute('CREATE TABLE IF NOT EXISTS reservations(bucket TEXT,created REAL,tokens INTEGER)')
                con.execute('BEGIN IMMEDIATE')
                con.execute('DELETE FROM reservations WHERE created<=?',(now-61,))
                count,usage,oldest=con.execute('SELECT COUNT(*),COALESCE(SUM(tokens),0),MIN(created) FROM reservations WHERE bucket=?',(bucket,)).fetchone()
                if count<rpm and usage+reserved<=tpm:
                    con.execute('INSERT INTO reservations VALUES(?,?,?)',(bucket,now,reserved));return
                delay=min(10,max(.1,oldest+61-now))
        time.sleep(delay)


def home_summary(sector):
    """Only home-relevant fields survive this cache; reports remain unchanged."""
    def load():
        report=selected_report(sector) or {}
        market=get_artifact(sector,'market') or {}
        from .market_summary import index_market_cap
        index=market.get('index',{})
        return dict(entries=[sector+':'+c['code'] for c in report.get('companies',[])],
            reportAvailable=bool(report),indexName=index.get('name'),indexSeries=index.get('history',[]),
            indexReturnPct=index.get('change'),tradedAt=index.get('traded_at',''),cap=index_market_cap(market))
    # GCS reads keep checking generations; no hidden stale remote object cache.
    if os.getenv('SERVICE_GCS_BUCKET'):return load()
    from datetime import datetime,timedelta,timezone
    stamps=[datetime.now(timezone(timedelta(hours=9))).date().isoformat()]
    for kind,key in (('report','current'),('report','prompt-'+report_version()),('market','current')):
        path=ROOT/_name(sector,kind,key)
        try:
            st=path.stat();stamp=(st.st_mtime_ns,st.st_ctime_ns,st.st_size,st.st_ino)
        except FileNotFoundError:stamp=None
        stamps.append(stamp)
    return _home_cache.get((str(ROOT),sector,report_version()),tuple(stamps),load,
        size=lambda value:len(json.dumps(value,ensure_ascii=False).encode('utf-8')))
