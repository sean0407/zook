# -*- coding: utf-8 -*-
"""The 各模型使用量 page: usage per account, detection, and installing npm-based CLIs without Node.js."""
import datetime, importlib.util, io, json, sys, tarfile, tempfile, unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))
spec = importlib.util.spec_from_file_location('zook_model_usage', BACKEND / 'server.py'); server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)
spec = importlib.util.spec_from_file_location('zook_cli_installer', BACKEND / 'cli_installer.py'); installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
A = 'a' * 32


class UsagePerAccount(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = server.Store(Path(self.temp.name))
        self.store.data['accounts'] = [dict(id=A, provider='codex', name='Waifdance', type='login')]
        self.bot = self.store.data['bots'][0]
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = lambda i, **u: dict(id=i, botId=self.bot['id'], status='completed', finishedAt=now, usage=dict(provider='codex', input=10, output=5, **u))
        self.store.data['jobs'] += [job('main', account=''), job('extra', account=A)]

    def tearDown(self): self.temp.cleanup()

    def test_each_account_counts_its_own_replies(self):
        self.assertEqual(server.provider_usage(self.store, 'codex')['week']['replies'], 1)
        self.assertEqual(server.provider_usage(self.store, 'codex', A)['week']['tokens'], 15)

    def test_older_replies_follow_the_account_the_bot_uses(self):
        self.bot['account'] = A
        self.store.data['jobs'].append(dict(id='old', botId=self.bot['id'], status='completed', finishedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), usage=dict(provider='codex', input=1, output=1)))
        self.assertEqual(server.provider_usage(self.store, 'codex', A)['week']['replies'], 2)
        self.assertEqual(server.provider_usage(self.store, 'codex')['week']['replies'], 1)

    def test_quota_is_kept_per_account(self):
        app = server.App(('127.0.0.1', 0), self.store, self.temp.name, 't')
        try:
            info = {'rateLimits': {'primary': {'usedPercent': 40, 'windowDurationMins': 300}}}
            app.record_quota('codex', info, A)
            self.assertEqual(self.store.data['quota']['codex@' + A]['windows'][0]['usedPercent'], 40.0)
            self.assertNotIn('codex', self.store.data['quota'])
        finally: app.server_close()


class GeminiAccounts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = server.Store(Path(self.temp.name))

    def tearDown(self): self.temp.cleanup()

    def test_runs_in_any_folder_and_a_key_account_ignores_the_google_sign_in(self):
        self.assertEqual(server.provider_env('gemini')['GEMINI_CLI_TRUST_WORKSPACE'], 'true')
        self.assertNotIn('GEMINI_CLI_TRUST_WORKSPACE', server.provider_env('codex'))
        account = dict(id=A, provider='gemini', name='金鑰', type='key')
        with mock.patch.object(server, 'secret_get', return_value='a-key-for-tests'):
            env = server.provider_env('gemini', account)
        settings = Path(env['GEMINI_CLI_HOME']) / '.gemini/settings.json'
        self.assertEqual(env['GEMINI_API_KEY'], 'a-key-for-tests')
        self.assertEqual(json.loads(settings.read_text())['security']['auth']['selectedType'], 'gemini-api-key')
        self.assertNotIn('a-key-for-tests', settings.read_text())

    def test_account_problems_are_explained(self):
        self.assertIn('API 金鑰', server.cli_issue('Error authenticating: IneligibleTierError: This client is no longer supported'))
        self.assertIn('重新新增', server.cli_issue('API key not valid. Please pass a valid API key.'))
        self.assertEqual(server.cli_issue('network timeout'), '')


