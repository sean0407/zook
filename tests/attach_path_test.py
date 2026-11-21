# -*- coding: utf-8 -*-
"""附上 from a typed path: only after the user clicks, only plain files in the user's own folders."""
import importlib.util, os, subprocess, sys, tempfile, unicodedata, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_attach_path', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)


class AttachPath(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(os.path.realpath(self.temp.name)) / 'home'; self.home.mkdir()
        self.old = os.environ.get('HOME'); os.environ['HOME'] = str(self.home)
        self.store = m.Store(self.home / 'Library' / 'Application Support' / 'zook'); m._active['data'] = self.store.data

    def tearDown(self):
        os.environ['HOME'] = self.old; self.temp.cleanup()

    def test_a_plain_file_in_the_users_folders(self):
        f = self.home / 'Documents' / '新品資料.txt'; f.parent.mkdir(); f.write_text('售價 520')
        meta = m.upload_from_path(self.store, str(f))
        self.assertEqual((meta['name'], meta['size']), ('新品資料.txt', len('售價 520'.encode())))
        self.assertEqual((self.store.dir / 'uploads' / meta['id'] / 'file').read_text(), '售價 520')

    def test_what_is_refused(self):
        def made(rel, text='x'):
            p = self.home / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p
        cases = [made('.ssh/id.txt'), made('Documents/.env.txt'), made('Library/Keychains/k.db'), made('library/cookies/c.txt'),
                 self.store.dir / 'swarmr.json', Path('/etc/hosts'), made('Documents/empty.txt', ''), self.home / 'missing.txt', self.home / 'Documents']
        link = self.home / 'Documents' / 'link.txt'; link.symlink_to(made('Library/Mail/m.txt'))
        hard = self.home / 'Documents' / 'hard.txt'; os.link(str(made('Documents/orig.txt')), str(hard))
        inner = self.home / 'Documents' / 'ok.txt'; inner.write_text('x')
        alias = self.home / 'Documents' / 'alias.txt'; alias.symlink_to(inner)  # a link to an allowed file is still a link
        folder_link = self.home / 'Shortcut'; folder_link.symlink_to(self.home / 'Documents')
        cases += [alias, folder_link / 'ok.txt', made('Documents/zook-sync-abc.json'), made('Documents/ZOOK-SYNC-abc.json'), Path(str(inner).upper())]
        cases.append(str(folder_link) + '/../Documents/ok.txt')  # .. could hide a link it steps back over
        accent = self.home / 'Café'; accent.mkdir(); self.store.data['sync'] = {'folder': unicodedata.normalize('NFD', str(accent))}; (accent / 'n.txt').write_text('x')
        cases.append(unicodedata.normalize('NFC', str(accent / 'n.txt')))  # the same folder written the other Unicode way
        flagged = self.home / 'Hidden'; flagged.mkdir(); (flagged / 'f.txt').write_text('x'); subprocess.run(['chflags', 'hidden', str(flagged)], check=True)
        cases.append(flagged / 'f.txt')
        for path in cases + [link, hard, 'relative.txt', '/x\x00y']:
            with self.subTest(path=str(path)), self.assertRaises(ValueError): m.upload_from_path(self.store, str(path))
        self.store.data['sync'] = {}
        self.assertEqual(list((self.store.dir / 'uploads').glob('*')) if (self.store.dir / 'uploads').exists() else [], [])  # nothing half-copied is left


    def test_the_task_host_is_told_where_the_copies_are(self):
        group = dict(id='g', name='團隊', botIds=[], messages=[dict(id='m', role='user', content='資料在 /tmp/a.txt', attachments=[dict(id='a' * 32, name='a.txt')])])
        text = m.task_transcript(self.store, group, bot_id='h' * 32)
        self.assertIn(str(self.store.dir / 'workspaces' / ('h' * 32) / 'attachments' / ('a' * 8 + '-a.txt')), text)


if __name__ == '__main__': unittest.main()
