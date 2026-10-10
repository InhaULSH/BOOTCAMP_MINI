import unittest
from dataclasses import replace
from unittest.mock import patch
import pandas as pd
from dart_remote.dart_signal_wordcloud import SignalConfig,_result_from_counts
from dart_remote.wordcloud import eligible,display
from dart_remote.test_signal_sector_isolation import SectorIsolationTests

class SignalTests(unittest.TestCase):
    def test_change_uses_every_year_in_long_history(self):
        config=SignalConfig('KRX_SEMI',years=(2021,2022,2023,2024,2025))
        counts={'HBM':{2021:0,2022:2,2023:2,2024:2,2025:2}}
        r=_result_from_counts(counts,{'HBM':{'a':1,'b':1}},{'a':5,'b':5},pd.Series({y:10 for y in config.years}),config,2)
        self.assertAlmostEqual(r.iloc[0].change_raw,0.4/2.0*0.2)
        self.assertEqual(display(r,config)[0]['years'],list(config.years))

    def test_one_or_two_years_are_supported(self):
        for years,expected in [((2025,),0),((2024,2025),.1)]:
            config=SignalConfig('KRX_SEMI',years=years)
            r=_result_from_counts({'HBM':{2024:1,2025:2}},{'HBM':{'a':1,'b':1}},{'a':5,'b':5},pd.Series({y:10 for y in years}),config,2)
            self.assertAlmostEqual(r.iloc[0].change_raw,expected)

    def test_chunk_share_scoring_and_penalties(self):
        config=SignalConfig('KRX_SEMI')
        counts={'HBM':{2023:1,2024:2,2025:4},'DRAM':{2023:4,2024:3,2025:2},'SSD':{2025:2}}
        companies={'HBM':{'a':3,'b':1},'DRAM':{'a':1,'b':1},'SSD':{'a':2}}
        r=_result_from_counts(counts,companies,{c:2 for c in "abcde"},pd.Series({2023:10,2024:10,2025:10}),config,5)
        self.assertNotIn('SSD',set(r.keyword))
        h=r.set_index('keyword').loc['HBM']
        self.assertAlmostEqual(h.change_raw,.16)
        self.assertAlmostEqual(h.concentration_penalty,7.5)
        self.assertAlmostEqual(h.spread_score,.6*40+.4*h.entropy_score)
        self.assertAlmostEqual(h.final_signal_score,.5*h.current_score+.3*h.change_score+.2*h.spread_score-7.5)
        self.assertEqual(display(r,config)[0]['text'],r.iloc[0].keyword)
        from snapdart.ui_project import keywords
        shown=keywords({'wordcloud':{'2025':display(r,config)}},2025)
        self.assertIn('현재 언급 점수',shown[0]['selectionReason'])
        self.assertEqual(shown[0]['signalScore'],r.iloc[0].final_signal_score)
        self.assertEqual(shown[0]['final_signal_score'],r.iloc[0].final_signal_score)
        self.assertEqual(shown[0]['display_weight'],100)
        self.assertEqual(shown[0]['is_hot'],bool(r.iloc[0].is_hot))
    def test_display_weights_top_n_and_equal_scores(self):
        from dart_remote.dart_signal_wordcloud import add_display_weights
        scores=pd.DataFrame({'final_signal_score':[90.,80.,70.]})
        weights=add_display_weights(scores).display_weight.tolist()
        self.assertEqual(weights,[100.,52.75,30.])
        self.assertEqual(add_display_weights(scores.iloc[:1]).display_weight.tolist(),[100.])
        tied=pd.DataFrame({'final_signal_score':[80.,80.,80.]})
        self.assertEqual(add_display_weights(tied).display_weight.tolist(),[100.,65.,30.])
    def test_company_uses_dedicated_scorer(self):
        from dart_remote.dart_company_signal_wordcloud import CompanySignalConfig,_result_from_counts as company_counts
        config=CompanySignalConfig('a',sector_index_code='KRX_SEMI')
        r=company_counts({'HBM':{2025:2}},pd.Series({2023:2,2024:2,2025:2}),config)
        self.assertEqual(len(r),1)
        self.assertNotIn('concentration_penalty',r.columns)
    def test_section_policy(self):
        row=dict(report_type='H1',section_name='II. 사업의 내용',subsection_name='기타 참고사항')
        self.assertTrue(eligible(row))
        row['section_name']='III. 재무에 관한 사항'
        self.assertFalse(eligible(row))
        row['subsection_name']='연구개발실적 상세표'
        self.assertTrue(eligible(row))

if __name__=='__main__':unittest.main()
