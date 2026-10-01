"""Local-only Ollama transport. No cloud fallback or API keys."""
import json
import os
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def generate(payload, model):
    from .llm import InputTooLarge
    base = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
    if urlparse(base).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('로컬 분석 주소에는 localhost만 사용할 수 있습니다.')
    ctx = int(os.getenv('OLLAMA_NUM_CTX', '131072'))
    output = min(int(os.getenv('OLLAMA_NUM_PREDICT', '8192')), payload['generationConfig'].get('maxOutputTokens', 8192))
    system = payload['systemInstruction']['parts'][0]['text']
    content = payload['contents'][0]['parts'][0]['text']
    schema = payload['generationConfig']['responseJsonSchema']
    # Ollama has no countTokens endpoint. UTF-8 bytes are a conservative bound,
    # with reserved template/output space; never silently truncate the prompt.
    estimate = len((system+content+json.dumps(schema,ensure_ascii=False)).encode('utf-8')) + 2048
    if estimate + output > ctx:
        raise InputTooLarge(f'로컬 입력 보수적 상한 {estimate:,} + 출력 {output:,}이 문맥 {ctx:,}을 초과합니다.')
    body = dict(model=model, stream=False, think=False, keep_alive='30m', format=schema,
                messages=[dict(role='system',content=system),dict(role='user',content=content)],
                options=dict(num_ctx=ctx,num_predict=output,temperature=payload['generationConfig'].get('temperature',1),seed=42,num_batch=int(os.getenv('OLLAMA_NUM_BATCH','32'))))
    request = Request(base+'/api/chat',data=json.dumps(body).encode('utf-8'),
                      headers={'Content-Type':'application/json'},method='POST')
    for attempt in range(3):
        try:
            with urlopen(request,timeout=3600) as response:
                result=json.load(response)
            if result.get('error'):
                raise RuntimeError('Ollama 모델 실행 실패: '+str(result['error']))
            if not result.get('done') or result.get('done_reason') == 'length':
                raise RuntimeError('로컬 모델 응답이 출력 한도에서 중단됐습니다. 기존 보고서는 보존됩니다.')
            return dict(candidates=[dict(finishReason='STOP',content={'parts':[{'text':result['message']['content']}]})],
                        modelVersion=model,usageMetadata=dict(promptTokenCount=result.get('prompt_eval_count'),
                        candidatesTokenCount=result.get('eval_count'),provider='ollama'))
        except HTTPError as error:
            if error.code in (429,500,502,503,504) and attempt < 2:
                time.sleep(5*(attempt+1))
                continue
            raise RuntimeError(f'Ollama HTTP {error.code}. 서버 및 모델 설치 상태를 확인하세요.') from None
        except (URLError,TimeoutError):
            raise RuntimeError('Ollama 연결 실패 또는 응답 시간 초과. 로컬 서버 실행 상태를 확인하세요.') from None
