# -*- coding: utf-8 -*-
"""「這次改用…」 says why the first model did not answer, not only 「無法回覆」."""
import importlib.util, sys, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_fallback_reason', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)


class FallbackReason(unittest.TestCase):
    def test_only_fixed_reasons(self):
        self.assertEqual(m.fallback_why('這個帳號的額度已用完。'), '額度已用完')
        self.assertEqual(m.fallback_why('', 'busy'), '服務太忙')
        self.assertEqual(m.fallback_why('請重新登入', 'denied'), '登入被拒絕')  # this try's own kind comes first
        self.assertEqual(m.fallback_why('回覆超過時間上限'), '回應逾時')
        self.assertEqual(m.fallback_why('找不到帳號「me@example.com」的 API 金鑰'), '找不到 API 金鑰')
        said = m.fallback_why('帳號 me@example.com 出了奇怪的錯')
        self.assertNotIn('example.com', said); self.assertEqual(said, '無法回覆（CLI 回報錯誤）')
        self.assertEqual(m.fallback_why('', None), '無法回覆（沒有說明原因）')

if __name__ == '__main__': unittest.main()
