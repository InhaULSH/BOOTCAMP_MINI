"""Public market snapshots and recent DART lists; never calls an LLM."""
import json
import math
import re
import os
import threading
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from .config import ROOT, COMPANIES, SERVICE_ROOT
from .collect import DartClient, save_json
from .config import load_env

PATH = SERVICE_ROOT / 'market.json'
KRX_CODE = '5044'
_FDR_LOCK = threading.Lock()

def collect_sector_index():
    from .krx_api import collect_history
    import pandas as pd
    rows=collect_history()
    frame=pd.DataFrame({'Close':[r['value'] for r in rows]},index=pd.to_datetime([r['date'] for r in rows]))
    return dict(index_frame(frame),source='KRX OPEN API')

def close_snapshot(history,as_of=None):
    from .krx_api import korea_today
    today=as_of or korea_today()
    # Reject today's intraday/daily row even if the provider ignores the end date.
    prices={}
    for row in history:
        day=datetime.strptime(row['date'][:10].replace('-',''),'%Y%m%d').date()
        value=number(row['value'])
        if day<today and value is not None and value>0:prices[day.isoformat()]=value
    rows=[dict(date=d,value=v) for d,v in sorted(prices.items())]
    if len(rows)<2:raise RuntimeError('실행일 이전의 두 거래일 종가가 필요합니다.')
    current,previous=rows[-1],rows[-2]
    return dict(history=rows,price=current['value'],traded_at=current['date'],previous_traded_at=previous['date'],
        change=(current['value']/previous['value']-1)*100,point_change=current['value']-previous['value'],price_basis='previous_session_close')

def index_frame(frame):
    if frame.empty or 'Close' not in frame:
        raise RuntimeError('KRX 반도체 지수 시세가 없습니다.')
    history=[dict(date=date.strftime('%Y-%m-%d'),value=close) for date,close in frame['Close'].sort_index().items()]
    return dict(name='KRX 반도체 지수',code=KRX_CODE,source='KRX OPEN API',stale=False,**close_snapshot(history))


def refresh_index_only():
    result=json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {}
    previous=result.get('index',{})
    # Keep five-company metric weights separate from the official index.
    result['representative_weights']=index_from_quotes(result.get('quotes',{})).get('weights',{})
    try:
        result['index']=collect_sector_index()
        print('KRX 반도체 지수 수집 완료',flush=True)
    except Exception as error:
        reason=str(error) if isinstance(error,RuntimeError) else 'KRX API 조회 실패. 기존 자료는 보존됩니다.'
        if previous.get('code')==KRX_CODE and previous.get('history'):
            result['index']=dict(previous,stale=True,error=reason+' · 저장된 동일 지수 자료')
        else:
            result['index']=dict(name='KRX 반도체 지수',code=KRX_CODE,history=[],change=None,error=reason)
        print(result['index']['error'],flush=True)
    result['index_fetched_at']=datetime.now().astimezone().isoformat()
    save_json(PATH,result)
    return result['index']


def number(value):
    try:
        n = float(str(value).replace(',', '').replace('%', ''))
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def market_cap(text):
    text = text.replace(',', '').replace(' ', '')
    total = 0
    for unit, scale in [('조', 1e12), ('억', 1e8)]:
        match = re.search(r'(\d+(?:\.\d+)?)' + unit, text)
        if match:
            total += float(match[1]) * scale
    return total or None


def get(url, xml=False):
    with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0 SnapDART/2.0'}), timeout=25) as response:
        raw = response.read()
    if xml:
        return ET.fromstring(raw.decode('euc-kr'))
    return json.loads(raw)


def collect_quote(code):
    import FinanceDataReader as fdr
    from .krx_api import korea_today
    today=korea_today();end=today-timedelta(days=1)
    frame=fdr.DataReader('NAVER:'+code,(end-timedelta(days=120)).isoformat(),end.isoformat())
    info=get(f'https://m.stock.naver.com/api/stock/{code}/integration')
    cap=next((market_cap(i['value']) for i in info['totalInfos'] if i['code']=='marketValue'),None)
    history=[dict(date=d.strftime('%Y-%m-%d'),value=v) for d,v in frame['Close'].sort_index().items()]
    result=close_snapshot(history,today);result['history']=result['history'][-65:]
    return dict(code=code,market_cap=cap,source='FinanceDataReader / NAVER',stale=False,**result)


