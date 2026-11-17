"""Isolated real stdio JSON-RPC MCP fixture; never accesses user services."""
import json
import os
import sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method, params = request['method'], request.get('params', {})
    if method == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fixture', 'version': '1'}}
    elif method == 'tools/list':
        if params.get('cursor') == 'page2':
            result = {'tools': [{'name': 'side_effect', 'description': 'Write fixture marker', 'inputSchema': {'type': 'object', 'properties': {'marker': {'type': 'string'}}}}]}
        else:
            result = {'tools': [{'name': 'echo', 'description': 'Echo an argument', 'inputSchema': {'type': 'object', 'properties': {'continuation_token': {'type': 'string'}, 'message': {'type': 'string'}}}}], 'nextCursor': 'page2'}
    elif method == 'tools/call':
        args = params.get('arguments', {})
        if params['name'] == 'side_effect':
            with open(os.environ['FIXTURE_MARKER'], 'w') as output:
                output.write(json.dumps(args))
        result = {'content': [{'type': 'text', 'text': json.dumps(args)}], 'structuredContent': args}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
