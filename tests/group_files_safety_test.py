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


if __name__ == '__main__': unittest.main()
