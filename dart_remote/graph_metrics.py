"""Sector-specific four-slot graph metrics, calculated from read-only facts."""
import math
from functools import cached_property
from . import db

REPORTS=('Q1','H1','Q3','FY')

def finite(v):
    return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)

def ratio(a,b):
    return a/b*100 if finite(a) and finite(b) and b>0 else None

def growth(a,b):
    return (a-b)/b*100 if finite(a) and finite(b) and b>0 else None

def resolve_flow(read, quarter):
    """Return an exact quarter and its inputs, never divide an annual total by four."""
    value, sources = read(REPORTS[quarter-1], 'quarterly')
    if finite(value):return value, sources, None
    def cumulative(q):
        if q == 0:return 0, []
        value,sources=read(REPORTS[q-1], 'annual' if q == 4 else 'cumulative')
        if finite(value):return value,sources
        parts=[read(REPORTS[i-1],'quarterly') for i in range(1,q+1)]
        if all(finite(v) for v,_ in parts):return sum(v for v,_ in parts),[r for _,ss in parts for r in ss]
        return None,[]
    current, cs = cumulative(quarter)
    previous, ps = cumulative(quarter-1)
    if finite(current) and finite(previous):
        return current-previous, cs+ps, '누적값 차감'
    annual, annual_sources = cumulative(4)
    others = [read(REPORTS[q-1], 'quarterly') for q in range(1,5) if q != quarter]
    if finite(annual) and all(finite(v) for v,_ in others):
        return annual-sum(v for v,_ in others), annual_sources+[r for _,ss in others for r in ss], '연간값에서 다른 3개 분기 차감'
    return None, [], None

def financial_flow(repo, code, year, quarter, basis, metric):
    def read(report, kind):
        f=repo.financial(code,year,report,basis,kind)
        if f.get('basis') != basis:return None, []
        return f.get(metric), [dict(r,year=year,report_type=report,fs_div=basis,value_type=kind)
            for r in f.get('financial_sources',{}).get(metric,[])]
    return resolve_flow(read,quarter)

def average(a,b):
    return (a+b)/2 if finite(a) and finite(b) else None

