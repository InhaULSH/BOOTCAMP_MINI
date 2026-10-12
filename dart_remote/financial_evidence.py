"""Verified financial facts for new2; no model calls and no report schema changes."""
import hashlib
import math
import re
from .repository import REPORTS, ACCOUNTS
from .response_validation import MONEY
from .citation_selection import CitationValidationError

LABELS = {'revenue':'매출액', 'operating_income':'영업이익', 'operating_cashflow':'영업활동현금흐름',
          'capex':'CAPEX', 'inventory':'재고자산', 'margin':'영업이익률', 'fcf':'잉여현금흐름',
          'capex_ratio':'CAPEX / 매출액', 'fcf_margin':'FCF Margin', 'rd':'연구개발비',
          'rd_ratio':'R&D / 매출액', 'net_interest_income':'순이자이익', 'net_income':'당기순이익',
          'credit_loss':'신용손실비용', 'equity':'자기자본', 'assets':'자산총계', 'loans':'대출채권'}
RATIOS = {'margin','capex_ratio','fcf_margin','rd_ratio'}
VERSION = 'financial-validation-v6-claim-local-context'


def scope_prefix(text):
    """Completed parenthetical comparisons must not change the main clause's year."""
    previous=None
    while previous != text:
        previous=text
        text=re.sub(r'\([^()]*\)|（[^（）]*）',' ',text)
    return text


