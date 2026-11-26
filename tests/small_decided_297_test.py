# -*- coding: utf-8 -*-
"""Four small things the user decided (decisions 2026-11-26 第二批):
#297 (#20) every form window with changes asks 「要放棄修改嗎？」 before Esc, a click outside, × or 取消 closes it; without
     changes it just closes; Enter in a field of a longer form does not save and close it.
#298 (#11, #21) the memory page is a plain list: memory is kept by the Bots, changed by telling a Bot 「記住…／忘掉…」, and a
     Bot can really forget (only in the user's own turn); 刪除 stays as it was.
#299 (#166③) a schedule made again for the same Bot or group, time and content is called 「…（2）」.
#302 (#18) an exported conversation also names the files each reply saved, beside the time, the model and the attachments."""
import http.client, importlib.util, json, os, re, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'
SERVER = ROOT / 'backend/server.py'


def source(name): return (JS / name).read_text(encoding='utf-8')


def case(text, action):
    start = text.index("case '%s':" % action)
    nxt = text.find('\n        case ', start + 1)
    return text[start:nxt if nxt > 0 else None]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'backend' / file)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


server = load('zook_small_297_server', 'server.py')
runtime = load('zook_small_297_runtime', 'runtime.py')


class UnsavedChanges(unittest.TestCase):
    def test_every_way_of_closing_asks_first(self):
        unsaved = source('21b-unsaved.js')
        self.assertIn('function requestCloseModal(', unsaved)
        self.assertIn("title: '要放棄修改嗎？'", unsaved); self.assertIn("ok: '放棄修改'", unsaved); self.assertIn("keep: '繼續編輯'", unsaved)
        actions = source('40-actions.js')
        self.assertIn('requestCloseModal()', case(actions, 'close-modal'))  # × and 取消
        self.assertIn('requestCloseModal()', case(actions, 'overlay'))  # a click outside
        forms = source('50-forms.js')
        self.assertRegex(forms, r"e\.key === 'Escape' && state\.modal\) \{\s*requestCloseModal\(\)")  # Esc
        self.assertIn('modalEditsReset()', source('20-models.js'))  # each window starts with nothing changed

    def test_only_real_changes_count(self):
        unsaved = source('21b-unsaved.js')
        self.assertIn('e.isTrusted', unsaved)  # what the page fills in by itself (a draft, the model list) is not a change
        self.assertIn('modalFields() !== modalEdit.snap', unsaved)  # typed and then put back: nothing to lose
        self.assertIn('memberSearch', unsaved)  # a search box is not part of what is saved

    def test_the_question_can_name_its_buttons(self):
        ask = source('21-ask.js')
        self.assertIn("keep = '取消'", ask); self.assertIn('${esc(keep)}', ask)

    def test_enter_does_not_save_a_longer_form(self):
        unsaved = source('21b-unsaved.js')
        self.assertIn("e.key !== 'Enter'", unsaved); self.assertIn("closest?.('.modal form')", unsaved)
        self.assertIn('|password)$/', unsaved)  # a password still goes in with Enter
        self.assertIn("querySelector('form[data-busy]')", unsaved)  # while it is being saved, closing waits
        self.assertIn('requestCloseModal()', case(source('40-actions.js'), 'chats'))  # 返回 from 對話名稱


class MemoryPage(unittest.TestCase):
    def test_page_says_bots_keep_it(self):
        page = source('20-models.js')
        page = page[page.index("} else if (state.page === 'memory') {"):page.index("} else if (state.page === 'mcp-legacy')")]
        self.assertIn('記憶由 Bot 自己記', page); self.assertIn('「忘掉…」', page); self.assertIn('「記住…」', page)
        self.assertIn('delete-memory', page)  # 刪除 was there before and stays
        self.assertNotIn('edit-memory', page); self.assertNotIn('add-memory', page)


