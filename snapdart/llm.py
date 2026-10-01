"""Grounded Gemini reports: schema validation, bounded retries and local cache."""
import hashlib
import json
import os
import random
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .config import load_env, SERVICE_ROOT
DATA = SERVICE_ROOT / 'llm'
load_env()
from .collect import save_json

PROVIDER = os.getenv('LLM_PROVIDER', 'gemini').lower()

if PROVIDER == 'ollama':
    MODEL = os.getenv(
        'OLLAMA_MODEL',
        'qwen3.5:9b-q4_K_M'
    )
else:
    MODEL = os.getenv(
        'GEMINI_MODEL',
        'gemini-3.5-flash-lite'
    )

TEXT = {'type':'string'}

def object_schema(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)

def compact_context(context):
    """Keep every dated evidence ID, but transmit identical text only once per company."""
    import copy
    result = copy.deepcopy(context)
    seen = {}
    for item in result.get('evidence', []):
        if 'text' not in item:
            continue
        # IDs start with stock code; identical wording across companies is not merged.
        key = (item['id'].split('-')[0], item['text'])
        if key in seen:
            item['text_ref'] = seen[key]
            del item['text']
        else:
            seen[key] = item['id']
    return result

class InputTooLarge(RuntimeError):
    pass

class TokenBudget:
    def __init__(self):
        self.events = []

    def reserve(self, tokens):
        tpm_limit = int(
            os.getenv('GEMINI_TPM_BUDGET', '225000')
        )
        rpm_limit = int(
            os.getenv('GEMINI_RPM_BUDGET', '10')
        )

        reserved = int(tokens * 1.05) + 1024

        if reserved > tpm_limit:
            raise InputTooLarge(
                f'단일 요청 입력 {tokens:,}토큰이 '
                f'설정된 TPM 예산 {tpm_limit:,}을 초과합니다.'
            )

        while True:
            now = time.monotonic()

            self.events = [
                (t, n)
                for t, n in self.events
                if now - t < 60
            ]

            token_usage = sum(n for _, n in self.events)

            rpm_ok = len(self.events) < rpm_limit
            tpm_ok = token_usage + reserved <= tpm_limit

            if rpm_ok and tpm_ok:
                self.events.append((now, reserved))
                return

            if not self.events:
                raise InputTooLarge(
                    '현재 요청이 설정된 Gemini 사용량 예산을 초과합니다.'
                )

            delay = max(
                0.1,
                self.events[0][0] + 60 - now
            )

            print(
                f'Gemini 사용량 제한 보호 · '
                f'{delay:.1f}초 대기',
                flush=True
            )
            time.sleep(min(delay, 10))

def gemini_http_message(error, key):
    """Expose useful API diagnostics without printing credentials or response metadata."""
    import re
    try:
        detail = json.loads(error.read().decode('utf-8')).get('error', {})
        message = str(detail.get('message', ''))
    except (ValueError, UnicodeError, AttributeError, OSError):
        message = ''
    for secret in (key, os.getenv('GEMINI_API_KEY'), os.getenv('GOOGLE_API_KEY')):
        if secret:
            message = message.replace(secret, '[REDACTED]')
    message = re.sub(r'AIza[\w-]+', '[REDACTED]', message)[:1000]
    if 'project has been denied access' in message.lower():
        action = 'Google이 API 프로젝트 접근을 차단했습니다. 토큰 제한 문제가 아니며 대기로 해결되지 않습니다. Google AI Studio에서 해당 키의 프로젝트를 확인하고 Google 지원팀에 접근 해제를 문의하세요.'
    elif error.code == 403:
        action = 'API 키 또는 프로젝트의 접근 권한을 확인하세요. 권한 오류는 대기로 해결되지 않습니다.'
    elif error.code == 429:
        action = 'API 요청·토큰·일일 할당량을 확인하세요.'
    else:
        action = 'API 키·모델·요청 설정을 확인하세요.'
    return f'Gemini HTTP {error.code}: {action} Google 응답: {message or "상세 메시지 없음"} 기존 보고서는 보존됩니다.'

def retry_delay(attempt, base=2.0, maximum=60.0):
    """Exponential backoff with small jitter."""
    delay = min(maximum, base * (2 ** attempt))
    jitter = random.uniform(0, min(1.0, delay * 0.1))
    return delay + jitter

def count_input_tokens(payload, key):
    generate_request = dict(payload)
    generate_request['model'] = f'models/{MODEL}'

    body = {
        'generateContentRequest': generate_request
    }

    request = Request(
        f'https://generativelanguage.googleapis.com/'
        f'v1beta/models/{MODEL}:countTokens',
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'x-goog-api-key': key,
        },
        method='POST',
    )

    for attempt in range(3):
        try:
            with urlopen(request, timeout=90) as response:
                count = json.load(response).get('totalTokens')

            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
            ):
                raise ValueError('invalid token count')

            return count

        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            if isinstance(error, HTTPError):
                retryable = error.code in (
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                )
            else:
                retryable = isinstance(
                    error,
                    (URLError, TimeoutError)
                )

            if retryable and attempt < 2:
                delay = retry_delay(attempt)

                if isinstance(error, HTTPError):
                    reason = f'HTTP {error.code}'
                else:
                    reason = type(error).__name__

                print(
                    f'Gemini 입력 토큰 계산 실패 ({reason}) · '
                    f'{delay:.1f}초 후 재시도',
                    flush=True,
                )

                time.sleep(delay)
                continue

            if isinstance(error, HTTPError):
                raise RuntimeError(
                    gemini_http_message(error, key)
                ) from None

            raise RuntimeError(
                'Gemini 입력 토큰 계산 실패. '
                '생성 요청은 보내지 않았습니다.'
            ) from None

