# -*- coding: utf-8 -*-
"""#354 (review of PR #127, what was left): the PDF pictures stay inside their byte budget, a page picture too big to send says so
instead of arriving cut short, and a Word file's pages keep their real numbers when one in the middle could not be pictured."""
import importlib.util, json, os, sys, tempfile, time, unittest, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zook_preview_tails', ROOT / 'backend/server.py'); server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)
sys.path.insert(0, str(ROOT / 'backend'))
import pagepics  # noqa: E402
from preview_polish_test import tiny_pdf  # noqa: E402


class PdfByteBudget(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'needs macOS CoreGraphics')
    def test_pictures_never_pass_the_byte_budget(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / 'p.pdf'; pdf.write_bytes(tiny_pdf(4)); one = Path(d) / 'one'; one.mkdir(); out = Path(d) / 'out'; out.mkdir()
            pagepics.USED.update(pixels=0, bytes=0); pagepics.SKIPPED[0] = 0
            page = os.path.getsize(pagepics.pdf_pages(str(pdf), str(one))[0][0][0])  # how big one page's picture is
            old = pagepics.MAX_BYTES; pagepics.MAX_BYTES = int(page * 1.5)  # room for one page, not two
            pagepics.USED.update(pixels=0, bytes=0); pagepics.SKIPPED[0] = 0
            try: done, missing = pagepics.pdf_pages(str(pdf), str(out))
            finally: pagepics.MAX_BYTES = old
            written = sum(os.path.getsize(str(out / n)) for n in os.listdir(str(out)))
            self.assertLessEqual(written, int(page * 1.5))
            self.assertEqual((len(done), missing, pagepics.SKIPPED[0], len(os.listdir(str(out)))), (1, [], 3, 1))  # the rest is said to be left out
            pagepics.SKIPPED[0] = 0; pagepics.USED.update(pixels=0, bytes=0)


class DocxPageNumbers(unittest.TestCase):
    def test_a_page_missing_in_a_piece_keeps_the_numbers_after_it(self):
        real_run, real_pdf = pagepics._run, pagepics.pdf_pages
        def fake_run(cmd, timeout=120):
            for n in (1, 2): Path(cmd[-2] + '-%d.pdf' % n).write_bytes(b'%PDF')
            return True
        def fake_pdf(path, out, width=1600):  # piece 1 has three pages, its second could not be drawn; piece 2 has one
            stem = os.path.basename(path)[:-4]; made = []
            for n in ((1, 3) if stem == 'part-1' else (1,)):
                png = os.path.join(out, '%s-%02d.png' % (stem, n)); Path(png).write_bytes(stem.encode() + b'/%d' % n); made.append((png, 595, 842))
            return made, [2] if stem == 'part-1' else []
        pagepics._run, pagepics.pdf_pages = fake_run, fake_pdf
        try:
            with tempfile.TemporaryDirectory() as d:
                doc = Path(d) / 'a.docx'
                with zipfile.ZipFile(str(doc), 'w') as z: z.writestr('word/document.xml', '<w:document/>')
                done, missing = pagepics.docx_pages(str(doc), d)
                named = {os.path.basename(p): Path(p).read_bytes() for p, _, _ in done}
        finally: pagepics._run, pagepics.pdf_pages = real_run, real_pdf
        self.assertEqual(missing, [2])
        self.assertEqual(named, {'a-01.png': b'part-1/1', 'a-03.png': b'part-1/3', 'a-04.png': b'part-2/1'})


class TooBigPage(unittest.TestCase):
    def test_a_page_picture_over_the_limit_says_so_instead_of_arriving_cut(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(os.path.realpath(d)); store = type('S', (), {'dir': root / 'data'})(); store.dir.mkdir()
            pdf = root / 'r.pdf'; pdf.write_bytes(b'%PDF-1.4 x')
            def fake(src, out):
                os.makedirs(out); Path(out, '1.png').write_bytes(b'\x89PNG' + b'x' * server.MAX_UPLOAD); Path(out, '2.png').write_bytes(b'\x89PNG small')
                return [os.path.join(out, '1.png'), os.path.join(out, '2.png')], '', 2
            real = server.office_render; server.office_render = fake
            try:
                server.office_preview(store, str(pdf))
                for _ in range(300):
                    state = server.office_preview(store, str(pdf))
                    if state['status'] != 'working': break
                    time.sleep(0.02)
            finally: server.office_render = real
            self.assertEqual((state['status'], state['pages'], state.get('big')), ('ready', 2, [1]))
            self.assertTrue(server.preview_page(store, str(pdf), 1) is None)  # never a picture cut short
            self.assertEqual(server.preview_page(store, str(pdf), 2), b'\x89PNG small')

    def test_pictured_pages_keep_their_real_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(os.path.realpath(d)); store = type('S', (), {'dir': root / 'data'})(); store.dir.mkdir()
            doc = root / 'r.docx'; doc.write_bytes(b'PK not really')
            def fake(src, out):  # page 2 could not be pictured
                os.makedirs(out); Path(out, 'preview-01.png').write_bytes(b'one'); Path(out, 'preview-03.png').write_bytes(b'three')
                return [os.path.join(out, 'preview-01.png'), os.path.join(out, 'preview-03.png')], '第 2 頁無法預覽，完整內容請下載後查看。', 3
            real = server.office_render; server.office_render = fake
            try:
                server.office_preview(store, str(doc))
                for _ in range(300):
                    state = server.office_preview(store, str(doc))
                    if state['status'] != 'working': break
                    time.sleep(0.02)
            finally: server.office_render = real
            self.assertEqual((state['pages'], state['total'], state.get('numbers')), (2, 3, [1, 3]))
            self.assertEqual(server.preview_page(store, str(doc), 2), b'three')
            code = (ROOT / 'frontend/js/36-outputs.js').read_text(encoding='utf-8'); self.assertIn('info.numbers', code)

    def test_a_cached_picture_over_the_limit_is_not_read_cut_short(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(os.path.realpath(d)); store = type('S', (), {'dir': root / 'data'})(); folder = root / 'data/previews/k'; folder.mkdir(parents=True)
            (folder / '1.png').write_bytes(b'x' * (server.MAX_UPLOAD + 1))
            self.assertTrue(server._cache_read(store, 'k', '1.png') is None)

    def test_the_preview_window_says_to_download_it(self):
        code = (ROOT / 'frontend/js/36-outputs.js').read_text(encoding='utf-8')
        self.assertIn('這頁太大，請下載查看', code); self.assertIn('info.big', code)


if __name__ == '__main__': unittest.main()
