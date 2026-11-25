# -*- coding: utf-8 -*-
"""Every Bot is told how to hand over files a person can open as they are (Excel showing its numbers in previews too)."""
import importlib.util, os, re, subprocess, sys, tempfile, time, unittest, zipfile
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
PAGEPICS = SERVER.with_name('pagepics.py')
spec = importlib.util.spec_from_file_location('zook_file_delivery', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)
spec = importlib.util.spec_from_file_location('zook_pagepics', PAGEPICS); pics = importlib.util.module_from_spec(spec); spec.loader.exec_module(pics)


class Store:
    def __init__(self, root): self.dir = Path(root); self.data = {'bots': [], 'knowledge': [], 'memories': []}
    def find(self, kind, key): return next((x for x in self.data[kind] if x['id'] == key), None)


class FileDelivery(unittest.TestCase):
    def setUp(self): m._active['data'] = {'settings': {}, 'rules': []}

    def test_every_bot_hears_it(self):
        text = m.identity_block(dict(name='業務小幫'))
        self.assertIn('完整路徑', text); self.assertIn('xlsxwriter', text); self.assertIn('轉成圖片', text); self.assertIn('qlmanage', text); self.assertIn('暫存程式', text); self.assertIn('【待確認', text)

    def test_named_location_previews_without_windows_and_scratch_cleanup(self):
        """巡檢 #22 #24 #25 #27 #28."""
        text = m.identity_block(dict(name='業務小幫'))
        self.assertIn('指定了存放位置', text); self.assertIn('同時放群組檔案和那個位置', text)  # #24
        self.assertIn(str(PAGEPICS), text); self.assertIn('不開視窗', text); self.assertIn('osascript', text); self.assertIn('~$', text)  # #25 #27
        self.assertIn('每一頁', text); self.assertIn('對比', text); self.assertIn('16:9', text)  # #27
        self.assertIn('mktemp -d', text); self.assertIn('不要放在交付位置或群組檔案裡', text); self.assertIn('群組主持人與成員', text)  # #22
        self.assertIn('Skill 的內部規則', text)  # #28
        self.assertIn('旋轉不滲漏', text); self.assertIn('沒有來源的數字', text)  # #41 #127: no made-up product facts or prices
        self.assertIn('多出來的事實或沒有來源的數字', ' '.join(m.MODERATOR_RULES['verify']))  # and a check looks for them
        self.assertIn("<<'EOF'", text); self.assertIn('NT$608,000', text); self.assertIn('存完一定回讀檔案', text)  # #55: $ eaten by the shell
        self.assertIn('讀不到、失敗時', text); self.assertIn('沒轉出的頁', text)  # a Bot limited to one folder cannot read the helper in the app

    def test_group_and_task_prompts_carry_it(self):
        """Group hosts and members and task-engine members all get the shared rules, plus the user's named location."""
        with tempfile.TemporaryDirectory() as root:
            store = Store(root); bot = dict(id='b1', name='成員', provider='codex'); store.data['bots'].append(bot)
            group = dict(id='g1', name='行銷', botIds=['b1'], messages=[])
            for prompt in (m.group_prompt(store, group, bot, False, writable=True), m.group_prompt(store, group, bot, False, moderator='kickoff', writable=True)):
                self.assertIn('不要放在交付位置或群組檔案裡', prompt); self.assertIn('使用者另外指定的存放位置也要存一份', prompt)
            run = dict(hostId='b1', tasks=[], goal='做簡報放 /tmp/out/'); task = dict(n=1, title='簡報', spec='做簡報', doneWhen='有檔案', depth=1)
            worker = m.task_worker_prompt(store, group, run, task, bot, True)
            self.assertIn('不要放在交付位置或群組檔案裡', worker); self.assertIn('工作說明指定的存放位置也要存一份', worker)


