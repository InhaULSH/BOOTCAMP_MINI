"""Validate positive acquisition outlays before quarter subtraction; never write upstream."""
import json
import hashlib
import logging
from datetime import date
from .graph_metrics import finite, REPORTS

VERSION='capex-proof-v1'

def compact(value):
    if isinstance(value,dict):return {k:compact(v) for k,v in value.items() if k!='original_table'}
    if isinstance(value,list):return [compact(v) for v in value]
    return value

def verified_financial(repo,code,year,report='FY',basis='CFS'):
    """Annual/cumulative LLM evidence follows the same outlay validation rules."""
    row=dict(repo.financial(code,year,report,basis=basis))
    if not finite(row.get('capex')):return row
    kind='annual' if report=='FY' else 'cumulative'
    value,sources=read(repo,code,year,basis,report,kind)
    errors=[check(s,year,basis,report,kind) for s in sources]
    if not sources:errors=['source_missing']
    if finite(value) and value<0:errors.append('negative_outlay')
    row['capex']=value if finite(value) and not any(errors) else None
    row['capex_validation']=dict(status='verified' if row['capex'] is not None else 'unverified',
        reasons=[e for e in errors if e],candidate=value)
    row['financial_sources']=dict(row.get('financial_sources',{}),capex=sources if row['capex'] is not None else [])
    return row

def flow(repo,code,year,basis,quarter):
    outcome=resolve(lambda t,k:read(repo,code,year,basis,t,k),year,basis,quarter)
    initial=outcome[3]
    if initial['status']!='verified' and hasattr(repo,'documents'):
        from .xml_financials import load
        def original(t,k):
            rows,_=load(repo,code,year,t,basis,k)
            rows=[r for r in rows if r.get('key')=='capex']
            amounts={r['value'] for r in rows}
            return (next(iter(amounts)),rows) if len(amounts)==1 else (None,[])
        replacement=resolve(original,year,basis,quarter)
        if replacement[3]['status']=='verified':
            outcome=replacement;outcome[3]['source']='active_original_xml'
            outcome[3]['previous_check']=initial
    record=json.loads(json.dumps(compact(outcome[3]),default=str,ensure_ascii=False))
    outcome=(*outcome[:3],record)
    if hasattr(repo,'sector'):
        from . import artifacts
        # Persist a compact trace, not full financial statements or a DB overwrite.
        key=hashlib.sha256(repr((VERSION,repo.sector.data_version,code,year,basis,quarter,record)).encode()).hexdigest()
        try:artifacts.put_artifact('_capex_validation','proof',record,key)
        except OSError:
            logging.getLogger(__name__).exception('CAPEX 검증 기록 저장 실패: %s',key)
    return outcome

def read(repo,code,year,basis,report,kind):
    """Try current active raw XML when DB CAPEX cannot be verified, not another basis."""
    f=repo.financial(code,year,report,basis,kind)
    value=f.get('capex');sources=f.get('financial_sources',{}).get('capex',[])
    if finite(value) and sources and hasattr(repo,'documents') and (
            value<0 or any(check(s,year,basis,report,kind) for s in sources)):
        from .xml_financials import load
        rows,_=load(repo,code,year,report,basis,kind)
        candidates=[r for r in rows if r.get('key')=='capex']
        amounts={r['value'] for r in candidates}
        if len(amounts)==1 and all(not check(s,year,basis,report,kind) for s in candidates):
            return next(iter(amounts)),candidates
    return value,sources

def accounts(row):
    value=row.get('source_account_ids')
    if isinstance(value,str):
        try:value=json.loads(value)
        except ValueError:return ()
    return tuple(sorted(value)) if isinstance(value,list) and all(isinstance(v,str) for v in value) else ()

def check(row,year,basis,report,kind):
    if row.get('review_required'):return 'review_required'
    if row.get('currency')!='KRW' or row.get('fs_div')!=basis:return 'basis_mismatch'
    if row.get('active_rcept_no')!=row.get('rcept_no') or not row.get('rcept_no'):return 'receipt_unverified'
    if not accounts(row):return 'account_unverified'
    end=date(year,{'Q1':3,'H1':6,'Q3':9,'FY':12}[report],{'Q1':31,'H1':30,'Q3':30,'FY':31}[report])
    start=date(year,1,1) if kind in ('annual','cumulative') else date(year,end.month-2,1)
    if str(row.get('period_start'))!=str(start) or str(row.get('period_end'))!=str(end):return 'period_mismatch'
    return None

def resolve(read,year,basis,quarter,allow_annual=True):
    """Computed DB quarters must be reconstructed from independently checked inputs."""
    inputs=[];issues=[]
    def fetch(report,kind):
        value,sources=read(report,kind)
        if not finite(value):return None,[]
        errors=[check(s,year,basis,report,kind) for s in sources]
        if not sources:errors=['source_missing']
        if value<0:errors.append('negative_outlay')
        inputs.append(dict(report_type=report,value_type=kind,value=value,sources=sources))
        if any(errors):issues.extend(e for e in errors if e);return None,sources
        return value,sources
    report=REPORTS[quarter-1]
    value,source=read(report,'quarterly')
    # Only a genuinely reported three-month figure bypasses cumulative subtraction.
    if finite(value) and source and all(not s.get('is_calculated') for s in source):
        value,source=fetch(report,'quarterly')
        if finite(value):return value,source,None,dict(status='verified',method=VERSION,inputs=inputs)
        inputs=[];issues=[]
    current,cs=fetch(report,'annual' if quarter==4 else 'cumulative')
    previous,ps=(0,[]) if quarter==1 else fetch(REPORTS[quarter-2],'cumulative')
    candidate=current-previous if finite(current) and finite(previous) else None
    if finite(candidate):
        signatures={accounts(s) for s in cs+ps}
        scopes={s.get('scope','company') for s in cs+ps}
        versions={s.get('data_version') for s in cs+ps}
        if len(signatures)!=1 or len(scopes)!=1 or len(versions)!=1:issues.append('definition_mismatch')
        if candidate<0:issues.append('negative_difference')
        if not issues:return candidate,cs+ps,'검증된 누적값 차감',dict(status='verified',method=VERSION,inputs=inputs,candidate=candidate)
    if candidate is None and len(inputs)==(1 if quarter==1 else 2):
        candidate=inputs[0]['value']-(inputs[1]['value'] if quarter>1 else 0)
        if candidate<0:issues.append('negative_difference')
    if candidate is None and not issues and allow_annual:
        annual,annual_sources=fetch('FY','annual')
        others=[resolve(read,year,basis,q,False) for q in range(1,5) if q!=quarter]
        if finite(annual) and all(finite(item[0]) for item in others):
            combined=annual_sources+[s for item in others for s in item[1]]
            candidate=annual-sum(item[0] for item in others)
            if candidate>=0 and len({accounts(s) for s in combined})==1 and len({s.get('data_version') for s in combined})==1:
                return candidate,combined,'검증된 연간값에서 다른 3개 분기 차감',dict(status='verified',method=VERSION,inputs=inputs,
                    other_quarters=[item[3] for item in others],candidate=candidate)
            issues.append('negative_difference' if candidate<0 else 'definition_mismatch')
    return None,cs+ps,None,dict(status='unverified',method=VERSION,reasons=sorted(set(issues or ['missing_inputs'])),inputs=inputs,candidate=candidate,
        message='누적 CAPEX의 출처·기간·계정 기준을 확인하고 있습니다. 검증 전에는 CAPEX와 FCF Margin을 표시하지 않습니다.')
