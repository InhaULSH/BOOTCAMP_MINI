"""KRX membership, not sector-specific copies of company data."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
from . import db
from .runtime_cache import request_value,scoped_catalog
from .artifacts import ROOT as SERVICE

BASE=Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Sector:
    id:str
    name:str
    membership_code:str
    data_version:str
    index_version:str
    index_code:str|None=None
    companies_order:tuple=()
    topics:tuple=('주요 사업 제품 고객 수요 시장 변화','설비투자 생산능력 연구개발 양산','경쟁 위험 가격 재고')
    terms:tuple=()
    profiles:dict|None=None

def _sectors(root=None,all_sectors=False):
    config_path=Path(os.getenv('SECTOR_CONFIG',str(BASE/'config/sectors.json')))
    config=json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    versions=db.rows('SELECT * FROM data_versions WHERE is_current=1')
    if len(versions)!=1 or not versions[0]['validated']:raise RuntimeError('검증된 현재 데이터 버전이 정확히 하나 있어야 합니다.')
    version=versions[0]
    allowed=set() if all_sectors else {v.strip() for v in os.getenv('SNAPDART_SECTORS','').split(',') if v.strip()}
    indices=db.rows('SELECT * FROM krx_indices WHERE is_active=1 ORDER BY index_code')
    indices=[r for r in indices if not allowed or allowed.intersection((r['display_name'] or r['index_name'],r['index_code'],r.get('official_index_code')))]
    if not indices:return []
    params={'i'+str(i):r['index_code'] for i,r in enumerate(indices)}
    placeholders=','.join(':'+key for key in params)
    all_members=db.rows("""SELECT k.index_code,k.corp_code,k.effective_from,k.effective_to,k.source_as_of,
        COALESCE(c.is_operational,0) AS is_operational FROM krx_index_constituents k
        LEFT JOIN companies c USING(corp_code) WHERE k.is_current=1 AND k.index_code IN ("""+placeholders+") ORDER BY k.index_code,k.corp_code",params)
    groups={r['index_code']:[] for r in indices}
    for m in all_members:groups[m['index_code']].append(m)
    result=[]
    for r in indices:
        name=r['display_name'] or r['index_name'];settings=config.get(name,{})
        current=groups[r['index_code']]
        if not any(m['is_operational'] for m in current):continue
        members=[{k:m[k] for k in ('corp_code','effective_from','effective_to','source_as_of')} for m in current]
        membership=hashlib.sha256(json.dumps(members,sort_keys=True).encode()).hexdigest()
        result.append(Sector(name,name,r['index_code'],version['data_version']+':'+membership,version['index_version'],
            r['official_index_code'] or settings.get('index_code') or r['index_code'],tuple(settings.get('companies_order',())),
            tuple(settings.get('queries',Sector.__dataclass_fields__['topics'].default)),tuple(settings.get('terms',())),settings.get('company_profiles',{})))
    return result

def sectors(root=None,all_sectors=False):
    key=('catalog',str(root),all_sectors,os.getenv('SNAPDART_SECTORS',''),os.getenv('SECTOR_CONFIG',''))
    path=Path(os.getenv('SECTOR_CONFIG',str(BASE/'config/sectors.json')))
    try:stat=path.stat();config_stamp=(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
    except FileNotFoundError:config_stamp=(str(path),None)
    connection=tuple(os.getenv(k,'') for k in ('MYSQL_HOST','MYSQL_PORT','MYSQL_DATABASE','MYSQL_USER','SQL_HOST_NAME','SQL_DEFAULT_SCHEMA','CLOUD_SQL_INSTANCE'))
    return request_value((key,config_stamp,connection),lambda:scoped_catalog((key,connection),config_stamp,lambda:_sectors(root,all_sectors)))

def sector(value=None):
    choices=sectors();value=value or os.getenv('SNAPDART_SECTOR')
    found=next((s for s in choices if value in (s.id,s.membership_code,s.index_code)),None) if value else next(iter(choices),None)
    if found is None:raise KeyError('현재 데이터가 구축된 지수를 선택하세요.')
    return found
