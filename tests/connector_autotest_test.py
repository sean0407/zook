# -*- coding: utf-8 -*-
"""#303 (#22): a connector you add is tested once at once. Only one that works is switched on for every Bot; one that does not
stays off with the reason. #288③: connector names that differ only in upper/lower case clash."""
import base64, copy, http.client, importlib.util, io, json, os, subprocess, sys, tempfile, threading, time, unittest, zipfile
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
MCP = r'''
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if 'id' not in m: continue
    if m['method'] == 'initialize': r = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 'fake', 'version': '1'}}
    elif m['method'] == 'tools/list': r = {'tools': [{'name': 'hello', 'description': 'x', 'inputSchema': {'type': 'object'}}]}
    else: r = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': r})); sys.stdout.flush()
'''


class ConnectorAddTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'home').mkdir()
        (self.root / 'mcp.py').write_text(MCP); (self.root / 'echo.py').write_text(MCP.replace("'hello'", "'key_' + __import__('os').environ.get('FAKE_KEY', 'none').replace('-', '_')")); (self.root / 'slow.py').write_text('import time\ntime.sleep(1.5)\n' + MCP); (self.root / 'broken.py').write_text('import sys\nsys.stderr.write("no token\\n"); sys.exit(3)\n')
        env = dict(os.environ, HOME=str(self.root / 'home'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SECRETS_DIR=str(self.root))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=60)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close(); return resp.status, json.loads(raw)

    def shared(self): return self.req('GET', '/api/state')[1]['settings']['sharedMcp']

    def test_one_that_works_is_switched_on(self):
        status, made = self.req('POST', '/api/connectors', {'name': 'Works', 'transport': 'stdio', 'command': '%s %s' % (sys.executable, self.root / 'mcp.py')})
        self.assertEqual(status, 201)
        self.assertEqual((made['on'], made['test']['status'], made['test']['toolCount']), (True, 'ready', 1))
        self.assertIn(made['id'], self.shared())

    def test_one_that_fails_stays_off_with_the_reason(self):
        status, made = self.req('POST', '/api/connectors', {'name': 'Broken', 'transport': 'stdio', 'command': '%s %s' % (sys.executable, self.root / 'broken.py')})
        self.assertEqual(status, 201)
        self.assertFalse(made['on']); self.assertEqual(made['test']['status'], 'error'); self.assertTrue(made['test']['error'])
        self.assertNotIn(made['id'], self.shared())
        self.assertEqual([m['name'] for m in self.req('GET', '/api/integrations')[1]['mcp'] if m['source'] == 'zook'], ['Broken'])  # kept, so it can be fixed

    def test_turn_on_after_sign_in_tests_again(self):
        status, made = self.req('POST', '/api/connectors', {'name': 'Broken', 'transport': 'stdio', 'command': '%s %s' % (sys.executable, self.root / 'broken.py')})
        status, out = self.req('POST', '/api/connectors/%s/turn-on' % made['id'].split(':')[1], {})
        self.assertEqual((status, out['on'], out['test']['status']), (200, False, 'error')); self.assertNotIn(made['id'], self.shared())
        spec = importlib.util.spec_from_file_location('zook_turn_on_phone', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        self.assertFalse(z.device_may('POST', '/api/connectors/abc/turn-on'))

    def race(self, change, **extra):
        """Add a slow connector that works, switch it off, ask for turn-on and make a change while it is being tested."""
        import threading
        body = dict({'name': 'Slow', 'transport': 'stdio', 'command': '%s %s' % (sys.executable, self.root / 'slow.py')}, **extra)
        made = self.req('POST', '/api/connectors', body)[1]; ident = made['id'].split(':')[1]
        self.assertTrue(made['on']); self.assertEqual(self.req('PATCH', '/api/settings', {'sharedMcp': []})[0], 200)
        out = {}
        worker = threading.Thread(target=lambda: out.update(self.req('POST', '/api/connectors/%s/turn-on' % ident, {})[1])); worker.start()
        time.sleep(0.6); change(ident); worker.join(30)
        return made['id'], ident, out

    def test_a_change_made_and_undone_during_the_test_keeps_it_off(self):
        def change(ident):
            self.assertEqual(self.req('PATCH', '/api/connectors/' + ident, {'env': {'MODE': 'b'}})[0], 200)
            self.assertEqual(self.req('PATCH', '/api/connectors/' + ident, {'env': {}})[0], 200)  # A -> B -> A
        made, ident, out = self.race(change)
        self.assertEqual((out['on'], out['test'].get('changed')), (False, True)); self.assertNotIn(made, self.shared())
        self.assertTrue(self.req('POST', '/api/connectors/%s/turn-on' % ident, {})[1]['on'])  # nothing changes now: on

    def test_a_key_replaced_under_the_same_id_during_the_test_keeps_it_off(self):
        change = lambda ident: self.assertEqual(self.req('PATCH', '/api/connectors/' + ident, {'secret': 'second-key-12345'})[0], 200)
        made, ident, out = self.race(change, secretName='FAKE_KEY', secret='first-key-12345')
        self.assertFalse(out['on']); self.assertTrue(out['test']['changed']); self.assertNotIn(made, self.shared())

    def test_switching_it_on_and_off_during_the_test_keeps_it_off(self):
        def change(ident):
            for shared in (['zook:' + ident], []): self.assertEqual(self.req('PATCH', '/api/settings', {'sharedMcp': shared})[0], 200)  # turned on, then off again
        made, ident, out = self.race(change)
        self.assertFalse(out['on']); self.assertTrue(out['test']['changed']); self.assertNotIn(made, self.shared())

    def test_a_refused_change_of_keys_leaves_the_old_keys(self):
        manifest = {'format': 'zook-pack', 'version': 1, 'skills': [], 'connectors': [{'name': 'Packed', 'transport': 'stdio', 'command': '%s %s' % (sys.executable, self.root / 'echo.py'),
                    'env': {}, 'headers': {}, 'secretName': 'FAKE_KEY', 'moreSecrets': ['EXTRA_KEY']}]}
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as z: z.writestr('zook.json', json.dumps(manifest))
        self.assertEqual(self.req('POST', '/api/pack', {'data': base64.b64encode(raw.getvalue()).decode()})[1]['connectors'], ['Packed'])
        item = next(m for m in self.req('GET', '/api/integrations')[1]['mcp'] if m['name'] == 'Packed'); ident = item['id'].split(':')[1]
        self.assertEqual(self.req('PATCH', '/api/connectors/' + ident, {'secret': 'first-key-12345', 'moreSecrets': {'EXTRA_KEY': 'extra-key-12345'}})[0], 200)
        status, _ = self.req('PATCH', '/api/connectors/' + ident, {'secret': 'second-key-12345', 'moreSecrets': {'EXTRA_KEY': 'not a key!'}})
        self.assertEqual(status, 400)
        self.assertEqual(self.req('POST', '/api/mcp/%s/test' % item['id'], {})[1]['tools'][0]['name'], 'key_first_key_12345')  # nothing was changed
        self.assertEqual(len(list(self.root.glob('[0-9a-f]' * 32))), 2)  # and no stray key left behind

    def test_names_that_differ_only_in_case_clash(self):
        command = '%s %s' % (sys.executable, self.root / 'mcp.py')
        self.assertEqual(self.req('POST', '/api/connectors', {'name': 'GitHub', 'transport': 'stdio', 'command': command})[0], 201)
        for name in ('github', ' GITHUB '):
            status, out = self.req('POST', '/api/connectors', {'name': name, 'transport': 'stdio', 'command': command})
            self.assertEqual(status, 400, name); self.assertIn('同名', out['error'])
        status, other = self.req('POST', '/api/connectors', {'name': 'Other', 'transport': 'stdio', 'command': command})
        ident = other['id'].split(':')[1]
        self.assertEqual(self.req('PATCH', '/api/connectors/' + ident, {'name': 'GITHUB'})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/connectors/' + ident, {'name': 'OTHER'})[0], 200)


class CatalogSignIn(unittest.TestCase):
    def test_a_catalog_connector_that_needs_a_sign_in_waits_for_it(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = importlib.util.spec_from_file_location('zook_catalog_signin', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
            z.CONNECTOR_CATALOG[:] = [z._c('svc', 'Svc', '測試', 'https://mcp.example.invalid/mcp', 'login', '測試。')]
            z.oauth_begin = lambda app, record, **kw: 'https://login.example.invalid/'
            store = z.Store(Path(temp) / 'data'); app = type('App', (), {'store': store, 'server_address': ('127.0.0.1', 1)})()
            record, url = z.catalog_add(app, 'svc')
            self.assertEqual(url, 'https://login.example.invalid/')
            self.assertEqual([c['id'] for c in store.data['connectors']], [record['id']])
            self.assertNotIn('zook:' + record['id'], store.data['settings'].get('sharedMcp') or [])  # on once signed in and tested

    def test_one_edited_while_it_was_tested_stays_off(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = importlib.util.spec_from_file_location('zook_first_test_race', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
            store = z.Store(Path(temp) / 'data')
            store.data['connectors'].append(dict(id='c1', name='C', transport='stdio', command='old', url='', env={}, secretName='', secretId='', headers={}, moreSecrets={}, origin=''))
            edited = []
            def tested(ident, inventory):
                if edited: return {'status': 'ready', 'toolCount': 1}
                for command in ('new', 'old'):  # another request changed it, and back again (A -> B -> A), while it was tested
                    with store.lock: store.data['connectors'][0]['command'] = command; z.connector_touch('c1')
                edited.append(1); return {'status': 'ready', 'toolCount': 1}
            z.runtime_module = lambda: type('R', (), {'test_connection': staticmethod(tested)})
            z.inventory_for = lambda store, **kw: {}
            on, test = z.connector_first_test(store, 'zook:c1')
            self.assertFalse(on); self.assertTrue(test['changed']); self.assertIn('設定已經被修改', test['error'])
            self.assertNotIn('zook:c1', store.data['settings'].get('sharedMcp') or [])
            self.assertEqual(z.connector_first_test(store, 'zook:c1')[0], True)  # tested as it is now: on

    def test_switching_or_signing_out_an_account_counts_as_a_change(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ['ZOOK_SECRETS_DIR'] = str(Path(temp) / 'secrets'); (Path(temp) / 'secrets').mkdir(); self.addCleanup(os.environ.pop, 'ZOOK_SECRETS_DIR', None)
            spec = importlib.util.spec_from_file_location('zook_first_test_accounts', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
            store = z.Store(Path(temp) / 'data')
            store.data['connectors'].append(dict(id='c1', name='C', transport='http', command='', url='https://x.example/mcp', env={}, secretName='', secretId='', headers={}, moreSecrets={}, origin='',
                                                 oauth={'secretId': 'a1', 'name': '帳號 1'}, otherAccounts=[{'secretId': 'a2', 'name': '帳號 2'}]))
            before = z.connector_rev('c1'); z.oauth_switch(store, 'c1', 'a2'); self.assertEqual(z.connector_rev('c1'), before + 1)
            z.oauth_logout(store, 'c1'); self.assertEqual(z.connector_rev('c1'), before + 2)
            # and so a test that overlaps one of them does not switch the connector on
            def tested(ident, inventory): z.oauth_logout(store, 'c1'); return {'status': 'ready', 'toolCount': 1}
            z.runtime_module = lambda: type('R', (), {'test_connection': staticmethod(tested)}); z.inventory_for = lambda store, **kw: {}
            self.assertFalse(z.connector_first_test(store, 'zook:c1')[0])

    def load(self, temp):
        os.environ['ZOOK_SECRETS_DIR'] = str(Path(temp) / 'secrets'); (Path(temp) / 'secrets').mkdir(); self.addCleanup(os.environ.pop, 'ZOOK_SECRETS_DIR', None)
        spec = importlib.util.spec_from_file_location('zook_first_test_%d' % id(temp), SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        return z, z.Store(Path(temp) / 'data')

    def test_a_read_racing_a_new_key_does_not_keep_the_old_one(self):
        with tempfile.TemporaryDirectory() as temp:
            z, _ = self.load(temp); key = 'a' * 32
            z.secret_set(key, 'old-value-12345'); real = z._secret_read; started, go = threading.Event(), threading.Event()
            def slow(ident): value = real(ident); started.set(); go.wait(5); return value
            z._secret_read = slow
            reader = threading.Thread(target=z.secret_get, args=(key,)); reader.start(); started.wait(5)
            z._secret_read = real; z.secret_set(key, 'new-value-12345'); go.set(); reader.join(5)
            self.assertEqual(z.secret_get(key), 'new-value-12345')

    def test_a_failed_catalog_save_puts_back_only_its_own_change(self):
        with tempfile.TemporaryDirectory() as temp:
            z, store = self.load(temp)
            z.CONNECTOR_CATALOG[:] = [z._c('svc', 'Svc', '測試', 'https://svc.example/mcp', 'key', '測試。')]; z._catalog_check = lambda item, key: None
            old = dict(id='c1', name='Svc', transport='http', command='', url='https://svc.example/mcp', env={}, secretName='', secretId='', headers={}, moreSecrets={}, origin='')
            store.data['connectors'].append(dict(old)); app = type('App', (), {'store': store, 'server_address': ('127.0.0.1', 1)})()
            def broken(): raise OSError('disk full')
            store.save = broken; before = z.connector_rev('c1')
            self.assertRaises(OSError, z.catalog_add, app, 'svc', 'good-key-12345')
            self.assertEqual(store.data['connectors'], [old]); self.assertEqual(z.connector_rev('c1'), before + 2)  # put back, and counted as a change
            patched = dict(old, name='Patched')
            def raced(): store.data['connectors'][:] = [patched]; z.connector_touch('c1'); raise OSError('disk full')  # another change saved meanwhile
            store.save = raced
            self.assertRaises(OSError, z.catalog_add, app, 'svc', 'good-key-12345')
            self.assertIs(store.data['connectors'][0], patched)

    def connector(self, **extra):
        return dict(dict(id='c1', name='Svc', transport='http', command='', url='https://svc.example/mcp', env={}, secretName='', secretId='', headers={}, moreSecrets={}, origin=''), **extra)

    def test_switching_off_while_a_test_finishes_stays_off(self):
        with tempfile.TemporaryDirectory() as temp:
            z, store = self.load(temp)
            store.data['connectors'].append(self.connector()); store.data['settings']['sharedMcp'] = ['zook:c1']
            fire, out = threading.Event(), []
            def tested(ident, inventory): fire.wait(5); return {'status': 'ready', 'toolCount': 1}
            z.runtime_module = lambda: type('R', (), {'test_connection': staticmethod(tested)}); z.inventory_for = lambda store, **kw: {}
            worker = threading.Thread(target=lambda: out.append(z.connector_first_test(store, 'zook:c1'))); worker.start(); time.sleep(0.3)
            real = z.update
            def racing(target, body, kind): real(target, body, kind); fire.set(); worker.join(0.5)  # the test finishes right after the list is changed
            z.update = racing
            z.settings_patch(store, {'sharedMcp': []})
            worker.join(5)
            self.assertNotIn('zook:c1', store.data['settings']['sharedMcp']); self.assertFalse(out[0][0])

    def keys(self, temp): return sorted(p.name for p in (Path(temp) / 'secrets').iterdir())

    def test_a_failed_save_of_new_keys_changes_nothing_and_leaves_no_key(self):
        with tempfile.TemporaryDirectory() as temp:
            z, store = self.load(temp)
            z.secret_set('a' * 32, 'old-key-12345'); store.data['connectors'].append(self.connector(transport='stdio', command='x', url='', secretName='K', secretId='a' * 32))
            record = dict(store.data['connectors'][0], moreSecrets={}); written = z.connector_keys_write(record, 'new-key-12345', {})
            def broken(): raise OSError('disk full')
            store.save = broken
            self.assertRaises(OSError, z.connector_publish, store, record, written)
            self.assertEqual(store.data['connectors'][0]['secretId'], 'a' * 32); self.assertEqual(self.keys(temp), ['a' * 32])

    def test_two_edits_at_once_leave_one_key_each_and_no_strays(self):
        with tempfile.TemporaryDirectory() as temp:
            z, store = self.load(temp)
            z.secret_set('a' * 32, 'old-key-12345'); z.secret_set('b' * 32, 'old-extra-12345')
            store.data['connectors'].append(self.connector(transport='stdio', command='x', url='', secretName='K', secretId='a' * 32, moreSecrets={'EXTRA': 'b' * 32}))
            first, second, third = (copy.deepcopy(store.data['connectors'][0]) for _ in range(3))  # all read before any was saved
            done = []
            for record, secret, more in ((first, 'first-key-12345', {}), (second, 'second-key-12345', {}), (third, None, {'EXTRA': 'new-extra-12345'})):
                written = z.connector_keys_write(record, secret, more)
                old, _ = z.connector_publish(store, record, written)
                for ident in old: z.secret_drop(ident)
            saved = store.data['connectors'][0]
            self.assertEqual((z.secret_get(saved['secretId']), z.secret_get(saved['moreSecrets']['EXTRA'])), ('second-key-12345', 'new-extra-12345'))  # the third did not undo the second
            self.assertEqual(self.keys(temp), sorted([saved['secretId'], saved['moreSecrets']['EXTRA']]))

    def test_a_key_that_cannot_be_deleted_is_logged(self):
        with tempfile.TemporaryDirectory() as temp:
            z, _ = self.load(temp)
            z.secret_delete = lambda ident: False
            err = io.StringIO(); real, sys.stderr = sys.stderr, err
            try: z.secret_drop('c' * 32)
            finally: sys.stderr = real
            self.assertIn('could not delete', err.getvalue()); self.assertIn('c' * 32, err.getvalue())

    def catalog(self, temp):
        z, store = self.load(temp)
        z.CONNECTOR_CATALOG[:] = [z._c('svc', 'Svc', '測試', 'https://svc.example/mcp', 'key', '測試。')]; z._catalog_check = lambda item, key: None
        return z, store, type('App', (), {'store': store, 'server_address': ('127.0.0.1', 1)})()

    def test_a_failed_catalog_save_does_not_leave_it_on(self):
        with tempfile.TemporaryDirectory() as temp:
            z, store, app = self.catalog(temp)
            store.data['connectors'].append(self.connector())
            def broken(): raise OSError('disk full')
            store.save = broken
            self.assertRaises(OSError, z.catalog_add, app, 'svc', 'good-key-12345')
            self.assertNotIn('zook:c1', store.data['settings'].get('sharedMcp') or []); self.assertEqual(self.keys(temp), [])

    def test_one_removed_during_the_catalog_check_is_not_brought_back(self):
        with tempfile.TemporaryDirectory() as temp:
            z, store, app = self.catalog(temp)
            store.data['connectors'].append(self.connector())
            def removed(item, key):
                with store.lock: store.data['connectors'][:] = []  # removed from another window meanwhile
            z._catalog_check = removed
            self.assertRaisesRegex(RuntimeError, '被移除', z.catalog_add, app, 'svc', 'good-key-12345')
            self.assertEqual(store.data['connectors'], []); self.assertNotIn('zook:c1', store.data['settings'].get('sharedMcp') or []); self.assertEqual(self.keys(temp), [])

    def test_a_refused_sign_in_counts_as_a_change_once(self):
        with tempfile.TemporaryDirectory() as temp:
            z, store = self.load(temp)
            store.data['connectors'].append(dict(id='c1', name='C', transport='http', url='https://x.example/mcp', oauth={'secretId': 'a1'}))
            before = z.connector_rev('c1')
            z._oauth_lost(store, 'c1', 'a1'); self.assertEqual(z.connector_rev('c1'), before + 1)
            z._oauth_lost(store, 'c1', 'a1'); self.assertEqual(z.connector_rev('c1'), before + 1)  # already marked: nothing new

    def test_a_sign_in_renewed_by_the_test_is_not_a_change(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = importlib.util.spec_from_file_location('zook_first_test_renew', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
            store = z.Store(Path(temp) / 'data')
            store.data['connectors'].append(dict(id='c1', name='C', transport='http', command='', url='https://x.example/mcp', env={}, secretName='', secretId='', headers={}, moreSecrets={}, origin='', oauth={'blob': 'a'}))
            def tested(ident, inventory): store.data['connectors'][0]['oauth'] = {'blob': 'b'}; return {'status': 'ready', 'toolCount': 1}
            z.runtime_module = lambda: type('R', (), {'test_connection': staticmethod(tested)})
            z.inventory_for = lambda store, **kw: {}
            self.assertEqual(z.connector_first_test(store, 'zook:c1')[0], True)


if __name__ == '__main__': unittest.main()
