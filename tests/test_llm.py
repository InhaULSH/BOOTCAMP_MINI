import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from snapdart.llm import validate_report, cached_report, YEARS, compact_context, TokenBudget, count_input_tokens
from snapdart.retrieval import select_passages, company_context

def fixture():
    evidence = [dict(id=f'e-{year}', year=year) for year in YEARS]
    card = dict(title='투자 확대 확인',fact='회사는 설비 투자 확대를 계획한다고 설명했습니다.',signal='설비 투자 계획',
                interpretation='생산 수요에 대응하려는 가능성이 있습니다.',financial_impact='실행되면 현금 유출이 커질 수 있습니다.',
                uncertainty='계획의 실제 실행 여부를 확인해야 합니다.',evidence_ids=['e-2025'])
    value = dict(summary='공시와 수치로 확인한 사업 변화에 대한 요약입니다.',opportunity='수요가 늘면 성장할 기회가 있습니다.',
                 risk='수요가 줄면 투자비 회수에 부담이 있습니다.',comparison='표본에 비해 높은 투자 비중을 보입니다.',
                 cards=[copy.deepcopy(card) for _ in range(3)],
                 timeline=[dict(year=y,summary='해당 연도의 공시에서는 투자를 계획했습니다.',stage='투자·개발 계획',evidence_ids=[f'e-{y}']) for y in YEARS],
                 checks=['생산능력의 실제 증가 여부','투자 지출의 현금흐름 영향'])
    return value,evidence

