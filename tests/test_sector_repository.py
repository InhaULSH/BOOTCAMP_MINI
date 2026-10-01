import json
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing
import unittest
from unittest.mock import patch
import numpy as np
from snapdart_data.catalog import sectors,connect
from snapdart_data.repository import Repository
from snapdart_data.pipeline import financial_history

def fixture(folder,revenue):
    folder.mkdir()
    with closing(sqlite3.connect(folder/'financial.db',isolation_level=None)) as c:
        c.executescript('''CREATE TABLE companies(corp_code TEXT,company_name TEXT,stock_code TEXT);
            CREATE TABLE periods(year INTEGER,report_type TEXT);
            CREATE TABLE financial_facts_final(corp_code TEXT,year INTEGER,report_type TEXT,fs_div TEXT,
             value_type TEXT,sj_div TEXT,currency TEXT,standard_account_nm TEXT,account_id TEXT,
             cash_outflow_amount INTEGER,normalized_value INTEGER,calculated_value INTEGER,is_calculated INTEGER,
             rcept_no TEXT,original_account_nm TEXT);''')
        c.execute('INSERT INTO companies VALUES(?,?,?)',('00000001','같은기업','123456'))
        for year in (2023,2024):
            c.execute('INSERT INTO periods VALUES(?,?)',(year,'FY'))
            for name,amount,section in [('매출액',revenue,'IS'),('영업이익',-10 if year==2023 else 10,'IS'),('영업활동현금흐름',100,'CF'),('유형자산취득(CAPEX)',20,'CF')]:
                c.execute('INSERT INTO financial_facts_final VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('00000001',year,'FY','CFS','annual',section,'KRW',name,'account',20 if 'CAPEX' in name else None,amount,None,0,'20240101000001',name))
    with closing(sqlite3.connect(folder/'filings.db',isolation_level=None)) as c:
        c.execute('''CREATE TABLE filing_chunks(chunk_id TEXT,corp_name TEXT,corp_code TEXT,year INTEGER,
            report_type TEXT,rcept_no TEXT,section_name TEXT,subsection_name TEXT,source_file TEXT,
            chunk_text TEXT,content_hash TEXT,embedding BLOB,embedding_model TEXT,dimensions INTEGER,selection_reason TEXT)''')
        for i,(text,vector) in enumerate([('고객 수요에 대응하는 설비투자 계획입니다. 사업 생산 계획입니다.',[1,0]),('전혀 관계없는 이사회 정보입니다.',[0,1])]):
            c.execute('INSERT INTO filing_chunks VALUES('+','.join('?'*15)+')',(str(i),'같은기업','00000001',2024,'FY','20240101000001','II. 사업의 내용',None,'untrusted/path',text,'hash',np.array(vector,dtype='<f4').tobytes(),'fixture-model',2,'narrative'))

class SectorRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        fixture(self.root/'A',123);fixture(self.root/'B',999)
        self.a,self.b=sectors(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_sector_isolation_same_company(self):
        self.assertEqual(Repository(self.a).financial('123456',2024)['revenue'],123)
        self.assertEqual(Repository(self.b).financial('123456',2024)['revenue'],999)
    def test_readonly(self):
        with connect(self.a.financial) as c:
            with self.assertRaises(sqlite3.OperationalError):c.execute('DELETE FROM companies')
        missing=self.root/'not-there.db'
        with self.assertRaises(sqlite3.OperationalError):connect(missing)
        self.assertFalse(missing.exists())
    def test_no_negative_baseline_growth(self):
        rows=financial_history(Repository(self.a),'123456',[2023,2024])
        self.assertIsNone(rows[0]['yoy']['revenue']);self.assertIsNone(rows[1]['yoy']['operating_income'])
        self.assertEqual(rows[1]['yoy']['revenue'],0)
    def test_filter_and_no_irrelevant_vector_answer(self):
        repo=Repository(self.a)
        hits,status=repo.search('설비투자','123456',2024,'FY')
        self.assertEqual([r['chunk_id'] for r in hits],['0']);self.assertIn('vector',status['mode'])
        self.assertEqual(repo.search('없는단어','123456',2024,'FY')[0],[])
        self.assertEqual(repo.search('설비투자','123456',2023,'FY')[0],[])
    def test_unknown_company_and_sql_like_input(self):
        with self.assertRaises(KeyError):Repository(self.a).company("' OR 1=1 --")
    def test_wrong_vector_dimension_fails(self):
        with closing(sqlite3.connect(self.a.filings,isolation_level=None)) as c:c.execute('UPDATE filing_chunks SET dimensions=3')
        with self.assertRaises(ValueError):Repository(self.a).search('설비투자','123456',2024)
    def test_quarterly_is_not_annual_fallback(self):
        self.assertIsNone(Repository(self.a).financial('123456',2024,'Q1')['revenue'])

if __name__=='__main__':unittest.main()
