# -*- coding: utf-8 -*-
import http.client, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


class OutputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name)); (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x')
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), HOME=str(self.root), PATH='/usr/bin:/bin')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'Maker', 'provider': 'codex'})[1]; self.work = self.root / 'data/workspaces' / self.bot['id']; self.work.mkdir(parents=True, exist_ok=True)

    def tearDown(self): self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None, raw=False):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); kind = resp.getheader('Content-Type'); conn.close()
        return (resp.status, data, kind) if raw else (resp.status, json.loads(data))

    def outputs(self): return self.req('GET', '/api/bots/%s/outputs' % self.bot['id'])[1]['outputs']

    def test_lists_working_files_but_not_attachments_links_or_hidden_files(self):
        (self.work / 'report.md').write_text('# 報告'); (self.work / 'sub').mkdir(); (self.work / 'sub/data.csv').write_text('a,b'); (self.work / '.secret').write_text('x')
        (self.work / 'attachments').mkdir(); (self.work / 'attachments/in.txt').write_text('x'); outside = self.root / 'private.txt'; outside.write_text('private'); (self.work / 'leak.txt').symlink_to(outside)
        found = {o['name']: o for o in self.outputs()}; self.assertEqual(sorted(found), ['data.csv', 'report.md']); self.assertEqual(found['report.md']['kind'], 'markdown')

    def test_preview_types_never_run_as_pages(self):
        (self.work / 'page.html').write_text('<script>alert(1)</script>'); (self.work / 'pic.svg').write_text('<svg onload="x"/>'); (self.work / 'doc.pdf').write_bytes(b'%PDF-1.4')
        by = {o['name']: o for o in self.outputs()}
        get = lambda name: self.req('GET', '/api/bots/%s/outputs/%s' % (self.bot['id'], by[name]['id']), raw=True)
        self.assertTrue(get('page.html')[2].startswith('text/plain')); self.assertEqual(get('pic.svg')[2], 'application/octet-stream'); self.assertEqual(get('doc.pdf')[2], 'application/pdf')

    def test_unknown_ids_and_other_paths_are_refused(self):
        self.assertEqual(self.req('GET', '/api/bots/%s/outputs/%s' % (self.bot['id'], '0' * 20), raw=True)[0], 404)
        self.assertEqual(self.req('GET', '/api/bots/%s/outputs/..%%2F..%%2Fswarmr.json' % self.bot['id'], raw=True)[0], 404)


if __name__ == '__main__': unittest.main()
