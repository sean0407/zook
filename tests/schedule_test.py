# -*- coding: utf-8 -*-
import datetime, http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest, unittest.mock
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CODEX = '''#!/usr/bin/env python3
import os, sys, time
s = sys.stdin.read()
open(os.path.join(os.path.dirname(sys.argv[0]), 'codex.args'), 'w').write(' '.join(sys.argv[1:]) + ' ZOOK_TOOL_WAIT=' + os.environ.get('ZOOK_TOOL_WAIT', ''))
if 'SLOW' in s: time.sleep(4)
print('done: ' + s.strip().splitlines()[-1][-40:])
'''


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_schedules', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class ScheduleTimes(unittest.TestCase):
    def test_last_due(self):
        due = load().schedule_last_due
        wed = datetime.datetime(2026, 11, 18, 10, 0, 30)  # a Wednesday
        self.assertEqual(due(dict(time='10:00', repeat='daily'), wed), datetime.datetime(2026, 11, 18, 10, 0))
        self.assertEqual(due(dict(time='10:01', repeat='daily'), wed), datetime.datetime(2026, 11, 17, 10, 1))
        self.assertEqual(due(dict(time='09:00', repeat='mon'), wed), datetime.datetime(2026, 11, 16, 9, 0))
        self.assertEqual(due(dict(time='09:00', repeat='weekdays'), datetime.datetime(2026, 11, 22, 12, 0)), datetime.datetime(2026, 11, 20, 9, 0))
        # every hour at the chosen minute; the hour part is ignored
        self.assertEqual(due(dict(time='00:15', repeat='hourly'), wed), datetime.datetime(2026, 11, 18, 9, 15))
        self.assertEqual(due(dict(time='23:00', repeat='hourly'), wed), datetime.datetime(2026, 11, 18, 10, 0))
        # once: only on that date
        self.assertEqual(due(dict(time='09:30', repeat='once', date='2026-11-18'), wed), datetime.datetime(2026, 11, 18, 9, 30))
        self.assertIsNone(due(dict(time='10:30', repeat='once', date='2026-11-18'), wed))
        # monthly: a day the month lacks runs on its last day
        self.assertEqual(due(dict(time='10:00', repeat='monthly', day=18), wed), datetime.datetime(2026, 11, 18, 10, 0))
        self.assertEqual(due(dict(time='11:00', repeat='monthly', day=18), wed), datetime.datetime(2026, 10, 18, 11, 0))
        self.assertEqual(due(dict(time='08:00', repeat='monthly', day=31), wed), datetime.datetime(2026, 10, 31, 8, 0))
        self.assertEqual(due(dict(time='08:00', repeat='monthly', day=31), datetime.datetime(2027, 3, 1)), datetime.datetime(2027, 2, 28, 8, 0))
        self.assertEqual(due(dict(time='08:00', repeat='monthly', day=30), datetime.datetime(2026, 11, 30, 9)), datetime.datetime(2026, 11, 30, 8, 0))


class ScheduleHistory(unittest.TestCase):
    def test_keeps_the_last_twenty(self):
        add = load().schedule_add_run; item = {}
        for i in range(25): add(item, dict(status='done', reason=str(i)))
        self.assertEqual([r['reason'] for r in item['runs']], [str(i) for i in range(5, 25)])
        self.assertTrue(all(r['id'] and r['at'] for r in item['runs']))


