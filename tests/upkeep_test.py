# -*- coding: utf-8 -*-
"""Backups, the activity record, usage budgets and the rules every Bot follows."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, os, sys
s = sys.stdin.read()
here = os.path.dirname(sys.argv[0])
open(os.path.join(here, os.path.basename(sys.argv[0]) + '.prompt'), 'w').write(s + '\\n'.join(sys.argv[1:]))
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'ok from ' + os.path.basename(sys.argv[0])}}))
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 600000, 'output_tokens': 300000}}))
'''


class UpkeepTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.start()
        self.bot = self.req('POST', '/api/bots', {'name': '小幫手', 'provider': 'codex'})[1]

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, dict({'Authorization': 'Bearer ' + self.token}, **(headers or {})))
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def ask(self, text='hi', bot=None):
        status, out = self.req('POST', '/api/chat', {'botId': (bot or self.bot)['id'], 'content': text})
        self.assertEqual(status, 202, out)
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + out['jobId'])[1]
            if job['status'] != 'running': return job
            time.sleep(0.1)
        self.fail('no reply')

    def bots(self): return [b['name'] for b in self.req('GET', '/api/state')[1]['bots']]

    def test_backup_restore_round_trip(self):
        status, made = self.req('POST', '/api/backups', {})
        self.assertEqual(status, 201)
        self.assertEqual(oct((self.root / 'data/backups' / made['name']).stat().st_mode & 0o777), '0o600')
        self.req('DELETE', '/api/bots/' + self.bot['id'])
        self.req('POST', '/api/bots', {'name': '之後才加的', 'provider': 'codex'})
        self.assertNotIn('小幫手', self.bots())
        status, out = self.req('POST', '/api/backups/%s/restore' % made['name'], {})
        self.assertEqual(status, 200, out)
        self.assertIn('小幫手', self.bots()); self.assertNotIn('之後才加的', self.bots())
        # What was there before the restore was kept, so the restore can be undone.
        kinds = [x['kind'] for x in self.req('GET', '/api/backups')[1]['items']]
        self.assertIn('safety', kinds)
        self.req('POST', '/api/backups/%s/restore' % out['safety'], {})
        self.assertIn('之後才加的', self.bots())
        # The restored data is what is on disk, and it is used after a restart.
        self.stop(); self.start()
        self.assertIn('之後才加的', self.bots())

    def test_restore_refuses_bad_names_and_files(self):
        for name in ('../swarmr.json', 'zook-manual-1.json', 'nope'):
            self.assertIn(self.req('POST', '/api/backups/%s/restore' % name.replace('/', '%2F'), {})[0], (400, 404))
        self.assertEqual(self.req('POST', '/api/backups/file', {'data': {'bots': 'x'}})[0], 400)
        self.assertEqual(self.req('POST', '/api/backups/file', {'data': {'bots': [{'id': 1}], 'settings': {}}})[0], 400)
        (self.root / 'data/backups').mkdir(exist_ok=True)
        bad = self.root / 'data/backups/zook-manual-20200101-000000.json'; bad.write_text('{not json')
        before = self.bots()
        self.assertEqual(self.req('POST', '/api/backups/%s/restore' % bad.name, {})[0], 400)
        self.assertEqual(self.bots(), before)
        self.assertEqual(self.req('DELETE', '/api/backups/' + bad.name)[0], 200)
        self.assertFalse(bad.exists())

    def test_file_backup_and_pairing_is_kept(self):
        data = self.req('POST', '/api/export', {})[1]
        data['bots'][0]['name'] = '從別台來的'; data['remoteDevices'] = [{'id': 'x', 'name': '別人的手機'}]
        status, made = self.req('POST', '/api/backups/file', {'data': data})
        self.assertEqual(status, 201, made)
        self.assertEqual(self.req('POST', '/api/backups/%s/restore' % made['name'], {})[0], 200)
        state = self.req('GET', '/api/state')[1]
        self.assertIn('從別台來的', [b['name'] for b in state['bots']])
        self.assertEqual(state['remoteDevices'], [])  # this Mac's own pairing is not replaced by the file's

    def test_daily_copies_are_trimmed(self):
        folder = self.root / 'data/backups'; folder.mkdir(exist_ok=True)
        for day in range(1, 29): (folder / ('zook-manual-202001%02d-000000.json' % day)).write_text('{}')
        self.req('POST', '/api/backups', {})
        names = sorted(p.name for p in folder.glob('zook-manual-*.json'))
        self.assertEqual(len(names), 20); self.assertNotIn('zook-manual-20200101-000000.json', names)

    def test_activity_records_changes_not_messages(self):
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'persona': '你很簡潔。', 'pinned': True})
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'pinned': False})  # layout only: not recorded
        self.req('PATCH', '/api/settings', {'permissionMode': 'auto'})
        self.ask('這句話不該出現在紀錄裡')
        self.req('DELETE', '/api/bots/' + self.bot['id'])
        out = self.req('GET', '/api/activity')[1]
        texts = [x['text'] for x in out['items']]
        self.assertEqual(texts[:4], ['刪除 Bot「小幫手」', '變更設定：主動性', '修改 Bot「小幫手」：人格檔案', '新增 Bot「小幫手」'])
        self.assertFalse(any('這句話' in t for t in texts))
        self.assertTrue(all(x['by'] == '這台 Mac' for x in out['items']))
        only = self.req('GET', '/api/activity?kind=setting')[1]['items']
        self.assertEqual([x['text'] for x in only], ['變更設定：主動性'])
        self.assertEqual(oct((self.root / 'data/activity.jsonl').stat().st_mode & 0o777), '0o600')
        # A failed request leaves no line.
        self.req('PATCH', '/api/settings', {'permissionMode': 'nope'})
        self.assertEqual(len(self.req('GET', '/api/activity')[1]['items']), len(texts))

    def test_rules_reach_every_bot(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'rules': 'x' * 10001})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'rules': '一律用繁體中文回答。'})[0], 200)
        self.ask()
        prompt = (self.root / 'bin/codex.prompt').read_text()
        self.assertIn('【固定規則】', prompt); self.assertIn('一律用繁體中文回答。', prompt)
        self.req('PATCH', '/api/settings', {'rules': ''})
        self.ask()
        self.assertNotIn('【固定規則】', (self.root / 'bin/codex.prompt').read_text())

    def test_budget_counts_and_stops(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'budgets': {'codex': 123}})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'budgets': {'nope': 1000000}})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'budgets': {'codex': 1000000}, 'budgetOver': 'stop'})[0], 200)
        self.assertEqual(self.ask()['status'], 'completed')  # 900,000 of 1,000,000
        view = next(x for x in self.req('GET', '/api/budget')[1]['items'] if x['id'] == 'codex')
        self.assertEqual((view['used'], view['limit'], view['state']), (900000, 1000000, 'near'))
        self.assertEqual(self.ask()['status'], 'completed')  # now over
        job = self.ask()
        self.assertEqual(job['status'], 'failed'); self.assertIn('用量預算已用完', job['error'])
        notices = self.req('GET', '/api/notifications?after=0')[1]['items']
        self.assertEqual([n['body'][:11] for n in notices], ['這個月的用量已達預算的', '這個月的用量預算已用完'])
        # Only a warning: replies go on.
        self.req('PATCH', '/api/settings', {'budgetOver': 'warn'})
        self.assertEqual(self.ask()['status'], 'completed')
        # No ceiling: the entry is removed.
        self.req('PATCH', '/api/settings', {'budgets': {'codex': 0}})
        self.assertEqual(self.req('GET', '/api/state')[1]['settings']['budgets'], {})

    def test_budget_switches_to_backup_model(self):
        cli = self.root / 'bin/claude'; cli.write_text('#!/usr/bin/env python3\nimport json\nprint(json.dumps({"result": "ok from claude", "usage": {"input_tokens": 5, "output_tokens": 5}}))\n'); cli.chmod(0o755)
        self.req('PATCH', '/api/settings', {'budgets': {'codex': 1000000}, 'budgetOver': 'switch', 'fallbacks': ['claude']})
        self.ask(); self.ask()
        job = self.ask()
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual((job.get('fallback') or {}).get('reason'), '用量預算已用完')

    def test_skill_template_becomes_a_shared_skill(self):
        items = self.req('GET', '/api/skill-templates')[1]['items']
        self.assertGreaterEqual(len(items), 8); self.assertFalse(any(x['added'] for x in items))
        status, made = self.req('POST', '/api/skills/template', {'id': 'meeting-notes'})
        self.assertEqual((status, made['name']), (201, '會議記錄整理'))
        text = (self.root / 'data/skills' / made['folder'] / 'SKILL.md').read_text()
        self.assertTrue(text.startswith('---\nname: 會議記錄整理\n')); self.assertIn('待辦事項', text)
        self.assertEqual(self.req('POST', '/api/skills/template', {'id': 'meeting-notes'})[0], 400)  # not twice
        self.assertEqual(self.req('POST', '/api/skills/template', {'id': '../x'})[0], 400)
        self.assertTrue(next(x for x in self.req('GET', '/api/skill-templates')[1]['items'] if x['id'] == 'meeting-notes')['added'])
        skills = self.req('GET', '/api/integrations')[1]['skills']
        mine = next(x for x in skills if x['name'] == '會議記錄整理')
        self.assertEqual((mine['source'], mine.get('origin')), ('zook', 'template'))
        self.assertIn('從範本加入 Skill「會議記錄整理」', [x['text'] for x in self.req('GET', '/api/activity')[1]['items']])
        self.assertEqual(self.req('DELETE', '/api/skills/' + made['id'])[0], 200)
        self.assertFalse((self.root / 'data/skills' / made['folder']).exists())

    def test_long_task_is_marked_and_announced(self):
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'x', 'long': 'yes'})[0], 400)
        status, out = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '整理全部資料', 'long': True})
        self.assertEqual(status, 202)
        end = time.time() + 15
        while time.time() < end and self.req('GET', '/api/jobs/' + out['jobId'])[1]['status'] == 'running': time.sleep(0.1)
        job = self.req('GET', '/api/jobs/' + out['jobId'])[1]
        self.assertTrue(job['long']); self.assertEqual(job['status'], 'completed')
        end = time.time() + 5
        while time.time() < end and not self.req('GET', '/api/notifications?after=0')[1]['items']: time.sleep(0.1)
        notices = self.req('GET', '/api/notifications?after=0')[1]['items']
        self.assertEqual([(n['title'], n['body'], n['kind'], n['targetId']) for n in notices], [('小幫手', '長任務完成：ok from codex', 'bot', self.bot['id'])])
        self.ask('一般訊息')  # an ordinary reply is not announced
        self.assertEqual(len(self.req('GET', '/api/notifications?after=0')[1]['items']), 1)


if __name__ == '__main__':
    unittest.main()
