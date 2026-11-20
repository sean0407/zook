# -*- coding: utf-8 -*-
"""OpenCode through `opencode run --format json`: replies, usage, conversations, Zook's tools, permissions and its free-model limit.
The fake CLI prints what the real one (2.3.2) printed for the same requests."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time, uuid
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0])
if a[:2] == ['run', '--help']: print('FLAGS --continue --session --fork --model --agent --format choice --file --title --archived --auto --standalone'); sys.exit(0)
if a[:2] == ['session', '--help']: print('SUBCOMMANDS list delete export import'); sys.exit(0)
if a and a[0] in ('--help', '-h'): print('SUBCOMMANDS auth mcp models run session'); sys.exit(0)
if a and a[0] in ('--version', '-v'): print('opencode v2.3.2'); sys.exit(0)
if a and a[0] == 'models': print('opencode/big-pickle\nopencode/mimo-v2.6-flash-free\nopenrouter/anthropic/claude-sonnet-5'); sys.exit(0)
known = os.path.join(here, 'sessions.txt')
if a[:2] == ['session', 'export']:
    ok = os.path.exists(known) and a[2] in open(known).read().split()
    if not ok: sys.stderr.write('Session not found: %s\n' % a[2])
    sys.exit(0 if ok else 1)
if not a or a[0] != 'run': sys.exit(2)
prompt = sys.stdin.read()
session = a[a.index('-s') + 1] if '-s' in a else 'ses_' + uuid.uuid4().hex[:12]
open(known, 'a').write(session + '\n')
config = json.loads(os.environ.get('OPENCODE_CONFIG_CONTENT') or '{}')
with open(os.path.join(here, 'runs.log'), 'a') as f: f.write(json.dumps(dict(args=a, prompt=prompt, config=config, cwd=os.getcwd(), key=os.environ.get('OPENROUTER_API_KEY', ''), env={k: v for k, v in os.environ.items() if k.startswith('OPENCODE_') and k != 'OPENCODE_CONFIG_CONTENT'})) + '\n')
def out(kind, **part): print(json.dumps(dict(type=kind, timestamp=1, sessionID=session, part=dict(part, sessionID=session, messageID='msg_1'))), flush=True)
if 'LIMIT' in prompt:
    print(json.dumps(dict(type='error', timestamp=1, sessionID=session, error=dict(type='provider.free-limit', message='Free usage limit reached. Connect a provider or subscribe to OpenCode Go to keep going, or switch models.', status=429))), flush=True)
    sys.exit(1)
out('step_start', type='step-start')
said = 'reply to: ' + prompt.strip().splitlines()[0][:40] if 'TOOL' not in prompt else ''
if 'TOOL' in prompt:
    server = config['mcp']['servers']['zook']
    proc = subprocess.Popen(server['command'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(i, method, params):
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\n'); proc.stdin.flush()
        return json.loads(proc.stdout.readline())
    rpc(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}})
    got = rpc(2, 'tools/call', {'name': 'zook_create_schedule', 'arguments': {'content': '每天提醒我喝水', 'repeat': 'daily', 'time': '09:00'}})
    rpc(3, 'tools/call', {'name': 'zook_remember', 'arguments': {'content': '使用者喜歡藍色'}})
    proc.stdin.close(); proc.wait(timeout=5)
    out('tool', type='tool', tool='zook_zook_remember', state=dict(status='completed', input={'text': '使用者喜歡藍色'}))
    said = 'remembered: ' + json.dumps(got.get('result') or got.get('error'), ensure_ascii=False)[:120]
out('text', type='text', text=said)
out('step_finish', type='step-finish', reason='stop', cost=0, tokens=dict(input=1000, output=7, reasoning=3, cache=dict(read=200, write=0)))
'''


class OpenCodeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/opencode'; cli.write_text(CLI); cli.chmod(0o755)
        (self.root / 'secrets').mkdir()
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0',
                   ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': '開碼', 'provider': 'opencode'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def ask(self, text, approve=None):
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text}); self.assertEqual(status, 202, sent)
        end = time.time() + 30
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            for a in job.get('approvals') or []:
                if a['status'] == 'pending' and approve is not None: self.req('POST', '/api/approvals/' + a['id'], {'decision': 'approve' if approve else 'deny'})
            if job['status'] != 'running': return job
            time.sleep(0.1)
        self.fail('no reply')

    def runs(self): return [json.loads(l) for l in (self.root / 'bin/runs.log').read_text().splitlines()]

    def test_reply_usage_and_isolated_settings(self):
        job = self.ask('你好')
        self.assertEqual(job['status'], 'completed'); self.assertTrue(job['content'].startswith('reply to: '))
        u = job['usage']
        self.assertEqual((u['provider'], u['input'], u['cachedInput'], u['output'], u['costUsd']), ('opencode', 1200, 200, 10, 0))
        run = self.runs()[0]
        self.assertEqual(run['args'][:6], ['run', '--standalone', '--format', 'json', '--archived', '-m'])
        self.assertEqual(run['args'][6], 'opencode/big-pickle')  # no model chosen: a free one, never a paid one
        self.assertIn('你好', run['prompt']); self.assertNotIn('你好', ' '.join(run['args']))  # the message goes in on stdin
        self.assertTrue(run['env']['OPENCODE_CONFIG_DIR'].startswith(str((self.root / 'data').resolve())) or run['env']['OPENCODE_CONFIG_DIR'].startswith(str(self.root / 'data')))
        for key in ('OPENCODE_DISABLE_PROJECT_CONFIG', 'OPENCODE_DISABLE_CLAUDE_CODE', 'OPENCODE_DISABLE_AUTOUPDATE'): self.assertEqual(run['env'][key], '1')
        rules = run['config']['permissions']
        self.assertEqual(rules[0], dict(action='*', resource='*', effect='deny'))  # nothing is left to "ask", which nobody could answer

    def test_conversation_continues_and_a_lost_one_starts_over(self):
        self.ask('第一則'); self.ask('第二則')
        first, second = self.runs()
        self.assertNotIn('-s', first['args']); self.assertIn('-s', second['args'])
        (self.root / 'bin/sessions.txt').write_text('')  # OpenCode no longer has it
        self.ask('第三則')
        third = self.runs()[2]
        self.assertNotIn('-s', third['args'])
        self.assertIn('第一則', third['prompt'])  # started over with the conversation so far, not just the last message

    def test_permissions_follow_the_bot(self):
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'careful'})
        self.ask('謹慎')
        rules = {(r['action'], r['effect']) for r in self.runs()[-1]['config']['permissions']}
        self.assertIn(('zook_*', 'allow'), rules); self.assertNotIn(('edit', 'allow'), rules); self.assertNotIn(('shell', 'allow'), rules)
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'auto', 'access': 'workspace'})
        self.ask('自動')
        rules = {(r['action'], r['effect']) for r in self.runs()[-1]['config']['permissions']}
        self.assertIn(('edit', 'allow'), rules); self.assertNotIn(('shell', 'allow'), rules); self.assertNotIn(('external_directory', 'allow'), rules)
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'access': 'full'})
        self.ask('整台')
        rules = {(r['action'], r['effect']) for r in self.runs()[-1]['config']['permissions']}
        self.assertIn(('shell', 'allow'), rules); self.assertIn(('external_directory', 'allow'), rules)

    def test_zook_tools_with_approval(self):
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'careful'})
        job = self.ask('TOOL 記住我喜歡藍色', approve=False)
        self.assertEqual(job['status'], 'completed')
        self.assertTrue(any(a['status'] == 'denied' for a in job['approvals']), (job.get('content'), job.get('approvals'), job.get('toolCalls')))  # Zook asked first; the user said no
        state = self.req('GET', '/api/state?full=1')[1]
        self.assertEqual(state['schedules'], [])  # refused, so nothing was created
        self.assertIn('藍色', json.dumps(state, ensure_ascii=False))  # a tool that needs no approval did its work

    def test_free_limit_is_explained(self):
        job = self.ask('LIMIT')
        self.assertEqual(job['status'], 'failed'); self.assertIn('免費模型的額度用完', job['error'])

    def test_openrouter_key_only_for_the_bot_that_uses_it(self):
        status, account = self.req('POST', '/api/accounts/opencode/profiles', {'name': 'OpenRouter', 'type': 'key', 'key': 'sk-or-v1-test1234567890'})
        self.assertEqual(status, 201, account)
        self.ask('沒有選帳號')
        self.assertEqual(self.runs()[-1]['key'], '')  # a Bot that did not pick the key never gets it
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'account': account['id']})
        self.ask('用 OpenRouter')
        run = self.runs()[-1]
        self.assertEqual(run['key'], 'sk-or-v1-test1234567890'); self.assertNotIn('sk-or', ' '.join(run['args']))  # never on a command line
        self.assertEqual(run['args'][6], 'opencode/big-pickle')  # with the key but no model chosen: still a free model
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'model': 'openrouter/anthropic/claude-sonnet-5'})
        self.ask('付費模型')
        self.assertEqual(self.runs()[-1]['args'][6], 'openrouter/anthropic/claude-sonnet-5')  # only when the user picked it
        self.assertNotIn('sk-or', (self.root / 'data/swarmr.json').read_text())  # the key is not in Zook's data either

    def test_model_list(self):
        out = self.req('GET', '/api/models?provider=opencode')[1]
        names = [m['name'] for m in out['models']]
        self.assertEqual(names, ['big-pickle（免費）', 'mimo-v2.6-flash-free（免費）'])  # OpenRouter's come from its own catalog, and only with a key


if __name__ == '__main__': unittest.main()
