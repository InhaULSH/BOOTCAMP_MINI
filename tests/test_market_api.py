import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch,MagicMock
from urllib.error import HTTPError
from snapdart import krx_api
from snapdart.market import close_snapshot

class MarketApiTests(unittest.TestCase):
    def test_today_excluded_and_weekend_last_session(self):
        history=[dict(date='2026-10-01',value=100),dict(date='2026-10-02',value=110),dict(date='2026-10-03',value=999)]
        result=close_snapshot(history,date(2026,10,3))
        self.assertEqual(result['price'],110)
        self.assertEqual(result['traded_at'],'2026-10-02')
        self.assertAlmostEqual(result['change'],10)
        self.assertEqual(close_snapshot(history[:2],date(2026,10,5))['traded_at'],'2026-10-02')
    def test_duplicate_dates_not_false_comparison(self):
        with self.assertRaises(RuntimeError):close_snapshot([dict(date='2026-10-01',value=100)]*2,date(2026,10,2))
    def response(self,rows):
        stream=MagicMock();stream.read.return_value=json.dumps({'OutBlock_1':rows}).encode()
        context=MagicMock();context.__enter__.return_value=stream
        return context
    def test_exact_index_date_and_auth_header(self):
        rows=[dict(IDX_NM='KRX 반도체',BAS_DD='20261001',CLSPRC_IDX='3,400.5')]
        with patch.object(krx_api,'urlopen',return_value=self.response(rows)) as call:
            point=krx_api.fetch_day(date(2026,10,1),'secret')
        self.assertEqual(point['value'],3400.5)
        request=call.call_args.args[0]
        self.assertNotIn('secret',request.full_url)
        self.assertEqual(request.get_header('Auth_key'),'secret')
    def test_no_substitution_or_wrong_date(self):
        for rows in [[dict(IDX_NM='KRX 300')],[dict(IDX_NM='KRX 반도체',BAS_DD='20200414',CLSPRC_IDX='100')]]:
            with patch.object(krx_api,'urlopen',return_value=self.response(rows)),self.assertRaises(RuntimeError):
                krx_api.fetch_day(date(2026,10,1),'secret')
    def test_sector_responses_share_daily_cache(self):
        rows=[dict(IDX_NM=name,BAS_DD='20261001',CLSPRC_IDX=str(value))
              for name,value in [('KRX 헬스케어',200),('KRX 철강',300)]]
        with TemporaryDirectory() as temp,patch.object(krx_api,'urlopen',return_value=self.response(rows)) as call:
            health=krx_api.fetch_day(date(2026,10,1),'secret','KRX 헬스케어',temp)
            steel=krx_api.fetch_day(date(2026,10,1),'secret','KRX 철강',temp)
        self.assertEqual(health['value'],200)
        self.assertEqual(steel['value'],300)
        self.assertEqual(call.call_count,1)
    def test_sector_index_frame_keeps_own_identity(self):
        import pandas as pd
        from snapdart.market import index_frame
        frame=pd.DataFrame({'Close':[100,110]},index=pd.to_datetime(['2026-10-01','2026-10-02']))
        result=index_frame(frame,name='KRX 철강 지수',code='KRX_STEEL')
        self.assertEqual(result['name'],'KRX 철강 지수')
        self.assertEqual(result['code'],'KRX_STEEL')
    def test_auth_error_never_leaks_credentials(self):
        with patch.object(krx_api,'urlopen',side_effect=HTTPError('secret',403,'secret',{},None)):
            with self.assertRaises(RuntimeError) as error:krx_api.fetch_day(date(2026,10,1),'secret')
        self.assertNotIn('secret',str(error.exception))
    def test_cache_resumes_and_keeps_completed_dates(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'days.json'
            with patch.object(krx_api,'key_value',return_value='secret'),patch.object(krx_api,'fetch_day',side_effect=[dict(date='2026-10-01',value=100),RuntimeError('failed')]),patch.object(krx_api.time,'sleep'):
                with self.assertRaises(RuntimeError):krx_api.collect_history(date(2026,10,2),path)
            saved=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['days']['2026-10-01']['value'],100)
