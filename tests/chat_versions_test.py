# -*- coding: utf-8 -*-
"""#305/#265/#77④: the single-Bot chat.
- 換模型重答 keeps the answers before it (重新回答 with the same model replaces it, as before): the reply carries them as versions (oldest first), each saying which model wrote it; the
  page switches 第 1／2 版 left and right; an older conversation without versions shows as before; the export has every version.
  Editing the question still replaces the answer. 原本：X／這次：Y stays.
- A message sent with 先規劃 says so on the user's bubble.
- Dates in notices carry the weekday: a one-off schedule, the reset time on a failed reply, and the Bots are told to write it."""
import datetime, http.client, importlib.util, json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ROOT / 'frontend/js'
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)
GEMINI = "#!/usr/bin/env python3\nprint('gemini answered')\n"
CODEX = '''#!/usr/bin/env python3
import json, sys
sys.stdin.read()
for e in [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'codex answered'}},
          {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 2}}]: print(json.dumps(e))
'''


def load_server(name):
    spec = importlib.util.spec_from_file_location(name, SERVER)
    m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)
    return m


def run_node(code):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'h.js'; f.write_text(code, encoding='utf-8')
        out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    if out.returncode != 0: raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


class Live(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name, text in (('gemini', GEMINI), ('codex', CODEX)): cli = self.root / 'bin' / name; cli.write_text(text); cli.chmod(0o755)
        home = self.root / 'codex-home'; home.mkdir(); (home / 'config.toml').write_text('model = "gpt-test-9"\n')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', CODEX_HOME=str(home), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': 'Tester', 'provider': 'gemini'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def wait(self, job_id):
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.2)
        self.fail('no reply')

    def redo(self, body):
        status, out = self.req('POST', '/api/chat/redo', dict(body, botId=self.bot['id']))
        self.assertEqual(status, 202, out); self.wait(out['jobId'])
        return next(b for b in self.req('GET', '/api/state?full=1')[1]['bots'] if b['id'] == self.bot['id'])['messages']

    def test_other_model_keeps_every_answer_with_its_model(self):
        sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '週報是什麼'})[1]; self.wait(sent['jobId'])
        first = self.redo({'mode': 'again'})[-1]                                                 # 重新回答 (same model): replaced as before
        self.assertNotIn('versions', first)
        messages = self.redo({'mode': 'again', 'provider': 'codex'})
        self.assertEqual([m['role'] for m in messages], ['user', 'assistant'])
        last = messages[-1]
        self.assertEqual(last['content'], 'codex answered')
        self.assertEqual(last['note'], '原本：Gemini／這次：Codex gpt-test-9')                    # #143 stays
        self.assertEqual(last['who'], 'Codex gpt-test-9')
        self.assertEqual([(v['content'], v['who'], v['id']) for v in last['versions']], [('gemini answered', 'Gemini', first['id'])])
        last = self.redo({'mode': 'again', 'provider': 'gemini'})[-1]
        self.assertEqual([(v['content'], v['who']) for v in last['versions']], [('gemini answered', 'Gemini'), ('codex answered', 'Codex gpt-test-9')])
        self.assertNotIn('versions', last['versions'][1])                                       # never nested
        out = self.req('GET', '/api/bots/%s/export' % self.bot['id'])[1]
        self.assertEqual(out['markdown'].count('gemini answered'), 2); self.assertIn('codex answered', out['markdown'])
        self.assertIn('第 1／3 版', out['markdown']); self.assertIn('第 3／3 版', out['markdown'])
        self.assertLess(out['markdown'].index('第 1／3 版'), out['markdown'].index('第 3／3 版'))
        again = self.redo({'mode': 'again'})                                                    # 重新回答 replaces, versions too
        self.assertEqual(len(again), 2); self.assertNotIn('versions', again[-1])
        edited = self.redo({'mode': 'edit', 'content': '週報怎麼寫'})                              # another question: the answers go
        self.assertNotIn('versions', edited[-1])

    def test_plan_is_kept_on_the_question(self):
        bot = self.req('POST', '/api/bots', {'name': 'Planner', 'provider': 'codex'})[1]
        sent = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': '規劃搬家', 'plan': True})
        self.assertEqual(sent[0], 202, sent); self.wait(sent[1]['jobId'])
        asked = next(b for b in self.req('GET', '/api/state?full=1')[1]['bots'] if b['id'] == bot['id'])['messages'][0]
        self.assertTrue(asked.get('plan'))


