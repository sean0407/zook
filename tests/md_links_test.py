# -*- coding: utf-8 -*-
"""#59/#112/#169/#203: a Markdown link to a file whose path has spaces or Chinese (written inside <…>, or a broken variant
such as `(</tmp/a.docx> >)`) shows as a clickable name, not as raw Markdown; a local file opens Zook's preview (or the
path is copied when Zook does not know the file); only http(s) links ever become real links."""
import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8')
OUTPUTS = (ROOT / 'frontend/js/36-outputs.js').read_text(encoding='utf-8')
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)


def block(src, start, end):
    a = src.index(start); return src[a:src.index(end, a)]


HARNESS = r"""
const document = {createElement: () => { const t = {}; Object.defineProperty(t, 'innerHTML', {set(v) { t.value = v.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&'); }}); return t; }};
const state = {outputs: {b1: [{id: 'o1', name: '上週 客服工單.xlsx', path: '/tmp/zook-inspect/A/上週 客服工單.xlsx'}, {id: 'o2', name: '報告.docx', path: '/Users/x/報告.docx'}]}};
__CHAT__
__OUTPUTS__
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const two = [['b1', [{id: 'a', name: 'r.docx', path: '/tmp/a/r.docx'}]], ['b2', [{id: 'b', name: 'r.docx', path: '/tmp/b/r.docx'}]]];
two.push(['b3', [{id: 'c', name: '100%20完成.docx', path: '/tmp/100%20完成.docx'}, {id: 'd', name: '100 完成.docx', path: '/tmp/100 完成.docx'}, {id: 'e', name: 'x y.pdf', path: '/tmp/x y.pdf'}]]);
const pick = p => (outputAt(two, p) || [null, {id: null}])[1].id;
const t0 = Date.now(); markdown('[a' + ' '.repeat(20000) + 'b](</tmp/x.txt>)'); markdown('[a](' + ' '.repeat(20000) + 'x'); markdown('[a](/tmp/x' + ' '.repeat(20000) + '"y'); const slow = Date.now() - t0;
console.log(JSON.stringify({md: cases.md.map(markdown), linked: cases.linked.map(t => linkOutputs(markdown(t), 'b1')), picks: ['/tmp/b/r.docx', '/private/tmp/a/r.docx', '/nowhere/r.docx', '/tmp/100%20完成.docx', '/tmp/x%20y.pdf'].map(pick), slow}));
"""


