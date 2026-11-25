# -*- coding: utf-8 -*-
"""#87 #95 #128 #203: small group items.
- Free discussion: a member who speaks after others adds a different angle instead of repeating them, and keeps to the length
  the user asked for; the host's kickoff gives each member a different side; a closing host does not paste whole reports again;
  a weekday is checked on this Mac's calendar before it is written.
- The sidebar's second line is a short first line of the newest message, never the Bot's 工作指示.
- While a group runs, the line under the message box says who it is waiting for and how far the ask is (「正在等 研究助手 發言（2／3）」).
- 「整理結論（多用一次模型請求）」 is now 「請大家做個總結（會多用 1 次額度）」, and 請其他成員查核 says what it does once."""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_misc87', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)
JS = ROOT / 'frontend/js'
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)


class Store:
    def __init__(self, root): self.dir = Path(root); self.data = {'bots': [], 'knowledge': [], 'memories': [], 'jobs': []}
    def find(self, kind, key): return next((x for x in self.data[kind] if x['id'] == key), None)


def block(src, start, end):
    a = src.index(start); return src[a:src.index(end, a)]


def run_node(code):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'h.js'; f.write_text(code, encoding='utf-8')
        out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    if out.returncode != 0: raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


class GroupPrompt(unittest.TestCase):
    def setUp(self):
        m._active['data'] = {'settings': {}, 'rules': []}
        self.temp = tempfile.TemporaryDirectory(); self.store = Store(self.temp.name)
        self.bots = [dict(id=c * 32, name=n) for c, n in (('a', '管理員'), ('b', '研究助手'), ('c', '工作助理'))]
        self.store.data['bots'] += self.bots
        self.group = dict(id='g1', name='週會', botIds=[b['id'] for b in self.bots], messages=[
            dict(id='u1', role='user', content='尾牙要不要改地點，各說兩句'),
            dict(id='r1', role='assistant', botId=self.bots[0]['id'], content='先維持原地點。', status='completed')])

    def tearDown(self): self.temp.cleanup()

    def prompt(self, bot=1, **kw): return m.group_prompt(self.store, self.group, self.bots[bot], kw.pop('broadcast', True), **kw)

    def test_free_discussion_asks_for_another_angle_and_the_length_asked(self):
        p = self.prompt()
        self.assertIn('補充不同的角度', p); self.assertIn('各說兩句', p); self.assertIn('執行 cal', p)

    def test_independent_round_and_kickoff(self):
        self.assertIn('從你自己的角色和專長切入', self.prompt(moderated=True, blind=True))
        kick = self.prompt(bot=0, moderator='kickoff')
        self.assertIn('不同的面向或角度', kick); self.assertIn('執行 cal', kick)
        self.assertNotIn('補充不同的角度', self.prompt(moderated=True))  # answering the host already says not to repeat

    def test_closing_host_does_not_paste_reports_again(self):
        for role in ('final', 'check_final', 'moderate'):
            self.assertIn('不要整段重貼', self.prompt(bot=0, moderator=role), role)
        merge = self.prompt(bot=0, moderator='split_merge')  # it still merges the whole result, without pasting the reports word for word
        self.assertIn('合併成完整成果', merge); self.assertIn('不要把成員報告的原文整段照貼', merge); self.assertNotIn('存成檔案', merge)  # read-only: cannot save
        self.assertIn('成果很長時存成檔案', self.prompt(bot=0, moderator='split_merge', writable=True))
        self.assertNotIn('不要整段重貼', self.prompt(bot=0, moderator='kickoff'))

    def test_a_check_is_left_as_it_was(self):
        p = self.prompt(bot=2, moderator='verify', target=self.group['messages'][1])
        self.assertNotIn('執行 cal', p); self.assertNotIn('不要整段重貼', p)


@unittest.skipUnless(NODE, 'node is not installed')
class Screens(unittest.TestCase):
    def test_sidebar_line_is_short_and_never_the_instructions(self):
        chat = (JS / '10-chat.js').read_text(encoding='utf-8')
        code = block(chat, 'const plainPreview', 'function matches') + r"""
const long = '# 結論\n\n' + '很長的回覆'.repeat(40) + '\n第二行';
console.log(JSON.stringify([messagePreview({instructions: '你是一位行政助理，負責…很長的系統提示', messages: []}),
  messagePreview({messages: [{content: long}]}), messagePreview({messages: [{content: '**好的**，[報表](x.xlsx) 做好了'}]})]));"""
        empty, cut, plain = run_node(code)
        self.assertEqual(empty, '開始新的對話')
        self.assertTrue(cut.startswith('結論') or cut.startswith('很長'), cut); self.assertLessEqual(len(cut), 60); self.assertNotIn('第二行', cut)
        self.assertEqual(plain, '好的，報表 做好了')

    def test_waiting_line_names_who_and_how_far(self):
        groups = (JS / '35-groups.js').read_text(encoding='utf-8')
        code = """const state = {data: {bots: [{id: 'a', name: '管理員'}, {id: 'b', name: '研究助手'}, {id: 'c', name: '工作助理'}]}};
const groupMsgs = g => g.messages, groupMembers = g => g.botIds.map(id => state.data.bots.find(b => b.id === id));
""" + block(groups, 'function groupWaitText', 'function scheduleGroupEstimate') + r"""
const g = messages => ({botIds: ['a', 'b', 'c'], messages});
const ask = {role: 'user', content: '尾牙？'}, done = id => ({role: 'assistant', botId: id, status: 'completed', content: 'x'}), now = id => ({role: 'assistant', botId: id, status: 'running', content: ''});
console.log(JSON.stringify([groupWaitText(g([ask, done('a'), now('b')])), groupWaitText(g([ask, now('a')])), groupWaitText(g([ask, done('a'), done('b'), done('c'), now('a')])),
  groupWaitText(g([ask, done('a')])), groupWaitText(g([done('a'), ask, {role: 'user', interjected: true, content: '補一句'}, now('b')])), groupWaitText(g([ask, now('b'), now('c')]))]));"""
        second, first, again, idle, interjected, two = run_node(code)
        self.assertEqual(second, '正在等 研究助手 發言（2／3）'); self.assertEqual(first, '正在等 管理員 發言（1／3）')
        self.assertEqual(again, '正在等 管理員 發言'); self.assertEqual(idle, ''); self.assertEqual(interjected, '正在等 研究助手 發言（1／3）')
        self.assertEqual(two, '正在等 研究助手、工作助理 發言（2／3）')

    def test_plain_words_on_the_buttons(self):
        groups = (JS / '35-groups.js').read_text(encoding='utf-8')
        self.assertIn('請大家做個總結（會多用 1 次額度）', groups); self.assertNotIn('多用一次模型請求', groups)
        self.assertIn('另一位成員核對事實、數字和檔案，會多用 1 次額度', groups)
        self.assertIn('${esc(groupWaitText(g))}', groups)
        actions = (JS / '40-actions.js').read_text(encoding='utf-8')
        self.assertNotIn("20 MB。${ATTACH_HINT}", actions)  # it was shown as it is written in the 更多選項 window


if __name__ == '__main__':
    unittest.main()
