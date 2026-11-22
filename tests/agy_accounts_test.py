# -*- coding: utf-8 -*-
"""Extra Antigravity accounts: agy only moves its sign-in with HOME, so each account gets its own home folder with the user's
everyday folders linked in. Zook's own checks keep using the real home folder."""
import http.client, importlib.util, json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
LINKED = ['Desktop', 'Documents', 'Downloads', 'Pictures', 'Movies', 'Music']
# Shaped after agy 1.5: `models` asks to sign in when this HOME has no sign-in; /usage reads the account's own limits.
AGY = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0]); home = os.environ.get('HOME', '')
signed = os.path.exists(os.path.join(home, '.gemini/antigravity-cli/signed'))
if a == ['--version']: print('1.5.10'); sys.exit(0)
if a == ['models']:
    if not signed: print('Fetching available models...\\nError: Please sign in to view available models. Launch the CLI without arguments to sign in.'); sys.exit(1)
    print('Fetching available models...\\ngemini-3.8-flash-low\\tGemini 3.8 Flash (Low)'); sys.exit(0)
if a[:2] == ['-p', '/usage']:
    left = float(open(os.path.join(home, '.gemini/antigravity-cli/signed')).read() or 1)
    print(json.dumps({'command': {'data': {'groups': [{'name': 'Gemini Models', 'buckets': [{'window': 'weekly', 'remaining_fraction': left, 'reset_time': '2026-11-25T04:26:45Z'}]}]}}})); sys.exit(0)
