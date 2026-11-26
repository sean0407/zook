# -*- coding: utf-8 -*-
"""產出 while a reply is still running (#53①), a card for every file a reply names, pictures too (#154①), the Bot's header in
words (#154②), and the shared rules about handing over work (#104, #154④)."""
import datetime, importlib.util, json, os, re, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_live_outputs', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def frontend(): return ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


class LiveOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))
        self.store = self.m.Store(self.root / 'data'); self.m._active['data'] = self.store.data
        self.bot = dict(id='b' * 32, name='企劃小幫', access='full'); self.store.data['bots'].append(self.bot)

    def tearDown(self): self.m.PROGRESS.clear(); self.temp.cleanup()

    def running(self, job_id):
        iso = datetime.datetime.fromtimestamp(time.time() - 5, datetime.timezone.utc).isoformat()
        self.store.data['jobs'].append(dict(id=job_id, botId=self.bot['id'], status='running', content='', createdAt=iso, toolCalls=[]))

    def feed(self, job_id, kind, lines):
        self.m.progress_start(job_id); feed = self.m.progress_feeder(kind, job_id)
        feed(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in lines).encode('utf-8'))

    def test_a_file_the_cli_reports_writing_shows_before_the_reply_ends(self):
        made = self.root / 'out' / '尾牙企劃書.pdf'; made.parent.mkdir(); made.write_bytes(b'%PDF')
        other = self.root / 'out' / '舊的.pdf'; other.write_bytes(b'x'); os.utime(other, (time.time() - 3600,) * 2)
        self.running('j1')
        self.feed('j1', 'claude', [dict(type='assistant', message=dict(content=[dict(type='tool_use', id='w', name='Write', input=dict(file_path=str(made)))])),
                                   dict(type='user', message=dict(content=[dict(type='tool_result', tool_use_id='w', content='ok')]))])
        names = [o['name'] for o in self.m.bot_outputs(self.store, self.bot)]
        self.assertIn('尾牙企劃書.pdf', names); self.assertNotIn('舊的.pdf', names)

    def test_codex_and_antigravity_writes_count_too_but_not_refused_ones(self):
        a = self.root / 'a.xlsx'; b = self.root / 'b.png'; no = self.root / 'no.md'
        for p in (a, b, no): p.write_bytes(b'x')
        self.running('j2'); self.running('j3'); self.running('j4')
        self.feed('j2', 'codex', [dict(type='item.completed', item=dict(id='i', type='file_change', changes=[dict(path=str(a))]))])
        self.feed('j3', 'antigravity', [dict(event='step_update', step_update=dict(step_index=1, state='DONE', step_type='tool', tool_name='write_file', tool_info=dict(parameters=dict(Path=str(b)))))])
        self.feed('j4', 'claude', [dict(type='assistant', message=dict(content=[dict(type='tool_use', id='n', name='Write', input=dict(file_path=str(no)))])),
                                   dict(type='user', message=dict(content=[dict(type='tool_result', tool_use_id='n', is_error=True, content='denied')]))])
        names = [o['name'] for o in self.m.bot_outputs(self.store, self.bot)]
        self.assertIn('a.xlsx', names); self.assertIn('b.png', names); self.assertNotIn('no.md', names)

    def test_only_running_replies_and_only_where_the_bot_may_write(self):
        made = self.root / 'x.txt'; made.write_bytes(b'x')
        self.bot['access'] = 'workspace'; self.running('j5')
        self.feed('j5', 'claude', [dict(type='assistant', message=dict(content=[dict(type='tool_use', id='w', name='Write', input=dict(file_path=str(made)))])),
                                   dict(type='user', message=dict(content=[dict(type='tool_result', tool_use_id='w', content='ok')]))])
        self.assertNotIn('x.txt', [o['name'] for o in self.m.bot_outputs(self.store, self.bot)])  # outside its working folder

    def test_attachments_and_later_changes_are_not_outputs(self):
        given = self.store.dir / 'workspaces' / self.bot['id'] / 'attachments' / '客訴.txt'; given.parent.mkdir(parents=True); given.write_bytes(b'x')
        later = self.root / 'later.txt'; later.write_bytes(b'x'); os.utime(later, (time.time() + 600,) * 2)  # changed after now: not by this reply so far
        self.running('j6')
        for i, path in enumerate((given, later)):
            self.feed('j6' if not i else 'j7', 'claude', [dict(type='assistant', message=dict(content=[dict(type='tool_use', id='w', name='Write', input=dict(file_path=str(path)))])),
                                                         dict(type='user', message=dict(content=[dict(type='tool_result', tool_use_id='w', content='ok')]))])
        self.running('j7')
        names = [o['name'] for o in self.m.bot_outputs(self.store, self.bot)]
        self.assertNotIn('客訴.txt', names); self.assertNotIn('later.txt', names)

    def test_window_fetches_outputs_again_as_the_reply_writes(self):
        js = frontend()
        self.assertIn('liveMark', js)  # the mark that makes 產出 load again changes with what the running reply reported
        self.assertRegex(js, r'progress\?\.write')

    def test_every_named_file_gets_a_card_pictures_too(self):
        js = frontend()
        body = js[js.index('function messageFiles'):]; body = body[:body.index('\n  }\n')]
        self.assertNotIn("rest = found.filter(f => f.kind !== 'image')", body)  # a picture is no longer left without its card
        self.assertIn('found.map', body)

    def test_header_names_the_model_in_words(self):
        js = frontend()
        self.assertIn('function modelWords', js)
        self.assertIn('modelWords(b.model', js)

    def test_account_menu_says_low_before_every_account_is_read(self):
        js = frontend()
        self.assertIn('const ringMark', js)  # the sidebar rings' figures stand in while the live read of every account is on its way
        self.assertIn('!state.quota && !a ? ringMark(id)', js)

    def test_shared_rules_about_handing_over(self):
        self.m._active['data'] = dict(settings={}, rules=[])
        text = self.m.identity_block(dict(name='企劃小幫'))
        self.assertIn('不能只說「已存檔」', text)  # #104
        self.assertIn('以下是我自己加的，請確認', text)  # #154④ product facts
        self.assertIn('原本就有的檔案和子資料夾', text)  # #154④ the folder the user named


if __name__ == '__main__': unittest.main()
