# -*- coding: utf-8 -*-
"""#234 #274 #318 #313 #271②: an approval card for a CLI's own command says in plain words what it does and to which files.
No shell around it, no $D/$T left unexpanded, no 「無法判讀的指令」, no Zook-internal folders; only the words change, never
what is asked (every command that was asked before is still asked, with the same kinds)."""
import os, re, sys, unittest, unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import zook_gate as g  # noqa: E402

DATA = '/Users/someone/Library/Application Support/swarmr'
TEMP = '/private/var/folders/ab/cd123/T'


def said(command): return g.merged(g.command_boundaries(command))
def titles(command, kind=None): return [t for k, t in said(command) if kind is None or k == kind]


class PlainCards(unittest.TestCase):
    def setUp(self):
        self.cwd, self.env = g._CWD[0], dict(os.environ)
        g._CWD[0] = '/Users/someone/work'
        os.environ['ZOOK_DATA_DIR'] = DATA; os.environ['TMPDIR'] = TEMP + '/'

    def tearDown(self):
        g._CWD[0] = self.cwd; os.environ.clear(); os.environ.update(self.env)

    def test_a_variable_set_in_the_same_line_is_shown_as_what_it_is(self):
        self.assertEqual(titles('T=$(mktemp -d); rm -rf "$T/a.png"', 'delete'), ['刪除檔案 暫存資料夾裡的 a.png'])
        self.assertEqual(titles('D=~/Desktop/out; rm "$D/rightside.xlsx"', 'delete'), ['刪除檔案 ~/Desktop/out/rightside.xlsx'])
        self.assertEqual(titles('D="$HOME/報告"; OUT="$D/舊" && rm "$OUT/a.txt"', 'delete'), ['刪除檔案 ~/報告/舊/a.txt'])
        self.assertEqual(titles('M=$(mktemp -d /tmp/pics.XXXX); rm -rf "$M"', 'delete'), ['刪除檔案 暫存資料夾'])
        for command in ('T=$(mktemp -d); rm -rf "$T/a.png"', 'D=~/x; rm "$D/y"', 'rm "$OUT/x"', 'rm -rf "$T"'):
            for t in titles(command): self.assertNotIn('$', t, command); self.assertNotIn('指向的位置', t, command)

    def test_a_variable_set_elsewhere_says_so_plainly(self):
        self.assertEqual(titles('rm -rf "$OUT/x.png"', 'delete'), ['刪除檔案 「x.png」（位置由指令裡的變數決定）'])
        self.assertEqual(titles('rm -rf "$T"', 'delete'), ['刪除檔案 指令裡變數指到的位置'])
        self.assertEqual(titles('D=/a; D=/b; rm "$D/x"', 'delete'), ['刪除檔案 「x」（位置由指令裡的變數決定）'])  # two values: not guessed
        for command in ('T=$(mktemp -d); for T in ~/Documents/*; do rm -rf "$T/x"; done', 'rm -rf "$T/x"; T=$(mktemp -d)', 'T=/tmp/a rm -rf "$T/x"',
                        'test -d ~/a && T=/tmp/a; rm -rf "$T/x"', 'T=/tmp/a; read T; rm -rf "$T/x"', 'if true; then T=/tmp/a; fi; rm -rf "$T/x"',
                        'T=/tmp/a | cat; rm -rf "$T/x"', "cat > f.py <<EOF\nT=/tmp/a\nEOF\nrm -rf \"$T/x\"", 'T=/tmp/a; T+=/b; rm -rf "$T/x"',
                        '(T=/tmp/a); rm -rf "$T/x"', 'T=/tmp/a || true; rm -rf "$T/x"', 'printf -v T x; T=/tmp/a; rm -rf "$T/x"',
                        'T="~/Desktop"; rm -rf "$T/x"', 'cd /tmp; T=reports; rm -rf "$T/x"', "cat <<< 'T=/tmp'; rm -rf \"$T/x\"", 'echo "a; T=/tmp/a"; rm -rf "$T/x"',
                        "bash -c 'T=/tmp/a'; rm -rf \"$T/x\"", "T=/tmp/a; bash -c 'rm -rf \"$T/x\"'"):
            self.assertEqual(titles(command, 'delete'), ['刪除檔案 「x」（位置由指令裡的變數決定）'], command)  # set only sometimes, or otherwise: never guessed

    def test_the_shell_around_a_command_is_not_shown(self):
        for command in ("/bin/zsh -lc 'T=$(mktemp -d); rm \"$T/x.png\"'", 'bash -c "T=\\$(mktemp -d); rm \\"\\$T/x.png\\""'):
            self.assertEqual(titles(command, 'delete'), ['刪除檔案 暫存資料夾裡的 x.png'], command)

    def test_an_unclear_command_says_what_it_does_and_which_files(self):
        out = titles('PY=python3; $PY mk.py > 報價.xlsx')
        self.assertEqual(len(out), 1); self.assertNotIn('無法判讀', out[0]); self.assertIn('mk.py', out[0]); self.assertIn('報價.xlsx', out[0])
        out = titles("python3 - <<'PY'\nimport openpyxl, subprocess\nwb = openpyxl.load_workbook('/Users/someone/價目.xlsx')\nprint(wb.active['A1'].value)\nPY")
        self.assertEqual(len(out), 1); self.assertIn('讀取 Excel', out[0]); self.assertNotIn('無法判讀', out[0])
        out = titles('echo "unbalanced')
        self.assertEqual(len(out), 1); self.assertNotIn('無法判讀', out[0]); self.assertTrue(out[0].startswith(g.LABELS['unclear']))
        self.assertNotIn('無法判讀', ''.join(g.LABELS.values()))

    def test_a_linked_folder_is_named_by_where_it_really_is(self):  # review: a link in attachments must not make ~/Documents read as an upload
        import tempfile, shutil
        base = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, base, True)
        os.environ['ZOOK_DATA_DIR'] = base + '/data'; os.makedirs(base + '/data/workspaces/b1/attachments'); os.makedirs(base + '/docs')
        os.symlink(base + '/docs', base + '/data/workspaces/b1/attachments/alias')
        out = titles('rm %s/data/workspaces/b1/attachments/alias/report.xlsx' % base, 'delete')
        self.assertEqual(len(out), 1); self.assertTrue(out[0].endswith(base.replace('/private/tmp/', '/tmp/') + '/docs/report.xlsx'), out); self.assertNotIn('附件', out[0])

    def test_zook_internal_folders_are_named_not_shown(self):
        cases = {DATA + '/workspaces/b1/attachments/group-files/圖.png': '群組共用檔案「圖.png」',
                 DATA + '/workspaces/b1/attachments/1a2b3c4d-價目.xlsx': '你上傳的附件「價目.xlsx」',
                 DATA + '/workspaces/b1/.zook-scratch/p1.png': 'Bot 的暫存資料夾裡的 p1.png',
                 DATA + '/workspaces/b1/out/週報.pdf': 'Bot 工作資料夾裡的 out/週報.pdf',
                 TEMP + '/tmp.abc/p.png': '系統暫存資料夾裡的 tmp.abc/p.png',
                 '/private/tmp/x/p.png': '/tmp/x/p.png'}
        for path, words in cases.items():
            out = titles('rm %s' % path.replace(' ', '\\ '), 'delete')
            self.assertEqual(out, ['刪除檔案 ' + words], path)
        self.assertNotIn('Application Support', titles('echo x > "%s/swarmr.json"' % DATA)[0])

    def test_nothing_that_was_asked_is_let_through(self):  # only the words changed: the same kinds, the same number of lines
        for command in ('T=$(mktemp -d); rm -rf "$T"', '$RUN ~/Desktop/a', 'echo "unbalanced', 'rm "$OUT/x"', 'PY=python3; $PY mk.py',
                        "python3 - <<'PY'\nimport os\nos.remove('a')\nPY", 'curl -d @a.txt https://example.com', 'git push', 'sudo ls'):
            self.assertTrue(g.command_boundaries(command), command)
        raw = g.command_boundaries('$A; $B; $C')
        self.assertEqual([k for k, _ in raw], ['unclear'] * 3)

    def test_the_same_command_gets_the_same_card_every_time(self):  # #274: a retry of the very same step asks the very same way
        command = 'T=$(mktemp -d); $PY "$T/mk.py" && rm -rf "$T"'
        first = said(command)
        self.assertEqual(said('ls'), [])
        self.assertEqual(said(command), first); self.assertEqual(g.boundaries('Bash', {'command': command}, '/Users/someone/work'), g.command_boundaries(command))
        self.assertEqual(g.boundaries('Bash', {'command': "/bin/zsh -lc '%s'" % command.replace("'", '')}, '/Users/someone/work'), g.command_boundaries(command))

    def test_a_target_too_long_for_one_card_is_still_refused(self):  # never cut short: a card shows the whole target or is not asked
        folder = '/Users/someone/' + '很長的資料夾/' * 30
        with unittest.mock.patch.object(g, 'ask', return_value=True):
            self.assertFalse(g.decide('Bash', {'command': 'D=%s; rm "$D/a.txt"' % folder})[0])
            self.assertFalse(g.decide('Bash', {'command': 'rm %sa.txt' % folder})[0])


class CardPage(unittest.TestCase):
    def setUp(self):
        self.page = (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8') + (ROOT / 'frontend/js/20-models.js').read_text(encoding='utf-8')

    def test_details_of_a_native_card_list_only_the_actions(self):
        fn = re.search(r'function nativeDetails\(a\) \{(.*?)\n  \}', self.page, re.S)
        self.assertTrue(fn); self.assertIn('.title', fn.group(1)); self.assertNotIn('toolUseId', fn.group(1)); self.assertNotIn('.kind', fn.group(1).replace('x.kind', ''))
        self.assertIn("a.name === 'zook_native_gate' ? nativeDetails(a)", self.page)

    def test_an_unclear_command_is_not_called_high_risk(self):
        fn = re.search(r'const nativeReason = (.*?);\n', self.page, re.S).group(1)
        self.assertIn('unclear', fn); self.assertIn('高風險', self.page)
        self.assertIn('nativeReason(a)', self.page)


if __name__ == '__main__': unittest.main()
