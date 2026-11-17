import http.client
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))
import gmail_mcp
import runtime


class GmailMessageTest(unittest.TestCase):
    """How the built-in Gmail connector builds and reads messages (no network)."""
    def test_addresses_are_checked(self):
        self.assertEqual(gmail_mcp.addresses(['Amy <amy@example.com>', 'bob@example.org'], 'to'), ['amy@example.com', 'bob@example.org'])
        self.assertEqual(gmail_mcp.addresses('a@example.com; b@example.com', 'cc'), ['a@example.com', 'b@example.com'])
        for bad in (['not-an-address'], ['a@b'], ['x@example.com\nBcc: evil@example.com']):
            with self.assertRaises(gmail_mcp.GmailError): gmail_mcp.addresses(bad, 'to')

    def test_compose_builds_a_plain_message(self):
        with patch.object(gmail_mcp, 'ADDRESS', 'me@gmail.com'):
            message, recipients = gmail_mcp.compose({'to': ['amy@example.com'], 'cc': ['bob@example.com'], 'subject': '會議  記錄', 'body': '你好\n第二行'})
        self.assertEqual((message['From'], message['To'], message['Cc'], message['Subject']), ('me@gmail.com', 'amy@example.com', 'bob@example.com', '會議 記錄'))
        self.assertEqual(recipients, ['amy@example.com', 'bob@example.com']); self.assertIn('第二行', message.get_content())
        for missing in ({'subject': 's', 'body': 'b'}, {'to': ['a@example.com'], 'body': 'b'}, {'to': ['a@example.com'], 'subject': 's', 'body': ' '}):
            with self.assertRaises(gmail_mcp.GmailError): gmail_mcp.compose(missing)

    def test_html_mail_is_read_as_text(self):
        import email, email.policy
        raw = b'From: a@example.com\r\nSubject: hi\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<style>p{color:red}</style><p>Hello &amp; welcome</p><p>Line two</p>'
        self.assertEqual(gmail_mcp.body_text(email.message_from_bytes(raw, policy=email.policy.default)), 'Hello & welcome\nLine two')

    def test_search_result_summary(self):
        meta = '3 (X-GM-THRID 1790000000000000001 X-GM-MSGID 1790000000000000002 UID 77 FLAGS (\\Seen) BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)] {90}'
        item = gmail_mcp.summary(meta, b'From: Amy <amy@example.com>\r\nTo: me@gmail.com\r\nSubject: =?utf-8?b?5L2g5aW9?=\r\nDate: Mon, 16 Nov 2026 10:00:00 +0800\r\n\r\n')
        self.assertEqual((item['id'], item['thread_id'], item['subject'], item['unread']), ('1790000000000000002', '1790000000000000001', '你好', False))

    def test_sending_always_needs_approval(self):
        self.assertTrue(runtime.is_dangerous_name('send_email'))  # asked even when 主動性 is 全部允許
        self.assertFalse(runtime.is_dangerous_name('create_draft')); self.assertFalse(runtime.is_dangerous_name('search_emails'))
        hints = {schema['name']: schema['annotations'].get('readOnlyHint') for schema, _ in gmail_mcp.TOOLS}
        self.assertEqual(hints, {'search_emails': True, 'read_email': True, 'create_draft': False, 'send_email': False})


class GmailSetupTest(unittest.TestCase):
    """Connecting Gmail in Zook: the password goes to the secret store, never to the data file or the interface."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'home').mkdir()
        env = dict(os.environ, HOME=str(self.root / 'home'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(self.root), ZOOK_GMAIL_SKIP_CHECK='1')
        self.proc = subprocess.Popen([sys.executable, str(BACKEND / 'server.py'), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5)
        self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def gmail(self):
        return next(m for m in self.req('GET', '/api/integrations')[1]['mcp'] if m['id'] == 'builtin:gmail')

    def test_connect_use_and_disconnect(self):
        self.assertEqual((self.gmail()['source'], self.gmail()['needsSetup']), ('builtin', True))
        for bad in ({'address': 'not-an-address', 'password': 'abcdabcdabcdabcd'}, {'address': 'me@gmail.com', 'password': 'my-login-password'}, {'address': 'me@gmail.com'}):
            self.assertEqual(self.req('POST', '/api/gmail', bad)[0], 400)
        self.assertEqual(self.req('POST', '/api/gmail', {'address': 'me@gmail.com', 'password': 'abcd efgh ijkl mnop'})[0], 200)  # pasted with Google's spaces
        item = self.gmail(); state = self.req('GET', '/api/state')[1]
        self.assertEqual((item['needsSetup'], item['address']), (False, 'me@gmail.com')); self.assertIn('builtin:gmail', state['settings']['sharedMcp'])
        self.assertNotIn('abcdefghijklmnop', json.dumps(state) + json.dumps(self.req('GET', '/api/integrations')[1]) + (self.root / 'data/swarmr.json').read_text())
        test = self.req('POST', '/api/mcp/builtin:gmail/test', {})[1]
        self.assertEqual((test['status'], sorted(t['name'] for t in test['tools'])), ('ready', ['create_draft', 'read_email', 'search_emails', 'send_email']))
        self.assertEqual(self.req('DELETE', '/api/gmail')[0], 200)
        self.assertTrue(self.gmail()['needsSetup']); self.assertNotIn('builtin:gmail', self.req('GET', '/api/state')[1]['settings']['sharedMcp'])


if __name__ == '__main__': unittest.main()
