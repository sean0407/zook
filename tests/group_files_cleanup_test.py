# -*- coding: utf-8 -*-
"""#213: deleting a group, or a Bot leaving 已刪除的 Bot for good, removes the copies of group files Zook put in Bot workspaces,
and only those. #150/#151: several files at once go in one by one with one summary; a long name keeps its 刪除 button."""
import http.client, json, os, sys, tempfile, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import choices_test

ROOT = Path(__file__).resolve().parents[1]
server = choices_test.origin_test.server if hasattr(choices_test.origin_test, 'server') else None
if server is None:
    import importlib.util
    spec = importlib.util.spec_from_file_location('zook_cleanup', ROOT / 'backend/server.py'); server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)


class Store:
    def __init__(self, root): self.dir = Path(root); self.data = dict(bots=[], deletedBots=[], groups=[], settings={}); self.lock = threading.RLock()
    def find(self, kind, item_id): return next((x for x in self.data[kind] if x.get('id') == item_id), None)


class Holder: pass


class CopyCleanup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name)); self.store = Store(self.root / 'data')
        self.shared = server.group_files_dir(self.store, 'g1'); self.shared.mkdir(parents=True)
        (self.shared / '報告.pdf').write_bytes(b'pdf'); (self.shared / 'notes.txt').write_text('shared')
        self.group = dict(id='g1', botIds=['b1', 'b2'])
        self.store.data['groups'].append(self.group); self.store.data['bots'] += [dict(id='b1'), dict(id='b2')]
        for bot in ('b1', 'b2', 'b3'): server.sync_group_files_in(self.store, 'g1', bot)

    def tearDown(self): self.temp.cleanup()

    def copy(self, bot): return server.group_copy_folder(self.store, bot)

    def test_deleting_a_group_removes_only_its_untouched_copies(self):
        (self.copy('b1') / 'notes.txt').write_text('changed by the Bot')  # no longer Zook's copy
        (self.copy('b1') / 'mine.txt').write_text('the Bot made this')
        (self.root / 'data/workspaces/b1/報告.pdf').write_bytes(b'pdf')  # same content, elsewhere in the workspace
        server.drop_group_files(self.store, Holder(), self.group).join(10)
        self.assertFalse(self.shared.exists())
        self.assertEqual(sorted(p.name for p in self.copy('b1').iterdir()), ['mine.txt', 'notes.txt'])
        self.assertEqual(list(self.copy('b2').iterdir()), [])
        self.assertTrue((self.root / 'data/workspaces/b1/報告.pdf').exists())

    def test_a_bot_kept_aside_or_busy_is_left_alone(self):
        self.store.data['bots'] = [dict(id='b2')]; self.store.data['deletedBots'] = [dict(id='b1')]  # b1 is in 已刪除的 Bot
        holder = Holder(); busy = holder.__dict__.setdefault('group_copy_locks', {}).setdefault('b2', threading.Lock()); busy.acquire()
        server.drop_group_files(self.store, holder, self.group).join(10); busy.release()
        self.assertEqual(sorted(p.name for p in self.copy('b1').iterdir()), ['notes.txt', '報告.pdf'])
        self.assertEqual(sorted(p.name for p in self.copy('b2').iterdir()), ['notes.txt', '報告.pdf'])

    def test_a_link_in_the_copy_folder_is_not_followed(self):
        outside = self.root / 'outside'; outside.mkdir(); (outside / 'notes.txt').write_text('shared')
        (self.copy('b1') / 'notes.txt').unlink(); (self.copy('b1') / 'notes.txt').symlink_to(outside / 'notes.txt')
        folder = self.copy('b2'); server.shutil.rmtree(str(folder)); folder.symlink_to(outside)
        server.drop_group_files(self.store, Holder(), self.group).join(10)
        self.assertEqual((outside / 'notes.txt').read_text(), 'shared'); self.assertTrue((self.copy('b1') / 'notes.txt').is_symlink())

    def test_a_bot_gone_for_good_loses_its_copies_but_not_its_workspace(self):
        (self.root / 'data/workspaces/b3/成果.xlsx').write_bytes(b'x')
        self.store.data['bots'] = []; self.store.data['deletedBots'] = []
        for n, bot in enumerate(['b3'] + ['k%02d' % i for i in range(server.TRASH_KEEP)]): server.trash_bot(self.store, dict(id=bot, name=bot))
        self.assertNotIn('b3', [b['id'] for b in self.store.data['deletedBots']])
        self.assertEqual(list(self.copy('b3').iterdir()), []); self.assertTrue((self.root / 'data/workspaces/b3/成果.xlsx').exists())

    def test_a_bot_still_in_the_trash_keeps_its_copies(self):
        self.store.data['bots'] = []
        server.trash_bot(self.store, dict(id='b1', name='b1'))
        self.assertEqual(sorted(p.name for p in self.copy('b1').iterdir()), ['notes.txt', '報告.pdf'])


