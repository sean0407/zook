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
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))
        self.store = self.m.Store(self.root / 'data'); self.m._active['data'] = self.store.data
        self.bot = dict(id='b' * 32, name='業務小幫', access='full')
        self.store.data['bots'].append(self.bot)

    def tearDown(self): self.temp.cleanup()

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


if __name__ == '__main__': unittest.main()
