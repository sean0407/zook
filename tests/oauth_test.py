# -*- coding: utf-8 -*-
import base64, hashlib, http.client, json, os, subprocess, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


class Provider(BaseHTTPRequestHandler):
    """A remote connector that needs sign-in, with its own authorization server."""
    state = {}
    def log_message(self, *args): pass
    def send(self, code, body, headers=None):
        raw = json.dumps(body).encode(); self.send_response(code)
        for k, v in dict({'Content-Type': 'application/json', 'Content-Length': str(len(raw))}, **(headers or {})).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        base = 'http://127.0.0.1:%d' % self.server.server_address[1]; path = urlsplit(self.path).path
        if path.startswith('/.well-known/oauth-protected-resource'): return self.send(200, {'resource': Provider.state.get('resource') or base + '/mcp', 'authorization_servers': [base]})
        if path.startswith('/.well-known/oauth-authorization-server'):
            return self.send(200, {'authorization_endpoint': base + '/authorize', 'token_endpoint': base + '/token', 'registration_endpoint': base + '/register', 'code_challenge_methods_supported': ['S256'], 'scopes_supported': ['openid', 'offline_access']})
        self.send(404, {})
    def do_POST(self):
        s = Provider.state; base = 'http://127.0.0.1:%d' % self.server.server_address[1]
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0'))); path = urlsplit(self.path).path
        if path == '/register': s['redirect'] = json.loads(raw)['redirect_uris'][0]; return self.send(201, {'client_id': 'client-1'})
        if path == '/token':
            form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}; s.setdefault('grants', []).append(form['grant_type'])
            if form['grant_type'] == 'authorization_code':
                good = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'].encode()).digest()).decode().rstrip('=') == s['challenge']
                if form['code'] != 'CODE-1' or not good: return self.send(400, {'error': 'invalid_grant'})
                return self.send(200, {'access_token': 'ACCESS-1-' + 'x' * 1800, 'refresh_token': 'REFRESH-1', 'expires_in': s.get('life', 3600)})
            if s.get('busy'): return self.send(503, {})
            if form.get('refresh_token') == 'REFRESH-1' and not s.get('revoked'): return self.send(200, {'access_token': 'ACCESS-2', 'expires_in': 3600})
            return self.send(400, {'error': 'invalid_grant'})
        if path == '/mcp':
            auth = self.headers.get('Authorization', ''); s.setdefault('seen', []).append(auth[:15]); s.setdefault('agents', []).append(self.headers.get('User-Agent', ''))
            if not auth.startswith('Bearer ACCESS-'): return self.send(401, {}, {'WWW-Authenticate': 'Bearer resource_metadata="%s/.well-known/oauth-protected-resource"' % base})
            msg = json.loads(raw)
            if msg.get('method') == 'initialize': return self.send(200, {'jsonrpc': '2.0', 'id': msg['id'], 'result': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 'p', 'version': '1'}}})
            if msg.get('method') == 'tools/list': return self.send(200, {'jsonrpc': '2.0', 'id': msg['id'], 'result': {'tools': [{'name': 'lookup', 'description': 'd', 'inputSchema': {'type': 'object'}}]}})
            return self.send(202, {})
        self.send(404, {})


