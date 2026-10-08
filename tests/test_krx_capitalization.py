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
        value=krx_market.merge(old,current,'5044')
        self.assertEqual([r['date'] for r in value['history']],['2026-09-30','2026-10-06'])
        self.assertEqual(value['constituent_market_cap'],500)