prompt = json.loads(sys.stdin.readline())['message']['content']
json.dump(dict(args=a, home=home, prompt=prompt), open(os.path.join(here, 'run.json'), 'w'))
print(json.dumps(dict(event='result', result=dict(status='SUCCESS', response='hi from ' + os.path.basename(home)))))
"""


def load():
    spec = importlib.util.spec_from_file_location('zook_agy_accounts', SERVER); m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m); return m


def fake_home(root):
    home = root / 'home'
    for name in LINKED + ['Library/Mobile Documents', 'Library/Keychains', '.ssh', '.config/gh', '.aws']: (home / name).mkdir(parents=True)
    (home / 'Desktop/keep.txt').write_text('mine'); (home / '.ssh/id_ed25519').write_text('secret')
    return home


class Units(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.home = fake_home(self.root); self.old_home = os.environ.get('HOME'); os.environ['HOME'] = str(self.home)
        self.store = self.m.Store(self.root / 'data'); self.account = dict(id='a' * 32, provider='antigravity', name='工作', type='login')
        self.store.data['accounts'] = [self.account, dict(id='c' * 32, provider='codex', name='C', type='login')]

    def tearDown(self):
        os.environ['HOME'] = self.old_home; self.temp.cleanup()

    def test_home_links_everyday_folders_and_nothing_sensitive(self):
        folder = self.m.agy_account_home(self.account['id'])
        self.assertEqual(folder, self.root / 'data/accounts' / self.account['id'])
        for name in LINKED: self.assertEqual(os.readlink(str(folder / name)), str(self.home / name))
        self.assertTrue((folder / 'Library').is_dir() and not (folder / 'Library').is_symlink())  # never the whole Library
        self.assertEqual([p.name for p in (folder / 'Library').iterdir()], ['Mobile Documents'])
        self.assertEqual(os.readlink(str(folder / 'Library/Mobile Documents')), str(self.home / 'Library/Mobile Documents'))
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(LINKED + ['Library']))
        for name in ('.ssh', '.config', '.aws', 'Library/Keychains'): self.assertFalse(os.path.lexists(str(folder / name)))
        self.assertEqual((folder / 'Desktop/keep.txt').read_text(), 'mine')  # ~/Desktop still means the user's own
        # A link pointed elsewhere is put back, a whole-Library link is replaced, a real folder agy made is left alone; a missing one is skipped.
        (folder / 'Desktop').unlink(); os.symlink(str(self.home / '.ssh'), str(folder / 'Desktop'))
        (folder / 'Music').unlink(); (folder / 'Music').mkdir()
        shutil.rmtree(str(folder / 'Library')); os.symlink(str(self.home / 'Library'), str(folder / 'Library'))
        shutil.rmtree(str(self.home / 'Movies')); (folder / 'Movies').unlink()
        self.m.agy_account_home(self.account['id'])
        self.assertEqual(os.readlink(str(folder / 'Desktop')), str(self.home / 'Desktop'))
        self.assertTrue((folder / 'Music').is_dir() and not (folder / 'Music').is_symlink())
        self.assertFalse((folder / 'Library').is_symlink()); self.assertFalse(os.path.lexists(str(folder / 'Movies')))
        self.assertTrue((self.home / 'Library/Keychains').is_dir())
        # A user folder that really leads to keys or the whole Library is not linked; a Library link goes even without iCloud Drive.
        shutil.rmtree(str(self.home / 'Pictures')); os.symlink(str(self.home / '.ssh'), str(self.home / 'Pictures'))
        shutil.rmtree(str(self.home / 'Library/Mobile Documents')); shutil.rmtree(str(folder / 'Library')); os.symlink(str(self.home / 'Library'), str(folder / 'Library'))
        self.m.agy_account_home(self.account['id'])
        self.assertFalse(os.path.lexists(str(folder / 'Pictures'))); self.assertFalse((folder / 'Library').is_symlink())
        self.assertEqual(list((folder / 'Library').iterdir()), [])
        # Removing the account removes the links, never what they point to.
        shutil.rmtree(str(folder)); self.assertEqual((self.home / 'Desktop/keep.txt').read_text(), 'mine'); self.assertTrue((self.home / '.ssh/id_ed25519').exists())

    def test_provider_env_moves_only_agy_home(self):
        env = self.m.provider_env('antigravity', self.account)
        self.assertEqual(env['HOME'], str(self.root / 'data/accounts' / self.account['id']))
        self.assertTrue(os.path.islink(os.path.join(env['HOME'], 'Desktop')))
        self.assertEqual(self.m.provider_env('antigravity')['HOME'], str(self.home))  # the default sign-in: unchanged
        codex = self.m.provider_env('codex', self.store.data['accounts'][1])
        self.assertEqual((codex['HOME'], codex['CODEX_HOME']), (str(self.home), str(self.root / 'data/accounts' / ('c' * 32))))
        self.assertEqual(os.environ['HOME'], str(self.home))  # Zook itself keeps the real home folder
        self.assertTrue(self.m.can_add_login('antigravity')); self.assertFalse(self.m.can_add_login('gemini'))  # Gemini: no change

    def test_access_checks_use_the_real_home(self):
        self.m.provider_env('antigravity', self.account)
        work = self.root / 'data/workspaces/b'; work.mkdir(parents=True)
        self.assertEqual(self.m.bot_access(dict(access='full'), work, 'antigravity'), ('full', self.home))
        self.assertIn(str(self.home) + '/Desktop', self.m.access_note('full', self.home, True))
        settings = json.dumps(self.m.antigravity_settings(True, 'folder', False))  # rules name tools, never a path under home
        self.assertNotIn(str(self.home), settings); self.assertNotIn('~', settings)
        args = self.m.antigravity_args('agy', '', 'standard', True, False, 'folder', self.home / 'Desktop', False)
        self.assertEqual(args[args.index('--add-dir') + 1], str(self.home / 'Desktop'))  # absolute: the same with any HOME
        self.m.prepare_antigravity_folder(work, 'folder', self.home / 'Documents', 100)
        self.assertEqual(sorted(p.name for p in work.iterdir()), ['.agents'])

    def test_a_linked_path_is_judged_as_the_real_one(self):
        folder = self.m.agy_account_home(self.account['id'])
        spec = importlib.util.spec_from_file_location('zook_gate_agy', SERVER.with_name('zook_gate.py')); gate = importlib.util.module_from_spec(spec)
        os.environ['ZOOK_DATA_DIR'] = str(self.root / 'data')
        try:
            spec.loader.exec_module(gate)
            kinds = lambda tool, data: sorted(k for k, _ in gate.boundaries(tool, data, str(self.root)))
            self.assertEqual(kinds('Bash', {'command': 'rm %s' % (folder / 'Desktop/keep.txt')}), kinds('Bash', {'command': 'rm %s' % (self.home / 'Desktop/keep.txt')}))
            self.assertIn('delete', kinds('Bash', {'command': 'rm %s' % (folder / 'Desktop/keep.txt')}))
            self.assertEqual(kinds('Read', {'file_path': str(folder / 'Desktop/keep.txt')}), [])
            self.assertIn('secret', kinds('Read', {'file_path': str(folder / '.gemini/antigravity-cli/x')}))  # the account's own sign-in
        finally: os.environ.pop('ZOOK_DATA_DIR', None)

    def test_kept_cli_is_per_account(self):
        args, cwd = ['agy', '--output-format', 'stream-json'], '/w'
        one, two = self.m.provider_env('antigravity'), self.m.provider_env('antigravity', self.account)
        self.assertNotEqual(self.m.live_mark(args, cwd, one, 'user'), self.m.live_mark(args, cwd, two, 'user'))
        self.assertEqual(self.m.live_mark(args, cwd, two, 'user'), self.m.live_mark(args, cwd, dict(two), 'user'))

    def test_terminal_sign_in_runs_agy_in_the_account_home(self):
        cli = self.root / 'bin/agy'; cli.parent.mkdir(); cli.write_text('#!/bin/sh\n'); cli.chmod(0o755)
        self.m.find_cli = lambda provider: str(cli)
        text = self.m.terminal_login_script('antigravity', self.account).read_text()
        self.assertIn('export HOME=' + str(self.root / 'data/accounts' / self.account['id']), text)
        self.assertTrue(text.rstrip().endswith('exec ' + str(cli)))
        self.assertNotIn('HOME', self.m.terminal_login_script('antigravity').read_text())  # the default sign-in: as before
        with self.assertRaises(ValueError): self.m.terminal_login_script('antigravity', dict(self.account, type='key'))


class Server(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve(); self.home = fake_home(self.root)
        (self.home / '.gemini/antigravity-cli').mkdir(parents=True); (self.home / '.gemini/antigravity-cli/signed').write_text('0.9')
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/agy'; cli.write_text(AGY); cli.chmod(0o755)
        env = dict(os.environ, HOME=str(self.home), PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1',
                   ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        (self.root / 'secrets').mkdir()
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.assertEqual(self.req('POST', '/api/accounts/antigravity/add', {})[0], 200)

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30); c.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d)

    def agy(self, path='/api/accounts'): return next(p for p in self.req('GET', path)[1]['providers'] if p['id'] == 'antigravity')

    def ask(self, bot):
        status, sent = self.req('POST', '/api/chat', {'botId': bot, 'content': 'hello'}); self.assertEqual(status, 202, sent)
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            if job['status'] != 'running': return job
            time.sleep(0.2)
        self.fail('no reply')

    def test_accounts_status_quota_menu_and_runs(self):
        before = self.agy()
        self.assertEqual((before['status'], before['canAddLogin'], before['profiles']), ('logged_in', True, []))
        status, work = self.req('POST', '/api/accounts/antigravity/profiles', {'name': '工作', 'type': 'login'}); self.assertEqual(status, 201, work)
        status, other = self.req('POST', '/api/accounts/antigravity/profiles', {'name': '其他', 'type': 'login'}); self.assertEqual(status, 201)
        folder = self.root / 'data/accounts' / work['id']
        (folder / '.gemini/antigravity-cli').mkdir(parents=True); (folder / '.gemini/antigravity-cli/signed').write_text('0.4')
        # The default sign-in was just checked and cached; each extra account is asked on its own.
        card = self.agy()
        self.assertEqual([(p['name'], p['status']) for p in card['profiles']], [('工作', 'logged_in'), ('其他', 'not_logged_in')])
        self.assertEqual(card['status'], 'logged_in')
        quota = self.agy('/api/quota')
        self.assertEqual(round(quota['quota']['windows'][0]['usedPercent']), 10)
        self.assertEqual([(p['name'], p['noQuotaApi'], round(((p['quota'] or {}).get('windows') or [{}])[0].get('usedPercent', -1))) for p in quota['profiles']], [('工作', False, 60), ('其他', False, -1)])
        self.assertEqual([p.get('autoOn') for p in quota['profiles']], [False, False])  # Antigravity is only picked automatically once turned on
        listed = next(p for p in self.req('GET', '/api/providers')[1]['providers'] if p['id'] == 'antigravity')['accounts']
        self.assertEqual([a['name'] for a in listed], ['工作', '其他'])  # 模型與帳號 in the Bot form
        # A Bot on the extra account runs agy in that account's home; the default one as before. Paths in the prompt are the real home.
        bot = self.req('POST', '/api/bots', {'name': 'A', 'provider': 'antigravity', 'account': work['id'], 'permissionMode': 'bypass', 'access': 'full'})[1]
        self.assertEqual(self.ask(bot['id'])['content'], 'hi from ' + work['id'])
        run = json.loads((self.root / 'bin/run.json').read_text())
        self.assertEqual(run['home'], str(folder)); self.assertIn(str(self.home) + '/Desktop', run['prompt']); self.assertNotIn(str(folder), run['prompt'])
        self.req('PATCH', '/api/bots/' + bot['id'], {'account': ''})
        self.ask(bot['id']); self.assertEqual(json.loads((self.root / 'bin/run.json').read_text())['home'], str(self.home))
        # Removing the account removes its folder and links, never the user's files.
        self.assertTrue(os.path.islink(str(folder / 'Desktop')))
        self.assertEqual(self.req('POST', '/api/accounts/antigravity/profiles/delete', {'account': work['id']})[0], 200)
        self.assertFalse(folder.exists()); self.assertEqual((self.home / 'Desktop/keep.txt').read_text(), 'mine')


if __name__ == '__main__': unittest.main()