class Forget(unittest.TestCase):
    def setUp(self):
        server.watch_auto_status = lambda store, bot: None
        patcher = mock.patch.dict(os.environ, {'ZOOK_NO_INTRO': '1'}); patcher.start(); self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = server.Store(Path(self.temp.name) / 'data')
        self.app = server.App(('127.0.0.1', 0), self.store, self.temp.name, 'token'); self.addCleanup(self.app.server_close)
        self.bot = next(b for b in self.store.data['bots'] if b['name'] == '工程師')
        self.other = next(b for b in self.store.data['bots'] if b['name'] == '管理員')

    def tools(self, bot, origin='user'):
        return {schema['name']: (handler, approval) for schema, handler, approval in self.app.app_tools(bot, runtime, origin=origin)}

    def test_a_bot_forgets_what_it_may_read(self):
        remember = self.tools(self.bot)['zook_remember'][0]
        remember({'content': '回覆用條列', 'scope': 'shared'}); remember({'content': '工程師專用：用 Python 3.9'})
        self.tools(self.other)['zook_remember'][0]({'content': '管理員自己的事'})
        forget, approval = self.tools(self.bot)['zook_forget']
        self.assertTrue(approval)  # follows 主動性, like other changes to Zook's own data
        with self.assertRaises(RuntimeError): forget({'content': '管理員自己的事'})  # another Bot's own memory is not its to forget
        with self.assertRaises(RuntimeError): forget({'content': ''})
        self.assertEqual(forget({'content': '回覆用條列'})['forgotten'], ['回覆用條列'])
        self.assertEqual(forget({'content': 'Python 3.9'})['forgotten'], ['工程師專用：用 Python 3.9'])  # a part of it is enough when only one fits
        self.assertEqual([m['content'] for m in self.store.data['memories']], ['管理員自己的事'])

    def test_more_than_one_fits(self):
        remember = self.tools(self.bot)['zook_remember'][0]
        remember({'content': '週報用條列'}); remember({'content': '月報用條列'})
        with self.assertRaises(RuntimeError) as said: self.tools(self.bot)['zook_forget'][0]({'content': '用條列'})
        self.assertIn('週報用條列', str(said.exception)); self.assertEqual(len(self.store.data['memories']), 2)

    def test_only_the_users_own_turn(self):
        self.tools(self.bot)['zook_remember'][0]({'content': '回覆用條列', 'scope': 'shared'})
        with self.assertRaises(RuntimeError): self.tools(self.bot, 'schedule')['zook_forget'][0]({'content': '回覆用條列'})
        self.assertEqual(len(self.store.data['memories']), 1)


class SameSchedule(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        (root / 'assets').mkdir(); (root / 'assets/index.html').write_text('x')
        env = dict(os.environ, PATH='/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(root / 'data'), '--assets', str(root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def test_numbered_like_groups(self):
        bot = self.req('GET', '/api/state')[1]['bots'][0]['id']
        body = {'botId': bot, 'content': '整理信件', 'time': '09:00', 'repeat': 'daily', 'on': False}
        names = [self.req('POST', '/api/schedules', body)[1].get('name', '') for _ in range(3)]
        self.assertEqual(names, ['', '整理信件（2）', '整理信件（3）'])  # unnamed: named after what it does
        self.assertEqual(self.req('POST', '/api/schedules', dict(body, name='早上'))[1]['name'], '早上（2）')  # a name of its own is numbered too
        self.assertEqual(self.req('POST', '/api/schedules', dict(body, name='早上'))[1]['name'], '早上（3）')
        self.assertEqual(self.req('POST', '/api/schedules', dict(body, time='10:00'))[1].get('name', ''), '')  # another time is another schedule
        self.assertEqual(self.req('POST', '/api/schedules', dict(body, content='整理檔案'))[1].get('name', ''), '')
        first = self.req('GET', '/api/state')[1]['schedules'][0]
        self.assertEqual(self.req('PATCH', '/api/schedules/' + first['id'], {'on': True})[1].get('name', ''), '')  # editing renames nothing

    def test_the_form_says_so(self):
        forms = source('50-forms.js')
        self.assertIn('已有相同的排程，這筆叫「', forms)


class ExportFiles(unittest.TestCase):
    def test_files_a_reply_saved_are_listed(self):
        bot = dict(id='b1', name='助手', chatId='c1', chats=[dict(id='c1', title='報表')],
                   messages=[dict(id='u1', role='user', content='做報表', createdAt='2026-11-23T06:00:00+00:00'),
                             dict(id='a1', role='assistant', status='completed', content='好了', createdAt='2026-11-23T06:01:00+00:00')])
        job = dict(id='j1', botId='b1', messageId='a1', status='completed', usage=dict(provider='claude', model='claude-x'),
                   toolCalls=[dict(name='native_write', arguments=dict(path='/Users/x/報表.xlsx')), dict(name='zook_workspace_write', arguments=dict(path='說明.md')),
                              dict(name='zook_workspace_write', arguments=dict(path='沒存成.md'), status='denied')],
                   wrote=['/Users/x/報表.xlsx', '/Users/x/圖.png'])
        text = server.export_chat(dict(bots=[bot], jobs=[job]), bot, 'c1')['markdown']
        self.assertIn('這則回覆存的檔案：報表.xlsx、說明.md、圖.png', text)
        self.assertNotIn('沒存成.md', text)  # turned down: not saved
        self.assertNotIn('/Users/x', text)  # names only, never where on this Mac


if __name__ == '__main__': unittest.main()
