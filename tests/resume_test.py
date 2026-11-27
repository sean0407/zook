# -*- coding: utf-8 -*-
"""#34: a reply or a task run cut off by Zook's restart carries on by itself."""
import datetime, http.client, importlib.util, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
# A Codex stand-in: a message with SLOW (not the history sent with it) says which conversation it writes into, then works for a long time (Zook is stopped meanwhile).
CODEX = r'''#!/usr/bin/env python3
import json, os, sys, time
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0]); text = sys.stdin.read()
with open(os.path.join(here, 'runs.jsonl'), 'a') as f: f.write(json.dumps(dict(args=a, prompt=text)) + '\n')
n = len(open(os.path.join(here, 'runs.jsonl')).readlines())
print(json.dumps(dict(type='thread.started', thread_id=a[a.index('resume') + 1] if 'resume' in a else 'thread-%d' % n)), flush=True)
asked = text.split('對話紀錄：', 1)[1].rsplit('\n使用者：', 1)[-1] if '對話紀錄：' in text else text  # this message only, not the history sent with it
if 'CMD' in asked and '重新啟動' not in text: print(json.dumps(dict(type='item.started', item=dict(id='i1', type='command_execution', command='curl -X POST x', status='in_progress'))), flush=True)
if ('SLOW' in asked or 'CMD' in asked) and '重新啟動' not in text: time.sleep(60)
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
        self.req('PATCH', '/api/settings', {'backgroundRuns': False})  # #34 on its own; with it on, a reply is not cut off at all (background_test.py)

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

    def cut_off(self, hard=False, text='SLOW 做一份長報告', wait=None):
        """Ask for slow work, then stop Zook once its CLI has said which conversation it writes into."""
        self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '先記住藍鯨'})
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed')
        sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})[1]
        self.until(lambda: any((j.get('cliSession') or {}).get('session') and (wait is None or j.get(wait)) for j in self.data()['jobs'] if j['id'] == sent['jobId']))  # saved on the Mac, never sent to a window
        # A reply that goes on in a CLI conversation notes it before its CLI starts (resume_feed): Zook is stopped only once the CLI
        # has its prompt. Stopped sooner, under load, the CLI never ran and the next message was sent the whole history.
        self.until(lambda: any(text in r['prompt'] for r in self.runs()))
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
        job = self.cut_off(hard=True)
        pid = next(j for j in self.data()['jobs'] if j['id'] == job)['cliPid'][0]
        os.kill(pid, 0)  # the crash left its CLI running
        self.start(); self.check_resumed()
        self.until(lambda: subprocess.run(['/bin/ps', '-p', str(pid)], capture_output=True).returncode != 0)  # stopped before the reply went on

    def test_a_reply_cut_off_on_a_backup_is_checked_again_before_it_goes_on(self):
        # #132: the Bot's own model is now Claude, so the Codex it was answering with is a backup Zook picked. This Codex never says it is
        # signed in to a subscription: the reply does not go on with it by itself.
        self.cut_off(); data = self.data()
        for b in data['bots']:
            if b['id'] == self.bot['id']: b['provider'] = 'claude'
        (self.root / 'data/swarmr.json').write_text(json.dumps(data))
        self.start(); time.sleep(2)
        self.assertFalse([r for r in self.runs() if '重新啟動' in r['prompt']])  # Codex was not started again to go on (its sign-in checks are logged too)
        self.assertNotEqual(self.state()['messages'][-1].get('content'), '接著做完了')

    def test_a_restored_backup_or_older_data_starts_nothing_by_itself(self):
        self.cut_off(); data = self.data()
        for j in data['jobs']:
            if j.get('interrupted'): j['status'] = 'running'; j.pop('interrupted'); j.pop('resumeSeen', None)  # as a backup taken mid-reply holds it
        data['savedAt'] = '2026-01-01T00:00:00+00:00'
        (self.root / 'data/swarmr.json').write_text(json.dumps(data))
        self.start(); time.sleep(1.5)
        self.assertEqual(len(self.runs()), 2); self.assertTrue(self.state()['messages'][-1].get('resumable'))

    def test_a_reply_that_may_have_acted_outward_waits_for_the_user(self):
        job = self.cut_off(); data = self.data()
        for j in data['jobs']:
            if j['id'] == job: j['toolCalls'] = [dict(id='c', name='gmail_send', category='external_write', status='running')]
        (self.root / 'data/swarmr.json').write_text(json.dumps(data))
        self.start(); time.sleep(1.5)
        self.assertEqual(len(self.runs()), 2)
        reply = self.state()['messages'][-1]
        self.assertTrue(reply.get('resumable')); self.assertIn('對外', reply.get('note', ''))

    def test_a_reply_that_ran_a_command_waits_for_the_user(self):
        # #285: the command is only in the CLI's own output until its turn ends; Zook notes that one started as soon as it is seen.
        job = self.cut_off(text='CMD 寄出週報', wait='usedTools')
        self.start(); time.sleep(1.5)
        self.assertEqual(len(self.runs()), 2)  # not done again by itself
        reply = self.state()['messages'][-1]
        self.assertTrue(reply.get('resumable')); self.assertIn('指令', reply.get('note', ''))
        self.assertEqual(self.req('POST', '/api/chat/resume', {'botId': self.bot['id'], 'messageId': reply['id']})[0], 202)  # the user decides
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed')
        self.assertIn('重新啟動', self.runs()[-1]['prompt'])

    def test_a_reply_whose_tools_are_not_known_waits_for_the_user(self):
        # A record from before #285 (or a try on a CLI whose output does not say when a tool starts): whether it ran one is not known.
        job = self.cut_off(); data = self.data()
        for j in data['jobs']:
            if j['id'] == job: j.pop('toolWatch', None); j.pop('toolsOn', None); j['nativeAccess'][3] = True  # its CLI could use its own tools
        (self.root / 'data/swarmr.json').write_text(json.dumps(data))
        self.start(); time.sleep(1.5)
        self.assertEqual(len(self.runs()), 2)
        reply = self.state()['messages'][-1]
        self.assertTrue(reply.get('resumable')); self.assertIn('無法確認', reply.get('note', ''))

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
        # #285: the one that was running stops for the user (it may have run commands Zook cannot see yet); the reported one is only checked.
        self.assertEqual([t['status'] for t in tasks], ['done', 'stuck', 'verifying', 'pending'])
        self.assertIn('按「重試」或「接受結果」', tasks[1]['note']); self.assertTrue(tasks[1]['resumed']); self.assertEqual(resumed, ['g'])
        self.assertIn('停下來等你確認', group['messages'][-1]['content']); self.assertIn('工作 2', group['messages'][-1]['content'])
        self.assertEqual(group['taskRun'].get('bonusAttempts', 0), 0)
        prompt = m.task_worker_prompt.__globals__['interrupt_note'](store.find('jobs', 'j1'))
        self.assertIn('寫入 report.md', prompt)

    def cut_run(self, m, fresh=True):
        class Store:
            def __init__(self): self.stopped_at = datetime.datetime.now(datetime.timezone.utc).isoformat() if fresh else '2020-01-01T00:00:00+00:00'
            data = {'jobs': [dict(id='j1', toolCalls=[])], 'settings': {'taskEngine': True}, 'bots': []}
            def find(self, kind, x): return next((j for j in self.data['jobs'] if j['id'] == x), None)
            def save(self): pass
        store = Store()
        group = dict(id='g', status='idle', messages=[], taskRun=dict(id='r', status='running', tasks=[
            dict(id='b', n=1, title='寄信', assignee='x', status='running', attempts=[dict(state='running', jobId='j1')]),
            dict(id='d', n=2, title='整理', assignee='x', status='pending', deps=[1], attempts=[])]))
        g = m.task_route.__globals__; self.addCleanup(g.__setitem__, 'task_board_update', g['task_board_update']); g['task_board_update'] = lambda *a: None
        m.task_recover(group, store)
        class App(m.Resuming):
            def task_resume(self, g): pass
        app = App(); app.store = store
        app.task_pickup(group)
        return store, group

    def press(self, m, store, group, what, task='b'):
        said = []
        class Handler:
            command = 'POST'
            class server:
                @staticmethod
                def task_resume(g): pass
                @staticmethod
                def task_poke(g): pass
            def error(self, code, text): said.append((code, text))
            def respond(self, code, body): said.append((code, body))
        m.task_route(Handler(), store, group, ['api', 'groups', 'g', 'tasks', task, what])
        return said[-1]

    def test_a_task_cut_by_a_restart_can_be_accepted(self):
        # The user's call (2026-11-25): work cut off by a restart waits; the user picks 「重試」 or 「接受結果」.
        m = load()
        store, group = self.cut_run(m)
        run = group['taskRun']; b = run['tasks'][0]
        self.assertEqual(b['status'], 'stuck'); self.assertIn('按「重試」或「接受結果」', b['note'])
        self.assertIn('「重試」或「接受結果」', group['messages'][-1]['content'])
        self.assertIn('按「重試」或「接受結果」', m.task_board_text(None, run))  # the phone's board says both too
        self.assertEqual(self.press(m, store, group, 'accept')[0], 202)
        self.assertEqual(b['status'], 'done'); self.assertTrue(b['acceptedCut']); self.assertEqual(b['verify']['state'], 'accepted')
        self.assertIn('中斷後手動接受', b['note']); self.assertIn('中斷後手動接受了工作 1', group['messages'][-1]['content'])
        m.task_resolve_deps(run)
        self.assertEqual(run['tasks'][1]['status'], 'ready')  # what waited for it can start
        self.assertIn('沒有回報完成', m.task_upstream_line(None, b))  # the next step is told it has no report to go on
        self.assertIn('中斷後手動接受', m.task_line(None, b)); self.assertIn('中斷後手動接受', m.task_board_text(None, run))
        self.assertEqual(self.press(m, store, group, 'accept')[0], 409)  # once

    def test_a_task_cut_by_a_late_restart_can_be_accepted_too(self):
        m = load()
        store, group = self.cut_run(m, fresh=False)
        b = group['taskRun']['tasks'][0]
        self.assertEqual(b['status'], 'unknown'); self.assertIn('「重試」或「接受結果」', group['messages'][-1]['content'])
        self.assertEqual(self.press(m, store, group, 'accept')[0], 202); self.assertEqual(b['status'], 'done')
        self.assertEqual(group['taskRun']['tasks'][1]['status'], 'pending')  # stopped only by the restart: what waited for it goes on
        m.task_resolve_deps(group['taskRun']); self.assertEqual(group['taskRun']['tasks'][1]['status'], 'ready')

    def test_a_task_that_reported_failure_just_before_a_restart_can_only_be_retried(self):
        m = load()
        g = m.task_route.__globals__; self.addCleanup(g.__setitem__, 'task_recover', g['task_recover'])
        real = g['task_recover']
        def recover(group, store=None):  # its zook_task_done(failed) came in, the turn had not ended yet
            group['taskRun']['tasks'][0]['attempts'][-1].update(state='reported', outcome='failed'); real(group, store)
        g['task_recover'] = recover; m.task_recover = recover
        for fresh in (True, False):
            store, group = self.cut_run(m, fresh)
            b = group['taskRun']['tasks'][0]
            self.assertNotIn('cut', b); self.assertNotIn('接受結果', b.get('note', ''))
            self.assertEqual(self.press(m, store, group, 'accept')[0], 409)

    def test_a_retried_cut_task_is_no_longer_acceptable_without_a_report(self):
        m = load()
        store, group = self.cut_run(m)
        b = group['taskRun']['tasks'][0]
        self.assertEqual(self.press(m, store, group, 'retry')[0], 202); self.assertNotIn('cut', b)
        b['status'] = 'stuck'; b['attempts'].append(dict(state='failed'))  # it failed on its own afterwards: nothing to accept
        self.assertEqual(self.press(m, store, group, 'accept')[0], 409)

    def test_a_running_task_without_any_record_of_tools_also_stops(self):
        m = load()
        class Store:
            def __init__(self): self.stopped_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            data = {'jobs': [dict(id='j1', toolCalls=[])]}  # its commands would only be written when its turn ended
            def find(self, kind, x): return next((j for j in self.data['jobs'] if j['id'] == x), None)
        group = dict(id='g', status='idle', messages=[], taskRun=dict(id='r', status='running', tasks=[dict(id='b', n=1, status='running', attempts=[dict(state='running', jobId='j1')])]))
        m.task_board_update = lambda *a: None
        m.task_recover(group, Store())
        class App(m.Resuming):
            def task_resume(self, g): pass
        app = App(); app.store = Store()
        app.task_pickup(group)
        self.assertEqual(group['taskRun']['tasks'][0]['status'], 'stuck')

    def test_a_finished_report_is_checked_again_even_after_an_outward_step(self):
        # #179: the work had already reported success; going on only checks it again, so nothing outward is repeated.
        m = load()
        class Store:
            def __init__(self): self.stopped_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            data = {'jobs': [dict(id='j1', ranOn='codex', toolCalls=[dict(name='gmail_send', category='external_write', status='completed')])]}
            def find(self, kind, x): return next((j for j in self.data['jobs'] if j['id'] == x), None)
        store = Store()
        group = dict(id='g', status='idle', messages=[], taskRun=dict(id='r', status='running', tasks=[
            dict(id='c', n=1, status='running', attempts=[dict(state='reported', outcome='succeeded', jobId='j1')])]))
        m.task_board_update = lambda *a: None
        m.task_recover(group, store)
        class App(m.Resuming):
            def task_resume(self, g): pass
        app = App(); app.store = store
        app.task_pickup(group)
        self.assertEqual(group['taskRun']['tasks'][0]['status'], 'verifying')
        self.assertEqual(m.task_worker_kind(store, group['taskRun']['tasks'][0]), 'codex')  # cut off before the turn wrote it: a checker of another vendor can still be chosen

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


class ToolWatchTest(unittest.TestCase):
    def test_each_cli_says_when_a_built_in_tool_starts(self):
        m = load(); seen = m.native_tool_started
        self.assertTrue(seen('claude', dict(type='assistant', message=dict(content=[dict(type='tool_use', name='Bash', id='1')]))))
        self.assertFalse(seen('claude', dict(type='assistant', message=dict(content=[dict(type='tool_use', name='mcp__zook__zook_read_file', id='1')]))))
        self.assertFalse(seen('claude', dict(type='assistant', message=dict(content=[dict(type='text', text='hi')]))))
        self.assertTrue(seen('codex', dict(type='item.started', item=dict(type='command_execution'))))
        self.assertTrue(seen('codex', dict(type='item.completed', item=dict(type='file_change'))))
        self.assertTrue(seen('codex', dict(type='item.started', item=dict(type='mcp_tool_call', server='gmail'))))
        self.assertFalse(seen('codex', dict(type='item.started', item=dict(type='mcp_tool_call', server='zook'))))
        self.assertFalse(seen('codex', dict(type='item.completed', item=dict(type='agent_message'))))
        self.assertTrue(seen('grok', dict(type='tool_call', toolName='run_terminal_cmd')))
        self.assertTrue(seen('cursor', dict(type='tool_call', subtype='started', tool_call=dict(shellToolCall={}))))
        self.assertFalse(seen('cursor', dict(type='tool_call', subtype='started', tool_call=dict(mcpToolCall={}))))
        self.assertTrue(seen('antigravity', dict(step_update=dict(step_type='tool', tool_name='run_command'))))
        self.assertFalse(seen('gemini', dict(type='tool_call')))

    def test_a_reply_is_marked_once_and_saved_at_once(self):
        m = load(); import threading
        class Store:
            lock = threading.RLock(); saves = 0; data = {'jobs': [dict(id='j')]}
            def find(self, kind, x): return self.data['jobs'][0] if x == 'j' else None
            def save(self): Store.saves += 1
        got = []; feed = m.tool_watch(Store(), 'j', 'codex', got.append)
        line = json.dumps(dict(type='item.started', item=dict(type='command_execution'))).encode()
        feed(line[:10]); self.assertNotIn('usedTools', Store.data['jobs'][0])  # half a line
        feed(line[10:] + b'\n' + line + b'\n')
        self.assertTrue(Store.data['jobs'][0]['usedTools']); self.assertEqual(Store.saves, 1)
        self.assertEqual(b''.join(got), line + b'\n' + line + b'\n')  # passed on untouched

    def test_what_is_carried_on_by_itself(self):
        m = load(); blocked = m.resume_blocked
        self.assertEqual(blocked(dict(toolWatch=True, nativeAccess=['folder', '/x', 'ask', True], toolCalls=[dict(name='zook_read_file', category='read', status='completed')])), '')
        self.assertEqual(blocked(dict(nativeAccess=['folder', '/x', 'ask', False], toolCalls=[])), '')  # no built-in tools at all
        self.assertIn('指令', blocked(dict(toolWatch=True, usedTools=True, nativeAccess=['folder', '/x', 'ask', True])))
        self.assertIn('無法確認', blocked(dict(toolWatch=False, nativeAccess=['folder', '/x', 'ask', True])))
        self.assertIn('無法確認', blocked(dict()))  # older record
        self.assertIn('無法確認', blocked(dict(toolWatch=False, toolsOn=True, nativeAccess=['folder', '/x', 'ask', False])))  # an earlier try could, on a CLI not watched
        self.assertIn('對外', blocked(dict(toolWatch=True, nativeAccess=['folder', '/x', 'ask', True], toolCalls=[dict(name='gmail_send', category='external_write', status='running')])))


if __name__ == '__main__':
    unittest.main()
