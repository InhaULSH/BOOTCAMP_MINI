"""MVP transport/provenance checks; semantic scores are advisory, not approval."""
import copy
import logging
import os
VERSION='mvp-validation-v1'

def enabled():
    return os.getenv('INSIGHT_VALIDATION_MODE','mvp').strip().lower()!='strict'

def validate(value,evidence,allow_financial=False):
    from .citation_selection import CitationValidationError
    def fail(message):
        raise CitationValidationError(message,[dict(error_code='MVP_RESPONSE_OR_SOURCE_INVALID',detail=message)])
    working=copy.deepcopy(value)
    if not isinstance(working,dict) or not isinstance(working.get('sentences'),list):fail('문장 형식 오류')
    lookup={e['id']:e for e in evidence};warnings=[];items=[]
    for index,item in enumerate(working['sentences'],1):
        if not isinstance(item,dict) or not isinstance(item.get('text'),str) or not item['text'].strip():fail('빈 문장 또는 문장 형식 오류')
        refs=item.get('refs')
        if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in lookup for ref in refs):fail('입력에 없는 근거 ID')
        refs=list(dict.fromkeys(refs))
        refs=[ref for ref in refs if lookup[ref]['kind']=='filing' or (allow_financial and lookup[ref]['kind']=='financial')]
        if not refs:fail('문장을 뒷받침할 입력 근거가 없습니다.')
        assessments=item.get('assessments',[])
        assessments=assessments if isinstance(assessments,list) else []
        normalized=[];kept=[]
        for ref in refs:
            source=lookup[ref]
            if source['kind']=='financial':kept.append(ref);continue
            passages={p['id']:p for p in source.get('passages',[]) if isinstance(p.get('text'),str) and isinstance(p.get('start'),int) and isinstance(p.get('end'),int) and 0<=p['start']<p['end']}
            a=next((a for a in assessments if isinstance(a,dict) and a.get('id')==ref),None)
            chosen=a.get('passage_ids',[]) if a else []
            chosen=chosen if isinstance(chosen,list) else []
            valid=list(dict.fromkeys(i for i in chosen if isinstance(i,str) and i in passages))
            if not valid:
                # Do not invent relevance grades or select a new quote for the model.
                warnings.append(dict(sentence_index=index,ref=ref,reason='원문 위치 평가 누락: 표시 각주에서 제외'))
                continue
            normalized.append(dict(a,id=ref,passage_ids=valid,
                passages=[dict(start=passages[i]['start'],end=passages[i]['end']) for i in valid],
                score=None,validation_status='source_location_only'))
            kept.append(ref)
        if not kept:
            warnings.append(dict(sentence_index=index,reason='표시 가능한 원문 위치가 없어 문장 생략'))
            continue
        item['refs']=kept;item['assessments']=normalized;items.append(item)
    working['sentences']=items
    working['insufficient_reason']=working.get('insufficient_reason') if isinstance(working.get('insufficient_reason'),str) else ''
    if not items and not working['insufficient_reason']:working['insufficient_reason']='현재 자료에서 출처를 연결할 수 있는 설명을 충분히 확보하지 못했습니다.'
    working['validation_mode']='mvp'
    if warnings:working['validation_warnings']=warnings
    value.clear();value.update(working)
    return value
