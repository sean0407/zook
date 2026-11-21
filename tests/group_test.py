import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'

# Fake CLI: answers as whichever Bot the group prompt says is speaking.
FAKE = r'''#!/usr/bin/env python3
import re, sys, time
s = sys.stdin.read()
name = re.search(r'現在輪到你（(.+?)）回覆', s)
name = name.group(1) if name else 'solo'
if 'SLOW' in s: time.sleep(30)
if 'ALLPASS' in s: print('PASS'); sys.exit(0)
if 'LOOP' in s:
    print('@Beta 換你' if name == 'Alpha' else '@Alpha 換你'); sys.exit(0)
if name == 'Host':
    if '本次目標與產出' in s: print('@Alpha：查資料\n@Beta：檢查 Alpha 的假設')
    elif '討論到此結束' in s: print('總結：共識與下一步')
    else: print('@Beta：Alpha 認為可行，你同意嗎？')
    sys.exit(0)
if 'MODERATED' in s and name in ('Alpha', 'Beta') and '你看不到他們的內容' in s:
    time.sleep(0.6); print(name + ' 獨立作答' + (' LEAK' if '獨立作答' in s else '')); sys.exit(0)
if 'MODERATED' in s and name in ('Alpha', 'Beta') and '最多 4 個重點' in s: print(name + ' 回應'); sys.exit(0)
if name == 'Alpha': print('交給 @Beta 檢查' if 'HANDOFF' in s else 'Alpha 回覆')
elif name == 'Beta': print('Beta 完成')
elif name == 'Gamma': print('PASS')
else: print('solo')
'''


class GroupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x')
        (self.root / 'bin').mkdir(); cli = self.root / 'bin/codex'; cli.write_text(FAKE); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + os.environ['PATH'], ZOOK_NO_INTRO='1')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.ids = {}
        for name in ('Alpha', 'Beta', 'Gamma'):
            status, bot = self.req('POST', '/api/bots', {'name': name, 'provider': 'codex'})
            self.assertEqual(status, 201); self.ids[name] = bot['id']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5)
        self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def group(self, *names):
        status, group = self.req('POST', '/api/groups', {'botIds': [self.ids[n] for n in names]})
        self.assertEqual(status, 201, group); return group

    def wait_idle(self, gid, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            group = self.req('GET', '/api/groups/' + gid)[1]['group']
            if group['status'] == 'idle': return group
            time.sleep(0.2)
        self.fail('group did not finish')

    def speakers(self, group):
        names = {v: k for k, v in self.ids.items()}
        return [(names.get(m.get('botId'), m['role']), m['content']) for m in group['messages'] if m['role'] != 'user']

    def test_validation_and_default_name(self):
        self.assertEqual(self.req('POST', '/api/groups', {'botIds': [self.ids['Alpha']]})[0], 400)
        self.assertEqual(self.req('POST', '/api/groups', {'botIds': [self.ids['Alpha'], 'missing']})[0], 400)
        group = self.group('Alpha', 'Beta')
        self.assertEqual(group['name'], 'Alpha、Beta')
        status, renamed = self.req('PATCH', '/api/groups/' + group['id'], {'name': '審稿小組'})
        self.assertEqual((status, renamed['name']), (200, '審稿小組'))

    def test_broadcast_hides_pass_and_keeps_order(self):
        group = self.group('Alpha', 'Beta', 'Gamma')
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '大家好'})[0], 202)
        self.assertEqual(self.speakers(self.wait_idle(group['id'])), [('Alpha', 'Alpha 回覆'), ('Beta', 'Beta 完成')])

    def test_all_pass_leaves_a_note(self):
        group = self.group('Alpha', 'Beta')
        self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': 'ALLPASS'})
        spoken = self.speakers(self.wait_idle(group['id']))
        self.assertEqual([s[0] for s in spoken], ['system'])

    def test_mention_targets_only_that_bot(self):
        group = self.group('Alpha', 'Beta', 'Gamma')
        self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '@Beta 請處理'})
        self.assertEqual(self.speakers(self.wait_idle(group['id'])), [('Beta', 'Beta 完成')])

    def test_handoff_from_bot_reply(self):
        group = self.group('Alpha', 'Beta', 'Gamma')
        self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '@Alpha HANDOFF'})
        self.assertEqual(self.speakers(self.wait_idle(group['id'])), [('Alpha', '交給 @Beta 檢查'), ('Beta', 'Beta 完成')])

    def test_turn_limit_stops_loops(self):
        group = self.group('Alpha', 'Beta')
        self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '@Alpha LOOP'})
        spoken = self.speakers(self.wait_idle(group['id'], 40))
        self.assertEqual(len([s for s in spoken if s[0] != 'system']), 8)
        self.assertEqual(spoken[-1][0], 'system')

    def test_stop_and_busy_guards(self):
        group = self.group('Alpha', 'Beta')
        self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '@Alpha SLOW'})
        time.sleep(0.5)
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': 'again'})[0], 409)
        self.req('PATCH', '/api/settings', {'queueWhenBusy': False})  # with the waiting line off, a busy Bot refuses as it always did
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.ids['Alpha'], 'content': 'hi'})[0], 409)
        self.assertEqual(self.req('DELETE', '/api/groups/' + group['id'])[0], 409)
        status, stopped = self.req('POST', '/api/groups/%s/stop' % group['id'], {})
        self.assertEqual((status, stopped['status']), (200, 'idle'))
        state = self.req('GET', '/api/state')[1]
        self.assertEqual(state['groups'][0]['messages'][-1]['status'], 'cancelled')
        self.assertEqual(self.req('DELETE', '/api/groups/' + group['id'])[0], 200)

    def test_admin_hosts_and_members_discuss(self):
        status, host = self.req('POST', '/api/bots', {'name': 'Host', 'provider': 'codex'}); self.ids['Host'] = host['id']
        self.assertEqual(self.req('PATCH', '/api/bots/' + host['id'], {'isAdmin': True})[0], 200)
        group = self.group('Host', 'Alpha', 'Beta')
        self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': 'MODERATED 研究一下'})
        started = time.time()
        spoken = self.speakers(self.wait_idle(group['id'], 40))
        self.assertEqual(spoken, [('Host', '@Alpha：查資料\n@Beta：檢查 Alpha 的假設'), ('Alpha', 'Alpha 獨立作答'), ('Beta', 'Beta 獨立作答'),
                                  ('Host', '@Beta：Alpha 認為可行，你同意嗎？'), ('Beta', 'Beta 回應'), ('Host', '@Beta：Alpha 認為可行，你同意嗎？'),
                                  ('Beta', 'Beta 回應'), ('Host', '總結：共識與下一步')])
        # Naming one Bot still goes straight to that Bot.
        before = len(spoken)
        self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '@Beta 請處理'})
        self.assertEqual([x[0] for x in self.speakers(self.wait_idle(group['id']))[before:]], ['Beta'])

    def test_deleting_bot_leaves_group(self):
        group = self.group('Alpha', 'Beta', 'Gamma')
        self.assertEqual(self.req('DELETE', '/api/bots/' + self.ids['Gamma'])[0], 200)
        state = self.req('GET', '/api/state')[1]
        self.assertEqual(state['groups'][0]['botIds'], [self.ids['Alpha'], self.ids['Beta']])


class MentionTest(unittest.TestCase):
    def test_mentions(self):
        spec = importlib.util.spec_from_file_location('zook_mentions', SERVER)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        bots = [{'id': 'a', 'name': '研究'}, {'id': 'b', 'name': '研究助手'}, {'id': 'c', 'name': 'Dev Bot'}]
        self.assertEqual(m.group_mentions('@研究助手 和 @dev bot 看一下', bots), ['b', 'c'])
        self.assertEqual(m.group_mentions('@研究 先看', bots), ['a'])
        self.assertEqual(m.group_mentions('@所有人 更新', bots), ['a', 'b', 'c'])
        self.assertEqual(m.group_mentions('email a@b.com', bots), [])
        self.assertTrue(m.is_pass(' pass。'))
        self.assertFalse(m.is_pass('I pass this to Beta'))


if __name__ == '__main__': unittest.main()
