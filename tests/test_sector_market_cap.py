import unittest
from datetime import date
from dart_remote.market_summary import index_market_cap


class SectorMarketCapTests(unittest.TestCase):
    def test_official_index_cap_not_representative_sum(self):
        market={'index':dict(constituent_market_cap=500,market_cap_traded_at='2026-10-06',market_cap_scope='all_index_constituents'),
                'quotes':{'A':{'market_cap':100}}}
        self.assertEqual(index_market_cap(market,date(2026,10,7))['constituentMarketCap'],500)

    def test_intraday_unknown_scope_or_invalid_cap_are_unavailable(self):
        base=dict(constituent_market_cap=500,market_cap_traded_at='2026-10-06',market_cap_scope='all_index_constituents')
        for change in (dict(market_cap_traded_at='2026-10-07'),dict(market_cap_scope='representatives'),dict(constituent_market_cap=-1),dict(constituent_market_cap=True),dict(constituent_market_cap=float('nan'))):
            self.assertIsNone(index_market_cap({'index':dict(base,**change)},date(2026,10,7))['constituentMarketCap'])
        self.assertIsNone(index_market_cap({'quotes':{'A':{'market_cap':100}}},date(2026,10,7))['constituentMarketCap'])
