"""Claim-specific evidence grading; quotes always come from the actual input."""
import hashlib
import re
import os

VERSION = 'claim-evidence-v3-single-prose'
INSTRUCTION = '''[문장별 공시 근거 선택]
기존 분석 지시를 유지하면서 요약과 근거 선택을 동시에 수행하세요.
각주에는 20자 이상의 자연어 설명 문장만 선택하세요. 표의 셀·수치 나열·금액·비율 등 정량 수치는 근거 문장으로 선택하지 않습니다. 재무 데이터는 분석에 활용하되 고객은 수치를 그래프에서 확인합니다.
공시 근거는 이번 입력 evidence의 kind=filing 청크에 한정합니다. 외부 지식이나 입력하지 않은 청크를 인용하지 마세요.
각 요약 문장을 뒷받침하는 후보 청크들을 문장별로 평가하세요. grades는 0(부합하지 않음), 1(약함), 2(부분적), 3(충분함), 4(매우 충분함)입니다.
F: 이 문장의 사실을 직접 뒷받침하는 정도(50%), U: 초보 투자자가 사업 신호를 이해하는 데 도움되는 정도(20%), C: 주어·제품·행위·조건이 명확한 정도(20%), T: 요약의 시점과 실제 사건 시점이 맞는 정도(10%).
보고서 연도를 과거 연구개발의 발생 연도로 취급하지 말고 계획·전망·진행·완료를 구별하세요. 기업 자체 공장과 공급업체 생산지를 구별하세요. 여러 기업의 공통 흐름이나 원인을 근거 없이 추론하지 마세요.
입력에 있으나 관련 없는 문구, 반복 문구는 irrelevant_content/redundancy로 none=0, some=5, substantial=10점을 각각 감점합니다. 필요한 조건·위험·단위·계산 기준은 불필요한 정보가 아닙니다.
점수 = 25*(0.5F+0.2U+0.2C+0.1T) - 두 감점. F>=3, C>=3, 최종 점수>=75이며 기업·사업·시점·사건 단계가 맞는 근거만 선택합니다.
평가한 후보는 assessments에 기록하세요. 각 후보의 passage_ids는 입력 청크의 passages에 주어진 문장 id만 선택합니다. 문자 위치를 직접 계산하지 말고, 필요한 인접 문장도 묶어 주어와 조건을 보존하세요. 원문의 문장을 고쳐 인용하지 마세요.
assessments.id와 refs에는 청크 ID(tN)를 쓰고 passage_ids에만 문장 ID(tN-pM)를 씁니다. financial ID(fN)를 assessments에 쓰지 마세요. 각 요약 문장 refs에 적격 공시 근거를 최소 1개 선택합니다. 하나의 근거만 있어도 그 근거가 직접 뒷받침하는 범위에서 인사이트를 생성하세요. 해당 문장의 주요 사실 전체를 뒷받침하는, 점수가 높은 근거부터 선택하세요. 1개로 충분하지 않으면 더 선택하되 고객에게 충분한 신호를 전달하는 최소한의 개수를 스스로 판단하세요. 같은 사실의 불필요한 반복이나 관계없는 근거를 채우지 마세요. 동일 청크의 여러 문장은 하나의 근거 청크로 취급하세요.
재무 근거 kind=financial은 분석용 입력이며 refs에 넣지 마세요. 각주는 자연어 공시 문장만 사용합니다.
적격 공시 근거가 하나도 없는 문장은 범위를 수정하거나 생략하세요. 충분한 문장을 전혀 만들 수 없다면 sentences=[]와 insufficient_reason을 반환하세요. 근거 부족을 숨기지 마세요.
grades와 평가 이유는 내부 검증용으로만 반환하며 고객용 요약에 점수나 주요 키워드로 선정한 이유를 표시하지 마세요.'''

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
            score=max(0,25*(.5*g['F']+.2*g['U']+.2*g['C']+.1*g['T'])-sum(penalty[a[k]] for k in ('irrelevant_content','redundancy')))
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
