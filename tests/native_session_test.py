# -*- coding: utf-8 -*-
"""A2: a Zook conversation continues the CLI's own conversation."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CODEX = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0]); text = sys.stdin.read()
with open(os.path.join(here, 'runs.jsonl'), 'a') as f: f.write(json.dumps(dict(args=a, prompt=text)) + '\n')
if 'resume' in a and os.path.exists(os.path.join(here, 'lost')): sys.stderr.write('Error: no rollout found for thread id x\n'); sys.exit(1)
if 'PLEASE-FAIL' in text: sys.exit(1)
print(json.dumps(dict(type='thread.started', thread_id=a[a.index('resume') + 1] if 'resume' in a else 'thread-%d' % len(open(os.path.join(here, 'runs.jsonl')).readlines()))))
print(json.dumps(dict(type='item.completed', item=dict(type='agent_message', text='ok'))))
'''


class NativeSessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_NO_INTRO='1')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'N', 'provider': 'codex'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20); c.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d)

    def wait(self, sent):
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            if job['status'] != 'running': time.sleep(0.05); return job
            time.sleep(0.1)
        self.fail('no reply')

    def say(self, text): return self.wait(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})[1])
    def last(self): return [json.loads(x) for x in (self.root / 'bin/runs.jsonl').read_text().splitlines()][-1]
    def state(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])

    def test_continues_and_new_conversations_start_blank(self):
        self.say('第一句話')
        first = self.last(); self.assertNotIn('resume', first['args']); self.assertNotIn('--ephemeral', first['args'])
        self.say('第二句話')
        run = self.last(); self.assertEqual(run['args'][-3:], ['resume', 'thread-1', '-'])
        self.assertIn('第二句話', run['prompt']); self.assertNotIn('對話紀錄', run['prompt']); self.assertNotIn('第一句話', run['prompt'])
        self.req('POST', '/api/bots/%s/chats' % self.bot['id'], {})
        self.say('新對話'); self.assertNotIn('resume', self.last()['args'])

    def test_a_lost_conversation_falls_back_to_what_zook_saved(self):
        self.say('記得藍鯨'); (self.root / 'bin/lost').write_text('x')
        job = self.say('剛才說什麼')
        self.assertEqual(job['status'], 'completed')
        run = self.last(); self.assertNotIn('resume', run['args']); self.assertIn('記得藍鯨', run['prompt'])
        self.assertIn('接不上', self.state()['messages'][-1]['note'])

    def test_rewriting_history_or_changing_model_starts_over(self):
        self.say('問題'); status, sent = self.req('POST', '/api/chat/redo', {'botId': self.bot['id'], 'mode': 'edit', 'content': '改過的問題'})
        self.wait(sent); self.assertNotIn('resume', self.last()['args'])
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'model': 'gpt-other'})
        self.say('換模型後'); self.assertNotIn('resume', self.last()['args'])
        self.say('同模型'); self.assertIn('resume', self.last()['args'])

    def test_the_question_comes_last_in_the_prompt(self):
        self.say('藍鯨有多大'); self.assertTrue(self.last()['prompt'].rstrip().endswith('藍鯨有多大'))
        self.say('牠吃什麼'); self.assertIn('resume', self.last()['args']); self.assertTrue(self.last()['prompt'].rstrip().endswith('牠吃什麼'))

    def test_changing_access_or_planning_starts_over(self):
        self.say('問題'); self.req('PATCH', '/api/bots/' + self.bot['id'], {'access': 'workspace'})
        self.say('換範圍後'); self.assertNotIn('resume', self.last()['args'])
        self.say('同範圍'); self.assertIn('resume', self.last()['args'])
        self.wait(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '先規劃', 'plan': True})[1])
        self.say('開始做'); self.assertNotIn('resume', self.last()['args'])

    def test_a_failed_reply_is_not_continued(self):
        self.say('開始'); runs = len((self.root / 'bin/runs.jsonl').read_text().splitlines())
        self.assertEqual(self.say('PLEASE-FAIL')['status'], 'failed')
        self.assertEqual(len((self.root / 'bin/runs.jsonl').read_text().splitlines()), runs + 1)  # it may have acted, so it is not run again
        self.say('再來'); run = self.last(); self.assertNotIn('resume', run['args']); self.assertIn('開始', run['prompt'])

    def test_long_conversations_are_kept_when_starting_over(self):
        self.say('最早的內容 甲乙丙')
        for i in range(30): self.say('第 %d 句' % i)
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'model': 'gpt-other'})
        self.say('現在'); self.assertIn('最早的內容 甲乙丙', self.last()['prompt'])

    def test_groups_do_not_keep_cli_conversations(self):
        other = self.req('POST', '/api/bots', {'name': 'M', 'provider': 'codex'})[1]
        group = self.req('POST', '/api/groups', {'name': 'G', 'botIds': [self.bot['id'], other['id']]})[1]
        self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '大家好'}); end = time.time() + 15
        while time.time() < end and next(g for g in self.req('GET', '/api/state')[1]['groups'] if g['id'] == group['id'])['status'] == 'running': time.sleep(0.2)
        self.assertIn('--ephemeral', self.last()['args'])


if __name__ == '__main__': unittest.main()
