# -*- coding: utf-8 -*-
"""#34: a reply or a task run cut off by Zook's restart carries on by itself."""
import datetime, http.client, importlib.util, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
# A Codex stand-in: a prompt with SLOW says which conversation it writes into, then works for a long time (Zook is stopped meanwhile).
CODEX = r'''#!/usr/bin/env python3
import json, os, sys, time
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0]); text = sys.stdin.read()
with open(os.path.join(here, 'runs.jsonl'), 'a') as f: f.write(json.dumps(dict(args=a, prompt=text)) + '\n')
n = len(open(os.path.join(here, 'runs.jsonl')).readlines())
print(json.dumps(dict(type='thread.started', thread_id=a[a.index('resume') + 1] if 'resume' in a else 'thread-%d' % n)), flush=True)
if 'SLOW' in text and '重新啟動' not in text: time.sleep(60)
print(json.dumps(dict(type='item.completed', item=dict(type='agent_message', text='接著做完了'))))
'''


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_resume', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class ResumeAfterRestart(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755); (self.root / 'home/.codex').mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.root / 'home'), PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'),
                        ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_RESUME_DELAY='0.2')
        self.proc = None; self.start()
        self.bot = self.req('POST', '/api/bots', {'name': 'N', 'provider': 'codex'})[1]

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self, hard=False):
        (self.proc.kill if hard else self.proc.terminate)(); self.proc.wait(timeout=10); self.proc.stdout.close(); self.proc.stderr.close(); self.proc = None

    def tearDown(self):
        if self.proc: self.stop()
        self.temp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20); c.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d)

    def runs(self): return [json.loads(x) for x in (self.root / 'bin/runs.jsonl').read_text().splitlines()]
    def data(self): return json.loads((self.root / 'data/swarmr.json').read_text())
    def state(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])

    def until(self, check, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            value = check()
            if value: return value
            time.sleep(0.1)
        self.fail('timed out')

    def cut_off(self, hard=False):
        """Ask for slow work, then stop Zook once its CLI has said which conversation it writes into."""
        self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '先記住藍鯨'})
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed')
        sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'SLOW 做一份長報告'})[1]
        self.until(lambda: any((j.get('cliSession') or {}).get('session') for j in self.data()['jobs'] if j['id'] == sent['jobId']))  # saved on the Mac, never sent to a window
        self.assertNotIn('cliSession', self.req('GET', '/api/jobs/' + sent['jobId'])[1])
        self.stop(hard)
        return sent['jobId']

    def check_resumed(self):
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed')
        last = self.runs()[-1]
        self.assertEqual(last['args'][-3:], ['resume', 'thread-1', '-'])  # the CLI conversation the cut-off reply was writing into
        self.assertIn('重新啟動', last['prompt']); self.assertIn('不要重複已經完成的動作', last['prompt']); self.assertNotIn('對話紀錄', last['prompt'])
        messages = self.state()['messages']
        self.assertEqual([m['role'] for m in messages[-2:]], ['user', 'assistant'])  # the same message, not a new pair
        self.assertEqual(messages[-1]['content'], '接著做完了'); self.assertIn('接續 Zook 重啟前中斷的回覆', messages[-1].get('note', ''))

    def test_a_closed_zook_carries_on_the_reply(self):
        self.cut_off(); self.start(); self.check_resumed()

    def test_a_crashed_zook_carries_on_the_reply(self):
        self.cut_off(hard=True); self.start(); self.check_resumed()

    def test_after_a_day_it_waits_for_the_user(self):
        self.cut_off()
        data = self.data(); old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=30)).isoformat()
        for j in data['jobs']:
            if j.get('interrupted'): j['interrupted'] = old
        (self.root / 'data/swarmr.json').write_text(json.dumps(data))
        self.start(); time.sleep(1.5)
        self.assertEqual(len(self.runs()), 2)  # nothing started by itself
        reply = self.state()['messages'][-1]
        self.assertEqual(reply['status'], 'failed'); self.assertTrue(reply.get('resumable'))
        status, sent = self.req('POST', '/api/chat/resume', {'botId': self.bot['id'], 'messageId': reply['id']})
        self.assertEqual(status, 202); self.check_resumed()
        self.assertEqual(self.req('POST', '/api/chat/resume', {'botId': self.bot['id'], 'messageId': reply['id']})[0], 400)  # only once

    def test_a_conversation_that_moved_on_is_left_alone(self):
        self.cut_off(); self.env['ZOOK_RESUME_DELAY'] = '4'; self.start()
        self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '另一件事'})  # the user moved on before Zook looked back
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed'); time.sleep(5)
        self.assertEqual(len(self.runs()), 3); self.assertEqual(self.state()['messages'][-2]['content'], '另一件事')


class TaskPickupTest(unittest.TestCase):
    def test_a_task_run_goes_on_where_it_stopped(self):
        m = load()
        class Store:
            def __init__(self): self.stopped_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            data = {'jobs': [dict(id='j1', toolCalls=[dict(name='zook_write_file', category='write', status='completed', label='寫入 report.md')])]}
            def find(self, kind, x): return next((j for j in self.data['jobs'] if j['id'] == x), None)
        store = Store()
        group = dict(id='g', status='idle', messages=[], taskRun=dict(id='r', status='running', tasks=[
            dict(id='a', n=1, status='done', attempts=[dict(state='reported', outcome='succeeded')]),
            dict(id='b', n=2, status='running', attempts=[dict(state='running', jobId='j1')]),
            dict(id='c', n=3, status='running', attempts=[dict(state='reported', outcome='succeeded')]),
            dict(id='d', n=4, status='pending', deps=[2], attempts=[])]))
        m.task_board_update = lambda *a: None
        m.task_recover(group, store)
        resumed = []
        class App(m.Resuming):
            def task_resume(self, g): resumed.append(g['id'])
        app = App(); app.store = store
        app.task_pickup(group)
        tasks = group['taskRun']['tasks']
        self.assertEqual([t['status'] for t in tasks], ['done', 'ready', 'verifying', 'pending'])
        self.assertTrue(tasks[1]['resumed']); self.assertEqual(resumed, ['g'])
        prompt = m.task_worker_prompt.__globals__['interrupt_note'](store.find('jobs', 'j1'))
        self.assertIn('寫入 report.md', prompt)

    def test_an_old_run_waits_for_the_user(self):
        m = load()
        class Store:
            def __init__(self): self.stopped_at = '2026-01-01T00:00:00+00:00'
        group = dict(id='g', status='idle', messages=[], taskRun=dict(id='r', status='running', tasks=[dict(id='b', n=1, status='running', attempts=[dict(state='running')])]))
        m.task_board_update = lambda *a: None
        m.task_recover(group, Store())
        class App(m.Resuming):
            def task_resume(self, g): raise AssertionError('started by itself')
        app = App(); app.store = Store()
        app.task_pickup(group)
        self.assertEqual(group['taskRun']['tasks'][0]['status'], 'unknown'); self.assertIn('重試', group['messages'][-1]['content'])


if __name__ == '__main__':
    unittest.main()