class LLMTests(unittest.TestCase):
    def setUp(self):
        provider = patch("snapdart.llm.PROVIDER", "gemini")
        provider.start()
        self.addCleanup(provider.stop)

    def test_citation_schema_and_provenance_isolation(self):
        from snapdart.llm import citation_schema, model_context, SCHEMA
        evidence=[dict(id='current',year=2025,text='내용',source_ids=['old'])]
        schema=citation_schema(SCHEMA,evidence)
        self.assertEqual(schema['properties']['cards']['items']['properties']['evidence_ids']['items']['enum'],['current'])
        self.assertNotIn('enum',SCHEMA['properties']['cards']['items']['properties']['evidence_ids']['items'])
        self.assertNotIn('source_ids',model_context(dict(evidence=evidence))['evidence'][0])
        self.assertEqual(evidence[0]['source_ids'],['old'])

    def test_invalid_reference_repaired_once_with_budget(self):
        from snapdart.llm import request_report
        from unittest.mock import MagicMock
        value,evidence=fixture()
        bad=copy.deepcopy(value); bad['cards'][0]['evidence_ids']=['wrong']
        def response(report):
            result=MagicMock()
            result.__enter__.return_value.read.return_value=json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(report)}]}}]}).encode()
            return result
        with tempfile.TemporaryDirectory() as tmp, patch('snapdart.llm.DATA',Path(tmp)), patch('snapdart.llm.load_env'), patch.dict('os.environ',{'GEMINI_API_KEY':'fake'}), patch('snapdart.llm.count_input_tokens',return_value=100), patch('snapdart.llm.TOKEN_BUDGET.reserve') as reserve, patch('snapdart.llm.urlopen',side_effect=[response(bad),response(value)]) as api:
            self.assertEqual(request_report(dict(evidence=evidence),evidence)['report'],value)
            self.assertEqual(reserve.call_count,2)
            self.assertEqual(len(list((Path(tmp)/'llm_errors').glob('*.json'))),1)
            self.assertIn('correction',json.loads(json.loads(api.call_args.args[0].data)['contents'][0]['parts'][0]['text']))

    def test_invalid_reference_stops_after_one_repair(self):
        from snapdart.llm import request_report
        from unittest.mock import MagicMock
        value,evidence=fixture(); value['cards'][0]['evidence_ids']=['wrong']
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(value)}]}}]}).encode()
        with tempfile.TemporaryDirectory() as tmp, patch('snapdart.llm.DATA',Path(tmp)), patch('snapdart.llm.load_env'), patch.dict('os.environ',{'GEMINI_API_KEY':'fake'}), patch('snapdart.llm.count_input_tokens',return_value=100), patch('snapdart.llm.TOKEN_BUDGET.reserve'), patch('snapdart.llm.urlopen',return_value=response) as api:
            with self.assertRaisesRegex(RuntimeError,'검증 실패'):
                request_report(dict(evidence=evidence),evidence)
            self.assertEqual(api.call_count,2)

    def test_duplicate_text_keeps_dates_and_changed_text(self):
        original={'evidence':[
            dict(id='005930-2021-a',year=2021,text='투자 10억원'),
            dict(id='005930-2022-b',year=2022,text='투자 10억원'),
            dict(id='005930-2023-c',year=2023,text='투자 11억원'),
            dict(id='000660-2022-d',year=2022,text='투자 10억원')]}
        result=compact_context(original)['evidence']
        self.assertEqual(result[1]['text_ref'],'005930-2021-a')
        self.assertEqual(result[1]['year'],2022)
        self.assertNotIn('text',result[1])
        self.assertIn('text',result[2])
        self.assertIn('text',result[3])
        self.assertIn('text',original['evidence'][1])

    def test_token_window_waits_and_rejects_oversized_request(self):
        now=[0.0]
        def sleep(seconds): now[0]+=seconds
        with patch('snapdart.llm.time.monotonic',side_effect=lambda:now[0]), patch('snapdart.llm.time.sleep',side_effect=sleep), patch.dict('os.environ',{'GEMINI_TPM_BUDGET':'225000'}):
            limiter=TokenBudget()
            limiter.reserve(110000)
            self.assertEqual(now[0],61)
            limiter.reserve(110000)
            self.assertEqual(now[0],122)
            with self.assertRaisesRegex(RuntimeError,'단일 요청'):
                limiter.reserve(250000)

    def test_count_tokens_includes_system_and_schema(self):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"totalTokens":1234}'
        payload=dict(systemInstruction={'parts':[{'text':'rules'}]},contents=[],generationConfig={'responseJsonSchema':{'type':'object'}})
        with patch('snapdart.llm.urlopen',return_value=response) as call:
            self.assertEqual(count_input_tokens(payload,'fake-test-key'),1234)
        sent=json.loads(call.call_args.args[0].data)['generateContentRequest']
        self.assertEqual(sent['systemInstruction'],payload['systemInstruction'])
        self.assertEqual(sent['generationConfig'],payload['generationConfig'])

    def test_all_periods_reach_model_with_unique_ids(self):
        filings = [dict(period='2025-'+month, rcept_no=str(i), report_nm=name)
                   for i, (month, name) in enumerate([('03','분기보고서'),('06','반기보고서'),('09','분기보고서'),('12','사업보고서')])]
        with tempfile.TemporaryDirectory() as tmp, patch('snapdart.retrieval.DATA',Path(tmp)):
            folder=Path(tmp)/'test'; folder.mkdir()
            (folder/'filings.json').write_text(json.dumps(filings),encoding='utf-8')
            texts=['수요 관련 설명입니다. '*10, '설비투자를 중단한다고 설명했습니다. '*10,
                   '생산능력 관련 설명입니다. '*10, 'HBM 사업 관련 설명입니다. '*10]
            with patch('snapdart.retrieval.business_text',side_effect=texts):
                context=company_context(dict(code='test',name='회사',sector='장비',history=[]))
            evidence=context['evidence']
            self.assertEqual({e['period'] for e in evidence},{f['period'] for f in filings})
            self.assertEqual(len({e['id'] for e in evidence}),len(evidence))
            self.assertIn('중단', ' '.join(e['text'] for e in evidence))
            self.assertTrue(next(e for e in evidence if e['period']=='2025-06')['changed_text'])

    def test_changed_passage_has_reserved_space(self):
        old='\n'.join('HBM 수요 설비투자 리스크 설명 '+str(i)+' '+('기존 내용입니다. '*10) for i in range(30))
        new='설비투자 중단이 결정되었다고 회사는 설명합니다. '*8
        passages=select_passages(old+'\n'+new+'\n'+old,previous_text=old)
        self.assertLessEqual(len(passages),20)
        self.assertIn(new.strip(),passages)

    def test_unknown_references_rejected(self):
        value,evidence=fixture()
        value['cards'][0]['evidence_ids']=['invented']
        with self.assertRaisesRegex(ValueError,'근거 ID'):
            validate_report(value,evidence)

    def test_timeline_cannot_use_later_year(self):
        value,evidence=fixture()
        value['timeline'][0]['evidence_ids']=['e-2025']
        with self.assertRaisesRegex(ValueError,'연도 불일치'):
            validate_report(value,evidence)

    def test_missing_duplicate_years_rejected(self):
        value,evidence=fixture()
        value['timeline'][1]=copy.deepcopy(value['timeline'][0])
        with self.assertRaisesRegex(ValueError,'누락 또는 중복'):
            validate_report(value,evidence)

    def test_review_cache_reuse_and_input_change(self):
        value,evidence=fixture()
        context=dict(evidence=evidence)
        response=dict(report=value,usage={},model='test')
        with tempfile.TemporaryDirectory() as tmp, patch('snapdart.llm.DATA',Path(tmp)), patch('snapdart.llm.request_report',side_effect=lambda *a,**kw: copy.deepcopy(response)) as request:
            _,hit=cached_report(context,evidence)
            self.assertFalse(hit)
            self.assertEqual(request.call_count,2)
            _,hit=cached_report(context,evidence)
            self.assertTrue(hit)
            self.assertEqual(request.call_count,2)
            cached_report(dict(context, changed=True),evidence)
            self.assertEqual(request.call_count,4)

    def test_review_failure_keeps_draft_for_retry(self):
        value,evidence=fixture()
        response=dict(report=value,usage={},model='test')
        with tempfile.TemporaryDirectory() as tmp, patch('snapdart.llm.DATA',Path(tmp)), patch('snapdart.llm.request_report',side_effect=[response,RuntimeError('review failed')]):
            with self.assertRaises(RuntimeError):
                cached_report(dict(evidence=evidence),evidence)
            cached=list(Path(tmp).rglob('*.json'))
            self.assertEqual(len(cached),1)
            self.assertNotIn('review_version',json.loads(cached[0].read_text(encoding='utf-8')))

    def test_retrieval_is_bounded_and_topic_diverse(self):
        text='\n'.join([f'{topic} 관련 문단 {i}입니다. '+('회사의 사업 내용과 시장 환경을 설명합니다. '*8) for topic in ['HBM','수요','설비투자','리스크'] for i in range(8)])
        passages=select_passages(text)
        self.assertLessEqual(len(passages),20)
        self.assertEqual(len(passages),len(set(passages)))
        self.assertTrue(all(len(p)<=1050 for p in passages))
        for keyword in ['HBM','수요','설비투자','리스크']:
            self.assertIn(keyword,' '.join(passages))

if __name__ == '__main__':
    unittest.main()
