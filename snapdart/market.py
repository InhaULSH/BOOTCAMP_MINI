"""Public market snapshots and recent DART lists; never calls an LLM."""
import json
import math
import re
import threading
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from .config import SERVICE_ROOT
from .dart_client import DartClient, save_json

from .settings import DATA_ROOT
PATH = DATA_ROOT / 'service/market.json'
KRX_CODE = '5044'
_FDR_LOCK = threading.Lock()

def collect_sector_index(selected=None):
    from .krx_api import collect_history
    from .data_access.catalog import sector
    from dart_remote import db
    import pandas as pd
    registered=sector(selected)
    names=db.rows('SELECT index_name FROM krx_indices WHERE index_code=:i',{'i':registered.membership_code})
    name=names[0]['index_name']
    rows=collect_history(name=name)
    frame=pd.DataFrame({'Close':[r['value'] for r in rows]},index=pd.to_datetime([r['date'] for r in rows]))
    from dart_remote.krx_market import collect,merge
    recent=collect([name],DATA_ROOT/'krx_api/daily_responses')[name]
    return merge(index_frame(frame,name=name+' 지수',code=registered.index_code),recent,registered.index_code)


def market_context(selected):
    from .data_access.repository import Repository
    repo=Repository(selected)
    companies=[dict(code=c['stock_code'],name=c['company_name']) for c in repo.companies()]
    path=PATH if repo.sector.name=='반도체' else DATA_ROOT/'service/market'/(''.join(c for c in repo.sector.membership_code if c.isalnum() or c=='_')+'.json')
    return repo.sector,companies,path

from dart_remote.market_quotes import close_snapshot

def index_frame(frame,name='KRX 반도체 지수',code=KRX_CODE):
    if frame.empty or 'Close' not in frame:
        raise RuntimeError(f'{name} 시세가 없습니다.')
    history=[dict(date=date.strftime('%Y-%m-%d'),value=close) for date,close in frame['Close'].sort_index().items()]
    return dict(name=name,code=code,source='KRX OPEN API',stale=False,**close_snapshot(history))


def refresh_index_only(selected=None):
    if selected is None:
        from .data_access.catalog import sectors
        return {s.id:refresh_index_only(s.id) for s in sectors(all_sectors=True)}
    registered,companies,path=market_context(selected)
    result=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    previous=result.get('index',{})
    # Keep five-company metric weights separate from the official index.
    result['representative_weights']=representative_weights(result.get('quotes',{}),[c['code'] for c in companies])
    try:
        result['index']=collect_sector_index(registered.id)
        print(registered.name+' 지수 수집 완료',flush=True)
    except Exception as error:
        reason=str(error) if isinstance(error,RuntimeError) else 'KRX API 조회 실패. 기존 자료는 보존됩니다.'
        if previous.get('code')==registered.index_code and previous.get('history'):
            result['index']=dict(previous,stale=True,error=reason+' · 저장된 동일 지수 자료')
        else:
            result['index']=dict(name=registered.name+' 지수',code=registered.index_code,history=[],change=None,error=reason)
        print(result['index']['error'],flush=True)
    result['index_fetched_at']=datetime.now().astimezone().isoformat()
    save_json(path,result)
    from dart_remote.artifacts import put_artifact
    from .data_access.catalog import sector
    put_artifact(registered.id,'market',result)
    return result['index']


from dart_remote.market_quotes import number, market_cap, get, collect_quote, representative_weights

def category(title):
    for name, pattern in [('설비·생산', '시설|설비|공장|생산'), ('공급·계약', '공급|계약'), ('연구·제품', '연구|개발|특허'), ('정기보고', '사업보고서|반기보고서|분기보고서'), ('실적', '영업.*실적|잠정|손익')]:
        if re.search(pattern, title):
            return name
    return '기타 공시'


def collect_recent(client, code,selected=None):
    from snapdart.data_access.repository import Repository
    stored=[dict(corp_code=Repository(selected).company(code)['corp_code'])]
    end = datetime.now().date()
    rows = []
    page = 1
    while True:
        response = client.request('list.json', corp_code=stored[0]['corp_code'],
                                  bgn_de=(end-timedelta(days=90)).strftime('%Y%m%d'), end_de=end.strftime('%Y%m%d'),
                                  page_count=100, page_no=page, sort='date', sort_mth='desc')
        rows.extend(response.get('list', []))
        if page >= int(response.get('total_page', 1)):
            break
        page += 1
    return [dict(code=code, title=r['report_nm'], date=r['rcept_dt'], id=r['rcept_no'], category=category(r['report_nm'])) for r in rows]


