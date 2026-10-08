"""Storyboard presentation adapter: no ingestion, model calls or invented data."""
from .data_access.repository import Repository
from .data_access.catalog import sectors
from .dashboard import load_view
from dart_remote.market_summary import index_market_cap
from .data_access.sources import revenue_source

KEYS=('revenue','operating_income','capex','operating_cashflow')
REPORT_TYPES=('Q1','H1','Q3','FY')

def quarter_rows(repo,company,years):
    output=[]
    for year in years:
        annual=next((r for r in company['history'] if r['year']==year),{})
        basis=annual.get('basis') or 'CFS'
        cumulative=[repo.financial(company['code'],year,t,basis) for t in REPORT_TYPES]
        for i,t in enumerate(REPORT_TYPES):
            direct=repo.financial(company['code'],year,t,basis,'quarterly')
            values={}
            for key in KEYS:
                if direct.get(key) is not None:values[key]=direct[key]
                elif i==0:values[key]=cumulative[i][key]
                else:
                    a,b=cumulative[i][key],cumulative[i-1][key]
                    values[key]=a-b if a is not None and b is not None else None
            if values['capex'] is not None and values['capex']<0:values['capex']=None
            output.append(dict(period=f'{year} Q{i+1}',basis=basis,revenue=values['revenue'],
                operatingProfit=values['operating_income'],capex=values['capex'],operatingCashFlow=values['operating_cashflow']))
    return output

def keywords(scope,year):
    # Pass production signal and visual weights without front-end normalization.
    supplied=scope.get('keywords',[])
    if isinstance(supplied,dict):supplied=supplied.get(str(year),[])
    if supplied:return supplied
    summaries=scope.get('keyword_insights',{}).get(str(year),{})
    output=[]
    for r in scope.get('wordcloud',{}).get(str(year),[])[:12]:
        score=r.get('final_signal_score')
        reason=(f"현재 언급 점수 {r['current_score']:.1f}점, 변화 점수 {r['change_score']:.1f}점, "
                f"확산 점수 {r['spread_score']:.1f}점에 50%·30%·20%를 적용했습니다. "
                f"기업 집중 감점 {r['concentration_penalty']:.1f}점과 일반 경영 감점 "
                f"{r['generic_business_penalty']}점을 빼 최종 {score:.1f}점입니다.") if score is not None else ''
        output.append(dict(keyword=r.get('keyword',r['text']),label=r.get('label',r['text']),count=r['count'],signalScore=score,
            final_signal_score=score,display_weight=r.get('display_weight'),is_hot=r.get('is_hot',False),
            isHot=r.get('is_hot',False),disclosureContext='',selectionReason=reason,source_refs=[],
            insight=summaries.get(r['text']),signal=r))
    return output


def project(selected=None):
    result=dict(sectors=[],companies=[],marketCapUnit='원')
    if selected is None:
        # Home reads catalogue + stored snapshots only, never rebuilds reports.
        from dart_remote.artifacts import get_artifact
        for registered in sectors():
            report=get_artifact(registered.id,'report') or {}
            market=get_artifact(registered.id,'market') or {};index=market.get('index',{})
            entries=[registered.id+':'+c['code'] for c in report.get('companies',[])]
            cap=index_market_cap(market)
            result['sectors'].append(dict(id=registered.id,name=registered.name,indexName=index.get('name') or registered.name+' 지수',
                analysisCompanyIds=entries,indexSeries=index.get('history',[]),indexReturnPct=index.get('change'),
                returnPeriod=index.get('traded_at','')+' 종가 · 직전 거래일 대비',
                **cap,reportAvailable=bool(report)))
        return result

    for registered in sectors():
        # Home does not trigger report rebuilding or DB financial scans for every sector.
        if selected and registered.id!=selected:
            result['sectors'].append(dict(id=registered.id,name=registered.name,analysisCompanyIds=[]));continue
        count=len(result['companies'])
        try:
            view=load_view(registered.id);repo=Repository(registered.id);years=view['years'];year=years[-1]
            index=view.get('market',{}).get('index',{})
            entries=[]
            for c in view['companies']:
                quote=view.get('market',{}).get('quotes',{}).get(c['code'],{})
                cid=registered.id+':'+c['code'];entries.append(cid)
                insight=c.get('ai_insights',{}).get(str(year),{})
                result['companies'].append(dict(id=cid,code=c['code'],sectorId=registered.id,name=c['name'],businessSummary=c['description'],
                    amountUnit='원',financials=quarter_rows(repo,c,years) if selected else [],dailyReturnPct=quote.get('change'),stockSeries=quote.get('history',[]),
                    marketSeriesPeriod=quote.get('traded_at','')+' 종가',keywords=keywords(c,year),aiInsight=insight,
                    disclosureSummary=c.get('disclosure_summary'),metricInsights=c.get('metric_insights',{})))
            result['sectors'].append(dict(id=registered.id,name=registered.name,indexName=index.get('name') or registered.name+' 지수',
                indexSeries=index.get('history',[]),indexReturnPct=index.get('change'),returnPeriod=index.get('traded_at','')+' 종가 · 직전 거래일 대비',
                **index_market_cap(view.get('market',{})),
                analysisCompanyIds=entries,coverage=view.get('coverage',{}),periods=[f'{y} Q{q}' for y in years for q in range(1,5)],keywords=keywords(view,year),
                aiInsight=view.get('ai_insights',{}).get(str(year),{}),metricInsights=view.get('metric_insights',{}),
                marketSeriesPeriod=index.get('traded_at','')+' 종가'))
        except (KeyError,ValueError,RuntimeError) as error:
            import logging
            logging.getLogger(__name__).warning('Sector %s unavailable: %s',registered.id,error)
            del result['companies'][count:]
            result['sectors'].append(dict(id=registered.id,name=registered.name,analysisCompanyIds=[],
                status='unavailable',statusMessage='이 산업의 분석 자료가 아직 준비되지 않았습니다.'))
    return result

def quarter_source(sector,code,year,quarter,key):
    if not 1<=quarter<=4 or key not in KEYS+('fcf',):raise ValueError('분기·지표를 확인하세요.')
    repo=Repository(sector)
    basis=repo.financial(code,year)['basis'] or 'CFS'
    components=[]
    keys=('operating_cashflow','capex') if key=='fcf' else (key,)
    for metric in keys:
        direct=repo.financial(code,year,REPORT_TYPES[quarter-1],basis,'quarterly') 
        direct_sources=direct.get('financial_sources',{}).get(metric,[])
        genuine_direct=direct.get(metric) is not None and any(not s.get('is_calculated') for s in direct_sources)
        periods=[quarter-1] if quarter==1 or genuine_direct else [quarter-1,quarter-2]
        for index in periods:
            t=REPORT_TYPES[index];f=repo.financial(code,year,t,basis,'quarterly' if genuine_direct else None)
            try:source=revenue_source(code,year,metric,sector_id=sector,report_type=t,basis=basis,value_type='quarterly' if genuine_direct else None)
            except (KeyError,ValueError,OSError):source=None
            components.append(dict(metric=metric,reportType=t,value=f[metric],source=source))
    return dict(company=repo.company(code)['company_name'],year=year,quarter=quarter,components=components,
        note='분기 수치는 직접 분기값이 있으면 사용하고, 나머지는 같은 재무 기준의 누적값 차이로 계산합니다. 표에는 해당 원본 누적값이 표시됩니다.')