class FinancialClaimError(ValueError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details=details
ALIASES = {'revenue':r'매출액|매출', 'operating_income':r'영업이익(?!률)|영업손실|영업손익',
           'operating_cashflow':r'영업활동\s*현금\s*흐름', 'capex':r'CAPEX(?!\s*/)|설비투자액|유형자산\s*취득액',
           'inventory':r'재고자산', 'margin':r'영업이익률', 'fcf':r'잉여현금흐름|FCF(?!\s*Margin)',
           'capex_ratio':r'CAPEX\s*/\s*매출액|설비투자\s*비율', 'fcf_margin':r'FCF\s*Margin|잉여현금흐름률',
           'rd':r'연구개발비|연구개발\s*지출|R&D\s*지출', 'rd_ratio':r'R&D\s*/\s*매출액|연구개발비\s*비율',
           'net_interest_income':r'순이자\s*(?:이익|수익)(?!률)', 'net_income':r'당기\s*순이익|순이익',
           'credit_loss':r'신용손실\s*비용|대손\s*비용', 'equity':r'자기자본|자본총계', 'assets':r'자산총계|총자산', 'loans':r'대출채권',
           # These are different definitions, not aliases of available financial facts.
           'unsupported':r'지배\s*주주(?:에\s*귀속되는)?\s*(?:당기\s*)?순이익|순이자\s*(?:마진|이익률|수익률)|NIM|ROE|ROA|CET1|보통주\s*자본\s*비율|자기자본\s*이익률|총자산\s*이익률'}

PERCENT = re.compile(r'([+＋\-−－]?\s*\d[\d,]*(?:\.\d+)?)\s*(%\s*[pP]|%|퍼센트포인트)')


def claim_metric(text, match, mode, ordered):
    """Read attached labels on either side; never choose a metric by its value."""
    prefix=scope_prefix(text[:match.start()])
    labels=metric_mentions(prefix)
    if match.start() in ordered:return ordered[match.start()][0]
    # Restrict forward labels to a grammatical attachment, not a later clause.
    tail=text[match.end():match.end()+100]
    after=metric_mentions(tail)
    attached=None
    if after:
        start,end,key=after[0]
        if re.fullmatch(r'\s*(?:(?:의|을|를|인|규모인|규모의|수준인|수준의)\s*)?',tail[:start]):
            attached=key
    if mode=='percent' and re.search(r'(?:매출액|매출)\s*(?:대비|의)\s*$',prefix):
        ratios={'capex':'capex_ratio','rd':'rd_ratio','fcf':'fcf_margin','operating_income':'margin'}
        # A numerator must be stated in the same clause, before or after the ratio.
        clause=re.split(r'[,，;!?]|(?<!\d)\.(?!\d)',prefix)[-1]
        before=[key for _,_,key in metric_mentions(clause) if key!='revenue']
        right=re.split(r'[,，;!?]|(?<!\d)\.(?!\d)',tail)[0]
        forward=[hit for hit in metric_mentions(right) if hit[2]!='revenue']
        if forward and re.search(r'입니다|이며|이고|했습니다|기록했고|다만|반면|또한|한편',right[:forward[0][0]]):
            forward=[]  # Do not borrow a numerator from a separate assertion.
        following=[key for _,_,key in forward]
        numerators=set(before[-1:]+following[:1])
        if len(numerators)==1 and next(iter(numerators)) in ratios:
            return ratios[next(iter(numerators))]
        raise FinancialClaimError('매출액 대비 비율의 분자 항목을 확인할 수 없거나 모호합니다.',claim=match.group())
    if attached:return attached
    if labels:return labels[-1][2]
    raise FinancialClaimError('수치 주장의 재무 항목을 확인할 수 없습니다.',claim=match.group(),mode=mode)


def metric_mentions(text):
    """Keep the longest overlapping label: CAPEX/매출액 is not revenue."""
    hits=[(m.start(),m.end(),key) for key,pattern in ALIASES.items()
          for m in re.finditer(pattern,text,re.I)]
    chosen=[]
    for start,end,key in sorted(hits,key=lambda h:(-(h[1]-h[0]),h[0],h[2])):
        if not any(start<b and end>a for a,b,_ in chosen):chosen.append((start,end,key))
    return sorted(chosen)


def ordered_claims(text, matches, evidence):
    """Resolve explicit '각각' lists by order, never by which number matches."""
    bindings={}
    previous_end=0
    for marker in re.finditer(r'각각',text):
        group=[];end=marker.end()
        for match,mode in sorted(matches,key=lambda item:item[0].start()):
            if match.start()<marker.end():continue
            gap=text[end:match.start()]
            if not re.fullmatch(r'\s*(?:[,，·]|및|와|과)?\s*',gap):break
            group.append((match,mode));end=match.end()
        # '각각' can describe business activity without introducing numeric claims.
        if not group:continue
        context=scope_prefix(text[previous_end:marker.start()])
        # End a prior independent clause, but not decimal points in monetary values.
        context=re.split(r'[;!?]|(?<!\d)\.(?!\d)',context)[-1]
        labels=list(dict.fromkeys(key for _,_,key in metric_mentions(context)))
        if len(labels)!=len(group) or len(labels)<2:
            raise ValueError('각각 표현의 재무 항목과 수치 개수·순서가 모호합니다. 항목별로 명시하세요.')
        named={e['company'] for e in evidence if e.get('company') and e['company'] in context}
        if len(named)>1:
            raise ValueError('여러 기업의 각각 수치는 기업별로 명시해야 합니다.')
        if len(set(re.findall(r'((?:19|20)\d{2})\s*년',context)))>1:
            raise ValueError('여러 기간의 각각 수치는 기간별로 명시해야 합니다.')
        if '연결' in context and '별도' in context:
            raise ValueError('연결·별도 각각 수치는 회계 기준별로 명시해야 합니다.')
        periods=set(re.findall(r'[1-4]분기|반기|상반기|연간|사업보고서',context))
        if '상반기' in periods:periods.discard('반기')
        if '연간' in periods:periods.discard('사업보고서')
        if len(periods)>1:
            raise ValueError('여러 보고기간의 각각 수치는 기간별로 명시해야 합니다.')
        suffix=re.split(r'[,，;.!?]',text[end:])[0][:24]
        for metric,(match,mode) in zip(labels,group):
            bindings[match.start()]=(metric,suffix)
        previous_end=end
    return bindings

def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def prepare(repo, companies, years, evidence, refs, citations):
    """Each ID identifies one metric/period/basis plus exact calculation inputs."""
    from .capex_validation import verified_financial
    from .graph_metrics import GraphData
    membership=getattr(repo.sector,'membership_code','')
    extra=GraphData(repo) if membership in ('KRX_BANK','KRX_HEALTH') else None
    summary=[]
    for company in companies:
        records=[dict(r,report_type='FY') for r in company['history']]
        basis=company['history'][-1].get('basis') or 'CFS'
        for year in sorted(set((years[-1],years[-1]-1))):
            for kind in ('Q1','H1','Q3'):
                records.append(verified_financial(repo,company['code'],year,kind,basis=basis))
        facts=[]
        for record in records:
            kind=record['report_type'];year=record['year'];basis=record.get('basis')
            if basis not in ('CFS','OFS'):continue
            values={k:record.get(k) for k in ACCOUNTS}
            sources={k:record.get('financial_sources',{}).get(k,[]) for k in values}
            if extra:
                metric_map=({'net_interest_income':'NET_INTEREST_INCOME','net_income':'NET_INCOME',
                    'credit_loss':'CREDIT_LOSS_EXPENSE','equity':'TOTAL_EQUITY','assets':'TOTAL_ASSETS',
                    'loans':'LOANS_AT_AMORTISED_COST'} if extra.bank else {'rd':'RD'})
                for key,metric in metric_map.items():
                    mode='point_in_time' if key in ('equity','assets','loans') else 'annual' if kind=='FY' else 'cumulative'
                    values[key],sources[key]=extra.value(company['code'],year,kind,basis,metric,mode)
            dependencies={k:[k] for k in values}
            for key,numerator in (('margin','operating_income'),('capex_ratio','capex'),('rd_ratio','rd')):
                a,b=values.get(numerator),values.get('revenue')
                values[key]=a/b*100 if finite(a) and finite(b) and b>0 else None
                dependencies[key]=[numerator,'revenue']
            cf,cap=values.get('operating_cashflow'),values.get('capex')
            values['fcf']=cf-cap if finite(cf) and finite(cap) else None
            dependencies['fcf']=['operating_cashflow','capex']
            rev=values.get('revenue')
            values['fcf_margin']=values['fcf']/rev*100 if finite(values['fcf']) and finite(rev) and rev>0 else None
            dependencies['fcf_margin']=['operating_cashflow','capex','revenue']
            for metric,value in values.items():
                inputs=[]
                if metric not in LABELS or not finite(value):continue
                for key in dependencies[metric]:
                    for source in sources.get(key,[]):
                        inputs.append(dict(metric=key,year=year,report_type=kind,basis=basis,
                            value_type=source.get('value_type','annual' if kind=='FY' else 'cumulative'),
                            receipt_no=source.get('rcept_no') or source.get('source_rcept_no',''),
                            source_text=source.get('source_text',''),section=source.get('section','재무제표'),
                            heading=source.get('heading') or source.get('original_account_nm') or source.get('source_account_nm',''),
                            estimated=bool(source.get('estimated')),value=values[key]))
                # Finite numbers without provenance are not eligible financial citations.
                if any(not any(i['metric']==key and i['receipt_no'] for i in inputs) for key in dependencies[metric]):continue
                eid='f'+str(len(evidence)+1)
                token='\0'.join(map(str,(repo.sector.id,company['code'],year,kind,basis,metric)))
                citation='fin-'+hashlib.sha256(token.encode()).hexdigest()[:24]
                receipts={i['receipt_no'] for i in inputs}
                fact=dict(id=eid,kind='financial',company=company['name'],year=year,report_type=kind,
                    period=f'{year}-{REPORTS[kind][0]}',metric=metric,label=LABELS[metric],unit='%' if metric in RATIOS else '원',
                    value_type='point_in_time' if metric in ('inventory','equity','assets','loans') else 'annual' if kind=='FY' else 'cumulative',
                    values={metric:value,'basis':basis,'report_type':kind},estimated=any(i['estimated'] for i in inputs))
                citations[citation]=dict(source_kind='financial',sector_id=repo.sector.id,code=company['code'],
                    company=company['name'],year=year,report_type=kind,basis=basis,period=fact['period'],
                    report_name=REPORTS[kind][1],receipt_no=next(iter(receipts)) if len(receipts)==1 else '',
                    section='재무제표',heading=LABELS[metric],paragraph_id=eid,financial_fact=dict(fact),source_inputs=inputs)
                evidence.append(fact);refs[eid]=citation;facts.append(fact)
        index={(f['year'],f['report_type'],f['values']['basis'],f['metric']):f for f in facts}
        for fact in facts:
            previous=index.get((fact['year']-1,fact['report_type'],fact['values']['basis'],fact['metric']))
            if not previous:continue
            current= fact['values'][fact['metric']];prior=previous['values'][fact['metric']]
            comparison=dict(ref=previous['id'],year=previous['year'],value=prior,difference=current-prior,
                growth_pct=(current-prior)/prior*100 if fact['metric'] not in RATIOS and prior>0 else None,
                difference_pp=current-prior if fact['metric'] in RATIOS else None,
                estimated=fact['estimated'] or previous['estimated'])
            fact['comparison']=comparison
            citations[refs[fact['id']]]['financial_fact']=dict(fact)
            citations[refs[fact['id']]]['comparison_source_ref']=refs[previous['id']]
        summary.append(dict(company=company['name'],financial_evidence_ids=[f['id'] for f in facts]))
    return summary

def _comparison_refs(sentence, candidates, lookup, auto_links, message):
    """Only follow a selected fact's verified predecessor; never search by value."""
    missing=[f for f in candidates if f.get('comparison',{}).get('ref') not in sentence['refs']]
    if not missing:return
    details=dict(current_ids=[f['id'] for f in missing],
                 required_refs=[f.get('comparison',{}).get('ref') for f in missing])
    if auto_links is None:raise FinancialClaimError(message,**details)
    for fact in missing:
        comparison=fact.get('comparison',{});previous=lookup.get(comparison.get('ref'))
        metric=fact['metric']
        valid=previous and previous.get('kind')=='financial' and all(
            fact.get(key)==previous.get(key) for key in ('company','metric','report_type','value_type'))
        valid=valid and previous.get('year')==fact['year']-1 and comparison.get('year')==previous['year']
        valid=valid and previous['values'].get('basis')==fact['values'].get('basis')
        current=fact['values'].get(metric);prior=previous['values'].get(metric) if previous else None
        valid=valid and finite(current) and finite(prior)
        if not valid:raise FinancialClaimError('비교 근거의 기업·항목·기간·회계 기준이 일치하지 않습니다.',**details)
        expected=dict(value=prior,difference=current-prior,
            growth_pct=(current-prior)/prior*100 if metric not in RATIOS and prior>0 else None,
            difference_pp=current-prior if metric in RATIOS else None)
        for key,number in expected.items():
            actual=comparison.get(key)
            if (number is None and actual is not None) or (number is not None and
                (not finite(actual) or not math.isclose(actual,number,rel_tol=1e-12,abs_tol=1e-9))):
                raise FinancialClaimError('비교 계산과 원자료가 일치하지 않습니다.',**details)
        if previous.get('estimated') and '추정' not in sentence['text']:
            raise ValueError('XML 대체 재무 값의 추정 표시가 누락되었습니다.')
        entry=dict(current_ref=fact['id'],added_ref=previous['id'],metric=metric,
                   company=fact['company'],year=fact['year'],comparison_year=previous['year'],
                   report_type=fact['report_type'],basis=fact['values']['basis'],
                   reason='선택한 현재 근거의 검증된 comparison.ref 연결')
        if entry not in auto_links:auto_links.append(entry)


def _check_sentence(sentence, evidence, auto_links=None):
    lookup={e['id']:e for e in evidence}
    selected=[lookup[i] for i in sentence['refs'] if lookup[i]['kind']=='financial']
    text=sentence['text']
    for fact in selected:
        if not finite(fact['values'].get(fact.get('metric'))):raise ValueError('유효하지 않은 재무 근거입니다.')
        if fact.get('estimated') or fact.get('comparison',{}).get('estimated'):
            if '추정' not in text:raise ValueError('XML 대체 재무 값의 추정 표시가 누락되었습니다.')
    matches=[(m,'money') for m in MONEY.finditer(text) if any(m.groups())]
    matches += [(m,'percent') for m in PERCENT.finditer(text)]
    ordered=ordered_claims(text,matches,evidence)
    for match,mode in matches:
        prefix=scope_prefix(text[:match.start()])
        metric=claim_metric(text,match,mode,ordered)
        if metric=='unsupported':raise ValueError('해당 금융 지표의 정의와 일치하는 검증 재무 근거가 없습니다.')
        candidates=[f for f in selected if f['metric']==metric]
        named=[(prefix.rfind(c),c) for c in {e['company'] for e in evidence} if c in prefix]
        if named:candidates=[f for f in candidates if f['company']==max(named)[1]]
        years=re.findall(r'((?:19|20)\d{2})\s*년',prefix)
        relative=bool(re.search(r'(?:전년\s*(?:동기)?|직전\s*연도|지난해)\s*[(:：（]?\s*$',prefix))
        # A relative amount selects the previous fact through the current fact's
        # verified comparison link, never by accepting any value that happens to match.
        if relative:
            current=[f for f in candidates if f.get('comparison') and
                     (not years or f['year']==int(years[-1]))]
            previous_ids={f['comparison']['ref'] for f in current}
            if not previous_ids:
                raise ValueError('전년 수치의 현재·비교 재무 근거가 누락되었습니다.')
            _comparison_refs(sentence,current,lookup,auto_links,'전년 수치의 현재·비교 재무 근거가 누락되었습니다.')
            candidates=[lookup[i] for i in previous_ids if i in lookup]
        elif years:candidates=[f for f in candidates if f['year']==int(years[-1])]
        periods=list(re.finditer(r'[1-4]분기|반기|상반기|연간|사업보고서',prefix))
        if periods:
            period=periods[-1].group()
            kind={'1분기':'Q1','2분기':'H1','반기':'H1','상반기':'H1','3분기':'Q3','4분기':'FY','연간':'FY','사업보고서':'FY'}[period]
            candidates=[f for f in candidates if f['report_type']==kind]
            if period in ('2분기','4분기'):
                candidates=[f for f in candidates if f.get('value_type')=='quarterly']
        if re.search(r'단일\s*분기|당분기|분기\s*단일',prefix):
            candidates=[f for f in candidates if f.get('value_type')=='quarterly' or f['report_type']=='Q1']
        basis=list(re.finditer(r'연결|별도',prefix))
        if basis:candidates=[f for f in candidates if f['values']['basis']==('CFS' if basis[-1].group()=='연결' else 'OFS')]
        is_comparison=(mode=='percent' and (metric not in RATIOS or 'p' in match.group(2).lower() or '포인트' in match.group(2))) or (mode=='money' and bool(re.search(r'차이|증가액|감소액',prefix[-15:])))
        if is_comparison and re.search(r'전\s*분기|직전\s*분기',prefix):
            raise ValueError('전분기 비교는 전년 동기 비교 결과로 검증할 수 없습니다.')
        if is_comparison:
            candidates=[f for f in candidates if f.get('comparison')]
            # The cited predecessor is a calculation input, not a second current
            # claim. Resolve only explicit comparison edges, never a largest value.
            predecessors={f['comparison']['ref'] for f in candidates}
            candidates=[f for f in candidates if f['id'] not in predecessors]
        if len({(f['company'],f['year'],f['report_type'],f['values']['basis']) for f in candidates})!=1:
            raise FinancialClaimError('수치의 기업·기간·회계 기준이 인용한 재무 근거와 맞지 않거나 모호합니다.',
                claim=match.group(),metric=metric,mode=mode,
                candidate_ids=[f['id'] for f in candidates],
                selected_metric_ids=[f['id'] for f in selected if f['metric']==metric],
                stated_year=int(years[-1]) if years else None,
                stated_period=periods[-1].group() if periods else None,
                stated_basis=basis[-1].group() if basis else None)
        if mode=='money':
            amount=sum(float(v.replace(',',''))*scale for v,scale in zip(match.groups(),(1e12,1e8,1e4,1)) if v)
            precision=min(scale*10**(-len(v.split('.')[-1]) if '.' in v else 0) for v,scale in zip(match.groups(),(1e12,1e8,1e4,1)) if v)
            if re.search(r'(?:-|−|마이너스)\s*$',prefix) or re.search(r'영업손실\D*$',prefix):amount=-amount
            numbers=[f['values'][metric] for f in candidates]
            if re.search(r'차이|증가액|감소액',prefix[-15:]):
                numbers=[f.get('comparison',{}).get('difference') for f in candidates]
                _comparison_refs(sentence,candidates,lookup,auto_links,'금액 차이의 비교 근거가 누락되었습니다.')
                if '감소액' in prefix[-15:]:numbers=[-v for v in numbers]
        else:
            number=re.sub(r'\s','',match.group(1)).replace(',','').translate(str.maketrans({'−':'-','－':'-','＋':'+'}))
            amount=float(number)
            if re.search(r'마이너스\s*$',prefix):amount=-abs(amount)
            precision=10**(-len(number.split('.')[-1]) if '.' in number else 0)
            delta='p' in match.group(2).lower() or '포인트' in match.group(2)
            if delta or metric not in RATIOS:
                _comparison_refs(sentence,candidates,lookup,auto_links,'증감 비교에는 현재 값과 비교 값의 재무 ID를 모두 연결해야 합니다.')
            numbers=[f.get('comparison',{}).get('difference_pp' if delta else 'growth_pct') for f in candidates] if delta or metric not in RATIOS else [f['values'][metric] for f in candidates]
            # A positive ratio level followed by "하락" remains a positive level.
            # Direction applies only to changes, not to 7.7% as the current margin.
            if is_comparison:
                suffix=ordered[match.start()][1] if match.start() in ordered else text[match.end():match.end()+12]
                decreasing=bool(re.search(r'감소|하락|축소',suffix))
                increasing=bool(re.search(r'증가|상승|확대|성장',suffix))
                if decreasing:
                    numbers=[v for v in numbers if finite(v) and v<=0]
                    if amount>=0:numbers=[-v for v in numbers]
                elif increasing:
                    numbers=[v for v in numbers if finite(v) and v>=0]
        if not any(finite(v) and abs(v-amount)<=precision/2+1e-6 for v in numbers):
            raise FinancialClaimError('수치가 인용한 재무 값 또는 검증된 비교 결과와 일치하지 않습니다.',
                claim=match.group(),metric=metric,mode=mode,claimed_value=amount,
                expected_values=numbers,tolerance=precision/2+1e-6,
                candidate_ids=[f['id'] for f in candidates],relative_period=relative)

def validate_financial(value, evidence):
    if not value['sentences']:return value
    lookup={e['id']:e for e in evidence}
    kinds={lookup[i]['kind'] for s in value['sentences'] for i in s['refs']}
    if not {'financial','filing'}<=kinds:
        raise CitationValidationError('new2 인사이트 문단에는 재무·공시 근거가 모두 필요합니다.',
            [dict(error_code='DUAL_EVIDENCE_REQUIRED',detail='두 종류의 의미 있는 근거가 부족하면 빈 sentences와 이유를 반환하세요.')])
    issues=[];pending=[]
    for index,sentence in enumerate(value['sentences'],1):
        links=[]
        try:
            _check_sentence(sentence,evidence,auto_links=links)
            pending.append((sentence,links))
        except ValueError as error:
            issues.append(dict(error_code='FINANCIAL_SCOPE_OR_VALUE_MISMATCH',sentence_index=index,detail=str(error),**getattr(error,'details',{})))
    if issues:raise CitationValidationError(issues[0]['detail'],issues)
    for sentence,links in pending:
        if not links:continue
        sentence.setdefault('llm_refs',list(sentence['refs']))
        sentence['refs']=list(dict.fromkeys(sentence['refs']+[link['added_ref'] for link in links]))
        sentence['auto_linked_financial_refs']=sentence.get('auto_linked_financial_refs',[])+links
    return value
