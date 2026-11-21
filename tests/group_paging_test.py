# -*- coding: utf-8 -*-
"""A very long group discussion: the window gets the newest part and can walk back to the first message; 查核, 分工 and each
member's own window still work on the whole of it; and the older part is summarised for the members, with every message kept."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = r'''#!/usr/bin/env python3
import json, os, sys, time
if '--help' in sys.argv or '--version' in sys.argv: print('codex-cli 9.9.9'); sys.exit(0)
s = sys.stdin.read(); here = os.path.dirname(sys.argv[0])
open(os.path.join(here, 'prompts-%f.txt' % time.time()), 'w').write(s)
if '整理成一份摘要' in s: text = 'SUMMARY-OF-OLD：前面講了很多'
elif '【判定】' in s: text = '【判定】同意\n看起來沒問題'
else: text = 'new reply'
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}}))
'''
TOTAL = 1200


class GroupPagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.start()
        self.req('PATCH', '/api/settings', {'permissionMode': 'auto'})
        self.a = self.req('POST', '/api/bots', {'name': 'Alpha', 'provider': 'codex'})[1]
        self.b = self.req('POST', '/api/bots', {'name': 'Beta', 'provider': 'codex'})[1]
        self.group = self.req('POST', '/api/groups', {'name': '長討論', 'botIds': [self.a['id'], self.b['id']], 'hostId': ''})[1]
        self.stop()
        path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text())
        group = next(g for g in data['groups'] if g['id'] == self.group['id'])
        def message(i):
            if i % 3 == 0: return dict(id='g%04d' % i, role='user', content='問題 %d' % i, createdAt='2026-01-01T00:00:00+00:00')
            return dict(id='g%04d' % i, role='assistant', botId=(self.a if i % 3 == 1 else self.b)['id'], content='回答 %d' % i, status='completed', createdAt='2026-01-01T00:00:00+00:00')
        group['messages'] = [message(i) for i in range(TOTAL)]
        group['messages'][-1] = dict(group['messages'][-1], checkOf='g1198')  # Beta's last reply is a check of Alpha's
        (self.root / 'data/chats').mkdir(exist_ok=True)
        stored = self.root / 'data/chats' / ('group.%s.json' % self.group['id'])
        if stored.exists(): stored.unlink()
        path.write_text(json.dumps(data)); self.start()

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close()

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def mine(self): return next(g for g in self.req('GET', '/api/state')[1]['groups'] if g['id'] == self.group['id'])
    def page(self, query): return self.req('GET', '/api/groups/%s/messages?%s' % (self.group['id'], query))[1]

    def idle(self):
        end = time.time() + 30
        while time.time() < end:
            g = self.req('GET', '/api/groups/' + self.group['id'])[1]['group']
            if g['status'] != 'running': return g
            time.sleep(0.1)
        self.fail('the discussion did not end')

    def prompts(self): return [p.read_text() for p in sorted((self.root / 'bin').glob('prompts-*.txt'))]

    def test_window_gets_the_newest_part_and_can_walk_back_to_the_first(self):
        g = self.mine()
        self.assertEqual((len(g['messages']), g['messages'][-1]['id'], g['olderCount']), (100, 'g1199', 1100))
        self.assertEqual(self.req('GET', '/api/groups/' + self.group['id'])[1]['group']['olderCount'], 1100)  # what the window polls, too
        seen, first = [m['id'] for m in g['messages']], g['messages'][0]['id']
        while True:
            part = self.page('before=' + first)
            seen = [m['id'] for m in part['messages']] + seen; first = part['messages'][0]['id']
            if not part['more']: break
        self.assertEqual(seen, ['g%04d' % i for i in range(TOTAL)])
        self.assertEqual(len(self.page('all=1')['messages']), TOTAL)  # 匯出對話
        self.assertEqual(self.page('from=g0500')['messages'][0]['id'], 'g0480')
        self.assertEqual(self.req('GET', '/api/state?full=1')[1]['groups'][0]['messages'][0]['id'], 'g0000')

    def test_member_counts_and_replies_since_the_last_question(self):
        g = self.mine()
        self.assertEqual(g['memberCounts'], {self.a['id']: 400, self.b['id']: 399})  # a check is not counted as speaking
        self.assertEqual(g['afterAsk'], dict(replies=1, card=False))  # the check after it is not a reply either

    def test_a_members_own_window_reaches_every_time_it_spoke(self):
        part = self.page('member=' + self.a['id'])
        self.assertEqual((len(part['turns']), part['more'], part['total']), (100, True, 400))
        self.assertEqual(part['turns'][-1]['id'], 'g1198'); self.assertEqual(part['turns'][-1]['asked']['content'], '問題 1197')
        turns = part['turns']
        while part['more']:
            part = self.page('member=%s&before=%s' % (self.a['id'], turns[0]['id'])); turns = part['turns'] + turns
        self.assertEqual([t['id'] for t in turns], ['g%04d' % i for i in range(1, TOTAL, 3)])
        self.assertEqual(turns[0]['asked']['content'], '問題 0')
        self.assertNotIn('g1199', [t['id'] for t in self.page('member=%s&all=1' % self.b['id'])['turns']])  # checks are shown with what they check

    def test_checking_a_reply_from_long_ago(self):
        path = '/api/groups/%s/messages/g0004/verify' % self.group['id']
        status, out = self.req('POST', path, {})
        if out.get('needsConfirm'): status, out = self.req('POST', path, {'confirm': True})
        self.assertEqual(status, 202, out)
        self.idle()
        check = next(m for m in self.page('all=1')['messages'] if m.get('checkOf') == 'g0004')
        self.assertEqual((check['verdict'], check['botId']), ('同意', self.b['id']))

    def test_split_work_after_the_older_part_is_summarised(self):
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '請分工規劃新產品', 'mode': 'split'})[0], 202)
        g = self.idle()
        self.assertEqual(g['summary']['text'], 'SUMMARY-OF-OLD：前面講了很多')
        everything = self.page('all=1')['messages']
        self.assertEqual(len([m for m in everything if m['id'].startswith('g')]), TOTAL)  # every message is still there
        replies = [m for m in everything[TOTAL:] if m['role'] == 'assistant']
        self.assertEqual([m['content'] for m in replies], ['new reply'] * 3)  # 分工: plan, the member's part, the merge
        marked = [m for m in everything if m.get('compacted')]
        self.assertEqual(len(marked), 1)
        at = next(i for i, m in enumerate(everything) if m['id'] == g['summary']['upTo'])
        self.assertTrue(everything[at + 1].get('compacted'))
        turns = [p for p in self.prompts() if '整理成一份摘要' not in p]
        self.assertTrue(turns and all('SUMMARY-OF-OLD' in p for p in turns))
        self.assertTrue(all('回答 5\n' not in p and '問題 1200' not in p for p in turns))
        self.assertIn('請分工規劃新產品', turns[0])
        # The next message does not summarise again: only what came after the summary counts.
        before = len(self.prompts())
        self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '@Alpha 補充一下'}); self.idle()
        self.assertFalse(any('整理成一份摘要' in p for p in self.prompts()[before:]))

    def test_switched_off_nothing_is_summarised(self):
        self.req('PATCH', '/api/settings', {'autoCompact': False})
        self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '@Alpha 你好'}); g = self.idle()
        self.assertNotIn('summary', g)
        self.assertFalse(any('整理成一份摘要' in p for p in self.prompts()))


if __name__ == '__main__': unittest.main()
