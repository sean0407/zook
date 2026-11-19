# -*- coding: utf-8 -*-
"""How the window looks is a setting: light or dark, and the size of the text."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import origin_test

ROOT = Path(__file__).resolve().parents[1]


class LookTest(origin_test.OriginTest):
    for _name in [n for n in dir(origin_test.OriginTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_only_the_listed_choices_are_kept(self):
        for key, good, bad in (('appearance', ('system', 'light', 'dark'), 'pink'), ('textSize', ('small', 'normal', 'large', 'xlarge'), 'huge')):
            for value in good:
                status, settings = self.req('PATCH', '/api/settings', {key: value})
                self.assertEqual((status, settings[key]), (200, value))
            self.assertEqual(self.req('PATCH', '/api/settings', {key: bad})[0], 400); self.assertEqual(self.req('PATCH', '/api/settings', {key: 3})[0], 400)
        self.assertEqual(self.req('GET', '/api/state')[1]['settings']['textSize'], 'xlarge')

    def test_the_message_box_offers_the_two_commands(self):
        page = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))
        for part in ("cmd: '/goal', key: 'long'", "cmd: '/plan', key: 'plan'", 'id="slash-menu"', "data-look=\"appearance\"", "data-look=\"textSize\""): self.assertIn(part, page)
        self.assertNotIn('longControl(', page); self.assertNotIn('planControl(', page)  # the two switches are gone from the box


if __name__ == '__main__': unittest.main()
