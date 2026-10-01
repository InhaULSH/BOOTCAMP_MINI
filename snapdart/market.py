"""Public market snapshots and recent DART lists; never calls an LLM."""
import json
import math
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from .config import ROOT, DATA, COMPANIES
from .collect import DartClient, save_json

PATH = ROOT / 'data' / 'market.json'


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
    basic = get(f'https://m.stock.naver.com/api/stock/{code}/basic')
    info = get(f'https://m.stock.naver.com/api/stock/{code}/integration')
    cap = next((market_cap(i['value']) for i in info['totalInfos'] if i['code'] == 'marketValue'), None)
    tree = get(f'https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=65&requestType=0', xml=True)
    history = []
    for item in tree.iter('item'):
        fields = item.attrib['data'].split('|')
        value = number(fields[4])
        if value and value > 0:
            history.append(dict(date=fields[0], value=value))
    return dict(code=code, price=number(basic.get('closePrice')), change=number(basic.get('fluctuationsRatio')),
                traded_at=basic.get('localTradedAt'), market_status=basic.get('marketStatus'),
                market_cap=cap, history=sorted(history, key=lambda x: x['date']), source='NAVER 증권')


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
    stored = json.loads((DATA/code/'filings.json').read_text(encoding='utf-8'))
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
    result['index'] = index_from_quotes(result['quotes']) if not any(q.get('stale') for q in result['quotes'].values()) else old.get('index', {})
    result['filings'].sort(key=lambda f:(f['date'], f['id']), reverse=True)
    save_json(PATH, result)
    print('시세·최근 공시 저장 완료. Gemini 호출 없음.', flush=True)


if __name__ == '__main__':
    refresh()
