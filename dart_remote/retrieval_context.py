"""Small historical anchors and non-selectable adjacent text, within fixed budgets."""
import os

VERSION = 'retrieval-context-v1'
NOTE = '''[검색 문맥과 비교 자료]
context_before/context_after는 원문을 이해하기 위한 인접 내용이며 각주 ID가 아닙니다.
각주는 passages의 원문 문장 ID만 선택하세요. 필요한 조건문이 passages에 있으면 함께 선택하세요.
인용 가능한 문장에 없는 내용을 인접 문맥만으로 새 주장으로 만들지 마세요.
historical_anchor는 같은 기업·검색 주제의 이전 기간 참고 자료입니다.
관련 자료라는 이유만으로 비교 가능하거나 증가·감소를 증명한다고 판단하지 마세요.
명시적인 변화 또는 비교 가능한 전후 근거가 없으면 현재 현황으로 설명 범위를 제한하세요.'''


def historical_anchors(repo, rows, years, keyword):
    """Keyword lookup is latest-only; add at most four scoped prior-period hits."""
    if not keyword or len(years) < 2: return rows
    latest = max(years); previous = max(y for y in years if y < latest)
    result = list(rows); seen = {r['chunk_id'] for r in rows}; scopes = set()
    for row in rows:
        code = row.get('stock_code'); report_type = row.get('report_type')
        if not code or row['year'] != latest: continue
        if report_type not in ('FY', 'Q1', 'H1', 'Q3'):
            report_type = {'12': 'FY', '03': 'Q1', '06': 'H1', '09': 'Q3'}.get(row['period'][-2:])
        if report_type is None or (code, report_type) in scopes: continue
        if len(scopes) >= 4: break
        scopes.add((code, report_type))
        hits, _ = repo.search(keyword, code, previous, report_type, top_k=1, business_only=True)
        for hit in hits:
            # Defense in depth against an incorrectly scoped search adapter.
            if (hit['chunk_id'] not in seen and hit.get('stock_code') == code and hit['year'] == previous
                    and hit.get('report_type', report_type) == report_type):
                result.append(dict(hit, anchor_start=0, historical_anchor=True))
                seen.add(hit['chunk_id'])
    return result


def add_context(evidence):
    """Keep exact offsets/IDs; add at most 4k chars total (configurable, capped)."""
    budget = max(0, min(8000, int(os.getenv('CITATION_CONTEXT_CHAR_BUDGET', '4000'))))
    filings = [e for e in evidence if e['kind'] == 'filing']
    # Round robin keeps one long company chunk from consuming all adjacent context.
    longest = max((len(e['passages']) for e in filings), default=0)
    for i in range(longest):
        for entry in filings:
            if i >= len(entry['passages']) or budget <= 0: continue
            passage = entry['passages'][i]; text = entry['text']
            for key, start, end in (
                ('context_before', max(0, passage['start'] - 120), passage['start']),
                ('context_after', passage['end'], min(len(text), passage['end'] + 120))):
                value = text[start:end]
                value = value[-budget:] if key == 'context_before' else value[:budget]
                if value:
                    passage[key] = value; budget -= len(value)
    return evidence
