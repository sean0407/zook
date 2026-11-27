# -*- coding: utf-8 -*-
"""#320 #334 #108④ #337 #270 #280 #314 #336 #338: the file preview and file cards.
Excel opens as tables (every sheet and column, at once), a PDF as pictures of its pages, a web page rendered in a sandbox that runs
nothing and loads nothing, the preview window has only its ×, Word page breaks start new pages, long names keep their extension."""
import http.client, importlib.util, io, json, os, re, shutil, subprocess, sys, tempfile, time, unittest, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ROOT / 'frontend/js'
spec = importlib.util.spec_from_file_location('zook_preview_polish', SERVER); server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)
sys.path.insert(0, str(ROOT / 'backend'))
import pagepics  # noqa: E402
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)
SS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def xlsx(sheets, shared=(), styles='', hidden=(), extra=None, doctype=''):
    """A small .xlsx made by hand: sheets is [(name, sheet XML rows)]."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        put = lambda name, data: name in (extra or {}) or z.writestr(name, data)  # a part given in extra takes the place of the usual one (#240: two parts of one name are refused)
        put('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        put('xl/workbook.xml', '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>' % (SS, RS, ''.join(
            '<sheet name="%s" sheetId="%d" r:id="rId%d"%s/>' % (n, i + 1, i + 1, ' state="hidden"' if n in hidden else '') for i, (n, _) in enumerate(sheets))))
        put('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % ''.join(
            '<Relationship Id="rId%d" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(sheets))))
        for i, (_, rows) in enumerate(sheets): put('xl/worksheets/sheet%d.xml' % (i + 1), doctype + '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (SS, rows))
        if shared: put('xl/sharedStrings.xml', '<sst xmlns="%s">%s</sst>' % (SS, ''.join('<si><t>%s</t></si>' % s for s in shared)))
        if styles: put('xl/styles.xml', '<styleSheet xmlns="%s">%s</styleSheet>' % (SS, styles))
        for name, data in (extra or {}).items(): z.writestr(name, data)
    return out.getvalue()


class SheetTables(unittest.TestCase):
    def test_every_sheet_and_column_with_values_as_excel_saved_them(self):
        styles = '<numFmts><numFmt numFmtId="164" formatCode="0.0%"/></numFmts><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="3"/></cellXfs>'
        row1 = ''.join('<c r="%s1" t="s"><v>%d</v></c>' % (c, i) for i, c in enumerate('ABCDEFGH'))
        row2 = '<c r="A2" s="1"><v>45992</v></c><c r="B2" s="2"><v>-0.034</v></c><c r="C2" s="3"><v>1234567</v></c><c r="H2"><f>SUM(A1:G1)</f><v>12.5</v></c><c r="D2" t="b"><v>1</v></c><c r="E2" t="inlineStr"><is><t>內文</t></is></c>'
        data = xlsx([('銷售', '<row r="1">%s</row><row r="2">%s</row>' % (row1, row2)), ('隱藏', '<row r="1"><c r="A1"><v>1</v></c></row>'), ('第二張', '<row r="3"><c r="B3"><v>7</v></c></row>')],
                    shared=['日期', '成長', '金額', '是否', '說明', 'F欄', 'G欄', '合計'], styles=styles, hidden=('隱藏',), extra={'xl/charts/chart1.xml': '<c/>'})
        got = server.sheet_tables(data)
        self.assertEqual([s['name'] for s in got['sheets']], ['銷售', '第二張'])  # a hidden sheet is left out
        first = got['sheets'][0]
        self.assertEqual(first['cols'], 8)  # #320: not only A–C
        self.assertEqual(first['rows'][0], [1, ['日期', '成長', '金額', '是否', '說明', 'F欄', 'G欄', '合計']])
        self.assertEqual(first['rows'][1], [2, ['2025-12-01', '-3.4%', '1,234,567', 'TRUE', '內文', '', '', '12.5']])
        self.assertEqual(got['sheets'][1]['rows'], [[3, ['', '7']]])
        self.assertTrue(got['charts'])

    def test_long_and_wide_sheets_are_cut_and_say_so(self):
        rows = ''.join('<row r="%d"><c r="A%d"><v>%d</v></c><c r="BZ%d"><v>1</v></c></row>' % (n, n, n, n) for n in range(1, server.SHEET_ROWS + 20))
        sheet = server.sheet_tables(xlsx([('大', rows)]))['sheets'][0]
        self.assertEqual(len(sheet['rows']), server.SHEET_ROWS); self.assertTrue(sheet['more']); self.assertTrue(sheet['wide']); self.assertEqual(sheet['cols'], 1)

    def test_crafted_sheets_stay_small(self):
        same = ''.join('<row r="1"><c r="A1"><v>%d</v></c></row>' % n for n in range(server.SHEET_ROWS + 50))  # one row number again and again
        self.assertEqual(len(server.sheet_tables(xlsx([('x', same)]))['sheets'][0]['rows']), server.SHEET_ROWS)
        wide = '<row r="1"><c r="%s1"><v>1</v></c><c r="A1" s="1"><v>0.5</v></c></row>' % ('A' * 5000)
        got = server.sheet_tables(xlsx([('x', wide)], styles='<numFmts><numFmt numFmtId="164" formatCode="0.%s"/></numFmts><cellXfs><xf numFmtId="0"/><xf numFmtId="164"/></cellXfs>' % ('0' * 5000)))['sheets'][0]
        self.assertTrue(got['wide']); self.assertEqual(got['rows'][0][1][0], '0.5000000000')
        old = server.SHEET_STRINGS; server.SHEET_STRINGS = 2
        try: self.assertTrue(server.sheet_tables(xlsx([('x', '<row r="1"><c r="A1" t="s"><v>2</v></c></row>')], shared=['a', 'b', 'c']))['partial'])  # says it is partial
        finally: server.SHEET_STRINGS = old
        self.assertFalse(server.sheet_tables(xlsx([('x', '<row r="1"><c r="A1"><v>1</v></c></row>')]))['partial'])
        twice = xlsx([('a', '<row r="1"><c r="A1"><v>1</v></c></row>')], extra={'xl/workbook.xml': '<workbook xmlns="%s" xmlns:r="%s"><sheets><sheet name="a" r:id="rId1"/><sheet name="b" r:id="rId1"/></sheets></workbook>' % (SS, RS)})
        self.assertEqual(len(server.sheet_tables(twice)['sheets']), 1)  # one sheet part is read once
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore'); out = io.BytesIO()
            with zipfile.ZipFile(out, 'w') as z: z.writestr('xl/workbook.xml', '<a/>'); z.writestr('xl/workbook.xml', '<b/>')
        with self.assertRaises(server.SheetRefused): server.sheet_tables(out.getvalue())  # two parts of one name (#240)

    def test_crafted_files_are_refused(self):
        bomb = '<!DOCTYPE x [<!ENTITY a "aaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        with self.assertRaises(server.SheetRefused): server.sheet_tables(xlsx([('x', '<row r="1"><c r="A1" t="inlineStr"><is><t>&b;</t></is></c></row>')], doctype=bomb))
        with self.assertRaises(server.SheetRefused): server.sheet_tables(b'not a zip')
        big = io.BytesIO()
        with zipfile.ZipFile(big, 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('xl/a.xml', b'0' * (server.PREVIEW_UNPACKED + 1))
        with self.assertRaises(server.SheetRefused): server.sheet_tables(big.getvalue())

    def test_sheet_preview_reads_only_a_real_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(os.path.realpath(d)); book = root / '報表.xlsx'; book.write_bytes(xlsx([('A', '<row r="1"><c r="A1"><v>3</v></c></row>')]))
            self.assertEqual(server.sheet_preview(str(book))['sheets'][0]['rows'], [[1, ['3']]])
            (root / 'link.xlsx').symlink_to(book)
            with self.assertRaises(OSError): server.sheet_preview(str(root / 'link.xlsx'))
            (root / 'bad.xlsx').write_bytes(b'PK broken')
            self.assertEqual(server.sheet_preview(str(root / 'bad.xlsx'))['status'], 'failed')
            with self.assertRaises(OSError): server.sheet_preview(str(root / 'a.docx'))


class PdfAndHtml(unittest.TestCase):
    def test_pdf_is_pictured_like_office_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(os.path.realpath(d)); store = type('S', (), {'dir': root / 'data'})(); store.dir.mkdir()
            pdf = root / 'r.pdf'; pdf.write_bytes(b'%PDF-1.4 x')
            real = server.office_render; seen = []
            server.office_render = lambda src, out: (seen.append(src), os.makedirs(out), Path(out, '1.png').write_bytes(b'\x89PNG'))[-1] and ([os.path.join(out, '1.png')], '', 1)
            try:
                self.assertEqual(server.office_preview(store, str(pdf))['status'], 'working')
                for _ in range(200):
                    state = server.office_preview(store, str(pdf))
                    if state['status'] != 'working': break
                    time.sleep(0.02)
            finally: server.office_render = real
            self.assertEqual(state['status'], 'ready'); self.assertTrue(seen[0].endswith('.pdf'))

    def test_html_is_its_own_kind_and_never_sent_as_a_page(self):
        self.assertEqual(server._output_kind('報告.html'), 'html'); self.assertEqual(server._output_kind('a.HTM'), 'html')
        with tempfile.TemporaryDirectory() as d:
            p = Path(os.path.realpath(d)) / 'x.html'; p.write_text('<script>alert(1)</script>')
            data, kind = server.output_response(dict(path=str(p), name='x.html', kind='html', size=p.stat().st_size))
            self.assertEqual(kind, 'text/plain; charset=utf-8')


class NamesAndNotes(unittest.TestCase):
    def test_long_upload_name_keeps_its_extension(self):
        self.assertEqual(server.upload_name('C-' + '長' * 200 + '.txt')[-4:], '.txt')
        self.assertEqual(len(server.upload_name('C-' + '長' * 200 + '.txt')), 120)
        self.assertEqual(server.upload_name('短.xlsx'), '短.xlsx')
        self.assertEqual(len(server.upload_name('x' * 300)), 120)

    def test_word_files_are_a4_and_not_signed_by_the_bot(self):
        self.assertIn('A4', server.FILE_DELIVERY_NOTE); self.assertIn('不要填 Bot 的名稱', server.FILE_DELIVERY_NOTE)

    def test_word_page_breaks_are_marked(self):
        xml = ('<w:body><w:p><w:r><w:t>一</w:t></w:r><w:r><w:br w:type="page"/></w:r></w:p>'
               '<w:p><w:pPr><w:pageBreakBefore/></w:pPr><w:r><w:t>二</w:t></w:r></w:p>'
               '<w:p><w:pPr><w:pageBreakBefore w:val="0"/></w:pPr><w:r><w:t>同頁</w:t></w:r></w:p>'
               '<w:p><w:pPr><w:sectPr><w:type w:val="continuous"/></w:sectPr></w:pPr></w:p>'
               '<w:p><w:pPr><w:sectPr/></w:pPr><w:r><w:t>三</w:t></w:r></w:p><w:p><w:r><w:br/></w:r></w:p></w:body>')
        self.assertEqual(pagepics.mark_page_breaks(xml).count(pagepics.PAGE_MARK), 3)
        slow = time.time(); pagepics.mark_page_breaks('<w:br ' * 200000); pagepics.mark_page_breaks('<w:p><w:pPr>' * 200000); self.assertLess(time.time() - slow, 2)  # malformed: no long scan

    @unittest.skipUnless(os.path.exists('/usr/bin/osascript') and not os.environ.get('CI'), "needs this Mac's text system")
    def test_real_word_file_breaks_into_pages(self):
        W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        para = lambda t: '<w:p><w:r><w:t>%s</w:t></w:r></w:p>' % t
        body = ''.join(para('第 %d 份' % n) + '<w:p><w:r><w:br w:type="page"/></w:r></w:p>' for n in range(3)) + para('錄取通知書')
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / 'b.docx'
            with zipfile.ZipFile(str(doc), 'w') as z:
                z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
                z.writestr('_rels/.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
                z.writestr('word/document.xml', '<?xml version="1.0"?><w:document xmlns:w="%s"><w:body>%s<w:sectPr/></w:body></w:document>' % (W, body))
            out = subprocess.run([sys.executable, str(ROOT / 'backend/pagepics.py'), str(doc), str(Path(d) / 'out')], capture_output=True, text=True, timeout=120)
            self.assertEqual(out.stdout.count('.png'), 4, out.stdout + out.stderr)


def tiny_pdf(pages):
    """A plain PDF with `pages` empty A4 pages, written by hand (offsets included)."""
    objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [%s] /Count %d >>' % (' '.join('%d 0 R' % (3 + i) for i in range(pages)), pages)]
    objs += ['<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>'] * pages
    out, offs = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1): offs.append(len(out)); out += ('%d 0 obj\n%s\nendobj\n' % (i, o)).encode()
    x = len(out); out += ('xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)).encode() + b''.join(b'%010d 00000 n \n' % o for o in offs)
    return out + ('trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, x)).encode()


class OutputLimits(unittest.TestCase):
    """Review of PR #127: what one preview may write, and what the cache keeps."""
    @unittest.skipUnless(sys.platform == 'darwin', 'needs macOS CoreGraphics')
    def test_pdf_pictures_stop_at_the_budget_and_say_so(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / 'big.pdf'; pdf.write_bytes(tiny_pdf(5)); out = Path(d) / 'out'; out.mkdir()
            old = pagepics.MAX_PIXELS; pagepics.MAX_PIXELS = 1600 * 2300 * 2  # room for two A4 pages
            pagepics.USED.update(pixels=0, bytes=0); pagepics.SKIPPED[0] = 0
            try: done, missing = pagepics.pdf_pages(str(pdf), str(out))
            finally: pagepics.MAX_PIXELS = old
            self.assertEqual((len(done), missing, pagepics.SKIPPED[0]), (2, [], 3))
            pagepics.SKIPPED[0] = 0; pagepics.USED.update(pixels=0, bytes=0)

    def test_cache_keeps_to_a_total_size(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(os.path.realpath(d)); store = type('S', (), {'dir': root / 'data'})(); previews = root / 'data/previews'; previews.mkdir(parents=True)
            names = []
            for n in range(3):
                src = root / ('f%d.docx' % n); src.write_bytes(b'PK%d' % n); key = server._preview_key(str(src), os.stat(str(src)))
                folder = previews / key; folder.mkdir(); (folder / '1.png').write_bytes(b'x' * 1000)
                (folder / 'done.json').write_text(json.dumps(dict(pages=1, total=1, path=str(src)))); os.utime(str(folder), (1000 + n, 1000 + n)); names.append(key)
            old = server.PREVIEW_BYTES; server.PREVIEW_BYTES = 2500
            try: server.sweep_previews(store, force=True)
            finally: server.PREVIEW_BYTES = old
            self.assertEqual(sorted(os.listdir(str(previews))), sorted(names[1:]))  # the oldest went first

    def test_a_docx_piece_that_cannot_be_read_is_named(self):
        real_run, real_pdf = pagepics._run, pagepics.pdf_pages
        def fake_run(cmd, timeout=120):
            for n in (1, 2, 3): Path(cmd[-2] + '-%d.pdf' % n).write_bytes(b'%PDF')
            return True
        def fake_pdf(path, out, width=1600):
            if path.endswith('part-2.pdf'): raise SystemExit('bad')
            png = os.path.join(out, os.path.basename(path) + '.png'); Path(png).write_bytes(b'png'); return [(png, 595, 842)], []
        pagepics._run, pagepics.pdf_pages = fake_run, fake_pdf
        try:
            with tempfile.TemporaryDirectory() as d:
                doc = Path(d) / 'a.docx'
                with zipfile.ZipFile(str(doc), 'w') as z: z.writestr('word/document.xml', '<w:document/>')
                done, missing = pagepics.docx_pages(str(doc), d)
        finally: pagepics._run, pagepics.pdf_pages = real_run, real_pdf
        self.assertEqual((len(done), missing), (2, [2]))

    def test_render_note_names_the_pages(self):
        code = (ROOT / 'backend/zook/officeview.py').read_text(encoding='utf-8')
        self.assertIn("無法預覽的頁：第 ([\\d、]+) 頁", code); self.assertIn('第 %s 頁無法預覽', code)
        self.assertIn("print('（無法預覽的頁：", (ROOT / 'backend/pagepics.py').read_text(encoding='utf-8'))

    def test_sheet_text_is_cut_while_read_and_infinity_is_fine(self):
        long = 'a' * 100000
        got = server.sheet_tables(xlsx([('x', '<row r="1"><c r="A1" t="inlineStr"><is><t>%s</t></is></c><c r="B1"><v>1e999</v></c><c r="C1"><v>%s</v></c></row>' % (long, '9' * 5000))], shared=[long]))
        row = got['sheets'][0]['rows'][0][1]
        self.assertEqual(len(row[0]), server.SHEET_TEXT); self.assertEqual(row[1], '1e999'); self.assertLessEqual(len(row[2]), server.SHEET_TEXT)
        parts = []; server._add_text(parts, 'x' * 1000); server._add_text(parts, 'y' * 1000)
        self.assertEqual(sum(map(len, parts)), server.SHEET_TEXT)  # nothing kept past the limit

    def test_sheet_is_fetched_once_when_opened(self):
        code = (JS / '36-outputs.js').read_text(encoding='utf-8')
        self.assertIn('sheetsRead.set(url, await res.json())', code); self.assertIn('let info = sheetsRead.get(src)', code)


class PageCode(unittest.TestCase):
    def read(self, name): return (JS / name).read_text(encoding='utf-8')

    def test_preview_window_has_only_its_close_cross(self):
        for name in ('36-outputs.js', '36b-files.js'):
            self.assertNotIn('data-action="close-modal">關閉</button>', self.read(name))  # #270
        self.assertIn("'viewer'", self.read('36-outputs.js'))

    def test_html_preview_is_sandboxed_and_offline(self):
        code = self.read('36-outputs.js')
        self.assertIn('sandbox=""', code)  # nothing allowed: no scripts, forms, pop-ups, same-origin
        self.assertNotRegex(code, r'sandbox="[^"]+"')
        policy = re.search(r'HTML_POLICY = "([^"]+)"', code).group(1)
        self.assertIn("default-src 'none'", policy); self.assertNotIn('http', policy); self.assertNotIn("'self'", policy)
        self.assertIn("kind === 'html'", code)
        frame = code[code.index('  function htmlFrame'):code.index('  async function previewBody')]
        self.assertIn("document.createElement('template')", frame)  # read inert, not cut with patterns (review: '>' inside quotes; nothing loads while read)
        for tag in ('meta[http-equiv]', 'base', 'link', 'script', 'iframe', 'object', 'embed'): self.assertIn(tag, frame)
        self.assertIn('(https?:\\/\\/|mailto:|#)', frame); self.assertIn("at.localName === 'href'", frame); self.assertIn("'src', 'srcset'", frame); self.assertIn("'ping', 'target'", frame)  # a link to Zook's own addresses is taken out

    def test_cards_icons_names_and_sizes(self):
        files, pages, groups = self.read('36b-files.js'), self.read('30-pages.js'), self.read('35-groups.js')
        self.assertIn('fileIcon(f.name)', files); self.assertIn('midName(f.name, 40)', files)  # #337①②
        self.assertIn("n < 1024 ? n + ' B'", pages)  # #337④
        self.assertIn('>預覽</button>', groups); self.assertIn("'html'", groups)  # #340
        self.assertIn('attach-input', self.read('10-chat.js')); self.assertIn("svg('clip')", self.read('10-chat.js'))  # #314 #336②

    @unittest.skipUnless(NODE, 'needs node to run the page code')
    def test_sheet_view_and_html_frame_render(self):
        code = self.read('36-outputs.js')
        part = code[code.index('  const sheetsRead'):code.index('  async function previewBody')] + code[code.index('  const columnName'):code.index('  document.addEventListener', code.index('  const columnName'))]
        harness = r"""
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
let fetched = null;
const fetch = async url => { fetched = url; return {status: 200, json: async () => ({status: 'ready', charts: true, sheets: [{name: '一', cols: 28, rows: [[1, ['a']], [5, ['', 'b']]], more: false, wide: false}, {name: '二', cols: 1, rows: [], more: true}]})}; };
__CODE__
(async () => {
  const box = {isConnected: true, innerHTML: ''};
  await fillSheetView(box, '/api/x');
  console.log(JSON.stringify({fetched, html: box.innerHTML, col: [columnName(1), columnName(26), columnName(27), columnName(60)]}));
})();
"""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'h.js'; f.write_text(harness.replace('__CODE__', part), encoding='utf-8')
            out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        self.assertEqual(got['fetched'], '/api/x/pages/sheets')
        self.assertEqual(got['col'], ['A', 'Z', 'AA', 'BH'])
        self.assertIn('data-sheet-tab="1"', got['html']); self.assertIn('<th>AB</th>', got['html']); self.assertIn('<th>5</th>', got['html'])
        self.assertIn('圖表不會顯示', got['html']); self.assertIn('前 300 列', got['html'])


class Routes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name)); (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x')
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), HOME=str(self.root), PATH='/usr/bin:/bin')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self): self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def test_sheets_route_for_outputs_and_group_files(self):
        bot = self.req('POST', '/api/bots', {'name': 'Maker', 'provider': 'codex'})[1]; other = self.req('POST', '/api/bots', {'name': 'Other', 'provider': 'codex'})[1]
        work = self.root / 'data/workspaces' / bot['id']; work.mkdir(parents=True, exist_ok=True)
        (work / '業績.xlsx').write_bytes(xlsx([('S', '<row r="1"><c r="D1"><v>9</v></c></row>')]))
        item = next(o for o in self.req('GET', '/api/bots/%s/outputs' % bot['id'])[1]['outputs'] if o['name'] == '業績.xlsx')
        status, got = self.req('GET', '/api/bots/%s/outputs/%s/pages/sheets' % (bot['id'], item['id']))
        self.assertEqual((status, got['sheets'][0]['rows']), (200, [[1, ['', '', '', '9']]]))
        group = self.req('POST', '/api/groups', {'name': 'G', 'botIds': [bot['id'], other['id']]})[1]
        shared = self.root / 'data/group-files' / group['id']; shared.mkdir(parents=True, exist_ok=True)
        (shared / 'q.xlsx').write_bytes(xlsx([('S', '<row r="2"><c r="A2"><v>4</v></c></row>')]))
        status, got = self.req('GET', '/api/groups/%s/files/q.xlsx/pages/sheets' % group['id'])
        self.assertEqual((status, got['sheets'][0]['rows']), (200, [[2, ['4']]]))
        self.assertEqual(self.req('GET', '/api/groups/%s/files/nope.xlsx/pages/sheets' % group['id'])[0], 404)


if __name__ == '__main__': unittest.main()
