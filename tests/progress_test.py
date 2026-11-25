# -*- coding: utf-8 -*-
"""等待時的進度 (#236): what a running reply has really done, how long it has been quiet, and 正在停止／強制停止."""
import http.client, importlib.util, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_progress', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class FeederTest(unittest.TestCase):
    def feed(self, kind, lines, chunk=9):
        m = load(); m.progress_start('j'); inner = []
        feed = m.progress_feeder(kind, 'j', inner.append)
        data = ''.join(json.dumps(x, ensure_ascii=False) + '\n' if not isinstance(x, str) else x + '\n' for x in lines).encode('utf-8')
        for i in range(0, len(data), chunk): feed(data[i:i + chunk])  # lines and characters cut in half on the way
        self.assertEqual(b''.join(inner), data)  # the words shown meanwhile get every byte, unchanged
        return m, m.progress_view(dict(id='j', status='running', toolCalls=[]))['progress']

    def test_claude_counts_each_tool_once(self):
        use = lambda i, name, **inp: dict(type='assistant', message=dict(content=[dict(type='tool_use', id=i, name=name, input=inp)]))
        m, p = self.feed('claude', [dict(type='system', subtype='init'), use('a', 'Read', file_path='/x/報告.docx'), use('a', 'Read', file_path='/x/報告.docx'),
                                    use('b', 'Bash', command='for f in *.png; do sips -Z 100 "$f"; done'), use('c', 'Write', file_path='/x/out.md'),
                                    use('d', 'TodoWrite', todos=[]), use('e', 'mcp__zook__zook_workspace_read', path='/x'), use('f', 'WebSearch', query='q'), 'not json'])
        self.assertEqual((p['read'], p['write'], p['command'], p['web']), (1, 1, 1, 1))
        self.assertEqual(p['step'], '查網路資料')
        self.assertTrue(abs(p['lastAt'] / 1000 - time.time()) < 5)

    def test_other_clis(self):
        item = lambda t, kind, **more: dict(type=t, item=dict(id=more.pop('id', 'i1'), type=kind, **more))
        m, p = self.feed('codex', [item('item.started', 'command_execution', command='python3 a.py'), item('item.completed', 'command_execution', command='python3 a.py'),
                                   item('item.completed', 'file_change', id='i2', changes=[dict(path='/w/a.xlsx'), dict(path='/w/b.xlsx')]), item('item.completed', 'agent_message', id='i3', text='好')])
        self.assertEqual((p['command'], p['write'], p['step']), (1, 2, '修改檔案「b.xlsx」'))
        m, p = self.feed('grok', [dict(type='tool_call', toolCallId='1', toolName='run_terminal_command', rawInput=dict(command='ls')), dict(type='tool_call', toolName='read_file', rawInput=dict(path='/a/b.txt')), dict(type='text', data='x')])
        self.assertEqual((p['command'], p['read'], p['step']), (1, 1, '讀取檔案「b.txt」'))
        m, p = self.feed('cursor', [dict(type='tool_call', subtype='started', call_id='c1', tool_call=dict(shellToolCall=dict(args=dict(command='ls')))),
                                    dict(type='tool_call', subtype='completed', call_id='c1', tool_call=dict(shellToolCall=dict(args=dict(command='ls')))),
                                    dict(type='tool_call', subtype='started', call_id='c2', tool_call=dict(editToolCall=dict(args=dict(path='/a/c.md'))))])
        self.assertEqual((p['command'], p['write']), (1, 1))
        step = lambda i, state, name, **given: dict(event='step_update', step_update=dict(step_index=i, state=state, step_type='tool', tool_name=name, tool_info=dict(parameters=given)))
        m, p = self.feed('antigravity', [step(2, 'ACTIVE', 'run_command', CommandLine='ls'), step(2, 'DONE', 'run_command', CommandLine='ls'), step(3, 'DONE', 'write_to_file', TargetFile='/a/d.txt'), step(4, 'DONE', 'view_file', AbsolutePath='/a/e.txt')])
        self.assertEqual((p['command'], p['write'], p['read']), (1, 1, 1))

    def test_zook_tools_and_what_is_shown(self):
        m = load(); m.progress_start('j')
        calls = [dict(name='zook_workspace_read', arguments=dict(path='/w/a.txt'), status='completed', createdAt='2099-01-01T00:00:00+00:00'),
                 dict(name='zook_native_gate', arguments=dict(title='刪除檔案'), status='completed'), dict(name='zook_workspace_write', status='denied'), dict(name='zook_remember', arguments=dict(content='x'), status='completed', createdAt='2099-01-01T00:00:00+00:00')]
        p = m.progress_view(dict(id='j', status='running', toolCalls=calls))['progress']
        self.assertEqual((p['read'], p['write'], p['tool'], p['step']), (1, 0, 1, '記住一件事：「x」'))
        self.assertEqual(m.progress_view(dict(id='j', status='completed')), {})  # nothing once it ended
        self.assertNotIn('progress', m.job_view(dict(id='nope', status='running')))
        self.assertIn('progress', m.job_view(dict(id='j', status='running')))
        before = m.PROGRESS['j']['last']; m.progress_touch('j'); self.assertEqual(m.PROGRESS['j']['last'], before)  # moves in steps only
        m.PROGRESS['j']['last'] -= 20; m.progress_touch('j'); self.assertGreater(m.PROGRESS['j']['last'], before - 1)
        m.progress_stop('j', object()); v = m.job_view(dict(id='j', status='cancelled'))
        self.assertTrue(v['stopping']); self.assertNotIn('progress', v)
        m.progress_end('j'); self.assertEqual(m.progress_view(dict(id='j', status='cancelled')), {})

    def test_only_work_really_done_counts(self):
        use = lambda i, name, **inp: dict(type='assistant', message=dict(content=[dict(type='tool_use', id=i, name=name, input=inp)]))
        m, p = self.feed('claude', [use('a', 'Glob', pattern='*.md'), use('b', 'Grep', pattern='x'), use('c', 'LS', path='/x')])
        self.assertEqual((p['read'], p['write'], p['command'], p['web']), (0, 0, 0, 0))  # names listed, no file opened
        calls = [dict(name='zook_workspace_write', arguments=dict(path='/w/a.txt'), status='waiting_approval'), dict(name='zook_browser_open', arguments=dict(url='https://a.b'), status='completed')]
        m.progress_start('k'); p = m.progress_view(dict(id='k', status='running', toolCalls=calls))['progress']
        self.assertEqual((p['write'], p['web'], p['tool']), (0, 1, 0))


