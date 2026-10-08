"""Build the unchanged presentation contract from any discovered sector DB pair."""
import hashlib
import json
import re
import uuid
from statistics import median
from .catalog import SERVICE
from .repository import Repository,REPORTS,ACCOUNTS
from . import prompts
from . import prompts as prompt_profiles
from dart_remote import citation_selection as selection

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
        # Preserve the whole retrieved chunk so subjects and qualifications survive.
        for row in pool:
            result.append(dict(row,anchor_start=0))
    return result

def generate(scope,report,repo,company=None,force=False,keyword=None):
    prompts=prompt_profiles.active()
    selection=prompt_profiles.selection_profile()
    from snapdart import llm
    companies=[company] if company else report['companies']
    rows=[] if keyword else evidence_rows(repo,companies,report['years'])
    if keyword:
        rows,status=repo.search(keyword,company and company['code'],report['years'][-1],top_k=16,business_only=True)
        rows=[dict(r,anchor_start=0,text=r['text']) for r in rows]
        if not rows:
            return dict(sentences=[],method='관련 공시 근거 부족')
    rows=selection.bounded_rows([r for r in rows if selection.passages(r['text'])],report['years'])
    citations=report['citations'];evidence=[];refs={}
    for i,row in enumerate(rows,1):
        eid='t'+str(i);refs[eid]=anchor(row,citations,start=row['anchor_start'])
        evidence.append(dict(id=eid,kind='filing',chunk_id=row['chunk_id'],year=row['year'],company=row['company'],period=row['period'],section=row['section'],heading=row['heading'],text=row['text'],passages=[dict(p,id=eid+'-p'+str(j)) for j,p in enumerate(selection.passages(row['text']),1)]))
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
        if prompts is prompt_profiles:
            return dict(sentences=[],method='분석 근거 부족',selection_version=selection.VERSION,insufficient_reason='확인 가능한 재무·공시 자료가 부족합니다.')
        return dict(sentences=[dict(text='확인 가능한 데이터가 부족합니다.',source_refs=[])],method='분석 근거 부족')
    if not rows:
        return dict(sentences=[],method='관련 공시 근거 부족',selection_version=selection.VERSION,insufficient_reason='이 설명을 뒷받침할 적격 자연어 공시 근거가 없습니다.')
    function='keyword' if keyword else 'company' if company else 'insight'
    context=prompts.context(repo.sector.name,financial,[e for e in evidence if e['kind']=='filing'],company and company['name'],keyword)
    if keyword:
        # Supply calculated signal statistics, never ask the model to invent them.
        signal=next((item for item in scope.get('wordcloud',{}).get(str(report['years'][-1]),[])
                     if item.get('text',item.get('keyword'))==keyword),None)
        if signal:
            context['keyword_statistics']={key:signal[key] for key in
                ('count','company_count','mention_rate','change_raw','years','scope') if key in signal}
            context['keyword_statistics']['definitions']={
                'count':'최신 분석 연도에서 해당 키워드가 포함된 중복 제거 청크 수; 단어 반복 횟수가 아님',
                'mention_rate':'최신 분석 연도 대상 청크 중 키워드 포함 청크 비율; 0-1 척도',
                'change_raw':'전체 분석 연도의 인접 연도 언급 비율 차이를 최근 구간에 더 큰 비중으로 가중평균; 3개년이면 0.4/0.6, 1개년이면 변화 0; 전년 대비 증가율이 아님'}
    context['evidence']=evidence
    context.pop('retrieved_chunks',None)  # Do not transmit the same chunk twice.
    instruction=prompts.instruction(function)+"\n"+selection.INSTRUCTION
    # Short customer summaries plus the existing per-sentence assessment JSON.
    # PDF 300/500-token limits cannot fit the later requested evidence grading.
    maximum=2 if keyword else None if company and prompts is not prompt_profiles else 3;minimum=1
    schema=selection.schema(llm,minimum,maximum,evidence)
    def validate(value,allowed):
        selection.validate(value,evidence,minimum,maximum)
        # Check monetary statements against their cited numeric evidence, allowing only rounding.
        money_pattern=r'(?:(\d[\d,.]*)\s*조\s*)?(?:(\d[\d,.]*)\s*억\s*)?(?:(\d[\d,.]*)\s*만\s*)?(\d[\d,.]*)?\s*원'
        for sentence in value['sentences']:
            cited=[e for e in evidence if e['id'] in sentence['refs']]
            for match in re.finditer(money_pattern,sentence['text']):
                if not any(match.groups()):continue
                amount=sum(float(v.replace(',',''))*scale for v,scale in zip(match.groups(),(1e12,1e8,1e4,1)) if v)
                values=[e['values'].get(k) for e in evidence if e['kind']=='financial' and e['company'] in {r['company'] for r in cited} for k in ACCOUNTS if e['values'].get(k) is not None]
                literal=match.group().replace(' ','')
                unit_precision=min(scale*10**(-len(v.split('.')[-1]) if '.' in v else 0) for v,scale in zip(match.groups(),(1e12,1e8,1e4,1)) if v)
                signed_amount=-amount if sentence['text'][max(0,match.start()-1):match.start()] in ('-','−') else amount
                if not any(abs(v-signed_amount)<=unit_precision/2+1e-6 for v in values) and not any(literal in e.get('text','').replace(' ','') for e in cited):raise ValueError('문장 금액이 인용한 입력 근거와 일치하지 않습니다.')
        return value
    digest=hashlib.sha256(json.dumps([prompts.VERSION,instruction,context,llm.PROVIDER,llm.MODEL],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    cache=SERVICE/repo.sector.id/'llm'/(digest+'.json')
    if cache.exists() and not force:result=json.loads(cache.read_text(encoding='utf-8'));validate(result['report'],evidence)
    else:
        result=llm.request_report(context,evidence,schema=schema,instruction=instruction,validator=validate,max_output_tokens=8192,temperature=1.0)
        result['input_snapshot']=selection.snapshot(evidence)
        atomic(cache,result)
    print(('키워드' if keyword else company['name'] if company else repo.sector.name+' 산업')+' 인사이트 생성·검증 완료',flush=True)
    rendered=[]
    by_id={e['id']:e for e in evidence};by_row={'t'+str(i):r for i,r in enumerate(rows,1)}
    for sentence in result['report']['sentences']:
        selected={a['id']:a for a in sentence['assessments']};source_refs=[]
        for eid in sentence['refs']:
            if by_id[eid]['kind']!='filing':source_refs.append(refs[eid]);continue
            assessment=selected[eid]
            for part in sorted(assessment['passages'],key=lambda p:p['start']):
                row=by_row[eid];quote=row['text'][part['start']:part['end']]
                ref=anchor(row,citations,quote,part['start']);source_refs.append(ref)
                citations[ref]['summary_text']=sentence['text']
                citations[ref]['evidence_score']=assessment['score']
                citations[ref]['selection_version']=selection.VERSION
        rendered.append(dict(text=sentence['text'].strip(),source_refs=list(dict.fromkeys(source_refs))))
    return dict(sentences=rendered,method='AI 생성 · 문장별 공시 근거 검증',prompt_version=prompts.VERSION,
        selection_version=selection.VERSION,insufficient_reason=result['report'].get('insufficient_reason',''))


def build(sector_id=None,use_llm=False,force=False,codes=None,years=None):
    repo=Repository(sector_id);years=repo.analysis_years(years)
    companies=[];citations={}
    for config in repo.companies():
        if codes and not any(i in (config['stock_code'],config['corp_code'],config['company_name']) for i in codes):continue
        code=config['stock_code'];history=financial_history(repo,code,years)
        docs=[d for d in repo.documents(code) if d['year'] in years]
        profile=(repo.sector.profiles or {}).get(code,{})
        companies.append(dict(code=code,name=config['company_name'],corp_code=config['corp_code'],sector=profile.get('business',repo.sector.name),description=profile.get('description','공시와 전사 재무를 바탕으로 사업 흐름을 살펴봅니다.'),
            history=history,documents=[dict(d,topics={}) for d in docs],report_count=len(docs),insights=[],topics={},wordcloud={}))
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
        mode='표준화 재무 DB + 공시 벡터 DB',source=dict(dataset_sha256=repo.fingerprint(),data_version=repo.sector.data_version.split(':',1)[0],index_version=repo.sector.index_version,financial_source='MySQL standardized_financials',filing_source='MySQL chunk_metadata',
        retrieval=__import__('dart_remote.mysql_vectors',fromlist=['backend']).backend(),wordcloud_method='disclosure-signal-v1'),citations=citations,wordcloud={},coverage=repo.coverage())
    from dart_remote.wordcloud import apply as apply_wordcloud
    apply_wordcloud(report,repo)
    for scope,company in [(report,None)]+[(c,c) for c in companies]:
        scope['ai_insights']={}
        selected_companies=[company] if company else companies
        for year in years:
            entries=[]
            for c in selected_companies:
                rows,_=repo.search(' '.join(repo.sector.topics),c['code'],year,'FY',top_k=2,business_only=True)
                if not rows:continue
                row=next((r for r in rows if selection.passages(r['text'])),None)
                if row is None:continue
                quote=selection.passages(row['text'])[0]['text']
                ref=anchor(row,citations,quote,selection.passages(row['text'])[0]['start'])
                entries.append(dict(text=f"{c['name']}의 {year}년 공시 발췌: “{quote}”",source_refs=[ref]))
            scope['ai_insights'][str(year)]=dict(sentences=entries,method='공시 근거 발췌 · AI 생성 전')
    if use_llm:
        from dart_remote.generation import generate_all
        generate_all(report,repo,generate,force)
    if Repository(repo.sector.id).fingerprint()!=repo.fingerprint():raise ValueError('생성 중 데이터 버전이 바뀌었습니다. 다시 생성하세요.')
    from dart_remote.artifacts import put_artifact
    put_artifact(repo.sector.id,'report',report)
    print(f'{repo.sector.name}: 기업 {len(companies)}개, 공시 {sum(c["report_count"] for c in companies)}개, DB 보고서 생성 완료',flush=True)
    return report

def load_report(sector_id=None):
    from dart_remote.artifacts import get_artifact
    repo=Repository(sector_id);report=get_artifact(repo.sector.id,'report')
    if report is None:raise RuntimeError('보고서가 없습니다. python -m snapdart.analyze --llm 으로 먼저 생성하세요.')
    if report.get('source',{}).get('dataset_sha256')!=repo.fingerprint():
        raise RuntimeError('DB 데이터 버전이 바뀌었습니다. python -m snapdart.analyze --llm 으로 다시 생성하세요. 기존 AI 분석은 자동으로 발췌 보고서로 덮어쓰지 않습니다.')
    from dart_remote.wordcloud import apply as apply_wordcloud
    return apply_wordcloud(report,repo)
