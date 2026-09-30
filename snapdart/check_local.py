"""Run a small real disclosure analysis to verify the local provider."""
import json
import os
from urllib.request import urlopen, Request
from .config import DATA, COMPANIES
from . import llm
from .analyze import business_text
from .retrieval import select_passages
from .hierarchy import SUMMARY_SCHEMA, INSTRUCTION, validate


def main():
    if llm.PROVIDER != 'ollama':
        raise RuntimeError('LLM_PROVIDER=ollama로 설정하세요.')
    base = os.getenv('OLLAMA_BASE_URL','http://127.0.0.1:11434').rstrip('/')
    with urlopen(base+'/api/version', timeout=10) as r:
        print('Ollama', json.load(r)['version'], flush=True)
    req = Request(base+'/api/show', data=json.dumps({'model':llm.MODEL}).encode(),
                  headers={'Content-Type':'application/json'})
    with urlopen(req, timeout=30) as r:
        details = json.load(r)['details']
    print('모델', llm.MODEL, details.get('parameter_size'), details.get('quantization_level'), flush=True)
    company=COMPANIES[0]
    folder=DATA/company['code']
    filing=json.loads((folder/'filings.json').read_text(encoding='utf-8'))[-1]
    passage=select_passages(business_text(folder/(filing['rcept_no']+'.zip')),limit=1)[0]
    evidence=[dict(id='local-smoke-2025', year=int(filing['period'][:4]), period=filing['period'], text=passage)]
    result=llm.request_report(dict(company=company['name'],evidence=evidence),evidence,
                              schema=SUMMARY_SCHEMA,instruction=INSTRUCTION,validator=validate)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    with urlopen(base+'/api/ps',timeout=10) as r:
        for model in json.load(r)['models']:
            print('로드 상태',model['name'],'context',model.get('context_length'),'GPU bytes',model.get('size_vram'),flush=True)


if __name__ == '__main__':
    main()
