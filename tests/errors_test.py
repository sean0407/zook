# -*- coding: utf-8 -*-
"""Why a CLI could not answer: one classifier, whole phrases only."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_errors', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        kind = load().classify_error
        cases = {
            'Failed to authenticate. API Error: 403 Forbidden': 'denied',
            'Error: Not logged in · Please run /login': 'auth',
            'unexpected status 401 Unauthorized: token has expired': 'auth',
            "You've hit your usage limit. Upgrade to Pro or try again in 3 hours.": 'quota',
            'insufficient_quota: You exceeded your current quota': 'quota',
            'Credit balance is too low to access the API': 'quota',
            'stream error: last status: 429 Too Many Requests': 'rate',
            '{"type":"overloaded_error","message":"Overloaded"}': 'busy',
            'upstream connect error, status 503': 'busy',
            "This model's maximum context length is 200000 tokens": 'context',
            'The model `gpt-9` does not exist or you do not have access to it.': 'model',
            'error sending request for url (https://api.example.com): connection refused': 'network',
            'getaddrinfo ENOTFOUND api.example.com': 'network',
            'something went sideways': 'unknown', '': 'unknown', None: 'unknown',
        }
        for text, expected in cases.items(): self.assertEqual(kind(text), expected, text)

    def test_bare_numbers_and_words_are_not_errors(self):
        kind = load().classify_error
        for text in ('listening on port 4010', 'request id 401abc429', 'the file quota.txt was read', 'see section 403 of the code', 'retry budget 503 ms', 'model card updated', 'network settings saved'):
            self.assertEqual(kind(text), 'unknown', text)

    def test_every_kind_has_a_sentence_and_a_reason(self):
        m = load()
        kinds = [k for k, _ in m.ERROR_PHRASES] + ['unknown']
        self.assertEqual(sorted(kinds), sorted(m.ERROR_MESSAGES)); self.assertEqual(sorted(kinds), sorted(m.ERROR_REASONS))
        for k in kinds:
            self.assertEqual(m.ERROR_MESSAGES[k].count('%s'), 1)
            self.assertEqual(m.fallback_reason(m.ERROR_MESSAGES[k] % 'Codex'), m.ERROR_REASONS[k] if k != 'denied' else '尚未登入', k)  # what the reply says when a backup model took over


CODEX = '''#!/usr/bin/env python3
import json, os, sys
sys.stdin.read()
mode = open(os.path.join(os.path.dirname(sys.argv[0]), 'mode')).read().strip()
if mode == 'talks-about-limits':
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Your plan has a usage limit and a quota; not logged in users see 401 Unauthorized.'}})); sys.exit(0)
if mode == 'network':
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'echo usage limit quota exceeded'}}))
    print(json.dumps({'type': 'turn.failed', 'error': {'message': 'stream disconnected before completion: error sending request'}})); sys.exit(1)
if mode == 'limit':
    print(json.dumps({'type': 'error', 'message': "You've hit your usage limit. Try again later."})); sys.exit(1)
if mode == 'secret':
    sys.stderr.write('panic at /Users/someone/.codex/auth.json token=sk-live-123456\\n'); sys.exit(2)
'''


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'E', 'provider': 'codex'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def ask(self, mode):
        (self.root / 'bin/mode').write_text(mode)
        job_id = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'hi'})[1]['jobId']
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.1)
        self.fail('no reply')

    def test_what_the_bot_says_is_not_mistaken_for_an_error(self):
        job = self.ask('talks-about-limits')
        self.assertEqual(job['status'], 'completed', job.get('error'))

    def test_the_cli_error_decides_not_the_work_it_did(self):
        job = self.ask('network')  # it ran a command that printed "usage limit", then lost its connection
        self.assertEqual((job['status'], job['errorKind']), ('failed', 'network')); self.assertIn('連不上 Codex', job['error'])
        job = self.ask('limit')
        self.assertEqual(job['errorKind'], 'quota'); self.assertIn('額度已用完', job['error'])

    def test_raw_output_is_never_shown(self):
        job = self.ask('secret')
        self.assertEqual(job['errorKind'], 'unknown')
        for leak in ('sk-live', 'auth.json', '/Users/', 'panic'): self.assertNotIn(leak, job['error'])


if __name__ == '__main__':
    unittest.main()
