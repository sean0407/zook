# -*- coding: utf-8 -*-
"""queue #261, decisions #28 (narrowed after review): a Bot deletes its own scratch files without asking. Zook makes one folder per
Bot (<data>/workspaces/<Bot>/.zook-scratch) and gives the gate its path and device:inode. Only a line that is nothing but one plain
rm / unlink of written-out paths of plain files right in that very folder, each with one name only, is not asked. /tmp and the Mac's
temporary folder are asked as before (other programs use them too); so is everything else. Moving a file into a scratch folder is
asked as a delete. Every test works only inside its own mkdtemp folder."""
import os, re, shutil, sys, tempfile, types, unittest, unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import zook_gate as g  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix='zk261-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.ws = os.path.join(self.base, 'workspaces', 'bot1'); os.makedirs(self.ws)
        self.scratch = os.path.join(self.ws, '.zook-scratch'); os.mkdir(self.scratch, 0o700)
        info = os.lstat(self.scratch)
        self.env = unittest.mock.patch.dict(os.environ, {'ZOOK_SCRATCH': self.scratch, 'ZOOK_SCRATCH_ID': '%d:%d' % (info.st_dev, info.st_ino),
                                                         'ZOOK_DATA_DIR': self.base})
        self.env.start(); self.addCleanup(self.env.stop)
        for k in ('ZOOK_GATE_ROOTS', 'ZOOK_GATE_SHELL'): os.environ.pop(k, None)
        cwd = g._CWD[0]; self.addCleanup(lambda: g._CWD.__setitem__(0, cwd)); g._CWD[0] = self.ws
        self.n = 0

    def fresh(self, folder=None, name=None):
        """A new plain file of its own (never shared between cases)."""
        self.n += 1
        p = os.path.join(folder or self.scratch, name or 'f%d.txt' % self.n)
        Path(p).write_text('x'); return p

    def kinds(self, command): return [k for k, _ in g.command_boundaries(command)]

    def free(self, command):
        self.assertEqual(g.command_boundaries(command), [], command)  # nothing at all, not even 'unclear'
        with unittest.mock.patch.object(g, 'ask', side_effect=AssertionError('asked: ' + command)):
            self.assertEqual(g.decide('Bash', {'command': command}, self.ws), (True, ''), command)

    def asked(self, command): self.assertIn('delete', self.kinds(command), command)


