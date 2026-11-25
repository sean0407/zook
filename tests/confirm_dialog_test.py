# -*- coding: utf-8 -*-
"""#175 (with #163, #192): every yes/no question is asked on the page, never with the browser's confirm(), which does not show in
the built-in browser and some embedded views (pressing 刪除 did nothing there). Each says what goes, whether it comes back and what
else changes; Esc, a click outside and 取消 mean no; the work runs with the button showing 處理中… so it is not sent twice."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'


def source(name): return (JS / name).read_text(encoding='utf-8')


def case(text, action):
    """The body of one `case 'x':` in 40-actions.js, up to the next case."""
    start = text.index("case '%s':" % action)
    nxt = text.find('\n        case ', start + 1)
    return text[start:nxt if nxt > 0 else None]


class ConfirmDialog(unittest.TestCase):
    def test_no_browser_confirm_left(self):
        for f in sorted(JS.glob('*.js')):
            hits = [n + 1 for n, line in enumerate(f.read_text(encoding='utf-8').splitlines()) if re.search(r'(?<![\w$.])confirm\s*\(|window\.confirm|\balert\s*\(|\bprompt\s*\(', line)]
            self.assertEqual(hits, [], '%s still uses a browser dialog on lines %s' % (f.name, hits))

    def test_the_question_itself(self):
        ask = source('21-ask.js')
        self.assertIn('function ask(', ask); self.assertIn('new Promise', ask)
        self.assertIn("e.key === 'Escape'", ask); self.assertIn('ask-overlay', ask)  # Esc and the backdrop are 取消
        self.assertIn('>取消<', ask); self.assertIn('danger-btn', ask)
        self.assertIn("working = ok + '中…'", ask); self.assertIn('yes.disabled = no.disabled = true', ask)
        self.assertIn('stopImmediatePropagation', ask)  # Esc closes only the question, not the window under it
        css = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
        self.assertIn('.danger-btn', css); self.assertIn('.ask-overlay { z-index: 105; }', css)

    def test_deleting_a_bot_says_what_happens(self):
        bot = case(source('40-actions.js'), 'delete-bot')
        self.assertIn('ask(', bot)
        self.assertIn('它在這些群組裡', bot); self.assertIn('會只剩 1 位', bot)  # kept from #217
        self.assertIn('喚回', bot); self.assertIn('各模型使用量', bot)  # can be brought back, and where
        self.assertIn('排程', bot)  # its schedules go with it

    def test_other_deletes_say_what_happens(self):
        actions = source('40-actions.js')
        group = case(actions, 'delete-group')
        self.assertIn('無法復原', group); self.assertIn('成員 Bot 不會被刪除', group); self.assertIn('群組檔案', group); self.assertIn('排程', group)
        for action in ('delete-memory', 'delete-note', 'delete-schedule', 'delete-chat'):
            body = case(actions, action)
            self.assertIn('ask(', body, action); self.assertIn('無法復原', body, action); self.assertIn('run:', body, action)

    def test_redo_asks_on_the_page(self):
        pages = source('30-pages.js'); forms = source('50-forms.js'); actions = source('40-actions.js')
        self.assertIn('async function redoAllowed', pages); self.assertIn("ok: '重新回答'", pages)
        self.assertEqual(forms.count('!(await redoAllowed(b))'), 2)
        self.assertIn('await redoAllowed(b)', case(actions, 'redo-again'))


if __name__ == '__main__': unittest.main()
