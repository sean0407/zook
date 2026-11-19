# -*- coding: utf-8 -*-
"""自動選擇 looks at what a Bot is for, and spreads a group's members over different models."""
import importlib.util, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
TEAM = ['香氛產品研發', '香氛法規品質', '香氛品牌設計', '香氛行銷成長', '香氛通路銷售', '香氛營運財務']


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_auto_role', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class AutoRoleTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory()
        self.store = self.m.Store(Path(self.temp.name) / 'data')
        self.store.data['settings']['autoModels'] = ['codex', 'claude', 'grok']
        self.store.data['autoStatus'] = {p: dict(signedIn=True, billed=False) for p in ('codex', 'claude', 'grok')}
        self.patches = [mock.patch.object(self.m, 'find_cli', return_value='/bin/true'), mock.patch.object(self.m, 'ability_on', return_value=True)]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def pick(self, text, **more):
        chain, mark = self.m.pick_auto(self.store, text, **more)
        return chain[0][0], mark

    def test_role_is_read_from_the_name_then_the_persona(self):
        role = self.m.auto_role
        self.assertEqual([role(dict(name=n)) for n in TEAM], ['analysis', 'analysis', None, None, None, 'analysis'])
        self.assertEqual(role(dict(name='工程師')), 'code'); self.assertEqual(role(dict(name='Backend Engineer')), 'code')
        self.assertIsNone(role(dict(name='工作助理', persona='', instructions='')))
        self.assertEqual(role(dict(name='小美', persona='你是公司的財務長。')), 'analysis')
        shared = '這是香氛體香膏事業團隊的一員。將已知事實、推測與待驗證項目分開，涉及法規與品質的內容要標註來源，並提出策略與規劃。'
        self.assertEqual(role(dict(name='香氛品牌設計', persona='負責品牌視覺', instructions=shared)), None)  # a text the whole team shares does not make everyone an analyst
        self.assertIsNone(role(dict(name='apiary keeper')))  # a word that merely contains "api" is not a coding role

    def test_plain_question_follows_the_bots_role(self):
        ask = '公司開張第一天，大家說說自己的看法'
        self.assertEqual(self.pick(ask)[0], 'claude')  # no Bot given: a short question goes to the fastest model
        self.assertEqual(self.pick(ask, bot=dict(name='香氛品牌設計'))[0], 'claude')
        model, mark = self.pick(ask, bot=dict(name='香氛法規品質'))
        self.assertEqual((model, mark['auto']), ('claude', 'Claude analysis')); self.assertIn('角色偏向長篇分析', mark['autoWhy'])
        self.assertEqual(self.pick(ask, bot=dict(name='工程師'))[0], 'codex')
        # What the message plainly asks for still comes first.
        self.assertEqual(self.pick('幫我修這段 python 的 bug', bot=dict(name='香氛法規品質'))[0], 'codex')
        self.assertEqual(self.pick('請比較兩個方案的優缺點', bot=dict(name='香氛品牌設計'))[0], 'claude')

    def test_group_members_are_spread_over_the_models(self):
        ask, taken, got = '公司開張第一天，大家說說自己的看法', [], {}
        for name in TEAM:
            model, mark = self.pick(ask, bot=dict(name=name), taken=taken)
            got[name] = model; taken.append(model)
        self.assertEqual(sorted(set(got.values())), ['claude', 'codex', 'grok'])
        self.assertEqual({m: list(got.values()).count(m) for m in set(got.values())}, {'claude': 2, 'codex': 2, 'grok': 2})
        self.assertEqual(got['香氛產品研發'], 'claude'); self.assertEqual(got['香氛品牌設計'], 'grok')  # the first of each kind gets its best fit
        self.assertNotEqual(got['香氛法規品質'], 'grok')  # a careful role is not handed the quick model while better ones are free
        # In later turns of the same round a member stays on the model it started with.
        model, mark = self.pick(ask, bot=dict(name='香氛法規品質'), taken=['grok', 'grok'], keep=got['香氛法規品質'])
        self.assertEqual(model, got['香氛法規品質'])
        # When spreading changes the choice, the mark says so.
        model, mark = self.pick(ask, bot=dict(name='香氛營運財務'), taken=['claude'])
        self.assertEqual(model, 'codex'); self.assertIn('分散使用不同模型', mark['autoWhy'])

    def test_low_quota_model_is_still_left_out(self):
        self.store.data['quota'] = {'claude': dict(updatedAt=self.m.NOW(), windows=[dict(label='5 小時', usedPercent=95, resetsAt=__import__('time').time() + 3600)])}
        model, mark = self.pick('今天有什麼看法', bot=dict(name='香氛法規品質'), taken=[])
        self.assertEqual(model, 'codex')

    def test_group_size(self):
        self.assertEqual((self.m.GROUP_MIN_BOTS, self.m.GROUP_MAX_BOTS), (2, 10))


if __name__ == '__main__':
    unittest.main()
