# -*- coding: utf-8 -*-
"""Choices answered with one click: options at the end of a reply, and a question in the middle of the work."""
import importlib.util, json, sys, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import origin_test

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
# A fake Claude: keeps the prompt, optionally calls one Zook tool, then answers with reply.txt.
CLAUDE = '''#!/usr/bin/env python3
import json, os, subprocess, sys
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)  # Zook asking what this CLI can do
here = os.path.dirname(sys.argv[0])
open(os.path.join(here, 'prompt.txt'), 'w').write(sys.stdin.read())
text = open(os.path.join(here, 'reply.txt')).read() if os.path.exists(os.path.join(here, 'reply.txt')) else 'ok'
if os.path.exists(os.path.join(here, 'call.json')) and '--mcp-config' in sys.argv:
    config = json.loads(sys.argv[sys.argv.index('--mcp-config') + 1])['mcpServers']['zook']
    proc = subprocess.Popen([config['command']] + config['args'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(i, method, params):
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\\n'); proc.stdin.flush()
        return json.loads(proc.stdout.readline())
    rpc(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}})
    names = [t['name'] for t in rpc(2, 'tools/list', {})['result']['tools']]
    out = rpc(3, 'tools/call', json.load(open(os.path.join(here, 'call.json'))))
    proc.stdin.close(); proc.wait(timeout=5)
    text = 'TOOLS:' + ','.join(names) + ' TOOL:' + json.dumps(out.get('result') or out.get('error'), ensure_ascii=False)
print(json.dumps({'type': 'result', 'result': text, 'is_error': False}))
'''


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_choices', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class SplitTest(unittest.TestCase):
    def test_only_a_block_written_as_asked_becomes_buttons(self):
        m = load(); split = m.split_choices
        self.assertEqual(split('要用哪一種？\n\n【選項】\n- 表格\n- 條列'), ('要用哪一種？', ['表格', '條列']))
        self.assertEqual(split('選一個\n【選項】\n* A\n* B\n* C\n* D\n'), ('選一個', ['A', 'B', 'C', 'D']))
        for text in ('沒有選項的回覆', '只有一個\n【選項】\n- A', '太多\n【選項】\n- 1\n- 2\n- 3\n- 4\n- 5', '【選項】\n- A\n- B', '在中間\n【選項】\n- A\n- B\n後面還有字',
                     '太長\n【選項】\n- %s\n- B' % ('字' * 61), '重複\n【選項】\n- A\n- A'):
            self.assertEqual(split(text), (text, None), text)

    def test_half_written_block_is_hidden_while_streaming(self):
        hide = load().hide_choice_block
        self.assertEqual(hide('要用哪一種？\n\n【選項】\n- 表'), '要用哪一種？')
        self.assertEqual(hide('要用哪一種？\n【選項】'), '要用哪一種？')
        self.assertEqual(hide('文章提到【選項】這個詞，後面還有很多內容。\n第二段\n第三段\n第四段\n第五段\n第六段'), '文章提到【選項】這個詞，後面還有很多內容。\n第二段\n第三段\n第四段\n第五段\n第六段')
        self.assertEqual(hide('一般文字'), '一般文字')
        self.assertEqual(hide('報告\n【選項】\n第一段很長的內容\n\n第二段'), '報告\n【選項】\n第一段很長的內容\n\n第二段')  # ordinary text after the word stays

    def test_long_or_odd_text_is_quick_and_never_becomes_a_button(self):
        m = load(); began = time.time()
        deep = '表格\n【選項】\n' + '\n'.join(' ' * 60 + 'x' for _ in range(8))
        self.assertEqual(m.hide_choice_block(deep), deep); self.assertEqual(m.split_choices(deep), (deep, None))
        wide = 'a' + ' ' * 80000 + '\n【選項】\n- A' + ' ' * 20000 + '\n- B'
        self.assertEqual(m.split_choices(wide)[1], ['A', 'B'])
        self.assertLess(time.time() - began, 1)
        for bad in ('- a\x0bevil\n- b', '- a\u202eb\n- c', '- a\u200bb\n- c', '- a\x1cb\n- c'):
            text = '選一個\n【選項】\n' + bad
            self.assertEqual(m.split_choices(text), (text, None), repr(bad))
        self.assertIsNone(m.clean_choice('a\nb')); self.assertEqual(m.clean_choice('  表格 '), '表格')


