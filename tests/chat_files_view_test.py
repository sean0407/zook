# -*- coding: utf-8 -*-
"""A group's shared files can be shown in the conversation: each is sent with a type that is safe to show (a picture as a
picture, a web page or SVG only as text), and the list says what kind each file is."""
import http.client, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000') + b'\x00' * 20


class ChatFilesViewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x')
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), PATH='/usr/bin:/bin')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None, headers=None, raw=False):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
        conn.request(method, path, data, dict({'Authorization': 'Bearer ' + self.token}, **(headers or {})))
        resp = conn.getresponse(); out = resp.read(); kind = resp.getheader('Content-Type'); conn.close()
        return resp.status, (out if raw else json.loads(out)), kind

    def test_shared_files_are_shown_safely(self):
        bots = self.req('GET', '/api/state')[1]['bots'][:2]
        group = self.req('POST', '/api/groups', {'name': '團隊', 'botIds': [b['id'] for b in bots]})[1]
        base = '/api/groups/%s/files' % group['id']
        for name, data in (('設計圖v0.1.png', PNG), ('說明.md', '# 標題'.encode()), ('頁面.html', b'<script>alert(1)</script>'), ('圖.svg', b'<svg onload="x()"/>'), ('資料.zip', b'PK')):
            status, _, _ = self.req('POST', base, data, {'X-File-Name': __import__('urllib.parse').parse.quote(name), 'Content-Type': 'application/octet-stream'})
            self.assertLess(status, 300)
        listed = {f['name']: f['kind'] for f in self.req('GET', base)[1]['files']}
        self.assertEqual(listed, {'設計圖v0.1.png': 'image', '說明.md': 'markdown', '頁面.html': 'text', '圖.svg': 'file', '資料.zip': 'file'})
        get = lambda n: self.req('GET', base + '/' + __import__('urllib.parse').parse.quote(n), raw=True)
        self.assertEqual(get('設計圖v0.1.png')[2], 'image/png')
        self.assertEqual(get('說明.md')[2], 'text/plain; charset=utf-8')
        self.assertEqual(get('頁面.html')[2], 'text/plain; charset=utf-8')  # never run as a page in Zook's window
        self.assertEqual(get('圖.svg')[2], 'application/octet-stream')  # like a Bot's own outputs: SVG is only downloaded
        self.assertEqual(get('資料.zip')[2], 'application/octet-stream')


if __name__ == '__main__': unittest.main()