class ManagedInstall(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = server.Store(Path(self.temp.name))

    def tearDown(self): self.temp.cleanup()

    def test_gemini_needs_no_node_on_this_mac(self):
        spec = server.P.spec(self.store.data, 'gemini')
        self.assertFalse(spec.get('requires'))
        args = server.install_args('gemini')
        self.assertTrue(args[1].endswith('cli_installer.py')); self.assertIn('@google/gemini-cli', args)
        self.assertEqual(args[args.index('--tools') + 1], str(self.store.dir / 'tools'))

    def test_installed_copy_is_found(self):
        with mock.patch.object(server.P, 'binary_for', return_value=None):
            self.assertIsNone(server.find_cli('gemini'))
            cli = self.store.dir / 'tools/bin/gemini'; cli.parent.mkdir(parents=True); cli.write_text('#!/bin/sh\n'); cli.chmod(0o755)
            self.assertEqual(server.find_cli('gemini'), str(cli))

    def test_the_copy_zook_installed_comes_before_an_older_one(self):
        cli = self.store.dir / 'tools/bin/gemini'; cli.parent.mkdir(parents=True); cli.write_text('#!/bin/sh\n'); cli.chmod(0o755)
        with mock.patch.object(server.P, 'binary_for', return_value='/usr/local/bin/gemini'):
            self.assertEqual(server.find_cli('gemini'), str(cli))

    def test_phone_sees_only_the_main_sign_ins(self):
        import types
        self.store.data['settings']['addedProviders'] = ['codex', 'claude', 'gemini']
        self.store.data['accounts'] = [dict(id=A, provider='claude', name='公司', type='key')]
        fake = types.SimpleNamespace(server=types.SimpleNamespace(store=self.store), device={'id': 'phone'}, codex_live_quota=lambda *a: None)
        status = dict(name='x', status='logged_in', method='', plan='', email='')
        with mock.patch.object(server, 'account_status', return_value=status):
            out = server.Handler.quota(fake)['providers']
        self.assertNotIn('gemini', [p['id'] for p in out])
        self.assertTrue(all(p['profiles'] == [] for p in out))

    def test_bots_start_the_installed_copy(self):
        argv, _ = server.P.command_args(server.P.spec(self.store.data, 'gemini'), 'f', 'hello', '', binary='/private/tools/bin/gemini')
        self.assertEqual(argv, ['/private/tools/bin/gemini', '-p', 'hello'])

    def test_archive_cannot_write_outside_its_folder(self):
        def archive(name, link=None):
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode='w:gz') as t:
                info = tarfile.TarInfo(name)
                if link: info.type = tarfile.SYMTYPE; info.linkname = link
                else: info.size = 1
                t.addfile(info, io.BytesIO(b'x') if not link else None)
            raw.seek(0); return raw
        for bad in (archive('../evil'), archive('/tmp/evil'), archive('node/link', '../../evil')):
            with tempfile.TemporaryDirectory() as d, tarfile.open(fileobj=bad, mode='r:gz') as t:
                with self.assertRaises(RuntimeError): installer.safe_extract(t, Path(d))
        chain = io.BytesIO()
        with tarfile.open(fileobj=chain, mode='w:gz') as t:
            for name, link in (('a/b', '..'), ('a/b/c', '../..')):
                info = tarfile.TarInfo(name); info.type = tarfile.SYMTYPE; info.linkname = link; t.addfile(info)
            info = tarfile.TarInfo('a/b/c/evil.txt'); info.size = 1; t.addfile(info, io.BytesIO(b'x'))
        chain.seek(0)
        with tempfile.TemporaryDirectory() as d, tarfile.open(fileobj=chain, mode='r:gz') as t:
            with self.assertRaises(RuntimeError): installer.safe_extract(t, Path(d) / 'in')
            self.assertFalse((Path(d) / 'evil.txt').exists())
        with tempfile.TemporaryDirectory() as d, tarfile.open(fileobj=archive('node/bin/npm-link', '../lib/npm'), mode='r:gz') as t:
            installer.safe_extract(t, Path(d))

    def test_download_must_match_the_published_checksum(self):
        sums = ('%s  node-v22.1.0-darwin-arm64.tar.gz\n%s  node-v22.1.0-darwin-x64.tar.gz\n' % ('1' * 64, '2' * 64))
        self.assertEqual(installer.pick_node(sums, 'arm64'), ('node-v22.1.0-darwin-arm64.tar.gz', '1' * 64))
        self.assertEqual(installer.pick_node(sums, 'x86_64'), ('node-v22.1.0-darwin-x64.tar.gz', '2' * 64))
        with self.assertRaises(RuntimeError): installer.pick_node('nothing', 'arm64')


if __name__ == '__main__': unittest.main()
