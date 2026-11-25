# -*- coding: utf-8 -*-
"""#43 #44 #115 #120 #156 #157 #205 #209 #224: the Bot form and the other windows say what is missing beside the button, refuse in
plain words with the limit, count long texts, point out a name another Bot has, and say what 帳號 and 備用模型 do; a long name in
the title bar ends in … instead of running under the buttons."""
import importlib.util, re, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_bot_forms', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def js(): return ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


def css(): return (ROOT / 'frontend/style.css').read_text(encoding='utf-8')


class PlainRefusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def refused(self, body):
        with self.assertRaises(ValueError) as caught: self.m.update({}, body, 'bot')
        return str(caught.exception)

    def test_bot_fields_say_what_and_how_much(self):
        self.assertEqual(self.refused({'name': '   '}), '名稱不能是空白。')
        self.assertEqual(self.refused({'instructions': '字' * 20000}), '工作指示最多 10,000 字，目前是 20,000 字。')
        self.assertEqual(self.refused({'persona': 'a' * 20001}), '人格檔案最多 20,000 字，目前是 20,001 字。')
        self.assertEqual(self.refused({'name': 'n' * 101}), '名稱最多 100 字，目前是 101 字。')
        self.assertEqual(self.refused({'jobTitle': 5}), '職稱的內容不對，請重新填寫。')
        for body in ({'name': '   '}, {'instructions': 'x' * 10001}):
            self.assertNotIn('欄位', self.refused(body)); self.assertNotRegex(self.refused(body), '[a-z]{4}')  # no field keys

    def test_within_the_limits_is_kept(self):
        bot = {}; self.m.update(bot, {'name': '小幫手', 'instructions': 'x' * 10000, 'persona': 'p' * 20000}, 'bot')
        self.assertEqual(len(bot['instructions']), 10000)


class FormWords(unittest.TestCase):
    def test_missing_is_said_beside_the_button(self):
        code = js()
        self.assertIn("fieldError(empty); sayMissing(form);", code)  # under the field (#63) and beside the button (#224)
        self.assertIn("'還沒填：' + names.join('、')", code)
        self.assertIn("f.noValidate = true", code)  # 「＋ 帳號」 with no name said something too (#209): every window, not only the Bot form
        self.assertIn('.form-need', css())

    def test_folder_not_picked_points_at_the_row(self):
        code = js()
        self.assertIn('needFolder(form)', code); self.assertNotIn("&& !data.accessFolder) { toast('請先選擇資料夾'); return; }", code)
        self.assertIn('存取範圍選了「指定資料夾」', code)
        self.assertIn('recheckForm(form); }', code)  # picking the folder takes the line away

    def test_limits_and_counts(self):
        code = js()
        self.assertIn('instructions: 10000', code); self.assertIn('instructions.maxLength = TEXT_LIMITS.instructions', code)
        self.assertIn("'：已到上限，多的字沒有放進來'", code)
        self.assertIn('名稱最多 ${limit} 字', code)

    def test_name_in_use_and_required_marks(self):
        code = js()
        self.assertIn('已經有一個叫「${name}」的 Bot', code)
        self.assertIn("persona.required = true", code)  # editing asks for it as making one does (#156)
        self.assertIn("'為 Bot 命名（必填）'", code); self.assertIn('need-mark', code)

    def test_account_and_fallback_say_what_they_do(self):
        code = js()
        self.assertIn('同一家的其他帳號要先到「各模型使用量」按「＋ 帳號」加入', code)
        self.assertIn('不會換成同一家', code)
        self.assertIn('同一家的 ${providerShort(id)} 不會切換', code)  # the 預設 line leaves the Bot's own CLI out (#43②)
        self.assertIn("base + levelMark(accountLevel(value, ''))", code)  # 已用完 beside a fallback, as beside an account (#43③)
        self.assertIn("[data-auto-reason]')?.toggleAttribute('hidden'", code)  # 自動配好… goes once another model is picked (#205③)
        self.assertIn('正在讀取這一家的模型…', code)  # the last CLI's model is not shown while the new list loads (#43⑥)
        self.assertIn("replace(/^換了一家[^。]*。/, '')", code)  # a model picked by hand ends that line (#43⑤)

    def test_quota_line_names_the_kind_of_model(self):
        code = js()
        self.assertIn('function groupsOf(wins, group)', code)  # Antigravity: 「Claude 與 GPT 模型」 vs 「Gemini 模型」 (#43④)
        self.assertIn("const which = l.group ? `的「${l.group}」` : ''", code)
        self.assertIn("g + '還剩 '", code)

    def test_detail_shows_thinking_level(self):
        self.assertIn("'思考強度：' + (EFFORTS.find(x => x.id === (b.effort || state.data.settings.effort))?.name || '標準')", js())

    def test_long_name_in_title_bar(self):
        style = css()
        self.assertRegex(style, r'\.main-header \.bot-pill[^{]*\{[^}]*overflow: hidden')
        self.assertRegex(style, r'grid-template-columns: minmax\(0, 1fr\) minmax\(0, max-content\) minmax\(max-content, 1fr\)')
        self.assertRegex(style, r'\.main-header \.header-actions \{ grid-column: 3;[^}]*position: static')
        self.assertNotIn('.main-header .header-actions { margin-left: 8px; }', style)  # narrow windows keep the buttons at the right edge


if __name__ == '__main__':
    unittest.main()
