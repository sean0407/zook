# -*- coding: utf-8 -*-
"""#241: each conversation has its own folder inside the Bot's workspace. When the user names no place, the Bot is told to save
there (not the real Desktop); 打開資料夾 shows it in Finder; what is saved there is listed in 產出."""
import os, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import choices_test


class ChatFolder(choices_test.ChoicesTest):
    for _name in [n for n in dir(choices_test.ChoicesTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def setUp(self):
        os.environ['ZOOK_NO_BROWSER'] = '1'  # never open a Finder window from a test
        super().setUp()

    def tearDown(self):
        super().tearDown(); os.environ.pop('ZOOK_NO_BROWSER', None)

    def test_the_bot_is_told_where_this_conversation_keeps_files(self):
        self.finish(self.send('做一份報表'))
        bot = next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])
        folder = Path(os.path.realpath(str(self.root / 'data'))) / 'workspaces' / self.bot['id'] / 'chat-files' / bot['chatId']
        self.assertIn('這段對話的資料夾：%s' % folder, self.prompt()); self.assertIn('不要存到桌面', self.prompt())
        self.assertTrue(folder.is_dir())
        status, out = self.req('POST', '/api/bots/%s/chats/%s/folder' % (self.bot['id'], bot['chatId']), {})
        self.assertEqual((status, os.path.realpath(out['path'])), (200, str(folder)))
        self.assertEqual(self.req('POST', '/api/bots/%s/chats/nope/folder' % self.bot['id'], {})[0], 404)
        (folder / '報表.xlsx').write_bytes(b'x')
        self.assertIn('報表.xlsx', [o['name'] for o in self.req('GET', '/api/bots/%s/outputs' % self.bot['id'])[1]['outputs']])

    def test_another_conversation_gets_another_folder(self):
        self.finish(self.send('第一段'))
        first = self.prompt()
        self.req('POST', '/api/bots/%s/chats' % self.bot['id'], {})
        self.finish(self.send('第二段'))
        pick = lambda text: text.split('這段對話的資料夾：', 1)[1].split('（', 1)[0]
        self.assertNotEqual(pick(first), pick(self.prompt()))


    def test_a_bot_kept_to_one_folder_saves_there(self):  # it may not write into its workspace, so it is not sent there
        app = (Path(__file__).resolve().parents[1] / 'backend/zook/app.py').read_text(encoding='utf-8')
        self.assertIn("saving = '' if bot_scope(bot)[0] == 'folder' else", app)
        m = choices_test.load(); m._active['data'] = {'settings': {}}
        self.assertEqual(m.bot_scope(dict(provider='codex', access='folder', accessFolder='/x'))[0], 'folder')

if __name__ == '__main__': unittest.main()
