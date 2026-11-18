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
            return self.send(200, {'authorization_endpoint': base + '/authorize', 'token_endpoint': base + '/token', 'registration_endpoint': base + '/register', 'code_challenge_methods_supported': ['S256']})
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
            auth = self.headers.get('Authorization', ''); s.setdefault('seen', []).append(auth[:15])
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
        self.connector = self.req('POST', '/api/connectors', {'name': 'Remote', 'transport': 'http', 'url': self.base + '/mcp'})[1]['id']; self.cid = self.connector.split(':')[1]

    def start(self):
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), ZOOK_NO_BROWSER='1', HOME=str(self.root))
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
        self.assertEqual((query['code_challenge_method'], query['redirect_uri'], query['resource']), ('S256', 'http://127.0.0.1:%d/oauth/callback' % self.port, self.base + '/mcp'))
        return query['state']

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
        Provider.state['life'] = 61; state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        time.sleep(1.5); self.assertTrue(self.item()['signedIn']); self.assertEqual(Provider.state['grants'], ['authorization_code', 'refresh_token'])
        self.stop(); self.start(); self.assertTrue(self.item()['signedIn']); self.assertEqual(len(Provider.state['grants']), 2)  # kept across a restart

    def test_a_dead_refresh_shows_sign_in_again(self):
        Provider.state['life'] = 61; Provider.state['revoked'] = True; state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        time.sleep(1.5); found = self.item(); self.assertTrue(found['needsLogin']); self.assertFalse(found['signedIn'])

    def test_a_connector_waiting_for_sign_in_does_not_stop_replies(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_rt_oauth', Path(SERVER).with_name('runtime.py')); rt = importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
        inventory = {'skills': [], 'mcp': [{'id': 'x', 'name': 'Remote'}], '_private': {'skills': {}, 'mcp': {'x': {'transport': 'http', 'url': self.base + '/mcp'}}}}
        session = rt.RuntimeSession([], ['x'], False, self.root / 'w', None, None, inventory=inventory)
        self.assertEqual(session.tools(), []); self.assertEqual(session.unavailable, ['Remote']); session.close()
        inventory['_private']['mcp']['x']['headers'] = {'Authorization': 'Bearer wrong-key'}  # a key that was refused is a real failure, and is shown
        session = rt.RuntimeSession([], ['x'], False, self.root / 'w', None, None, inventory=inventory)
        self.assertRaises(RuntimeError, session.tools); session.close()

    def test_editing_keeps_the_sign_in_and_changing_the_address_removes_it(self):
        state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        self.req('PATCH', '/api/connectors/' + self.cid, {'name': 'Renamed'}); self.assertTrue(self.item()['signedIn'])
        self.req('PATCH', '/api/connectors/' + self.cid, {'url': self.base + '/other'}); self.assertFalse(self.item()['signedIn']); self.assertEqual(list((self.root / 'secrets').iterdir()), [])

    def test_a_busy_token_service_does_not_force_signing_in_again(self):
        Provider.state['life'] = 61; Provider.state['busy'] = True; state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        time.sleep(1.5); self.assertFalse(self.item()['needsLogin']); Provider.state['busy'] = False; self.assertTrue(self.item()['signedIn'])

    def test_a_connector_naming_another_service_is_refused(self):
        Provider.state['resource'] = 'https://victim.example/mcp'
        status, body = self.req('POST', '/api/connectors/%s/login' % self.cid, {}); self.assertEqual(status, 409); self.assertIn('不一致', body['error'])

    def test_remote_services_cannot_point_sign_in_at_this_mac(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_oauth_urls', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        for url in ('http://127.0.0.1:9/x', 'https://127.0.0.1/x', 'https://10.0.0.5/x', 'https://localhost/x', 'http://example.com/x', 'file:///etc/passwd', 'https://a:b@example.com/'):
            self.assertRaises(RuntimeError, z._oauth_url, url)
        self.assertEqual(z._oauth_url('https://example.com/x'), 'https://example.com/x'); self.assertEqual(z._oauth_url('http://127.0.0.1:9/x', True), 'http://127.0.0.1:9/x')

    def test_cancelled_sign_in_and_wrong_host(self):
        state = self.login(); status, page = self.req('GET', '/oauth/callback?state=%s&error=access_denied' % state, auth=False); self.assertIn('取消', page)
        self.assertEqual(self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)[0], 400)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10); conn.request('GET', '/oauth/callback?state=a&code=b', headers={'Host': 'evil.example'}); self.assertEqual(conn.getresponse().status, 403); conn.close()

    def test_removing_the_connector_removes_its_tokens(self):
        state = self.login(); self.req('GET', '/oauth/callback?state=%s&code=CODE-1' % state, auth=False)
        self.assertTrue(list((self.root / 'secrets').iterdir())); self.req('DELETE', '/api/connectors/' + self.cid)
        self.assertEqual(list((self.root / 'secrets').iterdir()), [])


if __name__ == '__main__': unittest.main()
