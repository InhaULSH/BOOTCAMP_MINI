import json
import unittest
from unittest.mock import patch, MagicMock
from snapdart.local_llm import generate
from snapdart.llm import InputTooLarge

class LocalTests(unittest.TestCase):
    def test_report_uses_local_transport_without_gemini(self):
        from snapdart.llm import request_report
        report={"answer":"입력 자료 요약", "refs":["t1"]}
        evidence=[dict(id="t1",year=2025,text="입력 자료")]
        body = dict(candidates=[dict(finishReason='STOP',content={'parts':[{'text':json.dumps(report)}]})])
        with patch('snapdart.llm.PROVIDER','ollama'), patch('snapdart.local_llm.generate',return_value=body) as local, patch('snapdart.llm.count_input_tokens') as count, patch('snapdart.llm.TOKEN_BUDGET.reserve') as budget:
            self.assertEqual(request_report(dict(evidence=evidence),evidence,schema={"type":"object"},instruction="입력 자료만 사용",validator=lambda v,e:v)['report'],report)
            local.assert_called_once()
            count.assert_not_called()
            budget.assert_not_called()

    def payload(self, text='분석 자료'):
        return dict(systemInstruction={'parts':[{'text':'규칙'}]},
                    contents=[{'parts':[{'text':text}]}],
                    generationConfig={'responseJsonSchema':{'type':'object'}})

    def test_local_schema_and_no_auth(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps(dict(done=True,done_reason='stop',message={'content':'{}'},prompt_eval_count=10,eval_count=2)).encode()
        with patch('snapdart.local_llm.urlopen',return_value=response) as call:
            result=generate(self.payload(),'qwen3.5:9b-q4_K_M')
        request=call.call_args.args[0]
        self.assertNotIn('Authorization',request.headers)
        body=json.loads(request.data)
        self.assertFalse(body['think'])
        self.assertEqual(body['options']['num_batch'],32)
        self.assertEqual(body['options']['num_predict'],8192)
        self.assertEqual(body['format'],{'type':'object'})
        self.assertEqual(result['usageMetadata']['promptTokenCount'],10)

    def test_oversize_never_sent(self):
        with patch('snapdart.local_llm.urlopen') as call:
            with self.assertRaises(InputTooLarge):
                generate(self.payload('가'*150000),'model')
            call.assert_not_called()

    def test_remote_endpoint_rejected(self):
        with patch.dict('os.environ',{'OLLAMA_BASE_URL':'https://example.com'}):
            with self.assertRaisesRegex(RuntimeError,'localhost'):
                generate(self.payload(),'model')

    def test_explicit_generation_options_are_used(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"done":true,"done_reason":"stop","message":{"content":"{}"}}'
        payload=self.payload();payload['generationConfig'].update(maxOutputTokens=500,temperature=1)
        with patch('snapdart.local_llm.urlopen',return_value=response) as call:
            generate(payload,'model')
        options=json.loads(call.call_args.args[0].data)['options']
        self.assertEqual(options['num_predict'],500)
        self.assertEqual(options['temperature'],1)

    def test_truncated_response_not_accepted(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"done":true,"done_reason":"length"}'
        with patch('snapdart.local_llm.urlopen',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'출력 한도'):
                generate(self.payload(),'model')
