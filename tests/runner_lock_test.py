# -*- coding: utf-8 -*-
"""#290 A CLI's runner is waited for with the store lock let go: a runner slow to report its CLI does not hold up the rest of
Zook, a stop while it starts leaves nothing running, and Zook closing meanwhile still leaves the reply to be taken up."""
import http.client, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import background_test as bt  # its Codex stand-in

SERVER = bt.SERVER
RUNNER = SERVER.with_name('runner.py')
# Zook as it is, except that its runner is a stand-in that waits while the test's `hold` file is there, then is the real runner
# (same process, so the same pid and start time Zook recorded).
LAUNCH = r'''import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('zook_server_slow_runner', %r)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.RUNNER_SCRIPT = pathlib.Path(%r)
sys.argv = [%r] + sys.argv[1:]
m.main()
'''
SLOW = r'''import os, runpy, sys, time
here = os.path.dirname(os.path.abspath(__file__))
while os.path.exists(os.path.join(here, 'hold')): time.sleep(0.05)
sys.argv = [%r] + sys.argv[1:]
runpy.run_path(%r, run_name='__main__')
'''


class RunnerLockTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        for d in ('assets', 'bin', 'slow', 'secrets', 'home/.codex'): (self.root / d).mkdir(parents=True)
        (self.root / 'assets/index.html').write_text('x')
        cli = self.root / 'bin/codex'; cli.write_text(bt.CODEX); cli.chmod(0o755)
        (self.root / 'slow/runner.py').write_text(SLOW % (str(RUNNER), str(RUNNER)))
        (self.root / 'launch.py').write_text(LAUNCH % (str(SERVER), str(self.root / 'slow/runner.py'), str(SERVER)))
        self.env = dict(os.environ, HOME=str(self.root / 'home'), PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'),
                        ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_RESUME_DELAY='0.2',
                        ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = None; self.start()
        self.bot = self.req('POST', '/api/bots', {'name': 'N', 'provider': 'codex'})[1]

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(self.root / 'launch.py'), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=15); self.proc.stdout.close(); self.proc.stderr.close(); self.proc = None

    def tearDown(self):
        self.release(); (self.root / 'bin/go').write_text('1')
        if self.proc: self.stop()
        self.end_ours(); self.temp.cleanup()

    def ours(self):
        """This test's runners and stand-in CLIs that still run (by the test folder in their command line)."""
        lines = subprocess.run(['/bin/ps', '-axww', '-o', 'pid=,command='], capture_output=True, text=True).stdout.splitlines()
        return [int(l.split()[0]) for l in lines if str(self.root) + '/' in l and 'launch.py' not in l and int(l.split()[0]) != os.getpid()]

    def end_ours(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in self.ours():
                try: os.kill(pid, sig)
                except OSError: pass
            end = time.time() + 5
            while self.ours() and time.time() < end: time.sleep(0.1)

    def req(self, method, path, body=None, timeout=20):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout); c.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d)

    def hold(self): (self.root / 'slow/hold').write_text('1')
    def release(self):
        try: (self.root / 'slow/hold').unlink()
        except FileNotFoundError: pass
    def data(self): return json.loads((self.root / 'data/swarmr.json').read_text())
    def record(self, job): return next(j for j in self.data()['jobs'] if j['id'] == job).get('runner')
    def message(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])['messages'][-1]

    def alive(self, pid):
        try: os.kill(pid, 0)
        except ProcessLookupError: return False
        state = subprocess.run(['/bin/ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(state) and not state.startswith('Z')

    def until(self, check, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            value = check()
            if value: return value
            time.sleep(0.05)
        self.fail('timed out')

    def send_held(self, text):
        """A reply whose runner is started (on disk) but has not reported its CLI yet."""
        self.hold()
        job = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})[1]['jobId']
        record = self.until(lambda: self.record(job))
        return job, record

    def test_a_slow_runner_does_not_hold_up_other_requests(self):
        job, record = self.send_held('SLOW 寫一份長報告')
        time.sleep(0.5)  # well inside the runner's wait
        for _ in range(3):
            began = time.monotonic(); status, _ = self.req('GET', '/api/state', timeout=10)
            self.assertEqual(status, 200); self.assertLess(time.monotonic() - began, 1.0)  # not held until the runner reports
        self.assertEqual(self.message()['status'], 'running')
        self.assertFalse((self.root / 'bin/started').exists())  # its CLI has not started yet
        self.release(); self.until(lambda: (self.root / 'bin/started').exists())
        (self.root / 'bin/go').write_text('1')
        self.until(lambda: self.message().get('status') == 'completed')
        self.assertEqual(self.message()['content'], '背景完成')

    def test_a_stop_while_the_runner_starts_leaves_nothing_running(self):
        job, record = self.send_held('SLOW 寫一份長報告')
        self.assertTrue(self.alive(record['pid']))
        began = time.monotonic()
        self.assertEqual(self.req('POST', '/api/jobs/%s/cancel' % job, timeout=10)[0], 200)
        self.assertLess(time.monotonic() - began, 2.0)
        self.until(lambda: not self.alive(record['pid']), 10)  # its runner ended, before it read its settings
        self.release(); time.sleep(1.5)  # nothing it could still have started
        self.assertFalse((self.root / 'bin/started').exists()); self.assertFalse((self.root / 'bin/runs.jsonl').exists())
        self.assertEqual(self.ours(), [])
        self.assertEqual(self.message()['status'], 'cancelled')
        self.until(lambda: not (self.root / 'data/runs' / record['dir']).exists(), 10)

    def test_closing_zook_while_the_runner_starts_still_leaves_the_reply_to_go_on(self):
        job, record = self.send_held('SLOW 寫一份長報告')
        import threading
        closing = threading.Thread(target=self.stop); closing.start()
        time.sleep(1); self.assertTrue(closing.is_alive())  # Zook waits for a CLI still starting, as the lock once made it
        self.release(); closing.join(20); self.assertFalse(closing.is_alive())
        self.until(lambda: (self.root / 'bin/started').exists())  # it got its message
        self.assertTrue(self.alive(record['pid']))  # and goes on under its runner
        self.start()
        self.assertEqual(self.message()['status'], 'running')
        (self.root / 'bin/go').write_text('1')
        self.until(lambda: self.message().get('status') == 'completed')
        self.assertEqual(self.message()['content'], '背景完成')
        self.assertEqual(len((self.root / 'bin/runs.jsonl').read_text().splitlines()), 1)  # never started twice


class SlowKeptCliTest(unittest.TestCase):
    """The same for a conversation's kept CLI (live.py): its message waits for the runner, the rest of Zook does not."""
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('live_test_for_runner_lock', HERE / 'live_test.py')
        live = importlib.util.module_from_spec(spec); spec.loader.exec_module(live)
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        for d in ('assets', 'bin', 'slow', 'secrets'): (self.root / d).mkdir(parents=True)
        (self.root / 'assets/index.html').write_text('x')
        cli = self.root / 'bin/claude'; cli.write_text(live.CLAUDE); cli.chmod(0o755)
        (self.root / 'slow/runner.py').write_text(SLOW % (str(RUNNER), str(RUNNER)))
        (self.root / 'launch.py').write_text(LAUNCH % (str(SERVER), str(self.root / 'slow/runner.py'), str(SERVER)))
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600',
                        ZOOK_SHELL_ENV='0', ZOOK_RESUME_DELAY='0.2', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = None; self.start()
        self.req('PATCH', '/api/settings', {'provider': 'claude', 'permissionMode': 'auto'})
        self.bot = self.req('POST', '/api/bots', {'name': '助理', 'provider': 'claude'})[1]
        self.until(lambda: 'claude' in (self.req('GET', '/api/state?full=1')[1].get('abilityChecks') or {}))

    start = RunnerLockTest.start; stop = RunnerLockTest.stop; tearDown = RunnerLockTest.tearDown; ours = RunnerLockTest.ours; end_ours = RunnerLockTest.end_ours
    req = RunnerLockTest.req; hold = RunnerLockTest.hold; release = RunnerLockTest.release; data = RunnerLockTest.data; record = RunnerLockTest.record
    alive = RunnerLockTest.alive; until = RunnerLockTest.until; send_held = RunnerLockTest.send_held

    def job(self, job_id): return self.req('GET', '/api/jobs/' + job_id)[1]
    def starts(self):
        path = self.root / 'bin/starts.log'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def test_a_kept_cli_slow_to_start_gets_its_message_without_holding_zook(self):
        job, record = self.send_held('hi')
        time.sleep(0.5)
        began = time.monotonic(); self.assertEqual(self.req('GET', '/api/state', timeout=10)[0], 200); self.assertLess(time.monotonic() - began, 1.0)
        self.assertEqual(self.starts(), [])
        self.release()
        done = self.until(lambda: (lambda j: j if j['status'] != 'running' else None)(self.job(job)))
        pid = self.starts()[0]['pid']; self.assertTrue(self.starts()[0]['live'])
        self.assertEqual((done['status'], done['content']), ('completed', 'reply 1 from %d' % pid))
        second = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '再一次'})[1]['jobId']
        done = self.until(lambda: (lambda j: j if j['status'] != 'running' else None)(self.job(second)))
        self.assertEqual(done['content'], 'reply 2 from %d' % pid); self.assertEqual(len(self.starts()), 1)  # kept, as before

    def test_a_stop_while_a_kept_cli_starts_leaves_nothing_running(self):
        job, record = self.send_held('hi')
        self.assertEqual(self.req('POST', '/api/jobs/%s/cancel' % job, timeout=10)[0], 200)
        self.until(lambda: not self.alive(record['pid']), 10)
        self.release(); time.sleep(1.5)
        self.assertEqual(self.starts(), []); self.assertEqual(self.ours(), [])
        self.assertEqual(self.job(job)['status'], 'cancelled')
        third = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '再一次'})[1]['jobId']  # the next message works
        self.assertEqual(self.until(lambda: (lambda j: j if j['status'] != 'running' else None)(self.job(third)))['status'], 'completed')


if __name__ == '__main__': unittest.main()
