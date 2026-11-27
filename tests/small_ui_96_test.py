# -*- coding: utf-8 -*-
"""queue #96, #53②–③, #215②–③: small things in groups and Bot details.

- A group file named twice in a reply (a link and its path in brackets) is said once: 「尾牙企劃書.pdf（群組檔案）」.
- A dropdown's last choice is never cut off: the menu is as tall as the room in the window allows.
- The new-group form has one scroll (no list scrolling inside the window), a search box for many Bots, and the
  主持人／討論方式／回合上限 settings come before the long member list.
- A shared file's name opens its preview; downloading is its own button.
- A Bot's details say its CLI, account, the model it really runs on and its thinking level; a group's member list too.
- A check that was left 「正在查核」 after its run ended does not make the page ask the Mac again every 2.5 seconds.
"""
import json, os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = {p.name: p.read_text(encoding='utf-8') for p in (ROOT / 'frontend/js').glob('*.js')}
CSS = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)


def block(name, start, end):
    src = JS[name]; a = src.index(start); return src[a:src.index(end, a)]


def run(code):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'h.js'; f.write_text(code, encoding='utf-8')
        out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    if out.returncode: raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, 'needs node to run the page code')
class GroupFileNames(unittest.TestCase):
    def names(self, texts):
        code = block('10-chat.js', 'const esc =', 'const icons =') + block('10-chat.js', '  const hideInnerPaths', '\n')
        return run(code + '\nconsole.log(JSON.stringify(%s.map(hideInnerPaths)));' % json.dumps(texts, ensure_ascii=False))

    def test_said_once(self):
        w = '/private/var/folders/x/workspaces/' + 'a' * 32 + '/尾牙企劃書.pdf'
        sup = '/Users/x/Library/Application Support/swarmr/workspaces/' + 'b' * 32 + '/尾牙企劃書.pdf'
        got = self.names([
            '已完成：[尾牙企劃書.pdf](%s) (%s)' % (w, w),   # the case from P02
            '已完成：尾牙企劃書.pdf (%s)' % w,
            '[%s](%s)' % (w, w),
            '已完成：尾牙企劃書.pdf（%s）' % sup,           # a path with a space in it
            '看 [尾牙企劃書.pdf](%s) 和 報價單.xlsx' % w,
            '報告 (第二版) 和 尾牙.pdf (草稿)',              # brackets that are not about a group file stay as they are
        ])
        self.assertEqual(got, ['已完成：尾牙企劃書.pdf（群組檔案）', '已完成：尾牙企劃書.pdf（群組檔案）', '尾牙企劃書.pdf（群組檔案）',
                               '已完成：尾牙企劃書.pdf（群組檔案）', '看 尾牙企劃書.pdf（群組檔案） 和 報價單.xlsx',
                               '報告 (第二版) 和 尾牙.pdf (草稿)'])


@unittest.skipUnless(NODE, 'needs node to run the page code')
class MenuFits(unittest.TestCase):
    def place(self, *cases):
        code = block('30-pages.js', '  function menuPlace', '\n  }\n') + '\n  }\n'
        return run(code + '\nconsole.log(JSON.stringify(%s.map(c => menuPlace(...c))));' % json.dumps(cases))

    def test_whole_menu_shows_when_there_is_room(self):
        # (button top, button bottom, menu's natural height, window height)
        below, above, squeezed = self.place([300, 330, 377, 768], [600, 630, 377, 768], [200, 230, 700, 600])
        self.assertEqual(below, {'top': 336, 'maxHeight': 377})  # 6 ways with their hints: none cut off (was 340)
        self.assertEqual(above, {'top': 217, 'maxHeight': 377})
        self.assertLessEqual(squeezed['top'] + squeezed['maxHeight'], 600 - 8)  # never past the window's edge
        self.assertGreaterEqual(squeezed['top'], 8)

    def test_used_when_opening(self):
        self.assertIn('menuPlace(r.top, r.bottom', JS['30-pages.js'])


class GroupForm(unittest.TestCase):
    def test_one_scroll_search_and_settings_first(self):
        form = block('10-chat.js', '  function groupModal', '\n  }\n')
        self.assertIn('data-member-search', form)
        self.assertLess(form.index('groupSettingRows('), form.index('member-pick'))  # 主持人／討論方式／回合上限 before the long list
        self.assertRegex(CSS, r'#group-form \.member-pick \{[^}]*max-height: none')
        self.assertIn("'memberSearch'", JS['50-forms.js'])


