"""Storyboard presentation adapter: no ingestion, model calls or invented data."""
from .data_access.repository import Repository
from .data_access.catalog import sectors
from .dashboard import load_view
from dart_remote.market_summary import index_market_cap
from dart_remote.graph_metrics import GraphData,catalog,financial_flow
from dart_remote.capex_validation import flow as capex_flow
from dart_remote.runtime_cache import request_scope,cached_project,cached_graph
from .data_access.sources import revenue_source

KEYS=('revenue','operating_income','capex','operating_cashflow')
REPORT_TYPES=('Q1','H1','Q3','FY')

def quarter_rows(repo,company,years):
    output=[]
    for year in years:
        annual=next((r for r in company['history'] if r['year']==year),{})
        basis=annual.get('basis') or 'CFS'
        for i,t in enumerate(REPORT_TYPES):
            values={};derived={}
            for key in KEYS:
                if key=='capex':continue
                values[key],_,method=financial_flow(repo,company['code'],year,i+1,basis,key)
                if method:derived[dict(revenue='revenue',operating_income='operatingProfit',capex='capex',operating_cashflow='operatingCashFlow')[key]]=method
            values['capex'],_,method,validation=capex_flow(repo,company['code'],year,basis,i+1)
            if method:derived['capex']=method
            output.append(dict(period=f'{year} Q{i+1}',basis=basis,revenue=values['revenue'],
                operatingProfit=values['operating_income'],capex=values['capex'],operatingCashFlow=values['operating_cashflow'],derivedFields=derived,
                capexValidation=validation))
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


@request_scope
def project(selected=None,company=None):
    import logging,time
    start=time.perf_counter()
    try:return cached_project(_project,selected,sectors(),company)
    finally:logging.getLogger(__name__).debug('UI project %s %.3fs',selected or 'home',time.perf_counter()-start)

def _project(selected=None,company=None):
    result=dict(sectors=[],companies=[],marketCapUnit='원')
    if selected is None:
        # Home reads catalogue + stored snapshots only, never rebuilds reports.
        from dart_remote.artifacts import home_summary
        for registered in sectors():
            summary=home_summary(registered.id)
            result['sectors'].append(dict(id=registered.id,name=registered.name,indexName=summary['indexName'] or registered.name+' 지수',
                analysisCompanyIds=summary['entries'],indexSeries=summary['indexSeries'],indexReturnPct=summary['indexReturnPct'],
                returnPeriod=summary['tradedAt']+' 종가 · 직전 거래일 대비',
                **summary['cap'],reportAvailable=summary['reportAvailable']))
        return result

    for registered in sectors():
        # Home does not trigger report rebuilding or DB financial scans for every sector.
        if selected and registered.id!=selected:
            result['sectors'].append(dict(id=registered.id,name=registered.name,analysisCompanyIds=[]));continue
        count=len(result['companies'])
        try:
            view=load_view(registered.id);repo=Repository(registered);years=view['years'];year=years[-1]
            graphs=GraphData(repo);metrics=catalog(registered.membership_code)
            index=view.get('market',{}).get('index',{})
            entries=[]
            for c in view['companies']:
                quote=view.get('market',{}).get('quotes',{}).get(c['code'],{})
                cid=registered.id+':'+c['code'];entries.append(cid)
                if company is not None and c['code']!=company:
                    result['companies'].append(dict(id=cid,code=c['code'],sectorId=registered.id,name=c['name']))
                    continue
                insight=c.get('ai_insights',{}).get(str(year),{})
                result['companies'].append(dict(id=cid,code=c['code'],sectorId=registered.id,name=c['name'],businessSummary=c['description'],
                    metricProfile='bank' if graphs.bank else 'health' if graphs.health else 'industrial',metricCatalog=metrics,amountUnit='원',financials=cached_graph(lambda:graphs.public_rows(c,years,quarter_rows),registered,dict(code=c['code'],history=c['history']),years) if selected else [],dailyReturnPct=quote.get('change'),stockSeries=quote.get('history',[]),
                    marketSeriesPeriod=quote.get('traded_at','')+' 종가',keywords=keywords(c,year),aiInsight=insight,
                    disclosureSummary=c.get('disclosure_summary'),metricInsights=c.get('metric_insights',{})))
            result['sectors'].append(dict(id=registered.id,name=registered.name,indexName=index.get('name') or registered.name+' 지수',
                indexSeries=index.get('history',[]),indexReturnPct=index.get('change'),returnPeriod=index.get('traded_at','')+' 종가 · 직전 거래일 대비',
                **index_market_cap(view.get('market',{})),
                metricCatalog=metrics,analysisCompanyIds=entries,coverage=view.get('coverage',{}),periods=[f'{y} Q{q}' for y in years for q in range(1,5)],keywords=keywords(view,year),
                aiInsight=view.get('ai_insights',{}).get(str(year),{}),metricInsights=view.get('metric_insights',{}),
                marketSeriesPeriod=index.get('traded_at','')+' 종가'))
        except (KeyError,ValueError,RuntimeError) as error:
            import logging
            logging.getLogger(__name__).warning('Sector %s unavailable: %s',registered.id,error)
            del result['companies'][count:]
            result['sectors'].append(dict(id=registered.id,name=registered.name,analysisCompanyIds=[],
                status='unavailable',statusMessage='이 산업의 분석 자료가 아직 준비되지 않았습니다.'))
    return result