CODEX = '''#!/usr/bin/env python3
import json, os, signal, sys, time
here = os.path.dirname(sys.argv[0])
open(os.path.join(here, 'pid'), 'w').write(str(os.getpid()))
if os.path.exists(os.path.join(here, 'stubborn')): signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a CLI that does not end when asked
sys.stdin.read()
ev = lambda t, **item: print(json.dumps({'type': t, 'item': item}), flush=True)
ev('item.started', id='c1', type='command_execution', command='python3 make.py'); ev('item.completed', id='c1', type='command_execution', command='python3 make.py')
ev('item.started', id='c2', type='command_execution', command='sips -Z 10 a.png'); ev('item.completed', id='f1', type='file_change', changes=[{'path': '/tmp/x/報告.docx'}])
end = time.time() + 60
while not os.path.exists(os.path.join(here, 'go')) and time.time() < end: time.sleep(0.05)
ev('item.completed', id='m', type='agent_message', text='完成')
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 1, 'output_tokens': 1}}), flush=True)
'''


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'P', 'provider': 'codex'})[1]

    def tearDown(self):
        try: os.kill(int((self.root / 'bin/pid').read_text()), signal.SIGKILL)
        except (OSError, ValueError): pass
        self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def until(self, test, what, limit=20):
        end = time.time() + limit
        while time.time() < end:
            value = test()
            if value: return value
            time.sleep(0.1)
        self.fail(what)

    def job(self, job_id): return self.req('GET', '/api/jobs/' + job_id)[1]

    def start(self, background=True):
        self.req('PATCH', '/api/settings', {'backgroundRuns': background})
        return self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'hi'})[1]['jobId']

    def test_progress_while_it_works(self):
        job_id = self.start()
        p = self.until(lambda: (lambda j: j.get('progress') if (j.get('progress') or {}).get('write') else None)(self.job(job_id)), 'no progress')
        self.assertEqual((p['command'], p['write'], p['read'], p['step']), (2, 1, 0, '修改檔案「報告.docx」'))  # what the CLI reported, never the command itself
        self.assertNotIn('sips', json.dumps(p)); self.assertTrue(abs(p['lastAt'] / 1000 - time.time()) < 30)
        (self.root / 'bin/go').write_text('1')
        done = self.until(lambda: (lambda j: j if j['status'] != 'running' else None)(self.job(job_id)), 'no reply')
        self.assertEqual(done['content'], '完成'); self.assertNotIn('progress', done); self.assertNotIn('stopping', done)
        self.assertNotIn('progress', json.dumps(self.req('POST', '/api/export', {})[1]))  # never written to the data file

    def stopped_stays_until_gone(self, background):
        (self.root / 'bin/stubborn').write_text('1')
        job_id = self.start(background)
        self.until(lambda: (self.job(job_id).get('progress') or {}).get('command'), 'did not start')
        status, out = self.req('POST', '/api/jobs/%s/cancel' % job_id)  # ■, an empty body as before
        self.assertEqual((status, out['status'], out.get('stopping')), (200, 'cancelled', True))
        self.until(lambda: not self.job(job_id).get('stopping'), 'still stopping', limit=15)  # it was killed after a moment
        pid = int((self.root / 'bin/pid').read_text())
        self.until(lambda: subprocess.run(['/bin/ps', '-p', str(pid)], capture_output=True).returncode != 0, 'the CLI is still running')

    def test_stopped_reply_shows_stopping_until_its_cli_is_gone(self): self.stopped_stays_until_gone(False)
    def test_same_under_a_runner(self): self.stopped_stays_until_gone(True)

    def test_force_stop(self):
        (self.root / 'bin/stubborn').write_text('1')
        job_id = self.start(False)
        self.until(lambda: (self.job(job_id).get('progress') or {}).get('command'), 'did not start')
        self.req('POST', '/api/jobs/%s/cancel' % job_id)
        began = time.time()
        status, out = self.req('POST', '/api/jobs/%s/cancel' % job_id, {'force': True})
        self.assertEqual((status, out['status']), (200, 'cancelled'))
        pid = int((self.root / 'bin/pid').read_text())
        self.until(lambda: subprocess.run(['/bin/ps', '-p', str(pid)], capture_output=True).returncode != 0, 'not killed')
        self.assertLess(time.time() - began, 1.8)  # at once, not after the usual moment
        self.until(lambda: not self.job(job_id).get('stopping'), 'still stopping')
        self.assertEqual(self.req('POST', '/api/jobs/%s/cancel' % job_id, {'force': True})[0], 200)  # again, nothing left: harmless
        self.assertEqual(self.req('POST', '/api/jobs/%s/cancel' % job_id, {'force': 'yes'})[0], 200)

    def test_group_member(self):
        (self.root / 'bin/stubborn').write_text('1')
        other = self.req('POST', '/api/bots', {'name': 'Q', 'provider': 'codex'})[1]
        group = self.req('POST', '/api/groups', {'name': 'G', 'botIds': [self.bot['id'], other['id']]})[1]
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '@P 做報告'})[0] // 100, 2)
        seen = self.until(lambda: [j for j in self.req('GET', '/api/groups/' + group['id'])[1]['jobs'] if (j.get('progress') or {}).get('command')], 'member shows no progress')
        self.assertEqual(seen[0]['progress']['write'], 1)
        self.req('POST', '/api/groups/%s/stop' % group['id'])
        after = self.req('GET', '/api/groups/' + group['id'])[1]
        self.assertEqual(after['group']['status'], 'idle')
        self.assertEqual([(j['id'], j.get('stopping')) for j in after['jobs']], [(seen[0]['id'], True)])  # still ending: kept in sight
        self.until(lambda: not self.req('GET', '/api/groups/' + group['id'])[1]['jobs'], 'still stopping', limit=15)


if __name__ == '__main__':
    unittest.main()
