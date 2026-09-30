import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from snapdart import hierarchy, llm


class HierarchyTests(unittest.TestCase):
    def test_long_passage_split_without_loss(self):
        text = '가나다123'*1000
        chunks = list(hierarchy.batches([dict(id='005930-a', year=2025, period='2025-03', text=text)], 2500))
        entries = [e for batch in chunks for e in batch]
        self.assertEqual(''.join(e['text'] for e in entries), text)
        self.assertEqual(len({e['id'] for e in entries}), len(entries))
        self.assertTrue(all(sum(len(json.dumps(e,ensure_ascii=False)) for e in b)<=2500 for b in chunks))

    def test_period_year_reduction_cache_and_financial_preservation(self):
        evidence = [dict(id=f'005930-{y}-{m}', year=y, period=f'{y}-{m}', text=f'{y} {m} 투자 계획')
                    for y in llm.YEARS for m in ['03','06','09','12']]
        financial = dict(id='005930-financial',year=2025,values={'revenue':123})
        calls=[]
        def fake(context, entries, **kwargs):
            calls.append(context)
            return dict(report={'items':[dict(text='회사가 해당 기간에 투자를 계획했다고 설명했습니다.',evidence_ids=[entries[0]['id']])]}, usage={})
        with tempfile.TemporaryDirectory() as tmp, patch.object(llm,'DATA',Path(tmp)), patch.object(llm,'request_report',side_effect=fake):
            context=dict(company='회사',evidence=evidence+[financial])
            reduced=hierarchy.reduce_company(context)
            self.assertEqual(len(calls),25)
            self.assertEqual(len(reduced['evidence']),6)
            self.assertEqual(reduced['evidence'][-1],financial)
            hierarchy.reduce_company(context)
            self.assertEqual(len(calls),25)
            self.assertTrue(all('inputs' in json.loads(p.read_text(encoding='utf-8')) for p in Path(tmp).rglob('*.json')))

    def test_actual_token_overflow_splits_before_retry(self):
        entries=[dict(id=f'005930-{i}',year=2025,text='내용') for i in range(4)]
        def fake(context, evidence, **kw):
            if len(evidence)>2:
                raise llm.InputTooLarge('too large')
            return dict(report={'items':[dict(text='분할 요약',evidence_ids=[evidence[0]['id']])]},usage={})
        with tempfile.TemporaryDirectory() as tmp, patch.object(llm,'DATA',Path(tmp)), patch.object(llm,'request_report',side_effect=fake):
            self.assertEqual(len(hierarchy.summarize(entries,'test')),2)

    def test_unknown_summary_reference_rejected(self):
        with self.assertRaises(ValueError):
            hierarchy.validate({'items':[dict(text='내용',evidence_ids=['bad'])]},[dict(id='good')])
