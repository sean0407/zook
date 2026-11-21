# -*- coding: utf-8 -*-
"""A whole team from one sentence, and the job title each Bot carries."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
ROLE = lambda name, title, **more: dict(dict(name=name, jobTitle=title, duty='負責' + name, deliverable=name + '報告', worksWith='統籌', notDoing='其他人的事', persona='務實'), **more)
DRAFT = dict(team='香氛品牌', coordinator=ROLE('統籌', '專案統籌'), members=[ROLE('研發', '產品研發'), ROLE('行銷', '行銷企劃'), ROLE('財務', '財務管理')])
# A fake Claude that answers with reply.txt.
CLAUDE = '''#!/usr/bin/env python3
import json, os, sys
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)  # Zook asking what this CLI can do
here = os.path.dirname(sys.argv[0])
open(os.path.join(here, 'prompt.txt'), 'w').write(sys.stdin.read())
print(json.dumps({'type': 'result', 'result': open(os.path.join(here, 'reply.txt')).read(), 'is_error': False}))
'''


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_team_draft', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class ParseTest(unittest.TestCase):
    def test_draft_is_checked_field_by_field(self):
        m = load()
        team = m.parse_team('好的，這是規劃：\n```json\n' + json.dumps(DRAFT, ensure_ascii=False) + '\n```', existing=['行銷'])
        self.assertEqual((team['team'], team['coordinator']['name'], [r['name'] for r in team['members']]), ('香氛品牌', '統籌', ['研發', '行銷2', '財務']))  # a name already in use gets a number
        self.assertTrue(all(r[k] for r in [team['coordinator']] + team['members'] for k in ('name', 'jobTitle', 'duty', 'deliverable', 'worksWith', 'notDoing')))
        long = m.parse_team(json.dumps(dict(DRAFT, members=[ROLE('研' * 50, '職' * 50, duty='x' * 999)] + DRAFT['members'][1:] + [ROLE('法務', '行銷企劃')])))
        self.assertEqual((len(long['members'][0]['name']), len(long['members'][0]['jobTitle']), len(long['members'][0]['duty'])), (20, 12, 200))
        self.assertEqual(len({r['jobTitle'] for r in long['members']}), 4)  # the same title twice is not kept
        for bad in ('不是 JSON', '{}', json.dumps(dict(DRAFT, members=DRAFT['members'][:2])), json.dumps(dict(DRAFT, coordinator=dict(name='')))):
            self.assertRaises(ValueError, m.parse_team, bad)
        self.assertEqual(len(m.parse_team(json.dumps(dict(DRAFT, members=[ROLE('成員%d' % i, '職稱%d' % i) for i in range(12)])))['members']), 7)

    def test_job_title_decides_the_role_first(self):
        m = load()
        self.assertEqual(m.auto_role(dict(name='小美', jobTitle='財務管理')), 'analysis'); self.assertEqual(m.auto_role(dict(name='財務長', jobTitle='後端工程師')), 'code')
        self.assertIn('職稱是「行銷企劃」', m.identity_block(dict(name='小美', jobTitle='行銷企劃'))); self.assertNotIn('職稱', m.identity_block(dict(name='小美')))


class TeamTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/claude'; cli.write_text(CLAUDE); cli.chmod(0o755)
        (self.root / 'bin/reply.txt').write_text(json.dumps(DRAFT, ensure_ascii=False), encoding='utf-8')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'provider': 'claude'})

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def state(self): return self.req('GET', '/api/state')[1]

    def test_job_title_field(self):
        status, bot = self.req('POST', '/api/bots', {'name': '小美', 'jobTitle': ' 行銷企劃 '})
        self.assertEqual((status, bot['jobTitle']), (201, '行銷企劃'))
        self.assertEqual(self.req('PATCH', '/api/bots/' + bot['id'], {'jobTitle': '字' * 13})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/bots/' + bot['id'], {'jobTitle': ''})[1]['jobTitle'], '')

    def test_draft_creates_nothing_and_create_makes_everything(self):
        before = self.state()
        status, draft = self.req('POST', '/api/team/draft', {'goal': '做一個香氛品牌'})
        self.assertEqual(status, 200, draft); self.assertEqual((draft['team'], draft['goal'], len(draft['members'])), ('香氛品牌', '做一個香氛品牌', 3))
        self.assertIn('做一個香氛品牌', (self.root / 'bin/prompt.txt').read_text(encoding='utf-8'))
        after = self.state()
        self.assertEqual((len(after['bots']), len(after['groups']), after['jobs']), (len(before['bots']), len(before['groups']), before['jobs']))
        roles = [draft['coordinator']] + draft['members']; roles[1]['name'] = '產品研發組'
        status, made = self.req('POST', '/api/team', {'team': draft['team'], 'goal': draft['goal'], 'roles': roles, 'kickoff': False})
        self.assertEqual(status, 201, made)
        now = self.state(); new = [b for b in now['bots'] if b['id'] in {x['id'] for x in made['bots']}]
        self.assertEqual([(b['name'], b['jobTitle'], b['section'], b['provider']) for b in new], [('統籌', '專案統籌', '香氛品牌', 'auto'), ('產品研發組', '產品研發', '香氛品牌', 'auto'), ('行銷', '行銷企劃', '香氛品牌', 'auto'), ('財務', '財務管理', '香氛品牌', 'auto')])
        self.assertEqual(len({(b['color'], b['shape']) for b in new}), 4)
        group = next(g for g in now['groups'] if g['id'] == made['group']['id'])
        self.assertEqual((group['name'], group['botIds'], group['hostId'], group['status']), ('香氛品牌', [b['id'] for b in new], new[0]['id'], 'idle'))
        text = new[2]['instructions']
        for part in ('團隊目標：做一個香氛品牌', '負責：負責行銷', '主要交付物：行銷報告', '不負責：其他人的事', '統籌（專案統籌），統籌', '產品研發組（產品研發）'): self.assertIn(part, text)
        self.assertIn('香氛品牌', now['settings']['sections'])

    def test_nothing_is_left_behind_when_it_cannot_be_made(self):
        roles = [DRAFT['coordinator']] + DRAFT['members']; count = len(self.state()['bots'])
        for body in (dict(team='x', goal='g', roles=roles[:3]), dict(team='x', goal='g', roles=roles + [ROLE('', '')]), dict(team='', goal='g', roles=roles), dict(team='x', goal='g', roles=[roles[0]] * 4), dict(team='x', goal='g', roles='no')):
            self.assertEqual(self.req('POST', '/api/team', body)[0], 400, body)
        self.assertEqual(self.req('POST', '/api/team', dict(team='甲', goal='g', roles=roles))[0], 201)
        self.assertEqual(self.req('POST', '/api/team', dict(team='乙', goal='g', roles=roles))[0], 400)  # the names are taken now
        self.assertEqual(len(self.state()['bots']), count + 4)
        (self.root / 'bin/reply.txt').write_text('抱歉我不會', encoding='utf-8')
        self.assertEqual(self.req('POST', '/api/team/draft', {'goal': '隨便'})[0], 400)
        self.assertEqual(self.req('POST', '/api/team/draft', {'goal': ''})[0], 400)

    def test_kickoff_starts_the_discussion(self):
        (self.root / 'bin/reply.txt').write_text('我的起步清單：一、二、三', encoding='utf-8')
        roles = [DRAFT['coordinator']] + DRAFT['members']
        status, made = self.req('POST', '/api/team', dict(team='甲', goal='g', roles=roles, kickoff=True))
        self.assertEqual(status, 201, made)
        group = self.req('GET', '/api/groups/' + made['group']['id'])[1]['group']
        self.assertEqual(group['messages'][0]['role'], 'user'); self.assertIn('起步清單', group['messages'][0]['content'])
        self.req('POST', '/api/groups/%s/stop' % made['group']['id'], {})


if __name__ == '__main__': unittest.main()
