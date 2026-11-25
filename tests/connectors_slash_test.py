# -*- coding: utf-8 -*-
"""#182, #183, #197: connector status and errors say in plain words why a connector cannot be used and what to do next;
small fixes on the Skills and connectors page; the / menu says what is wrong and how to use it."""
import json, re, shutil, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'
sys.path.insert(0, str(ROOT / 'backend'))
import runtime


def source(name): return (JS / name).read_text(encoding='utf-8')


def case(text, action):
    start = text.index("case '%s':" % action)
    nxt = text.find('\n        case ', start + 1)
    return text[start:nxt if nxt > 0 else None]


class ConnectorErrors(unittest.TestCase):
    def test_unreachable_address_is_plain_and_not_a_sign_in(self):
        inv = {'_private': {'mcp': {'zook:x': {'transport': 'http', 'url': 'http://127.0.0.1:9/none'}}}}
        r = runtime.test_connection('zook:x', inv)
        self.assertEqual(r['status'], 'error')
        self.assertIn('連不上這個網址', r['error'])
        self.assertFalse(r['needsLogin'])

    def test_sign_in_needed_is_marked(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0))); self.send_response(401); self.end_headers()
            def log_message(self, *a): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            r = runtime.test_connection('zook:x', {'_private': {'mcp': {'zook:x': {'transport': 'http', 'url': 'http://127.0.0.1:%d/mcp' % server.server_address[1]}}}})
        finally: server.shutdown(); server.server_close()
        self.assertTrue(r['needsLogin'])

    def test_not_a_connector_says_so(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(b'<html>hi</html>')
            def log_message(self, *a): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            r = runtime.test_connection('zook:x', {'_private': {'mcp': {'zook:x': {'transport': 'http', 'url': 'http://127.0.0.1:%d/' % server.server_address[1]}}}})
        finally: server.shutdown(); server.server_close()
        self.assertIn('不是連接器', r['error'])

    def test_no_english_connector_errors_left(self):
        text = (ROOT / 'backend/runtime.py').read_text(encoding='utf-8')
        english = re.findall(r"RuntimeError\('(?:MCP|Configure|Configured|Legacy|Remote|Unsupported|Server|Invalid|This configured|A configured)[^']*'", text)
        self.assertEqual(english, [])

    def test_skill_notes_say_what_to_do(self):
        text = (ROOT / 'backend/zook/accounts.py').read_text(encoding='utf-8')
        body = text[text.index('def skill_notes'):text.index('def connector_from_config')]
        self.assertIn('「連接器」', body.split("Zook 裡沒有")[1].split('\n')[0])  # missing: where to add it
        self.assertIn('用不到可以不管', body)


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class ConnectorCards(unittest.TestCase):
    """Runs the directory card builder of 20-models.js in node."""
    HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const text = fs.readFileSync(process.argv[2], 'utf8');
const code = text.slice(text.indexOf('const SOURCE_NAMES'), text.indexOf('function directoryPage('));
const input = JSON.parse(process.argv[3]);
const ctx = {state: input.state, esc: s => String(s), console};
vm.createContext(ctx);
vm.runInContext(code + '\nthis.out = directoryItems(' + JSON.stringify(input.tab) + ');', ctx);
console.log(JSON.stringify(ctx.out));
'''

    def items(self, state, tab='mcp'):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / 'h.js'; h.write_text(self.HARNESS, encoding='utf-8')
            out = subprocess.run(['node', str(h), str(JS / '20-models.js'), json.dumps({'state': state, 'tab': tab})], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return {i['id']: i for i in json.loads(out.stdout)}

    def state(self, mcp, tests=None, shared=None):
        return {'integrations': {'mcp': mcp, 'skills': [], 'plugins': []}, 'mcpTests': tests or {},
                'data': {'settings': {'sharedMcp': shared if shared is not None else [m['id'] for m in mcp]}}}

    def test_failed_test_is_unusable_not_shared(self):
        mcp = [{'id': 'zook:a', 'name': 'A', 'source': 'zook', 'editable': True, 'canLogin': True, 'config': {'url': 'http://127.0.0.1:9/none'}}]
        a = self.items(self.state(mcp, {'zook:a': {'status': 'error', 'error': '連不上這個網址。', 'needsLogin': False}}))['zook:a']
        self.assertEqual(a['status'][1], '目前無法使用')
        self.assertNotIn('共用中', a['meta'])
        self.assertIn('連不上這個網址', a['note'])
        self.assertFalse(a['canLogin'], 'an address that cannot be reached is not a sign-in problem')

    def test_sign_in_failure_keeps_login(self):
        mcp = [{'id': 'zook:a', 'name': 'A', 'source': 'zook', 'editable': True, 'canLogin': True, 'config': {'url': 'https://x.example/mcp'}}]
        a = self.items(self.state(mcp, {'zook:a': {'status': 'error', 'error': '需要登入', 'needsLogin': True}}))['zook:a']
        self.assertTrue(a['canLogin'])

    def test_needs_login_is_not_shared(self):
        mcp = [{'id': 'zook:n', 'name': 'Notion', 'source': 'zook', 'canLogin': True, 'signedIn': True, 'needsLogin': True}]
        n = self.items(self.state(mcp))['zook:n']
        self.assertNotIn('共用中', n['meta'])
        self.assertIn('目前無法使用', n['meta'])

    def test_working_connector_still_shared(self):
        mcp = [{'id': 'zook:w', 'name': 'W', 'source': 'zook'}]
        w = self.items(self.state(mcp, {'zook:w': {'status': 'ready', 'toolCount': 1, 'tools': [{'name': 'x'}]}}))['zook:w']
        self.assertEqual(w['meta'], '所有 Bot 共用中')

    def test_google_card_explains_gmail_is_separate(self):
        mcp = [{'id': 'builtin:gmail', 'name': 'Gmail', 'source': 'builtin', 'gmail': True, 'address': 'a@b.c'},
               {'id': 'builtin:google', 'name': 'Google', 'source': 'builtin', 'google': True, 'needsSetup': True}]
        g = self.items(self.state(mcp, shared=[]))['builtin:google']
        self.assertIn('Gmail', g['description'])
        self.assertNotIn('測試連線', g['description'])


class PageSource(unittest.TestCase):
    def test_skill_off_says_where_it_went(self):
        forms = source('50-forms.js')
        self.assertIn('移到「未啟用」', forms)

    def test_tab_count_shows_how_many_are_on(self):
        self.assertIn('已開啟', source('20-models.js')[source('20-models.js').index('const counts'):][:900])

    def test_removed_template_comes_back(self):
        self.assertIn('state.templates = null', case(source('40-actions.js'), 'skill-remove'))

    def test_templates_reachable_from_top(self):
        models = source('20-models.js')
        self.assertIn('data-action="jump-templates"', models)
        self.assertIn('id="skill-templates"', source('39-upkeep.js'))

    def test_pack_says_what_it_is(self):
        self.assertIn('.zookpack', source('20-models.js'))

    def test_page_survives_reload(self):
        last = source('34c-lastopen.js')
        self.assertIn('restorePage', last)
        self.assertIn('restorePage()', source('30-pages.js'))

    def test_connector_form_error_stays_by_the_field(self):
        self.assertIn('class="form-error', source('20-models.js')[source('20-models.js').index('function connectorModal'):][:4000])
        forms = source('50-forms.js')
        branch = forms[forms.index("form.id === 'connector-form'"):forms.index("form.id === 'profile-form'")]
        self.assertIn('.form-error', branch)
        self.assertNotIn("toast('環境變數", branch)

    def test_connector_type_switch_keeps_height(self):
        self.assertIn('connector-panes', source('20-models.js'))
        self.assertIn('.connector-panes', (ROOT / 'frontend/style.css').read_text(encoding='utf-8'))


class SlashMenu(unittest.TestCase):
    def setUp(self): self.look = source('38-look.js')

    def test_unknown_command_is_told(self):
        self.assertIn('沒有「', self.look)

    def test_keys_are_shown(self):
        self.assertIn('↑↓', self.look); self.assertIn('Esc', self.look)

    def test_plan_has_no_covering_notice(self):
        self.assertNotIn("toast('這則訊息 Bot 只會提出計畫", self.look)
        self.assertIn('state.plan[b.id]', source('10-chat.js'))  # the message box itself says so

    def test_menu_survives_redraw(self):
        models = source('20-models.js')
        self.assertIn('updateMentionMenu();\n    refreshSlash();', models)


if __name__ == '__main__':
    unittest.main()
