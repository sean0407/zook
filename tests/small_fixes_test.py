# -*- coding: utf-8 -*-
"""0.18.3: a Bot made by a Bot gets the account and thinking level it was asked for (or is told plainly it could not),
and an account whose workspace ran out of credits counts as used up."""
import importlib.util, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
EXTRA, KEY = 'a' * 32, 'b' * 32


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_small_fixes', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class SmallFixesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = self.m.Store(Path(self.temp.name) / 'data')
        self.store.data['accounts'] = [dict(id=EXTRA, provider='codex', name='Waifdance', type='login'), dict(id=KEY, provider='claude', name='公司金鑰', type='key')]
        self.m._active['data'] = self.store.data

    def tearDown(self): self.temp.cleanup()

    def test_account_and_thinking_level_are_applied(self):
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='codex', model='gpt-6.2-astra', account='waifdance', effort='medium'))
        self.assertEqual(fields, dict(provider='codex', model='gpt-6.2-astra', account=EXTRA, effort='standard'))
        self.assertEqual(notes, [])
        self.assertEqual(self.m.tool_bot_fields(self.store, dict(provider='codex', effort='深入'))[0]['effort'], 'deep')

    def test_what_cannot_be_applied_is_said(self):
        fields, notes = self.m.tool_bot_fields(self.store, dict(account='Waifdance'))  # no CLI named: 自動選擇 has no account of its own
        self.assertNotIn('account', fields); self.assertTrue(any('Waifdance' in n for n in notes))
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='claude', account='Waifdance'))  # another CLI's account
        self.assertNotIn('account', fields); self.assertTrue(notes)
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='codex', account='不存在', effort='超級'))
        self.assertEqual(fields, dict(provider='codex')); self.assertEqual(len(notes), 2)

    def test_a_workspace_out_of_credits_is_used_up(self):
        snap = {'windows': [{'label': '5 小時', 'usedPercent': 0, 'resetsAt': time.time() + 3600}], 'limitReached': 'workspace_owner_credits_depleted', 'updatedAt': '2026-11-21T00:00:00+00:00'}
        self.store.data['quota'] = {'codex': snap}
        self.assertTrue(self.m.quota_exhausted(self.store, 'codex'))
        self.assertTrue(self.m.auto_quota_low(self.store, 'codex'))
        self.store.data['quota'] = {'codex': dict(snap, limitReached=None)}
        self.assertFalse(self.m.quota_exhausted(self.store, 'codex')); self.assertFalse(self.m.auto_quota_low(self.store, 'codex'))


if __name__ == '__main__': unittest.main()
