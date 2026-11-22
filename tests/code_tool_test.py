# -*- coding: utf-8 -*-
"""A connector tool that runs the code it is given (node_repl's js) is running a program, whatever its read-only hint says."""
import importlib.util, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend')); import runtime
spec = importlib.util.spec_from_file_location('zook_code_tool', ROOT / 'backend/server.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class CodeTool(unittest.TestCase):
    def session(self):
        s = runtime.RuntimeSession([], [], False, ROOT, lambda *a: True, lambda e: None)
        s.routes = {'mcp_node_repl__js': ('a1b2c3', 'js'), 'mcp_files__read_file': ('d4e5f6', 'read_file'), 'mcp_x__evaluate': ('9f9f9f', 'evaluate'),
                    'mcp_db__query': ('aaaaaa', 'query')}  # connector ids are hashes; their registered names say what they are
        s.inventory = {'mcp': [{'id': '9f9f9f', 'name': 'node-repl'}, {'id': 'aaaaaa', 'name': 'replica-db'}]}
        s.annotations = {k: {'readOnlyHint': True} for k in s.routes}
        return s

    def test_code_runners_are_code(self):
        s = self.session()
        self.assertEqual(s.classify('mcp_node_repl__js', {'code': 'fs.statSync(\"a\")'}), 'code')  # asked in 自動 too
        self.assertEqual(s.classify('mcp_files__read_file', {'path': 'a'}), 'external_read')
        self.assertEqual(s.classify('mcp_x__evaluate', {}), 'code')  # known only by the connector's registered name
        self.assertEqual(s.classify('mcp_db__query', {}), 'external_read')  # 「replica」 is not 「repl」
        self.assertIn('code', runtime.ASK_IN_MODE['auto'])
        for name in ('javascript_tool', 'run_python', 'execute_script', 'runCode', 'jupyter-exec'): self.assertTrue(runtime.is_code_runner('', name), name)
        for name in ('run_report', 'read_file', 'replicate_table', 'search'): self.assertFalse(runtime.is_code_runner('', name), name)

    def test_plain_title(self):
        self.assertEqual(m.describe_call(dict(name='mcp_node_repl__js', category='code', sourceLabel='node_repl', label='js')), '執行一段程式（node_repl）')


if __name__ == '__main__': unittest.main()
