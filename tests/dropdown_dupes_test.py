# -*- coding: utf-8 -*-
"""#103: no dropdown lists the same choice twice (「標準（預設）」 and 「標準」), and 思考強度 has 中."""
import importlib.util, json, re, shutil, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_dropdowns', SERVER); server = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(server)
JS = {p.name: p.read_text(encoding='utf-8') for p in (ROOT / 'frontend/js').glob('*.js')}


def snippet(name, pattern):
    found = re.search(pattern, JS[name], re.S)
    if not found: raise AssertionError('not found in %s: %s' % (name, pattern))
    return found.group(0)


def run_js(code):
    out = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=30)
    if out.returncode: raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class Medium(unittest.TestCase):
    def test_medium_reaches_every_cli_that_takes_a_level(self):
        self.assertIn('medium', server.EFFORTS)
        self.assertEqual(server.effort_args('codex', 'medium'), ['-c', 'model_reasoning_effort="medium"'])
        self.assertEqual(server.effort_args('claude', 'medium'), ['--effort', 'medium'])
        self.assertEqual(server.effort_args('grok', 'medium'), ['--reasoning-effort', 'medium'])
        self.assertEqual(server.effort_args('antigravity', 'medium'), ['--effort', 'medium'])
        self.assertEqual(server.effort_args('codex', 'standard'), [])  # 標準 still leaves the CLI's own default
        self.assertEqual(server.pick_effort('medium'), 'medium')
        self.assertEqual(server.TOOL_EFFORTS['中'], 'medium')
        self.assertEqual(server.TOOL_EFFORTS['medium'], 'medium')

    def test_form_lists_medium(self):
        self.assertIn("{id: 'medium', name: '中'", JS['20-models.js'])


@unittest.skipUnless(shutil.which('node'), 'needs node')
class NoDuplicates(unittest.TestCase):
    def with_default(self, options, current, own, label=None):
        fn = snippet('20-models.js', r'const withDefault = .*?\n')
        return run_js(fn + 'console.log(JSON.stringify(withDefault(%s, %s, %s, %s)))' % (json.dumps(options), json.dumps(current), json.dumps(own), json.dumps(label)))

    def names(self, items): return [x['name'] for x in items]

    def test_effort_default_is_one_line(self):
        efforts = [{'id': 'standard', 'name': '標準'}, {'id': 'fast', 'name': '快速'}, {'id': 'medium', 'name': '中'}, {'id': 'deep', 'name': '深入'}]
        got = self.with_default(efforts, 'standard', '')
        self.assertEqual(got[0]['id'], '')  # following the default still saves as ''
        self.assertEqual(self.names(got), ['預設（目前是 標準）', '快速', '中', '深入'])
        kept = self.with_default(efforts, 'standard', 'standard')  # a Bot that set 標準 itself keeps it, said differently
        self.assertEqual([x['id'] for x in kept], ['', 'standard', 'fast', 'medium', 'deep'])
        self.assertEqual(len(set(self.names(kept))), 5)
        self.assertNotIn('標準', self.names(kept))

    def test_access_and_switches(self):
        access = [{'id': 'full', 'name': '整台 Mac'}, {'id': 'folder', 'name': '指定資料夾'}]
        self.assertEqual(self.names(self.with_default(access, 'full', '')), ['預設（目前是 整台 Mac）', '指定資料夾'])
        onoff = [{'id': 'on', 'name': '開啟'}, {'id': 'off', 'name': '關閉'}]
        self.assertEqual(self.names(self.with_default(onoff, 'off', '')), ['預設（目前是 關閉）', '開啟'])

    def test_chain_default_hides_nothing(self):
        got = self.with_default([{'id': '__none', 'name': '不自動換'}, {'id': 'claude', 'name': 'Claude'}], None, '', 'Claude → Grok')
        self.assertEqual(self.names(got), ['預設（目前是 Claude → Grok）', '不自動換', 'Claude'])

    def provider_choice(self, provider, account, accounts, main=None):
        fn = snippet('10-chat.js', r'const choiceOptions = .*?\n  \};\n')
        stub = ('const esc = s => String(s); const levelMark = () => ""; const accountLevel = () => 0;'
                'const mainAccountName = id => (%s)[id] || "";' % json.dumps(main or {}) +
                'const state = {data: {settings: {provider: "codex"}}, providers: [{id: "codex", name: "Codex", accounts: %s}, {id: "claude", name: "Claude", accounts: []}]};' % json.dumps(accounts))
        html = run_js(stub + fn + 'console.log(JSON.stringify(choiceOptions(%s, %s)))' % (json.dumps(provider), json.dumps(account)))
        return re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', html)

    def test_main_account_is_named(self):  # #281③ #333⑥: the CLI's own sign-in by name, not only 預設
        labels = [x[1] for x in self.provider_choice('auto', '', [{'id': 'w', 'name': 'Waifdance'}], {'codex': 'sean', 'claude': 'amy'})]
        self.assertEqual(labels[0], '預設（目前是 Codex・sean）')
        self.assertIn('Codex（Waifdance）', labels)
        labels = [x[1] for x in self.provider_choice('claude', '', [], {'codex': 'sean', 'claude': 'amy'})]
        self.assertIn('Claude', labels)  # no extra account: the name alone, as before

    def test_model_and_account_default_not_twice(self):
        got = self.provider_choice('auto', '', [{'id': 'w', 'name': 'Waifdance'}])
        labels = [x[1] for x in got]
        self.assertEqual(labels[0], '預設（目前是 Codex）')
        self.assertFalse(any('預設帳號' in x for x in labels if x.startswith('Codex')), labels)
        self.assertIn('Codex（Waifdance）', labels)
        self.assertEqual(len(labels), len(set(labels)))
        pinned = self.provider_choice('codex', '', [{'id': 'w', 'name': 'Waifdance'}])  # a Bot set to Codex itself keeps that choice
        self.assertIn('codex', [x[0] for x in pinned])
        self.assertEqual(len({x[1] for x in pinned}), len(pinned))

    def test_model_default_not_twice(self):
        code = JS['20-models.js']
        self.assertIn("(named ? '預設（目前是 ' + named + '）' : '預設（這一家建議的型號）')", code)
        self.assertNotIn("+ '（預設）' : '各家建議的型號'", code)


if __name__ == '__main__': unittest.main()
