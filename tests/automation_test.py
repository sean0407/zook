# -*- coding: utf-8 -*-
"""Local scripts: a second listener that can give a Bot a task and nothing more."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
CLI = ROOT / 'backend/zook_cli.py'
CLAUDE = '''#!/usr/bin/env python3
import json, os, subprocess, sys, time
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)  # Zook asking what this CLI can do
prompt = sys.stdin.read()
here = os.path.dirname(sys.argv[0])
ask = prompt.strip().splitlines()[-1]
time.sleep(float(open(os.path.join(here, 'delay')).read()))
call = os.path.join(here, 'call.json')
if os.path.exists(call) and ('請建立排程' in ask or '建一個 Bot' in ask):  # only the message that asks for it uses the tool
    config = json.loads(sys.argv[sys.argv.index('--mcp-config') + 1])['mcpServers']['zook']
    proc = subprocess.Popen([config['command']] + config['args'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(i, method, params):
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\\n'); proc.stdin.flush(); return json.loads(proc.stdout.readline())
    rpc(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}})
    out = rpc(2, 'tools/call', json.load(open(call))); proc.stdin.close(); proc.wait(timeout=5)
    print(json.dumps({'type': 'result', 'result': 'TOOL:' + json.dumps(out.get('result') or out.get('error'), ensure_ascii=False), 'is_error': False})); sys.exit(0)
print(json.dumps({'type': 'result', 'result': '完成：' + ask[-14:], 'is_error': False}))
'''


class AutomationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/claude'; cli.write_text(CLAUDE); cli.chmod(0o755); (self.root / 'bin/delay').write_text('0.2')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'provider': 'claude'})
        self.open = self.req('POST', '/api/bots', {'name': '文件整理員', 'provider': 'claude'})[1]
        self.closed = self.req('POST', '/api/bots', {'name': '沒開的', 'provider': 'claude'})[1]
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.open['id'], {'scripts': True})[1]['scripts'], True)
        self.folder = self.root / 'data/automation'
        self.url = (self.folder / 'url').read_text().strip(); self.sport = int(self.url.rsplit(':', 1)[1])
        self.auth = (self.folder / 'headers').read_text().strip().split(': ', 1)[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def script(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.sport, timeout=45)
        send = dict({'Authorization': self.auth}, **(headers or {}))
        if host: send['Host'] = host
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, send)
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def cli(self, *args, stdin=None):
        done = subprocess.run([sys.executable, str(CLI)] + list(args), input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60, env=dict(os.environ, ZOOK_AUTOMATION=str(self.folder)))
        return done.returncode, done.stdout.strip(), done.stderr.strip()

    def test_files_are_private_and_the_door_is_narrow(self):
        self.assertEqual(oct(self.folder.stat().st_mode & 0o777), '0o700')
        for name in ('url', 'headers'): self.assertEqual(oct((self.folder / name).stat().st_mode & 0o777), '0o600')
        self.assertNotEqual(self.auth, 'Bearer ' + self.token); self.assertNotEqual(self.sport, self.port)
        ok = self.script('GET', '/v1/agents')
        self.assertEqual(ok, (200, {'agents': [{'id': self.open['id'], 'name': '文件整理員'}]}))  # only the Bot it was switched on for
        self.assertEqual(self.script('GET', '/v1/agents', headers={'Authorization': 'Bearer wrong'})[0], 403)
        self.assertEqual(self.script('GET', '/v1/agents', headers={'Authorization': 'Bearer ' + self.token})[0], 403)  # the window's own token does not work here
        self.assertEqual(self.script('GET', '/v1/agents', headers={'Origin': 'http://127.0.0.1:%d' % self.sport})[0], 403)  # anything a browser sends
        self.assertEqual(self.script('GET', '/v1/agents', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.script('GET', '/v1/agents', host='evil.example:%d' % self.sport)[0], 403)  # DNS rebinding
        self.assertEqual(self.script('GET', '/v1/agents', host='localhost:%d' % self.sport)[0], 403)
        # The window's API is not reachable with the script token, and nothing else is served here.
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10); conn.request('GET', '/api/state', headers={'Authorization': self.auth}); self.assertEqual(conn.getresponse().status, 403); conn.close()
        for path in ('/api/state', '/v1/settings', '/v1/agents/%s/approvals/x' % self.open['id'], '/'): self.assertEqual(self.script('GET', path)[0], 404, path)
        self.assertEqual(self.script('POST', '/v1/agents/%s/messages' % self.closed['id'], {'content': 'hi'})[0], 404)
        self.assertEqual(self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': ''})[0], 400)
        self.assertEqual(self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': 'x', 'wait': 99999})[0], 400)

    def test_send_wait_status_and_resend(self):
        status, out = self.script('POST', '/v1/agents/%s/messages' % quote('文件整理員'), {'content': '整理下載資料夾', 'wait': 20, 'id': 'nightly-0001'})
        self.assertEqual((status, out['status']), (200, 'completed')); self.assertIn('整理下載資料夾', out['answer'])
        again = self.script('POST', '/v1/agents/%s/messages' % quote('文件整理員'), {'content': '整理下載資料夾', 'wait': 5, 'id': 'nightly-0001'})[1]
        self.assertEqual(again['id'], out['id'])  # the same key: no second reply
        self.assertEqual(self.script('GET', '/v1/agents/%s/deliveries/%s' % (self.open['id'], out['id']))[1]['status'], 'completed')
        job = self.req('GET', '/api/jobs/' + out['id'])[1]
        self.assertEqual(job['origin'], 'script')
        bot = next(b for b in self.req('GET', '/api/state?full=1')[1]['bots'] if b['id'] == self.open['id'])
        self.assertEqual(bot['messages'], [])  # nothing lands in the conversation the user has open
        own = next(c for c in bot['chats'] if c.get('kind') == 'script')
        self.assertEqual([(m.get('author'), m['content']) for m in own['messages'] if m['role'] == 'user'], [('本機腳本', '整理下載資料夾')])
        self.assertEqual(self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': 'x', 'id': 'n1'})[0], 400)  # a key that would be ignored is refused out loud
        # A reply made in the window cannot be looked up from here.
        mine = self.req('POST', '/api/chat', {'botId': self.open['id'], 'content': '我自己問的'})[1]['jobId']
        time.sleep(1)
        self.assertEqual(self.script('GET', '/v1/agents/%s/deliveries/%s' % (self.open['id'], mine))[0], 404)

    def test_busy_bot_queues_and_the_turn_stays_a_script_turn(self):
        (self.root / 'bin/delay').write_text('1.5')
        self.req('POST', '/api/chat', {'botId': self.open['id'], 'content': '先佔住'})
        status, out = self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': '排在後面的腳本工作'})
        self.assertEqual((status, out['status']), (202, 'queued')); waited = out['id']
        (self.root / 'bin/call.json').write_text(json.dumps(dict(name='zook_create_schedule', arguments=dict(content='每小時做事', repeat='hourly', time='00:00'))))
        done = self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': '請建立排程', 'wait': 30})[1]
        self.assertEqual(done['status'], 'completed'); self.assertIn('由本機腳本啟動', done['answer'])
        self.assertEqual(self.req('GET', '/api/state')[1]['schedules'], [])
        jobs = [j for j in self.req('POST', '/api/export', {})[1]['jobs'] if j.get('origin') == 'script']
        self.assertEqual(len(jobs), 2)  # the one that waited in line is a script turn too
        later = self.script('GET', '/v1/agents/%s/deliveries/%s' % (self.open['id'], waited))  # the id given while it waited still finds its reply
        self.assertEqual((later[0], later[1]['status']), (200, 'completed'))
        prompt_note = [j for j in jobs]
        self.assertTrue(all(j.get('chatId') == jobs[0]['chatId'] for j in jobs))  # both in the scripts' own conversation

    def test_cannot_approve_and_is_told_to_wait_for_the_user(self):
        self.req('PATCH', '/api/settings', {'permissionMode': 'manual'})
        self.req('PATCH', '/api/bots/' + self.open['id'], {'isAdmin': True})
        (self.root / 'bin/call.json').write_text(json.dumps(dict(name='zook_create_bot', arguments=dict(name='腳本想建的 Bot', persona='認真', instructions='幫忙'))))
        status, out = self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': '建一個 Bot', 'wait': 20})
        self.assertEqual((status, out['status']), (200, 'needs_approval'), out)
        code, text, err = self.cli('status', '文件整理員', out['id'])
        self.assertEqual(code, 3); self.assertIn('等你在 Zook 核准', err)
        job = self.req('GET', '/api/jobs/' + out['id'])[1]
        self.req('POST', '/api/approvals/' + job['approvals'][0]['id'], {'decision': 'deny'})
        self.assertNotIn('腳本想建的 Bot', [b['name'] for b in self.req('GET', '/api/state')[1]['bots']])

    def test_command_line_tool(self):
        self.assertEqual(self.cli('list'), (0, '%s\t文件整理員' % self.open['id'], ''))
        code, text, err = self.cli('run', '文件整理員', '-', '--wait', '--timeout', '30s', stdin='從標準輸入來的工作')
        self.assertEqual((code, err), (0, '')); self.assertIn('完成：', text)
        code, text, err = self.cli('run', '文件整理員', '問一下', '--wait', '--json')
        self.assertEqual((code, json.loads(text)['status']), (0, 'completed'))
        self.assertEqual(self.cli('run', '沒開的', 'hi', '--wait')[0], 2)
        self.assertEqual(self.cli('run', '文件整理員', 'hi', '--timeout', 'soon')[0], 2)
        missing = subprocess.run([sys.executable, str(CLI), 'list'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ, ZOOK_AUTOMATION=str(self.root / 'nowhere')))
        self.assertEqual(missing.returncode, 2)

    def test_rate_limit_and_switching_off(self):
        (self.root / 'bin/delay').write_text('0')
        for i in range(60): self.assertEqual(self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': '第 %d 則' % i, 'wait': 10})[0], 200)
        status, out = self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': '第 61 則'})
        self.assertEqual(status, 429); self.assertIn('一小時內', out['error'])
        self.req('PATCH', '/api/bots/' + self.open['id'], {'scripts': False})
        self.assertEqual(self.script('GET', '/v1/agents')[1], {'agents': []})
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.open['id'], {'scripts': 'yes'})[0], 400)

    def test_silent_connection_is_dropped_and_the_line_is_not_filled(self):
        import socket
        idle = socket.create_connection(('127.0.0.1', self.sport), timeout=30)
        started = time.time()
        self.assertEqual(idle.recv(10), b'')  # closed by Zook, without having sent anything
        self.assertLess(time.time() - started, 22); idle.close()
        (self.root / 'bin/delay').write_text('4')
        self.req('POST', '/api/chat', {'botId': self.open['id'], 'content': '先佔住'})
        codes = [self.script('POST', '/v1/agents/%s/messages' % self.open['id'], {'content': '排隊 %d' % i})[0] for i in range(11)]
        self.assertEqual((codes[:10], codes[10]), ([202] * 10, 429))  # scripts take at most half of the line
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.open['id'], 'content': '使用者自己的'})[0], 202)  # the user can still get in


if __name__ == '__main__':
    unittest.main()
