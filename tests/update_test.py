import importlib.util
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import server


class UpdateCheckTest(unittest.TestCase):
    """What Zook concludes from a release listing. Downloading and swapping the app is rehearsed against a real release."""
    def serve(self, release):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                raw = json.dumps(release).encode(); self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), H); threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown); self.addCleanup(httpd.server_close)
        return 'http://127.0.0.1:%d/latest' % httpd.server_address[1]

    def updater(self, release, current='0.4.1'):
        with patch.dict(os.environ, {'ZOOK_UPDATE_URL': self.serve(release)}):
            u = server.Updater(lambda: False); u.current = current; u.check(force=True)
        return u

    def test_versions_compare_by_number(self):
        self.assertTrue(server.version_tuple('v0.10.0') > server.version_tuple('0.9.9'))
        self.assertIsNone(server.version_tuple('0.4')); self.assertIsNone(server.version_tuple('0.4.1; rm -rf /'))

    def test_newer_release_from_this_project_is_offered(self):
        link = 'https://github.com/%s/releases/download/v0.5.0/Zook-0.5.0.dmg' % server.UPDATE_REPO
        view = self.updater({'tag_name': 'v0.5.0', 'body': 'notes', 'assets': [{'name': 'Zook-0.5.0.dmg', 'browser_download_url': link, 'digest': 'sha256:ab', 'size': 5}]}).view()
        self.assertEqual((view['latest'], view['available'], view['notes']), ('0.5.0', True, 'notes'))
        self.assertFalse(view['canInstall'])  # run from source, there is no app to replace

    def test_same_or_older_release_is_not_offered(self):
        link = 'https://github.com/%s/releases/download/v0.4.1/Zook-0.4.1.dmg' % server.UPDATE_REPO
        for tag in ('v0.4.1', 'v0.3.0', 'nightly'):
            self.assertFalse(self.updater({'tag_name': tag, 'assets': [{'name': 'Zook.dmg', 'browser_download_url': link}]}).view()['available'])

    def test_download_from_anywhere_else_is_refused(self):
        for link in ('https://github.com/someone-else/zook/releases/download/v9.0.0/Zook.dmg', 'https://evil.example/Zook.dmg', 'http://github.com/%s/releases/download/v9.0.0/Zook.dmg' % server.UPDATE_REPO):
            u = self.updater({'tag_name': 'v9.0.0', 'assets': [{'name': 'Zook.dmg', 'browser_download_url': link}]})
            self.assertFalse(u.view()['available'])
            with self.assertRaises(RuntimeError): u.download()

    def test_unreachable_server_is_not_an_update(self):
        with patch.dict(os.environ, {'ZOOK_UPDATE_URL': 'http://127.0.0.1:9/none'}):
            u = server.Updater(lambda: False); u.check(force=True)
        self.assertFalse(u.view()['available']); self.assertTrue(u.view()['error'])


if __name__ == '__main__': unittest.main()
