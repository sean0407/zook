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

    def test_old_match_changed_since_is_left_alone(self):
        m, store = self.m, self.store
        bot = dict(id='a', name='分析師', provider='grok', account='', persona='細心的分析師', autoAssigned=True, autoReason=OLD, autoModelPending=True)
        store.data['bots'].append(bot)
        m.auto_migrate(store)
        self.assertEqual(bot['provider'], 'grok'); self.assertEqual(self.logged(), [])
        self.assertFalse([k for k in bot if k.startswith('auto')])  # only the leftover marks are cleared
        found = m._OLD_MATCH.search('分析和寫報告多，配 Codex（Waifdance）（Claude（Home） 額度不足）')
        self.assertEqual(found.group(1), 'Codex（Waifdance）')

    def test_best_fit_signed_out_waits_for_it(self):
        m, store = self.m, self.store
        store.data['autoStatus']['claude']['signedIn'] = False
        bot = dict(id='a', name='分析師', provider='codex', account='', model='gpt-5.5', persona='細心的分析師', autoAssigned=True, autoReason=OLD)
        store.data['bots'].append(bot)
        m.auto_migrate(store)
        self.assertEqual((bot['provider'], bot['autoRematch']), ('codex', True)); self.assertEqual(self.logged(), [])
        store.data['autoStatus']['claude']['signedIn'] = True
        m.auto_retry(store)
        self.assertEqual(bot['provider'], 'claude'); self.assertNotIn('autoRematch', bot)

    def test_bots_left_on_auto_when_every_quota_was_low_are_matched(self):
        m, store = self.m, self.store
        bot = dict(id='a', name='分析師', provider='auto', persona='細心的分析師')  # 0.20.0 could pick nothing and did not mark it
        store.data['bots'].append(bot)
        m.auto_migrate(store)
        self.assertEqual((bot['provider'], bot['autoAssigned']), ('claude', True))
        self.assertIn('固定配好', self.logged()[0])

    def test_an_old_mac_writing_back_its_pick_is_matched_again(self):
        m, store = self.m, self.store
        bot = dict(id='a', name='分析師', provider='codex', account='', model='gpt-5.5', persona='細心的分析師', autoAssigned=True, autoReason=OLD, messages=[], chats=[])
        store.data['bots'].append(bot)
        m.auto_migrate(store)
        self.assertEqual(bot['provider'], 'claude')
        old = m.sync_clean('bots:a', dict(name='分析師', provider='codex', model='gpt-5.5', persona='細心的分析師', fixedModel=True))  # 0.20.0 on the other Mac
        self.assertTrue(m.sync_put(store, 'bots:a', dict(old)))
        self.assertEqual((bot['provider'], bot['autoRematch'], bot['autoAssigned']), ('codex', True, True))
        self.log.reset_mock(); m.auto_retry(store)
        self.assertEqual(bot['provider'], 'claude'); self.assertEqual(len(self.logged()), 1)
        hand = m.sync_clean('bots:a', dict(name='分析師', provider='codex', model='gpt-5.5', persona='細心的分析師'))  # picked by hand there
        self.assertTrue(m.sync_put(store, 'bots:a', dict(hand)))
        self.log.reset_mock(); m.auto_retry(store)
        self.assertEqual(bot['provider'], 'codex'); self.assertFalse([k for k in bot if k.startswith('auto')]); self.assertEqual(self.logged(), [])

    def add_accounts(self):
        store, now = self.store, time.time()
        store.data['accounts'] = [dict(id='w1', provider='claude', name='Work', type='login'), dict(id='w2', provider='claude', name='Home', type='login')]
        for a in ('w1', 'w2'): store.data['autoStatus']['claude@' + a] = dict(signedIn=True, billed=False, checkedAt=now)
        store.data['quota'].update({'claude@w1': dict(updatedAt=self.m.NOW(), windows=[dict(label='5 小時', usedPercent=80, resetsAt=now + 3600)]),
                                    'claude@w2': dict(updatedAt=self.m.NOW(), windows=[dict(label='5 小時', usedPercent=20, resetsAt=now + 3600)])})

    def test_backups_try_the_same_cli_first_then_the_choices_for_the_work(self):
        m, store = self.m, self.store
        self.add_accounts()
        bot = dict(id='a', name='分析師', provider='claude', account='', model='claude-opus-5-5', persona='細心的分析師', autoAssigned=True)
        self.assertEqual(m.auto_backups(store, bot, 'claude'), [['claude', 'claude-opus-5-5', 'w2'], ['claude', 'claude-opus-5-5', 'w1'], ['codex', '', '']])
        store.data['settings']['fallbacks'] = ['codex']  # the user's own backups come first, and are not tried twice
        chain = [list(x) for x in m.provider_chain(store, bot, 'claude', bot['model'])] + m.auto_backups(store, bot, 'claude')
        self.assertEqual([x[0] for x in chain], ['claude', 'codex', 'claude', 'claude'])
        self.assertEqual(m.auto_backups(store, dict(bot, autoAssigned=False), 'claude'), [])  # a model the user chose: only its own backups
        self.assertEqual(m.auto_backups(store, bot, 'claude', dict(autoNamed=True, redoOf='x')), [])  # 換模型重答 names the model
        store.data['settings']['autoModels'] = ['codex']  # the default Claude sign-in is off: an extra account is still a choice
        made = dict(id='b', name='分析師二', provider='auto', persona='細心的分析師')
        m.auto_on_create(store, made)
        self.assertEqual((made['provider'], made['account']), ('claude', 'w1'))

    def test_a_used_up_match_answers_with_a_backup_this_once(self):
        m, store = self.m, self.store
        self.add_accounts()
        store.data['quota']['claude'] = dict(updatedAt=m.NOW(), windows=[dict(label='5 小時', usedPercent=100, resetsAt=time.time() + 3600)])
        bot = dict(id='a', name='分析師', provider='claude', account='', model='', persona='細心的分析師', autoAssigned=True, autoReason='分析和寫報告多，配 Claude',
                   messages=[dict(id='m1', role='assistant', content='', status='running')], chats=[])
        store.data['bots'].append(bot)
        store.data['jobs'].append(dict(id='j', botId='a', messageId='m1', status='running', createdAt=m.NOW()))
        app = m.App(('127.0.0.1', 0), store, self.temp.name, 'local-token'); ran = []
        def attempt(job_id, prompt, p, model, run_bot, inventory, final):
            ran.append((p, run_bot.get('account') or ''))
            with store.lock: store.find('jobs', job_id)['status'] = 'completed'
        try:
            with mock.patch.object(app, '_run_attempt', side_effect=attempt), mock.patch.object(m, 'auto_recheck_live'), mock.patch.object(m, 'auto_recheck'):
                app._run_job('j', 'hi', 'claude', '', bot=dict(bot))
        finally: app.server_close()
        self.assertEqual(ran, [('claude', 'w2')])  # Claude itself is used up: its other account with most left
        self.assertIn('這次改用 Claude（Home）', bot['messages'][0]['note']); self.assertIn('額度已用完', bot['messages'][0]['note'])
        self.assertEqual((bot['provider'], bot['account']), ('claude', ''))  # the match stays

    def test_held_in_is_told(self):
        m, store = self.m, self.store
        bot = dict(id='a', name='分析師', provider='codex', account='', persona='細心的分析師', autoAssigned=True, autoReason=OLD)
        store.data['bots'].append(bot)
        m.auto_migrate(store)
        self.assertIn('改配 Claude', self.logged()[0]); self.assertIn('存取改成只限工作資料夾、先問，要放寬請到 Bot 設定', self.logged()[0])


if __name__ == '__main__':
    unittest.main()
