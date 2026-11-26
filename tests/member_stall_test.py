# -*- coding: utf-8 -*-
"""#307 成員卡住: a group member silent for MEMBER_STALL is stopped and its backup model redoes its part; one that keeps working is
left alone however long it takes. The 15 minutes are a constant the tests shrink, so nothing waits for real."""
import contextlib, importlib.util, json, os, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
WORKING = '''#!/usr/bin/env python3
import json, sys, time
sys.stdin.read()
for i in range(8):
    print(json.dumps({'type': 'item.started', 'item': {'id': 'r%d' % i, 'type': 'reasoning'}}), flush=True); time.sleep(0.3)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'finished the long work'}}), flush=True)
'''
SILENT = '#!/usr/bin/env python3\nimport sys, time\nsys.stdin.read(); time.sleep(60)\n'
RAN_COMMAND = '''#!/usr/bin/env python3
import json, sys, time
sys.stdin.read()
print(json.dumps({'type': 'item.completed', 'item': {'id': 'c1', 'type': 'command_execution', 'command': 'curl x'}}), flush=True)
time.sleep(60)
'''
CLAUDE = '#!/usr/bin/env python3\nimport json, sys\nsys.stdin.read()\nprint(json.dumps({"type": "result", "result": "backup did it", "is_error": False}))\n'


