# -*- coding: utf-8 -*-
"""#63: pressing 建立 a second time before the first answered made a second Bot of the same name. The window now sends an id with
what a form makes (a Bot, a group, a schedule, a note); the same request again gets what the first one made, not a copy. The
buttons show 建立中… / 刪除中… while the request is on its way, and an empty required field says so next to the field."""
import http.client, json, os, re, subprocess, sys, tempfile, threading, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ROOT / 'frontend/js'


class CreateOnce(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        (root / 'assets').mkdir(); (root / 'assets/index.html').write_text('x')
        env = dict(os.environ, PATH='/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(root / 'data'), '--assets', str(root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def state(self): return self.req('GET', '/api/state')[1]

    def test_a_bot_pressed_twice_is_made_once(self):
        before = len(self.state()['bots'])
        body = {'name': '業務小幫手', 'persona': '直接', 'provider': 'codex', 'clientId': 'form-0001-abcdef'}
        status, first = self.req('POST', '/api/bots', body)
        self.assertEqual(status, 201, first)
        status, again = self.req('POST', '/api/bots', body)
        self.assertEqual(status, 200, again); self.assertEqual(again['id'], first['id']); self.assertIs(again['duplicate'], True)
        self.assertEqual(len(self.state()['bots']), before + 1)
        # Another form (another id) is another Bot, and so is a request without an id (older apps, scripts), as before.
        self.assertEqual(self.req('POST', '/api/bots', dict(body, clientId='form-0002-abcdef'))[0], 201)
        self.assertEqual(self.req('POST', '/api/bots', {'name': '業務小幫手', 'provider': 'codex'})[0], 201)
        self.assertEqual(self.req('POST', '/api/bots', {'name': '業務小幫手', 'provider': 'codex'})[0], 201)
        self.assertEqual(len(self.state()['bots']), before + 4)
        # Once the first one is deleted, the same request makes it again rather than answering with a Bot that is gone.
        self.assertEqual(self.req('DELETE', '/api/bots/' + first['id'])[0], 200)
        status, remade = self.req('POST', '/api/bots', body)
        self.assertEqual(status, 201); self.assertNotEqual(remade['id'], first['id'])

    def test_two_presses_at_the_same_time(self):
        before = len(self.state()['bots'])
        body = {'name': '同時', 'persona': '直接', 'provider': 'codex', 'clientId': 'form-race-abcdef'}
        out = []
        threads = [threading.Thread(target=lambda: out.append(self.req('POST', '/api/bots', body))) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sorted(s for s, _ in out), [200, 200, 201], out)
        self.assertEqual(len({b['id'] for _, b in out}), 1)
        self.assertEqual(len(self.state()['bots']), before + 1)

    def test_a_refused_request_can_be_sent_again(self):
        body = {'name': ' ', 'provider': 'codex', 'clientId': 'form-0003-abcdef'}
        self.assertEqual(self.req('POST', '/api/bots', body)[0], 400)
        self.assertEqual(self.req('POST', '/api/bots', dict(body, name='好了'))[0], 201)  # fixed and sent again with the same id

    def test_groups_schedules_and_notes(self):
        bots = [self.req('POST', '/api/bots', {'name': n, 'provider': 'codex'})[1] for n in ('甲', '乙')]
        group = {'name': '小組', 'botIds': [b['id'] for b in bots], 'clientId': 'form-group-abcdef'}
        schedule = {'botId': bots[0]['id'], 'content': '日報', 'time': '09:00', 'repeat': 'daily', 'on': False, 'clientId': 'form-sched-abcdef'}
        note = {'title': '價目', 'content': 'A 100', 'clientId': 'form-notes-abcdef'}
        for path, body, key in (('/api/groups', group, 'groups'), ('/api/schedules', schedule, 'schedules'), ('/api/knowledge', note, 'knowledge')):
            before = len(self.state()[key])
            s1, first = self.req('POST', path, body); s2, again = self.req('POST', path, body)
            self.assertEqual((s1, s2), (201, 200), path); self.assertEqual(again['id'], first['id'], path)
            self.assertEqual(len(self.state()[key]), before + 1, path)
            self.assertEqual(self.req('POST', path, dict(body, clientId=None))[0], 201, path)  # without an id: made, as before


def source(name): return (JS / name).read_text(encoding='utf-8')


class CreateButtons(unittest.TestCase):
    def test_forms_say_they_are_working(self):
        forms = source('50-forms.js')
        self.assertIn('form.dataset.busy', forms)  # a second press while the first is on its way does nothing
        self.assertRegex(forms, r'建立\|儲存\|新增'); self.assertIn("+ '中…'", forms)  # 建立 Bot → 建立中…
        self.assertIn('button.disabled = true', forms)
        self.assertIn('建立失敗：', forms)  # a failure says why
        for form in ('bot-form', 'group-form', 'schedule-form', 'note-form'):  # each sends the id of this opening of the form
            start = forms.index("} else if (form.id === '%s')" % form, forms.index("document.addEventListener('submit'")); body = forms[start:forms.index('} else if', start + 5)]
            self.assertIn('onceId(form)', body, form)

    def test_deleting_says_deleting(self):
        ask = source('21-ask.js')
        self.assertIn("working = ok + '中…'", ask); self.assertIn('yes.textContent = working', ask)  # 刪除 → 刪除中…

    def test_an_empty_required_field_is_said_next_to_it(self):
        models = source('20-models.js'); forms = source('50-forms.js')
        self.assertIn('<form id="bot-form" novalidate>', models)  # the browser's own small bubble does not always show
        self.assertIn('data-need="請填寫人格檔案', models); self.assertIn('data-need="請填寫 Bot 名稱', models)
        self.assertIn('function fieldError', forms); self.assertIn('field-error', forms)
        self.assertIn('.field-error', (ROOT / 'frontend/style.css').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
