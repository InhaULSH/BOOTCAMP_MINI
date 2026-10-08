"""Conservative financial-table fallback when upstream JSON facts are absent.

No LLM estimates, upstream writes, or per-metric filling of existing JSON data.
"""
import hashlib
import re
from decimal import Decimal, InvalidOperation
from . import db, artifacts
from .original_document import parsed

VERSION='xml-financial-v2'
END_MONTH={'Q1':3,'H1':6,'Q3':9,'FY':12}
ALIASES={
    'revenue':('매출액','수익(매출액)','영업수익','수익'),
    'operating_income':('영업이익','영업이익(손실)','영업손익','영업손실'),
    'inventory':('재고자산',),
    'operating_cashflow':('영업활동현금흐름','영업활동으로인한현금흐름'),
    'capex':('유형자산의취득','유형자산취득','유형자산의취득으로인한현금유출'),
}
DATE=r'(\d{4})\s*[.년/-]\s*(\d{1,2})\s*[.월/-]\s*(\d{1,2})\s*일?'

def clean(text):
    return re.sub(r'\s+','',text)

def account(text):
    text=re.sub(r'\(?주\s*\d+(?:\s*[,，]\s*\d+)*\)?','',text)
    return re.sub(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX\d]+[.．]','',clean(text).lstrip('ㆍ·'))

def number(text,multiplier):
    text=clean(text).replace(',','').replace('−','-').replace('△','-')
    if re.fullmatch(r'\(\d+(?:\.\d+)?\)',text):text='-'+text[1:-1]
    if not re.fullmatch(r'-?\d+(?:\.\d+)?',text):return None
    try:
        value=Decimal(text)*multiplier
        return int(value) if value==value.to_integral_value() else None
    except InvalidOperation:return None

def grid(table):
    """Expand header spans but retain each original numeric cell only once."""
    occupied={};rows=[]
    for ri,tr in enumerate(n for n in table.iter() if n.tag.upper()=='TR'):
        row=[];col=0
        for cell in tr:
            if cell.tag.upper() not in ('TD','TH','TE','TU'):continue
            while (ri,col) in occupied:col+=1
            rs=int(cell.get('ROWSPAN',cell.get('rowspan','1')))
            cs=int(cell.get('COLSPAN',cell.get('colspan','1')))
            if not (1<=rs<=100 and 1<=cs<=100):raise ValueError('재무 표 병합 범위 오류')
            item=dict(text=' '.join(cell.itertext()).strip(),row=ri,column=col,rowspan=rs,colspan=cs)
            for r in range(ri,ri+rs):
                for c in range(col,col+cs):
                    if (r,c) in occupied:raise ValueError('재무 표 셀 중첩')
                    occupied[r,c]=item
            row.append(item);col+=cs
        rows.append(row)
    return rows,occupied

def extract_facts(raw,year,report_type,basis,value_type,receipt,document_id):
    root,_,_=parsed(raw)
    heading='';context='';table_index=0;found=[]
    # Title and date/unit introduction tables precede each actual statement.
    for node in root.iter():
        tag=node.tag.upper()
        if tag in ('TITLE','SUBTITLE'):
            heading=' '.join(node.itertext()).strip();context=''
        elif tag=='P':context+=' '+' '.join(node.itertext())
        elif tag=='TABLE':
            table_index+=1
            text=' '.join(node.itertext())
            caption=clean(text)
            if '재무제표' in clean(heading) and '주석' not in heading and caption in (
                '재무상태표','연결재무상태표','현금흐름표','연결현금흐름표',
                '손익계산서','연결손익계산서','포괄손익계산서','연결포괄손익계산서'):
                heading=heading.split(':',1)[0]+': '+caption;context=''
            kind=next((k for word,k in [('재무상태표','BS'),('현금흐름표','CF'),('손익계산서','IS')] if word in clean(heading)),None)
            if not kind or '주석' in heading or ('CFS' if '연결' in heading else 'OFS')!=basis:continue
            rows,cells=grid(node)
            accounts=[(row,cell,key) for row in rows for cell in row[:1]
                      for key,names in ALIASES.items() if account(cell['text']) in names]
            if not accounts:
                context+=' '+text;continue
            # EPS rows can specify "원" inside a "백만원" statement. Use
            # the statement introduction, not a unit attached to another row.
            header_text=' '.join(c['text'] for row in rows[:accounts[0][1]['row']] for c in row)
            units=re.findall(r'단위\s*[:：]\s*(백만원|천원|억원|원)',context or header_text)
            if not units or len(set(units))!=1:continue
            multiplier={'원':1,'천원':1000,'백만원':1000000,'억원':100000000}[units[-1]]
            dates=[tuple(map(int,m)) for m in re.findall(DATE,context)]
            if not any(y==year and m==END_MONTH[report_type] for y,m,d in dates):continue
            terms=re.findall(r'제\s*(\d+)\s*기[\s\S]{0,40}?'+DATE,context)
            current_terms={term for term,y,m,d in terms if int(y)==year}
            for row,label,key in accounts:
                if (key in ('revenue','operating_income') and kind!='IS' or key=='inventory' and kind!='BS'
                    or key in ('operating_cashflow','capex') and kind!='CF'):continue
                candidates=[]
                for cell in row[1:]:
                    if cell['colspan']!=1:continue
                    headers=' '.join(cells[r,cell['column']]['text'] for r in range(label['row']) if (r,cell['column']) in cells)
                    header_terms=re.findall(r'제\s*(\d+)\s*기',headers)
                    header_dates=[tuple(map(int,m)) for m in re.findall(DATE,headers)]
                    current=(any(t in current_terms for t in header_terms) or
                             any(y==year and m==END_MONTH[report_type] for y,m,d in header_dates))
                    if not current:continue
                    period='point_in_time' if kind=='BS' else ('annual' if report_type=='FY' else 'cumulative')
                    if report_type!='FY' and kind=='IS':
                        if '누적' in headers:period='cumulative'
                        elif re.search(r'3\s*개월',headers):period='quarterly'
                        elif report_type!='Q1' and len([c for c in row[1:] if number(c['text'],1) is not None])>2:
                            continue # Ambiguous three-month vs cumulative columns.
                    if kind!='BS' and value_type!=period and not (report_type=='Q1' and value_type in ('quarterly','cumulative')):continue
                    if kind!='BS' and period in ('annual','cumulative') and not any(y==year and m==1 and d==1 for y,m,d in dates):continue
                    amount=number(cell['text'],multiplier)
                    if amount is None:continue
                    if key=='capex':amount=abs(amount)
                    if account(label['text'])=='영업손실':amount=-abs(amount)
                    candidates.append(dict(key=key,value=amount,currency='KRW',sj_div=kind,
                        original_account_nm=label['text'],rcept_no=receipt,document_id=document_id,
                        table_index=table_index,row_index=cell['row'],column_index=cell['column'],
                        source_text=' '.join(c['text'] for c in row),section='III. 재무에 관한 사항',heading=heading,
                        original_table=rows,original_unit=units[-1],
                        fs_div=basis,value_type=period,source_kind='xml',is_derived=False,calculation_method=None))
                # Multiple compatible columns are not resolved by choosing the first.
                if len(candidates)==1:found.extend(candidates)
    return found

