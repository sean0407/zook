# -*- coding: utf-8 -*-
"""Source files stay small enough to work with."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Layout(unittest.TestCase):
    def test_no_source_file_over_a_thousand_lines(self):
        for file in [*ROOT.glob('backend/*.py'), *ROOT.glob('backend/zook/*.py'), *ROOT.glob('frontend/js/*.js')]:
            self.assertLessEqual(len(file.read_text(encoding='utf-8').splitlines()), 1000, file.name)


if __name__ == '__main__': unittest.main()
