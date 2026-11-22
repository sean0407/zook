# -*- coding: utf-8 -*-
"""OpenCode, GitHub Copilot and Kimi are no longer supported: they are not offered, and older data that names them is moved on."""
import http.client, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
FAKE = '#!/bin/sh\necho "1.0.0"\n'
GONE = ('opencode', 'copilot', 'kimi')


def bot(bot_id, name, provider, **extra):
    return dict(dict(id=bot_id, name=name, color='#14b8a6', shape='circle', instructions='', provider=provider, model='m1', pinned=False, section='團隊', messages=[]), **extra)


class RemovedCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.proc = None
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('cursor-agent',) + GONE:
            cli = self.root / 'bin' / name; cli.write_text(FAKE); cli.chmod(0o755)

    def start(self, data=None):
        if data is not None:
            (self.root / 'data').mkdir(); (self.root / 'data/swarmr.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        if self.proc: self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close()
        self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def test_not_offered_even_when_installed(self):
        self.start()
        picker = {p['id'] for p in self.req('GET', '/api/providers')[1]['providers']}
        accounts = self.req('GET', '/api/accounts')[1]
        listed = {p['id'] for p in accounts['providers']} | {p['id'] for p in accounts.get('catalog') or []}
        for pid in GONE: self.assertNotIn(pid, picker); self.assertNotIn(pid, listed)
        self.assertIn('cursor', picker)
        self.assertIn('agent', {p['id']: p for p in accounts['providers']}['cursor']['loginNote'])  # its installer takes over the agent command
        self.assertEqual(self.req('POST', '/api/bots', {'name': 'K', 'provider': 'kimi'})[0], 400)

    def test_older_data_moves_to_auto_and_says_so(self):
        data = dict(knowledge=[], jobs=[], bots=[bot('b1', '寫手', 'opencode', account='a1', fallbacks=['kimi', 'claude']), bot('b2', '助理', 'copilot'), bot('b3', '工程師', 'claude', account='a2')],
                    deletedBots=[bot('b4', '舊的', 'kimi', deletedAt='')],
                    accounts=[dict(id='a1', name='OpenRouter', provider='opencode', type='key'), dict(id='a2', name='公司', provider='claude', type='login')],
                    settings=dict(provider='opencode', model='opencode/big-pickle', fallbacks=['opencode', 'codex'], autoModels=['claude', 'opencode'],
                                  addedProviders=['codex', 'claude', 'opencode', 'kimi'], hiddenProviders=['copilot'], autoAccounts={'a1': True, 'a2': True}))
        self.start(data)
        state = self.req('GET', '/api/state')[1]
        bots = {b['id']: b for b in state['bots']}
        for bot_id in ('b1', 'b2'): self.assertEqual((bots[bot_id]['provider'], bots[bot_id]['model'], bots[bot_id].get('account')), ('auto', '', ''))
        self.assertEqual(bots['b1']['fallbacks'], ['claude'])
        self.assertEqual((bots['b3']['provider'], bots['b3']['model'], bots['b3']['account']), ('claude', 'm1', 'a2'))  # other CLIs are left as they were
        s = state['settings']
        self.assertNotIn('provider', s); self.assertNotIn('model', s)
        self.assertEqual((s['fallbacks'], s['autoModels'], s['addedProviders'], s['hiddenProviders'], s['autoAccounts']), (['codex'], ['claude'], ['codex', 'claude'], [], {'a2': True}))
        saved = json.loads((self.root / 'data/swarmr.json').read_text(encoding='utf-8'))
        self.assertEqual([a['id'] for a in saved['accounts']], ['a2'])
        self.assertEqual([(b['id'], b['provider']) for b in saved['deletedBots']], [('b4', 'auto')])
        texts = [a['text'] for a in self.req('GET', '/api/activity')[1]['items']]
        note = next(t for t in texts if '自動選擇' in t)
        self.assertIn('寫手', note); self.assertIn('助理', note); self.assertNotIn('工程師', note); self.assertNotIn('舊的', note)
        self.assertIn('OpenCode', note); self.assertIn('Kimi', note)
        self.assertTrue(any('預設提供者' in t and 'Codex' in t for t in texts))

    def test_default_followers_only_removed_auto_list_and_odd_values(self):
        data = dict(knowledge=[], jobs=[], bots=[bot('b1', '跟預設', '', model='opencode/big-pickle'), bot('b2', '跟預設沒選模型', '', model='')],
                    settings=dict(provider='opencode', model='x', autoModels=['opencode'], fallbacks=[{'odd': 1}, 'kimi']))
        self.start(data)
        state = self.req('GET', '/api/state')[1]; bots = {b['id']: b for b in state['bots']}
        self.assertEqual((bots['b1']['provider'], bots['b1']['model']), ('auto', ''))  # it would have sent OpenCode's model to Codex
        self.assertEqual(bots['b2']['provider'], '')  # nothing of OpenCode's: it follows the new default
        self.assertNotIn('autoModels', state['settings'])  # only OpenCode was chosen: back to the usual choice, not to none

    def test_another_mac_naming_a_removed_cli(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_removed_sync', SERVER); m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)
        out = m.sync_clean('bots:' + 'a' * 16, dict(name='寫手', provider='opencode', model='opencode/big-pickle', instructions='', color='#111111', shape='circle', section='團隊'))
        self.assertIsNotNone(out); self.assertEqual((out['provider'], out['model']), ('auto', ''))

    def test_nothing_is_noted_when_no_data_names_them(self):
        self.start(dict(knowledge=[], jobs=[], bots=[bot('b1', '寫手', 'codex')], settings=dict(provider='claude', model='')))
        self.assertEqual(self.req('GET', '/api/state')[1]['bots'][0]['provider'], 'codex')
        self.assertFalse([a for a in self.req('GET', '/api/activity')[1]['items'] if '不再支援' in a['text']])


if __name__ == '__main__': unittest.main()
