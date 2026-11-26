# -*- coding: utf-8 -*-
"""#303 (#22): a connector you add is tested once at once. Only one that works is switched on for every Bot; one that does not
stays off with the reason. #288③: connector names that differ only in upper/lower case clash."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, unittest
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
        (self.root / 'mcp.py').write_text(MCP); (self.root / 'broken.py').write_text('import sys\nsys.stderr.write("no token\\n"); sys.exit(3)\n')
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
                store.data['connectors'][0]['command'] = 'new'; edited.append(1)  # another request saved a change meanwhile
                return {'status': 'ready', 'toolCount': 1}
            z.runtime_module = lambda: type('R', (), {'test_connection': staticmethod(tested)})
            z.inventory_for = lambda store, **kw: {}
            self.assertEqual(z.connector_first_test(store, 'zook:c1')[0], False)
            self.assertNotIn('zook:c1', store.data['settings'].get('sharedMcp') or [])
            self.assertEqual(z.connector_first_test(store, 'zook:c1')[0], True)  # tested as it is now: on


if __name__ == '__main__': unittest.main()
