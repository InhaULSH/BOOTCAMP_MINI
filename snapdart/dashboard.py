"""Read-only presentation model. Financial arithmetic stays outside the LLM."""
import copy
import json
import math
from .config import ROOT, DATA
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
    weights = market.get('index', {}).get('weights', {})
    for company in data['companies']:
        for row in company['history']:
            revenue, fcf = row.get('revenue'), row.get('fcf')
            row['fcf_margin'] = fcf/revenue*100 if finite(fcf) and finite(revenue) and revenue>0 else None
        company['trend_summary'] = trend_summary(company['history'])
    history = []
    for year in data['years']:
        rows = {c['code']: next((r for r in c['history'] if r['year']==year), {}) for c in data['companies']}
        history.append(dict(year=year, **{key:weighted(rows,weights,key) for key,_ in METRICS}))
    data['weighted_history'] = history
    data['trend_summary'] = trend_summary(history)
    data['market'] = market
    return data


def load_view():
    report = json.loads((ROOT/'data/reports.json').read_text(encoding='utf-8'))
    path = ROOT/'data/market.json'
    market = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not market.get('filings'):
        market['filings'] = []
        for company in report['companies']:
            path = DATA/company['code']/'filings.json'
            if path.exists():
                rows = json.loads(path.read_text(encoding='utf-8'))
                market['filings'].extend(dict(code=company['code'], title=f['report_nm'], date=f['rcept_dt'],
                    id=f['rcept_no'], category=category(f['report_nm']), archived=True) for f in rows)
        market['filings'].sort(key=lambda f:f['date'], reverse=True)
    return build_view(report,market)
