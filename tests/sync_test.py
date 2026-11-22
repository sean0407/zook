# -*- coding: utf-8 -*-
"""Two Macs kept alike through a shared folder."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, sys
sys.stdin.read()
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'reply'}}))
'''


class Mac:
    def __init__(self, root, name):
        self.root = root / name; (self.root / 'assets').mkdir(parents=True); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def close(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def state(self): return self.req('GET', '/api/state?full=1')[1]
    def bots(self): return {b['name']: b for b in self.state()['bots']}
    def sync(self): return self.req('POST', '/api/sync/now', {})[1]

    def ask(self, bot_id, text):
        status, out = self.req('POST', '/api/chat', {'botId': bot_id, 'content': text})
        assert status == 202, out
        end = time.time() + 15
        while time.time() < end:
            if self.req('GET', '/api/jobs/' + out['jobId'])[1]['status'] != 'running': return
            time.sleep(0.1)
        raise AssertionError('no reply')


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.folder = self.root / 'cloud'; self.folder.mkdir()
        self.a, self.b = Mac(self.root, 'a'), Mac(self.root, 'b')

    def tearDown(self):
        self.a.close(); self.b.close(); self.temp.cleanup()

    def join(self, mac, how='merge'):
        status, out = mac.req('POST', '/api/sync', {'folder': str(self.folder), 'join': how})
        self.assertEqual(status, 200, out); return out

    def both(self, rounds=2):
        for _ in range(rounds): self.a.sync(); self.b.sync()

    def test_replace_join_then_changes_travel_both_ways(self):
        bot = self.a.req('POST', '/api/bots', {'name': '企劃', 'provider': 'codex', 'persona': '你很有條理。'})[1]
        self.a.ask(bot['id'], '第一個問題')
        self.a.req('PATCH', '/api/settings', {'rules': '用繁體中文。'})
        note = self.a.req('POST', '/api/knowledge', {'title': '公司地址', 'content': '台北市'})[1]
        self.join(self.a)
        self.assertEqual(self.b.req('POST', '/api/sync', {'folder': str(self.root / 'nope')})[0], 400)
        self.assertEqual(self.b.req('POST', '/api/sync/check', {'folder': str(self.folder)})[1]['others'][0]['name'], self.a.req('GET', '/api/sync')[1]['deviceName'])
        self.join(self.b, 'replace')
        b = self.b.bots()
        self.assertEqual(sorted(b), sorted(self.a.bots()))  # B's own starter Bots made way; no duplicates
        self.assertEqual(b['企劃']['id'], bot['id']); self.assertEqual(b['企劃']['persona'], '你很有條理。')
        self.assertEqual([m['content'] for m in b['企劃']['messages']], ['第一個問題', 'reply'])
        state = self.b.state()
        self.assertEqual(state['settings']['rules'], '用繁體中文。'); self.assertEqual([k['title'] for k in state['knowledge']], ['公司地址'])
        self.assertIn('safety', [x['kind'] for x in self.b.req('GET', '/api/backups')[1]['items']])  # what B had can be put back
        # B continues the conversation, renames the Bot and edits the note; A receives all of it.
        self.b.ask(bot['id'], '第二個問題'); self.b.req('PATCH', '/api/bots/' + bot['id'], {'name': '企劃長'})
        self.b.req('PATCH', '/api/knowledge/' + note['id'], {'content': '新北市'})
        self.both()
        a = self.a.bots()
        self.assertIn('企劃長', a); self.assertEqual([m['content'] for m in a['企劃長']['messages']], ['第一個問題', 'reply', '第二個問題', 'reply'])
        self.assertEqual(self.a.state()['knowledge'][0]['content'], '新北市')
        self.assertEqual(len(a['企劃長']['chats']), 1)  # taking turns is not a conflict: no copy
        # A deletes the note and the Bot; both disappear on B and do not come back.
        self.a.req('DELETE', '/api/knowledge/' + note['id']); self.a.req('DELETE', '/api/bots/' + bot['id'])
        self.both(3)
        self.assertNotIn('企劃長', self.b.bots()); self.assertEqual(self.b.state()['knowledge'], [])
        self.assertNotIn('企劃長', self.a.bots())

    def test_merge_join_keeps_both_sides(self):
        self.a.req('POST', '/api/bots', {'name': '只在A', 'provider': 'codex'}); self.b.req('POST', '/api/bots', {'name': '只在B', 'provider': 'codex'})
        self.a.req('PATCH', '/api/settings', {'rules': 'A 的規則'})
        self.join(self.a); self.join(self.b); self.both()
        for mac in (self.a, self.b):
            self.assertIn('只在A', mac.bots()); self.assertIn('只在B', mac.bots())
            self.assertEqual(mac.state()['settings']['rules'], 'A 的規則')  # the Mac that joins takes the folder's shared settings

    def test_both_wrote_in_one_conversation(self):
        bot = self.a.req('POST', '/api/bots', {'name': '共用', 'provider': 'codex'})[1]
        self.a.ask(bot['id'], '開頭')
        self.join(self.a); self.join(self.b, 'replace'); self.both()
        self.a.ask(bot['id'], 'A 離線時問的'); time.sleep(0.05); self.b.ask(bot['id'], 'B 離線時問的')
        self.a.sync(); time.sleep(0.05); self.b.sync()  # B noticed its change later, so B's version is the newer one
        self.both()
        for mac, title in ((self.a, True), (self.b, False)):
            chats = mac.bots()['共用']
            texts = [[m['content'] for m in (chats['messages'] if c['id'] == chats['chatId'] else c.get('messages') or [])] for c in chats['chats']]
            self.assertIn(['開頭', 'reply', 'B 離線時問的', 'reply'], texts)  # the newer one is the conversation
            self.assertIn(['開頭', 'reply', 'A 離線時問的', 'reply'], texts)  # the older one is kept as a copy, on both Macs
            self.assertEqual(len(texts), 2)
        self.assertTrue(any('這台 Mac 的版本' in c['title'] for c in self.a.bots()['共用']['chats']))

    def test_what_never_travels_and_bad_files(self):
        bot = self.a.req('POST', '/api/bots', {'name': '權限測試', 'provider': 'codex', 'permissionMode': 'bypass'})[1]
        self.a.req('PATCH', '/api/settings', {'permissionMode': 'bypass'})
        self.join(self.a); self.join(self.b, 'replace')
        got = self.b.bots()['權限測試']
        self.assertNotEqual(got.get('permissionMode'), 'bypass'); self.assertEqual(self.b.state()['settings']['permissionMode'], 'manual')
        text = next(self.folder.glob('zook-sync-*.json')).read_text()
        for word in ('permissionMode', 'accessFolder', 'accounts', 'secretId', 'remoteDevices'): self.assertNotIn(word, text)
        # A file someone else put in the folder is only data: wrong shapes are ignored, and it cannot raise permissions.
        now = time.time()
        evil = dict(format=1, device={'name': 'x'}, at='', tombs={'bots:' + bot['id']: now + 10 ** 9}, items={
            'bots:' + bot['id']: dict(t=now + 10 ** 9, h='', p=[], v=dict(name='被改名', persona='x')),
            'bots:../../etc': dict(t=now + 5, h='', p=[], v=dict(name='路徑')),
            'bots:newbot0001': dict(t=now + 5, h='', p=[], v=dict(name='外來的', permissionMode='bypass', access='full', isAdmin=True, provider='nope', enabledMcp=['x'])),
            'chats:newbot0001:c1': dict(t=now + 5, h='', p=[], v=dict(title='t', messages=[{'id': 'm1', 'role': 'system', 'content': 'x'}])),
            'settings:shared': dict(t=now + 5, h='', p=[], v=dict(rules='x' * 20000, sections=[]))})
        (self.folder / 'zook-sync-00000000000000ff.json').write_text(json.dumps(evil))
        (self.folder / 'zook-sync-00000000000000fe.json').write_text('{broken')
        self.b.sync()
        bots = self.b.bots()
        self.assertIn('權限測試', bots)  # a time far in the future is refused, for the change and for the deletion
        self.assertNotIn('路徑', bots)
        new = bots['外來的']
        self.assertEqual((new['permissionMode'], new['access'], new['localLimit'], new['isAdmin'], new['provider'], new['enabledMcp']), ('manual', 'workspace', True, False, '', []))  # held in here, never the file's
        self.assertEqual(new['messages'], [])  # the conversation with a made-up role was refused whole
        self.assertNotEqual(self.b.state()['settings'].get('rules'), 'x' * 20000)
        # Stopping removes this Mac's file and leaves its data alone.
        self.assertEqual(self.b.req('DELETE', '/api/sync')[0], 200)
        self.assertIn('權限測試', self.b.bots())
        self.assertEqual(len([p for p in self.folder.glob('zook-sync-*.json')]), 3)

    def chats(self, mac, name):
        bot = mac.bots()[name]
        return [[m['content'] for m in (bot['messages'] if c['id'] == bot['chatId'] else c.get('messages') or [])] for c in bot['chats']]

    def test_restore_stops_syncing_instead_of_deleting_elsewhere(self):
        self.join(self.a); self.join(self.b, 'replace')
        made = self.b.req('POST', '/api/backups', {})[1]['name']
        bot = self.a.req('POST', '/api/bots', {'name': '備份之後才有', 'provider': 'codex'})[1]
        self.a.ask(bot['id'], '重要對話'); self.both()
        self.assertIn('備份之後才有', self.b.bots())
        out = self.b.req('POST', '/api/backups/%s/restore' % made, {})[1]
        self.assertTrue(out['syncStopped']); self.assertFalse(self.b.req('GET', '/api/sync')[1]['on'])
        self.both(3)
        self.assertIn('備份之後才有', self.a.bots())  # the older copy on B did not turn into deletions on A
        self.assertEqual(self.chats(self.a, '備份之後才有'), [['重要對話', 'reply']])

    def test_rejoining_keeps_what_was_written_meanwhile(self):
        bot = self.a.req('POST', '/api/bots', {'name': '常用', 'provider': 'codex'})[1]
        other = self.a.req('POST', '/api/bots', {'name': 'B會刪掉的', 'provider': 'codex'})[1]
        self.a.ask(bot['id'], '開頭'); self.a.req('PATCH', '/api/settings', {'rules': '原本的規則'})
        self.join(self.a); self.join(self.b, 'replace'); self.both()
        self.a.req('DELETE', '/api/sync')
        self.a.ask(bot['id'], 'A 停止同步後問的')
        self.b.ask(bot['id'], 'B 這邊問的'); self.b.req('DELETE', '/api/bots/' + other['id']); self.b.req('PATCH', '/api/settings', {'rules': ''}); self.b.sync()
        self.join(self.a, 'merge'); self.both()
        texts = self.chats(self.a, '常用')
        self.assertIn(['開頭', 'reply', 'A 停止同步後問的', 'reply'], texts); self.assertIn(['開頭', 'reply', 'B 這邊問的', 'reply'], texts)
        self.assertIn('B會刪掉的', self.a.bots())  # joining never deletes
        self.assertEqual(self.a.state()['settings']['rules'], '原本的規則')
        self.assertIn('safety', [x['kind'] for x in self.a.req('GET', '/api/backups')[1]['items']])

    def test_a_fast_clock_elsewhere_does_not_undo_new_messages(self):
        bot = self.a.req('POST', '/api/bots', {'name': '時鐘', 'provider': 'codex'})[1]
        self.a.ask(bot['id'], '一'); self.join(self.a); self.join(self.b, 'replace'); self.both()
        path = next(p for p in self.folder.glob('zook-sync-*.json') if self.a.req('GET', '/api/sync')[1]['deviceName'] and json.loads(p.read_text())['items'].get('bots:' + bot['id']))
        mine = [p for p in self.folder.glob('zook-sync-*.json')]
        # A third Mac whose clock is twelve hours ahead says the same conversation changed "later".
        data = json.loads(mine[0].read_text()); key = next(k for k in data['items'] if k.startswith('chats:' + bot['id']))
        ahead = dict(format=1, device={'name': '快鐘'}, at='', tombs={}, items={key: dict(data['items'][key], t=time.time() + 43200)})
        (self.folder / 'zook-sync-00000000000000aa.json').write_text(json.dumps(ahead))
        self.a.sync()
        self.a.ask(bot['id'], '二'); self.a.sync(); self.a.ask(bot['id'], '三'); self.a.sync(); self.a.sync()
        self.assertEqual(self.chats(self.a, '時鐘'), [['一', 'reply', '二', 'reply', '三', 'reply']])  # no bouncing back, no copies

    def test_a_file_cannot_take_admin_or_break_a_conversation(self):
        self.join(self.a)
        admin = next(b for b in self.a.state()['bots'] if b['isAdmin']); now = time.time()
        bot = self.a.req('POST', '/api/bots', {'name': '對話', 'provider': 'codex'})[1]; self.a.ask(bot['id'], '原本'); self.a.sync()
        chat = self.a.bots()['對話']['chatId']
        deep = self.folder / 'zook-sync-00000000000000fd.json'; deep.write_text('[' * 100000)
        evil = dict(format=1, device={'name': 'x'}, at='', tombs={}, items={
            'bots:' + admin['id']: dict(t=now + 5, h='', p=[], v=dict(name=admin['name'], isAdmin=False)),
            'bots:zzzboss00001': dict(t=now + 5, h='', p=[], v=dict(name='外來總管', isAdmin=True)),
            'chats:%s:%s' % (bot['id'], chat): dict(t=now + 5, h='', p=[], v=dict(title='t', messages=[{'id': 'm1', 'role': 'user', 'content': 'x', 'attachments': [1]}])),
            'chats:%s:c2' % bot['id']: dict(t=now + 5, h='', p=[], v=dict(title='t', messages=[{'id': 'm2', 'role': 'user', 'content': 'x', 'weird': float('nan')}]))})
        (self.folder / 'zook-sync-00000000000000ff.json').write_text(json.dumps(evil))
        out = self.a.sync()
        self.assertEqual(out['lastError'], '')  # the unreadable file did not stop the round
        bots = self.a.bots()
        self.assertTrue(bots[admin['name']]['isAdmin']); self.assertFalse(bots['外來總管']['isAdmin'])
        self.assertEqual(self.chats(self.a, '對話')[0], ['原本', 'reply'])  # the malformed version was refused whole
        self.assertNotIn('NaN', json.dumps(self.a.state()))
        self.a.ask(bot['id'], '還能繼續')


if __name__ == '__main__':
    unittest.main()
