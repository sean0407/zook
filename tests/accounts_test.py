import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'

# Fake CLIs keep login state in a marker file; no real accounts are touched.
CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
marker = os.environ['FAKE_HOME'] + '/claude.login'
a = sys.argv[1:]
assert 'ANTHROPIC_API_KEY' not in os.environ
if a == ['auth', 'status']:
    ok = os.path.exists(marker)
    print(json.dumps({'loggedIn': ok, 'authMethod': 'claude.ai', 'subscriptionType': 'max', 'email': 'me@example.com'})); sys.exit(0 if ok else 1)
if a[:2] == ['auth', 'login']:
    print('\x1b[1mOpening browser\x1b[0m. If it did not open, visit: https://claude.ai/oauth/authorize?code=true&state=abc&pad=' + 'x' * 700 + '&end=1', flush=True)
    print('Paste code here if prompted >', flush=True)
    if sys.stdin.readline().strip() == 'GOOD-CODE':
        open(marker, 'w').close(); print('Login successful'); sys.exit(0)
    print('Invalid code'); sys.exit(1)
if a == ['auth', 'logout']:
    if os.path.exists(marker): os.remove(marker)
    sys.exit(0)
'''
CODEX = r'''#!/usr/bin/env python3
import os, sys, time
marker = os.environ['FAKE_HOME'] + '/codex.login'
a = sys.argv[1:]
if a == ['login', 'status']:
    if os.path.exists(marker): print('Logged in using ChatGPT'); sys.exit(0)
    print('Not logged in'); sys.exit(1)
if a[:1] == ['login']:
    if '--device-auth' in a: print('Open https://auth.openai.com/codex/device and enter code ABCD-12345', flush=True)
    else: print('Starting local login server on http://localhost:1455.\nIf your browser did not open, navigate to this URL to authenticate:\n\nhttps://auth.openai.com/oauth/authorize?client_id=x', flush=True)
    time.sleep(60)
if a == ['logout']:
    if os.path.exists(marker): os.remove(marker)
'''


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x')
        (self.root / 'bin').mkdir()
        for name, body in (('claude', CLAUDE), ('codex', CODEX)):
            f = self.root / 'bin' / name; f.write_text(body); f.chmod(0o755)
        (self.root / 'codex.login').touch()
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + os.environ['PATH'], FAKE_HOME=str(self.root), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ANTHROPIC_API_KEY='should-be-removed')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5)
        self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def providers(self):
        return {p['id']: p for p in self.req('GET', '/api/accounts')[1]['providers']}

    def wait_login(self, provider, state):
        for _ in range(100):
            login = self.providers()[provider]['login']
            if login and login['state'] == state: return login
            time.sleep(0.1)
        self.fail('login did not reach ' + state)

    def test_status(self):
        p = self.providers()
        self.assertEqual((p['codex']['status'], p['codex']['method']), ('logged_in', 'ChatGPT 帳號'))
        self.assertEqual((p['claude']['status'], p['claude']['email']), ('not_logged_in', ''))

    def test_claude_login_with_pasted_code_then_logout(self):
        status, view = self.req('POST', '/api/accounts/claude/login', {'method': 'claudeai'})
        self.assertEqual(status, 202)
        for _ in range(50):
            view = self.providers()['claude']['login']
            if view['url'] and view['needsCode']: break
            time.sleep(0.1)
        self.assertTrue(view['url'].startswith('https://claude.ai/oauth/authorize'))
        self.assertTrue(view['url'].endswith('&end=1'))  # long sign-in URLs must not be cut off
        self.assertNotIn('\x1b', ' '.join(view['log']))
        self.assertEqual(self.req('POST', '/api/accounts/claude/login', {})[0], 409)
        self.assertEqual(self.req('POST', '/api/accounts/claude/login/code', {'code': 'GOOD-CODE'})[0], 200)
        self.wait_login('claude', 'succeeded')
        p = self.providers()['claude']
        self.assertEqual((p['status'], p['email'], p['plan']), ('logged_in', 'me@example.com', 'max'))
        self.assertEqual(self.req('POST', '/api/accounts/claude/logout', {}), (200, {'ok': True}))
        self.assertEqual(self.providers()['claude']['status'], 'not_logged_in')

    def test_codex_device_login_and_cancel(self):
        self.req('POST', '/api/accounts/codex/login', {'method': 'device'})
        for _ in range(50):
            view = self.providers()['codex']['login']
            if view['deviceCode']: break
            time.sleep(0.1)
        self.assertEqual((view['url'], view['deviceCode'], view['needsCode']), ('https://auth.openai.com/codex/device', 'ABCD-12345', False))
        self.req('POST', '/api/accounts/codex/login/cancel', {})
        self.assertEqual(self.wait_login('codex', 'cancelled')['error'], '已取消登入。')

    def test_validation(self):
        self.assertEqual(self.req('POST', '/api/accounts/claude/login', {'method': 'sso-bypass'})[0], 400)
        self.assertEqual(self.req('POST', '/api/accounts/nope/login', {})[0], 404)
        self.assertEqual(self.req('POST', '/api/accounts/codex/login/code', {'code': 'x'})[0], 400)


if __name__ == '__main__': unittest.main()
