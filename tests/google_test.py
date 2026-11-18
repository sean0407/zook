# -*- coding: utf-8 -*-
import http.client, importlib.util, json, os, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]; SERVER = ROOT / 'backend/server.py'


class Google(BaseHTTPRequestHandler):
    seen = []
    email = 'me@example.com'
    def log_message(self, *args): pass
    def send(self, code, body):
        raw = json.dumps(body).encode(); self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        path = urlsplit(self.path).path; Google.seen.append(('GET', path, self.headers.get('Authorization', '')))
        if path == '/gmail/v1/users/me/profile': return self.send(200, {'emailAddress': Google.email})
        if path == '/gmail/v1/users/me/messages': return self.send(200, {'messages': [{'id': 'm1'}]})
        if path == '/gmail/v1/users/me/messages/m1': return self.send(200, {'id': 'm1', 'snippet': 'hello', 'labelIds': ['UNREAD'], 'payload': {'headers': [{'name': 'Subject', 'value': '週報'}, {'name': 'From', 'value': 'amy@example.com'}]}})
        if path == '/calendar/v3/calendars/primary/events': return self.send(200, {'items': [{'id': 'e1', 'summary': '站會', 'start': {'dateTime': '2026-11-19T09:00:00+08:00'}, 'end': {'dateTime': '2026-11-19T09:30:00+08:00'}}]})
        if path == '/drive/v3/files': return self.send(200, {'files': [{'id': 'f1', 'name': '計畫.txt', 'mimeType': 'text/plain'}]})
        self.send(404, {})
    def do_POST(self):
        path = urlsplit(self.path).path; raw = self.rfile.read(int(self.headers.get('Content-Length', '0'))); Google.seen.append(('POST', path, raw[:200]))
        if path == '/token':
            form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            if form.get('client_secret') != 'SECRET-123456': return self.send(400, {})
            return self.send(200, {'access_token': 'GACCESS', 'refresh_token': 'GREFRESH', 'expires_in': 3600})
        if path == '/gmail/v1/users/me/messages/send': return self.send(200, {'id': 'sent1'})
        self.send(404, {})


class GoogleTest(unittest.TestCase):
    def setUp(self):
        Google.seen = []; Google.email = 'me@example.com'
        self.google = ThreadingHTTPServer(('127.0.0.1', 0), Google); threading.Thread(target=self.google.serve_forever, daemon=True).start()
        self.api = 'http://127.0.0.1:%d' % self.google.server_address[1]
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'secrets').mkdir()
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), ZOOK_NO_BROWSER='1', HOME=str(self.root), ZOOK_GOOGLE_API=self.api)
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.google.shutdown(); self.google.server_close(); self.temp.cleanup()

    def req(self, method, path, body=None, auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token} if auth else {})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        try: return resp.status, json.loads(raw)
        except ValueError: return resp.status, raw.decode()

    def item(self): return next(m for m in self.req('GET', '/api/integrations')[1]['mcp'] if m.get('google'))

    def sign_in(self, write):
        status, body = self.req('POST', '/api/google', {'clientId': 'client-1234567890', 'clientSecret': 'SECRET-123456', 'write': write}); self.assertEqual(status, 200, body)
        query = {k: v[0] for k, v in parse_qs(urlsplit(body['url']).query).items()}
        self.assertEqual(self.req('GET', '/oauth/callback?state=%s&code=abc' % query['state'], auth=False)[0], 200)
        return query

    def test_read_only_sign_in_offers_only_reading(self):
        self.assertTrue(self.item()['needsSetup']); query = self.sign_in(False)
        self.assertNotIn('gmail.send', query['scope']); self.assertIn('gmail.readonly', query['scope']); self.assertEqual((query['access_type'], query['code_challenge_method']), ('offline', 'S256'))
        found = self.item(); self.assertEqual((found['needsSetup'], found['address'], found['write']), (False, 'me@example.com', False))
        tools = [t['name'] for t in self.req('POST', '/api/mcp/builtin:google/test', {})[1]['tools']]
        self.assertEqual(tools, ['gmail_search', 'gmail_read', 'calendar_list', 'drive_search', 'drive_read'])
        saved = (self.root / 'data/swarmr.json').read_text() + json.dumps(self.req('GET', '/api/state')[1]) + json.dumps(self.req('GET', '/api/integrations')[1])
        for secret in ('GACCESS', 'GREFRESH', 'SECRET-123456'): self.assertNotIn(secret, saved)

    def test_write_sign_in_adds_tools_and_sign_out_removes_everything(self):
        self.sign_in(True); tools = [t['name'] for t in self.req('POST', '/api/mcp/builtin:google/test', {})[1]['tools']]
        self.assertEqual(tools[5:], ['gmail_send', 'calendar_create', 'calendar_update', 'drive_upload', 'drive_update'])
        self.assertEqual(self.req('DELETE', '/api/google')[0], 200); self.assertTrue(self.item()['needsSetup']); self.assertEqual(list((self.root / 'secrets').iterdir()), [])

    def test_a_second_google_account_can_be_added_and_made_the_default(self):
        self.assertEqual(self.req('POST', '/api/google', {'add': True})[0], 400)   # nothing to add to yet
        self.sign_in(True); Google.email = 'work@example.com'
        status, body = self.req('POST', '/api/google', {'add': True}); self.assertEqual(status, 200, body)
        query = {k: v[0] for k, v in parse_qs(urlsplit(body['url']).query).items()}; self.assertIn('select_account', query['prompt']); self.assertIn('gmail.send', query['scope'])
        self.assertEqual(self.req('GET', '/oauth/callback?state=%s&code=abc' % query['state'], auth=False)[0], 200)
        accounts = self.item()['accounts']; self.assertEqual([(a['name'], a['active']) for a in accounts], [('me@example.com', True), ('work@example.com', False)])
        self.assertEqual(self.req('POST', '/api/google/account', {'account': accounts[1]['id']})[0], 200); self.assertEqual(self.item()['address'], 'work@example.com')
        status, body = self.req('POST', '/api/google', {'clientId': 'client-1234567890', 'clientSecret': 'SECRET-123456', 'write': True})   # plain sign-in again, choosing the other listed address
        Google.email = 'me@example.com'; query = {k: v[0] for k, v in parse_qs(urlsplit(body['url']).query).items()}; self.req('GET', '/oauth/callback?state=%s&code=abc' % query['state'], auth=False)
        self.assertEqual([(a['name'], a['active']) for a in self.item()['accounts']], [('work@example.com', True), ('me@example.com', False)])   # nobody was dropped
        self.assertEqual(self.req('DELETE', '/api/google')[0], 200); self.assertEqual([a['name'] for a in self.item()['accounts']], ['me@example.com']); self.assertFalse(self.item()['needsSetup'])
        saved = (self.root / 'data/swarmr.json').read_text()
        for secret in ('GACCESS', 'GREFRESH', 'SECRET-123456'): self.assertNotIn(secret, saved)

    def test_bad_client_details_are_refused(self):
        self.assertEqual(self.req('POST', '/api/google', {'clientId': 'x', 'clientSecret': 'SECRET-123456'})[0], 400)


