# -*- coding: utf-8 -*-
"""#235: an approval card the CLI no longer waits for stays in sight, greyed, saying so (知道了 closes it); pressing a button on one
says it no longer counts; after 允許這次 the wait is shown with how long it has been, and after a few minutes how to get unstuck."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ApprovalAfter(unittest.TestCase):
    def setUp(self):
        self.chat = (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8')
        self.actions = (ROOT / 'frontend/js/40-actions.js').read_text(encoding='utf-8')

    def test_cards_show_what_happened_after(self):
        fn = re.search(r'function approvalAfter\(jobs\) \{(.*?)\n  \}', self.chat, re.S).group(1)
        self.assertIn("a.status === 'expired' && a.withdrawn", fn); self.assertIn('已不再等這個核准', fn); self.assertIn('dismiss-approval', fn)
        self.assertIn("j.status === 'running'", fn)  # only while that reply runs
        self.assertIn('decidedAt', fn); self.assertIn('callsAt', fn); self.assertIn("a.status === 'pending'", fn); self.assertIn('已過', fn); self.assertIn('停止後再試', fn)
        self.assertIn('approvalAfter(jobs || jobsForBot(botId))', self.chat)

    def test_a_button_on_a_card_that_ended_says_so(self):
        self.assertIn("case 'dismiss-approval'", self.actions)
        self.assertIn('這張核准卡已經結束', self.actions)
        self.assertIn('/已結束/', self.actions)  # the server's 409 「此審批已結束。」


if __name__ == '__main__': unittest.main()
