# -*- coding: utf-8 -*-
"""巡檢 #176: the memory page fits a phone and says how memory is used; a typed path with spaces is still offered as an
attachment; a group member's permission line is not cut off; a Bot's build script does not sit among its outputs; a member that
saves the same content someone else already saved does not leave a second copy."""
import importlib.util, json, os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = lambda name: (ROOT / 'frontend/js' / name).read_text(encoding='utf-8')
CSS = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)
SERVER = ROOT / 'backend/server.py'


def block(src, start, end):
    a = src.index(start); return src[a:src.index(end, a)]


def run_node(code, data):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'h.js'; f.write_text(code, encoding='utf-8')
        out = subprocess.run([NODE, str(f)], input=json.dumps(data), capture_output=True, text=True, timeout=30)
    if out.returncode: raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class MemoryPage(unittest.TestCase):
    def test_phone_width_buttons_are_big_enough(self):
        phone = [body for head, body in re.findall(r'@media \(max-width: (\d+)px\) \{(.*?)\n\}', CSS, re.S) if int(head) <= 699]
        rule = re.search(r'\.card \.actions \.link\s*\{([^}]*)\}', '\n'.join(phone))
        self.assertTrue(rule, 'phone width gives card buttons their own size')
        self.assertIn('min-height: 44px', rule.group(1)); self.assertIn('min-width: 44px', rule.group(1))

    def test_the_page_says_what_each_reply_reads(self):
        page = block(JS('20-models.js'), "} else if (state.page === 'memory') {", "} else if (state.page === 'mcp-legacy')")
        self.assertIn('最近 40 則', page)
        self.assertIn('不論哪一家的 Bot', page)
        self.assertIn('原 Bot 已刪除，沒有 Bot 會用到', page)  # ② unchanged: a deleted Bot's memory says nobody reads it

    def test_member_permission_line_wraps(self):
        rule = re.search(r'^\.member-row small \{([^}]*)\}', CSS, re.M).group(1)
        self.assertNotIn('nowrap', rule); self.assertNotIn('ellipsis', rule)


@unittest.skipUnless(NODE, 'needs node to run the page code')
class TypedPaths(unittest.TestCase):
    def offers(self, texts):
        code = block(JS('30-pages.js'), 'const PATH_WORD', '\n  function showPathOffers') + "\nconsole.log(JSON.stringify(JSON.parse(require('fs').readFileSync(0, 'utf8')).map(typedPaths)));"
        return run_node(code, texts)

    def test_paths_with_spaces(self):
        got = self.offers([
            '幫我看 /Users/sean/Documents/Claude code/報價 單.xlsx 謝謝',
            '/Users/sean/Documents/Claude\\ code/a.pdf',
            "請整理 '/Users/sean/My Files/b.docx'",
            '/tmp/a.txt 和 /tmp/b.txt',
            '/Users/sean/Documents/Claude code/x.xlsx，再看 /tmp/plain.csv',
        ])
        self.assertIn('/Users/sean/Documents/Claude code/報價 單.xlsx', got[0])
        self.assertEqual(got[1], ['/Users/sean/Documents/Claude code/a.pdf'])
        self.assertEqual(got[2], ['/Users/sean/My Files/b.docx'])
        self.assertEqual(sorted(got[3]), ['/tmp/a.txt', '/tmp/b.txt'])  # two paths stay two, not one long one
        self.assertEqual(sorted(got[4]), ['/Users/sean/Documents/Claude code/x.xlsx', '/tmp/plain.csv'])

    def test_punctuation_and_sentences_around_it(self):
        got = self.offers(['檔案在 /Users/a/Claude code/r.pdf。請看', '（/Users/a/My Docs/x.csv）和「/Users/a/b c/y.txt」', '/Users/a/b c/one.txt、/Users/a/b c/two.txt'])
        self.assertEqual(got[0], ['/Users/a/Claude code/r.pdf'])
        self.assertEqual(sorted(got[1]), ['/Users/a/My Docs/x.csv', '/Users/a/b c/y.txt'])
        self.assertEqual(sorted(got[2]), ['/Users/a/b c/one.txt', '/Users/a/b c/two.txt'])

    def test_long_near_paths_stay_fast(self):
        code = block(JS('30-pages.js'), 'const PATH_WORD', '\n  function showPathOffers') + """
const worst = ['/' + 'a b '.repeat(5000) + '/x', ' /a/b c'.repeat(3300), ' /a/b c.d e'.repeat(1800), '/a/' + 'w.tx '.repeat(4000) + '/b', ' /'.repeat(10000)];
const t = Date.now(); for (let i = 0; i < 5; i++) worst.forEach(typedPaths); console.log(JSON.stringify(Date.now() - t));"""
        self.assertLess(run_node(code, []), 2000)

    def test_no_fragments_and_still_at_most_three(self):
        got = self.offers(['/Users/sean/Claude code/a.txt', ' '.join('/tmp/f%d.txt' % i for i in range(6)), 'a' * 20000 + ' /x/y z'])
        self.assertEqual(got[0], ['/Users/sean/Claude code/a.txt'])
        self.assertEqual(len(got[1]), 3); self.assertEqual(got[2], [])


