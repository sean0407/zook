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

# Fake Grok CLI shaped after grok 1.0.77: `models`, `login`, `update`, headless `--prompt-file`.
GROK = r'''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
log = os.environ['FAKE_HOME'] + '/grok.args'
if a == ['models']:
    if not os.path.exists(os.environ['FAKE_HOME'] + '/grok.login'): print('You are not authenticated.\n')
    print('Default model: grok-4.6\n\nAvailable models:\n  * grok-4.6 (default)\n  - grok-4.5'); sys.exit(0)
if a == ['update']: print('Updated to 1.0.78'); sys.exit(0)
if a == ['update', '--check', '--json']: print('{"currentVersion":"1.0.77","latestVersion":"1.0.78","updateAvailable":true}'); sys.exit(0)
if a[:1] == ['login']: open(os.environ['FAKE_HOME'] + '/grok.login', 'w').close(); print('Signing in with Grok...'); print('\u2713 Signed in as me@example.com'); sys.exit(0)
if a == ['logout']:
    p = os.environ['FAKE_HOME'] + '/grok.login'
    if os.path.exists(p): os.remove(p)
    sys.exit(0)
if '--prompt-file' in a:
    open(log, 'w').write(' '.join(a) + ' ENV:' + ','.join('%s=%s' % (k, v) for k, v in sorted(os.environ.items()) if k.startswith('GROK_')))
    prompt = open(a[a.index('--prompt-file') + 1]).read()
    print('\x1b[1mgrok says\x1b[0m: ' + ('memory-ok' if '你是' in prompt else 'no-prompt')); sys.exit(0)
sys.exit(2)
'''
# A user-added CLI: prompt arrives on stdin, model via --model.
ECHO = r'''#!/usr/bin/env python3
import sys
a = sys.argv[1:]
if a == ['whoami']: sys.exit(0)
text = sys.stdin.read()
print('echo-cli model=%s chars=%d' % (a[a.index('--model') + 1] if '--model' in a else 'default', len(text)))
'''


class ProvidersTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x')
        (self.root / 'bin').mkdir()
        for name, body in (('grok', GROK), ('echo-cli', ECHO)):
            f = self.root / 'bin' / name; f.write_text(body); f.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', FAKE_HOME=str(self.root), ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(self.root))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5)
        self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def accounts(self):
        return self.req('GET', '/api/accounts')[1]

    def chat(self, provider, model=''):
        bot = self.req('GET', '/api/state')[1]['bots'][0]
        self.assertEqual(self.req('PATCH', '/api/bots/' + bot['id'], {'provider': provider, 'model': model})[0], 200)
        job_id = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': 'hello'})[1]['jobId']
        for _ in range(100):
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.1)
        self.fail('job did not finish')

    def test_grok_detected_login_models_and_chat(self):
        data = self.accounts()
        grok = next(p for p in data['providers'] if p['id'] == 'grok')  # auto-detected because the CLI is installed
        self.assertEqual((grok['status'], [m['id'] for m in grok['loginMethods']]), ('not_logged_in', ['browser', 'device']))
        self.assertEqual(grok['version'], {'current': '1.0.77', 'latest': '1.0.78', 'updateAvailable': True, 'error': ''})
        self.assertIn('gemini', [c['id'] for c in data['catalog']])
        self.assertTrue(next(c for c in data['catalog'] if c['id'] == 'gemini')['requirementMet'])  # Zook brings its own Node.js
        models = self.req('GET', '/api/models?provider=grok')[1]
        self.assertEqual([m['id'] for m in models['models']], ['grok-4.6', 'grok-4.5'])
        self.req('POST', '/api/accounts/grok/login', {'method': 'device'})
        for _ in range(50):
            if next(p for p in self.accounts()['providers'] if p['id'] == 'grok')['email']: break  # the sign-in has finished and been recorded
            time.sleep(0.1)
        grok = next(p for p in self.accounts()['providers'] if p['id'] == 'grok')
        self.assertEqual((grok['status'], grok['email']), ('logged_in', 'me@example.com'))  # captured from the sign-in output
        job = self.chat('grok', 'grok-4.5')
        self.assertEqual((job['status'], job['content']), ('completed', 'grok says: memory-ok'))
        args = (self.root / 'grok.args').read_text()
        for flag in ('GROK_MEMORY=0', 'GROK_CLAUDE_AGENTS_ENABLED=false', 'GROK_CLAUDE_RULES_ENABLED=false', 'GROK_CLAUDE_SKILLS_ENABLED=false',
                     'GROK_CLAUDE_MCPS_ENABLED=false', 'GROK_CURSOR_RULES_ENABLED=false', 'GROK_CURSOR_MCPS_ENABLED=false', '--permission-mode dontAsk', '--sandbox strict', '--deny Bash', '--deny Edit', '--allow MCPTool(zook_*)', '--trust', '--no-subagents', '--disable-web-search', '--model grok-4.5'):
            self.assertIn(flag, args)
        self.assertEqual(list((self.root / 'data/workspaces').glob('*/.grok')), [])  # per-reply prompt + MCP config removed
        bot = self.req('GET', '/api/state')[1]['bots'][0]
        self.assertEqual(self.req('PATCH', '/api/settings', {'webSearch': True})[0], 200)
        self.chat('grok', 'grok-4.5')
        args = (self.root / 'grok.args').read_text()
        self.assertIn('--allow WebSearch --allow WebFetch', args); self.assertNotIn('--disable-web-search', args)
        self.assertEqual(self.req('PATCH', '/api/settings', {'webSearch': 'yes'})[0], 400)
        self.assertEqual(self.req('POST', '/api/accounts/grok/logout', {})[0], 200)
        grok = next(p for p in self.accounts()['providers'] if p['id'] == 'grok')
        self.assertEqual((grok['status'], grok['email']), ('not_logged_in', ''))

    def test_extra_accounts_are_separate_and_chosen_per_bot(self):
        def grok(): return next(p for p in self.accounts()['providers'] if p['id'] == 'grok')
        self.assertEqual((grok()['profiles'], grok()['canAddLogin'], grok()['canAddKey']), ([], True, True))
        self.assertEqual(self.req('POST', '/api/accounts/grok/profiles', {'name': '工作', 'type': 'key', 'key': 'short'})[0], 400)
        status, key = self.req('POST', '/api/accounts/grok/profiles', {'name': '工作', 'type': 'key', 'key': 'xai-test-key-0001'})
        self.assertEqual(status, 201)
        self.assertEqual(self.req('POST', '/api/accounts/grok/profiles', {'name': '工作', 'type': 'key', 'key': 'xai-test-key-0002'})[0], 400)  # same name
        status, login = self.req('POST', '/api/accounts/grok/profiles', {'name': '個人', 'type': 'login'})
        self.assertEqual(status, 201)
        self.assertEqual([(p['name'], p['type'], p['status']) for p in grok()['profiles']], [('工作', 'key', 'logged_in'), ('個人', 'login', 'not_logged_in')])
        self.assertNotIn('xai-test-key-0001', json.dumps(self.req('GET', '/api/state')[1]) + json.dumps(self.accounts()))  # the key is never sent back
        self.assertEqual(self.req('POST', '/api/accounts/grok/login', {'method': 'device', 'account': key['id']})[0], 400)  # a key account has no sign-in
        self.assertEqual(self.req('POST', '/api/accounts/grok/login', {'method': 'device', 'account': 'nope'})[0], 404)
        listed = next(p for p in self.req('GET', '/api/providers')[1]['providers'] if p['id'] == 'grok')['accounts']
        self.assertEqual([a['name'] for a in listed], ['工作', '個人'])

        (self.root / 'grok.login').touch()
        bot = self.req('GET', '/api/state')[1]['bots'][0]
        self.assertEqual(self.req('PATCH', '/api/bots/' + bot['id'], {'account': 'nope'})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/bots/' + bot['id'], {'account': key['id']})[0], 200)
        self.assertEqual(self.chat('grok')['status'], 'completed')
        self.assertRegex((self.root / 'grok.args').read_text(), r'GROK_HOME=\S*/data/accounts/' + key['id'])
        self.assertEqual(self.req('PATCH', '/api/bots/' + bot['id'], {'account': ''})[0], 200)
        self.chat('grok'); self.assertNotIn('GROK_HOME=', (self.root / 'grok.args').read_text())  # the CLI's own sign-in

        self.req('PATCH', '/api/bots/' + bot['id'], {'account': login['id']})
        self.assertEqual(self.req('POST', '/api/accounts/grok/profiles/delete', {'account': login['id']})[0], 200)
        self.assertEqual(self.req('GET', '/api/state')[1]['bots'][0]['account'], '')  # the Bot falls back to the CLI's own sign-in
        self.assertEqual(self.req('POST', '/api/accounts/grok/profiles/delete', {'account': key['id']})[0], 200)
        self.assertFalse((self.root / key['id']).exists()); self.assertFalse((self.root / 'data/accounts' / key['id']).exists())
        self.assertEqual(grok()['profiles'], [])

    def test_install_updates_existing_and_checks_requirements(self):
        status, view = self.req('POST', '/api/accounts/grok/install', {})
        self.assertEqual(status, 202)
        for _ in range(50):
            inst = next(p for p in self.accounts()['providers'] if p['id'] == 'grok')['install']
            if inst['state'] != 'running': break
            time.sleep(0.1)
        self.assertEqual(inst['state'], 'succeeded')
        self.assertIn('Updated to 1.0.78', ' '.join(inst['log']))

    def test_custom_provider_lifecycle(self):
        self.assertEqual(self.req('POST', '/api/accounts/custom', {'name': 'X', 'command': 'echo-cli --bad'})[0], 400)
        self.assertEqual(self.req('POST', '/api/accounts/custom', {'name': 'X', 'command': 'echo-cli', 'args': '"unclosed'})[0], 400)
        status, item = self.req('POST', '/api/accounts/custom', {'name': 'Echo CLI', 'command': 'echo-cli', 'model_args': '--model {model}',
                                                                  'models': 'small, large', 'status': 'echo-cli whoami'})
        self.assertEqual((status, item['id']), (201, 'custom-echo-cli'))
        p = next(x for x in self.accounts()['providers'] if x['id'] == 'custom-echo-cli')
        self.assertEqual((p['status'], p['custom'], p['tools']), ('logged_in', True, False))
        self.assertEqual([m['id'] for m in self.req('GET', '/api/models?provider=custom-echo-cli')[1]['models']], ['small', 'large'])
        job = self.chat('custom-echo-cli', 'large')
        self.assertEqual(job['status'], 'completed'); self.assertTrue(job['content'].startswith('echo-cli model=large chars='))
        status, err = self.req('POST', '/api/accounts/custom-echo-cli/remove', {})
        self.assertEqual(status, 409); self.assertIn('使用這個提供者', err['error'])
        bot = self.req('GET', '/api/state')[1]['bots'][0]
        self.req('PATCH', '/api/bots/' + bot['id'], {'provider': ''})
        self.assertEqual(self.req('POST', '/api/accounts/custom-echo-cli/remove', {})[0], 200)
        self.assertNotIn('custom-echo-cli', [x['id'] for x in self.accounts()['providers']])
        self.assertEqual(self.req('PATCH', '/api/bots/' + bot['id'], {'provider': 'custom-echo-cli'})[0], 400)

    def test_builtins_cannot_be_removed_but_others_can(self):
        self.assertEqual(self.req('POST', '/api/accounts/codex/remove', {})[0], 409)
        self.assertEqual(self.req('POST', '/api/accounts/grok/remove', {})[0], 200)
        self.assertNotIn('grok', [x['id'] for x in self.accounts()['providers']])
        self.assertEqual(self.req('POST', '/api/accounts/grok/add', {})[0], 200)
        self.assertIn('grok', [x['id'] for x in self.accounts()['providers']])


if __name__ == '__main__': unittest.main()
