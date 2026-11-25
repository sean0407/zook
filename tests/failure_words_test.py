# -*- coding: utf-8 -*-
"""#238: every failed reply carries a kind, whether trying again helps, and a plain next step with buttons that do something
that already exists (retry, another model, the usage page, a new chat, the Bot's settings, or macOS's own privacy page)."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_failure_words', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


M = load()


def info(error='', kind=None, **more):
    return M.failure_info(dict(status='failed', error=error, **({'errorKind': kind} if kind else {}), **more))


class KindsTest(unittest.TestCase):
    def test_macos_privacy_is_told_apart(self):
        self.assertEqual(M.classify_error('Error: Operation not permitted (os error 1)'), 'privacy')
        self.assertEqual(M.classify_error("open '/Users/x/Desktop/a.txt': EPERM"), 'privacy')
        self.assertEqual(M.classify_error('execution error: Not authorized to send Apple events to Finder. (-1743)'), 'automation')
        self.assertEqual(M.classify_error('connection refused'), 'network')  # the older kinds still win where they match
        self.assertEqual(M.classify_error('the permitted operations are listed'), 'unknown')

    def test_each_kind_says_whether_retry_helps_and_what_to_do(self):
        cases = [  # (failure, kind it is shown as, retry helps, buttons)
            (info(M.ERROR_MESSAGES['quota'] % 'Codex', 'quota'), 'quota', False, ['redo-model', 'usage', 'retry']),
            (info('這個月的用量預算已用完。可到「各模型使用量」調整上限。'), 'quota', False, ['redo-model', 'usage', 'retry']),
            (info(M.ERROR_MESSAGES['auth'] % 'Claude', 'auth'), 'auth', False, ['usage', 'redo-model', 'retry']),
            (info(M.ERROR_MESSAGES['denied'] % 'Claude', 'denied'), 'auth', False, ['usage', 'redo-model', 'retry']),
            (info(M.ERROR_MESSAGES['network'] % 'Grok', 'network'), 'network', True, ['retry', 'redo-model']),
            (info('執行逾時：已超過時間上限。'), 'timeout', True, ['retry', 'redo-model']),
            (info('找不到所選 CLI，請先安裝並登入。'), 'install', False, ['usage', 'redo-model', 'retry']),
            (info('這次輸入沒有經過使用者核准。'), 'approval', True, ['retry']),
            (info(M.ERROR_MESSAGES['privacy'] % 'Codex', 'privacy'), 'privacy', False, ['settings', 'retry']),
            (info(M.ERROR_MESSAGES['automation'] % 'Codex', 'automation'), 'privacy', False, ['settings', 'retry']),
            (info(M.ERROR_MESSAGES['context'] % 'Codex', 'context'), 'context', False, ['new-chat', 'redo-model']),
            (info(M.ERROR_MESSAGES['model'] % 'Codex', 'model'), 'model', False, ['edit-bot', 'redo-model']),
            (info(M.ERROR_MESSAGES['busy'] % 'Codex', 'busy'), 'busy', True, ['retry', 'redo-model']),
            (info('服務重新啟動，工作已中斷。'), 'interrupted', True, ['retry']),
            (info('something odd'), 'other', True, ['retry', 'redo-model']),
            (info(M.ERROR_MESSAGES['unknown'] % 'Codex', 'unknown'), 'other', True, ['retry', 'redo-model']),
            (info(''), 'other', True, ['retry', 'redo-model']),
        ]
        for f, kind, retry, buttons in cases:
            self.assertEqual((f['kind'], f['retry'], [a['action'] for a in f['actions']]), (kind, retry, buttons), f)
            self.assertTrue(f['label'] and f['next']); self.assertNotIn('%s', f['next'])
            for a in f['actions']: self.assertTrue(a['label'])

    def test_the_kind_a_cli_reported_comes_before_the_words(self):
        self.assertEqual(info('CLI 執行失敗。', 'quota')['kind'], 'quota')
        self.assertEqual(info('CLI 執行失敗。', 'unknown')['kind'], 'other')

    def test_privacy_opens_the_matching_settings_page(self):
        files, automation = info(M.ERROR_MESSAGES['privacy'] % 'Codex', 'privacy'), info(M.ERROR_MESSAGES['automation'] % 'Codex', 'automation')
        self.assertEqual(files['actions'][0]['pane'], 'files'); self.assertEqual(automation['actions'][0]['pane'], 'automation')
        self.assertIn('完整磁碟取用權限', files['next']); self.assertIn('自動化', automation['next'])
        self.assertEqual(M.PRIVACY_PANES['files'], 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles')
        self.assertEqual(M.PRIVACY_PANES['automation'], 'x-apple.systempreferences:com.apple.preference.security?Privacy_Automation')

    def test_quota_says_when_it_comes_back(self):
        f = info(M.ERROR_MESSAGES['quota'] % 'Codex', 'quota', quotaResetAt='2026-11-25T06:30:00Z')
        self.assertEqual(f['resetAt'], '2026-11-25T06:30:00Z')
        self.assertNotIn('resetAt', info(M.ERROR_MESSAGES['network'] % 'Codex', 'network', quotaResetAt='2026-11-25T06:30:00Z'))

    def test_reset_time_comes_from_the_full_window(self):
        class S: pass
        store, later = S(), time.time() + 3600
        store.data = {'quota': {'codex': {'windows': [{'usedPercent': 40, 'resetsAt': later - 600}, {'usedPercent': 100, 'resetsAt': later * 1000}]},
                                'codex@acc1': {'windows': [{'usedPercent': 100, 'resetsAt': time.time() - 10}]}}}
        at = M.quota_reset_at(store, 'codex', '')
        self.assertEqual(at, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(later))))
        self.assertEqual(M.quota_reset_at(store, 'codex', 'acc1'), '')  # already reset: nothing to promise
        self.assertEqual(M.quota_reset_at(store, 'grok', ''), '')

    def test_only_failed_jobs_carry_it(self):
        self.assertIsNone(M.failure_info(dict(status='completed', error='')))
        self.assertIn('failure', M.job_view(dict(id='j', status='failed', error='執行逾時：已超過時間上限。')))
        self.assertNotIn('failure', M.job_view(dict(id='j', status='completed', content='hi')))


CODEX = '''#!/usr/bin/env python3
import json, sys
sys.stdin.read()
print(json.dumps({'type': 'turn.failed', 'error': {'message': 'failed to read /Users/x/Desktop/a.txt: Operation not permitted (os error 1)'}})); sys.exit(1)
'''


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CODEX); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_NO_BROWSER='1')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def test_a_blocked_file_shows_where_to_allow_it(self):
        bot = self.req('POST', '/api/bots', {'name': 'E', 'provider': 'codex'})[1]
        self.req('PATCH', '/api/settings', {'fallbacks': []})
        job_id = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': 'hi'})[1]['jobId']
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': break
            time.sleep(0.1)
        self.assertEqual(job['status'], 'failed'); self.assertEqual(job['failure']['kind'], 'privacy'); self.assertNotIn('/Users/x', job['error'])
        listed = next(j for j in self.req('GET', '/api/state')[1]['jobs'] if j['id'] == job_id)
        self.assertEqual(listed['failure']['kind'], 'privacy')

    def test_only_the_two_privacy_pages_can_be_opened(self):
        self.assertEqual(self.req('POST', '/api/privacy-settings', {'pane': 'files'}), (200, {'opened': True}))
        self.assertEqual(self.req('POST', '/api/privacy-settings', {'pane': 'automation'})[0], 200)
        for bad in ('x-apple.systempreferences:com.apple.preference.security', 'https://example.com', '', None, 3):
            self.assertEqual(self.req('POST', '/api/privacy-settings', {'pane': bad})[0], 400, bad)


class WindowTest(unittest.TestCase):
    def test_the_failed_reply_shows_kind_reason_and_buttons(self):
        page = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))
        for part in ('function failureCard(', 'data-action="open-privacy"', "case 'open-privacy'", 'privacy-settings', 'failure-card'):
            self.assertTrue(part in page, part)
        self.assertIn('.failure-card', (ROOT / 'frontend/style.css').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