@unittest.skipUnless(NODE, 'needs node to run the page code')
class OutputScripts(unittest.TestCase):
    def split(self, lists):
        code = block(JS('36-outputs.js'), '  const BUILD_SCRIPT', '\n  function outputsPanel') + "\nconsole.log(JSON.stringify(JSON.parse(require('fs').readFileSync(0, 'utf8')).map(l => splitScripts(l).map(x => x.map(o => o.name)))));"
        return run_node(code, lists)

    def test_scripts_beside_files_are_kept_apart(self):
        got = self.split([[{'name': 'Q3報告.xlsx'}, {'name': 'create_q3_report.py'}, {'name': 'build.js'}],
                          [{'name': 'tool.py'}, {'name': 'run.sh'}],
                          [{'name': 'a.pdf'}]])
        self.assertEqual(got[0], [['Q3報告.xlsx'], ['create_q3_report.py', 'build.js']])
        self.assertEqual(got[1], [['tool.py', 'run.sh'], []])  # a Bot that only wrote code: the code is what it made
        self.assertEqual(got[2], [['a.pdf'], []])

    def test_a_switch_shows_them(self):
        panel = block(JS('36-outputs.js'), '  function outputsPanel', '\n  // A PDF opens')
        self.assertIn('toggle(', panel); self.assertIn('data-show-scripts', panel)
        self.assertIn('dataset.showScripts', JS('50-forms.js'))


class SameContentIsNotCopied(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('zook_176', SERVER); self.server = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.server)
        self.temp = tempfile.TemporaryDirectory(); root = Path(os.path.realpath(self.temp.name))
        self.store = type('S', (), {})(); self.store.dir = root / 'data'
        self.shared = self.server.group_files_dir(self.store, 'g1'); self.shared.mkdir(parents=True); (self.shared / '報銷.xlsx').write_text('v1')
        (self.store.dir / 'workspaces/b1').mkdir(parents=True)

    def tearDown(self): self.temp.cleanup()

    def test_identical_rework_is_not_a_second_file(self):
        seen = self.server.sync_group_files_in(self.store, 'g1', 'b1'); copy = self.server.group_copy_folder(self.store, 'b1')
        (self.shared / '報銷.xlsx').write_text('v2'); (copy / '報銷.xlsx').write_text('v2')  # someone saved v2 meanwhile; this member made the same v2
        self.server.sync_group_files_out(self.store, 'g1', 'B-報銷專員', 'b1', seen)
        self.assertEqual(sorted(p.name for p in self.shared.iterdir()), ['報銷.xlsx'])


if __name__ == '__main__': unittest.main()
