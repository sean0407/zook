import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADAPTER = Path(__file__).resolve().parents[1] / 'backend/tool_server.py'


def sign(*parts): return hmac.new(b'isolated-token', b'\n'.join(p if isinstance(p, bytes) else str(p).encode() for p in parts), 'sha256').hexdigest()


class Handler(BaseHTTPRequestHandler):
    prove = True
    def log_message(self, *args): pass
    def do_POST(self):
        raw_in = self.rfile.read(int(self.headers['Content-Length'])); nonce, when = self.headers['X-Zook-Nonce'], self.headers['X-Zook-Time']
        assert 'Authorization' not in self.headers  # the token itself is never sent
        assert self.headers['X-Zook-Sig'] == sign('call', nonce, when, '%d%s' % (self.server.server_port, self.path), raw_in)
        body = json.loads(raw_in)
        result = {'tools': [{'name': 'example', 'inputSchema': {'type': 'object'}}]} if body['method'] == 'tools/list' else {'content': [{'type': 'text', 'text': body['params']['arguments']['value']}]}
        raw = json.dumps(result).encode(); self.send_response(200); self.send_header('Content-Length', str(len(raw)))
        if self.prove: self.send_header('X-Zook-Proof', sign('answer', nonce, 200, raw))
        self.end_headers(); self.wfile.write(raw)


class Imposter(Handler): prove = False  # a program that took the port over: it cannot prove the answer


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

    def test_answer_without_proof_is_refused(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Imposter)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            env = dict(os.environ, ZOOK_WORKER_URL='http://127.0.0.1:%d/api/worker/job' % server.server_port, ZOOK_WORKER_TOKEN='isolated-token')
            message = {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'example', 'arguments': {'value': 'actual'}}}
            p = subprocess.run([sys.executable, str(ADAPTER)], input=json.dumps(message) + '\n', text=True, capture_output=True, env=env, timeout=5, check=True)
            self.assertIn('error', json.loads(p.stdout)); self.assertNotIn('actual', p.stdout)
        finally:
            server.shutdown(); server.server_close(); thread.join()


class GateAnswerTest(unittest.TestCase):
    """zook_gate.py's question to Zook: only an answer proved with the token for this very request lets an action through."""
    def ask(self, handler):
        import importlib.util
        spec = importlib.util.spec_from_file_location('gate_for_answer', ADAPTER.with_name('zook_gate.py')); gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        old = {k: os.environ.get(k) for k in ('ZOOK_WORKER_URL', 'ZOOK_WORKER_TOKEN')}
        os.environ.update(ZOOK_WORKER_URL='http://127.0.0.1:%d/api/worker/job' % server.server_port, ZOOK_WORKER_TOKEN='isolated-token')
        try: return gate.ask([('delete', '刪除檔案')])
        finally:
            for k, v in old.items(): os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            server.shutdown(); server.server_close(); thread.join()

    def test_proved_answer_counts(self):
        class Yes(Handler):
            def do_POST(self):
                raw_in = self.rfile.read(int(self.headers['Content-Length'])); nonce = self.headers['X-Zook-Nonce']
                assert 'Authorization' not in self.headers and self.headers['X-Zook-Sig'] == sign('call', nonce, self.headers['X-Zook-Time'], '%d%s' % (self.server.server_port, self.path), raw_in)
                raw = b'{"approved": true}'; self.send_response(200); self.send_header('Content-Length', str(len(raw)))
                if self.prove: self.send_header('X-Zook-Proof', sign('answer', nonce, 200, raw))
                self.end_headers(); self.wfile.write(raw)
        class NoProof(Yes): prove = False
        self.assertTrue(self.ask(Yes))
        self.assertFalse(self.ask(NoProof))  # a program on an old port cannot approve


if __name__ == '__main__': unittest.main()
