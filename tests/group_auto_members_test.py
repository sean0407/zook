# -*- coding: utf-8 -*-
"""#218: a group set to 自動 needs a host and at least two members; when its host is deleted or taken out, it goes back to 自由 and says so."""
import http.client, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '#!/bin/sh\nexit 0\n'


class GroupAutoMembers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        (root / 'assets').mkdir(); (root / 'assets/index.html').write_text('x'); (root / 'bin').mkdir()
        for name in ('codex', 'claude'): cli = root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SHELL_ENV='0', ZOOK_SCHEDULE_TICK='3600', ZOOK_SECRETS_DIR=str(root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(root / 'data'), '--assets', str(root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskEngine': True})[0], 200)
        self.bots = {n: self.req('POST', '/api/bots', {'name': n, 'provider': p})[1]['id'] for n, p in (('Alpha', 'codex'), ('Beta', 'claude'), ('Gamma', 'codex'))}

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def create(self, names=('Alpha', 'Beta', 'Gamma'), **fields):
        return self.req('POST', '/api/groups', dict({'botIds': [self.bots[n] for n in names]}, **fields))

    def get(self, gid): return self.req('GET', '/api/groups/' + gid)[1]['group']

    def test_auto_needs_a_host_when_created(self):
        status, body = self.create(hostId='', mode='auto')
        self.assertEqual(status, 400); self.assertIn('主持人', body['error'])
        self.assertEqual(self.create(mode='auto')[0], 400)  # no host named: not 管理員 by default
        status, body = self.create(hostId=self.bots['Alpha'], mode='auto')
        self.assertEqual(status, 201, body); self.assertEqual(body['mode'], 'auto')

    def test_auto_needs_a_host_when_edited(self):
        g = self.create(hostId='', mode='free')[1]
        status, body = self.req('PATCH', '/api/groups/' + g['id'], {'mode': 'auto', 'hostId': ''})
        self.assertEqual(status, 400); self.assertIn('主持人', body['error'])
        self.assertEqual(self.get(g['id'])['mode'], 'free')
        g = self.create(hostId=self.bots['Alpha'], mode='auto')[1]
        status, body = self.req('PATCH', '/api/groups/' + g['id'], {'hostId': ''})
        self.assertEqual(status, 400); self.assertIn('主持人', body['error'])

    def test_auto_needs_two_members(self):
        g = self.create(('Alpha', 'Beta'), hostId=self.bots['Alpha'], mode='free')[1]
        self.req('DELETE', '/api/bots/' + self.bots['Beta'])
        status, body = self.req('PATCH', '/api/groups/' + g['id'], {'mode': 'auto', 'hostId': self.bots['Alpha']})
        self.assertEqual(status, 400); self.assertIn('2 位成員', body['error'])

    def test_deleted_host_turns_auto_back_to_free(self):
        g = self.create(hostId=self.bots['Gamma'], mode='auto')[1]
        self.assertEqual(self.req('DELETE', '/api/bots/' + self.bots['Gamma'])[0], 200)
        found = self.get(g['id'])
        self.assertEqual((found['hostId'], found['mode']), ('', 'free'))
        self.assertTrue(any('改回「自由」' in m['content'] for m in found['messages']), found['messages'])

    def test_host_taken_out_turns_auto_back_to_free(self):
        g = self.create(hostId=self.bots['Gamma'], mode='auto')[1]
        status, body = self.req('PATCH', '/api/groups/' + g['id'], {'botIds': [self.bots['Alpha'], self.bots['Beta']]})
        self.assertEqual(status, 200, body)
        found = self.get(g['id'])
        self.assertEqual((found['hostId'], found['mode']), ('', 'free'))
        self.assertIn('改回「自由」', found['messages'][-1]['content'])

    def test_other_modes_lose_only_the_host(self):
        g = self.create(hostId=self.bots['Gamma'], mode='debate')[1]
        self.req('DELETE', '/api/bots/' + self.bots['Gamma'])
        found = self.get(g['id'])
        self.assertEqual((found['hostId'], found['mode']), ('', 'debate'))
        self.assertNotIn('自由', found['messages'][-1]['content'])

    def test_same_vendor_is_not_blocked(self):
        status, body = self.create(('Alpha', 'Gamma'), hostId=self.bots['Alpha'], mode='auto')
        self.assertEqual(status, 201, body)


if __name__ == '__main__':
    unittest.main()
