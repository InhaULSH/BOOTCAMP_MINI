"""Exercise report-period comparisons through the actual service-facing engines."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd
from dart_remote import dart_signal_wordcloud as industry
from dart_remote import dart_company_signal_wordcloud as company
from dart_remote.wordcloud import display


class Extractor:
    def __init__(self, *args):pass
    def extract_many(self, texts):
        return [{'HBM'} if 'HBM' in text else set() for text in texts]


class CompanyExtractor:
    def __init__(self, names, vocabulary, stopwords, roles):
        self.vocabulary=vocabulary;self.company_names=set(names);self.configured_terms=set()
    def register_entity_aliases(self, texts):pass
    def has_sector_context(self, text):return True
    def _accept(self, word):return True
    def extract_many(self, texts):
        result=[]
        for text in texts:
            observation=company.CandidateObservation()
            if 'HBM' in text:
                observation.direct['HBM'].add(('protected_tech','configured tech','test'))
            result.append(observation)
        return result


def corpus():
    # Full 2025-year rate is deliberately unlike 2025's Q1/H1-only rate.
    rows=[]
    for code in ('a','b'):
        for year,kinds in ((2023,('FY',)),(2024,('FY',)),
                           (2025,('Q1','H1','Q3','FY')),(2026,('Q1','H1'))):
            for kind in kinds:
                hits=2 if year==2026 or (year==2025 and kind in ('Q3','FY')) else 1
                for n in range(5):
                    i=len(rows)
                    rows.append(dict(chunk_id=str(i),vector_id=i,corp_code=code,year=year,
                        report_type=kind,section_name='II. 사업의 내용',
                        chunk_text='HBM 생산' if n<hits else '일반 설명'))
    return pd.DataFrame(rows)


class ComparablePeriodTests(unittest.TestCase):
    def test_industry_repository_corpus_uses_same_report_types(self):
        config=industry.SignalConfig('KRX_SEMI')
        members=pd.DataFrame([dict(corp_code=c,corp_name=c) for c in ('a','b')])
        with patch.object(industry,'KeywordExtractor',Extractor),patch.object(industry,'query',side_effect=AssertionError('unexpected DB query')):
            result=industry.score_keywords(corpus(),config,members)
        row=result.iloc[0]
        self.assertAlmostEqual(row.rate_2025,.3)
        self.assertAlmostEqual(row.comparable_rate_2025,.2)
        self.assertAlmostEqual(row.comparable_rate_2026,.4)
        self.assertAlmostEqual(row.change_raw,.144)
        shown=display(result,config)[0]
        self.assertAlmostEqual(shown['comparable_rate_2025'],.2)

    def test_company_repository_corpus_has_no_unscoped_DB_read(self):
        config=company.CompanySignalConfig('a','KRX_SEMI')
        with patch.object(company,'CompanyCandidateExtractorV2',CompanyExtractor),patch.object(company,'query',side_effect=AssertionError('unexpected DB query')):
            result=company.score_database_company_keywords_v2(config,'会社',chunks=corpus())
        row=result.iloc[0]
        self.assertEqual(row.count_2026,4)
        self.assertAlmostEqual(row.comparable_rate_2025,.2)
        self.assertAlmostEqual(row.change_raw,.144)

    def test_disjoint_report_types_do_not_fall_back_to_full_year(self):
        frame=pd.DataFrame([dict(keyword='HBM',rate_2023=.1,rate_2024=.2,rate_2025=.9)])
        change=industry._change_raw_from_comparable_periods(frame,pd.Series({2023:10,2024:10,2025:10}),
                 (2023,2024,2025),{}, {(2024,'FY'):10,(2025,'H1'):10},())
        self.assertAlmostEqual(change.iloc[0],.1)

    def test_nonconsecutive_years_do_not_create_growth(self):
        frame=pd.DataFrame([dict(keyword='HBM',rate_2023=.1,rate_2025=.9)])
        result=industry._change_raw_from_comparable_periods(frame,pd.Series({2023:10,2025:10}),(2023,2025))
        self.assertEqual(result.iloc[0],0)

    def test_missing_early_industry_year_stays_missing(self):
        config=industry.SignalConfig('KRX_SEMI',years=(2023,2024,2025))
        result=industry._result_from_counts({'HBM':{2024:2,2025:4}},
            {'HBM':{'a':2,'b':2}},{'a':5,'b':5},pd.Series({2023:0,2024:10,2025:10}),config,2)
        self.assertTrue(pd.isna(result.iloc[0].count_2023))
        self.assertAlmostEqual(result.iloc[0].change_raw,.2)

    def test_diagnostic_where_preserves_approved_release(self):
        selection=dict(selected=dict(data_version='approved-physical-version'))
        with patch('dart_remote.release_selection.resolve',return_value=selection):
            i_where,i_params=industry._analysis_where(industry.SignalConfig('KRX_SEMI'),pd.DataFrame([dict(corp_code='a')]))
            c_where,c_params=company._analysis_where(company.CompanySignalConfig('a','KRX_SEMI'))
        for where,params in ((i_where,i_params),(c_where,c_params)):
            self.assertIn('data_version = %s',where)
            self.assertIn('approved-physical-version',params)


if __name__=='__main__':unittest.main()
