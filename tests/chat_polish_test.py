# -*- coding: utf-8 -*-
"""#89/#45/#169: the single-Bot chat.
- An option button under a finished reply fills the message box instead of sending at once (a click that lands on it by
  mistake, when the page moves, sends nothing).
- A bare file:///… in a reply is a link that opens Zook's preview (or copies the path), like a Markdown link to a file.
- A message the Mac takes a while to accept shows 「已送出，Bot 準備中…」 instead of staying on 「傳送中…」.
- zook_read_skill tells the model to pass skill_id (Antigravity first tried skill_name and failed)."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)


def block(src, start, end):
    a = src.index(start); return src[a:src.index(end, a)]


def run_node(code):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'h.js'; f.write_text(code, encoding='utf-8')
        out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    if out.returncode != 0: raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


CHOICES = r"""
const handlers = {};
const document = {addEventListener: (t, f) => (handlers[t] = handlers[t] || []).push(f)};
const input = {value: '', focused: false, focus() { this.focused = true; }, setSelectionRange() {}, dispatchEvent() {}};
const $ = s => s === '#chat-input' ? input : null;
const state = {selected: 'b1', data: {settings: {}}};
const posted = [];
const post = (...a) => { posted.push(a); return Promise.resolve({}); };
const render = () => {}, toast = () => {}, refresh = async () => {}, poll = () => {}, esc = s => String(s), jobsForBot = () => [];
__CODE__
function click(text) {
  const row = {querySelectorAll: () => []};
  const chip = {dataset: {choice: text}, disabled: false, closest: () => row};
  const e = {target: {closest: sel => sel === '[data-choice]' ? chip : null}, preventDefault() {}};
  for (const f of handlers.click) f(e);
}
click('改成到職週年區間');
const first = input.value, focused = input.focused;
input.value = '請再加合計列';
click('改成到職週年區間');
setTimeout(() => console.log(JSON.stringify({posted: posted.length, first, focused, second: input.value})), 50);
"""

SENDING = r"""
const window = globalThis, document = {addEventListener() {}};
const state = {sending: []};
const esc = s => String(s);
let renders = 0;
const render = () => { renders++; }, refresh = async () => {}, poll = () => {}, pollGroup = () => {};
let fail = null;
const post = () => new Promise((_, no) => { fail = no; });
__CODE__
const s = sendingAdd('b1/c1', 'chat', {content: '追問一下'});
sendingSend(s);
const early = sendingView('b1/c1', []);
setTimeout(() => {
  const later = sendingView('b1/c1', []), drawn = renders;
  fail(new Error('連不上 Zook'));
  setTimeout(() => console.log(JSON.stringify({early, later, drawn, failed: sendingView('b1/c1', [])})), 20);
}, 2500);
"""


@unittest.skipUnless(NODE, 'needs node to run the page code')
class ChatPage(unittest.TestCase):
    def test_option_button_fills_the_box_and_sends_nothing(self):
        out = run_node(CHOICES.replace('__CODE__', (JS / '33-choices.js').read_text(encoding='utf-8')))
        self.assertEqual(out['posted'], 0)                                   # nothing sent by the click
        self.assertEqual(out['first'], '改成到職週年區間'); self.assertTrue(out['focused'])
        self.assertEqual(out['second'], '請再加合計列\n改成到職週年區間')        # what was typed stays; the option is added

    def test_slow_send_says_it_is_on_its_way(self):
        look = (JS / '38-look.js').read_text(encoding='utf-8')
        out = run_node(SENDING.replace('__CODE__', look[look.index('// Sending:'):]))
        self.assertIn('傳送中…', out['early'])
        self.assertIn('已送出，Bot 準備中…', out['later']); self.assertNotIn('傳送中…', out['later'])
        self.assertGreater(out['drawn'], 0)                                  # the page is drawn again when the words change
        self.assertIn('沒有送出：連不上 Zook', out['failed']); self.assertNotIn('準備中', out['failed'])

    def test_quick_send_never_says_preparing(self):
        look = (JS / '38-look.js').read_text(encoding='utf-8')
        code = SENDING.replace('__CODE__', look[look.index('// Sending:'):]).split('const s = sendingAdd')[0].replace(
            'const post = () => new Promise((_, no) => { fail = no; });', 'const post = () => Promise.resolve({});')
        out = run_node(code + "const s = sendingAdd('b1/c1', 'chat', {content: 'x'}); sendingSend(s);\n"
                       "setTimeout(() => console.log(JSON.stringify({slow: !!s.slow, done: s.done})), 2000);")
        self.assertEqual(out, {'slow': False, 'done': True})

    def test_bare_file_url_opens_like_a_file_link(self):
        chat = (JS / '10-chat.js').read_text(encoding='utf-8')
        code = HARNESS_MD.replace('__CHAT__', block(chat, 'const esc =', 'const icons ='))
        out = run_node(code)
        html = out[0]
        self.assertIn('class="link local-link" data-path="/tmp/zook out/chart.png"', html)
        self.assertIn('>file:///tmp/zook%20out/chart.png</button>。', html)    # the full stop is not part of the path
        self.assertNotIn('href="file:', html)
        self.assertIn('data-path="/Users/x/報告.docx"', out[1])
        self.assertNotIn('local-link', out[2])                               # inside `code` it stays as written
        self.assertNotIn('local-link', out[3])                               # file://host/… is not a file on this Mac
        self.assertIn('data-path="/tmp/a.png"', out[4]); self.assertIn('</button>，然後', out[4])   # ends at Chinese punctuation
        self.assertIn('data-path="/tmp/b.png"', out[4])
        self.assertIn('data-path="/tmp/報告.docx"', out[5])                  # no space before it, Chinese in the name
        self.assertIn('<strong><button', out[6])


HARNESS_MD = r"""
const document = {createElement: () => { const t = {}; Object.defineProperty(t, 'innerHTML', {set(v) { t.value = v.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&'); }}); return t; }};
__CHAT__
console.log(JSON.stringify(['圖在 file:///tmp/zook%20out/chart.png。', '（file:///Users/x/%E5%A0%B1%E5%91%8A.docx）', '`file:///tmp/a.png`', 'file://server/share/a.png', '請開啟 file:///tmp/a.png，然後 file:///tmp/b.png。', '圖在file:///tmp/報告.docx', '**file:///tmp/c.png**'].map(markdown)));
"""


class SkillTool(unittest.TestCase):
    def test_read_skill_says_to_pass_skill_id(self):
        sys.path.insert(0, str(ROOT / 'backend'))
        import runtime
        with tempfile.TemporaryDirectory() as d:
            skill = Path(d) / 's'; skill.mkdir(); (skill / 'SKILL.md').write_text('x', encoding='utf-8')
            inventory = {'skills': [{'id': 'skill:t', 'name': '報表'}], 'mcp': [],
                         '_private': {'skills': {'skill:t': {'path': str(skill / 'SKILL.md'), 'root': str(skill)}}, 'mcp': {}}}
            session = runtime.RuntimeSession(['skill:t'], [], False, Path(d), lambda *a: True, lambda e: None, inventory)
            try: tools = {t['name']: t for t in session.tools()}
            finally: session.close()
        for name in ('zook_read_skill', 'zook_read_skill_resource'):
            self.assertIn('skill_id', tools[name]['description'])
            self.assertIn('not the name', tools[name]['description'])


if __name__ == '__main__':
    unittest.main()
