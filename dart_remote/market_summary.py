"""Only official whole-index capitalization is eligible for home bubble size."""
from datetime import date, datetime, timedelta, timezone
from math import isfinite


def index_market_cap(market, as_of=None):
    index=market.get('index',{})
    value=index.get('constituent_market_cap')
    day=index.get('market_cap_traded_at')
    today=as_of or datetime.now(timezone(timedelta(hours=9))).date()
    try:
        valid_day=date.fromisoformat(day)<today
    except (ValueError,TypeError):valid_day=False
    valid=(valid_day and index.get('market_cap_scope')=='all_index_constituents'
           and not isinstance(value,bool) and isinstance(value,(int,float)) and isfinite(value) and value>0)
    return dict(constituentMarketCap=value if valid else None,
                marketCapTradedAt=day if valid else None,marketCapUnit='원',
                marketCapStale=bool(index.get('stale')),marketCapScope='all_index_constituents')
