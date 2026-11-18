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

    def test_redoing_a_plan_is_still_a_plan(self):
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'bypass'})[0], 200)
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '整理桌面', 'plan': True, 'effort': 'deep'})
        self.wait_job(sent['jobId'])
        for body in ({'mode': 'again'}, {'mode': 'edit', 'content': '整理下載資料夾'}):
            status, sent = self.req('POST', '/api/chat/redo', dict(body, botId=self.bot['id']))
            self.assertEqual(status, 202, sent)
            job = self.wait_job(sent['jobId'])
            args = (self.root / 'bin/codex.args').read_text().splitlines()
            self.assertTrue(job['plan']); self.assertEqual(job['effort'], 'deep')
            self.assertIn('read-only', args); self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
            self.assertIn('只提出計畫', (self.root / 'bin/codex.prompt').read_text())

    def test_clis_zook_cannot_hold_to_read_only_refuse_a_plan(self):
        gemini = self.root / 'bin/gemini'; gemini.write_text('#!/bin/sh\necho hi\n'); gemini.chmod(0o755)
        other = self.req('POST', '/api/bots', {'name': 'G', 'provider': 'gemini'})[1]
        self.assertEqual(self.req('POST', '/api/chat', {'botId': other['id'], 'content': 'x', 'plan': True})[0], 400)
        self.assertEqual(next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == other['id'])['messages'], [])


class PlanApprovals(unittest.TestCase):
    def test_zook_tools_that_write_are_gone_while_planning(self):
        import runtime
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); app = server.App(('127.0.0.1', 0), store, d, 't')
            try:
                admin = next(b for b in store.data['bots'] if b.get('isAdmin'))
                names = {t[0]['name'] for t in server.plan_safe(app.app_tools(admin, runtime))}
                self.assertEqual(names, {'zook_list_schedules', 'zook_list_team'})
            finally: app.server_close()

    def test_changes_are_declined_reading_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); app = server.App(('127.0.0.1', 0), store, d, 't')
            try:
                bot = store.data['bots'][0]
                store.data['jobs'].append(dict(id='j', botId=bot['id'], messageId='m', status='running', plan=True, approvals=[], toolCalls=[
                    dict(id='w', name='zook_workspace_write', category='internal', arguments={}), dict(id='r', name='x', category='external_read', arguments={})]))
                self.assertFalse(app.approve('j', 'w', 'zook_workspace_write', {}, 'builtin:workspace'))
                got = []; t = threading.Thread(target=lambda: got.append(app.approve('j', 'r', 'x', {}, 'm'))); t.start()
                job = store.data['jobs'][0]
                for _ in range(200):
                    if len(job['approvals']) == 2: break
                    threading.Event().wait(0.01)
                self.assertEqual([a['status'] for a in job['approvals']], ['denied', 'pending'])  # outside reads ask, as in 謹慎
                job['approvals'][1]['status'] = 'approved'; app.approval_events[job['approvals'][1]['id']].set(); t.join(3)
                self.assertEqual(got, [True])
                self.assertEqual(app.live_permission(bot['id'], 'j'), 'manual')  # nothing runs without asking during a plan
            finally: app.server_close()


if __name__ == '__main__': unittest.main()
