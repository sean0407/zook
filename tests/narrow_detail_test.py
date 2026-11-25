# -*- coding: utf-8 -*-
"""Narrow window detail panel (#118, #60, #152): below the wide layout the side panel covers the page
instead of squeezing the conversation, has a close button and a backdrop, and Escape closes it."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'frontend' / 'style.css').read_text(encoding='utf-8')
JS = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend' / 'js').glob('*.js')))


def blocks(css):
    out, i = [], 0
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    while True:
        start = css.find('{', i)
        if start < 0:
            return out
        depth, j = 1, start + 1
        while depth:
            depth += {'{': 1, '}': -1}.get(css[j], 0)
            j += 1
        out.append((css[i:start].strip(), css[start + 1:j - 1]))
        i = j


def wide_at():
    """The window width above which the panel sits beside the conversation (the JS decides it too)."""
    return int(re.search(r'const DETAIL_WIDE = (\d+);', JS).group(1))


class NarrowDetail(unittest.TestCase):
    def test_js_and_css_use_the_same_width(self):
        w = wide_at()
        self.assertIn(f'@media (max-width: {w}px)', CSS)
        self.assertNotIn('innerWidth > 1100', JS, 'the width lives in one constant')

    def test_narrow_panel_covers_the_page(self):
        w = wide_at()
        overlay = [b for h, b in blocks(CSS) if h == f'@media (max-width: {w}px)' and re.search(r'\.detail\s*\{[^}]*position:\s*fixed', b)]
        self.assertTrue(overlay, 'a narrow media query makes .detail a fixed panel over the page')
        body = overlay[-1]
        self.assertRegex(body, r'\.detail\s*\{[^}]*z-index:\s*\d+')
        self.assertRegex(body, r'\.detail-backdrop\s*\{[^}]*display:\s*block')
        # Nothing hides the panel at a narrow width any more (the button must do something).
        for head, rule in blocks(CSS):
            if head.startswith('@media'):
                self.assertNotRegex(rule, r'(^|\})\s*\.detail\s*\{\s*display:\s*none')
        # The backdrop is hidden when the panel sits beside the conversation.
        self.assertRegex(CSS, r'(^|\n)\.detail-backdrop\s*\{[^}]*display:\s*none')

    def test_panel_stays_below_windows_and_messages(self):
        w = wide_at()
        body = next(b for h, b in blocks(CSS) if h == f'@media (max-width: {w}px)' and '.detail-backdrop' in b)
        z = int(re.search(r'\.detail\s*\{[^}]*z-index:\s*(\d+)', body).group(1))
        modal_z = int(re.search(r'#modal-root\s*\{[^}]*z-index:\s*(\d+)', CSS).group(1))
        self.assertLess(z, modal_z)

    def test_backdrop_and_escape_close_the_panel(self):
        self.assertRegex(JS, r'class="detail-backdrop" data-action="toggle-detail"')
        for fn in ('function detail(b)', 'function groupDetail(g)'):
            body = JS[JS.index(fn):JS.index('<aside class="detail"', JS.index(fn))]
            self.assertIn('detailBackdrop()', body, fn)
        self.assertRegex(JS, r"e\.key === 'Escape' && state\.detailOpen && !state\.modal && narrowDetail\(\)")

    def test_attachment_cards_stay_inside_the_message_box(self):
        self.assertRegex(CSS, r'\.pending-file\s*\{[^}]*max-width:\s*min\(260px,\s*100%\)')


if __name__ == '__main__': unittest.main()
