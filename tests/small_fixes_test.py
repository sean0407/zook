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
        self.assertEqual(fields, dict(provider='codex', model='gpt-6.2-astra', account=EXTRA, effort='medium'))  # 中 is its own level since #103
        self.assertEqual(notes, [])
        self.assertEqual(self.m.tool_bot_fields(self.store, dict(provider='codex', effort='深入'))[0]['effort'], 'deep')

    def test_what_cannot_be_applied_is_said(self):
        fields, notes = self.m.tool_bot_fields(self.store, dict(account='Waifdance'))  # no CLI named: 自動選擇 has no account of its own
        self.assertNotIn('account', fields); self.assertTrue(any('Waifdance' in n for n in notes))
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='claude', account='Waifdance'))  # another CLI's account
        self.assertNotIn('account', fields); self.assertTrue(notes)
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='codex', account='不存在', effort='超級'))
        self.assertEqual(fields, dict(provider='codex')); self.assertEqual(len(notes), 2)

    def test_same_names_api_keys_and_thinking_levels(self):
        self.store.data['accounts'] += [dict(id='c' * 32, provider='codex', name='Work', type='login'), dict(id='d' * 32, provider='codex', name='work', type='key'),
                                        dict(id='e' * 32, provider='codex', name='公司', type='key')]
        self.assertEqual(self.m.tool_bot_fields(self.store, dict(provider='codex', account='Work'))[0]['account'], 'c' * 32)  # exact name first
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='codex', account='WORK'))
        self.assertNotIn('account', fields); self.assertIn('不只一個', notes[0])
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='codex', account='公司'))
        self.assertNotIn('account', fields); self.assertIn('API 計費', notes[0])
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='gemini', effort='high'))
        self.assertNotIn('effort', fields); self.assertTrue(notes)

    def test_a_full_window_that_has_reset_no_longer_decides(self):
        reset = {'windows': [dict(label='5 小時', usedPercent=100, resetsAt='2026-01-01T00:00:00+00:00')], 'limitReached': 'usage_limit_reached', 'updatedAt': self.m.NOW()}
        self.store.data['quota'] = {'codex': reset}
        self.assertFalse(self.m.limit_reached_now(reset)); self.assertFalse(self.m.auto_quota_low(self.store, 'codex'))

    def test_a_sign_in_known_to_bill_is_not_bound(self):
        self.store.data['accounts'].append(dict(id='f' * 32, provider='claude', name='Console', type='login'))
        self.store.data.setdefault('autoStatus', {})[self.m.auto_account_key(self.store.data['accounts'][-1])] = dict(signedIn=True, billed=True)
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='claude', account='Console'))
        self.assertNotIn('account', fields); self.assertIn('API 計費', notes[0])

    def test_a_version_without_thinking_levels_is_said(self):
        self.store.data['abilityChecks'] = {'claude': {'missing': {'effort': 'x'}}}
        fields, notes = self.m.tool_bot_fields(self.store, dict(provider='claude', effort='deep'))
        self.assertNotIn('effort', fields); self.assertTrue(notes)

    def test_an_old_limit_reading_no_longer_decides(self):
        old = {'windows': [], 'limitReached': 'workspace_owner_credits_depleted', 'updatedAt': '2026-01-01T00:00:00+00:00'}
        self.store.data['quota'] = {'codex': old}
        self.assertFalse(self.m.quota_exhausted(self.store, 'codex')); self.assertFalse(self.m.auto_quota_low(self.store, 'codex'))

    def test_a_workspace_out_of_credits_is_used_up(self):
        snap = {'windows': [{'label': '5 小時', 'usedPercent': 0, 'resetsAt': time.time() + 3600}], 'limitReached': 'workspace_owner_credits_depleted', 'updatedAt': self.m.NOW()}
        self.store.data['quota'] = {'codex': snap}
        self.assertTrue(self.m.quota_exhausted(self.store, 'codex'))
        self.assertTrue(self.m.auto_quota_low(self.store, 'codex'))
        self.store.data['quota'] = {'codex': dict(snap, limitReached=None)}
        self.assertFalse(self.m.quota_exhausted(self.store, 'codex')); self.assertFalse(self.m.auto_quota_low(self.store, 'codex'))


if __name__ == '__main__': unittest.main()
