# -*- coding: utf-8 -*-
import importlib.util, os, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_safety', SERVER); server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)


class Store:
    def __init__(self, root): self.dir = Path(root)


class GroupFileSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name)); self.store = Store(self.root / 'data')
        self.shared = server.group_files_dir(self.store, 'g1'); self.shared.mkdir(parents=True); (self.shared / 'keep.txt').write_text('keep')
        self.bot = self.store.dir / 'workspaces/b1'; self.bot.mkdir(parents=True)

    def tearDown(self): self.temp.cleanup()

    def test_a_planted_attachments_link_cannot_erase_group_files(self):
        (self.bot / 'attachments').symlink_to(self.store.dir)
        server.sync_group_files_in(self.store, 'g1', 'b1')
        self.assertEqual((self.shared / 'keep.txt').read_text(), 'keep'); self.assertFalse((self.bot / 'attachments').is_symlink())

    def test_things_planted_in_place_of_folders_are_replaced(self):
        for make in (lambda p: p.write_text('x'), lambda p: os.mkfifo(str(p)), lambda p: p.symlink_to(self.root / 'missing')):
            target = self.bot / 'attachments'
            if target.is_dir() and not target.is_symlink(): server.shutil.rmtree(str(target))
            elif os.path.lexists(str(target)): target.unlink()
            make(target); self.assertEqual(list(server.sync_group_files_in(self.store, 'g1', 'b1')), ['keep.txt'])
            self.assertEqual((target / 'group-files/keep.txt').read_text(), 'keep')

    def test_attachments_never_follow_a_planted_link(self):
        outside = self.root / 'outside'; outside.mkdir(); upload = self.store.dir / 'uploads/aaaaaaaa11'; upload.mkdir(parents=True); (upload / 'file').write_text('private')
        item = dict(id='aaaaaaaa11', name='r.txt'); (self.bot / 'attachments').symlink_to(outside)
        server.place_attachments(self.store, 'b1', [item]); self.assertEqual(list(outside.iterdir()), [])
        link = self.bot / 'attachments/aaaaaaaa-r.txt'; link.unlink(); link.symlink_to(outside / 'made.txt')
        server.place_attachments(self.store, 'b1', [item]); self.assertFalse((outside / 'made.txt').exists()); self.assertEqual(link.read_text(), 'private')

    def test_a_subfolder_does_not_stop_the_other_files_coming_back(self):
        seen = server.sync_group_files_in(self.store, 'g1', 'b1'); copy = server.group_copy_folder(self.store, 'b1')
        (copy / 'a.txt').write_text('a'); (copy / 'drafts').mkdir(); (copy / 'z.txt').write_text('z')
        self.assertEqual(server.sync_group_files_out(self.store, 'g1', 'B', 'b1', seen)[0], ['a.txt', 'z.txt'])

    def test_lock_and_temporary_files_are_not_shared(self):
        """巡檢 #25: PowerPoint's ~$ lock file showed up as a group file with download and 「請其他成員查核」."""
        seen = server.sync_group_files_in(self.store, 'g1', 'b1'); copy = server.group_copy_folder(self.store, 'b1')
        for name in ('提案.pptx', '~$提案.pptx', '.~lock.提案.odp#', 'draft.TMP', '.DS_Store', 'Thumbs.db'): (copy / name).write_text('x')
        self.assertEqual(server.sync_group_files_out(self.store, 'g1', 'B', 'b1', seen)[0], ['提案.pptx'])
        (self.shared / '~$keep.txt').write_text('lock')  # one already there from before is not listed either
        self.assertEqual([e.name for e in server._plain_files(self.shared)], ['keep.txt', '提案.pptx'])

    def test_an_upload_that_would_be_hidden_is_refused(self):
        """An uploaded capture.tmp was stored, listed nowhere, and could not be downloaded or deleted."""
        group = dict(id='g1')
        for name in ('capture.tmp', '~$提案.pptx', 'Thumbs.db', 'page.crdownload'):
            temp = self.root / 'upload'; temp.write_bytes(b'data')
            with self.assertRaises(ValueError) as caught: server.add_group_file(self.store, group, name, temp, 4, '你')
            self.assertIn('改檔名', str(caught.exception)); self.assertTrue(temp.exists())
        self.assertEqual(sorted(p.name for p in self.shared.iterdir()), ['keep.txt'])
        temp = self.root / 'upload'; self.assertEqual(server.add_group_file(self.store, group, 'capture.txt', temp, 4, '你'), 'capture.txt')
        self.assertEqual([f['name'] for f in server.list_group_files(self.store, group)], ['capture.txt', 'keep.txt'])

    def test_hidden_answers_are_not_copied_to_later_members(self):
        (self.shared / 'other.txt').write_text('answer')
        self.assertEqual(list(server.sync_group_files_in(self.store, 'g1', 'b1', {'other.txt'})), ['keep.txt'])
        self.assertFalse((server.group_copy_folder(self.store, 'b1') / 'other.txt').exists())

    def test_a_planted_folder_link_brings_nothing_back(self):
        secret = self.root / 'private'; secret.mkdir(); (secret / 'id_rsa').write_text('secret')
        seen = server.sync_group_files_in(self.store, 'g1', 'b1'); folder = server.group_copy_folder(self.store, 'b1')
        for item in folder.iterdir(): item.unlink()
        folder.rmdir(); folder.symlink_to(secret)
        self.assertEqual(server.sync_group_files_out(self.store, 'g1', 'B', 'b1', seen), ([], [])); self.assertFalse((self.shared / 'id_rsa').exists())

    def test_a_planted_parent_link_brings_nothing_back(self):
        secret = self.root / 'private/group-files'; secret.mkdir(parents=True); (secret / 'id_rsa').write_text('secret')
        seen = server.sync_group_files_in(self.store, 'g1', 'b1'); parent = self.bot / 'attachments'
        server.shutil.rmtree(str(parent)); parent.symlink_to(secret.parent)
        self.assertEqual(server.sync_group_files_out(self.store, 'g1', 'B', 'b1', seen), ([], []))

    def test_a_file_link_inside_the_copy_is_ignored(self):
        secret = self.root / 'secret.txt'; secret.write_text('secret')
        seen = server.sync_group_files_in(self.store, 'g1', 'b1'); (server.group_copy_folder(self.store, 'b1') / 'leak.txt').symlink_to(secret)
        self.assertEqual(server.sync_group_files_out(self.store, 'g1', 'B', 'b1', seen)[0], []); self.assertFalse((self.shared / 'leak.txt').exists())

    def test_changes_come_back_and_conflicts_keep_both(self):
        seen = server.sync_group_files_in(self.store, 'g1', 'b1'); copy = server.group_copy_folder(self.store, 'b1')
        (copy / 'keep.txt').write_text('mine'); (copy / 'new.txt').write_text('new'); (self.shared / 'keep.txt').write_text('theirs')
        saved = server.sync_group_files_out(self.store, 'g1', 'Beta', 'b1', seen)[0]
        self.assertEqual(sorted(saved), ['keep（Beta）.txt', 'new.txt']); self.assertEqual((self.shared / 'keep.txt').read_text(), 'theirs')

    def test_long_names_keep_their_extension_and_never_crash(self):
        name = 'x' * 200 + '.pdf'; first = server.free_group_file_name(self.shared, name); self.assertTrue(first.endswith('.pdf')); self.assertLessEqual(len(first), 120)
        (self.shared / first).write_text('a'); second = server.free_group_file_name(self.shared, name, 'Beta'); self.assertNotEqual(first, second); self.assertTrue(second.endswith('.pdf'))

    def test_everyone_is_not_a_member_name(self):
        self.assertFalse(server.group_everyone('@全部門助理 看一下', [dict(name='全部門助理')])); self.assertTrue(server.group_everyone('@全部 看一下', [dict(name='全部門助理')]))

    def test_card_keeps_the_text_before_the_summary(self):
        self.assertEqual(server.group_card('完整成果\n【結論】甲')['body'], '完整成果')


    def test_reported_files_are_looked_for_as_zook_saved_them(self):  # #245
        (self.shared / 'ab.xlsx').write_text('x'); (self.shared / '報價單（甲）.xlsx').write_text('x'); (self.shared / '報價單（舊版）.pdf').write_text('x')
        listed = ['a:b.xlsx', '報價單.xlsx', '報價單.pdf', 'README']
        self.assertEqual(server.checked_present(self.store, 'g1', listed, exact=listed, owner='甲'), ['報價單.pdf', 'README'])
        self.assertEqual(server.checked_present(self.store, 'g1', ['keep.txt', 'gone.docx']), ['gone.docx'])
        (self.shared / '提案.pptx').write_text('old'); self.assertEqual(server.checked_present(self.store, 'g1', ['提案（新版）.pptx', '提案.pptx（群組檔案）'], exact=['提案（新版）.pptx']), ['提案（新版）.pptx'])
        (self.shared / '舊版合約.docx').write_text('old'); self.assertEqual(server.checked_present(self.store, 'g1', ['合約.docx']), ['合約.docx'])  # an older file that merely ends the same is not it
        group = dict(id='g1', fileInfo={'報價單（甲）.xlsx': {'by': '甲'}, 'ab.xlsx': {'by': '乙'}})
        self.assertEqual(server.task_files_missing(self.store, group, '甲', dict(files=['報價單.xlsx', 'ab.xlsx']), {}), ['ab.xlsx'])  # another member's file is not its work
        self.assertEqual(server.task_files_missing(self.store, group, '甲', dict(files=['ab.xlsx']), dict(savedFiles=['ab.xlsx'])), [])
        self.assertEqual(server.task_files_missing(self.store, group, '甲', dict(files=[]), dict(skippedFiles=['big.pdf'])), ['big.pdf'])
        self.assertEqual(server.task_files_missing(self.store, group, '甲', dict(files=[], summary='已存好報價單.xlsx，依照需求.pdf'), {}, '讀 /tmp/in/需求.pdf'), ['已存好報價單.xlsx'])  # named in the summary only (the words run together); the input file is not its work
        (self.shared / '報價單.xlsx').write_text('x')
        self.assertEqual(server.task_files_missing(self.store, group, '甲', dict(files=[], summary='已存好報價單.xlsx'), {}), ['已存好報價單.xlsx'])  # someone else's file of that name
        self.assertEqual(server.task_files_missing(self.store, dict(group, fileInfo={'報價單.xlsx': {'by': '甲'}}), '甲', dict(files=[], summary='已存好報價單.xlsx'), {}), [])
        self.assertEqual(server.task_files_missing(self.store, dict(group, fileInfo={'報價單.xlsx': {'by': '甲', 'byId': 'other'}}), '甲', dict(files=['報價單.xlsx']), {}, owner_id='mine'), ['報價單.xlsx'])  # another Bot named 甲
        self.assertEqual(server.task_files_missing(self.store, group, '甲', dict(files=[], summary='已存好新版需求.pdf'), {}, '讀 /tmp/in/需求.pdf'), ['已存好新版需求.pdf'])  # not the input it read
        (self.shared / 'Q3 報價單.xlsx').write_text('q3')
        self.assertEqual(server.task_files_missing(self.store, dict(group, fileInfo={'Q3 報價單.xlsx': {'by': '甲'}}), '甲', dict(files=['Q3 報價單.xlsx'], summary='已存好 Q3 報價單.xlsx'), dict(savedFiles=['Q3 報價單.xlsx'])), [])  # a piece of a whole name it handed over
        self.assertEqual([server.group_is_checker(dict(name=n)) for n in ('查核員', '非查核員', '不負責查核員', 'QA', 'AQAB')], [True, False, False, True, False])
        self.assertEqual([server.group_is_checker(dict(name='甲', persona=x)) for x in ('不只負責查核，也要寫報價。', '主要不負責查核，做報價單。', '你擔任驗收角色。', '負責檢查其他成員的成果。', '主要撰寫驗收報告。', '我是設計師，曾負責驗收舊版，現在製作報價單。', '過去負責查核，現在做報價。', '我是設計師，負責驗收其他成員的成果。')], [True, False, True, True, False, False, False, True])
        self.assertEqual([server.group_is_checker(dict(name=n)) for n in ('品質檢查員', '驗收報告撰寫', '文件審核員', '檢查專員', '品質檢查專員', '品質改善工程師', '品質檢查流程設計師', '驗收工程師', 'QA 工程師')], [True, False, True, True, True, False, False, True, True])
        self.assertEqual(server.verify_again(dict(verify=dict(state='done', need={'a.xlsx': 'h'}))), dict(state='waiting', need={'a.xlsx': 'h'}))
        (self.shared / '新版報價.xlsx').write_text('n'); self.assertEqual(server.task_files_missing(self.store, dict(group, fileInfo={'新版報價.xlsx': {'by': '甲', 'byId': 'mine'}}), '甲', dict(files=['報價.xlsx']), dict(savedFiles=['新版報價.xlsx']), owner_id='mine'), ['報價.xlsx'])  # a longer name is another file

if __name__ == '__main__': unittest.main()
