# -*- coding: utf-8 -*-
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = '''#!/usr/bin/env python3
import os, sys
if len(sys.argv) > 1 and sys.argv[1] != 'exec': print('Logged in using ChatGPT'); sys.exit(0)
open(os.environ['PROMPT_LOG'], 'w').write(sys.stdin.read()); print('ok')
'''


class ProjectsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name)); self.log = self.root / 'prompt.txt'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir(); (self.root / 'shared').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', PROMPT_LOG=str(self.log), HOME=str(self.root))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.a = self.req('POST', '/api/bots', {'name': 'Ann', 'provider': 'codex'})[1]; self.b = self.req('POST', '/api/bots', {'name': 'Ben', 'provider': 'codex'})[1]
        self.note = self.req('POST', '/api/knowledge', {'title': '上市日', 'content': '十二月一日', 'botId': self.b['id']})[1]

    def tearDown(self): self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close(); return resp.status, json.loads(raw)

    def ask(self, bot):
        job = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': '進度？'})[1]['jobId']
        for _ in range(100):
            if self.req('GET', '/api/jobs/' + job)[1]['status'] != 'running': break
            time.sleep(.1)
        return self.log.read_text()

    def test_project_note_folder_and_knowledge_reach_only_its_bots(self):
        status, project = self.req('POST', '/api/projects', {'name': '新品上市', 'note': '重點是通路陳列', 'folder': str(self.root / 'shared'), 'botIds': [self.a['id']], 'knowledgeIds': [self.note['id']]}); self.assertEqual(status, 201, project)
        inside = self.ask(self.a)
        for text in ('專案「新品上市」', '重點是通路陳列', str(self.root / 'shared'), '十二月一日'): self.assertIn(text, inside)
        outside = self.ask(self.b); self.assertNotIn('新品上市', outside); self.assertNotIn('通路陳列', outside)

    def test_a_bot_is_in_one_project_and_deleting_keeps_everything(self):
        one = self.req('POST', '/api/projects', {'name': '甲', 'botIds': [self.a['id'], self.b['id']]})[1]; two = self.req('POST', '/api/projects', {'name': '乙', 'botIds': [self.a['id']]})[1]
        state = self.req('GET', '/api/state')[1]; by = {p['name']: p for p in state['projects']}
        self.assertEqual((by['甲']['botIds'], by['乙']['botIds']), ([self.b['id']], [self.a['id']]))
        self.assertEqual(self.req('DELETE', '/api/projects/' + two['id'])[0], 200); state = self.req('GET', '/api/state')[1]
        self.assertEqual(len(state['projects']), 1); self.assertTrue(any(b['id'] == self.a['id'] for b in state['bots'])); self.assertTrue((self.root / 'shared').is_dir())
        self.req('DELETE', '/api/knowledge/' + self.note['id']); self.assertEqual(self.req('DELETE', '/api/bots/' + self.b['id'])[0], 200); self.assertEqual(self.req('GET', '/api/state')[1]['projects'][0]['botIds'], [])

    def test_bad_projects_are_refused(self):
        self.req('POST', '/api/projects', {'name': '甲'})
        for body in ({'name': ''}, {'name': '甲'}, {'name': '丙', 'folder': '/no/such/folder'}, {'name': '丁', 'botIds': ['nobody']}): self.assertEqual(self.req('POST', '/api/projects', body)[0], 400, body)


if __name__ == '__main__': unittest.main()
