# -*- coding: utf-8 -*-
"""Remote access: what the backend allows a paired device to do, pairing rules, and (when the local relay
and the zook-remote program are available) the whole path device -> relay -> Mac."""
import base64, hashlib, http.client, importlib.util, json, os, socket, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_remote_test', SERVER)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
TOOL = Path(os.environ.get('ZOOK_REMOTE_TOOL') or ROOT / 'build/Zook.app/Contents/MacOS/zook-remote')
RELAY = os.environ.get('ZOOK_TEST_RELAY', 'ws://127.0.0.1:8799')


def relay_up():
    host, port = RELAY.split('://')[1].split(':')
    try:
        with socket.create_connection((host, int(port)), timeout=1): return True
    except OSError: return False


class BackendRulesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = m.Store(Path(self.temp.name))
        self.app = m.App(('127.0.0.1', 0), self.store, self.temp.name, 'local-token')
        self.app.bridge_token = 'bridge-token'
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.port = self.app.server_address[1]
        self.key = base64.b64encode(b'k' * 32).decode(); self.device = hashlib.sha256(b'k' * 32).hexdigest()[:32]

    def tearDown(self):
        self.app.shutdown(); self.app.server_close(); self.temp.cleanup()

    def req(self, method, path, body=None, token='local-token', device=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Authorization': 'Bearer ' + token}
        if device is not None: headers['X-Zook-Device'] = device
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def pair(self):
        self.app.pairing = dict(secret='one-time', expiresAt=time.time() + 60, lookups=0)
        return self.req('POST', '/api/remote/bridge/paired', {'id': self.device, 'publicKey': self.key, 'name': 'iPhone', 'secret': 'one-time'}, token='bridge-token')

    def test_off_by_default(self):
        self.assertEqual(self.store.data['settings']['remote'], {'enabled': False, 'relayUrl': ''})
        self.assertEqual(self.store.data['remoteDevices'], [])

    def test_pairing_needs_the_current_secret_and_is_single_use(self):
        self.assertEqual(self.req('GET', '/api/remote/bridge/pairing', token='bridge-token')[0], 404)  # nothing in progress
        self.app.pairing = dict(secret='one-time', expiresAt=time.time() + 60, lookups=0)
        bad = {'id': self.device, 'publicKey': self.key, 'name': 'x', 'secret': 'guess'}
        self.assertEqual(self.req('POST', '/api/remote/bridge/paired', bad, token='bridge-token')[0], 403)
        self.assertEqual(self.req('POST', '/api/remote/bridge/paired', dict(bad, secret='one-time', id='0' * 32), token='bridge-token')[0], 400)  # id must match the key
        self.assertEqual(self.pair()[0], 200)
        self.assertEqual(self.req('POST', '/api/remote/bridge/paired', dict(bad, secret='one-time'), token='bridge-token')[0], 403)  # used up
        self.app.pairing = dict(secret='old', expiresAt=time.time() - 1, lookups=0)
        self.assertEqual(self.req('POST', '/api/remote/bridge/paired', dict(bad, secret='old'), token='bridge-token')[0], 403)  # expired

    def test_pairing_secret_is_dropped_after_too_many_lookups(self):
        self.app.pairing = dict(secret='one-time', expiresAt=time.time() + 60, lookups=0)
        codes = [self.req('GET', '/api/remote/bridge/pairing', token='bridge-token')[0] for _ in range(12)]
        self.assertEqual(codes[:10], [200] * 10); self.assertEqual(codes[10:], [404, 404])

    def test_device_can_do_daily_things_only(self):
        self.pair()
        bot = self.store.data['bots'][0]['id']
        ok = [('GET', '/api/state'), ('GET', '/api/usage/bots'), ('GET', '/api/remote/me')]
        for method, path in ok: self.assertEqual(self.req(method, path, token='bridge-token', device=self.device)[0], 200, path)
        blocked = [('PATCH', '/api/settings', {'permissionMode': 'bypass'}), ('PATCH', '/api/settings', {'remote': {'enabled': False, 'relayUrl': ''}}),
                   ('PATCH', '/api/bots/' + bot, {'name': 'x'}), ('DELETE', '/api/bots/' + bot, None), ('POST', '/api/bots', {'name': 'x'}),
                   ('POST', '/api/export', {}), ('GET', '/api/remote', None), ('POST', '/api/remote/pairing', {}), ('DELETE', '/api/remote/devices/' + self.device, None),
                   ('POST', '/api/accounts/codex/login', {}), ('POST', '/api/groups', {'botIds': []}), ('GET', '/api/remote/bridge/devices', None), ('GET', '/index.html', None)]
        for method, path, body in blocked:
            status, data = self.req(method, path, body, token='bridge-token', device=self.device)
            self.assertEqual(status, 403, path)
        self.assertEqual(self.store.data['settings']['permissionMode'], 'manual')
        self.assertTrue(self.store.data['remoteDevices'][0]['lastSeenAt'])

    def test_unknown_or_revoked_device_is_refused(self):
        self.assertEqual(self.req('GET', '/api/state', token='bridge-token', device='f' * 32)[0], 401)
        self.pair()
        self.assertEqual(self.req('DELETE', '/api/remote/devices/' + self.device)[0], 200)
        self.assertEqual(self.req('GET', '/api/state', token='bridge-token', device=self.device)[0], 401)

    def test_bridge_paths_need_the_bridge_and_the_bridge_cannot_act_as_the_owner(self):
        self.assertEqual(self.req('GET', '/api/remote/bridge/devices')[0], 403)              # the app's own token is not the bridge
        self.assertEqual(self.req('GET', '/api/state', token='bridge-token')[0], 403)        # bridge without a device gets nothing else
        self.assertEqual(self.req('GET', '/api/state', token='wrong')[0], 403)
        self.app.bridge_token = None
        self.assertEqual(self.req('GET', '/api/remote/bridge/devices', token='bridge-token')[0], 403)  # remote access off: no bridge at all

    def test_relay_address_must_be_encrypted_unless_local(self):
        set_remote = lambda url, on=True: self.req('PATCH', '/api/settings', {'remote': {'enabled': on, 'relayUrl': url}})[0]
        self.assertEqual(set_remote('ws://relay.example.com'), 400)
        self.assertEqual(set_remote('https://relay.example.com'), 400)
        self.assertEqual(set_remote(''), 400)            # cannot turn on without an address
        self.assertEqual(set_remote('', on=False), 200)
        self.assertEqual(set_remote('wss://zook-relay.example.workers.dev', on=False), 200)
        self.assertEqual(set_remote('ws://127.0.0.1:8799', on=False), 200)


@unittest.skipUnless(TOOL.is_file(), 'zook-remote is not built')
class EncryptionTest(unittest.TestCase):
    def test_encryption_selftest(self):
        out = subprocess.run([str(TOOL), 'selftest'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual((out.returncode, out.stdout.decode().strip()), (0, 'selftest ok'), out.stderr.decode())


FAKE_CODEX = '''#!/usr/bin/env python3
import sys
sys.stdin.read(); print('phone reply ok')
'''


@unittest.skipUnless(TOOL.is_file() and relay_up(), 'needs zook-remote and the local relay (npx wrangler dev --port 8799 in relay/)')
class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(FAKE_CODEX); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_REMOTE_TOOL=str(TOOL))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.state = str(self.root / 'phone.json')
        self.assertEqual(self.mac('PATCH', '/api/settings', {'remote': {'enabled': True, 'relayUrl': RELAY}, 'provider': 'codex'})[0], 200)
        end = time.time() + 15
        while time.time() < end and not self.mac('GET', '/api/remote')[1]['connected']: time.sleep(0.3)
        self.assertTrue(self.mac('GET', '/api/remote')[1]['connected'], 'the Mac side did not reach the relay')

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=8)
        self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def mac(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        return resp.status, json.loads(raw)

    def pair(self, url, state=None, name='測試 iPhone'):
        return subprocess.run([str(TOOL), 'device-pair', '--state', state or self.state, '--payload', url, '--name', name, '--timeout', '10'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def phone(self, method, path, body=None, state=None, timeout=15):
        args = [str(TOOL), 'device-request', '--state', state or self.state, '--method', method, '--path', path, '--timeout', str(timeout)]
        if body is not None: args += ['--body', json.dumps(body, ensure_ascii=False)]
        out = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if out.returncode: return -out.returncode, out.stderr.decode().strip()
        reply = json.loads(out.stdout)
        return reply['status'], json.loads(reply['text']) if reply['text'][:1] in '{[' else reply['text']

    def test_pair_chat_limits_and_revoke(self):
        status, pairing = self.mac('POST', '/api/remote/pairing')
        self.assertEqual(status, 200); self.assertTrue(pairing['qr'].startswith('data:image/png;base64,iVBOR'))
        self.assertEqual(self.pair(pairing['url']).returncode, 0)
        self.assertNotEqual(self.pair(pairing['url'], state=str(self.root / 'second.json')).returncode, 0)   # a QR code works once
        self.assertFalse((self.root / 'second.json').exists())

        status, state = self.phone('GET', '/api/state')
        self.assertEqual(status, 200); bot = state['bots'][0]['id']
        self.assertEqual(self.phone('POST', '/api/chat', {'botId': bot, 'content': 'hi'})[0], 202)
        end = time.time() + 20
        while time.time() < end:
            last = next(b for b in self.phone('GET', '/api/state')[1]['bots'] if b['id'] == bot)['messages'][-1]
            if last.get('status') != 'running': break
            time.sleep(0.3)
        self.assertEqual((last['status'], last['content']), ('completed', 'phone reply ok'))

        self.assertEqual(self.phone('PATCH', '/api/settings', {'permissionMode': 'bypass'}), (403, {'error': '這個動作只能在 Mac 上進行。'}))
        self.assertEqual(self.phone('POST', '/api/chat', {'botId': 'missing', 'content': 'x' * 700000})[0], 404)   # split into parts and delivered whole

        # A stranger who knows the room and the Mac's public key but holds another key gets nowhere.
        saved = json.loads(Path(self.state).read_text()); stranger = dict(saved, privateKey=base64.b64encode(os.urandom(32)).decode())
        (self.root / 'stranger.json').write_text(json.dumps(stranger))
        self.assertLess(self.phone('GET', '/api/state', state=str(self.root / 'stranger.json'), timeout=6)[0], 0)

        device = self.mac('GET', '/api/remote')[1]['devices'][0]
        self.assertEqual(device['name'], '測試 iPhone'); self.assertTrue(device['lastSeenAt'])
        self.assertEqual(self.mac('DELETE', '/api/remote/devices/' + device['id'])[0], 200)
        self.assertLess(self.phone('GET', '/api/remote/me', timeout=6)[0], 0)                                    # revoked: cannot connect

    def test_turning_remote_off_disconnects_everything(self):
        self.assertEqual(self.pair(self.mac('POST', '/api/remote/pairing')[1]['url']).returncode, 0)
        self.assertEqual(self.phone('GET', '/api/remote/me')[0], 200)
        self.assertEqual(self.mac('PATCH', '/api/settings', {'remote': {'enabled': False, 'relayUrl': RELAY}})[0], 200)
        time.sleep(1.5)
        self.assertFalse(self.mac('GET', '/api/remote')[1]['connected'])
        self.assertEqual(self.phone('GET', '/api/remote/me', timeout=5)[0], -3)                                   # "cannot reach your Mac"
        self.assertEqual(self.mac('POST', '/api/remote/pairing')[0], 409)                                         # no pairing while off


if __name__ == '__main__': unittest.main()
