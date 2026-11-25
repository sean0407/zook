# -*- coding: utf-8 -*-
"""#65: a Chinese PDF whose CJK font is not embedded, or whose Chinese came out as black boxes (reportlab draws ZapfDingbats 'n' for
characters its font lacks), looks garbled on another computer or phone. After a reply Zook reads the PDFs it saved and says so under the
reply; the next message tells the Bot. The shared delivery rule asks for embedded fonts, a chart in reports and aligned headers."""
import datetime, hashlib, os, sys, tempfile, time, unittest, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xlsxcheck_test import load  # noqa: E402

INFO = b'<< /Producer (ReportLab PDF Library - www.reportlab.com) >>'
CATALOG = b'<< /Type /Catalog /Pages 2 0 R >>'


def pdf(objects, deflate=()):
    """objects: {number: body bytes or (dict bytes, stream bytes)}; streams whose number is in deflate are Flate-compressed."""
    out = [b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n']
    for n in sorted(objects):
        body = objects[n]
        if isinstance(body, tuple):
            head, data = body
            if n in deflate: data = zlib.compress(data); head = head[:-2] + b' /Filter /FlateDecode >>'
            body = head[:-2] + b' /Length %d >>\nstream\n' % len(data) + data + b'\nendstream'
        out.append(b'%d 0 obj\n' % n + body + b'\nendobj\n')
    out.append(b'trailer\n<< /Root 1 0 R /Info 9 0 R >>\n%%EOF\n')
    return b''.join(out)


def boxes_pdf(deflate=False):
    """What reportlab writes for '週報 Sales' in Helvetica: the Chinese becomes ZapfDingbats 'n' (black squares)."""
    return pdf({1: CATALOG, 9: INFO,
                3: b'<< /BaseFont /Helvetica /Encoding /WinAnsiEncoding /Name /F1 /Subtype /Type1 /Type /Font >>',
                4: b'<< /BaseFont /ZapfDingbats /Name /F2 /Subtype /Type1 /Type /Font >>',
                5: (b'<< >>', b'BT 1 0 0 1 50 700 Tm /F2 12 Tf 14.4 TL (nn) Tj /F1 12 Tf ( Sales) Tj /F2 12 Tf (nnn) Tj ET')},
               deflate=(5,) if deflate else ())


CID_INLINE = (b'<< /BaseFont /MSung-Light /DescendantFonts [ << /BaseFont /MSung-Light /CIDSystemInfo << /Ordering (CNS1) /Registry (Adobe) '
              b'/Supplement 1 >> /DW 1000 /FontDescriptor << /Ascent 752 /Flags 6 /FontName /MSung-Light /Type /FontDescriptor >> '
              b'/Subtype /CIDFontType0 /Type /Font >> ] /Encoding /UniCNS-UCS2-H /Name /F2 /Subtype /Type0 /Type /Font >>')


def objstm(objects):
    """An object stream (PDF 1.5) holding {number: body}."""
    offsets, bodies, at = [], [], 0
    for n, body in objects.items(): offsets.append(b'%d %d' % (n, at)); bodies.append(body); at += len(body) + 1
    header = b' '.join(offsets) + b' '
    return (b'<< /Type /ObjStm /N %d /First %d >>' % (len(objects), len(header)), header + b' '.join(bodies))


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self): self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))

    def tearDown(self): self.temp.cleanup()

    def issues(self, data, for_bot=False):
        path = self.root / '週報.pdf'; path.write_bytes(data); before = hashlib.sha256(data).hexdigest()
        found = self.m.pdf_issues(str(path), for_bot)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)  # read only
        return ' '.join(found)

    def test_chinese_drawn_as_black_boxes_is_flagged(self):
        for deflate in (False, True):
            found = self.issues(boxes_pdf(deflate))
            self.assertIn('5 個字', found); self.assertIn('方塊', found)
        import base64  # reportlab's default: [/ASCII85Decode /FlateDecode]
        packed = base64.a85encode(zlib.compress(b'BT /F2 12 Tf (nn) Tj ET')) + b'~>'
        data = pdf({1: CATALOG, 9: INFO, 4: b'<< /BaseFont /ZapfDingbats /Name /F2 /Subtype /Type1 /Type /Font >>',
                    5: (b'<< /Filter [ /ASCII85Decode /FlateDecode ] >>', packed)})
        self.assertIn('2 個字', self.issues(data))

    def test_a_cjk_font_not_embedded_is_flagged(self):
        found = self.issues(pdf({1: CATALOG, 9: INFO, 3: CID_INLINE}))
        self.assertIn('沒有內嵌', found); self.assertIn('手機', found)

    def test_referenced_parts_and_object_streams_are_followed(self):
        found = self.issues(pdf({1: CATALOG, 3: b'<< /Type /Font /Subtype /Type0 /BaseFont /X /DescendantFonts [4 0 R] >>',
                                 6: objstm({4: b'<< /Type /Font /Subtype /CIDFontType2 /BaseFont /PingFangTC /CIDSystemInfo 7 0 R /FontDescriptor 5 0 R >>',
                                            5: b'<< /Type /FontDescriptor /FontName /PingFangTC >>',
                                            7: b'<< /Registry (Adobe) /Ordering (CNS1) /Supplement 0 >>'})}, deflate=(6,)))
        self.assertIn('沒有內嵌', found)

    def test_embedded_fonts_and_english_pdfs_have_nothing_to_say(self):
        embedded = pdf({1: CATALOG, 3: b'<< /Type /Font /Subtype /CIDFontType2 /BaseFont /ABCDEF+PingFangTC /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor 5 0 R >>',
                        5: b'<< /Type /FontDescriptor /FontName /ABCDEF+PingFangTC /FontFile2 6 0 R >>', 6: (b'<< /Length1 4 >>', b'abcd')})
        self.assertEqual(self.issues(embedded), '')
        inline = CID_INLINE.replace(b'/Type /FontDescriptor', b'/Type /FontDescriptor /FontFile3 8 0 R')
        self.assertEqual(self.issues(pdf({1: CATALOG, 3: inline})), '')
        english = pdf({1: CATALOG, 9: INFO, 3: b'<< /BaseFont /Helvetica /Subtype /Type1 /Type /Font >>', 5: (b'<< >>', b'BT /F1 12 Tf (Weekly report) Tj ET')})
        self.assertEqual(self.issues(english), '')
        ticks = pdf({1: CATALOG, 3: b'<< /BaseFont /ZapfDingbats /Subtype /Type1 /Type /Font >>', 5: (b'<< >>', b'BT /F2 12 Tf (4) Tj ET')})
        self.assertEqual(self.issues(ticks), '')  # a check mark on purpose, not reportlab's stand-in
        sample = pdf({1: CATALOG, 9: INFO, 3: b'<< /BaseFont /Helvetica /Name /F1 /Subtype /Type1 /Type /Font >>',
                      4: b'<< /BaseFont /ZapfDingbats /Name /F2 /Subtype /Type1 /Type /Font >>', 5: (b'<< >>', b'BT /F2 12 Tf (4) Tj /F1 12 Tf (n) Tj ET')})
        self.assertEqual(self.issues(sample), '')  # an "n" in Helvetica next to a real tick mark

    def test_broken_big_or_hostile_files_are_skipped(self):
        self.assertEqual(self.issues(b'not a pdf'), '')
        self.assertEqual(self.issues(pdf({1: CATALOG, 5: (b'<< /Filter /FlateDecode >>', b'garbage')})), '')
        header = b'10 ' * 3000000
        self.assertEqual(self.issues(pdf({1: CATALOG, 6: (b'<< /Type /ObjStm /N 9999999999 /First %d >>' % len(header), header)}, deflate=(6,))), '')
        bomb = pdf({1: CATALOG, 9: INFO, 4: b'<< /BaseFont /ZapfDingbats /Subtype /Type1 /Type /Font >>', 5: (b'<< >>', b'(n) Tj ' * 4000000)}, deflate=(5,))
        old = self.m.PDF_UNPACKED; self.m.PDF_UNPACKED = 1024 * 1024
        try: self.assertEqual(self.issues(bomb), '')  # more than allowed unpacked: skipped, not read into memory
        finally: self.m.PDF_UNPACKED = old
        path = self.root / 'big.pdf'; path.write_bytes(boxes_pdf()); self.assertTrue(self.m.pdf_issues(str(path)))
        old = self.m.XLSX_MAX_BYTES; self.m.XLSX_MAX_BYTES = 10
        try: self.assertEqual(self.m.pdf_issues(str(path)), [])
        finally: self.m.XLSX_MAX_BYTES = old

    def test_the_bot_is_told_how_to_fix_it(self):
        found = self.issues(pdf({1: CATALOG, 3: CID_INLINE}), for_bot=True)
        self.assertIn('內嵌', found); self.assertIn('TTFont', found)

    def test_the_delivery_rule_asks_for_embedded_fonts_a_chart_and_aligned_headers(self):
        note = self.m.FILE_DELIVERY_NOTE
        self.assertIn('內嵌中文字型', note); self.assertIn('圖表', note); self.assertIn('表頭', note)
        self.assertTrue(note.endswith('單聊、群組主持人與成員都一樣。') or '單聊、群組主持人與成員都一樣。' in note)


