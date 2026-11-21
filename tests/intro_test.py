# -*- coding: utf-8 -*-
"""A new Bot greets in its own words and offers questions you might ask it, made once from its persona when it is created or changed."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, os, sys
if 'login' in sys.argv: print('Logged in using ChatGPT'); sys.exit(0)
if set(sys.argv) & {'--help', '--version', 'models', 'app-server'}: sys.exit(0)
prompt = sys.stdin.read()
if '見到使用者時說的一句口語化招呼' in prompt and os.environ.get('INTRO_SLOW'): import time; time.sleep(3)
if '見到使用者時說的一句口語化招呼' not in prompt:
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '一般回覆'}}, ensure_ascii=False)); sys.exit(0)
open(os.environ['INTRO_LOG'], 'a').write(json.dumps(sys.argv[1:]) + '\\n' + prompt + '\\n=====\\n')
name = '香氛研發' if '香氛研發' in prompt else '新名字'
said = json.dumps({'greeting': '嗨！我是%s，今天想從哪個配方開始聊？' % name, 'questions': ['這款體香膏的成分安全嗎？', '保存期限大概多久？', '敏感肌可以用嗎？', '第四題', '第五題']}, ensure_ascii=False)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': said}}, ensure_ascii=False))  # as Codex reports a reply
'''


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_intro', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class IntroParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def test_never_on_api_billing_a_used_up_budget_or_limit(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        store = self.m.Store(Path(temp.name) / 'data'); self.m._active['data'] = store.data
        store.data['accounts'] = [dict(id='k' * 32, provider='codex', name='API', type='key')]
        store.data['autoStatus'] = {'codex': dict(signedIn=True, billed=False), 'claude': dict(signedIn=True, billed=True)}
        bot = dict(id='b', name='x')
        self.assertEqual(self.m.intro_blocked(store, bot, 'codex', ''), '')
        self.assertEqual(self.m.intro_blocked(store, bot, 'codex', 'k' * 32), 'API 計費')
        self.assertEqual(self.m.intro_blocked(store, bot, 'claude', ''), 'API 計費')
        store.data['quota'] = {'codex': {'windows': [{'label': '5 小時', 'usedPercent': 100, 'resetsAt': time.time() + 3600}]}}
        self.assertEqual(self.m.intro_blocked(store, bot, 'codex', ''), '額度已用完')

    def test_broken_text_and_stored_junk_are_refused(self):
        self.assertIsNone(self.m.parse_intro('{"greeting": "\\ud800", "questions": ["\\ud800"]}'))
        self.assertEqual(self.m.parse_intro('{"greeting": "嗨", "questions": ["/goal 做完"]}')['questions'], ['goal 做完'])  # never a slash command
        self.assertFalse(self.m.intro_valid(dict(greeting='嗨', questions={'a': 1})))

    def test_reply_is_read_strictly(self):
        ok = self.m.parse_intro('好的：\n```json\n{"greeting": "嗨，我是小香！", "questions": ["A？", "", "B？", 3, "C？", "D？"]}\n```')
        self.assertEqual(ok, dict(greeting='嗨，我是小香！', questions=['A？', 'B？', 'C？']))
        self.assertIsNone(self.m.parse_intro('沒有 JSON'))
        self.assertIsNone(self.m.parse_intro('{"greeting": "", "questions": ["A"]}'))
        self.assertIsNone(self.m.parse_intro('{"greeting": "嗨", "questions": []}'))
        long = self.m.parse_intro(json.dumps({'greeting': '嗨' * 300, 'questions': ['問' * 300]}))
        self.assertLessEqual(len(long['greeting']), 81); self.assertLessEqual(len(long['questions'][0]), 41)

    def test_source_follows_what_the_bot_is(self):
        a = dict(name='研發', jobTitle='研發', persona='細心', instructions='配方', color='#000')
        self.assertEqual(self.m.intro_source(a), self.m.intro_source(dict(a, color='#fff')))  # looks do not matter
        self.assertNotEqual(self.m.intro_source(a), self.m.intro_source(dict(a, persona='直接')))


class IntroServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'intro.log'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', INTRO_LOG=str(self.log), ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def intro_of(self, bot_id, unlike=None):
        for _ in range(150):
            bot = next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == bot_id)
            if bot.get('intro') and bot['intro'] != unlike: return bot['intro']
            time.sleep(.1)
        self.fail('no greeting was made')

    def test_made_when_created_and_again_when_the_persona_changes(self):
        bot = self.req('POST', '/api/bots', {'name': '香氛研發', 'provider': 'codex', 'persona': '細心的配方師', 'jobTitle': '研發', 'permissionMode': 'bypass'})[1]
        intro = self.intro_of(bot['id'])
        self.assertEqual(intro['greeting'], '嗨！我是香氛研發，今天想從哪個配方開始聊？'); self.assertEqual(len(intro['questions']), 3)
        log = self.log.read_text()
        self.assertIn('細心的配方師', log); self.assertIn('--sandbox', log); self.assertIn('read-only', log)  # read-only, whatever the Bot may do in chats
        self.assertEqual(next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == bot['id'])['messages'], [])  # nothing lands in the conversation
        self.req('PATCH', '/api/bots/' + bot['id'], {'color': '#123456'}); time.sleep(.5)
        self.assertEqual(self.log.read_text().count('====='), 1)  # looks alone do not ask again
        self.req('PATCH', '/api/bots/' + bot['id'], {'name': '新名字'})
        self.assertEqual(self.intro_of(bot['id'], unlike=intro)['greeting'], '嗨！我是新名字，今天想從哪個配方開始聊？')

    def test_an_older_bot_asks_when_its_empty_conversation_opens(self):
        bot = next(b for b in self.req('GET', '/api/state')[1]['bots'] if not b.get('intro'))  # a starter Bot made before any greeting
        bot = self.req('PATCH', '/api/bots/' + bot['id'], {'provider': 'codex'})[1]
        intro = self.intro_of(bot['id'])
        status, _ = self.req('POST', '/api/bots/%s/intro' % bot['id'], {})
        self.assertEqual(status, 202); time.sleep(.5)
        self.assertEqual(self.log.read_text().count('====='), 1); self.assertTrue(intro['questions'])  # still fits the Bot: not made again

    def test_a_message_is_answered_while_the_greeting_is_being_made(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close()
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', INTRO_LOG=str(self.log), ZOOK_SECRETS_DIR=str(self.root / 'secrets'), INTRO_SLOW='1')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        bot = self.req('POST', '/api/bots', {'name': '香氛研發', 'provider': 'codex', 'persona': 'x'})[1]
        time.sleep(.5)
        status, job = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': '你好'})
        self.assertEqual(status, 202, job)  # not 「已有執行中的工作」, and not queued behind the greeting
        for _ in range(100):
            if self.req('GET', '/api/jobs/' + job['jobId'])[1]['status'] != 'running': break
            time.sleep(.1)
        self.assertEqual(self.req('GET', '/api/jobs/' + job['jobId'])[1]['content'], '一般回覆')
        self.assertTrue(self.intro_of(bot['id'])['greeting'])


if __name__ == '__main__': unittest.main()
