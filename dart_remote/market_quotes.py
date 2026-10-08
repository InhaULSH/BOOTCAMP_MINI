"""Shared previous-session stock collection; no LLM calls."""
import json, math, re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
def close_snapshot(history,as_of=None):
    from .krx_market import today_korea as korea_today
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
    from .krx_market import today_korea as korea_today
    today=korea_today();end=today-timedelta(days=1)
    frame=fdr.DataReader('NAVER:'+code,(end-timedelta(days=120)).isoformat(),end.isoformat())
    info=get(f'https://m.stock.naver.com/api/stock/{code}/integration')
    cap=next((market_cap(i['value']) for i in info['totalInfos'] if i['code']=='marketValue'),None)
    history=[dict(date=d.strftime('%Y-%m-%d'),value=v) for d,v in frame['Close'].sort_index().items()]
    result=close_snapshot(history,today);result['history']=result['history'][-65:]
    return dict(code=code,market_cap=cap,source='FinanceDataReader / NAVER',stale=False,**result)


def representative_weights(quotes,codes):
    """Current market-cap weights for metrics, separate from the official KRX index."""
    if not codes:return {}
    if any(not quotes.get(c, {}).get('market_cap') or not quotes[c].get('history') for c in codes):
        return {}
    total = sum(quotes[c]['market_cap'] for c in codes)
    return {c: quotes[c]['market_cap'] / total for c in codes}