class FreeDeletes(Base):
    def test_plain_deletes_of_scratch_files_are_not_asked(self):
        for make in (lambda: 'rm %s' % self.fresh(), lambda: 'rm -f "%s"' % self.fresh(), lambda: "rm -fv '%s'" % self.fresh(),
                     lambda: 'unlink %s' % self.fresh(), lambda: '/bin/rm -- %s' % self.fresh(), lambda: 'rm -f -v %s %s' % (self.fresh(), self.fresh()),
                     lambda: 'rm "%s"' % self.fresh(name='報告 草稿.txt'), lambda: 'rm -- %s' % self.fresh(name='-r.txt')):
            command = make()
            self.free(command)

    def test_each_single_change_is_asked(self):
        f = self.fresh
        cases = {
            'another command (;)': lambda: 'rm %s; true' % f(), 'another command (&&)': lambda: 'rm %s && true' % f(),
            'a pipe': lambda: 'true | rm %s' % f(), 'background (&)': lambda: 'rm %s &' % f(), 'a subshell': lambda: '(rm %s)' % f(),
            'command substitution': lambda: 'echo $(rm %s)' % f(), 'backticks': lambda: 'echo `rm %s`' % f(),
            'output redirection': lambda: 'rm %s > /dev/null' % f(), 'stderr redirection': lambda: 'rm %s 2>/dev/null' % f(),
            'a variable': lambda: 'rm "$ZOOK_SCRATCH/%s"' % os.path.basename(f()), 'a wildcard *': lambda: (f(), 'rm %s/*' % self.scratch)[1],
            'a wildcard ?': lambda: 'rm %s?' % f()[:-1], 'braces': lambda: 'rm %s/{%s,x}' % (self.scratch, os.path.basename(f())),
            'a ..': lambda: 'rm %s/../.zook-scratch/%s' % (self.scratch, os.path.basename(f())), 'a /./': lambda: 'rm %s/./%s' % (self.scratch, os.path.basename(f())),
            'a double slash': lambda: 'rm %s//%s' % (self.scratch, os.path.basename(f())), 'cd': lambda: 'cd %s && rm %s' % (self.scratch, os.path.basename(f())),
            'a relative path': lambda: 'rm .zook-scratch/%s' % os.path.basename(f()), 'a tilde': lambda: 'rm ~/%s' % os.path.basename(f()),
            'a backslash': lambda: 'rm %s\\ ' % f(), 'a comment': lambda: 'rm %s # x' % f(), 'a newline': lambda: 'rm %s\ntrue' % f(),
            'a tab': lambda: 'rm\t%s' % f(), 'unbalanced quote': lambda: 'rm "%s' % f(), 'mixed quotes': lambda: 'rm "%s\'' % f(),
            '-r': lambda: 'rm -r %s' % f(), '-P': lambda: 'rm -P %s' % f(), '-i': lambda: 'rm -i %s' % f(), '-d': lambda: 'rm -d %s' % f(),
            'sudo': lambda: 'sudo rm %s' % f(), 'VAR=': lambda: 'FOO=1 rm %s' % f(), 'command': lambda: 'command rm %s' % f(),
            'env': lambda: 'env rm %s' % f(), 'xargs': lambda: 'echo %s | xargs rm' % f(), 'bash -c': lambda: 'bash -c "rm %s"' % f(),
            'shred': lambda: 'shred %s' % f(), 'trash': lambda: 'trash %s' % f(), 'rmdir': lambda: 'rmdir %s' % self.scratch,
            'the folder itself': lambda: 'rm -rf %s' % self.scratch, 'the folder as a file': lambda: 'rm %s' % self.scratch,
            'a trailing slash': lambda: 'rm %s/' % f(), 'not there': lambda: 'rm %s/gone.txt' % self.scratch,
            'another file too': lambda: 'rm %s %s' % (f(), f(self.ws)), 'a file in the workspace': lambda: 'rm %s' % f(self.ws),
            'a file in a temporary folder': lambda: 'rm %s' % f(self.base), 'a sub folder file': lambda: (os.makedirs(self.scratch + '/sub', exist_ok=True), 'rm %s' % f(self.scratch + '/sub'))[1],
            'another case': lambda: 'rm %s/.ZOOK-SCRATCH/%s' % (self.ws, os.path.basename(f())), '=word': lambda: 'rm =%s' % f(),
            'no file': lambda: 'rm -f', 'only --': lambda: 'rm --', 'unlink option': lambda: 'unlink -f %s' % f(),
            './rm': lambda: './rm %s' % f(), 'rm as variable': lambda: '$R %s' % f(),
        }
        for why, make in cases.items():
            command = make()
            self.assertNotEqual(g.command_boundaries(command), [], why)

    def test_a_link_in_the_folder_is_asked(self):
        target = self.fresh(self.base, 'user.txt')
        link = os.path.join(self.scratch, 'link.txt'); os.symlink(target, link)
        self.asked('rm %s' % link)

    def test_a_hard_link_is_asked(self):
        outside = self.fresh(self.base, 'user.txt')
        inside = os.path.join(self.scratch, 'hard.txt'); os.link(outside, inside)
        self.asked('rm %s' % inside)

    def test_a_folder_in_the_folder_is_asked(self):
        os.mkdir(os.path.join(self.scratch, 'd'))
        self.asked('rm %s/d' % self.scratch)

    def test_a_folder_zook_did_not_make_is_asked(self):
        p = self.fresh()
        os.rename(self.scratch, self.scratch + '-moved'); os.mkdir(self.scratch); os.rename(self.scratch + '-moved/' + os.path.basename(p), p)
        self.asked('rm %s' % p)  # same path, another folder: its identity does not match

    def test_a_link_in_place_of_the_folder_is_asked(self):
        p = self.fresh()
        elsewhere = os.path.join(self.base, 'elsewhere'); os.rename(self.scratch, elsewhere); os.symlink(elsewhere, self.scratch)
        self.asked('rm %s' % p)

    def test_without_zook_s_folder_nothing_is_free(self):
        p = self.fresh()
        for env in ({'ZOOK_SCRATCH': ''}, {'ZOOK_SCRATCH_ID': ''}, {'ZOOK_SCRATCH_ID': '1:2'}, {'ZOOK_SCRATCH': self.ws}):
            with unittest.mock.patch.dict(os.environ, env):
                self.asked('rm %s' % p)

    def test_tmp_and_the_system_temporary_folder_are_asked_again(self):
        for folder in ('/tmp', tempfile.gettempdir()):
            own = tempfile.mkdtemp(dir=folder, prefix='zk261-'); self.addCleanup(shutil.rmtree, own, True)
            p = self.fresh(own)
            self.asked('rm %s' % p)
        self.asked('d=$(mktemp -d); rm -f "$d/a.json"')