def catalog(sector):
    bank=sector in ('은행','KRX_BANK');health=sector in ('헬스케어','KRX_HEALTH')
    specs=[('매출 지수','매출은 얼마나 성장하고 있나요?','기준 분기의 매출을 100으로 놓고, 이후 매출이 얼마나 늘거나 줄었는지 비교합니다. 예를 들어 120이면 기준 분기보다 매출이 20% 늘었다는 뜻입니다.','분기 매출액 ÷ 최초 분석 분기 매출액 × 100'),
        ('영업이익률','팔아서 얼마나 이익을 남기고 있나요?','매출에서 본업에 드는 비용을 빼고 남는 이익의 비율입니다. 10%라면 100원어치를 팔아 본업에서 10원의 이익을 남겼다는 뜻입니다.','분기 영업이익 ÷ 분기 매출액 × 100'),
        ('R&D / 매출액' if health else 'CAPEX / 매출액','연구개발에 얼마나 쓰고 있나요?' if health else '공장과 장비에 얼마나 투자하고 있나요?',
         '매출에 비해 신약·제품 등의 연구개발 비용을 얼마나 썼는지 보여줍니다. 비율이 높아져도 매출이 줄어든 결과일 수 있어 실제 연구개발비도 함께 살펴보세요.' if health else '매출에 비해 공장·장비 등 자산을 마련하는 데 현금을 얼마나 썼는지 보여줍니다. 비율이 높아져도 매출이 줄어든 결과일 수 있어 실제 투자액도 함께 살펴보세요.',
         '분기 연구개발비 ÷ 분기 매출액 × 100' if health else '분기 CAPEX ÷ 분기 매출액 × 100'),
        ('FCF Margin','투자하고도 현금이 남고 있나요?','본업에서 들어온 현금에서 설비투자 지출을 빼고, 남은 현금이 매출의 몇 %인지 보여줍니다. 음수라도 미래를 위한 투자 확대 때문일 수 있으므로 적자와 같은 뜻은 아닙니다.','(분기 영업활동현금흐름 − 분기 CAPEX) ÷ 분기 매출액 × 100')]
    if bank:specs=[('순이자이익 지수','이자로 남기는 수익은 얼마나 늘고 있나요?','받은 이자에서 지급한 이자를 뺀 순이자이익을 기준 분기 100과 비교합니다. 예를 들어 120이면 기준 분기보다 순이자이익이 20% 늘었다는 뜻입니다.','분기 순이자이익 ÷ 최초 분석 분기 순이자이익 × 100'),
        ('ROE','자기자본으로 얼마나 이익을 내고 있나요?','주주의 몫인 자기자본에 비해 순이익을 얼마나 냈는지 보여줍니다. 여기서는 분기 순이익을 4배 하여 1년 기준으로 환산하므로 실제 연간 실적과는 다를 수 있습니다.','분기 순이익 × 4 ÷ 평균 자기자본 × 100'),
        ('대손비용률 proxy','못 받을 돈에 대비한 비용은 얼마나 되나요?','대출금을 돌려받지 못할 가능성에 대비한 신용손실비용을 분기 기준에서 1년 기준으로 환산해 대출채권과 비교합니다. 공시 수치로 계산한 참고 지표이므로 은행이 발표한 공식 대손비용률과 다를 수 있습니다.','분기 신용손실비용 × 4 ÷ 평균 대출채권 × 100'),
        ('자기자본비율','자산 중 자기자본은 얼마나 되나요?','전체 자산 중 주주의 몫인 자기자본이 차지하는 비율입니다. 은행의 규제 기준인 BIS·CET1 자본비율과는 계산 방식이 다릅니다.','분기 말 자본총계 ÷ 자산총계 × 100')]
    return {k:dict(title=t,question=q,unit='지수' if k=='revenue' else '%',help=h,formula=f) for k,(t,q,h,f) in zip(('revenue','operating','capex','fcf'),specs)}

def calculate(rows,bank=False,health=False,baseline_period=None):
    from .disclosure_policy import WARNING
    lookup={r['period']:r for r in rows}
    baseline_period=baseline_period or (min(lookup) if lookup else None)
    base=lookup.get(baseline_period,{})
    for r in rows:
        r['indexBasePeriod']=baseline_period
        y,q=map(int,r['period'].replace(' Q',' ').split())
        previous=lookup.get(f'{y} Q{q-1}' if q>1 else f'{y-1} Q4',{})
        comparable=base.get('basis')==r.get('basis')
        if bank:
            same=previous.get('basis')==r.get('basis')
            equity=average(previous.get('equity'),r.get('equity')) if same else None
            loans=average(previous.get('loans'),r.get('loans')) if same else None
            r['metrics']=dict(revenue=ratio(r.get('netInterestIncome'),base.get('netInterestIncome')) if comparable else None,
                operating=ratio(r.get('netIncome')*4 if finite(r.get('netIncome')) else None,equity),
                capex=ratio(r.get('creditLoss')*4 if finite(r.get('creditLoss')) else None,loans),
                fcf=ratio(r.get('equity'),r.get('assets')))
            r['averageEquity']=equity;r['averageLoans']=loans
        else:
            cf,cap=r.get('operatingCashFlow'),r.get('capex')
            r['metrics']=dict(revenue=ratio(r.get('revenue'),base.get('revenue')) if comparable else None,
                operating=ratio(r.get('operatingProfit'),r.get('revenue')),
                capex=ratio(r.get('rd') if health else cap,r.get('revenue')),
                fcf=ratio(cf-cap if finite(cf) and finite(cap) else None,r.get('revenue')))
        dependencies=({'revenue':[(r,'netInterestIncome'),(base,'netInterestIncome')],
            'operating':[(r,'netIncome'),(previous,'equity'),(r,'equity')],
            'capex':[(r,'creditLoss'),(previous,'loans'),(r,'loans')],
            'fcf':[(r,'equity'),(r,'assets')]} if bank else {
            'revenue':[(r,'revenue'),(base,'revenue')],
            'operating':[(r,'operatingProfit'),(r,'revenue')],
            'capex':[(r,'rd' if health else 'capex'),(r,'revenue')],
            'fcf':[(r,'operatingCashFlow'),(r,'capex'),(r,'revenue')]})
        r['estimatedMetrics']={key:WARNING for key,inputs in dependencies.items()
                               if finite(r['metrics'].get(key)) and any(field in source.get('estimatedFields',{}) for source,field in inputs)}
    return rows

