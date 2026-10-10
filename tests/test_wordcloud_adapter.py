import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
import pandas as pd
from dart_remote.wordcloud import apply,display
from dart_remote.dart_company_signal_wordcloud import CompanySignalConfig


class WordcloudAdapterTests(unittest.TestCase):
    def test_missing_early_year_still_calls_company_scorer(self):
        repo=Mock();repo.sector=SimpleNamespace(membership_code='KRX_SEMI',id='반도체')
        repo.fingerprint.return_value='snapshot'
        repo.company.return_value=dict(corp_code='a',corp_name='회사')
        repo.chunks.side_effect=lambda code,y: [] if y==2023 else [dict(chunk_id=str(y),corp_code='a',year=y,
            chunk_text='HBM 수요와 설비투자 확대',vector_id=y,section_name='II. 사업의 내용',report_type='FY')]
        report=dict(years=[2023,2024,2025],companies=[dict(code='A')],source={})
        with patch('dart_remote.wordcloud.db.rows',return_value=[dict(stock_code='A',corp_code='a',corp_name='회사',weight=1)]),patch('dart_remote.wordcloud.artifacts.get_artifact',return_value=None),patch('dart_remote.wordcloud.artifacts.put_artifact'),patch('dart_remote.wordcloud.score_database_company_keywords_v2',return_value=pd.DataFrame()) as score,patch('dart_remote.wordcloud.score_keywords',return_value=pd.DataFrame()):
            apply(report,repo)
        score.assert_called_once()
        self.assertEqual(list(score.call_args.kwargs['chunks']['year']),[2024,2025])
        self.assertEqual(report['wordcloud_signal']['companies']['A']['missing_years'],[2023])

    def test_company_serializer_retains_ui_and_llm_fields(self):
        row=dict(keyword='HBM',count_2025=3,rate_2025=.3,current_score=80,change_score=90,change_raw=.1,
            diversity_score=70,signal_score=80,final_signal_score=80,final_rank=1,is_hot=False,
            generic_business_penalty=0)
        item=display(pd.DataFrame([row]),CompanySignalConfig('a',sector_index_code='KRX_SEMI'))[0]
        self.assertEqual(item['text'],'HBM');self.assertEqual(item['count'],3)
        self.assertEqual(item['scope'],'company');self.assertEqual(item['company_count'],1)
        self.assertIsInstance(item['display_weight'],float)
        self.assertIsInstance(item['is_hot'],bool)
