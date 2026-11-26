# -*- coding: utf-8 -*-
"""設定頁 (#75, #76, #186, #187, #188): model lists with plain names, readable grey text, menus that work from the keyboard,
words a newcomer understands, what is saved and what is not, and a page that fits a phone."""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
CSS = re.sub(r'/\*.*?\*/', '', (ROOT / 'frontend/style.css').read_text(encoding='utf-8'), flags=re.S)
JS = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


def rule(selector):
    """The body of the first top-level rule whose selector list is exactly this selector."""
    for m in re.finditer(r'(?:(?<=\})|^)\s*([^{}@]+?)\s*\{([^{}]*)\}', CSS):
        if [s.strip() for s in m.group(1).split(',')] == [selector]:
            return m.group(2)
    raise AssertionError('no rule for ' + selector)


def color(body):
    return re.search(r'(?<![-\w])color:\s*#([0-9a-f]{6}|[0-9a-f]{3})\b', body, re.I).group(1)


def luminance(rgb):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    return .2126 * ch(rgb[0]) + .7152 * ch(rgb[1]) + .0722 * ch(rgb[2])


def contrast(a, b):
    x, y = luminance(a), luminance(b)
    return (max(x, y) + .05) / (min(x, y) + .05)


def rgb(hexa):
    hexa = hexa if len(hexa) == 6 else ''.join(c * 2 for c in hexa)
    return [int(hexa[i:i + 2], 16) for i in (0, 2, 4)]


def dark(c):
    """The dark look inverts the page with filter: invert(.92) (style.css)."""
    return [round(v * (1 - 2 * .92) + 255 * .92) for v in c]


