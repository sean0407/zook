# -*- coding: utf-8 -*-
"""Messages sent while a Bot is busy wait in line."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, os, sys, time
s = sys.stdin.read()
here = os.path.dirname(sys.argv[0])
ask = s.strip().splitlines()[-1]
open(os.path.join(here, 'asked.log'), 'a').write(ask + '\\n')
time.sleep(float(open(os.path.join(here, 'delay')).read()))
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '回覆：' + ask[-12:]}}))
'''


class WaitingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755); (self.root / 'bin/delay').write_text('0.8')
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.start()
        self.bot = self.req('POST', '/api/bots', {'name': 'W', 'provider': 'codex'})[1]

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def say(self, text, **more): return self.req('POST', '/api/chat', dict({'botId': self.bot['id'], 'content': text}, **more))
    def me(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])
    def asked(self):
        path = self.root / 'bin/asked.log'
        return [l.replace('使用者：', '') for l in path.read_text().splitlines()] if path.exists() else []

    def settle(self, count, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            me = self.me()
            done = [m for m in me['messages'] if m['role'] == 'assistant' and m.get('status') == 'completed']
            if len(done) >= count and not me.get('queue'): return me
            time.sleep(0.1)
        self.fail('still waiting: %s' % json.dumps(self.me().get('queue'), ensure_ascii=False))

    def test_three_in_a_row_are_answered_in_order(self):
        first = self.say('第一則')
        self.assertEqual((first[0], 'jobId' in first[1]), (202, True))
        second, third = self.say('第二則'), self.say('第三則', long=True)
        self.assertEqual((second[0], second[1]['queued'], third[1]['queued']), (202, True, True))
        waiting = self.me()['queue']
        self.assertEqual([(e['content'], e.get('long')) for e in waiting], [('第二則', None), ('第三則', True)])
        self.assertEqual([m['content'] for m in self.me()['messages'] if m['role'] == 'user'], ['第一則'])  # not in the conversation until sent
        me = self.settle(3)
        self.assertEqual([m['content'] for m in me['messages']], ['第一則', '回覆：第一則', '第二則', '回覆：第二則', '第三則', '回覆：第三則'])
        self.assertEqual(self.asked(), ['第一則', '第二則', '第三則'])  # each exactly once, in order

    def test_cancel_one_and_resend_is_not_doubled(self):
        self.say('甲')
        b = self.say('乙', clientId='msg-queue-0001')[1]; c = self.say('丙')[1]
        self.assertEqual(self.say('乙', clientId='msg-queue-0001')[1], dict(b, duplicate=True))  # sent again by a flaky phone: still one place in line
        self.assertEqual(len(self.me()['queue']), 2)
        self.assertEqual(self.req('DELETE', '/api/bots/%s/queue/%s' % (self.bot['id'], b['queueId']))[0], 200)
        self.assertEqual(self.req('DELETE', '/api/bots/%s/queue/%s' % (self.bot['id'], b['queueId']))[0], 409)
        me = self.settle(2)
        self.assertEqual([m['content'] for m in me['messages'] if m['role'] == 'user'], ['甲', '丙'])
        self.assertEqual(self.req('DELETE', '/api/bots/%s/queue/%s' % (self.bot['id'], c['queueId']))[0], 409)  # already sent

    def test_line_survives_a_restart_and_the_interrupted_reply_goes_first(self):
        # #34: the reply the restart cut off is carried on (in its own message, once), then what was waiting is answered.
        (self.root / 'bin/delay').write_text('30')
        self.req('PATCH', '/api/settings', {'backgroundRuns': False})  # on, the reply is not cut off at all (background_test.py)
        self.say('被中斷的'); self.say('等著的')
        time.sleep(0.5); self.stop()
        (self.root / 'bin/delay').write_text('0.2'); self.start()
        me = self.settle(2)
        self.assertEqual([(m['content'], m.get('status')) for m in me['messages']], [('被中斷的', None), ('回覆：被中斷的', 'completed'), ('等著的', None), ('回覆：等著的', 'completed')])
        self.assertIn('接續 Zook 重啟前中斷的回覆', me['messages'][1].get('note', ''))
        self.assertEqual(self.asked().count('被中斷的'), 2)

    def test_switched_off_refuses_as_before_and_bad_messages_are_refused_at_once(self):
        self.say('忙著')
        self.assertEqual(self.say('   ')[0], 400)
        self.assertEqual(self.say('x', plan='yes')[0], 400)
        for i in range(20): self.assertEqual(self.say('排 %d' % i)[0], 202)
        status, out = self.say('第二十一則')
        self.assertEqual(status, 400); self.assertIn('排隊的訊息已有 20 則', out['error'])
        self.assertEqual(self.req('PATCH', '/api/settings', {'queueWhenBusy': 'x'})[0], 400)
        self.req('PATCH', '/api/settings', {'queueWhenBusy': False})
        self.assertEqual(self.say('關掉之後')[0], 409)

    def test_deleted_conversation_takes_its_line_with_it(self):
        self.say('先有一則'); self.settle(1); self.stop()
        path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text())
        bot = next(b for b in data['bots'] if b['id'] == self.bot['id'])
        bot['chats'].append(dict(id='old-chat', title='舊對話', createdAt='2020-01-01T00:00:00+00:00', updatedAt='2020-01-01T00:00:00+00:00', messages=[dict(id='m0', role='user', content='舊的')]))
        bot['queue'] = [dict(id='q1', chatId='old-chat', content='排在舊對話的', createdAt='now')]
        path.write_text(json.dumps(data)); self.start()
        self.assertEqual(self.req('DELETE', '/api/bots/%s/chats/old-chat' % self.bot['id'])[0], 200)  # before the line starts moving again
        self.assertFalse(self.me().get('queue'))
        time.sleep(3)
        self.assertNotIn('排在舊對話的', self.asked())

    def test_restored_backup_does_not_resend_what_was_waiting(self):
        (self.root / 'bin/delay').write_text('1.2')
        self.say('第一則'); self.say('排隊的')
        made = self.req('POST', '/api/backups', {})[1]['name']  # taken while one message is still in line
        self.settle(2)
        self.assertEqual(self.req('POST', '/api/backups/%s/restore' % made, {})[0], 200)
        self.assertFalse(self.me().get('queue'))
        self.say('新的一則'); time.sleep(3)
        self.assertEqual(self.asked().count('排隊的'), 1)

    def test_no_jumping_the_line_and_a_stuck_entry_does_not_block(self):
        self.say('甲'); self.say('乙')
        # 乙 is waiting. Something makes it impossible to send (its conversation is gone): it must not hold up what comes after.
        self.stop()
        path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text())
        bot = next(b for b in data['bots'] if b['id'] == self.bot['id'])
        bot['queue'] = [dict(id='x1', chatId='no-such-chat', content='對話已不存在', createdAt='now'), dict(id='x2', chatId=bot['chatId'], content='丙', createdAt='now')]
        path.write_text(json.dumps(data)); (self.root / 'bin/delay').write_text('0.3'); self.start()
        end = time.time() + 10
        while time.time() < end and self.me().get('queue'): time.sleep(0.1)
        me = self.me()
        self.assertFalse(me.get('queue')); self.assertNotIn('對話已不存在', self.asked())
        self.assertIn('丙', [m['content'] for m in me['messages'] if m['role'] == 'user'])

    def test_two_sent_at_once_are_answered_in_the_order_sent(self):
        # #142: the second message reaches the Mac before the first. It says which one it follows, so it waits for that one.
        import threading
        out = {}
        late = threading.Thread(target=lambda: out.update(second=self.say('再用一句話說明什麼是月報', clientId='msg-order-0002', after='msg-order-0001')))
        late.start(); time.sleep(0.5)
        first = self.say('用一句話說明什麼是週報', clientId='msg-order-0001'); late.join(10)
        self.assertEqual((first[0], 'jobId' in first[1]), (202, True))
        self.assertEqual((out['second'][0], out['second'][1].get('queued')), (202, True))
        me = self.settle(2)
        self.assertEqual([m['content'] for m in me['messages'] if m['role'] == 'user'], ['用一句話說明什麼是週報', '再用一句話說明什麼是月報'])
        self.assertEqual(self.asked(), ['用一句話說明什麼是週報', '再用一句話說明什麼是月報'])

    def test_a_message_whose_predecessor_never_comes_is_not_held_for_long(self):
        began = time.time()
        sent = self.say('甲', clientId='msg-order-0003', after='msg-never-arrives')
        self.assertEqual((sent[0], 'jobId' in sent[1]), (202, True))
        self.assertLess(time.time() - began, 8)
        began = time.time(); self.say('乙', clientId='msg-order-0004', after='msg-order-0003')  # its predecessor is in: no wait at all
        self.assertLess(time.time() - began, 1.5)


if __name__ == '__main__':
    unittest.main()
