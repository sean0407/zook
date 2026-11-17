import http.client
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
# A tiny connector: reports the key it was given (only whether it arrived) and offers one tool.
MCP = r'''
import json, os, sys
for line in sys.stdin:
    m = json.loads(line)
    if 'id' not in m: continue
    if m['method'] == 'initialize': r = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 'fake', 'version': '1'}}
    elif m['method'] == 'tools/list': r = {'tools': [{'name': 'key_' + ('present' if os.environ.get('FAKE_KEY') == 'key-value-12345' else 'missing') + '_' + os.environ.get('MODE', 'none'), 'description': 'x', 'inputSchema': {'type': 'object'}}]}
    else: r = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': r})); sys.stdout.flush()
'''


class ConnectorsTest(unittest.TestCase):
    """Connectors added in Zook itself: stored in Zook, key kept apart, shared by every Bot."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'home').mkdir()
        (self.root / 'mcp.py').write_text(MCP)
        env = dict(os.environ, HOME=str(self.root / 'home'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(self.root))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
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

    def listed(self):
        return [m for m in self.req('GET', '/api/integrations')[1]['mcp'] if m['source'] == 'zook']

    def test_add_use_edit_and_remove(self):
        command = '%s %s' % (sys.executable, self.root / 'mcp.py')
        for bad in ({'name': '', 'transport': 'stdio', 'command': command}, {'name': 'x', 'transport': 'stdio', 'command': ''}, {'name': 'x', 'transport': 'stdio', 'command': 'a "b'},
                    {'name': 'x', 'transport': 'http', 'url': 'http://example.com/mcp'}, {'name': 'x', 'transport': 'ftp'},
                    {'name': 'x', 'transport': 'stdio', 'command': command, 'env': {'BAD NAME': '1'}}, {'name': 'x', 'transport': 'stdio', 'command': command, 'secretName': 'FAKE_KEY'}):
            self.assertEqual(self.req('POST', '/api/connectors', bad)[0], 400, bad)
        status, made = self.req('POST', '/api/connectors', {'name': '我的工具', 'transport': 'stdio', 'command': command, 'env': {'MODE': 'one'}, 'secretName': 'FAKE_KEY', 'secret': 'key-value-12345'})
        self.assertEqual(status, 201)
        self.assertEqual(self.req('POST', '/api/connectors', {'name': '我的工具', 'transport': 'stdio', 'command': command})[0], 400)  # same name
        item = self.listed()[0]
        self.assertEqual((item['id'], item['name'], item['editable'], item['config']['hasSecret'], item['config']['secretName']), (made['id'], '我的工具', True, True, 'FAKE_KEY'))
        state = self.req('GET', '/api/state')[1]
        self.assertIn(made['id'], state['settings']['sharedMcp'])  # on for every Bot as soon as it is added
        everything = json.dumps(state) + json.dumps(self.req('GET', '/api/integrations')[1]) + (self.root / 'data/swarmr.json').read_text()
        self.assertNotIn('key-value-12345', everything)  # the key is neither sent back nor written to Zook's data file
        test = self.req('POST', '/api/mcp/' + made['id'] + '/test', {})[1]
        self.assertEqual((test['status'], [t['name'] for t in test['tools']]), ('ready', ['key_present_one']))

        ident = made['id'].split(':')[1]
        self.assertEqual(self.req('PATCH', '/api/connectors/' + ident, {'env': {'MODE': 'two'}})[0], 200)  # the key is kept when not retyped
        self.assertEqual(self.req('POST', '/api/mcp/' + made['id'] + '/test', {})[1]['tools'][0]['name'], 'key_present_two')
        self.assertEqual(self.req('PATCH', '/api/connectors/' + ident, {'clearSecret': True})[0], 200)
        self.assertEqual(self.req('POST', '/api/mcp/' + made['id'] + '/test', {})[1]['tools'][0]['name'], 'key_missing_two')
        self.assertFalse(self.listed()[0]['config']['hasSecret'])

        self.assertEqual(self.req('DELETE', '/api/connectors/' + ident)[0], 200)
        self.assertEqual(self.listed(), []); self.assertNotIn(made['id'], self.req('GET', '/api/state')[1]['settings']['sharedMcp'])
        self.assertEqual(self.req('DELETE', '/api/connectors/' + ident)[0], 404)

    def test_web_address_connector(self):
        status, made = self.req('POST', '/api/connectors', {'name': '遠端', 'transport': 'http', 'url': 'https://mcp.example.com/mcp', 'secret': 'token-abcdef-123'})
        self.assertEqual(status, 201)
        item = self.listed()[0]
        self.assertEqual((item['transport'], item['config']['url'], item['config']['hasSecret']), ('http', 'https://mcp.example.com/mcp', True))
        self.assertNotIn('token-abcdef-123', json.dumps(self.req('GET', '/api/integrations')[1]))
        self.assertEqual(self.req('POST', '/api/connectors', {'name': '本機', 'transport': 'http', 'url': 'http://127.0.0.1:9/mcp'})[0], 201)  # plain http only on this Mac


if __name__ == '__main__': unittest.main()
