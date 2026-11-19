# -*- coding: utf-8 -*-
"""A reply shown while it is being written."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_stream', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class FeederTest(unittest.TestCase):
    def run_feed(self, kind, lines, chunk=7):
        m = load(); m.partial_start(dict(id='j', messageId='m'))
        feed = m.partial_feeder(kind, 'j'); seen = []
        data = ''.join(json.dumps(x, ensure_ascii=False) + '\n' if not isinstance(x, str) else x + '\n' for x in lines).encode('utf-8')
        for i in range(0, len(data), chunk):  # arrives in pieces that cut lines and characters in half
            feed(data[i:i + chunk])
            if not seen or seen[-1] != m.partial_text('j'): seen.append(m.partial_text('j'))
        return m, seen

    def test_claude_words_arrive_one_by_one(self):
        ev = lambda e, **more: dict(type='stream_event', event=e, **more)
        delta = lambda t: ev(dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text=t)))
        m, seen = self.run_feed('claude', [dict(type='system', subtype='init'), ev(dict(type='message_start')), delta('我先'), delta('查一下。'),
                                           ev(dict(type='content_block_delta', delta=dict(type='input_json_delta', partial_json='{"q"'))),
                                           ev(dict(type='content_block_delta', delta=dict(type='text_delta', text='子代理的話')), parent_tool_use_id='t1'),
                                           'not json at all', ev(dict(type='message_start')), delta('台北是'), delta('首都。'), dict(type='result', result='台北是首都。')])
        self.assertIn('我先查一下。', seen); self.assertEqual(seen[-1], '台北是首都。')  # the second message replaced the first
        self.assertFalse(any('子代理' in s or '{"q"' in s for s in seen))
        self.assertIn('台北是', seen)  # really piece by piece, not only the end

    def test_other_clis(self):
        step = lambda i, t: dict(event='step_update', step_update=dict(step_index=i, state='ACTIVE', step_type='agent_response', text_delta=t))
        m, seen = self.run_feed('antigravity', [dict(event='init'), dict(event='step_update', step_update=dict(step_index=0, step_type='user_input')), step(1, '先看'), step(1, '檔案'), step(3, '結論'), step(3, '如下')])
        self.assertIn('先看檔案', seen); self.assertEqual(seen[-1], '結論如下')
        m, seen = self.run_feed('grok', [dict(type='thought', data='想一想'), dict(type='text', data='你'), dict(type='text', data='好'), dict(type='end')])
        self.assertEqual(seen[-1], '你好'); self.assertFalse(any('想一想' in s for s in seen))
        m, seen = self.run_feed('codex', [dict(type='thread.started'), dict(type='item.completed', item=dict(type='agent_message', text='第一段')), dict(type='item.completed', item=dict(type='command_execution', command='ls')),
                                          dict(type='item.completed', item=dict(type='agent_message', text='最後的回覆'))])
        self.assertEqual([s for s in seen if s], ['第一段', '最後的回覆'])
        self.assertIsNone(m.partial_feeder('plain', 'j')); self.assertIsNone(m.partial_feeder('gemini', 'j'))

    def test_nothing_is_kept_after_the_reply(self):
        m, seen = self.run_feed('grok', [dict(type='text', data='半句')])
        self.assertEqual(m.partial_of_message('m'), '半句'); self.assertEqual(m.job_view(dict(id='j', status='running'))['partial'], '半句')
        self.assertNotIn('partial', m.job_view(dict(id='j', status='completed')))
        m.partial_start(dict(id='j', messageId='m')); self.assertEqual(m.partial_text('j'), '')  # another model takes over: the half reply is gone
        m.partial_end('j'); self.assertEqual(m.partial_of_message('m'), '')


CODEX = '''#!/usr/bin/env python3
import json, os, sys, time
sys.stdin.read()
mode = open(os.path.join(os.path.dirname(sys.argv[0]), 'mode')).read().strip()
say = lambda t: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': t}}), flush=True)
say('先說第一段'); time.sleep(1.2)
if mode == 'fail': print(json.dumps({'type': 'turn.failed', 'error': {'message': 'stream disconnected'}}), flush=True); sys.exit(1)
say('這是完整的最後回覆'); time.sleep(0.3)
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 5}}), flush=True)
'''
CLAUDE = '''#!/usr/bin/env python3
import json, os, sys, time
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)  # Zook asking what this CLI can do
sys.stdin.read()
open(os.path.join(os.path.dirname(sys.argv[0]), 'claude.args'), 'w').write(' '.join(sys.argv[1:]))
time.sleep(0.8)
print(json.dumps({'type': 'result', 'result': '備用模型的回覆', 'is_error': False, 'usage': {'input_tokens': 3, 'output_tokens': 2}}))
'''


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name, text in (('codex', CODEX), ('claude', CLAUDE)):
            cli = self.root / 'bin' / name; cli.write_text(text); cli.chmod(0o755)
        (self.root / 'bin/mode').write_text('ok')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'S', 'provider': 'codex'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def events(self, job_id):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request('GET', '/api/jobs/%s/stream' % job_id, headers={'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); self.assertEqual(resp.getheader('Content-Type'), 'text/event-stream; charset=utf-8')
        out = [json.loads(line[6:]) for line in resp.read().decode('utf-8').splitlines() if line.startswith('data: ')]
        conn.close(); return out

    def send(self, bot=None):
        return self.req('POST', '/api/chat', {'botId': (bot or self.bot)['id'], 'content': 'hi'})[1]['jobId']

    def wait(self, job_id):
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.1)
        self.fail('no reply')

    def test_stream_then_the_finished_reply(self):
        job_id = self.send()
        seen = []
        watcher = threading.Thread(target=lambda: seen.extend(self.events(job_id))); watcher.start()
        time.sleep(0.6)
        polled = self.req('GET', '/api/jobs/' + job_id)[1]
        self.assertEqual((polled['status'], polled.get('partial')), ('running', '先說第一段'))  # the phone's way: asking again
        watcher.join(timeout=15)
        self.assertEqual(seen[0], {'text': '先說第一段'}); self.assertEqual(seen[-1], {'done': True})
        self.assertIn({'text': '這是完整的最後回覆'}, seen)  # not a continuation of the first, so it is sent whole
        job = self.wait(job_id)
        self.assertEqual((job['content'], job['usage']['input']), ('這是完整的最後回覆', 10)); self.assertNotIn('partial', job)
        self.assertNotIn('partial', json.dumps(self.req('POST', '/api/export', {})[1]))  # never written to the data file
        self.assertEqual(self.events(job_id), [{'done': True}])  # asking afterwards ends at once
        self.assertEqual(self.req('GET', '/api/jobs/nope/stream')[0], 404)

    def test_half_reply_is_dropped_when_a_backup_takes_over(self):
        self.req('PATCH', '/api/settings', {'fallbacks': ['claude']}); (self.root / 'bin/mode').write_text('fail')
        job_id = self.send(); time.sleep(0.6)
        self.assertEqual(self.req('GET', '/api/jobs/' + job_id)[1].get('partial'), '先說第一段')
        time.sleep(1.1)  # codex has failed; claude is answering and has shown nothing yet
        self.assertNotIn('partial', self.req('GET', '/api/jobs/' + job_id)[1])
        job = self.wait(job_id)
        end = time.time() + 3
        while 'fallback' not in job and time.time() < end: time.sleep(0.05); job = self.req('GET', '/api/jobs/' + job_id)[1]  # the note is written a moment after the reply
        self.assertEqual((job['content'], job['fallback']['provider']), ('備用模型的回覆', 'claude'))
        self.assertIn('--include-partial-messages', (self.root / 'bin/claude.args').read_text())

    def test_switched_off_is_as_before(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'streamReplies': 'no'})[0], 400)
        self.req('PATCH', '/api/settings', {'streamReplies': False, 'fallbacks': ['claude']})
        job_id = self.send(); time.sleep(0.6)
        self.assertNotIn('partial', self.req('GET', '/api/jobs/' + job_id)[1])
        self.assertEqual(self.wait(job_id)['content'], '這是完整的最後回覆')
        (self.root / 'bin/mode').write_text('fail'); self.wait(self.send())
        self.assertNotIn('--include-partial-messages', (self.root / 'bin/claude.args').read_text())  # the CLI is called the way it was


if __name__ == '__main__':
    unittest.main()