class OAuthTest(unittest.TestCase):
    def setUp(self):
        Provider.state = {}
        self.provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider); threading.Thread(target=self.provider.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:%d' % self.provider.server_address[1]
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'secrets').mkdir()
        self.start()
        made = self.req('POST', '/api/connectors', {'name': 'Remote', 'transport': 'http', 'url': self.base + '/mcp'})[1]; self.connector = made['id']; self.cid = self.connector.split(':')[1]
        self.assertFalse(made['on']); self.assertTrue(made['test']['needsLogin'])  # #303: not signed in yet, so it waits, off
        self.assertEqual(self.req('PATCH', '/api/settings', {'sharedMcp': [self.connector]})[0], 200)  # as the page does once signed in and tested

    def start(self):
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), ZOOK_NO_BROWSER='1', HOME=str(self.root))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self): self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close()
    def tearDown(self): self.stop(); self.provider.shutdown(); self.provider.server_close(); self.temp.cleanup()

    def req(self, method, path, body=None, auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token} if auth else {})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        try: return resp.status, json.loads(raw)
        except ValueError: return resp.status, raw.decode()

    def item(self): return next(m for m in self.req('GET', '/api/integrations')[1]['mcp'] if m['id'] == self.connector)

    def login(self):
        status, body = self.req('POST', '/api/connectors/%s/login' % self.cid, {}); self.assertEqual(status, 200, body)
        query = {k: v[0] for k, v in parse_qs(urlsplit(body['url']).query).items()}; Provider.state['challenge'] = query['code_challenge']
        self.assertIn('offline_access', query.get('scope', ''))   # asked for whenever the service offers it, so the sign-in lasts
        self.assertEqual((query['code_challenge_method'], query['redirect_uri'], query['resource']), ('S256', 'http://127.0.0.1:%d/oauth/callback' % self.port, self.base + '/mcp'))
        return query['state']

    def test_one_still_off_can_be_tested_once_signed_in(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'sharedMcp': []})[0], 200)  # #303: waiting for its sign-in
        state = self.login(); self.assertEqual(self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)[0], 200)
        test = self.req('POST', '/api/mcp/%s/test' % self.connector, {})[1]; self.assertEqual((test['status'], test['toolCount']), ('ready', 1))

    def test_sign_in_use_and_sign_out(self):
        self.assertTrue(self.item()['canLogin']); self.assertFalse(self.item()['signedIn'])
        state = self.login()
        self.assertEqual(self.req('GET', '/oauth/callback?state=nope&code=CODE-1', auth=False)[0], 400)
        status, page = self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False); self.assertEqual(status, 200); self.assertIn('登入完成', page)
        self.assertEqual(self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)[0], 400)  # one use only
        self.assertTrue(self.item()['signedIn'])
        test = self.req('POST', '/api/mcp/%s/test' % self.connector, {})[1]; self.assertEqual((test['status'], test['toolCount']), ('ready', 1))
        saved = (self.root / 'data/swarmr.json').read_text(); self.assertNotIn('ACCESS-1', saved); self.assertNotIn('REFRESH-1', saved)
        self.assertNotIn('ACCESS-1', json.dumps(self.req('GET', '/api/state')[1])); self.assertNotIn('ACCESS-1', json.dumps(self.req('GET', '/api/integrations')[1]))
        self.assertEqual(self.req('POST', '/api/connectors/%s/logout' % self.cid, {})[0], 200); self.assertFalse(self.item()['signedIn'])
        self.assertEqual([p for p in (self.root / 'secrets').iterdir()], [])

    def test_expired_access_is_refreshed_and_a_dead_refresh_asks_again(self):
        Provider.state['life'] = 4; state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        time.sleep(2.5); self.assertTrue(self.item()['signedIn']); self.assertEqual(Provider.state['grants'], ['authorization_code', 'refresh_token'])
        self.stop(); self.start(); self.assertTrue(self.item()['signedIn']); self.assertEqual(len(Provider.state['grants']), 2)  # kept across a restart

    def test_a_dead_refresh_shows_sign_in_again(self):
        Provider.state['life'] = 4; Provider.state['revoked'] = True; state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        time.sleep(2.5); found = self.item(); self.assertTrue(found['needsLogin']); self.assertFalse(found['signedIn'])

    def test_a_connector_waiting_for_sign_in_does_not_stop_replies(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_rt_oauth', Path(SERVER).with_name('runtime.py')); rt = importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
        inventory = {'skills': [], 'mcp': [{'id': 'x', 'name': 'Remote'}], '_private': {'skills': {}, 'mcp': {'x': {'transport': 'http', 'url': self.base + '/mcp'}}}}
        session = rt.RuntimeSession([], ['x'], False, self.root / 'w', None, None, inventory=inventory)
        self.assertEqual(len(session.tools()), 2)                                   # only the two stand-in tools; nothing is connected for a plain reply
        asked = session.call('zook_connector_tools', {'connector': 'Remote'})
        self.assertTrue(asked['isError']); self.assertIn('需要登入', asked['content'][0]['text']); self.assertEqual(session.unavailable, ['Remote']); session.close()
        inventory['_private']['mcp']['x']['headers'] = {'Authorization': 'Bearer wrong-key'}  # a key that was refused is explained, and the reply still goes on
        session = rt.RuntimeSession([], ['x'], False, self.root / 'w', None, None, inventory=inventory)
        self.assertIn('授權被拒絕', session.call('zook_connector_tools', {'connector': 'Remote'})['content'][0]['text']); session.close()
        self.assertTrue(all('python' not in a.lower() for a in Provider.state.get('agents', ['x'])))

    def test_editing_keeps_the_sign_in_and_changing_the_address_removes_it(self):
        state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        self.req('PATCH', '/api/connectors/' + self.cid, {'name': 'Renamed'}); self.assertTrue(self.item()['signedIn'])
        self.req('PATCH', '/api/connectors/' + self.cid, {'url': self.base + '/other'}); self.assertFalse(self.item()['signedIn']); self.assertEqual(list((self.root / 'secrets').iterdir()), [])

    def test_a_busy_token_service_does_not_force_signing_in_again(self):
        Provider.state['life'] = 4; Provider.state['busy'] = True; state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        time.sleep(2.5); self.assertFalse(self.item()['needsLogin']); time.sleep(2); self.assertFalse(self.item()['needsLogin'])
        Provider.state['busy'] = False; self.assertTrue(self.item()['signedIn'])

    def test_a_connector_naming_another_service_is_refused(self):
        Provider.state['resource'] = 'https://victim.example/mcp'
        status, body = self.req('POST', '/api/connectors/%s/login' % self.cid, {}); self.assertEqual(status, 409); self.assertIn('不一致', body['error'])

    def test_a_late_sign_in_for_an_old_address_cannot_touch_the_new_one(self):
        old = self.login()                                                     # started for the first address, not finished
        self.req('PATCH', '/api/connectors/' + self.cid, {'url': self.base + '/mcp?v=2'})
        self.assertEqual(self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % old, auth=False)[0], 400)
        self.assertEqual(list((self.root / 'secrets').iterdir()), []); self.assertFalse(self.item()['signedIn'])

    def test_default_port_and_case_still_match(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_oauth_place', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        place = lambda u: z._place(z.urllib.parse.urlparse(u))
        self.assertEqual(place('https://C.example:443/mcp'), place('https://c.example/mcp')); self.assertNotEqual(place('https://c.example:8443/mcp'), place('https://c.example/mcp'))

    def test_remote_services_cannot_point_sign_in_at_this_mac(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_oauth_urls', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        for url in ('http://127.0.0.1:9/x', 'https://127.0.0.1/x', 'https://10.0.0.5/x', 'https://localhost/x', 'http://example.com/x', 'file:///etc/passwd', 'https://a:b@example.com/',
                    'https://localhost./x', 'https://127.1/x', 'https://2130706433/x', 'https://0x7f.0.0.1/x', 'https://0/x', 'https://100.64.0.1/x', 'https://[::1]/x', 'https://[::ffff:127.0.0.1]/x', 'https://LOCALHOST/x'):
            self.assertRaises(RuntimeError, z._oauth_url, url)
        self.assertEqual(z._oauth_url('https://example.com/x'), 'https://example.com/x'); self.assertEqual(z._oauth_url('http://127.0.0.1:9/x', True), 'http://127.0.0.1:9/x')

    def test_several_accounts_with_a_default_that_can_be_changed(self):
        def sign_in(add):
            status, body = self.req('POST', '/api/connectors/%s/login' % self.cid, {'add': True} if add else {}); self.assertEqual(status, 200, body)
            query = {k: v[0] for k, v in parse_qs(urlsplit(body['url']).query).items()}; Provider.state['challenge'] = query['code_challenge']
            self.assertEqual(self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % query['state'], auth=False)[0], 200)
        sign_in(False); sign_in(True); accounts = self.item()['accounts']
        self.assertEqual([(a['name'], a['active']) for a in accounts], [('帳號 1', True), ('帳號 2', False)]); parts = len(list((self.root / 'secrets').iterdir()))
        self.assertEqual(self.req('POST', '/api/connectors/%s/account' % self.cid, {'account': accounts[1]['id']})[0], 200)
        self.assertEqual([(a['name'], a['active']) for a in self.item()['accounts']], [('帳號 2', True), ('帳號 1', False)])
        self.assertEqual(self.req('POST', '/api/connectors/%s/account' % self.cid, {'account': accounts[1]['id'], 'name': '公司'})[0], 200); self.assertEqual(self.item()['accounts'][0]['name'], '公司')
        self.assertEqual(self.req('POST', '/api/connectors/%s/account' % self.cid, {'account': 'nope'})[0], 404)
        self.req('PATCH', '/api/connectors/' + self.cid, {'name': 'Renamed'}); self.assertEqual(len(self.item()['accounts']), 2)   # editing keeps both
        self.req('POST', '/api/connectors/%s/logout' % self.cid, {}); left = self.item()['accounts']
        self.assertEqual([(a['name'], a['active']) for a in left], [('帳號 1', True)]); self.assertTrue(self.item()['signedIn']); self.assertEqual(len(list((self.root / 'secrets').iterdir())), parts // 2)
        self.req('DELETE', '/api/connectors/' + self.cid); self.assertEqual(list((self.root / 'secrets').iterdir()), [])

    def test_signing_in_again_refreshes_the_account_it_was_started_for(self):
        def begin(add=False):
            body = self.req('POST', '/api/connectors/%s/login' % self.cid, {'add': True} if add else {})[1]
            query = {k: v[0] for k, v in parse_qs(urlsplit(body['url']).query).items()}; Provider.state['challenge'] = query['code_challenge']; return query['state']
        finish = lambda state: self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        finish(begin()); finish(begin(True)); a, b = self.item()['accounts']
        again = begin()                                                      # sign in again to the first account…
        self.req('POST', '/api/connectors/%s/account' % self.cid, {'account': b['id']})   # …and switch to the second before the browser returns
        finish(again); now = self.item()['accounts']
        self.assertEqual([(x['name'], x['active']) for x in now], [('帳號 2', True), ('帳號 1', False)]); self.assertEqual(now[0]['id'], b['id']); self.assertNotEqual(now[1]['id'], a['id'])

    def test_a_refusal_marks_only_the_account_that_was_refused(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_oauth_lost', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        accounts = [dict(secretId='b' * 32), dict(secretId='a' * 32)]
        self.assertFalse(z._mark_lost(accounts, 'c' * 32)); self.assertTrue(z._mark_lost(accounts, 'a' * 32)); self.assertEqual([bool(x.get('needsLogin')) for x in accounts], [False, True])

    def test_cancelled_sign_in_and_wrong_host(self):
        state = self.login(); status, page = self.req('GET', '/oauth/callback?state=%s&error=access_denied' % state, auth=False); self.assertIn('取消', page)
        self.assertEqual(self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)[0], 400)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10); conn.request('GET', '/oauth/callback?state=a&code=b', headers={'Host': 'evil.example'}); self.assertEqual(conn.getresponse().status, 403); conn.close()

    def test_removing_the_connector_removes_its_tokens(self):
        state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        self.assertTrue(list((self.root / 'secrets').iterdir())); self.req('DELETE', '/api/connectors/' + self.cid)
        self.assertEqual(list((self.root / 'secrets').iterdir()), [])


if __name__ == '__main__': unittest.main()
