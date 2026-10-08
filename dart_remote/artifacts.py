"""Application artifacts, independent of the read-only DART database."""
import hashlib
import json
import os
import sqlite3
import time
import uuid
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

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
                value=session.get(url,params={'alt':'media','ifGenerationMatch':generation},timeout=30)
                if value.status_code in (404,412):continue
                value.raise_for_status();return value.json(),generation
        raise RuntimeError('공유 캐시가 갱신 중입니다. 다시 실행하세요.')
    path=ROOT/name
    return (json.loads(path.read_text(encoding='utf-8')),path.stat().st_mtime_ns) if path.exists() else (None,0)

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