class ChoicesTest(origin_test.OriginTest):
    for _name in [n for n in dir(origin_test.OriginTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def setUp(self):
        super().setUp()
        (self.root / 'bin/claude').write_text(CLAUDE); (self.root / 'bin/call.json').unlink()

    def reply(self, text): (self.root / 'bin/reply.txt').write_text(text, encoding='utf-8')
    def prompt(self): return (self.root / 'bin/prompt.txt').read_text(encoding='utf-8')
    def last(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])['messages'][-1]
    def send(self, text='請問'): return self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})[1]['jobId']

    def test_options_at_the_end_of_a_reply_become_buttons(self):
        self.reply('要用哪一種格式？\n\n【選項】\n- 表格\n- 條列\n')
        job, _ = self.finish(self.send())
        self.assertEqual(job['content'], '要用哪一種格式？'); self.assertIn('【選項】', self.prompt())
        self.assertEqual((self.last()['content'], self.last()['options']), ('要用哪一種格式？', ['表格', '條列']))

    def test_switch_off_is_exactly_as_before(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'choiceButtons': 'no'})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'choiceButtons': False})[0], 200)
        self.reply('要用哪一種格式？\n\n【選項】\n- 表格\n- 條列')
        self.call('zook_ask_user', dict(question='要哪一個？', options=['A', 'B']))
        job, _ = self.finish(self.send())
        self.assertNotIn('【選項】', self.prompt()); self.assertNotIn('zook_ask_user', self.prompt())
        self.assertNotIn('zook_ask_user', job['content'].split(' TOOL:')[0]); self.assertNotIn('questions', job)
        self.assertNotIn('options', self.last())
        (self.root / 'bin/call.json').unlink()
        job, _ = self.finish(self.send())
        self.assertEqual(self.last()['content'], '要用哪一種格式？\n\n【選項】\n- 表格\n- 條列')

    def waiting(self, job_id):
        end = time.time() + 10
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            pending = [q for q in job.get('questions') or [] if q['status'] == 'pending']
            if pending or job['status'] != 'running': return job, pending
            time.sleep(0.05)
        self.fail('no question')

    def test_question_waits_for_the_answer_and_is_not_an_approval(self):
        self.call('zook_ask_user', dict(question='報告要用哪一種格式？', options=['表格', '條列']))
        job_id = self.send(); job, pending = self.waiting(job_id)
        self.assertEqual((pending[0]['question'], pending[0]['options']), ('報告要用哪一種格式？', ['表格', '條列']))
        self.assertEqual(job['approvals'], [])
        qid = pending[0]['id']
        self.assertEqual(self.req('POST', '/api/questions/' + qid, {'answer': ''})[0], 400)
        self.assertEqual(self.req('POST', '/api/questions/' + qid, {'answer': 'x' * 2001})[0], 400)
        self.assertEqual(self.req('POST', '/api/questions/nope', {'answer': 'x'})[0], 404)
        self.assertEqual(self.req('POST', '/api/questions/' + qid, {'answer': '我想要兩種都有'})[0], 200)  # the user's own words are fine too
        self.assertEqual(self.req('POST', '/api/questions/' + qid, {'answer': '表格'})[0], 409)
        job, asked = self.finish(job_id)
        self.assertIn('我想要兩種都有', job['content']); self.assertIn('不是對任何動作的核准', job['content']); self.assertEqual(asked, [])
        self.assertIn('zook_ask_user', self.prompt())

    def test_an_answer_does_not_approve_the_next_action(self):
        self.call('zook_ask_user', dict(question='要建立排程嗎？', options=['要', '不要']))
        job_id = self.send(); job, pending = self.waiting(job_id)
        self.req('POST', '/api/questions/' + pending[0]['id'], {'answer': '要'}); self.finish(job_id)
        self.call('zook_create_schedule', dict(content='偷偷建立', repeat='daily', time='10:00'))
        job, asked = self.finish(self.send(), approve=False)
        self.assertEqual(len(asked), 1)  # still asked, and refused
        self.assertEqual(self.schedules(), [])

    def test_bad_questions_are_refused(self):
        for arguments in (dict(question=''), dict(question='問', options=['只有一個']), dict(question='問', options=['A', 'A']), dict(question='問', options=['1', '2', '3', '4', '5']), dict(question='問' * 501)):
            self.call('zook_ask_user', arguments)
            job, _ = self.finish(self.send())
            self.assertIn('isError', job['content'], arguments); self.assertNotIn('questions', job)

    def test_stopping_the_reply_ends_the_question(self):
        self.call('zook_ask_user', dict(question='要哪一個？', options=['A', 'B']))
        job_id = self.send(); job, pending = self.waiting(job_id)
        self.req('POST', '/api/jobs/%s/cancel' % job_id, {})
        job = self.req('GET', '/api/jobs/' + job_id)[1]
        self.assertEqual(job['questions'][0]['status'], 'expired')
        self.assertEqual(self.req('POST', '/api/questions/' + pending[0]['id'], {'answer': 'A'})[0], 409)

    def test_restart_ends_an_open_question(self):
        m = load(); folder = self.root / 'other'; store = m.Store(folder)
        store.data['bots'].append(dict(id='b', name='x', messages=[dict(id='m', role='assistant', content='', status='running')]))
        store.data['jobs'].append(dict(id='j', botId='b', messageId='m', status='running', questions=[dict(id='q', question='?', options=[], status='pending')]))
        store.save()
        self.assertEqual(m.Store(folder).data['jobs'][0]['questions'][0]['status'], 'expired')

    def test_nobody_to_ask_in_a_scheduled_turn(self):
        mine = self.req('POST', '/api/schedules', {'botId': self.bot['id'], 'content': '排程', 'time': '00:00', 'repeat': 'daily', 'on': False})[1]
        self.call('zook_ask_user', dict(question='要哪一個？', options=['A', 'B']))
        self.reply('結果\n【選項】\n- A\n- B')
        job = self.run_schedule_once(mine['id'])
        self.assertIn('沒有人可以回答', job['content']); self.assertNotIn('questions', job); self.assertNotIn('【選項】', self.prompt())


if __name__ == '__main__': unittest.main()
