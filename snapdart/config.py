"""Shared paths; importing configuration never queries MySQL."""
from .settings import ROOT, load_env
from snapdart.data_access.catalog import SERVICE
SERVICE_ROOT=SERVICE

# Compatibility for older callers; active market collection selects explicitly.
def __getattr__(name):
    if name not in ('YEARS','COMPANIES'):raise AttributeError(name)
    from snapdart.data_access.repository import Repository
    repo=Repository()
    if name=='YEARS':return repo.years()
    return [dict(code=c['stock_code'],name=c['company_name'],sector=repo.sector.name,
        description='공시와 전사 재무 기반 분석') for c in repo.companies()]
