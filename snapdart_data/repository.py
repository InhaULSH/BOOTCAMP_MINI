"""SQL facts and existing-vector retrieval behind one sector boundary."""
import hashlib
import json
import re
from functools import lru_cache
import numpy as np
from .catalog import connect,sector

REPORTS={'Q1':('03','1분기보고서'),'H1':('06','반기보고서'),'HY':('06','반기보고서'),'Q3':('09','3분기보고서'),'FY':('12','사업보고서')}
ACCOUNTS={'revenue':('매출액','수익(매출액)','영업수익','수익'),
 'operating_income':('영업이익','영업이익(손실)','영업손익'),
 'operating_cashflow':('영업활동현금흐름','영업활동으로 인한 현금흐름','영업활동으로인한현금흐름'),
 'inventory':('재고자산',),'capex':('유형자산취득(CAPEX)',)}
IDS={'revenue':('ifrs-full_Revenue','ifrs_Revenue'),'operating_income':('dart_OperatingIncomeLoss',),
 'operating_cashflow':('ifrs-full_CashFlowsFromUsedInOperatingActivities','ifrs_CashFlowsFromUsedInOperatingActivities'),
 'inventory':('ifrs-full_Inventories','ifrs_Inventories')}

class Repository:
    def __init__(self,selected=None):self.sector=selected if hasattr(selected,'financial') else sector(selected)
    def companies(self):
        with connect(self.sector.financial) as con:
            rows=[dict(r) for r in con.execute('SELECT * FROM companies WHERE stock_code IS NOT NULL ORDER BY stock_code')]
        order={code:i for i,code in enumerate(self.sector.companies_order)}
        return sorted(rows,key=lambda r:(order.get(r['stock_code'],len(order)),r['stock_code']))
    def company(self,identifier):
        found=[r for r in self.companies() if identifier in (r['stock_code'],r['corp_code'],r['company_name'])]
        if len(found)!=1:raise KeyError('섹터에 속한 기업을 정확히 지정하세요.')
        return found[0]
    def years(self):
        with connect(self.sector.financial) as con:
            return [r[0] for r in con.execute('SELECT DISTINCT year FROM periods ORDER BY year')]
    def facts(self,code,year,report_type='FY',basis='CFS',value_type=None):
        company=self.company(code)
        value_type=value_type or ('annual' if report_type=='FY' else 'cumulative')
        with connect(self.sector.financial) as con:
            rows=con.execute('''SELECT * FROM financial_facts_final WHERE corp_code=? AND year=?
                AND report_type=? AND fs_div=? AND (value_type=? OR value_type='point_in_time')''',
                (company['corp_code'],int(year),report_type,basis,value_type)).fetchall()
        return [dict(r) for r in rows]
    def metric(self,rows,key):
        sections=('IS','CIS') if key in ('revenue','operating_income') else ('BS',) if key=='inventory' else ('CF',)
        for section in sections:
            pool=[r for r in rows if r['sj_div']==section and r['currency']=='KRW']
            # CAPEX uses the promoted direct/derived amount, never the raw component union twice.
            if key=='capex':matches=[r for r in pool if r['standard_account_nm']=='유형자산취득(CAPEX)' and r['cash_outflow_amount'] is not None]
            else:
                matches=[r for r in pool if r['standard_account_nm'] in ACCOUNTS[key]]
                if not matches:matches=[r for r in pool if r['account_id'] in IDS.get(key,())]
            pairs=[(r, r['cash_outflow_amount'] if key=='capex' else r['calculated_value'] if r['is_calculated'] else r['normalized_value']) for r in matches]
            values={v for _,v in pairs if v is not None}
            if len(values)==1:return next(iter(values)),[dict(r,value=v) for r,v in pairs if v is not None]
            if len(values)>1:raise ValueError(f'{key}: 동일 기업·기간·기준에서 서로 다른 계정 값이 발견됐습니다.')
        return None,[]
    def financial(self,code,year,report_type='FY',basis='CFS',value_type=None):
        rows=self.facts(code,year,report_type,basis,value_type)
        values={};sources={}
        for key in ACCOUNTS:values[key],sources[key]=self.metric(rows,key)
        return dict(year=int(year),report_type=report_type,basis=basis if rows else None,**values,financial_sources=sources)
    def documents(self,code):
        corp=self.company(code)['corp_code']
        with connect(self.sector.filings) as con:
            rows=con.execute('''SELECT corp_name,corp_code,year,report_type,rcept_no,COUNT(*) AS chunk_count
                FROM filing_chunks WHERE corp_code=? GROUP BY corp_name,corp_code,year,report_type,rcept_no ORDER BY year,report_type''',(corp,)).fetchall()
        return [dict(r,period=f"{r['year']}-{REPORTS[r['report_type']][0]}",report_name=REPORTS[r['report_type']][1],
            receipt_no=r['rcept_no'],document_id=r['rcept_no'],document_role='main',stock_code=code) for r in rows]
    def chunks(self,code=None,year=None,report_type=None):
        where=[];params=[]
        if code:where.append('corp_code=?');params.append(self.company(code)['corp_code'])
        if year is not None:where.append('year=?');params.append(int(year))
        if report_type:where.append('report_type=?');params.append(report_type)
        query='SELECT * FROM filing_chunks'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY rcept_no,chunk_id'
        with connect(self.sector.filings) as con:
            return [dict(r) for r in con.execute(query,params)]
    def chunk(self,chunk_id):
        with connect(self.sector.filings) as con:
            row=con.execute('SELECT * FROM filing_chunks WHERE chunk_id=?',(chunk_id,)).fetchone()
        if row is None:raise KeyError('청크가 없습니다.')
        return dict(row)
    def adapt(self,row,score=None):
        code=self.company(row['corp_code'])['stock_code']
        return dict(chunk_id=row['chunk_id'],document_id=row['rcept_no'],paragraph_ids=[row['chunk_id']],
            company=row['corp_name'],stock_code=code,year=row['year'],period=f"{row['year']}-{REPORTS[row['report_type']][0]}",
            report_name=REPORTS[row['report_type']][1],report_type=row['report_type'],receipt_no=row['rcept_no'],
            section=row['section_name'],heading=row.get('subsection_name') or row['section_name'],text=row['chunk_text'],
            start_char=0,end_char=len(row['chunk_text']),table_id='',retrieval_score=score,
            sector_id=self.sector.id,content_hash=row['content_hash'],embedding_model=row['embedding_model'])
    def search(self,query,code=None,year=None,report_type=None,top_k=5,business_only=False):
        if not isinstance(query,str) or not query.strip():raise ValueError('검색어가 필요합니다.')
        if not 1<=top_k<=40:raise ValueError('top_k는 1-40이어야 합니다.')
        stamp=self.sector.filings.stat()
        rows,matrix,norms=_vector_pool(str(self.sector.filings),stamp.st_mtime_ns,stamp.st_size,code and self.company(code)['corp_code'],year,report_type,business_only)
        terms=list(dict.fromkeys(re.findall(r'[A-Za-z][A-Za-z0-9-]*|[가-힣]{2,}',query.lower())))
        aliases={'ai':['인공지능'],'capex':['설비투자','유형자산'],'hbm':['고대역폭'],'현금흐름':['영업활동현금흐름'],'연구개발':['개발']}
        terms=list(dict.fromkeys(terms+[a for t in terms for a in aliases.get(t,[])]))
        scores=np.asarray([sum(min(5,r['chunk_text'].lower().count(t)) for t in terms)/max(1,len(terms)) *
            min(1,len(re.findall('[가-힣]',r['chunk_text']))/max(1,len(r['chunk_text']))*3) for r in rows],dtype=np.float32)
        if not len(rows) or not np.any(scores):return [],dict(mode='no-relevant-evidence',query=query)
        # The imported custom hash encoder source is absent. Never embed with a different encoder.
        # Build an in-space query from keyword-matching stored vectors, then retrieve by cosine.
        seeds=np.argsort(-scores,kind='stable')[:min(5,int(np.count_nonzero(scores)))]
        centroid=np.average(matrix[seeds],axis=0,weights=scores[seeds]);length=np.linalg.norm(centroid)
        cosine=matrix@centroid/np.maximum(norms*length,1e-12)
        combined=.55*cosine+.45*(scores/max(float(scores.max()),1))
        # Require some keyword support: neighbours alone are not proof of query relevance.
        chosen=[i for i in np.argsort(-combined,kind='stable') if scores[i]>0][:top_k]
        return [self.adapt(rows[i],float(combined[i])) for i in chosen],dict(mode='sqlite-stored-vector-seeded-hybrid',
            embedding_model=rows[0]['embedding_model'],query=query,seed_count=len(seeds),scope=dict(sector=self.sector.id,code=code,year=year,report_type=report_type))
    def select_evidence(self,code,limit_per_period=8):
        selected={};statuses=[]
        for doc in self.documents(code):
            period={}
            for query in self.sector.topics:
                hits,status=self.search(query,code,doc['year'],doc['report_type'],max(1,limit_per_period//len(self.sector.topics)),business_only=True)
                statuses.append(status)
                period.update((h['chunk_id'],h) for h in hits)
            selected.update(list(period.items())[:limit_per_period])
        return sorted(selected.values(),key=lambda r:(r['period'],r['chunk_id'])),dict(mode='sqlite-stored-vector-seeded-hybrid',periods=len(self.documents(code)),queries=list(self.sector.topics))
    def fingerprint(self):
        info={}
        for path in (self.sector.financial,self.sector.filings):
            stat=path.stat();info[path.name]=dict(bytes=stat.st_size,modified_ns=stat.st_mtime_ns)
        config=self.sector.folder.parent/'sectors.json'
        info['sector_config']=json.loads(config.read_text(encoding='utf-8')).get(self.sector.id,{}) if config.exists() else {}
        info['code_version']='db-v1'
        return hashlib.sha256(json.dumps(info,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

@lru_cache(maxsize=32)
def _vector_pool(path,mtime,size,corp,year,report_type,business_only):
    where=[];params=[]
    for key,value in [('corp_code',corp),('year',year),('report_type',report_type)]:
        if value is not None:where.append(key+'=?');params.append(value)
    if business_only:
        where.append("(section_name LIKE 'II.%' OR section_name LIKE 'IV.%')")
    with connect(__import__('pathlib').Path(path)) as con:
        rows=[dict(r) for r in con.execute('SELECT * FROM filing_chunks'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY chunk_id',params)]
    models={(r['embedding_model'],r['dimensions']) for r in rows}
    if len(models)>1:raise ValueError('서로 다른 임베딩 모델·차원을 한 검색에서 혼합할 수 없습니다.')
    if not rows:return [],np.empty((0,0),dtype=np.float32),np.empty(0)
    vectors=[]
    for row in rows:
        vector=np.frombuffer(row.pop('embedding'),dtype='<f4')
        if len(vector)!=row['dimensions'] or not np.all(np.isfinite(vector)):raise ValueError('벡터 크기 또는 유효성 오류')
        vectors.append(vector)
    matrix=np.stack(vectors);norms=np.linalg.norm(matrix,axis=1)
    return rows,matrix,norms
