# -*- coding: utf-8 -*-
"""自動選擇 matches a Bot by its work only, never by the quota left at that moment (2026-11-22), and Bots 0.20.0 matched by the
quota left are matched again once."""
import importlib.util, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
OLD = '分析和寫報告多，配 Codex（Claude 額度不足）'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_auto_work', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class AutoWorkTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory()
        self.store = self.m.Store(Path(self.temp.name) / 'data'); self.store.data['bots'].clear()
        self.store.data['settings'].update(autoModels=['codex', 'claude'], autoFixed=True, permissionMode='bypass', access='full')
        self.store.data['autoStatus'] = {p: dict(signedIn=True, billed=False, checkedAt=time.time()) for p in ('codex', 'claude')}
        self.store.data['quota'] = {'claude': dict(updatedAt=self.m.NOW(), windows=[dict(label='5 小時', usedPercent=97, resetsAt=time.time() + 3600)])}
        self.log = mock.MagicMock()
        self.patches = [mock.patch.object(self.m, 'find_cli', return_value='/bin/true'), mock.patch.object(self.m, 'ability_on', return_value=True),
                        mock.patch.object(self.m, 'codex_default_model', return_value=''), mock.patch.object(self.m, 'log_activity', self.log),
                        mock.patch.object(self.m, 'refresh_auto_status', side_effect=lambda store, wait=False: self.m.auto_retry(store))]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def logged(self): return [c.args[2] for c in self.log.call_args_list]

    def test_analysis_bot_gets_claude_even_when_its_quota_is_low(self):
        bot = dict(id='a', name='分析師', provider='auto', persona='細心的分析師')
        reason = self.m.auto_on_create(self.store, bot, grant=True)
        self.assertEqual(bot['provider'], 'claude'); self.assertNotIn('額度不足', reason); self.assertTrue(bot['autoAssigned'])
        coder = dict(id='b', name='工程師', provider='auto', instructions='你是工程師')
        self.m.auto_on_create(self.store, coder)
        self.assertEqual(coder['provider'], 'codex')
        self.store.data['quota']['codex'] = dict(updatedAt=self.m.NOW(), windows=[dict(label='5 小時', usedPercent=99, resetsAt=time.time() + 3600)])
        both = dict(id='c', name='分析師二', provider='auto', persona='細心的分析師')
        self.assertTrue(self.m.auto_on_create(self.store, both))  # every quota low: still matched by the work
        self.assertEqual(both['provider'], 'claude')
        self.store.data['settings']['autoModels'] = []
        none = dict(id='d', name='分析師三', provider='auto', persona='細心的分析師')
        self.assertEqual(self.m.auto_on_create(self.store, none), ''); self.assertEqual(none['provider'], 'auto')  # nothing usable: each message picks

    def test_old_quota_matches_are_matched_again_once_and_told(self):
        m, store = self.m, self.store
        moved = dict(id='a', name='分析師', provider='codex', account='', model='gpt-5.5', persona='細心的分析師', autoAssigned=True, autoReason=OLD)
        stays = dict(id='b', name='工程師', provider='codex', account='', model='gpt-5.5', instructions='你是工程師', autoAssigned=True, autoReason='寫程式多，配 Codex（Claude 額度不足）')
        fine = dict(id='c', name='另一位分析師', provider='codex', account='', model='gpt-5.5', persona='細心的分析師', autoAssigned=True, autoReason='分析和寫報告多，配 Codex')
        store.data['bots'] += [moved, stays, fine]
        m.auto_migrate(store)
        self.assertEqual((moved['provider'], moved['autoReason'], moved['autoModelPending']), ('claude', '分析和寫報告多，配 Claude', True))
        self.assertEqual((stays['provider'], stays['model'], stays['autoReason']), ('codex', 'gpt-5.5', '寫程式多，配 Codex'))
        self.assertEqual((fine['provider'], fine['autoReason']), ('codex', '分析和寫報告多，配 Codex'))  # matched without a quota note: left alone
        self.assertTrue(all('autoRematch' not in b for b in store.data['bots']))
        told = self.logged()
        self.assertEqual(len(told), 1); self.assertIn('分析師', told[0]); self.assertIn('改配 Claude', told[0]); self.assertNotIn('額度不足', told[0])
        self.assertTrue(store.data['settings']['autoByWork'])
        # Only once: a Bot with the old note found later (another restart) is not matched again.
        again = dict(id='d', name='分析師四', provider='codex', account='', persona='細心的分析師', autoAssigned=True, autoReason=OLD)
        store.data['bots'].append(again); self.log.reset_mock()
        m.auto_migrate(store)
        self.assertEqual(again['provider'], 'codex'); self.assertEqual(self.logged(), [])
        saved = m.Store(store.dir)
        self.assertTrue(saved.data['settings']['autoByWork']); self.assertEqual(saved.find('bots', 'a')['provider'], 'claude')

    def test_waits_until_a_model_can_be_picked(self):
        m, store = self.m, self.store
        bot = dict(id='a', name='分析師', provider='codex', account='', persona='細心的分析師', autoAssigned=True, autoReason=OLD)
        store.data['bots'].append(bot); store.data.pop('autoStatus')
        m.auto_migrate(store)
        self.assertEqual((bot['provider'], bot['autoRematch']), ('codex', True))  # sign-ins not known yet: tried after the next check
        store.data['autoStatus'] = {p: dict(signedIn=True, billed=False, checkedAt=time.time()) for p in ('codex', 'claude')}
        m.auto_retry(store)
        self.assertEqual(bot['provider'], 'claude'); self.assertNotIn('autoRematch', bot)

    def test_rematch_never_widens_access(self):
        m, store = self.m, self.store
        bot = dict(id='a', name='分析師', provider='codex', account='', persona='細心的分析師', autoAssigned=True, autoReason=OLD, permissionMode='bypass', access='full')
        store.data['bots'].append(bot)
        m.auto_migrate(store)
        self.assertEqual((bot['provider'], bot.get('gateFull'), bot['localLimit']), ('claude', None, True))
        self.assertEqual((m.permission_mode(store, bot, 'claude'), m.bot_scope(bot, 'claude')), ('manual', ('workspace', '')))

    def test_another_macs_choice_is_not_matched_again(self):
        m, store = self.m, self.store
        bot = dict(id='a', name='分析師', provider='codex', account='', persona='細心的分析師', autoAssigned=True, autoReason=OLD, messages=[], chats=[])
        store.data['bots'].append(bot)
        self.assertTrue(m.sync_put(store, 'bots:a', m.sync_clean('bots:a', dict(name='分析師', provider='grok', model='', persona='細心的分析師'))))
        self.assertNotIn('autoAssigned', bot); self.assertNotIn('autoReason', bot)  # picked by hand on the other Mac
        synced = dict(id='b', name='分析師二', messages=[], chats=[])
        store.data['bots'].append(synced)
        self.assertTrue(m.sync_put(store, 'bots:b', m.sync_clean('bots:b', dict(name='分析師二', provider='codex', model='gpt-5.5', persona='細心的分析師', fixedModel=True))))
        m.auto_migrate(store)
        self.assertEqual((bot['provider'], store.find('bots', 'b')['provider']), ('grok', 'codex')); self.assertEqual(self.logged(), [])


if __name__ == '__main__':
    unittest.main()
