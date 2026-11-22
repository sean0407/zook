import http.client
import importlib.util
from unittest import mock
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('hello')
        (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'
        cli.write_text('#!/usr/bin/env python3\nimport os,sys,time,subprocess\ns=sys.stdin.read()\nif "FAIL_CLI" in s: sys.exit(1)\nif "WAIT_FOR_CANCEL" in s:\n child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"])\n open(os.environ["FAKE_CHILD_PID"],"w").write(str(child.pid))\n time.sleep(30)\nprint("test response")\n')
        cli.chmod(0o755)
        claude = self.root / 'bin/claude'
        claude.write_text('#!/usr/bin/env python3\nimport json,sys\nif \'--help\' in sys.argv or \'--version\' in sys.argv: sys.exit(0)\nsys.stdin.read()\nprint(json.dumps({"result":"claude response"}))\n')
        claude.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin')+os.pathsep+os.environ['PATH'], FAKE_CHILD_PID=str(self.root/'child.pid'), ZOOK_NO_INTRO='1')
        self.start_server()

    def start_server(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root/'data'), '--assets', str(self.root/'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port = ready['port']; self.token = ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5)
        self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def request(self, method, path, body=None, headers=None, auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'Authorization': 'Bearer '+self.token} if auth else {}
        h.update(headers or {})
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, payload, h)
        resp = conn.getresponse(); raw = resp.read(); status = resp.status
        conn.close()
        try: data = json.loads(raw)
        except ValueError: data = raw
        return status, data

    def test_security_and_persistence(self):
        self.assertEqual(self.request('GET', '/api/state', auth=False)[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Host':'evil.test'})[0], 403)
        self.assertEqual(self.request('POST', '/api/bots', {'name':'X'}, {'Origin':'https://evil.test'})[0], 403)
        self.assertEqual(self.request('GET', '/%2e%2e/data/swarmr.json')[0], 404)
        self.assertEqual(self.request('GET', '/', headers={'Cookie':'swarmr_session='+self.token}, auth=False), (200, b'hello'))
        status, bot = self.request('POST', '/api/bots', {'name':'Test'})
        self.assertEqual(status, 201)
        self.assertEqual(self.request('POST', '/api/knowledge', {'title':'Note', 'content':'Details', 'tags':['tag']})[0], 201)
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()
        self.start_server()
        state = self.request('GET', '/api/state')[1]
        self.assertTrue(any(x['id'] == bot['id'] for x in state['bots']))
        self.assertEqual(state['knowledge'][0]['content'], 'Details')
        self.assertEqual(os.stat(self.root/'data/swarmr.json').st_mode & 0o777, 0o600)

    def test_claude_auth_failure_is_actionable(self):
        cli = self.root/'bin/claude'
        cli.write_text('#!/usr/bin/env python3\nimport json,sys\nsys.stdin.read()\nprint(json.dumps({"is_error":True,"result":"Failed to authenticate. API Error: 403 Forbidden"}))\nsys.exit(1)\n')
        bot = self.request('GET', '/api/state')[1]['bots'][0]
        self.request('PATCH', '/api/bots/'+bot['id'], {'provider':'claude'})
        status, reply = self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'hello'})
        self.assertEqual(status, 202)
        for _ in range(100):
            job = self.request('GET', '/api/jobs/'+reply['jobId'])[1]
            if job['status'] != 'running': break
            time.sleep(.02)
        self.assertEqual(job['status'], 'failed')
        self.assertIn('403', job['error'])
        self.assertIn('登入', job['error'])

    def test_claude_personal_login_ignores_gateway_environment(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close()
        for key in ('ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
            self.env[key] = 'test-override'
        cli = self.root/'bin/claude'
        cli.write_text('''#!/usr/bin/env python3
import json,os,sys
keys = ('ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')
assert not any(k in os.environ for k in keys)
if sys.argv[1:] == ['auth', 'status']:
 print(json.dumps({'loggedIn':False}))
 sys.exit(1)
assert ('--safe-mode' in sys.argv or '--restricted' in sys.argv) and '--strict-mcp-config' in sys.argv
assert '--settings' in sys.argv  # a Claude Bot has its own tools behind Zook's boundary gate (2026-11-22)
sys.stdin.read()
print(json.dumps({'result':'personal response'}))
''')
        self.start_server()
        providers = self.request('GET', '/api/diagnostics')[1]['providers']
        self.assertEqual(next(x for x in providers if x['id']=='claude')['authStatus'], 'not_logged_in')
        bot = self.request('GET', '/api/state')[1]['bots'][0]
        self.request('PATCH', '/api/bots/'+bot['id'], {'provider':'claude'})
        reply = self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'hello'})[1]
        for _ in range(100):
            job = self.request('GET', '/api/jobs/'+reply['jobId'])[1]
            if job['status'] != 'running': break
            time.sleep(.02)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['content'], 'personal response')

    def test_claude_missing_login_explains_next_step(self):
        cli = self.root/'bin/claude'
        cli.write_text('#!/usr/bin/env python3\nimport json,sys\nsys.stdin.read()\nprint(json.dumps({"is_error":True,"result":"Not logged in · Please run /login"}))\nsys.exit(1)\n')
        bot = self.request('GET', '/api/state')[1]['bots'][0]
        self.request('PATCH', '/api/bots/'+bot['id'], {'provider':'claude'})
        reply = self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'hello'})[1]
        for _ in range(100):
            job = self.request('GET', '/api/jobs/'+reply['jobId'])[1]
            if job['status'] != 'running': break
            time.sleep(.02)
        self.assertEqual(job['status'], 'failed')
        self.assertIn('各模型使用量', job['error'])

    def test_models_rejects_invalid_provider(self):
        self.assertEqual(self.request('GET', '/api/models?provider=unknown')[0], 400)

    def test_bot_deletion_requires_knowledge_reassignment(self):
        bot = self.request('GET', '/api/state')[1]['bots'][0]
        note = self.request('POST', '/api/knowledge', {'title':'Private', 'content':'content', 'botId':bot['id']})[1]
        status, error = self.request('DELETE', '/api/bots/'+bot['id'])
        self.assertEqual(status, 409)
        self.assertIn('知識', error['error'])
        self.assertEqual(self.request('PATCH', '/api/knowledge/'+note['id'], {'botId':''})[0], 200)
        self.assertEqual(self.request('DELETE', '/api/bots/'+bot['id'])[0], 200)
        self.assertEqual(self.request('GET', '/api/state')[1]['knowledge'][0]['botId'], '')

    def test_chat_and_cancellation(self):
        bot = self.request('GET', '/api/state')[1]['bots'][0]
        status, reply = self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'hello'})
        self.assertEqual(status, 202)
        for _ in range(100):
            job = self.request('GET', '/api/jobs/'+reply['jobId'])[1]
            if job['status'] != 'running': break
            time.sleep(.02)
        self.assertEqual(job['status'], 'completed'); self.assertEqual(job['content'], 'test response')
        status, reply = self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'WAIT_FOR_CANCEL'})
        self.assertEqual(status, 202)
        self.request('PATCH', '/api/settings', {'queueWhenBusy': False})  # with the waiting line off, a busy Bot refuses as it always did
        self.assertEqual(self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'busy'})[0], 409)
        self.assertEqual(self.request('POST', '/api/jobs/'+reply['jobId']+'/cancel')[1]['status'], 'cancelled')
        time.sleep(.1)
        self.assertEqual(self.request('GET', '/api/jobs/'+reply['jobId'])[1]['status'], 'cancelled')
        messages = self.request('GET', '/api/state')[1]['bots'][0]['messages']
        self.assertEqual(messages[-1]['status'], 'cancelled')


    def test_bot_inherits_global_provider(self):
        self.assertEqual(self.request('PATCH', '/api/settings', {'provider':'claude'})[0], 200)
        status, bot = self.request('POST', '/api/bots', {'name':'Inherit', 'provider':''})
        self.assertEqual(status, 201)
        self.assertEqual(bot['provider'], '')
        self.assertEqual(self.request('PATCH', '/api/settings', {'provider':''})[0], 400)
        reply = self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'hello'})[1]
        for _ in range(100):
            job = self.request('GET', '/api/jobs/'+reply['jobId'])[1]
            if job['status'] != 'running': break
            time.sleep(.02)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['content'], 'claude response')
        self.assertEqual(self.request('GET', '/api/state')[1]['bots'][0]['provider'], '')

    def test_failure_validation_and_recovery(self):
        bot = self.request('GET', '/api/state')[1]['bots'][0]
        before = self.request('GET', '/api/state')[1]['settings']
        self.assertEqual(self.request('PATCH', '/api/settings', {'model':'new', 'provider':'bogus'})[0], 400)
        self.assertEqual(self.request('GET', '/api/state')[1]['settings'], before)
        reply = self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'FAIL_CLI'})[1]
        for _ in range(100):
            job = self.request('GET', '/api/jobs/'+reply['jobId'])[1]
            if job['status'] != 'running': break
            time.sleep(.02)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(self.request('GET', '/api/state')[1]['bots'][0]['messages'][-1]['status'], 'failed')
        reply = self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'WAIT_FOR_CANCEL'})[1]
        self.assertEqual(self.request('DELETE', '/api/bots/'+bot['id'])[0], 409)
        self.proc.terminate(); self.proc.wait(timeout=8); self.proc.stdout.close(); self.proc.stderr.close()
        self.start_server()
        self.assertEqual(self.request('GET', '/api/jobs/'+reply['jobId'])[1]['status'], 'failed')

    def test_sigterm_kills_job_descendants(self):
        bot = self.request('GET', '/api/state')[1]['bots'][0]
        self.request('POST', '/api/chat', {'botId':bot['id'], 'content':'WAIT_FOR_CANCEL'})
        for _ in range(100):
            if (self.root/'child.pid').exists(): break
            time.sleep(.02)
        self.assertTrue((self.root/'child.pid').exists())
        pid = int((self.root/'child.pid').read_text())
        self.proc.terminate(); self.proc.wait(timeout=8); self.proc.stdout.close(); self.proc.stderr.close()
        # A killed process may briefly remain as a zombie pending reaping.
        alive = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
        self.assertTrue(not alive or alive.startswith('Z'), alive)
        self.start_server()

