import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from snapdart import llm


class CurrentTransportTests(unittest.TestCase):
    def test_explicit_prompt_is_transmitted_unchanged_and_repair_keeps_schema(self):
        evidence=[dict(id='t1',year=2025,text='입력 근거')]
        schema=llm.object_schema({'answer':llm.TEXT,'refs':{'type':'array','items':llm.TEXT}})
        payloads=[]
        def response(payload,model):
            payloads.append(payload)
            refs=['unknown'] if len(payloads)==1 else ['t1']
            value={'answer':'자료에 나타난 변화입니다.','refs':refs}
            return {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(value)}]}}]}
        def validate(value,allowed):
            if value['refs']!=['t1']:raise ValueError('입력에 없는 근거 ID')
            return value
        with tempfile.TemporaryDirectory() as folder, patch.object(llm,'DATA',Path(folder)), \
             patch.object(llm,'PROVIDER','ollama'), patch('snapdart.local_llm.generate',side_effect=response):
            result=llm.request_report({'evidence':evidence},evidence,schema=schema,
                instruction='정의서의 공통 지시문',validator=validate,temperature=1,max_output_tokens=500)
        self.assertEqual(result['report']['refs'],['t1'])
        self.assertEqual(len(payloads),2)
        for payload in payloads:
            self.assertEqual(payload['systemInstruction']['parts'][0]['text'],'정의서의 공통 지시문')
            self.assertEqual(payload['generationConfig']['responseJsonSchema'],schema)
        repair=json.loads(payloads[-1]['contents'][0]['parts'][0]['text'])
        self.assertNotIn('timeline',repair['task'])

    def test_token_window_and_oversized_input(self):
        now=[0.0]
        def sleep(seconds):now[0]+=seconds
        with patch.object(llm.time,'monotonic',side_effect=lambda:now[0]), patch.object(llm.time,'sleep',side_effect=sleep), \
             patch.dict('os.environ',{'GEMINI_TPM_BUDGET':'225000','GEMINI_RPM_BUDGET':'10'}):
            limiter=llm.TokenBudget();limiter.reserve(110000);limiter.reserve(110000)
            self.assertEqual(now[0],60)
            with self.assertRaises(llm.InputTooLarge):limiter.reserve(250000)
