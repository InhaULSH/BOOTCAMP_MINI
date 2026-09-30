"""Bounded, topic-diverse retrieval over all periodic business sections."""
import re
from .analyze import TOPICS, business_text
from .config import DATA

def select_passages(text, limit=20, size=1050, previous_text=''):
    paragraphs = [re.sub(r'\s+', ' ', p).strip() for p in text.splitlines()]
    chunks = []
    for paragraph in paragraphs:
        if len(paragraph) < 55:
            continue
        for offset in range(0, len(paragraph), size):
            chunk = paragraph[offset:offset+size]
            if len(chunk) >= 55 and chunk not in chunks:
                chunks.append(chunk)
    selected = set(range(min(2, len(chunks))))
    for pattern in TOPICS.values():
        ranked = sorted(range(len(chunks)), key=lambda i: (-len(re.findall(pattern, chunks[i], re.I)), i))
        matches = [i for i in ranked if re.search(pattern, chunks[i], re.I)]
        selected.update(matches[:3])
        if matches:
            selected.add(max(matches))
    # Reserve space for changed topic passages; textual novelty is not an event.
    previous = re.sub(r'\s+', ' ', previous_text)
    changed = [i for i, chunk in enumerate(chunks)
               if previous_text and chunk not in previous
               and any(re.search(p, chunk, re.I) for p in TOPICS.values())]
    chosen = list(sorted(selected))[:max(0, limit-4)] if changed else list(sorted(selected))[:limit]
    chosen += [i for i in changed if i not in chosen][:min(4, limit)]
    chosen += [i for i in sorted(selected) if i not in chosen][:max(0, limit-len(chosen))]
    return [chunks[i] for i in sorted(chosen[:limit])]

def company_context(company):
    import json
    folder = DATA / company['code']
    filings = json.loads((folder / 'filings.json').read_text(encoding='utf-8'))
    evidence = []
    coverage = []
    previous_text, previous_period = '', None
    for filing in sorted(filings, key=lambda f: f['period']):
        year = int(filing['period'][:4])
        period = filing['period']
        text = business_text(folder / (filing['rcept_no']+'.zip'))
        passages = select_passages(text, previous_text=previous_text)
        normalized_previous = re.sub(r'\s+', ' ', previous_text)
        coverage.append(dict(period=period, passages=len(passages), parsed=bool(text)))
        for i, passage in enumerate(passages):
            evidence.append(dict(id=f"{company['code']}-{period}-{filing['rcept_no']}-text-{i}",
                                 year=year, period=period, report_name=filing['report_nm'],
                                 kind='회사 공시 서술', text=passage, compared_period=previous_period,
                                 changed_text=bool(previous_text) and passage not in normalized_previous))
        if text:
            previous_text, previous_period = text, period
    for row in company['history']:
        formatted = {}
        for key, value in row.items():
            if key == 'positions':
                formatted[key] = {k: round(v, 2) if v is not None else None for k, v in value.items()}
            elif isinstance(value, float):
                formatted[key] = round(value, 2)
            else:
                formatted[key] = value
        evidence.append(dict(id=f"{company['code']}-{row['year']}-financial", year=row['year'], kind='Python 계산 수치', scope='연간·전사 재무', values=formatted))
    return dict(company=company['name'], sector=company['sector'], coverage=coverage, evidence=evidence)
