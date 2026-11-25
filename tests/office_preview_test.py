# -*- coding: utf-8 -*-
"""#239: Excel, Word and PowerPoint files are previewed as pictures of their pages (產出, chat file cards, group files).
The pictures are made once per version of a file, kept in data/previews, and removed with the file. Quick Look is never
needed here: the part that makes pictures is replaced by a fake (one test uses the real one, only on a Mac that has it)."""
import http.client, importlib.util, json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ROOT / 'frontend/js'
spec = importlib.util.spec_from_file_location('zook_office', SERVER); server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20


class Store:
    def __init__(self, root): self.dir = Path(root)


def wait_ready(store, path, strict=False, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        state = server.office_preview(store, path, strict)
        if state['status'] != 'working': return state
        time.sleep(0.02)
    raise AssertionError('preview never finished')


class OfficePreviewLogic(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name)); self.store = Store(self.root / 'data')
        self.store.dir.mkdir(); self.made = []
        self.real_render = server.office_render
        def fake(source, out):
            self.made.append(Path(source).read_bytes()); os.makedirs(out)
            pages = []
            for n in (1, 2, 10):  # numbered pages come back in page order, not as text sorts them
                p = os.path.join(out, 'preview-%d.png' % n); Path(p).write_bytes(PNG + str(n).encode()); pages.append(p)
            return pages, '', 3
        server.office_render = fake
        self.doc = self.root / '報告.docx'; self.doc.write_bytes(b'PK first')

    def tearDown(self): server.office_render = self.real_render; self.temp.cleanup()

    def test_kinds_and_download_types(self):
        for name in ('a.docx', 'b.XLSX', 'c.pptx'): self.assertEqual(server._output_kind(name), 'office')
        self.assertEqual(server._output_kind('d.doc'), 'file')
        self.assertIn('wordprocessingml', server.OFFICE_TYPES['.docx'])

    def test_pictures_are_made_once_and_again_only_when_the_file_changes(self):
        self.assertEqual(server.office_preview(self.store, str(self.doc))['status'], 'working')
        ready = wait_ready(self.store, str(self.doc))
        self.assertEqual((ready['status'], ready['pages']), ('ready', 3))
        self.assertEqual([server.preview_page(self.store, str(self.doc), n)[-2:] for n in (1, 2, 3)], [PNG[-1:] + b'1', PNG[-1:] + b'2', b'10'])
        self.assertIsNone(server.preview_page(self.store, str(self.doc), 4)); self.assertIsNone(server.preview_page(self.store, str(self.doc), '../done.json'))
        self.assertEqual(wait_ready(self.store, str(self.doc))['version'], ready['version']); self.assertEqual(len(self.made), 1)  # cached
        self.assertEqual(self.made[0], b'PK first')  # made from a private copy of the file
        self.doc.write_bytes(b'PK second version'); os.utime(str(self.doc), (time.time() + 5, time.time() + 5))
        again = wait_ready(self.store, str(self.doc))
        self.assertNotEqual(again['version'], ready['version']); self.assertEqual(self.made[-1], b'PK second version')
        self.assertEqual(sorted(os.listdir(str(self.store.dir / 'previews'))), [again['version']])  # the old pictures are gone, no work folder left

    def test_same_size_and_time_rewritten_still_counts_as_changed(self):
        first = wait_ready(self.store, str(self.doc))['version']; when = os.stat(str(self.doc))
        time.sleep(0.05); self.doc.write_bytes(b'PK other'); os.utime(str(self.doc), ns=(when.st_atime_ns, when.st_mtime_ns))
        self.assertNotEqual(wait_ready(self.store, str(self.doc))['version'], first); self.assertEqual(len(self.made), 2)

    def test_a_note_says_what_the_pictures_leave_out(self):
        server.office_render = lambda source, out: (os.makedirs(out) or Path(out, '1.png').write_bytes(PNG) and [os.path.join(out, '1.png')], '有幾頁沒有轉出預覽圖', 1)
        self.assertEqual(wait_ready(self.store, str(self.doc))['note'], '有幾頁沒有轉出預覽圖')

    def test_clearing_never_reaches_through_links(self):
        version = wait_ready(self.store, str(self.doc))['version']
        outside = self.root / 'outside'; (outside / 'keep').mkdir(parents=True); (outside / 'keep/a.txt').write_text('keep')
        (self.store.dir / 'previews' / version / 'link').symlink_to(outside / 'keep')
        self.doc.unlink(); server.sweep_previews(self.store, force=True)
        self.assertEqual((outside / 'keep/a.txt').read_text(), 'keep'); self.assertEqual(os.listdir(str(self.store.dir / 'previews')), [])
        moved = self.root / 'moved'; (self.store.dir / 'previews').rename(moved); (self.store.dir / 'previews').symlink_to(outside)
        self.assertEqual(server._remove_preview(self.store, 'keep'), 0); self.assertTrue((outside / 'keep/a.txt').exists())

    def test_a_broken_failure_record_is_tried_again(self):
        def broken(source, out): raise RuntimeError('壞了')
        server.office_render = broken; wait_ready(self.store, str(self.doc))
        key = server._preview_key(str(self.doc), os.stat(str(self.doc))); record = self.store.dir / 'previews' / key / 'failed.json'
        for at in ([1], float('inf'), 'x', 10 ** 400):
            record.write_text(json.dumps(dict(reason='舊的', path=str(self.doc), at=at)))
            self.assertNotEqual(server.office_preview(self.store, str(self.doc)).get('reason'), '舊的')
            wait_ready(self.store, str(self.doc))

    def test_long_files_picture_only_the_first_pages(self):
        calls = []
        import importlib.util as iu
        spec2 = iu.spec_from_file_location('zook_pics_cap', ROOT / 'backend/pagepics.py'); pics = iu.module_from_spec(spec2); spec2.loader.exec_module(pics)
        deck = self.root / 'd.pptx'
        import zipfile
        with zipfile.ZipFile(str(deck), 'w') as z:
            z.writestr('ppt/presentation.xml', '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst>' + ''.join('<p:sldId id="%d"/>' % (256 + n) for n in range(5)) + '</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>')
        def fake(path, folder, width=1600):
            calls.append(path); made = os.path.join(folder, os.path.basename(path) + '.png'); Path(made).write_bytes(PNG); return made
        pics.quicklook = fake; out = self.root / 'pics'
        import io, contextlib
        said = io.StringIO()
        with contextlib.redirect_stdout(said): pics.main(['pagepics.py', str(deck), str(out), '--pages', '2'])
        self.assertEqual(len(calls), 2); self.assertIn('共 5 頁，只轉了前 2 頁', said.getvalue())

    def test_a_planted_cache_link_shows_nothing(self):
        key = server._preview_key(str(self.doc), os.stat(str(self.doc))); outside = self.root / 'outside'; outside.mkdir()
        (outside / '1.png').write_bytes(b'secret'); (outside / 'done.json').write_text(json.dumps(dict(pages=1, total=1, path=str(self.doc))))
        (self.store.dir / 'previews').mkdir(); (self.store.dir / 'previews' / key).symlink_to(outside)
        self.assertIsNone(server._preview_json(self.store, key, 'done.json')); self.assertIsNone(server.preview_page(self.store, str(self.doc), 1))

    def test_a_file_that_unpacks_huge_is_not_pictured(self):
        import zipfile
        with zipfile.ZipFile(str(self.doc), 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('big.xml', b'0' * (server.PREVIEW_UNPACKED + 1))
        state = wait_ready(self.store, str(self.doc), seconds=60)
        self.assertEqual(state['status'], 'failed'); self.assertIn('太大', state['reason']); self.assertEqual(self.made, [])

    def test_only_a_few_files_wait_at_once(self):
        with server._preview_lock: server._preview_running.update({'a', 'b', 'c'})
        try: self.assertIn('過一會兒', server.office_preview(self.store, str(self.doc))['reason'])
        finally:
            with server._preview_lock: server._preview_running.difference_update({'a', 'b', 'c'})

    def test_a_deleted_file_takes_its_pictures_with_it(self):
        version = wait_ready(self.store, str(self.doc))['version']
        self.assertTrue((self.store.dir / 'previews' / version / '1.png').exists())
        self.doc.unlink(); server.sweep_previews(self.store, force=True)
        self.assertEqual(os.listdir(str(self.store.dir / 'previews')), [])

    def test_a_failure_says_why(self):
        def broken(source, out): raise RuntimeError('這份檔案沒辦法轉成預覽圖')
        server.office_render = broken
        state = wait_ready(self.store, str(self.doc))
        self.assertEqual(state, dict(status='failed', reason='這份檔案沒辦法轉成預覽圖'))

    def test_links_hard_links_and_other_types_are_refused(self):
        secret = self.root / 'secret.docx'; secret.write_bytes(b'PK secret')
        link = self.root / 'link.docx'; link.symlink_to(secret)
        with self.assertRaises(OSError): server.office_preview(self.store, str(link))
        os.link(str(secret), str(self.root / 'hard.docx'))
        with self.assertRaises(OSError): server.office_preview(self.store, str(self.root / 'hard.docx'))
        (self.root / 'notes.txt').write_text('x')
        with self.assertRaises(OSError): server.office_preview(self.store, str(self.root / 'notes.txt'))
        folder = self.root / 'real'; folder.mkdir(); (folder / 'a.docx').write_bytes(b'PK'); (self.root / 'alias').symlink_to(folder)
        with self.assertRaises(OSError): server.office_preview(self.store, str(self.root / 'alias/a.docx'), strict=True)  # 產出: only its real place
        self.assertEqual(self.made, [])

    def test_too_big_is_explained_without_trying(self):
        with open(str(self.doc), 'wb') as f: f.truncate(server.MAX_UPLOAD + 1)
        state = server.office_preview(self.store, str(self.doc))
        self.assertEqual(state['status'], 'failed'); self.assertIn('20 MB', state['reason']); self.assertEqual(self.made, [])

    @unittest.skipUnless(os.path.exists('/usr/bin/qlmanage') and os.path.exists('/usr/bin/textutil') and not os.environ.get('CI'), 'needs this Mac\'s Quick Look')
    def test_real_word_file_gets_every_page(self):
        server.office_render = self.real_render
        text = self.root / 'long.txt'; text.write_text('\n\n'.join('第 %d 段：測試文字，用來產生好幾頁。' % n * 4 for n in range(300)), encoding='utf-8')
        subprocess.run(['/usr/bin/textutil', '-convert', 'docx', str(text), '-output', str(self.doc)], check=True)
        state = wait_ready(self.store, str(self.doc), seconds=120)
        self.assertEqual(state['status'], 'ready'); self.assertGreater(state['pages'], 1)
        self.assertTrue(server.preview_page(self.store, str(self.doc), 2).startswith(b'\x89PNG'))


class OfficePreviewRoutes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name)); (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x')
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), HOME=str(self.root), PATH='/usr/bin:/bin')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'Maker', 'provider': 'codex'})[1]; self.work = self.root / 'data/workspaces' / self.bot['id']; self.work.mkdir(parents=True, exist_ok=True)

    def tearDown(self): self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None, raw=False):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); kind = resp.getheader('Content-Type'); conn.close()
        return (resp.status, data, kind) if raw else (resp.status, json.loads(data))

    def made_before(self, path, pages=2):
        """Pictures already in the cache, as if Quick Look had made them: the server must not need it."""
        folder = self.root / 'data/previews' / server._preview_key(str(path), os.stat(str(path))); folder.mkdir(parents=True)
        for n in range(1, pages + 1): (folder / ('%d.png' % n)).write_bytes(PNG)
        (folder / 'done.json').write_text(json.dumps(dict(pages=pages, total=pages, path=str(path))))
        return folder

    def test_outputs_preview_and_download(self):
        deck = self.work / '提案.pptx'; deck.write_bytes(b'PK deck'); self.made_before(deck, 3)
        item = next(o for o in self.req('GET', '/api/bots/%s/outputs' % self.bot['id'])[1]['outputs'] if o['name'] == '提案.pptx')
        self.assertEqual(item['kind'], 'office')
        base = '/api/bots/%s/outputs/%s' % (self.bot['id'], item['id'])
        state = self.req('GET', base + '/pages')[1]
        self.assertEqual((state['status'], state['pages']), ('ready', 3))
        status, data, kind = self.req('GET', base + '/pages/2', raw=True)
        self.assertEqual((status, kind, data), (200, 'image/png', PNG))
        self.assertEqual(self.req('GET', base + '/pages/9', raw=True)[0], 404)
        self.assertIn('presentationml', self.req('GET', base, raw=True)[2])  # #201: downloads as what it is
        self.assertEqual(self.req('GET', '/api/bots/%s/outputs/%s/pages' % (self.bot['id'], '0' * 20), raw=True)[0], 404)  # nothing outside the listed outputs

    def test_group_file_preview_and_delete_clears_pictures(self):
        other = self.req('POST', '/api/bots', {'name': 'Other', 'provider': 'codex'})[1]
        group = self.req('POST', '/api/groups', {'name': 'G', 'botIds': [self.bot['id'], other['id']]})[1]
        shared = self.root / 'data/group-files' / group['id']; shared.mkdir(parents=True, exist_ok=True)
        sheet = shared / '報價.xlsx'; sheet.write_bytes(b'PK sheet'); folder = self.made_before(sheet, 1)
        listed = self.req('GET', '/api/groups/%s/files' % group['id'])[1]['files']
        self.assertEqual([f['kind'] for f in listed], ['office'])
        base = '/api/groups/%s/files/%s' % (group['id'], '%E5%A0%B1%E5%83%B9.xlsx')
        self.assertEqual(self.req('GET', base + '/pages')[1]['status'], 'ready')
        self.assertEqual(self.req('GET', base + '/pages/1', raw=True)[1], PNG)
        self.assertIn('spreadsheetml', self.req('GET', base, raw=True)[2])
        self.assertEqual(self.req('GET', '/api/groups/%s/files/%s/pages' % (group['id'], 'nope.xlsx'), raw=True)[0], 404)
        self.assertEqual(self.req('DELETE', base)[0], 200)
        for _ in range(100):
            if not folder.exists(): break
            time.sleep(0.05)
        self.assertFalse(folder.exists())

    def test_a_linked_group_folder_shows_nothing(self):
        other = self.req('POST', '/api/bots', {'name': 'Other', 'provider': 'codex'})[1]
        group = self.req('POST', '/api/groups', {'name': 'G', 'botIds': [self.bot['id'], other['id']]})[1]
        elsewhere = self.root / 'private'; elsewhere.mkdir(); secret = elsewhere / '機密.docx'; secret.write_bytes(b'PK secret')
        shared = self.root / 'data/group-files' / group['id']; shutil.rmtree(str(shared), ignore_errors=True); shared.parent.mkdir(parents=True, exist_ok=True); shared.symlink_to(elsewhere)
        page = '/api/groups/%s/files/%s/pages' % (group['id'], '%E6%A9%9F%E5%AF%86.docx')
        self.assertEqual(self.req('GET', page, raw=True)[0], 404)
        shared.unlink(); (elsewhere / group['id']).mkdir(); os.replace(str(secret), str(elsewhere / group['id'] / '機密.docx'))
        shutil.rmtree(str(shared.parent)); shared.parent.symlink_to(elsewhere)  # the whole group-files folder is a link
        self.assertEqual(self.req('GET', page, raw=True)[0], 404)
        self.assertFalse((self.root / 'data/previews').exists() and os.listdir(str(self.root / 'data/previews')))


class OfficePreviewWindow(unittest.TestCase):
    def test_preview_window_shows_pages_and_no_local_path(self):
        outputs = (JS / '36-outputs.js').read_text(encoding='utf-8'); files = (JS / '36b-files.js').read_text(encoding='utf-8'); groups = (JS / '35-groups.js').read_text(encoding='utf-8')
        self.assertIn('正在產生預覽…', outputs)
        self.assertNotIn('esc(o.path)}</p>', outputs)  # #70④: no full path at the bottom of the window
        self.assertIn("kind === 'office'", files)  # group files open the same page preview
        self.assertIn("'office'", groups)
        self.assertIn('o.size > 20 * 1048576', outputs)  # over 20 MB the download link would fail: Finder only


if __name__ == '__main__': unittest.main()
