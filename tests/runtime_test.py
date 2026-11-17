import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import runtime

FIXTURE = Path(__file__).parent / 'fixtures/mcp_fixture.py'


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.skill = self.root / 'skill'; self.skill.mkdir()
        (self.skill / 'SKILL.md').write_text('---\nname: Real fixture\ndescription: Read fixture instructions\n---\nRead reference.txt and write a workspace note.')
        (self.skill / 'reference.txt').write_text('Verified real resource content')
        self.marker = self.root / 'marker'
        self.config = {'transport': 'stdio', 'command': sys.executable, 'args': [str(FIXTURE)],
                       'env': {'FIXTURE_MARKER': str(self.marker), 'API_TOKEN': 'configured-super-secret'}}
        self.inventory = {'skills': [{'id': 'skill:test', 'name': 'Fixture'}], 'mcp': [],
            '_private': {'skills': {'skill:test': {'path': str(self.skill / 'SKILL.md'), 'root': str(self.skill)}},
                         'mcp': {'fixture:mcp': self.config}}}
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            session.close()
        self.temp.cleanup()

    def session(self, skills=None, mcp=None, approve=None, commands=False):
        events = []
        session = runtime.RuntimeSession(skills or [], mcp or [], commands, self.root / 'workspace',
            approve if approve is not None else lambda *a: True, events.append, self.inventory)
        self.sessions.append(session)
        return session, events

    def external_name(self, session, original):
        session.tools()
        return next(name for name, route in session.routes.items() if route[1] == original)

    def test_real_stdio_handshake_paging_schema_and_call(self):
        session, events = self.session(mcp=['fixture:mcp'])
        name = self.external_name(session, 'echo')
        schema = next(t for t in session.tools() if t['name'] == name)['inputSchema']
        self.assertEqual(schema['properties']['continuation_token'], {'type': 'string'})
        self.assertEqual(len(session.routes), 2)
        result = session.call(name, {'message': 'actual protocol result'})
        self.assertEqual(json.loads(result['content'][0]['text'])['message'], 'actual protocol result')
        self.assertEqual([e['status'] for e in events], ['waiting_approval', 'running', 'completed'])
        process = session.clients['fixture:mcp'].process
        session.close()
        self.assertIsNotNone(process.poll())

    def test_denial_has_no_external_side_effect(self):
        session, events = self.session(mcp=['fixture:mcp'], approve=lambda *args: False)
        result = session.call(self.external_name(session, 'side_effect'), {'marker': 'denied'})
        self.assertTrue(result['isError'])
        self.assertFalse(self.marker.exists())
        self.assertEqual(events[-1]['status'], 'denied')

    def test_approval_arguments_are_frozen(self):
        def approval(call_id, name, args, source):
            args['marker'] = 'mutated'
            return True
        session, _ = self.session(mcp=['fixture:mcp'], approve=approval)
        session.call(self.external_name(session, 'side_effect'), {'marker': 'approved'})
        self.assertEqual(json.loads(self.marker.read_text()), {'marker': 'approved'})

    def test_unselected_and_unknown_tools_refused(self):
        session, _ = self.session()
        self.assertEqual(session.tools(), [])
        self.assertTrue(session.call('zook_workspace_read', {'path': 'a'})['isError'])
        self.assertEqual(session.clients, {})
        with self.assertRaises(RuntimeError):
            self.session(mcp=['unknown'])

    def test_skill_and_resource_are_real_and_constrained(self):
        session, _ = self.session(skills=['skill:test'])
        self.assertIn('Read reference.txt', session.call('zook_read_skill', {'skill_id': 'skill:test'})['content'][0]['text'])
        self.assertEqual(session.call('zook_read_skill_resource', {'skill_id': 'skill:test', 'path': 'reference.txt'})['content'][0]['text'], 'Verified real resource content')
        self.assertTrue(session.call('zook_read_skill_resource', {'skill_id': 'skill:test', 'path': '../marker'})['isError'])
        (self.skill / 'escape').symlink_to(self.root)
        self.assertTrue(session.call('zook_read_skill_resource', {'skill_id': 'skill:test', 'path': 'escape/marker'})['isError'])

    def test_workspace_real_write_read_and_containment(self):
        session, _ = self.session(mcp=['builtin:workspace'])
        self.assertNotIn('isError', session.call('zook_workspace_write', {'path': 'folder/note.txt', 'content': 'actual note'}))
        self.assertEqual(session.call('zook_workspace_read', {'path': 'folder/note.txt'})['content'][0]['text'], 'actual note')
        listed = json.loads(session.call('zook_workspace_list', {})['content'][0]['text'])
        self.assertEqual(listed['entries'][0]['name'], 'folder')
        (session.workspace / 'escape').symlink_to(self.root)
        self.assertTrue(session.call('zook_workspace_write', {'path': 'escape/marker', 'content': 'x'})['isError'])
        self.assertTrue(session.call('zook_workspace_read', {'path': '/etc/passwd'})['isError'])
        self.assertTrue(session.call('zook_workspace_write', {'path': '../marker', 'content': 'x'})['isError'])
        self.assertFalse(self.marker.exists())

    def test_write_denied(self):
        session, _ = self.session(mcp=['builtin:workspace'], approve=lambda *a: False)
        self.assertTrue(session.call('zook_workspace_write', {'path': 'no', 'content': 'x'})['isError'])
        self.assertFalse((session.workspace / 'no').exists())

    def test_redaction_keeps_public_urls_but_removes_credentials(self):
        redactor = runtime.Redactor(self.inventory)
        self.assertEqual(redactor.text('https://example.com/article'), 'https://example.com/article')
        value = redactor.value({'api_token': 'user-secret', 'message': 'configured-super-secret'})
        self.assertEqual(value, {'api_token': '[redacted]', 'message': '[redacted]'})
        self.assertNotIn('hidden', redactor.text('https://user:hidden@example.com/api?token=hidden'))

    def test_discover_real_config_and_secret_free_public_catalog(self):
        home = self.root / 'home'; (home / '.codex').mkdir(parents=True)
        (home / '.codex/config.toml').write_text('[mcp_servers."With Space"]\nurl="https://private.example/mcp?token=secret"\n[mcp_servers."With Space".http_headers]\nAuthorization="Bearer secret"\n')
        (home / '.claude.json').write_text(json.dumps({'mcpServers': {'fixture': self.config}}))
        skilldir = home / '.agents/skills/example'; skilldir.mkdir(parents=True)
        (skilldir / 'SKILL.md').write_text('---\nname: Example\ndescription: Real instructions\n---\nBody')
        result = runtime.discover(home)
        public = json.dumps({k: v for k, v in result.items() if k != '_private'})
        self.assertNotIn('Bearer secret', public)
        self.assertNotIn('private.example', public)
        self.assertNotIn('FIXTURE_MARKER', public)
        self.assertEqual(result['skills'][0]['name'], 'Example')
        self.assertEqual([x['id'] for x in result['mcp']], [x['id'] for x in runtime.discover(home)['mcp']])
        self.assertEqual(len(result['mcp']), 3)

    def test_helpers_are_exact_scripts_selected_and_approved(self):
        helper = self.skill / 'helper.py'
        helper.write_text('from pathlib import Path\nPath("result").write_text("helper ran")\nprint("done")')
        session, events = self.session(skills=['skill:test'], commands=True)
        args = {'skill_id': 'skill:test', 'argv': [sys.executable, 'helper.py']}
        result = session.call('zook_run_skill_helper', args)
        self.assertFalse(result['isError'])
        self.assertEqual((session.workspace / 'result').read_text(), 'helper ran')
        self.assertEqual(events[0]['status'], 'waiting_approval')
        self.assertTrue(session.call('zook_run_skill_helper', {'skill_id': 'skill:test', 'argv': [sys.executable, '-c', 'print(1)']})['isError'])
        disabled, _ = self.session(skills=['skill:test'])
        self.assertTrue(disabled.call('zook_run_skill_helper', args)['isError'])

    def test_legacy_sse_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError, 'Legacy SSE'):
            runtime.ProtocolClient({'transport': 'sse', 'url': 'https://example.com/sse'})

    def test_http_json_and_sse_sessions(self):
        recorded = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                msg = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                recorded.append((msg['method'], self.headers.get('Mcp-Session-Id')))
                if 'id' not in msg:
                    self.send_response(202); self.end_headers(); return
                if msg['method'] == 'initialize':
                    result = {'protocolVersion': runtime.PROTOCOL, 'capabilities': {}}
                else:
                    result = {'tools': [{'name': 'echo', 'description': 'HTTP fixture', 'inputSchema': {'type': 'object', 'properties': {}}}]}
                body = json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}).encode()
                self.send_response(200)
                self.send_header('Mcp-Session-Id', 'fixture-session')
                if msg['method'] == 'tools/list':
                    body = b'event: message\ndata: ' + body + b'\n\n'
                    self.send_header('Content-Type', 'text/event-stream')
                else:
                    self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            result = runtime.test_connection('http:test', {'_private': {'mcp': {'http:test': {'transport': 'http', 'url': 'http://127.0.0.1:%s/mcp' % server.server_port}}}})
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['toolCount'], 1)
            self.assertEqual(recorded, [('initialize', None), ('notifications/initialized', 'fixture-session'), ('tools/list', 'fixture-session')])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


