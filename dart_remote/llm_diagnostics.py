"""Private validation records, shared by local and deployed Gemini clients."""
import hashlib
import json
import logging
import uuid
from . import artifacts

REPAIR_TASK='''검증 오류를 수정한 전체 JSON을 반환하세요. issues의 문장 번호·근거 ID·실제 계산 점수·미달 조건을 확인하세요.
점수를 통과시키기 위해 평가 등급만 높이지 마세요. 최종 문장과 실제 원문의 관계를 다시 평가하세요.
원문이 일부 주장만 뒷받침하면 문장을 좁히거나 더 직접적인 입력 원문으로 교체하세요.
문장이나 근거가 바뀌면 평가도 다시 수행하세요. 부적격 근거를 제거할 때 남은 근거가 모든 주요 주장을 뒷받침해야 합니다.
sentences 배열의 각 항목은 요약 1문장입니다. 지시된 문장 수와 적격 근거 조건을 함께 지키세요.
문장 수를 채우기 위해 내용을 만들어내거나 반복하지 마세요. 추가 문장은 별도 근거가 있는 배경·조건·위험만 허용합니다.
필요한 문장을 근거로 뒷받침할 수 없다면 sentences=[]와 구체적인 insufficient_reason을 반환하세요.
입력 밖 근거나 원문 위치를 만들지 말고 제공된 JSON Schema와 입력 근거 ID를 따르세요.'''

def repair_task(schema):
    if 'sentences' in schema.get('properties',{}):return REPAIR_TASK
    return '검증 오류를 수정한 전체 JSON을 반환하세요. 제공된 JSON Schema와 입력 근거 ID를 따르세요.'

def record_validation(error,finish_reason,response,evidence,context,schema,repair=False):
    try:
        parsed=json.loads(response)
        sentences=parsed.get('sentences') if isinstance(parsed,dict) else None
        actual=len(sentences) if isinstance(sentences,list) else None
        facts=parsed.get('facts') if isinstance(parsed,dict) else None
        actual_facts=len(facts) if isinstance(facts,list) else None
    except (ValueError,TypeError):actual=None;actual_facts=None
    array=schema.get('properties',{}).get('sentences',{})
    alternatives=array.get('anyOf',[])
    minimum=next((a['minItems'] for a in alternatives if 'minItems' in a),None)
    scope=dict(sector=context.get('sector_name'),company=context.get('company'),keyword=context.get('keyword'),
               function='keyword' if context.get('keyword') else 'company' if context.get('company') else 'insight')
    diagnostic=dict(error=str(error),finish_reason=finish_reason,response=response,
        issues=getattr(error,'issues',[dict(error_code='RESPONSE_VALIDATION_ERROR',detail=str(error))]),
        allowed_ids=[dict(id=e['id'],year=e.get('year')) for e in evidence],
        stage=context.get('generation_stage','single'),prompt_version=context.get('prompt_version'),
        actual_fact_count=actual_facts,maximum_facts=schema.get('properties',{}).get('facts',{}).get('maxItems'),
        scope=scope,actual_sentence_count=actual,minimum_sentences=minimum,maximum_sentences=array.get('maxItems'),
        attempt=2 if repair else 1,rule='JSON Schema·문장 수·입력 근거와 점수 검증')
    name=hashlib.sha256(json.dumps(diagnostic,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    path=artifacts.ROOT/'llm'/'llm_errors'/(name+'.json')
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary.write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.chmod(0o600);temporary.replace(path)
    except OSError:
        logging.warning('Gemini validation diagnostic could not be saved; diagnostic_id=%s',name)
    finally:
        try:temporary.unlink(missing_ok=True)
        except OSError:pass
    logging.warning('Gemini validation failed: %s; sector=%s company=%s keyword=%s; sentences=%s allowed=%s-%s; attempt=%s; error=%s; diagnostic_id=%s',
        type(error).__name__,scope['sector'],scope['company'] or '-',scope['keyword'] or '-',actual,minimum,array.get('maxItems'),diagnostic['attempt'],str(error),name)
    return diagnostic
