# -*- coding: utf-8 -*-
"""自動選擇 treats every account as its own choice: a second Codex account answers when the default one is low."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, os, sys
name = os.path.basename(sys.argv[0])
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)
if 'login' in sys.argv: print('Logged in using ChatGPT'); sys.exit(0)
if set(sys.argv) & {'models', 'app-server'}: print('Logged in'); sys.exit(0)
sys.stdin.read()
home = os.environ.get('CODEX_HOME', '')
open(os.environ['AUTO_LOG'], 'a').write(name + ' ' + (os.path.basename(home) if home else '-') + '\\n')
if name == 'claude': print(json.dumps({'type': 'result', 'result': 'from ' + name, 'is_error': False}))
else: print('from ' + name)
'''
EXTRA = 'a' * 32
KEY = 'b' * 32


class AutoAccountTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'used.log'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        self.start()
        self.req('PATCH', '/api/settings', {'autoModels': ['codex', 'claude']})
        self.bot = self.req('POST', '/api/bots', {'name': 'Auto', 'provider': 'auto'})[1]

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def start(self):
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', AUTO_LOG=str(self.log), ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        env.pop('CODEX_HOME', None)
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close()

    def restart(self, change):
        self.stop()
        path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text()); change(data); path.write_text(json.dumps(data))
        self.start()

    def with_accounts(self, codex_used=0, key=False, switches=None):
        def change(data):
            data['accounts'] = [dict(id=EXTRA, provider='codex', name='Waifdance', type='login')] + ([dict(id=KEY, provider='codex', name='API', type='key')] if key else [])
            window = lambda used: {'windows': [{'label': '5 小時', 'usedPercent': used, 'resetsAt': time.time() + 3600}], 'updatedAt': '2026-11-21T00:00:00+00:00'}
            data['quota'] = {'codex': window(codex_used), 'codex@' + EXTRA: window(5)}
            data.pop('autoStatus', None)
            if switches is not None: data['settings']['autoAccounts'] = switches
        self.restart(change)
        for _ in range(150):
            if 'codex@' + EXTRA in (self.req('GET', '/api/state')[1].get('autoStatus') or {}): return
            time.sleep(.1)
        self.fail('the extra account never got a sign-in status')

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def send(self, text):
        status, job = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})
        self.assertLess(status, 300, job)
        for _ in range(150):
            state = self.req('GET', '/api/state')[1]
            bot = next(b for b in state['bots'] if b['id'] == self.bot['id'])
            if bot['messages'][-1].get('status') != 'running': return bot['messages'][-1], next(j for j in state['jobs'] if j['id'] == job['jobId'])
            time.sleep(.1)
        self.fail('reply did not finish')

    def test_default_account_goes_first_and_the_extra_one_is_next(self):
        self.with_accounts()
        reply, job = self.send('幫我修這段 python 的 bug')
        self.assertEqual(reply['auto'], 'Codex code')
        self.assertEqual(self.log.read_text().split(), ['codex', '-'])
        self.assertEqual(job['autoChain'][:2], [['codex', ''], ['codex', '', EXTRA]])
        self.assertEqual(job['usage']['account'] if job.get('usage') else '', '')

    def test_low_default_account_moves_to_the_other_account(self):
        self.with_accounts(codex_used=95)
        reply, job = self.send('幫我修這段 python 的 bug')
        self.assertEqual(reply['auto'], 'Codex（Waifdance） code')
        self.assertIn('Codex 額度不足', reply['autoWhy'])
        self.assertEqual(self.log.read_text().split(), ['codex', EXTRA])  # the CLI ran in that account's own folder

    def test_switched_off_account_is_not_used(self):
        self.with_accounts(codex_used=95, switches={EXTRA: False})
        reply, _ = self.send('幫我修這段 python 的 bug')
        self.assertEqual(reply['auto'], 'Claude code')

    def test_api_key_account_is_never_picked(self):
        self.with_accounts(codex_used=95, key=True, switches={EXTRA: False, KEY: True})
        reply, _ = self.send('幫我修這段 python 的 bug')
        self.assertEqual(reply['auto'], 'Claude code')
        self.assertEqual(self.req('PATCH', '/api/settings', {'autoAccounts': {KEY: True}})[0], 400)  # cannot be switched on either

    def test_usage_page_shows_a_switch_per_account(self):
        self.with_accounts()
        codex = next(p for p in self.req('GET', '/api/quota')[1]['providers'] if p['id'] == 'codex')
        extra = next(a for a in codex['profiles'] if a['id'] == EXTRA)
        self.assertTrue(extra['autoOn']); self.assertFalse(extra['autoBilled'])
        self.assertEqual(self.req('PATCH', '/api/settings', {'autoAccounts': {EXTRA: False}})[0], 200)
        codex = next(p for p in self.req('GET', '/api/quota')[1]['providers'] if p['id'] == 'codex')
        self.assertFalse(next(a for a in codex['profiles'] if a['id'] == EXTRA)['autoOn'])

    def test_settings_reject_unknown_accounts_and_values(self):
        self.with_accounts()
        self.assertEqual(self.req('PATCH', '/api/settings', {'autoAccounts': {'c' * 32: True}})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'autoAccounts': {EXTRA: 'yes'}})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'autoAccounts': [EXTRA]})[0], 400)


if __name__ == '__main__': unittest.main()
