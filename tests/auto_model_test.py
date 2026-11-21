# -*- coding: utf-8 -*-
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, os, sys
name = os.path.basename(sys.argv[0])
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True, 'authMethod': os.environ.get('CLAUDE_METHOD', 'claude.ai')})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)  # Zook asking what this CLI can do
if 'login' in sys.argv: print('Logged in using ChatGPT'); sys.exit(0)
if set(sys.argv) & {'models', '--version', '--help', 'app-server'}: print('Logged in'); sys.exit(0)
sys.stdin.read()
open(os.environ['AUTO_LOG'], 'a').write(name + '\\n')
if name == 'claude': print(json.dumps({'type': 'result', 'result': 'from ' + name, 'is_error': False}))
else: print('from ' + name)
'''


class AutoModelTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'used.log'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', AUTO_LOG=str(self.log))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'autoModels': ['codex', 'claude']})
        self.bot = self.req('POST', '/api/bots', {'name': 'Auto', 'provider': 'auto', 'model': 'x'})[1]
        self.ready()

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def ready(self):
        for _ in range(100):
            if len(self.req('GET', '/api/state')[1].get('autoStatus') or {}) >= 2: return
            time.sleep(.1)
        self.fail('sign-in status never arrived')

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def send(self, text):
        status, job = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})
        self.assertLess(status, 300, job)
        for _ in range(100):
            bot = next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])
            if bot['messages'][-1].get('status') != 'running': return bot['messages'][-1]
            time.sleep(.1)
        self.fail('reply did not finish')

    def quota(self, provider, used):
        path = self.root / 'data/swarmr.json'
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close()
        data = json.loads(path.read_text()); data['quota'] = {provider: {'windows': [{'label': '5 小時', 'usedPercent': used, 'resetsAt': time.time() + 3600}], 'updatedAt': '2026-11-18T00:00:00+00:00'}}
        path.write_text(json.dumps(data))
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', AUTO_LOG=str(self.log))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.ready()

    def test_task_picks_model_and_says_why(self):
        self.assertEqual(self.bot['model'], '')
        reply = self.send('幫我修這段 python 的 bug')
        self.assertEqual(reply['auto'], 'Codex code'); self.assertNotIn('note', reply); self.assertEqual(self.log.read_text().split(), ['codex'])
        reply = self.send('請分析這兩個方案的優缺點')
        self.assertEqual(reply['auto'], 'Claude analysis'); self.assertIn('長篇分析', reply['autoWhy'])

    def test_low_quota_is_skipped(self):
        self.quota('codex', 95)
        reply = self.send('寫一個 python 函式')
        self.assertEqual(reply['auto'], 'Claude code'); self.assertIn('Codex 額度不足', reply['autoWhy'])

    def test_all_low_tells_the_user_and_sends_nothing(self):
        self.req('PATCH', '/api/settings', {'autoModels': ['codex']})
        self.quota('codex', 95)
        status, body = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '你好'})
        self.assertEqual(status, 400); self.assertIn('額度都低於 10%', body['error']); self.assertIn('付費', body['error'])
        self.assertFalse(self.log.exists())

    def test_api_billing_is_never_picked_even_when_turned_on(self):
        path = self.root / 'data/swarmr.json'
        self.quota('none', 0)
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close()
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', AUTO_LOG=str(self.log), CLAUDE_METHOD='api_key')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        for _ in range(100):
            if (self.req('GET', '/api/state')[1].get('autoStatus') or {}).get('claude', {}).get('billed'): break
            time.sleep(.1)
        reply = self.send('請分析這兩個方案')
        self.assertEqual(reply['auto'], 'Codex analysis'); self.assertEqual(self.log.read_text().split(), ['codex'])

    def test_named_redo_does_not_fall_back_to_other_models(self):
        self.send('寫 python')
        status, job = self.req('POST', '/api/chat/redo', {'botId': self.bot['id'], 'mode': 'again', 'provider': 'claude'})
        self.assertEqual(status, 202)
        for _ in range(100):
            found = next(j for j in self.req('GET', '/api/state')[1]['jobs'] if j['id'] == job['jobId'])
            if found['status'] != 'running': break
            time.sleep(.1)
        self.assertEqual(found['autoChain'], [['claude', '', '']]); self.assertTrue(found['autoNamed'])  # its own sign-in, as named

    def test_settings_reject_unknown_models_and_auto_as_default(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'autoModels': ['nope']})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'provider': 'auto'})[0], 400)

    def test_named_model_bot_is_unchanged(self):
        bot = self.req('POST', '/api/bots', {'name': 'Fixed', 'provider': 'claude'})[1]
        self.req('POST', '/api/chat', {'botId': bot['id'], 'content': '寫 python'})
        for _ in range(100):
            if self.log.exists(): break
            time.sleep(.1)
        self.assertEqual(self.log.read_text().split(), ['claude'])


if __name__ == '__main__': unittest.main()
