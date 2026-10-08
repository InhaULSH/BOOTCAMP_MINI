"""Versioned, deterministic disclosure signals; no Gemini requests here."""
import hashlib
import json
from dataclasses import replace
import pandas as pd
from . import db, artifacts
from .dart_signal_wordcloud import SignalConfig, score_keywords, wordcloud_items
from .signal_keyword_rules import ALLOWED_SECTION_PREFIXES, ALLOWED_SUBSECTION_PHRASES

VERSION='disclosure-signal-v2-all-years'

def eligible(row):
    return row['report_type'] in ('Q1','H1','Q3','FY') and (
        row['section_name'].startswith(ALLOWED_SECTION_PREFIXES) or
        any(p in (row.get('subsection_name') or '') for p in ALLOWED_SUBSECTION_PHRASES))

def display(scored,config):
    items=wordcloud_items(scored.head(config.top_n))
    latest=config.years[-1]
    for item,row in zip(items,scored.head(config.top_n).to_dict('records')):
        item.update(text=item['keyword'],count=int(row[f'count_{latest}']),
                    current_score=float(row['current_score']),change_score=float(row['change_score']),
                    spread_score=float(row['spread_score']),change_raw=float(row['change_raw']),
                    mention_rate=float(row[f'rate_{latest}']),method=VERSION,
                    years=list(config.years),scope='company' if config.company_scope else 'sector')
    return items

def apply(report,repo):
    years=tuple(report['years'])
    if not years:raise ValueError('공시 신호 계산에는 분석 연도가 필요합니다.')
    # Weight selection is independent of UI ordering and financial chart membership.
    members=db.rows('''SELECT c.corp_code,c.corp_name,c.stock_code,k.weight
        FROM krx_index_constituents k JOIN companies c USING(corp_code)
        WHERE k.index_code=:i AND k.is_current=1 AND c.is_operational=1
        ORDER BY (k.weight IS NULL),k.weight DESC,c.corp_code LIMIT 5''',{'i':repo.sector.membership_code})
    allowed={c['code'] for c in report['companies']}
    members=[r for r in members if r['stock_code'] in allowed]
    config=SignalConfig(repo.sector.membership_code,years=years)
    # Hash the engine/rules as well as DB version, years and selected companies.
    from pathlib import Path
    rules=hashlib.sha256(b''.join((Path(__file__).parent/n).read_bytes() for n in
        ('dart_signal_wordcloud.py','signal_keyword_rules.py','wordcloud.py'))).hexdigest()
    key=hashlib.sha256(json.dumps([repo.fingerprint(),years,members,[c['code'] for c in report['companies']],rules],sort_keys=True).encode()).hexdigest()
    cached=artifacts.get_artifact(repo.sector.id,'wordcloud-'+key)
    if cached is None:
        company_outputs={};sector_chunks=[]
        columns=['chunk_id','corp_code','year','chunk_text']
        for company in report['companies']:
            rows=[r for y in years for r in repo.chunks(company['code'],y) if eligible(r)]
            frame=pd.DataFrame(rows,columns=columns).drop_duplicates('chunk_id')
            meta=repo.company(company['code'])
            company_config=replace(config,min_latest_companies=1,company_scope=True)
            metadata=pd.DataFrame([dict(corp_code=meta['corp_code'],corp_name=meta['corp_name'])])
            totals=frame.groupby('year').size().to_dict()
            missing=[y for y in years if not totals.get(y)]
            company_outputs[company['code']]=dict(items=[] if missing else display(score_keywords(frame,company_config,metadata),company_config),missing_years=missing)
            if company['code'] in {m['stock_code'] for m in members}:sector_chunks.extend(rows)
        frame=pd.DataFrame(sector_chunks,columns=columns).drop_duplicates('chunk_id')
        missing=[y for y in years if not (frame['year']==y).any()]
        items=[] if missing or not members else display(score_keywords(frame,config,pd.DataFrame(members)),config)
        cached=dict(items=items,companies=company_outputs,years=list(years),missing_years=missing,
                    selected_companies=members,method=VERSION)
        artifacts.put_artifact(repo.sector.id,'wordcloud-'+key,cached)
    for scope,items in [(report,cached['items'])]+[(c,cached['companies'][c['code']]['items']) for c in report['companies']]:
        # The latest-year view summarizes signals across the entire analysis period.
        scope['wordcloud']={str(y):[] for y in report['years']}
        scope['wordcloud'][str(years[-1])]=items
        scope.pop('keywords',None)
    report['wordcloud_signal']=cached
    report['source']['wordcloud_method']=VERSION
    return report
