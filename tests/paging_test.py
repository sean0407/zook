# -*- coding: utf-8 -*-
"""A very long conversation: the window gets the newest part; everything else still sees all of it."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from urllib.parse import quote

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, os, sys
s = sys.stdin.read()
open(os.path.join(os.path.dirname(sys.argv[0]), 'prompt.txt'), 'w').write(s)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'new reply'}}))
'''
TOTAL = 1200


class PagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.start()
        self.bot = self.req('POST', '/api/bots', {'name': '長談', 'provider': 'codex'})[1]
        self.stop()
        path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text())
        bot = next(b for b in data['bots'] if b['id'] == self.bot['id'])
        bot['messages'] = [dict(id='m%04d' % i, role='user' if i % 2 == 0 else 'assistant', content=('問題 %d' if i % 2 == 0 else '回答 %d') % i + ('：藍鯨計畫' if i == 7 else ''),
                                createdAt='2026-01-01T00:00:00+00:00', **({} if i % 2 == 0 else {'status': 'completed'})) for i in range(TOTAL)]
        bot['chats'].append(dict(id='side', title='另一個對話', createdAt='2026-01-01T00:00:00+00:00', updatedAt='2025-01-01T00:00:00+00:00',
                                 messages=[dict(id='s1', role='user', content='旁支對話裡提到藍鯨'), dict(id='s2', role='assistant', content='好', status='completed')]))
        path.write_text(json.dumps(data)); self.start()

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def me(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])
    def page(self, query): return self.req('GET', '/api/bots/%s/messages?%s' % (self.bot['id'], query))[1]

    def test_window_gets_the_newest_part_and_can_walk_back_to_the_first(self):
        me = self.me()
        self.assertEqual((len(me['messages']), me['messages'][-1]['id'], me['olderCount']), (100, 'm1199', 1100))
        side = next(c for c in me['chats'] if c['id'] == 'side')
        self.assertNotIn('messages', side); self.assertEqual(side['count'], 1)
        self.assertEqual(next(c for c in me['chats'] if c['id'] == me['chatId'])['count'], 600)
        seen, first = [m['id'] for m in me['messages']], me['messages'][0]['id']
        while True:
            page = self.page('before=' + first)
            self.assertLessEqual(len(page['messages']), 100)
            seen = [m['id'] for m in page['messages']] + seen; first = page['messages'][0]['id']
            if not page['more']: break
        self.assertEqual(seen, ['m%04d' % i for i in range(TOTAL)])  # every message once, in order
        self.assertEqual(self.req('GET', '/api/bots/%s/messages?before=nope' % self.bot['id'])[0], 400)

    def test_search_finds_an_early_message_and_can_jump_to_it(self):
        out = self.req('GET', '/api/search?q=' + quote('藍鯨'))[1]
        self.assertEqual({(h['chatId'], h['messageId']) for h in out['hits']}, {(self.me()['chatId'], 'm0007'), ('side', 's1')})
        self.assertIn('藍鯨計畫', next(h for h in out['hits'] if h['messageId'] == 'm0007')['snippet'])
        only = self.req('GET', '/api/search?q=%s&bot=%s' % (quote('藍鯨'), self.bot['id']))[1]
        self.assertEqual(sorted(only['chats']), sorted([self.me()['chatId'], 'side']))
        self.assertEqual(self.req('GET', '/api/search?q=')[1], {'hits': [], 'chats': []})
        jump = self.page('from=m0007')
        self.assertEqual((jump['messages'][0]['id'], jump['messages'][-1]['id'], jump['more']), ('m0000', 'm1199', False))
        self.assertEqual(self.page('chat=side&before=')['messages'][0]['id'], 's1')  # another conversation, by id

    def test_everything_else_still_sees_the_whole_conversation(self):
        # Export: the window asks for all of it.
        self.assertEqual(len(self.page('all=1')['messages']), TOTAL)
        self.assertEqual(len(next(b for b in self.req('POST', '/api/export', {})[1]['bots'] if b['id'] == self.bot['id'])['messages']), TOTAL)
        # A new message and a redo work on the real conversation, not on the window.
        job = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '第 1201 則'})[1]['jobId']
        end = time.time() + 15
        while time.time() < end and self.req('GET', '/api/jobs/' + job)[1]['status'] == 'running': time.sleep(0.1)
        me = self.me()
        self.assertEqual((me['olderCount'], [m['content'] for m in me['messages'][-2:]]), (1102, ['第 1201 則', 'new reply']))
        self.assertIn('回答 1199', (self.root / 'bin/prompt.txt').read_text())  # the model was given the recent history as before
        status, redo = self.req('POST', '/api/chat/redo', {'botId': self.bot['id'], 'mode': 'edit', 'content': '改寫的第 1201 則'})
        self.assertEqual(status, 202)
        end = time.time() + 15
        while time.time() < end and self.req('GET', '/api/jobs/' + redo['jobId'])[1]['status'] == 'running': time.sleep(0.1)
        whole = self.page('all=1')['messages']
        self.assertEqual((len(whole), whole[-2]['content'], whole[0]['id']), (TOTAL + 2, '改寫的第 1201 則', 'm0000'))
        # A backup and its restore carry all of it.
        made = self.req('POST', '/api/backups', {})[1]['name']
        after = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '備份之後'})[1]['jobId']
        end = time.time() + 15  # a restore waits for no reply: the fake CLI must have finished (slow when the suite runs 8 at a time)
        while time.time() < end and self.req('GET', '/api/jobs/' + after)[1]['status'] == 'running': time.sleep(0.1)
        self.assertEqual(self.req('POST', '/api/backups/%s/restore' % made, {})[0], 200)
        self.assertEqual(len(self.page('all=1')['messages']), TOTAL + 2)
        # Opening another conversation and coming back keeps both whole.
        self.assertEqual(self.req('POST', '/api/bots/%s/chats/side/open' % self.bot['id'], {})[0], 200)
        me = self.me()
        self.assertEqual(([m['id'] for m in me['messages']], me['olderCount']), (['s1', 's2'], 0))
        self.assertEqual(next(c for c in me['chats'] if c['id'] != 'side' and c.get('count') == 601)['count'], 601)

    def test_sync_file_and_phone_view(self):
        folder = self.root / 'cloud'; folder.mkdir()
        self.assertEqual(self.req('POST', '/api/sync', {'folder': str(folder), 'join': 'merge'})[0], 200)
        shared = json.loads(next(folder.glob('zook-sync-*.json')).read_text())
        chat = next(v for k, v in shared['items'].items() if k.startswith('chats:%s:' % self.bot['id']) and not k.endswith(':side'))
        self.assertEqual(len(chat['v']['messages']), TOTAL)  # the other Macs get the whole conversation
        spec_path = SERVER
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_server_for_paging', spec_path); module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
        self.stop()
        store = module.Store(self.root / 'data')
        view = module.mobile_bot(store, store.find('bots', self.bot['id']))
        self.assertEqual((len(view['messages']), view['messages'][-1]['id']), (80, 'm1199'))  # the phone always took the newest 80
        self.start()


if __name__ == '__main__':
    unittest.main()
