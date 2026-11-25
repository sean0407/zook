# -*- coding: utf-8 -*-
"""Extra Antigravity accounts: agy only moves its sign-in with HOME, so each account gets its own home folder with the user's
everyday folders linked in. Zook's own checks keep using the real home folder."""
import http.client, importlib.util, json, os, pwd, re, shlex, shutil, signal, subprocess, sys, tempfile, threading, time, unittest
from unittest import mock
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


class FakeHost:
    """`security` on the user's login keychain, as agykeychain._agy_host runs it: (exit code, output); 44 means no such item."""
    def __init__(self): self.items, self.calls, self.fail, self.ready = {}, [], '', True

    def __call__(self, args, command=None):
        self.calls.append((args, command)); words = shlex.split(command) if command else list(args)
        if self.fail in ('all', words[0]): return 51, ''
        assert words[-1] == pwd.getpwuid(os.getuid()).pw_dir + '/Library/Keychains/login.keychain-db', words  # always named
        assert words[words.index('-s') + 1] == 'Zook Antigravity keychain'
        who = words[words.index('-a') + 1]
        if words[0] == 'add-generic-password': self.items[who] = words[words.index('-w') + 1]; return 0, ''
        if words[0] == 'find-generic-password': return (0, self.items[who] + '\n') if who in self.items else (44, '')
        if words[0] == 'delete-generic-password': return (0, '') if self.items.pop(who, None) else (44, '')
        raise AssertionError(words)

class Base(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.home = fake_home(self.root); self.old_home = os.environ.get('HOME'); os.environ['HOME'] = str(self.home)
        os.environ.pop('ZOOK_SECRETS_DIR', None); self.host = FakeHost(); self.m._agy_host = self.host  # the real path, never the user's own keychain
        self.m.agy_host_ready = lambda: self.host.ready
        self.store = self.m.Store(self.root / 'data'); self.account = dict(id='a' * 32, provider='antigravity', name='工作', type='login')
        self.store.data['accounts'] = [self.account, dict(id='c' * 32, provider='codex', name='C', type='login')]

    def tearDown(self):
        os.environ['HOME'] = self.old_home; self.temp.cleanup()


class Units(Base):
    def test_home_links_everyday_folders_and_nothing_sensitive(self):
        folder = self.m.agy_account_home(self.account['id'])
        self.assertEqual(folder, self.root / 'data/accounts' / self.account['id'])
        for name in LINKED: self.assertEqual(os.readlink(str(folder / name)), str(self.home / name))
        self.assertTrue((folder / 'Library').is_dir() and not (folder / 'Library').is_symlink())  # never the whole Library
        self.assertEqual(sorted(p.name for p in (folder / 'Library').iterdir()), ['Keychains', 'Mobile Documents'])
        self.assertEqual(os.readlink(str(folder / 'Library/Mobile Documents')), str(self.home / 'Library/Mobile Documents'))
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(LINKED + ['Library']))
        for name in ('.ssh', '.config', '.aws'): self.assertFalse(os.path.lexists(str(folder / name)))
        self.assertFalse((folder / 'Library/Keychains').is_symlink())  # its own keychain folder, never the user's
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
        self.assertEqual([p.name for p in (folder / 'Library').iterdir()], ['Keychains'])
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
            gate.SCRATCH = re.compile(r'(?!)')  # this fake home is in the Mac's temporary folder: judge it as the user's real files (decisions #28)
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


def security(home, *args):
    """`security` as agy runs it (agy saves its sign-in through /usr/bin/security); a timeout means macOS showed a dialog."""
    return subprocess.run(['/usr/bin/security'] + list(args), env=dict(os.environ, HOME=str(home)), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)


