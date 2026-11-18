# -*- coding: utf-8 -*-
"""B5: plan first."""
import importlib.util, sys, tempfile, threading, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import attachment_test

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_plan', SERVER); server = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(server)


class PlanChat(attachment_test.AttachmentTest):
    test_upload_send_and_read_back = test_limits = test_group_members_all_get_the_file = None

    def test_plan_runs_read_only_even_when_everything_is_allowed(self):
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'bypass'})[0], 200)
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '整理桌面', 'plan': True})
        self.assertEqual(status, 202)
        job = self.wait_job(sent['jobId'])
        args = (self.root / 'bin/codex.args').read_text().splitlines()
        self.assertIn('read-only', args); self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
        self.assertIn('只提出計畫', (self.root / 'bin/codex.prompt').read_text())
        self.assertTrue(job['plan'])
        bot = next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])
        self.assertEqual([m.get('plan') for m in bot['messages']], [True, True])
        # the next message is normal again
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '請照上面的計畫執行。'})
        self.wait_job(sent['jobId'])
        self.assertIn('--dangerously-bypass-approvals-and-sandbox', (self.root / 'bin/codex.args').read_text().splitlines())
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'x', 'plan': 'yes'})[0], 400)


class PlanApprovals(unittest.TestCase):
    def test_changes_are_declined_reading_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); app = server.App(('127.0.0.1', 0), store, d, 't')
            try:
                bot = store.data['bots'][0]
                store.data['jobs'].append(dict(id='j', botId=bot['id'], messageId='m', status='running', plan=True, approvals=[], toolCalls=[
                    dict(id='w', name='zook_workspace_write', category='internal', arguments={}), dict(id='r', name='x', category='external_read', arguments={})]))
                self.assertFalse(app.approve('j', 'w', 'zook_workspace_write', {}, 'builtin:workspace'))
                self.assertTrue(app.approve('j', 'r', 'x', {}, 'm'))
                self.assertEqual([a['status'] for a in store.data['jobs'][0]['approvals']], ['denied', 'approved'])
                self.assertEqual(app.live_permission(bot['id'], 'j'), 'manual')  # nothing runs without asking during a plan
            finally: app.server_close()


if __name__ == '__main__': unittest.main()
