# -*- coding: utf-8 -*-
"""Phone width (#98, #131): the page fits a 375-wide screen, so the main buttons stay on screen."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'frontend' / 'style.css').read_text(encoding='utf-8')


def blocks(css):
    """Top-level rules as (selector or @media head, body), with nested media blocks kept whole."""
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


def media_max(head):
    m = re.match(r'@media\s*\(\s*max-width\s*:\s*(\d+)px\s*\)$', head)
    return int(m.group(1)) if m else None


class Narrow(unittest.TestCase):
    def test_phone_media_query_lifts_the_minimum_width(self):
        phone = [(media_max(h), b) for h, b in blocks(CSS) if media_max(h) and media_max(h) >= 375]
        lifted = [(w, b) for w, b in phone if re.search(r'\.layout\s*\{[^}]*min-width:\s*0', b)]
        self.assertTrue(lifted, 'a max-width media query at or above 375 sets .layout min-width to 0')
        width, body = lifted[0]
        # Covers every width below the desktop minimum, so 641–699 does not scroll sideways either.
        desktop_min = int(re.search(r'^\.layout\s*\{[^}]*min-width:\s*(\d+)px', CSS, re.M).group(1))
        self.assertEqual(width + 1, desktop_min, 'exactly the widths below the desktop minimum; 700 and up keep the desktop layout')
        self.assertRegex(body, r'\.layout\s*\{[^}]*flex-direction:\s*column')
        self.assertRegex(body, r'\.sidebar\s*\{[^}]*width:\s*auto')
        # The menu opens downwards and scrolls; long names cannot push dropdowns or header buttons off screen.
        self.assertRegex(body, r'\.popup\s*\{[^}]*top:[^}]*overflow-y:\s*auto')
        self.assertRegex(body, r'\.dd-btn\s*\{[^}]*max-width:\s*100%')
        self.assertRegex(body, r'\.header-actions\s*\{[^}]*min-width:\s*0')
        # No later rule outside a media query puts a wide minimum back on the layout.
        all_blocks = blocks(CSS)
        idx = next(i for i, (h, b) in enumerate(all_blocks) if media_max(h) == width)
        for head, rule in all_blocks[idx + 1:]:
            if not head.startswith('@') and '.layout' in [s.strip() for s in head.split(',')]:
                self.assertNotRegex(rule, r'min-width:\s*[1-9]')

    def test_main_containers_have_no_fixed_width_wider_than_a_phone_outside_desktop_rules(self):
        # Outside media queries only .layout may carry a wide minimum (lifted above); modals and pages must not.
        for head, body in blocks(CSS):
            if head.startswith('@'):
                continue
            for sel in ('.main', '.page', '.modal', '.modal-overlay', '.sidebar', '.page-top', '.modal-foot'):
                if sel in [s.strip() for s in head.split(',')]:
                    for m in re.finditer(r'(?<![-\w])min-width:\s*(\d+)px', body):
                        self.assertLessEqual(int(m.group(1)), 375, f'{head} min-width {m.group(1)}px')
                    for m in re.finditer(r'(?<![-\w])width:\s*(\d+)px', body):
                        if sel != '.sidebar':  # the sidebar's fixed width is replaced at phone width
                            self.assertLessEqual(int(m.group(1)), 375, f'{head} width {m.group(1)}px')

    def test_modal_fits_the_screen(self):
        self.assertRegex(CSS, r'\.modal\s*\{[^}]*width:\s*min\(440px,\s*100%\)')

    def test_empty_required_field_is_marked(self):
        self.assertRegex(CSS, r'\.modal (input|textarea|select):user-invalid')


if __name__ == '__main__': unittest.main()
