#!/usr/bin/env python3
"""Per-job MCP stdio adapter; credentials exist only in its inherited environment."""
import json
import os
import sys
import urllib.error
import urllib.request

MAX_LINE = 1024 * 1024
MAX_RESPONSE = 3 * 1024 * 1024  # the runtime sends up to 2 MiB (a screenshot), plus the JSON around it
BASE = os.environ.get('ZOOK_WORKER_URL', '')
TOKEN = os.environ.get('ZOOK_WORKER_TOKEN', '')
try: WAIT = max(30, int(os.environ.get('ZOOK_TOOL_WAIT') or 660))  # a tool call may wait for the user's approval
except ValueError: WAIT = 660


def forward(method, params):
    req = urllib.request.Request(BASE, data=json.dumps({'method': method, 'params': params}).encode(),
                                 headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=WAIT) as response:
            return json.loads(response.read(MAX_RESPONSE))
    except (urllib.error.URLError, ValueError, OSError):
        raise RuntimeError('Zook 工具連線已中斷，請重新執行工作。')


def main():
    for line in sys.stdin.buffer:
        try:
            if len(line) > MAX_LINE: raise ValueError('request too large')
            req = json.loads(line)
            if not isinstance(req, dict): raise ValueError('invalid request')
            method, ident = req.get('method'), req.get('id')
            if ident is None: continue
            if method == 'initialize':
                result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'zook', 'version': '1.0'}}
            elif method == 'ping': result = {}
            elif method in ('tools/list', 'tools/call'):
                result = forward(method, req.get('params') or {})
            else:
                raise ValueError('method not found')
            response = {'jsonrpc': '2.0', 'id': ident, 'result': result}
        except (ValueError, TypeError, RuntimeError) as exc:
            response = {'jsonrpc': '2.0', 'id': locals().get('ident'), 'error': {'code': -32603, 'message': str(exc)[:300]}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