class MemberStallTest(unittest.TestCase):
    def setUp(self):
        os.environ['ZOOK_NO_INTRO'] = '1'
        spec = importlib.util.spec_from_file_location('zook_member_stall', SERVER)
        self.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)

    def run_member(self, script, backups=(), stall=0.6, group=True, extra=None, patches=()):
        m = self.m
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'codex').write_text(script); (root / 'claude').write_text(CLAUDE)
            for name in ('codex', 'claude'): (root / name).chmod(0o755)
            store = m.Store(root / 'data'); bot = store.data['bots'][0]
            bot.update(name='研究員', provider='codex', fallbacks=list(backups))
            store.data['settings']['fallbacks'] = []
            job = {'id': 'job', 'botId': bot['id'], 'messageId': 'msg', 'status': 'running', 'createdAt': m.NOW()}
            msg = {'id': 'msg', 'role': 'assistant', 'botId': bot['id'], 'content': '', 'status': 'running', 'createdAt': m.NOW()}
            job.update(extra or {})
            if group:
                g = {'id': 'g1', 'name': '專案組', 'botIds': [bot['id']], 'messages': [msg], 'status': 'running'}
                store.data['groups'].append(g); job['groupId'] = 'g1'
            else: bot['messages'].append(msg)
            store.data['jobs'].append(job)
            app = m.App(('127.0.0.1', 0), store, root, 'token')
            calls = []
            def find(p, *a, **k):
                calls.append(p); return str(root / p) if (root / p).exists() else None
            self.hosted = []
            real_popen = m.bg_popen
            def popen(*a, **k):
                proc = real_popen(*a, **k); self.hosted.append(isinstance(proc, m.HostedProc)); return proc
            try:
                with mock.patch.object(m, 'MEMBER_STALL', stall), mock.patch.object(m, 'JOB_TIMEOUT', 30), mock.patch.object(m, 'find_cli', side_effect=find), \
                     mock.patch.object(m, 'bg_popen', side_effect=popen), contextlib.ExitStack() as stack:
                    for target, value in patches: stack.enter_context(mock.patch.object(m, target, value))
                    started = time.time()
                    thread = threading.Thread(target=app.run_job, args=('job', 'test', 'codex', ''))
                    thread.start(); thread.join(timeout=20)
                    self.assertFalse(thread.is_alive(), 'the job was left running')
                notes = [x['content'] for x in (store.find('groups', 'g1') or {}).get('messages', []) if x.get('role') == 'system']
                return dict(store.find('jobs', 'job')), notes, time.time() - started
            finally: app.server_close()

    def test_member_that_keeps_working_is_not_stalled(self):
        job, notes, took = self.run_member(WORKING, backups=['claude'], stall=0.8)
        self.assertEqual((job['status'], job.get('content')), ('completed', 'finished the long work'), job.get('error'))
        self.assertGreater(took, 2); self.assertEqual(notes, [])
        self.assertNotIn('fallback', job)

    def test_silent_member_is_redone_by_its_backup(self):
        job, notes, took = self.run_member(SILENT, backups=['claude'])
        self.assertEqual((job['status'], job.get('content')), ('completed', 'backup did it'), job.get('error'))
        self.assertEqual(job['fallback']['provider'], 'claude')
        self.assertEqual(len(notes), 1, notes)
        self.assertIn('研究員', notes[0]); self.assertIn('沒有任何動作', notes[0]); self.assertIn('Claude', notes[0])
        self.assertLess(took, 10)

    def test_silent_member_without_backup_is_handed_over(self):
        job, notes, _ = self.run_member(SILENT, backups=[])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(len(notes), 1, notes)
        self.assertIn('研究員', notes[0]); self.assertIn('沒有可用的備用模型', notes[0])

    def test_member_that_ran_a_command_is_not_redone(self):
        job, notes, _ = self.run_member(RAN_COMMAND, backups=['claude'])
        self.assertEqual(job['status'], 'failed')
        self.assertNotIn('fallback', job)
        self.assertEqual(len(notes), 1, notes)
        self.assertIn('研究員', notes[0]); self.assertIn('你決定', notes[0]); self.assertNotIn('改用', notes[0])

    def test_stall_limit_only_for_group_replies(self):
        m = self.m
        self.assertEqual(m.MEMBER_STALL, 15 * 60)
        self.assertEqual(m.reply_quiet('codex', {'groupId': 'g'}), m.MEMBER_STALL)
        self.assertEqual(m.reply_quiet('antigravity', {'groupId': 'g'}), m.MEMBER_STALL)  # 15 minutes for every CLI in a group
        self.assertEqual(m.reply_quiet('codex', {}), m.JOB_TIMEOUT)
        self.assertEqual(m.reply_quiet('codex', {'groupId': 'g', 'long': True}), m.LONG_JOB_TIMEOUT)
        self.assertGreater(m.runner_quiet('codex', {'groupId': 'g'}), m.MEMBER_STALL)  # the runner's own stop comes after Zook's

    def test_progress_says_what_it_is_doing_now(self):
        m = self.m
        m.progress_start('p1')
        feed = m.progress_feeder('codex', 'p1')
        lines = [{'type': 'item.completed', 'item': {'id': 'f1', 'type': 'file_change', 'changes': [{'path': '/tmp/報告.md'}]}},
                 {'type': 'item.started', 'item': {'id': 'c2', 'type': 'command_execution', 'command': 'ls'}}]
        feed(''.join(json.dumps(x) + '\n' for x in lines).encode())
        p = m.progress_view({'id': 'p1', 'status': 'running'})['progress']
        self.assertEqual(p['now'], '執行指令')
        self.assertEqual(p['files'], [{'w': 'write', 'name': '報告.md'}])
        feed((json.dumps({'type': 'item.completed', 'item': {'id': 'c2', 'type': 'command_execution'}}) + '\n').encode())
        p = m.progress_view({'id': 'p1', 'status': 'running'})['progress']
        self.assertEqual(p.get('now', ''), ''); self.assertEqual(p['command'], 1)
        m.progress_end('p1')

    def test_antigravity_command_still_running_is_not_redone(self):
        # A command Antigravity started and never finished may have reached outside: the part is not done again on another model.
        m = self.m
        m.progress_start('a1')
        feed = m.progress_feeder('antigravity', 'a1')
        step = {'event': 'step_update', 'step_update': {'step_type': 'tool', 'state': 'RUNNING', 'step_index': 3, 'tool_name': 'run_command', 'tool_info': {'parameters': {}}}}
        feed((json.dumps(step) + '\n').encode())
        self.assertEqual(m.progress_view({'id': 'a1', 'status': 'running'})['progress']['now'], '執行指令')
        job = {'id': 'a1', 'toolCalls': []}
        self.assertTrue(m.stall_mark(None, job, 'antigravity', True, 900))
        self.assertTrue(job['stallNow']['acted'])
        step['step_update']['state'] = 'DONE'; feed((json.dumps(step) + '\n').encode())
        p = m.progress_view({'id': 'a1', 'status': 'running'})['progress']
        self.assertEqual((p.get('now', ''), p['command']), ('', 1))
        m.progress_end('a1')

    def test_reading_only_member_is_redone(self):
        m = self.m
        m.progress_start('a2')
        m.progress_feeder('codex', 'a2')((json.dumps({'type': 'item.completed', 'item': {'id': 'f', 'type': 'file_change', 'changes': [{'path': '/tmp/a.md'}]}}) + '\n').encode())
        job = {'id': 'a2', 'toolCalls': []}
        self.assertFalse(m.stall_mark(None, job, 'codex', True, 900))  # a file it wrote is redone, not sent anywhere
        self.assertFalse(m.stall_mark(None, job, 'gemini', False, 900))
        m.progress_end('a2')
        self.assertTrue(m.stall_mark(None, {'id': 'a3'}, 'gemini', True, 900))  # its steps cannot be read: careful

    # A group reply under a runner (background.py) is not what Zook does today (bg_fits), but if it ever were, a stall must still
    # be stopped through the runner and handed on correctly.
    def test_stall_under_a_runner_is_stopped_and_handed_on(self):
        job, notes, took = self.run_member(SILENT, backups=['claude'], patches=[('bg_fits', lambda j: True)])
        self.assertEqual(self.hosted, [True, True], 'both tries ran under a runner')
        self.assertEqual((job['status'], job.get('content')), ('completed', 'backup did it'), job.get('error'))
        self.assertEqual(len(notes), 1, notes); self.assertIn('改用 Claude', notes[0])
        self.assertLess(took, 15)

    def test_backup_runner_that_never_starts_is_not_said_to_take_over(self):
        m, seen = self.m, []
        real = m.bg_ready
        def ready(app, proc):
            seen.append(1); real(app, proc)
            if len(seen) == 2: raise RuntimeError('沒有啟動')  # as bg_ready does when the backup's runner never reports its CLI
        job, notes, _ = self.run_member(SILENT, backups=['claude'], patches=[('bg_fits', lambda j: True), ('bg_ready', ready)])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(len(notes), 1, notes); self.assertNotIn('改用', notes[0]); self.assertIn('沒能接手', notes[0])

    def test_reply_taken_up_after_a_restart_is_not_redone(self):
        job, notes, _ = self.run_member(SILENT, backups=['claude'], extra={'reattach': True, 'ran': ['codex', '', '']})
        self.assertEqual(job['status'], 'failed'); self.assertNotIn('fallback', job)
        self.assertEqual(len(notes), 1, notes); self.assertIn('重新開啟', notes[0]); self.assertNotIn('改用', notes[0])
        self.assertNotIn('stallTakenUp', job)

    def test_switch_is_not_said_for_a_stopped_reply(self):
        m = self.m
        with tempfile.TemporaryDirectory() as directory:
            store = m.Store(Path(directory) / 'data')
            store.data['groups'].append({'id': 'g', 'name': 'G', 'botIds': [], 'messages': []})
            job = {'id': 'j', 'groupId': 'g', 'botId': 'x', 'status': 'cancelled', 'stallSwitch': {'minutes': 15, 'acted': False}}
            m.stall_switch(store, job, 'claude', ''); m.stall_finish(store, job)
            self.assertEqual(store.find('groups', 'g')['messages'], [])


if __name__ == '__main__':
    unittest.main()
