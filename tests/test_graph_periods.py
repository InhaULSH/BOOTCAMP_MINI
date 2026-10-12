import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from dart_remote.graph_periods import display_periods, financial_basis


class GraphPeriodTests(unittest.TestCase):
    def test_missing_annual_uses_existing_ofs_quarters(self):
        repo=SimpleNamespace(facts=lambda c,y,t,b,k: [{}] if b=='OFS' and t in ('Q1','H1') else [])
        self.assertEqual(financial_basis(repo,'295310',2026),'OFS')
        self.assertEqual(financial_basis(repo,'295310',2026,'CFS'),'OFS')

    def test_preferred_basis_and_no_facts(self):
        repo=SimpleNamespace(facts=lambda *args: [{}])
        self.assertEqual(financial_basis(repo,'c',2026,'OFS'),'OFS')
        self.assertEqual(financial_basis(repo,'c',2026),'CFS')
        repo.facts=lambda *args: []
        self.assertEqual(financial_basis(repo,'c',2026,'OFS'),'OFS')

    def test_quarter_calculation_receives_actual_basis(self):
        from snapdart import ui_project as ui
        repo=SimpleNamespace(facts=lambda c,y,t,b,k: [{}] if b=='OFS' and t in ('Q1','H1') else [])
        def flow(repo,c,y,q,b,key):
            self.assertEqual(b,'OFS')
            return (100 if q<=2 else None),[],None
        with patch.object(ui,'financial_flow',side_effect=flow),\
             patch.object(ui,'capex_flow',return_value=(10,[],None,{'status':'verified'})):
            rows=ui.quarter_rows(repo,{'code':'295310','history':[{'year':2026,'basis':None}]},[2026])
        self.assertEqual(rows[0]['revenue'],100)
        self.assertEqual(rows[1]['revenue'],100)
        self.assertEqual(rows[0]['basis'],'OFS')

    def test_only_empty_tail_is_trimmed(self):
        periods=[f'2026 Q{q}' for q in range(1,5)]
        rows=[dict(period=p,metrics={'operating':None}) for p in periods]
        rows[1]['revenue']=0  # Zero is a real value, not a missing quarter.
        self.assertEqual(display_periods(rows,periods),periods[:2])

    def test_sector_latest_period_uses_all_companies(self):
        periods=[f'2026 Q{q}' for q in range(1,5)]
        rows=[dict(period='2026 Q1',revenue=100),dict(period='2026 Q2',netInterestIncome=50)]
        self.assertEqual(display_periods(rows,periods),periods[:2])

    def test_ratios_and_empty_data(self):
        periods=['2026 Q1','2026 Q2']
        self.assertEqual(display_periods([dict(period='2026 Q2',metrics={'roe':-3})],periods),periods)
        self.assertEqual(display_periods([dict(period='2026 Q2',revenue=float('nan'))],periods),[])

    def test_projection_sector_and_company_stop_at_actual_quarter(self):
        from snapdart import ui_project as ui
        sector=SimpleNamespace(id='s',name='s',membership_code='KRX_SEMI')
        view=dict(years=[2025,2026],companies=[dict(code=c,name=c,description='',history=[]) for c in ('1','2')])
        periods=[f'{y} Q{q}' for y in (2025,2026) for q in range(1,5)]
        def rows(c,*_):
            return [dict(period=p,basis='CFS',revenue=100 if p<='2026 Q2' else None,
                         metrics={'revenue':100 if p<='2026 Q2' else None}) for p in periods]
        repo=SimpleNamespace(documents=lambda _: [dict(year=2025,report_type='Q1'),dict(year=2026,report_type='H1')])
        graph=Mock(bank=False,health=False);graph.public_rows.side_effect=rows
        with patch.object(ui,'sectors',return_value=[sector]),patch.object(ui,'load_view',return_value=view),\
             patch.object(ui,'Repository',return_value=repo),patch.object(ui,'GraphData',return_value=graph),\
             patch.object(ui,'cached_graph',side_effect=lambda load,*args:load()):
            industry=ui._project('s')
            company=ui._project('s','1')
        self.assertEqual(industry['sectors'][0]['periods'][-1],'2026 Q2')
        self.assertTrue(all(c['financials'][-1]['period']=='2026 Q2' for c in industry['companies']))
        self.assertEqual(company['companies'][0]['periods'][-1],'2026 Q2')
        self.assertEqual(company['companies'][0]['financials'][-1]['period'],'2026 Q2')
