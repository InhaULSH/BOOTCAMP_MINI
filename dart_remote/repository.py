"""Central MySQL facts and scoped chunk retrieval. No upstream writes."""
import hashlib
import json
import os
import re
from functools import cached_property,lru_cache
from . import db
from .catalog import sector

REPORTS={'Q1':('03','1분기보고서'),'H1':('06','반기보고서'),'HY':('06','반기보고서'),'Q3':('09','3분기보고서'),'FY':('12','사업보고서')}
ACCOUNTS={'revenue':('매출액','수익(매출액)','영업수익','수익'),
 'operating_income':('영업이익','영업이익(손실)','영업손익'),
 'operating_cashflow':('영업활동현금흐름','영업활동으로 인한 현금흐름','영업활동으로인한현금흐름'),
 'inventory':('재고자산',),'capex':('유형자산취득(CAPEX)',)}
IDS={'revenue':('ifrs-full_Revenue','ifrs_Revenue'),'operating_income':('dart_OperatingIncomeLoss',),
 'operating_cashflow':('ifrs-full_CashFlowsFromUsedInOperatingActivities','ifrs_CashFlowsFromUsedInOperatingActivities'),
 'inventory':('ifrs-full_Inventories','ifrs_Inventories')}

class Repository:
    def __init__(self,selected=None):self.sector=selected if hasattr(selected,'membership_code') else sector(selected)
    @cached_property
    def members(self):
        return db.rows('''SELECT c.*,c.corp_name AS company_name FROM krx_index_constituents k JOIN companies c USING(corp_code)
            WHERE k.index_code=:i AND k.is_current=1 ORDER BY c.stock_code''',{'i':self.sector.membership_code})
    def companies(self):
        order={c:i for i,c in enumerate(self.sector.companies_order)}
        return sorted([c for c in self.members if c['is_operational'] and c['stock_code']],key=lambda c:(order.get(c['stock_code'],len(order)),c['stock_code']))
    def company(self,identifier):
        found=[c for c in self.companies() if identifier in (c['stock_code'],c['corp_code'],c['company_name'])]
        if len(found)!=1:raise KeyError('선택한 지수에 속한 운영 기업을 정확히 지정하세요.')
        return found[0]
    def _scope(self,code=None):
        identifiers=code if isinstance(code,(list,tuple)) else ([code] if code else [])
        corps=list(dict.fromkeys(self.company(c)['corp_code'] for c in identifiers)) if identifiers else [c['corp_code'] for c in self.companies()]
        params={'c'+str(i):c for i,c in enumerate(corps)}
        return ('corp_code IN ('+','.join(':'+k for k in params)+')' if params else '1=0'),params
    def years(self):
        where,params=self._scope()
        params['version']=self.sector.data_version.split(':',1)[0]
        return [r['year'] for r in db.rows('SELECT DISTINCT year FROM coverage WHERE '+where+' AND data_version=:version ORDER BY year',params)]
    def analysis_years(self,requested=None):
        """Select years without silently mixing snapshots during upstream sync."""
        available=self.years()
        version=self.sector.data_version.split(':',1)[0]
        if not available:
            where,params=self._scope()
            actual=db.rows('SELECT DISTINCT data_version FROM coverage WHERE '+where,params)
            versions=', '.join(r['data_version'] for r in actual) or '없음'
            raise ValueError(f'{self.sector.name}: 현재 버전 {version}의 분석 연도가 없습니다. '
                             f'coverage에 존재하는 버전: {versions}. DB 동기화와 현재 버전 등록을 확인하세요.')
        selected=sorted(available if requested is None else requested)
        if not selected or not set(selected)<=set(available):
            raise ValueError(f'{self.sector.name}: 요청 연도 {selected}가 현재 버전 {version}에 없습니다. '
                             f'사용 가능한 연도: {available}')
        return selected
    @cached_property
    def _all_facts(self):
        where,params=self._scope()
        params['version']=self.sector.data_version.split(':',1)[0]
        # Preserve CAPEX review/sign/account metadata discarded by the unified view.
        rows=db.rows('''SELECT s.*,x.review_required,x.source_account_ids,x.source_account_names,
            x.sign_normalized,x.normalized_value AS signed_normalized_value,x.capex_method,
            (SELECT MIN(f.rcept_no) FROM filings f WHERE f.corp_code=s.corp_code AND f.year=s.year
             AND f.report_type=s.report_type AND f.data_version=s.data_version AND f.is_active=1
             HAVING COUNT(DISTINCT f.rcept_no)=1) AS active_rcept_no
            FROM standardized_financials s LEFT JOIN capex_facts x
              ON s.standard_account='유형자산취득(CAPEX)' AND x.corp_code=s.corp_code
              AND x.year=s.year AND x.report_type=s.report_type AND x.fs_div=s.fs_div
              AND x.value_type=s.value_type AND x.data_version=s.data_version AND x.is_active=1
            WHERE '''+where.replace('corp_code','s.corp_code')+' AND s.data_version=:version',params)
        # The upstream view INNER JOINs standard_accounts by the exact name.
        # "영업이익(손실)" is present in financial_facts but absent from that
        # catalogue. Recover missing operating-profit and operating-cashflow facts, identified by
        # the DART account ID or an exact operating-profit alias; never infer
        # operating profit from gross profit or continuing-operation profit.
        aliases=ACCOUNTS['operating_income']+('영업손실','영업순손익')
        fallback_params=dict(params,operating_id=IDS['operating_income'][0],cf_id=IDS['operating_cashflow'][0],cf_old=IDS['operating_cashflow'][1])
        for i,name in enumerate(aliases):fallback_params['a'+str(i)]=name
        alias_sql=','.join(':a'+str(i) for i in range(len(aliases)))
        raw=db.rows('''SELECT f.*,c.corp_name,
            CASE WHEN f.is_calculated=1 THEN f.calculated_value ELSE f.normalized_value END AS value,
            CASE WHEN f.sj_div='CF' THEN '영업활동현금흐름' ELSE '영업이익' END AS standard_account,'reported' AS value_source
            FROM financial_facts f JOIN companies c USING(corp_code)
            WHERE '''+where+''' AND f.data_version=:version AND f.is_active=1
            AND ((f.sj_div IN ('IS','CIS') AND (f.account_id=:operating_id OR f.standard_account_nm IN ('''+alias_sql+''')))
              OR (f.sj_div='CF' AND f.account_id IN (:cf_id,:cf_old)))
            AND NOT EXISTS (SELECT 1 FROM standardized_financials v
                WHERE v.corp_code=f.corp_code AND v.year=f.year AND v.report_type=f.report_type
                AND v.rcept_no=f.rcept_no AND v.fs_div=f.fs_div AND v.sj_div=f.sj_div
                AND v.currency=f.currency AND v.value_type=f.value_type AND v.data_version=f.data_version
                AND v.account_id=f.account_id)''',fallback_params)
        for r in raw:
            r['upstream_standard_account_nm']=r['standard_account_nm']
            r['financial_lookup']='financial_facts-operating-cashflow-fallback' if r['sj_div']=='CF' else 'financial_facts-operating-profit-fallback'
        rows.extend(raw)
        for r in rows:
            value=r['value'];r.update(standard_account_nm=r['standard_account'],normalized_value=value,calculated_value=value,
                cash_outflow_amount=value if r['standard_account']=='유형자산취득(CAPEX)' else None,
                is_derived=r['value_source']=='derived')
        return rows
    @cached_property
    def _facts_index(self):
        groups={}
        for row in self._all_facts:
            key=tuple(row[k] for k in ('corp_code','year','report_type','fs_div','value_type'))
            groups.setdefault(key,[]).append(row)
        return groups
    def facts(self,code,year,report_type='FY',basis='CFS',value_type=None):
        if report_type not in REPORTS or basis not in ('CFS','OFS'):raise ValueError('보고서·재무 기준 오류')
        report_type='H1' if report_type=='HY' else report_type
        value_type=value_type or ('annual' if report_type=='FY' else 'cumulative')
        if value_type not in ('annual','cumulative','quarterly','point_in_time'):raise ValueError('수치 기간 유형 오류')
        corp=self.company(code)['corp_code']
        return [r for kind in dict.fromkeys((value_type,'point_in_time'))
                for r in self._facts_index.get((corp,int(year),report_type,basis,kind),[])]
    def metric(self,rows,key):
        for section in (('IS','CIS') if key in ('revenue','operating_income') else ('BS',) if key=='inventory' else ('CF',)):
            pool=[r for r in rows if r['sj_div']==section and r['currency']=='KRW']
            matches=[r for r in pool if r['standard_account_nm'] in ACCOUNTS[key]]
            if not matches:matches=[r for r in pool if r.get('account_id') in IDS.get(key,())]
            pairs=[(r,r.get('value',r.get('calculated_value') if r.get('is_calculated') else r.get('normalized_value'))) for r in matches]
            values={v for _,v in pairs if v is not None}
            if len(values)>1:raise ValueError(f'{key}: 같은 기업·기간·기준의 계정 값이 충돌합니다.')
            if values:return next(iter(values)),[dict(r,value=v) for r,v in pairs if v is not None]
        return None,[]
    @lru_cache(maxsize=256)
    def json_financial_exists(self,code,year,report_type):
        # The remote store has imported JSON rows, not the original JSON files.
        # Test the entire report, including unmapped accounts and other bases.
        params=dict(c=self.company(code)['corp_code'],y=int(year),t=report_type,
                    v=self.sector.data_version.split(':',1)[0])
        return bool(db.rows('''SELECT (EXISTS(SELECT 1 FROM financial_facts
            WHERE corp_code=:c AND year=:y AND report_type=:t AND data_version=:v AND is_active=1)
            OR EXISTS(SELECT 1 FROM coverage WHERE corp_code=:c AND year=:y
                AND report_type=:t AND data_version=:v AND financial_exists=1)) AS present''',params)[0]['present'])
    def financial(self,code,year,report_type='FY',basis='CFS',value_type=None):
        rows=self.facts(code,year,report_type,basis,value_type);values={};sources={}
        report_type='H1' if report_type=='HY' else report_type
        mode='json';note=''
        if not rows and not self.json_financial_exists(code,year,report_type):
            from .xml_financials import load
            rows,note=load(self,code,year,report_type,basis,value_type or ('annual' if report_type=='FY' else 'cumulative'))
            mode='xml'
            for key in ACCOUNTS:
                selected=[r for r in rows if r['key']==key]
                distinct={r['value'] for r in selected}
                values[key]=next(iter(distinct)) if len(distinct)==1 else None
                sources[key]=selected if len(distinct)==1 else []
                if len(distinct)>1:note+=f' {key}: XML 표의 값이 충돌하여 표시하지 않았습니다.'
        else:
            for key in ACCOUNTS:values[key],sources[key]=self.metric(rows,key)
        return dict(year=int(year),report_type=report_type,basis=basis if rows else None,**values,financial_sources=sources,
                    financial_source=mode,financial_note=note)
    @lru_cache(maxsize=128)
    def documents(self,code):
        rows=db.rows('''SELECT f.*,c.corp_name FROM filings f JOIN companies c USING(corp_code)
            WHERE f.corp_code=:c AND f.is_active=1 AND f.data_version=:v ORDER BY year,rcept_dt,rcept_no''',
            {'c':self.company(code)['corp_code'],'v':self.sector.data_version.split(':',1)[0]})
        return [dict(r,period=f"{r['year']}-{REPORTS[r['report_type']][0]}",report_name=r['dart_report_name'] or REPORTS[r['report_type']][1],
            receipt_no=r['rcept_no'],document_id=r['rcept_no'],document_role='main',stock_code=code) for r in rows]
    def chunks(self,code=None,year=None,report_type=None,business_only=False,include_vectors=False):
        if include_vectors:raise ValueError('벡터는 mysql_vectors의 검증된 스냅샷을 통해 조회하세요.')
        if report_type is not None and report_type not in REPORTS:raise ValueError('보고서 유형 오류')
        where,params=self._scope(code);conditions=[where,'is_active=1','is_searchable=1','data_version=:version']
        params['version']=self.sector.data_version.split(':',1)[0]
        for key,value in [('year',year),('report_type','H1' if report_type=='HY' else report_type)]:
            if value is not None:conditions.append(key+'=:'+key);params[key]=value
        if business_only:conditions.append("section_name LIKE 'II.%'")
        fields='chunk_id,vector_id,corp_code,corp_name,year,report_type,rcept_no,section_name,subsection_name,chunk_text,content_hash,embedding_model,model_revision,embedding_dimension,index_version,data_version,content_type,search_priority'
        return [dict(r,chunk_order=r['vector_id'],dimensions=r['embedding_dimension']) for r in db.rows('SELECT '+fields+' FROM chunk_metadata WHERE '+' AND '.join(conditions)+' ORDER BY vector_id',params)]
    def chunk(self,chunk_id):
        where,params=self._scope();params.update(id=chunk_id,version=self.sector.data_version.split(':',1)[0])
        rows=db.rows('SELECT * FROM chunk_metadata WHERE '+where+' AND chunk_id=:id AND is_active=1 AND data_version=:version',params)
        if not rows:raise KeyError('현재 지수와 데이터 버전에 속한 청크가 없습니다.')
        r=rows[0];return dict(r,chunk_order=r['vector_id'],dimensions=r['embedding_dimension'])
    def adapt(self,row,score=None):
        return dict(chunk_id=row['chunk_id'],document_id=row['rcept_no'],paragraph_ids=[row['chunk_id']],company=row['corp_name'],
            stock_code=self.company(row['corp_code'])['stock_code'],year=row['year'],period=f"{row['year']}-{REPORTS[row['report_type']][0]}",
            report_name=REPORTS[row['report_type']][1],report_type=row['report_type'],receipt_no=row['rcept_no'],section=row['section_name'],
            heading=row.get('subsection_name') or row['section_name'],text=row['chunk_text'],start_char=0,end_char=len(row['chunk_text']),
            table_id='',retrieval_score=score,sector_id=self.sector.id,content_hash=row['content_hash'],embedding_model=row['embedding_model'])
    def search(self,query,code=None,year=None,report_type=None,top_k=5,business_only=False):
        if isinstance(code,list):code=tuple(code)
        if not isinstance(query,str) or not query.strip():raise ValueError('검색어가 필요합니다.')
        if not 1<=top_k<=40:raise ValueError('top_k는 1-40이어야 합니다.')
        rows=self.chunks(code,year,report_type,business_only)
        from .vector import rank
        ranked,mode=rank(query,rows,top_k,self.sector.index_version)
        coverage=self.coverage(code,year,report_type)
        return [self.adapt(r,score) for r,score in ranked],dict(mode=mode,query=query,coverage=coverage,
            scope=dict(sector=self.sector.id,code=code,year=year,report_type=report_type))
    @lru_cache(maxsize=128)
    def coverage(self,code=None,year=None,report_type=None):
        where,params=self._scope(code)
        for key,value in [('year',year),('report_type',report_type)]:
            if value is not None:where+=' AND '+key+'=:'+key;params[key]=value
        params['version']=self.sector.data_version.split(':',1)[0]
        rows=db.rows('SELECT corp_code,financial_exists,filing_exists,chunk_exists,embedding_exists,status,reason FROM coverage WHERE '+where+' AND data_version=:version',params)
        present={r['corp_code'] for r in rows if r['chunk_exists']}
        identifiers=code if isinstance(code,(list,tuple)) else ([code] if code else [])
        scoped={self.company(c)['corp_code'] for c in identifiers} if identifiers else {c['corp_code'] for c in self.companies()}
        missing=[c['company_name'] for c in self.companies() if c['corp_code'] in scoped and c['corp_code'] not in present]
        unbuilt=[c['company_name'] for c in self.members if not c['is_operational']]
        return dict(constituent_count=len(self.members),operational_count=len(self.companies()),missing_chunk_companies=missing,unbuilt_companies=unbuilt,
            incomplete_reports=[r for r in rows if r['status']!='PASS'])
    @lru_cache(maxsize=128)
    def select_evidence(self,code,limit_per_period=8):
        selected={};docs=self.documents(code)
        from .mysql_vectors import backend
        method=backend()
        if method in ('numpy','faiss'):
            # Score each company/topic once, then select within each period.
            # Inner products are independent of candidate count, so this keeps
            # the per-period Top-K rule while avoiding repeated remote reads.
            from .mysql_vectors import rank
            rows=self.chunks(code,business_only=True)
            per_query=[]
            count=max(1,limit_per_period//len(self.sector.topics))
            for query in self.sector.topics:
                ranked,_=rank(query,rows,len(rows),self.sector.index_version,method)
                periods={}
                for row,score in ranked:
                    bucket=periods.setdefault((row['year'],row['report_type']),[])
                    if len(bucket)<count:bucket.append(self.adapt(row,score))
                per_query.append(periods)
            for doc in docs:
                period={}
                for groups in per_query:
                    period.update((h['chunk_id'],h) for h in groups.get((doc['year'],doc['report_type']),[]))
                selected.update(list(period.items())[:limit_per_period])
            return sorted(selected.values(),key=lambda r:(r['period'],r['chunk_id'])),dict(mode=method,periods=len(docs))
        for doc in docs:
            period={}
            for query in self.sector.topics:
                hits,_=self.search(query,code,doc['year'],doc['report_type'],max(1,limit_per_period//len(self.sector.topics)),True)
                period.update((h['chunk_id'],h) for h in hits)
            selected.update(list(period.items())[:limit_per_period])
        return sorted(selected.values(),key=lambda r:(r['period'],r['chunk_id'])),dict(mode=__import__('dart_remote.mysql_vectors',fromlist=['backend']).backend(),periods=len(docs))
    def fingerprint(self):
        config=dict(version=self.sector.data_version,index_version=self.sector.index_version,membership=self.sector.membership_code,
            topics=self.sector.topics,terms=self.sector.terms,profiles=self.sector.profiles,order=self.sector.companies_order,
            search_backend=__import__('dart_remote.mysql_vectors',fromlist=['backend']).backend(),embedding_revision=__import__('dart_remote.mysql_vectors',fromlist=['REVISION']).REVISION,search_api=os.getenv('FILING_SEARCH_API_URL',''),adapter='central-mysql-bge-v6-company-wordcloud')
        return hashlib.sha256(json.dumps(config,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
