"""Reconcile approved metrics against exact, independently identified XML cells.

Never rewrites upstream receipts. Unknown/ambiguous contexts fail closed.
"""
import hashlib
import io
import json
import logging
import os
import re
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal
from functools import lru_cache
from . import db, artifacts
from .asset_versions import source_versions, version_filter
from .xml_source import decode, sanitize
from .xml_financials import number, grid

VERSION='receipt-proof-v1'
REPORT_CODES={'FY':('11011',),'Q1':('11013',),'H1':('11012',),'Q3':('11013','11014')}
# DART XML uses the quarterly document code for both Q1 and Q3;
# ACONTEXT below determines the exact reporting period.
_download_failures={}
PERIODS={'FY':('annual','FY'),'FQA':('cumulative','Q1'),'FQQ':('quarterly','Q1'),
         'HYA':('cumulative','H1'),'HYQ':('quarterly','H1'),
         'TQA':('cumulative','Q3'),'TQQ':('quarterly','Q3')}
SCOPE={'holding_consolidated':'CFS','bank_separate':'OFS'}
MAX_BYTES=100*1024*1024

class Unverified(ValueError):pass

def strict_fragment(fragment):
    fixed,_=sanitize(fragment)
    # No recovery: a malformed financial table is never used as proof.
    return ET.fromstring(fixed)

@lru_cache(maxsize=4)
def db_document(document_id,version,sha,size):
    rows=db.rows('SELECT raw_xml FROM filing_source_documents WHERE document_id=:d AND data_version=:v AND is_active=1',dict(d=document_id,v=version))
    if len(rows)!=1:raise Unverified('원문이 조회 중 변경되었습니다.')
    raw=bytes(rows[0]['raw_xml'])
    if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=sha:raise Unverified('원문 무결성 검사 실패')
    return raw

def api_documents(receipt):
    key=os.getenv('OPENDART_API_KEY')
    failure_key=(receipt,hashlib.sha256((key or '').encode()).hexdigest())
    failed=_download_failures.get(failure_key)
    if failed and time.monotonic()-failed[0]<60:raise Unverified(failed[1])
    cache=artifacts.ROOT/'receipt_xml'/f'{receipt}.zip'
    if cache.exists():data=cache.read_bytes()
    else:
        if not key:raise Unverified('불일치 출처의 원문이 DB에 없고 OPENDART_API_KEY도 없습니다.')
        import requests
        try:
            with requests.get('https://opendart.fss.or.kr/api/document.xml',params=dict(crtfc_key=key,rcept_no=receipt),timeout=(10,60),stream=True) as response:
                if response.status_code!=200:raise Unverified('OPENDART 원문 요청 실패')
                output=bytearray()
                for part in response.iter_content(1024*1024):
                    output.extend(part)
                    if len(output)>MAX_BYTES:raise Unverified('원문 크기 제한 초과')
                data=bytes(output)
        except requests.RequestException:raise Unverified('OPENDART 원문 연결 실패') from None
        if not zipfile.is_zipfile(io.BytesIO(data)):
            try:status=ET.fromstring(data).findtext('status') or 'unknown'
            except ET.ParseError:status='invalid_response'
            message='OPENDART 원문을 받지 못했습니다. 상태 코드: '+status
            if len(_download_failures)>100:_download_failures.clear()
            _download_failures[failure_key]=(time.monotonic(),message)
            raise Unverified(message)
        cache.parent.mkdir(parents=True,exist_ok=True)
        temporary=cache.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        try:temporary.write_bytes(data);os.replace(temporary,cache)
        finally:temporary.unlink(missing_ok=True)
    output=[]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries=[i for i in z.infolist() if i.filename.lower().endswith('.xml')]
        if sum(i.file_size for i in entries)>MAX_BYTES:raise Unverified('압축 해제 크기 제한 초과')
        for item in entries:
            raw=z.read(item);output.append((raw,dict(document_id=item.filename,sha256=hashlib.sha256(raw).hexdigest(),origin='opendart')))
    if not output:raise Unverified('XML 원문이 없습니다.')
    return output

