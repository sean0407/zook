# -*- coding: utf-8 -*-
"""Roadmap part 8, the small tails (item/355-misc-tails).
#355 a single chat's reply that says it looked at the pages as pictures without making one is marked, as a group's already is;
#339/#123④ 知識庫: same title, upload again after a failure, errors beside the field, a stale 試搜尋 cleared after a delete, a
draft kept over a reload, and a question box that keeps its failure inside; #325/#84⑦/#337⑥/#350 narrow windows and font sizes."""
import http.client, json, os, re, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ROOT / 'frontend/js'


def source(name): return (JS / name).read_text(encoding='utf-8')


CODEX = '''#!/usr/bin/env python3
import json, os, sys
sys.stdin.read()
here = os.path.dirname(sys.argv[0]); mode = open(os.path.join(here, 'mode')).read().strip()
say = lambda t: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': t}}), flush=True)
if mode == 'rendered':
    print(json.dumps({'type': 'item.completed', 'item': {'id': 'c1', 'type': 'command_execution', 'command': 'qlmanage -t -s 1600 -o /tmp/x a.pptx', 'status': 'completed', 'exit_code': 0, 'aggregated_output': ''}}), flush=True)
if mode == 'plain': say('簡報做好了，共 8 頁。'); sys.exit(0)
say('簡報做好了，我已逐頁轉成圖片檢查過，版面沒有問題。')
'''


class SingleChatLayoutClaim(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755); (self.root / 'bin/mode').write_text('claim')
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
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

    def reply(self, mode):
        (self.root / 'bin/mode').write_text(mode)
        job_id = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '做簡報'})[1]['jobId']
        end = time.time() + 15
        while time.time() < end and self.req('GET', '/api/jobs/' + job_id)[1]['status'] == 'running': time.sleep(0.05)
        self.assertEqual(self.req('GET', '/api/jobs/' + job_id)[1]['status'], 'completed')
        return next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])['messages'][-1]

    def test_claim_without_a_picture_is_marked(self):
        self.assertTrue(self.reply('claim').get('unseenLayout'))

    def test_claim_with_a_picture_or_no_claim_is_not(self):
        self.assertFalse(self.reply('rendered').get('unseenLayout'))
        self.assertFalse(self.reply('plain').get('unseenLayout'))

    def test_the_mark_is_shown_under_the_reply(self):
        line = next(x for x in source('20-models.js').splitlines() if 'const noteLine' in x)
        self.assertIn('m.unseenLayout', line); self.assertIn('版面', line)


class Knowledge(unittest.TestCase):
    def test_same_title_is_said(self):
        text = source('36c-knowledge.js')
        self.assertIn('const knowSameName', text); self.assertIn('同名', text)

    def test_failed_file_can_be_sent_again(self):
        text = source('36c-knowledge.js')
        self.assertIn('data-action="know-reupload"', text)
        self.assertIn("case 'know-reupload'", source('40-actions.js'))

    def test_errors_stay_beside_the_field(self):
        text = source('36c-knowledge.js')
        self.assertIn('function knowError', text)
        forms = source('50-forms.js'); at = forms.index("form.id === 'note-form'")
        self.assertIn('knowError', forms[at:at + 300])

    def test_delete_clears_the_old_trial_search(self):
        actions = source('40-actions.js'); at = actions.index("case 'delete-note':")
        self.assertIn('knowSearch', actions[at:actions.index('break;', at)])

    def test_draft_kept_over_a_reload(self):
        text = source('36c-knowledge.js')
        self.assertIn('swarmr-know-draft', text)
        self.assertIn('swarmr-know-draft', source('21b-unsaved.js'))  # 放棄修改 drops it


class AskKeepsTheReason(unittest.TestCase):
    def test_failure_stays_in_the_question(self):
        text = source('21-ask.js')
        self.assertIn('ask-error', text)
        self.assertNotIn('catch (err) { close(); reject(err); }', text)  # a toast after the box closed looked like nothing happened (#339①)


class NarrowWindow(unittest.TestCase):
    def setUp(self): self.css = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')

    def test_font_scale_is_wider(self):
        look = source('38-look.js')  # #350⑤: 特大 was only 1.25 times
        self.assertIn("{id: 'xlarge', name: '特大', zoom: 1.35}", look)

    def test_narrow_rules(self):
        self.assertIn('/* #325 */', self.css); self.assertIn('/* #84⑦:', self.css); self.assertIn('/* #350③:', self.css); self.assertIn('calc(40dvh / var(--zoom, 1))', self.css)


def load():
    import importlib.util
    spec = importlib.util.spec_from_file_location('zook_server_for_misc_tails', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class QuietByCli(unittest.TestCase):  # #237
    def test_progress_says_which_cli(self):
        m = load(); m.progress_start('j1', 'codex')
        try: self.assertEqual(m.progress_view(dict(id='j1', status='running'))['progress']['cli'], 'codex')
        finally: m.progress_end('j1')
        m.progress_start('j2')
        try: self.assertEqual(m.progress_view(dict(id='j2', status='running'))['progress']['cli'], '')
        finally: m.progress_end('j2')

    def test_window_waits_per_cli(self):
        text = source('37b-progress.js')
        self.assertIn('QUIET_MINUTES', text); self.assertIn('stuckAfter(d.cli, d.long)', text)
        self.assertIn("cli: p?.cli || ''", text)


class CodeIsNotACommand(unittest.TestCase):  # #201③: guarded here; the words come from actwords.py
    def test_code_words_are_not_listed(self):
        m = load()
        for command in ('node -e "try{x()}catch(e){console.log(e)}"', "/bin/zsh -lc 'node -e \"const e=1; console.log(e)\"'", 'cat <<EOF | node\nconsole.log(e)\nEOF'):
            said = m.plain_command_summary(command)
            self.assertNotIn('console', said); self.assertNotRegex(said, r'(^|[、；：])e($|[、；])')


class NarrowSidebarFolds(unittest.TestCase):  # user 2026-11-27: 480 wide or less, folded by default; ☰ opens; picking closes
    def test_folded_by_default_and_opened_by_the_button(self):
        chat = source('10-chat.js')
        self.assertIn("<aside class=\"sidebar ${state.sideOpen ? 'side-open' : ''}\">", chat)
        self.assertIn('data-side-fold', chat)
        css = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
        at = css.index('.side-fold { display: none;')
        rules = css[at:at + 600]
        self.assertIn('@media (max-width: 480px)', rules); self.assertIn('.sidebar:not(.side-open) > :not(.side-top) { display: none; }', rules)

    def test_picking_folds_it_again(self):
        fold = source('34e-sidefold.js')
        for action in ('select-bot', 'select-group', 'page'): self.assertIn("'%s'" % action, fold)
        self.assertIn('(max-width: 480px)', fold)
        self.assertIn('state.sideOpen = false', fold)


if __name__ == '__main__':
    unittest.main()
