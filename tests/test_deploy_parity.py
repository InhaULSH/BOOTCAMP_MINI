"""Prevent local feature updates silently missing from the cloud package."""
import unittest
import ast
import sys
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]

class DeploymentParityTests(unittest.TestCase):
    def test_cloud_ui_imports_are_self_contained(self):
        tree=ast.parse((ROOT/'deploy/cloudapp/ui_project.py').read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(n,ast.ImportFrom) and (n.module or '').startswith('data_access') for n in ast.walk(tree)))
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
        self.assertEqual((ROOT/'snapdart/data_access/prompts_new2.py').read_bytes(),(ROOT/'deploy/cloudapp/prompts_new2.py').read_bytes())

    def test_llm_repair_gate_matches(self):
        functions=[]
        for path in ('snapdart/llm.py','deploy/cloudapp/llm.py'):
            tree=ast.parse((ROOT/path).read_text(encoding='utf-8'))
            functions.append(ast.dump(next(f for f in tree.body if isinstance(f,ast.FunctionDef) and f.name=='request_report'),include_attributes=False))
        self.assertEqual(functions[0],functions[1])

    def test_generation_and_atomic_cache_helpers_match(self):
        # Missing cache helpers previously escaped copy-only parity checks.
        functions=[]
        class RuntimeImports(ast.NodeTransformer):
            def visit_ImportFrom(self,node):
                if [a.name for a in node.names]==['llm'] and node.module in (None,'snapdart'):
                    node.module='runtime_llm';node.level=0
                return node
        for path in ('snapdart/data_access/pipeline.py','deploy/cloudapp/pipeline.py'):
            tree=RuntimeImports().visit(ast.parse((ROOT/path).read_text(encoding='utf-8')))
            functions.append({f.name:ast.dump(f,include_attributes=False)
                              for f in tree.body if isinstance(f,ast.FunctionDef)})
        for name in ('atomic','generate','anchor','evidence_rows','financial_history'):
            with self.subTest(function=name):self.assertEqual(functions[0][name],functions[1][name])

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
