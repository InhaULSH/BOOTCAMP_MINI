"""UI routing checks do not connect to MySQL or generate reports."""
import gzip
import os
import sys
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from dart_remote.ui_version import page_bytes, page_asset, ui_version

ROOT = Path(__file__).resolve().parents[1]


class UIVersionTests(unittest.TestCase):
    def test_old_preserves_all_original_pages_byte_for_byte(self):
        with patch.dict(os.environ, {'UI_VERSION': 'old'}):
            for name in ('index.html', 'industry.html', 'company.html'):
                page = ROOT / 'web' / name
                self.assertEqual(page_bytes(page), page.read_bytes())

    def test_new_pages_use_same_api_renderer_and_theme(self):
        with patch.dict(os.environ, {'UI_VERSION': 'new'}):
            for name in ('index.html', 'industry.html', 'company.html'):
                value = page_bytes(ROOT / 'web' / name).decode()
                self.assertIn('data-ui-version="new"', value)
                self.assertIn('class="ui-skeleton"', value)
                self.assertNotIn('class="load-status"', value)
                self.assertEqual(value.count('/assets/ui-new.css'), 1)
                self.assertIn('src="assets/app.js"', value)

    def test_versions_have_distinct_compressed_etags(self):
        page = ROOT / 'web/index.html'
        values = []
        for version in ('old', 'new'):
            with patch.dict(os.environ, {'UI_VERSION': version}):
                body, tag, compressed = page_asset(page, True)
                self.assertTrue(compressed)
                self.assertEqual(gzip.decompress(body), page_bytes(page))
                values.append(tag)
        self.assertNotEqual(*values)

    def test_invalid_environment_is_rejected(self):
        with patch.dict(os.environ, {'UI_VERSION': 'unknown'}):
            with self.assertRaises(ValueError):
                ui_version()

    def test_local_html_and_new_assets_are_served(self):
        from app import Handler
        for version in ('old', 'new'):
            for path in ('/', '/industry.html', '/company.html', '/assets/ui-new.css',
                         '/assets/ui-new.js', '/assets/fonts/PretendardVariable.woff2'):
                h = object.__new__(Handler)
                h.path = path
                h.headers = Message()
                h.wfile = BytesIO()
                h.send_response = Mock()
                h.send_header = Mock()
                h.end_headers = Mock()
                with patch.dict(os.environ, {'UI_VERSION': version}):
                    h.do_GET()
                h.send_response.assert_called_once_with(200)
                self.assertTrue(h.wfile.getvalue())
                if path == '/':
                    self.assertEqual(b'data-ui-version="new"' in h.wfile.getvalue(), version == 'new')

    def test_cloud_pages_match_local_without_database_calls(self):
        sys.path.insert(0, str(ROOT / 'deploy'))
        try:
            from cloudapp.main import app
            from fastapi.testclient import TestClient
            # No context manager: omit lifespan/prewarm/market startup entirely.
            client = TestClient(app)
            for version in ('old', 'new'):
                with patch.dict(os.environ, {'UI_VERSION': version}):
                    for path, name in (('/', 'index.html'), ('/index.html', 'index.html'),
                                       ('/industry.html', 'industry.html'), ('/company.html', 'company.html')):
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.content, page_bytes(ROOT / 'web' / name))
                    self.assertEqual(client.get('/assets/ui-new.css').status_code, 200)
                    self.assertEqual(client.get('/assets/fonts/PretendardVariable.woff2').status_code, 200)
            client.close()
        finally:
            sys.path.pop(0)