class GroupFilesTab(unittest.TestCase):
    def test_name_opens_preview(self):
        tab = block('35-groups.js', '  function groupFilesTab', '\n  }\n')
        self.assertIn('data-group-file=', tab)
        self.assertIn('>下載</a>', tab)


@unittest.skipUnless(NODE, 'needs node to run the page code')
class ModelLine(unittest.TestCase):
    def line(self, bot, jobs=(), settings=None):
        stub = 'const esc = s => s; const state = %s;\nconst efforts = () => [{id: "standard", name: "標準"}, {id: "fast", name: "快速"}, {id: "medium", name: "中"}, {id: "deep", name: "深入"}];\n' % json.dumps({
            'data': {'settings': settings or {'provider': 'codex'}, 'jobs': list(jobs)}, 'modelNames': {},
            'providers': [{'id': 'codex', 'name': 'Codex', 'accounts': [{'id': 'w', 'name': 'Waifdance'}]}, {'id': 'claude', 'name': 'Claude'}]}, ensure_ascii=False)
        stub += 'const providerList = () => state.providers; const providerShort = id => id === "auto" ? "自動選擇" : providerList().find(p => p.id === id)?.name || id;\n'
        stub += block('20-models.js', '  function modelWords', '\n  }\n') + '\n  }\n'
        return run(stub + block('20-models.js', '  function botModelLine', '\n  }\n') + '\n  }\nconsole.log(JSON.stringify(botModelLine(%s)));' % json.dumps(bot, ensure_ascii=False))

    def test_account_model_and_effort(self):
        self.assertEqual(self.line({'id': 'b', 'provider': 'codex', 'account': 'w', 'model': 'gpt-6-luna', 'effort': 'deep'}), 'Codex（Waifdance） · GPT 6 Luna · 思考強度：深入')  # the set model in words (#154②)
        # no model set: the one its last reply really ran on
        self.assertEqual(self.line({'id': 'b', 'provider': 'claude'}, [{'botId': 'b', 'usage': {'provider': 'claude', 'model': 'claude-opus-5-5'}}]), 'Claude · 預設型號（最近一次是 claude-opus-5-5） · 思考強度：標準')
        self.assertEqual(self.line({'id': 'b', 'provider': ''}), 'Codex · 預設型號 · 思考強度：標準')
        jobs = [{'botId': 'b', 'usage': {'provider': 'claude', 'model': 'old'}}, {'botId': 'x', 'usage': {'provider': 'grok', 'model': 'other-bot'}}, {'botId': 'b', 'usage': {'provider': 'grok', 'model': 'grok-5'}}]
        self.assertEqual(self.line({'id': 'b', 'provider': 'auto', 'effort': 'fast'}, jobs), '自動選擇 · 預設型號（最近一次是 grok-5） · 思考強度：快速')  # 自動選擇: whichever it used last
        self.assertEqual(self.line({'id': 'b', 'provider': 'claude'}, jobs), 'Claude · 預設型號（最近一次是 old） · 思考強度：標準')  # only that CLI's replies

    def test_used_in_details_and_member_list(self):
        self.assertIn('botModelLine(b)', block('20-models.js', '  function detail(b)', '\n  }\n'))
        self.assertIn('botModelLine(b', JS['10-chat.js'])


@unittest.skipUnless(NODE, 'needs node to run the page code')
class LeftoverCheck(unittest.TestCase):
    def test_no_loop_once_the_mac_said_it_ended(self):
        fn = block('35-groups.js', '  const groupNeedsPoll', '\n')
        code = 'const state = {groupQuiet: {}}; const groupMsgs = g => g.messages; const groupFileMark = g => g.messages.length + ":" + g.messages.map(m => m.status).join();\n' + fn + '''
const g = {id: 'g', status: 'idle', messages: [{id: 'a', status: 'completed'}, {id: 'c', checkOf: 'a', status: 'running'}]};
const before = groupNeedsPoll(g);
state.groupQuiet.g = groupFileMark(g);  // what pollGroup notes when the Mac says the run is over
const after = groupNeedsPoll(g);
g.messages.push({id: 'd', checkOf: 'a', status: 'running'});
const changed = groupNeedsPoll(g);
console.log(JSON.stringify([before, after, changed, groupNeedsPoll({id: 'h', status: 'running', messages: []})]));'''
        self.assertEqual(run(code), [True, False, True, True])
        self.assertIn('state.groupQuiet[groupId] = groupFileMark(data.group)', JS['10-chat.js'])


if __name__ == '__main__':
    unittest.main()
