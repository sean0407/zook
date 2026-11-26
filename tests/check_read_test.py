# -*- coding: utf-8 -*-
"""#240 查核讀檔 (併 #47、#64、#78、#178、#311、#149、#49、#273): Excel, Word, PowerPoint and PDF files a group shares get a text
version a checker or host can read when the file itself cannot be opened (a PDF also its page count and pictures of its first pages);
a check that cannot read the files says 「無法查核（讀不到檔案）」 instead of failing the work; 請其他成員查核 never asks a member who
handed in files in that ask, prefers the group's own checker, and says so when nobody is left."""
import importlib.util, json, os, sys, tempfile, time, unittest, zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_check_read', SERVER); server = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(server)


def make_xlsx(path):
    with zipfile.ZipFile(str(path), 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="報價" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>安裝數量</t></si><si><t>小計</t></si></sst>')
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                   '<row r="9"><c r="A9" t="s"><v>0</v></c><c r="C9"><v>70</v></c></row>'
                   '<row r="10"><c r="A10" t="s"><v>1</v></c><c r="C10"><f>C9*2</f><v>140</v></c><c r="D10"><f>SUM(C9:C10)</f></c></row></sheetData></worksheet>')


def make_pptx(path):
    with zipfile.ZipFile(str(path), 'w') as z:
        z.writestr('ppt/slides/slide1.xml', '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>到職第一天</a:t></a:r></a:p></p:sld>')


