"""Read-only presentation model. Financial arithmetic stays outside the LLM."""
import copy
import json
import math
from . import config  # Register the shared pipeline path before importing it.
from snapdart_data.pipeline import growth
from .market import category

METRICS = [('revenue_growth', '매출 성장률'), ('margin', '영업이익률'),
           ('capex_ratio', '설비투자 비중'), ('fcf_margin', '투자 후 현금 비중')]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def weighted(rows, weights, key):
    # Missing constituents must not silently change the meaning of the index.
    if not rows or any(not finite(r.get(key)) or not finite(weights.get(code)) or weights[code] <= 0 for code, r in rows.items()):
        return None
    total = sum(weights[c] for c in rows)
    return sum(weights[c]*r[key] for c,r in rows.items()) / total if total else None


def trend_summary(history):
    if len(history) < 2:
        return '비교할 연간 지표가 부족합니다.'
    before, after = history[-2:]
    if before.get('basis') != after.get('basis'):
        return '연결·별도 재무제표 기준이 달라 해당 구간의 변화 해석을 생략했습니다.'
    parts = []
    for key, label in METRICS:
        a, b = before.get(key), after.get(key)
        if finite(a) and finite(b):
            delta = b-a
            direction = '높아졌습니다' if delta > 0 else '낮아졌습니다' if delta < 0 else '같습니다'
            parts.append(f'{label}은 {a:.1f}%에서 {b:.1f}%로 {direction}' + (f' ({abs(delta):.1f}%p 변화).' if delta else '.'))
            if key == 'revenue_growth':
                parts.append('매출이 전년보다 늘어난 상태입니다.' if b > 0 else '매출이 전년보다 줄어든 상태입니다.' if b < 0 else '매출 규모가 전년과 같습니다.')
            elif key == 'margin':
                parts.append('매출에서 본업의 이익으로 남는 비중을 뜻합니다.')
            elif key == 'capex_ratio':
                parts.append('투자 비중만으로 투자 성과나 과잉투자를 판단할 수는 없습니다.')
            elif key == 'fcf_margin':
                parts.append('영업에서 들어온 현금과 설비 지출을 함께 살펴야 합니다.')
    return f'{before["year"]}년과 {after["year"]}년 비교: ' + (' '.join(parts) if parts else '동일 기준의 지표 또는 지수 비중이 부족해 변화 요약을 계산하지 않았습니다.')


def build_view(report, market=None):
    data = copy.deepcopy(report)
    market = market or {}
    weights = market.get('representative_weights', market.get('index', {}).get('weights', {}))
    for company in data['companies']:
        for row in company['history']:
            revenue, fcf = row.get('revenue'), row.get('fcf')
            row['fcf_margin'] = fcf/revenue*100 if finite(fcf) and finite(revenue) and revenue>0 else None
        for i,row in enumerate(company['history']):
            if 'yoy' in row:continue
            previous=company['history'][i-1] if i else {}
            comparable=bool(previous) and previous.get('basis')==row.get('basis')
            row['yoy']={key:growth(row.get(key),previous.get(key)) if comparable else None
                for key in ('revenue','operating_income','capex','operating_cashflow')}
        company['trend_summary'] = trend_summary(company['history'])
    history = []
    for year in data['years']:
        rows = {c['code']: next((r for r in c['history'] if r['year']==year), {}) for c in data['companies']}
        history.append(dict(year=year, **{key:weighted(rows,weights,key) for key,_ in METRICS}))
    data['weighted_history'] = history
    data['trend_summary'] = trend_summary(history)
    data['market'] = copy.deepcopy(market)
    from .market import close_snapshot
    # Old saved intraday quotes must not reappear when a refresh fails.
    for quote in list(data['market'].get('quotes',{}).values())+[data['market'].get('index',{})]:
        if not quote.get('history'):continue
        try:quote.update(close_snapshot(quote['history']))
        except (RuntimeError,ValueError,TypeError,KeyError):
            quote.update(price=None,change=None,history=[],stale=True,error='전일 종가 비교 자료가 부족합니다.')
    expected=data.get('index_code','5044')
    if not expected or market.get('index', {}).get('code') != expected:
        data['market']['index'] = dict(name=data.get('sector_name','반도체')+' 지수',code=expected,history=[],change=None,error='해당 섹터 지수를 수집해 주세요.')
    return data


def load_view(sector_id=None):
    from snapdart_data.pipeline import load_report
    from snapdart_data.catalog import SERVICE,sectors
    report=load_report(sector_id)
    path=SERVICE/'market.json' if report.get('index_code')=='5044' else SERVICE/report['sector_id']/'market.json'
    market=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    market=dict(market)
    if not market.get('filings'):
        market['filings']=[dict(code=c['code'],title=d['report_name'],date=d['rcept_no'][:8],id=d['rcept_no'],category='정기 공시',archived=True)
            for c in report['companies'] for d in c['documents']]
    view=build_view(report,market)
    view['sectors']=[dict(id=s.id,name=s.name,index_code=s.index_code) for s in sectors()]
    return view
