# -*- coding: utf-8 -*-
"""#39: a member's reply names a file in its own workspace. Another member (or the one checking it) reads that file from its own
copy of the group's files, so the path is rewritten to the place it can open; a check is told to open the files before passing."""
import importlib.util, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_check_paths', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)


class Store:
    def __init__(self, root): self.dir = Path(root); self.data = {'bots': [], 'knowledge': [], 'memories': [], 'jobs': []}
    def find(self, kind, key): return next((x for x in self.data[kind] if x['id'] == key), None)


class CheckPaths(unittest.TestCase):
    def setUp(self):
        m._active['data'] = {'settings': {}, 'rules': []}
        self.temp = tempfile.TemporaryDirectory(); self.store = Store(self.temp.name)
        self.host = dict(id='h' * 32, name='主持人', provider='claude'); self.maker = dict(id='d' * 32, name='簡報設計', provider='antigravity')
        self.store.data['bots'] += [self.host, self.maker]
        self.group = dict(id='g1', name='行銷', botIds=[self.host['id'], self.maker['id']], messages=[], fileInfo={'簡報.pptx': {'origName': '簡報v1.pptx'}})
        shared = m.group_files_dir(self.store, 'g1'); shared.mkdir(parents=True); (shared / '簡報.pptx').write_bytes(b'x'); (shared / 'a.png').write_bytes(b'x')
        theirs = self.store.dir / 'workspaces' / self.maker['id']
        self.reply = dict(id='r1', role='assistant', botId=self.maker['id'], status='completed',
                          content='做好了：%s/簡報v1.pptx，封面 %s/a.png，備註 %s/草稿.md，參考 /Users/someone/a.png' % (theirs, theirs, theirs))
        self.group['messages'].append(self.reply)

    def tearDown(self): self.temp.cleanup()

    def test_a_check_gets_paths_it_can_open(self):
        prompt = m.group_prompt(self.store, self.group, self.host, False, target=self.reply)
        mine = m.group_copy_folder(self.store, self.host['id'])
        self.assertIn(str(mine / '簡報.pptx'), prompt); self.assertIn(str(mine / 'a.png'), prompt)  # by its kept name, and by the name it was uploaded with
        self.assertIn('草稿.md', prompt)  # not among the group's files: left as it was
        self.assertIn('/Users/someone/a.png', prompt)  # a same-named file outside the author's workspace is another file
        self.assertIn('查核前要實際打開這些檔案', prompt)

    def test_the_discussion_shows_other_members_files_where_the_reader_finds_them(self):
        prompt = m.group_prompt(self.store, self.group, self.host, False)
        self.assertIn(str(m.group_copy_folder(self.store, self.host['id']) / 'a.png'), prompt)
        self.assertNotIn('查核前要實際打開', prompt)
        own = m.group_prompt(self.store, self.group, self.maker, False)  # its own words stay as it wrote them
        self.assertIn(str(self.store.dir / 'workspaces' / self.maker['id'] / 'a.png'), own)

    def test_a_hidden_file_is_not_pointed_to(self):
        prompt = m.group_prompt(self.store, self.group, self.host, False, target=self.reply, hidden_files={'a.png'})
        self.assertNotIn(str(m.group_copy_folder(self.store, self.host['id']) / 'a.png'), prompt)


if __name__ == '__main__': unittest.main()
