# -*- coding: utf-8 -*-
"""Roadmap part 8, batch 1: clear bugs.
#317/#330 刪除群組 read the form after the question had replaced it; #264 停止 kept nothing of what was already written;
#277 what the user added mid-reply was lost when the reply went on in the CLI's own conversation; #263 an empty message did
nothing at all; #258 a link in a reply to a file that is not there looked like any other link."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ROOT / 'frontend/js'


def source(name): return (JS / name).read_text(encoding='utf-8')


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_bug_pack', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class Frontend(unittest.TestCase):
    def test_delete_group_keeps_the_id_before_asking(self):
        text = source('40-actions.js')
        start = text.index("case 'delete-group':"); body = text[start:text.index('\n        case ', start + 1)]
        self.assertIn('ask(', body)
        self.assertLess(body.index("$('#group-form')"), body.index('ask('))  # the question replaces the form (#317)
        self.assertNotIn("$('#group-form')", body[body.index('ask('):])

    def test_empty_message_says_so(self):
        forms = source('50-forms.js')
        at = forms.index('if (!content && !attachments.length)')
        self.assertIn('請先輸入內容', forms[at:at + 200])  # not a silent return (#263)

    def test_stopped_reply_is_marked(self):
        models = source('20-models.js')
        line = next(x for x in models.splitlines() if 'const noteLine' in x)
        self.assertIn("m.status === 'cancelled'", line); self.assertIn('已停止回覆', line)  # #264: kept words, marked as stopped

    def test_missing_file_link_is_marked(self):
        chat, outputs = source('10-chat.js'), source('36-outputs.js')
        self.assertIn('markMissing(', chat)  # the single chat's replies (#258)
        self.assertIn('function markMissing', outputs); self.assertIn('檔案找不到', outputs)
        self.assertIn('missingFiles', outputs)


class MissingLinks(unittest.TestCase):
    def test_only_links_to_absent_files(self):
        m = load()
        with tempfile.TemporaryDirectory() as d:
            here = Path(d) / '報表.txt'; here.write_text('x'); spaced = Path(d) / 'a b.txt'; spaced.write_text('x')
            gone = d + '/三封客訴回覆.txt'
            text = '檔案：[三封客訴回覆.txt](%s)，另一份 [報表](<%s>)、[有空格](%s) 與 file://%s 。純文字路徑 %s/沒連結.txt 不算；[網頁](https://x.com/a.txt)' % (
                gone, here, str(spaced).replace(' ', '%20'), d + '/%E4%B8%8D%E5%9C%A8.txt', d)
            self.assertEqual(m.reply_missing_links(text), [gone, d + '/不在.txt'])
            self.assertEqual(m.reply_missing_links(''), []); self.assertEqual(m.reply_missing_links(None), [])
            self.assertEqual(m.reply_missing_links('[外接](/Volumes/沒插/a.txt) [網路](file:///Network/x/b.txt)'), [])  # another disk may not answer quickly: not checked
            self.assertEqual(m.reply_missing_links('`[在程式碼裡](/nowhere/a.txt)`'), [])
            self.assertEqual(m.reply_missing_links('[繞路](/tmp/../Volumes/沒插/a.txt)'), [])
            locked = Path(d) / '鎖住'; locked.mkdir(); (locked / 'a.txt').write_text('x'); locked.chmod(0)
            try: self.assertEqual(m.reply_missing_links('[看不到](%s/a.txt)' % locked), [])  # cannot look: not said to be missing
            finally: locked.chmod(0o700)


class StoppedWords(unittest.TestCase):
    def test_words_between_two_attempts_are_kept(self):
        m = load(); m._active['data'] = {'settings': {}}
        m.partial_start(dict(id='j', messageId='m')); m.PARTIALS['j']['text'] = '前半段\n【選項】\n- 甲\n- 乙'
        self.assertEqual(m.partial_kept('j'), '前半段')  # the choice block is not part of what was said
        m.partial_end('j', True); self.assertEqual(m.partial_kept('j'), '前半段')  # the attempt ended, the next has not started
        self.assertEqual(m.partial_kept('j'), '')  # kept once: the stopped reply took it
        m.partial_start(dict(id='j', messageId='m')); m.PARTIALS['j']['text'] = '完成了'; m.partial_end('j'); self.assertNotIn('j', m.PARTIAL_GAP)  # finished: nothing is kept
        m.partial_end('j', True); m.partial_start(dict(id='j', messageId='m')); self.assertEqual(m.partial_kept('j'), '')  # a backup started: its own words only
        m.partial_end('k'); self.assertEqual(m.partial_kept('k'), '')


CODEX = '''#!/usr/bin/env python3
import json, os, sys, time
sys.stdin.read()
here = os.path.dirname(sys.argv[0]); mode = open(os.path.join(here, 'mode')).read().strip()
say = lambda t: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': t}}), flush=True)
if mode == 'link': say('已存好：[客訴回覆.txt](/nowhere/zook-test/客訴回覆.txt)'); sys.exit(0)
say('先說第一段')
end = time.time() + 30
while not os.path.exists(os.path.join(here, 'go')) and time.time() < end: time.sleep(0.02)
say('完整回覆')
'''


class StopAndLinks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755); (self.root / 'bin/mode').write_text('slow')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'S', 'provider': 'codex'})[1]

    def tearDown(self):
        (self.root / 'bin/go').write_text('1')
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def until(self, test, what, limit=15):
        end = time.time() + limit
        while time.time() < end:
            value = test()
            if value: return value
            time.sleep(0.05)
        self.fail(what)

    def last(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])['messages'][-1]

    def test_stop_keeps_what_was_written(self):
        job_id = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'hi'})[1]['jobId']
        self.until(lambda: self.req('GET', '/api/jobs/' + job_id)[1].get('partial') == '先說第一段', 'no partial reply')
        self.assertEqual(self.req('POST', '/api/jobs/%s/cancel' % job_id)[0], 200)
        reply = self.last()
        self.assertEqual((reply['status'], reply['content']), ('cancelled', '先說第一段'))
        time.sleep(0.5); self.assertEqual(self.last()['content'], '先說第一段')  # the ending CLI does not blank it afterwards

    def test_stop_before_any_words_is_as_before(self):
        (self.root / 'bin/mode').write_text('slow')
        self.req('PATCH', '/api/settings', {'streamReplies': False})
        job_id = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'hi'})[1]['jobId']
        time.sleep(0.4); self.req('POST', '/api/jobs/%s/cancel' % job_id)
        self.assertEqual((self.last()['status'], self.last()['content']), ('cancelled', ''))

    def test_link_to_a_missing_file_is_noted(self):
        (self.root / 'bin/mode').write_text('link')
        job_id = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'hi'})[1]['jobId']
        self.until(lambda: self.req('GET', '/api/jobs/' + job_id)[1]['status'] == 'completed', 'no reply')
        self.assertEqual(self.last().get('missingFiles'), ['/nowhere/zook-test/客訴回覆.txt'])


# A Codex stand-in that says which conversation it writes into and, for SLOW, works long enough for Zook to be stopped meanwhile.
RESUMING = r'''#!/usr/bin/env python3
import json, os, sys, time
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0]); text = sys.stdin.read()
with open(os.path.join(here, 'runs.jsonl'), 'a') as f: f.write(json.dumps(dict(args=a, prompt=text)) + '\n')
n = len(open(os.path.join(here, 'runs.jsonl')).readlines())
print(json.dumps(dict(type='thread.started', thread_id=a[a.index('resume') + 1] if 'resume' in a else 'thread-%d' % n)), flush=True)
asked = text.split('對話紀錄：', 1)[1].rsplit('\n使用者：', 1)[-1] if '對話紀錄：' in text else text
if 'SLOW' in asked and '重新啟動' not in text: time.sleep(60)
print(json.dumps(dict(type='item.completed', item=dict(type='agent_message', text='接著做完了'))))
'''


class AddedTextOnResume(unittest.TestCase):
    """#277: a reply that goes on in the CLI's own conversation is sent a short prompt; what the user added must still be in it."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(RESUMING); cli.chmod(0o755); (self.root / 'home/.codex').mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.root / 'home'), PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'),
                        ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_RESUME_DELAY='0.2')
        self.proc = None; self.start()
        self.bot = self.req('POST', '/api/bots', {'name': 'N', 'provider': 'codex'})[1]
        self.req('PATCH', '/api/settings', {'backgroundRuns': False})

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self):
        self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close(); self.proc.stderr.close(); self.proc = None

    def tearDown(self):
        if self.proc: self.stop()
        self.temp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20); c.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d)

    def runs(self): return [json.loads(x) for x in (self.root / 'bin/runs.jsonl').read_text().splitlines()]
    def data(self): return json.loads((self.root / 'data/swarmr.json').read_text())
    def state(self): return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])

    def until(self, check, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            value = check()
            if value: return value
            time.sleep(0.1)
        self.fail('timed out')

    def test_added_message_reaches_the_resumed_cli(self):
        self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '先記住藍鯨'})
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed')
        sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': 'SLOW 做一份長報告'})[1]
        self.until(lambda: any((j.get('cliSession') or {}).get('session') for j in self.data()['jobs'] if j['id'] == sent['jobId']))
        self.until(lambda: any('SLOW 做一份長報告' in r['prompt'] for r in self.runs()))
        self.stop()
        bot = next(b for b in self.data()['bots'] if b['id'] == self.bot['id'])
        file = next((self.root / 'data/chats' / bot['id']).glob('*.json'))  # the open conversation (chatfiles.py)
        chat = json.loads(file.read_text()); messages = chat['messages']
        messages.insert(len(messages) - 1, dict(id='added1', role='user', content='另外加上結論段落', createdAt=messages[-1]['createdAt'], interjected=True))  # sent while it answered
        file.write_text(json.dumps(chat, ensure_ascii=False))
        self.start()
        self.until(lambda: self.state()['messages'][-1].get('status') == 'completed')
        last = self.runs()[-1]
        self.assertEqual(last['args'][-3:], ['resume', 'thread-1', '-'])  # went on in the CLI's own conversation
        self.assertEqual(last['prompt'].count('另外加上結論段落'), 1)  # told once, after the short prompt


if __name__ == '__main__':
    unittest.main()
