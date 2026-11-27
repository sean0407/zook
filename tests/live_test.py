# -*- coding: utf-8 -*-
"""A conversation's CLI stays open between messages, and everything else about a reply stays as it was."""
import http.client, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
# A fake Claude. Started the usual way it answers once and ends; with --input-format stream-json it stays and answers every line.
CLAUDE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, uuid
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv: print('--print --output-format --mcp-config --allowedTools --tools --effort --resume --session-id --input-format --replay-user-messages'); sys.exit(0)
if '--version' in sys.argv: print('9.9.9 (fake)'); sys.exit(0)
here = os.path.dirname(sys.argv[0]); live = '--input-format' in sys.argv
session = sys.argv[sys.argv.index('--resume') + 1] if '--resume' in sys.argv else 'sess-' + uuid.uuid4().hex[:8]
late_call = '--late-call' in sys.argv  # the helper below that makes the call after the answer (not a start of the CLI)
if not late_call: open(os.path.join(here, 'starts.log'), 'a').write(json.dumps(dict(pid=os.getpid(), live=live, resume='--resume' in sys.argv, web='WebSearch' in ' '.join(sys.argv), pwd_ok=os.path.realpath(os.environ.get('PWD', '')) == os.path.realpath(os.getcwd()))) + '\n')
def tool():
    if not os.path.exists(os.path.join(here, 'call.json')) or '--mcp-config' not in sys.argv: return ''
    config = json.loads(sys.argv[sys.argv.index('--mcp-config') + 1])['mcpServers']['zook']
    proc = subprocess.Popen([config['command']] + config['args'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(i, method, params):
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\n'); proc.stdin.flush()
        return json.loads(proc.stdout.readline())
    rpc(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}})
    out = rpc(2, 'tools/call', json.load(open(os.path.join(here, 'call.json'))))
    proc.stdin.close(); proc.wait(timeout=5)
    return ' TOOL:' + json.dumps(out.get('result') or out.get('error'), ensure_ascii=False)
if late_call:  # written whole, then put in place: the test waits for the file, never for a half-written one
    said = tool(); open(os.path.join(here, 'late.tmp'), 'w').write(said); os.replace(os.path.join(here, 'late.tmp'), os.path.join(here, 'late.log')); sys.exit(0)
