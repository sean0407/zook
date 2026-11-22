# -*- coding: utf-8 -*-
"""The 「先問」 gate (2026-11-22): Claude and Cursor Bots have the whole Mac and ask only at the four safety boundaries.
A fake Claude runs Zook's PreToolUse hook the way the real one does, before each of its own tools."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest, unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
sys.path.insert(0, str(ROOT / 'backend'))
import zook_gate  # noqa: E402

CLAUDE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
if 'auth' in a: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if '--help' in a or '--version' in a: sys.exit(0)
prompt = sys.stdin.read()
here = os.path.dirname(sys.argv[0])
open(os.path.join(here, 'args.log'), 'a').write(json.dumps(a) + '\n')
settings = json.loads(a[a.index('--settings') + 1]) if '--settings' in a else None
if settings: subprocess.run(settings['hooks']['SessionStart'][0]['hooks'][0]['command'], shell=True, input=json.dumps({'hook_event_name': 'SessionStart'}), text=True)  # as Claude does when it starts
def hook(tool, data, env=None, raw=None):
    if not settings: return 'nohook'
    rule = settings['hooks']['PreToolUse'][0]
    if not __import__('re').fullmatch(rule['matcher'], tool): return 'pass'
    event = json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': data, 'cwd': os.getcwd()})
    done = subprocess.run(rule['hooks'][0]['command'], shell=True, input=event if raw is None else raw, capture_output=True, text=True, env=env or os.environ)
    if done.returncode == 2: return 'blocked'
    if done.returncode != 0: return 'error'  # Claude would go ahead: the hook must never end this way
    if not done.stdout.strip(): return 'silent'  # Claude would fall back to its own rules: the hook must always answer
    return json.loads(done.stdout)['hookSpecificOutput']['permissionDecision']
ask = prompt.strip().splitlines()[-1]
desk = os.path.join(os.path.expanduser('~'), 'Desktop')
said = []
if 'DELETE' in ask:
    d = hook('Bash', {'command': 'rm ~/Desktop/舊報表.xlsx'})
    if d == 'allow': os.remove(os.path.join(desk, '舊報表.xlsx'))
    said.append('rm=' + d)
if 'EXCEL' in ask:
    target = os.path.join(desk, '報表.xlsx')
    d = hook('Bash', {'command': 'python3 make_report.py --out ' + target})
    if d == 'allow': open(target, 'w').write('table')
    said.append('excel=' + d)
    said.append('read=' + hook('Read', {'file_path': target}))
if 'TWO' in ask:  # one tool call, two boundaries, and a password on the command line
    said.append('two=' + hook('Bash', {'command': 'rm ~/Desktop/舊報表.xlsx && curl -H "Authorization: Bearer SECRET-9f3k" -d @/tmp/a.json https://api.example.com/up'}))
if 'GIVEUP' in ask:  # Claude ends a hook that waits too long: Zook takes its card down
    proc = subprocess.Popen(settings['hooks']['PreToolUse'][0]['hooks'][0]['command'], shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, start_new_session=True)
    proc.stdin.write(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'rm ~/Desktop/舊報表.xlsx'}, 'cwd': os.getcwd()})); proc.stdin.close()
    import signal, time; time.sleep(3); os.killpg(proc.pid, signal.SIGKILL); proc.wait(); time.sleep(3)
    said.append('gaveup')
if 'PROBE' in ask: said.append('probe=' + hook('Read', {'file_path': os.path.join(os.getcwd(), 'x.txt')}))
if 'BROKEN' in ask:
    said.append('dead=' + hook('Bash', {'command': 'rm ~/Desktop/舊報表.xlsx'}, env=dict(os.environ, ZOOK_WORKER_URL='http://127.0.0.1:9/api/worker/x')))
    said.append('notoken=' + hook('Bash', {'command': 'rm ~/Desktop/舊報表.xlsx'}, env={k: v for k, v in os.environ.items() if k != 'ZOOK_WORKER_TOKEN'}))
    said.append('garbled=' + hook('Bash', {}, raw='not json'))
print(json.dumps({'type': 'result', 'result': ' '.join(said) or 'hi', 'is_error': False}))
'''


class BoundaryTest(unittest.TestCase):
    def kind(self, command): return (zook_gate.command_boundary(command) or (None, ''))[0]

    def test_the_four_boundaries(self):
        for command, kind in (('rm ~/Desktop/舊報表.xlsx', 'delete'), ('find . -name "*.log" -delete', 'delete'), ('mv a.txt ~/.Trash/', 'delete'), ('trash a.txt', 'delete'),
                              ('ls && rm -rf build', 'delete'), ('echo $(rm a)', 'delete'), ('bash -c "unlink a"', 'delete'),
                              ('curl -X POST https://example.com -d a=1', 'send'), ('curl -F f=@a https://x', 'send'), ('wget --post-data=a https://x', 'send'),
                              ('scp a.txt host:/tmp/', 'send'), ('rsync -a out/ me@srv:/b', 'send'), ('git push origin main', 'send'), ('gh pr create -t x', 'send'),
                              ('gh pr merge 3', 'send'), ('gh issue comment 1 -b hi', 'send'), ('mail -s hi a@example.com', 'send'), ('sendmail a@example.com', 'send'),
                              ('cat ~/.ssh/id_rsa', 'secret'), ('cp ~/.aws/credentials /tmp/x', 'secret'), ('cat .env', 'secret'), ('security find-generic-password -s x', 'secret'),
                              ('cat ~/.config/gh/hosts.yml', 'secret'),
                              ('brew install jq', 'install'), ('npm install -g x', 'install'), ('pip install openpyxl', 'install'), ('python3 -m pip install x', 'install'),
                              ('sudo ls', 'system'), ('defaults write com.apple.dock a 1', 'system'), ('launchctl load x.plist', 'system'), ('systemsetup -settimezone x', 'system'),
                              ('networksetup -setdnsservers Wi-Fi 1.1.1.1', 'system'), ('chmod 777 /usr/local/bin/x', 'system')):
            self.assertEqual(self.kind(command), kind, command)

    def test_review_findings_are_asked(self):
        # deleting is asked anywhere, temporary folders too; redirections; every starting point; options with values; unreadable commands
        for command, kind in (('rm /tmp/zook-scratch.py', 'delete'), ('rm -f "/private/tmp/a b.png"', 'delete'), ('find /tmp ~/Desktop -name x -delete', 'delete'),
                              ('cat < ~/.ssh/id_rsa', 'secret'), ('wc -l < ~/.aws/credentials', 'secret'), ('echo x >> ~/.ssh/authorized_keys', 'secret'),
                              ('find /tmp ~/.ssh -name "*.pub"', 'secret'), ('find ~ -name "*" -exec cat {} +', 'secret'), ('grep -r token ~', 'secret'),
                              ('grep -R password /', 'secret'), ('rg -i key ~', 'secret'), ('tar czf all.tgz ~', 'secret'), ('cp -r ~ /Volumes/USB', 'secret'),
                              ('git -C ~/proj push origin main', 'send'), ('git -c user.name=x push', 'send'), ('gh --repo me/app pr create -t x', 'send'),
                              ('gh -R me/app issue comment 3 -b hi', 'send'), ('sudo -u root rm /etc/hosts', 'system'),
                              ('echo "unbalanced', 'unclear'), ('$RUN ~/Desktop/a', 'unclear'), ('git --frobnicate push', 'unclear'),
                              ('python3 -c "import shutil; shutil.rmtree(\'x\')"', 'unclear'), ('node -e "require(\'child_process\').execSync(\'x\')"', 'unclear'),
                              ('python3 - <<EOF\nimport os\nos.remove("a")\nEOF', 'unclear')):
            self.assertEqual(self.kind(command), kind, command)
        self.assertIn(('delete', '刪除檔案 ~/Desktop/舊報表.xlsx'), zook_gate.command_boundaries('sudo rm ~/Desktop/舊報表.xlsx'))

    def test_every_boundary_of_one_call_is_listed(self):
        found = zook_gate.command_boundaries('rm ~/Desktop/a.txt && curl -d @b.json https://u:pw@api.example.com/x; brew install jq')
        self.assertEqual([k for k, _ in found], ['delete', 'send', 'install'])
        self.assertEqual(found[1], ('send', '對外送出 檔案 %s/b.json 到 api.example.com' % zook_gate._where(os.getcwd())))  # the file and where it goes, never the password

    def test_titles_never_hold_the_command(self):
        for command in ('curl -H "Authorization: Bearer SECRET-1" -X POST https://api.example.com', 'security add-generic-password -a me -s x -w SECRET-1',
                        'mysql -pSECRET-1 < ~/.ssh/x', 'git push https://me:SECRET-1@github.com/me/x main', 'brew install --token=SECRET-1 jq',
                        'sudo -S SECRET-1', 'defaults write com.x key SECRET-1', 'mail -s SECRET-1 a@example.com'):
            found = zook_gate.command_boundaries(command)
            self.assertTrue(found, command)
            self.assertNotIn('SECRET-1', json.dumps(found, ensure_ascii=False), command)

    def test_zook_and_cli_settings_are_guarded(self):
        backend = str(ROOT / 'backend')
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['ZOOK_DATA_DIR'] = tmp
            try:
                for command in ('echo x > %s/zook_gate.py' % backend, 'cp evil.py %s/cursor_guard.py' % backend, 'sed -i "" s/a/b/ %s/zook/gate.py' % backend,
                                'mv %s/zook_gate.py /tmp/' % backend, 'echo {} > ~/proj/.cursor/hooks.json', 'tee ~/.claude/settings.json',
                                'echo {} > %s/swarmr.json' % tmp, 'cp x %s/workspaces/b1/.cursor/hooks.json' % tmp):
                    self.assertIn('guard', [k for k, _ in zook_gate.command_boundaries(command)], command)
                self.assertIn('guard', [k for k, _ in zook_gate.command_boundaries('rm %s/zook_gate.py' % backend)])
                self.assertEqual(zook_gate.command_boundaries('echo hi > %s/workspaces/b1/報告.md' % tmp), [])  # the Bot's own work
                self.assertEqual(zook_gate.boundary('Write', {'file_path': '%s/workspaces/b1/.cursor/hooks.json' % tmp, 'content': '{}'})[0], 'guard')
                self.assertEqual(zook_gate.boundary('Edit', {'file_path': backend + '/zook_gate.py', 'old_string': 'a', 'new_string': 'b'})[0], 'guard')
                app = '/Applications/Zook.app/Contents/Resources/backend/zook_gate.py'
                with unittest.mock.patch.object(zook_gate, 'HERE', '/Applications/Zook.app/Contents/Resources/backend'):
                    self.assertEqual(zook_gate.boundary('Write', {'file_path': app, 'content': 'x'})[0], 'guard')
                    self.assertEqual(zook_gate.boundary('Write', {'file_path': '/Applications/Zook.app/Contents/Info.plist', 'content': 'x'})[0], 'guard')
            finally: os.environ.pop('ZOOK_DATA_DIR', None)

    def test_round_two(self):
        # CLI sign-ins are keys too, and so are Zook's own extra accounts
        for path in ('~/.codex/auth.json', '~/.gemini/oauth_creds.json', '~/.grok/auth.json', '~/.config/cursor/auth.json', '~/proj/service-account-x.json', '~/proj/server.pem'):
            self.assertEqual(zook_gate.boundary('Read', {'file_path': path})[0], 'secret', path)
        self.assertIsNone(zook_gate.boundary('Read', {'file_path': '~/.grok/bin/grok'}))
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(os.environ, {'ZOOK_DATA_DIR': tmp}):
            self.assertEqual(zook_gate.boundary('Read', {'file_path': tmp + '/accounts/a1/auth.json'})[0], 'secret')
            self.assertEqual(zook_gate.command_boundary('cat %s/accounts/a1/config.toml' % tmp)[0], 'secret')
            # emptying an existing file with the shell is deleting it
            kept = Path(tmp, 'workspaces/b/報告.md'); kept.parent.mkdir(parents=True); kept.write_text('內容')
            for command in ('> %s' % kept, ': > %s' % kept, 'truncate -s 0 %s' % kept, 'cp /dev/null %s' % kept):
                self.assertIn('delete', [k for k, _ in zook_gate.command_boundaries(command)], command)
            self.assertEqual(zook_gate.command_boundaries('echo hi > %s' % kept), [])
        # two files of the same name in different folders are two lines, each with where it is
        found = zook_gate.command_boundaries('rm ~/a/報告.md ~/b/報告.md')
        self.assertEqual(found, [('delete', '刪除檔案 ~/a/報告.md、~/b/報告.md')])
        self.assertEqual(zook_gate.command_boundaries('rm ~/a/x && rm ~/b/x'), [('delete', '刪除檔案 ~/a/x'), ('delete', '刪除檔案 ~/b/x')])
        # more than one card shows in full is refused, never approved as a batch
        many = ' && '.join('rm ~/f%d' % i for i in range(11))
        with unittest.mock.patch.object(zook_gate, 'ask', side_effect=AssertionError('asked')):
            allowed, why = zook_gate.decide('Bash', {'command': many})
            self.assertFalse(allowed); self.assertIn('分成幾個較小的步驟', why)
            self.assertFalse(zook_gate.decide('Bash', {'command': 'rm ~/' + 'a' * 250})[0])
        # what the activity record keeps of a command
        self.assertEqual(zook_gate.command_summary('ls -la && grep -n x notes.txt'), '執行指令：ls、grep')
        self.assertNotIn('SECRET', zook_gate.command_summary('curl -H "X-Key: SECRET" https://a.example.com -d x'))

    def test_round_three(self):
        # two uploads of the same file to the same site are shown as two
        found = zook_gate.merged(zook_gate.command_boundaries('curl -T /tmp/a.pdf https://x.example.com && curl -T /tmp/a.pdf https://x.example.com'))
        self.assertEqual(found, [('send', '對外送出 檔案 /tmp/a.pdf 到 x.example.com（共 2 次）')])
        self.assertEqual(zook_gate.command_boundaries('scp /tmp/a.pdf me@host:/x'), [('send', '對外送出 檔案 /tmp/a.pdf 到 host')])
        self.assertEqual(len(zook_gate.command_boundaries('echo $(rm /tmp/a)')), 1)  # what runs inside $( ) is counted once
        many = ' && '.join(['curl -T /tmp/a.pdf https://x.example.com'] * 11)
        with unittest.mock.patch.object(zook_gate, 'ask', side_effect=AssertionError('asked')):
            self.assertFalse(zook_gate.decide('Bash', {'command': many})[0])  # counted before they are merged
        # a reply held to folders: every path is checked against them
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(os.environ, {'ZOOK_GATE_ROOTS': json.dumps([tmp + '/attachments'])}):
            self.assertTrue(zook_gate.decide('Read', {'file_path': tmp + '/attachments/a.pdf'}, home=tmp)[0])
            for tool, data in (('Read', {'file_path': '~/Documents/私人.docx'}), ('Grep', {'pattern': 'x'}), ('Glob', {'pattern': '../**/*.pdf', 'path': tmp + '/attachments'}),
                               ('Bash', {'command': 'ls'}), ('Read', {'file_path': tmp + '/attachments/../x'})):
                self.assertFalse(zook_gate.decide(tool, data, home=tmp)[0], (tool, data))
        # the hook itself: a read-only reply never gets an allow, only a refusal outside the folders; and it leaves its mark
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, ZOOK_GATE_ROOTS=json.dumps([tmp]), ZOOK_GATE_DEFER='1', ZOOK_GATE_MARK=tmp + '/mark', ZOOK_GATE_NONCE='n0nce')
            run = lambda event: subprocess.run([sys.executable, str(ROOT / 'backend/zook_gate.py')], input=json.dumps(event), capture_output=True, text=True, env=env)
            inside = run({'hook_event_name': 'PreToolUse', 'tool_name': 'Read', 'tool_input': {'file_path': tmp + '/a.txt'}, 'cwd': tmp})
            self.assertEqual((inside.returncode, inside.stdout), (0, ''))
            outside = run({'hook_event_name': 'PreToolUse', 'tool_name': 'Read', 'tool_input': {'file_path': '/etc/hosts'}, 'cwd': tmp})
            self.assertEqual(json.loads(outside.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertEqual(Path(tmp + '/mark').read_text(), 'n0nce:tool\nn0nce:tool\n')  # this CLI's own word, once for each tool checked
            os.unlink(tmp + '/mark'); self.assertEqual(run({'hook_event_name': 'SessionStart'}).returncode, 0); self.assertEqual(Path(tmp + '/mark').read_text(), 'n0nce:start\n')

    def test_round_four(self):
        # every send in one call is shown with its file and where it goes; one call with several is refused, never one card for all
        self.assertEqual(zook_gate.command_boundaries('curl -T /tmp/a.pdf https://x.example.com/hooks/T0KEN-123?token=SECRET'), [('send', '對外送出 檔案 /tmp/a.pdf 到 x.example.com')])  # the site only: a path may carry a token
        for command in ('curl -T /tmp/a.pdf https://x.example.com/a -T /tmp/b.pdf https://x.example.com/b', 'curl -F f=@/tmp/a -F g=@/tmp/b https://x.example.com',
                        'curl -d @/tmp/a https://x.example.com/a --next -d @/tmp/b https://x.example.com/b',
                        'curl -T /tmp/a.pdf "https://x.example.com/{a,b}"', 'curl -d @/tmp/a "https://x.example.com/item[1-3]"', 'curl -K /tmp/upload.cfg', 'curl --config=/tmp/c -X POST https://x.example.com'):
            with unittest.mock.patch.object(zook_gate, 'ask', side_effect=AssertionError('asked')):
                allowed, why = zook_gate.decide('Bash', {'command': command})
            self.assertFalse(allowed, command); self.assertIn('每次一個檔案、一個目的地', why)
        for command in ('curl -g -T /tmp/a.pdf "https://x.example.com/[1-3]"', 'curl --globoff -d @/tmp/a "https://x.example.com/{a}"', 'curl -T /tmp/a https://x.example.com/a]'):
            with unittest.mock.patch.object(zook_gate, 'ask', side_effect=AssertionError('asked')):
                self.assertFalse(zook_gate.decide('Bash', {'command': command})[0], command)  # any brace or bracket: refused, -g or not
        found = zook_gate.merged(zook_gate.command_boundaries('curl -T /tmp/a.pdf https://x.example.com/T0KEN-9/credentials.json'))
        self.assertNotIn('T0KEN', json.dumps(found, ensure_ascii=False)); self.assertIn('x.example.com', found[0][1])  # a key-like name at the end of an address: still the site only
        # a key file by the name it was uploaded with, and by what a link really points to
        with tempfile.TemporaryDirectory() as tmp:
            att = Path(tmp, 'workspaces/b/attachments'); att.mkdir(parents=True)
            (att / '1a2b3c4d-credentials.json').write_text('{}'); (att / '9z8y7x6w-報告.pdf').write_text('x')
            self.assertEqual(zook_gate.boundary('Read', {'file_path': str(att / '1a2b3c4d-credentials.json')})[0], 'secret')
            self.assertIsNone(zook_gate.boundary('Read', {'file_path': str(att / '9z8y7x6w-報告.pdf')}))
            Path(tmp, '.env').write_text('K=1'); (att / 'notes.txt').symlink_to(Path(tmp, '.env'))
            self.assertEqual(zook_gate.boundary('Read', {'file_path': str(att / 'notes.txt')})[0], 'secret')
            self.assertTrue(zook_gate.secret_name(str(att / 'x.txt'), original='id_ed25519'))
            (att / '5e6f7a8b-env').write_text('K=1')  # uploaded as .env: the upload drops the leading dot
            self.assertEqual(zook_gate.boundary('Read', {'file_path': str(att / '5e6f7a8b-env')})[0], 'secret')
            (att / '0f0f0f0f-notes.txt').write_text('x'); (att.parent / '.zook-uploads.json').write_text(json.dumps({'0f0f0f0f-notes.txt': 'service-account-prod.json'}))
            self.assertEqual(zook_gate.boundary('Read', {'file_path': str(att / '0f0f0f0f-notes.txt')})[0], 'secret')  # by the name it was uploaded with

    def test_search_tools(self):
        self.assertEqual(zook_gate.boundary('Grep', {'pattern': 'token', 'path': '~'})[0], 'secret')
        self.assertEqual(zook_gate.boundary('Grep', {'pattern': 'token'}, home=os.path.expanduser('~'))[0], 'secret')  # its default is where it started
        self.assertIsNone(zook_gate.boundary('Grep', {'pattern': 'token', 'path': '~/Desktop'}))
        self.assertEqual(zook_gate.boundary('Glob', {'pattern': '~/.ssh/*'})[0], 'secret')

    def test_ordinary_work_is_not_asked(self):
        for command in ('ls -la ~/Desktop', 'python3 make.py > ~/Desktop/報表.csv', 'curl -s https://example.com', 'git status', 'git commit -m x', 'gh pr view 3',
                        'brew list', 'npm install', 'defaults read com.apple.dock', 'launchctl list', 'chmod +x ./run.sh', 'scp a b', 'cp a.txt ~/Desktop/',
                        'qlmanage -t -s 1600 -o /tmp/x ~/Desktop/a.xlsx', 'git -C ~/proj status', 'gh --repo me/app pr view 3', 'grep -n x notes.txt',
                        'find ~/Desktop -name "*.xlsx"', 'python3 -c "print(1+1)"', 'ls 2>/dev/null', 'echo ok > /tmp/out.txt'):
            self.assertIsNone(zook_gate.command_boundary(command), command)

    def test_file_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            kept = os.path.join(tmp, 'a.txt'); Path(kept).write_text('content')
            self.assertEqual(zook_gate.boundary('Write', {'file_path': kept, 'content': ''})[0], 'delete')  # emptying a file
            self.assertEqual(zook_gate.boundary('Edit', {'file_path': kept, 'old_string': 'content', 'new_string': ''})[0], 'delete')
            self.assertIsNone(zook_gate.boundary('Write', {'file_path': kept, 'content': 'new'}))
            self.assertIsNone(zook_gate.boundary('Edit', {'file_path': kept, 'old_string': 'cont', 'new_string': ''}))
        self.assertEqual(zook_gate.boundary('Read', {'file_path': '~/.ssh/id_ed25519'})[0], 'secret')
        self.assertEqual(zook_gate.boundary('Write', {'file_path': os.path.expanduser('~/.claude/settings.json'), 'content': '{}'})[0], 'guard')
        self.assertEqual(zook_gate.boundary('Delete', {'path': '/x/舊報表.xlsx'}), ('delete', '刪除檔案 /x/舊報表.xlsx'))
        self.assertIsNone(zook_gate.boundary('mcp__zook__zook_remember', {'content': 'rm -rf /'}))

    def test_titles_are_plain(self):
        self.assertEqual(zook_gate.command_boundary('rm ~/Desktop/舊報表.xlsx'), ('delete', '刪除檔案 ~/Desktop/舊報表.xlsx'))
        self.assertEqual(zook_gate.command_boundary('brew install x'), ('install', '安裝軟體 brew install x'))

    def test_no_zook_means_no(self):
        env = dict(os.environ, ZOOK_WORKER_URL='', ZOOK_WORKER_TOKEN='')
        run = lambda event: subprocess.run([sys.executable, str(ROOT / 'backend/zook_gate.py')], input=event, capture_output=True, text=True, env=env)
        done = run(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'rm ~/Desktop/a.txt'}}))
        self.assertEqual(json.loads(done.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
        done = run(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'ls'}}))
        self.assertEqual(json.loads(done.stdout)['hookSpecificOutput']['permissionDecision'], 'allow')  # ordinary: the hook itself allows it, nothing else does
        self.assertEqual(run('{').returncode, 2)  # unreadable: a refusal Claude obeys


class GateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.home = self.root / 'home'; (self.home / 'Desktop').mkdir(parents=True)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/claude'; cli.write_text(CLAUDE); cli.chmod(0o755)
        env = dict(os.environ, HOME=str(self.home), PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1',
                   ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root / 'secrets'),
                   ZOOK_CLAUDE_MANAGED_DIR=str(self.root / 'policy'), ZOOK_CLAUDE_MDM='[]')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'permissionMode': 'manual', 'access': 'workspace'})  # the defaults the other CLIs use do not apply
        self.bot = self.req('POST', '/api/bots', {'name': '助理', 'provider': 'claude'})[1]
        self.old = self.home / 'Desktop/舊報表.xlsx'; self.old.write_text('old')
        first = self.ask('PROBE')  # Zook gives the whole Mac only after it has seen its hook check a tool here
        self.assertEqual(first['nativeAccess'][0], 'workspace')

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def ask(self, text, answer=None):
        status, sent = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text}); self.assertEqual(status, 202, sent)
        end = time.time() + 40
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            for a in job.get('approvals') or []:
                if a['status'] == 'pending' and answer is not None: time.sleep(1.5); self.req('POST', '/api/approvals/' + a['id'], {'decision': answer})
            if job['status'] != 'running': return job
            time.sleep(0.1)
        self.fail('no reply')

    def last_args(self): return json.loads((self.root / 'bin/args.log').read_text().splitlines()[-1])

    def test_delete_asks_and_no_keeps_the_file(self):
        job = self.ask('DELETE', answer='deny')
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertIn('rm=deny', job['content'])
        self.assertEqual([(a['text'], a['status'], a['category']) for a in job['approvals']], [('刪除檔案 ~/Desktop/舊報表.xlsx', 'denied', 'danger')])
        self.assertTrue(self.old.exists())
        job = self.ask('DELETE', answer='approve')
        self.assertIn('rm=allow', job['content']); self.assertFalse(self.old.exists())

    def test_whole_mac_and_ordinary_work_goes_ahead(self):
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'manual', 'access': 'workspace'})  # kept, not used for a Claude Bot
        job = self.ask('EXCEL')
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertEqual(job['content'], 'excel=allow read=allow'); self.assertEqual(job.get('approvals') or [], [])
        self.assertTrue((self.home / 'Desktop/報表.xlsx').exists())
        args = self.last_args()
        self.assertIn('Bash', args[args.index('--tools') + 1].split(','))
        self.assertEqual(args[args.index('--add-dir') + 1], '/')
        hook = json.loads(args[args.index('--settings') + 1])['hooks']['PreToolUse'][0]['hooks'][0]
        self.assertEqual(hook['onFailure'], 'block')  # a hook that times out or crashes is a refusal
        self.assertEqual(args[args.index('--permission-mode') + 1], 'manual')
        allowed = args[args.index('--allowedTools') + 1].split(',')
        self.assertFalse(set(allowed) & {'Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep'})  # nothing runs without the hook's own answer
        self.assertEqual(job['nativeAccess'][0], 'full'); self.assertEqual(job['nativeAccess'][2], 'auto')
        bot = next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])
        self.assertEqual((bot['permissionMode'], bot['access']), ('manual', 'workspace'))  # the data is kept

    def test_one_card_lists_every_action_and_keeps_no_command(self):
        job = self.ask('TWO', answer='deny')
        self.assertIn('two=deny', job['content'])
        self.assertEqual([a['text'] for a in job['approvals']], ['刪除檔案 ~/Desktop/舊報表.xlsx\n對外送出 檔案 /tmp/a.json 到 api.example.com'])
        self.assertNotIn('SECRET-9f3k', json.dumps(self.req('GET', '/api/jobs/' + job['id'])[1], ensure_ascii=False))
        self.assertNotIn('SECRET-9f3k', (self.root / 'data/activity.jsonl').read_text() if (self.root / 'data/activity.jsonl').exists() else '')
        self.assertTrue(self.old.exists())

    def test_a_card_the_cli_stopped_waiting_for_is_taken_down(self):
        job = self.ask('GIVEUP')
        self.assertEqual([(a['status'], a.get('withdrawn')) for a in job['approvals']], [('expired', True)])
        self.assertTrue(self.old.exists())

    def test_a_policy_that_turns_hooks_off_leaves_claude_no_tools(self):
        self.req('PATCH', '/api/settings', {'webSearch': True})
        (self.root / 'policy').mkdir(); (self.root / 'policy/managed-settings.json').write_text(json.dumps({'allowManagedHooksOnly': True}))
        self.ask('EXCEL')
        args = self.last_args()
        self.assertEqual(args[args.index('--tools') + 1], '')  # no built-in tool, and no web tools either
        self.assertNotIn('--settings', args); self.assertNotIn('--add-dir', args)
        self.assertNotIn('WebSearch', args[args.index('--allowedTools') + 1])
        (self.root / 'policy/managed-settings.json').unlink()
        self.ask('EXCEL'); args = self.last_args()
        self.assertIn('WebSearch', args[args.index('--tools') + 1]); self.assertIn('--settings', args)

    def test_a_broken_gate_refuses(self):
        job = self.ask('BROKEN')
        self.assertEqual(job['content'], 'dead=deny notoken=deny garbled=blocked')
        self.assertTrue(self.old.exists())


class AutoAssignTest(unittest.TestCase):
    """D: a Bot on 自動選擇 gets its model when it is made, from its persona and work instructions."""
    CLI = '''#!/usr/bin/env python3
import json, os, sys
name = os.path.basename(sys.argv[0])
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if 'login' in sys.argv: print('Logged in using ChatGPT'); sys.exit(0)
if set(sys.argv) & {'models', '--version', '--help', 'app-server'}: print('Logged in'); sys.exit(0)
sys.stdin.read()
if name == 'claude': print(json.dumps({'type': 'result', 'result': 'from ' + name, 'is_error': False}))
else: print('from ' + name)
'''

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(self.CLI); cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600')
        self.start()
        self.req('PATCH', '/api/settings', {'autoModels': ['codex', 'claude']})
        self.first = self.req('POST', '/api/bots', {'name': '先來的', 'provider': 'auto', 'persona': '細心的分析師'})[1]  # sign-ins not known yet: stays on 自動選擇
        for _ in range(100):
            if len(self.req('GET', '/api/state')[1].get('autoStatus') or {}) >= 2: break
            time.sleep(.1)

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=self.env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def stop(self): self.proc.terminate(); self.proc.wait(timeout=10); self.proc.stdout.close()

    def tearDown(self): self.stop(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def test_made_edited_and_chosen_by_hand(self):
        self.assertEqual(self.first['provider'], 'auto')
        bot = self.req('POST', '/api/bots', {'name': '阿工', 'provider': 'auto', 'persona': '認真', 'instructions': '你是工程師，負責維護網站。'})[1]
        self.assertEqual((bot['provider'], bot['account'], bot['autoAssigned'], bot['autoReason']), ('codex', '', True, '寫程式多，配 Codex'))
        status, edited = self.req('PATCH', '/api/bots/' + bot['id'], {'instructions': '幫忙回覆客戶的簡短問題。', 'provider': 'codex', 'model': '', 'account': ''})
        self.assertEqual((edited['provider'], edited['autoAssigned']), ('claude', True))
        self.assertIn('改配 Claude', edited['autoNotice'])
        status, edited = self.req('PATCH', '/api/bots/' + bot['id'], {'provider': 'codex', 'model': '', 'account': ''})  # chosen by hand
        self.assertEqual(edited['provider'], 'codex'); self.assertNotIn('autoAssigned', edited); self.assertNotIn('autoReason', edited)
        status, edited = self.req('PATCH', '/api/bots/' + bot['id'], {'instructions': '你是工程師。'})
        self.assertEqual(edited['provider'], 'codex'); self.assertNotIn('autoNotice', edited)  # no longer matched automatically

    def test_bots_from_before_are_matched_once_and_told(self):
        self.stop()
        path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text())
        data['settings'].pop('autoFixed', None); path.write_text(json.dumps(data))
        self.start()
        for _ in range(100):
            bot = next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.first['id'])
            if bot['provider'] != 'auto': break
            time.sleep(.1)
        self.assertEqual((bot['provider'], bot['autoReason']), ('claude', '分析和寫報告多，配 Claude'))
        log = (self.root / 'data/activity.jsonl').read_text()
        self.assertIn('Bot「先來的」原本用自動選擇，現在固定配好：分析和寫報告多，配 Claude', log)


if __name__ == '__main__': unittest.main()
