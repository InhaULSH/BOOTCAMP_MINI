import gzip
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from dart_remote.http_assets import public_asset,accepts_gzip,_assets
from dart_remote.runtime_cache import cached_project,_project_cache,cached_graph,_graph_cache

class WebPerformanceTests(unittest.TestCase):
    def test_local_static_and_json_headers(self):
        from app import Handler
        from email.message import Message
        from io import BytesIO
        def handler(path,etag=None):
            h=object.__new__(Handler);h.path=path;h.headers=Message();h.headers['Accept-Encoding']='gzip'
            if etag:h.headers['If-None-Match']=etag
            h.wfile=BytesIO();h.send_response=Mock();h.send_header=Mock();h.end_headers=Mock()
            return h
        first=handler('/assets/app.js');first.do_GET()
        headers=dict(call.args for call in first.send_header.call_args_list)
        self.assertEqual(headers['Content-Encoding'],'gzip')
        self.assertIn(b'loadProject',gzip.decompress(first.wfile.getvalue()))
        second=handler('/assets/app.js',headers['ETag']);second.do_GET()
        second.send_response.assert_called_once_with(304)
        self.assertEqual(second.wfile.getvalue(),b'')
        response=handler('/api/source');response.send_json({'text':'a'*2048})
        headers=dict(call.args for call in response.send_header.call_args_list)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(headers['Content-Encoding'],'gzip')

    def test_static_update_and_encoding(self):
        _assets.clear()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'app.js';path.write_bytes(b'a'*2048)
            body,etag,encoded=public_asset(path,True)
            self.assertTrue(encoded);self.assertEqual(gzip.decompress(body),b'a'*2048)
            path.write_bytes(b'b'*2049)
            self.assertNotEqual(public_asset(path,True)[1],etag)
        self.assertFalse(accepts_gzip('gzip;q=0, br'))
        self.assertTrue(accepts_gzip('br, gzip;q=0.5'))

    def test_company_projection_and_menu(self):
        from snapdart import ui_project as ui
        sector=SimpleNamespace(id='반도체',name='반도체',membership_code='KRX_SEMI')
        view=dict(years=[2024],companies=[dict(code=c,name=c,description='',history=[]) for c in ('1','2')])
        graph=Mock(bank=False,health=False);graph.public_rows.return_value=[]
        with patch.object(ui,'sectors',return_value=[sector]),patch.object(ui,'load_view',return_value=view),\
             patch.object(ui,'Repository'),patch.object(ui,'GraphData',return_value=graph),\
             patch.object(ui,'cached_graph',side_effect=lambda load,*args:load()):
            result=ui._project('반도체','2')
        self.assertEqual([c['id'] for c in result['companies']],['반도체:1','반도체:2'])
        self.assertNotIn('financials',result['companies'][0])
        self.assertIn('financials',result['companies'][1])
        self.assertEqual(graph.public_rows.call_count,1)

    def test_project_cache_separates_company(self):
        _project_cache.clear();load=Mock(return_value={'sectors':[]})
        load.__module__='test_projection'
        with patch.dict(os.environ,{'UI_CACHE_SECONDS':'30','SERVICE_GCS_BUCKET':''}):
            cached_project(load,'s',[],company='1');cached_project(load,'s',[],company='2')
            cached_project(load,'s',[],company='1')
        self.assertEqual(load.call_count,2)

    def test_graph_reuse_copy_and_report_invalidation(self):
        from dart_remote import artifacts
        _graph_cache.clear();sector=SimpleNamespace(id='s',data_version='v1')
        load=Mock(return_value=[{'metrics':{'a':1}}])
        with tempfile.TemporaryDirectory() as folder,patch.object(artifacts,'ROOT',Path(folder)),\
             patch.dict(os.environ,{'UI_CACHE_SECONDS':'30','SERVICE_GCS_BUCKET':''}):
            path=Path(folder)/artifacts._name('s','report','current');path.parent.mkdir(parents=True);path.write_text('1')
            first=cached_graph(load,sector,{'code':'1'},[2024]);first[0]['metrics']['a']=9
            self.assertEqual(cached_graph(load,sector,{'code':'1'},[2024])[0]['metrics']['a'],1)
            self.assertEqual(load.call_count,1)
            path.write_text('updated')
            cached_graph(load,sector,{'code':'1'},[2024]);self.assertEqual(load.call_count,2)

    def test_original_cache_keeps_live_validation(self):
        from dart_remote import original_document as source
        source._rendered_documents.clear()
        result=dict(document_html='<p>example</p>',highlight_matched=True)
        with patch.object(source,'read_xml',return_value=b'xml') as read,patch.object(source,'render',return_value=result) as render:
            source.document_view('r','quote',chunk_id='a');source.document_view('r','quote',chunk_id='a')
            self.assertEqual(read.call_count,2);self.assertEqual(render.call_count,1)
        with patch.object(source,'read_xml',side_effect=ValueError('invalid mapping')):
            self.assertIsNone(source.document_view('r','quote',chunk_id='a')['document_html'])

    def test_static_browser_revalidation_and_api_policy(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
        from cloudapp.main import app
        from fastapi.testclient import TestClient
        with patch.dict(os.environ,{'NO_MARKET_REFRESH':'1','UI_PREWARM':'0'}),TestClient(app) as client:
            first=client.get('/assets/app.js',headers={'Accept-Encoding':'identity'})
            second=client.get('/assets/app.js',headers={'If-None-Match':first.headers['etag'],'Accept-Encoding':'identity'})
            self.assertEqual(second.status_code,304)
            self.assertEqual(first.headers['cache-control'],'no-cache')
            self.assertEqual(client.get('/healthz').headers['cache-control'],'no-store')
            self.assertEqual(client.get('/assets/app.js').headers.get('content-encoding'),'gzip')