def load(repo,code,year,report_type,basis,value_type):
    version=repo.sector.data_version.split(':',1)[0]
    docs=[d for d in repo.documents(code) if d['year']==int(year) and d['report_type']==report_type]
    if not docs:return [],'해당 기간 원본 공시가 없습니다.'
    receipt=max(docs,key=lambda d:(d.get('rcept_dt') or '',d['rcept_no']))['rcept_no']
    documents=db.rows('SELECT document_id,sha256,byte_size FROM filing_source_documents '
        'WHERE rcept_no=:r AND data_version=:v AND is_active=1',dict(r=receipt,v=version))
    cache_key=hashlib.sha256(repr((VERSION,version,receipt,documents,year,report_type,basis,value_type)).encode()).hexdigest()
    cached=artifacts.get_artifact('_xml_financial','facts',cache_key)
    if cached is not None:return cached['rows'],cached['note']
    rows=[];errors=[]
    for doc in documents:
        source=db.rows('SELECT raw_xml FROM filing_source_documents WHERE document_id=:d AND data_version=:v AND is_active=1',dict(d=doc['document_id'],v=version))
        if not source:raise RuntimeError('XML 조회 중 데이터가 변경되었습니다.')
        raw=bytes(source[0]['raw_xml'])
        if len(raw)!=doc['byte_size'] or hashlib.sha256(raw).hexdigest()!=doc['sha256']:
            raise ValueError('재무 보완 XML 체크섬 또는 크기 오류')
        try:rows.extend(extract_facts(raw,int(year),report_type,basis,value_type,receipt,doc['document_id']))
        except (ValueError,TypeError) as error:errors.append(str(error))
    note='JSON 재무 자료 부재로 원본 XML 표에서 검증된 수치를 추출했습니다.' if rows else 'XML에서 단위·기간·계정을 확정할 수 있는 재무 수치가 없습니다.'
    if errors:note+=' 일부 XML 표를 해석하지 못했습니다.'
    artifacts.put_artifact('_xml_financial','facts',dict(rows=rows,note=note),cache_key)
    return rows,note

def source_view(row):
    """Render the exact extracted table, including spans, without chunk guessing."""
    from html import escape
    body='<h3>'+escape(row['heading'])+'</h3><p>단위: '+escape(row['original_unit'])+'</p><table>'
    for cells in row['original_table']:
        body+='<tr>'
        for cell in cells:
            style=' style="background:#fff1aa"' if (cell['row'],cell['column'])==(row['row_index'],row['column_index']) else ''
            body+=f'<td rowspan="{cell["rowspan"]}" colspan="{cell["colspan"]}"{style}>'+escape(cell['text'])+'</td>'
        body+='</tr>'
    body+='</table>'
    return '<!doctype html><meta charset="utf-8"><style>body{font:14px/1.7 sans-serif;margin:24px}table{border-collapse:collapse}td{padding:7px;border:1px solid #ddd}</style>'+body
