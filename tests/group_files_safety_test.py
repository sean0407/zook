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
