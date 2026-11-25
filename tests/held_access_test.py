# -*- coding: utf-8 -*-
"""#284: a Claude or Cursor Bot that Zook held in still shows 「存取範圍」 in 編輯 Bot. Choosing 「整台 Mac」 there, in this Mac's window,
puts it back behind the safety gate (gateFull), the same as picking its model here again; nothing else lifts it, and the gate's own
checks still decide (a Claude setup whose hook was not seen yet answers that one reply in the workspace)."""
import http.client, importlib.util, json, os, re, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
sys.path.insert(0, str(ROOT / 'backend'))
spec = importlib.util.spec_from_file_location('zook_server_for_held_access', SERVER)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
JS = {p.name: p.read_text(encoding='utf-8') for p in (ROOT / 'frontend/js').glob('*.js')}


def held(provider):
    return dict(id='h', name='收緊的', provider=provider, localLimit=True, access='workspace', permissionMode='manual')


class HeldAccessRules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = m.Store(Path(self.temp.name) / 'data')
        self.store.data['settings'].update(permissionMode='bypass', access='full')

    def run_on(self, bot, kind):
        return m.permission_mode(self.store, bot, kind), m.bot_scope(bot, kind)

    def test_whole_mac_chosen_here_puts_it_behind_the_gate(self):
        for provider in ('claude', 'cursor'):
            before = held(provider); after = dict(before, access='full')
            m.local_choice(before, after, dict(access='full', accessFolder=''))
            self.assertTrue(after.get('gateFull'), provider); self.assertNotIn('localLimit', after)
            self.assertEqual((after['access'], after['permissionMode']), ('workspace', 'manual'))  # its own, unused on the gate, never widened
            self.assertEqual(self.run_on(after, provider), ('auto', ('full', '')))
            self.assertEqual(self.run_on(after, 'codex'), ('manual', ('workspace', '')))  # a backup CLI without the gate: still held

    def test_nothing_else_lifts_it(self):
        folder = self.temp.name
        for body in (dict(access='folder', accessFolder=folder), dict(permissionMode='bypass'), dict(access='', accessFolder='')):
            before = held('claude'); after = dict(before, **body)
            m.local_choice(before, after, body)
            self.assertNotIn('gateFull', after, body); self.assertTrue(after['localLimit'], body)
            self.assertEqual(self.run_on(after, 'claude'), ('manual', ('workspace', '')), body)
        before = held('claude'); after = dict(before, access='full')
        m.local_choice(before, after, dict(access='full'), local=False)  # a paired phone
        self.assertNotIn('gateFull', after); self.assertTrue(after['localLimit'])
        before = held('auto'); after = dict(before, access='full')  # 自動選擇: the match decides, never this
        m.local_choice(before, after, dict(access='full')); self.assertNotIn('gateFull', after)

    def test_other_clis_keep_their_own_choice(self):
        before = held('codex'); after = dict(before, access='full')
        m.local_choice(before, after, dict(access='full'))
        self.assertNotIn('gateFull', after); self.assertNotIn('localLimit', after)
        self.assertEqual(m.bot_scope(after, 'codex'), ('full', ''))

    def test_claude_still_waits_for_its_check_to_be_seen(self):
        before = held('claude'); after = dict(before, access='full')
        m.local_choice(before, after, dict(access='full'))
        job, work = {}, Path(self.temp.name) / 'ws'
        with mock.patch.object(m, 'claude_gate_seen', return_value=False):
            self.assertEqual(m.claude_scope(self.store, 'claude', after, 'full', Path.home(), work, job), ('workspace', work))
        self.assertTrue(job['gateProbe'])
        with mock.patch.object(m, 'claude_gate_seen', return_value=True):
            self.assertEqual(m.claude_scope(self.store, 'claude', after, 'full', Path.home(), work, {}), ('full', Path.home()))


class HeldAccessOverHttp(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {'ZOOK_NO_INTRO': '1'}); env.start(); self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = m.Store(Path(self.temp.name) / 'data')
        self.app = m.App(('127.0.0.1', 0), self.store, self.temp.name, 'local-token'); self.app.bridge_token = 'bridge-token'
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.addCleanup(self.app.server_close); self.addCleanup(self.app.shutdown)
        for p in (mock.patch.object(m, 'find_cli', return_value='/bin/true'), mock.patch.object(m, 'log_activity'),
                  mock.patch.object(m, 'watch_auto_status', lambda store, bot: None)):
            p.start(); self.addCleanup(p.stop)
        with self.store.lock:
            self.store.data['bots'].append(dict(held('claude'), messages=[], chats=[]))
            self.store.data.setdefault('remoteDevices', []).append(dict(id='dev1', name='iPhone'))

    def req(self, body, token='local-token', device=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.app.server_address[1], timeout=10)
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        if device is not None: headers['X-Zook-Device'] = device
        conn.request('PATCH', '/api/bots/h', json.dumps(body).encode(), headers)
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def test_saving_the_form_with_whole_mac(self):
        form = dict(name='收緊的', persona='x', provider='claude', account='', model='', access='full', accessFolder='')
        status, _ = self.req(form, token='bridge-token', device='dev1')
        self.assertTrue(self.store.find('bots', 'h')['localLimit'])  # refused or held: never widened from the phone
        status, body = self.req(dict(form, access='workspace'))
        self.assertEqual(status, 200); self.assertTrue(self.store.find('bots', 'h')['localLimit'])  # left as it was
        status, body = self.req(form)
        self.assertEqual(status, 200)
        bot = self.store.find('bots', 'h')
        self.assertTrue(bot['gateFull']); self.assertNotIn('localLimit', bot)


class HeldAccessForm(unittest.TestCase):
    def test_the_held_row_is_shown_and_explained(self):
        src = JS['20-models.js']
        self.assertIn('data-held-access', src)
        row = re.search(r'const HELD_ACCESS_NOTE = .*', src).group(0)
        self.assertIn('安全檢查生效', row); self.assertIn('工作資料夾', row)
        sync = re.search(r'function syncFeatureRows\(form\) \{.*?\n  \}', src, re.S).group(0)
        self.assertIn('[data-held-access]', sync)
        submit = JS['50-forms.js']
        self.assertIn("heldAccess", submit)


if __name__ == '__main__':
    unittest.main()
