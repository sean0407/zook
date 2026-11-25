# -*- coding: utf-8 -*-
"""產出: files a Bot made show in its panel even when its CLI does not report the write (Antigravity's steps, a file made by a command)."""
import datetime, importlib.util, json, os, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_named_outputs', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class NamedOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load(); global FOLDER_NEVER; FOLDER_NEVER = cls.m.FOLDER_NEVER

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))
        self.store = self.m.Store(self.root / 'data'); self.m._active['data'] = self.store.data
        self.bot = dict(id='b' * 32, name='業務小幫', access='full')
        self.store.data['bots'].append(self.bot)


    def job(self, content, start, end, **extra):
        iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
        self.store.data['jobs'].append(dict(dict(id=os.urandom(8).hex(), botId=self.bot['id'], status='completed', content=content, createdAt=iso(start), finishedAt=iso(end), toolCalls=[]), **extra))

    def test_antigravity_write_steps_are_recorded(self):
        lines = [dict(event='step_update', step_update=dict(step_index=4, state='DONE', step_type='tool', tool_name='write_file', tool_info=dict(name='write_file', parameters=dict(Path='/tmp/x/報表.xlsx')))),
                 dict(event='step_update', step_update=dict(step_index=5, state='DONE', step_type='tool', tool_name='run_command', tool_info=dict(name='run_command', parameters=dict(CommandLine='python3 make.py')))),
                 dict(event='step_update', step_update=dict(step_index=6, state='DONE', step_type='tool', tool_name='read_file', tool_info=dict(name='read_file', parameters=dict(Path='/tmp/x/a.csv')))),
                 dict(event='result', result=dict(status='SUCCESS', response='好了'))]
        out = self.m.parse_cli_output('antigravity', '\n'.join(json.dumps(x, ensure_ascii=False) for x in lines), 'm')
        self.assertEqual([(w['name'], list(w['arguments'].values())[0]) for w in out['web']], [('native_write', '/tmp/x/報表.xlsx'), ('native_command', '執行指令：python3')])  # a summary, never the command

    def test_a_file_the_reply_names_counts_when_it_changed_during_the_reply(self):
        made = self.root / 'out' / '第三季業績.xlsx'; made.parent.mkdir(); start = time.time(); made.write_bytes(b'x'); end = time.time() + 1
        old = self.root / 'out' / '舊檔.pdf'; old.write_bytes(b'y'); os.utime(old, (start - 3600, start - 3600))
        self.job('已存到 %s，參考了 %s，網址 https://a.com/z.html' % (made, old), start, end)
        names = [o['name'] for o in self.m.bot_outputs(self.store, self.bot)]
        self.assertIn('第三季業績.xlsx', names); self.assertNotIn('舊檔.pdf', names)  # named, but not changed by this reply

    def test_whole_words_only_and_quick_on_odd_text(self):
        self.assertEqual(self.m.named_paths('存在 /tmp/a/sales.xlsx-old 和 /tmp/a/報表.xlsx。網址 https://a.com/b.html'), ['/tmp/a/報表.xlsx'])
        start = time.time(); self.m.named_paths('/a' * 20000 + '/'); self.m.named_paths(('/x' * 50 + ' ') * 400)
        self.assertLess(time.time() - start, 1)  # no backtracking on long runs of slashes

    def test_plans_and_attachments_are_not_outputs(self):
        start = time.time()
        made = self.root / 'plan.xlsx'; made.write_bytes(b'x')
        self.job('規劃：會存到 %s' % made, start, time.time() + 1, plan=True)
        given = self.store.dir / 'workspaces' / self.bot['id'] / 'attachments' / 'a.csv'; given.parent.mkdir(parents=True); given.write_bytes(b'x')
        self.job('讀了 %s' % given, start, time.time() + 1)
        names = [o['name'] for o in self.m.bot_outputs(self.store, self.bot)]
        self.assertNotIn('plan.xlsx', names); self.assertNotIn('a.csv', names)

    def test_named_files_survive_when_old_replies_are_trimmed(self):
        made = self.root / 'r.xlsx'; start = time.time(); made.write_bytes(b'x')
        self.job('存在 %s' % made, start, time.time() + 1)
        for _ in range(self.m.JOBS_FULL_PER_BOT + 2): self.job('其他', start, start + 1)
        self.m.trim_jobs(self.store)
        first = self.store.data['jobs'][0]
        self.assertNotIn('content', first); self.assertIn(str(made), first.get('wrote') or [])
        self.assertIn('r.xlsx', [o['name'] for o in self.m.bot_outputs(self.store, self.bot)])

    def test_files_a_command_wrote_into_the_folder_the_work_was_sent_to(self):
        self.m.FOLDER_NEVER = ()  # this test's folder sits in the Mac's scratch space; real scratch folders are never listed (below)
        out = self.root / 'zook-inspect' / 'A'; out.mkdir(parents=True)
        old = out / '上週.png'; old.write_bytes(b'o'); start = time.time(); os.utime(old, (start - 3600, start - 3600))
        made = out / 'ig.png'; made.write_bytes(b'x'); (out / 'sub').mkdir(); (out / 'sub' / 'deep.png').write_bytes(b'x')
        chat = dict(id='c1', title='', messages=[dict(id='u1', role='user', content='做一張 IG 方形圖放 %s/' % out), dict(id='r1', role='assistant', content='好了')])
        self.bot['chats'] = [chat]
        self.job('圖做好了。', start, time.time() + 1, chatId='c1', messageId='r1')  # names no file: it was made by a swift script
        names = [o['name'] for o in self.m.bot_outputs(self.store, self.bot)]
        self.assertIn('ig.png', names)
        self.assertNotIn('上週.png', names); self.assertNotIn('deep.png', names)  # older than the reply; inside a sub-folder
        self.job('另外放在 file://%s 了' % out, start, time.time() + 1)  # a folder in the reply counts the same way
        self.assertIn('ig.png', [o['name'] for o in self.m.bot_outputs(self.store, self.bot)])

    def test_folder_words(self):
        self.assertEqual(self.m.named_folders('放 /tmp/zook/A/ 和 /tmp/x/報表.xlsx，暫存 /var/folders/ab/T/x，/private/etc/x，根目錄 /tmp'), ['/tmp/zook/A'])

    def test_a_busy_folder_still_shows_what_changed_and_zook_data_never_does(self):
        self.m.FOLDER_NEVER = ()
        out = self.root / 'busy'; out.mkdir(); start = time.time()
        for i in range(80):
            f = out / ('old%02d.txt' % i); f.write_bytes(b'o'); os.utime(f, (start - 3600, start - 3600))
        (out / 'new.png').write_bytes(b'x')
        (self.store.dir / 'mine.json').write_bytes(b'{}')
        upper = str(self.store.dir).upper() if os.path.exists(str(self.store.dir).upper()) else str(self.store.dir)  # the Mac's disk ignores case
        self.job('放在 %s/ 和 %s/' % (out, upper), start, time.time() + 1)
        names = [o['name'] for o in self.m.bot_outputs(self.store, self.bot)]
        self.assertIn('new.png', names); self.assertNotIn('mine.json', names); self.assertFalse([n for n in names if n.startswith('old')])

    def test_named_folders_survive_when_old_replies_are_trimmed(self):
        self.m.FOLDER_NEVER = ()
        out = self.root / 'kept'; out.mkdir(); start = time.time(); (out / 'a.png').write_bytes(b'x')
        self.job('放在 %s/' % out, start, time.time() + 1)
        for _ in range(self.m.JOBS_FULL_PER_BOT + 2): self.job('其他', start - 10, start - 9)
        self.m.trim_jobs(self.store)
        self.assertEqual(self.store.data['jobs'][0].get('namedFolders'), [str(out)])
        self.assertIn('a.png', [o['name'] for o in self.m.bot_outputs(self.store, self.bot)])

    def tearDown(self):
        self.m.FOLDER_NEVER = FOLDER_NEVER; self.temp.cleanup()


if __name__ == '__main__': unittest.main()
