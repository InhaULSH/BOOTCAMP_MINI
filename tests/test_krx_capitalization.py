import unittest
from datetime import date
from unittest.mock import patch
from dart_remote import krx_market


def response(day, cap=1000):
    return {'OutBlock_1':[dict(IDX_NM=n,BAS_DD=day,CLSPRC_IDX='100',MKTCAP=str(cap)) for n in ('KRX 반도체','KRX 철강')]}


class KrxCapitalizationTests(unittest.TestCase):
    def test_previous_session_full_index_caps_share_requests(self):
        with patch.object(krx_market,'daily',side_effect=[response('20261002'),response('20261001',900)]) as fetch:
            result=krx_market.collect(['KRX 반도체','KRX 철강'],'unused',date(2026,10,5))
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(fetch.call_args_list[0].args[0],date(2026,10,2))
        for value in result.values():
            self.assertEqual(value['constituent_market_cap'],1000)
            self.assertEqual(value['market_cap_traded_at'],'2026-10-02')
            self.assertEqual(value['traded_at'],value['market_cap_traded_at'])
            self.assertEqual(value['market_cap_scope'],'all_index_constituents')

    def test_holiday_not_cached_as_zero_market_cap(self):
        with patch.object(krx_market,'daily',side_effect=[{'OutBlock_1':[]},response('20261001'),response('20260930')]):
            result=krx_market.collect(['KRX 반도체'],'unused',date(2026,10,3))
        self.assertEqual(result['KRX 반도체']['traded_at'],'2026-10-01')

    def test_wrong_date_missing_or_zero_cap_rejected(self):
        for day,cap in [('20261001',1000),('20261002',0),('20261002','-')]:
            with patch.object(krx_market,'daily',return_value=response(day,cap)),self.assertRaises(RuntimeError):
                krx_market.collect(['KRX 반도체'],'unused',date(2026,10,3))

    def test_merge_keeps_history_but_drops_future(self):
        old={'history':[dict(date='2026-09-30',value=90),dict(date='2026-10-07',value=999)]}
        current=dict(traded_at='2026-10-06',history=[dict(date='2026-10-06',value=100)],constituent_market_cap=500)
        value=krx_market.merge(old,current,'5044',date(2026,10,7))
        self.assertEqual([r['date'] for r in value['history']],['2026-09-30','2026-10-06'])
        self.assertEqual(value['constituent_market_cap'],500)

    def test_older_refresh_keeps_latest_close_and_cap(self):
        old=dict(code='5044',traded_at='2026-10-08',price=110,constituent_market_cap=900,
                 history=[dict(date='2026-10-08',value=110)])
        current=dict(traded_at='2026-10-07',price=100,constituent_market_cap=500,
                     history=[dict(date='2026-10-06',value=90),dict(date='2026-10-07',value=100)])
        value=krx_market.merge(old,current,'5044',date(2026,10,10))
        self.assertEqual(value['traded_at'],'2026-10-08')
        self.assertEqual(value['constituent_market_cap'],900)
        self.assertEqual(len(value['history']),3)
        self.assertTrue(value['stale'])

    def test_initial_backfill_then_incremental_and_resume(self):
        from tempfile import TemporaryDirectory
        def fetch(day,*args,**kwargs):return response(day.strftime('%Y%m%d'))
        with TemporaryDirectory() as directory,patch.object(krx_market,'daily',side_effect=fetch) as api,patch.object(krx_market.time,'sleep'):
            first=krx_market.collect_history(['KRX 반도체','KRX 철강'],directory,date(2026,10,10))
            calls=api.call_count
            self.assertGreater(calls,700)
            self.assertEqual(first['KRX 반도체']['history'][0]['date'],'2023-10-09')
            self.assertEqual(first['KRX 철강']['traded_at'],'2026-10-09')
            api.reset_mock()
            second=krx_market.collect_history(['KRX 반도체','KRX 철강'],directory,date(2026,10,13),refresh=True)
            self.assertLess(api.call_count,10)
            self.assertEqual(second['KRX 반도체']['traded_at'],'2026-10-12')

    def test_interrupted_backfill_keeps_completed_day(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory,patch.object(krx_market,'daily',side_effect=[response('20261009'),RuntimeError('failed')]),patch.object(krx_market.time,'sleep'):
            with self.assertRaises(RuntimeError):krx_market.collect_history(['KRX 반도체'],directory,date(2026,10,10))
            saved=json.loads(next((Path(directory)/'history').glob('*.json')).read_text())
            self.assertEqual(saved['days']['2026-10-09']['value'],100)

    def test_empty_refresh_preserves_cached_daily_response(self):
        import json,os
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import MagicMock
        with TemporaryDirectory() as directory:
            cached=response('20261008')
            (Path(directory)/'2026-10-08.json').write_text(json.dumps(cached))
            stream=MagicMock();stream.read.return_value=json.dumps({'OutBlock_1':[]}).encode()
            context=MagicMock();context.__enter__.return_value=stream
            with patch.dict(os.environ,{'KRX_API':'test'}),patch.object(krx_market,'urlopen',return_value=context):
                self.assertEqual(krx_market.daily(date(2026,10,8),directory,True),cached)