@unittest.skipUnless(NODE, 'needs node to run the page code')
class MarkdownLinks(unittest.TestCase):
    def run_js(self, md=(), linked=()):
        code = HARNESS.replace('__CHAT__', block(CHAT, 'const esc =', 'const icons =')).replace('__OUTPUTS__', block(OUTPUTS, '  const samePath', '  // A link to a file on this Mac opens') + block(OUTPUTS, '  function linkOutputs', '\n  }\n') + '\n  }\n')
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'h.js'; f.write_text(code, encoding='utf-8')
            out = subprocess.run([NODE, str(f)], input=json.dumps({'md': list(md), 'linked': list(linked)}), capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_angle_bracket_and_broken_paths_become_links(self):
        md = self.run_js(md=[
            '[下載報表](</tmp/zook-inspect/A/上週 客服工單.xlsx>)',
            '[下載 Word 檔：（會議 紀錄）](</tmp/zook-inspect/A/會議 紀錄.docx> >)',
            '[下載](/tmp/zook-inspect/A/週報 (1).xlsx)',
            '[看這裡](<file:///tmp/a%20b.pdf>)',
            '[長的\n檔名](</tmp/x y.docx>)',
            '[官網](<https://example.com/a b>)',
        ])['md']
        for html in md:
            self.assertNotIn('](', html); self.assertNotIn('&lt;/', html); self.assertNotIn('&gt;)', html)
        self.assertIn('data-path="/tmp/zook-inspect/A/上週 客服工單.xlsx"', md[0]); self.assertIn('>下載報表</button>', md[0])
        self.assertIn('data-path="/tmp/zook-inspect/A/會議 紀錄.docx"', md[1]); self.assertIn('下載 Word 檔：（會議 紀錄）</button>', md[1])
        self.assertIn('data-path="/tmp/zook-inspect/A/週報 (1).xlsx"', md[2])
        self.assertIn('data-path="/tmp/a b.pdf"', md[3])
        self.assertIn('>長的 檔名</button>', md[4])
        self.assertIn('href="https://example.com/a%20b"', md[5])
        for html in md[:5]:
            self.assertIn('class="link local-link"', html); self.assertNotIn('href=', html)  # a local file never becomes a page address

    def test_review_cases(self):
        out = self.run_js(md=['https://a.com[x](</tmp/b c.txt>)', 'https://a.com\u00000\u0000', '[a](</tmp/a)b c.docx>)', '[a](/tmp/a%20b.pdf)', '[`會`議](</tmp/`會`議.docx>)', '[' + ' ' * 20000 + 'x](</tmp/a.txt>)'])
        md = out['md']
        self.assertIn('<a href="https://a.com" rel="noopener noreferrer">https://a.com</a><button', md[0])  # the next link is not swallowed into href
        self.assertNotIn('\u0000', md[1]); self.assertNotIn('<button', md[1])
        self.assertIn('data-path="/tmp/a)b c.docx"', md[2]); self.assertIn('data-path="/tmp/a%20b.pdf"', md[3])
        self.assertIn('data-path="/tmp/`會`議.docx"', md[4]); self.assertIn('<code>會</code>議</button>', md[4])
        self.assertEqual(out['picks'], ['b', 'a', None, 'c', 'e'])  # the exact path wins over a file with the same name; two same names: none
        self.assertLess(out['slow'], 300)

    def test_only_safe_links(self):
        md = self.run_js(md=[
            '[點我](javascript:alert(1))', '[點我](<javascript:alert(1)>)', '[點我](<JaVaScRiPt:alert(1)>)', '[x](data:text/html,hi)',
            '[a](</tmp/"><img src=x onerror=alert(1)>.txt>)', '[a](https://x.com/"onmouseover="alert(1))', '[a](//evil.example/x.png)',
        ])['md']
        for html in md:
            self.assertNotIn('javascript:', html.lower()); self.assertNotIn('data:', html); self.assertNotIn('<img', html); self.assertNotIn('"onmouseover', html)
            self.assertNotIn('href="//', html)
        self.assertEqual(md[0], '<p>點我</p>')

    def test_old_forms_still_work(self):
        md = self.run_js(md=['[網站](https://example.com/x)', '看 https://example.com/y 這頁', '`[a](</tmp/b c.txt>)`', '**[粗](</tmp/a b.txt>)**', '[純檔名](報告.docx)', '[1] 與 (2) 不是連結'])['md']
        self.assertIn('<a href="https://example.com/x" rel="noopener noreferrer">網站</a>', md[0])
        self.assertIn('<a href="https://example.com/y"', md[1])
        self.assertIn('<code>[a](&lt;/tmp/b c.txt&gt;)</code>', md[2])  # code stays code
        self.assertIn('<strong><button', md[3])
        self.assertEqual(md[4], '<p>純檔名</p>')
        self.assertEqual(md[5], '<p>[1] 與 (2) 不是連結</p>')

    def test_a_link_to_an_output_is_left_to_its_card(self):
        out = self.run_js(linked=['[下載](</tmp/zook-inspect/A/上週 客服工單.xlsx>)', '[下載](</private/tmp/zook-inspect/A/上週 客服工單.xlsx>)', '[報告](</elsewhere/報告.docx>)', '[別的](</tmp/不認識.txt>)', '[下載](/tmp/zook-inspect/A/上週%20客服工單.xlsx)'])['linked']
        self.assertIn('<span class="file-ref">下載</span>', out[0]); self.assertIn('<span class="file-ref">下載</span>', out[1])  # #280: its card under the reply, not a second link
        self.assertIn('data-action="output-open" data-id="o1"', out[4])  # written so no card finds it: the link still opens it
        self.assertNotIn('output-open', out[2])  # only the same name somewhere else: a different file, not opened
        self.assertIn('local-link', out[3]); self.assertNotIn('output-open', out[3])


@unittest.skipUnless(NODE, 'needs node to run the page code')
class GroupPaths(unittest.TestCase):
    def test_group_link_with_spaces_hides_inner_path(self):
        line = block(CHAT, 'const esc =', 'const icons =') + block(CHAT, '  const hideInnerPaths', '\n')
        code = line + "\nconst w = '/Users/x/Library/Application Support/swarmr/workspaces/' + 'a'.repeat(32);\nconsole.log(hideInnerPaths('[下載](<' + w + '/週 報.docx>)') + '|' + hideInnerPaths('[下載](' + w + '/週報%20(1).docx \\'說明\\')') + '|' + hideInnerPaths('[下載](file:' + w + '/a.docx)'));"
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'g.js'; f.write_text(code, encoding='utf-8')
            out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), '下載：週 報.docx（群組檔案）|下載：週報 (1).docx（群組檔案）|下載：a.docx（群組檔案）', out.stderr)  # the name stays, so its file card shows


class LocalLinkClicks(unittest.TestCase):
    def test_click_opens_preview_or_copies(self):
        handler = block(OUTPUTS, "closest?.('.local-link')", 'function linkOutputs')
        self.assertIn('openOutput(hit[0], hit[1].id)', handler); self.assertIn("path.endsWith('/group-files/' + g.id + '/' + f.name)", handler); self.assertIn('openGroupFile(g.id', handler); self.assertIn('clipboard', handler)


if __name__ == '__main__': unittest.main()
