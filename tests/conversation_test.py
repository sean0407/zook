# -*- coding: utf-8 -*-
"""B1: several conversations per Bot."""
import datetime, http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CODEX = '''#!/usr/bin/env python3
import sys
s = sys.stdin.read()
print('seen: ' + ' | '.join(l for l in s.splitlines() if l.startswith(('user:', 'assistant:', '使用者：'))))
'''


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
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

    def state_bot(self):
        return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])

    def say(self, text):
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})
        self.assertEqual(status, 202, sent)
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            if job['status'] != 'running': return job
            time.sleep(0.2)
        self.fail('no reply')

    def test_new_switch_rename_delete(self):
        bot = self.state_bot()
        self.assertEqual(len(bot['chats']), 1); self.assertEqual(bot['chatId'], bot['chats'][0]['id'])
        self.say('第一個對話的問題')
        first = self.state_bot()['chatId']
        self.assertEqual(self.state_bot()['chats'][0]['title'], '第一個對話的問題')  # titled by its first message
        status, chat = self.req('POST', '/api/bots/%s/chats' % self.bot['id'], {})
        self.assertEqual(status, 201)
        bot = self.state_bot()
        self.assertEqual((bot['chatId'], bot['messages']), (chat['id'], []))
        job = self.say('第二個對話')
        self.assertNotIn('第一個對話', job['content'])  # a new conversation starts blank
        # an empty conversation is reused instead of piling up
        self.req('POST', '/api/bots/%s/chats' % self.bot['id'], {}); self.req('POST', '/api/bots/%s/chats' % self.bot['id'], {})
        self.assertEqual(len(self.state_bot()['chats']), 3)
        self.assertEqual(self.req('POST', '/api/bots/%s/chats/%s/open' % (self.bot['id'], first), {})[0], 200)
        bot = self.state_bot()
        self.assertEqual([m['content'] for m in bot['messages'] if m['role'] == 'user'], ['第一個對話的問題'])
        other = next(c for c in bot['chats'] if c['id'] == chat['id'])
        self.assertEqual([m['content'] for m in other['messages'] if m['role'] == 'user'], ['第二個對話'])  # kept in the list
        self.assertNotIn('messages', next(c for c in bot['chats'] if c['id'] == first))  # the open one lives in bot.messages
        self.assertEqual(self.req('PATCH', '/api/bots/%s/chats/%s' % (self.bot['id'], first), {'title': '改過的名字'})[1]['title'], '改過的名字')
        self.assertEqual(self.req('PATCH', '/api/bots/%s/chats/%s' % (self.bot['id'], first), {'title': ''})[0], 400)
        self.assertEqual(self.req('DELETE', '/api/bots/%s/chats/%s' % (self.bot['id'], first))[0], 200)
        bot = self.state_bot()
        self.assertNotIn(first, [c['id'] for c in bot['chats']]); self.assertNotEqual(bot['chatId'], first)
        for chat in list(bot['chats']): self.req('DELETE', '/api/bots/%s/chats/%s' % (self.bot['id'], chat['id']))
        bot = self.state_bot()
        self.assertEqual((len(bot['chats']), bot['messages']), (1, []))  # a Bot always has one conversation

    def test_reply_lands_in_its_own_conversation_after_switching(self):
        self.say('hello')
        first = self.state_bot()['chatId']
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'second question'})
        self.req('POST', '/api/bots/%s/chats' % self.bot['id'], {})  # switch away while it replies
        end = time.time() + 15
        while self.req('GET', '/api/jobs/' + sent['jobId'])[1]['status'] == 'running' and time.time() < end: time.sleep(0.2)
        bot = self.state_bot()
        self.assertEqual(bot['messages'], [])
        kept = next(c for c in bot['chats'] if c['id'] == first)['messages']
        self.assertEqual([m.get('status') for m in kept if m['role'] == 'assistant'], ['completed', 'completed'])
        self.assertEqual(self.req('GET', '/api/jobs/' + sent['jobId'])[1]['chatId'], first)
        # deleting a conversation that is still replying is refused
        self.req('POST', '/api/bots/%s/chats/%s/open' % (self.bot['id'], first), {})

    def test_schedule_messages_go_to_their_own_conversation(self):
        self.say('working on something')
        mine = self.state_bot()['chatId']
        status, item = self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': 'daily report', 'time': '10:00'})
        self.assertEqual(self.req('POST', '/api/schedules/%s/run' % item['id'], {})[0], 202)
        end = time.time() + 15
        while time.time() < end:
            bot = self.state_bot(); sched = next((c for c in bot['chats'] if c.get('kind') == 'schedule'), None)
            if sched and sched.get('messages') and sched['messages'][-1].get('status') == 'completed': break
            time.sleep(0.2)
        self.assertEqual(bot['chatId'], mine)  # what you were doing is not interrupted
        self.assertEqual(sched['title'], '排程')
        self.assertEqual(sched['messages'][0]['content'], 'daily report')
        run = self.req('GET', '/api/state')[1]['schedules'][0]['runs'][-1]
        self.assertEqual((run['chatId'], run['messageId']), (sched['id'], sched['messages'][0]['id']))

    def test_old_data_becomes_the_first_conversation(self):
        self.say('legacy question')
        self.stop()
        path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text())
        for b in data['bots']: b.pop('chats', None); b.pop('chatId', None)
        path.write_text(json.dumps(data)); self.start()
        bot = self.state_bot()
        self.assertEqual(len(bot['chats']), 1)
        self.assertEqual((bot['chatId'], bot['chats'][0]['title']), (bot['chats'][0]['id'], 'legacy question'))
        self.assertEqual(bot['messages'][0]['content'], 'legacy question')

    def test_delete_refused_while_replying(self):
        slow = self.root / 'bin/codex'; slow.write_text("#!/usr/bin/env python3\nimport sys,time\nsys.stdin.read(); time.sleep(3); print('ok')\n")
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'x'})
        chat = self.state_bot()['chatId']
        self.assertEqual(self.req('DELETE', '/api/bots/%s/chats/%s' % (self.bot['id'], chat))[0], 409)


if __name__ == '__main__': unittest.main()