class GoogleTools(unittest.TestCase):
    """The connector itself, and that every change asks first."""
    def setUp(self):
        Google.seen = []
        self.google = ThreadingHTTPServer(('127.0.0.1', 0), Google); threading.Thread(target=self.google.serve_forever, daemon=True).start()
        os.environ.update(ZOOK_GOOGLE_API='http://127.0.0.1:%d' % self.google.server_address[1], ZOOK_GOOGLE_TOKEN='GACCESS', ZOOK_GOOGLE_WRITE='1')
        spec = importlib.util.spec_from_file_location('zook_google_mcp', ROOT / 'backend/google_mcp.py'); self.g = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.g)

    def tearDown(self):
        self.google.shutdown(); self.google.server_close()
        for key in ('ZOOK_GOOGLE_API', 'ZOOK_GOOGLE_TOKEN', 'ZOOK_GOOGLE_WRITE'): os.environ.pop(key, None)

    def call(self, name, **args): return json.loads(self.g.handle({'method': 'tools/call', 'params': {'name': name, 'arguments': args}})['content'][0]['text'])

    def test_reading_mail_calendar_and_drive(self):
        self.assertEqual(self.call('gmail_search', query='is:unread')['messages'][0]['subject'], '週報')
        self.assertEqual(self.call('calendar_list', time_min='2026-11-19T00:00:00+08:00', time_max='2026-11-20T00:00:00+08:00')['events'][0]['title'], '站會')
        self.assertEqual(self.call('drive_search', query="it's")['files'][0]['name'], '計畫.txt')
        self.assertTrue(all(a == 'Bearer GACCESS' for m, p, a in Google.seen if m == 'GET'))

    def test_sending_mail(self):
        self.assertEqual(self.call('gmail_send', to=['amy@example.com'], subject='嗨', body='內容'), {'sent': True, 'id': 'sent1'})

    def test_every_change_always_asks(self):
        spec = importlib.util.spec_from_file_location('zook_rt', ROOT / 'backend/runtime.py'); rt = importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
        session = rt.RuntimeSession.__new__(rt.RuntimeSession); session.extras = {}
        session.routes = {t[0]['name']: ('builtin:google', t[0]['name']) for t in self.g.TOOLS}; session.annotations = {t[0]['name']: t[0]['annotations'] for t in self.g.TOOLS}
        kinds = {name: session.classify(name, {}) for name in session.routes}
        self.assertEqual({k for k, v in kinds.items() if v == 'danger'}, {'gmail_send', 'calendar_create', 'calendar_update', 'drive_upload', 'drive_update'})
        self.assertEqual({v for k, v in kinds.items() if v != 'danger'}, {'external_read'})
        self.assertIn('danger', rt.APPROVAL['bypass'] if hasattr(rt, 'APPROVAL') else {'danger'})


if __name__ == '__main__': unittest.main()