class TextVersions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = server.Store(Path(self.tmp.name) / 'data')
        self.store.data['groups'] = [dict(id='g1', name='G', botIds=['b1'], messages=[], fileInfo={})]
        self.shared = server.group_files_dir(self.store, 'g1'); self.shared.mkdir(parents=True)
        self.texts = server.group_copy_folder(self.store, 'b1') / server.GROUP_TEXT_FOLDER

    def tearDown(self): self.tmp.cleanup()

    def turn(self, bot='b1', skip=()):
        seen = server.sync_group_files_in(self.store, 'g1', bot, skip)
        return seen, server.group_text_in(self.store, 'g1', bot, seen)

    def test_excel_text_keeps_cells_and_formulas_and_is_never_a_shared_file(self):
        make_xlsx(self.shared / '報價單.xlsx'); (self.shared / 'notes.txt').write_text('x')
        seen, made = self.turn()
        text = (self.texts / '報價單.xlsx.txt').read_text(encoding='utf-8')
        for want in ('【工作表 報價】', 'A9：安裝數量', 'C9：70', 'C10：140（公式 =C9*2）', 'D10：（公式 =SUM(C9:C10)，沒有存計算結果）'): self.assertIn(want, text)
        self.assertEqual(made, ['報價單.xlsx'])  # a plain text file needs none
        saved, skipped = server.sync_group_files_out(self.store, 'g1', 'B1', 'b1', seen)
        self.assertEqual((saved, skipped), ([], []))  # the text versions are Zook's, never brought back as the member's work
        self.assertEqual(sorted(e.name for e in server._plain_files(self.shared)), ['notes.txt', '報價單.xlsx'])
        self.assertFalse(list(self.shared.rglob('*.txt.txt')))

    def test_a_text_version_is_made_once_per_version_and_hidden_files_get_none(self):
        make_xlsx(self.shared / 'a.xlsx'); make_pptx(self.shared / '簡報.pptx')
        calls = []
        real = server.group_text_extract
        with mock.patch.object(server, 'group_text_extract', side_effect=lambda *a: calls.append(a[0].name) or real(*a)):
            self.turn(); self.turn(); self.turn(skip={'a.xlsx'})
        self.assertEqual(len(calls), 2)
        self.assertEqual(sorted(p.name for p in self.texts.iterdir()), ['簡報.pptx.txt'])  # a file hidden from this turn has no text version either
        self.assertIn('到職第一天', (self.texts / '簡報.pptx.txt').read_text(encoding='utf-8'))

    def test_a_pdf_says_its_pages_and_gets_pictures(self):
        (self.shared / '規格書.pdf').write_bytes(b'%PDF-1.4 big')
        def pictures(path, out):
            for n in (1, 2): (Path(out) / ('p-%02d.png' % n)).write_bytes(b'png')
        with mock.patch.object(server, 'group_text_pdf', return_value=(5, '【第 1 頁】\n規格一\n【第 2 頁】\n規格二')), mock.patch.object(server, 'group_text_pictures', side_effect=pictures):
            self.turn()
        text = (self.texts / '規格書.pdf.txt').read_text(encoding='utf-8')
        self.assertIn('共 5 頁', text); self.assertIn('規格二', text); self.assertIn('規格書.pdf-第01頁.png', text)
        self.assertEqual(sorted(p.name for p in self.texts.iterdir()), ['規格書.pdf-第01頁.png', '規格書.pdf-第02頁.png', '規格書.pdf.txt'])

    def test_a_file_zook_cannot_read_says_so(self):
        (self.shared / '壞掉.xlsx').write_bytes(b'not a zip')
        self.turn()
        text = (self.texts / '壞掉.xlsx.txt').read_text(encoding='utf-8')
        self.assertIn('Zook 讀不到', text); self.assertIn('無法查核（讀不到檔案）', text)

    def test_group_file_tool_gives_the_text_version_of_an_office_file(self):
        make_xlsx(self.shared / '報價單.xlsx')
        read = server.group_file_tool(self.store, 'g1', server.runtime_module())[1]
        out = read({'name': '報價單.xlsx'})
        self.assertIn('C9：70', out['content']); self.assertIn('文字版', out.get('note', ''))

    def test_read_only_antigravity_gets_the_text_versions(self):
        make_xlsx(self.shared / '報價單.xlsx')
        with mock.patch.object(tempfile, 'tempdir', os.path.realpath(self.tmp.name)):
            self.turn()
            rules, note, _ = server.agy_read_paths(self.store, 'b1', dict(id='j1', groupFiles=True, groupId='g1'))
            self.assertTrue([r for r in rules if r.endswith('報價單.xlsx.txt')], rules); self.assertIn('報價單.xlsx.txt', note)
            server.agy_cleanup(self.store, 'b1', 'j1', True)

    def test_the_prompt_says_where_the_text_versions_are(self):
        make_xlsx(self.shared / '報價單.xlsx')
        note = server.group_text_note(self.store, 'b1', ['報價單.xlsx', 'a.txt'])
        self.assertIn(str(self.texts), note); self.assertIn('無法查核', note)
        self.assertEqual(server.group_text_note(self.store, 'b1', ['a.txt']), '')

    def test_a_deleted_groups_text_versions_go(self):
        make_xlsx(self.shared / '報價單.xlsx'); self.turn()
        self.assertTrue((self.store.dir / 'group-text' / 'g1').is_dir())
        server.drop_group_files(self.store, None, self.store.data['groups'][0]).join(5)
        self.assertFalse((self.store.dir / 'group-text' / 'g1').exists())


class Verdicts(unittest.TestCase):
    def test_a_check_that_could_not_read_the_files(self):
        self.assertEqual(server.group_verdict('【判定】無法查核\n報價單.xlsx 打不開'), '無法查核')
        for rule in (server.MODERATOR_RULES['verify'][0], server.MODERATOR_RULES['split_check'][1]): self.assertIn('【判定】無法查核', rule)
        self.assertIn('讀不到', ''.join(server.MODERATOR_RULES['split_merge']))


