# -*- coding: utf-8 -*-
"""What this Mac allows a Bot comes only from the user on this Mac (queue #36, #37): a backup put back, a Bot from another Mac, and a
Bot made by another Bot keep to their workspace and 謹慎, also after 自動選擇 matches them, until the user widens it in this Mac's window.
A Bot's own tools and a paired phone cannot widen it."""
import http.client, importlib.util, json, os, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
sys.path.insert(0, str(ROOT / 'backend'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


m = load('zook_server_for_local_grant', SERVER)
runtime = load('zook_runtime_for_local_grant', ROOT / 'backend/runtime.py')


class LocalGrantTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {'ZOOK_NO_INTRO': '1'}); env.start(); self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = m.Store(Path(self.temp.name) / 'data')
        self.app = m.App(('127.0.0.1', 0), self.store, self.temp.name, 'local-token'); self.app.bridge_token = 'bridge-token'
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.addCleanup(self.app.server_close); self.addCleanup(self.app.shutdown)
        settings = self.store.data['settings']
        settings.update(permissionMode='bypass', access='full', autoModels=['codex'])  # the widest the defaults can be
        self.store.data['autoStatus'] = {'codex': dict(signedIn=True, billed=False, checkedAt=time.time())}
        for p in (mock.patch.object(m, 'find_cli', return_value='/bin/true'), mock.patch.object(m, 'ability_on', return_value=True),
                  mock.patch.object(m, 'codex_default_model', return_value=''), mock.patch.object(m, 'log_activity'),
                  mock.patch.object(m, 'watch_auto_status', lambda store, bot: None)):
            p.start(); self.addCleanup(p.stop)
        self.admin = next(b for b in self.store.data['bots'] if b.get('isAdmin'))

    def held(self, bot):
        return (m.permission_mode(self.store, bot, 'codex'), m.bot_scope(bot, 'codex'))

    def req(self, method, path, body=None, token='local-token', device=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.app.server_address[1], timeout=10)
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        if device is not None: headers['X-Zook-Device'] = device
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    # 36: a backup put back
    def test_restore_keeps_this_macs_grants_and_holds_in_bots_it_never_had(self):
        store = self.store
        with store.lock:
            mine = next(b for b in store.data['bots'] if not b.get('isAdmin'))
            mine.update(provider='codex', access='full', permissionMode='auto', scripts=True)  # set up by the user here
            copy_ = json.loads(json.dumps(store.data))
            for b in copy_['bots']: b.update(access='full', permissionMode='bypass', isAdmin=True, scripts=True)  # widened in the copy
            copy_['bots'].append(dict(id='old', name='舊 Bot', provider='codex', access='full', permissionMode='bypass', isAdmin=True, scripts=True, messages=[], chats=[]))
            copy_['bots'].append(dict(id='wait', name='等配模', provider='auto', autoPending=True, persona='寫程式', access='full', permissionMode='bypass', messages=[], chats=[]))
            copy_['deletedBots'] = [dict(id='gone', name='刪掉的', provider='codex', isAdmin=True, access='full', permissionMode='bypass', messages=[], chats=[])]
            copy_['settings'].update(access='full', permissionMode='bypass')
            store.data['settings'].update(access='workspace', permissionMode='manual'); store.save()
            name = m.backup_write(store, 'manual', copy_)
            m.backup_restore(self.app, name)
        data = self.app.store.data; find = lambda i: next(b for b in data['bots'] if b['id'] == i)
        self.assertEqual((data['settings']['access'], data['settings']['permissionMode']), ('workspace', 'manual'))  # this Mac's defaults
        kept = find(mine['id'])
        self.assertEqual((kept['access'], kept['permissionMode'], kept['isAdmin'], kept['scripts']), ('full', 'auto', False, True))  # unchanged
        self.assertNotIn('localLimit', kept)
        self.assertTrue(find(self.admin['id'])['isAdmin'])
        self.assertEqual([b['id'] for b in data['bots'] if b.get('isAdmin')], [self.admin['id']])  # one 管理員: this Mac's
        old = find('old')
        self.assertEqual((old['isAdmin'], old['scripts'], old['localLimit']), (False, False, True))
        self.assertEqual(self.held(old), ('manual', ('workspace', '')))
        gone = data['deletedBots'][0]
        self.assertEqual((gone['isAdmin'], gone['localLimit'], gone['permissionMode']), (False, True, 'manual'))
        with self.app.store.lock: m.auto_retry(self.app.store)  # matched in the background after the restore
        wait = find('wait')
        self.assertEqual((wait['provider'], wait['localLimit']), ('codex', True))
        self.assertEqual(self.held(wait), ('manual', ('workspace', '')))

    def test_restore_moving_a_bot_onto_another_cli_drops_the_whole_mac(self):
        old = dict(settings={'provider': 'codex'}, bots=[dict(id='c', name='c', provider='claude', gateFull=True, access='full', permissionMode='bypass')])
        new = dict(settings={'provider': 'codex'}, bots=[dict(id='c', name='c', provider='cursor')])
        m.restore_keep_access(old, new)
        self.assertEqual((new['bots'][0].get('gateFull'), new['bots'][0].get('localLimit')), (None, True))
        new = dict(settings={'provider': 'codex'}, bots=[dict(id='c', name='c', provider='claude')])
        m.restore_keep_access(old, new); self.assertTrue(new['bots'][0]['gateFull'])  # the same model: what this Mac allowed stays

    # 36: sync
    def test_a_bot_from_another_mac_is_held_in(self):
        store = self.store
        with store.lock:
            self.assertTrue(m.sync_put(store, 'bots:far', m.sync_clean('bots:far', dict(name='遠端', provider='codex', model='', access='full', permissionMode='bypass', isAdmin=True))))
            far = store.find('bots', 'far')
        self.assertEqual((far['isAdmin'], far['localLimit']), (False, True))
        self.assertEqual(self.held(far), ('manual', ('workspace', '')))
        with store.lock: m.sync_put(store, 'bots:far', m.sync_clean('bots:far', dict(name='遠端2', provider='codex', model='')))
        self.assertTrue(far['localLimit'])  # a later change from there does not lift it

    # 37: a Bot made by another Bot
    def tools(self):
        return {schema['name']: handler for schema, handler, approval in self.app.app_tools(self.admin, runtime)}

    def test_sub_bot_is_held_in_through_matching_and_rematching(self):
        made = self.tools()['zook_create_bot']({'name': '子 Bot', 'persona': '工程師', 'instructions': '寫程式', 'access': 'full', 'permissionMode': 'bypass'})
        sub = self.store.find('bots', made['id'])
        self.assertEqual((sub['provider'], sub['localLimit'], sub['isAdmin']), ('codex', True, False))  # 自動選擇 matched it to Codex
        self.assertEqual(self.held(sub), ('manual', ('workspace', '')))
        named = self.tools()['zook_create_bot']({'name': '指定 Codex', 'persona': 'x', 'instructions': 'x', 'provider': 'codex'})
        self.assertEqual(self.held(self.store.find('bots', named['id'])), ('manual', ('workspace', '')))
        with self.store.lock:  # its work changed: matched again, still held in
            after = dict(sub, instructions='寫程式與分析資料'); m.auto_on_edit(self.store, sub, after, dict(instructions=after['instructions']))
        self.assertTrue(after['localLimit']); self.assertEqual(self.held(after), ('manual', ('workspace', '')))
        status, body = self.req('PATCH', '/api/bots/' + sub['id'], dict(instructions='寫程式、寫測試'))  # an edit that does not touch access
        self.assertEqual(status, 200); self.assertTrue(body['localLimit'])

    def test_only_the_user_in_this_macs_window_widens_it(self):
        made = self.tools()['zook_create_bot']({'name': '子 Bot', 'persona': '工程師', 'instructions': '寫程式'})
        bot_id = made['id']
        with self.store.lock:
            self.store.data.setdefault('remoteDevices', []).append(dict(id='dev1', name='iPhone'))
        status, _ = self.req('PATCH', '/api/bots/' + bot_id, dict(access='full', permissionMode='bypass'), token='bridge-token', device='dev1')
        self.assertEqual(status, 403)  # the phone
        sub = self.store.find('bots', bot_id)
        candidate = dict(sub, access='full'); m.local_choice(sub, candidate, dict(access='full'), local=False)
        self.assertTrue(candidate['localLimit'])  # anything that is not this Mac's window
        self.assertTrue(self.store.find('bots', bot_id)['localLimit'])
        status, body = self.req('PATCH', '/api/bots/' + bot_id, dict(permissionMode='auto'))  # the user, here: only what was changed
        self.assertEqual(status, 200); self.assertNotIn('localLimit', body)
        self.assertEqual(self.held(self.store.find('bots', bot_id)), ('auto', ('workspace', '')))
        status, body = self.req('PATCH', '/api/bots/' + bot_id, dict(access='full'))
        self.assertEqual(self.held(self.store.find('bots', bot_id)), ('auto', ('full', '')))


    # Codex review of 3399496: nothing that is not the user in this Mac's window widens a Bot or starts a new program.
    def restore_copy(self, change):
        store = self.store
        with store.lock:
            copy_ = json.loads(json.dumps(store.data)); change(copy_)
            name = m.backup_write(store, 'manual', copy_); m.backup_restore(self.app, name)
        return self.app.store.data

    def test_restore_starts_no_program_and_runs_no_schedule(self):
        with self.store.lock:
            self.store.data['connectors'] = [dict(id='mine', name='本機', transport='stdio', command='/bin/echo')]
            self.store.data['settings']['sharedMcp'] = ['zook:mine']; self.store.data['claudeGate'] = {}
        def change(c):
            c['customProviders'] = [dict(id='custom-evil', name='壞', command='/bin/sh')]
            c['bots'][0].update(provider='custom-evil', fallbacks=['custom-evil', 'codex'])
            c['settings'].update(provider='custom-evil', sharedMcp=['zook:mine', 'zook:new'])
            c['connectors'] = [dict(id='mine', name='本機', transport='stdio', command='/bin/sh'), dict(id='new', name='新', transport='stdio', command='/bin/sh')]
            c['schedules'] = [dict(id='s1', botId=self.admin['id'], on=True, content='做事', trigger='time')]
            c['claudeGate'] = {'k': True}
        data = self.restore_copy(change)
        self.assertEqual((data['customProviders'], data['settings']['provider'], data['bots'][0]['provider'], data['bots'][0]['fallbacks']), ([], 'codex', '', ['codex']))
        self.assertEqual(data['settings']['sharedMcp'], ['zook:mine'])  # the copy's own connector is there, off
        self.assertEqual({c['id']: c['command'] for c in data['connectors']}, {'mine': '/bin/echo', 'new': '/bin/sh'})  # this Mac's definition stays
        self.assertFalse(data['schedules'][0]['on']); self.assertEqual(data.get('claudeGate'), {})

    def test_restore_rejects_ids_that_name_folders(self):
        for bad in ('../x', '/tmp/x', '', 'a' * 65):
            data = dict(bots=[dict(id=bad, name='x')], settings={})
            with self.assertRaises(ValueError): m.backup_check(data)
        with self.assertRaises(ValueError): m.backup_check(dict(bots=[dict(id='ok', name='x', chats=[dict(id='../c')])], settings={}))
        with self.assertRaises(ValueError): m.backup_check(dict(bots=[], deletedBots=[dict(id='../d', name='x')], settings={}))

    def test_an_old_backup_never_picks_the_admin_by_name(self):
        with self.store.lock: self.admin['name'] = '總管'
        def change(c):
            c['settings'].pop('abilitiesV2', None)
            c['bots'].append(dict(id='imp', name='管理員', provider='codex', messages=[], chats=[]))
        data = self.restore_copy(change)
        self.assertEqual([b['id'] for b in data['bots'] if b.get('isAdmin')], [self.admin['id']])

    def test_recovery_from_a_broken_file_holds_everything_in(self):
        store = self.store
        with store.lock:
            store.data['remoteDevices'] = [dict(id='dev1', name='iPhone')]
            store.data['customProviders'] = [dict(id='custom-x', name='x', command='/bin/echo')]
            m.backup_write(store, 'auto', store.data)
            store.path.write_text('{broken')
            m.recover_data(store)
        data = store.data
        self.assertTrue(all(b['localLimit'] and not b['isAdmin'] for b in data['bots']))
        self.assertEqual((data['remoteDevices'], data['customProviders'], data['settings']['sharedMcp']), ([], [], []))

    def test_bots_found_in_old_copies_come_back_held_in(self):
        store = self.store
        with store.lock:
            old = json.loads(json.dumps(store.data)); old['bots'].append(dict(id='lost', name='舊的', provider='codex', access='full', permissionMode='bypass', isAdmin=True))
            (store.dir / 'swarmr.old.json').write_text(json.dumps(old))
            store.data['jobs'].append(dict(id='j', botId='lost', status='done')); store.data['settings'].pop('trashSeeded', None)
            m.recover_deleted_bots(store)
            for b in store.data['bots']: b['isAdmin'] = False  # no 管理員 now
            back = m.restore_bot(store, 'lost')
        self.assertEqual((back['isAdmin'], back['localLimit']), (False, True)); self.assertEqual(self.held(back), ('manual', ('workspace', '')))

    def test_no_custom_cli_for_a_bot_made_by_a_bot_or_the_phone(self):
        with self.store.lock: self.store.data['customProviders'] = [dict(id='custom-x', name='x', command='/bin/echo')]
        made = self.tools()['zook_create_bot']({'name': '子', 'persona': 'x', 'instructions': 'x', 'provider': 'custom-x'})
        self.assertNotEqual(self.store.find('bots', made['id'])['provider'], 'custom-x'); self.assertTrue(made['notApplied'])
        with self.assertRaises(ValueError): m.mobile_create_bot(self.store, dict(name='手機', provider='custom-x'))
        phone = m.mobile_create_bot(self.store, dict(name='手機'))
        self.assertEqual(self.held(phone), ('manual', ('workspace', '')))
        chain = [('custom-x', '', None, False), ('codex', '', None, False)]
        self.assertEqual(m.held_backups(dict(localLimit=True, provider='custom-x'), 'custom-x', chain), [chain[1]])
        self.assertEqual(m.held_backups(dict(localLimit=True, provider='custom-x'), 'custom-x', chain[:1]), [])  # the reply stops

    def test_sync_gives_no_admin_by_name_and_returns_this_macs_own_bots(self):
        store = self.store
        with store.lock:
            mine = next(b for b in store.data['bots'] if not b.get('isAdmin')); mine.update(access='folder', accessFolder=self.temp.name, permissionMode='auto')
            for b in list(store.data['bots']): m.sync_drop_bot(store, b)  # a 取代 join
            m.sync_put(store, 'bots:' + mine['id'], m.sync_clean('bots:' + mine['id'], dict(name=mine['name'], provider='codex', model='')))
            m.sync_put(store, 'bots:far', m.sync_clean('bots:far', dict(name='管理員', provider='codex', model='')))
        back = store.find('bots', mine['id'])
        self.assertEqual((back['access'], back['permissionMode']), ('folder', 'auto')); self.assertNotIn('localLimit', back)
        self.assertFalse(store.find('bots', 'far')['isAdmin'])
        with store.lock: m.sync_put(store, 'bots:' + self.admin['id'], m.sync_clean('bots:' + self.admin['id'], dict(name='管理員', provider='codex', model='')))
        self.assertTrue(store.find('bots', self.admin['id'])['isAdmin'])  # this Mac's own 管理員 comes back as it was

    def test_sync_stops_when_a_backup_is_put_back_meanwhile(self):
        store = self.store; folder = Path(self.temp.name) / 'sync'; folder.mkdir()
        with store.lock: state = m.sync_state(store); state['folder'] = str(folder)
        def restored(*a):
            store.data['sync'] = dict(store.data['sync'], folder='')  # what backup_restore does to the data meanwhile
            return []
        with mock.patch.object(m, 'sync_read_others', restored): result = m.sync_pass(self.app)
        self.assertFalse(result['on']); self.assertEqual(list(folder.iterdir()), [])

    def test_upgrade_holds_in_earlier_bot_made_and_synced_bots_once(self):
        store = self.store
        with store.lock:
            store.data['bots'] += [dict(id='kid', name='舊子 Bot', provider='codex', pinned=False), dict(id='far', name='遠端', provider='codex'), dict(id='own', name='自己的', provider='codex', pinned=False)]
            store.data['jobs'].append(dict(id='j', botId=self.admin['id'], status='done', toolCalls=[dict(name='zook_create_bot', arguments=dict(name='舊子 Bot'))]))
            m.sync_marks(store)['stamps']['bots:far'] = ['x', 1, False, []]; m.sync_marks_save(store)
            store.data['settings'].pop('heldInSet', None)
            self.assertTrue(m.held_in_migrate(store))
            store.find('bots', 'own')['access'] = 'full'
            self.assertFalse(m.held_in_migrate(store))  # once
        self.assertEqual([bool(store.find('bots', i).get('localLimit')) for i in ('kid', 'far', 'own')], [True, True, False])

    def test_rematching_never_carries_the_whole_mac_to_another_cli(self):
        bot = dict(id='c', name='c', provider='cursor', gateFull=True)
        m.set_access_after_match(bot, False, 'claude')
        self.assertEqual((bot.get('gateFull'), bot['localLimit'], bot['access'], bot['permissionMode']), (None, True, 'workspace', 'manual'))
        bot = dict(id='c', name='c', provider='claude', gateFull=True); m.set_access_after_match(bot, False, 'claude'); self.assertTrue(bot['gateFull'])
        moved = dict(id='g', name='g', provider='codex', gateFull=True, access='full', permissionMode='bypass'); m.limit_locally(moved)
        self.assertEqual((moved['access'], moved['permissionMode']), ('workspace', 'manual'))  # lifting the limit later brings back neither
        after = dict(moved); m.local_choice(moved, after, dict(access='folder', accessFolder=self.temp.name))
        self.assertEqual(after['permissionMode'], 'manual')

    def test_a_change_not_from_this_macs_window_is_undone(self):
        before = dict(id='b', name='b', provider='codex', localLimit=True, access='workspace', permissionMode='manual', isAdmin=False, scripts=False)
        after = dict(before, access='full', permissionMode='bypass', isAdmin=True, scripts=True, accessFolder='/')
        m.local_choice(before, after, dict(access='full', permissionMode='bypass', isAdmin=True, scripts=True), local=False)
        self.assertEqual({k: after.get(k) for k in ('access', 'permissionMode', 'isAdmin', 'scripts', 'localLimit', 'accessFolder')},
                         dict(access='workspace', permissionMode='manual', isAdmin=False, scripts=False, localLimit=True, accessFolder=None))

    def test_a_settings_pack_never_turns_a_connector_on(self):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('zook.json', json.dumps(dict(format='zook-pack', version=1, skills=[], connectors=[dict(name='包裡的', transport='stdio', command='/bin/echo', on=True)])))
        result = m.pack_import(self.store, buf.getvalue())
        self.assertEqual(result['connectors'], ['包裡的'])
        record = next(c for c in self.store.data['connectors'] if c['name'] == '包裡的')
        self.assertNotIn('zook:' + record['id'], self.store.data['settings'].get('sharedMcp') or [])

if __name__ == '__main__':
    unittest.main()