class ConnectorStartTest(unittest.TestCase):
    """A connector is started the way the user's own shell would start it, and a failure says why."""
    SERVER = "import sys, json\nprint('Starting server v1...')\nfor line in sys.stdin:\n    m = json.loads(line)\n    if 'id' in m: print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'protocolVersion': '2025-06-18', 'tools': []}})); sys.stdout.flush()\n"

    def test_banner_on_standard_output_is_ignored(self):
        client = runtime.ProtocolClient({'command': sys.executable, 'args': ['-c', self.SERVER]})
        self.assertEqual(client.request('tools/list', {})['tools'], []); client.close()

    def test_failure_reports_what_the_connector_said(self):
        with self.assertRaises(RuntimeError) as caught:
            runtime.ProtocolClient({'command': sys.executable, 'args': ['-c', "import sys; sys.stderr.write('Session expired. token=abc123 Run login again.\\n'); sys.exit(1)"]})
        self.assertIn('Session expired', str(caught.exception)); self.assertNotIn('abc123', str(caught.exception))

    def test_command_is_found_in_the_usual_install_folders(self):
        with tempfile.TemporaryDirectory() as home:
            tools = Path(home) / '.nvm/versions/node/v20.0.0/bin'; tools.mkdir(parents=True)
            script = tools / 'fake-mcp'; script.write_text('#!' + sys.executable + '\n' + self.SERVER); script.chmod(0o755)
            with patch.dict(os.environ, {'HOME': home, 'PATH': '/usr/bin:/bin'}):
                client = runtime.ProtocolClient({'command': 'fake-mcp', 'args': []}); client.close()
                with self.assertRaises(RuntimeError) as caught: runtime.ProtocolClient({'command': 'no-such-mcp', 'args': []})
            self.assertIn('no-such-mcp', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
