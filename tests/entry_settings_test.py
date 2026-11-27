# -*- coding: utf-8 -*-
"""起步指引、說明與常用入口 (#308 #66① #272)，設定頁的「進階」與改了就存 (#300)."""
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))
CSS = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')


def body(name):
    """The source of one function, up to the next top-level function of the same file."""
    m = re.search(r'\n  (?:async )?function ' + re.escape(name) + r'\(.*?(?=\n  (?:async )?function |\n  const |\n  document\.addEventListener)', JS, re.S)
    if not m: raise AssertionError('no function ' + name)
    return m.group(0)


class Entries(unittest.TestCase):
    def test_start_steps_name_each_first_thing_and_lead_there(self):
        steps = body('startCard')
        for words in ('加帳號', '建第一個 Bot', '問一句話', '建群組', '看用量'):
            self.assertIn(words, JS, words)
        self.assertIn('START_STEPS', steps)
        for go in ('data-action="page" data-id="usage"', 'data-action="new-bot"', 'data-action="new-group"', 'data-start="ask"'):
            self.assertIn(go, JS, go)

    def test_start_steps_show_on_the_home_and_empty_states(self):
        self.assertIn('startCard(true)', body('emptyIntro'))
        self.assertIn('startCard(true)', body('chat'))  # no Bot yet
        self.assertIn("inChat && state.data.settings.startTips === false", body('startCard'))  # hidden once 收起, always in 說明

    def test_only_one_start_card(self):
        # 2026-11-27 user: the old three-step 開始使用 Zook card is gone; 從這裡開始 shows on a fresh install (startTips not set yet)
        for old in ('function guideCard', 'function guideSteps', 'function finishGuide', '開始使用 Zook', 'guide-card', 'data-up="guide-'):
            self.assertNotIn(old, JS, old)
        self.assertNotIn('.guide-card', CSS)
        self.assertIn("inChat && state.data.settings.startTips === false) return ''", body('startCard'))  # only an explicit 收起 hides it

    def test_help_has_an_address_and_entries_are_in_plain_sight(self):
        self.assertIn("'help'", re.search(r'PAGE_HASHES = \[[^\]]*\]', JS).group(0))
        self.assertIn("help: '說明'", JS)
        self.assertIn('helpPage()', body('page'))
        side = body('sidebar')
        self.assertIn('${sideNav()}', side)
        self.assertIn('SIDE_NAV.map', body('sideNav'))
        nav = re.search(r'const SIDE_NAV = \[.*?\];', JS).group(0)
        for page in ('usage', 'schedules', 'knowledge', 'skills', 'help'):
            self.assertIn("['" + page + "'", nav, page)
        self.assertIn("['help', '?', '說明']", side)  # also in 我的工作區

    def test_start_tips_setting_is_a_plain_switch(self):
        spec = importlib.util.spec_from_file_location('swarmr_entry_settings', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        data = {'settings': {}}
        changes = {}
        module.upkeep_fields(data, {'startTips': False}, changes)
        self.assertEqual(changes['startTips'], False)
        with self.assertRaises(ValueError):
            module.upkeep_fields(data, {'startTips': 'no'}, {})


class SettingsPage(unittest.TestCase):
    def test_advanced_is_folded_by_default(self):
        page = body('page')
        self.assertIn('advancedSettings()', page)
        adv = body('advancedSettings')
        for part in ('taskSection()', 'syncSection()', 'updateSection()'):
            self.assertIn(part, adv)
            self.assertNotIn('+ ' + part + ' +', page.split('advancedSettings()')[0][-400:])
        self.assertIn("state.folds.settingsAdvanced ? 'open' : ''", adv)  # closed unless opened

    def test_everything_saves_when_changed(self):
        for word in ('儲存規則', '儲存模型設定', 'data-unsaved hidden>尚未儲存', '改完要按'):
            self.assertNotIn(word, JS, word)
        self.assertIn('function saveModelSettings(form)', JS)
        self.assertIn('function saveRules(', JS)
        self.assertIn('✓ 已儲存', JS)

    def test_only_the_last_of_several_saves_counts(self):
        save = body('autoSave')
        self.assertIn('if (seq !== autoSave.seq) return false;', save)  # a late answer neither restores an older value nor marks a row
        self.assertIn('state.savedFlash = {title,', save)
        for fn in ('saveModelSettings', 'saveRules'):
            self.assertIn('autoSave(', body(fn))
            self.assertNotIn("post('settings'", body(fn))


if __name__ == '__main__': unittest.main()