class MovesIntoScratch(Base):
    def test_moving_a_file_into_scratch_is_a_delete(self):
        s = self.scratch
        for command in ('mv ~/Documents/r.docx %s/' % s, 'mv ~/a.txt %s/a.txt' % s, 'mv -f r.docx %s' % s, 'mv -- -r.docx %s/' % s,
                        'mv ~/a .zook-scratch/', 'cd %s && mv ~/a .zook-scratch/' % os.path.dirname(self.ws) + '/bot1',
                        'cd /; cd %s; mv ~/a .zook-scratch/x' % self.ws, 'cd %s; mv ~/a x' % s, '%s; mv ~/a x' % s,
                        'cd foo; mv ~/a x', 'cd -; mv ~/a x', 'popd; mv ~/a x', 'cd $D; mv ~/a x', 'env -C %s mv ~/a y' % s,
                        'mv -t %s ~/a' % s, 'mv --target-directory=%s ~/a' % s, 'mv -ft %s ~/a' % s, 'gmv -t %s ~/a' % s,
                        'ls ~/old | xargs mv -t %s' % s, 'echo r | xargs -I {} mv {} %s/' % s, 'find ~ -name r -exec mv {} %s/ \\;' % s,
                        'mv ~/a $D', 'mv ~/a %s/*' % self.ws, 'mv ~/a {%s,x}' % s, 'mv ~/a %s/.ZOOK-SCRATCH/' % self.ws,
                        'rsync -a --remove-source-files ~/Documents/ %s/x/' % s, 'zip -m %s/a.zip ~/r.docx' % s, 'zip -9m %s/a.zip ~/r' % s,
                        'mv %s/../../bot2/.zook-scratch/a %s/' % (s, s), 'git mv r.docx %s/r.docx' % s, 'git -C ~/p mv -f a .zook-scratch/'):
            self.asked(command)

    def test_a_link_named_like_the_folder_is_not_already_scratch(self):
        fake = os.path.join(self.base, 'x', '.zook-scratch'); os.makedirs(os.path.dirname(fake)); os.symlink(os.path.join(self.base, 'docs'), fake)
        os.makedirs(os.path.join(self.base, 'docs'))
        self.asked('mv %s/r.docx %s/' % (fake, self.scratch))

    def test_other_moves_are_not(self):
        p = self.fresh()
        for command in ('mv %s %s.old' % (p, p), 'mv ~/a.txt ~/b.txt', 'mv a.txt b.txt', 'cd ~/proj && mv a.txt b.txt', 'mv /tmp/a /tmp/b',
                        'mv ~/a /tmp/', 'rsync -at ~/a ~/b', 'zip /tmp/a.zip ~/r.docx', 'mv -- -a b', 'git mv a b'):
            self.assertNotIn('delete', self.kinds(command), command)

    def test_other_ways_of_removing_files(self):
        for command in ('tar --remove-files -cf /tmp/x.tar ~/x', 'gtar --remove-files -cf x.tar ~/a', 'rsync -a --delete ~/e/ ~/dir/'):
            self.asked(command)
        for command in ('node -e "require(\'fs\').renameSync(\'a\', \'b\')"', 'swift -e "try FileManager.default.moveItem(atPath: p, toPath: t)"'):
            self.assertIn('unclear', self.kinds(command), command)


