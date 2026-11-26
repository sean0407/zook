# -*- coding: utf-8 -*-
"""The usage page's cards can be put in order (dragged, or most left first), the message box has stop and send side by side,
and a message is on screen at once: nothing slow (a connector's sign-in being renewed) stands between pressing send and the Mac
taking the message."""
import http.client, http.server, importlib.util, json, os, re, subprocess, sys, tempfile, threading, time, unittest, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
CLAUDE = '''#!/usr/bin/env python3
import json, sys
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)
sys.stdin.read(); print(json.dumps({'type': 'result', 'result': 'ok', 'is_error': False}))
'''


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_cards', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def frontend(): return ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


class CardOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def card(self, key, status='logged_in', windows=None, **more):
        return dict(id=key, status=status, quota=dict(windows=windows or [], updatedAt='2026-11-23T00:00:00+00:00') if windows is not None else None, **more)

    def test_custom_order_survives_accounts_coming_and_going(self):
        items = [self.card(k) for k in ('codex', 'codex::a1', 'claude', 'grok')]
        settings = dict(usageCardOrder=['grok', 'gone::x', 'claude', 'codex'], usageCardSort='custom')  # codex::a1 is new, gone::x was removed
        self.assertEqual([x['id'] for x in self.m.usage_card_sort(settings, items)], ['grok', 'claude', 'codex', 'codex::a1'])
        self.assertEqual([x['id'] for x in self.m.usage_card_sort({}, items)], ['codex', 'codex::a1', 'claude', 'grok'])  # nothing saved: as listed

    def test_auto_puts_most_left_first_and_used_up_or_signed_out_last(self):
        later = time.time() + 3600
        w = lambda label, used: dict(label=label, usedPercent=used, resetsAt=later)
        items = [self.card('signedout', status='not_logged_in'), self.card('out', windows=[w('5 小時', 100), w('每週', 10)]),
                 self.card('codex', windows=[w('5 小時', 70), w('每週', 0)]),   # the five-hour limit is the one to watch: 30% left
                 self.card('weekly', windows=[w('每週', 20)]),                  # only a weekly one: 80% left
                 self.card('nodata', windows=[]), self.card('claude', windows=[w('5 小時', 40), w('每週', 90)])]
        got = [x['id'] for x in self.m.usage_card_sort(dict(usageCardSort='auto', usageCardOrder=['claude']), items)]
        self.assertEqual(got, ['weekly', 'claude', 'codex', 'nodata', 'out', 'signedout'])
        reset = [self.card('past', windows=[dict(label='5 小時', usedPercent=100, resetsAt=time.time() - 60)])]  # it has reset: full again
        self.assertEqual(self.m.usage_card_focus(reset[0]), (0, 100.0))

    def test_settings_are_checked(self):
        changes = {}
        self.m.usage_card_fields({'usageCardSort': 'auto', 'usageCardOrder': ['codex', 'codex', 'claude::a']}, changes)
        self.assertEqual(changes, {'usageCardSort': 'auto', 'usageCardOrder': ['codex', 'claude::a']})
        for bad in ({'usageCardSort': 'random'}, {'usageCardOrder': 'codex'}, {'usageCardOrder': [1]}, {'usageCardOrder': ['x'] * 201}, {'usageCardOrder': ['']}):
            with self.assertRaises(ValueError): self.m.usage_card_fields(bad, {})

    def test_the_page(self):
        page = frontend()
        for part in ("{id: 'custom', name: '自訂（可拖動）'}", "{id: 'auto', name: '自動（剩最多的在前）'}", 'class="usage-family-head" draggable="true"', "usageCardSort: 'custom'", 'data-card-sort'):
            self.assertIn(part, page)
        self.assertNotIn('interject-pick', page); self.assertNotIn('busySend', page); self.assertNotIn('interject:', page)  # the switch is gone
        chat = (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8')
        bot_box = re.search(r'data-action="voice".{0,400}?</form>', chat.split('function activeGroup')[0], re.S).group(0)
        self.assertLess(bot_box.index('data-action="voice"'), bot_box.index('data-action="cancel-job"'))  # 麥克風、停止、發送, from left to right
        self.assertLess(bot_box.index('data-action="cancel-job"'), bot_box.index('type="submit"'))
        self.assertIn('sendingAdd(', page); self.assertIn('sendingView(', chat)  # shown before the Mac answers


class SlowToken(http.server.BaseHTTPRequestHandler):
    asked = 0
    def do_POST(self):
        SlowToken.asked += 1
        self.rfile.read(int(self.headers.get('Content-Length') or 0)); time.sleep(1.5)
        self.send_response(503); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self, *a): pass


