# -*- coding: utf-8 -*-
"""#35 背景執行: a one-to-one reply goes on under its runner while Zook is closed or crashed, and is taken up when Zook opens again."""
import http.client, json, os, signal, subprocess, sys, tempfile, time, unittest, urllib.request
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
# A Codex stand-in. It says it started (a file), then waits for the test's go-ahead (another file). TOOL also asks Zook to write a
# file through its tool address, as Codex's MCP adapter would.
CODEX = r'''#!/usr/bin/env python3
import json, os, sys, time, urllib.request
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0]); text = sys.stdin.read()
with open(os.path.join(here, 'runs.jsonl'), 'a') as f: f.write(json.dumps(dict(args=a, prompt=text[-400:])) + '\n')
n = len(open(os.path.join(here, 'runs.jsonl')).readlines())
print(json.dumps(dict(type='thread.started', thread_id=a[a.index('resume') + 1] if 'resume' in a else 'thread-%d' % n)), flush=True)
said = '一般回覆'
if 'SLOW' in text or 'TOOL' in text:
    open(os.path.join(here, 'started'), 'w').write(str(os.getpid()))
    while not os.path.exists(os.path.join(here, 'go')): time.sleep(0.05)
    said = '背景完成'
if 'TOOL' in text:
    body = json.dumps({'method': 'tools/call', 'params': {'name': 'zook_create_schedule', 'arguments': {'content': '整理信箱', 'repeat': 'daily', 'time': '09:00'}}}).encode()
    req = urllib.request.Request(os.environ['ZOOK_WORKER_URL'], data=body, headers={'Authorization': 'Bearer ' + os.environ['ZOOK_WORKER_TOKEN'], 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r: result = json.loads(r.read())
        said = 'tool:' + ('error' if result.get('isError') else 'ok')
    except Exception as exc: said = 'tool:broken'
print(json.dumps(dict(type='item.completed', item=dict(type='agent_message', text=said))), flush=True)
'''


class BackgroundRunTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755); (self.root / 'home/.codex').mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.root / 'home'), PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'),
                        ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_RESUME_DELAY='0.2',
                        ZOOK_SECRETS_DIR=str(self.root / 'secrets'))  # the runner key outlives a restart, as it does in the Keychain
        (self.root / 'secrets').mkdir()
        self.proc = None; self.start()
        self.bot = self.req('POST', '/api/bots', {'name': 'N', 'provider': 'codex'})[1]

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self, hard=False):
        (self.proc.kill if hard else self.proc.terminate)(); self.proc.wait(timeout=15); self.proc.stdout.close(); self.proc.stderr.close(); self.proc = None

    def tearDown(self):
        (self.root / 'bin/go').write_text('1')  # nothing waits on after the test
        if self.proc: self.stop()
        time.sleep(0.3); self.temp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20); c.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d)

    def runs(self): return [json.loads(x) for x in (self.root / 'bin/runs.jsonl').read_text().splitlines()]
    def data(self): return json.loads((self.root / 'data/swarmr.json').read_text())
    def state(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])
    def job(self, job_id): return next(j for j in self.req('GET', '/api/state')[1]['jobs'] if j['id'] == job_id)
    def schedules(self): return len((self.req('GET', '/api/state')[1] if self.proc else self.data()).get('schedules') or [])
    def cli_pid(self): return int((self.root / 'bin/started').read_text())
    def go(self): (self.root / 'bin/go').write_text('1')

    def alive(self, pid):
        try: os.kill(pid, 0); return True
        except ProcessLookupError: return False

    def until(self, check, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            value = check()
            if value: return value
            time.sleep(0.1)
        self.fail('timed out')

    def send(self, text):
        job = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})[1]['jobId']
        self.until(lambda: (self.root / 'bin/started').exists())
        return job

    def finished(self, content):
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed')
        reply = self.state()['messages'][-1]
        self.assertEqual(reply['content'], content); self.assertNotIn('接續', reply.get('note', ''))
        self.assertEqual([m['role'] for m in self.state()['messages']], ['user', 'assistant'])
        return reply

    def test_closing_zook_does_not_stop_the_reply(self):
        self.send('SLOW 寫一份長報告'); pid = self.cli_pid()
        self.stop(); time.sleep(0.5)
        self.assertTrue(self.alive(pid))  # still working
        self.start()
        self.assertEqual(self.state()['messages'][-1]['status'], 'running')  # taken up, still 進行中
        self.go(); self.finished('背景完成')
        self.assertEqual(len(self.runs()), 1)  # never started again
        self.until(lambda: not list((self.root / 'data/runs').iterdir()))  # the run's files are gone once the reply is in

    def test_a_reply_that_finished_while_closed_is_simply_done(self):
        self.send('SLOW 寫一份長報告'); pid = self.cli_pid()
        self.stop(); self.go()
        self.until(lambda: not self.alive(pid))
        self.start(); self.finished('背景完成'); self.assertEqual(len(self.runs()), 1)

    def test_a_crash_does_not_stop_the_reply(self):
        self.send('SLOW 寫一份長報告'); pid = self.cli_pid()
        self.stop(hard=True); time.sleep(0.3); self.assertTrue(self.alive(pid))
        self.start(); self.go(); self.finished('背景完成'); self.assertEqual(len(self.runs()), 1)

    def test_an_action_asked_while_closed_waits_for_approval(self):
        self.send('TOOL 寫一個檔案')
        self.stop(); self.go(); time.sleep(1.5)  # it calls the tool while Zook is closed: the call waits
        self.assertEqual(self.schedules(), 0)
        self.start()
        approval = self.until(lambda: next((a for j in self.req('GET', '/api/state')[1]['jobs'] for a in j.get('approvals') or [] if a['status'] == 'pending'), None))
        self.assertEqual(self.schedules(), 0)  # not before the user says so
        self.assertEqual(self.req('POST', '/api/approvals/' + approval['id'], {'decision': 'approve'})[0], 200)
        self.finished('tool:ok'); self.assertEqual(self.schedules(), 1)

    def test_an_approval_waiting_when_zook_closes_is_asked_again(self):
        self.send('TOOL 寫一個檔案'); self.go()
        self.until(lambda: any(a['status'] == 'pending' for j in self.req('GET', '/api/state')[1]['jobs'] for a in j.get('approvals') or []))
        self.stop()
        self.start()
        approval = self.until(lambda: next((a for j in self.req('GET', '/api/state')[1]['jobs'] for a in j.get('approvals') or [] if a['status'] == 'pending'), None))
        self.assertEqual(self.schedules(), 0)  # closing approved nothing
        self.req('POST', '/api/approvals/' + approval['id'], {'decision': 'approve'})
        self.finished('tool:ok'); self.assertEqual(self.schedules(), 1)

    def test_stop_still_works_on_a_reply_taken_up(self):
        job = self.send('SLOW 寫一份長報告'); pid = self.cli_pid()
        self.stop(); self.start()
        self.until(lambda: self.state()['messages'][-1]['status'] == 'running')
        self.assertEqual(self.req('POST', '/api/jobs/%s/cancel' % job)[0], 200)
        self.until(lambda: not self.alive(pid))

    def test_with_the_switch_off_closing_stops_the_reply(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'backgroundRuns': False})[0], 200)
        self.send('SLOW 寫一份長報告'); pid = self.cli_pid()
        self.stop(); self.until(lambda: not self.alive(pid))

    def test_a_runner_that_is_gone_leaves_the_reply_to_resume(self):
        job = self.send('SLOW 寫一份長報告'); pid = self.cli_pid()
        self.stop()
        record = next(j for j in self.data()['jobs'] if j['id'] == job)['runner']
        info = json.loads((self.root / 'data/runs' / record['dir'] / 'info').read_text())
        os.kill(info['runner'], signal.SIGKILL); os.killpg(pid, signal.SIGKILL)  # as a Mac restart would
        self.until(lambda: not self.alive(pid))
        self.go(); self.start()
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed')
        self.assertEqual(len(self.runs()), 2)  # 接著做 (#34) took over
        self.assertIn('接續', self.state()['messages'][-1].get('note', ''))

    def test_the_runner_refuses_calls_without_the_reply_token(self):
        job = self.send('SLOW 寫一份長報告')
        record = next(j for j in self.data()['jobs'] if j['id'] == job)['runner']
        info = json.loads((self.root / 'data/runs' / record['dir'] / 'info').read_text())
        for path, auth in (('/api/worker/' + job, 'Bearer nope'), ('/control', 'Bearer nope'), ('/control', 'Bearer ' + self.token)):
            req = urllib.request.Request('http://127.0.0.1:%d%s' % (info['port'], path), data=b'{"action": "stop"}', headers={'Authorization': auth})
            with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(req, timeout=5)
            self.assertEqual(caught.exception.code, 403)
        self.assertTrue(self.alive(self.cli_pid()))
        self.assertNotIn('runner', self.job(job))  # never sent to a window
        self.go(); self.finished('背景完成')