class HiddenCommands(unittest.TestCase):
    def test_commands_behind_shell_words_and_wrappers_are_read(self):
        kinds = lambda c: [k for k, _ in g.command_boundaries(c)]
        for command in ('if true; then rm ~/a; fi', 'x && { rm ~/a; }', '! rm ~/a', 'for f in a; do rm ~/a; done', 'while true; do rm ~/a; done',
                        'echo x | xargs -I {} rm {}', 'echo x | xargs -n 1 rm', 'nice -n 5 rm ~/a', 'env -u X rm ~/a', 'noglob rm ~/a',
                        'timeout -s KILL 5 rm ~/a', 'coproc rm ~/x', 'repeat 1 rm ~/x', 'coproc foo { rm ~/a; }', 'coproc foo rm ~/a',
                        'function f { rm ~/a; }; f'):
            self.assertIn('delete', kinds(command), command)
        for command in ('$(echo rm) ~/a', '`echo rm` ~/a', '"$(echo rm)" ~/a', 'd= $(echo rm) ~/a', 'env -S "rm ~/a"'):
            self.assertIn('unclear', kinds(command), command)
        self.assertEqual(kinds('d=$(date +%s); echo $d'), [])


class ZookMakesTheFolder(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix='zk261-')))
        self.addCleanup(shutil.rmtree, str(self.base), True)
        (self.base / 'workspaces' / 'bot1').mkdir(parents=True)
        ns = {'os': os, 're': re, 'stat': __import__('stat'), 'time': __import__('time'), 'threading': __import__('threading'), 'GATED_KINDS': ('claude', 'cursor')}
        source = (ROOT / 'backend' / 'zook' / 'gate.py').read_text(encoding='utf-8')
        start = source.index('# Each Bot\'s own scratch folder'); end = source.index('def gate_access_note')
        exec(compile(source[start:end], 'gate.py', 'exec'), ns)
        self.ns = ns; self.store = types.SimpleNamespace(dir=self.base)

    def test_made_once_and_kept(self):
        env = {}; folder = self.ns['scratch_env'](self.store, 'bot1', env)
        self.assertEqual(folder, str(self.base / 'workspaces/bot1/.zook-scratch'))
        info = os.lstat(folder); self.assertEqual(env['ZOOK_SCRATCH_ID'], '%d:%d' % (info.st_dev, info.st_ino)); self.assertEqual(env['ZOOK_SCRATCH'], folder)
        Path(folder, 'a.txt').write_text('x')
        again = {}; self.ns['scratch_env'](self.store, 'bot1', again)
        self.assertEqual(again, env); self.assertTrue(Path(folder, 'a.txt').exists())
        self.assertIn(folder, self.ns['scratch_note'](folder)); self.assertEqual(self.ns['scratch_note'](None), '')

    def test_a_folder_put_in_its_place_is_moved_aside_never_deleted(self):
        env = {}; folder = self.ns['scratch_env'](self.store, 'bot1', env)
        os.rename(folder, str(self.base / 'away')); docs = self.base / 'docs'; docs.mkdir(); (docs / 'keep.txt').write_text('x')
        os.symlink(str(docs), folder)
        again = {}; self.ns['scratch_env'](self.store, 'bot1', again)
        self.assertNotEqual(again['ZOOK_SCRATCH_ID'], env['ZOOK_SCRATCH_ID'])
        self.assertTrue(os.path.isdir(folder) and not os.path.islink(folder)); self.assertTrue((docs / 'keep.txt').exists())
        self.assertEqual(len(list((self.base / 'workspaces/bot1').glob('.zook-scratch-old-*'))), 1)
        with unittest.mock.patch.dict(os.environ, again):
            p = os.path.join(folder, 'n.txt'); Path(p).write_text('x')
            self.assertEqual(g.command_boundaries('rm %s' % p), [])


if __name__ == '__main__': unittest.main()