class SendIsQuick(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir(); (self.root / 'secrets').mkdir()
        cli = self.root / 'bin/claude'; cli.write_text(CLAUDE); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1',
                        ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.token_server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), SlowToken)
        threading.Thread(target=self.token_server.serve_forever, daemon=True).start()
        self.proc = None

    def tearDown(self):
        if self.proc: self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close()
        self.token_server.shutdown(); self.temp.cleanup()

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def test_a_connector_renewing_its_sign_in_does_not_hold_up_the_message(self):
        self.start(); bot = self.req('POST', '/api/bots', {'name': '助理', 'provider': 'claude'})[1]
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close()
        # Three connectors whose sign-ins are due for renewal, at a sign-in service that takes 1.5 seconds to answer.
        saved = os.environ.get('ZOOK_SECRETS_DIR'); os.environ['ZOOK_SECRETS_DIR'] = str(self.root / 'secrets')
        try:
            m = load(); data = json.loads((self.root / 'data/swarmr.json').read_text())
            for i in range(3):
                sid, url = uuid.uuid4().hex, 'http://127.0.0.1:%d/mcp%d' % (self.token_server.server_port, i)
                m.blob_set(sid, dict(access='a', refresh='r', expiresAt=time.time() + 600, life=3600))
                cid = uuid.uuid4().hex; data['settings'].setdefault('sharedMcp', []).append('zook:' + cid)  # turned on here: only then is a sign-in renewed
                data['connectors'].append(dict(id=cid, name='Slow%d' % i, transport='http', url=url, headers={},
                                               oauth=dict(url=url, secretId=sid, clientId='c', tokenEndpoint='http://127.0.0.1:%d/token' % self.token_server.server_port, local=True)))
            (self.root / 'data/swarmr.json').write_text(json.dumps(data))
        finally:
            if saved is None: os.environ.pop('ZOOK_SECRETS_DIR', None)
            else: os.environ['ZOOK_SECRETS_DIR'] = saved
        self.start()
        time.sleep(0.5); SlowToken.asked = 0
        began = time.time(); status, sent = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': 'hello'}); took = time.time() - began
        self.assertEqual(status, 202, sent); self.assertLess(took, 1.0)  # before: 4.5 seconds, one renewal after another
        end = time.time() + 30
        while time.time() < end and self.req('GET', '/api/jobs/' + sent['jobId'])[1]['status'] == 'running': time.sleep(0.1)
        self.assertEqual(self.req('GET', '/api/jobs/' + sent['jobId'])[1]['status'], 'completed')  # the reply renews them itself
        self.assertGreaterEqual(SlowToken.asked, 3)  # each connector's sign-in was renewed for the reply, off the request

    def test_the_light_list_only_leaves_out_sign_ins(self):
        m = load(); store = m.Store(self.root / 'data')
        store.data['settings'].setdefault('sharedMcp', []).append('zook:' + 'c' * 32)  # turned on here
        store.data['connectors'].append(dict(id='c' * 32, name='Slow', transport='http', url='http://127.0.0.1:1/mcp', headers={}, oauth=dict(url='http://127.0.0.1:1/mcp', secretId='d' * 32, clientId='c', tokenEndpoint='http://127.0.0.1:1/token')))
        asked = []; real = m.oauth_access
        m.oauth_access = lambda *a: asked.append(1) or 'tok'
        try: light, full = m.inventory_for(store, tokens=False), m.inventory_for(store)
        finally: m.oauth_access = real
        self.assertEqual(len(asked), 1)  # only the full list asked for a token
        self.assertTrue(light.get('_light')); self.assertNotIn('_light', full)
        self.assertEqual([x['id'] for x in light['mcp']], [x['id'] for x in full['mcp']])  # the same choices to check a Bot against
        self.assertNotIn('Authorization', light['_private']['mcp']['zook:' + 'c' * 32]['headers'])


if __name__ == '__main__': unittest.main()
