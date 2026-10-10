import unittest
from types import SimpleNamespace
from unittest.mock import patch
from snapdart.ui_project import project

class SectorAvailabilityTests(unittest.TestCase):
    def test_home_never_builds_reports_or_loads_models(self):
        sectors=[SimpleNamespace(id='반도체',name='반도체'),SimpleNamespace(id='헬스케어',name='헬스케어')]
        with patch('snapdart.ui_project.sectors',return_value=sectors),patch('snapdart.ui_project.load_view') as load,patch('snapdart.ui_project.Repository') as repository,patch('dart_remote.artifacts.get_artifact',return_value=None):
            result=project()
        self.assertEqual([r['name'] for r in result['sectors']],['반도체','헬스케어'])
        load.assert_not_called()

    def test_default_analyze_visits_all_sectors_even_after_failure(self):
        from snapdart.analyze import build
        sectors=[SimpleNamespace(id=n,name=n) for n in ('헬스케어','반도체','철강')]
        with patch('snapdart.data_access.catalog.sectors',return_value=sectors),patch('snapdart.data_access.pipeline.build',side_effect=[ValueError('bad'),{},{}]) as run:
            with self.assertRaisesRegex(RuntimeError,'헬스케어'):build()
        self.assertEqual([c.args[0] for c in run.call_args_list],['헬스케어','반도체','철강'])

    def test_explicit_analyze_visits_only_requested_sector(self):
        from snapdart.analyze import build
        with patch('snapdart.data_access.pipeline.build',return_value={}) as run:
            build(sector_id='반도체')
        self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0],'반도체')

    def test_market_prices_default_visits_all_sectors(self):
        from snapdart import market
        sectors=[SimpleNamespace(id=n,name=n) for n in ('헬스케어','반도체','철강')]
        contexts=[(s,[dict(code=str(i),name=s.name)],__import__('pathlib').Path('unused-test-market.json')) for i,s in enumerate(sectors)]
        with patch('snapdart.data_access.catalog.sectors',return_value=sectors),patch.object(market,'market_context',side_effect=contexts),patch.object(market,'collect_quote',return_value=dict(market_cap=100,history=[{}])),patch.object(market,'save_json'),patch('dart_remote.artifacts.put_artifact'),patch.object(market,'refresh_index_only') as index:
            market.refresh_prices()
        self.assertEqual([c.args[0] for c in index.call_args_list],['헬스케어','반도체','철강'])

    def test_catalog_filter_skips_other_sector_reads(self):
        from dart_remote.catalog import sectors
        def rows(sql,params=None):
            if 'data_versions' in sql:return [dict(validated=True,data_version='v',index_version='i')]
            if 'krx_indices' in sql:return [dict(display_name=n,index_name=n,index_code=c,official_index_code=None) for n,c in [('바이오','BIO'),('반도체','KRX_SEMI')]]
            self.assertEqual(params,{'i0':'KRX_SEMI'})
            return [dict(index_code='KRX_SEMI',corp_code='c',effective_from=None,effective_to=None,source_as_of=None,is_operational=1)]
        with patch.dict('os.environ',{'SNAPDART_SECTORS':'반도체'}),patch('dart_remote.catalog.db.rows',side_effect=rows):
            self.assertEqual([s.name for s in sectors()],['반도체'])
