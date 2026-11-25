# -*- coding: utf-8 -*-
"""Queue #46: whenever Zook itself holds Bots in to their workspace and 先問 (an upgrade, a backup put back, a damaged data file,
another Mac, 自動選擇 matching again, a Bot made by a Bot or on the phone), one plain line goes into the activity record and one
Mac notification is queued, naming the Bots, why, and where to widen them again. The rules themselves are unchanged."""
import importlib.util, json, os, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
sys.path.insert(0, str(ROOT / 'backend'))


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_held_notice', SERVER)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


m = load()


class HeldNoticeTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {'ZOOK_NO_INTRO': '1'}); env.start(); self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = m.Store(Path(self.temp.name) / 'data')
        self.app = self.start(self.store)
        self.store.data['settings'].update(permissionMode='bypass', access='full')
        for p in (mock.patch.object(m, 'find_cli', return_value='/bin/true'), mock.patch.object(m, 'ability_on', return_value=True),
                  mock.patch.object(m, 'codex_default_model', return_value=''), mock.patch.object(m, 'watch_auto_status', lambda store, bot: None)):
            p.start(); self.addCleanup(p.stop)

    def start(self, store):
        app = m.App(('127.0.0.1', 0), store, self.temp.name, 'local-token')
        threading.Thread(target=app.serve_forever, daemon=True).start()
        self.addCleanup(app.server_close); self.addCleanup(app.shutdown)
        return app

    def told(self, app=None):
        """(activity lines about holding in, notifications about it)."""
        lines = [x['text'] for x in m.activity_list(self.store)['items'] if '只限工作資料夾' in x['text']]
        return lines, [n for n in (app or self.app).notices if '只限工作資料夾' in n['body']]

    def check_one(self, names, why, app=None):
        lines, notes = self.told(app)
        self.assertEqual(len(lines), 1, lines); self.assertEqual(len(notes), 1, notes)
        for name in names: self.assertIn('「%s」' % name, lines[0]); self.assertIn('「%s」' % name, notes[0]['body'])
        self.assertIn(why, lines[0]); self.assertIn(why, notes[0]['body'])
        self.assertIn('編輯設定', lines[0]); self.assertIn('存取範圍', lines[0])  # where to widen it
        self.assertIn('編輯設定', notes[0]['body'])
        self.assertEqual((notes[0]['kind'], notes[0]['targetId']), ('page', 'activity'))  # the notification opens the activity record
        self.assertIn('收緊', notes[0]['title'])
        return lines[0], notes[0]

    def test_upgrade_that_holds_in_bots_made_by_a_bot_says_so(self):
        store = self.store
        with store.lock:
            admin = next(b for b in store.data['bots'] if b.get('isAdmin'))
            store.data['bots'] += [dict(id='qa', name='QA 測試工程師', provider='codex', access='full', permissionMode='bypass'),
                                   dict(id='pm', name='產品經理', provider='codex', access='full', permissionMode='bypass'),
                                   dict(id='own', name='自己的', provider='codex')]
            store.data['jobs'].append(dict(id='j', botId=admin['id'], status='done', toolCalls=[dict(name='zook_create_bot', arguments=dict(name=n)) for n in ('QA 測試工程師', '產品經理')]))
            store.data['settings'].pop('heldInSet', None)
        m.local_migrate(store)
        line, _ = self.check_one(['QA 測試工程師', '產品經理'], '升級')
        self.assertNotIn('自己的', line)
        m.local_migrate(store)
        self.assertEqual([len(x) for x in self.told()], [1, 1])  # once

    def test_bots_held_in_by_an_earlier_version_are_told_once(self):
        store = self.store
        with store.lock:
            store.data['bots'].append(dict(id='qa', name='QA 測試工程師', provider='codex', localLimit=True, access='workspace', permissionMode='manual'))
            store.data['settings'].pop('heldTold', None)
        m.local_migrate(store)
        self.check_one(['QA 測試工程師'], '之前的版本')
        m.local_migrate(store)
        self.assertEqual([len(x) for x in self.told()], [1, 1])

    def test_nothing_is_said_when_nothing_was_held_in(self):
        store = self.store
        with store.lock:
            store.data['settings'].pop('heldInSet', None)
            name = m.backup_write(store, 'manual', json.loads(json.dumps(store.data)))
            m.backup_restore(self.app, name)
        m.local_migrate(store)
        self.assertEqual(self.told(), ([], []))

    def test_restore_names_the_bots_it_held_in(self):
        store = self.store
        with store.lock:
            copy_ = json.loads(json.dumps(store.data))
            copy_['bots'].append(dict(id='old', name='舊 Bot', provider='codex', access='full', permissionMode='bypass', messages=[], chats=[]))
            mine = next(b for b in store.data['bots'] if not b.get('isAdmin')); mine.update(provider='codex', access='full', permissionMode='auto')
            next(b for b in copy_['bots'] if b['id'] == mine['id'])['provider'] = 'claude'  # another CLI in the copy: loses what it had here
            store.save()
            name = m.backup_write(store, 'manual', copy_)
            m.backup_restore(self.app, name)
        self.check_one(['舊 Bot', mine['name']], '還原備份')

    def test_a_damaged_data_file_is_told_once_the_window_is_there(self):
        store = self.store
        with store.lock:
            m.backup_write(store, 'auto', store.data)
            names = [b['name'] for b in store.data['bots']]
        store.path.write_text('{broken')
        fresh = m.Store(store.dir)  # recover_data runs here, before the service is up
        app = self.start(fresh)
        lines = [x['text'] for x in m.activity_list(fresh)['items'] if '只限工作資料夾' in x['text']]
        notes = [n for n in app.notices if '只限工作資料夾' in n['body']]
        self.assertEqual((len(lines), len(notes)), (1, 1))
        for name in names: self.assertIn('「%s」' % name, lines[0])
        self.assertIn('資料檔', lines[0])

    def test_a_bot_from_another_mac_is_told(self):
        store = self.store; folder = Path(self.temp.name) / 'sync'; folder.mkdir()
        with store.lock:
            state = m.sync_state(store); state['folder'] = str(folder)
            m.sync_marks(store)['stamps']['x'] = ['x', 1, True, []]  # not joining: what the other Mac has that is newer is taken
        value = dict(name='遠端助理', provider='codex', model='')
        others = [('other-mac', {'bots:farbot1': dict(t=time.time() - 5, h='', p=[], v=value)}, {})]
        with mock.patch.object(m, 'sync_read_others', return_value=others): m.sync_pass(self.app)
        self.assertTrue(store.find('bots', 'farbot1')['localLimit'])
        self.check_one(['遠端助理'], '另一台 Mac')
        with mock.patch.object(m, 'sync_read_others', return_value=others): m.sync_pass(self.app)
        self.assertEqual([len(x) for x in self.told()], [1, 1])  # not again

    def test_rematch_that_holds_in_is_notified(self):
        store = self.store
        with store.lock:
            store.data['settings'].update(autoModels=['claude'], autoFixed=True)
            store.data['autoStatus'] = {'claude': dict(signedIn=True, billed=False, checkedAt=time.time())}
            store.data['bots'].append(dict(id='w', name='等配模', provider='auto', autoPending=True, persona='細心的分析師', access='full', permissionMode='bypass'))
            m.auto_retry(store)
        self.assertTrue(store.find('bots', 'w')['localLimit'])
        self.check_one(['等配模'], '自動選擇')

    def test_old_quota_rematch_is_notified_without_a_second_line(self):
        store = self.store
        with store.lock:
            store.data['settings'].update(autoModels=['codex', 'claude'], autoFixed=True)
            store.data['autoStatus'] = {p: dict(signedIn=True, billed=False, checkedAt=time.time()) for p in ('codex', 'claude')}
            store.data['bots'].append(dict(id='a', name='分析師', provider='codex', account='', persona='細心的分析師', autoAssigned=True, autoRematch=True,
                                           autoOldReason='分析和寫報告多，配 Codex（Claude 額度不足）', autoReason='分析和寫報告多，配 Codex（Claude 額度不足）', access='full'))
            m.auto_retry(store)
        self.assertTrue(store.find('bots', 'a')['localLimit'])
        lines, notes = self.told()
        self.assertEqual((len(lines), len(notes)), (1, 1)); self.assertIn('「分析師」', notes[0]['body'])

    def test_bot_made_by_a_bot_or_the_phone_is_told(self):
        store = self.store
        with store.lock: admin = next(b for b in store.data['bots'] if b.get('isAdmin'))
        runtime = importlib.util.module_from_spec(importlib.util.spec_from_file_location('zook_runtime_for_held_notice', ROOT / 'backend/runtime.py'))
        runtime.__spec__.loader.exec_module(runtime)
        tools = {schema['name']: handler for schema, handler, approval in self.app.app_tools(admin, runtime)}
        tools['zook_create_bot']({'name': '子 Bot', 'persona': 'x', 'instructions': 'x'})
        self.check_one(['子 Bot'], '管理員')

    def test_a_model_change_not_from_this_macs_window_is_told(self):
        store = self.store
        with store.lock:
            bot = next(b for b in store.data['bots'] if not b.get('isAdmin')); bot.update(provider='claude', gateFull=True)
            after = dict(bot, provider='codex'); m.local_choice(bot, after, dict(provider='codex'), local=False)  # what the Mac's own PATCH route does
            m.auto_on_edit(store, bot, after, dict(provider='codex'))
        self.assertTrue(after['localLimit'])
        self.check_one([bot['name']], '手機上換了')
        with store.lock:
            again = dict(after, name=after['name']); m.local_choice(after, again, dict(name=after['name']))
            m.auto_on_edit(store, after, again, dict(name=after['name']))
        self.assertEqual([len(x) for x in self.told()], [1, 1])  # already held in: not told again

    def test_claude_gate_not_seen_any_more_is_told_once(self):
        store = self.store
        with store.lock:
            bot = next(b for b in store.data['bots'] if not b.get('isAdmin')); bot.update(provider='claude', gateFull=True, account='')
            env = m.provider_env('claude', None); store.data['claudeGate'] = {m.claude_gate_key(env): True}
        mark = Path(self.temp.name) / 'mark'; mark.write_text('')
        m.claude_gate_after(store, env, [str(mark), 'word', 0], True)
        lines, notes = self.told()
        self.assertEqual((len(lines), len(notes)), (1, 1)); self.assertIn('「%s」' % bot['name'], notes[0]['body']); self.assertIn('自動恢復', notes[0]['body'])
        m.claude_gate_after(store, env, [str(mark), 'word', 0], True)
        self.assertEqual([len(x) for x in self.told()], [1, 1])  # already not seen: not told again

    def test_phone_made_bot_is_told(self):
        m.mobile_create_bot(self.store, dict(name='手機 Bot'))
        self.check_one(['手機 Bot'], '手機')


if __name__ == '__main__':
    unittest.main()
