# -*- coding: utf-8 -*-
"""#33 through a real reply: a Bot set to Codex's own sign-in, used up, answers with the same Codex's other account (the model kept)
before any other CLI, and the reply says which account. An account known to be API billing is never switched to."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

W1 = 'a1' * 16  # an extra account id has the form Zook gives it
SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CODEX = '''#!/usr/bin/env python3
import os, sys
home = os.environ.get('CODEX_HOME', '')
if sys.argv[1:3] == ['login', 'status']: print('Logged in using an API key' if os.path.exists(os.path.join(home, 'apikey')) else 'Logged in using ChatGPT'); sys.exit(0)
sys.stdin.read()
if 'accounts' in os.environ.get('CODEX_HOME', ''): print('codex w1 says hi'); sys.exit(0)
sys.stderr.write('You have hit your usage limit.\\n'); sys.exit(1)
'''


class SameCliBackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        self.proc = None; self.start()
        self.bot = self.req('POST', '/api/bots', {'name': 'Tester', 'provider': 'codex'})[1]
        self.req('PATCH', '/api/settings', {'fallbacks': ['claude']})

    def start(self):
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1',
                   ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()

    def tearDown(self): self.stop(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def ask(self, content):
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': content})[0], 202)
        end = time.time() + 20
        while time.time() < end:
            state = self.req('GET', '/api/state')[1]
            last = next(b for b in state['bots'] if b['id'] == self.bot['id'])['messages'][-1]
            if last.get('status') != 'running':
                time.sleep(0.3); state = self.req('GET', '/api/state')[1]
                return next(b for b in state['bots'] if b['id'] == self.bot['id'])['messages'][-1], state['jobs'][-1]
            time.sleep(0.2)
        self.fail('no reply')

    def with_account(self, billed, checked=None):
        self.stop()
        data = self.root / 'data/swarmr.json'; state = json.loads(data.read_text()); now = time.time()
        state['accounts'] = [dict(id=W1, provider='codex', name='Waifdance', type='login', createdAt='2026-11-01T00:00:00+00:00')]
        state['autoStatus'] = {'codex': dict(signedIn=True, billed=False, checkedAt=now), 'codex@' + W1: dict(signedIn=True, billed=billed, checkedAt=now if checked is None else checked)}
        state['quota'] = {'codex': {'windows': [{'label': '5 小時', 'usedPercent': 100, 'resetsAt': now + 3600}], 'updatedAt': '2026-11-27T00:00:00+00:00'},
                          'codex@' + W1: {'windows': [{'label': '5 小時', 'usedPercent': 40, 'resetsAt': now + 3600}], 'updatedAt': '2026-11-27T00:00:00+00:00'}}
        data.write_text(json.dumps(state)); self.start()

    def test_the_other_codex_account_answers(self):
        self.with_account(False)
        message, job = self.ask('hello')
        self.assertEqual((message['status'], message['content']), ('completed', 'codex w1 says hi'))
        self.assertIn('改用 Codex（Waifdance）', message['note']); self.assertIn('額度已用完', message['note'])
        self.assertEqual(job['ran'][2], W1)

    def test_an_api_billed_account_is_never_switched_to(self):
        self.with_account(True)
        message, job = self.ask('hello')
        self.assertNotEqual(message.get('content'), 'codex w1 says hi')
        self.assertNotEqual((job.get('ran') or ['', '', ''])[2], W1)

    def test_with_no_backups_at_all_the_same_cli_still_takes_over(self):
        self.req('PATCH', '/api/settings', {'fallbacks': []})  # 設定: 不使用 for both
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bot['id'], {'fallbacks': []})[0], 200)  # and 不自動換 on the Bot
        self.with_account(False)
        message, job = self.ask('hello')
        self.assertEqual((message['status'], message['content']), ('completed', 'codex w1 says hi'))  # 不自動換 only keeps other CLIs out (2026-11-27)
        self.assertIn('改用 Codex（Waifdance）', message['note'])

    def test_an_account_switched_to_an_api_key_since_is_not_used(self):
        folder = self.root / 'data/accounts' / W1; folder.mkdir(parents=True); (folder / 'apikey').write_text('')  # signed in with a key outside Zook
        self.with_account(False, checked=0)  # Zook still thinks it is a subscription, from a check long ago
        message, job = self.ask('hello')
        self.assertNotEqual(message.get('content'), 'codex w1 says hi'); self.assertNotEqual((job.get('ran') or ['', '', ''])[2], W1)


if __name__ == '__main__': unittest.main()