def documents(receipt,version):
    if not re.fullmatch(r'\d{14}',str(receipt)):raise Unverified('접수번호 형식 오류')
    params=dict(r=receipt);condition=version_filter('data_version',source_versions(version),params)
    rows=db.rows('SELECT document_id,data_version,sha256,byte_size FROM filing_source_documents WHERE rcept_no=:r AND is_active=1 AND '+condition,params)
    if rows:return [(db_document(r['document_id'],r['data_version'],r['sha256'],r['byte_size']),dict(r,origin='mysql')) for r in rows]
    return api_documents(receipt)

@lru_cache(maxsize=4)
def tagged_facts(raw):
    source,_=decode(raw)
    companies=re.findall(r'<COMPANY-NAME\b[^>]*>[\s\S]*?</COMPANY-NAME>',source)
    names=re.findall(r'<DOCUMENT-NAME\b[^>]*>[\s\S]*?</DOCUMENT-NAME>',source)
    if len(companies)!=1 or len(names)!=1:raise Unverified('원문의 기업·보고서 식별이 모호합니다.')
    company=strict_fragment(companies[0]);name=strict_fragment(names[0])
    identity=dict(corp_code=company.get('AREGCIK'),report_code=name.get('ACODE'))
    output=[];table_index=0
    # Match complete tables only. Any malformed/nested table is rejected.
    for match in re.finditer(r'<TABLE\b[^>]*>[\s\S]*?</TABLE>',source):
        table_index+=1
        try:table=strict_fragment(match.group());rows,_=grid(table)
        except (ET.ParseError,ValueError,TypeError):continue
        if any(n is not table and n.tag=='TABLE' for n in table.iter()):continue
        # Unit must be declared, independent of the XBRL rounding precision.
        intro=source[max(0,match.start()-16000):match.start()]
        units=re.findall(r'단위\s*[:：]\s*(백만원|천원|억원|원)',intro)
        if not units:continue
        unit=units[-1];multiplier={'원':1,'천원':1000,'백만원':1000000,'억원':100000000}[unit]
        for ri,tr in enumerate(n for n in table.iter() if n.tag=='TR'):
            for ci,cell in enumerate(n for n in tr if n.tag in ('TE','TU','TD','TH')):
                aid=cell.get('ACODE');context=cell.get('ACONTEXT','')
                m=re.fullmatch(r'CFY(\d{4})([de])([A-Z]+)_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_(Consolidated|Separate)Member',context)
                if not aid or not m:continue # additional segment axes are not the whole company
                year,kind,period,basis=m.groups()
                if period not in PERIODS:continue
                value_type,report=PERIODS[period]
                if kind=='e':value_type='point_in_time'
                amount=number(''.join(cell.itertext()),multiplier)
                if amount is None:continue
                precision=cell.get('ADECIMAL')
                if precision != str(-len(str(multiplier))+1):continue
                negated=cell.get('ANEGATED','N')
                if negated not in ('Y','N'):continue
                amount=-amount if negated=='Y' else amount
                output.append(dict(account_id=aid,context=context,year=int(year),report_type=report,value_type=value_type,
                    fs_div='CFS' if basis=='Consolidated' else 'OFS',value=amount,original_unit=unit,
                    table_index=table_index,row_index=ri,column_index=ci,cell_text=''.join(cell.itertext()),
                    source_text=' '.join(tr.itertext()).strip(),negated=negated))
    return identity,output

def prove(row,receipt,version):
    """Require a unique semantic cell value, not a substring containing a number."""
    matches=[]
    for raw,meta in documents(receipt,version):
        try:identity,facts=tagged_facts(raw)
        except (Unverified,ET.ParseError):continue
        if identity['corp_code']!=row['corp_code'] or identity['report_code'] not in REPORT_CODES.get(row['report_type'],()):continue
        for fact in facts:
            if all(fact.get(k)==row.get(k) for k in ('year','report_type','fs_div','value_type')) and fact['account_id']==row.get('source_account_id'):
                matches.append(dict(fact,rcept_no=receipt,document_id=meta['document_id'],sha256=meta['sha256'],origin=meta['origin']))
    values={r['value'] for r in matches}
    if values!={row['value']}:raise Unverified('원문의 계정·기간·단위 수치가 없거나 저장값과 다릅니다.')
    return matches

