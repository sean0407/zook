# -*- coding: utf-8 -*-
"""#108: attaching says which files a Bot can read, warns about program files, says when the same file is attached twice
and when a group upload was saved under another name; a shared file opens a preview, with 下載 beside it, and has an icon for its kind."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend' / 'js').glob('*.js')))


class AttachHints(unittest.TestCase):
    def test_the_hint_names_what_a_bot_can_read(self):
        self.assertIn('ATTACH_HINT', JS)
        hint = re.search(r"const ATTACH_HINT = '([^']+)'", JS).group(1)
        for word in ('PDF', 'Word', 'Excel', '圖片', '.exe'): self.assertIn(word, hint)
        self.assertGreaterEqual(JS.count('${ATTACH_HINT}') + JS.count('+ ATTACH_HINT'), 2)  # the more-options window and the group's files

    def test_program_files_are_flagged(self):
        m = re.search(r'const UNREADABLE = /([^/]+)/i', JS); self.assertTrue(m)
        pattern = re.compile(m.group(1), re.I)
        for name in ('setup.exe', 'Tool.DMG', 'a.pkg', 'x.msi', 'lib.dll'): self.assertTrue(pattern.search(name), name)
        for name in ('報價.xlsx', '說明.pdf', 'exe.txt', '報告.docx', 'a.png'): self.assertFalse(pattern.search(name), name)
        self.assertIn('Bot 讀不懂內容', JS)

    def test_the_same_file_twice_is_said(self):
        self.assertIn('已經附上同一個檔案', JS)
        self.assertIn('存成「', JS)  # a group upload renamed because the name was taken

    def test_shared_files_preview_and_icons(self):
        row = re.search(r'files\.map\(f => `<div class="group-file">(.+?)`\)\.join', JS, re.S).group(1)
        self.assertIn('data-group-file=', row); self.assertIn('>下載</a>', row); self.assertIn('fileIcon(', row)
        self.assertIn('function fileIcon', JS)
        self.assertNotIn('<span class="file-icon">📄</span>', JS)  # the waiting file shows its kind too


if __name__ == '__main__':
    unittest.main()
