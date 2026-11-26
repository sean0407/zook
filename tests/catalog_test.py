# -*- coding: utf-8 -*-
import http.client, importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'secrets').mkdir()
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), ZOOK_NO_BROWSER='1', HOME=str(self.root))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self): self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close(); return resp.status, json.loads(raw)

    def test_every_entry_is_an_official_https_address(self):
        spec = importlib.util.spec_from_file_location('zook_catalog', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        ids = [x['id'] for x in z.CONNECTOR_CATALOG]; self.assertEqual(len(ids), len(set(ids)))
        for item in z.CONNECTOR_CATALOG:
            at = urlsplit(item['url']); self.assertEqual(at.scheme, 'https', item['id']); self.assertFalse(at.username or z._is_local_host(at.hostname), item['id'])
            self.assertIn(item['auth'], ('login', 'open', 'key', 'manual')); self.assertTrue(item['about'] and item['category'])
        self.assertFalse(z.device_may('GET', '/api/connector-catalog')); self.assertFalse(z.device_may('POST', '/api/connector-catalog/notion'))

    def load(self):
        """The backend in this process, with the catalog pointed at a stand-in service on this Mac."""
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        spec = importlib.util.spec_from_file_location('zook_catalog_live', SERVER); z = importlib.util.module_from_spec(spec); spec.loader.exec_module(z)
        class Service(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                msg = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
                if self.headers.get('Authorization') != 'Bearer good-key-12345': self.send_response(401); self.send_header('Content-Length', '0'); self.end_headers(); return
                result = {'tools': []} if msg.get('method') == 'tools/list' else {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 's', 'version': '1'}}
                raw = json.dumps({'jsonrpc': '2.0', 'id': msg.get('id'), 'result': result}).encode()
                self.send_response(200 if 'id' in msg else 202); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        service = ThreadingHTTPServer(('127.0.0.1', 0), Service); threading.Thread(target=service.serve_forever, daemon=True).start(); self.addCleanup(service.server_close); self.addCleanup(service.shutdown)
        os.environ['ZOOK_SECRETS_DIR'] = str(self.root / 'secrets2'); (self.root / 'secrets2').mkdir(); self.addCleanup(os.environ.pop, 'ZOOK_SECRETS_DIR', None)
        z.CONNECTOR_CATALOG[:] = [z._c('svc', 'Svc', '測試', 'http://127.0.0.1:%d/mcp' % service.server_address[1], 'key', '測試。'), z._c('gone', 'Gone', '測試', 'http://127.0.0.1:9/mcp', 'open', '測試。')]
        store = z.Store(self.root / 'data2'); app = type('App', (), {'store': store, 'server_address': ('127.0.0.1', 1)})()
        return z, app, store

    def test_a_wrong_key_or_an_unreachable_service_adds_nothing(self):
        z, app, store = self.load()
        self.assertRaisesRegex(ValueError, '不接受這組金鑰', z.catalog_add, app, 'svc', 'wrong-key-12345'); self.assertRaisesRegex(ValueError, '連不上', z.catalog_add, app, 'gone')
        self.assertEqual(store.data['connectors'], []); self.assertEqual(list((self.root / 'secrets2').iterdir()), [])

    def test_a_good_key_is_added_once_and_a_new_key_replaces_the_old(self):
        z, app, store = self.load()
        first, _ = z.catalog_add(app, 'svc', 'good-key-12345'); again, _ = z.catalog_add(app, 'svc', 'good-key-12345')
        self.assertEqual((len(store.data['connectors']), first['id']), (1, again['id'])); self.assertEqual(len(list((self.root / 'secrets2').iterdir())), 1)
        self.assertEqual(z.secret_get(store.data['connectors'][0]['secretId']), 'good-key-12345'); self.assertEqual(z.secret_get(first['secretId']), '')  # the new key under a new id, the old one gone; self.assertNotIn('good-key-12345', json.dumps(store.data))

    def test_a_failed_save_leaves_no_key_behind(self):
        z, app, store = self.load()
        def broken(): raise OSError('disk full')
        store.save = broken
        self.assertRaises(OSError, z.catalog_add, app, 'svc', 'good-key-12345')
        self.assertEqual(store.data['connectors'], []); self.assertEqual(list((self.root / 'secrets2').iterdir()), [])

    def test_entries_that_cannot_be_linked_yet_and_unknown_ones_are_refused(self):
        self.assertEqual(self.req('POST', '/api/connector-catalog/slack', {})[0], 400); self.assertEqual(self.req('POST', '/api/connector-catalog/nope', {})[0], 404); self.assertEqual(self.req('POST', '/api/connector-catalog/github', {})[0], 400)
        self.assertEqual(self.req('GET', '/api/state')[1]['connectors'], [])


if __name__ == '__main__': unittest.main()
