# -*- coding: utf-8 -*-
"""Cursor through `cursor-agent -p --output-format stream-json`: replies, usage, conversations, Zook's tools, and the folder guard.
The fake CLI prints what the real one (2026.11.19) printed for the same requests, and runs the guard hook the way Cursor does."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
GUARD = ROOT / 'backend/cursor_guard.py'
CLI = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, uuid, shlex
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0])
if a and a[0] in ('--help', '-h'): print('Options: --print --output-format --stream-partial-output --mode --resume --model --force --approve-mcps --trust --add-dir --sandbox'); sys.exit(0)
if a and a[0] in ('--version', '-v'): print('2026.11.19-f005e9d'); sys.exit(0)
if a and a[0] == 'models': print('Available models\n\nauto - Auto (current, default)\ncomposer-2.5 - Composer 2.5\ngrok-4.7-low-fast - Grok 4.7  Low Fast​​'); sys.exit(0)
if a and a[0] == 'status': print('✓ Logged in as someone@example.com'); sys.exit(0)
if '-p' not in a: sys.exit(2)
prompt = sys.stdin.read()
session = a[a.index('--resume') + 1] if '--resume' in a else str(uuid.uuid4())
chat = os.path.join(os.environ['CURSOR_CONFIG_DIR'], 'chats', 'abc', session); os.makedirs(chat, exist_ok=True)
cursor_dir = os.path.join(os.getcwd(), '.cursor')
hooks = json.load(open(os.path.join(cursor_dir, 'hooks.json')))
mcp = json.load(open(os.path.join(cursor_dir, 'mcp.json')))
def guard(tool, data):
    hook = hooks['hooks']['preToolUse'][0]
    done = subprocess.run(shlex.split(hook['command']), input=json.dumps(dict(hook_event_name='preToolUse', tool_name=tool, tool_input=data, workspace_roots=[os.getcwd()])), capture_output=True, text=True)
    open(os.path.join(here, 'hook.log'), 'a').write(repr((hook['command'], done.stdout, done.stderr[-300:])) + '\n')
    try: return json.loads(done.stdout).get('permission') == 'allow'
    except ValueError: return not hook.get('failClosed')
with open(os.path.join(here, 'runs.log'), 'a') as f:
    f.write(json.dumps(dict(args=a, prompt=prompt, cwd=os.getcwd(), hooks=hooks, mcp=mcp, guard=os.environ.get('ZOOK_CURSOR_GUARD'), egress=os.environ.get('CURSOR_FORCED_SHELL_EGRESS', ''),
                            key=os.environ.get('CURSOR_API_KEY', ''))) + '\n')
def out(**e): print(json.dumps(dict(e, session_id=session)), flush=True)
out(type='system', subtype='init', apiKeySource='login', cwd=os.getcwd(), model='Auto', permissionMode='default')
if 'NOAUTH' in prompt:
    sys.stderr.write('Error: Authentication required. Please run `agent login` first, or set CURSOR_API_KEY environment variable.\n'); sys.exit(1)
out(type='assistant', message=dict(role='assistant', content=[dict(type='text', text="I'll take a look first.")]), timestamp_ms=1)
results = []
if 'FILES' in prompt:
    inside = os.path.join(os.getcwd(), 'note.txt')
    for tool, data in (('Write', {'file_path': inside, 'content': 'A'}), ('Read', {'file_path': '/etc/hosts'}), ('Write', {'file_path': '/tmp/zook-cursor-outside.txt', 'content': 'B'}), ('Shell', {'command': 'date'})):
        out(type='tool_call', subtype='started', call_id='c', tool_call={'editToolCall' if tool == 'Write' else 'readToolCall' if tool == 'Read' else 'shellToolCall': {'args': {'path': data.get('file_path', ''), 'command': data.get('command', '')}}})
        results.append('%s %s=%s' % (tool, data.get('file_path') or data.get('command'), 'ok' if guard(tool, data) else 'denied'))
if 'TOOL' in prompt:
    server = mcp['mcpServers']['zook']
    env = dict(os.environ, **{k: os.environ.get(v[6:-1], '') for k, v in server['env'].items()})
    proc = subprocess.Popen([server['command']] + server['args'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    def rpc(i, method, params):
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\n'); proc.stdin.flush()
        return json.loads(proc.stdout.readline())
    rpc(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}})
    out(type='tool_call', subtype='started', call_id='m', tool_call={'mcpToolCall': {'args': {'name': 'zook-zook_remember', 'toolName': 'zook_remember'}}})
    allowed = guard('MCP:zook_remember', {})
    got = rpc(2, 'tools/call', {'name': 'zook_remember', 'arguments': {'content': '使用者喜歡綠色'}}) if allowed else {}
    proc.stdin.close(); proc.wait(timeout=5)
    results.append('remembered: ' + json.dumps(got.get('result') or got.get('error'), ensure_ascii=False)[:80])
final = ' | '.join(results) if results else 'reply to: ' + prompt.strip().splitlines()[0][:40]
out(type='assistant', message=dict(role='assistant', content=[dict(type='text', text=final[:10])]), timestamp_ms=2)
out(type='assistant', message=dict(role='assistant', content=[dict(type='text', text=final[10:])]), timestamp_ms=3)
out(type='assistant', message=dict(role='assistant', content=[dict(type='text', text=final)]))
out(type='result', subtype='success', is_error=False, result="I'll take a look first." + final, usage=dict(inputTokens=1000, outputTokens=20, cacheReadTokens=300, cacheWriteTokens=0))
'''


class CursorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir(); (self.root / 'secrets').mkdir()
        cli = self.root / 'bin/cursor-agent'; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0',
                   ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': '游標', 'provider': 'cursor'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close(); self.temp.cleanup()
        try: os.remove('/tmp/zook-cursor-outside.txt')
        except OSError: pass

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

    def hooklog(self): return (self.root / 'bin/hook.log').read_text()

    def runs(self): return [json.loads(l) for l in (self.root / 'bin/runs.log').read_text().splitlines()]

    def test_reply_usage_and_settings(self):
        job = self.ask('你好')
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertEqual(job['content'], 'reply to: ' + job['content'][10:])  # what it said after its last step, once, not the streamed pieces too
        self.assertNotIn('take a look', job['content'])
        u = job['usage']
        self.assertEqual((u['provider'], u['input'], u['cachedInput'], u['output'], u['costUsd']), ('cursor', 1300, 300, 20, None))
        run = self.runs()[0]
        for flag in ('-p', '--force', '--trust', '--approve-mcps'): self.assertIn(flag, run['args'])
        self.assertIn('你好', run['prompt']); self.assertNotIn('你好', ' '.join(run['args']))  # the message goes in on stdin
        self.assertEqual(run['hooks']['hooks']['preToolUse'][0]['failClosed'], True)
        self.assertIn('cursor_guard.py', run['hooks']['hooks']['preToolUse'][0]['command'])
        self.assertEqual(run['mcp']['mcpServers']['zook']['env']['ZOOK_WORKER_TOKEN'], '${env:ZOOK_WORKER_TOKEN}')  # the token itself is never written down
        self.assertEqual(run['egress'], '1')  # 上網搜尋 is off by default: Cursor's web search and fetch are off too

    def test_conversation_continues_and_a_lost_one_starts_over(self):
        self.ask('第一則'); self.ask('第二則')
        first, second = self.runs()
        self.assertNotIn('--resume', first['args']); self.assertIn('--resume', second['args'])
        import shutil; shutil.rmtree(self.root / 'data/tools/cursor-config/chats')  # Cursor no longer has it
        self.ask('第三則')
        third = self.runs()[2]
        self.assertNotIn('--resume', third['args']); self.assertIn('第一則', third['prompt'])

    def test_guard_follows_the_bot(self):
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'auto', 'access': 'workspace'})
        job = self.ask('FILES')
        self.assertIn('note.txt=ok', job['content'], self.hooklog()[:1500]); self.assertIn('/etc/hosts=denied', job['content'])
        self.assertIn('zook-cursor-outside.txt=denied', job['content']); self.assertIn('date=denied', job['content'])
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'manual'})
        job = self.ask('FILES')
        self.assertIn('note.txt=denied', job['content'])  # 謹慎: only Zook's tools
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'auto', 'access': 'full'})
        job = self.ask('FILES')
        self.assertIn('/etc/hosts=ok', job['content']); self.assertIn('date=ok', job['content'])
        self.assertIn('--sandbox', self.runs()[-1]['args'])

    def test_web_switch(self):
        self.req('PATCH', '/api/settings', dict(webSearch=True))
        self.ask('上網')
        self.assertEqual(self.runs()[-1]['egress'], '')

    def test_zook_tools(self):
        job = self.ask('TOOL 記住我喜歡綠色')
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertIn('remembered', job['content'])
        self.assertIn('綠色', json.dumps(self.req('GET', '/api/state?full=1')[1], ensure_ascii=False))

    def test_not_signed_in_is_explained(self):
        job = self.ask('NOAUTH')
        self.assertEqual(job['status'], 'failed'); self.assertIn('Cursor 還沒登入', job['error'])

    def test_status_and_models(self):
        p = {x['id']: x for x in self.req('GET', '/api/accounts')[1]['providers']}['cursor']
        self.assertEqual((p['status'], p['email'], p['chat']), ('logged_in', 'someone@example.com', True))
        names = [m['name'] for m in self.req('GET', '/api/models?provider=cursor')[1]['models']]
        self.assertEqual(names, ['Auto（Cursor 自動選）', 'Composer 2.5', 'Grok 4.7  Low Fast'])


class GuardTest(unittest.TestCase):
    def run_guard(self, rule, tool, data, root='/w'):
        done = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(dict(tool_name=tool, tool_input=data, workspace_roots=[root])), capture_output=True, text=True,
                              env=dict(os.environ, ZOOK_CURSOR_GUARD=json.dumps(rule) if rule is not None else ''))
        return json.loads(done.stdout)['permission']

    def test_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = os.path.realpath(tmp); os.mkdir(w + '/in'); os.symlink('/etc', w + '/in/escape')
            rule = dict(read=[w + '/in'], write=[w + '/in'], shell=False, task=False)
            self.assertEqual(self.run_guard(rule, 'Write', {'file_path': w + '/in/a.txt'}), 'allow')
            self.assertEqual(self.run_guard(rule, 'Write', {'file_path': 'a.txt'}, root=w + '/in'), 'allow')  # relative to the workspace
            self.assertEqual(self.run_guard(rule, 'Write', {'file_path': w + '/in/../a.txt'}), 'deny')
            self.assertEqual(self.run_guard(rule, 'Read', {'file_path': w + '/in/escape/hosts'}), 'deny')  # a link out of the folder
            self.assertEqual(self.run_guard(rule, 'Delete', {'file_path': '/tmp/x'}), 'deny')
            self.assertEqual(self.run_guard(rule, 'Shell', {'command': 'ls'}), 'deny')
            self.assertEqual(self.run_guard(rule, 'Task', {'prompt': 'x'}), 'deny')
            self.assertEqual(self.run_guard(rule, 'MCP:zook_remember', {}), 'allow')
            self.assertEqual(self.run_guard(rule, 'MCP:other_tool', {}), 'deny')
            self.assertEqual(self.run_guard(dict(rule, write=[]), 'Write', {'content': 'no path given'}), 'deny')
            os.mkdir(w + '/in/.cursor')
            self.assertEqual(self.run_guard(rule, 'Write', {'file_path': w + '/in/.cursor/mcp.json'}), 'deny')  # would start any command next time
            self.assertEqual(self.run_guard(rule, 'Write', {'file_path': w + '/in/.claude/settings.json'}), 'deny')
            self.assertEqual(self.run_guard(rule, 'Delete', {'file_path': w + '/in/.cursor/hooks.json'}), 'deny')
            self.assertEqual(self.run_guard(dict(read=None, write=None, shell=True, task=True), 'Write', {'file_path': '~/.cursor/mcp.json'}), 'deny')
            self.assertEqual(self.run_guard(rule, 'Read', {'file_path': w + '/in/.cursor/mcp.json'}), 'allow')
            self.assertEqual(self.run_guard(rule, 'Write', {'file_path': w + '/in/.CURSOR/HOOKS.JSON'}), 'deny')  # the disk ignores case
            self.assertEqual(self.run_guard(rule, 'Delete', {'file_path': w + '/in/.cursor'}), 'deny')
            self.assertEqual(self.run_guard(rule, 'Delete', {'file_path': w + '/in'}), 'deny')  # not the whole folder
            self.assertEqual(self.run_guard(rule, 'SomeNewTool', {'x': 1}), 'deny')  # unknown tools are refused
            self.assertEqual(self.run_guard(rule, 'BackgroundJob', {'command': 'curl x', 'cwd': w + '/in'}), 'deny')  # a command under any name
            self.assertEqual(self.run_guard(rule, 'Read', {'paths': [w + '/in/a', '/etc/hosts']}), 'deny')  # every path in a list
            self.assertEqual(self.run_guard(rule, 'TodoWrite', {'todos': []}), 'allow')
            careful = dict(read=[w + '/in/attachments'], write=[], shell=False, task=False)
            self.assertEqual(self.run_guard(careful, 'Grep', {'pattern': 'x'}, root=w + '/in'), 'deny')  # no folder given: the whole workspace
            own = os.path.realpath(os.path.expanduser('~/.cursor/projects'))
            mine = own + '/Users-x-workspaces-' + os.path.basename(w + '/in') + '/agent-tools/r.txt'
            self.assertEqual(self.run_guard(careful, 'Write', {'file_path': mine}, root=w + '/in'), 'allow')  # Cursor's own long results
            self.assertEqual(self.run_guard(careful, 'Read', {'file_path': own + '/someone-else/agent-transcripts/t.jsonl'}, root=w + '/in'), 'deny')
            self.assertEqual(self.run_guard(None, 'Read', {'file_path': w + '/in/a'}), 'deny')  # no rule: nothing
            self.assertEqual(self.run_guard(dict(read=None, write=None, shell=True, task=True), 'Write', {'file_path': '/etc/x'}), 'allow')


if __name__ == '__main__': unittest.main()