class PagePictures(unittest.TestCase):
    """Every page of a PDF or a deck becomes a picture, with no app window and nothing left behind."""
    def test_ratio_names(self):
        self.assertEqual(pics.ratio(12192000, 6858000), '16:9'); self.assertEqual(pics.ratio(9144000, 6858000), '4:3'); self.assertEqual(pics.ratio(595, 842), 'A4 直式')

    def test_each_slide_is_pictured_from_its_own_copy(self):
        with tempfile.TemporaryDirectory() as root:
            deck = Path(root) / 'd.pptx'; out = Path(root) / 'pics'; out.mkdir(); seen = []
            with zipfile.ZipFile(deck, 'w') as z:
                z.writestr('ppt/presentation.xml', '<p:presentation><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/></p:sldIdLst>'
                                                   '<p:sldSz cx="12192000" cy="6858000"/></p:presentation>')
                z.writestr('ppt/slides/slide1.xml', 'one')

            def fake(path, folder, width=1600):
                with zipfile.ZipFile(path) as z: seen.append(re.findall(r'id="(\d+)"', z.read('ppt/presentation.xml').decode())); self.assertEqual(z.read('ppt/slides/slide1.xml'), b'one')
                made = os.path.join(folder, os.path.basename(path) + '.png'); open(made, 'wb').close(); return made
            real, pics.quicklook = pics.quicklook, fake
            try: pages, missing = pics.pptx_pages(str(deck), str(out))
            finally: pics.quicklook = real
            self.assertEqual(missing, []); self.assertEqual(seen, [['256'], ['257']]); self.assertEqual(sorted(os.listdir(out)), ['d-01.png', 'd-02.png'])
            self.assertEqual([pics.ratio(w, h) for _, w, h in pages], ['16:9', '16:9']); self.assertEqual(sorted(os.listdir(root)), ['d.pptx', 'pics'])

    def deck(self, root, prefix='p:', declare=True, slides=('256', '257')):
        deck = Path(root) / 'd.pptx'; ns = 'xmlns%s="http://schemas.openxmlformats.org/presentationml/2006/main"' % ((':' + prefix[:-1]) if prefix else '')
        items = ''.join('<%ssldId id="%s" r:id="rId%s"/>' % (prefix, s, s) for s in slides)
        with zipfile.ZipFile(deck, 'w') as z:
            z.writestr('ppt/presentation.xml', '<%spresentation %s xmlns:r="r"><%ssldIdLst>%s</%ssldIdLst><%ssldSz cx="12192000" cy="6858000"/></%spresentation>'
                       % (prefix, ns if declare else '', prefix, items, prefix, prefix, prefix))
        return deck

    def run_deck(self, deck, out, fail=()):
        seen = []
        def fake(path, folder, width=1600):
            with zipfile.ZipFile(path) as z: seen.append(re.findall(r'id="(\d+)"', z.read('ppt/presentation.xml').decode()))
            if len(seen) in fail: return None
            made = os.path.join(folder, os.path.basename(path) + '.png'); open(made, 'wb').close(); return made
        real, pics.quicklook = pics.quicklook, fake
        try: return pics.pptx_pages(str(deck), str(out)), seen
        finally: pics.quicklook = real

    def test_slides_are_found_by_namespace_not_by_prefix(self):
        for prefix in ('ps:', ''):
            with tempfile.TemporaryDirectory() as root:
                out = Path(root) / 'pics'; out.mkdir()
                (pages, missing), seen = self.run_deck(self.deck(root, prefix), out)
                self.assertEqual((len(pages), missing, seen), (2, [], [['256'], ['257']]), prefix)
                self.assertEqual([pics.ratio(w, h) for _, w, h in pages], ['16:9', '16:9'])

    def test_missing_slides_are_named_and_fail(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / 'pics'; out.mkdir(); deck = self.deck(root, slides=('256', '257', '258'))
            (pages, missing), _ = self.run_deck(deck, out, fail=(2,))
            self.assertEqual((len(pages), missing), (2, [2]))
            real = pics.pptx_pages; pics.pptx_pages = lambda path, folder: (pages, missing)
            try:
                with self.assertRaises(SystemExit) as caught: pics.main(['pagepics.py', str(deck), str(out)])
            finally: pics.pptx_pages = real
            self.assertIn('第 2 頁', str(caught.exception.code)); self.assertNotIn('第 1', str(caught.exception.code))

    def test_stopping_it_leaves_no_copies(self):
        """Zook stops a job with SIGTERM: the one-slide copies, kept inside the output (scratch) folder, are removed."""
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / 'pics'; ready = Path(root) / 'ready'; deck = self.deck(root)
            driver = ('import importlib.util, sys, time\n'
                      'spec = importlib.util.spec_from_file_location("p", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n'
                      'def slow(path, folder, width=1600):\n    open(sys.argv[2], "w").write(folder); time.sleep(60)\n'
                      'm.quicklook = slow; m.main(["pagepics.py", sys.argv[3], sys.argv[4]])\n')
            proc = subprocess.Popen(['/usr/bin/python3', '-c', driver, str(PAGEPICS), str(ready), str(deck), str(out)], stderr=subprocess.PIPE)
            end = time.time() + 30
            while not ready.exists() and time.time() < end: time.sleep(0.05)
            folder = ready.read_text(); self.assertEqual(Path(folder).parent, out); self.assertTrue(os.listdir(folder))
            proc.terminate(); proc.wait(timeout=10); proc.stderr.close()
            self.assertNotEqual(proc.returncode, 0); self.assertEqual(os.listdir(out), [])

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS only')
    def test_a_picture_that_cannot_be_written_fails(self):
        with tempfile.TemporaryDirectory() as root:
            pdf = Path(root) / 'r.pdf'; out = Path(root) / 'pics'; out.mkdir(); self.pdf(pdf); out.chmod(0o555)
            try: result = subprocess.run(['/usr/bin/python3', str(PAGEPICS), str(pdf), str(out)], capture_output=True, text=True, timeout=120)
            finally: out.chmod(0o755)
            self.assertEqual(result.returncode, 1); self.assertIn('第 1、2 頁', result.stderr); self.assertEqual(os.listdir(out), [])

    def pdf(self, pdf):
        objs = ['<</Type/Catalog/Pages 2 0 R>>', '<</Type/Pages/Kids[3 0 R 4 0 R]/Count 2>>', '<</Type/Page/Parent 2 0 R/MediaBox[0 0 960 540]>>', '<</Type/Page/Parent 2 0 R/MediaBox[0 0 960 540]>>']
        body, offsets = b'%PDF-1.4\n', []
        for i, o in enumerate(objs, 1): offsets.append(len(body)); body += ('%d 0 obj\n%s\nendobj\n' % (i, o)).encode()
        xref = len(body); body += ('xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)).encode() + b''.join(b'%010d 00000 n \n' % x for x in offsets)
        pdf.write_bytes(body + ('trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)).encode())

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS only')
    def test_every_pdf_page(self):
        with tempfile.TemporaryDirectory() as root:
            pdf = Path(root) / 'r.pdf'; out = Path(root) / 'pics'
            objs = ['<</Type/Catalog/Pages 2 0 R>>', '<</Type/Pages/Kids[3 0 R 4 0 R]/Count 2>>', '<</Type/Page/Parent 2 0 R/MediaBox[0 0 960 540]>>', '<</Type/Page/Parent 2 0 R/MediaBox[0 0 960 540]>>']
            body, offsets = b'%PDF-1.4\n', []
            for i, o in enumerate(objs, 1): offsets.append(len(body)); body += ('%d 0 obj\n%s\nendobj\n' % (i, o)).encode()
            xref = len(body); body += ('xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)).encode() + b''.join(b'%010d 00000 n \n' % x for x in offsets)
            pdf.write_bytes(body + ('trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)).encode())
            result = subprocess.run(['/usr/bin/python3', str(PAGEPICS), str(pdf), str(out)], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(result.stdout.count('比例 16:9'), 2)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['r-01.png', 'r-02.png'])
            self.assertEqual((out / 'r-01.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')


if __name__ == '__main__': unittest.main()
