"""Build the unchanged presentation contract from any discovered sector DB pair."""
import hashlib
import json
import re
import uuid
from collections import Counter
from statistics import median
from .catalog import SERVICE,sector,sectors
from .repository import Repository,REPORTS,ACCOUNTS
from . import prompts

def ratio(a,b):return a/b*100 if a is not None and b is not None and b>0 else None
def growth(a,b):return ratio(a-b,b) if a is not None and b is not None else None
def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)

def financial_history(repo,code,years):
    history=[]
    for year in years:
        row=repo.financial(code,year)
        if row['basis'] is None:row=repo.financial(code,year,basis='OFS')
        previous=next((r for r in history if r['year']==year-1 and r['basis']==row['basis']),{})
        row['yoy']={key:growth(row[key],previous.get(key)) for key in ('revenue','operating_income','capex','operating_cashflow')}
        row['margin']=ratio(row['operating_income'],row['revenue']);row['capex_ratio']=ratio(row['capex'],row['revenue'])
        row['fcf']=row['operating_cashflow']-row['capex'] if row['operating_cashflow'] is not None and row['capex'] is not None else None
        row['fcf_margin']=ratio(row['fcf'],row['revenue'])
        for key in ('revenue','capex','inventory'):row[key+'_growth']=growth(row[key],previous.get(key))
        row['positions']={};history.append(row)
    return history

def counts(repo,code,year):
    terms=repo.sector.terms
    if not terms:
        terms=tuple(dict.fromkeys(t for q in repo.sector.topics for t in re.findall(r'[A-Za-z][A-Za-z0-9]*|[가-힣]{2,}',q)))
    result=Counter()
    for row in repo.chunks(code,year):
        text=row['chunk_text'];section=row['section_name']
        if not re.match(r'^II\s*\.\s*사업',section):continue
        for term in terms:
            pattern=r'(?<![A-Za-z0-9])'+re.escape(term)+r'(?![A-Za-z0-9])' if term.isascii() else re.escape(term)
            result[term]+=len(re.findall(pattern,text,re.I))
    return [dict(text=t,count=n) for t,n in sorted(result.items(),key=lambda x:(-x[1],x[0])) if n]

def anchor(row,citations,quote=None,start=0):
    quote=quote or row['text']
    key='src-'+hashlib.sha256((row['sector_id']+'\0'+row['chunk_id']+'\0'+str(start)+'\0'+quote).encode()).hexdigest()[:24]
    citations[key]=dict(sector_id=row['sector_id'],document_id=row['receipt_no'],paragraph_id=row['chunk_id'],chunk_id=row['chunk_id'],
        company=row['company'],period=row['period'],report_name=row['report_name'],receipt_no=row['receipt_no'],section=row['section'],heading=row['heading'],
        quote=quote,start_char=start,end_char=start+len(quote),source_kind='filing')
    return key

def evidence_rows(repo,companies,years):
    result=[]
    for company in companies:
        rows,_=repo.select_evidence(company['code'],8)
        # Latest year's all report types plus bounded historical anchors for change claims.
        pool=[]
        for year in years:
            periods=sorted({r['period'] for r in rows if r['year']==year})
            for period in periods:
                group=[r for r in rows if r['period']==period]
                pool.extend(group[:2 if year==years[-1] else 1])
        for row in pool:
            # Anchor at a sentence boundary instead of an arbitrary truncated quotation.
            sentences=[(m.start(),m.group().strip()) for m in re.finditer(r'[^\n]+',row['text']) if 30<=len(m.group().strip())<=320]
            if not sentences:
                parts=re.split(r'(?<=[다요])\.\s+',row['text']);offset=0
                for part in parts:
                    if 30<=len(part.strip())<=320:sentences.append((row['text'].find(part),part.strip()))
            if not sentences:continue
            position,text=max(sentences,key=lambda pair:sum(pair[1].lower().count(t.lower()) for q in repo.sector.topics for t in q.split()))
            position=row['text'].find(text,position)
            result.append(dict(row,text=text,anchor_start=position))
    return result

