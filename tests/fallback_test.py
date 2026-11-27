# -*- coding: utf-8 -*-
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CODEX = '''#!/usr/bin/env python3
import sys
s = sys.stdin.read()
if 'CODEX-OK' in s: print('codex says hi'); sys.exit(0)
sys.stderr.write('You have hit your usage limit.\\n'); sys.exit(1)
'''
CLAUDE = '''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:3] == ['auth', 'status']:  # a subscription, unless the test signed it in with Anthropic Console (paid by use)
    print(json.dumps({'loggedIn': True, 'authMethod': 'console' if os.path.exists(os.path.join(os.path.dirname(__file__), 'console')) else 'claude.ai'})); sys.exit(0)
sys.stdin.read()
print(json.dumps({'type': 'result', 'result': 'claude says hi', 'is_error': False}))
'''


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name, body in (('codex', CODEX), ('claude', CLAUDE)):
            cli = self.root / 'bin' / name; cli.write_text(body); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'Tester', 'provider': 'codex'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5)
        self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

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
                time.sleep(0.3); state = self.req('GET', '/api/state')[1]  # the note about the model that took over is added a moment after the reply
                return next(b for b in state['bots'] if b['id'] == self.bot['id'])['messages'][-1], state['jobs'][-1]
            time.sleep(0.2)
        self.fail('no reply')

    def test_switches_to_backup_and_says_so(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'fallbacks': ['claude']})[0], 200)
        message, job = self.ask('hello')
        self.assertEqual((message['status'], message['content']), ('completed', 'claude says hi'))
        self.assertIn('改用 Claude', message['note']); self.assertIn('額度已用完', message['note'])
        self.assertEqual(job['fallback']['provider'], 'claude')
        self.assertEqual(job['attempts'][0], {'provider': 'codex', 'reason': '額度已用完'})  # a fixed reason only, never the CLI's words
        message, job = self.ask('CODEX-OK')  # the first choice works again: no switch, no note
        self.assertEqual(message['content'], 'codex says hi'); self.assertNotIn('note', message)

    def test_no_backup_fails_as_before(self):
        message, job = self.ask('hello')
        self.assertEqual(message['status'], 'failed'); self.assertIn('額度', job['error'])

    def test_bot_can_turn_backup_off_or_pick_its_own(self):
        self.req('PATCH', '/api/settings', {'fallbacks': ['claude']})
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bot['id'], {'fallbacks': []})[0], 200)
        self.assertEqual(self.ask('hello')[0]['status'], 'failed')
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bot['id'], {'fallbacks': None})[0], 200)
        self.assertEqual(self.ask('hello')[0]['content'], 'claude says hi')
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bot['id'], {'fallbacks': ['nope']})[0], 400)

    def test_known_used_up_quota_skips_without_trying(self):
        self.req('PATCH', '/api/settings', {'fallbacks': ['claude']})
        data = self.root / 'data/swarmr.json'
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()
        state = json.loads(data.read_text()); state['quota'] = {'codex': {'windows': [{'label': '5 小時', 'usedPercent': 100, 'resetsAt': time.time() + 3600}], 'updatedAt': '2026-01-01T00:00:00+00:00'}}
        data.write_text(json.dumps(state))
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        message, job = self.ask('CODEX-OK')  # Codex would answer, but Zook already knows it is used up
        self.assertEqual(message['content'], 'claude says hi'); self.assertIn('額度已用完', message['note'])

    def test_a_backup_on_api_billing_is_skipped_and_the_reply_says_why(self):
        # #132: the default Claude sign-in is Anthropic Console (paid by use): Codex is used up, and Claude must not answer instead.
        (self.root / 'bin/console').write_text('')
        self.req('PATCH', '/api/settings', {'fallbacks': ['claude']})
        message, job = self.ask('hello')
        self.assertEqual(message['status'], 'failed'); self.assertNotEqual(message.get('content'), 'claude says hi')
        self.assertNotIn('claude', [a.get('provider') for a in job.get('attempts') or [] if a.get('reason') == '額度已用完'])
        self.assertIn('備用的 Claude 沒有改用', job['error']); self.assertIn('API 計費', job['error']); self.assertIn('不用 API 計費', job['error'])
        (self.root / 'bin/console').unlink()  # signed in with the subscription again: the backup answers
        self.assertEqual(self.ask('hello')[0]['content'], 'claude says hi')


if __name__ == '__main__': unittest.main()
