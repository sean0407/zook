# -*- coding: utf-8 -*-
"""巡檢 #58、#73: the memory page can be found from 設定 and a Bot's details and says in plain words what it is;
deleting a memory asks in Zook's own dialog; the Skills and connectors page hides local paths behind 編輯, tells
what to do on an empty 插件 tab, says which Skills are off, and names what a button adds."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = lambda name: (ROOT / 'frontend/js' / name).read_text(encoding='utf-8')


class MemoryPage(unittest.TestCase):
    def setUp(self):
        self.models, self.actions = JS('20-models.js'), JS('40-actions.js')

    def test_the_page_says_what_memory_is(self):
        self.assertIn('這裡是 Bot 幫你記住的習慣和偏好（例如：回覆用條列）。標「所有 Bot 共用」的每個 Bot 都知道；標 Bot 名稱的只有那個 Bot 知道。', self.models)
        self.assertIn('要改請直接跟 Bot 說「記住…」或「忘掉…」', self.models)  # #298: told first, in the lead line
        self.assertNotIn('Bot 記下的長期記憶', self.models)
        self.assertIn("'所有 Bot 共用'", self.models)
        self.assertIn('原 Bot 已刪除，沒有 Bot 會用到', self.models)
        self.assertNotIn(' 記下 · ', self.models)
        self.assertIn("' 記住'", self.models)

    def test_settings_and_bot_details_lead_to_it(self):
        self.assertIn("settingRow('記憶', 'Bot 記住的偏好，點此查看'", self.models)
        self.assertIn('data-action="page" data-id="memory"', self.models.split('function memoryNote(b)')[1].split('function detail(b)')[0])
        self.assertIn('${memoryNote(b)}', self.models.split('function detail(b)')[1].split('function formatDate')[0])

    def test_delete_asks_in_zook_and_says_it_cannot_be_undone(self):
        self.assertNotIn("confirm('確定刪除這則記憶？')", self.actions)
        block = self.actions.split("case 'delete-memory': {")[1].split("case 'group-continue'")[0]
        self.assertIn("await ask({title: '刪除這則記憶？'", block)  # the page's own dialog; it sends once and reports a failure
        self.assertIn('之後不會再記得這件事', block)
        self.assertIn('刪除後無法復原', self.actions)


class SkillsAndConnectors(unittest.TestCase):
    def setUp(self):
        self.models, self.actions = JS('20-models.js'), JS('40-actions.js')
        self.catalog, self.upkeep = JS('38-catalog.js'), JS('39-upkeep.js')

    def test_a_connector_card_shows_no_path(self):
        self.assertNotIn('(i.config.command || i.config.url)', self.models)
        self.assertIn('function connectorPlace(', self.models)
        self.assertIn("'這台 Mac 上的程式' + (name ? '（' + name + '）' : '') + '。'", self.models)

    def test_connector_place_names(self):
        # The plain name is worked out in the page; the same rules are checked here so they stay readable.
        body = self.models.split('function connectorPlace(')[1].split('\n  }')[0]
        for word in ['.app', '網址', '這台 Mac 上的程式']: self.assertIn(word, body)

    def test_an_empty_plugins_tab_says_what_to_do(self):
        self.assertIn('還沒有插件', self.models)
        self.assertIn('Claude Code 的「插件」管理', self.models)
        self.assertIn("await loadPage(id); render();", self.actions)
        self.assertIn('data-action="dir-tab" data-id="skills"', self.models)

    def test_switched_off_skills_say_so(self):
        self.assertIn("SKILLS_OFF = '未啟用'", self.models)
        self.assertIn('所有 Bot 都不會再用它', JS('50-forms.js'))  # the card switch is a change event

    def test_import_names_the_skills(self):
        self.assertIn("r.imported.join('、')", self.actions)

    def test_add_buttons_name_what_they_add(self):
        self.assertIn('aria-label="加入「${esc(t.name)}」"', self.upkeep)
        self.assertIn('aria-label="${esc(label + \'「\' + i.name + \'」\')}"', self.catalog)

    def test_a_failed_connection_is_not_cut_off(self):
        self.assertIn('<p class="dir-note error-text">沒有連上：', self.catalog)
        self.assertNotIn("'連線失敗：' + t.error : t?.status", self.models)

    def test_connector_types_in_plain_words(self):
        form = self.models.split('function connectorModal(')[1].split('\n  }')[0]
        self.assertNotIn('uvx', form.split('const types')[1].split(';')[0])
        self.assertNotIn('Streamable HTTP', form)


if __name__ == '__main__': unittest.main()
