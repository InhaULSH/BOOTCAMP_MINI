"""Shared local/deploy implementation and independent application artifacts."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dart_remote import artifacts
ROOT=Path(__file__).resolve().parents[1]
class ConsolidatedPathTests(unittest.TestCase):
    def test_shared_adapter_copies_match(self):
        # Local-only retirement must not modify the preserved deployment package.
        for name in ('db.py','artifacts.py','dart_db_client.py'):
            file=ROOT/'dart_remote'/name
            self.assertEqual(file.read_bytes(),(ROOT/'deploy/dart_remote'/file.name).read_bytes(),file.name)
    def test_retired_sibling_packages_are_absent(self):
        self.assertFalse((ROOT/'data_new').exists());self.assertFalse((ROOT/'snapdart_data').exists())
        for name in ('search_server','team_client','data/반도체','web/app.js','web/style.css'):
            self.assertFalse((ROOT/name).exists(),name)
        self.assertTrue((ROOT/'config/sectors.json').is_file())
        self.assertTrue((ROOT/'data/service/market.json').is_file())
    def test_artifacts_do_not_write_to_upstream_db(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(artifacts,'ROOT',Path(folder)),patch.dict('os.environ',{'SERVICE_GCS_BUCKET':''}),patch('dart_remote.db.engine') as engine:
            artifacts.put_artifact('반도체','report',{'v':1})
            self.assertEqual(artifacts.get_artifact('반도체','report'),{'v':1})
            self.assertIsNone(artifacts.get_artifact('다른산업','report'))
            self.assertEqual(list(Path(folder).rglob('*.tmp')),[]);engine.assert_not_called()
    def test_cloud_generation_requires_shared_quota_store(self):
        with patch.dict('os.environ',{'K_SERVICE':'test','SERVICE_GCS_BUCKET':''}):
            with self.assertRaisesRegex(RuntimeError,'SERVICE_GCS_BUCKET'):artifacts.reserve(100)