class Picking(unittest.TestCase):
    """請其他成員查核 (#149, #49①, #273③)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = server.Store(Path(self.tmp.name) / 'data')
        self.store.data['bots'] = [dict(id=i, name=n, provider=p) for i, n, p in (('host', '主持', 'claude'), ('maker', '報價專員', 'codex'), ('qa', '查核員', 'codex'), ('other', '企劃', 'codex'))]
        self.patch = mock.patch.object(server, 'find_cli', return_value='/bin/true'); self.patch.start()

    def tearDown(self): self.patch.stop(); self.tmp.cleanup()

    def group(self, ids, **fields):
        messages = [dict(id='u1', role='user', content='做報價單'), dict(id='m1', role='assistant', botId='maker', content='已存好報價單.xlsx', status='completed', savedFiles=['報價單.xlsx']),
                    dict(id='m2', role='assistant', botId='host', content='【結論】報價單.xlsx 完成', status='completed')]
        group = dict(id='g1', name='G', botIds=ids, hostId='host', messages=messages, fileInfo={'報價單.xlsx': dict(by='報價專員', byId='maker')}, **fields)
        self.store.data['groups'] = [group]; return group

    def test_who_handed_in_files_is_never_asked(self):
        group = self.group(['host', 'maker', 'other'], checkMode='none')
        self.assertEqual(server.group_verifier(self.store, group, group['messages'][2])[0], 'other')

    def test_the_groups_checker_comes_first(self):
        group = self.group(['host', 'maker', 'other', 'qa'], checkMode='pick', checkerId='qa')
        pick = server.group_verifier(self.store, group, group['messages'][2])
        self.assertEqual(pick[0], 'qa')
        legacy = self.group(['host', 'maker', 'other', 'qa'])  # from before 驗收方式: the checker by its name
        self.assertEqual(server.group_verifier(self.store, legacy, legacy['messages'][2])[0], 'qa')

    def test_nobody_left_is_said(self):
        group = self.group(['host', 'maker'], checkMode='auto')
        self.assertIsNone(server.group_verifier(self.store, group, group['messages'][2]))
        why = server.verifier_missing(self.store, group, group['messages'][2])
        self.assertIn('報價專員', why); self.assertIn('沒有其他成員可以查核', why)

    def test_a_maker_of_a_file_the_reply_names_is_not_asked_in_a_later_ask(self):
        group = self.group(['host', 'maker', 'other'], checkMode='none')
        group['messages'] += [dict(id='u2', role='user', content='再確認一次'), dict(id='m3', role='assistant', botId='host', content='報價單.xlsx 沒問題', status='completed')]
        self.assertEqual(server.group_verifier(self.store, group, group['messages'][4])[0], 'other')


import task_engine_test as base
from task_engine_test import PLAN, WAKE, SUMMARY, create, done


class TaskUnreadable(base.TaskEngineTest):
    """任務引擎: a checker that could not read the work does not send it back to be redone; it waits for the user."""
    for _name in [n for n in dir(base.TaskEngineTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_unreadable_waits_for_the_user_instead_of_failing(self):
        codex = self.req('POST', '/api/bots', {'name': '丁', 'provider': 'codex'})[1]
        self.group = self.req('POST', '/api/groups', {'name': '混合', 'botIds': [self.bots['主持']['id'], self.bots['甲']['id'], codex['id']], 'hostId': self.bots['主持']['id']})[1]
        self.engine(); self.autoaccept = False
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': '=== 要驗收的工作', 'calls': [{'name': 'zook_task_verdict', 'arguments': {'result': 'unreadable', 'reasons': '報價單.xlsx 打不開'}}]},
                    {'match': '=== 工作 1', 'calls': [done('列好了。')]}, {'match': WAKE, 'reply': SUMMARY}])
        self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '做事', 'mode': 'auto'})
        end, task = time.time() + 30, {}
        while time.time() < end:
            group = self.req('GET', '/api/groups/' + self.group['id'])[1]['group']; run = group.get('taskRun') or {}
            if run.get('awaitingConfirm'): self.confirm(group)
            task = (run.get('tasks') or [{}])[0]
            if task.get('status') == 'review': break
            time.sleep(0.1)
        self.assertEqual((task.get('status'), task.get('failures'), len(task.get('attempts') or [])), ('review', 0, 1))  # not redone
        self.assertIn('無法查核（讀不到檔案）', task['note']); self.assertEqual(task['verify']['verdict'], 'unreadable')


if __name__ == '__main__': unittest.main()
