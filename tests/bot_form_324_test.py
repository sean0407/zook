# -*- coding: utf-8 -*-
"""G49–G53 (#324 #332②③ #309①⑤ #196 #333②–⑦ #281③): 備用模型 said after making a Bot and while 自動配 hides it, one way to
the default order from the Bot form and the usage page, a second press before making a Bot whose name is taken, what is still
needed shown before 建立 is pressed, 長任務／先規劃 as switches, the main account's name in the menus, 主持人分工 without a host,
and a group of one member says so instead of 預計 1 次回覆."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def js(): return ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


class Fallback(unittest.TestCase):
    def test_after_making_a_bot_the_toast_says_what_backup_does(self):
        code = js()
        self.assertIn('createdWords(', code)
        self.assertIn('額度用完時會換備用模型', code)
        self.assertIn('額度用完時不會換別家', code)
        self.assertIn('Array.isArray(own) ? own : state.data.settings.fallbacks', code)  # 預設 with an empty order in 設定 is 不換別家 too
        self.assertIn('troubleText(t, botProvider(nb), nb.fallbacks, nb.nextBackup', code)  # a Bot made on a used-up account

    def test_auto_says_why_the_backup_row_is_hidden(self):
        code = js()
        self.assertIn('data-auto-fallback', code)
        self.assertIn("form.querySelector('[data-auto-fallback]')?.toggleAttribute('hidden', !auto)", code)
        self.assertIn('建立後才知道用哪一家', code)

    def test_one_way_to_the_default_order(self):
        code = js()
        self.assertIn('data-action="fallback-settings"', code)
        self.assertIn('[data-fallback-slot]', code)
        self.assertIn('預設順序在「設定 → 模型」', code)  # the Bot form and the budget on the usage page say the same place


class NameAndPersona(unittest.TestCase):
    def test_same_name_needs_a_second_press(self):
        code = js()
        self.assertIn('sameNameAgain(form, data.name)', code)
        self.assertIn('再按一次「建立 Bot」', code)

    def test_what_is_needed_shows_before_pressing(self):
        code = js()
        self.assertIn('data-form-todo', code)
        self.assertIn('建立前要填：', code)
        self.assertIn('data-action="persona-sample"', code)


class Switches(unittest.TestCase):
    def test_long_and_plan_are_switches(self):
        code = js()
        self.assertIn('longPlanRows()', code)
        self.assertIn("toggle('data-long'", code)
        self.assertIn("toggle('data-plan", code)
        self.assertNotIn('<b>/goal</b> 開啟長任務', code)


class Accounts(unittest.TestCase):
    def test_main_account_is_named(self):
        code = js()
        self.assertIn('mainAccountName(', code)
        self.assertIn("'預設帳號' + (main ? '・' + main : '')", code)
        self.assertIn("state.accounts = a", code)  # read when the Bot form opens


class Groups(unittest.TestCase):
    def test_split_without_host_is_said(self):
        code = js()
        self.assertIn("mode === 'split' && !host", code)
        self.assertIn('「主持人分工」沒有設主持人', code)
        self.assertIn("autoChecker(ids, '', cm === 'same')", code)  # the 查核員 picked by 自動／同家複查 does not lead the work

    def test_one_member_group_estimate(self):
        self.assertIn("groupMembers(g).length < 2 ? '' : e.text || fallback", js())


if __name__ == '__main__':
    unittest.main()
