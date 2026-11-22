# -*- coding: utf-8 -*-
"""Every Bot is told how to hand over files a person can open as they are (Excel showing its numbers in previews too)."""
import importlib.util, sys, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_file_delivery', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)


class FileDelivery(unittest.TestCase):
    def test_every_bot_hears_it(self):
        m._active['data'] = {'settings': {}, 'rules': []}
        text = m.identity_block(dict(name='業務小幫'))
        self.assertIn('完整路徑', text); self.assertIn('xlsxwriter', text); self.assertIn('轉成圖片', text); self.assertIn('qlmanage', text); self.assertIn('暫存程式', text); self.assertIn('【待確認', text)


if __name__ == '__main__': unittest.main()
