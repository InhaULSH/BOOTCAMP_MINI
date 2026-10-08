"""Claim-specific evidence grading; quotes always come from the actual input."""
import hashlib
import re
import os

VERSION = 'claim-evidence-v4-user-40-30'
INSTRUCTION = '''[문장별 공시 근거 선택]
요약 문장 작성과 함께 해당 요약 문장을 뒷받침하는 각주 근거 문장 선택을 함께 수행하세요.
각 문장의 핵심 사실을 입력 공시가 뒷받침하는지 확인하고, 그 문장을 설명하는 데 필요한 근거만 선택하세요.

[허용되는 근거]
- 이번 입력 evidence의 kind=filing 청크만 각주 근거로 사용하세요.
- 각주에는 입력 passages에 있는 20자 이상의 자연어 문장을 선택하세요.
- 표의 셀, 수치 나열, 금액·비율 등 정량 정보는 각주 문장으로 절대 선택하지 마세요.
- kind=financial 자료는 분석에 활용할 수 있으나 refs와 assessments에는 넣지 마세요.
- 외부 자료나 입력에 없는 청크를 인용하지 마세요.
- 원문 문장을 고치거나 원문 위치를 만들어내지 마세요.

[평가 등급]
각 요약 문장에 대해 후보 근거를 0-4점으로 평가하세요.
0은 부합하지 않음, 1은 약함, 2는 부분적, 3은 충분함, 4는 매우 충분함입니다.

F, 사실 부합도 — 40%
선택한 원문이 요약 문장의 사실을 직접 뒷받침하는 정도입니다.
같은 키워드가 등장한다는 이유만으로 높은 점수를 주지 마세요.
주체·행위·방향·조건·원인에 관한 주장이 원문과 맞는지 확인하세요.

U, 사업 이해에 대한 도움 — 30%
선택한 원문이 해당 키워드 또는 분석 대상의 실제 사업 현황과 변화 방향을 초보 사용자가 구체적으로 이해하는 데 도움이 되는 정도입니다.
표현이 쉽거나 흥미롭다는 이유만으로 높은 점수를 주지 마세요.
사업적 의미가 없는 반복 문구나 작성 기준 설명은 낮게 평가하세요.

C, 명확성 — 20%
주체·제품·행위·조건이 명확하고, 원문 맥락을 보존하여 오해 없이 설명할 수 있는 정도입니다.

T, 시점 적합성 — 10%
요약의 시점과 실제 사건의 시점이 맞고, 현황·계획·진행·완료를 정확히 구분하는 정도입니다.

[감점과 적격 조건]
관련 없는 내용과 불필요한 반복에 대해 각각 평가하세요.
irrelevant_content와 redundancy는 none=0, some=5, substantial=10점 감점입니다.
사실 해석에 필요한 조건·위험·단위·비교 기준은 불필요한 정보로 취급하지 마세요.

점수 = max(0, 25*(0.4F+0.3U+0.2C+0.1T) - 두 감점)

F>=3, C>=3, 최종 점수>=75인 근거만 선택하세요.
이 기준을 충족하더라도 요약 문장의 주요 주장을 뒷받침하지 못하면 근거로 사용하지 마세요.

[근거 연결]
- assessments.id와 refs에는 청크 ID(tN)를 사용하세요.
- passage_ids에는 입력에서 제공된 문장 ID(tN-pM)만 사용하세요.
- 필요한 인접 문장을 함께 선택하여 주체와 조건을 보존하세요.
- 동일 청크의 여러 문장은 하나의 근거 청크로 취급하세요.
- 각 문장에 적격 공시 근거를 최소 1개 연결하세요.
- 여러 기업의 공통 동향을 설명한다면 그 기업들과 공통 동향을 실제로 뒷받침하는 근거를 선택하세요.
- 하나의 근거로 부족하면 추가 근거를 선택하되, 관계없는 근거로 개수를 채우지 마세요.
- 근거가 뒷받침하는 범위보다 문장이 넓으면 문장을 좁히거나 생략하세요.

[출력과 근거 부족]
- 제공된 JSON Schema를 따르세요.
- 평가 등급과 이유는 내부 검증용으로 반환하고 고객용 문장에는 표시하지 마세요.
- 적격 근거가 없는 문장은 생략하세요.
- 충분한 설명을 만들 수 없으면 sentences=[]와 insufficient_reason을 반환하세요.
- 근거 부족을 모호한 종합 문장으로 숨기지 마세요.'''

def natural_passage(value):
    """Conservative prose-only citation gate; dates/product names remain usable."""
    value=value.strip()
    if re.search(r'(?<![A-Za-z0-9])\d',value):return False
    if len(value)<20 or re.search(r'[|\t]|\d[\d,.]*\s*(?:%|퍼센트|억원|억\s*원|조\s*원|만원|천원|백만원|원(?:\s|$)|배(?:\s|$)|톤|만개|천개)',value):return False
    if re.search(r'(?<![A-Za-z])\d[\d,.]*\s*(?:억|조)(?:\s|$)',value):return False
    if len(re.findall(r'[가-힣]',value))>=10:
        return bool(re.search(r'(?:다[.!?]?$|하며|하여|하고|이며|되는|위해|따라|있어|합니다|습니다)',value))
    return len(re.findall(r'[A-Za-z]+',value))>=5 and bool(re.search(r'[.!?]$',value))

def passages(text):
    """Stable input offsets, including table lines, without modifying original text."""
    result=[]
    for match in re.finditer(r'[^\n]+', text):
        for sentence in re.finditer(r'.+?(?:[.!?](?=\s|$)|$)', match.group()):
            value=sentence.group(); left=len(value)-len(value.lstrip())
            start=match.start()+sentence.start()+left; end=match.start()+sentence.end()
            while end>start and text[end-1].isspace():end-=1
            if end>start and natural_passage(text[start:end]):result.append(dict(start=start,end=end,text=text[start:end]))
    return result

