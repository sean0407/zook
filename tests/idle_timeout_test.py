# -*- coding: utf-8 -*-
"""A reply is stopped for being silent, not for taking long."""
import importlib.util, json, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
WORKING = '''#!/usr/bin/env python3
import json, sys, time
sys.stdin.read()
for i in range(%d):
    print(json.dumps({'type': 'item.started', 'n': i}), flush=True); time.sleep(0.3)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'finished the long work'}}), flush=True)
'''
SILENT = '#!/usr/bin/env python3\nimport sys, time\nsys.stdin.read(); time.sleep(60)\n'
BIG = '#!/usr/bin/env python3\nimport sys\nsys.stdin.read(); sys.stdout.write("x" * 300000); sys.stderr.write("e" * 300000)\nprint()\nimport json; print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "big ok"}}))\n'


class IdleTimeoutTest(unittest.TestCase):
    def run_one(self, script, quiet, hard, long=False):
        spec = importlib.util.spec_from_file_location('zook_idle_timeout', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cli = root / 'codex'; cli.write_text(script); cli.chmod(0o755)
            store = module.Store(root / 'data'); bot = store.data['bots'][0]
            bot['messages'].append({'id': 'msg', 'role': 'assistant', 'content': '', 'status': 'running', 'createdAt': 'now'})
            job = {'id': 'job', 'botId': bot['id'], 'messageId': 'msg', 'status': 'running'}
            if long: job['long'] = True
            store.data['jobs'].append(job)
            app = module.App(('127.0.0.1', 0), store, root, 'token')
            try:
                with mock.patch.object(module, 'JOB_TIMEOUT', quiet), mock.patch.object(module, 'JOB_HARD_TIMEOUT', hard), mock.patch.object(module, 'LONG_JOB_TIMEOUT', hard), \
                     mock.patch.object(module, 'find_cli', return_value=str(cli)):
                    started = time.time()
                    thread = threading.Thread(target=app.run_job, args=('job', 'test', 'codex', ''))
                    thread.start(); thread.join(timeout=15)
                    self.assertFalse(thread.is_alive(), 'the job was left running')
                return dict(job), time.time() - started
            finally: app.server_close()

    def test_busy_reply_outlives_the_quiet_limit(self):
        job, took = self.run_one(WORKING % 8, quiet=0.8, hard=30)  # works for about 2.4 seconds, never silent for 0.8
        self.assertEqual((job['status'], job.get('content')), ('completed', 'finished the long work'), job.get('error'))
        self.assertGreater(took, 2)

    def test_silent_reply_is_stopped(self):
        job, took = self.run_one(SILENT, quiet=0.6, hard=30)
        self.assertEqual(job['status'], 'failed'); self.assertIn('逾時', job['error']); self.assertIn('沒有任何進展', job['error'])
        self.assertLess(took, 8)

    def test_overall_limit_still_applies(self):
        job, took = self.run_one(WORKING % 40, quiet=5, hard=1.2)  # keeps printing, but only 1.2 seconds are allowed
        self.assertEqual(job['status'], 'failed'); self.assertIn('已超過時間上限', job['error'])
        self.assertLess(took, 9)

    def test_long_task_may_stay_silent(self):
        job, took = self.run_one('#!/usr/bin/env python3\nimport sys, time, json\nsys.stdin.read(); time.sleep(1.5)\nprint(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "quiet but done"}}))\n', quiet=0.4, hard=20, long=True)
        self.assertEqual((job['status'], job.get('content')), ('completed', 'quiet but done'), job.get('error'))

    def test_large_output_on_both_pipes_is_read_whole(self):
        job, _ = self.run_one(BIG, quiet=5, hard=20)  # more than a pipe holds, on both pipes at once
        self.assertEqual((job['status'], job.get('content')), ('completed', 'big ok'), job.get('error'))


if __name__ == '__main__':
    unittest.main()
