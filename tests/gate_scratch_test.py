# -*- coding: utf-8 -*-
"""queue #261, decisions #28 (2026-11-25, the user's call): a Bot deletes its own scratch files without asking. Only files: in /tmp,
in the Mac's temporary folder (/private/var/folders/*/*/T/), or in a folder made by $(mktemp …) in the same command line. Never the
folder itself, a wildcard, a .., or a file that is really (after links) somewhere else; every other delete is asked as before.
An earlier security review asked for /tmp deletes to be asked (gate_test); the user changed that rule here."""
import os, sys, tempfile, unittest, unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import zook_gate as g  # noqa: E402


def kinds(command): return [k for k, _ in g.command_boundaries(command)]


class ScratchDelete(unittest.TestCase):
    def setUp(self):
        self.cwd = g._CWD[0]; g._CWD[0] = str(Path.home() / 'zook-gate-test-work')
        self.made = []
        self.tmp = self.scratch('/tmp')                       # /tmp/…, really /private/tmp/…
        self.sys = self.scratch(tempfile.gettempdir())        # /var/folders/…/T/…
        self.env = unittest.mock.patch.dict(os.environ, {'TMPDIR': tempfile.gettempdir() + '/'}); self.env.start()

    def tearDown(self):
        self.env.stop(); g._CWD[0] = self.cwd
        for p in reversed(self.made):
            try: os.rmdir(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)
            except OSError: pass

    def scratch(self, folder, folder_too=False):
        if folder_too: p = tempfile.mkdtemp(dir=folder, prefix='zk261-')
        else:
            fd, p = tempfile.mkstemp(dir=folder, prefix='zk261-'); os.write(fd, b'x'); os.close(fd)
        self.made.append(p); return p

    def free(self, command): self.assertNotIn('delete', kinds(command), command)

    def asked(self, command): self.assertIn('delete', kinds(command), command)

    def test_scratch_files_are_deleted_without_asking(self):
        name = os.path.basename(self.sys)
        for command in ('rm %s' % self.tmp, 'rm -f "%s"' % self.tmp, '/bin/rm -fv %s' % self.tmp, 'unlink %s' % self.tmp, 'rm -- %s' % self.tmp,
                        'rm %s' % self.sys, 'rm -f %s %s' % (self.tmp, self.sys), 'rm -f "$TMPDIR/%s"' % name, 'rm "${TMPDIR}%s"' % name,
                        'python3 %s && rm %s' % (self.tmp, self.tmp), 'if [ -f %s ]; then rm %s; fi' % (self.tmp, self.tmp),
                        'echo done > %s.log; rm -f %s; ls /tmp' % (self.tmp, self.tmp),
                        'd=$(mktemp -d); python3 make.py > "$d/a.json"; rm -f "$d/a.json"',
                        'd="$(mktemp -d -t zook)" && echo hi > "${d}/x.txt" && cat "$d/x.txt" && rm "${d}/x.txt"',
                        'out=$(mktemp -dt zook); touch $out/a.png; rm -f $out/a.png'):
            self.free(command)

    def test_other_deletes_are_still_asked(self):
        folder = self.scratch('/tmp', folder_too=True)
        inside = os.path.join(folder, 'a.txt'); Path(inside).write_text('x'); self.made.append(inside)
        link = os.path.join('/tmp', 'zk261-link-%d' % os.getpid()); os.symlink(self.tmp, link); self.made.append(link)
        hard = self.tmp + '-hard'; os.link(self.tmp, hard); self.made.append(hard)
        for command in ('rm -r %s' % self.tmp, 'rm -rf %s' % folder, 'rmdir %s' % folder, 'rm -d %s' % folder, 'rm /tmp', 'rm %s/' % folder,
                        'rm /tmp/zk261-*', 'rm "%s"/*.txt' % folder, 'rm %s/../%s' % (folder, os.path.basename(self.tmp)),
                        'rm %s' % link, 'rm %s' % hard, 'rm -P %s' % self.tmp, 'shred %s' % self.tmp, 'trash %s' % self.tmp,
                        'rm /tmp/zk261-not-there', 'rm -f %s ~/報告.xlsx' % self.tmp, 'cd ~/Documents && rm %s' % os.path.basename(self.tmp),
                        'sudo rm %s' % self.tmp, 'bash -c "rm %s"' % self.tmp, 'echo $(rm %s)' % self.tmp, 'echo x | xargs rm %s' % self.tmp,
                        'cp ~/a.docx %s && rm %s' % (self.tmp, self.tmp), 'ln -sfn ~/Documents %s; rm %s/a.txt' % (folder, folder),
                        'find /tmp -name x -delete', 'FOO=1 rm %s' % self.tmp, 'command rm %s' % self.tmp, './rm %s' % self.tmp):
            self.asked(command)

    def test_a_file_that_really_is_elsewhere_is_asked(self):
        with tempfile.TemporaryDirectory() as base:
            base = os.path.realpath(base); os.makedirs(base + '/in'); os.makedirs(base + '/out')
            for f in ('/in/a.txt', '/out/b.txt'): Path(base + f).write_text('x')
            os.symlink(base + '/out', base + '/in/link')
            with unittest.mock.patch.object(g, 'SCRATCH', __import__('re').compile(__import__('re').escape(base + '/in/'))):  # only in/ is scratch
                self.free('rm %s/in/a.txt' % base)
                for command in ('rm %s/in/link/b.txt' % base, 'rm %s/out/b.txt' % base, 'rm %s/in/link' % base, 'rm %s/in/../out/b.txt' % base):
                    self.asked(command)

    def test_a_mktemp_folder_counts_only_when_nothing_else_can_change_it(self):
        for command in ('d=$(mktemp -d); rm -rf "$d"', 'd=$(mktemp -d); rm "$d"', 'd=$(mktemp -d); rm -r "$d/x"', 'd=$(mktemp -d); rm "$d/sub/x"',
                        'd=$(mktemp -d); rm "$d/*.png"', 'd=$(mktemp -d); rm "$d/.."', 'd=$(mktemp -d); rm "$e/x"', 'rm "$d/x"',
                        'd=$(mktemp -d); d=~/Documents; rm "$d/r.docx"', 'd=$(mktemp -d); read d; rm "$d/x"', 'd=$(mktemp -d); printf -v d %s ~; rm "$d/x"',
                        'd=$(mktemp -d); export d=~; rm "$d/x"', 'd=$(mktemp -d); d+=/x; rm "$d/y"', '(d=$(mktemp -d)); rm "$d/x"',
                        'd=$(mktemp -d); rm \'$d/x\'', 'd=$(mktemp -d); rm \\$d/x', 'd=$(mktemp -u); rm "$d/x"', 'd=$(mktemp -du); rm "$d/x"',
                        'd=$(mktemp -d); mv ~/Documents/r.docx "$d/r"; rm -f "$d/r"', 'd=$(mktemp -d); ln -s ~/Documents/r "$d/r"; rm "$d/r"',
                        'HOME=$(mktemp -d); rm "$HOME/.zshrc"', 'PATH=$(mktemp -d); rm "$PATH/x"', 'path=$(mktemp -d); rm "$path/x"',
                        '# d=$(mktemp -d)\nrm "$d/.zshrc"', 'd=$(echo ~); rm "$d/x"', 'd=$(mktemp -d $(echo ~)); rm "$d/x"', 'd=`mktemp -d`; rm "$d/x"',
                        'mktemp() { echo ~; }; d=$(mktemp -d); rm "$d/x"', 'd=$(mktemp -d); : ${d:=~}; rm "$d/x"', 'd=$(mktemp -d); rm "${d:-~}/x"',
                        'd=$(mktemp -d ~/Documents/XXXXXX); rm "$d/a"', 'd=$(mktemp -d ../XXXXXX); rm "$d/a"', 'd=$(mktemp -d .); rm "$d/a"',
                        'd=$(mktemp -d ~/Documents/Claude); rm "$d/Zook"', 'echo "a; d=$(mktemp -d); b"; rm $d/.file',
                        'rm -f %s > ~/Desktop/a.txt' % self.tmp, 'rm %s >$HOME/important' % self.tmp, 'rm %s > f' % self.tmp,
                        'false && d=$(mktemp -d); rm $d/.file', 'rm -f %s 2> ~/Desktop/a.txt' % self.tmp,
                        'TMPDIR=~/Documents; rm "$TMPDIR/r.docx"', ': ${TMPDIR:=~}; rm "$TMPDIR/r"', 'export TMPDIR=~; rm $TMPDIR/r',
                        'rm "$TMPDIR/../x"', 'rm "$HOME/x"', 'cat <<EOF\nd=$(mktemp -d)\nEOF\nrm "$d/x"'):
            self.asked(command)

    def test_moving_a_file_into_scratch_is_a_delete(self):
        # otherwise moving a file to /tmp, then deleting it there, would delete it without asking
        for command in ('mv ~/Documents/r.docx /tmp/', 'mv ~/Documents/r.docx "$TMPDIR/r.docx"', 'mv -f r.docx %s' % self.tmp,
                        'd=$(mktemp -d); mv ~/Documents/r.docx "$d/"', 'rsync -a --remove-source-files ~/Documents/ /tmp/x/', 'zip -m /tmp/a.zip ~/r.docx',
                        'find ~ -name r.docx -exec mv {} /tmp/ \\;', 'echo r | xargs -I {} mv {} /tmp/', 'mv -t /tmp ~/Desktop/a.txt',
                        'mv --target-directory=/tmp ~/a.txt', 'mv -ft /tmp ~/a.txt', 'gmv -t /tmp ~/a.txt', 'cd /tmp; mv ~/a.txt y', 'cd /tmp && mv ~/a.txt .',
                        '(cd /tmp; mv ~/a y)', 'pushd /tmp; mv ~/a y', 'env -C /tmp mv ~/a y', 'cd /private; cd tmp; mv ~/a b',
                        'a=/private/t; mv ~/a ${a}mp/', 'mv ~/a /pr*/tm*', 'mv ~/a /tm[p]/', 'mv ~/a {/private/tmp,}', 'mv ~/a $(echo /pr)ivate/t""mp',
                        'rsync -a --remove-sent-files ~/x /tmp/', 'tar --remove-files -cf /tmp/x.tar ~/x', 'rsync -a --delete /tmp/e/ ~/dir/',
                        'coproc rm ~/x', 'repeat 1 rm ~/x', 'zip -9m /tmp/x.zip ~/a', 'zip -r9m /tmp/x.zip ~/a', 'ls ~/old | xargs mv -t /tmp',
                        'gtar --remove-files -cf /tmp/x.tar ~/a', 'bsdtar --remove-f -cf /tmp/x.tar ~/a', 'rsync --remove-source-f ~/a /tmp/',
                        'env --chdir=/tmp mv ~/a y', 'cd ~ && mv a.txt /tmp', 'cd ~; mv -t /tmp a.txt', 'mv a.txt /tmp',
                        'coproc foo { rm ~/a; }', 'coproc foo rm ~/a', 'function f { rm ~/a; }; f'):
            self.asked(command)
        for command in ('node -e "require(\'fs\').renameSync(\'a\', \'/tmp/a\')"', 'swift -e "try FileManager.default.moveItem(atPath: p, toPath: t)"'):
            self.assertIn('unclear', kinds(command), command)
        for command in ('mv %s %s.old' % (self.tmp, self.tmp), 'mv ~/a.txt ~/b.txt', 'mv a.txt b.txt', 'cd ~/proj && mv a.txt b.txt', 'rsync -at ~/a ~/b', 'rsync -a ~/x/ /tmp/x/', 'zip /tmp/a.zip ~/r.docx'):
            self.assertNotIn('delete', kinds(command), command)

    def test_commands_hidden_behind_shell_words_are_read(self):
        for command in ('if true; then rm ~/a; fi', 'x && { rm ~/a; }', '! rm ~/a', 'for f in a; do rm ~/a; done', 'while true; do rm ~/a; done',
                        'echo x | xargs -I {} rm {}', 'echo x | xargs -n 1 rm', 'nice -n 5 rm ~/a', 'env -u X rm ~/a', 'noglob rm ~/a',
                        'timeout -s KILL 5 rm ~/a'):
            self.asked(command)
        for command in ('$(echo rm) ~/a', '`echo rm` ~/a', '"$(echo rm)" ~/a', 'd= $(echo rm) ~/a'):
            self.assertIn('unclear', kinds(command), command)
        self.assertEqual(kinds('d=$(date +%s); echo $d'), [])


if __name__ == '__main__': unittest.main()
