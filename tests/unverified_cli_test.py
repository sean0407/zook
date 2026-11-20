# -*- coding: utf-8 -*-
"""Cursor, GitHub Copilot and Kimi: installed and signed in to from Zook, but not yet verified for replies, so no Bot can use them."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
FAKE = '#!/bin/sh\necho "$0 $*" >> "$(dirname "$0")/called.log"\necho "1.0.0"\n'


class UnverifiedCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('cursor-agent', 'copilot', 'kimi'):
            cli = self.root / 'bin' / name; cli.write_text(FAKE); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def test_shown_for_install_and_sign_in_only(self):
        picker = {p['id']: p for p in self.req('GET', '/api/providers')[1]['providers']}
        found = {p['id']: p for p in self.req('GET', '/api/accounts')[1]['providers']}
        for pid in ('cursor', 'copilot', 'kimi'):
            p = found[pid]
            self.assertTrue(picker[pid]['installed']); self.assertFalse(picker[pid]['chat']); self.assertFalse(p['chat']); self.assertTrue(p['terminalLogin'])
            self.assertEqual(p['status'], 'installed')  # whether it is signed in is not claimed
            self.assertIn('還沒驗證', p['loginNote'])
        self.assertIn('agent', found['cursor']['loginNote'])  # its installer takes over the agent command
        self.assertTrue(picker['codex']['chat'])

    def test_a_bot_on_one_cannot_reply(self):
        bot = self.req('POST', '/api/bots', {'name': 'K', 'provider': 'kimi'})[1]
        sent = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': 'hi'})[1]
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            if job['status'] != 'running': break
            time.sleep(0.1)
        self.assertEqual(job['status'], 'failed'); self.assertIn('還沒驗證', job['error'])
        self.assertNotIn('-p', (self.root / 'bin/called.log').read_text() if (self.root / 'bin/called.log').exists() else '')  # it was never asked anything


if __name__ == '__main__': unittest.main()