class Keychain(Base):
    """Each extra account gets its own keychain, so agy's sign-in no longer makes macOS ask for a missing keychain."""
    def user_keychains(self):
        real = pwd.getpwuid(os.getuid()).pw_dir
        return [security(real, *a).stdout for a in (['list-keychains', '-d', 'user'], ['default-keychain', '-d', 'user'])]

    def kc(self, folder): return folder / 'Library/Keychains/zook-agy.keychain-db'

    def test_own_keychain_made_unlocked_and_never_on_a_command_line(self):
        before, calls, real_run = self.user_keychains(), [], subprocess.run
        def run(args, *a, **k): calls.append((list(args), dict(k.get('env') or {}))); return real_run(args, *a, **k)
        with mock.patch('subprocess.run', run): folder = self.m.agy_account_home(self.account['id'])
        keychains = folder / 'Library/Keychains'; secret = self.host.items[self.account['id']]
        self.assertEqual(len(secret), 64); self.assertTrue(self.kc(folder).is_file())
        self.assertEqual(os.readlink(str(keychains / 'login.keychain-db')), 'zook-agy.keychain-db')
        self.assertIn(str(self.kc(folder)), security(folder, 'default-keychain').stdout)
        self.assertEqual(security(folder, 'show-keychain-info', str(self.kc(folder))).stderr.split()[-1], 'no-timeout')
        self.assertEqual(security(folder, 'add-generic-password', '-U', '-s', 'antigravity', '-a', 'x', '-w', 'tok').returncode, 0)  # no dialog
        for args, env in calls + [(list(a or []), {}) for a, _ in self.host.calls]:
            self.assertFalse(any(secret in x for x in args + list(env.values())), args)  # stdin only
        for path in folder.rglob('*'):
            if path.is_file() and not path.is_symlink() and path.name != 'zook-agy.keychain-db': self.assertNotIn(secret, path.read_text(errors='ignore'))
        self.assertFalse(any(secret in v for v in self.m.provider_env('antigravity', self.account).values()))  # never in agy's environment
        self.assertEqual(self.user_keychains(), before)  # the user's search list and default keychain stay as they were
        # Locked again (after a restart, say): the next run unlocks it with the same password, read again from the login keychain.
        self.assertEqual(security(folder, 'lock-keychain', str(self.kc(folder))).returncode, 0)
        self.m._agy_keychain_cache.clear(); self.m.provider_env('antigravity', self.account)
        self.assertEqual(security(folder, 'find-generic-password', '-s', 'antigravity', '-a', 'x', '-w').stdout.strip(), 'tok')
        self.assertEqual(self.host.items[self.account['id']], secret)

    def test_a_password_that_cannot_be_read_now_changes_nothing(self):
        folder = self.m.agy_account_home(self.account['id']); data = self.kc(folder).read_bytes(); secret = self.host.items[self.account['id']]
        self.m._agy_keychain_cache.clear(); self.host.fail = 'all'  # the login keychain is locked, refused or timed out
        with self.assertRaises(RuntimeError): self.m.provider_env('antigravity', self.account)  # agy is not started
        cli = self.root / 'bin/agy'; cli.parent.mkdir(exist_ok=True); cli.write_text('#!/bin/sh\n'); cli.chmod(0o755)
        self.m.find_cli = lambda provider: str(cli)  # a Mac without agy (CI) must reach the keychain check too
        with self.assertRaises(RuntimeError): self.m.terminal_login_script('antigravity', self.account)
        self.assertEqual(self.kc(folder).read_bytes(), data); self.assertEqual(self.host.items[self.account['id']], secret)
        self.assertEqual(sorted(p.name for p in (folder / 'Library/Keychains').iterdir() if not p.name.startswith('.fl')), ['login.keychain-db', 'zook-agy.keychain-db'])
        # Could not store a new one: nothing half made is left.
        shutil.rmtree(str(folder / 'Library/Keychains')); self.host.items.clear(); self.host.fail = 'add-generic-password'
        with self.assertRaises(RuntimeError): self.m.agy_account_home(self.account['id'])
        self.assertFalse(os.path.lexists(str(self.kc(folder))))

    def test_older_accounts_get_one_and_nothing_is_deleted(self):
        folder = self.m.account_dir(self.account['id']); keychains = folder / 'Library/Keychains'; keychains.mkdir(parents=True)
        (keychains / 'login.keychain-db').write_text('an earlier sign-in')  # left by the sign-in before this release
        (folder / 'Library/Preferences').mkdir(); (folder / 'Library/Preferences/com.apple.security.plist').write_text('elsewhere')
        self.m.agy_account_home(self.account['id'])
        names = sorted(p.name for p in keychains.iterdir() if not p.name.startswith('.fl'))
        self.assertEqual(names[:2], ['login.keychain-db', 'login.keychain-db.zook-old-' + names[1].rsplit('-', 1)[-1]])
        self.assertEqual((keychains / names[1]).read_text(), 'an earlier sign-in')
        self.assertEqual([p.read_text() for p in (folder / 'Library/Preferences').iterdir()], ['elsewhere'])  # kept beside, not in use
        self.assertIn(str(self.kc(folder)), security(folder, 'default-keychain').stdout)
        # Its password surely gone (not merely unreadable): a new keychain, the old one kept beside.
        first = self.host.items.pop(self.account['id']); self.m._agy_keychain_cache.clear()
        self.m.agy_account_home(self.account['id']); self.assertNotEqual(self.host.items[self.account['id']], first)
        self.assertEqual(len([p for p in keychains.iterdir() if p.name.startswith('zook-agy.keychain-db.zook-old-')]), 1)
        self.assertEqual(security(folder, 'add-generic-password', '-U', '-s', 'antigravity', '-a', 'x', '-w', 'tok').returncode, 0)

    def test_two_starts_at_once_agree_on_one_password(self):
        errors = []
        def start():
            try: self.m.agy_account_home(self.account['id'])
            except Exception as e: errors.append(e)
        threads = [threading.Thread(target=start) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])
        folder = self.root / 'data/accounts' / self.account['id']
        self.assertEqual(security(folder, 'lock-keychain', str(self.kc(folder))).returncode, 0)
        self.assertEqual(security(folder, 'unlock-keychain', '-p', self.host.items[self.account['id']], str(self.kc(folder))).returncode, 0)

    def test_quotes_in_the_data_folder(self):
        self.m.Store(self.root / "O'Brien x" / 'data'); self.store = None
        self.m._active['data']['accounts'] = [self.account]
        folder = self.m.agy_account_home(self.account['id'])
        self.assertIn("O'Brien x", str(folder)); self.assertIn(str(self.kc(folder)), security(folder, 'default-keychain').stdout)

    def test_no_such_item_counts_only_from_a_login_keychain_that_is_there(self):
        folder = self.m.agy_account_home(self.account['id']); data = self.kc(folder).read_bytes()
        self.host.items.clear(); self.host.ready = False; self.m._agy_keychain_cache.clear()  # "no such item" from a missing keychain file
        with self.assertRaises(RuntimeError): self.m.agy_account_home(self.account['id'])
        self.assertEqual(self.kc(folder).read_bytes(), data); self.assertEqual(self.host.items, {})
        self.assertFalse([p for p in (folder / 'Library/Keychains').iterdir() if 'zook-old' in p.name])

    def removed(self):
        self.store.data['accounts'] = [a for a in self.store.data['accounts'] if a['id'] != self.account['id']]

    def test_removal_ends_its_agy_and_forgets_everything_or_says_why(self):
        folder = self.m.agy_account_home(self.account['id']); (folder / '.zook-login').mkdir(); secret = self.host.items[self.account['id']]
        signing = subprocess.Popen(['/bin/sh', '-c', 'trap "" TERM; /bin/sleep 60'], cwd=str(folder / '.zook-login'))  # a Terminal sign-in that ignores SIGTERM
        app = type('App', (), {})(); self.removed()
        self.host.fail = 'delete-generic-password'
        self.assertIn('鑰匙圈', self.m.agy_account_remove(app, self.account['id']))
        self.assertEqual(signing.wait(timeout=1), -signal.SIGKILL)  # already gone when removal went on
        self.assertTrue(self.kc(folder).is_file()); self.assertEqual(self.host.items[self.account['id']], secret)  # put back: still opens
        self.host.fail = ''
        with mock.patch('os.rename', side_effect=OSError('busy')):  # the folder cannot go: the password stays
            self.assertIn('資料夾', self.m.agy_account_remove(app, self.account['id']))
        self.assertEqual(self.host.items[self.account['id']], secret); self.assertTrue(self.kc(folder).is_file())
        def slow(*a, **k): raise subprocess.TimeoutExpired('lsof', 30)
        with mock.patch('subprocess.run', slow): self.assertIn('Antigravity', self.m.agy_account_remove(app, self.account['id']))
        self.assertEqual(self.host.items[self.account['id']], secret); self.assertTrue(folder.exists())
        self.assertEqual(self.m.agy_account_remove(app, self.account['id']), '')
        self.assertFalse(folder.exists()); self.assertNotIn(self.account['id'], self.host.items)
        with self.assertRaises(RuntimeError): self.m.agy_account_home(self.account['id'])  # a late quota check does not bring it back
        self.assertFalse(folder.exists()); self.assertNotIn(self.account['id'], self.host.items)

    def test_another_zook_still_holding_the_account_does_not_make_it_again(self):
        folder = self.m.agy_account_home(self.account['id'])
        self.assertEqual(self.m.agy_account_remove(type('App', (), {})(), self.account['id']), '')  # removed by the other Zook
        self.assertIsNotNone(self.m.find_account(self.account['id']))  # still in this one's memory
        with self.assertRaises(RuntimeError): self.m.agy_account_home(self.account['id'])
        self.assertFalse(folder.exists()); self.assertNotIn(self.account['id'], self.host.items)

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
        kept = self.root / 'secrets' / ('agy-keychain-' + work['id']); self.assertTrue(kept.exists())
        self.assertEqual(self.req('POST', '/api/accounts/antigravity/profiles/delete', {'account': work['id']})[0], 200)
        self.assertFalse(folder.exists()); self.assertEqual((self.home / 'Desktop/keep.txt').read_text(), 'mine')
        self.assertFalse(kept.exists())  # its keychain password goes with it


if __name__ == '__main__': unittest.main()