def bounded_rows(rows,years):
    """Round-robin company coverage; full chunks, bounded request characters."""
    from itertools import zip_longest
    groups={}
    for row in rows:groups.setdefault(row['company'],[]).append(row)
    def priority(r):
        annual=r['period'].endswith('-12')
        return (0 if annual and r['year']==years[-1] else 1 if annual else 2,-r['year'],r['period'],r['chunk_id'])
    groups=[sorted(g,key=priority) for g in groups.values()]
    budget=max(4000,int(os.getenv('CITATION_INPUT_CHAR_BUDGET','48000')))
    used=0;result=[];seen=set()
    for batch in zip_longest(*groups):
        for row in batch:
            if row is None or row['chunk_id'] in seen:continue
            if used+len(row['text'])>budget:continue
            used+=len(row['text']);seen.add(row['chunk_id']);result.append(row)
    return result

def schema(llm, minimum, maximum, evidence):
    grade=llm.object_schema({k:dict(type='integer',minimum=0,maximum=4) for k in ('F','U','C','T')})
    chunk_id=dict(type='string',enum=[e['id'] for e in evidence if e['kind']=='filing'],description='청크 ID tN. 문장 ID tN-pM은 사용하지 않음')
    passage_id=dict(type='string',enum=[p['id'] for e in evidence if e['kind']=='filing' for p in e['passages']],description='해당 청크 내부 원문 문장 ID tN-pM')
    assessment=llm.object_schema({'id':chunk_id,'grades':grade,
        'suitable':dict(type='boolean'),'reason':llm.TEXT,
        'irrelevant_content':dict(type='string',enum=['none','some','substantial']),
        'redundancy':dict(type='string',enum=['none','some','substantial']),
        'passage_ids':dict(type='array',items=passage_id,minItems=1)})
    item=llm.object_schema({'text':llm.TEXT,'refs':dict(type='array',items=dict(type='string',enum=[e['id'] for e in evidence if e['kind']=='filing'],description='자연어 공시 청크 ID tN만 사용. 재무 ID와 문장 ID 금지')),
        'assessments':dict(type='array',items=assessment)})
    array=dict(type='array',items=item)
    if maximum:array['maxItems']=maximum
    return llm.object_schema({'sentences':array,'insufficient_reason':llm.TEXT})

def validate(value,evidence,minimum,maximum):
    items=value.get('sentences') if isinstance(value,dict) else None
    if not isinstance(items,list):raise ValueError('문장 형식 오류')
    if not items:
        if not value.get('insufficient_reason'):raise ValueError('근거 부족 이유가 없습니다.')
        return value
    if len(items)<minimum or (maximum and len(items)>maximum):raise ValueError('문장 수 오류')
    lookup={e['id']:e for e in evidence}
    for item in items:
        if not isinstance(item.get('text'),str) or not item['text'].strip():raise ValueError('빈 요약 문장')
        refs=item.get('refs',[])
        if not isinstance(refs,list) or any(i not in lookup or lookup[i]['kind']!='filing' for i in refs):raise ValueError('입력 근거 ID 오류')
        if len(refs)!=len(set(refs)):raise ValueError('refs에 동일 근거 ID가 반복되었습니다. 동일 청크의 여러 문장은 1개 근거입니다. 적격 공시 근거가 뒷받침하는 문장으로 다시 작성하거나 sentences=[]와 insufficient_reason을 반환하세요.')
        eligible={}; seen=set()
        for a in item.get('assessments',[]):
            e=lookup.get(a.get('id'))
            if not e or e['kind']!='filing' or e['id'] in seen:raise ValueError('공시 후보 ID 오류')
            seen.add(e['id']);g=a['grades']
            if any(type(g.get(k)) is not int or not 0<=g[k]<=4 for k in ('F','U','C','T')):raise ValueError('평가 등급 오류')
            penalty={'none':0,'some':5,'substantial':10}
            if any(a.get(k) not in penalty for k in ('irrelevant_content','redundancy')):raise ValueError('감점 등급 오류')
            score=max(0,25*(.4*g['F']+.3*g['U']+.2*g['C']+.1*g['T'])-sum(penalty[a[k]] for k in ('irrelevant_content','redundancy')))
            valid={p['id']:p for p in e['passages']}
            chosen=a.get('passage_ids',[])
            if not chosen or len(set(chosen))!=len(chosen) or any(i not in valid for i in chosen):raise ValueError('입력에 없는 원문 문장 ID')
            if any(not natural_passage(valid[i]['text']) for i in chosen):raise ValueError('근거는 20자 이상의 자연어 문장만 허용합니다. 수치·표 문장은 제외하세요.')
            a['passages']=[dict(start=valid[i]['start'],end=valid[i]['end']) for i in chosen]
            a['score']=round(score,2)
            if a.get('suitable') is True and g['F']>=3 and g['C']>=3 and score>=75:eligible[e['id']]=a
        chosen=[i for i in refs if lookup[i]['kind']=='filing']
        if not chosen:raise ValueError('문장마다 적격 자연어 공시 근거가 최소 1개 필요합니다. 근거가 없으면 해당 문장을 생략하세요.')
        if any(i not in eligible for i in chosen):raise ValueError('선택 근거의 점수 또는 적격 기준 미달')
        item['refs']=sorted(chosen,key=lambda i:eligible[i]['score'],reverse=True)+[i for i in refs if lookup[i]['kind']!='filing']
    return value

def snapshot(evidence):
    import json
    return dict(version=VERSION,input_sha256=hashlib.sha256(json.dumps(evidence,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),evidence=evidence)
