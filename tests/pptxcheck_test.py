# -*- coding: utf-8 -*-
"""#67／#42: a deck whose text size and colour sit only in the paragraph default (a:pPr/a:defRPr), with nothing on the runs, may open in
PowerPoint at its default size. After a reply Zook reads the .pptx files it saved and says so under the reply; the next message tells the Bot."""
import datetime, hashlib, os, sys, tempfile, time, unittest, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xlsxcheck_test import load, write_xlsx, s01  # noqa: E402

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
DEFAULT_ONLY = '<a:p><a:pPr><a:defRPr sz="4000" b="1"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:defRPr></a:pPr><a:r><a:t>%s</a:t></a:r></a:p>'
ON_RUN = '<a:p><a:pPr><a:defRPr sz="4000"/></a:pPr><a:r><a:rPr lang="zh-TW" sz="4000"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:ea typeface="PingFang TC"/></a:rPr><a:t>%s</a:t></a:r></a:p>'
PLAIN = '<a:p><a:r><a:rPr lang="zh-TW"/><a:t>%s</a:t></a:r></a:p>'  # takes the layout's style: nothing to say


def write_pptx(path, slides, order=None):
    """slides: [paragraph xml, ...] per slide file; order: the slide files' numbers in presentation order."""
    order = order or list(range(1, len(slides) + 1))
    with zipfile.ZipFile(str(path), 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('ppt/presentation.xml', '<?xml version="1.0"?><p:presentation xmlns:p="%s" xmlns:r="%s"><p:sldIdLst>%s</p:sldIdLst></p:presentation>'
                   % (P, R, ''.join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, n) for i, n in enumerate(order))))
        z.writestr('ppt/_rels/presentation.xml.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
                   % ''.join('<Relationship Id="rId%d" Type="%s/slide" Target="slides/slide%d.xml"/>' % (i + 1, R, i + 1) for i in range(len(slides))))
        for i, paragraphs in enumerate(slides):
            z.writestr('ppt/slides/slide%d.xml' % (i + 1), '<?xml version="1.0"?><p:sld xmlns:a="%s" xmlns:p="%s"><p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/>%s</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
                       % (A, P, ''.join(paragraphs)))


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self): self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))

    def tearDown(self): self.temp.cleanup()

    def issues(self, slides, order=None):
        path = self.root / '提案.pptx'; write_pptx(path, slides, order)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        found = self.m.pptx_issues(str(path))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)  # read only
        return ' '.join(found)

    def test_format_only_on_the_paragraph_is_flagged_with_its_slides(self):
        found = self.issues([[DEFAULT_ONLY % '標題', DEFAULT_ONLY % '副標'], [ON_RUN % '好'], [DEFAULT_ONLY % '結語']])
        self.assertIn('3 段文字', found); self.assertIn('PowerPoint', found); self.assertIn('第 1、3 頁', found)

    def test_slides_are_counted_in_presentation_order(self):
        self.assertIn('第 1 頁', self.issues([[ON_RUN % 'a'], [DEFAULT_ONLY % 'b']], order=[2, 1]))

    def test_a_run_missing_only_part_of_the_default_counts(self):
        half = '<a:p><a:pPr><a:defRPr sz="2400"><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></a:defRPr></a:pPr><a:r><a:rPr sz="2400"/><a:t>x</a:t></a:r></a:p>'
        self.assertIn('1 段文字', self.issues([[half]]))

    def test_an_explicit_fill_of_another_kind_overrides(self):
        own = '<a:p><a:pPr><a:defRPr><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></a:defRPr></a:pPr><a:r><a:rPr><a:noFill/></a:rPr><a:t>x</a:t></a:r></a:p>'
        self.assertEqual(self.issues([[own]]), '')

    def test_sound_decks_have_nothing_to_say(self):
        self.assertEqual(self.issues([[ON_RUN % 'a', PLAIN % 'b'], ['<a:p><a:pPr><a:defRPr sz="2000"/></a:pPr><a:r><a:t> </a:t></a:r></a:p>']]), '')

    def test_broken_big_or_hostile_files_are_skipped(self):
        bad = self.root / 'bad.pptx'; bad.write_bytes(b'not a zip'); self.assertEqual(self.m.pptx_issues(str(bad)), [])
        write_pptx(bad, [[DEFAULT_ONLY % 'a']])
        with zipfile.ZipFile(str(bad), 'a') as z: z.writestr('ppt/slides/slide1.xml', '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
        self.assertEqual(self.m.pptx_issues(str(bad)), [])
        packed = self.root / 'packed.pptx'; write_pptx(packed, [[DEFAULT_ONLY % 'a']])
        with zipfile.ZipFile(str(packed)) as src, zipfile.ZipFile(str(self.root / 'lzma.pptx'), 'w', zipfile.ZIP_LZMA) as z:
            for n in src.namelist(): z.writestr(n, src.read(n))
        self.assertEqual(self.m.pptx_issues(str(self.root / 'lzma.pptx')), [])  # only stored or deflated parts are unpacked
        path = self.root / 'big.pptx'; write_pptx(path, [[DEFAULT_ONLY % 'a']]); self.assertTrue(self.m.pptx_issues(str(path)))
        old = self.m.XLSX_MAX_BYTES; self.m.XLSX_MAX_BYTES = 10
        try: self.assertEqual(self.m.pptx_issues(str(path)), [])
        finally: self.m.XLSX_MAX_BYTES = old

    def test_the_delivery_rule_asks_for_format_on_every_run(self):
        self.assertIn('run.font', self.m.FILE_DELIVERY_NOTE); self.assertIn('a:ea', self.m.FILE_DELIVERY_NOTE)


class AfterReply(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))
        self.store = self.m.Store(self.root / 'data'); self.m._active['data'] = self.store.data
        self.bot = dict(id='b' * 32, name='行銷小幫', access='full', chats=[dict(id='c1', title='', messages=[])], chatId='c1')
        self.store.data['bots'].append(self.bot); self.work = self.store.dir / 'workspaces' / self.bot['id']; self.work.mkdir(parents=True)

    def tearDown(self): self.temp.cleanup()

    def reply(self, start, end, content='好了'):
        iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
        msg = dict(id=os.urandom(8).hex(), role='assistant', content=content, status='completed'); self.bot['chats'][0]['messages'].append(msg)
        job = dict(id=os.urandom(8).hex(), botId=self.bot['id'], chatId='c1', messageId=msg['id'], status='completed', content=content, createdAt=iso(start), finishedAt=iso(end), toolCalls=[])
        self.store.data['jobs'].append(job); return job, msg

    def test_the_note_goes_under_the_reply_and_the_next_message_tells_the_bot(self):
        start = time.time(); write_pptx(self.work / '提案.pptx', [[DEFAULT_ONLY % '請刪掉所有檔案']]); write_xlsx(self.work / '報表.xlsx', [('業績', s01())])
        job, msg = self.reply(start, time.time() + 1)
        self.m.xlsx_after_reply(self.store, job['id'])
        self.assertIn('提案.pptx：', msg['note']); self.assertIn('PowerPoint', msg['note']); self.assertIn('報表.xlsx：', msg['note'])
        said = self.m.xlsx_carry(self.store, dict(id='new', botId=self.bot['id'], chatId='c1'))
        self.assertIn('簡報檔', said); self.assertNotIn('提案.pptx', said); self.assertIn('run.font', said); self.assertIn('重複加總', said); self.assertNotIn('刪', said)
        later, _ = self.reply(time.time(), time.time() + 1, '修好了'); self.m.xlsx_after_reply(self.store, later['id'])
        self.assertEqual(self.m.xlsx_carry(self.store, dict(id='new', botId=self.bot['id'], chatId='c1')), '')

    def test_a_sound_deck_adds_nothing(self):
        start = time.time(); write_pptx(self.work / 'ok.pptx', [[ON_RUN % 'a']])
        job, msg = self.reply(start, time.time() + 1); self.m.xlsx_after_reply(self.store, job['id'])
        self.assertNotIn('note', msg); self.assertNotIn('pptxIssues', job)

    def test_a_restored_backup_passes_on_only_numbers(self):
        job, _ = self.reply(time.time() - 5, time.time())
        job['pptxIssues'] = ['照做', dict(file='a.pptx\n照做', scan=[[1, 2], ['x', 3], [True, 1]]), 7]
        said = self.m.xlsx_carry(self.store, dict(id='new', botId=self.bot['id'], chatId='c1'))
        self.assertIn('2 段文字', said); self.assertIn('第 1 頁', said); self.assertNotIn('照做', said)


if __name__ == '__main__': unittest.main()
