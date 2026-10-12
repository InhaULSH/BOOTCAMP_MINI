"""Dual financial/filing references only for new2 industry/company calls."""
from . import citation_selection as base
from .financial_evidence import validate_financial
import copy
VERSION = 'claim-evidence-new2-v7-mvp-default'
INSTRUCTION = """[목적]

최종 문장 작성과 그 문장을 뒷받침하는 근거 선택을 같은 호출에서 수행하세요.

문장에 포함된 재무 주장과 사업 주장을 구분하고, 각각 실제로 뒷받침하는 근거를 연결하세요.

한 근거가 문장의 모든 내용을 단독으로 뒷받침할 필요는 없지만, 선택한 근거들을 함께 보았을 때 문장의 주요 주장 모두가 확인되어야 합니다.

[산업·기업 인사이트의 허용 근거]

- 이번 입력 evidence에 제공된 kind=financial과 kind=filing 자료만 사용하세요.
- 재무 주장에는 해당 기업·기간·항목의 재무 근거 ID를 연결하세요.
- 사업 주장에는 실제 공시 문장을 포함한 공시 근거 ID를 연결하세요.
- 증감이나 비율 변화를 설명한다면 현재 값, 비교 값과 계산에 사용된 원자료를 추적할 수 있도록 근거를 연결하세요.
- 한 문장에 재무와 사업 주장이 함께 있으면 두 종류의 근거를 모두 연결하세요.
- 재무만 설명하는 문장에는 재무 근거를, 사업만 설명하는 문장에는 공시 근거를 연결할 수 있습니다.
- 최종 문단 전체에서는 두 종류의 중요한 내용과 근거가 모두 반영되어야 합니다.
- 공시 문장을 재무 수치의 직접 출처처럼 사용하지 마세요.
- 재무 수치만으로 사업 목적, 원인 또는 실행 상태를 설명하지 마세요.

[공시 키워드 인사이트의 허용 근거]

- 각주에는 kind=filing의 적격 자연어 공시 근거만 사용하세요.
- kind=financial 자료는 refs와 assessments에 넣지 마세요.
- 각 문장에 해당 설명을 뒷받침하는 적격 공시 근거를 연결하세요.

[재무 근거의 적격 조건]

- 기업, 기간, 항목, 단위, 연결·별도 기준과 누적·단일 기간 기준이 주장과 일치해야 합니다.
- 사용한 값과 비교 결과가 입력에서 확인되어야 합니다.
- 추정이나 검토 상태를 숨기지 않아야 합니다.
- 확인할 수 없는 계산이나 입력에 없는 항목을 사용하지 마세요.
- 재무 근거에는 자연어 문장 길이 조건이나 F/U/C/T 평가를 적용하지 마세요.
- 재무 근거를 공시 청크나 원문 문장 ID로 바꾸어 반환하지 마세요.

[자연어 공시 근거의 적격 조건]

- 입력 passages에 제공된 20자 이상의 자연어 원문 문장만 선택하세요.
- 표의 셀과 정량 수치를 자연어 원문 문장처럼 선택하지 마세요.
- 표 안의 자연어 정보도 입력에서 인용 가능한 원문 문장과 위치로 제공된 경우에만 선택하세요.
- 원문 문장을 고치거나 원문 위치를 만들어내지 마세요.
- 필요한 인접 문장을 함께 선택하여 주체와 조건을 보존하세요.
- context_before/context_after는 문맥을 이해하는 자료이며 각주 ID가 아닙니다.
- 인용 가능한 문장에 없는 내용을 인접 문맥만으로 새 주장으로 만들지 마세요.

[공시 근거 평가]

선택한 공시 근거가 담당하는 사업 주장 또는 인과 주장을 기준으로 평가하세요.
해당 근거에 재무 수치가 없다는 이유만으로, 별도 재무 근거가 담당하는 주장까지 뒷받침하도록 요구하지 마세요.

각 항목을 0-4점으로 평가하세요.
0은 부합하지 않음, 1은 약함, 2는 부분적, 3은 충분함, 4는 매우 충분함입니다.

F, 사실 부합도 — 40%
주체, 행위, 방향, 조건, 원인에 관한 해당 주장을 원문이 직접 뒷받침하는 정도입니다.
같은 키워드가 등장한다는 이유만으로 높은 점수를 주지 마세요.

U, 사업 이해에 대한 도움 — 30%
해당 원문이 실제 사업 현황과 방향을 초보 사용자가 이해하는 데 도움이 되는 정도입니다.
표현이 쉽거나 흥미롭다는 이유만으로 높은 점수를 주지 마세요.

C, 명확성 — 20%
주체, 제품, 행위와 조건이 명확하고 원문 맥락을 보존하여 설명할 수 있는 정도입니다.

T, 시점 적합성 — 10%
주장의 시점과 실제 사건 시점이 맞고 현황·계획·진행·완료를 정확히 구분하는 정도입니다.

[감점과 기준]

irrelevant_content와 redundancy는 각각 none=0, some=5, substantial=10점 감점합니다.

사실 해석에 필요한 조건, 위험, 단위와 비교 기준을 불필요한 정보로 취급하지 마세요.

점수 = max(0, 25 × (0.4F + 0.3U + 0.2C + 0.1T) - 두 감점)

F>=3, C>=3, 최종 점수>=75이고 해당 주장을 실제로 뒷받침하는 공시 근거만 선택하세요.

기준을 충족시키기 위해 점수를 높이지 마세요. 근거가 부족하면 주장의 범위를 좁히거나 생략하세요.

[근거 ID 연결]

- refs에는 이번 입력에 존재하며 해당 기능에서 허용된 근거 ID만 사용하세요.
- 산업·기업 인사이트의 refs에는 재무 ID(fN)와 공시 청크 ID(tN)를 사용할 수 있습니다.
- 키워드 인사이트의 refs에는 공시 청크 ID(tN)만 사용하세요.
- assessments에는 refs로 선택한 공시 청크(tN)의 평가만 반환하세요.
- passage_ids에는 해당 청크에 실제로 제공된 문장 ID(tN-pM)만 사용하세요.
- 재무 ID(fN)는 assessments와 passage_ids에 넣지 마세요.
- 동일 청크의 여러 문장은 하나의 공시 근거 청크로 취급하세요.
- 동일 근거 ID를 반복하지 마세요.
- 여러 기업의 공통 동향을 설명한다면 그 범위를 실제로 뒷받침하는 근거들을 선택하세요.
- 관계없는 근거로 개수를 채우거나 근거보다 넓은 주장을 만들지 마세요.
[출력 형식]

- 제공된 JSON Schema를 따르세요.
- sentences 배열의 각 항목은 완결된 요약 한 문장입니다.
- 각 항목에 text, refs, assessments를 반환하세요.
- text에는 고객용 문장만 작성하세요.
- refs에는 그 문장을 뒷받침하는 실제 근거 ID를 반환하세요.
- assessments에는 선택한 공시 근거의 평가와 원문 문장 ID만 반환하세요.
- 재무 근거만 사용하는 문장의 assessments는 빈 배열로 반환하세요.
- 정상적으로 설명할 수 있으면 insufficient_reason은 빈 문자열로 반환하세요.
- 후보 목록, 중간 분석 결과, 흐름 개수, 단계별 판단 과정은 반환하지 마세요.
- 평가 이유는 짧게 작성하세요.
- 선택하지 않은 후보의 평가나 장황한 설명을 출력하지 마세요.
- 요청된 JSON 외의 설명, 제목이나 코드 블록을 반환하지 마세요.

[근거 부족]

- 관련 자료가 부족하면 확인 가능한 범위를 넘어서 설명하지 마세요.
- 자료가 충분하지만 중요한 변화가 없는 경우와 자료 부족으로 판단할 수 없는 경우를 구분하세요.
- 산업·기업 인사이트에서 두 종류의 적격하고 의미 있는 정보를 함께 반영할 수 없다면 sentences=[]와 구체적인 insufficient_reason을 반환하세요.
- 키워드 인사이트에서 용어와 관련 사업 현황을 설명할 적격 공시 근거가 없다면 sentences=[]와 insufficient_reason을 반환하세요.
- 문장 수나 정보 균형을 채우기 위해 사소한 사실, 확인되지 않은 변화 또는 모호한 종합 문장을 만들지 마세요."""
passages = base.passages
bounded_rows = base.bounded_rows
def snapshot(evidence):
    result = base.snapshot(evidence)
    result['version'] = VERSION
    return result

