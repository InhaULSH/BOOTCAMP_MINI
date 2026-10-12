"""Retiring a prompt must not change or misidentify retained report versions."""
import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from dart_remote import artifacts
from dart_remote.prompt_context import active_version, using_version
from snapdart.data_access import prompts, prompts_new2, prompts_old


ROOT = Path(__file__).resolve().parents[1]


class PromptVersionTests(unittest.TestCase):
    def test_retained_profiles_and_keyword_behavior(self):
        with patch.dict(os.environ, {'LLM_PROMPT_VERSION': 'new'}):
            self.assertIs(prompts.active(), prompts)
            for version, module in (('new', prompts), ('new2', prompts_new2), ('old', prompts_old)):
                with self.subTest(version=version), using_version(version):
                    self.assertIs(prompts.active(), module)
            self.assertIsNone(active_version())
        self.assertEqual(prompts_new2.instruction('keyword'), prompts.instruction('keyword'))

    def test_retired_configuration_rejected(self):
        with self.assertRaises(ValueError):
            with using_version('new3'):
                self.fail('Retired profile entered')
        with patch.dict(os.environ, {'LLM_PROMPT_VERSION': 'new3'}), self.assertRaises(ValueError):
            prompts.active()
        with patch.dict(os.environ, {'REPORT_PROMPT_VERSION': 'new3'}), self.assertRaises(ValueError):
            artifacts.report_version()

    def test_legacy_retired_reports_never_become_new(self):
        for report in (
            {'report_prompt_version': 'new3'},
            {'report_prompt_version': 'new3', 'ai_insights': {'2026': {'prompt_version': prompts.VERSION}}},
            {'ai_insights': {'2026': {'prompt_version': 'bigin-user-2026-10-12-new3-v1-final'}}},
        ):
            self.assertIsNone(artifacts.identify_report(report))
        with patch.dict(os.environ, {'REPORT_PROMPT_VERSION': 'new'}), patch.object(
            artifacts, 'get_artifact', side_effect=[None, report]
        ):
            self.assertIsNone(artifacts.selected_report('sector'))

    def test_existing_report_ids_unchanged(self):
        for module, version in ((prompts, 'new'), (prompts_new2, 'new2'), (prompts_old, 'old')):
            with self.subTest(version=version):
                report = {'ai_insights': {'2026': {'prompt_version': module.VERSION}}}
                self.assertEqual(artifacts.identify_report(report), version)
                report['report_prompt_version'] = version
                self.assertEqual(artifacts.identify_report(report), version)

    def test_cli_choices_match_retained_profiles(self):
        for name in ('app.py', 'snapdart/analyze.py', 'snapdart/query.py', 'deploy/cloudapp/cli.py'):
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and any(isinstance(a, ast.Constant) and a.value == '--prompt-version' for a in node.args)]
            self.assertEqual(len(calls), 1, name)
            choices = next(kw.value for kw in calls[0].keywords if kw.arg == 'choices')
            self.assertEqual(ast.literal_eval(choices), ['new', 'new2', 'old'], name)

    def test_removed_modules_absent(self):
        for name in ('snapdart/data_access/prompts_new3.py', 'dart_remote/citation_selection_new3.py',
                     'dart_remote/new3_definition.py', 'deploy/cloudapp/prompts_new3.py',
                     'deploy/dart_remote/citation_selection_new3.py', 'deploy/dart_remote/new3_definition.py'):
            self.assertFalse((ROOT / name).exists(), name)


if __name__ == '__main__':
    unittest.main()