def generate(scope,report,repo,company=None,force=False,keyword=None):
    from snapdart import llm
    companies=[company] if company else report['companies']
    rows=evidence_rows(repo,companies,report['years'])
    if keyword:
        rows,status=repo.search(keyword,company and company['code'],report['years'][-1],top_k=8,business_only=True)
        rows=[dict(r,anchor_start=0,text=r['text'][:280]) for r in rows]
    citations=report['citations'];evidence=[];refs={}
    for i,row in enumerate(rows,1):
        eid='t'+str(i);refs[eid]=anchor(row,citations,start=row['anchor_start'])
        evidence.append(dict(id=eid,kind='filing',year=row['year'],company=row['company'],period=row['period'],text=row['text']))
    financial=[]
    for c in companies:
        records=[]
        for row in c['history']:
            records.append({key:row.get(key) for key in ('year','basis','revenue','operating_income','capex','operating_cashflow','yoy','margin','fcf')})
        # Include quarter/half-year changes without confusing quarterly and cumulative CF.
        interim=[];interim_records=[]
        for report_type in ('Q1','H1','Q3'):
            f=repo.financial(c['code'],report['years'][-1],report_type,basis=c['history'][-1]['basis'] or 'CFS')
            interim.append({k:f[k] for k in ('year','report_type','basis','revenue','operating_income','capex','operating_cashflow')})
            interim_records.append(f)
        financial.append(dict(company=c['name'],annual=records,interim_cumulative=interim))
        for row in c['history']:
            eid='f'+str(len(evidence)+1)
            receipts={f['rcept_no'] for entries in row['financial_sources'].values() for f in entries}
            # A financial citation is resolved to its original report, not a guessed filing sentence.
            financial_citation='fin-'+hashlib.sha256((repo.sector.id+c['code']+str(row['year'])).encode()).hexdigest()[:24]
            citations[financial_citation]=dict(source_kind='financial',sector_id=repo.sector.id,code=c['code'],year=row['year'],company=c['name'],basis=row['basis'],report_name='사업보고서',
                period=f"{row['year']}-12",receipt_no=next(iter(receipts),'') if len(receipts)<=1 else '',section='재무제표',heading='표준화 재무 데이터',paragraph_id=eid)
            refs[eid]=financial_citation
            evidence.append(dict(id=eid,kind='financial',year=row['year'],company=c['name'],values=records[c['history'].index(row)]))
        for f,values in zip(interim_records,interim):
            if not any(values.get(k) is not None for k in ACCOUNTS):continue
            eid='f'+str(len(evidence)+1);report_type=f['report_type']
            receipts={s['rcept_no'] for entries in f.get('financial_sources',{}).values() for s in entries}
            key='fin-'+hashlib.sha256((repo.sector.id+c['code']+str(f['year'])+report_type).encode()).hexdigest()[:24]
            citations[key]=dict(source_kind='financial',sector_id=repo.sector.id,code=c['code'],year=f['year'],company=c['name'],report_type=report_type,basis=f['basis'],
                report_name=REPORTS[report_type][1],period=f"{f['year']}-{REPORTS[report_type][0]}",receipt_no=next(iter(receipts),'') if len(receipts)<=1 else '',section='재무제표',heading='표준화 누적 재무 데이터',paragraph_id=eid)
            refs[eid]=key
            evidence.append(dict(id=eid,kind='financial',year=f['year'],company=c['name'],values=values))
    if not rows and not any(any(r.get(k) is not None for k in ACCOUNTS) for c in companies for r in c['history']):
        return dict(sentences=[dict(text='확인 가능한 데이터가 부족합니다.',source_refs=[])],method='분석 근거 부족')
    function='keyword' if keyword else 'company' if company else 'insight'
    context=prompts.context(repo.sector.name,financial,[e for e in evidence if e['kind']=='filing'],company and company['name'],keyword)
    context['evidence']=evidence
    instruction=prompts.instruction(function)
    maximum=2 if keyword else None if company else 3;minimum=1 if keyword or company else 2
    # Keep the existing sentence citations required by the UI. Schema field
    # descriptions explain transport fields, not additional analysis rules.
    sentence_schema=dict(type='array',minItems=minimum,items=llm.object_schema({'text':dict(type='string',description='인사이트의 한 문장'), 'refs':dict(type='array',items=llm.TEXT,description='이 문장을 뒷받침하는 입력 evidence의 id')}))
    if maximum is not None:sentence_schema['maxItems']=maximum
    schema=llm.object_schema({'sentences':sentence_schema})
    def validate(value,allowed):
        if not isinstance(value,dict) or not isinstance(value.get('sentences'),list) or len(value['sentences'])<minimum or (maximum is not None and len(value['sentences'])>maximum):raise ValueError('문장 수 오류')
        for sentence in value['sentences']:
            if not isinstance(sentence,dict):raise ValueError('문장 형식 오류')
            text=sentence.get('text');ids=sentence.get('refs')
            if not isinstance(text,str) or not text.strip():raise ValueError('문장 형식 오류')
            if not isinstance(ids,list) or any(not isinstance(i,str) or i not in refs for i in ids):raise ValueError('입력에 없는 근거 ID')
        # Check monetary statements against their cited numeric evidence, allowing only rounding.
        money_pattern=r'(?:(\d[\d,.]*)\s*조\s*)?(?:(\d[\d,.]*)\s*억\s*)?(?:(\d[\d,.]*)\s*만\s*)?(\d[\d,.]*)?\s*원'
        for sentence in value['sentences']:
            cited=[e for e in evidence if e['id'] in sentence['refs']]
            for match in re.finditer(money_pattern,sentence['text']):
                if not any(match.groups()):continue
                amount=sum(float(v.replace(',',''))*scale for v,scale in zip(match.groups(),(1e12,1e8,1e4,1)) if v)
                values=[e['values'].get(k) for e in cited if e['kind']=='financial' for k in ACCOUNTS if e['values'].get(k) is not None]
                literal=match.group().replace(' ','')
                unit_precision=min(scale*10**(-len(v.split('.')[-1]) if '.' in v else 0) for v,scale in zip(match.groups(),(1e12,1e8,1e4,1)) if v)
                signed_amount=-amount if sentence['text'][max(0,match.start()-1):match.start()] in ('-','−') else amount
                if not any(abs(v-signed_amount)<=unit_precision/2+1e-6 for v in values) and not any(literal in e.get('text','').replace(' ','') for e in cited):raise ValueError('문장 금액이 인용한 입력 근거와 일치하지 않습니다.')
        return value
    digest=hashlib.sha256(json.dumps([prompts.VERSION,instruction,context,llm.PROVIDER,llm.MODEL],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    cache=SERVICE/repo.sector.id/'llm'/(digest+'.json')
    if cache.exists() and not force:result=json.loads(cache.read_text(encoding='utf-8'));validate(result['report'],evidence)
    else:
        result=llm.request_report(context,evidence,schema=schema,instruction=instruction,validator=validate,max_output_tokens=300 if keyword else 500,temperature=1)
        atomic(cache,result)
    print(('키워드' if keyword else company['name'] if company else repo.sector.name+' 산업')+' 인사이트 생성·검증 완료',flush=True)
    return dict(sentences=[dict(text=s['text'].strip(),source_refs=list(dict.fromkeys(refs[i] for i in s['refs']))) for s in result['report']['sentences']],method='AI 생성 · DB 근거',prompt_version=prompts.VERSION)

def build(sector_id=None,use_llm=False,force=False,codes=None,years=None):
    repo=Repository(sector_id);available=repo.years();years=sorted(years or available[-3:])
    if not years or not set(years)<=set(available):raise ValueError('요청 연도가 DB에 없습니다.')
    companies=[];citations={}
    for config in repo.companies():
        if codes and not any(i in (config['stock_code'],config['corp_code'],config['company_name']) for i in codes):continue
        code=config['stock_code'];history=financial_history(repo,code,years)
        docs=[d for d in repo.documents(code) if d['year'] in years]
        settings_path=repo.sector.folder.parent/'sectors.json'
        settings=json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else {}
        profile=settings.get(repo.sector.id,{}).get('company_profiles',{}).get(code,{})
        companies.append(dict(code=code,name=config['company_name'],corp_code=config['corp_code'],sector=profile.get('business',repo.sector.name),description=profile.get('description','공시와 전사 재무를 바탕으로 사업 흐름을 살펴봅니다.'),
            history=history,documents=[dict(d,topics={}) for d in docs],report_count=len(docs),insights=[],topics={},wordcloud={str(y):counts(repo,code,y) for y in years}))
    if not companies:raise ValueError('요청 기업이 해당 섹터 DB에 없습니다.')
    metrics=('revenue_growth','margin','capex_growth','capex_ratio','inventory_growth','fcf')
    industry=[]
    for year in years:
        summary=dict(year=year)
        for key in metrics:
            vals=[r[key] for c in companies for r in c['history'] if r['year']==year and r[key] is not None]
            summary[key]=median(vals) if vals else None;summary[key+'_n']=len(vals)
            for c in companies:
                r=next(r for r in c['history'] if r['year']==year);v=r[key]
                r['positions'][key]=100*(sum(x<v for x in vals)+.5*vals.count(v))/len(vals) if v is not None and len(vals)>=2 else None
        industry.append(summary)
    report=dict(sector_id=repo.sector.id,sector_name=repo.sector.name,index_code=repo.sector.index_code,companies=companies,years=years,industry=industry,signals=[],diffusion=[],
        mode='표준화 재무 DB + 공시 벡터 DB',source=dict(data_root=str(repo.sector.folder),dataset_sha256=repo.fingerprint(),financial_source='financial.db',filing_source='filings.db',
        retrieval='기존 벡터 공간의 키워드 근거 중심벡터 + 코사인·키워드 결합',wordcloud_method='사업 관련 섹션의 DB 청크 단순 빈도; 청크간 중복 표현 포함'),citations=citations,wordcloud={})
    for year in years:
        total=Counter()
        for c in companies:total.update({r['text']:r['count'] for r in c['wordcloud'][str(year)]})
        report['wordcloud'][str(year)]=[dict(text=t,count=n) for t,n in sorted(total.items(),key=lambda x:(-x[1],x[0])) if n]
    for scope,company in [(report,None)]+[(c,c) for c in companies]:
        scope['ai_insights']={}
        selected_companies=[company] if company else companies
        for year in years:
            entries=[]
            for c in selected_companies:
                rows,_=repo.search(' '.join(repo.sector.topics),c['code'],year,'FY',top_k=2,business_only=True)
                if not rows:continue
                row=rows[0];quote=row['text'][:120]
                ref=anchor(row,citations,quote)
                entries.append(dict(text=f"{c['name']}의 {year}년 공시 발췌: “{quote}”",source_refs=[ref]))
                if len(entries)==2:break
            scope['ai_insights'][str(year)]=dict(sentences=entries,method='공시 근거 발췌 · AI 생성 전')
        if use_llm:scope['ai_insights'][str(years[-1])]=generate(scope,report,repo,company,force)
    atomic(repo.sector.report,report)
    print(f'{repo.sector.name}: 기업 {len(companies)}개, 공시 {sum(c["report_count"] for c in companies)}개, DB 보고서 생성 완료',flush=True)
    return report

def load_report(sector_id=None):
    repo=Repository(sector_id)
    if not repo.sector.report.exists():return build(repo.sector.id)
    report=json.loads(repo.sector.report.read_text(encoding='utf-8'))
    if report.get('source',{}).get('dataset_sha256')!=repo.fingerprint():
        # Data refresh invalidates old generated claims, never silently retain stale insights.
        return build(repo.sector.id)
    return report