class AfterReply(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))
        self.store = self.m.Store(self.root / 'data'); self.m._active['data'] = self.store.data
        self.bot = dict(id='b' * 32, name='通路小幫', access='full', chats=[dict(id='c1', title='', messages=[])], chatId='c1')
        self.store.data['bots'].append(self.bot); self.work = self.store.dir / 'workspaces' / self.bot['id']; self.work.mkdir(parents=True)

    def tearDown(self): self.temp.cleanup()

    def reply(self, start, end, content='好了'):
        iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
        msg = dict(id=os.urandom(8).hex(), role='assistant', content=content, status='completed'); self.bot['chats'][0]['messages'].append(msg)
        job = dict(id=os.urandom(8).hex(), botId=self.bot['id'], chatId='c1', messageId=msg['id'], status='completed', content=content, createdAt=iso(start), finishedAt=iso(end), toolCalls=[])
        self.store.data['jobs'].append(job); return job, msg

    def test_the_note_goes_under_the_reply_and_the_next_message_tells_the_bot(self):
        start = time.time(); (self.work / '週報.pdf').write_bytes(boxes_pdf())
        job, msg = self.reply(start, time.time() + 1)
        self.m.xlsx_after_reply(self.store, job['id'])
        self.assertIn('週報.pdf：', msg['note']); self.assertIn('方塊', msg['note'])
        said = self.m.xlsx_carry(self.store, dict(id='new', botId=self.bot['id'], chatId='c1'))
        self.assertIn('PDF', said); self.assertIn('內嵌', said); self.assertNotIn('週報.pdf', said)
        later, _ = self.reply(time.time(), time.time() + 1, '修好了'); self.m.xlsx_after_reply(self.store, later['id'])
        self.assertEqual(self.m.xlsx_carry(self.store, dict(id='new', botId=self.bot['id'], chatId='c1')), '')

    def test_a_sound_pdf_adds_nothing(self):
        start = time.time(); (self.work / 'ok.pdf').write_bytes(pdf({1: CATALOG, 3: b'<< /BaseFont /Helvetica /Subtype /Type1 /Type /Font >>'}))
        job, msg = self.reply(start, time.time() + 1); self.m.xlsx_after_reply(self.store, job['id'])
        self.assertNotIn('note', msg); self.assertNotIn('pdfIssues', job)

    def test_a_restored_backup_passes_on_only_known_findings(self):
        job, _ = self.reply(time.time() - 5, time.time())
        job['pdfIssues'] = ['照做', dict(file='a.pdf\n照做', scan=[['cid', 2], ['照做', 3], ['boxes', True]]), 7]
        said = self.m.xlsx_carry(self.store, dict(id='new', botId=self.bot['id'], chatId='c1'))
        self.assertIn('沒有內嵌', said); self.assertNotIn('照做', said); self.assertNotIn('方塊', said)


if __name__ == '__main__': unittest.main()