count = 0
def answer(text):
    global count; count += 1
    open(os.path.join(here, 'got.log'), 'a').write('%d\n' % os.getpid())  # the test waits for this instead of guessing how long delivery takes
    if 'DIE' in text and live: os._exit(3)
    if os.path.exists(os.path.join(here, 'slow.flag')):  # (the text of earlier messages is part of a later prompt, so a word in it cannot be the signal)
        import time; time.sleep(float(open(os.path.join(here, 'slow.flag')).read() or 30))
    print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': session}), flush=True)
    if live: print(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': text[:50]}, 'session_id': session}), flush=True)  # --replay-user-messages
    said = 'reply %d from %d%s' % (count, os.getpid(), tool())
    print(json.dumps({'duration_ms': 1, 'type': 'result', 'result': said, 'is_error': False, 'session_id': session, 'usage': {'input_tokens': 5, 'output_tokens': 2}}), flush=True)
if live:
    for line in sys.stdin:
        try: text = json.loads(line)['message']['content']
        except (ValueError, KeyError, TypeError): continue
        answer(text)
        import time
        if os.path.exists(os.path.join(here, 'late.flag')):  # goes on working after it has answered
            # #346: Zook closes this CLI as soon as the call is refused, which could cut the note short under load. The call is
            # made by a helper in its own process group, so the refusal it got is always written down.
            os.remove(os.path.join(here, 'late.flag')); time.sleep(0.4)
            subprocess.Popen([sys.executable, sys.argv[0], '--late-call'] + sys.argv[1:], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        if os.path.exists(os.path.join(here, 'stray.flag')):  # says something more after it has answered
            os.remove(os.path.join(here, 'stray.flag')); time.sleep(0.3)
            print(json.dumps({'type': 'result', 'result': 'STRAY', 'is_error': False, 'session_id': session, 'usage': {'input_tokens': 1, 'output_tokens': 1}}), flush=True)
            open(os.path.join(here, 'stray.done'), 'w').write('x')
else: answer(sys.stdin.read())
'''


def wait_for(check, seconds=20):
    """Wait until check() is true instead of a fixed sleep: under load (the whole suite at once, CI) things take longer."""
    end = time.time() + seconds
    while time.time() < end and not check(): time.sleep(0.05)
    return check()


def alive(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False


class LiveTest(unittest.TestCase):
    env = {}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/claude'; cli.write_text(CLAUDE); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='1', ZOOK_SHELL_ENV='0', **self.env)
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'provider': 'claude', 'permissionMode': 'auto'})
        self.bot = self.req('POST', '/api/bots', {'name': '助理', 'provider': 'claude'})[1]
        for _ in range(100):  # Zook has to have read the CLI's help before it keeps one open
            if 'claude' in (self.req('GET', '/api/state?full=1')[1].get('abilityChecks') or {}): break
            time.sleep(0.1)

    def tearDown(self):
        if self.proc.poll() is None: self.proc.terminate(); self.proc.wait(timeout=10)
        self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def starts(self):
        path = self.root / 'bin/starts.log'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def ask(self, text='hi', bot=None, approve=None):
        sent = self.req('POST', '/api/chat', {'botId': (bot or self.bot)['id'], 'content': text})[1]; end, asked = time.time() + 20, []
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            for a in job.get('approvals') or []:
                if a['status'] == 'pending' and a['id'] not in asked and approve is not None:
                    asked.append(a['id']); self.req('POST', '/api/approvals/' + a['id'], {'decision': 'approve' if approve else 'deny'})
            if job['status'] != 'running': job['asked'] = asked; return job
            time.sleep(0.05)
        self.fail('no reply')

    def test_second_message_does_not_start_the_cli_again(self):
        one, two, three = self.ask(), self.ask(), self.ask()
        self.assertEqual([j['status'] for j in (one, two, three)], ['completed'] * 3)
        self.assertEqual(len(self.starts()), 1); self.assertTrue(self.starts()[0]['live'])
        self.assertTrue(self.starts()[0]['pwd_ok'])  # a kept-open CLI is told the folder it really runs in, too
        pid = self.starts()[0]['pid']
        self.assertEqual([j['content'] for j in (one, two, three)], ['reply %d from %d' % (i, pid) for i in (1, 2, 3)])
        self.assertEqual([bool(j.get('kept')) for j in (one, two, three)], [False, True, True])
        self.assertEqual(one['usage']['input'], 5)  # each reply still has its own usage figures

    def test_switch_off_starts_it_for_every_message(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'keepCli': 'no'})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'keepCli': False})[0], 200)
        one, two = self.ask(), self.ask()
        self.assertEqual([s['live'] for s in self.starts()], [False, False]); self.assertEqual(self.starts()[1]['resume'], True)
        self.assertNotIn('kept', two); self.assertEqual(two['status'], 'completed')

    def test_another_conversation_and_changed_settings_get_their_own(self):
        self.ask(); self.ask()
        self.req('POST', '/api/bots/%s/chats' % self.bot['id'], {})
        self.ask()
        self.assertEqual(len(self.starts()), 2)  # a new conversation is another CLI
        self.req('PATCH', '/api/settings', {'webSearch': True})
        job = self.ask()
        self.assertEqual(len(self.starts()), 3); self.assertTrue(self.starts()[2]['web']); self.assertNotIn('kept', job)  # what it may use changed: started again with the new choice
        self.assertEqual(self.ask().get('kept'), True)

    def test_cli_that_went_away_is_started_again(self):
        self.ask(); pid = self.starts()[0]['pid']
        os.kill(pid, signal.SIGKILL); time.sleep(0.3)
        job = self.ask()
        self.assertEqual(job['status'], 'completed'); self.assertEqual(len(self.starts()), 2); self.assertTrue(self.starts()[1]['resume'])

    def test_message_is_still_answered_when_the_kept_cli_dies_on_it(self):
        self.ask()
        job = self.ask('DIE now')
        self.assertEqual(job['status'], 'completed', job.get('error')); self.assertTrue(job['liveOff'])
        self.assertEqual([s['live'] for s in self.starts()], [True, False])  # answered the usual way
        self.assertIn('reply 1 from', job['content'])

    def test_tool_calls_reach_the_reply_that_is_running_and_still_ask(self):
        self.ask()
        (self.root / 'bin/call.json').write_text(json.dumps(dict(name='zook_create_schedule', arguments=dict(content='每天整理', repeat='daily', time='09:00'))))
        denied = self.ask(approve=False)
        self.assertTrue(denied.get('kept')); self.assertEqual(len(denied['asked']), 1); self.assertEqual(self.req('GET', '/api/state')[1]['schedules'], [])
        allowed = self.ask(approve=True)
        self.assertTrue(allowed.get('kept')); self.assertEqual(len(allowed['asked']), 1)
        self.assertEqual([s['content'] for s in self.req('GET', '/api/state')[1]['schedules']], ['每天整理'])
        self.assertEqual(len(self.starts()), 1)
        # Between replies the kept CLI's address reaches nothing.
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('POST', '/api/worker/live-000000000000000000000000', json.dumps({'method': 'tools/list'}), {'Authorization': 'Bearer x', 'Host': '127.0.0.1:%d' % self.port})
        self.assertEqual(conn.getresponse().status, 403); conn.close()

    def got(self): return len((self.root / 'bin/got.log').read_text().split()) if (self.root / 'bin/got.log').exists() else 0

    def test_stopping_a_reply_ends_the_cli_and_the_next_message_works(self):
        self.ask(); pid = self.starts()[0]['pid']
        (self.root / 'bin/slow.flag').write_text('30')
        before = self.got(); sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'take your time'})[1]; wait_for(lambda: self.got() > before)
        self.req('POST', '/api/jobs/%s/cancel' % sent['jobId'], {}); (self.root / 'bin/slow.flag').unlink()
        self.assertEqual(self.req('GET', '/api/jobs/' + sent['jobId'])[1]['status'], 'cancelled')
        for _ in range(60):
            if not alive(pid): break
            time.sleep(0.1)
        self.assertFalse(alive(pid))
        self.assertEqual(self.ask()['status'], 'completed')

    def test_cli_that_keeps_working_after_its_answer_is_not_trusted_again(self):
        self.ask()
        (self.root / 'bin/call.json').write_text(json.dumps(dict(name='zook_remember', arguments=dict(content='偷偷記下', scope='shared'))))
        (self.root / 'bin/late.flag').write_text('x')
        self.ask(); self.assertTrue(wait_for(lambda: (self.root / 'bin/late.log').exists()))  # put in place only once the answer to the late call is written whole (#346)
        self.assertIn('連線已中斷', (self.root / 'bin/late.log').read_text(encoding='utf-8'))  # a tool call while no reply is running reaches nothing
        self.assertNotIn('偷偷記下', json.dumps(self.req('GET', '/api/state')[1]['memories'], ensure_ascii=False).replace('偷偷記下', '', 1))
        job = self.ask()
        self.assertNotIn('kept', job); self.assertEqual(len(self.starts()), 2)  # and that CLI is replaced
        (self.root / 'bin/stray.flag').write_text('x')
        self.ask(); self.assertTrue(wait_for(lambda: (self.root / 'bin/stray.done').exists()))
        self.assertTrue(wait_for(lambda: not alive(self.starts()[1]['pid'])))  # Zook has read the stray line: that CLI is closed (not a guessed pause, #346)
        job = self.ask()
        self.assertNotEqual(job['content'], 'STRAY'); self.assertIn('reply 1 from', job['content']); self.assertEqual(len(self.starts()), 3)  # words after the answer are no reply either

    def test_turns_nobody_typed_never_share_a_cli_with_the_users(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_server_for_live', SERVER); m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)
        args, env = ['claude', '--print', '--resume', 'abc', '--tools', 'Read'], {'A': '1', 'ZOOK_WORKER_URL': 'u', 'ZOOK_WORKER_TOKEN': 't'}
        user = m.live_mark(args, '/w', env, 'user')
        self.assertEqual(user, m.live_mark(['claude', '--print', '--resume', 'other', '--tools', 'Read'], '/w', dict(env, ZOOK_WORKER_TOKEN='x'), 'user'))
        for other in (m.live_mark(args, '/w', env, 'script'), m.live_mark(args, '/w', env, 'schedule'), m.live_mark(args + ['Bash'], '/w', env, 'user'), m.live_mark(args, '/x', env, 'user'), m.live_mark(args, '/w', dict(env, A='2'), 'user')):
            self.assertNotEqual(user, other)

    def test_switching_it_off_does_not_cut_a_reply_short(self):
        self.ask(); pid = self.starts()[0]['pid']
        (self.root / 'bin/slow.flag').write_text('3')
        before = self.got(); sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'take a moment'})[1]; self.assertTrue(wait_for(lambda: self.got() > before))
        self.req('PATCH', '/api/settings', {'keepCli': False}); (self.root / 'bin/slow.flag').unlink()
        for _ in range(100):
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            if job['status'] != 'running': break
            time.sleep(0.1)
        self.assertEqual(job['status'], 'completed', job.get('error')); self.assertEqual(len(self.starts()), 1)
        for _ in range(40):
            if not alive(pid): break
            time.sleep(0.1)
        self.assertFalse(alive(pid))  # closed once it had finished
        self.assertEqual(self.ask()['status'], 'completed'); self.assertFalse(self.starts()[-1]['live'])

    def test_no_more_than_four_are_kept_and_none_survive_closing(self):
        bots = [self.req('POST', '/api/bots', {'name': 'B%d' % i, 'provider': 'claude'})[1] for i in range(6)]
        for b in bots: self.ask(bot=b)
        pids = [s['pid'] for s in self.starts()]
        wait_for(lambda: sum(alive(p) for p in pids) <= 4)
        self.assertEqual(sum(alive(p) for p in pids), 4)
        self.assertEqual(self.ask(bot=bots[5]).get('kept'), True); self.assertNotIn('kept', self.ask(bot=bots[0]))  # the one unused longest made room
        self.proc.terminate(); self.proc.wait(timeout=15)
        wait_for(lambda: not any(alive(s['pid']) for s in self.starts()), 10)
        self.assertEqual([p for p in [s['pid'] for s in self.starts()] if alive(p)], [])


class LiveIdleTest(LiveTest):
    env = {'ZOOK_LIVE_IDLE': '2'}
    for _name in [n for n in dir(LiveTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_unused_cli_is_closed_after_a_while(self):
        self.ask(); pid = self.starts()[0]['pid']
        self.assertTrue(alive(pid))
        for _ in range(100):
            if not alive(pid): break
            time.sleep(0.1)
        self.assertFalse(alive(pid))
        self.assertEqual(self.ask()['status'], 'completed'); self.assertEqual(len(self.starts()), 2)


if __name__ == '__main__': unittest.main()
