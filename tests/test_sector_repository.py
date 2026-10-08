"""Remote contract tests: synthetic rows, no remote writes or model calls."""
import os
import unittest
from unittest.mock import patch
from dart_remote.catalog import Sector
from dart_remote.repository import Repository
from dart_remote import db
from dart_remote.vector import rank

S=Sector('반도체','반도체','KRX_SEMI','test-v1:membership','index-v1')
def member(corp='c1',stock='000001'):
    return dict(corp_code=corp,stock_code=stock,corp_name='시험기업',company_name='시험기업',is_operational=1)
def chunk(text='HBM 수요의 변화',id='a'):
    return dict(chunk_id=id,vector_id=1,corp_code='c1',corp_name='시험기업',year=2024,report_type='FY',rcept_no='receipt',
        section_name='II. 사업의 내용',subsection_name='',chunk_text=text,content_hash='hash',embedding_model='BAAI/bge-m3',
        model_revision='rev',embedding_dimension=1024,dimensions=1024,index_version='index-v1',data_version='test-v1')

class SectorRepositoryTests(unittest.TestCase):
    def repo(self):
        r=Repository(S);r.members=[member()];return r
    def test_upstream_readonly(self):
        for sql in ('DELETE FROM companies','INSERT INTO companies VALUES(1)','CREATE TABLE x(a INT)'):
            with patch.object(db,'engine') as engine:
                with self.assertRaises(ValueError):db.rows(sql)
                engine.assert_not_called()
    def test_company_scope_and_bound_parameters(self):
        r=self.repo()
        with self.assertRaises(KeyError):r.company("' OR 1=1 --")
        def query(sql,params):
            self.assertIn('corp_code IN (:c0)',sql);self.assertEqual(params['c0'],'c1')
            self.assertIn('is_active=1',sql);self.assertIn('is_searchable=1',sql)
            self.assertEqual(params['version'],'test-v1');self.assertEqual(params['report_type'],'H1')
            self.assertNotIn('embedding,',sql);return [chunk()]
        with patch.object(db,'rows',side_effect=query):r.chunks('000001',2024,'HY')
    def test_actual_view_value_used_even_when_calculated(self):
        r=self.repo();base=dict(corp_code='c1',year=2024,report_type='FY',fs_div='CFS',value_type='annual',sj_div='CF',
            standard_account='유형자산취득(CAPEX)',value=23,value_source='derived',currency='KRW',account_id='x',is_calculated=1,original_account_nm='취득')
        # The second query is the operating-profit fallback, not a CAPEX row.
        with patch.object(db,'rows',side_effect=[[base],[],[dict(present=1)]]) as query:
            result=r.financial('000001',2024)
            self.assertEqual(result['capex'],23);self.assertIsNone(result['revenue'])
            self.assertIn('standardized_financials',query.call_args_list[0].args[0])
            self.assertIsNone(r.financial('000001',2024,'Q1')['capex'])
    def test_missing_and_conflict_are_not_zero_or_arbitrary(self):
        r=self.repo();row=dict(sj_div='IS',currency='KRW',standard_account_nm='매출액',value=12)
        self.assertEqual(r.metric([],'revenue'),(None,[]))
        with self.assertRaises(ValueError):r.metric([row,dict(row,value=20)],'revenue')
    def test_keyword_mode_does_not_claim_semantic_search(self):
        r=self.repo()
        with patch.dict(os.environ,{'SEARCH_BACKEND':'keyword'}),patch.object(r,'chunks',return_value=[chunk(),chunk('이사회 개최','b')]),patch.object(r,'coverage',return_value={}):
            hits,status=r.search('HBM','000001',2024,'FY')
            self.assertEqual([h['chunk_id'] for h in hits],['a']);self.assertEqual(status['mode'],'mysql-keyword-only')
            self.assertEqual(r.search('없는단어','000001',2024)[0],[])
if __name__=='__main__':unittest.main()
