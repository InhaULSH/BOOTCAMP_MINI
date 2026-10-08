"""Source resolution from immutable remote MySQL chunks and financial rows."""
from .repository import Repository,ACCOUNTS
from . import db

def source_excerpt(ref,sector_id,load_report):
    repo=Repository(sector_id);citation=load_report(repo.sector.id).get('citations',{}).get(ref)
    if not citation:raise KeyError('등록되지 않은 출처입니다.')
    if citation.get('source_kind')=='financial':
        f=repo.financial(citation['code'],citation['year'],citation.get('report_type','FY'),citation.get('basis') or 'CFS')
        text=' · '.join(f'{name}: {f[key]:,}원' for key,name in [('revenue','매출'),('operating_income','영업이익'),('capex','CAPEX'),('operating_cashflow','영업활동현금흐름')] if f[key] is not None)
        result=dict(citation=citation,blocks=[dict(paragraph_id=citation['paragraph_id'],text=text,highlight=[0,len(text)])],document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+citation['receipt_no'])
        try:result.update(revenue_source(citation['code'],citation['year'],sector_id=sector_id,report_type=citation.get('report_type','FY'),basis=f['basis']))
        except KeyError:pass
        from .original_document import document_view
        receipt=citation.get('receipt_no') or result.get('document_url','').split('rcpNo=')[-1]
        result.update(document_view(receipt,result.get('source_text') or text,result.get('section',''),result.get('heading',''),chunk_id=result.get('paragraph_id') or None,data_version=repo.sector.data_version.split(':',1)[0]))
        result['blocks']=[]
        return result
    from .citation_selection import natural_passage
    if not natural_passage(citation['quote']):raise ValueError('이 각주는 이전 선정 기준으로 생성되었습니다. 자연어 근거 기준으로 분석을 다시 생성하세요.')
    row=repo.chunk(citation['chunk_id']);a,b=citation['start_char'],citation['end_char']
    if row['chunk_text'][a:b]!=citation['quote']:raise ValueError('청크 버전과 각주가 다릅니다. 분석을 다시 생성하세요.')
    from .original_document import document_view
    return dict(citation=citation,blocks=[],
        document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+row['rcept_no'],
        **document_view(row['rcept_no'],citation['quote'],citation.get('section',''),citation.get('heading',''),citation.get('summary_text',''),chunk_id=row['chunk_id'],data_version=row['data_version']))


def revenue_source(code,year,key='revenue',sector_id=None,report_type='FY',basis=None,value_type=None):
    repo=Repository(sector_id)
    if key not in ACCOUNTS:raise KeyError('지표가 없습니다.')
    f=repo.financial(code,year,report_type,basis or 'CFS',value_type)
    if basis is None and f['basis'] is None:f=repo.financial(code,year,report_type,'OFS',value_type)
    if f[key] is None:raise KeyError('해당 지표의 재무 수치가 없습니다.')
    sources=f['financial_sources'][key];receipt=next(iter({r['rcept_no'] for r in sources}),'')
    if f.get('financial_source')=='xml':
        from .xml_financials import source_view
        row=sources[0]
        return dict(company=repo.company(code)['company_name'],year=year,value=f[key],basis=f['basis'],
            section=row['section'],heading=row['heading'],paragraph_id='',document_id=row['document_id'],unit='원',
            table=None,source_text=row['source_text'],derived=False,calculation_method=None,
            note=f['financial_note'],document_html=source_view(row),highlight_matched=True,
            document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt)
    names={r['original_account_nm'] for r in sources}|set(ACCOUNTS[key])
    candidates=repo.chunks(code,year,report_type)
    relevant=[r for r in candidates if r['rcept_no']==receipt and any(n in r['chunk_text'] for n in names)]
    row=next((r for r in relevant if r['section_name'].startswith('III.')),next(iter(relevant),None))
    return dict(company=repo.company(code)['company_name'],year=year,value=f[key],basis=f['basis'],
        section=row['section_name'] if row else '재무제표',heading=row.get('subsection_name') or '재무 수치 출처' if row else '재무 수치 출처',
        paragraph_id=row['chunk_id'] if row else '',unit='원',table=None,source_text=row['chunk_text'] if row else '',
        derived=any(r.get('is_derived') for r in sources),calculation_method=sources[0].get('calculation_method'),
        note='원격 DB에는 원본 표의 셀 구조가 없습니다. 관련 공시 문구와 DART 원문 링크를 제공합니다.',
        document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt)
