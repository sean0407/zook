# -*- coding: utf-8 -*-
import datetime, http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CODEX = '''#!/usr/bin/env python3
import sys, time
s = sys.stdin.read()
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
            state = self.req('GET', '/api/state')[1]
            if check(state): return state
            time.sleep(0.2)
        self.fail('timed out')

    def messages(self, state): return next(b for b in state['bots'] if b['id'] == self.bot['id'])['messages']

    def backdate(self, since, **more):
        """Pretend the schedule was saved earlier, so its time has already come."""
        self.stop(); path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text())
        data['schedules'][0].update(since=since.isoformat(), **more); path.write_text(json.dumps(data)); self.start()

    def test_checks_and_runs_on_request(self):
        base = {'botId': self.bot['id'], 'content': 'morning report', 'time': '10:00', 'repeat': 'daily'}
        for bad in ({'time': '25:00'}, {'repeat': 'hourly'}, {'content': ' '}, {'botId': 'nope'}, {'on': 'yes'}):
            self.assertEqual(self.req('POST', '/api/schedules', dict(base, **bad))[0], 400, bad)
        status, item = self.req('POST', '/api/schedules', base)
        self.assertEqual((status, item['on'], item['catchUp']), (201, True, True))
        self.assertEqual(self.req('POST', '/api/schedules/%s/run' % item['id'], {})[0], 202)
        state = self.wait(lambda s: len(self.messages(s)) == 2 and self.messages(s)[-1].get('status') == 'completed')
        asked, reply = self.messages(state)
        self.assertEqual((asked['content'], asked['author']), ('morning report', '排程')); self.assertTrue(reply['content'].startswith('done'))
        self.assertEqual(state['schedules'][0]['lastStatus'], 'sent')
        self.assertEqual(self.req('PATCH', '/api/schedules/' + item['id'], {'time': '11:30', 'repeat': 'weekdays', 'on': False})[1]['time'], '11:30')
        self.assertEqual(self.req('DELETE', '/api/bots/' + self.bot['id'])[0], 200)  # its schedules go with it
        self.assertEqual(self.req('GET', '/api/state')[1]['schedules'], [])

    def test_runs_when_the_time_comes_once(self):
        now = datetime.datetime.now()
        self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'tick', 'time': now.strftime('%H:%M'), 'repeat': 'daily'})
        time.sleep(1.2)
        self.assertEqual(self.messages(self.req('GET', '/api/state')[1]), [])  # saved after today's time: waits for tomorrow
        self.backdate(now - datetime.timedelta(hours=3))  # as if Zook had been closed over the time
        state = self.wait(lambda s: s['schedules'][0].get('lastStatus') == 'sent' and self.messages(s)[-1].get('status') == 'completed')
        time.sleep(1.2)
        self.assertEqual(len(self.messages(self.req('GET', '/api/state')[1])), 2)  # once, not on every check

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
        # switching a schedule between a Bot and a group keeps exactly one target
        self.assertEqual(self.req('PATCH', '/api/schedules/' + item['id'], {'botId': self.bot['id']})[1]['groupId'], '')
        self.assertEqual(self.req('PATCH', '/api/schedules/' + item['id'], {'groupId': group['id']})[1]['botId'], '')
        self.assertEqual(self.req('DELETE', '/api/groups/' + group['id'])[0], 200)  # its schedules go with it
        self.assertEqual(self.req('GET', '/api/state')[1]['schedules'], [])

    def test_missed_is_skipped_when_catch_up_is_off(self):
        earlier = datetime.datetime.now() - datetime.timedelta(minutes=30)
        self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'tick', 'time': earlier.strftime('%H:%M'), 'repeat': 'daily', 'catchUp': False})
        self.backdate(earlier - datetime.timedelta(hours=1))
        state = self.wait(lambda s: s['schedules'][0].get('lastStatus') == 'missed')
        self.assertEqual(self.messages(state), [])

    def test_waits_while_the_bot_is_busy(self):
        now = datetime.datetime.now()
        self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'after', 'time': now.strftime('%H:%M'), 'repeat': 'daily', 'catchUp': False})
        self.backdate(now - datetime.timedelta(hours=1), since_note='x')
        # the first check may already have sent it; either way a busy Bot must not lose the message
        self.assertIn(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'SLOW'})[0], (202, 409))
        state = self.wait(lambda s: s['schedules'][0].get('lastStatus') == 'sent' and all(m.get('status') != 'running' for m in self.messages(s)), 25)
        self.assertEqual([m['content'] for m in self.messages(state) if m['role'] == 'user' and m.get('author') == '排程'], ['after'])


if __name__ == '__main__': unittest.main()
