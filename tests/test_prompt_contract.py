"""Prompt fidelity and citation validation without calling a model API."""
import copy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from snapdart_data import pipeline, prompts


class PromptContractTests(unittest.TestCase):
    def generate(self, sentences, filing_count=1, financial_values=None, company_scope=False):
        captured = {}
        def request(context, evidence, **options):
            captured.update(options)
            value = options['validator']({'sentences': sentences}, evidence)
            return {'report': value}
        llm = types.SimpleNamespace(PROVIDER='test', MODEL='test', TEXT={'type': 'string'},
            object_schema=lambda props: {'type': 'object', 'properties': props}, request_report=request)
        package = types.ModuleType('snapdart')
        package.llm = llm
        row = dict(year=2025, basis='CFS', revenue=None, operating_income=None,
            capex=None, operating_cashflow=None, yoy={}, margin=None, fcf=None, financial_sources={})
        row.update(financial_values or {})
        companies = [dict(code=str(i), name=name, history=[copy.deepcopy(row)])
            for i, name in enumerate(('기업가', '기업나'))]
        report = dict(companies=companies, years=[2025], citations={})
        repo = types.SimpleNamespace(sector=types.SimpleNamespace(id='test', name='테스트'),
            financial=lambda *a, **k: dict(row, report_type=a[2]))
        evidence = dict(sector_id='test', chunk_id='chunk1', receipt_no='receipt',
            company='기업가', year=2025, period='2025-12', report_name='사업보고서',
            section='사업', heading='현황', text='입력 공시의 사업 변화 설명', anchor_start=0)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent/'tmp') as folder, \
             patch.dict(sys.modules, {'snapdart': package}), \
             patch.object(pipeline, 'SERVICE', Path(folder)), \
             patch.object(pipeline, 'evidence_rows', return_value=[dict(evidence,chunk_id='chunk'+str(i)) for i in range(filing_count)]):
            result = pipeline.generate(report, report, repo, company=companies[0] if company_scope else None,force=True)
        if captured:captured['citations']=report['citations']
        return result, captured

    def test_no_company_name_or_two_company_evidence_requirement(self):
        result, captured = self.generate([
            {'text': '제공된 자료에서 제품 구성이 달라졌습니다.', 'refs': ['t1']},
            {'text': '산업 공통 흐름을 판단할 근거는 충분하지 않습니다.', 'refs': ['t1']},
        ])
        self.assertEqual(len(result['sentences']), 2)
        self.assertEqual(captured['instruction'], prompts.COMMON+'\n'+prompts.INSIGHT)
        self.assertEqual(captured['temperature'], 1)
        self.assertEqual(captured['max_output_tokens'], 500)

    def test_no_added_character_limit_or_phrase_ban(self):
        text = '제공된 공시 내용을 바탕으로 변화를 설명합니다. ' * 12
        result, _ = self.generate([
            {'text': text+'공시에 확인된 개선에 힘입어 구성이 바뀌었습니다.', 'refs': ['t1']},
            {'text': text, 'refs': ['t1']},
        ])
        self.assertGreater(sum(len(s['text']) for s in result['sentences']), 400)

    def test_unknown_citation_still_rejected(self):
        with self.assertRaisesRegex(ValueError, '입력에 없는 근거 ID'):
            self.generate([{'text': '사업 변화입니다.', 'refs': ['missing']},
                {'text': '자료의 한계입니다.', 'refs': ['t1']}])

    def test_industry_user_task_comes_from_definition(self):
        task = prompts.context('반도체', [], [])['task']
        self.assertIn('위 데이터를 바탕으로 반도체 산업에서 나타나는 주요 흐름을 분석하세요.', task)
        self.assertNotIn('최소 두', prompts.instruction())
        self.assertNotIn('400', prompts.instruction())

    def test_four_filing_references_need_no_financial_reference(self):
        result, captured = self.generate([
            {'text': '공시에서 공통 사업 변화를 확인했습니다.', 'refs': ['t1','t2','t3','t4']},
            {'text': '자료의 한계로 원인을 단정하지 않습니다.', 'refs': []},
        ],filing_count=4)
        self.assertEqual(len(result['sentences'][0]['source_refs']),4)
        refs_schema=captured['schema']['properties']['sentences']['items']['properties']['refs']
        self.assertNotIn('maxItems',refs_schema)
        self.assertNotIn('minItems',refs_schema)

    def test_financial_only_input_can_explain_disclosure_limit(self):
        result, _ = self.generate([
            {'text':'제공된 재무자료에 매출 변화가 있습니다.','refs':['f1']},
            {'text':'공시 근거가 부족해 변화의 원인을 판단하기 어렵습니다.','refs':[]},
        ],filing_count=0,financial_values={'revenue':10000})
        self.assertEqual(len(result['sentences']),2)

    def test_no_material_returns_pdf_data_limit_without_model_call(self):
        result, captured=self.generate([],filing_count=0)
        self.assertFalse(captured)
        self.assertEqual(result['sentences'][0]['text'],'확인 가능한 데이터가 부족합니다.')

    def test_company_prompt_has_no_invented_sentence_count(self):
        result,captured=self.generate([{'text':'기업의 사업 현황입니다.','refs':['t1']}],company_scope=True)
        self.assertEqual(len(result['sentences']),1)
        self.assertNotIn('maxItems',captured['schema']['properties']['sentences'])

    def test_money_sign_and_arbitrary_amount_are_rejected(self):
        for text in ('영업이익은 1,234원입니다.','영업이익은 -1,200원입니다.'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError,'금액'):
                self.generate([{'text':text,'refs':['f2']}, {'text':'근거의 한계를 확인합니다.','refs':[]}],financial_values={'operating_income':-1234})

    def test_negative_money_preserves_the_input_sign(self):
        result,_=self.generate([{'text':'영업이익은 -1,234원입니다.','refs':['f2']}, {'text':'근거의 한계를 확인합니다.','refs':[]}],financial_values={'operating_income':-1234})
        self.assertEqual(len(result['sentences']),2)

    def test_midyear_financial_reference_keeps_its_report_type(self):
        result,captured=self.generate([{'text':'반기 재무자료에 변화가 있습니다.','refs':['f4']}, {'text':'원인은 공시 근거로 확인해야 합니다.','refs':[]}],financial_values={'revenue':10000})
        ref=result['sentences'][0]['source_refs'][0]
        citation=captured['citations'][ref]
        self.assertEqual(citation['report_type'],'H1')
        self.assertEqual(citation['period'],'2025-06')
        self.assertEqual(citation['report_name'],'반기보고서')


if __name__ == '__main__':
    unittest.main()
