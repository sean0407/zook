# -*- coding: utf-8 -*-
"""Grok with 存取範圍 = 指定資料夾 starts inside that folder, where its own sandbox keeps it."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
GROK = '''#!/usr/bin/env python3
import json, os, sys
if set(sys.argv) & {'models', '--version', '--help'}: print('ok'); sys.exit(0)
here = os.path.dirname(sys.argv[0])
cwd = sys.argv[sys.argv.index('--cwd') + 1]
prompt_file = sys.argv[sys.argv.index('--prompt-file') + 1]
seen = dict(cwd=cwd, processCwd=os.getcwd(), args=sys.argv[1:], promptInside=os.path.realpath(prompt_file).startswith(os.path.realpath(cwd) + os.sep),
            grok=sorted(os.listdir(os.path.join(cwd, '.grok'))), prompt=open(prompt_file).read())
json.dump(seen, open(os.path.join(here, 'seen.json'), 'w'), ensure_ascii=False)
print(json.dumps({'type': 'text', 'data': 'ok'})); print(json.dumps({'type': 'end', 'stopReason': 'end_turn', 'usage': {'input_tokens': 10, 'output_tokens': 2}}))
'''


def gone(path, seconds=10):
    """The clean-up runs right after the reply is marked finished: wait for it instead of checking at once (a slow CI machine)."""
    end = time.time() + seconds
    while time.time() < end and path.exists(): time.sleep(0.05)
    return not path.exists()


class GrokFolderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir(); (self.root / 'project').mkdir()
        cli = self.root / 'bin/grok'; cli.write_text(GROK); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'permissionMode': 'auto'})

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def ask(self, bot):
        job_id = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': 'hi'})[1]['jobId']
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + job_id)[1]
            if job['status'] != 'running': return job
            time.sleep(0.1)
        self.fail('no reply')

    def seen(self): return json.loads((self.root / 'bin/seen.json').read_text())

    def test_starts_in_the_chosen_folder_and_leaves_nothing_behind(self):
        folder = self.root / 'project'
        bot = self.req('POST', '/api/bots', {'name': 'G', 'provider': 'grok', 'access': 'folder', 'accessFolder': str(folder)})[1]
        job = self.ask(bot)
        self.assertEqual(job['status'], 'completed', job.get('error'))
        seen = self.seen()
        self.assertEqual((seen['cwd'], seen['processCwd']), (str(folder), str(folder)))
        self.assertTrue(seen['promptInside'])  # its sandbox could not read a prompt kept anywhere else
        self.assertIn('--sandbox', seen['args']); self.assertEqual(seen['args'][seen['args'].index('--sandbox') + 1], 'strict')
        self.assertIn('.zook-owned', seen['grok']); self.assertIn('config.toml', seen['grok'])
        self.assertIn('可以讀寫這個資料夾內的檔案', seen['prompt']); self.assertNotIn('碰不到使用者指定的資料夾', seen['prompt'])
        self.assertTrue(gone(folder / '.grok'))  # removed when the reply ended (just after it is marked finished)

    def test_a_grok_folder_that_is_already_there_is_never_touched(self):
        folder = self.root / 'project'; (folder / '.grok').mkdir(); (folder / '.grok/config.toml').write_text('mine')
        bot = self.req('POST', '/api/bots', {'name': 'G', 'provider': 'grok', 'access': 'folder', 'accessFolder': str(folder)})[1]
        job = self.ask(bot)
        self.assertEqual(job['status'], 'failed'); self.assertIn('已經有 .grok 設定', job['error'])
        self.assertEqual((folder / '.grok/config.toml').read_text(), 'mine'); self.assertEqual(sorted(os.listdir(folder / '.grok')), ['config.toml'])

    def test_a_folder_left_by_a_crash_is_cleaned_up_and_other_scopes_stay_in_the_workspace(self):
        folder = self.root / 'project'; (folder / '.grok').mkdir(); (folder / '.grok/.zook-owned').write_text('old-job'); (folder / '.grok/.zook-prompt-old.txt').write_text('leftover')
        bot = self.req('POST', '/api/bots', {'name': 'G', 'provider': 'grok', 'access': 'folder', 'accessFolder': str(folder)})[1]
        self.assertEqual(self.ask(bot)['status'], 'completed'); self.assertTrue(gone(folder / '.grok'))
        inside = self.req('POST', '/api/bots', {'name': 'W', 'provider': 'grok', 'access': 'workspace'})[1]
        self.assertEqual(self.ask(inside)['status'], 'completed')
        self.assertIn('workspaces', self.seen()['cwd']); self.assertNotEqual(self.seen()['cwd'], str(folder))


if __name__ == '__main__':
    unittest.main()
