# -*- coding: utf-8 -*-
import http.client, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CODEX = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a[:2] == ['login', 'status']: print('Logged in using ChatGPT'); sys.exit(0)
if a[:1] == ['app-server']:
    extra = 'accounts' in os.environ.get('CODEX_HOME', '')
    for line in sys.stdin:
        m = json.loads(line)
        if 'id' not in m: continue
        result = {}
        if m['method'] == 'account/read': result = {'account': {'type': 'chatgpt', 'email': 'second@example.com' if extra else 'first@example.com', 'planType': 'plus' if extra else 'team', 'workspaceName': 'Side' if extra else 'Main'}}
        print(json.dumps({'id': m['id'], 'result': result}), flush=True)
    sys.exit(0)
print('codex 1.0.0')
'''


class AccountCards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        (root / 'assets').mkdir(); (root / 'assets/index.html').write_text('x'); (root / 'bin').mkdir()
        cli = root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SECRETS_DIR=str(root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(root / 'data'), '--assets', str(root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def test_each_codex_account_shows_its_own_details(self):
        self.assertLess(self.req('POST', '/api/accounts/codex/profiles', {'name': '副帳號', 'type': 'login'})[0], 300)
        codex = next(p for p in self.req('GET', '/api/accounts')[1]['providers'] if p['id'] == 'codex')
        self.assertEqual((codex['email'], codex['plan'], codex['workspace']), ('first@example.com', 'team', 'Main'))
        extra = codex['profiles'][0]
        self.assertEqual((extra['name'], extra['email'], extra['plan'], extra['workspace'], extra['method']), ('副帳號', 'second@example.com', 'plus', 'Side', 'ChatGPT 帳號'))


if __name__ == '__main__': unittest.main()
