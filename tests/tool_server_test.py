import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADAPTER = Path(__file__).resolve().parents[1] / 'backend/tool_server.py'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        assert self.headers['Authorization'] == 'Bearer isolated-token'
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        result = {'tools': [{'name': 'example', 'inputSchema': {'type': 'object'}}]} if body['method'] == 'tools/list' else {'content': [{'type': 'text', 'text': body['params']['arguments']['value']}]}
        raw = json.dumps(result).encode(); self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)


class ToolServerTest(unittest.TestCase):
    def test_protocol_and_forward(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            env = dict(os.environ, ZOOK_WORKER_URL='http://127.0.0.1:%d/api/worker/job' % server.server_port, ZOOK_WORKER_TOKEN='isolated-token')
            messages = [{'jsonrpc':'2.0', 'id':1, 'method':'initialize'}, {'jsonrpc':'2.0', 'method':'notifications/initialized'}, {'jsonrpc':'2.0', 'id':2, 'method':'tools/list'}, {'jsonrpc':'2.0', 'id':3, 'method':'tools/call', 'params':{'name':'example', 'arguments':{'value':'actual'}}}, {'jsonrpc':'2.0', 'id':4, 'method':'ping'}]
            p = subprocess.run([sys.executable, str(ADAPTER)], input=''.join(json.dumps(x)+'\n' for x in messages), text=True, capture_output=True, env=env, timeout=5, check=True)
            results = [json.loads(x) for x in p.stdout.splitlines()]
            self.assertEqual([x['id'] for x in results], [1, 2, 3, 4]); self.assertEqual(results[2]['result']['content'][0]['text'], 'actual')
            self.assertNotIn('isolated-token', p.stdout+p.stderr)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
