# -*- coding: utf-8 -*-
"""#246: one table per CLI (models, thinking levels, read-only, access, native tools, quota); every menu is made from it.
Needs no CLI installed: the table and the views are read straight from the code, and the JS parts run in node when it is there."""
import importlib.util, json, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = {p.name: p.read_text(encoding='utf-8') for p in (ROOT / 'frontend/js').glob('*.js')}
KEYS = {'models', 'modelsHow', 'modelGroups', 'efforts', 'effortNote', 'readOnly', 'access', 'gated', 'nativeTools', 'zookTools', 'quota', 'quotaHow', 'features'}


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_cli_table', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def run_js(code):
    out = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=30)
    if out.returncode: raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def snippet(name, pattern):
    found = re.search(pattern, JS[name], re.S)
    if not found: raise AssertionError('not found in %s: %s' % (name, pattern))
    return found.group(0)


class Table(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = self.m.Store(Path(self.temp.name) / 'data')
        self.store.data['settings']['addedProviders'] = list(self.m.P.CATALOG)  # every CLI shown, none installed

    def tearDown(self): self.temp.cleanup()

    def test_one_row_per_cli_and_nothing_else(self):
        table = self.m.CLI_TABLE
        self.assertEqual(set(table), set(self.m.P.CATALOG) | {'custom'})  # a new CLI in providers.py needs its row here, and the other way round
        for pid, row in table.items(): self.assertEqual(set(row) - {'effortFlag'}, KEYS, pid)
        efforts, access = self.m.ALL_EFFORTS, self.m.ALL_ACCESS
        for pid, row in table.items():
            self.assertTrue(row['efforts'] and set(row['efforts']) <= set(efforts) and row['efforts'][0] == 'standard', pid)
            self.assertTrue(row['access'] and set(row['access']) <= set(access), pid)
            self.assertEqual(bool(row.get('effortFlag')), len(row['efforts']) > 1, pid)  # a level is offered only where Zook can pass it
            if len(row['efforts']) == 1: self.assertTrue(row['effortNote'], pid)  # and says why not
            self.assertTrue(row['modelsHow'] and row['quotaHow'], pid)

    def test_the_rest_of_zook_follows_the_table(self):
        m, table = self.m, self.m.CLI_TABLE
        self.assertEqual(m.PLAN_KINDS, tuple(k for k, r in table.items() if r['readOnly']))
        self.assertEqual(set(m.GATED_KINDS), {k for k, r in table.items() if r['gated']})  # the safety gate keeps its own list (gate work elsewhere); they must agree
        for kind in ('codex', 'claude', 'grok', 'antigravity'): self.assertNotEqual(m.effort_args(kind, 'deep'), [], kind)
        self.assertEqual(m.effort_args('codex', 'medium'), ['-c', 'model_reasoning_effort="medium"'])
        self.assertEqual((m.effort_args('cursor', 'deep'), m.effort_args('gemini', 'deep'), m.effort_args('codex', 'standard')), ([], [], []))
        for name, kinds in m.FEATURES.items(): self.assertEqual(tuple(kinds), tuple(k for k, r in table.items() if name in r['features']), name)
        self.assertEqual(set(m.EFFORTS), set(m.ALL_EFFORTS))
        self.assertTrue(m.team_effort_ok(self.store, 'codex')); self.assertFalse(m.team_effort_ok(self.store, 'cursor')); self.assertFalse(m.team_effort_ok(self.store, 'gemini'))

    def test_window_gets_the_table(self):
        view = self.m.state_view(self.store)['cliTable']
        self.assertEqual([x['name'] for x in view['efforts']], ['標準', '快速', '中', '深入'])
        self.assertEqual([x['id'] for x in view['access']], ['full', 'folder', 'workspace'])
        clis = view['clis']
        self.assertEqual(set(clis), set(self.m.P.CATALOG))
        self.assertEqual(clis['cursor']['efforts'], ['standard']); self.assertIn('型號名稱', clis['cursor']['effortNote'])
        self.assertTrue(clis['cursor']['modelGroups'])
        self.assertEqual(clis['claude']['access'], ['full']); self.assertTrue(clis['claude']['gated'])
        self.assertEqual(clis['codex']['efforts'], ['standard', 'fast', 'medium', 'deep'])
        self.assertNotIn('effortFlag', clis['codex'])  # how the CLI is called stays on the Mac
        self.store.data['customProviders'] = [dict(id='custom-x', name='X', command='x')]
        self.assertEqual(self.m.state_view(self.store)['cliTable']['clis']['custom-x']['efforts'], ['standard'])

    def test_broken_level_is_said(self):
        self.store.data['abilityChecks'] = {'grok': dict(version='1', missing={'effort': ['--reasoning-effort']})}
        row = self.m.state_view(self.store)['cliTable']['clis']['grok']
        self.assertEqual(row['efforts'], ['standard']); self.assertIn('這個版本', row['effortNote'])

    def test_gemini_lists_models_without_the_cli(self):  # #204③
        got = self.m.model_list('gemini')
        self.assertEqual([x['id'] for x in got['models']], ['pro', 'flash', 'flash-lite']); self.assertEqual(got['status'], 'available')
        self.assertIn('Gemini CLI 沒有列出型號的指令', self.m.CLI_TABLE['gemini']['modelsHow'])

    def test_families(self):  # #220: Cursor's ~300 models in groups
        names = ['Auto（Cursor 自動選）', 'Codex 5.3 Low', 'GPT-5.2 High', 'Grok 4.6 Low'] + ['Claude Opus 5 %d' % i for i in range(30)] + ['Claude Sonnet 5 %d' % i for i in range(20)] + ['Gemini 3 Pro']
        models = [dict(id='m%d' % i, name=n) for i, n in enumerate(names)]
        self.m.add_families(models)
        fam = {x['name']: x['family'] for x in models}
        self.assertEqual((fam['Codex 5.3 Low'], fam['GPT-5.2 High'], fam['Grok 4.6 Low'], fam['Gemini 3 Pro'], fam['Auto（Cursor 自動選）']), ('Codex', 'GPT', 'Grok', 'Gemini', 'Auto'))
        self.assertEqual((fam['Claude Opus 5 1'], fam['Claude Sonnet 5 1']), ('Claude Opus', 'Claude Sonnet'))  # a family over 40 is split by its second word
        few = [dict(id='claude-opus', name='Claude Opus'), dict(id='claude-sonnet', name='Claude Sonnet')]
        self.m.add_families(few); self.assertEqual({x['family'] for x in few}, {'Claude'})
        bare = [dict(id='gpt-6-luna', name='gpt-6-luna')]; self.m.add_families(bare); self.assertEqual(bare[0]['family'], 'GPT')

    def test_model_card_shows_the_table(self):
        got = self.m.ability_view(self.store, 'gemini')
        self.assertEqual(got['table']['efforts'], ['standard']); self.assertFalse(got['table']['quota'])


class Front(unittest.TestCase):
    def test_no_menu_is_written_out_in_the_page(self):
        js = ''.join(JS.values())
        for gone in (r'\bEFFORTS\b', r'\bACCESS\b', r'\bGATED_CLIS\b'): self.assertIsNone(re.search(gone, js), gone)  # nor left in use anywhere (31-team.js had one)
        self.assertIn('cliRow(', JS['20-models.js'])

    @unittest.skipUnless(shutil.which('node'), 'needs node')
    def test_menus_from_the_table(self):
        state = {'data': {'settings': {'provider': 'codex'}, 'cliTable': {
            'efforts': [{'id': 'standard', 'name': '標準'}, {'id': 'fast', 'name': '快速'}, {'id': 'medium', 'name': '中'}, {'id': 'deep', 'name': '深入'}],
            'access': [{'id': 'full', 'name': '整台 Mac'}, {'id': 'folder', 'name': '指定資料夾'}, {'id': 'workspace', 'name': '只限 Bot 工作區'}],
            'clis': {'codex': {'efforts': ['standard', 'fast', 'medium', 'deep'], 'access': ['full', 'folder', 'workspace'], 'gated': False, 'readOnly': True},
                     'cursor': {'efforts': ['standard'], 'access': ['full'], 'gated': True, 'readOnly': True, 'effortNote': '寫在型號名稱裡'},
                     'gemini': {'efforts': ['standard'], 'access': ['full', 'folder', 'workspace'], 'gated': False, 'readOnly': False}}}}}
        code = snippet('20-models.js', r'// #246 table helpers.*?// end #246 table helpers\n')
        got = run_js('const state = %s;\n%s\nconsole.log(JSON.stringify([effortsFor("cursor").map(x => x.id), effortsFor("codex").map(x => x.id), accessFor("cursor").map(x => x.id), gatedCli("cursor"), gatedCli("codex"), planOk("gemini"), planOk("codex"), efforts().length, accessChoices().length, effortsFor("unknown").map(x => x.id)]))' % (json.dumps(state), code))
        self.assertEqual(got, [['standard'], ['standard', 'fast', 'medium', 'deep'], ['full'], True, False, False, True, 4, 3, ['standard']])

    @unittest.skipUnless(shutil.which('node'), 'needs node')
    def test_team_card_levels_from_the_table(self):  # review: 31-team.js still named the removed list and failed to draw
        state = {'data': {'settings': {'provider': 'codex'}, 'cliTable': {'efforts': [{'id': 'standard', 'name': '標準'}, {'id': 'deep', 'name': '深入'}], 'access': [],
                 'clis': {'claude': {'efforts': ['standard', 'deep'], 'access': ['full'], 'gated': True, 'readOnly': True}}}}, 'team': {'choices': [{'id': 'claude', 'name': 'Claude', 'effort': True}]}}
        helpers = snippet('20-models.js', r'// #246 table helpers.*?// end #246 table helpers\n')
        team = snippet('31-team.js', r'  function teamModelOptions.*?\n  function teamCard')[:-len('  function teamCard')]
        html = run_js('const esc = s => String(s); const dropdown = (n, v, o) => n + ":" + o.map(x => x.name).join(","); const state = %s;\n%s\n%s\nconsole.log(JSON.stringify(teamModelRow({provider: "claude", effort: ""})))' % (json.dumps(state), helpers, team))
        self.assertIn('effort:預設,標準,深入', html)

    @unittest.skipUnless(shutil.which('node'), 'needs node')
    def test_long_menu_has_groups_and_search(self):
        fn = snippet('20-models.js', r'  function dropdown\(.*?\n  \}\n')
        opts = [{'id': '', 'name': '預設'}] + [{'id': 'c%d' % i, 'name': 'Claude %d' % i, 'group': 'Claude'} for i in range(10)] + [{'id': 'g%d' % i, 'name': 'GPT %d' % i, 'group': 'GPT'} for i in range(10)]
        html = run_js('const esc = s => String(s);\n%s\nconsole.log(JSON.stringify(dropdown("m", "c3", %s)))' % (fn, json.dumps(opts)))
        self.assertIn('class="dd-search"', html)
        self.assertEqual(re.findall(r'class="dd-group"[^>]*>([^<]+)<', html), ['Claude', 'GPT'])
        short = run_js('const esc = s => String(s);\n%s\nconsole.log(JSON.stringify(dropdown("m", "", %s)))' % (fn, json.dumps(opts[:4])))
        self.assertNotIn('dd-search', short)

    @unittest.skipUnless(shutil.which('node'), 'needs node')
    def test_model_options_grouped(self):
        fn = snippet('20-models.js', r'  const modelOptionsHtml = .*?\n')
        models = [{'id': 'a', 'name': 'A1', 'family': 'Claude'}, {'id': 'b', 'name': 'B1', 'family': 'GPT'}, {'id': 'c', 'name': 'A2', 'family': 'Claude'}]
        html = run_js('const esc = s => String(s);\n%s\nconsole.log(JSON.stringify(modelOptionsHtml(%s, m => m.name, true)))' % (fn, json.dumps(models)))
        self.assertEqual(re.findall(r'<optgroup label="([^"]+)">', html), ['Claude', 'GPT'])
        self.assertLess(html.index('A2'), html.index('B1'))  # a family's models together, in the list's own order
        flat = run_js('const esc = s => String(s);\n%s\nconsole.log(JSON.stringify(modelOptionsHtml(%s, m => m.name, false)))' % (fn, json.dumps(models)))
        self.assertNotIn('optgroup', flat)


if __name__ == '__main__':
    unittest.main()
