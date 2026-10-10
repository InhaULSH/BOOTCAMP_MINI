"""Bounded new2 fact extraction; original passage IDs remain the only citations."""
VERSION = 'insight-plan-v1'
INSTRUCTION = '''[공시 근거 사실 정리]
사용자에게 보여줄 최종 인사이트를 작성하지 마세요.
입력 공시에서 직접 확인되는 중요한 사실을 max_facts 이내로 정리하세요.
산업 분석은 최대 10개, 기업 분석과 키워드 설명은 최대 5개입니다. 개수를 억지로 채우지 마세요.
수요·제품·고객·생산·수주·투자·수익성·위험과 관련된 사실을 우선하세요.
각 fact에는 중심 사실 하나, 실행 상태 state, 원문 support를 연결하세요.
state는 current(현황), planned(계획), ongoing(진행), completed(완료), uncertain(확인 불가) 중 원문에 맞게 고르세요.
support.id는 공시 청크 ID, passage_ids는 해당 청크의 입력 원문 문장 ID입니다.
기업·보고서·연도·위치는 ID로 코드가 연결하므로 추측하거나 새로 만들지 마세요.
주체나 조건을 이해하는 데 필요한 인접 원문도 함께 선택하세요.
일반적인 용어 설명이나 단어 등장 자체를 실제 사업 활동의 증거로 취급하지 마세요.
키워드 설명에서는 입력 공시에서 사용된 용어의 뜻과 관련 사업 활동을 함께 정리하세요.
명시적인 변화 또는 비교 가능한 전후 근거가 없으면 증가·축소·전환했다고 판단하지 마세요.
한 기업의 사실을 산업 전체로 확대하지 마세요. 계획·진행·완료를 바꾸지 마세요.
확인되지 않는 원인·성과·전망을 추가하지 마세요.
인용 근거는 kind=filing의 passages만 허용합니다. 문맥 보충이나 재무 행은 인용 ID가 아닙니다.
설명할 사실이 없으면 facts=[]와 구체적인 insufficient_reason을 반환하세요.
이 결과는 잠정적인 사실 정리이며 최종 문장은 별도의 근거 검증을 받아야 합니다.'''

DRAFT_INSTRUCTION = '''[new2: 정리된 사실로 최종 인사이트 작성]
evidence_plan은 원문에 연결된 잠정적인 사실 정리입니다. 최종 문장을 원문과 다시 대조하세요.
정리된 사실의 주체·시점·조건·실행 상태를 보존하여 핵심 사업 신호를 먼저 설명하세요.
모든 사실을 나열할 필요는 없습니다. 사업 이해에 중요한 정도와 근거의 직접성을 판단해 핵심 사실을 선택하세요.
같은 흐름을 뒷받침하는 사실은 의미를 보존하여 요약하되 공시에서 확인되지 않는 공통 원인이나 관계를 만들지 마세요.
추가 문장은 근거가 있는 배경·기업별 대응·조건·위험을 새롭게 전달할 때만 작성하세요.
같은 사실을 표현만 바꾸어 반복하거나 확인되지 않는 원인·전망을 추가하지 마세요.
각주에는 evidence_plan.support에 선택된 청크와 원문 문장만 사용하세요.
정리된 사실보다 설명 범위가 넓어지면 문장을 좁히거나 생략하세요.
최종 문장과 선택 원문의 관계에 대해 기존 F/U/C/T 평가와 감점을 다시 수행하세요.
사실 정리 단계의 판단을 최종 문장에 그대로 적용하거나 등급만 높여 통과시키지 마세요.
적격 근거로 설명할 수 없으면 sentences=[]와 구체적인 insufficient_reason을 반환하세요.'''


def schema(llm, evidence, limit):
    filings = [e for e in evidence if e['kind'] == 'filing']
    support = llm.object_schema({
        'id': dict(type='string', enum=[e['id'] for e in filings]),
        'passage_ids': dict(type='array', minItems=1, items=dict(type='string',
            enum=[p['id'] for e in filings for p in e['passages']]))})
    fact = llm.object_schema({'fact': llm.TEXT,
        'state': dict(type='string', enum=['current', 'planned', 'ongoing', 'completed', 'uncertain']),
        'support': dict(type='array', minItems=1, items=support)})
    return llm.object_schema({'facts': dict(type='array', maxItems=limit, items=fact),
        'insufficient_reason': llm.TEXT})


def validate(value, evidence, limit=5):
    from .citation_selection import CitationValidationError, natural_passage
    def fail(message, **details):
        raise CitationValidationError(message, [dict(error_code='INVALID_EVIDENCE_PLAN', **details)])
    if not isinstance(value, dict) or not isinstance(value.get('facts'), list):
        fail('근거 사실 정리 형식 오류')
    reason = value.get('insufficient_reason')
    if not isinstance(reason, str): fail('근거 사실 정리의 부족 사유 형식 오류')
    if len(value['facts']) > limit: fail(f'근거 사실은 최대 {limit}개입니다.',maximum=limit,actual=len(value['facts']))
    if not value['facts'] and not reason.strip(): fail('근거 사실이 없으면 부족 사유가 필요합니다.')
    lookup = {e['id']: e for e in evidence if e['kind'] == 'filing'}
    facts = []
    for index, fact in enumerate(value['facts'], 1):
        if not isinstance(fact, dict) or not isinstance(fact.get('fact'), str) or not fact['fact'].strip():
            fail('빈 근거 사실', fact_index=index)
        if fact.get('state') not in ('current', 'planned', 'ongoing', 'completed', 'uncertain'):
            fail('근거 사실의 실행 상태 오류', fact_index=index)
        support = fact.get('support')
        if not isinstance(support, list) or not support: fail('근거 사실에 원문이 필요합니다.', fact_index=index)
        seen = set(); sources = []
        for source in support:
            eid = source.get('id') if isinstance(source, dict) else None
            if not isinstance(eid, str) or eid not in lookup or eid in seen:
                fail('근거 사실의 입력 청크 ID 오류', fact_index=index)
            seen.add(eid); entry = lookup[eid]
            passages = {p['id']: p for p in entry['passages']}
            ids = source.get('passage_ids')
            if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in passages for i in ids)
                    or len(ids) != len(set(ids))):
                fail('근거 사실의 입력 원문 문장 ID 오류', fact_index=index, ref=eid)
            if any(not natural_passage(passages[i]['text']) for i in ids):
                fail('근거 사실에 적격 자연어 원문이 필요합니다.', fact_index=index, ref=eid)
            # Resolve provenance in code, never trust model-created metadata or offsets.
            sources.append(dict(id=eid, passage_ids=ids,
                company=entry.get('company'), year=entry.get('year'), period=entry.get('period'),
                chunk_id=entry.get('chunk_id')))
        facts.append(dict(fact=fact['fact'].strip(), state=fact['state'], support=sources))
    return dict(facts=facts, insufficient_reason=reason)


def validate_final(value, plan):
    from .citation_selection import CitationValidationError
    allowed = {}
    for fact in plan['facts']:
        for source in fact['support']:
            allowed.setdefault(source['id'], set()).update(source['passage_ids'])
    issues = []
    for index, sentence in enumerate(value['sentences'], 1):
        for assessment in sentence['assessments']:
            if not set(assessment['passage_ids']) <= allowed.get(assessment['id'], set()):
                issues.append(dict(error_code='UNPLANNED_PASSAGE', sentence_index=index, ref=assessment['id']))
    if issues: raise CitationValidationError('사실 정리에 없는 원문이 최종 근거로 선택되었습니다.', issues)
    return value
