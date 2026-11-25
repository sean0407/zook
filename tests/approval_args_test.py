# -*- coding: utf-8 -*-
"""An approval card's details read as words: a list of choices or nested details never shows as [object Object] (#54)."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ApprovalArgs(unittest.TestCase):
    def setUp(self): self.page = (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8')

    def test_details_go_through_the_word_formatter(self):
        args = re.search(r'function argsList\(args\) \{(.*?)\n  \}', self.page, re.S).group(1)
        self.assertIn('plainValue(v)', args)
        self.assertNotIn("v.join('、')", args)  # joining a list of objects printed [object Object]

    def test_formatter_handles_lists_of_objects_and_depth(self):
        fn = re.search(r'function plainValue\(v, depth = 0\) \{(.*?)\n  \}', self.page, re.S).group(1)
        self.assertIn('Array.isArray(v)', fn)
        self.assertIn('plainValue(x, depth + 1)', fn)   # each item of a list is turned into words too
        self.assertIn('plainValue(y, depth + 1)', fn)   # and each nested value
        self.assertIn('depth > 3', fn)                  # deep nesting stops instead of running on


if __name__ == '__main__': unittest.main()
