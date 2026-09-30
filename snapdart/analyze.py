"""Deterministic financial analysis and business-section sentence extraction."""
import json
import re
import zipfile
from html.parser import HTMLParser
from statistics import median
from .config import ROOT, DATA, COMPANIES, YEARS
from .collect import save_json

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)
    def handle_endtag(self, tag):
        if tag.lower() in ('p', 'title', 'tr', 'section-1', 'section-2'):
            self.parts.append('\n')

def business_text(path):
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith('.xml')]
        if not names:
            return ''
        # Main report has the largest XML; attached audit files are smaller.
        raw = archive.read(max(names, key=lambda n: archive.getinfo(n).file_size))
    for encoding in ('utf-8-sig', 'euc-kr'):
        try:
            source = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    else:
        source = raw.decode('utf-8', errors='replace')
    parser = TextParser()
    parser.feed(source)
    text = ''.join(parser.parts)
    text = re.sub(r'[^\S\n]+', ' ', text)
    starts = list(re.finditer(r'(?m)^\s*II\s*\.\s*사업의\s*내용\s*$', text))
    if not starts:
        return ''  # Do not mistake unrelated sections for business discussion.
    sections = []
    for start in starts:
        remaining = text[start.end():]
        end = re.search(r'(?m)^\s*III\s*\.\s*재무에\s*관한', remaining)
        if end:
            sections.append(remaining[:end.start()])
    # The table of contents repeats the same section names: choose the body.
    return max(sections, key=len, default='')

TOPICS = {
    'AI·고부가 제품': r'HBM|인공지능|AI\s|고부가|고대역폭',
    '수요·시장': r'수요|시장.*성장|업황|공급과잉',
    '생산·투자': r'설비투자|생산능력|증설|가동률|CAPEX',
    '위험 요인': r'불확실|경쟁.*심화|가격.*하락|위험|리스크',
}

def excerpts(text):
    sentences = re.split(r'\n+|(?<=[다요])\.\s+', text)
    results = {}
    for topic, pattern in TOPICS.items():
        candidates = []
        for sentence in sentences:
            sentence = sentence.strip()
            if 45 <= len(sentence) <= 750 and re.search(pattern, sentence, re.I):
                if sentence not in candidates:
                    candidates.append(sentence)
        results[topic] = candidates[:3]
    return results

def amount(value):
    value = str('' if value is None else value).replace(',', '').strip()
    if value in ('', '-', '－'):
        return None
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    try:
        return int(value)
    except ValueError:
        return None

ACCOUNTS = {
    'revenue': (['ifrs-full_Revenue', 'ifrs_Revenue'], ['매출액', '수익(매출액)', '영업수익']),
    'operating_income': (['dart_OperatingIncomeLoss'], ['영업이익', '영업이익(손실)', '영업손익']),
    'inventory': (['ifrs-full_Inventories', 'ifrs_Inventories'], ['재고자산']),
    'operating_cashflow': (['ifrs-full_CashFlowsFromUsedInOperatingActivities', 'ifrs_CashFlowsFromUsedInOperatingActivities'], ['영업활동현금흐름', '영업활동으로인한현금흐름']),
    'capex': (['ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities', 'ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities'], ['유형자산의취득', '유형자산취득']),
}

def get_account(rows, key):
    ids, names = ACCOUNTS[key]
    sections = ('IS', 'CIS') if key in ('revenue', 'operating_income') else (('BS',) if key == 'inventory' else ('CF',))
    for section in sections:
        pool = [r for r in rows if r.get('sj_div') == section and r.get('currency', 'KRW') == 'KRW']
        matches = [r for r in pool if r.get('account_id') in ids]
        if not matches:
            matches = [r for r in pool if re.sub(r'\s+', '', r.get('account_nm', '')) in names]
        values = {amount(r.get('thstrm_amount')) for r in matches} - {None}
        if len(values) == 1:
            value = values.pop()
            return abs(value) if key == 'capex' else value
    return None

def ratio(a, b):
    return a / b * 100 if a is not None and b is not None and b > 0 else None

def growth(now, previous):
    return ratio(now - previous, previous) if now is not None and previous is not None else None

def financials(folder):
    history = []
    for year in YEARS:
        path = folder / f'financial_{year}.json'
        raw = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        row = dict(year=year, basis=raw.get('basis'), **{key: get_account(raw.get('list', []), key) for key in ACCOUNTS})
        row['margin'] = ratio(row['operating_income'], row['revenue'])
        row['capex_ratio'] = ratio(row['capex'], row['revenue'])
        row['fcf'] = row['operating_cashflow'] - row['capex'] if row['operating_cashflow'] is not None and row['capex'] is not None else None
        previous = history[-1] if history and history[-1]['basis'] == row['basis'] else {}
        for key in ('revenue', 'capex', 'inventory'):
            row[key + '_growth'] = growth(row[key], previous.get(key))
        history.append(row)
    return history

def fmt(value, percent=False):
    return '확인 불가' if value is None else (f'{value:,.1f}%' if percent else f'{value / 100000000:,.0f}억 원')

