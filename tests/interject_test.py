# -*- coding: utf-8 -*-
"""Antigravity stays open between messages too, and a message sent while a Bot is answering can be told to it right away (插話)."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
# A fake Claude kept open. A message containing HOLD makes it work for a while; a message that arrives meanwhile is read at its
# next step and answered in the same reply, unless the first one contained ALONE (then it is answered right after, as Claude
# does when there is no step to read it at).
CLAUDE = r'''#!/usr/bin/env python3
import json, os, queue, sys, threading, time, uuid
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv: print('--print --output-format --mcp-config --allowedTools --tools --effort --resume --session-id --input-format --replay-user-messages'); sys.exit(0)
if '--version' in sys.argv: print('9.9.9 (fake)'); sys.exit(0)
here = os.path.dirname(sys.argv[0]); live = '--input-format' in sys.argv
session = sys.argv[sys.argv.index('--resume') + 1] if '--resume' in sys.argv else 'sess-' + uuid.uuid4().hex[:8]
open(os.path.join(here, 'starts.log'), 'a').write(json.dumps(dict(pid=os.getpid(), live=live)) + '\n')
def out(**d): print(json.dumps(d), flush=True)
def result(text, cost): out(type='result', result=text, is_error=False, session_id=session, total_cost_usd=cost, usage={'input_tokens': 5, 'output_tokens': 2})
if not live:
    text = sys.stdin.read(); open(os.path.join(here, 'said.log'), 'a').write(json.dumps(text) + '\n')
    if 'HOLD' in text: time.sleep(3)
    out(type='system', subtype='init', session_id=session); result('once', 0.01); sys.exit(0)
lines = queue.Queue()
threading.Thread(target=lambda: [lines.put(l) for l in sys.stdin] and lines.put(None), daemon=True).start()
cost = 0.0
while True:
    line = lines.get()
    if line is None: break
    text = json.loads(line)['message']['content']; open(os.path.join(here, 'said.log'), 'a').write(json.dumps(text) + '\n')
    out(type='system', subtype='init', session_id=session); out(type='user', message={'role': 'user', 'content': text}, session_id=session)
    if 'HOLD' not in text: cost += 0.01; result('plain answer', cost); continue
    out(type='assistant', message={'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'step 1'}}]}, session_id=session)
    try: more = lines.get(timeout=6)
    except queue.Empty: more = None
    if more is None: cost += 0.01; result('finished the long job', cost); continue
    extra = json.loads(more)['message']['content']; open(os.path.join(here, 'said.log'), 'a').write(json.dumps(extra) + '\n')
    if 'ALONE' in text:
        cost += 0.01; result('long job part one', cost)
        out(type='system', subtype='init', session_id=session); out(type='user', message={'role': 'user', 'content': extra}, session_id=session)
        cost += 0.02; result('then: ' + extra.splitlines()[-1], cost)
    else:
        out(type='user', message={'role': 'user', 'content': [{'type': 'tool_result', 'content': 'ok'}]}, session_id=session)
        out(type='user', message={'role': 'user', 'content': extra}, session_id=session, isReplay=True)
        cost += 0.01; result('changed course: ' + extra.splitlines()[-1], cost)
'''
# A fake agy that reads one message per line and answers each, as `agy --input-format stream-json` does. Its result reports
# the tokens of the whole conversation so far; each step, its own.
AGY = r'''#!/usr/bin/env python3
import json, os, sys, time
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0])
if a == ['--help']: print('--input-format --output-format --settings --mode --effort --conversation --print'); sys.exit(0)
if a == ['--version']: print('1.5.12'); sys.exit(0)
if a == ['models']: print('m\tM'); sys.exit(0)
if a[:2] == ['-p', '/usage']: print('{}'); sys.exit(0)
conv = a[a.index('--conversation') + 1] if '--conversation' in a else 'conv-%d' % os.getpid()
open(os.path.join(here, 'starts.log'), 'a').write(json.dumps(dict(pid=os.getpid(), resume='--conversation' in a)) + '\n')
def out(**d): print(json.dumps(d), flush=True)
total = 0; n = 0
out(event='init', conversation_id=conv, init=dict(cwd=os.getcwd()))
for line in sys.stdin:
    text = json.loads(line)['message']['content']; n += 1; total += 100
    out(event='step_update', step_update=dict(conversation_id=conv, step_type='user_input', state='DONE'))
    if 'HOLD' in text: time.sleep(2)
    out(event='step_update', step_update=dict(conversation_id=conv, step_index=2 * n, step_type='agent_response', state='DONE', text_delta='answer %d' % n, usage=dict(input_tokens=100, output_tokens=7, cache_read_tokens=0)))
    out(event='result', result=dict(conversation_id=conv, status='SUCCESS', response='answer %d from %d' % (n, os.getpid()), usage=dict(input_tokens=total, output_tokens=7 * n, cache_read_tokens=0)))
'''


class Base(unittest.TestCase):
    provider = 'claude'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name, text in (('claude', CLAUDE), ('agy', AGY)):
            cli = self.root / 'bin' / name; cli.write_text(text); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        if self.provider == 'antigravity': self.assertEqual(self.req('POST', '/api/accounts/antigravity/add', {})[0], 200)
        else: self.req('PATCH', '/api/settings', {'provider': 'claude', 'permissionMode': 'auto'})
        self.bot = self.req('POST', '/api/bots', {'name': '助理', 'provider': self.provider})[1]
        for _ in range(100):  # Zook has to have read the CLI's help before it keeps one open
            if self.provider in (self.req('GET', '/api/state?full=1')[1].get('abilityChecks') or {}): break
            time.sleep(0.1)

    def tearDown(self):
        if self.proc.poll() is None: self.proc.terminate(); self.proc.wait(timeout=10)
        self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def send(self, text, **more): return self.req('POST', '/api/chat', dict({'botId': self.bot['id'], 'content': text}, **more))

    def wait(self, job_id, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.05)
        self.fail('no reply')

    def starts(self):
        path = self.root / 'bin/starts.log'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def said(self):
        path = self.root / 'bin/said.log'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def messages(self):
        bot = next(b for b in self.req('GET', '/api/state?full=1')[1]['bots'] if b['id'] == self.bot['id'])
        return bot['messages']

    def running(self, job_id):
        end = time.time() + 10
        while time.time() < end:  # the reply has started and its CLI has read the first message
            if any('HOLD' in s for s in self.said()): return
            time.sleep(0.05)
        self.fail('the reply did not start')


class Interject(Base):
    def test_changes_the_reply_that_is_running(self):
        self.wait(self.send('first')[1]['jobId'])  # the conversation's CLI is open from here on
        job_id = self.send('HOLD do the long job')[1]['jobId']; self.running(job_id)
        status, sent = self.send('make it shorter')
        self.assertEqual((status, sent.get('interjected'), sent.get('jobId')), (202, True, job_id))
        job = self.wait(job_id)
        self.assertEqual((job['status'], job['content']), ('completed', 'changed course: make it shorter'))
        self.assertEqual(len(self.starts()), 1)
        self.assertIn('使用者在你回覆途中補充', self.said()[-1])  # it is told what this message is
        texts = [(m['role'], m['content'], bool(m.get('interjected'))) for m in self.messages()]
        self.assertEqual(texts[-3:], [('user', 'HOLD do the long job', False), ('user', 'make it shorter', True), ('assistant', 'changed course: make it shorter', False)])
        self.assertEqual(round(job['usage']['costUsd'], 4), 0.01)  # its own part of what the CLI has cost so far
        self.assertEqual(self.wait(self.send('after')[1]['jobId'])['content'], 'plain answer')  # and the CLI is still good to use

    def test_read_only_after_the_answer_is_still_part_of_the_reply(self):
        self.wait(self.send('first')[1]['jobId'])
        job_id = self.send('HOLD ALONE the long job')[1]['jobId']; self.running(job_id)
        self.assertTrue(self.send('and add a title')[1].get('interjected'))
        job = self.wait(job_id)
        self.assertEqual(job['content'], 'long job part one\n\nthen: and add a title')
        self.assertEqual((job['usage']['input'], job['usage']['output'], round(job['usage']['costUsd'], 4)), (10, 4, 0.03))
        self.assertEqual(self.wait(self.send('after')[1]['jobId'])['content'], 'plain answer')
        self.assertEqual(len(self.starts()), 1)

    def test_falls_back_to_the_line(self):
        # The first message of a conversation starts its CLI the usual way, which cannot be told anything meanwhile.
        self.req('PATCH', '/api/settings', {'keepCli': False})
        job_id = self.send('HOLD the long job')[1]['jobId']
        time.sleep(0.5)
        status, sent = self.send('wait, one more thing')
        self.assertEqual((status, sent.get('queued')), (202, True)); self.assertIn('排在後面', sent['notice'])
        self.wait(job_id)
        end = time.time() + 20  # the message that waited in line is sent and answered
        while time.time() < end and (len(self.said()) < 2 or any(j['status'] == 'running' for j in self.req('GET', '/api/state?full=1')[1]['jobs'])): time.sleep(0.1)
        self.req('PATCH', '/api/settings', {'queueWhenBusy': False})
        job_id = self.send('HOLD again')[1]['jobId']; time.sleep(0.5)
        status, sent = self.send('and now')
        self.assertEqual(status, 409); self.assertIn('無法在回覆途中', sent['error'])

    def test_with_nothing_running_it_is_an_ordinary_message(self):
        status, sent = self.send('hello')
        self.assertEqual(status, 202); self.assertNotIn('interjected', sent)
        self.assertEqual(self.wait(sent['jobId'])['status'], 'completed')

    def test_attachments_wait(self):
        self.wait(self.send('first')[1]['jobId'])
        job_id = self.send('HOLD the long job')[1]['jobId']; self.running(job_id)
        status, sent = self.send('look', plan=True)
        self.assertEqual((status, sent.get('queued')), (202, True)); self.assertIn('先規劃', sent['notice'])
        self.wait(job_id)

    def test_something_new_waits_its_turn(self):
        # No switch any more: Zook decides. A new request is not a correction of the running reply, so it waits in line.
        self.wait(self.send('first')[1]['jobId'])
        job_id = self.send('HOLD do the long job')[1]['jobId']; self.running(job_id)
        status, sent = self.send('請幫我另外整理一份下個月展覽活動的完整企劃書給大家參考')
        self.assertEqual((status, sent.get('queued'), sent.get('interjected'), sent.get('notice')), (202, True, None, None))
        self.assertEqual(self.wait(job_id)['content'], 'finished the long job')  # the running reply never heard it
        end = time.time() + 20
        while time.time() < end and not any(m['role'] == 'user' and '展覽' in m['content'] and m.get('queued') for m in self.messages()): time.sleep(0.1)
        said = next(m for m in self.messages() if '展覽' in m['content'])
        self.assertEqual((said.get('queued'), bool(said.get('interjected'))), (True, False))  # shown as 排在後面

    def test_the_old_switch_is_gone(self):
        self.req('PATCH', '/api/settings', {'busySend': 'now'})
        self.assertNotIn('busySend', self.req('GET', '/api/state')[1]['settings'])
        self.wait(self.send('first')[1]['jobId'])
        job_id = self.send('HOLD do the long job')[1]['jobId']; self.running(job_id)
        self.assertTrue(self.send('寫一份完整的年度報告，包含每一季的營收、成本與明年的計畫', interject=True)[1].get('queued'))  # an old client's flag decides nothing
        self.wait(job_id)


class Antigravity(Base):
    provider = 'antigravity'

    def test_stays_open_and_counts_each_reply_once(self):
        one = self.wait(self.send('hello')[1]['jobId']); two = self.wait(self.send('again')[1]['jobId']); three = self.wait(self.send('more')[1]['jobId'])
        self.assertEqual([j['status'] for j in (one, two, three)], ['completed'] * 3)
        self.assertEqual(len(self.starts()), 1)
        pid = self.starts()[0]['pid']
        self.assertEqual([j['content'] for j in (one, two, three)], ['answer %d from %d' % (n, pid) for n in (1, 2, 3)])
        self.assertEqual([j['usage']['input'] for j in (one, two, three)], [100, 100, 100])  # agy's result is the conversation's total; each reply is counted once
        self.assertEqual([bool(j.get('kept')) for j in (one, two, three)], [False, True, True])

    def test_cannot_be_told_midway(self):
        self.wait(self.send('hello')[1]['jobId'])
        job_id = self.send('HOLD think')[1]['jobId']; time.sleep(0.3)
        status, sent = self.send('stop')
        self.assertEqual((status, sent.get('queued')), (202, True)); self.assertIn('無法在回覆途中', sent['notice'])
        self.assertEqual(self.wait(job_id)['status'], 'completed')
        end = time.time() + 15
        while time.time() < end and not any(m['content'] == 'stop' and m['role'] == 'user' for m in self.messages()): time.sleep(0.1)
        self.assertTrue(any(m['content'] == 'stop' for m in self.messages()))  # sent once the reply was over




class Units(unittest.TestCase):
    """The parts that decide when a reply is complete, checked directly."""
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location('zook_interject', SERVER); cls.z = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.z)

    def test_which_messages_join_the_running_reply(self):
        joins = ['等等，先不要寄', '不要用表格', '改成三點就好', '另外加一段結論', '還有記得附上來源', '順便檢查錯字', '對了，用英文', '停', '短一點',
                 'make it shorter', 'wait, one more thing', 'stop', 'actually use the second file', '把剛剛那段改成條列，並且把每一點的說明都寫得更完整一些',
                 '@Gamma 預算改成五萬', '@Alpha 好']
        waits = ['請幫我另外整理一份下個月展覽活動的完整企劃書給大家參考', '台北明天天氣如何', '這是什麼？', '幫我查一下最近有哪些新的 AI 工具可以用在行銷上面',
                 'write a short summary of the quarterly report for the whole team', '@Beta 幫我寫一份完整的新產品上市計畫書給業務部門使用', '', '@Alpha']
        self.assertEqual([t for t in joins if not self.z.interject_wanted(t, ['Alpha', 'Beta', 'Gamma'])], [])
        self.assertEqual([t for t in waits if self.z.interject_wanted(t, ['Alpha', 'Beta', 'Gamma'])], [])

    def cli(self, args):
        cli = self.z.LiveCli(('b', 'c'), args, tempfile.gettempdir(), dict(os.environ), 'm', 'live-x', 't')
        self.addCleanup(cli.close, 3)
        return cli

    def line(self, **d): return (json.dumps(d) + '\n').encode()

    def test_only_the_message_sent_counts_as_read(self):
        turn = self.cli(['sleep', '30']).begin('job', 'do the work', 10 ** 6, None)
        turn.take(self.line(type='user', message={'role': 'user', 'content': 'do the work'}))
        self.assertTrue(turn.echoed)
        self.assertEqual(turn.add('shorter please'), '')
        turn.take(self.line(type='user', message={'role': 'user', 'content': 'This session is being continued from a summary'}))  # Claude's own, not ours
        turn.take(self.line(type='user', message={'role': 'user', 'content': [{'type': 'tool_result', 'content': 'ok'}]}))
        turn.take(self.line(type='result', result='part one'))
        self.assertFalse(turn.done.is_set())  # the added message has not been read yet
        turn.take(self.line(type='user', message={'role': 'user', 'content': [{'type': 'text', 'text': self.z.INTERJECT_NOTE + 'shorter please'}]}))
        turn.take(self.line(type='result', result='part two'))
        self.assertTrue(turn.done.is_set() and turn.finished); self.assertEqual(len(turn.answers), 2)

    def test_an_answer_is_kept_when_the_added_message_is_never_read(self):
        cli = self.cli(['sleep', '30']); turn = cli.begin('job', 'go', 10 ** 6, None)
        turn.take(self.line(type='user', message={'role': 'user', 'content': 'go'})); turn.add('stop')
        turn.take(self.line(type='result', result='done anyway'))
        self.assertFalse(turn.wait(0.1))
        turn.last -= self.z.LIVE_UNREAD + 1
        self.assertTrue(turn.wait(0.1)); self.assertEqual(turn.returncode, 0); self.assertTrue(cli.spoiled)
        end = time.time() + 5
        while time.time() < end and cli.alive(): time.sleep(0.05)
        self.assertFalse(cli.alive())

    def test_an_answer_without_the_message_repeated_sends_it_again(self):
        cli = self.cli(['sleep', '30']); turn = cli.begin('job', 'go', 10 ** 6, None)
        turn.take(self.line(type='system', subtype='init'))
        turn.take(self.line(type='user', message={'role': 'user', 'content': 'something else entirely'}))
        turn.take(self.line(type='result', result='an answer to who knows what'))
        self.assertFalse(turn.wait(0.1))
        turn.last -= self.z.LIVE_UNCLAIMED + 1
        self.assertTrue(turn.wait(0.1)); self.assertTrue(turn.lost()); self.assertNotEqual(turn.returncode, 0)  # lost: Zook starts the CLI the usual way
        self.assertTrue(cli.spoiled)

    def test_messages_arrive_in_order_and_are_capped(self):
        turn = self.cli(['cat']).begin('job', 'first', 10 ** 6, None)  # cat repeats every line it is given, in the order it got them
        reasons = [turn.add('more %d' % i) for i in range(self.z.INTERJECT_MAX + 1)]
        self.assertEqual(reasons[:-1], [''] * self.z.INTERJECT_MAX); self.assertIn('補充', reasons[-1])
        end = time.time() + 5
        while time.time() < end and turn.pending: time.sleep(0.05)
        self.assertTrue(turn.echoed); self.assertEqual(turn.pending, [])  # each was matched against the next one expected

    def test_output_between_messages_closes_it(self):
        cli = self.cli(['sh', '-c', 'read x; echo \'{"type":"result","result":"a"}\'; sleep 0.3; echo \'{"type":"assistant"}\'; sleep 30'])
        turn = cli.begin('job', 'hi', 10 ** 6, None); turn.echoed = True
        self.assertTrue(turn.wait(5))
        end = time.time() + 5
        while time.time() < end and cli.alive(): time.sleep(0.05)
        self.assertTrue(cli.spoiled); self.assertFalse(cli.alive())

    def test_antigravity_folder_left_as_written(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d); (work / '.agents').mkdir(); (work / '.agents/mcp_config.json').write_text('{}')
            self.assertFalse(self.z.agy_touched(work))
            (work / '.agents/hooks.json').write_text('{}'); self.assertTrue(self.z.agy_touched(work))
            (work / '.agents/hooks.json').unlink(); (work / '_agent').mkdir(); self.assertTrue(self.z.agy_touched(work))


if __name__ == '__main__': unittest.main()