def validate(row,active,version,candidates):
    """Return evidence only after both receipts and every FY-Q3 input match."""
    if row.get('review_status')!='approved' or row.get('unit')!='KRW':raise Unverified('승인된 원화 수치가 아닙니다.')
    if SCOPE.get(row.get('scope'))!=row.get('fs_div'):raise Unverified('검증을 지원하지 않는 회계 범위입니다.')
    if any(row.get(k)!=active.get(k) for k in ('corp_code','year','report_type')):raise Unverified('대조 공시의 기업·기간이 다릅니다.')
    receipt=row.get('source_rcept_no');evidence=[]
    if row['value_type']=='quarterly' and row['report_type']=='FY':
        inputs=row.get('source_values') or {}
        try:inputs=json.loads(inputs) if isinstance(inputs,str) else inputs
        except ValueError:raise Unverified('계산 입력 형식 오류') from None
        if not isinstance(inputs,dict) or not all(isinstance(inputs.get(k),(int,float)) and not isinstance(inputs[k],bool) for k in ('FY','Q3')):raise Unverified('4분기 계산 입력이 없습니다.')
        if Decimal(str(inputs['FY']))-Decimal(str(inputs['Q3']))!=Decimal(str(row['value'])):raise Unverified('4분기 계산식이 저장값과 다릅니다.')
        annual=dict(row,value_type='annual',value=inputs['FY'])
        evidence+=prove(annual,receipt,version)+prove(annual,active['rcept_no'],version)
        previous=[r for r in candidates if all(r.get(k)==row.get(k) for k in ('corp_code','year','fs_div','scope','metric_code')) and r.get('report_type')=='Q3' and r.get('value_type')=='cumulative' and r.get('active_rcept_no')==r.get('source_rcept_no') and r.get('value')==inputs['Q3']]
        if not previous:raise Unverified('승인된 동일 기준 Q3 누적 입력이 없습니다.')
        previous_values={r['value'] for r in previous}
        if len(previous_values)!=1:raise Unverified('Q3 입력값 충돌')
        evidence+=prove(previous[0],previous[0]['source_rcept_no'],version)
        formula='FY - Q3'
    else:
        evidence+=prove(row,receipt,version)+prove(row,active['rcept_no'],version);formula=None
    return dict(status='verified',method=VERSION,verified_at=int(time.time()),stored_receipt=receipt,
        active_receipt=active['rcept_no'],formula=formula,evidence=evidence)

def reconcile(rows,version):
    accepted=[]
    for row in rows:
        if row.get('review_status')!='approved' or row.get('unit')!='KRW':continue
        if row.get('active_rcept_no') and row.get('source_rcept_no')==row.get('active_rcept_no'):
            accepted.append(row);continue
        if not row.get('active_rcept_no'):continue
        active=dict(corp_code=row['corp_code'],year=row['year'],report_type=row['report_type'],rcept_no=row['active_rcept_no'])
        try:
            proof=validate(row,active,version,rows)
            key=hashlib.sha256(json.dumps([VERSION,version,row,proof['evidence']],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
            artifacts.put_artifact('_receipt_validation','proof',proof,key)
            accepted.append(dict(row,receipt_validation=proof))
        except (Unverified,ET.ParseError,OSError,ValueError,zipfile.BadZipFile) as error:
            failure=dict(status='unverified',method=VERSION,checked_at=int(time.time()),stored_receipt=row.get('source_rcept_no'),
                active_receipt=row.get('active_rcept_no'),reason=str(error),metric_code=row['metric_code'],value_type=row['value_type'])
            key=hashlib.sha256(json.dumps([VERSION,version,row],sort_keys=True,default=str).encode()).hexdigest()
            try:artifacts.put_artifact('_receipt_validation','failure',failure,key)
            except OSError:pass
            logging.getLogger(__name__).warning('원문 대조 미통과: corp=%s year=%s report=%s metric=%s reason=%s',row['corp_code'],row['year'],row['report_type'],row['metric_code'],str(error))
    return accepted