def index_from_quotes(quotes):
    """Explicit prototype index: current cap weights held fixed across the chart."""
    codes = [c['code'] for c in COMPANIES]
    if any(not quotes.get(c, {}).get('market_cap') or not quotes[c].get('history') for c in codes):
        return dict(name='대표 5사 주가 지수', weights={}, history=[], change=None)
    total = sum(quotes[c]['market_cap'] for c in codes)
    weights = {c: quotes[c]['market_cap'] / total for c in codes}
    prices = {c: {p['date']: p['value'] for p in quotes[c]['history']} for c in codes}
    dates = sorted(set.intersection(*(set(p) for p in prices.values())))
    if not dates:
        return dict(name='대표 5사 주가 지수', weights=weights, history=[], change=None)
    history = [dict(date=d, value=100 * sum(weights[c]*prices[c][d]/prices[c][dates[0]] for c in codes)) for d in dates]
    change = (history[-1]['value']/history[-2]['value']-1)*100 if len(history)>1 else None
    return dict(name='대표 5사 주가 지수', weights=weights, history=history, change=change,
                method='현재 시가총액 비중을 고정해 각 종목의 시작일=100 가격을 가중평균한 실증 지수. KRX 공식 지수·과거 투자수익률이 아닙니다.')


def category(title):
    for name, pattern in [('설비·생산', '시설|설비|공장|생산'), ('공급·계약', '공급|계약'), ('연구·제품', '연구|개발|특허'), ('정기보고', '사업보고서|반기보고서|분기보고서'), ('실적', '영업.*실적|잠정|손익')]:
        if re.search(pattern, title):
            return name
    return '기타 공시'


def collect_recent(client, code):
    from snapdart_data.repository import Repository
    stored=[dict(corp_code=Repository().company(code)['corp_code'])]
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


def refresh():
    old = json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {}
    result = dict(quotes={}, filings=[], errors=[], fetched_at=datetime.now().astimezone().isoformat())
    try:
        client = DartClient()
    except RuntimeError:
        client = None
    for company in COMPANIES:
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
            result['filings'].extend(collect_recent(client, code))
        except Exception:
            result['filings'].extend(dict(f, stale=True) for f in old.get('filings', []) if f['code']==code)
            result['errors'].append(company['name']+' 최근 공시 갱신 실패')
    # Never mix old quotes into a newly calculated index.
    result['representative_weights'] = index_from_quotes(result['quotes']).get('weights', {})
    result['index'] = old.get('index', {})
    result['filings'].sort(key=lambda f:(f['date'], f['id']), reverse=True)
    save_json(PATH, result)
    refresh_index_only()
    print('시세·최근 공시 저장 완료. Gemini 호출 없음.', flush=True)


def refresh_prices():
    old=json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {}
    result=dict(old);result['quotes']=dict(old.get('quotes',{}));result['errors']=[]
    result['fetched_at']=datetime.now().astimezone().isoformat()
    for company in COMPANIES:
        code=company['code']
        try:
            result['quotes'][code]=collect_quote(code)
            print(company['name']+' 전일 종가 수집 완료',flush=True)
        except Exception:
            if code in result['quotes']:result['quotes'][code]=dict(result['quotes'][code],stale=True)
            result['errors'].append(company['name']+' 전일 종가 갱신 실패 · 저장된 자료 유지')
    result['representative_weights']=index_from_quotes(result['quotes']).get('weights',{})
    save_json(PATH,result);refresh_index_only()

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--index-only',action='store_true',help='KRX 반도체 지수만 갱신')
    parser.add_argument('--prices-only',action='store_true',help='시세만 갱신; DART/Gemini 호출 없음')
    args=parser.parse_args()
    refresh_index_only() if args.index_only else refresh_prices() if args.prices_only else refresh()