class Backend(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load_server('zook_server_for_versions')

    def test_export_of_an_old_reply_without_versions_is_unchanged(self):
        bot = dict(id='b1', name='Bot', chatId='c1', chats=[dict(id='c1', title='t')], messages=[
            dict(id='u1', role='user', content='q', createdAt='2026-11-23T06:00:00+00:00'),
            dict(id='a1', role='assistant', status='completed', content='only answer', createdAt='2026-11-23T06:01:00+00:00')])
        md = self.m.export_chat(dict(bots=[bot], jobs=[]), bot, 'c1')['markdown']
        self.assertIn('only answer', md); self.assertNotIn('版', md)

    def test_at_most_ten_versions_in_all(self):
        old = dict(id='a0', role='assistant', content='newest old', versions=[dict(id='v%d' % i, content=str(i)) for i in range(12)])
        msg = {}
        self.m.redo_versions(type('S', (), {'data': {'jobs': []}})(), dict(provider='auto'), [dict(role='user', content='q'), old], 'q', msg, 'codex', '')
        self.assertEqual(len(msg['versions']) + 1, 10); self.assertEqual(msg['versions'][-1]['content'], 'newest old')

    def test_one_off_schedule_says_the_weekday(self):
        when = self.m.schedule_when(dict(repeat='once', date='2026-12-01', time='08:00'))
        day = '12/1（週二）' if datetime.date.today().year == 2026 else '2026/12/1（週二）'
        self.assertEqual(when, day + ' 08:00（只一次）')

    def test_bots_are_told_to_write_the_weekday(self):
        block = self.m.identity_block(dict(name='B'))
        self.assertIn('（週', block.split('現在時間：')[1][:30])
        self.assertIn('星期', block); self.assertIn('（週', self.m.WEEKDAY_NOTE)


PAGE = r"""
const state = {versionAt: {}};
const esc = s => String(s);
__CODE__
const old = {id: 'a1', role: 'assistant', content: 'old only', status: 'completed'};
const m = {id: 'a3', role: 'assistant', content: 'third', who: 'Codex gpt-5.5', status: 'completed',
           versions: [{id: 'a1', content: 'first', who: 'Gemini'}, {id: 'a2', content: 'second', who: ''}]};
const out = {oldShown: versionShown(old) === old, oldBar: versionBar(old), latest: versionBar(versionShown(m))};
state.versionAt.a3 = 0;
const v = versionShown(m);
out.first = [v.content, v.id, v._of.id]; out.firstBar = versionBar(v);
out.planTag = planTag({role: 'user', plan: true}); out.noPlan = planTag({role: 'user'}) + planTag({role: 'assistant', plan: true});
out.today = dayWeek(new Date(2026, 11, 1));
console.log(JSON.stringify(out));
"""

FAILURE = r"""
const esc = s => String(s), state = {jobDetails: {}};
__CODE__
console.log(JSON.stringify({when: failureWhen('2026-12-01T10:30:00')}));
"""


@unittest.skipUnless(NODE, 'needs node to run the page code')
class Page(unittest.TestCase):
    def test_versions_switch_and_plan_tag(self):
        out = run_node(PAGE.replace('__CODE__', (JS / '40b-redo.js').read_text(encoding='utf-8').replace('document.addEventListener', '(() => {}) || document.addEventListener')))
        self.assertTrue(out['oldShown']); self.assertEqual(out['oldBar'], '')                    # an older conversation: as before
        self.assertIn('第 3／3 版', out['latest']); self.assertIn('Codex gpt-5.5', out['latest'])
        self.assertEqual(out['first'], ['first', 'a1', 'a3'])
        self.assertIn('第 1／3 版', out['firstBar']); self.assertIn('Gemini', out['firstBar'])
        self.assertIn('data-action="reply-version"', out['firstBar'])
        self.assertIn('先規劃', out['planTag']); self.assertEqual(out['noPlan'], '')
        self.assertEqual(out['today'], '12/1（週二）')

    def test_failure_reset_time_has_the_weekday(self):
        code = (JS / '40b-redo.js').read_text(encoding='utf-8').replace('document.addEventListener', '(() => {}) || document.addEventListener')
        failure = (JS / '37c-failure.js').read_text(encoding='utf-8')
        out = run_node(FAILURE.replace('__CODE__', code + failure[failure.index('  function failureWhen'):failure.index('  // The card for a failed reply')]))
        self.assertTrue(out['when'].startswith('12/1（週二）'), out)


class Wiring(unittest.TestCase):
    def test_chat_page_uses_versions_and_plan_tag(self):
        chat = (JS / '10-chat.js').read_text(encoding='utf-8')
        for name in ('versionShown(', 'versionBar(', 'planTag('): self.assertIn(name, chat)
        self.assertIn("case 'reply-version'", (JS / '40-actions.js').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
