# -*- coding: utf-8 -*-
"""A conversation too long for the model is turned into a summary, and the CLI starts fresh from it."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
COMMON = '''
import json, os, sys
here = os.path.dirname(sys.argv[0])
mode = open(os.path.join(here, 'mode')).read().strip()
def log(prompt): open(os.path.join(here, 'prompts.log'), 'a').write(prompt + '\\n=====\\n')
SUMMARY = '把下面這段對話整理成一份摘要'
'''
GROK = '#!/usr/bin/env python3' + COMMON + '''
if set(sys.argv) & {'models', '--version', '--help'}: print('ok'); sys.exit(0)
prompt = open(sys.argv[sys.argv.index('--prompt-file') + 1]).read(); log(prompt)
if SUMMARY in prompt:
    if mode == 'summary-fails': sys.exit(1)
    text = '摘要：代號是藍鯨-4827。'
else: text = '一般回覆'
used = 200 if (mode == 'small-after' and '更早的對話已整理成這份摘要' in prompt) else 5000
print(json.dumps({'type': 'text', 'data': text}))
print(json.dumps({'type': 'end', 'stopReason': 'end_turn', 'usage': {'input_tokens': used, 'output_tokens': 5}}))
'''
CODEX = '#!/usr/bin/env python3' + COMMON + '''
prompt = sys.stdin.read(); log(prompt)
if SUMMARY in prompt: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '摘要：代號是藍鯨-4827。'}})); sys.exit(0)
if mode == 'too-long' and '更早的對話已整理成這份摘要' not in prompt:
    print(json.dumps({'type': 'turn.failed', 'error': {'message': 'context_length_exceeded: input is too long'}})); sys.exit(1)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '一般回覆'}}))
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 900000, 'output_tokens': 5}}))
'''


class CompactTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name, text in (('grok', GROK), ('codex', CODEX)):
            cli = self.root / 'bin' / name; cli.write_text(text); cli.chmod(0o755)
        self.mode('ok')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_COMPACT_AT='1000')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def mode(self, value): (self.root / 'bin/mode').write_text(value)

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def bot(self, provider): return self.req('POST', '/api/bots', {'name': 'C-' + provider, 'provider': provider})[1]

    def ask(self, bot, text):
        job_id = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': text})[1]['jobId']
        end = time.time() + 20
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.1)
        self.fail('no reply')

    def prompts(self):
        path = self.root / 'bin/prompts.log'
        return [p for p in path.read_text().split('\n=====\n') if p.strip()] if path.exists() else []

    def summaries(self): return [p for p in self.prompts() if '把下面這段對話整理成一份摘要' in p]
    def whole(self, bot): return next(b for b in self.req('POST', '/api/export', {})[1]['bots'] if b['id'] == bot['id'])

    def test_two_long_replies_then_the_next_starts_from_a_summary(self):
        self.mode('small-after'); bot = self.bot('grok')
        self.ask(bot, '代號是藍鯨-4827，請記住'); self.ask(bot, '第二則')
        self.assertEqual(self.summaries(), [])  # one long reply is not enough; two in a row are
        job = self.ask(bot, '第三則：代號是什麼？')
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertEqual(len(self.summaries()), 1)
        self.assertIn('代號是藍鯨-4827，請記住', self.summaries()[0]); self.assertNotIn('第三則', self.summaries()[0])  # the earlier part, not the new question
        last = self.prompts()[-1]
        self.assertIn('（更早的對話已整理成這份摘要）\n摘要：代號是藍鯨-4827。', last); self.assertIn('使用者：第三則：代號是什麼？', last)
        me = self.whole(bot); chat = next(c for c in me['chats'] if c['id'] == me['chatId'])
        self.assertEqual(chat['summary']['text'], '摘要：代號是藍鯨-4827。')
        self.assertEqual([m.get('compacted') for m in me['messages'] if m['role'] == 'user'], [None, None, True])
        self.assertEqual(len(me['messages']), 6)  # nothing was removed from the conversation
        state = self.req('GET', '/api/state')[1]
        self.assertFalse(any(j.get('internal') for j in state['jobs']))
        self.assertFalse(any(j.get('internal') for j in self.req('POST', '/api/export', {})[1]['jobs']))  # the helper run leaves nothing behind
        # It got smaller, so it may be done again later; and a later prompt that starts fresh carries summary plus what came after.
        self.ask(bot, '第四則')
        self.assertNotIn('compactOff', next(c for c in self.whole(bot)['chats'])); self.assertIn('assistant: 一般回覆', self.prompts()[-1])

    def test_no_use_doing_it_again_when_it_did_not_help(self):
        bot = self.bot('grok')  # every reply reports 5000, summary or not
        for text in ('一', '二', '三', '四', '五', '六'): self.ask(bot, text)
        self.assertEqual(len(self.summaries()), 1)
        chat = next(c for c in self.whole(bot)['chats'])
        self.assertIn('沒有明顯下降', chat['compactOff'])

    def test_two_failures_stop_it_and_say_so(self):
        self.mode('summary-fails'); bot = self.bot('grok')
        jobs = [self.ask(bot, t) for t in ('一', '二', '三', '四', '五')]
        self.assertTrue(all(j['status'] == 'completed' for j in jobs))  # the replies themselves were never held up
        self.assertEqual(len(self.summaries()), 2)
        me = self.whole(bot); chat = next(c for c in me['chats'])
        self.assertIn('失敗兩次', chat['compactOff']); self.assertNotIn('summary', chat)
        self.assertTrue(any('失敗兩次' in (m.get('note') or '') for m in me['messages']))

    def test_cli_says_too_long_then_tidy_and_try_once_more(self):
        bot = self.bot('codex')
        self.ask(bot, '代號是藍鯨-4827'); self.ask(bot, '第二則')
        self.assertEqual(self.summaries(), [])  # Codex tidies its own conversations: nothing is done ahead of time, however much it reports
        self.mode('too-long')
        job = self.ask(bot, '第三則')
        self.assertEqual((job['status'], job.get('content')), ('completed', '一般回覆'), job.get('error'))
        self.assertEqual(len(self.summaries()), 1); self.assertIn('（更早的對話已整理成這份摘要）', self.prompts()[-1])
        # Switched off: the same error is reported as it is, in plain words.
        self.req('PATCH', '/api/settings', {'autoCompact': False})
        other = self.bot('codex'); self.mode('ok'); self.ask(other, '一'); self.ask(other, '二'); self.mode('too-long')
        job = self.ask(other, '三')
        self.assertEqual((job['status'], job['errorKind']), ('failed', 'context')); self.assertIn('對話太長', job['error'])
        self.assertEqual(len(self.summaries()), 1)
        self.assertEqual(self.req('PATCH', '/api/settings', {'autoCompact': 'x'})[0], 400)


if __name__ == '__main__':
    unittest.main()
