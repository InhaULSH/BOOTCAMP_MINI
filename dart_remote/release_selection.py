"""Explicit physical release selection; upstream version flags stay untouched."""
import hashlib
import json
import os
import re
import time
from threading import RLock
from . import db
from . import analysis_validation as validation

VERSION='release-selection-v2'
_presence={}
_lock=RLock()

def financial_equivalence(registered,selected):
    """A whole SQLite file hash includes document references, not just amounts.

    Different hashes are accepted only for a logged document-ID-only patch of
    the immediately preceding release. This is a restricted migration contract,
    not a claim that arbitrary differing financial files have equal values.
    """
    hashes=[row.get('financial_sqlite_sha256') for row in (registered,selected)]
    if not all(isinstance(h,str) and re.fullmatch(r'[0-9a-fA-F]{64}',h) for h in hashes):
        raise ValueError('재무 내용 해시가 없거나 잘못되었습니다.')
    if hashes[0]==hashes[1]:return 'financial-file-hash'
    if not registered.get('created_at'):raise ValueError('재무 내용 해시가 다르고 등록 시점이 없습니다.')
    previous=db.rows('SELECT data_version FROM data_versions WHERE validated=1 AND created_at<:t ORDER BY created_at DESC LIMIT 1',{'t':registered['created_at']})
    runs=db.rows('SELECT * FROM sync_runs WHERE data_version=:v',{'v':registered['data_version']})
    if (len(previous)!=1 or previous[0]['data_version']!=selected['data_version'] or not runs
        or any(r['table_name']!='financial_metric_values_document_id' or r['status']!='success'
               or r['rows_inserted']!=0 or r['rows_deactivated']!=0
               or r['rows_updated']!=r['rows_source'] or not r['finished_at'] for r in runs)):
        raise ValueError('재무 내용 해시가 다르고 문서 ID만 수정한 동기화 이력이 확인되지 않습니다.')
    links=db.rows('''SELECT COUNT(*) n,SUM(CASE WHEN d.document_id IS NULL
        OR d.is_active<>1 OR d.rcept_no<>m.source_rcept_no THEN 1 ELSE 0 END) bad
        FROM financial_metric_values m LEFT JOIN filing_source_documents d
        ON d.document_id=m.source_document_id WHERE m.source_document_id IS NOT NULL''')[0]
    if links['bad'] or links['n']<max(r['rows_source'] for r in runs):
        raise ValueError('문서 ID 수정 후 재무 지표와 원문 연결이 유효하지 않습니다.')
    return 'document-id-only-patch'

def check_presence(selected,signature):
    connection=tuple(os.getenv(k,'') for k in ('MYSQL_HOST','MYSQL_PORT','MYSQL_DATABASE','MYSQL_USER','SQL_HOST_NAME','SQL_PORT','SQL_DEFAULT_SCHEMA','SQL_USER_NAME','CLOUD_SQL_INSTANCE'))
    key=(connection,signature)
    if validation.active():
        def check():
            for table in ('financial_facts','filings','coverage','chunk_metadata'):
                active=' AND is_active=1' if table!='coverage' else ''
                index=' AND index_version=:i AND is_searchable=1' if table=='chunk_metadata' else ''
                count=db.rows('SELECT COUNT(*) n FROM '+table+' WHERE data_version=:v'+active+index,
                              {'v':selected['data_version'],'i':selected['index_version']})[0]['n']
                if not count:raise ValueError(f'지정한 조회 버전의 {table} 자료가 없습니다. 다른 버전으로 자동 전환하지 않습니다.')
        return validation.once('physical-presence',key,check)
    with _lock:
        if time.monotonic()-_presence.get(key,float('-inf'))<30:return
        for table in ('financial_facts','filings','coverage','chunk_metadata'):
            active=' AND is_active=1' if table!='coverage' else ''
            index=' AND index_version=:i AND is_searchable=1' if table=='chunk_metadata' else ''
            count=db.rows('SELECT COUNT(*) n FROM '+table+' WHERE data_version=:v'+active+index,
                          {'v':selected['data_version'],'i':selected['index_version']})[0]['n']
            if not count:raise ValueError(f'지정한 조회 버전의 {table} 자료가 없습니다. 다른 버전으로 자동 전환하지 않습니다.')
        if len(_presence)>=16:_presence.clear()
        _presence[key]=time.monotonic()

def resolve():
    registered=db.rows('SELECT * FROM data_versions WHERE is_current=1')
    if len(registered)!=1 or not registered[0]['validated']:
        raise RuntimeError('검증된 현재 데이터 버전이 정확히 하나 있어야 합니다.')
    registered=registered[0]
    requested=os.getenv('SERVICE_DATA_VERSION','').strip()
    selected=registered
    if requested:
        found=db.rows('SELECT * FROM data_versions WHERE data_version=:v AND validated=1',{'v':requested})
        if len(found)!=1:raise ValueError('SERVICE_DATA_VERSION으로 지정한 검증된 버전이 없습니다.')
        selected=found[0]
        # Live, unversioned metric rows may not be attached to unrelated filings.
        for field in ('vector_sqlite_sha256','faiss_sha256'):
            value=selected.get(field)
            if not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',value) or value!=registered.get(field):
                raise ValueError(f'조회 버전과 등록 버전의 내용 해시({field})가 다릅니다. 버전을 임의로 혼합하지 않습니다.')
    def identity(row):
        return {k:row.get(k) for k in ('data_version','index_version','validated','financial_sqlite_sha256',
                                     'vector_sqlite_sha256','faiss_sha256','manifest_sha256')}
    signature=hashlib.sha256(json.dumps({'policy':VERSION,'registered':identity(registered),
                                       'selected':identity(selected)},sort_keys=True).encode()).hexdigest()
    equivalence=validation.once('financial-equivalence',signature,lambda:financial_equivalence(registered,selected)) if requested else 'registered-release'
    if requested:check_presence(selected,signature)
    return dict(registered=registered,selected=selected,explicit=bool(requested),signature=signature,equivalence=equivalence)
