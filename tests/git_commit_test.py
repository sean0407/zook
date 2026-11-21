# -*- coding: utf-8 -*-
"""提交到 git: Zook commits for a Bot that works in a chosen folder, without running anything the Bot could have planted."""
import importlib.util, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_git_commit', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def git(folder, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.run(['git', '-c', 'user.name=Tester', '-c', 'user.email=t@example.com'] + list(args), cwd=str(folder), capture_output=True, text=True, env=env, check=True).stdout


class GitCommit(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.repo = self.root / 'proj'; self.repo.mkdir(); git(self.repo, 'init', '-q')
        git(self.repo, 'config', 'user.name', 'Tester'); git(self.repo, 'config', 'user.email', 't@example.com')
        (self.repo / 'a.txt').write_text('one\n'); git(self.repo, 'add', '-A'); git(self.repo, 'commit', '-q', '-m', 'first')

    def tearDown(self): self.temp.cleanup()

    def test_changes_are_committed_as_the_user_without_hooks(self):
        hook = self.repo / '.git/hooks/pre-commit'; hook.write_text('#!/bin/sh\ntouch "%s"\nexit 1\n' % (self.root / 'hook-ran')); hook.chmod(0o755)
        (self.repo / 'a.txt').write_text('two\n'); (self.repo / 'b.txt').write_text('new\n')
        result = self.m.git_commit(self.repo, '修好 a 並新增 b')
        self.assertTrue(result['committed']); self.assertEqual(sorted(result['files']), ['a.txt', 'b.txt']); self.assertEqual(result['author'], 'Tester')
        self.assertIn('修好 a 並新增 b', git(self.repo, 'log', '-1', '--format=%s'))
        self.assertFalse((self.root / 'hook-ran').exists())  # hooks never run

    def test_nothing_to_commit_says_so(self):
        self.assertEqual(self.m.git_commit(self.repo, 'x'), {'committed': False, 'reason': '沒有變更可以提交。'})

    def test_settings_that_run_programs_are_refused(self):
        for key, value in (('filter.x.clean', 'touch /tmp/zook-should-not-run'), ('core.fsmonitor', 'true'), ('include.path', '/tmp/x'), ('gpg.program', '/bin/echo'),
                           ('hook.e.command', 'touch /tmp/zook-should-not-run'), ('alias.x', '!touch /tmp/zook-should-not-run')):
            with self.subTest(key=key):
                git(self.repo, 'config', key, value); (self.repo / 'a.txt').write_text(key)
                with self.assertRaises(RuntimeError) as caught: self.m.git_commit(self.repo, 'x')
                self.assertIn('請你自己 commit', str(caught.exception))
                git(self.repo, 'config', '--unset', key)

    def test_only_a_plain_repository_of_this_folder(self):
        plain = self.root / 'plain'; plain.mkdir()
        with self.assertRaises(RuntimeError): self.m.git_commit(plain, 'x')  # no repository here; git does not look upwards
        inside = self.repo / 'sub'; inside.mkdir(); (inside / 'c.txt').write_text('c')
        with self.assertRaises(RuntimeError): self.m.git_commit(inside, 'x')  # a folder inside a repository is not one
        linked = self.root / 'linked'; linked.mkdir(); (linked / '.git').symlink_to(self.repo / '.git')
        with self.assertRaises(RuntimeError): self.m.git_commit(linked, 'x')
        (self.repo / '.git/commondir').write_text('../elsewhere\n')
        with self.assertRaises(RuntimeError) as caught: self.m.git_commit(self.repo, 'x')
        self.assertIn('共用', str(caught.exception))

    def test_plain_settings_still_commit(self):
        git(self.repo, 'remote', 'add', 'origin', 'https://example.com/x.git'); (self.repo / 'a.txt').write_text('three\n')
        self.assertTrue(self.m.git_commit(self.repo, 'ok')['committed'])

    def test_links_inside_git_are_refused(self):
        outside = self.root / 'rc'; outside.write_text('')
        logs = self.repo / '.git/logs/HEAD'; logs.unlink(); logs.symlink_to(outside)
        (self.repo / 'a.txt').write_text('x')
        with self.assertRaises(RuntimeError) as caught: self.m.git_commit(self.repo, 'x ;touch PWNED')
        self.assertIn('捷徑或連結', str(caught.exception)); self.assertEqual(outside.read_text(), '')
        logs.unlink(); os.link(str(outside), str(logs))  # a hard link to a file elsewhere
        with self.assertRaises(RuntimeError): self.m.git_commit(self.repo, 'x')
        self.assertEqual(outside.read_text(), '')

    def test_a_nested_repository_is_not_added(self):
        other = self.root / 'other'; other.mkdir(); git(other, 'init', '-q'); (other / 'o.txt').write_text('o'); git(other, 'add', '-A'); git(other, 'commit', '-q', '-m', 'o')
        nested = self.repo / 'peek'; nested.mkdir(); (nested / '.git').write_text('gitdir: %s\n' % (other / '.git'))
        with self.assertRaises(RuntimeError) as caught: self.m.git_commit(self.repo, 'x')
        self.assertIn('另一個 git 專案', str(caught.exception))
        self.assertEqual(git(self.repo, 'diff', '--cached', '--name-only'), '')  # nothing left staged
        self.assertEqual(git(self.repo, 'log', '--format=%s'), 'first\n')

    def test_offered_only_outside_the_whole_mac(self):
        class R:
            @staticmethod
            def _schema(name, *a, **k): return {'name': name}
        self.assertEqual(self.m.git_tools(None, {}, 'full', self.repo, R, 'codex'), [])
        self.assertEqual(self.m.git_tools(None, {}, 'folder', self.root, R, 'codex'), [])  # not a repository
        self.assertEqual(self.m.git_tools(None, {}, 'folder', self.repo, R, 'claude'), [])  # its own tools can write .git
        tools = self.m.git_tools(None, {}, 'folder', self.repo, R, 'codex')
        self.assertEqual((tools[0][0]['name'], tools[0][2]), ('zook_git_commit', True))  # asks first as 主動性 says

    def test_zook_file_tools_cannot_write_git_data(self):
        sys.path.insert(0, str(SERVER.parent)); import runtime
        session = runtime.RuntimeSession([], ['builtin:workspace'], False, self.repo, lambda *a: True, lambda e: None)
        before = (self.repo / '.git/config').read_text()
        for path in ('.git/config', '.GIT/hooks/pre-commit', 'sub/.git/config'):
            out = session.call('zook_workspace_write', {'path': path, 'content': '[core]\n'})
            self.assertTrue(out.get('isError'), path); self.assertIn('.git', out['content'][0]['text'])
        self.assertEqual((self.repo / '.git/config').read_text(), before); self.assertFalse((self.repo / '.git/hooks/pre-commit').exists())
        self.assertFalse(session.call('zook_workspace_write', {'path': 'ok.txt', 'content': 'x'}).get('isError'))  # other files still work


if __name__ == '__main__': unittest.main()
