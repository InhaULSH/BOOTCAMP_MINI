"""Period/chunk -> annual evidence -> company/industry report, with resumable caches."""
import hashlib
import json
from . import llm
from .collect import save_json

CHARS = 16000
SUMMARY_SCHEMA = llm.object_schema({'items': {'type': 'array', 'minItems': 1, 'maxItems': 3 if llm.PROVIDER == 'ollama' else 6,
    'items': llm.object_schema({'text': {'type': 'string', 'maxLength': 350 if llm.PROVIDER == 'ollama' else 650},
                              'evidence_ids': llm.REFS})}})
INSTRUCTION = llm.SYSTEM.split('summary:')[0] + '''
이번 작업은 최종 보고서가 아니라 입력 묶음의 근거 요약이다. items만 반환한다.
수요·제품·투자·위험의 중요한 사실과 변화, 회사 전망/계획/실행의 구분을 보존한다.
각 text는 650자 이내로 기간을 명시하고 사실과 가능한 해석을 구분한다.
각 항목에 그 내용을 지지하는 입력 evidence_ids를 넣는다. 다른 기간을 추정하지 않는다.
연간 종합에서는 분기별 변화와 반대 증거를 보존하고 연말 내용으로 덮어쓰지 않는다.
자료가 부족하면 부족하다고 명시한다. 입력 요약은 원문 자체가 아니며 검증된 실적으로 격상하지 않는다.
'''


if llm.PROVIDER == 'ollama':
    INSTRUCTION += '\n로컬 실행에서는 최대 3개 항목, 항목당 350자 이내로 핵심 변화와 불확실성을 보존한다.'


def validate(value, evidence):
    ids = {e['id'] for e in evidence}
    items = value.get('items') if isinstance(value, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= SUMMARY_SCHEMA['properties']['items']['maxItems']:
        raise ValueError('중간 요약 개수 오류')
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not 1 <= len(item['text']) <= SUMMARY_SCHEMA['properties']['items']['items']['properties']['text']['maxLength']:
            raise ValueError('중간 요약 길이 오류')
        refs = item.get('evidence_ids')
        if not isinstance(refs, list) or not 1 <= len(refs) <= 6 or any(not isinstance(r, str) or r not in ids for r in refs):
            raise ValueError('중간 요약 근거 오류')
    return value


def batches(evidence, limit=CHARS):
    """Bound serialized characters, preserving every selected passage and date."""
    batch, size = [], 0
    for e in evidence:
        # Existing retrieval chunks are <=1050 chars; further split custom/long inputs.
        text = e.get('text')
        parts = [text[i:i+1000] for i in range(0, len(text), 1000)] if text else [None]
        for i, part in enumerate(parts):
            item = dict(e)
            if part is not None:
                item['text'] = part
            if len(parts) > 1:
                item['parent_id'] = e['id']
                item['id'] = e['id'] + f'-part-{i}'
            length = len(json.dumps(item, ensure_ascii=False))
            if batch and size + length > limit:
                yield batch
                batch, size = [], 0
            batch.append(item)
            size += length
    if batch:
        yield batch


def summarize(evidence, label, force=False):
    context = dict(task=label, evidence=evidence)
    digest = hashlib.sha256(json.dumps([llm.CACHE_PROFILE, llm.MODEL, llm.PROMPT_VERSION, INSTRUCTION,
        SUMMARY_SCHEMA, context], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    path = llm.DATA / 'llm_cache' / 'chunks' / (digest + '.json')
    if path.exists() and not force:
        result = json.loads(path.read_text(encoding='utf-8'))
        validate(result['report'], evidence)
    else:
        try:
            result = llm.request_report(context, evidence, schema=SUMMARY_SCHEMA,
                                       instruction=INSTRUCTION, validator=validate)
        except llm.InputTooLarge:
            if len(evidence) < 2:
                raise
            middle = len(evidence)//2
            return summarize(evidence[:middle], label, force) + summarize(evidence[middle:], label, force)
        result['inputs'] = context
        save_json(path, result)
    year = evidence[0]['year']
    return [dict(id=f"{evidence[0]['id'].split('-')[0]}-summary-{digest[:20]}-{i}", year=year,
                 kind='공시 기반 중간 요약·원문 아님', text=item['text'],
                 source_ids=item['evidence_ids']) for i, item in enumerate(result['report']['items'])]


def reduce_company(context, force=False):
    annual = []
    raw = context['evidence']
    for year in llm.YEARS:
        summaries = []
        periods = sorted({e['period'] for e in raw if e['year'] == year and 'period' in e})
        for period in periods:
            entries = [e for e in raw if e.get('period') == period]
            for index, batch in enumerate(batches(entries)):
                label = f"{context['company']} {period} 문단 묶음 {index+1}"
                summaries.extend(summarize(batch, label, force))
                print(label + ' 요약 완료', flush=True)
        # Hierarchical reduction also bounds atypically large intermediate outputs.
        while len(json.dumps(summaries, ensure_ascii=False)) > CHARS * 2:
            reduced = []
            for batch in batches(summaries):
                reduced.extend(summarize(batch, f"{context['company']} {year} 중간 통합", force))
            if len(json.dumps(reduced, ensure_ascii=False)) >= len(json.dumps(summaries, ensure_ascii=False)):
                raise RuntimeError('중간 요약이 충분히 축약되지 않았습니다. 저장된 묶음부터 재실행하세요.')
            summaries = reduced
        if summaries:
            annual.extend(summarize(summaries, f"{context['company']} {year} 분기 변화 종합", force))
    financials = [e for e in raw if 'values' in e]
    return dict(context, evidence=annual+financials,
                input_kind='기업·기간별 문단 요약을 연간 종합한 자료. source_ids는 내부 추적용이며 최종 인용은 입력 id 사용')
