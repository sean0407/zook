# -*- coding: utf-8 -*-
"""queue #261, decisions #28 (redone twice after review): a Bot's own scratch files are deleted by Zook's tool zook_clean_scratch,
without asking, and only plain files right in the folder Zook made (<data>/workspaces/<Bot>/.zook-scratch, its identity kept by Zook).
A shell rm is asked as on main, wherever it points, the scratch folder too; so is /tmp. Moving a file into a scratch folder is asked
as a delete. Every test works only inside its own mkdtemp folder."""
import os, re, secrets, shutil, stat, sys, tempfile, threading, time, types, unittest, unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import zook_gate as g  # noqa: E402


def scratch_module(logged):
    ns = {'os': os, 're': re, 'stat': stat, 'time': time, 'threading': threading, 'secrets': secrets,
          'log_activity': lambda store, kind, text, by='': logged.append((kind, text, by))}
    exec(compile((ROOT / 'backend' / 'zook' / 'scratch.py').read_text(encoding='utf-8'), 'scratch.py', 'exec'), ns)
    return ns


class Base(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix='zk261-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.ws = os.path.join(self.base, 'workspaces', 'bot1'); os.makedirs(self.ws)
        self.scratch = os.path.join(self.ws, '.zook-scratch'); os.mkdir(self.scratch, 0o700)
        info = os.lstat(self.scratch); self.ident = '%d:%d' % (info.st_dev, info.st_ino)
        self.env = unittest.mock.patch.dict(os.environ, {'ZOOK_SCRATCH': self.scratch, 'ZOOK_SCRATCH_ID': self.ident, 'ZOOK_DATA_DIR': self.base})
        self.env.start(); self.addCleanup(self.env.stop)
        for k in ('ZOOK_GATE_ROOTS', 'ZOOK_GATE_SHELL'): os.environ.pop(k, None)
        cwd = g._CWD[0]; self.addCleanup(lambda: g._CWD.__setitem__(0, cwd)); g._CWD[0] = self.ws
        self.n = 0

    def fresh(self, folder=None, name=None):
        self.n += 1
        p = os.path.join(folder or self.scratch, name or 'f%d.txt' % self.n)
        Path(p).write_text('x'); return p

    def kinds(self, command): return [k for k, _ in g.command_boundaries(command)]

    def asked(self, command): self.assertIn('delete', self.kinds(command), command)


class ShellDeletesAreAsked(Base):
    """Back to main: any rm is asked, the scratch folder's plain files too, with every other reason kept."""
    def test_rm_in_the_scratch_folder_is_asked(self):
        for command in ('rm %s' % self.fresh(), 'rm -f "%s"' % self.fresh(), 'unlink %s' % self.fresh(), '/bin/rm -- %s' % self.fresh(),
                        'rm %s -f' % self.fresh(), "rm '%s'" % self.fresh(name="a'b.txt")):
            self.asked(command)
            with unittest.mock.patch.object(g, 'ask', return_value=False) as ask:
                self.assertFalse(g.decide('Bash', {'command': command}, self.ws)[0], command)
                self.assertIn('delete', [k for k, _ in ask.call_args[0][0]], command)

    def test_secrets_in_the_scratch_folder_keep_their_reason(self):
        for name in ('.env', 'credentials.json'):
            self.assertIn('secret', self.kinds('rm %s' % self.fresh(name=name)), name)

    def test_tmp_is_asked(self):
        own = tempfile.mkdtemp(dir='/tmp', prefix='zk261-'); self.addCleanup(shutil.rmtree, own, True)
        self.asked('rm %s' % self.fresh(own))
        self.asked('d=$(mktemp -d); rm -f "$d/a.json"')


class MovesIntoScratch(Base):
    def test_moving_a_file_into_scratch_is_a_delete(self):
        s = self.scratch
        other = os.path.join(self.base, 'workspaces', 'bot2', '.zook-scratch'); os.makedirs(other); self.fresh(other, 'a')
        for command in ('mv ~/Documents/r.docx %s/' % s, 'mv ~/a.txt %s/a.txt' % s, 'mv -f r.docx %s' % s, 'mv -- -r.docx %s/' % s,
                        'mv ~/a .zook-scratch/', 'cd %s && mv ~/a .zook-scratch/' % self.ws, 'builtin cd %s; mv ~/a x' % s, 'command cd %s; mv ~/a x' % s,
                        'cd /; cd %s; mv ~/a .zook-scratch/x' % self.ws, 'cd %s; mv ~/a x' % s, '%s; mv ~/a x' % s,
                        'cd foo; mv ~/a x', 'cd -; mv ~/a x', 'popd; mv ~/a x', 'cd $D; mv ~/a x', 'env -C %s mv ~/a y' % s,
                        'mv -t %s ~/a' % s, 'mv --target-directory=%s ~/a' % s, 'mv -ft %s ~/a' % s, 'gmv -t %s ~/a' % s,
                        'ls ~/old | xargs mv -t %s' % s, 'echo r | xargs -I {} mv {} %s/' % s, 'find ~ -name r -exec mv {} %s/ \\;' % s,
                        'mv ~/a $D', 'mv ~/a %s/*' % self.ws, 'mv ~/a {%s,x}' % s, 'mv ~/a %s/.ZOOK-SCRATCH/' % self.ws,
                        'mv %s/a %s/' % (other, s), 'git mv r.docx %s/r.docx' % s, 'git -C ~/p mv -f a .zook-scratch/', 'git -C ~/p mv a b'):
            self.asked(command)

    def test_a_link_named_like_the_folder_is_not_already_scratch(self):
        docs = os.path.join(self.base, 'docs'); os.makedirs(docs)
        fake = os.path.join(self.base, 'x', '.zook-scratch'); os.makedirs(os.path.dirname(fake)); os.symlink(docs, fake)
        self.asked('mv %s/r.docx %s/' % (fake, self.scratch))

    def test_other_moves_are_not(self):
        p = self.fresh()
        for command in ('mv %s %s.old' % (p, p), 'mv ~/a.txt ~/b.txt', 'mv a.txt b.txt', 'cd ~/proj && mv a.txt b.txt', 'mv /tmp/a /tmp/b',
                        'mv ~/a /tmp/', 'rsync -at ~/a ~/b', 'zip /tmp/a.zip ~/r.docx', 'mv -- -a b', 'git mv a b'):
            self.assertNotIn('delete', self.kinds(command), command)

    def test_tools_that_remove_their_sources_are_asked_wherever_they_go(self):
        for command in ('tar --remove-files -cf /tmp/x.tar ~/x', 'gtar --remove-files -cf x.tar ~/a', 'rsync -a --delete ~/e/ ~/dir/',
                        'rsync -a --remove-source-files ~/Documents/ ~/Backup/', 'zip -m ~/a.zip ~/r.docx', 'zip -9m ~/a.zip ~/r'):
            self.asked(command)
        for command in ('node -e "require(\'fs\').renameSync(\'a\', \'b\')"', 'swift -e "try FileManager.default.moveItem(atPath: p, toPath: t)"'):
            self.assertIn('unclear', self.kinds(command), command)


class HiddenCommands(unittest.TestCase):
    def test_commands_behind_shell_words_and_wrappers_are_read(self):
        kinds = lambda c: [k for k, _ in g.command_boundaries(c)]
        for command in ('if true; then rm ~/a; fi', 'x && { rm ~/a; }', '! rm ~/a', 'for f in a; do rm ~/a; done', 'while true; do rm ~/a; done',
                        'echo x | xargs -I {} rm {}', 'echo x | xargs -n 1 rm', 'echo x | xargs -tn 1 rm', 'nice -n 5 rm ~/a', 'env -u X rm ~/a',
                        'noglob rm ~/a', 'timeout -s KILL 5 rm ~/a', 'coproc rm ~/x', 'repeat 1 rm ~/x', 'coproc foo { rm ~/a; }', 'function f { rm ~/a; }; f'):
            self.assertIn('delete', kinds(command), command)
        for command in ('$(echo rm) ~/a', '`echo rm` ~/a', '"$(echo rm)" ~/a', 'd= $(echo rm) ~/a', 'env -S "rm ~/a"'):
            self.assertIn('unclear', kinds(command), command)
        self.assertIn('secret', kinds('cat ~/.aws$(printf /credentials)'))  # what $( ) prints stays a word of its own, as on main
        self.assertEqual(kinds('d=$(date +%s); echo $d'), [])


class CleanTool(Base):
    def setUp(self):
        super().setUp(); self.logged = []; self.ns = scratch_module(self.logged)

    def clean(self, names): return self.ns['clean_scratch'](self.scratch, self.ident, names)

    def test_deletes_plain_files_of_the_folder(self):
        a, b = self.fresh(name='a.py'), self.fresh(name='報告 草稿.json')
        self.assertEqual(self.clean(['a.py', '報告 草稿.json', 'gone.txt']), (['a.py', '報告 草稿.json'], ['gone.txt（不存在）']))
        self.assertFalse(os.path.exists(a) or os.path.exists(b))

    def test_names_with_a_path_are_refused_and_nothing_is_deleted(self):
        keep = self.fresh(name='keep.txt'); user = self.fresh(self.ws, 'user.txt')
        for names in (['../user.txt'], ['..'], ['.'], ['/etc/hosts'], [user], ['sub/a.txt'], ['.env'], ['.hidden'], [''], ['a\nb'], [' keep.txt'],
                      ['keep.txt', '../user.txt'], [], 'keep.txt', [1], ['x'] * 51):
            with self.assertRaises(RuntimeError, msg=repr(names)): self.clean(names)
        self.assertTrue(os.path.exists(keep) and os.path.exists(user))

    def test_links_folders_and_hard_links_are_kept(self):
        user = self.fresh(self.ws, 'user.txt'); os.symlink(user, os.path.join(self.scratch, 'link.txt'))
        os.symlink(self.ws, os.path.join(self.scratch, 'dirlink'))
        os.mkdir(os.path.join(self.scratch, 'sub')); self.fresh(os.path.join(self.scratch, 'sub'), 'inner.txt')
        other = self.fresh(self.ws, 'other.txt'); os.link(other, os.path.join(self.scratch, 'hard.txt'))
        deleted, kept = self.clean(['link.txt', 'dirlink', 'sub', 'hard.txt'])
        self.assertEqual(deleted, []); self.assertEqual(len(kept), 4)
        for p in ('link.txt', 'dirlink', 'sub/inner.txt', 'hard.txt'): self.assertTrue(os.path.lexists(os.path.join(self.scratch, p)), p)
        self.assertTrue(os.path.exists(user) and os.path.exists(other))

    def test_a_replaced_folder_is_refused(self):
        p = self.fresh(name='a.txt')
        os.rename(self.scratch, self.scratch + '-away'); os.mkdir(self.scratch); self.fresh(name='a.txt')
        with self.assertRaises(RuntimeError): self.clean(['a.txt'])  # same path, another folder
        self.assertTrue(os.path.exists(p))
        shutil.rmtree(self.scratch); os.symlink(self.scratch + '-away', self.scratch)
        with self.assertRaises(RuntimeError): self.clean(['a.txt'])  # a link to the very folder: never followed
        self.assertTrue(os.path.exists(self.scratch + '-away/a.txt'))
        os.unlink(self.scratch)
        with self.assertRaises(RuntimeError): self.clean(['a.txt'])  # gone

    def test_the_tool_is_never_asked_and_is_recorded(self):
        runtime = types.SimpleNamespace(_schema=lambda name, desc, props, req=(), ro=True: {'name': name, 'annotations': {'readOnlyHint': ro}})
        self.assertEqual(self.ns['scratch_tools'](object(), {'name': 'B'}, runtime, None), [])
        [(schema, run, need)] = self.ns['scratch_tools'](object(), {'name': '小幫手'}, runtime, (self.scratch, self.ident))
        self.assertEqual((schema['name'], need, schema['annotations']['readOnlyHint']), ('zook_clean_scratch', False, False))  # not offered while planning
        self.fresh(name='a.py')
        self.assertEqual(run({'names': ['a.py']}), {'deleted': ['a.py']})
        self.assertEqual(len(self.logged), 1); self.assertIn('小幫手', self.logged[0][1]); self.assertIn('a.py', self.logged[0][1])
        self.assertEqual(run({'names': ['a.py']}), {'deleted': [], 'notDeleted': ['a.py（不存在）']}); self.assertEqual(len(self.logged), 1)

    def test_the_note_points_to_the_tool_not_rm(self):
        note = self.ns['scratch_note']((self.scratch, self.ident))
        self.assertIn(self.scratch, note); self.assertIn('zook_clean_scratch', note); self.assertIn('不要用 rm', note)
        self.assertEqual(self.ns['scratch_note'](None), '')


class ZookMakesTheFolder(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix='zk261-')))
        self.addCleanup(shutil.rmtree, str(self.base), True)
        (self.base / 'workspaces' / 'bot1').mkdir(parents=True)
        self.ns = scratch_module([]); self.store = types.SimpleNamespace(dir=self.base)
        self.folder = str(self.base / 'workspaces/bot1/.zook-scratch')

    def make(self, env=None):
        env = {} if env is None else env
        return self.ns['scratch_env'](self.store, 'bot1', env), env

    def test_made_once_and_kept(self):
        made, env = self.make()
        info = os.lstat(self.folder)
        self.assertEqual(made, (self.folder, '%d:%d' % (info.st_dev, info.st_ino)))
        self.assertEqual(env, {'ZOOK_SCRATCH': self.folder, 'ZOOK_SCRATCH_ID': made[1]})
        Path(self.folder, 'a.txt').write_text('x')
        again, env2 = self.make()
        self.assertEqual(again, made); self.assertTrue(Path(self.folder, 'a.txt').exists())
        self.assertEqual([p.name for p in (self.base / 'workspaces/bot1').iterdir()], ['.zook-scratch'])  # no leftover temporary folder

    def test_a_folder_put_in_its_place_is_moved_aside_never_deleted(self):
        made, _ = self.make()
        os.rename(self.folder, str(self.base / 'away')); docs = self.base / 'docs'; docs.mkdir(); (docs / 'keep.txt').write_text('x')
        os.symlink(str(docs), self.folder)
        again, _ = self.make()
        self.assertNotEqual(again[1], made[1])
        self.assertTrue(os.path.isdir(self.folder) and not os.path.islink(self.folder)); self.assertTrue((docs / 'keep.txt').exists())
        self.assertEqual(len(list((self.base / 'workspaces/bot1').glob('.zook-scratch-old-*'))), 1)
        Path(self.folder, 'n.txt').write_text('x')
        self.assertEqual(self.ns['clean_scratch'](self.folder, again[1], ['n.txt']), (['n.txt'], []))

    def test_the_identity_is_the_folder_put_in_place(self):
        """The identity comes from the folder Zook opened; one swapped in at the path before it is put there is never recorded."""
        real_rename = os.rename
        def swap(src, dst):
            if os.path.basename(str(src)).startswith('.zook-scratch-new-'):
                os.mkdir(dst); Path(dst, 'user.txt').write_text('x')  # someone's folder appears at the path first
            return real_rename(src, dst)
        with unittest.mock.patch.object(self.ns['os'], 'rename', side_effect=swap):
            made, env = self.make({'ZOOK_SCRATCH': '/x', 'ZOOK_SCRATCH_ID': '1:2'})
        self.assertIsNone(made); self.assertEqual(env, {})  # nothing inherited is left either
        self.assertTrue(Path(self.folder, 'user.txt').exists())
        self.assertFalse((self.base / 'tools/scratch/bot1').exists())
        self.assertEqual([p.name for p in (self.base / 'workspaces/bot1').iterdir()], ['.zook-scratch'])

    def test_a_damaged_record_touches_nothing(self):
        made, _ = self.make(); Path(self.folder, 'a.txt').write_text('x')
        record = self.base / 'tools/scratch/bot1'
        for content in (b'\xff\xfe', b'not an id'):
            record.write_bytes(content)
            again, env = self.make()
            self.assertIsNone(again); self.assertEqual(env, {})
            self.assertTrue(Path(self.folder, 'a.txt').exists())
            self.assertEqual(os.lstat(self.folder).st_ino, int(made[1].split(':')[1]))


if __name__ == '__main__': unittest.main()
