# -*- coding: utf-8 -*-
"""A message is taken in at once (#289): while Zook's data is busy (another reply's CLI starting holds it), the window still hears
"收下了" within a moment, and the order, the line, a message sent twice and a refusal all come out as before."""
import http.client, importlib.util, json, os, sys, tempfile, threading, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, os, sys, time
s = sys.stdin.read()
here = os.path.dirname(sys.argv[0])
ask = s.strip().splitlines()[-1]
open(os.path.join(here, 'asked.log'), 'a').write(ask + '\\n')
time.sleep(0.3)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '回覆：' + ask[-12:]}}))
'''


class FastSend(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir(); (self.root / 'secrets').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        self.saved = dict(os.environ)
        os.environ.update(PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        spec = importlib.util.spec_from_file_location('zook_fast_send', SERVER)
        self.m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(self.m)
        self.app = self.m.App(('127.0.0.1', 0), self.m.Store(self.root / 'data'), self.root / 'assets', 'tok')
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.bot = self.req('POST', '/api/bots', {'name': 'F', 'provider': 'codex'})[1]

    def tearDown(self):
        self.app.shutdown(); self.app.server_close()
        os.environ.clear(); os.environ.update(self.saved); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.app.server_address[1], timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer tok'})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def say(self, text, **more):
        began = time.time(); out = self.req('POST', '/api/chat', dict({'botId': self.bot['id'], 'content': text}, **more))
        return out + (time.time() - began,)

    def busy(self, seconds):
        """Holds Zook's data the way a reply starting its CLI does, from now for this long."""
        held = threading.Event()
        def hold():
            with self.app.store.lock: held.set(); time.sleep(seconds)
        threading.Thread(target=hold, daemon=True).start(); held.wait(5)

    def me(self):
        with self.app.store.lock: return json.loads(json.dumps(self.app.store.find('bots', self.bot['id'])))

    def asked(self):
        path = self.root / 'bin/asked.log'
        return [l.replace('使用者：', '') for l in path.read_text().splitlines()] if path.exists() else []

    def settle(self, count, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            me = self.me(); done = [m for m in me['messages'] if m['role'] == 'assistant' and m.get('status') in ('completed', 'failed')]
            if len(done) >= count and not me.get('queue'): return me
            time.sleep(0.1)
        self.fail('not settled: %s' % json.dumps(self.me()['messages'], ensure_ascii=False))

    def test_taken_at_once_while_zook_is_busy(self):
        self.busy(3)
        status, out, took = self.say('你好', clientId='fast-send-0001')
        self.assertEqual((status, out), (202, {'accepted': True}))
        self.assertLess(took, 1.5)  # before: 3 seconds, as long as the other work held the data
        me = self.settle(1)
        self.assertEqual([(m['role'], m['content']) for m in me['messages']], [('user', '你好'), ('assistant', '回覆：你好')])
        status, again, _ = self.say('你好', clientId='fast-send-0001')  # its answer was lost: sent again, the same reply comes back
        self.assertEqual((status, again.get('duplicate'), 'jobId' in again), (202, True, True))
        self.assertEqual(self.asked(), ['你好'])

    def test_sent_twice_while_it_is_being_taken_in_is_answered_once(self):
        self.busy(2)
        first, second = self.say('只要一次', clientId='fast-send-0002'), self.say('只要一次', clientId='fast-send-0002')
        self.assertEqual((first[0], second[0]), (202, 202))
        self.settle(1); time.sleep(0.5)
        self.assertEqual(self.asked(), ['只要一次'])

    def test_order_and_line_are_kept(self):
        self.busy(2)
        a = self.say('第一則', clientId='fast-send-000a')
        b = self.say('第二則', clientId='fast-send-000b', after='fast-send-000a')
        c = self.say('第三則', clientId='fast-send-000c', after='fast-send-000b')
        self.assertTrue(all(x[0] == 202 and x[2] < 1.5 for x in (a, b, c)), (a, b, c))
        me = self.settle(3)
        self.assertEqual([m['content'] for m in me['messages'] if m['role'] == 'user'], ['第一則', '第二則', '第三則'])
        self.assertEqual(self.asked(), ['第一則', '第二則', '第三則'])

    def test_quick_answers_are_as_before(self):
        status, out, took = self.say('馬上', clientId='fast-send-0003')
        self.assertEqual(status, 202); self.assertIn('jobId', out); self.assertLess(took, 1.5)  # nothing in the way: the reply's id, as before
        status, out, _ = self.say('')
        self.assertEqual((status, out.get('error')), (400, '訊息內容無效。'))  # refused at once, as before
        self.assertEqual(self.req('POST', '/api/chat', {'botId': 'nobody', 'content': 'x'})[0], 404)
        self.settle(1)

    def test_refused_after_the_answer_is_said_in_the_conversation(self):
        self.busy(2)
        status, out, _ = self.say('用奇怪的思考強度', clientId='fast-send-0004', effort='bogus')
        self.assertEqual((status, out), (202, {'accepted': True}))
        me = self.settle(1)
        self.assertEqual([(m['role'], m['content'], m.get('status')) for m in me['messages']], [('user', '用奇怪的思考強度', None), ('assistant', '', 'failed')])
        self.assertEqual(me['messages'][1]['note'], '這則訊息沒有送出：思考強度無效。')
        self.assertEqual(self.asked(), [])

    def test_a_refusal_stays_before_the_message_sent_after_it(self):
        self.busy(2)
        self.say('設定錯的那則', clientId='fast-send-0005', effort='bogus')
        self.say('下一則請回答', clientId='fast-send-0006', after='fast-send-0005')
        me = self.settle(2)
        self.assertEqual([(m['role'], m['content'], m.get('status')) for m in me['messages']],
                         [('user', '設定錯的那則', None), ('assistant', '', 'failed'), ('user', '下一則請回答', None), ('assistant', '回覆：下一則請回答', 'completed')])

    def test_the_window_keeps_one_only_taken_in(self):
        js = ''.join(p.read_text(encoding='utf-8') for p in sorted((SERVER.parents[1] / 'frontend/js').glob('*.js')))
        self.assertIn('s.accepted = !!result.accepted', js)  # shown as 已送出 until the conversation has it, not dropped at the next refresh
        self.assertIn('if (!s.accepted) forget(s)', js)
        self.assertIn('(!x.done || x.accepted)', js)  # the next message still says it comes after this one (#142)


if __name__ == '__main__': unittest.main()