def citation_schema(schema, evidence):
    import copy

    if not evidence:
        raise ValueError('인용 가능한 근거가 없습니다.')

    return copy.deepcopy(schema)

def model_context(context):
    # Provenance remains in local caches; it is not a selectable citation.
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in ('source_ids', 'parent_id')}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return compact_context(clean(context))

def request_report(
    context,
    evidence,
    schema=None,
    instruction=None,
    validator=None,
    _repair=None,
    max_output_tokens=14000,
    temperature=None
):
    load_env()

    key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')

    if PROVIDER == 'gemini' and not key:
        raise RuntimeError('.env에 GEMINI_API_KEY가 필요합니다.')

    compact = model_context(context)

    if schema is None or instruction is None or validator is None:
        raise ValueError('현재 호출 경로의 schema, instruction, validator가 필요합니다.')
    content = compact
    if _repair is not None:
        content = dict(materials=content, correction=_repair,
            task='검증 오류를 수정한 전체 JSON을 반환합니다. 제공된 JSON Schema와 입력 근거 ID를 따릅니다.')
    system_text = instruction

    payload = {
        'systemInstruction': {
            'parts': [
                {'text': system_text}
            ]
        },
        'contents': [
            {
                'role': 'user',
                'parts': [
                    {
                        'text': json.dumps(
                            content,
                            ensure_ascii=False
                        )
                    }
                ]
            }
        ],
        'generationConfig': {
            'responseMimeType': 'application/json',
            'responseJsonSchema': citation_schema(
                schema,
                evidence
            ),
            'maxOutputTokens': max_output_tokens,
        }
    }

    if temperature is not None:payload['generationConfig']['temperature']=temperature
    if PROVIDER == 'ollama':
        from .local_llm import generate
        body = generate(payload, MODEL)
    elif PROVIDER == 'gemini':
        tokens = count_input_tokens(payload, key)
        request = Request(f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent',
                          data=json.dumps(payload).encode('utf-8'),
                          headers={'Content-Type':'application/json','x-goog-api-key':key}, method='POST')
        for attempt in range(3):
            TOKEN_BUDGET.reserve(tokens)
            try:
                with urlopen(request, timeout=180) as response:
                    body = json.load(response)
                break
            except HTTPError as error:
                retryable = error.code in (
                    408, 429, 500, 502, 503, 504
                )

                if retryable and attempt < 2:
                    delay = retry_delay(attempt)

                    print(
                        f'Gemini HTTP {error.code} · '
                        f'{delay:.1f}초 후 재시도',
                        flush=True
                    )

                    time.sleep(delay)
                    continue

                raise RuntimeError(
                    gemini_http_message(error, key)
                ) from None
            except (URLError, TimeoutError) as error:
                if attempt < 2:
                    delay = retry_delay(attempt)

                    print(
                        f'Gemini 네트워크 오류 '
                        f'({type(error).__name__}) · '
                        f'{delay:.1f}초 후 재시도',
                        flush=True,
                    )

                    time.sleep(delay)
                    continue

                raise RuntimeError(
                    'Gemini 네트워크 연결 실패. '
                    '기존 보고서는 보존됩니다.'
                ) from None
    else:
        raise RuntimeError('LLM_PROVIDER는 ollama 또는 gemini여야 합니다.')

    text = ''
    finish_reason = None

    try:
        candidate = body['candidates'][0]
        finish_reason = candidate.get('finishReason')

        if finish_reason != 'STOP':
            raise ValueError(
                'Gemini 응답이 정상 종료되지 않았습니다. '
                f'finishReason={finish_reason!r}'
            )

        text = ''.join(
            p.get('text', '')
            for p in candidate['content']['parts']
            if not p.get('thought')
        )

        report = validator(
            json.loads(text),
            evidence
        )

        return dict(
            report=report,
            usage=body.get('usageMetadata', {}),
            model=body.get('modelVersion', MODEL)
        )

    except (KeyError, IndexError, TypeError, ValueError) as error:
        diagnostic = dict(
            error=str(error),
            finish_reason=finish_reason,
            response=text,
            allowed_ids=[
                {
                    'id': e['id'],
                    'year': e['year']
                }
                for e in evidence
            ],
            rule='JSON Schema와 입력 근거 ID 검증'
        )

        name = hashlib.sha256(
            json.dumps(
                diagnostic,
                ensure_ascii=False
            ).encode()
        ).hexdigest()

        save_json(
            DATA / 'llm_errors' / (name + '.json'),
            diagnostic
        )

        if _repair is None:
            print(
                '분석 응답 검증 실패 · '
                '근거 목록으로 한 차례 교정합니다.',
                flush=True
            )

            return request_report(
                context,
                evidence,
                schema=schema,
                instruction=instruction,
                validator=validator,
                _repair=diagnostic,
                max_output_tokens=max_output_tokens,temperature=temperature
            )

        raise RuntimeError(
            f'LLM 결과 검증 실패: {error}. '
            '기존 보고서는 보존됩니다.'
        ) from None

TOKEN_BUDGET = TokenBudget()
