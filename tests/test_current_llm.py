import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from snapdart import llm
from dart_remote import llm_diagnostics


class CurrentTransportTests(unittest.TestCase):
    def test_fact_extraction_failure_does_not_spawn_a_repair(self):
        schema=llm.object_schema({'facts':dict(type='array',items=llm.TEXT),'insufficient_reason':llm.TEXT})
        body={'candidates':[dict(finishReason='STOP',content=dict(parts=[dict(text='{"facts":[],"insufficient_reason":""}')]))]}
        with tempfile.TemporaryDirectory() as folder,patch.object(llm_diagnostics.artifacts,'ROOT',Path(folder)),\
             patch.dict('os.environ',{'GEMINI_API_KEY':'test-key'}),patch.object(llm,'count_input_tokens',return_value=100),\
             patch.object(llm.TOKEN_BUDGET,'reserve'),patch.object(llm,'urlopen',return_value=io.BytesIO(json.dumps(body).encode())) as call:
            with self.assertRaisesRegex(RuntimeError,'검증 실패'):
                llm.request_report({},[dict(id='t1')],schema=schema,instruction='근거 정리',
                    validator=Mock(side_effect=ValueError('부족 사유 오류')),allow_repair=False)
        self.assertEqual(call.call_count,1)

    def test_finish_reason_controls_retry(self):
        evidence=[dict(id='t1',year=2025,text='입력 근거')]
        schema=llm.object_schema({'answer':llm.TEXT})
        for reason,expected_calls in (('MAX_TOKENS',2),('SAFETY',1)):
            payloads=[]
            def response(request,**options):
                payloads.append(json.loads(request.data))
                candidate={'finishReason':reason} if len(payloads)==1 else {'finishReason':'STOP','content':{'parts':[{'text':'{"answer":"확인된 내용"}'}]}}
                return io.BytesIO(json.dumps({'candidates':[candidate]}).encode())
            with tempfile.TemporaryDirectory() as folder,patch.object(llm_diagnostics.artifacts,'ROOT',Path(folder)),\
                 patch.dict('os.environ',{'GEMINI_API_KEY':'test-key'}),patch.object(llm,'count_input_tokens',return_value=100),\
                 patch.object(llm.TOKEN_BUDGET,'reserve'),patch.object(llm,'urlopen',side_effect=response):
                if reason=='SAFETY':
                    with self.assertRaisesRegex(RuntimeError,'정책'):llm.request_report({},evidence,schema=schema,instruction='기존 지시',validator=lambda v,e:v,max_output_tokens=8192)
                else:
                    llm.request_report({},evidence,schema=schema,instruction='기존 지시',validator=lambda v,e:v,max_output_tokens=8192)
                    correction=json.loads(payloads[1]['contents'][0]['parts'][0]['text'])
                    self.assertTrue(correction['correction']['compact_output'])
                    self.assertEqual(payloads[1]['generationConfig']['maxOutputTokens'],8192)
            self.assertEqual(len(payloads),expected_calls)

    def test_explicit_prompt_is_transmitted_unchanged_and_repair_keeps_schema(self):
        evidence=[dict(id='t1',year=2025,text='입력 근거')]
        schema=llm.object_schema({'answer':llm.TEXT,'refs':{'type':'array','items':llm.TEXT}})
        payloads=[]
        def response(request,**options):
            payload=json.loads(request.data)
            payloads.append(payload)
            refs=['unknown'] if len(payloads)==1 else ['t1']
            value={'answer':'자료에 나타난 변화입니다.','refs':refs}
            return io.BytesIO(json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(value)}]}}]}).encode())
        def validate(value,allowed):
            if value['refs']!=['t1']:raise ValueError('입력에 없는 근거 ID')
            return value
        with tempfile.TemporaryDirectory() as folder, patch.object(llm,'DATA',Path(folder)), \
             patch.object(llm_diagnostics.artifacts,'ROOT',Path(folder)), \
             patch.dict('os.environ',{'GEMINI_API_KEY':'test-key'}), \
             patch.object(llm,'count_input_tokens',return_value=100), \
             patch.object(llm.TOKEN_BUDGET,'reserve'), patch.object(llm,'urlopen',side_effect=response):
            result=llm.request_report({'evidence':evidence},evidence,schema=schema,
                instruction='정의서의 공통 지시문',validator=validate,temperature=1,max_output_tokens=500)
        self.assertEqual(result['report']['refs'],['t1'])
        self.assertEqual(len(payloads),2)
        for payload in payloads:
            self.assertEqual(payload['systemInstruction']['parts'][0]['text'],'정의서의 공통 지시문')
            self.assertEqual(payload['generationConfig']['responseJsonSchema'],schema)
            self.assertEqual(payload['generationConfig']['temperature'],1)
            self.assertEqual(payload['generationConfig']['maxOutputTokens'],500)
        repair=json.loads(payloads[-1]['contents'][0]['parts'][0]['text'])
        self.assertNotIn('timeline',repair['task'])
        self.assertNotIn('sentences',repair['task'])

    def test_token_window_and_oversized_input(self):
        now=[0.0]
        def sleep(seconds):now[0]+=seconds
        with patch.object(llm.time,'monotonic',side_effect=lambda:now[0]), patch.object(llm.time,'sleep',side_effect=sleep), \
             patch.dict('os.environ',{'GEMINI_TPM_BUDGET':'225000','GEMINI_RPM_BUDGET':'10'}):
            limiter=llm.TokenBudget();limiter.reserve(110000);limiter.reserve(110000)
            self.assertEqual(now[0],60)
            with self.assertRaises(llm.InputTooLarge):limiter.reserve(250000)
