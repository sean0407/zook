# -*- coding: utf-8 -*-
"""#347 #211 #101①④⑧ #278 #215①: files that look done but are not.
- An Excel total over another sheet's column that stops before the last rows (原始明細!$G$2:$G$55 with data down to row 57).
- A PDF looked at as pictures: pagepics says which pages are mostly blank (a cover or page 2 left half empty), and the PDF check
  says when text is drawn too small to read (chart labels).
- Pictures for a platform come out at its size (IG 方形 1080×1080) and the size is checked after saving."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xlsxcheck_test import load, cell, write_xlsx  # noqa: E402
from pdfcheck_test import pdf, CATALOG, INFO  # noqa: E402

PAGEPICS = Path(__file__).resolve().parents[1] / 'backend/pagepics.py'


def detail(first=4, last=57):
    """原始明細: a header in row 3, then one sale per row: region in B, amount in G."""
    cells = [cell('B3', 0, kind='s'), cell('G3', 1, kind='s')]
    for r in range(first, last + 1): cells += [cell('B%d' % r, r % 3, kind='s'), cell('G%d' % r, 40000 + r)]
    return cells


class ShortRanges(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self): self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))

    def tearDown(self): self.temp.cleanup()

    def scan(self, sheets):
        path = self.root / '報表.xlsx'; write_xlsx(path, sheets)
        return self.m.xlsx_scan(str(path))

    def test_a_cross_sheet_range_that_stops_before_the_last_rows_is_said(self):
        f = 'SUMIFS(原始明細!$G$2:$G$55,原始明細!$B$2:$B$55,A2)'
        found = self.scan([('彙總', [cell('A2', 0, kind='s'), cell('B2', 2404800, f)]), ('原始明細', detail())])
        short = [x for x in found if x[0] == 'short']
        self.assertEqual(len(short), 1, found)
        self.assertEqual(short[0][2][0][:3], (1, '彙總', 'B2')); self.assertEqual(short[0][2][0][3:], (55, 57))
        said = self.m.xlsx_render(found); self.assertTrue(any('第 55 列' in x and '第 57 列' in x for x in said), said)
        for_bot = self.m.xlsx_render([list(x) for x in found], for_bot=True)
        self.assertTrue(any('第 1 張工作表!B2' in x and '涵蓋' in x for x in for_bot), for_bot); self.assertFalse(any('彙總' in x for x in for_bot))

    def test_quoted_sheet_names_and_the_same_sheet(self):
        f = "COUNTIFS('原始 明細'!B2:B30,\"北區\")"
        self.assertEqual([x[0] for x in self.scan([('彙總', [cell('B2', 9, f)]), ('原始 明細', detail(2, 40))])], ['short'])
        same = detail() + [cell('K2', 7, 'SUMIF(B4:B50,1,G4:G50)')]
        self.assertEqual([x[0] for x in self.scan([('明細', same)])], ['short'])
        computed = detail(4, 20) + [cell('H%d' % r, 2 * r, 'G%d*2' % r) for r in range(4, 21)] + [cell('K2', 1, 'SUMIF(B4:B18,1,H4:H18)')]  # a column worked out by formulas
        self.assertEqual([x[0] for x in self.scan([('明細', computed)])], ['short'])
        gap = detail(4, 20) + [cell('K2', 1, 'SUMIF(B4:B18,1,G4:G18)')]  # a blank region in row 19: the amounts still run on
        gap = [c for c in gap if 'r="B19"' not in c]
        self.assertEqual([x[0] for x in self.scan([('明細', gap)])], ['short'])

    def test_ranges_that_reach_the_end_or_stop_at_a_total_row_are_fine(self):
        full = 'SUMIFS(原始明細!$G$2:$G$57,原始明細!$B$2:$B$57,A2)'
        self.assertEqual(self.scan([('彙總', [cell('B2', 1, full)]), ('原始明細', detail())]), [])
        roomy = 'SUMIFS(原始明細!$G:$G,原始明細!$B:$B,A2)'  # whole columns: nothing to miss
        self.assertEqual(self.scan([('彙總', [cell('B2', 1, roomy)]), ('原始明細', detail())]), [])
        totals = detail(4, 20) + [cell('B21', 2, kind='s'), cell('G21', 5, 'SUM(G4:G20)'), cell('K2', 1, 'SUMIF(B4:B20,1,G4:G20)')]  # row 21 is the total row
        self.assertEqual([x for x in self.scan([('明細', totals)]) if x[0] == 'short'], [])
        sections = detail(4, 20) + [cell('B21', 2, kind='s'), cell('G21', 5, 'SUM(G4:G20)')] + detail(22, 30)[2:] + [cell('K2', 1, 'SUMIF(B4:B20,1,G4:G20)')]
        self.assertEqual([x for x in self.scan([('明細', sections)]) if x[0] == 'short'], [])  # the total sits in the sum column only: the condition column stops there too
        a_quarter = detail(4, 20) + [cell('K2', 1, 'SUM(G4:G6)')]  # a plain SUM of the first rows is a choice (Q1), not a slip
        self.assertEqual([x for x in self.scan([('明細', a_quarter)]) if x[0] == 'short'], [])
        unknown = 'SUMIFS(不在!$G$2:$G$5,不在!$B$2:$B$5,A2)'
        self.assertEqual(self.scan([('彙總', [cell('B2', 1, unknown)]), ('原始明細', detail())]), [])

    def test_the_rule_still_asks_for_ranges_to_the_last_row(self):
        self.assertIn('涵蓋到最後一筆資料', self.m.FILE_DELIVERY_NOTE)


def page_pdf(path, pages):
    """pages: [(height of the black band from the top, as a share of the page)]; 0 is an empty page."""
    objs = ['<</Type/Catalog/Pages 2 0 R>>', '<</Type/Pages/Kids[%s]/Count %d>>' % (' '.join('%d 0 R' % (3 + 2 * i) for i in range(len(pages))), len(pages))]
    for i, share in enumerate(pages):
        objs.append('<</Type/Page/Parent 2 0 R/MediaBox[0 0 600 800]/Contents %d 0 R>>' % (4 + 2 * i))
        draw = '0 0 0 rg 50 %d 500 %d re f' % (800 - int(800 * share), int(800 * share)) if share else ''
        objs.append('<</Length %d>>\nstream\n%s\nendstream' % (len(draw), draw))
    body, offsets = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1): offsets.append(len(body)); body += ('%d 0 obj\n%s\nendobj\n' % (i, o)).encode()
    xref = len(body); body += ('xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)).encode() + b''.join(b'%010d 00000 n \n' % x for x in offsets)
    path.write_bytes(body + ('trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)).encode())


class BlankPages(unittest.TestCase):
    def test_pagepics_names_the_pages_that_are_mostly_blank(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / '週報.pdf'; page_pdf(path, [0.2, 0.9, 0.5, 0.1])  # a cover with a fifth used; the last page may end early
            result = subprocess.run(['/usr/bin/python3', str(PAGEPICS), str(path), str(Path(root) / 'pics')], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            line = next((x for x in result.stdout.splitlines() if '空白' in x), '')
            self.assertIn('第 1 頁', line); self.assertNotIn('第 2 頁', line); self.assertNotIn('第 3 頁', line); self.assertNotIn('第 4 頁', line)
            self.assertIn('約 80%', line)

    def test_a_full_document_says_nothing_of_blanks(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'r.pdf'; page_pdf(path, [0.9, 0.9, 0.3])
            result = subprocess.run(['/usr/bin/python3', str(PAGEPICS), str(path), str(Path(root) / 'pics')], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr); self.assertNotIn('空白', result.stdout)


class TinyText(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def scan(self, stream):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'r.pdf'
            path.write_bytes(pdf({1: CATALOG, 9: INFO, 3: b'<< /BaseFont /Helvetica /Name /F1 /Subtype /Type1 /Type /Font >>', 5: (b'<< >>', stream)}, deflate=(5,)))
            return self.m.pdf_scan(str(path))

    def test_labels_drawn_too_small_are_said(self):
        labels = b' '.join(b'BT 1 0 0 1 %d 100 Tm /F1 4.5 Tf (Q%d) Tj ET' % (50 + 40 * i, i) for i in range(4))
        found = self.scan(b'BT 1 0 0 1 50 700 Tm /F1 12 Tf (Sales) Tj ET ' + labels)
        self.assertEqual(found, [['tiny', 4]])
        said = self.m.pdf_render(found, for_bot=True); self.assertTrue(any('6 pt' in x or '太小' in x for x in said), said)
        self.assertTrue(self.m.pdf_render(found))

    def test_scaled_text_and_a_footnote_are_fine(self):
        self.assertEqual(self.scan(b'BT 12 0 0 12 50 700 Tm /F1 1 Tf (Sales) Tj (More) Tj ET BT /F1 5 Tf (p.1) Tj ET'), [])  # Chrome writes 1 Tf with a scaled Tm
        narrow = b' '.join(b'BT 0.4 0 0 1 %d 100 Tm /F1 10 Tf (Q%d) Tj ET' % (50 + 40 * i, i) for i in range(4))  # narrowed sideways, still 10 pt tall
        self.assertEqual(self.scan(narrow), [])


class Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def test_pictures_follow_the_platform_and_are_measured(self):
        note = self.m.FILE_DELIVERY_NOTE
        for x in ('1080×1080', '1080×1350', '1080×1920', 'sips -g pixelWidth'): self.assertIn(x, note)

    def test_pdf_self_check_asks_for_blank_pages_small_labels_and_headers(self):
        note = self.m.FILE_DELIVERY_NOTE
        for x in ('大片空白', '圖表', '字級', '表頭'): self.assertIn(x, note)


if __name__ == '__main__': unittest.main()