class ScheduleNotices(unittest.TestCase):
    def test_first_sentence(self):
        first = load().first_sentence
        self.assertEqual(first('## 今日結論\n\n**大盤偏多**。理由如下：一、二。'), '今日結論')
        self.assertEqual(first('大盤偏多。理由如下'), '大盤偏多。')
        self.assertEqual(first('x' * 300), 'x' * 119 + '…')
        self.assertEqual(first(''), '')

    def test_asks_by_notification_when_a_scheduled_run_needs_approval(self):
        import threading
        server = load()
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); app = server.App(('127.0.0.1', 0), store, d, 't')
            try:
                bot = store.data['bots'][0]
                store.data['jobs'] += [dict(id='j', botId=bot['id'], messageId='m', status='running', toolCalls=[dict(id='c', name='zook_create_bot', category='danger', arguments={'name': 'X'})], approvals=[]),
                                       dict(id='k', botId=bot['id'], messageId='n', status='running', toolCalls=[dict(id='c', name='zook_create_bot', category='danger', arguments={'name': 'Y'})], approvals=[])]
                store.data['schedules'].append(dict(id='s', botId=bot['id'], content='x', time='10:00', repeat='daily', on=True, runs=[dict(id='r', kind='bot', targetId=bot['id'], jobId='j', messageId='q', status='running')]))
                for job in ('j', 'k'): threading.Thread(target=app.approve, args=(job, 'c', 'zook_create_bot', {}, 'builtin:zook'), daemon=True).start()
                for _ in range(100):
                    if all(j['approvals'] for j in store.data['jobs']): break
                    threading.Event().wait(0.02)
                items = app.notices_after(0)['items']
                self.assertEqual([(n['title'], n['body'], n['messageId']) for n in items], [(bot['name'], '需要你核准：新增 Bot「X」', 'q')])  # only the scheduled run asks this way
                for job in store.data['jobs']: job['status'] = 'cancelled'; app.expire_job(job['id'])
            finally: app.server_close()

    def test_unattended_approval_gives_up_after_the_wait(self):
        server = load()
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.dict(os.environ, ZOOK_SCHEDULE_APPROVAL_WAIT='0.3'):
            store = server.Store(Path(d)); app = server.App(('127.0.0.1', 0), store, d, 't')
            try:
                bot = store.data['bots'][0]
                store.data['jobs'].append(dict(id='j', botId=bot['id'], messageId='m', status='running', toolCalls=[dict(id='c', name='zook_create_bot', category='danger', arguments={})], approvals=[]))
                run = dict(id='r', kind='bot', targetId=bot['id'], jobId='j', messageId='q', status='running')
                store.data['schedules'].append(dict(id='s', botId=bot['id'], content='x', time='10:00', repeat='daily', on=True, runs=[run]))
                started = time.time()
                self.assertFalse(app.approve('j', 'c', 'zook_create_bot', {}, 'builtin:zook'))
                self.assertLess(time.time() - started, 5)
                self.assertEqual(store.data['jobs'][0]['approvals'][0]['status'], 'expired')
                store.data['jobs'][0].update(status='completed', content='沒有核准，所以沒做。')
                with store.lock: app.settle_schedule_runs()
                self.assertEqual((run['status'], run['reason']), ('done', '有動作等你核准超過 24 小時，視為拒絕。'))
            finally: app.server_close()

    def test_mail_card_names_the_recipient_and_subject(self):
        say = load().describe_send
        self.assertEqual(say('send_email', {'to': 'amy@example.com', 'subject': '週報', 'body': '...'}), '寄信給 amy@example.com，主旨「週報」，內容開頭：...')
        self.assertEqual(say('gmail_send', {'to': ['amy@example.com'], 'subject': '嗨'}), '寄信給 amy@example.com，主旨「嗨」')
        many = say('gmail_send', {'to': ['p%d@example.com' % i for i in range(12)], 'cc': ['boss@example.com'], 'bcc': ['x@evil.example'], 'subject': 's'})
        for text in ('p9@example.com', '以及另外 2 位', '副本 boss@example.com', '密件副本 x@evil.example'): self.assertIn(text, many)
        changed = load().describe_write('calendar_update', {'event_id': 'e1', 'attendees': ['new@example.com'], 'description': '改地點'})
        for text in ('編號 e1', '與會者改成 new@example.com', '說明 改成「改地點」'): self.assertIn(text, changed)
        self.assertIn('編號 f1', load().describe_write('drive_update', {'file_id': 'f1', 'content': 'abc'}))
        self.assertIn('建立行程「站會」', load().describe_write('calendar_create', {'title': '站會', 'start': '2026-11-19T09:00:00+08:00', 'end': '2026-11-19T09:30:00+08:00', 'attendees': ['amy@example.com']}))
        self.assertIn('上傳檔案「計畫.txt」', load().describe_write('drive_upload', {'name': '計畫.txt', 'content': 'abc'}))
        self.assertEqual(say('send_message', {'to': ['a@x.com', 'b@x.com'], 'subject': 'Hi'}), '寄信給 a@x.com、b@x.com，主旨「Hi」')
        self.assertIsNone(say('create_draft', {'to': 'a@x.com'}))


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='0.3', ZOOK_SHELL_ENV='0')
        self.start()
        self.bot = self.req('POST', '/api/bots', {'name': 'Tester', 'provider': 'codex'})[1]

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def wait(self, check, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            state = self.req('GET', '/api/state?full=1')[1]
            if check(state): return state
            time.sleep(0.2)
        self.fail('timed out')

    def messages(self, state):
        """The Bot's open conversation followed by the one schedules write into."""
        bot = next(b for b in state['bots'] if b['id'] == self.bot['id'])
        return bot['messages'] + [m for c in bot.get('chats') or [] if c.get('kind') == 'schedule' and c['id'] != bot.get('chatId') for m in c.get('messages') or []]

    def backdate(self, since, **more):
        """Pretend the schedule was saved earlier, so its time has already come."""
        self.stop(); path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text())
        data['schedules'][0].update(since=since.isoformat(), **more); path.write_text(json.dumps(data)); self.start()

    def test_checks_and_runs_on_request(self):
        base = {'botId': self.bot['id'], 'content': 'morning report', 'time': '10:00', 'repeat': 'daily'}
        for bad in ({'time': '25:00'}, {'repeat': 'yearly'}, {'content': ' '}, {'botId': 'nope'}, {'on': 'yes'},
                    {'repeat': 'once'}, {'repeat': 'once', 'date': '2020-01-01'}, {'repeat': 'once', 'date': '2026-02-30'},
                    {'repeat': 'monthly'}, {'repeat': 'monthly', 'day': 32}, {'repeat': 'monthly', 'day': '5'}):
            self.assertEqual(self.req('POST', '/api/schedules', dict(base, **bad))[0], 400, bad)
        status, item = self.req('POST', '/api/schedules', base)
        self.assertEqual((status, item['on'], item['catchUp']), (201, True, True))
        self.assertEqual(self.req('POST', '/api/schedules/%s/run' % item['id'], {})[0], 202)
        state = self.wait(lambda s: len(self.messages(s)) == 2 and self.messages(s)[-1].get('status') == 'completed')
        asked, reply = self.messages(state)
        self.assertEqual((asked['content'], asked['author']), ('morning report', '排程')); self.assertTrue(reply['content'].startswith('done'))
        self.assertEqual(state['schedules'][0]['lastStatus'], 'sent')
        # the run history settles once the reply is in, and points at the message the schedule sent
        state = self.wait(lambda s: s['schedules'][0]['runs'][-1]['status'] == 'done')
        run = state['schedules'][0]['runs'][-1]
        self.assertEqual((run['kind'], run['targetId'], run['messageId']), ('bot', self.bot['id'], asked['id']))
        self.assertTrue(run['summary'].startswith('done'))
        notes = self.req('GET', '/api/notifications?after=0')[1]
        self.assertEqual([(n['title'], n['kind'], n['targetId'], n['messageId']) for n in notes['items']], [('Tester', 'bot', self.bot['id'], asked['id'])])
        self.assertTrue(notes['items'][0]['body'].startswith('done'))
        self.assertEqual(self.req('GET', '/api/notifications?after=%d' % notes['seq'])[1]['items'], [])
        self.assertEqual(self.req('PATCH', '/api/settings', {'scheduleNotify': False})[0], 200)
        self.assertEqual(self.req('POST', '/api/schedules/%s/run' % item['id'], {})[0], 202)
        self.wait(lambda s: s['schedules'][0]['runs'][-1]['status'] == 'done')
        self.assertEqual(self.req('GET', '/api/notifications?after=%d' % notes['seq'])[1]['items'], [])
        self.assertEqual(self.req('PATCH', '/api/schedules/' + item['id'], {'time': '11:30', 'repeat': 'weekdays', 'on': False})[1]['time'], '11:30')
        self.assertEqual(len(self.req('GET', '/api/state?full=1')[1]['schedules'][0]['runs']), 2)  # editing keeps the history
        self.assertEqual(self.req('DELETE', '/api/bots/' + self.bot['id'])[0], 200)  # its schedules go with it
        self.assertEqual(self.req('GET', '/api/state?full=1')[1]['schedules'], [])

    def test_runs_when_the_time_comes_once(self):
        now = datetime.datetime.now()
        self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'tick', 'time': now.strftime('%H:%M'), 'repeat': 'daily'})
        time.sleep(1.2)
        self.assertEqual(self.messages(self.req('GET', '/api/state?full=1')[1]), [])  # saved after today's time: waits for tomorrow
        self.backdate(now - datetime.timedelta(hours=3))  # as if Zook had been closed over the time
        state = self.wait(lambda s: s['schedules'][0].get('lastStatus') == 'sent' and self.messages(s)[-1].get('status') == 'completed')
        time.sleep(1.2)
        self.assertEqual(len(self.messages(self.req('GET', '/api/state?full=1')[1])), 2)  # once, not on every check

    def test_group_schedule(self):
        other = self.req('POST', '/api/bots', {'name': 'Second', 'provider': 'codex'})[1]
        status, group = self.req('POST', '/api/groups', {'name': 'Team', 'botIds': [self.bot['id'], other['id']]})
        self.assertEqual(status, 201)
        self.assertEqual(self.req('POST', '/api/schedules', {'groupId': 'nope', 'content': 'x', 'time': '10:00'})[0], 400)
        status, item = self.req('POST', '/api/schedules', {'groupId': group['id'], 'content': 'discuss the market', 'time': '10:00', 'repeat': 'daily'})
        self.assertEqual((status, item['groupId'], item.get('botId')), (201, group['id'], ''))
        self.assertEqual(self.req('POST', '/api/schedules/%s/run' % item['id'], {})[0], 202)
        self.assertEqual(self.req('POST', '/api/schedules/%s/run' % item['id'], {})[0], 409)  # the group is still discussing
        g = lambda s: next(x for x in s['groups'] if x['id'] == group['id'])
        state = self.wait(lambda s: g(s)['status'] == 'idle' and sum(m['role'] == 'assistant' for m in g(s)['messages']) == 2)
        first = g(state)['messages'][0]
        self.assertEqual((first['content'], first['author']), ('discuss the market', '排程'))
        self.assertTrue(all(m['content'].startswith('done') for m in g(state)['messages'] if m['role'] == 'assistant'))
        self.assertEqual(self.messages(state), [])  # nothing lands in the Bot's own conversation
        state = self.wait(lambda s: s['schedules'][0]['runs'][-1]['status'] == 'done')
        run = state['schedules'][0]['runs'][-1]
        self.assertEqual((run['kind'], run['targetId'], run['messageId']), ('group', group['id'], first['id']))
        # switching a schedule between a Bot and a group keeps exactly one target
        self.assertEqual(self.req('PATCH', '/api/schedules/' + item['id'], {'botId': self.bot['id']})[1]['groupId'], '')
        self.assertEqual(self.req('PATCH', '/api/schedules/' + item['id'], {'groupId': group['id']})[1]['botId'], '')
        self.assertEqual(self.req('DELETE', '/api/groups/' + group['id'])[0], 200)  # its schedules go with it
        self.assertEqual(self.req('GET', '/api/state?full=1')[1]['schedules'], [])

    def test_once_runs_then_turns_itself_off(self):
        now = datetime.datetime.now(); later = now + datetime.timedelta(days=2)
        status, item = self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'just once', 'repeat': 'once',
                                                           'date': later.strftime('%Y-%m-%d'), 'time': '10:00'})
        self.assertEqual((status, item['date']), (201, later.strftime('%Y-%m-%d')))
        hour_ago = now - datetime.timedelta(hours=1)
        self.backdate(now - datetime.timedelta(hours=2), date=hour_ago.strftime('%Y-%m-%d'), time=hour_ago.strftime('%H:%M'))
        state = self.wait(lambda s: s['schedules'][0].get('lastStatus') == 'sent')
        self.assertEqual((state['schedules'][0]['on'], state['schedules'][0]['done']), (False, True))
        time.sleep(1)
        self.assertEqual(len([m for m in self.messages(self.req('GET', '/api/state?full=1')[1]) if m['role'] == 'user']), 1)
        # a monthly schedule keeps its day
        later = now + datetime.timedelta(days=40)
        status, item = self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'x', 'repeat': 'once', 'date': '%d-%d-%d' % (later.year, later.month, later.day), 'time': '10:00'})
        self.assertEqual(item['date'], later.strftime('%Y-%m-%d'))  # stored zero-padded
        status, item = self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'rent', 'repeat': 'monthly', 'day': 31, 'time': '09:00'})
        self.assertEqual((status, item['day']), (201, 31))

    def test_scheduled_runs_wait_longer_for_approval(self):
        args = lambda: (self.root / 'bin/codex.args').read_text()
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'hi'})[0], 202)
        self.wait(lambda s: self.messages(s)[-1].get('status') == 'completed')
        self.assertIn('mcp_servers.zook.tool_timeout_sec=660', args()); self.assertIn('ZOOK_TOOL_WAIT=660', args())
        status, item = self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'x', 'time': '10:00'})
        self.assertEqual(self.req('POST', '/api/schedules/%s/run' % item['id'], {})[0], 202)
        self.wait(lambda s: self.messages(s)[-1].get('status') == 'completed')
        self.assertIn('mcp_servers.zook.tool_timeout_sec=87000', args()); self.assertIn('ZOOK_TOOL_WAIT=87000', args())

    def test_missed_is_skipped_when_catch_up_is_off(self):
        earlier = datetime.datetime.now() - datetime.timedelta(minutes=30)
        self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'tick', 'time': earlier.strftime('%H:%M'), 'repeat': 'daily', 'catchUp': False})
        self.backdate(earlier - datetime.timedelta(hours=1))
        state = self.wait(lambda s: s['schedules'][0].get('lastStatus') == 'missed')
        self.assertEqual(self.messages(state), [])
        self.assertEqual([(r['status'], r['reason']) for r in state['schedules'][0]['runs']], [('missed', '到時間時 Zook 沒有開著。')])
        self.assertEqual([(n['title'], n['body']) for n in self.req('GET', '/api/notifications?after=0')[1]['items']], [('Tester', '錯過：到時間時 Zook 沒有開著。')])

    def test_waits_while_the_bot_is_busy(self):
        now = datetime.datetime.now()
        self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'after', 'time': now.strftime('%H:%M'), 'repeat': 'daily', 'catchUp': False})
        self.backdate(now - datetime.timedelta(hours=1), since_note='x')
        # the first check may already have sent it; either way a busy Bot must not lose the message
        self.assertIn(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'SLOW'})[0], (202, 409))
        state = self.wait(lambda s: s['schedules'][0].get('lastStatus') == 'sent' and all(m.get('status') != 'running' for m in self.messages(s)), 25)
        self.assertEqual([m['content'] for m in self.messages(state) if m['role'] == 'user' and m.get('author') == '排程'], ['after'])


if __name__ == '__main__': unittest.main()
