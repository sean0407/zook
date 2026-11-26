# -*- coding: utf-8 -*-
"""#248: a 「想問你」 card that goes away before the user answers says why, instead of vanishing: the Bot stopped waiting for it
(its CLI gave up on the call, or it ran out of time). Zook never answers for the user, and the Bot is told so."""
import re, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import choices_test

ROOT = Path(__file__).resolve().parents[1]
# A fake Claude that asks a question and then stops waiting for it (as a CLI does when the call is cancelled or times out).
GIVES_UP = '''#!/usr/bin/env python3
import json, os, subprocess, sys, time
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)
sys.stdin.read()
if '--mcp-config' in sys.argv:
    config = json.loads(sys.argv[sys.argv.index('--mcp-config') + 1])['mcpServers']['zook']
    proc = subprocess.Popen([config['command']] + config['args'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def send(i, method, params): proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\\n'); proc.stdin.flush()
    send(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}); proc.stdout.readline()
    send(2, 'tools/list', {}); proc.stdout.readline()
    send(3, 'tools/call', {'name': 'zook_ask_user', 'arguments': {'question': '要安裝 xlsxwriter 嗎？', 'options': ['要', '不要']}})
    time.sleep(2); proc.kill(); proc.wait()
    time.sleep(3)
print(json.dumps({'type': 'result', 'result': 'done', 'is_error': False}))
'''


class QuestionGone(choices_test.ChoicesTest):
    for _name in [n for n in dir(choices_test.ChoicesTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_a_question_the_bot_stopped_waiting_for_says_why(self):
        (self.root / 'bin/claude').write_text(GIVES_UP)
        job_id = self.send(); job, pending = self.waiting(job_id)
        self.assertEqual(len(pending), 1)
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['questions'][0]['status'] != 'pending': break
            time.sleep(0.1)
        question = job['questions'][0]
        self.assertEqual((question['status'], question.get('expiredWhy')), ('expired', 'gone'))
        self.assertNotIn('answer', question)
        self.assertEqual(self.req('POST', '/api/questions/' + question['id'], {'answer': '要'})[0], 409)

    def test_stopping_the_reply_is_told_apart(self):
        self.call('zook_ask_user', dict(question='要哪一個？', options=['A', 'B']))
        job_id = self.send(); self.waiting(job_id)
        self.req('POST', '/api/jobs/%s/cancel' % job_id, {})
        question = self.req('GET', '/api/jobs/' + job_id)[1]['questions'][0]
        self.assertEqual((question['status'], question.get('expiredWhy')), ('expired', 'ended'))

    def test_a_restart_says_why(self):
        m = choices_test.load(); folder = self.root / 'other'; store = m.Store(folder)
        store.data['bots'].append(dict(id='b', name='x', messages=[dict(id='m', role='assistant', content='', status='running')]))
        store.data['jobs'].append(dict(id='j', botId='b', messageId='m', status='running', questions=[dict(id='q', question='?', options=[], status='pending')]))
        store.save()
        question = m.Store(folder).data['jobs'][0]['questions'][0]
        self.assertEqual((question['status'], question.get('expiredWhy')), ('expired', 'restart'))

    def test_the_message_box_answers_a_waiting_question(self):  # user 11-26
        js = ROOT / 'frontend/js'
        page = (js / '33-choices.js').read_text(encoding='utf-8')
        fn = page[page.index("// User 11-26"):page.index("document.addEventListener('input', e => { if (e.target.dataset.answerDraft)")]
        for words in ("e.target.id !== 'chat-form'", 'activeGroup()', 'pendingList().length', 'pendingQuestions(state.selected)[0]', 'e.stopImmediatePropagation()', 'answerQuestion(q.id, text)', '}, true);'):
            self.assertIn(words, fn)
        later = [f.name for f in sorted(js.glob('*.js')) if "addEventListener('submit'" in f.read_text(encoding='utf-8') and 'chat-form' in f.read_text(encoding='utf-8') and f.name != '33-choices.js']
        self.assertTrue(later and all(name > '33-choices.js' for name in later), later)  # it runs before the message is sent
        self.assertIn('answered', page[page.index('async function answerQuestion'):page.index('// User 11-26')])  # and the card is marked answered

    def test_an_answer_from_the_box_reaches_the_bot(self):  # what the page posts for it is the card's own answer call
        self.call('zook_ask_user', dict(question='要安裝嗎？', options=['要', '不要']))
        job_id = self.send(); job, pending = self.waiting(job_id)
        self.assertEqual(self.req('POST', '/api/questions/' + pending[0]['id'], {'answer': '好，先裝 xlsxwriter'})[0], 200)
        job, _ = self.finish(job_id)
        self.assertEqual(job['questions'][0]['status'], 'answered'); self.assertIn('好，先裝 xlsxwriter', job['content'])

    def test_the_bot_is_told_not_to_answer_for_the_user(self):
        code = (ROOT / 'backend/zook/choices.py').read_text(encoding='utf-8')
        self.assertIn('不代表使用者拒絕', code)

    def test_the_page_keeps_a_card_that_says_why(self):
        page = (ROOT / 'frontend/js/33-choices.js').read_text(encoding='utf-8')
        fn = re.search(r'function goneQuestions\(botId\) \{(.*?)\n  \}', page, re.S)
        self.assertTrue(fn); body = fn.group(1)
        for words in ("expiredWhy === 'timeout'", "expiredWhy === 'gone'", "expiredWhy === 'ended' && j.status !== 'cancelled'", '沒有替你選', 'dismiss-question'): self.assertIn(words, body)
        self.assertIn('goneQuestions(b.id)', (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
