# -*- coding: utf-8 -*-
"""#214: what was open last is remembered per window. Each tab keeps its own Bot, group and conversation in sessionStorage,
which its reload reads first; localStorage only seeds a new tab. The Mac's open conversation of a Bot (bot.chatId) stays what
the phone and a new window use. Every storage read and write is inside try/catch."""
import json, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'
FILE = JS / '34c-lastopen.js'


def source(name): return (JS / name).read_text(encoding='utf-8')


def case(text, action):
    start = text.index("case '%s':" % action)
    nxt = text.find('\n        case ', start + 1)
    return text[start:nxt if nxt > 0 else None]


class LastOpenSource(unittest.TestCase):
    def test_one_place_reads_and_writes(self):
        self.assertTrue(FILE.exists(), 'the per-window memory lives in 34c-lastopen.js')
        for f in sorted(JS.glob('*.js')):
            if f == FILE: continue
            self.assertNotIn('zook-last-chat', f.read_text(encoding='utf-8'), '%s touches the last-open key directly' % f.name)
        self.assertIn('restoreLastOpen()', source('30-pages.js'))
        self.assertIn('saveLastOpen()', source('20-models.js'))

    def test_storage_only_inside_try(self):
        for n, line in enumerate(FILE.read_text(encoding='utf-8').splitlines(), 1):
            if re.search(r'\b(sessionStorage|localStorage)\b', line) and not line.lstrip().startswith('//'):
                self.assertIn('try', line, 'line %d uses storage outside try' % n)

    def test_this_windows_own_choices_count(self):
        actions = source('40-actions.js')
        for action in ('open-chat', 'new-chat', 'delete-chat', 'select-bot'):
            self.assertIn('chooseChat(', case(actions, action), action)
        pages = source('30-pages.js')
        body = pages[pages.index('async function openConversation'):pages.index('// Keep a message that was jumped to')]
        jump = next(l for l in body.splitlines() if 'where?.chatId' in l)
        self.assertNotIn('chooseChat(', jump)  # not only when the jump switched conversations: always, for a Bot
        self.assertIn('state.selected = id; chooseChat(id);', body)
        forms = source('50-forms.js')
        self.assertIn('chooseChat(botId)', forms)  # sending in a conversation makes it this window's


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class LastOpenBehaviour(unittest.TestCase):
    """Runs 34c-lastopen.js in node with two fake tabs sharing one localStorage."""
    HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const code = fs.readFileSync(process.argv[2], 'utf8');
function store(init) { const m = new Map(Object.entries(init || {})); return {getItem: k => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, String(v)), dump: () => Object.fromEntries(m)}; }
const shared = store();
const bots = () => [{id: 'x', chatId: 'c2', chats: [{id: 'c1'}, {id: 'c2'}]}, {id: 'y', chatId: 'd1', chats: [{id: 'd1'}]}];
function tab(session, data) {
  const posted = [];
  const ctx = {state: {page: 'chat', data: data || {bots: bots(), groups: [{id: 'g'}]}}, sessionStorage: session, localStorage: shared,
    post: p => { posted.push(p); return Promise.resolve({}); }, refresh: () => Promise.resolve(), posted, JSON, Object};
  vm.createContext(ctx); vm.runInContext(code + '\n;this.restoreLastOpen = restoreLastOpen; this.saveLastOpen = saveLastOpen; this.chooseChat = chooseChat;', ctx);
  return ctx;
}
const out = {};
// Tab A opens group g; tab B opens Bot x, conversation c1 (B chose it), then the Mac's open conversation of x becomes c2.
const sa = store(), sb = store();
let a = tab(sa); a.restoreLastOpen(); a.state.lastRestored = true; a.state.groupId = 'g'; a.state.selected = 'y'; a.saveLastOpen();
let b = tab(sb); b.restoreLastOpen(); b.state.lastRestored = true; b.state.groupId = null; b.state.selected = 'x';
b.state.data.bots[0].chatId = 'c1'; b.chooseChat('x'); b.state.data.bots[0].chatId = 'c2'; b.saveLastOpen();
// Reload A: its own group, not B's Bot.
a = tab(sa); a.restoreLastOpen(); out.aGroup = a.state.groupId || null; out.aPosted = a.posted;
// Reload B: Bot x, and its own conversation c1 is opened again on the Mac.
b = tab(sb); b.restoreLastOpen(); out.bBot = b.state.selected; out.bGroup = b.state.groupId || null; out.bPosted = b.posted;
// Before the re-open arrives the page still shows the Mac's c2: drawing it must not replace this tab's own c1.
b.state.lastRestored = true; b.saveLastOpen(); out.bKept = JSON.parse(sb.getItem('zook-last-chat')).chats.x;
// A new tab: the last window's Bot/group, the Mac's conversation (nothing opened).
const c = tab(store()); c.restoreLastOpen(); out.cBot = c.state.selected; out.cPosted = c.posted;
// Broken storage: nothing throws.
const broken = {getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); }};
const d = tab(broken); d.restoreLastOpen(); out.brokenBot = d.state.selected; d.state.lastRestored = true; d.state.selected = 'x'; d.saveLastOpen(); d.chooseChat('x'); out.brokenOk = true;
// A conversation that was deleted meanwhile is not opened.
const se = store({'zook-last-chat': JSON.stringify({bot: 'x', group: '', chats: {x: 'gone'}})});
const e = tab(se); e.restoreLastOpen(); out.gonePosted = e.posted;
console.log(JSON.stringify(out));
'''

    def test_two_tabs(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / 'h.js'; harness.write_text(self.HARNESS, encoding='utf-8')
            run = subprocess.run(['node', str(harness), str(FILE)], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(out['aGroup'], 'g')
        self.assertEqual(out['aPosted'], [])
        self.assertEqual(out['bBot'], 'x'); self.assertIsNone(out['bGroup'])
        self.assertEqual(out['bPosted'], ['bots/x/chats/c1/open'])
        self.assertEqual(out['bKept'], 'c1')
        self.assertEqual(out['brokenBot'], 'x')  # this tab's storage blocked: the shared one still gives a start
        self.assertEqual(out['cBot'], 'x'); self.assertEqual(out['cPosted'], [])
        self.assertTrue(out['brokenOk'])
        self.assertEqual(out['gonePosted'], [])


if __name__ == '__main__':
    unittest.main()