class DeleteGroupOverHttp(choices_test.ChoicesTest):
    for _name in [n for n in dir(choices_test.ChoicesTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def upload(self, group_id, name, data):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request('POST', '/api/groups/%s/files' % group_id, body=data, headers={'X-File-Name': name, 'Cookie': 'swarmr_session=' + self.token, 'Content-Type': 'application/octet-stream', 'Content-Length': str(len(data))})
        resp = conn.getresponse(); out = json.loads(resp.read()); conn.close(); return resp.status, out

    def test_deleting_a_group_clears_members_copies(self):
        other = self.req('POST', '/api/bots', {'name': '專員', 'provider': 'claude'})[1]
        group = self.req('POST', '/api/groups', {'name': '行銷', 'botIds': [self.bot['id'], other['id']]})[1]
        self.assertEqual(self.upload(group['id'], 'brief.pdf', b'%PDF-1')[0], 201)
        data = self.root / 'data'
        for bot in (self.bot['id'], other['id']):  # what a group turn leaves behind
            copy = data / 'workspaces' / bot / 'attachments/group-files'; copy.mkdir(parents=True, exist_ok=True); (copy / 'brief.pdf').write_bytes(b'%PDF-1')
        self.assertEqual(self.req('DELETE', '/api/groups/' + group['id'])[0], 200)
        for _ in range(50):  # the comparing runs after the answer
            if not any((data / 'workspaces' / b / 'attachments/group-files/brief.pdf').exists() for b in (self.bot['id'], other['id'])): break
            time.sleep(0.1)
        for bot in (self.bot['id'], other['id']): self.assertFalse((data / 'workspaces' / bot / 'attachments/group-files/brief.pdf').exists())
        self.assertFalse((data / 'group-files' / group['id']).exists())


class PageSide(unittest.TestCase):
    def test_a_bad_file_does_not_stop_the_rest(self):
        groups = (ROOT / 'frontend/js/35-groups.js').read_text(encoding='utf-8')
        body = groups[groups.index('async function uploadGroupFiles'):groups.index('function fileSummary')]
        self.assertNotIn('break', body); self.assertIn('failed.push', body); self.assertIn('fileSummary(ok.length, failed)', body)
        self.assertIn('group-file-note', groups)
        pages = (ROOT / 'frontend/js/30-pages.js').read_text(encoding='utf-8')
        self.assertIn("fileSummary(ok, failed, '附上')", pages); self.assertNotIn("toast('每則訊息最多 10 個檔案'); break;", pages)

    def test_a_long_name_keeps_the_delete_button(self):
        css = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
        self.assertIn('.group-file > button { flex-shrink: 0;', css); self.assertIn('grid-template-columns: minmax(0, 1fr)', css)
        groups = (ROOT / 'frontend/js/35-groups.js').read_text(encoding='utf-8'); pages = (ROOT / 'frontend/js/30-pages.js').read_text(encoding='utf-8')
        self.assertIn('<strong title="${esc(f.name)}">', groups); self.assertIn('class="pending-name" title="${esc(f.name)}">${esc(midName(f.name, 24))}', pages)


if __name__ == '__main__': unittest.main()