class GraphData:
    def __init__(self,repo):
        self.repo=repo;self.bank=repo.sector.membership_code=='KRX_BANK';self.health=repo.sector.membership_code=='KRX_HEALTH'
    @cached_property
    def profiles(self):
        if not self.bank:return {}
        where,params=self.repo._scope()
        return {r['corp_code']:r for r in db.rows('SELECT * FROM company_financial_profiles WHERE '+where+' AND valid_to IS NULL',params)}
    @cached_property
    def extras(self):
        if not (self.bank or self.health):return []
        where,params=self.repo._scope();params['v']=self.repo.sector.data_version.split(':',1)[0]
        if self.bank:
            # Approved mismatches are admitted only after independent XML proof.
            from .receipt_validation import reconcile
            candidates=db.rows("""SELECT m.*,f.rcept_no AS active_rcept_no
              FROM financial_metric_values m LEFT JOIN
              (SELECT corp_code,year,report_type,MIN(rcept_no) rcept_no FROM filings
               WHERE data_version=:v AND is_active=1 GROUP BY corp_code,year,report_type
               HAVING COUNT(DISTINCT rcept_no)=1) f USING(corp_code,year,report_type)
              WHERE """+where+""" AND m.review_status='approved' AND m.unit='KRW'""",params)
            return reconcile(candidates,params['v'])
        return self.health_extras(where,params)
    def health_extras(self,where,params):
        from .receipt_validation import reconcile
        primary=db.rows("""SELECT m.*,f.rcept_no AS active_rcept_no
            FROM financial_metric_values m LEFT JOIN
            (SELECT corp_code,year,report_type,MIN(rcept_no) rcept_no FROM filings
             WHERE data_version=:v AND is_active=1 GROUP BY corp_code,year,report_type
             HAVING COUNT(DISTINCT rcept_no)=1) f USING(corp_code,year,report_type)
            WHERE """+where+" AND m.metric_code='RND_EXPENSE'",params)
        # A document's R&D total and an income-statement expense are not the same
        # series. Reserve the whole company/year/basis even if validation fails.
        primary_groups={(r['corp_code'],r['year'],r['fs_div']) for r in primary}
        approved=[r for r in primary if r.get('review_status')=='approved' and r.get('unit')=='KRW'
                  and finite(r.get('value')) and r['value']>=0
                  and r.get('scope')=={'CFS':'consolidated','OFS':'separate'}.get(r['fs_div'])]
        rows=db.rows("""SELECT f.*,CASE WHEN is_calculated=1 THEN calculated_value ELSE normalized_value END value,
            (SELECT MIN(a.rcept_no) FROM filings a WHERE a.corp_code=f.corp_code AND a.year=f.year
             AND a.report_type=f.report_type AND a.data_version=f.data_version AND a.is_active=1
             HAVING COUNT(DISTINCT a.rcept_no)=1) active_rcept_no
            FROM financial_facts f WHERE """+where+""" AND is_active=1 AND data_version=:v AND currency='KRW'
            AND sj_div IN ('IS','CIS') AND (account_id IN ('ifrs-full_ResearchAndDevelopmentExpense','dart_OrdinaryDevelopmentExpense')
              OR original_account_nm IN ('연구개발비','연구와 개발 비용','경상연구개발비'))""",params)
        candidates=[dict(r,source_account_id=r['account_id'],source_rcept_no=r['rcept_no'],unit='KRW',
                         review_status='approved',metric_code='RD',scope='holding_consolidated' if r['fs_div']=='CFS' else 'bank_separate')
                    for r in rows if (r['corp_code'],r['year'],r['fs_div']) not in primary_groups]
        return reconcile(approved+candidates,params['v'])
    def value(self,code,year,t,basis,metric,kind):
        corp=self.repo.company(code)['corp_code']
        pool=[r for r in self.extras if r['corp_code']==corp and r['year']==year and r['report_type']==t
              and r['fs_div']==basis and r['value_type']==kind and (not self.bank or r['metric_code']==metric)]
        if self.bank:
            scope=self.profiles.get(corp,{}).get('comparison_scope')
            pool=[r for r in pool if r['scope']==scope]
        elif self.health:
            pool=[r for r in pool if r.get('metric_code') in ('RND_EXPENSE','RD') and finite(r.get('value'))]
        values={r['value'] for r in pool if r['value'] is not None}
        return (next(iter(values)),pool) if len(values)==1 else (None,[])
    def flow(self,code,y,q,basis,metric):
        value,sources,derived=resolve_flow(lambda t,kind:self.value(code,y,t,basis,metric,kind),q)
        # Revised cumulative totals can use a different reporting perimeter.
        # Do not turn a negative difference into a negative R&D spending ratio.
        if self.health and finite(value) and value<0 and any(s.get('metric_code')=='RND_EXPENSE' for s in sources):
            return None,[]
        return value, [dict(r,derivation=derived) for r in sources] if derived else sources
    def rows(self,company,years,ordinary):
        expanded=sorted(set(years)|{y-1 for y in years});code=company['code'];output=[]
        if not self.bank:
            output=ordinary(self.repo,company,expanded)
            if self.health:
                for r in output:
                    y,q=map(int,r['period'].replace(' Q',' ').split())
                    r['rd'],r['rdSources']=self.flow(code,y,q,r['basis'],'RD')
                    from .disclosure_policy import annotate
                    annotate(r,'rd',r['rdSources'])
                    if any(s.get('derivation') for s in r['rdSources']):r.setdefault('derivedFields',{})['rd']=r['rdSources'][0]['derivation']
        else:
            corp=self.repo.company(code)['corp_code'];profile=self.profiles.get(corp,{})
            basis=profile.get('preferred_fs_div')
            for y in expanded:
                for q,t in enumerate(REPORTS,1):
                    r=dict(period=f'{y} Q{q}',basis=basis,scope=profile.get('comparison_scope'),metricSources={})
                    for field,metric in [('netInterestIncome','NET_INTEREST_INCOME'),('netIncome','NET_INCOME'),('creditLoss','CREDIT_LOSS_EXPENSE')]:
                        r[field],r['metricSources'][field]=self.flow(code,y,q,basis,metric)
                        if any(s.get('derivation') for s in r['metricSources'][field]):r.setdefault('derivedFields',{})[field]=r['metricSources'][field][0]['derivation']
                    for field,metric in [('equity','TOTAL_EQUITY'),('assets','TOTAL_ASSETS'),('loans','LOANS_AT_AMORTISED_COST')]:
                        r[field],r['metricSources'][field]=self.value(code,y,t,basis,metric,'point_in_time')
                        if field=='loans' and r[field] is None:
                            r[field],r['metricSources'][field]=self.value(code,y,t,basis,'LOANS_AT_AMORTISED_COST_NOTE','point_in_time')
                    from .disclosure_policy import annotate
                    for field,sources in r['metricSources'].items():annotate(r,field,sources)
                    output.append(r)
        return [r for r in calculate(output,self.bank,self.health,f'{min(years)} Q1') if int(r['period'][:4]) in years]

    def public_rows(self,company,years,ordinary):
        # Provenance is retrieved on demand by the source endpoint, not sent on every chart load.
        rows=self.rows(company,years,ordinary)
        for row in rows:
            row.pop('metricSources',None);row.pop('rdSources',None)
            proof=row.get('capexValidation')
            if proof:
                # Full input tables remain in the source endpoint, not every chart payload.
                row['capexValidation']={k:v for k,v in proof.items() if k not in ('inputs','other_quarters','previous_check')}
        return rows
