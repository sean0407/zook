# -*- coding: utf-8 -*-
"""#256 #332① #162 #56③ #103②④ #147① #159 #251 #281② #189⑦ #257⑥ (G44–G46、G48): the Bot form.
- A Claude or Cursor Bot hides 存取範圍; what that hidden menu still holds is not sent, and never stops the form (G45).
- Two windows editing one Bot: the second save sees the first one's change and says 「這個 Bot 已在別處修改」 instead of
  overwriting it (G46).
- The model part sits at the top, is chosen from a menu only, says 重新整理清單, is locked while its list is read, and a new
  CLI puts 思考強度 back to 預設 too (G44).
- 主動性 is no longer shown on a Bot (G48); the permission logic behind it is unchanged."""
import http.client, importlib.util, json, os, re, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
sys.path.insert(0, str(ROOT / 'backend'))
spec = importlib.util.spec_from_file_location('zook_server_for_bot_form_256', SERVER)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
JS = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


def bot_form_submit():
    start = JS.index("} else if (form.id === 'bot-form') {")
    return JS[start:JS.index("} else if (form.id === 'mcp-bots-form')", start)]


class HiddenAccess(unittest.TestCase):
    def test_hidden_access_is_not_sent_and_does_not_block(self):
        code = bot_form_submit()
        self.assertIn("accessShown = !form.querySelector('[data-access-row]')?.hidden", code)
        self.assertIn('if (accessShown) Object.assign(data, {access:', code)
        self.assertIn("if (accessShown && data.access === 'folder' && !data.accessFolder)", code)
        self.assertNotIn("toast('請先選擇資料夾')", code)  # nothing hidden can stop the form any more

    def test_fixed_access_is_said_instead(self):
        self.assertIn('data-access-fixed', JS)
        self.assertIn("form.querySelector('[data-access-fixed]')", JS)
        self.assertIn('Skills 和連接器由所有 Bot 共用', JS)


class EditConflict(unittest.TestCase):
    def test_rule(self):
        bot = dict(id='b', name='小幫手', jobTitle='新職稱', persona='p', provider='codex')
        self.assertFalse(m.edit_conflict(bot, {'name': 'x'}))  # no base (a phone, an older window): as before
        body = {'name': 'x', 'base': dict(name='小幫手', jobTitle='新職稱', persona='p', provider='codex', model=None, pinned=None)}
        self.assertFalse(m.edit_conflict(bot, body)); self.assertNotIn('base', body)  # never stored on the Bot
        self.assertTrue(m.edit_conflict(bot, {'base': dict(name='小幫手', jobTitle='舊職稱')}))
        self.assertTrue(m.edit_conflict(bot, {'base': dict(name='小幫手', jobTitle=None)}))  # it had none when the window opened
        self.assertFalse(m.edit_conflict(dict(bot, model=''), {'base': dict(model=None)}))  # empty and missing are the same
        self.assertFalse(m.edit_conflict(bot, {'base': dict(messages=['x'], chatId='other')}))  # only what the form edits

    def test_the_form_sends_what_it_opened_with(self):
        self.assertIn('form.botBase = botBase(b)', JS)
        self.assertIn('if (id && form.botBase) data.base = form.botBase', bot_form_submit())
        self.assertIn('error.status === 409', bot_form_submit())


class EditConflictOverHttp(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {'ZOOK_NO_INTRO': '1'}); env.start(); self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = m.Store(Path(self.temp.name) / 'data')
        self.app = m.App(('127.0.0.1', 0), self.store, self.temp.name, 'local-token')
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.addCleanup(self.app.server_close); self.addCleanup(self.app.shutdown)
        for p in (mock.patch.object(m, 'find_cli', return_value='/bin/true'), mock.patch.object(m, 'log_activity'),
                  mock.patch.object(m, 'watch_auto_status', lambda store, bot: None)):
            p.start(); self.addCleanup(p.stop)
        with self.store.lock:
            self.store.data['bots'].append(dict(id='b', name='小幫手', jobTitle='舊職稱', persona='p', provider='codex', messages=[], chats=[]))

    def patch(self, body):
        conn = http.client.HTTPConnection('127.0.0.1', self.app.server_address[1], timeout=10)
        conn.request('PATCH', '/api/bots/b', json.dumps(body).encode(), {'Authorization': 'Bearer local-token', 'Content-Type': 'application/json'})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def test_second_window_is_told(self):
        opened = dict(name='小幫手', jobTitle='舊職稱', persona='p', provider='codex')
        status, _ = self.patch(dict(opened, jobTitle='新職稱', base=opened))  # window B
        self.assertEqual(status, 200)
        status, body = self.patch(dict(opened, persona='改過的人格', base=opened))  # window A, opened before B saved
        self.assertEqual(status, 409); self.assertIn('這個 Bot 已在別處修改', body['error'])
        bot = self.store.find('bots', 'b')
        self.assertEqual((bot['jobTitle'], bot['persona']), ('新職稱', 'p')); self.assertNotIn('base', bot)


class ModelArea(unittest.TestCase):
    def test_model_part_is_above_persona(self):
        start = JS.index('function botModal(')
        form = JS[start:JS.index('const form = $(\'#bot-form\')', start)]
        self.assertLess(form.index('name="providerChoice"'), form.index('name="persona"'))
        self.assertLess(form.index("settingRow('思考強度'"), form.index('name="persona"'))

    def test_chosen_from_a_menu_only(self):
        self.assertIn("modelPicker(b.model||'', false, false)", JS)
        self.assertIn('（不在這一家的清單裡，可能無法回覆）', JS)
        self.assertNotIn('<option value="__custom__">自己輸入型號…</option>\';', JS)  # the placeholder while a new list is read

    def test_plain_refresh_and_lock(self):
        self.assertIn('>重新整理清單</button>', JS); self.assertNotIn('>重新偵測</button>', JS)
        self.assertNotIn('可以按「重新偵測」', JS)
        self.assertIn('select.disabled = true', JS); self.assertIn('select.disabled = false', JS)

    def test_new_cli_resets_effort(self):
        self.assertIn("setDropdown(form, 'effort', '')", JS)

    def test_a_late_list_for_another_cli_is_dropped(self):
        self.assertIn('form.elements.provider.value !== provider', JS)

    def test_auto_line_goes_with_auto(self):  # #333③: 自動配's line under 模型與帳號 stayed for every other choice
        self.assertIn('.field small.muted[hidden] { display: none; }', (ROOT / 'frontend/style.css').read_text(encoding='utf-8'))

    def test_default_named_as_in_the_list(self):
        self.assertIn('清單裡沒有這個型號', JS)


class NoInitiative(unittest.TestCase):
    def test_bot_details_do_not_say_initiative(self):
        perm = re.search(r'const permText = b => .*', JS).group(0)
        self.assertNotIn('主動性', perm)


if __name__ == '__main__':
    unittest.main()