def company_insights(history):
    latest = history[-1]
    previous = history[-2]
    cards = []
    g = latest['revenue_growth']
    if g is not None:
        cards.append(dict(title='매출과 수익성', fact=f"매출 전년 대비 {g:+.1f}%, 영업이익률 {fmt(latest['margin'], True)}.", signal='매출 외형 확대' if g > 0 else ('매출 외형 축소' if g < 0 else '매출 유지'), interpretation='매출 변화만으로 수요의 구조적 성장을 단정할 수 없습니다. 판매량·가격·제품 구성의 영향을 함께 살펴야 합니다.'))
    if latest['capex'] is not None and latest['fcf'] is not None:
        cards.append(dict(title='투자와 현금흐름', fact=f"유형자산 취득 {fmt(latest['capex'])}, 영업현금흐름 {fmt(latest['operating_cashflow'])}, 단순 FCF {fmt(latest['fcf'])}.", signal='영업현금으로 유형자산 취득 충당' if latest['fcf'] >= 0 else '유형자산 취득이 영업현금흐름을 초과', interpretation='설비 지출은 당기 현금을 줄이지만 미래 생산에 기여할 수 있습니다. 취득액만으로 증설 규모나 투자 성과를 판단하지 않습니다.'))
    ig = latest['inventory_growth']
    if ig is not None and g is not None:
        cards.append(dict(title='재고 부담', fact=f'재고자산 전년 대비 {ig:+.1f}%, 매출 전년 대비 {g:+.1f}%.', signal='재고가 매출보다 빠르게 증가' if ig > g else '재고 증가율이 매출 증가율 이하', interpretation='재고 축적은 수요 둔화 또는 선제 생산 모두와 연결될 수 있습니다. 재고 증가를 곧바로 부실재고로 해석하지 않습니다.'))
    return cards

def build(use_llm=False, force=False):
    companies = []
    for config in COMPANIES:
        folder = DATA / config['code']
        index = folder / 'filings.json'
        filings = json.loads(index.read_text(encoding='utf-8')) if index.exists() else []
        documents = []
        for filing in filings:
            path = folder / (filing['rcept_no'] + '.zip')
            if path.exists():
                text = business_text(path)
                documents.append(dict(period=filing['period'], topics=excerpts(text), parsed=bool(text)))
        history = financials(folder)
        annuals = [d for d in documents if d['period'].endswith('-12')]
        latest_topics = annuals[-1]['topics'] if annuals else {}
        companies.append(dict(**config, history=history, insights=company_insights(history), topics=latest_topics,
                              documents=documents, report_count=len(documents)))
    metrics = ('revenue_growth', 'margin', 'capex_growth', 'capex_ratio', 'inventory_growth', 'fcf')
    industry = []
    for i, year in enumerate(YEARS):
        record = dict(year=year)
        for metric in metrics:
            values = [c['history'][i][metric] for c in companies if c['history'][i][metric] is not None]
            record[metric] = median(values) if values else None
            record[metric + '_n'] = len(values)
        industry.append(record)
    for c in companies:
        for i, record in enumerate(c['history']):
            record['positions'] = {}
            for metric in metrics:
                values = [other['history'][i][metric] for other in companies if other['history'][i][metric] is not None]
                value = record[metric]
                # Empirical midpoint percentile: equal values share position.
                record['positions'][metric] = (100 * (sum(v < value for v in values) + .5 * values.count(value)) / len(values)) if value is not None and len(values) >= 2 else None
    signals = []
    for metric, title in [('revenue_growth','매출'), ('capex_growth','유형자산 취득'), ('inventory_growth','재고자산')]:
        values = [c['history'][-1][metric] for c in companies if c['history'][-1][metric] is not None]
        signals.append(dict(title=title, positive=sum(v > 0 for v in values), count=len(values), median=median(values) if values else None))
    diffusion = []
    for year in YEARS:
        docs = [d for c in companies for d in c['documents'] if d['period'] == f'{year}-12' and d['parsed']]
        diffusion.append(dict(year=year, count=len(docs), topics={topic:sum(bool(d['topics'][topic]) for d in docs) for topic in TOPICS}))
    result = dict(companies=companies, industry=industry, signals=signals, diffusion=diffusion,
                  mode='공시 문장 추출 + 규칙 기반 해석', years=YEARS)
    if use_llm:
        from .llm import enrich
        enrich(result,force=force)
    save_json(ROOT / 'data' / 'reports.json', result)
    print(f"보고서 생성: {len(companies)}개 기업, 공시 {sum(c['report_count'] for c in companies)}개")

if __name__ == '__main__':
    import argparse
    import os
    from .config import load_env
    load_env()
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--llm', action='store_true', help='선택한 LLM 분석 생성 (기본: 로컬 Ollama 사용)')
    mode.add_argument('--refresh-llm', action='store_true', help='선택한 LLM 분석 캐시를 재사용하지 않고 다시 생성')
    mode.add_argument('--offline', action='store_true', help='API 호출 없이 규칙 기반 보고서 생성')
    args = parser.parse_args()
    use_llm = not args.offline and bool(os.getenv('LLM_PROVIDER', 'ollama') == 'ollama' or args.llm or args.refresh_llm or os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'))
    build(use_llm, force=args.refresh_llm)
