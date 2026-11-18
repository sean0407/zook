# -*- coding: utf-8 -*-
"""B2: files and screenshots attached to a message."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from urllib.parse import quote

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CODEX = '''#!/usr/bin/env python3
import os, sys
s = sys.stdin.read()
here = os.path.dirname(sys.argv[0])
open(os.path.join(here, 'codex.args'), 'w').write('\\n'.join(sys.argv[1:]))
open(os.path.join(here, 'codex.prompt'), 'w').write(s)
print('ok')
'''
PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000') + b'\\x00' * 20


class AttachmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'Tester', 'provider': 'codex'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path, body, dict({'Authorization': 'Bearer ' + self.token}, **(headers or {})))
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, resp.getheader('Content-Type'), data

    def req(self, method, path, body=None):
        status, _, data = self.raw(method, path, json.dumps(body).encode() if body is not None else None)
        return status, json.loads(data)

    def upload(self, name, data):
        status, _, out = self.raw('POST', '/api/uploads', data, {'X-File-Name': quote(name), 'Content-Type': 'application/octet-stream'})
        return status, json.loads(out)

    def wait_job(self, job_id):
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.2)
        self.fail('no reply')

    def test_upload_send_and_read_back(self):
        status, image = self.upload('螢幕截圖 1.png', PNG)
        self.assertEqual((status, image['name'], image['kind'], image['size']), (201, '螢幕截圖 1.png', 'image', len(PNG)))
        status, doc = self.upload('../報告.txt', '內容'.encode())
        self.assertEqual((doc['name'], doc['kind']), ('報告.txt', 'file'))  # no folders in names
        status, ctype, data = self.raw('GET', '/api/uploads/' + image['id'])
        self.assertEqual((status, ctype, data), (200, 'image/png', PNG))
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '看看這張圖', 'attachments': [image['id'], doc['id']]})
        self.assertEqual(status, 202, sent)
        self.wait_job(sent['jobId'])
        folder = self.root / 'data/workspaces' / self.bot['id'] / 'attachments'
        files = sorted(p.name for p in folder.iterdir())
        self.assertEqual(len(files), 2)
        self.assertEqual((folder / next(f for f in files if f.endswith('.png'))).read_bytes(), PNG)
        args = (self.root / 'bin/codex.args').read_text().splitlines()
        self.assertEqual(args[:2], ['exec', '-i']); self.assertTrue(args[2].endswith('.png'))  # Codex sees the image itself
        prompt = (self.root / 'bin/codex.prompt').read_text()
        self.assertIn('報告.txt', prompt); self.assertIn(str(folder), prompt)
        asked = next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])['messages'][0]
        self.assertEqual([a['name'] for a in asked['attachments']], ['螢幕截圖 1.png', '報告.txt'])

    def test_limits(self):
        status, _, _ = self.raw('POST', '/api/uploads', b'x', {'X-File-Name': 'big.bin', 'Content-Length': str(20 * 1024 * 1024 + 1)})
        self.assertEqual(status, 413)
        ids = [self.upload('f%d.txt' % i, b'x')[1]['id'] for i in range(11)]
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'x', 'attachments': ids})[0], 400)
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'x', 'attachments': ['0' * 32]})[0], 400)
        self.assertEqual(self.raw('GET', '/api/uploads/' + '../swarmr.json')[0], 404)
        # a message may be only attachments
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '', 'attachments': ids[:1]})
        self.assertEqual(status, 202)

    def test_group_members_all_get_the_file(self):
        other = self.req('POST', '/api/bots', {'name': 'Second', 'provider': 'codex'})[1]
        group = self.req('POST', '/api/groups', {'name': 'G', 'botIds': [self.bot['id'], other['id']]})[1]
        doc = self.upload('資料.csv', b'a,b\n1,2\n')[1]
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '請看資料', 'attachments': [doc['id']]})[0], 202)
        end = time.time() + 15
        while time.time() < end and next(g for g in self.req('GET', '/api/state')[1]['groups'] if g['id'] == group['id'])['status'] == 'running': time.sleep(0.2)
        for bot in (self.bot, other):
            self.assertEqual(len(list((self.root / 'data/workspaces' / bot['id'] / 'attachments').iterdir())), 1)
        self.assertIn('資料.csv', (self.root / 'bin/codex.prompt').read_text())


if __name__ == '__main__': unittest.main()
