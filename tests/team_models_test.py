# -*- coding: utf-8 -*-
"""A team from one sentence gets the models and thinking levels the sentence names, and says so when one cannot be used here."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, types, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
ROLE = lambda name, title, **more: dict(dict(name=name, jobTitle=title, duty='負責' + name, deliverable=name + '成品', worksWith='統籌', notDoing='其他人的事', persona='務實'), **more)
GOAL = '做新品上市，文案用 Claude、設計用 Codex、查核用 Grok、查核要深入'
# The model named 文案 and 設計 in its JSON but forgot 查核: Zook reads that one from the sentence itself.
DRAFT = dict(team='新品上市', coordinator=ROLE('統籌', '專案統籌'),
             members=[ROLE('文案', '文案企劃', model='Claude'), ROLE('設計', '視覺設計', model='codex', effort=''), ROLE('查核', '事實查核')])
CLAUDE = '''#!/usr/bin/env python3
import json, os, sys
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)
here = os.path.dirname(sys.argv[0])
sys.stdin.read()
print(json.dumps({'type': 'result', 'result': open(os.path.join(here, 'reply.txt')).read(), 'is_error': False}))
'''
CODEX = '#!/bin/sh\nexit 0\n'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_team_models', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class ParseTest(unittest.TestCase):
    def test_named_model_and_level_are_read(self):
        m = load()
        team = m.parse_team(json.dumps(DRAFT, ensure_ascii=False))
        self.assertEqual([(r.get('wanted'), r.get('effort')) for r in team['members']], [('claude', ''), ('codex', ''), ('', '')])
        self.assertEqual(m.team_named_provider('用 ChatGPT 寫'), 'codex'); self.assertEqual(m.team_named_provider('沒有指定'), '')
        self.assertEqual((m.team_effort('深入'), m.team_effort('high'), m.team_effort('隨便')), ('deep', 'deep', ''))
        self.assertIn('model', m.TEAM_ASK)

    def test_sentence_is_read_clause_by_clause(self):
        m = load()
        wishes = lambda goal: [(k, v, subject) for k, v, _, subject in m.team_sentence_wishes(goal)]
        self.assertEqual(wishes(GOAL), [('wanted', 'claude', '文案'), ('wanted', 'codex', '設計'), ('wanted', 'grok', '查核'), ('effort', 'deep', '查核')])
        self.assertEqual(wishes('文案、設計用 Claude'), [('wanted', 'claude', '文案'), ('wanted', 'claude', '設計')])
        self.assertEqual(wishes('做 ChatGPT 外掛，快速上市，查核標準要嚴'), [])  # a product or a plain word, not a choice
        roles = [ROLE('文案', '文案企劃'), ROLE('設計', '視覺設計')]
        self.assertIs(m._team_role_for('並讓文案', roles), roles[0]); self.assertIsNone(m._team_role_for('大家', roles))

    def test_signed_out_is_a_problem(self):
        m = load()
        store = types.SimpleNamespace(data={'settings': {'addedProviders': ['claude', 'codex']}, 'autoStatus': {'claude': {'signedIn': False}}})
        m.find_cli = lambda pid: '/bin/' + pid
        self.assertIn('還沒登入', m.team_provider_problem(store, 'claude')); self.assertEqual(m.team_provider_problem(store, 'codex'), '')
        m.find_cli = lambda pid: None
        self.assertIn('沒有安裝', m.team_provider_problem(store, 'codex'))


class TeamModelsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir(); (self.root / 'home').mkdir()
        for name, text in (('claude', CLAUDE), ('codex', CODEX)):
            cli = self.root / 'bin' / name; cli.write_text(text); cli.chmod(0o755)
        self.reply(DRAFT)
        # A home of its own: a Grok or Cursor installed on this Mac is not seen.
        env = dict(os.environ, HOME=str(self.root / 'home'), PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1',
                   ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'provider': 'claude'}); self.req('POST', '/api/accounts/grok/add', {})  # Grok is added but not installed

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def reply(self, draft): (self.root / 'bin/reply.txt').write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def test_named_models_are_used_and_a_missing_one_is_asked(self):
        status, draft = self.req('POST', '/api/team/draft', {'goal': GOAL})
        self.assertEqual(status, 200, draft)
        lead, copy, design, check = [draft['coordinator']] + draft['members']
        self.assertEqual((lead['provider'], copy['provider'], design['provider']), ('auto', 'claude', 'codex'))
        self.assertEqual((check['provider'], check['effort']), ('', 'deep'))  # Grok is named but not installed here: the user picks
        self.assertIn('Grok', check['problem']); self.assertIn('沒有安裝', check['problem'])
        choices = {c['id']: c for c in draft['choices']}
        self.assertEqual(choices['claude']['problem'], ''); self.assertIn('沒有安裝', choices['grok']['problem']); self.assertIn('auto', choices)
        roles = [lead, copy, design, check]
        body = lambda: dict(team=draft['team'], goal=draft['goal'], roles=roles, kickoff=False)
        status, err = self.req('POST', '/api/team', body()); self.assertEqual(status, 400); self.assertIn('查核', err['error'])
        check['provider'] = 'grok'
        status, err = self.req('POST', '/api/team', body()); self.assertEqual(status, 400); self.assertIn('Grok', err['error'])
        check['provider'] = 'claude'
        status, made = self.req('POST', '/api/team', body()); self.assertEqual(status, 201, made)
        bots = {b['id']: b for b in self.req('GET', '/api/state')[1]['bots']}
        new = [bots[b['id']] for b in made['bots']]
        self.assertEqual([(b['name'], b['provider'], b.get('effort', '')) for b in new[1:]], [('文案', 'claude', ''), ('設計', 'codex', ''), ('查核', 'claude', 'deep')])
        self.assertTrue(new[1].get('gateFull'))  # made by the user on this Mac, like a Bot made in 新增 Bot
        self.assertNotIn('autoAssigned', new[1])

    def test_one_model_for_two_roles_and_no_false_alarms(self):
        status, draft = self.req('POST', '/api/team/draft', {'goal': '做 ChatGPT 外掛並快速上市，文案、設計用 Claude'})
        self.assertEqual(status, 200, draft)
        self.assertEqual([(r['name'], r['provider'], r['effort']) for r in draft['members']], [('文案', 'claude', ''), ('設計', 'claude', ''), ('查核', 'auto', '')])
        self.assertEqual(draft['warnings'], [])  # the model's own 「codex」 for 設計 is overruled by the sentence

    def test_a_named_model_given_to_nobody_is_said(self):
        self.reply(dict(DRAFT, members=[ROLE('文案', '文案企劃'), ROLE('設計', '視覺設計'), ROLE('業務', '通路業務')]))
        status, draft = self.req('POST', '/api/team/draft', {'goal': '做新品上市，最後由大家用 Codex 把關'})
        self.assertEqual(status, 200, draft)
        self.assertTrue(any('Codex' in w for w in draft['warnings']), draft['warnings'])
        self.assertEqual({r['provider'] for r in draft['members']}, {'auto'})
        roles = [draft['coordinator']] + draft['members']
        roles[1]['effort'] = 'nonsense'
        self.assertEqual(self.req('POST', '/api/team', dict(team='甲', goal='g', roles=roles))[0], 400)
        roles[1]['effort'] = 'fast'; roles[2]['provider'] = 'gemini'
        status, err = self.req('POST', '/api/team', dict(team='甲', goal='g', roles=roles)); self.assertEqual(status, 400, err)


if __name__ == '__main__': unittest.main()
