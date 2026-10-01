"""DB citations and immutable original XML tables; no inferred reconstructed tables."""
from functools import lru_cache
import json
import re
from .repository import Repository
from .catalog import connect,sector

def source_excerpt(ref,sector_id=None):
    repo=Repository(sector_id)
    report=json.loads(repo.sector.report.read_text(encoding='utf-8'))
    citation=report.get('citations',{}).get(ref)
    if not citation:raise KeyError('등록되지 않은 출처입니다.')
    if citation.get('source_kind')=='financial':
        financial=repo.financial(citation['code'],citation['year'],citation.get('report_type','FY'),basis=citation.get('basis','CFS'))
        text=' · '.join(f'{name}: {financial[key]:,}원' for key,name in [('revenue','매출'),('operating_income','영업이익'),('capex','현금 유형자산 취득'),('operating_cashflow','영업활동현금흐름')] if financial[key] is not None)
        result=dict(citation=citation,blocks=[dict(paragraph_id=citation['paragraph_id'],text=text,highlight=[0,len(text)])],document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+citation['receipt_no'])
        if citation.get('report_type','FY')=='FY':
            try:result['table']=revenue_source(citation['code'],citation['year'],sector_id=repo.sector.id)['table']
            except KeyError:pass
        return result
    row=repo.chunk(citation['chunk_id']);text=row['chunk_text']
    a,b=citation['start_char'],citation['end_char']
    if text[a:b]!=citation['quote']:raise ValueError('DB 원문과 각주 위치가 일치하지 않습니다. 보고서를 다시 생성하세요.')
    # Query adjacent chunk IDs inside the exact same document/section, using numeric chunk order.
    with connect(repo.sector.filings) as con:
        rows=[dict(r) for r in con.execute('SELECT chunk_id,chunk_text FROM filing_chunks WHERE rcept_no=? AND section_name=?',(row['rcept_no'],row['section_name']))]
    def order(r):return tuple(int(p) if p.isdigit() else p for p in r['chunk_id'].split(':'))
    rows.sort(key=order);i=next(i for i,r in enumerate(rows) if r['chunk_id']==row['chunk_id'])
    blocks=[dict(paragraph_id=r['chunk_id'],text=r['chunk_text'],highlight=[a,b] if r['chunk_id']==row['chunk_id'] else None) for r in rows[max(0,i-1):i+2]]
    return dict(citation=citation,blocks=blocks,document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+row['rcept_no'])

@lru_cache(maxsize=30)
def _original(path,mtime):
    from .xml_source import extract
    from .xml_source import decode
    from .xml_source import table_rows
    source,_=decode(__import__('pathlib').Path(path).read_bytes())
    _,_,blocks,tables,checks=extract(source)
    if not checks['text_coverage_exact']:raise ValueError('원문 텍스트 추출 검증 실패')
    headings={b['table_id']:(b['section'],b['heading']) for b in blocks if b['table_id']}
    return [dict(table_id=t['table_id'],rows=table_rows(t),section=headings.get(t['table_id'],('',''))[0],heading=headings.get(t['table_id'],('',''))[1]) for t in tables]

def revenue_source(code,year,key='revenue',sector_id=None):
    repo=Repository(sector_id);company=repo.company(code)
    if key not in ('revenue','operating_income','capex','operating_cashflow'):raise KeyError('지표가 없습니다.')
    financial=repo.financial(code,year)
    if financial['basis'] is None:financial=repo.financial(code,year,basis='OFS')
    value=financial[key];sources=financial['financial_sources'][key]
    if not sources or value is None:raise KeyError('검증된 재무 수치가 없습니다.')
    from .repository import ACCOUNTS
    normalize=lambda name:re.sub(r'\s','',re.sub(r'\(주[^)]*\)','',name))
    names={normalize(r['original_account_nm']) for r in sources}|{normalize(n) for n in ACCOUNTS[key]}
    candidates=[];derived=[]
    for receipt in sorted({r['rcept_no'] for r in sources}):
        path=repo.sector.folder/'original'/f'{receipt}.xml'
        if not path.exists():continue
        for table in _original(str(path),path.stat().st_mtime_ns):
            heading=table['heading']
            if financial['basis']=='CFS' and '별도' in heading:continue
            if key=='capex' and sources[0].get('is_derived'):
                components=json.loads(sources[0]['source_values']);targets=[];scales=[]
                for component in components:
                    label=normalize(component['account_nm']);expected=component['normalized_value'];found=None
                    for original_row in table['rows']:
                        cells=original_row['cells']
                        if not cells or normalize(cells[0]['text'])!=label:continue
                        for cell in cells[1:2]:
                            try:amount=float(re.sub(r'[,\s]','',cell['text']).replace('(','-').replace(')','').replace('△','-').replace('−','-'))
                            except ValueError:continue
                            for scale in (1,1000,1000000,100000000):
                                if abs(abs(amount)*scale-abs(expected))<scale:found=(cell,scale);break
                    if not found:break
                    targets.append(found[0]);scales.append(found[1])
                if len(targets)==len(components) and targets and len(set(scales))==1 and abs(abs(sum(c['normalized_value'] for c in components))-value)<=1:
                    derived.append((0 if '연결' in heading else 1,table,targets,scales[0],receipt))
            for row in table['rows']:
                cells=row['cells']
                if not cells or normalize(cells[0]['text']) not in names:continue
                for cell in cells[1:2]:
                    raw=re.sub(r'[,\s]','',cell['text']).replace('(','-').replace(')','').replace('△','-').replace('−','-')
                    try:amount=float(raw)
                    except ValueError:continue
                    for scale in (1,1000,1000000,100000000):
                        if abs((abs(amount) if key=='capex' else amount)*scale-value)<scale:
                            candidates.append((0 if '연결' in heading else 1,table,cell,scale,receipt))
    if not candidates and not derived:raise KeyError('DB 금액과 일치하는 전체 원문 표를 확인하지 못했습니다.')
    if derived and not candidates:
        _,table,targets,scale,receipt=min(derived,key=lambda x:x[0]);target=targets[0]
    else:
        _,table,target,scale,receipt=min(candidates,key=lambda x:x[0]);targets=[target]
    marked={t['cell_path'] for t in targets}
    table=dict(table,rows=[dict(r,cells=[dict(c,highlight=c['cell_path'] in marked,primary_highlight=c['cell_path']==target['cell_path'],header='/TH[' in c['cell_path']) for c in r['cells']]) for r in table['rows']])
    return dict(company=company['company_name'],year=year,value=value,basis=financial['basis'],section=table['section'],heading=table['heading'],paragraph_id=target['cell_path'],table=table,
        unit={1:'원',1000:'천 원',1000000:'백만 원',100000000:'억 원'}[scale],derived=bool(sources[0].get('is_derived')),
        calculation_method=sources[0].get('calculation_method'),document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt)
