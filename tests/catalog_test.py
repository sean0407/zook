# -*- coding: utf-8 -*-
import http.client, importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'secrets').mkdir()
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(self.root / 'secrets'), ZOOK_NO_BROWSER='1', HOME=str(self.root))
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

    def test_adding_a_key_connector_keeps_the_key_out_of_the_data_file(self):
        self.assertEqual(self.req('POST', '/api/connector-catalog/github', {})[0], 400)
        status, made = self.req('POST', '/api/connector-catalog/github', {'key': 'ghp_exampleexample123456'}); self.assertEqual((status, made['login']), (200, False))
        self.assertNotIn('ghp_exampleexample123456', (self.root / 'data/swarmr.json').read_text())
        items = {i['id']: i for i in self.req('GET', '/api/connector-catalog')[1]['items']}; self.assertTrue(items['github']['added']); self.assertFalse(items['notion']['added'])
        self.assertEqual(self.req('POST', '/api/connector-catalog/github', {'key': 'ghp_exampleexample123456'})[1]['id'], made['id'])  # not added twice
        self.assertIn(made['id'], self.req('GET', '/api/state')[1]['settings']['sharedMcp'])

    def test_entries_that_cannot_be_linked_yet_and_unknown_ones_are_refused(self):
        self.assertEqual(self.req('POST', '/api/connector-catalog/slack', {})[0], 400); self.assertEqual(self.req('POST', '/api/connector-catalog/nope', {})[0], 404)
        self.assertEqual(self.req('GET', '/api/state')[1]['connectors'], [])


if __name__ == '__main__': unittest.main()
