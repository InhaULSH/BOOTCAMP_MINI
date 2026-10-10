"""Typed transport checks, scoped monetary facts and invalid-cache regeneration."""
import json
import logging
import math
import re

VERSION='response-v1-scoped-money'
OUTPUT_NOTE='후보 비교는 유지하되 최종 assessments에는 refs로 선택한 청크의 평가만 반환하세요. 평가 이유는 짧게 작성하고, 선택하지 않은 후보의 평가나 장황한 설명을 출력하지 마세요.'

def response_text(body):
    if not isinstance(body,dict):raise ValueError('Gemini 응답 본문은 객체여야 합니다.')
    candidates=body.get('candidates')
    if not isinstance(candidates,list) or not candidates:
        reason=body.get('promptFeedback',{}).get('blockReason') if isinstance(body.get('promptFeedback',{}),dict) else None
        return '',reason or 'NO_CANDIDATES'
    candidate=candidates[0]
    if not isinstance(candidate,dict):raise ValueError('Gemini candidate는 객체여야 합니다.')
    content=candidate.get('content')
    if candidate.get('finishReason')!='STOP' and (not isinstance(content,dict) or not isinstance(content.get('parts'),list)):
        return '',candidate.get('finishReason')
    content=candidate.get('content',{})
    if not isinstance(content,dict):raise ValueError('Gemini content는 객체여야 합니다.')
    parts=content.get('parts',[])
    if not isinstance(parts,list):raise ValueError('Gemini parts는 배열이어야 합니다.')
    output=[]
    for part in parts:
        if not isinstance(part,dict):raise ValueError('Gemini part는 객체여야 합니다.')
        if part.get('thought'):continue
        text=part.get('text','')
        if not isinstance(text,str):raise ValueError('Gemini text는 문자열이어야 합니다.')
        output.append(text)
    return ''.join(output),candidate.get('finishReason')

def cached_result(path,validate,generate):
    if path.exists():
        try:
            result=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(result,dict) or not isinstance(result.get('report'),dict):raise ValueError('캐시 형식 오류')
            validate(result['report'])
            return result
        except (ValueError,KeyError,TypeError,AttributeError,UnicodeError,FileNotFoundError):
            logging.warning('생성 캐시 검증 실패 · 해당 요청만 재생성합니다.')
            path.unlink(missing_ok=True)
    return generate()

METRICS={'revenue':r'매출액|매출', 'operating_income':r'영업이익|영업손실|영업손익',
         'operating_cashflow':r'영업활동\s*(?:현금흐름|현금 흐름)', 'capex':r'CAPEX|설비투자|유형자산\s*취득'}
MONEY=re.compile(r'(?:(\d[\d,.]*)\s*조\s*)?(?:(\d[\d,.]*)\s*억\s*)?(?:(\d[\d,.]*)\s*만\s*)?(\d[\d,.]*)?\s*원')

def _validate_money(value,evidence):
    lookup={e['id']:e for e in evidence}
    for sentence in value['sentences']:
        text=sentence['text'];cited=[lookup[i] for i in sentence['refs']]
        for match in MONEY.finditer(text):
            if not any(match.groups()):continue
            prefix=text[:match.start()]
            labels=[(m.end(),k) for k,pattern in METRICS.items() for m in re.finditer(pattern,prefix,re.I)]
            if not labels:raise ValueError('문장 금액의 재무 항목을 확인할 수 없습니다.')
            metric=max(labels)[1]
            companies={e['company'] for e in cited}
            known_companies={e['company'] for e in evidence}
            named=[(prefix.rfind(c),c) for c in known_companies if c in prefix]
            if named:
                named_company=max(named)[1]
                if named_company not in companies:raise ValueError('문장 금액의 기업이 인용 근거와 다릅니다.')
                companies={named_company}
            years=re.findall(r'((?:19|20)\d{2})\s*년',prefix)
            selected_years={int(years[-1])} if years else {e['year'] for e in cited}
            period_matches=list(re.finditer(r'1분기|반기|상반기|3분기|연간|사업보고서',prefix))
            periods={'1분기':'Q1','반기':'H1','상반기':'H1','3분기':'Q3','연간':'FY','사업보고서':'FY'}
            report_types={periods[period_matches[-1].group()]} if period_matches else { {'03':'Q1','06':'H1','09':'Q3','12':'FY'}.get(e.get('period','')[-2:]) for e in cited}
            basis_matches=list(re.finditer(r'연결|별도',prefix))
            bases={ 'CFS' if basis_matches[-1].group()=='연결' else 'OFS' } if basis_matches else set()
            candidates=[e for e in evidence if e['kind']=='financial' and e['company'] in companies and e['year'] in selected_years
                        and e.get('report_type',e['values'].get('report_type','FY')) in report_types
                        and (not bases or e['values'].get('basis') in bases)]
            if len(companies)!=1 or len(selected_years)!=1 or len(report_types)!=1 or None in report_types or len({e['values'].get('basis') for e in candidates})!=1:
                raise ValueError('문장 금액의 기업·연도·보고서·회계 기준이 모호합니다.')
            amount=sum(float(v.replace(',',''))*scale for v,scale in zip(match.groups(),(1e12,1e8,1e4,1)) if v)
            nearby=prefix[-12:]
            if nearby.endswith(('-','−')) or re.search(r'마이너스\s*$',nearby) or re.search(r'영업손실\D*$',prefix):amount=-amount
            precision=min(scale*10**(-len(v.split('.')[-1]) if '.' in v else 0) for v,scale in zip(match.groups(),(1e12,1e8,1e4,1)) if v)
            numbers=[e['values'].get(metric) for e in candidates]
            if not any(isinstance(n,(int,float)) and math.isfinite(n) and abs(n-amount)<=precision/2+1e-6 for n in numbers):
                raise ValueError('문장 금액이 인용한 입력 근거의 기업·연도·보고서·재무 항목과 일치하지 않습니다.')
    return value

def validate_money(value,evidence):
    from .citation_selection import CitationValidationError
    # Validate one sentence at a time so monetary errors can name the exact item.
    for index,sentence in enumerate(value['sentences'],1):
        try:_validate_money(dict(sentences=[sentence]),evidence)
        except ValueError as error:
            raise CitationValidationError(str(error),[dict(error_code='MONEY_SCOPE_OR_VALUE_MISMATCH',
                sentence_index=index,detail=str(error))]) from None
    return value
