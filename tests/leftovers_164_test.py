# -*- coding: utf-8 -*-
"""#164 #180 #69: a handed-in file path is never cut in the middle; a deck whose size is named 4:3 but drawn 16:9 is caught;
a checker says plainly when it did not see a deck's pages; a brand's Skill is not put on another brand; light grey text is readable;
特大 text in a 768-wide browser does not scroll sideways."""
import importlib.util, inspect, pathlib, re, sys, tempfile, unittest, zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zook_leftovers_164', ROOT / 'backend/server.py')
m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(ROOT / 'backend')); spec.loader.exec_module(m)
CSS = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PATH = '/Users/someone/Library/Application Support/swarmr/groups/0123456789abcdef/files/人資部/2026 年度/新人到職說明_2026-12.pdf'


def deck(path, size):
    with zipfile.ZipFile(str(path), 'w') as z:
        z.writestr('ppt/presentation.xml', '<?xml version="1.0"?><p:presentation xmlns:p="%s" xmlns:r="%s"><p:sldIdLst/>%s</p:presentation>' % (P, R, size))
        z.writestr('ppt/_rels/presentation.xml.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')


class PathsTest(unittest.TestCase):
    def test_clip_keeps_a_path_whole(self):
        said = '已存好，檔案在 ' + PATH + '，請查看。後面還有一些說明文字' * 3
        for n in range(20, 160, 7):
            short = m.task_clip(said, n)
            if PATH[:5] in short: self.assertIn(PATH, short, n)  # either the whole path or none of it
            self.assertTrue(short.endswith('…'))
        self.assertEqual(m.task_clip('短的', 10), '短的')
        self.assertEqual(m.task_clip('甲' * 50, 10), '甲' * 10 + '…')  # plain words are still cut where asked

    def test_board_and_files_keep_the_extension(self):
        files = m.task_file_names([PATH + '\n', ' ', '/tmp/a.pptx'])
        self.assertEqual(files, [PATH, '/tmp/a.pptx'])
        task = dict(n=1, title='到職說明', assignee='', status='stuck', note='', attempts=[dict(state='reported', outcome='succeeded', summary='做好了，存在 ' + PATH + ' 。共 7 頁', files=files)])
        run = dict(tasks=[task], gates=[], status='running')
        board = m.task_board_text(None, run)
        self.assertIn('新人到職說明_2026-12.pdf', board)
        self.assertNotRegex(board, r'_2026-12\.p(?!df)')
        self.assertIn(PATH, m.task_line(None, task))

    def test_long_path_is_accepted(self):
        self.assertGreater(m.TASK_FILE_CHARS, len(PATH) * 3)  # the old limit was 300 in, 200 kept
        self.assertEqual(m.task_file_names(['x' * 900 + '.pdf']), ['x' * 900 + '.pdf'])

    def test_restored_books_check_each_file(self):
        """A backup's handed-in files are checked one by one: strings, at most 20, each within the limit."""
        book = lambda files: dict(id='r1', status='running', origin='user', hostId='h', tasks=[dict(
            id='t1', n=1, title='到職說明', status='done', assignee='b', spec='做一份到職說明', doneWhen='交出檔案', attempts=[dict(state='reported', files=files)])])
        self.assertTrue(m.task_run_ok(book([PATH])))
        for bad in ([7], [['x']], ['x' * (m.TASK_FILE_CHARS + 1)], ['a.pdf'] * 21):
            self.assertFalse(m.task_run_ok(book(bad)), bad[:1])


class DeckSizeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.dir = pathlib.Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def scan(self, size):
        path = self.dir / 'a.pptx'; deck(path, size); return m.pptx_scan(str(path))

    def test_named_four_three_drawn_wide(self):
        scan = self.scan('<p:sldSz cx="12192000" cy="6858000" type="screen4x3"/>')  # what pptxgenjs writes for 16:9
        self.assertEqual([tuple(x) for x in scan], [m.PPTX_SIZE_WRONG])
        said = m.pptx_render([list(x) for x in scan]); self.assertEqual(len(said), 1); self.assertIn('投影片大小', said[0])
        self.assertIn('sldSz', m.pptx_render([list(x) for x in scan], for_bot=True)[0])

    def test_sound_sizes_say_nothing(self):
        for size in ('<p:sldSz cx="12192000" cy="6858000"/>', '<p:sldSz cx="9144000" cy="6858000" type="screen4x3"/>',
                     '<p:sldSz cx="9144000" cy="5143500" type="screen16x9"/>', '<p:sldSz cx="7772400" cy="10058400" type="letter"/>', '<p:sldSz cx="x" cy="1" type="screen4x3"/>'):
            self.assertEqual(self.scan(size), [], size)

    def test_restored_scan_is_rebuilt_from_numbers(self):
        self.assertEqual(m.pptx_render([[0, 2], [True, 1], ['0', 1]]), [])
        self.assertEqual(len(m.pptx_render([[0, 1], [2, 3]])), 2)


class PromptTest(unittest.TestCase):
    def test_checker_is_told_to_look_at_pages(self):
        rule = m.task_layout_rule(dict(summary='做好了', files=['/tmp/x/到職簡報.pptx']))
        self.assertIn('版面未驗證', rule); self.assertIn('qlmanage', rule); self.assertIn(m.PAGEPICS, rule)
        self.assertIn('版面未驗證', m.task_layout_rule(dict(summary='存成 報告.pdf檔')))
        self.assertEqual(m.task_layout_rule(dict(summary='算好了', files=['/tmp/x/a.xlsx'])), '')
        self.assertIn('版面未驗證', m.task_layout_rule(dict(summary='簡報已做好，共 7 頁', files=['/tmp/x/deck'])))  # no extension said
        self.assertIn('task_layout_rule(attempt)', inspect.getsource(m.task_verify_prompt))

    def test_brand_skill_not_put_on_another_brand(self):
        self.assertIn('品牌', m.SKILL_PICK_NOTE); self.assertIn('不要套', m.SKILL_PICK_NOTE)


def lum(h):
    h = h.lstrip('#'); h = ''.join(c * 2 for c in h) if len(h) == 3 else h
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


class LookTest(unittest.TestCase):
    def rule(self, selector):
        found = re.search(r'(?:^|\n|\})\s*' + re.escape(selector) + r'\s*\{([^}]*)\}', CSS)
        self.assertTrue(found, selector); return found.group(1)

    def test_secondary_text_is_readable(self):
        """#69④: time stamps, empty states, the sidebar's 群組 label, usage reset times: at least 4.5:1 on white."""
        muted = re.search(r'--muted:\s*(#[0-9a-fA-F]{6})', CSS).group(1)
        for selector in ('.date', '.section-head', '.detail-empty', '.blank', '.side-empty', '.system-note', '.quota-reset', '.composer-note', '.speaker', '.ev-where', '.compact-line'):
            color = re.search(r'(?<![-\w])color:\s*([^;\n}]+)', self.rule(selector)).group(1).strip()
            value = muted if color == 'var(--muted)' else color
            self.assertGreaterEqual(1.05 / (lum(value) + .05), 4.5, '%s %s' % (selector, color))

    def test_big_text_fits_a_narrow_browser(self):
        """#69②: 特大 (zoom 1.25) at 768 wide: the 700 minimum is counted before the zoom, so nothing is cut off on the right."""
        self.assertRegex(CSS, r'@media \(min-width: 700px\) \{ html\.zoomed \.layout \{ min-width:calc\(700px / var\(--zoom, 1\)\); \} \}')


if __name__ == '__main__':
    unittest.main()
