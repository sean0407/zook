# -*- coding: utf-8 -*-
"""#181 #306 #303 #288 on the Skills 與連接器 page: a plain-words header, a Chinese 「能做什麼」 on every card, writing a Skill,
the catalog on top with 自己新增 under 進階, one search box that says which other tab has matches, and a 已關閉 section."""
import json, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'


def source(name): return (JS / name).read_text(encoding='utf-8')


class PageSource(unittest.TestCase):
    def setUp(self): self.models, self.forms, self.page = source('20-models.js'), source('50-forms.js'), source('38d-skillforms.js')

    def test_header_says_what_skills_and_connectors_are(self):
        intro = self.page.split('function dirPageIntro()')[1].split('\n  }')[0]
        for words in ('Skill</strong> 是寫給 Bot 的做事方法', '連接器</strong>讓 Bot 能使用外部服務', '所有 Bot、所有模型共用', '知識庫', '記憶'): self.assertIn(words, intro)
        self.assertIn('${dirPageIntro()}<div class="dir-bar">', self.models)

    def test_catalog_first_and_adding_by_hand_under_advanced(self):
        page = self.models.split('function directoryPage(')[1].split('\n  }\n')[0]
        self.assertLess(page.index("${tab === 'mcp' ? catalogSections(q) : ''}"), page.index('${groups.length ? groups.map'))
        self.assertNotIn('connector-add', page)
        advanced = self.page.split('function mcpAdvanced()')[1].split('\n  }')[0]
        self.assertIn('<span>進階</span>', advanced); self.assertIn('data-action="connector-add">＋ 自己新增', advanced)
        self.assertIn('成功才開啟', advanced)

    def test_a_new_connector_reports_its_first_test(self):
        block = self.forms.split("form.id === 'connector-form'")[1].split("form.id === 'profile-form'")[0]
        self.assertIn('connectorAddedNote(made)', block); self.assertIn('state.mcpTests[made.id] = made.test', block)
        note = self.page.split('function connectorAddedNote(')[1].split('\n  }')[0]
        self.assertIn('先維持關閉', note); self.assertIn('要先登入', note)
        self.assertIn('connectorOnIfReady(made.id)', source('38-catalog.js'))

    def test_skill_form_is_plain_fields(self):
        form = self.page.split('function skillModal(')[1].split('\n  }')[0]
        for field in ('name="name"', 'name="description"', '<textarea name="body"', '只是文字，不能執行程式', '照你的核准設定先問你'): self.assertIn(field, form)
        self.assertNotIn('<select', form)
        self.assertIn('data-up="skill-new">＋ 新增 Skill', self.models)
        self.assertIn('data-up="skill-edit"', self.models)

    def test_search_box_is_one_for_the_three_tabs(self):
        self.assertIn("q ? dirMatches(id, q) + ' 個符合'", self.models)
        self.assertIn('dirNoMatch(tab, q)', self.models)
        self.assertIn('搜尋框是三個分頁共用的', self.page)


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class Cards(unittest.TestCase):
    HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const models = fs.readFileSync(process.argv[2], 'utf8'), page = fs.readFileSync(process.argv[3], 'utf8');
const code = models.slice(models.indexOf('const SOURCE_NAMES'), models.indexOf('function directoryPage(')) + page;
const input = JSON.parse(process.argv[4]);
const ctx = {state: input.state, esc: s => String(s), console, document: {addEventListener() {}}};
vm.createContext(ctx);
vm.runInContext(code + '\nthis.out = {items: directoryItems(' + JSON.stringify(input.tab) + '), none: dirNoMatch(' + JSON.stringify(input.tab) + ', ' + JSON.stringify(input.q) + ')};', ctx);
console.log(JSON.stringify(ctx.out));
'''

    def run_page(self, state, tab, q=''):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / 'h.js'; h.write_text(self.HARNESS, encoding='utf-8')
            out = subprocess.run(['node', str(h), str(JS / '20-models.js'), str(JS / '38d-skillforms.js'), json.dumps({'state': state, 'tab': tab, 'q': q})], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout); return {i['id']: i for i in result['items']}, result['none']

    def state(self, skills=(), mcp=(), off=(), shared=()):
        return {'integrations': {'skills': list(skills), 'mcp': list(mcp), 'plugins': []}, 'mcpTests': {}, 'templates': [], 'catalog': [],
                'dirQuery': '', 'data': {'settings': {'disabledSkills': list(off), 'sharedMcp': list(shared)}}}

    def test_every_skill_card_says_what_it_can_do_in_chinese(self):
        skills = [{'id': 's:en', 'name': 'pdf', 'description': 'Use this skill whenever the user wants to do anything with PDF files.', 'source': 'claude'},
                  {'id': 's:zh', 'name': '客服回覆', 'description': '依公司語氣回覆客戶問題。', 'source': 'zook', 'origin': 'custom', 'editable': True}]
        items, _ = self.run_page(self.state(skills, off=['s:en']), 'skills')
        self.assertTrue(items['s:en']['description'].startswith('能做什麼：製作或處理文件'))
        self.assertIn('原文說明：Use this skill', items['s:en']['description'])
        self.assertEqual(items['s:zh']['description'], '能做什麼：依公司語氣回覆客戶問題。')
        self.assertTrue(items['s:zh']['writable']); self.assertNotIn('editable', items['s:zh'])  # editable is the connector card's 編輯/移除; self.assertEqual(items['s:zh']['meta'], '你寫的 Skill')
        self.assertEqual((items['s:en']['group'], items['s:zh']['group']), ('已關閉', '已開啟'))

    def test_a_connector_switched_off_goes_to_its_own_section(self):
        mcp = [{'id': 'zook:on', 'name': 'Notion', 'source': 'zook', 'editable': True, 'about': '搜尋、讀取和編輯 Notion 的頁面與資料庫。', 'config': {'url': 'https://mcp.notion.com/mcp'}},
               {'id': 'zook:off', 'name': 'Mine', 'source': 'zook', 'editable': True, 'config': {'command': 'mine'}},
               {'id': 'codex:x', 'name': 'Found', 'source': 'codex', 'copyable': True}]
        items, _ = self.run_page(self.state(mcp=mcp, shared=['zook:on']), 'mcp')
        self.assertEqual(items['zook:on']['group'], '已連接'); self.assertEqual(items['zook:off']['group'], '已關閉')
        self.assertEqual(items['codex:x']['group'], '在這台 Mac 上找到的')  # not one you added: stays with what was found
        self.assertEqual(items['zook:on']['description'], '能做什麼：搜尋、讀取和編輯 Notion 的頁面與資料庫。')
        self.assertIn('按「測試連線」看它能做什麼', items['zook:off']['description'])

    def test_an_empty_tab_names_the_tab_with_matches(self):
        state = self.state(skills=[{'id': 's:a', 'name': 'Notion 筆記', 'description': '整理筆記。', 'source': 'zook'}], mcp=[{'id': 'zook:n', 'name': 'Notion', 'source': 'zook', 'editable': True}])
        state['dirQuery'] = 'Notion'
        _, none = self.run_page(state, 'plugins', 'notion')
        self.assertIn('插件裡沒有符合「Notion」的項目', none)
        self.assertIn('data-id="skills">看Skills（1 個）', none); self.assertIn('data-id="mcp">看連接器（1 個）', none)
        _, here = self.run_page(state, 'skills', 'notion')
        self.assertEqual(here, '')


if __name__ == '__main__': unittest.main()
