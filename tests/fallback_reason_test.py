# -*- coding: utf-8 -*-
"""「這次改用…」 says why the first model did not answer, not only 「無法回覆」."""
import importlib.util, sys, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_fallback_reason', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)


class FallbackReason(unittest.TestCase):
    def test_known_kinds_and_plain_words(self):
        self.assertEqual(m.fallback_why('這個帳號的額度已用完。'), '額度已用完')
        self.assertEqual(m.fallback_why('', 'busy'), '服務太忙')
        self.assertEqual(m.fallback_why('Antigravity 這次沒有回覆內容（結束碼 3）。\n其他'), '無法回覆：Antigravity 這次沒有回覆內容（結束碼 3）。')
        self.assertEqual(m.fallback_why('x' * 80)[-1], '…')
        self.assertEqual(m.fallback_why('', None), '無法回覆')


if __name__ == '__main__': unittest.main()
