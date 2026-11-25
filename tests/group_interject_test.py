# -*- coding: utf-8 -*-
"""插話: the user speaks while a group discussion runs, without stopping it first."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = r'''#!/usr/bin/env python3
import json, os, re, sys, time
a = sys.argv[1:]; kind = os.path.basename(sys.argv[0])
if a[:2] == ['login', 'status']: print('Logged in using ChatGPT'); sys.exit(0)
if a[:2] == ['auth', 'status']: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if 'app-server' in a or '--help' in a or '--version' in a: sys.exit(0)
s = sys.stdin.read()
name = re.search(r'現在輪到你（(.+?)）回覆', s); name = name.group(1) if name else 'solo'
slow = os.environ['SLOW_MARK']
if name == 'Alpha' and os.path.exists(slow): os.remove(slow); time.sleep(2.5)  # long enough for the user to speak
open(os.environ['GROUP_LOG'], 'a').write(json.dumps(dict(name=name, saw='五萬' in s)) + '\n')
text = name + ' 好'
if kind == 'claude': print(json.dumps({'type': 'result', 'result': text, 'is_error': False}))
else: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})); print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 5}}))
'''


class GroupInterject(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'runs.log'; self.slow = self.root / 'slow'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', GROUP_LOG=str(self.log), SLOW_MARK=str(self.slow), ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bots = {n: self.req('POST', '/api/bots', {'name': n, 'provider': p})[1] for n, p in (('Alpha', 'codex'), ('Beta', 'claude'), ('Gamma', 'codex'))}

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        try: return resp.status, json.loads(data)
        except ValueError: return resp.status, data

    def group(self, names):
        status, group = self.req('POST', '/api/groups', {'botIds': [self.bots[n]['id'] for n in names]}); self.assertEqual(status, 201, group); return group

    def wait(self, test, what):
        for _ in range(200):
            if test(): return
            time.sleep(.05)
        self.fail(what)

    def settle(self, group):
        def idle():
            time.sleep(.3)  # a round started for an unseen message begins right after the first one ends
            return self.req('GET', '/api/groups/' + group['id'])[1]['group']['status'] != 'running'
        self.wait(idle, 'discussion did not finish')
        return self.req('GET', '/api/groups/' + group['id'])[1]['group']

    def runs(self): return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_a_mentioned_member_answers_next_and_sees_the_message(self):
        g = self.group(('Alpha', 'Beta', 'Gamma')); self.slow.write_text('1')
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '大家討論活動'})[0], 202)
        self.wait(lambda: self.req('GET', '/api/groups/' + g['id'])[1]['group']['status'] == 'running' and not self.slow.exists(), 'Alpha did not start')
        status, body = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@Gamma 預算改成五萬'})
        self.assertEqual(status, 202, body); self.assertTrue(body['interjected']); self.assertEqual(body['next'], ['Gamma']); self.assertEqual(body['to'], 'Gamma')
        found = self.settle(g)
        order = [r['name'] for r in self.runs()]
        self.assertEqual(order, ['Alpha', 'Gamma', 'Beta'])  # Gamma jumped ahead of Beta
        self.assertTrue(all(r['saw'] for r in self.runs()[1:]))  # every later turn read it
        said = next(m for m in found['messages'] if m.get('role') == 'user' and '五萬' in m['content'])
        self.assertTrue(said.get('interjected'))

    def test_a_message_no_turn_saw_gets_its_own_round(self):
        g = self.group(('Alpha', 'Beta')); self.slow.write_text('1')
        self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@Alpha 寫個計畫'})
        self.wait(lambda: not self.slow.exists(), 'Alpha did not start')
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '預算改成五萬'})[0], 202)
        self.settle(g)
        self.assertEqual([(r['name'], r['saw']) for r in self.runs()], [('Alpha', False), ('Alpha', True), ('Beta', True)])  # the new round goes to everyone

    def test_a_structured_round_reads_it_at_the_next_step(self):
        # #94／#126, decided by the user: 即時插入. 輪流 goes on in its order, and every step after it reads the message.
        g = self.group(('Alpha', 'Beta', 'Gamma')); self.slow.write_text('1')
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '輪流說', 'mode': 'turns'})[0], 202)
        self.wait(lambda: not self.slow.exists(), 'Alpha did not start')
        status, body = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '預算改成五萬'})
        self.assertEqual(status, 202, body); self.assertEqual((body['interjected'], body['queued'], body['waiting']), (True, False, False))
        self.assertEqual(body['to'], '下一位回覆的成員')
        found = self.settle(g)
        self.assertEqual([(r['name'], r['saw']) for r in self.runs()], [('Alpha', False), ('Beta', True), ('Gamma', True)])  # read at once; no extra round
        said = next(m for m in found['messages'] if '五萬' in m['content'])
        self.assertTrue(said.get('interjected')); self.assertNotIn('queued', said); self.assertEqual(said.get('heardBy'), 'Beta')

    def test_a_split_round_reads_it_before_the_host_merges(self):
        # #126: the host's next turn has it, so the summary is not built on the old numbers.
        status, g = self.req('POST', '/api/groups', {'botIds': [self.bots[n]['id'] for n in ('Alpha', 'Beta', 'Gamma')], 'hostId': self.bots['Gamma']['id']})
        self.assertEqual(status, 201, g); self.slow.write_text('1')
        self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '分工做', 'mode': 'split'})
        self.wait(lambda: not self.slow.exists(), 'Alpha did not start')
        body = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '桌菜預算五萬'})[1]
        self.assertTrue(body['interjected'])
        self.settle(g)
        runs = self.runs()
        self.assertEqual(runs[-1]['name'], 'Gamma'); self.assertTrue(runs[-1]['saw'])  # the merge read it
        self.assertEqual(len([r for r in runs if r['name'] == 'Gamma']), 2)  # plan and merge only: no extra round for it

    def test_stop_leaves_nothing_waiting(self):
        g = self.group(('Alpha', 'Beta')); self.slow.write_text('1')
        self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@Alpha 寫個計畫'})
        self.wait(lambda: not self.slow.exists(), 'Alpha did not start')
        body = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@Beta 預算改成五萬'})[1]
        self.assertTrue(body['interjected']); self.assertEqual(body['next'], ['Beta'])
        self.assertEqual(self.req('POST', '/api/groups/%s/stop' % g['id'], {})[0], 200)
        time.sleep(3)  # the stopped round would have answered it by now
        found = self.req('GET', '/api/groups/' + g['id'])[1]['group']
        self.assertEqual(found['status'], 'idle')
        self.assertNotIn('Beta', [r['name'] for r in self.runs()])  # Beta was not called after the stop (Alpha was cut off before it logged)
        self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@Alpha 繼續'})
        self.settle(g)
        self.assertTrue(self.runs()[-1]['saw'] and self.runs()[-1]['name'] == 'Alpha')  # read like any message; Beta was not called by the old @

    def test_something_new_joins_too(self):
        # 即時插入 for every message, not only a correction: the turns after it read it, and nothing waits for the end of the round.
        g = self.group(('Alpha', 'Beta', 'Gamma')); self.slow.write_text('1')
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '大家討論活動'})[0], 202)
        self.wait(lambda: not self.slow.exists(), 'Alpha did not start')
        status, body = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '請幫我寫一份下個月展覽活動的完整企劃書，總預算是五萬元，給整個團隊參考'})
        self.assertEqual(status, 202, body); self.assertEqual((body['interjected'], body['queued'], body['waiting']), (True, False, False))
        found = self.settle(g)
        self.assertEqual([(r['name'], r['saw']) for r in self.runs()], [('Alpha', False), ('Beta', True), ('Gamma', True)])
        said = next(m for m in found['messages'] if '展覽' in m['content'])
        self.assertTrue(said.get('interjected')); self.assertNotIn('waiting', said)

    def test_several_messages_each_reach_the_member_they_name(self):
        g = self.group(('Alpha', 'Beta', 'Gamma')); self.slow.write_text('1')
        self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '大家討論活動'})
        self.wait(lambda: not self.slow.exists(), 'Alpha did not start')
        a = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@Gamma 請另外寫一份下個月展覽活動的完整企劃書，總預算是五萬元'})[1]
        b = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@Beta 請寫一份給客戶的完整說明信，說明報價的計算方式'})[1]
        c = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '等等，短一點'})[1]
        self.assertEqual([x['interjected'] for x in (a, b, c)], [True, True, True]); self.assertEqual([a['to'], b['to']], ['Gamma', 'Beta'])
        found = self.settle(g)
        self.assertEqual([(r['name'], r['saw']) for r in self.runs()], [('Alpha', False), ('Gamma', True), ('Beta', True)])  # the named ones answered next, once each
        self.assertFalse(any(m.get('waiting') for m in found['messages']))

    def test_files_wait_for_the_end_of_the_discussion(self):
        g = self.group(('Alpha', 'Beta')); self.slow.write_text('1')
        self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@Alpha 寫個計畫'})
        self.wait(lambda: not self.slow.exists(), 'Alpha did not start')
        status, body = self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '看這個', 'attachments': ['x']})
        self.assertEqual(status, 409); self.assertIn('附件', body.get('error', ''))
        self.settle(g)


class InterjectNoteTest(unittest.TestCase):
    def test_the_window_says_who_takes_it(self):
        look = (Path(__file__).resolve().parents[1] / 'frontend/js/38-look.js').read_text(encoding='utf-8')
        line = next(x for x in look.splitlines() if 'window.sentNote' in x)
        self.assertIn('交給 ${esc(m.interjectTo)} 處理', line); self.assertIn('${esc(m.heardBy)} 已讀到', line)  # names escaped: the note is drawn as HTML


if __name__ == '__main__': unittest.main()
