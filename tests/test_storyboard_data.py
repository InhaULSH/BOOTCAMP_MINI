import unittest
from types import SimpleNamespace
from unittest.mock import patch
from snapdart.ui_project import quarter_rows,keywords

class FakeRepo:
    def __init__(self,missing=False):self.missing=missing
    def financial(self,code,year,report_type,basis='CFS',value_type=None):
        i=('Q1','H1','Q3','FY').index(report_type)
        value=None if self.missing and i==1 else (i+1)*100
        if value_type=='quarterly':value=None
        return dict(revenue=value,operating_income=value,capex=value,operating_cashflow=value,basis=basis)

class StoryboardTests(unittest.TestCase):
    def test_missing_direct_quarters_rebuild_cumulative(self):
        c={'code':'a','history':[{'year':2025,'basis':'CFS'}]}
        rows=quarter_rows(FakeRepo(),c,[2025])
        self.assertEqual([r['revenue'] for r in rows],[100]*4)
        self.assertEqual([r['period'] for r in rows],['2025 Q1','2025 Q2','2025 Q3','2025 Q4'])
    def test_missing_does_not_become_zero(self):
        c={'code':'a','history':[{'year':2025,'basis':'CFS'}]}
        rows=quarter_rows(FakeRepo(True),c,[2025])
        self.assertIsNone(rows[1]['revenue']);self.assertIsNone(rows[2]['revenue'])
    def test_frequency_is_not_importance(self):
        result=keywords({'wordcloud':{'2025':[{'text':'HBM','count':5}]}},2025)
        self.assertEqual(result[0]['count'],5);self.assertNotIn('importance',result[0])
    def test_upstream_importance_preserved(self):
        supplied=[dict(label='HBM',importance=.8,selectionReason='제공된 평가')]
        self.assertEqual(keywords({'keywords':supplied},2025),supplied)
    def test_keyword_summary_and_sources_preserved(self):
        insight={'sentences':[{'text':'공시에서 확인한 요약입니다.','source_refs':['t1']} ]}
        scope={'wordcloud':{'2025':[{'text':'HBM','count':5}]},
               'keyword_insights':{'2025':{'HBM':insight}}}
        result=keywords(scope,2025)
        self.assertEqual(result[0]['insight'],insight)
        self.assertNotIn('importance',result[0])
        self.assertIsNone(keywords(scope,2024)[0]['insight'] if keywords(scope,2024) else None)
    def test_missing_keyword_evidence_does_not_call_gemini(self):
        from snapdart.data_access import pipeline
        from snapdart import llm
        repo=SimpleNamespace(search=lambda *a,**k:([],{}))
        with patch.object(llm,'request_report') as request:
            result=pipeline.generate({},dict(companies=[],years=[2025]),repo,keyword='없는 키워드')
        request.assert_not_called()
        self.assertEqual(result['sentences'],[])