def refresh(selected=None):
    if selected is None:
        from .data_access.catalog import sectors
        for s in sectors(all_sectors=True):refresh(s.id)
        return
    registered,companies,path=market_context(selected)
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    result = dict(quotes={}, filings=[], errors=[], fetched_at=datetime.now().astimezone().isoformat())
    try:
        client = DartClient()
    except RuntimeError:
        client = None
    for company in companies:
        code = company['code']
        try:
            result['quotes'][code] = collect_quote(code)
            print(company['name']+' 주가 수집 완료', flush=True)
        except Exception:
            if code in old.get('quotes', {}):
                result['quotes'][code] = dict(old['quotes'][code], stale=True)
            result['errors'].append(company['name']+' 시세 갱신 실패 (이전 자료가 있으면 유지)')
        try:
            if client is None:
                raise RuntimeError()
            result['filings'].extend(collect_recent(client, code,registered.id))
        except Exception:
            result['filings'].extend(dict(f, stale=True) for f in old.get('filings', []) if f['code']==code)
            result['errors'].append(company['name']+' 최근 공시 갱신 실패')
    # Never mix old quotes into a newly calculated index.
    result['representative_weights'] = representative_weights(result['quotes'],[c['code'] for c in companies])
    result['index'] = old.get('index', {})
    result['filings'].sort(key=lambda f:(f['date'], f['id']), reverse=True)
    save_json(path, result)
    from dart_remote.artifacts import put_artifact
    from .data_access.catalog import sector
    put_artifact(registered.id,'market',result)
    refresh_index_only(registered.id)
    print('시세·최근 공시 저장 완료. Gemini 호출 없음.', flush=True)


def refresh_prices(selected=None,refresh_index=True):
    if selected is None:
        from .data_access.catalog import sectors
        targets=sectors(all_sectors=True)
        print('시세 수집 대상: '+', '.join(s.name for s in targets),flush=True)
        for s in targets:refresh_prices(s.id,refresh_index=False)
        if refresh_index:
            for s in targets:refresh_index_only(s.id)
        return
    registered,companies,path=market_context(selected)
    old=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    result=dict(old);result['quotes']={c['code']:old['quotes'][c['code']] for c in companies if c['code'] in old.get('quotes',{})};result['errors']=[]
    result['fetched_at']=datetime.now().astimezone().isoformat()
    for company in companies:
        code=company['code']
        try:
            result['quotes'][code]=collect_quote(code)
            print(company['name']+' 전일 종가 수집 완료',flush=True)
        except Exception:
            if code in result['quotes']:result['quotes'][code]=dict(result['quotes'][code],stale=True)
            result['errors'].append(company['name']+' 전일 종가 갱신 실패 · 저장된 자료 유지')
    result['representative_weights']=representative_weights(result['quotes'],[c['code'] for c in companies])
    save_json(path,result)
    from dart_remote.artifacts import put_artifact
    from .data_access.catalog import sector
    put_artifact(registered.id,'market',result)
    if refresh_index:refresh_index_only(registered.id)


def refresh_latest_indices(selected=None,force=False):
    from .data_access.catalog import sectors,sector
    from dart_remote import db
    from dart_remote.krx_market import collect,merge
    from dart_remote.artifacts import put_artifact
    targets=[sector(selected)] if selected else sectors(all_sectors=True)
    names={s.id:db.rows('SELECT index_name FROM krx_indices WHERE index_code=:i',{'i':s.membership_code})[0]['index_name'] for s in targets}
    snapshots=collect(list(names.values()),DATA_ROOT/'krx_api/daily_responses',refresh=force)
    for s in targets:
        _,_,path=market_context(s.id)
        result=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        result['index']=merge(result.get('index',{}),snapshots[names[s.id]],s.index_code)
        result['index_fetched_at']=datetime.now().astimezone().isoformat()
        save_json(path,result);put_artifact(s.id,'market',result)
        print(s.name+' 전체 시가총액·지수 수집 완료 · '+result['index']['traded_at'],flush=True)
    return {s.id:snapshots[names[s.id]] for s in targets}

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--index-only',action='store_true',help='각 산업의 KRX 지수만 갱신')
    parser.add_argument('--prices-only',action='store_true',help='시세만 갱신; DART/Gemini 호출 없음')
    parser.add_argument('--latest-indices',action='store_true',help='전일 기준 KRX 지수·전체 시가총액만 즉시 갱신')
    parser.add_argument('--sector',help='생략 시 MySQL의 전체 섹터')
    args=parser.parse_args()
    refresh_latest_indices(args.sector,force=True) if args.latest_indices else refresh_index_only(args.sector) if args.index_only else refresh_prices(args.sector) if args.prices_only else refresh(args.sector)