class KeptCliTest(unittest.TestCase):
    """A conversation's kept CLI (live.py) that is answering when Zook closes finishes that answer, and the next Zook shows it."""
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('live_test_for_background', Path(__file__).with_name('live_test.py'))
        live = importlib.util.module_from_spec(spec); spec.loader.exec_module(live)
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir(); (self.root / 'secrets').mkdir()
        cli = self.root / 'bin/claude'; cli.write_text(live.CLAUDE); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600',
                        ZOOK_SHELL_ENV='0', ZOOK_RESUME_DELAY='0.2', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.start()
        self.req('PATCH', '/api/settings', {'provider': 'claude', 'permissionMode': 'auto'})
        self.bot = self.req('POST', '/api/bots', {'name': '助理', 'provider': 'claude'})[1]
        for _ in range(100):
            if 'claude' in (self.req('GET', '/api/state?full=1')[1].get('abilityChecks') or {}): break
            time.sleep(0.1)

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        if self.proc.poll() is None: self.proc.terminate(); self.proc.wait(timeout=10)
        self.proc.stdout.close(); time.sleep(0.3); self.temp.cleanup()

    req = BackgroundRunTest.req
    until = BackgroundRunTest.until
    alive = BackgroundRunTest.alive

    def job(self, job_id): return self.req('GET', '/api/jobs/' + job_id)[1]

    def test_a_kept_cli_finishes_its_answer_while_zook_is_closed(self):
        first = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'hi'})[1]['jobId']
        self.until(lambda: self.job(first)['status'] == 'completed')
        starts = lambda: [json.loads(x) for x in (self.root / 'bin/starts.log').read_text().splitlines()]
        pid = starts()[0]['pid']; self.assertTrue(starts()[0]['live'])
        (self.root / 'bin/slow.flag').write_text('2')
        second = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '再一次'})[1]['jobId']
        time.sleep(0.5); self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close()
        self.assertTrue(self.alive(pid))
        self.start()
        done = self.until(lambda: (lambda j: j if j['status'] != 'running' else None)(self.job(second)))
        self.assertEqual((done['status'], done['content']), ('completed', 'reply 2 from %d' % pid))
        self.assertEqual(len(starts()), 1)  # the same CLI, never started again
        self.until(lambda: not self.alive(pid))  # and not kept after that answer
        third = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '第三次'})[1]['jobId']
        self.assertEqual(self.until(lambda: (lambda j: j if j['status'] != 'running' else None)(self.job(third)))['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
