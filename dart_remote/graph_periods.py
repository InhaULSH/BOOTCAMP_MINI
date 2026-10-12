"""Quarter display boundaries from actual financial values, including derived values."""
from .graph_metrics import finite, REPORTS

FIELDS = ('revenue', 'operatingProfit', 'capex', 'operatingCashFlow', 'rd',
          'netInterestIncome', 'netIncome', 'creditLoss', 'equity', 'assets', 'loans')


def financial_basis(repo, code, year, preferred=None):
    """Use one actual accounting basis per year, even before the annual filing."""
    order=list(dict.fromkeys([preferred] + ['CFS','OFS']))
    for basis in order:
        if basis not in ('CFS','OFS'):
            continue
        for report in REPORTS:
            kinds=('quarterly','annual' if report=='FY' else 'cumulative')
            if any(repo.facts(code,year,report,basis,kind) for kind in kinds):
                return basis
    return preferred if preferred in ('CFS','OFS') else 'CFS'


def display_periods(rows, periods):
    """Trim only the empty tail; keep earlier gaps and the original index baseline."""
    candidates = sorted(set(periods))
    available = [row['period'] for row in rows if row.get('period') in candidates and
                 (any(finite(row.get(field)) for field in FIELDS) or
                  any(finite(v) for v in row.get('metrics', {}).values()))]
    if not available:
        return []
    last = max(available)
    return [period for period in candidates if period <= last]