class ModelLists(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location('swarmr_settings_page', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_gemini_offers_its_three_short_names(self):
        module = self.load()
        with mock.patch.object(module, 'find_cli', return_value=None):
            result = module.model_list('gemini')
        self.assertEqual([m['id'] for m in result['models']], ['pro', 'flash', 'flash-lite'])  # names Gemini CLI itself accepts with -m
        self.assertTrue(all('（' in m['name'] for m in result['models']))  # with a few words on what each is for

    def test_claude_lists_its_aliases_even_when_its_help_does_not(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as home, mock.patch.object(module.pathlib.Path, 'home', return_value=Path(home)), \
                mock.patch.object(module, 'find_cli', return_value=None):
            result = module.model_list('claude')
        self.assertEqual([m['id'] for m in result['models']], ['opus', 'sonnet', 'haiku'])
        self.assertEqual(result['models'][0]['name'], 'Opus（最強）')

    def test_notes_are_plain_words(self):
        source = (ROOT / 'backend/zook/library.py').read_text(encoding='utf-8')
        for word in ('本機 Codex 服務', '使用本機快取', '別名來自 CLI', 'grok models 取得', 'agy models 取得', 'cursor-agent models 取得', '模型 ID'):
            self.assertNotIn(word, source)


class Readable(unittest.TestCase):
    def test_grey_text_on_the_settings_page_is_at_least_4_5_to_1_in_both_looks(self):
        white = [255, 255, 255]
        greys = {'--muted': re.search(r'--muted:\s*#([0-9a-f]{6})', CSS).group(1)}
        for sel in ('.muted', '.page p', '.setting-copy span', '.dd-opt small', '.model-note', '.link', '.plain-copy span', '.unsaved-note', '.saved-flash'):
            greys[sel] = color(rule(sel))
        for name, value in greys.items():
            c = rgb(value)
            self.assertGreaterEqual(contrast(c, white), 4.5, name + ' in the light look')
            self.assertGreaterEqual(contrast(dark(c), dark(white)), 4.5, name + ' in the dark look')


class Layout(unittest.TestCase):
    def test_rows_wrap_instead_of_squeezing_the_title(self):
        self.assertRegex(rule('.setting-row'), r'flex-wrap:\s*wrap')
        self.assertRegex(rule('.setting-copy'), r'flex:\s*1 1 \d+em')  # the words keep about a dozen characters; the control goes under them
        self.assertRegex(CSS, r'\.model-row \.model-tools\s*\{[^}]*flex:\s*1 1 100%')  # the model note runs under the whole row (#75①)
        self.assertRegex(rule('.setting-copy span'), r'overflow-wrap:\s*anywhere')  # a long folder path cannot push the row off a phone screen

    def test_the_gear_says_settings(self):
        self.assertTrue('gear-btn" data-action="page" data-id="settings" title="設定">${svg(\'settings\')}<span>設定</span>' in JS, 'gear-btn" data-action="page" data-id="settings" title="設定">${svg(\'settings\')}<span>設定</span>')


class Keyboard(unittest.TestCase):
    def test_arrow_keys_move_through_an_open_menu(self):
        self.assertTrue("['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)" in JS, "['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)")
        self.assertTrue("dd.querySelector('.dd-btn').focus({preventScroll: true});  // the keyboard stays on this menu" in JS, "dd.querySelector('.dd-btn').focus({preventScroll: true});  // the keyboard stays on this menu")

    def test_skip_link_and_focus_kept_after_a_redraw(self):
        self.assertTrue('data-skip>跳到頁面內容' in JS, 'data-skip>跳到頁面內容')
        self.assertTrue('restoreControlFocus(controlFocus)' in JS, 'restoreControlFocus(controlFocus)')


class Words(unittest.TestCase):
    def test_no_leftover_jargon(self):
        for word in ("'多代理協作'", "'依驗收紀錄派工'", "'保持 CLI 開啟'", '自訂模型…', "'（快取）'", "'開發版本'", '已更新 Bot 預設', "'選項按鈕'",
                     "'排程與觸發可用內建瀏覽器'", "'預設提供者'", "'備用模型 ' + (i + 1)", '這個 CLI 同時最多幾項', '跳到「備份與還原」'):
            self.assertFalse(word in JS, word)

    def test_new_words_are_there(self):
        for word in ('預設用哪家 AI', '備用 AI ', '分工給小幫手', '照過去表現派工', 'Bot 提問時顯示按鈕', '接著問時回得更快', '自己輸入型號…', '群組自動分工（任務引擎）'):
            self.assertTrue(word in JS, word)

    def test_a_cli_that_cannot_take_tasks_is_explained(self):
        self.assertTrue("filter(p => p.installed && !p.tools && p.id !== 'auto')" in JS, "filter(p => p.installed && !p.tools && p.id !== 'auto')")  # Gemini: said, not silently left out (#75③)


class Saving(unittest.TestCase):
    def test_saved_and_unsaved_are_shown(self):
        self.assertTrue('✓ 已儲存' in JS, '✓ 已儲存')
        self.assertEqual(JS.count('data-unsaved hidden>尚未儲存'), 2)  # 固定規則 and 模型, the two parts that wait for their button
        self.assertTrue("if (row?.closest('#settings-form')) return;" in JS, 'rows waiting for 儲存 are never marked saved on their own')
        self.assertTrue("settingFailed(); throw e;" in JS, 'a failed save marks nothing')
        self.assertTrue("if (path === 'settings' && method === 'PATCH') settingSaved();" in JS, "if (path === 'settings' && method === 'PATCH') settingSaved();")

    def test_the_page_has_its_own_address(self):
        self.assertTrue("PAGE_HASHES = ['settings'," in JS, 'settings is one of the pages with an address')  # #168③: every page now
        self.assertTrue("history.replaceState(null, '', want)" in JS, "history.replaceState(null, '', want)")

    def test_settings_menus_are_drawn_alike_and_have_a_table_of_contents(self):
        self.assertTrue('function mirrorSelects(form)' in JS, 'function mirrorSelects(form)')
        self.assertTrue('content = settingsNav() + lookSection()' in JS, 'content = settingsNav() + lookSection()')


if __name__ == '__main__': unittest.main()
