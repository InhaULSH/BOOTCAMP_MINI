"""Prevent local feature updates silently missing from the cloud package."""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]

class DeploymentParityTests(unittest.TestCase):
    def test_shared_runtime_and_frontend_are_identical(self):
        for folder in ('dart_remote','web','config'):
            for source in (ROOT/folder).rglob('*'):
                if not source.is_file() or '__pycache__' in source.parts:continue
                target=ROOT/'deploy'/source.relative_to(ROOT)
                with self.subTest(file=str(source.relative_to(ROOT))):
                    self.assertTrue(target.is_file())
                    self.assertEqual(source.read_bytes(),target.read_bytes())

    def test_prompt_text_is_identical(self):
        self.assertEqual((ROOT/'snapdart/data_access/prompts.py').read_bytes(),(ROOT/'deploy/cloudapp/prompts.py').read_bytes())

    def test_docker_installs_original_xml_dependency(self):
        self.assertIn('requirements-lock.txt',(ROOT/'deploy/Dockerfile').read_text())
        self.assertIn('lxml==',(ROOT/'deploy/requirements-lock.txt').read_text())

    def test_cloud_cli_default_build_visits_all_sectors(self):
        sys.path.insert(0,str(ROOT/'deploy'))
        try:
            from cloudapp import cli
            items=[SimpleNamespace(id=n,name=n) for n in ('헬스케어','반도체','철강')]
            with patch.object(sys,'argv',['cli','build','--llm']),patch('cloudapp.catalog.sectors',return_value=items),patch.object(cli,'build') as build,patch.object(cli.db,'close'):
                cli.main()
            self.assertEqual([c.args[0] for c in build.call_args_list],['헬스케어','반도체','철강'])
            self.assertTrue(all(c.args[1] for c in build.call_args_list))
        finally:sys.path.pop(0)
