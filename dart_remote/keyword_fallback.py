"""Customer messages are independent of private model/network diagnostics."""
import re
MESSAGES={
    'insufficient_evidence':'최근 공시에서 의미 있게 포착된 키워드이지만, 특정 사업 변화와 직접 연결해 설명할 만큼 충분한 근거 문장은 확인되지 않았습니다.',
    'rate_limit':'현재 설명 요청이 많아 잠시 제공이 지연되고 있습니다.',
    'unavailable':'현재 공시 설명을 불러오는 데 시간이 걸리고 있습니다.',
    'verification':'최근 공시에서 의미 있게 포착된 키워드이지만, 설명과 근거의 일치 여부를 충분히 확인하지 못했습니다.',
    'not_generated':'이 키워드의 상세 설명은 아직 준비되지 않았습니다.',
    'configuration':'현재 상세 설명을 제공하기 어렵습니다. 관련 공시에서 키워드의 내용을 직접 확인하실 수 있습니다.',
}

def classify(reason):
    text=str(reason).lower()
    status=re.search(r'(?:http\s*(?:error\s*)?|상태\s*코드\s*[:：]?\s*)(\d{3})\b',text)
    code=int(status.group(1)) if status else None
    if code in (401,403,404) or any(k in text for k in ('인증','권한','api key','안전 예산','단일 요청 입력')):return 'configuration'
    if code==429 or any(k in text for k in ('할당량','사용량 제한','rate limit')):return 'rate_limit'
    if code in (408,500,502,503,504,800) or any(k in text for k in ('네트워크','연결 실패','timeout')):return 'unavailable'
    if any(k in text for k in ('검증','json','근거 id','응답')):return 'verification'
    return 'insufficient_evidence'

def result(reason):
    code=classify(reason)
    return dict(sentences=[],fallback_reason=code,retryable=code in ('unavailable','rate_limit'),insufficient_reason=MESSAGES[code],method='키워드 설명 안내')
