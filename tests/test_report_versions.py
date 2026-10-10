"""Offline report selection: no database or model access."""
import copy
import os
import unittest
from unittest.mock import patch
from dart_remote import artifacts

class ReportVersionTests(unittest.TestCase):
    def setUp(self):
        self.store={}
        def read(sector,kind,key='current'):
            return copy.deepcopy(self.store.get((sector,kind,key)))
        def write(sector,kind,payload,key='current',generation=None):
            self.store[sector,kind,key]=copy.deepcopy(payload);return True
        self.patches=[patch.object(artifacts,'get_artifact',side_effect=read),
                      patch.object(artifacts,'put_artifact',side_effect=write),
                      patch.dict(os.environ,{'REPORT_PROMPT_VERSION':'new'})]
        for item in self.patches:item.start();self.addCleanup(item.stop)
    def report(self,text):
        return {'companies':[],'ai_insights':{},'citations':{'r':text},'text':text}
    def test_versions_and_sectors_remain_independent(self):
        for version in ('new','new2','old'):
            artifacts.publish_report('s',self.report(version),version)
        artifacts.publish_report('s',self.report('latest new'),'new')
        artifacts.publish_report('t',self.report('other'),'new')
        for version,text in [('new','latest new'),('new2','new2'),('old','old')]:
            with patch.dict(os.environ,{'REPORT_PROMPT_VERSION':version}):
                result=artifacts.selected_report('s')
                self.assertEqual(result['text'],text)
                self.assertEqual(result['citations'],{'r':text})
    def test_missing_version_does_not_fall_back(self):
        artifacts.publish_report('s',self.report('new'),'new')
        with patch.dict(os.environ,{'REPORT_PROMPT_VERSION':'old'}):
            self.assertIsNone(artifacts.selected_report('s'))
    def test_legacy_inference_and_retention(self):
        old=self.report('legacy')
        old['ai_insights']={'2024':{'prompt_version':'bigin-pdf-v7-shared-industry-factors'}}
        self.store['s','report','current']=old
        with patch.dict(os.environ,{'REPORT_PROMPT_VERSION':'old'}):
            self.assertEqual(artifacts.selected_report('s')['text'],'legacy')
        artifacts.publish_report('s',self.report('new'),'new')
        with patch.dict(os.environ,{'REPORT_PROMPT_VERSION':'old'}):
            self.assertEqual(artifacts.selected_report('s')['text'],'legacy')
    def test_unidentified_or_mixed_legacy_is_not_used(self):
        legacy=self.report('unknown')
        self.store['s','report','current']=legacy
        self.assertIsNone(artifacts.selected_report('s'))
        legacy['ai_insights']={'2024':{'prompt_version':'bigin-user-v4'},'2023':{'prompt_version':'bigin-pdf-v7'}}
        self.assertIsNone(artifacts.identify_report(legacy))
    def test_non_llm_build_does_not_replace_success(self):
        artifacts.publish_report('s',self.report('success'),'new')
        artifacts.publish_report('s',self.report('excerpt'))
        self.assertEqual(artifacts.selected_report('s')['text'],'success')
    def test_home_uses_selected_report_and_keeps_market_shared(self):
        for version,code in [('new','1'),('new2','2')]:
            report=self.report(version);report['companies']=[{'code':code}]
            artifacts.publish_report('s',report,version)
        self.store['s','market','current']={'index':{'name':'same index','history':[]}}
        with patch.dict(os.environ,{'SERVICE_GCS_BUCKET':'test'}):
            for version,code in [('new','1'),('new2','2')]:
                with patch.dict(os.environ,{'REPORT_PROMPT_VERSION':version}):
                    home=artifacts.home_summary('s')
                    self.assertEqual(home['entries'],['s:'+code])
                    self.assertEqual(home['indexName'],'same index')
    def test_pipeline_keeps_dataset_validation_and_never_generates(self):
        from types import SimpleNamespace
        from snapdart.data_access import pipeline
        repo=SimpleNamespace(sector=SimpleNamespace(id='s'),fingerprint=lambda:'current')
        report=self.report('saved');report['source']={'dataset_sha256':'current'}
        artifacts.publish_report('s',report,'new')
        with patch.object(pipeline,'Repository',return_value=repo),patch.object(pipeline,'generate') as generate,patch('dart_remote.wordcloud.apply',side_effect=lambda report,repo:report):
            self.assertEqual(pipeline.load_report('s')['text'],'saved')
            repo.fingerprint=lambda:'changed'
            with self.assertRaisesRegex(RuntimeError,'DB 데이터 버전'):pipeline.load_report('s')
            with patch.dict(os.environ,{'REPORT_PROMPT_VERSION':'old'}):
                with self.assertRaisesRegex(RuntimeError,'old 버전'):pipeline.load_report('s')
            generate.assert_not_called()
    def test_invalid_selection_rejected(self):
        with patch.dict(os.environ,{'REPORT_PROMPT_VERSION':'typo'}):
            with self.assertRaises(ValueError):artifacts.report_version()
    def test_prefix_identification(self):
        for identifier,version in [('bigin-user-2026-v4','new'),('bigin-user-2026-new2-v1','new2')]:
            report=self.report('x');report['ai_insights']={'2024':{'prompt_version':identifier}}
            self.assertEqual(artifacts.identify_report(report),version)

if __name__=='__main__':unittest.main()
