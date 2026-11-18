# -*- coding: utf-8 -*-
"""Antigravity through its official CLI, agy."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_agy', SERVER); server = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(server)
USAGE = {'status': 'SUCCESS', 'response': 'x', 'command': {'name': 'usage', 'data': {'groups': [
    {'name': 'Gemini Models', 'buckets': [{'window': 'weekly', 'remaining_fraction': 0.75, 'reset_time': '2026-11-25T04:26:45Z'}]},
    {'name': 'Claude and GPT models', 'buckets': [{'window': 'weekly', 'remaining_fraction': 1.0, 'reset_time': '2026-11-25T04:29:49Z'}]}]}}}
AGY = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0])
if a == ['models']: print('Fetching available models...\\ngemini-3.8-flash-low\\tGemini 3.8 Flash (Low)'); sys.exit(0)
if a == ['--version']: print('1.5.10'); sys.exit(0)
if a[:2] == ['-p', '/usage']: print(open(os.path.join(here, 'usage.json')).read()); sys.exit(0)
config = open('.agents/mcp_config.json').read() if os.path.exists('.agents/mcp_config.json') else ''
prompt = json.loads(sys.stdin.readline())['message']['content']
json.dump(dict(args=a, cwd=os.getcwd(), config=config, token=os.environ.get('ZOOK_WORKER_TOKEN', ''), prompt=prompt), open(os.path.join(here, 'run.json'), 'w'))
print(json.dumps(dict(event='init', init=dict(cwd=os.getcwd()))))
if 'BUSY' in prompt: print(json.dumps(dict(event='result', result=dict(status='ERROR', error='UNAVAILABLE: No capacity available for model')))); sys.exit(3)
print(json.dumps(dict(event='result', result=dict(status='SUCCESS', response='agy says hi\\n', usage=dict(input_tokens=100, output_tokens=7, thinking_tokens=2, cache_read_tokens=40, total_tokens=107)))))
"""


class Units(unittest.TestCase):
    def test_reply_and_usage(self):
        out = server.parse_cli_output('antigravity', json.dumps(dict(event='result', result=dict(status='SUCCESS', response='OK\n', usage=dict(input_tokens=10, output_tokens=2, cache_read_tokens=4)))), 'm')
        self.assertEqual((out['content'], out['usage']['input'], out['usage']['cachedInput'], out['usage']['output']), ('OK', 10, 4, 2))
        self.assertTrue(server.parse_cli_output('antigravity', json.dumps(dict(event='result', result=dict(status='ERROR', error='boom'))))['isError'])
        self.assertTrue(server.parse_cli_output('antigravity', 'not json')['unparsable'])
        self.assertEqual(server.antigravity_error('the MCP server is unavailable'), '')

    def test_careful_runs_cannot_change_anything_and_credits_stay_off(self):
        s = server.antigravity_settings(False, 'workspace', False)
        self.assertFalse(s['useG1Credits'])
        for rule in ('write_file(*)', 'command(*)', 'execute_url(*)', 'read_url(*)'): self.assertIn(rule, s['permissions']['deny'])
        self.assertIn('mcp(zook/*)', s['permissions']['allow'])
        args = server.antigravity_args('agy', '', 'standard', False, True, 'full', '/x', True)
        self.assertEqual(args[args.index('--mode') + 1], 'plan'); self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertIn('--dangerously-skip-permissions', server.antigravity_args('agy', '', 'deep', True, False, 'full', '/x', True))
        self.assertIn('--sandbox', server.antigravity_args('agy', '', 'deep', True, False, 'workspace', '/x', True))
        self.assertEqual(server.antigravity_args('agy', 'm', 'deep', False, False, 'workspace', '/x', True)[-4:], ['--model', 'm', '--effort', 'high'])

    def test_a_planted_tool_config_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            work, chosen = Path(d) / 'w', Path(d) / 'c'; chosen.mkdir()
            for name in server.AGY_ROOTS: (work / name).mkdir(parents=True); (work / name / 'hooks.json').write_text('{}')
            server.prepare_antigravity_folder(work, 'workspace', work, 100)
            self.assertEqual(sorted(p.name for p in work.iterdir()), ['.agents']); self.assertEqual([p.name for p in (work / '.agents').iterdir()], ['mcp_config.json'])
            for name in server.AGY_ROOTS:
                (chosen / name).mkdir()
                with self.assertRaises(RuntimeError): server.prepare_antigravity_folder(work, 'folder', chosen, 100)
                (chosen / name).rmdir()
            server.prepare_antigravity_folder(work, 'folder', chosen, 100)


class Chat(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/agy'; cli.write_text(AGY); cli.chmod(0o755); (self.root / 'bin/usage.json').write_text(json.dumps(USAGE))
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.assertEqual(self.req('POST', '/api/accounts/antigravity/add', {})[0], 200)
        self.bot = self.req('POST', '/api/bots', {'name': 'A', 'provider': 'antigravity'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30); c.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d)

    def ask(self, **more):
        status, sent = self.req('POST', '/api/chat', dict({'botId': self.bot['id'], 'content': 'hello'}, **more)); self.assertEqual(status, 202, sent)
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            if job['status'] != 'running': return job
            time.sleep(0.2)
        self.fail('no reply')

    def test_reply_tools_cleanup_and_quota(self):
        job = self.ask()
        self.assertEqual((job['status'], job['content'], job['usage']['provider'], job['usage']['input']), ('completed', 'agy says hi', 'antigravity', 100))
        run = json.loads((self.root / 'bin/run.json').read_text())
        self.assertEqual(run['cwd'], str((self.root / 'data/workspaces' / self.bot['id']).resolve()))
        self.assertIn('tool_server.py', run['config']); self.assertTrue(run['token']); self.assertNotIn(run['token'], run['config'])
        self.assertNotIn(run['token'], ' '.join(run['args'])); self.assertIn('hello', run['prompt']); self.assertNotIn('hello', ' '.join(run['args']))  # the conversation is not on the command line
        self.assertFalse((self.root / 'data/workspaces' / self.bot['id'] / '.agents').exists())
        card = next(p for p in self.req('GET', '/api/quota')[1]['providers'] if p['id'] == 'antigravity')
        self.assertEqual((card['status'], card['noQuotaApi']), ('logged_in', False))
        self.assertEqual([(w['label'], w['usedPercent']) for w in card['quota']['windows']], [('Gemini 模型 · 每週', 25.0), ('Claude 與 GPT 模型 · 每週', 0.0)])
        self.assertEqual(self.req('GET', '/api/models?provider=antigravity')[1]['models'][0]['id'], 'gemini-3.8-flash-low')

    def test_plan_is_read_only_and_errors_are_explained(self):
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'bypass'})
        self.ask(plan=True)
        args = json.loads((self.root / 'bin/run.json').read_text())['args']
        self.assertEqual(args[args.index('--mode') + 1], 'plan'); self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertIn('太忙', self.ask(content='BUSY')['error'])


if __name__ == '__main__': unittest.main()
