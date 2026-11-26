# -*- coding: utf-8 -*-
"""Queue #243: the phone is told only four things — a reply finished, a reply failed, an action waits for approval,
a question waits for an answer. Everything else (schedule started, Bots held in, backups, usage) stays on the Mac and
in the activity record. Each of the four has its own switch in 設定, all on by default. A phone notification names
the Bot or group in plain words and carries no conversation text, key or path."""
import http.client, importlib.util, json, os, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zook_server_for_phone_notice', ROOT / 'backend/server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
SECRET = 'sk-ant-api03-SECRETSECRETSECRET /Users/sean/private/report.xlsx'


class PhoneNoticeTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {'ZOOK_NO_INTRO': '1'}); env.start(); self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = m.Store(Path(self.temp.name) / 'data')
        self.app = m.App(('127.0.0.1', 0), self.store, self.temp.name, 'local-token')
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.addCleanup(self.app.server_close); self.addCleanup(self.app.shutdown)
        self.bot = self.store.data['bots'][0]; self.bot['name'] = '寫手'

    def phone(self, after=0): return m.notices_for(self.app, after, device=True)['items']
    def mac(self, after=0): return m.notices_for(self.app, after, device=False)['items']

    def job(self, **extra):
        job = dict(id=m.ID(), botId=self.bot['id'], messageId='msg1', status='running', content='', createdAt=m.NOW(), toolCalls=[], approvals=[])
        job.update(extra)
        with self.store.lock: self.store.data['jobs'].append(job)
        return job

    def finish(self, job, status, content='', error=''):
        def fake(app, job_id, *args, **kw):
            with app.store.lock: app.store.find('jobs', job_id).update(status=status, content=content, error=error)
        with mock.patch.object(m.App, '_run_job', fake), mock.patch.object(m.App, 'queue_drain', lambda *a: None):
            self.app.run_job(job['id'], 'p', 'claude', '', None, None)

    def test_mac_only_notices_do_not_reach_the_phone(self):
        with self.store.lock:
            self.app.notify('排程', '排程開始：整理信件', 'bot', self.bot['id'], '', always=True)
            self.app.notify('Bot 已收緊', '「寫手」只限工作資料夾', 'page', 'activity', '', always=True)
            self.app.notify('備份', '已還原備份', 'page', 'settings', '', always=True)
        self.assertEqual(len(self.mac()), 3)
        self.assertEqual(self.phone(), [])

    def test_a_finished_reply_tells_the_phone_in_plain_words_without_its_text(self):
        self.finish(self.job(), 'completed', content=SECRET)
        [item] = self.phone()
        self.assertEqual(item['title'], '寫手'); self.assertIn('回覆完成', item['body'])
        self.assertEqual((item['kind'], item['targetId'], item['messageId']), ('bot', self.bot['id'], 'msg1'))
        for part in ('sk-ant', '/Users', 'report'): self.assertNotIn(part, json.dumps(item, ensure_ascii=False))
        self.assertEqual(self.mac(), [])  # an ordinary reply did not show on the Mac before, and still does not

    def test_a_failed_reply_tells_the_phone_without_the_error_text(self):
        self.finish(self.job(), 'failed', error=SECRET)
        [item] = self.phone()
        self.assertEqual(item['title'], '寫手'); self.assertIn('失敗', item['body'])
        for part in ('sk-ant', '/Users', 'report'): self.assertNotIn(part, json.dumps(item, ensure_ascii=False))

    def test_stopped_group_and_helper_jobs_do_not_notify(self):
        self.finish(self.job(), 'cancelled')
        self.finish(self.job(groupId='g1'), 'completed')  # a group says it once, when the discussion ends
        self.finish(self.job(messageId=''), 'completed')  # internal helpers have no message
        self.assertEqual(self.phone(), [])

    def test_an_approval_tells_the_phone(self):
        job = self.job()
        with mock.patch.object(m, 'bg_await', lambda event, timeout: False):
            self.app.approve(job['id'], 'c1', 'native_command', {'command': 'rm ' + SECRET}, 'native')
        [item] = self.phone()
        self.assertEqual(item['title'], '寫手'); self.assertIn('核准', item['body'])
        for part in ('sk-ant', '/Users', 'rm '): self.assertNotIn(part, json.dumps(item, ensure_ascii=False))

    def test_a_question_tells_the_phone(self):
        job = self.job()
        runtime = mock.Mock(); runtime._schema = lambda name, desc, props, req: dict(name=name)
        with mock.patch.object(m, 'choices_on', lambda store: True), mock.patch.object(m, 'bg_await', lambda event, timeout: False):
            [(schema, ask, _)] = m.question_tools(self.app, job['id'], runtime)
            with self.assertRaises(RuntimeError): ask({'question': '要寄給 ' + SECRET + ' 嗎？', 'options': ['要', '不要']})
        [item] = self.phone()
        self.assertEqual(item['title'], '寫手'); self.assertIn('回答', item['body'])
        for part in ('sk-ant', '/Users', '寄給'): self.assertNotIn(part, json.dumps(item, ensure_ascii=False))

    def test_a_group_discussion_that_ends_tells_the_phone_once(self):
        with self.store.lock:
            other = dict(self.bot, id='b2', name='審稿'); self.store.data['bots'].append(other)
            group = dict(id='g1', name='編輯部', botIds=[self.bot['id'], 'b2'], messages=[], status='running', runId='r1')
            self.store.data['groups'].append(group)
        with mock.patch.object(m.App, 'compact_group', lambda *a: None), mock.patch.object(m.App, '_run_steps', lambda *a: None):
            self.app.run_group('g1', 'r1', [], True, resume=dict(kind='steps', steps=[]))
        [item] = self.phone()
        self.assertEqual((item['title'], item['kind'], item['targetId']), ('編輯部', 'group', 'g1')); self.assertIn('群組', item['body'])

    def test_a_group_discussion_that_breaks_tells_the_phone_it_did_not_finish(self):
        with self.store.lock:
            self.store.data['bots'].append(dict(self.bot, id='b2', name='審稿'))
            self.store.data['groups'].append(dict(id='g1', name='編輯部', botIds=[self.bot['id'], 'b2'], messages=[], status='running', runId='r1'))
        def broken(*a): raise RuntimeError('boom')
        with mock.patch.object(m.App, 'compact_group', lambda *a: None), mock.patch.object(m.App, '_run_steps', broken):
            with self.assertRaises(RuntimeError): self.app.run_group('g1', 'r1', [], True, resume=dict(kind='steps', steps=[]))
        [item] = self.phone()
        self.assertEqual(item['body'], m.PHONE_TEXT['group']['failed'])

    def test_each_kind_has_its_own_switch_all_on_by_default(self):
        self.assertEqual(m.phone_events_on(self.store), dict(done=True, failed=True, approval=True, question=True))
        conn = http.client.HTTPConnection('127.0.0.1', self.app.server_address[1], timeout=5)
        def patch(body):
            conn.request('PATCH', '/api/settings', json.dumps(body), {'Authorization': 'Bearer local-token', 'Content-Type': 'application/json'})
            r = conn.getresponse(); return r.status, json.loads(r.read() or b'{}')
        status, settings = patch({'phoneNotify': {'done': False}})
        self.assertEqual(status, 200); self.assertEqual(settings['phoneNotify'], dict(done=False, failed=True, approval=True, question=True))
        for bad in ({'phoneNotify': {'done': 'no'}}, {'phoneNotify': {'scheduleStart': True}}, {'phoneNotify': []}):
            self.assertEqual(patch(bad)[0], 400, bad)
        self.finish(self.job(), 'completed'); self.finish(self.job(), 'failed')
        self.assertEqual([i['body'] for i in self.phone()], [m.PHONE_TEXT['bot']['failed']])  # 回覆完成 is off; 失敗 still comes

    def test_the_mac_window_endpoint_keeps_only_mac_notices(self):
        with self.store.lock: self.app.notify('排程', '排程完成', 'bot', self.bot['id'], '', always=True)
        self.finish(self.job(), 'completed')
        conn = http.client.HTTPConnection('127.0.0.1', self.app.server_address[1], timeout=5)
        conn.request('GET', '/api/notifications?after=0', headers={'Authorization': 'Bearer local-token'})
        body = json.loads(conn.getresponse().read())
        self.assertEqual([i['body'] for i in body['items']], ['排程完成']); self.assertEqual(body['seq'], 2)


if __name__ == '__main__':
    unittest.main()