def schema(llm, minimum, maximum, evidence):
    return base.schema(llm, minimum, maximum, evidence, allow_financial=True)

def validate(value, evidence, minimum, maximum):
    from .mvp_validation import enabled,validate as validate_mvp
    if enabled():
        validate_mvp(value,evidence,allow_financial=True)
        # Financial matching remains diagnostic only; never call this fully verified.
        try:validate_financial(copy.deepcopy(value),evidence)
        except base.CitationValidationError as error:
            value.setdefault('validation_warnings',[]).extend(error.issues)
        return value
    # Validate a copy: failed repair attempts must not acquire partial auto-links.
    working=copy.deepcopy(value);errors=[]
    try:base.validate(working, evidence, minimum, maximum, allow_financial=True)
    except base.CitationValidationError as error:errors.append(error)
    lookup={e['id']:e for e in evidence}
    items=working.get('sentences') if isinstance(working,dict) else None
    safe=isinstance(items,list) and all(isinstance(s,dict) and isinstance(s.get('text'),str)
        and isinstance(s.get('refs'),list) and len(s['refs'])==len(set(r for r in s['refs'] if isinstance(r,str)))
        and all(isinstance(r,str) and r in lookup for r in s['refs']) for s in items)
    # A citation assessment error must not hide an independent financial error.
    if safe:
        try:validate_financial(working,evidence)
        except base.CitationValidationError as error:errors.append(error)
    if errors:
        raise base.CitationValidationError('; '.join(str(e) for e in errors),
            [issue for error in errors for issue in error.issues]) from None
    value.clear();value.update(working)
    return value