class UsageTest(unittest.TestCase):
    def test_codex_model_list_rpc(self):
        spec = importlib.util.spec_from_file_location('swarmr_server_rpc', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory)/'codex'
            cli.write_text("#!/usr/bin/env python3\nimport json,sys\nfor line in sys.stdin:\n m=json.loads(line)\n if m.get('id')==1: print(json.dumps({'id':1,'result':{}}),flush=True)\n if m.get('id')==2: print(json.dumps({'id':2,'result':{'data':[{'id':'safe-model','displayName':'Safe Model','account':'secret'},{'id':'hidden','hidden':True}]}}),flush=True)\n")
            cli.chmod(0o755)
            models = module.codex_models_cli(str(cli))
            self.assertEqual(models, [{'id':'safe-model','name':'Safe Model','source':'cli'}])

    def test_models_cache_filter_and_missing_cli(self):
        spec = importlib.util.spec_from_file_location('swarmr_server_models', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); (home/'.codex').mkdir()
            cache = {'identity':{'email':'secret@example.com'}, 'models':[
                {'slug':'model-ok','display_name':'Model OK','visibility':'list','description':'secret'},
                {'slug':'hidden-model','visibility':'hide'}, {'slug':'hidden-flag','hidden':True}, {'slug':'bad\nname','visibility':'list'},
                {'slug':'model-ok','display_name':'Duplicate'}]}
            (home/'.codex/models_cache.json').write_text(json.dumps(cache))
            with mock.patch.object(module.pathlib.Path, 'home', return_value=home), mock.patch.object(module, 'find_cli', return_value=None):
                result = module.model_list('codex')
                self.assertEqual(result['source'], 'cache')
                self.assertEqual(result['models'], [{'id':'model-ok','name':'Model OK','source':'cache'}])
                self.assertNotIn('secret', json.dumps(result))
                (home/'.codex/models_cache.json').unlink()
                self.assertEqual(module.model_list('codex')['status'], 'unavailable')

    def test_models_cli_failure_falls_back(self):
        spec = importlib.util.spec_from_file_location('swarmr_server_models_fallback', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); (home/'.codex').mkdir()
            (home/'.codex/models_cache.json').write_text(json.dumps({'models':[{'slug':'fallback'}]}))
            with mock.patch.object(module.pathlib.Path, 'home', return_value=home), mock.patch.object(module, 'find_cli', return_value='/fake'), mock.patch.object(module, 'codex_models_cli', side_effect=TimeoutError):
                result = module.model_list('codex')
            self.assertEqual(result['models'][0]['id'], 'fallback')
            self.assertEqual(result['source'], 'cache')

    def test_timeout_kills_sigterm_resistant_process(self):
        import threading
        spec = importlib.util.spec_from_file_location('swarmr_server_timeout', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cli = root/'codex'
            cli.write_text('#!/usr/bin/env python3\nimport signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n')
            cli.chmod(0o755)
            store = module.Store(root/'data'); bot = store.data['bots'][0]
            bot['messages'].append({'id':'msg','role':'assistant','content':'','status':'running','createdAt':'now'})
            job = {'id':'job','botId':bot['id'],'messageId':'msg','status':'running'}
            store.data['jobs'].append(job)
            app = module.App(('127.0.0.1', 0), store, root, 'token')
            try:
                with mock.patch.object(module, 'JOB_TIMEOUT', .5), mock.patch.object(module, 'find_cli', return_value=str(cli)):
                    thread = threading.Thread(target=app.run_job, args=('job', 'test', 'codex', ''))
                    thread.start(); thread.join(timeout=6)
                    self.assertFalse(thread.is_alive(), 'timeout left job running')
                self.assertEqual(job['status'], 'failed')
                self.assertIn('逾時', job['error'])
            finally: app.server_close()

    def test_cli_out_of_credits_is_actionable(self):
        import threading
        spec = importlib.util.spec_from_file_location('swarmr_server_credits', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cli = root/'codex'
            cli.write_text('#!/usr/bin/env python3\nimport sys\nsys.stdin.read()\nsys.stderr.write("ERROR: Your workspace is out of credits. Add credits to continue.\\n")\nsys.exit(1)\n')
            cli.chmod(0o755)
            store = module.Store(root/'data'); bot = store.data['bots'][0]
            bot['messages'].append({'id':'msg','role':'assistant','content':'','status':'running','createdAt':'now'})
            job = {'id':'job','botId':bot['id'],'messageId':'msg','status':'running'}
            store.data['jobs'].append(job)
            app = module.App(('127.0.0.1', 0), store, root, 'token')
            try:
                with mock.patch.object(module, 'find_cli', return_value=str(cli)):
                    app.run_job('job', 'test', 'codex', '')
                self.assertEqual(job['status'], 'failed')
                self.assertIn('額度', job['error'])
            finally: app.server_close()

    def test_startup_recovery_and_legacy_mcp(self):
        import builtins
        spec = importlib.util.spec_from_file_location('swarmr_server_legacy', SERVER)
        if str(SERVER.parent) not in sys.path: sys.path.insert(0, str(SERVER.parent))  # where the vendored TOML reader is, as when Zook runs
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); (home/'.codex').mkdir()
            (home/'.codex/config.toml').write_text('[mcp_servers.example]\ncommand = "hidden"\n')
            original_import = builtins.__import__
            def legacy_import(name, *args, **kwargs):
                if name == 'tomllib': raise ImportError('legacy')
                return original_import(name, *args, **kwargs)
            with mock.patch.object(module.pathlib.Path, 'home', return_value=home), mock.patch('builtins.__import__', side_effect=legacy_import):
                entries = module.integrations(module.Store(home/'inventory-data'))['mcp']
            self.assertIn('example', [entry['name'] for entry in entries])
            self.assertIn('builtin:workspace', [entry['id'] for entry in entries])
            self.assertNotIn('hidden', json.dumps(entries))
            store = module.Store(home/'data'); bot = store.data['bots'][0]
            msg = {'id':'msg', 'role':'assistant', 'content':'', 'status':'running', 'createdAt':'now'}
            bot['messages'].append(msg)
            store.data['jobs'].append({'id':'job','botId':bot['id'],'messageId':'msg','status':'running'})
            store.save()
            restored = module.Store(home/'data')
            self.assertEqual(restored.data['jobs'][0]['status'], 'failed')
            self.assertEqual(restored.data['bots'][0]['messages'][0]['status'], 'failed')

    def test_daily_deltas_and_stream_deduplication(self):
        spec = importlib.util.spec_from_file_location('swarmr_server', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); cp = home/'.codex/sessions/2026/11/01'; cp.mkdir(parents=True)
            cl = home/'.claude/projects/test'; cl.mkdir(parents=True)
            def event(day, payload, kind='event_msg'):
                return {'timestamp':'2026-11-%02dT00:00:00Z'%day, 'type':kind, 'payload':payload}
            def snap(day, inp, out):
                return event(day, {'type':'token_count', 'info':{'total_token_usage':{'input_tokens':inp,'output_tokens':out}}})
            records = [event(1, {'model':'model-a'}, 'turn_context'), snap(1, 100, 10), snap(1, 100, 10), snap(2, 150, 20), snap(2, 10, 2), snap(2, 'bad', 4)]
            (cp/'a.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in records))
            def assistant(day, mid, inp, out):
                return {'timestamp':'2026-11-%02dT00:00:00Z'%day, 'type':'assistant','message':{'id':mid,'model':'model-b','usage':{'input_tokens':inp,'output_tokens':out}}}
            records = [assistant(1, 'm1', 10, 1), assistant(1, 'm1', 10, 5), assistant(2, 'm2', 20, 4), assistant(2, 'm3', 'bad', 4), assistant(3, 'm4', 0, 0)]
            (cl/'a.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in records))
            with mock.patch.object(module.pathlib.Path, 'home', return_value=home): result = module.usage()
            groups = {(x['date'], x['provider']):x for x in result['groups']}
            self.assertEqual((groups['2026-11-01','codex']['inputTokens'], groups['2026-11-01','codex']['outputTokens']), (100,10))
            self.assertEqual((groups['2026-11-02','codex']['inputTokens'], groups['2026-11-02','codex']['outputTokens']), (60,12))
            self.assertEqual(groups['2026-11-02','codex']['model'], 'model-a')
            self.assertEqual((groups['2026-11-01','claude']['inputTokens'], groups['2026-11-01','claude']['outputTokens']), (10,5))
            self.assertEqual(groups['2026-11-02','claude']['inputTokens'], 20)
            self.assertTrue(all(x['sessions'] == 1 for x in groups.values()))
            self.assertEqual(result['sessionCount'], 2)
            self.assertNotIn(('2026-11-03','claude'), groups)

if __name__ == '__main__': unittest.main()

class WorkerSecurityTest(unittest.TestCase):
    def test_approval_and_worker_scope(self):
        import threading
        import urllib.request
        spec = importlib.util.spec_from_file_location('backend_test_server', SERVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            store = module.Store(directory); bot = store.data['bots'][0]
            job = {'id':'one', 'botId':bot['id'], 'messageId':'missing', 'status':'running', 'toolCalls':[], 'approvals':[]}
            other = {'id':'two', 'botId':bot['id'], 'messageId':'missing', 'status':'running', 'toolCalls':[], 'approvals':[]}
            store.data['jobs'].extend([job, other]); store.save()
            app = module.App(('127.0.0.1', 0), store, directory, 'ui-token')
            class Session:
                def call(self, name, args): return {'content':[{'type':'text','text':name}]}
                def close(self): pass
            app.workers['one'] = {'token':'worker-one', 'tools':[], 'session':Session()}
            app.workers['two'] = {'token':'worker-two', 'tools':[], 'session':Session()}
            thread = threading.Thread(target=app.serve_forever, daemon=True); thread.start()
            def post(path, token, body):
                conn = http.client.HTTPConnection('127.0.0.1', app.server_port, timeout=3)
                conn.request('POST', path, json.dumps(body), {'Authorization':'Bearer '+token}); res = conn.getresponse(); data=json.loads(res.read()); conn.close(); return res.status, data
            try:
                self.assertEqual(post('/api/worker/one', 'ui-token', {'method':'tools/list'})[0], 403)
                self.assertEqual(post('/api/worker/two', 'worker-one', {'method':'tools/list'})[0], 403)
                self.assertEqual(post('/api/worker/one', 'worker-one', {'method':'tools/list'})[0], 200)
                self.assertEqual(post('/api/approvals/nope', 'worker-one', {'decision':'approve'})[0], 403)
                module_event = {'id':'call', 'name':'write', 'source':'workspace', 'status':'waiting_approval', 'arguments':{'path':'a'}}
                app.record_event('one', module_event)
                result=[]; pending=threading.Thread(target=lambda: result.append(app.approve('one', 'call', 'write', {'path':'a'}, 'workspace'))); pending.start()
                for _ in range(100):
                    if job['approvals']: break
                    time.sleep(.01)
                aid = job['approvals'][0]['id']
                self.assertEqual(post('/api/approvals/'+aid, 'ui-token', {'decision':'deny'})[1]['status'], 'denied')
                pending.join(2); self.assertEqual(result, [False])
                self.assertEqual(post('/api/approvals/'+aid, 'ui-token', {'decision':'approve'})[0], 409)
                pending=threading.Thread(target=lambda: result.append(app.approve('one', 'second', 'write', {}, 'workspace'))); pending.start()
                for _ in range(100):
                    if len(job['approvals']) == 2: break
                    time.sleep(.01)
                with store.lock: app.expire_job('one')
                pending.join(2); self.assertFalse(result[-1]); self.assertEqual(job['approvals'][-1]['status'], 'expired')
            finally:
                app.shutdown(); app.server_close(); thread.join()
