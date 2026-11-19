# -*- coding: utf-8 -*-
"""What is left of each model's limits, and the cost and token overview on the usage page."""
import datetime, importlib.util, json, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_usage_view', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def ago(days=0): return (datetime.datetime.now().astimezone() - datetime.timedelta(days=days)).isoformat()


class UsageViewTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.store = self.m.Store(Path(self.temp.name) / 'data')
        self.bot = dict(id='b1', name='助理', messages=[]); self.store.data['bots'].append(self.bot)

    def tearDown(self): self.temp.cleanup()

    def job(self, provider, model, days=0, **usage):
        job = dict(id=self.m.ID(), botId='b1', status='completed', createdAt=ago(days), finishedAt=ago(days), usage=dict(dict(provider=provider, model=model, costUsd=None), **usage))
        self.store.data['jobs'].append(job); return job

    def test_rings_say_what_is_left(self):
        soon, past = time.time() + 3600, time.time() - 60
        self.store.data['quota'] = {'codex': {'windows': [{'label': '5 小時', 'usedPercent': 7, 'resetsAt': soon}, {'label': '每週', 'usedPercent': 85, 'resetsAt': soon}], 'updatedAt': ago()},
                                    'claude': {'windows': [{'label': '5 小時', 'usedPercent': 96, 'resetsAt': past}], 'updatedAt': ago()},
                                    'antigravity': {'windows': [{'label': 'Gemini 模型 · 每週', 'usedPercent': 100, 'resetsAt': soon}, {'label': 'Claude 與 GPT 模型 · 每週', 'usedPercent': 20, 'resetsAt': soon}], 'updatedAt': ago()}}
        self.store.data['autoStatus'] = {'grok': dict(signedIn=True, billed=False), 'gemini': dict(signedIn=False, billed=False)}
        self.store.data['settings']['addedProviders'] = ['codex', 'claude', 'grok', 'antigravity', 'gemini']
        rings = {r['id']: r for r in self.m.usage_rings(self.store)}
        self.assertEqual(list(rings)[:5], ['codex', 'claude', 'grok', 'antigravity', 'gemini'])  # every model, signed in or not
        self.assertEqual((rings['codex']['fiveHour'], rings['codex']['week'], rings['codex']['left']), (93, 15, 15)); self.assertEqual([w['left'] for w in rings['codex']['windows']], [93, 15])
        self.assertEqual((rings['claude']['fiveHour'], rings['claude']['week']), (100, None))  # that limit has reset since it was read
        self.assertEqual((rings['grok']['left'], rings['grok']['windows'], rings['grok']['known']), (None, [], True))  # signed in, no limit data
        self.assertEqual((rings['antigravity']['fiveHour'], rings['antigravity']['week']), (None, 0))  # follows the model Zook runs by default
        self.assertEqual((rings['gemini']['known'], rings['gemini']['left']), (False, None))
        self.assertEqual(self.m.state_view(self.store)['rings'], self.m.usage_rings(self.store))

    def test_price_only_for_models_on_the_list(self):
        price, cost = self.m.price_for, self.m.usage_cost
        self.assertEqual(price('gpt-6-sol'), price('openai/gpt-6-sol')); self.assertEqual(price('claude-sonnet-5-5'), price('claude-sonnet-5.5'))
        self.assertIsNone(price('預設模型')); self.assertIsNone(price('gpt-6-sol-future')); self.assertIsNone(price(''))
        row = price('gpt-6-sol')
        got, kind = cost(dict(model='gpt-6-sol', input=1000000, cachedInput=400000, output=100000, costUsd=None))
        self.assertEqual(kind, 'estimated'); self.assertAlmostEqual(got, 0.6 * row[0] + 0.4 * row[1] + 0.1 * row[3])
        self.assertEqual(cost(dict(model='whatever', input=5, output=5, costUsd=0.25)), (0.25, 'reported'))  # the CLI's own figure wins
        self.assertEqual(cost(dict(model='預設模型', input=5, output=5, costUsd=None)), (None, None))

    def test_overview_adds_up_by_hand(self):
        self.job('claude', 'claude-sonnet-5-5', 0, input=1000, cachedInput=600, cacheWrite=100, output=50, costUsd=0.02)
        self.job('claude', 'claude-sonnet-5-5', 1, input=2000, cachedInput=0, cacheWrite=0, output=10, costUsd=0.01)
        self.job('codex', 'gpt-6-sol', 0, input=1000000, cachedInput=500000, output=1000)
        self.job('codex', '預設模型', 0, input=10, cachedInput=0, output=1)
        self.job('codex', 'gpt-6-sol', 40, input=999, cachedInput=0, output=9)  # outside 30 days
        self.bot['messages'] = [dict(id='1', role='user', content='hi', createdAt=ago()), dict(id='2', role='assistant', content='x', createdAt=ago()), dict(id='3', role='user', author='排程', content='x', createdAt=ago()), dict(id='4', role='user', content='old', createdAt=ago(40))]
        o = self.m.usage_overview(self.store, 30); row = self.m.price_for('gpt-6-sol')
        codex = (500000 * row[0] + 500000 * row[1] + 1000 * row[3]) / 1e6
        self.assertAlmostEqual(o['cost'], round(0.03 + codex, 4)); self.assertEqual((o['replies'], o['unpriced'], len(o['days'])), (4, 1, 30))
        t = o['totals']
        self.assertEqual((t['withCacheRead'], t['withoutCacheRead'], t['cachedInput'], t['output'], t['sent'], t['replies']), (1003010 + 1061, 1003010 + 1061 - 500600, 500600, 1061, 1, 4))
        self.assertEqual(t['freshInput'], 1003010 - 500600 - 100); self.assertEqual(t['cacheWrite'], 100)
        self.assertEqual(t['freshInput'] + t['cachedInput'] + t['cacheWrite'] + t['output'], t['withCacheRead'])  # nothing is counted twice
        by = {p['id']: p for p in o['providers']}
        self.assertEqual((by['claude']['kind'], by['codex']['kind'], by['codex']['unpriced'], by['codex']['unpricedModels']), ('reported', 'estimated', 1, ['預設模型']))
        self.assertEqual(by['claude']['daily'][-2:], [0.01, 0.02]); self.assertAlmostEqual(sum(p['share'] for p in o['providers']), 100, delta=0.2)
        self.assertEqual(self.m.usage_overview(self.store, 90)['replies'], 5)
        self.assertRaises(ValueError, self.m.usage_overview, self.store, 31)

    def test_cache_write_is_a_dash_when_no_cli_reports_it(self):
        self.job('codex', 'gpt-6-sol', 0, input=100, cachedInput=0, output=1)
        self.assertIsNone(self.m.usage_overview(self.store, 7)['totals']['cacheWrite'])

    def test_chart_is_the_same_after_old_replies_are_folded_away(self):
        for days in (2, 35, 60): self.job('claude', 'claude-sonnet-5-5', days, input=1000, cachedInput=200, cacheWrite=50, output=30, costUsd=0.5)['slim'] = True
        before = self.m.usage_overview(self.store, 90)
        self.m.trim_jobs(self.store)
        self.assertEqual(len(self.store.data['jobs']), 1)
        after = self.m.usage_overview(self.store, 90)
        self.assertEqual(before, after); self.assertEqual(after['cost'], 1.5)
        self.assertNotIn('usageDaily', self.m.state_view(self.store))

    def test_claude_and_grok_report_cache_writes(self):
        claude = json.dumps({'type': 'result', 'result': 'hi', 'usage': {'input_tokens': 10, 'cache_read_input_tokens': 300, 'cache_creation_input_tokens': 40, 'output_tokens': 5}, 'total_cost_usd': 0.01})
        u = self.m.parse_cli_output('claude', claude)['usage']
        self.assertEqual((u['input'], u['cachedInput'], u['cacheWrite'], u['output']), (350, 300, 40, 5))
        codex = json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 60, 'output_tokens': 5}})
        self.assertNotIn('cacheWrite', self.m.parse_cli_output('codex', codex, 'gpt-6-sol')['usage'])

    def test_codex_default_model_is_read_from_its_settings(self):
        home = Path(self.temp.name) / 'codex'; home.mkdir()
        (home / 'config.toml').write_text('model = "gpt-6-luna"\nmodel_reasoning_effort = "medium"\n[profiles.x]\nmodel = "other"\n')
        self.assertEqual(self.m.codex_default_model({'CODEX_HOME': str(home)}), 'gpt-6-luna')
        self.assertEqual(self.m.codex_default_model({'CODEX_HOME': str(home / 'missing')}), '')


if __name__ == '__main__': unittest.main()