@request_scope
def quarter_source(sector,code,year,quarter,key):
    if not 1<=quarter<=4 or key not in KEYS+('fcf','rd','bank_growth','roe','credit_cost','equity_ratio'):raise ValueError('분기·지표를 확인하세요.')
    repo=Repository(sector)
    if key in ('rd','bank_growth','roe','credit_cost','equity_ratio'):
        return graph_source(repo,code,year,quarter,key)
    basis=repo.financial(code,year)['basis'] or 'CFS'
    components=[]
    keys=('operating_cashflow','capex') if key=='fcf' else (key,)
    targets=[(year,quarter,basis)]
    if key=='revenue':
        base_year=min(repo.analysis_years());base_basis=repo.financial(code,base_year)['basis'] or 'CFS'
        if (base_year,1,base_basis) not in targets:targets.append((base_year,1,base_basis))
    for target_year,target_q,target_basis in targets:
        for metric in keys:
            if metric=='capex':
                value,inputs,method,validation=capex_flow(repo,code,target_year,target_basis,target_q)
                if validation['status']!='verified':return dict(note=validation['message'],validation=validation,components=[])
            else:value,inputs,method=financial_flow(repo,code,target_year,target_q,target_basis,metric)
            for item in inputs:
                t=item['report_type'];kind=item['value_type']
                try:source=revenue_source(code,target_year,metric,sector_id=sector,report_type=t,basis=target_basis,value_type=kind)
                except (KeyError,ValueError,OSError):source=None
                components.append(dict(metric=metric,reportType=f'{target_year} {t}',value=item['value'],source=source))
            if method:components.append(dict(metric=metric+' (역산)',reportType=f'{target_year} {REPORT_TYPES[target_q-1]}',value=value,source=dict(source_text=method)))
    return dict(company=repo.company(code)['company_name'],year=year,quarter=quarter,components=components,
        note='매출 지수의 출처는 현재 분기와 최초 분석 분기입니다. 분기값을 우선 사용하며, 없으면 같은 재무 기준의 누적값 차감 또는 연간값에서 나머지 3분기 차감으로 역산합니다.')


def graph_source(repo,code,year,quarter,key):
    """Show numerator and denominator receipts without mixing accounting bases."""
    graphs=GraphData(repo);company=dict(code=code,history=[])
    years=repo.analysis_years();rows=graphs.rows(company,years,quarter_rows)
    lookup={r['period']:r for r in rows};current=lookup[f'{year} Q{quarter}']
    previous=lookup.get(f'{year} Q{quarter-1}' if quarter>1 else f'{year-1} Q4',{})
    selections=[]
    if key=='rd':selections=[(current,'rd')]
    elif key=='bank_growth':selections=[(current,'netInterestIncome'),(lookup.get(f'{min(years)} Q1',{}),'netInterestIncome')]
    elif key=='roe':selections=[(current,'netIncome'),(previous,'equity'),(current,'equity')]
    elif key=='credit_cost':selections=[(current,'creditLoss'),(previous,'loans'),(current,'loans')]
    else:selections=[(current,'equity'),(current,'assets')]
    components=[];seen=set()
    for row,field in selections:
        sources=row.get('rdSources',[]) if field=='rd' else row.get('metricSources',{}).get(field,[])
        for source in sources:
            proof=source.get('receipt_validation')
            if proof:
                for evidence in proof['evidence']:
                    ident=(field,evidence['rcept_no'],evidence['table_index'],evidence['row_index'],evidence['column_index'])
                    if ident in seen:continue
                    seen.add(ident)
                    components.append(dict(metric=field+' (원문 대조)',reportType=f"{evidence['year']} {evidence['report_type']} · {evidence['fs_div']}",
                        value=evidence['value'],source=dict(source_text=evidence['source_text'],
                        document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+evidence['rcept_no'],
                        note=f"원문 대조 통과 · 표 {evidence['table_index']}, 행 {evidence['row_index']+1}, 열 {evidence['column_index']+1} · 단위 {evidence['original_unit']}")))
                if proof.get('formula'):
                    components.append(dict(metric=field+' (검증된 역산)',reportType=f"{source['year']} {source['report_type']}",value=source['value'],
                        source=dict(note='양쪽 원문과 Q3 누적 입력을 확인했습니다. 계산식: '+proof['formula'])))
                continue
            receipt=source.get('source_rcept_no') or source.get('rcept_no') or ''
            ident=(receipt,field,source.get('value_type'))
            if ident in seen:continue
            seen.add(ident)
            components.append(dict(metric=field,reportType=f"{source['year']} {source['report_type']} · {source['fs_div']}",
                value=source['value'],source=dict(source_text=(source.get('derivation')+' · ' if source.get('derivation') else '')+(source.get('source_account_name') or source.get('original_account_nm') or source.get('metric_code','')),
                    document_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt,
                    note='같은 재무 기준의 승인된 계정 수치입니다. 링크에서 원본 공시를 확인할 수 있습니다.')))
    if key=='rd':
        try:
            source=revenue_source(code,year,'revenue',sector_id=repo.sector.id,report_type=REPORT_TYPES[quarter-1],basis=current['basis'],value_type='quarterly')
            components.append(dict(metric='매출액 (분기)',reportType=REPORT_TYPES[quarter-1],value=source['value'],source=source))
        except (KeyError,ValueError,OSError):pass
    return dict(company=repo.company(code)['company_name'],year=year,quarter=quarter,components=components,
        note='매출·순이자이익 지수는 최초 분석 분기를 100으로 표시합니다. ROE·대손비용률 proxy는 저장된 분기 금액을 4배 연환산하고 직전 분기 말과 현재 분기 말 잔액의 평균을 사용합니다. 분기값이 없으면 같은 재무 기준의 누적값·연간값으로 역산하며 접수번호가 다른 승인 값은 양쪽 원문 대조를 통과한 경우만 사용하며 검토 필요 값은 사용하지 않습니다.')
