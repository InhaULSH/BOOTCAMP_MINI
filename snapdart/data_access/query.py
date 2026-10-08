"""Typed sector/company/period query context; no model-generated SQL."""
from dataclasses import dataclass
from .repository import Repository

@dataclass(frozen=True)
class Query:
    question: str
    sector: str|None=None
    company: str|None=None
    year: int|None=None
    report_type: str='FY'
    basis: str='CFS'
    value_type: str|None=None
    intent: str='hybrid'
    top_k: int=5

def retrieve(query:Query):
    if query.intent not in ('financial','filing','hybrid'):raise ValueError('intent는 financial/filing/hybrid 중 하나입니다.')
    if query.report_type not in ('FY','Q1','H1','HY','Q3'):raise ValueError('보고서 유형이 올바르지 않습니다.')
    if query.basis not in ('CFS','OFS'):raise ValueError('재무 기준이 올바르지 않습니다.')
    repo=Repository(query.sector);year=query.year if query.year is not None else repo.years()[-1]
    companies=[repo.company(query.company)] if query.company else repo.companies()
    financial=[];chunks=[];statuses=[]
    report_type='H1' if query.report_type=='HY' else query.report_type
    for company in companies:
        code=company['stock_code']
        if query.intent in ('financial','hybrid'):
            financial.append(dict(company=company['company_name'],**repo.financial(code,year,report_type,query.basis,query.value_type)))
        if query.intent in ('filing','hybrid'):
            rows,status=repo.search(query.question,code,year,report_type,query.top_k)
            chunks.extend(rows);statuses.append(status)
    return dict(sector=repo.sector.name,question=query.question,year=year,report_type=report_type,intent=query.intent,
        financial_data=financial,retrieved_chunks=chunks,retrieval=statuses)
