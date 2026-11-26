# -*- coding: utf-8 -*-
"""Backup settings (queue #232, decisions #10): on/off, how often, how many to keep, where, a name for a backup made by hand,
backups that include files, what a restore will lose (#50) and who is busy when a restore has to wait."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import json, sys, time
s = sys.stdin.read()
if 'slow' in s + ' '.join(sys.argv): time.sleep(30)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'ok'}}))
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 10}}))
'''


class Harness:
    tick = '3600'
    files_limit = ''

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK=self.tick, ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        if self.files_limit: self.env['ZOOK_BACKUP_FILES_LIMIT'] = self.files_limit
        self.data = self.root / 'data'
        self.start()
        self.bot = self.req('POST', '/api/bots', {'name': '小幫手', 'provider': 'codex'})[1]

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.data), '--assets', str(self.root / 'assets')],
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

    def backups(self): return self.req('GET', '/api/backups')[1]

    def wait_idle(self):
        end = time.time() + 20
        while time.time() < end:
            out = self.backups()
            if not out.get('running') and not out.get('restoring'): return out
            time.sleep(0.2)
        self.fail('backup still running')


class BackupSettingsTest(Harness, unittest.TestCase):
    def test_settings_have_defaults_and_only_take_choices(self):
        out = self.backups()
        self.assertEqual({k: out['settings'][k] for k in ('auto', 'every', 'keep', 'withFiles')}, dict(auto=True, every='daily', keep=14, withFiles=False))
        self.assertTrue(out['settings']['isDefault']); self.assertEqual(out['settings']['folder'], str((self.data / 'backups').resolve()))
        self.assertEqual(out['choices']['keep'], [3, 7, 14, 30, 60])
        status, s = self.req('PATCH', '/api/settings', {'backup': {'auto': False, 'every': 'weekly', 'keep': 7, 'withFiles': True}})
        self.assertEqual(status, 200, s)
        got = self.backups()['settings']
        self.assertEqual((got['auto'], got['every'], got['keep'], got['withFiles']), (False, 'weekly', 7, True))
        for bad in ({'every': 'hourly'}, {'keep': 5}, {'auto': 'yes'}, {'withFiles': 1}, {'folder': '/tmp'}, 'x'):
            self.assertEqual(self.req('PATCH', '/api/settings', {'backup': bad})[0], 400, bad)
        # The place is only ever one the user picked in the Mac's own chooser, never a path sent in.
        self.assertEqual(self.req('POST', '/api/backups/folder', {'folder': str(self.root)})[0], 400)
        self.assertEqual(self.req('POST', '/api/backups/folder', {'reset': True})[0], 200)

    def test_a_backup_made_by_hand_can_be_named(self):
        status, made = self.req('POST', '/api/backups', {'label': '  搬家前\n備份  '})
        self.assertEqual(status, 201, made)
        item = next(x for x in made['items'] if x['name'] == made['name'])
        self.assertEqual(item['label'], '搬家前 備份'); self.assertFalse(item['hasFiles'])
        self.assertEqual(self.req('POST', '/api/backups', {'label': 'x' * 41})[0], 400)
        self.req('DELETE', '/api/backups/' + made['name'])
        self.assertNotIn(made['name'], json.loads((self.data / 'backups/labels.json').read_text()))

    def test_chosen_folder_is_used_and_older_copies_still_listed(self):
        old = self.req('POST', '/api/backups', {})[1]['name']
        chosen = self.root / 'mine'; chosen.mkdir()
        self.stop()
        data = json.loads((self.data / 'swarmr.json').read_text()); data['settings']['backup'] = {'folder': '/tmp'}  # never read from the data
        (self.data / 'swarmr.json').write_text(json.dumps(data)); (self.data / 'backup-folder.json').write_text(json.dumps({'folder': str(chosen)})); self.start()
        made = self.req('POST', '/api/backups', {})[1]['name']
        self.assertTrue((chosen / 'Zook 備份' / made).is_file())
        names = [x['name'] for x in self.backups()['items']]
        self.assertIn(old, names); self.assertIn(made, names)
        self.assertEqual(self.req('POST', '/api/backups/%s/restore' % old, {})[0], 200)
        # The place belongs to this Mac: a restore keeps it.
        self.assertEqual(self.backups()['settings']['folder'], str((chosen / 'Zook 備份').resolve()))
        # Startup recovery finds the copies in the chosen place, even once Zook's own folder has none left.
        time.sleep(1.1)  # backups are named by the second; the restore above just made one
        newest = self.req('POST', '/api/backups', {'label': '最新'})[1]['name']
        self.stop()
        for p in (self.data / 'backups').glob('zook-*'): p.unlink()
        (self.data / 'swarmr.json').write_text('broken'); self.start()
        self.assertEqual(self.req('GET', '/api/state')[1]['settings']['recovered']['backup'], newest)

    def test_restore_keeps_this_macs_phone_and_backup_settings(self):
        old = self.req('POST', '/api/backups', {})[1]['name']  # made with the defaults
        self.assertEqual(self.req('PATCH', '/api/settings', {'backup': {'auto': False, 'every': 'weekly', 'keep': 7, 'withFiles': False}, 'remoteExpiryDays': 90})[0], 200)
        self.stop()
        data = json.loads((self.data / 'swarmr.json').read_text()); data['settings']['remote'] = {'enabled': False, 'relayUrl': 'https://relay.example.test'}
        (self.data / 'swarmr.json').write_text(json.dumps(data)); self.start()
        before = {k: self.req('GET', '/api/state')[1]['settings'][k] for k in ('remote', 'remoteExpiry', 'backup')}
        self.assertEqual(before['remoteExpiry']['days'], 90); self.assertEqual(before['backup']['every'], 'weekly')
        self.assertEqual(self.req('POST', '/api/backups/%s/restore' % old, {})[0], 200)
        after = self.req('GET', '/api/state')[1]['settings']
        self.assertEqual({k: after[k] for k in ('remote', 'remoteExpiry', 'backup')}, before)

    def test_files_are_included_when_switched_on_without_secrets(self):
        ws = self.data / 'workspaces' / self.bot['id']; ws.mkdir(parents=True, exist_ok=True)
        (ws / '報告.txt').write_text('產出'); (ws / '.env').write_text('KEY=1'); (ws / 'server.pem').write_text('x')
        (ws / '.claude').mkdir(); (ws / '.claude/auth.json').write_text('token')
        outside = self.root / 'outside.txt'; outside.write_text('不該進備份'); os.symlink(str(outside), str(ws / 'link.txt'))
        up = self.data / 'uploads' / 'u1'; up.mkdir(parents=True); (up / 'file').write_text('附件'); (up / 'meta.json').write_text('{}')
        self.assertGreater(self.backups()['filesSize'], 0)
        self.req('PATCH', '/api/settings', {'backup': {'withFiles': True}})
        status, made = self.req('POST', '/api/backups', {'label': '含檔案'})
        self.assertEqual(status, 202, made); self.assertTrue(made['pending'])
        out = self.wait_idle()
        item = next(x for x in out['items'] if x['name'] == made['name'])
        self.assertTrue(item['hasFiles']); self.assertEqual(item['label'], '含檔案')
        path = self.data / 'backups' / made['name']
        self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')
        names = zipfile.ZipFile(str(path)).namelist()
        self.assertIn('data.json', names); self.assertIn('files/workspaces/%s/報告.txt' % self.bot['id'], names); self.assertIn('files/uploads/u1/file', names)
        for leaked in ('.env', 'server.pem', 'auth.json', 'link.txt'): self.assertFalse(any(n.endswith(leaked) for n in names), leaked)
        # Restoring puts back missing files and leaves the ones there alone.
        (ws / '報告.txt').unlink(); (up / 'file').write_text('之後改過')
        self.req('POST', '/api/bots', {'name': '之後才加的', 'provider': 'codex'})
        status, done = self.req('POST', '/api/backups/%s/restore' % made['name'], {})
        self.assertEqual(status, 200, done); self.assertTrue(done['filesPending'])
        self.wait_idle()
        self.assertEqual((ws / '報告.txt').read_text(), '產出'); self.assertEqual((up / 'file').read_text(), '之後改過')
        self.assertNotIn('之後才加的', [b['name'] for b in self.req('GET', '/api/state')[1]['bots']])

    def test_restore_of_files_never_writes_outside(self):
        made = self.req('POST', '/api/backups', {})[1]['name']
        bad = self.data / 'backups' / made.replace('.json.gz', '.zip')
        with zipfile.ZipFile(str(bad), 'w') as z:
            z.writestr('data.json', json.dumps(self.req('POST', '/api/export', {})[1]))
            for name in ('files/../../evil.txt', 'files/workspaces/../../evil2.txt', 'files/other/x.txt', 'files//abs.txt', 'files/workspaces/b/.env', 'files/workspaces/b/ok.txt'):
                z.writestr(name, 'x')
        ws = self.data / 'workspaces' / 'lnk'; (self.data / 'workspaces').mkdir(exist_ok=True); os.symlink(str(self.root), str(ws))
        with zipfile.ZipFile(str(bad), 'a') as z: z.writestr('files/workspaces/lnk/through.txt', 'x')
        status, done = self.req('POST', '/api/backups/%s/restore' % bad.name, {})
        self.assertEqual(status, 200, done); self.wait_idle()
        self.assertTrue((self.data / 'workspaces/b/ok.txt').is_file())
        for gone in (self.root / 'evil.txt', self.data / 'evil.txt', self.data / 'evil2.txt', self.data / 'other', self.data / 'workspaces/b/.env', self.root / 'through.txt'):
            self.assertFalse(gone.exists(), gone)

    def test_preview_says_what_is_lost_and_restore_says_what_happened(self):
        made = self.req('POST', '/api/backups', {})[1]['name']
        self.req('POST', '/api/bots', {'name': '之後才加的', 'provider': 'codex'})
        other = self.req('POST', '/api/bots', {'name': '第二位', 'provider': 'codex'})[1]
        self.req('POST', '/api/groups', {'name': '新群組', 'botIds': [self.bot['id'], other['id']]})
        status, p = self.req('GET', '/api/backups/%s/preview' % made)
        self.assertEqual(status, 200, p)
        self.assertEqual(sorted(p['lost']['bots']), ['之後才加的', '第二位']); self.assertEqual(p['lost']['groups'], ['新群組'])
        self.assertGreaterEqual(p['lost']['chats'], 2)
        self.assertEqual(p['busy'], []); self.assertFalse(p['hasFiles'])
        self.assertEqual(p['backup']['bots'], len([b for b in self.req('GET', '/api/state')[1]['bots']]) - 2)
        self.assertEqual(self.req('GET', '/api/backups/nope/preview')[0], 404)
        status, done = self.req('POST', '/api/backups/%s/restore' % made, {})
        self.assertEqual(status, 200, done)
        self.assertEqual(done['restored']['groups'], 0); self.assertIn('held', done); self.assertTrue(done['safety'].startswith('zook-safety-'))

    def test_busy_restore_names_who_is_busy(self):
        made = self.req('POST', '/api/backups', {})[1]['name']
        job = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'slow please'})[1]
        end = time.time() + 10
        while time.time() < end and not self.req('GET', '/api/backups/%s/preview' % made)[1]['busy']: time.sleep(0.2)
        p = self.req('GET', '/api/backups/%s/preview' % made)[1]
        self.assertEqual([(x['type'], x['name']) for x in p['busy']], [('bot', '小幫手')])
        status, out = self.req('POST', '/api/backups/%s/restore' % made, {})
        self.assertEqual(status, 409); self.assertIn('小幫手', out['error'])
        self.req('POST', '/api/jobs/%s/cancel' % job['jobId'], {'force': True})
        end = time.time() + 15
        while time.time() < end and self.req('GET', '/api/backups/%s/preview' % made)[1]['busy']: time.sleep(0.2)
        self.assertEqual(self.req('POST', '/api/backups/%s/restore' % made, {})[0], 200)

    def test_stop_then_restore_also_stops_what_waits_in_line(self):
        # 停止後還原 (#50③): stopped and restored in one step, so a message waiting behind the stopped reply cannot start in between.
        made = self.req('POST', '/api/backups', {})[1]['name']
        self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'slow one'})
        end = time.time() + 10
        while time.time() < end and not self.req('GET', '/api/backups/%s/preview' % made)[1]['busy']: time.sleep(0.2)
        status, queued = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'slow two'})
        self.assertLess(status, 300, queued)
        status, done = self.req('POST', '/api/backups/%s/restore' % made, {'stop': True})
        self.assertEqual(status, 200, done)
        self.assertEqual([(x['type'], x['name']) for x in done['stopped']], [('bot', '小幫手')])
        time.sleep(1.5)
        self.assertEqual(self.req('GET', '/api/backups/%s/preview' % made)[1]['busy'], [])
        js = (ROOT / 'frontend/js/39-upkeep.js').read_text()
        self.assertIn('stop: true', js); self.assertNotIn('backupStopAll', js)  # the page asks for it in the same request, never stops and waits itself

    def test_backup_section_says_what_is_in_it(self):
        js = (ROOT / 'frontend/js/39-upkeep.js').read_text()
        self.assertIn('記憶', js.split('function backupSection')[1].split('const BUDGET_OVER')[0])
        self.assertIn('不含檔案', js); self.assertIn('在 Finder 顯示', js); self.assertIn('停止後還原', js)
        actions = (ROOT / 'frontend/js/40-actions.js').read_text()
        self.assertNotIn("'Zook-export.json'", actions)


class BackupScheduleTest(Harness, unittest.TestCase):
    tick = '1'

    def autos(self): return sorted(p.name for p in (self.data / 'backups').glob('zook-auto-*'))

    def test_keep_off_and_weekly(self):
        self.req('PATCH', '/api/settings', {'backup': {'auto': False}})
        for p in (self.data / 'backups').glob('zook-auto-*'): p.unlink()
        time.sleep(2.5); self.assertEqual(self.autos(), [])
        folder = self.data / 'backups'; folder.mkdir(exist_ok=True)
        for day in range(1, 6): (folder / ('zook-auto-202001%02d-000000.json' % day)).write_text('{}')
        self.req('PATCH', '/api/settings', {'backup': {'auto': True, 'keep': 3}})
        end = time.time() + 8
        while time.time() < end and len(self.autos()) != 3: time.sleep(0.3)
        self.assertEqual(len(self.autos()), 3); self.assertNotIn('zook-auto-20200101-000000.json', self.autos())
        # Weekly: a copy from two days ago is recent enough.
        self.req('PATCH', '/api/settings', {'backup': {'auto': False}}); time.sleep(1.5)
        for p in (self.data / 'backups').glob('zook-auto-*'): p.unlink()
        two_days = time.strftime('%Y%m%d-%H%M%S', time.localtime(time.time() - 2 * 86400))
        (folder / ('zook-auto-%s.json' % two_days)).write_text('{}')
        self.req('PATCH', '/api/settings', {'backup': {'every': 'weekly', 'auto': True}})
        time.sleep(2.5); self.assertEqual(self.autos(), ['zook-auto-%s.json' % two_days])


class BackupFilesLimitTest(Harness, unittest.TestCase):
    files_limit = '10'

    def test_too_many_files_backs_up_data_only(self):
        ws = self.data / 'workspaces' / self.bot['id']; ws.mkdir(parents=True, exist_ok=True); (ws / 'big.txt').write_text('x' * 100)
        self.req('PATCH', '/api/settings', {'backup': {'withFiles': True}})
        made = self.req('POST', '/api/backups', {})[1]
        out = self.wait_idle()
        names = [x['name'] for x in out['items']]
        self.assertFalse(any(n.endswith('.zip') for n in names)); self.assertTrue(any(n.startswith('zook-manual-') and n.endswith('.json.gz') for n in names))
        self.assertIn('只備份資料', out.get('lastNote') or '')


if __name__ == '__main__':
    unittest.main()
