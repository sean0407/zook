# -*- coding: utf-8 -*-
"""Antigravity through its official CLI, agy."""
import fnmatch, http.client, importlib.util, json, os, signal, subprocess, sys, tempfile, threading, time, types, unittest
from unittest import mock
from urllib.parse import quote
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_agy', SERVER); server = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(server)
USAGE = {'status': 'SUCCESS', 'response': 'x', 'command': {'name': 'usage', 'data': {'groups': [
    {'name': 'Gemini Models', 'buckets': [{'window': 'weekly', 'remaining_fraction': 0.75, 'reset_time': '2026-11-25T04:26:45Z'}]},
    {'name': 'Claude and GPT models', 'buckets': [{'window': 'weekly', 'remaining_fraction': 1.0, 'reset_time': '2026-11-25T04:29:49Z'}]}]}}}
AGY = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]; here = os.path.dirname(sys.argv[0])
if a == ['models']: print('Fetching available models...\\ngemini-3.8-flash-low\\tGemini 3.8 Flash (Low)'); sys.exit(0)
if a == ['--version']: print('1.5.10'); sys.exit(0)
if a[:2] == ['-p', '/usage']: print(open(os.path.join(here, 'usage.json')).read()); sys.exit(0)
config = open('.agents/mcp_config.json').read() if os.path.exists('.agents/mcp_config.json') else ''
prompt = json.loads(sys.stdin.readline())['message']['content']
json.dump(dict(args=a, cwd=os.getcwd(), config=config, token=os.environ.get('ZOOK_WORKER_TOKEN', ''), prompt=prompt, pid=os.getpid()), open(os.path.join(here, 'run.json'), 'w'))
print(json.dumps(dict(event='init', init=dict(cwd=os.getcwd()))), flush=True)
if 'HANG' in prompt:
    import time; time.sleep(120)
if 'BUSY' in prompt: print(json.dumps(dict(event='result', result=dict(status='ERROR', error='UNAVAILABLE: No capacity available for model')))); sys.exit(3)
print(json.dumps(dict(event='result', result=dict(status='SUCCESS', response='agy says hi\\n', usage=dict(input_tokens=100, output_tokens=7, thinking_tokens=2, cache_read_tokens=40, total_tokens=107)))))
"""


def pathlib_read(path): return Path(path).read_bytes()


class Units(unittest.TestCase):
    def setUp(self):  # each test's own temporary folder: turn copies go there (zook-agy-turns)
        self.tmp = tempfile.mkdtemp(); self.patch = mock.patch.object(tempfile, 'tempdir', os.path.realpath(self.tmp)); self.patch.start()

    def tearDown(self):
        self.patch.stop(); subprocess.run(['/bin/rm', '-rf', self.tmp])

    def test_reply_and_usage(self):
        out = server.parse_cli_output('antigravity', json.dumps(dict(event='result', result=dict(status='SUCCESS', response='OK\n', usage=dict(input_tokens=10, output_tokens=2, cache_read_tokens=4)))), 'm')
        self.assertEqual((out['content'], out['usage']['input'], out['usage']['cachedInput'], out['usage']['output']), ('OK', 10, 4, 2))
        self.assertTrue(server.parse_cli_output('antigravity', json.dumps(dict(event='result', result=dict(status='ERROR', error='boom'))))['isError'])
        self.assertTrue(server.parse_cli_output('antigravity', 'not json')['unparsable'])
        # A later message in a conversation: the result counts every earlier one too, the finished steps only this one.
        lines = [dict(event='step_update', step_update=dict(step_index=6, state='ACTIVE', step_type='agent_response', text_delta='O')),
                 dict(event='step_update', step_update=dict(step_index=6, state='DONE', step_type='agent_response', usage=dict(input_tokens=309, output_tokens=13, cache_read_tokens=11406))),
                 dict(event='step_update', step_update=dict(step_index=7, state='DONE', step_type='tool')),
                 dict(event='step_update', step_update=dict(step_index=8, state='DONE', step_type='agent_response', usage=dict(input_tokens=10, output_tokens=2, cache_read_tokens=5))),
                 dict(event='result', result=dict(status='SUCCESS', response='OK', usage=dict(input_tokens=12296, output_tokens=196, cache_read_tokens=22154)))]
        u = server.parse_cli_output('antigravity', '\n'.join(json.dumps(l) for l in lines))['usage']
        self.assertEqual((u['input'], u['output'], u['cachedInput']), (319, 15, 11411))
        self.assertEqual(server.antigravity_error('the MCP server is unavailable'), '')

    def test_careful_runs_cannot_change_anything_and_credits_stay_off(self):
        s = server.antigravity_settings(False, 'workspace', False)
        self.assertFalse(s['useG1Credits'])
        for rule in ('write_file(*)', 'command(*)', 'execute_url(*)', 'read_url(*)'): self.assertIn(rule, s['permissions']['deny'])
        self.assertIn('mcp(zook/*)', s['permissions']['allow'])
        args = server.antigravity_args('agy', '', 'standard', False, True, 'full', '/x', True)
        self.assertEqual(args[args.index('--mode') + 1], 'plan'); self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertIn('--dangerously-skip-permissions', server.antigravity_args('agy', '', 'deep', True, False, 'full', '/x', True))
        self.assertIn('--sandbox', server.antigravity_args('agy', '', 'deep', True, False, 'workspace', '/x', True))
        self.assertEqual(server.antigravity_args('agy', 'm', 'deep', False, False, 'workspace', '/x', True)[-4:], ['--model', 'm', '--effort', 'high'])

    def test_a_planted_tool_config_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            work, chosen = Path(d) / 'w', Path(d) / 'c'; chosen.mkdir()
            for name in server.AGY_ROOTS: (work / name).mkdir(parents=True); (work / name / 'hooks.json').write_text('{}')
            server.prepare_antigravity_folder(work, 'workspace', work, 100)
            self.assertEqual(sorted(p.name for p in work.iterdir()), ['.agents']); self.assertEqual([p.name for p in (work / '.agents').iterdir()], ['mcp_config.json'])
            for name in server.AGY_ROOTS:
                (chosen / name).mkdir()
                with self.assertRaises(RuntimeError): server.prepare_antigravity_folder(work, 'folder', chosen, 100)
                (chosen / name).rmdir()
            server.prepare_antigravity_folder(work, 'folder', chosen, 100)

    def grants_store(self, d):
        store = server.Store(Path(d) / 'data'); store.data['groups'] = [dict(id='g1', messages=[], fileInfo={'key.txt': {'origName': 'credentials.json'}})]
        def upload(name, orig=None, data=b'%PDF'):
            uid = os.urandom(16).hex(); folder = store.dir / 'uploads' / uid; folder.mkdir(parents=True)
            (folder / 'file').write_bytes(data); meta = dict(id=uid, name=name, size=len(data), kind='file', **({'origName': orig} if orig else {}))
            (folder / 'meta.json').write_text(json.dumps(meta)); return meta
        return store, upload

    def rules_files(self, rules):
        return sorted({os.path.basename(r) for r in rules})

    def test_a_read_only_turn_may_read_only_its_own_copies(self):
        with tempfile.TemporaryDirectory() as d:
            store, upload = self.grants_store(d)
            mine, other, key, env = upload('報告 (2).pdf', data=b'mine'), upload('私聊.pdf'), upload('credentials.json'), upload('env', '.env')
            placed = server.place_attachments(store, 'b1', [mine, key, env]); server.place_attachments(store, 'b1', [other])
            shared = server.group_files_dir(store, 'g1'); shared.mkdir(parents=True)
            for name in ('預算.pdf', 'key.txt', 'hidden.pdf', 'a[1]*?.pdf'): (shared / name).write_bytes(b'%PDF')
            (store.dir / 'workspaces/b2').mkdir(); (store.dir / 'workspaces/b1/notes.txt').write_text('x')
            server.sync_group_files_in(store, 'g1', 'b1', {'hidden.pdf'})
            job = dict(id='j1', attachments=[str(x) for x in placed], attachmentIds=[mine['id'], key['id'], env['id']], groupFiles=True, groupId='g1')
            rules, note, blocked = server.agy_read_paths(store, 'b1', job)
            turn = Path(tempfile.gettempdir()) / 'zook-agy-turns/b1/j1'
            self.assertEqual(self.rules_files(rules), ['1-報告 _2_.pdf', '2-a_1___.pdf', '3-預算.pdf', '4-a_1___.pdf.txt', '5-預算.pdf.txt'])  # keys (by either name), hidden files and other chats left out; the shared PDFs' text versions (#240)
            self.assertTrue(all(r.startswith((str(turn), os.path.realpath(str(turn)))) for r in rules))  # never the folder, never the Bot's own copies
            self.assertFalse([r for r in rules if set(r) & set('()[]*?')])
            self.assertEqual((turn / '1-報告 _2_.pdf').read_bytes(), b'mine'); self.assertIn('報告 (2).pdf', note)
            s = server.antigravity_settings(False, 'workspace', False, rules, blocked)
            self.assertFalse([r for r in s['permissions']['allow'] if not r.startswith(('read_file(', 'mcp(zook'))])  # reading only
            for rule in ('write_file(*)', 'command(*)', 'execute_url(*)'): self.assertIn(rule, s['permissions']['deny'])
            # agy reads anything unless denied, and a deny wins: Zook's folders other than this Bot's workspace are closed.
            w = str(store.dir / 'workspaces')
            for place in (w + '/b1/attachments', w + '/b1/attachments/group-files', w + '/b2', str(store.dir / 'uploads'), str(store.dir / 'swarmr.json')):
                self.assertTrue([r for r in s['permissions']['deny'] if fnmatch.fnmatchcase(place, r[len('read_file('):-1])], place)
            for place in (w + '/b1/notes.txt', str(turn / '1-報告 _2_.pdf')):
                self.assertFalse([r for r in s['permissions']['deny'] if r.startswith('read_file(') and fnmatch.fnmatchcase(place, r[len('read_file('):-1])], place)
            self.assertNotIn('read_file', ' '.join(server.antigravity_settings(True, 'workspace', False)['permissions']['deny']))  # a turn that can write: unchanged
            server.agy_cleanup(store, 'b1', 'j1', True); self.assertFalse(turn.exists())

    def test_read_grants_ignore_what_a_bot_left_in_its_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            store, upload = self.grants_store(d)
            mine = upload('a.pdf', data=b'original'); placed = server.place_attachments(store, 'b1', [mine])
            placed[0].write_bytes(b'changed by a writable turn')
            job = dict(id='j2', attachments=[str(placed[0])], attachmentIds=[mine['id']])
            rules, _, _ = server.agy_read_paths(store, 'b1', job)
            self.assertEqual(placed[0].read_bytes(), b'changed by a writable turn')  # the Bot's own copy is left as it is
            self.assertEqual(pathlib_read(rules[0]), b'original')  # the turn reads the upload
            server.agy_cleanup(store, 'b1', 'j2', True)
            # A link in place of the turn folder: nothing is named.
            os.symlink(str(Path(d)), str(Path(tempfile.gettempdir()) / 'zook-agy-turns/b1/j3'))
            try: self.assertEqual(server.agy_read_paths(store, 'b1', dict(job, id='j3'))[:2], ([], ''))
            finally: os.unlink(str(Path(tempfile.gettempdir()) / 'zook-agy-turns/b1/j3'))

    def test_a_data_folder_with_brackets_still_gets_rules(self):
        with tempfile.TemporaryDirectory() as d:
            store, upload = self.grants_store(str(Path(d) / 'Zook (test)'))
            mine = upload('a.pdf'); server.place_attachments(store, 'b1', [mine])
            rules, _, blocked = server.agy_read_paths(store, 'b1', dict(id='j5', attachmentIds=[mine['id']]))
            self.assertEqual(self.rules_files(rules), ['1-a.pdf']); self.assertFalse([r for r in rules + blocked if set(r[10:-1]) & set('()')])
            self.assertTrue(rules[0].startswith(os.path.join(tempfile.gettempdir(), 'zook-agy-turns')))
            self.assertTrue([r for r in blocked if fnmatch.fnmatchcase(str(store.dir / 'workspaces/b1/attachments/x'), r[10:-1])])  # still closed
            server.agy_cleanup(store, 'b1', 'j5', True); self.assertFalse(os.path.exists(rules[0]))

    def test_this_turns_files_come_before_the_cap(self):
        with tempfile.TemporaryDirectory() as d:
            store, upload = self.grants_store(d)
            shared = server.group_files_dir(store, 'g1'); shared.mkdir(parents=True)
            for n in range(server.AGY_READ_MAX + 20): (shared / ('%03d.pdf' % n)).write_bytes(b'x')
            server.sync_group_files_in(store, 'g1', 'b1')
            mine = upload('z.pdf'); server.place_attachments(store, 'b1', [mine])
            rules, _, _ = server.agy_read_paths(store, 'b1', dict(id='j6', attachmentIds=[mine['id']], groupFiles=True, groupId='g1'))
            files = self.rules_files(rules); self.assertEqual(len(files), server.AGY_READ_MAX); self.assertIn('1-z.pdf', files)

    def test_a_check_copies_only_what_the_author_could_read(self):
        base = Path(tempfile.mkdtemp(dir='/private/tmp'))
        try:
            with tempfile.TemporaryDirectory() as d:
                store, upload = self.grants_store(d)
                (base / '企劃.pdf').write_bytes(b'%PDF-1'); (base / '.h').mkdir(); (base / '.h/a.pdf').write_bytes(b'%PDF')
                own = store.dir / 'workspaces/host/out'; own.mkdir(parents=True); (own / '草案.pdf').write_bytes(b'%PDF-2')
                server.group_files_dir(store, 'g1').mkdir(parents=True); (server.group_files_dir(store, 'g1') / 'shared.pdf').write_bytes(b'%PDF')
                said = '已存到 %s/企劃.pdf、%s/草案.pdf，另見 %s/.h/a.pdf、%s/shared.pdf' % (base, own, base, base)
                message = dict(id='m1', botId='host', content=said); group = store.data['groups'][0]; group['messages'].append(message)
                store.data['jobs'].append(dict(id='hj', messageId='m1', groupId='g1', botId='host', nativeAccess=['workspace', str(own.parent), 'auto', True]))
                def check(access):
                    store.data['jobs'][-1]['nativeAccess'] = access; job = dict(id='cj')
                    with store.lock: plan = server.named_check_plan(store, group, message)
                    return job, server.named_check_copy(store, 'g1', 'checker', job, plan)
                job, note = check(['workspace', str(own.parent), 'auto', True])
                self.assertEqual([Path(x).name.split('-', 1)[1] for x in job['attachments']], ['草案.pdf'])  # its own workspace only
                self.assertIn('企劃.pdf（路徑在範圍外）', note); self.assertNotIn('shared.pdf', note)
                job, note = check(['full', '/', 'auto', True])
                self.assertEqual(sorted(Path(x).name.split('-', 1)[1] for x in job['attachments']), ['企劃.pdf', '草案.pdf'])
                self.assertIn('a.pdf（隱藏檔', note)  # the same checks as a path the user attaches
                uploads = len(os.listdir(str(store.dir / 'uploads')))
                check(['full', '/', 'auto', True]); self.assertEqual(len(os.listdir(str(store.dir / 'uploads'))), uploads)  # not uploaded again
                (base / '企劃.pdf').write_bytes(b'%PDF-changed'); check(['full', '/', 'auto', True])
                self.assertEqual(len(os.listdir(str(store.dir / 'uploads'))), uploads + 1)
                job, note = check(['full', '/', 'auto', False])  # 謹慎: only its workspace
                self.assertIn('企劃.pdf（路徑在範圍外）', note)
        finally: subprocess.run(['/bin/rm', '-rf', str(base)])

    def test_a_member_the_host_gives_nothing_is_not_woken(self):
        bots = [dict(id='a', name='客服小幫手'), dict(id='b', name='總務小幫手'), dict(id='c', name='人資')]
        plan = '本次目標與產出：尾牙企劃\n- **客服小幫手**：本次沒有客服工作項目\n2. 總務小幫手：確認沒有遺漏的場地需求\n人資（Codex）：無'
        self.assertEqual(server.split_idle(plan, bots), {'a', 'c'})
        self.assertEqual(server.split_idle('客服小幫手：整理沒有回覆的客訴\n總務小幫手：無需額外工作。', bots), {'b'})
        with tempfile.TemporaryDirectory() as d:
            store, _ = self.grants_store(d); store.data['bots'] = bots; store.data['groups'][0].update(runId='r')
            fake = types.SimpleNamespace(store=store)
            steps = [dict(role='split_work', bots=['a', 'b']), dict(role='split_merge', bots=['c'])]
            left = server.GroupRuns._skip_idle(fake, 'g1', 'r', dict(job=dict(content=plan)), steps)
            self.assertEqual([s['bots'] for s in left], [['b'], ['c']]); self.assertIn('客服小幫手', store.data['groups'][0]['messages'][-1]['content'])
            self.assertEqual(server.GroupRuns._skip_idle(fake, 'g1', 'r', dict(job=dict(content='客服小幫手：無\n總務小幫手：無')), steps)[0]['role'], 'split_merge')

    def test_a_group_turn_whose_files_cannot_be_placed_safely_does_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            store, _ = self.grants_store(d)
            (store.dir / 'workspaces/b2').mkdir(parents=True); os.symlink(str(store.dir / 'workspaces/b2'), str(store.dir / 'workspaces/b1'))
            fake = types.SimpleNamespace(store=store, run_job=mock.Mock(), processes={})
            fake._group_stage_failed = lambda *a: server.GroupRuns._group_stage_failed(fake, *a)
            for staged in (True, False):
                job = dict(id='j%s' % staged, botId='b1', groupId='g1', messageId='m', status='running'); store.data['jobs'].append(job)
                turn = dict(bot=dict(id='b1', name='x'), job=job, provider='antigravity', prompt='', model='', skipFiles=set(), writable=False, staged=staged)
                server.GroupRuns._group_job(fake, 'g1', turn)
                self.assertEqual(job['status'], 'failed'); self.assertIn('工作資料夾', job['error'])
            fake.run_job.assert_not_called()

    def test_a_silent_antigravity_reply_is_stopped_sooner(self):
        self.assertEqual(server.agy_quiet('antigravity', 900), min(900, server.AGY_QUIET))
        self.assertEqual(server.agy_quiet('codex', 900), 900)
        self.assertIn('Antigravity', server.quiet_reason('antigravity', 300)); self.assertIn('5 分鐘', server.quiet_reason('antigravity', 300))

    def test_stopping_survives_a_group_that_refuses_the_signal(self):
        # macOS answers EPERM to killpg for a group whose leader ended but was not collected yet; stopping must not fail on it.
        proc = subprocess.Popen(['/bin/sleep', '30'], start_new_session=True)
        try:
            with mock.patch.object(server.os, 'killpg', side_effect=PermissionError(1, 'Operation not permitted')):
                server.terminate_tree(proc); server.kill_group(proc)
            self.assertEqual(proc.wait(timeout=5), -signal.SIGTERM)
            with mock.patch.object(server.os, 'killpg', side_effect=PermissionError(1, 'x')), mock.patch.object(server.os, 'kill') as kill:
                server.terminate_tree(proc)  # collected: its number is never signalled again
            kill.assert_not_called()
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()

    def test_a_refused_group_signal_still_reaches_the_helpers(self):
        proc = subprocess.Popen(['/bin/sh', '-c', '/bin/sleep 30 & wait'], start_new_session=True)
        try:
            end = time.time() + 5
            while not server.group_members(proc.pid) and time.time() < end: time.sleep(0.05)
            helper = server.group_members(proc.pid)[0]
            with mock.patch.object(server.os, 'killpg', side_effect=PermissionError(1, 'x')): self.assertTrue(server.signal_group(proc, signal.SIGKILL))
            proc.wait(timeout=5); end = time.time() + 5
            while time.time() < end:
                try: os.kill(helper, 0)
                except OSError: break
                time.sleep(0.05)
            else: self.fail('the helper was left running')
            self.assertFalse(server.group_alive(proc))
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()

    def test_one_agy_per_bot(self):
        def kept(key, kind='antigravity'):
            return server.LiveCli(key, ['/bin/sleep', '30'], tempfile.gettempdir(), dict(os.environ), 'm', 'live-%s-%s' % key, 't', kind)
        chat, other, group_bot, claude = kept(('b1', 'c1')), kept(('b1', 'c2')), kept(('b2', 'c1')), kept(('b1', 'c3'), 'claude')
        everyone = [chat, other, group_bot, claude]
        app = types.SimpleNamespace(lives={c.key: c for c in everyone}, live_ids={c.ident: c for c in everyone}, live_lock=threading.Lock())
        try:
            self.assertEqual(server.live_drop_bot(app, 'b1', {'chatId': 'c1'}), 1)  # its own conversation's kept agy may answer
            self.assertEqual(sorted(app.lives), [('b1', 'c1'), ('b1', 'c3'), ('b2', 'c1')]); self.assertFalse(other.alive())
            self.assertEqual(server.live_drop_bot(app, 'b1', {'chatId': 'c1', 'groupId': 'g'}), 1)  # a group turn: none is kept next to it
            self.assertFalse(chat.alive()); self.assertTrue(group_bot.alive()); self.assertTrue(claude.alive())
            self.assertNotIn(chat.ident, app.live_ids)
        finally:
            for c in everyone: c.close(wait=3)


    def test_a_stopped_agy_ends_before_the_next_one_starts(self):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d) / 'data')
            proc = subprocess.Popen(['/bin/sh', '-c', 'trap "" TERM; /bin/sleep 30 & wait'], start_new_session=True)  # slow to stop
            store.data['jobs'] += [dict(id='old', botId='b1', status='cancelled', runKind='antigravity'), dict(id='new', botId='b1', status='running')]
            app = types.SimpleNamespace(store=store, processes={'old': proc})
            began = time.monotonic()
            try:
                server.live_drop_bot(app, 'b1', dict(id='new', groupId='g'))
                self.assertFalse(server.group_alive(proc)); self.assertLess(time.monotonic() - began, 9)
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()

    def test_two_replies_of_one_bot_take_turns(self):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d) / 'data')
            store.data['jobs'] += [dict(id=x, botId='b1', status='running') for x in ('j1', 'j2', 'j3')]
            app = types.SimpleNamespace(store=store, processes={}); order = []
            server.agy_hold(app, 'b1', 'j1'); server.agy_hold(app, 'b1', 'j1')  # the same reply again (a group turn, then its run)
            later = threading.Thread(target=lambda: (server.agy_hold(app, 'b1', 'j2'), order.append('j2'))); later.start()
            time.sleep(0.8); self.assertEqual(order, []); self.assertTrue(later.is_alive())  # waits for the first
            server.agy_hold(app, 'b2', 'j3'); server.agy_release(app, 'j3')  # another Bot does not wait
            order.append('j1 done'); server.agy_release(app, 'j1'); later.join(5)
            self.assertEqual(order, ['j1 done', 'j2'])
            store.data['jobs'].append(dict(id='j4', botId='b1', status='cancelled'))
            with self.assertRaises(RuntimeError): server.agy_hold(app, 'b1', 'j4')  # stopped while waiting
            server.agy_release(app, 'j2')

    def test_closing_a_kept_agy_ends_it_and_its_helpers(self):
        cli = server.LiveCli(('b1', 'c1'), ['/bin/sh', '-c', 'trap "" TERM; /bin/sleep 30 & wait'], tempfile.gettempdir(), dict(os.environ), 'm', 'live-y', 't', 'antigravity')
        try:
            end = time.time() + 5
            while not server.group_members(cli.proc.pid) and time.time() < end: time.sleep(0.05)
            cli.close(wait=1)
            self.assertFalse(server.group_alive(cli.proc))
        finally:
            if cli.proc.poll() is None: cli.proc.kill(); cli.proc.wait()

    def test_a_kept_agy_that_no_longer_fits_is_ended_before_its_replacement(self):
        d = tempfile.gettempdir()
        cli = server.LiveCli(('b1', 'c1'), ['/bin/sleep', '30'], d, dict(os.environ), 'old-mark', 'live-x', 't', 'antigravity')
        app = types.SimpleNamespace(lives={cli.key: cli}, live_ids={cli.ident: cli}, live_lock=threading.Lock())
        try:
            args, env = ['agy', '--mode', 'plan'], {'A': '1'}
            cli.mark, cli.session = server.live_mark(args, d, env, 'user', server.agy_config('antigravity', d)), 's1'
            server.live_settle(app, dict(botId='b1', chatId='c1'), 'antigravity', args, d, env, 's1'); self.assertTrue(cli.alive())  # it fits: kept
            server.live_settle(app, dict(botId='b1', chatId='c1'), 'antigravity', ['agy'], d, env, 's1')  # 先規劃 switched off
            self.assertIsNotNone(cli.proc.poll()); self.assertEqual(app.lives, {})  # ended, not merely asked to end
        finally: cli.close(wait=3)


class Chat(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/agy'; cli.write_text(AGY); cli.chmod(0o755); (self.root / 'bin/usage.json').write_text(json.dumps(USAGE))
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_CLI_DIRS=str(self.root / 'bin'), ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_AGY_QUIET='2')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.assertEqual(self.req('POST', '/api/accounts/antigravity/add', {})[0], 200)
        self.bot = self.req('POST', '/api/bots', {'name': 'A', 'provider': 'antigravity'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30); c.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d)

    def ask(self, **more):
        status, sent = self.req('POST', '/api/chat', dict({'botId': self.bot['id'], 'content': 'hello'}, **more)); self.assertEqual(status, 202, sent)
        end = time.time() + 15
        while time.time() < end:
            job = self.req('GET', '/api/jobs/' + sent['jobId'])[1]
            if job['status'] != 'running': return job
            time.sleep(0.2)
        self.fail('no reply')

    def test_reply_tools_cleanup_and_quota(self):
        job = self.ask()
        self.assertEqual((job['status'], job['content'], job['usage']['provider'], job['usage']['input']), ('completed', 'agy says hi', 'antigravity', 100))
        run = json.loads((self.root / 'bin/run.json').read_text())
        self.assertEqual(run['cwd'], str((self.root / 'data/workspaces' / self.bot['id']).resolve()))
        self.assertIn('tool_server.py', run['config']); self.assertTrue(run['token']); self.assertNotIn(run['token'], run['config'])
        self.assertNotIn(run['token'], ' '.join(run['args'])); self.assertIn('hello', run['prompt']); self.assertNotIn('hello', ' '.join(run['args']))  # the conversation is not on the command line
        self.assertFalse((self.root / 'data/workspaces' / self.bot['id'] / '.agents').exists())
        card = next(p for p in self.req('GET', '/api/quota')[1]['providers'] if p['id'] == 'antigravity')
        self.assertEqual((card['status'], card['noQuotaApi']), ('logged_in', False))
        self.assertEqual([(w['label'], w['usedPercent']) for w in card['quota']['windows']], [('Gemini 模型 · 每週', 25.0), ('Claude 與 GPT 模型 · 每週', 0.0)])
        self.assertEqual(self.req('GET', '/api/models?provider=antigravity')[1]['models'][0]['id'], 'gemini-3.8-flash-low')

    def test_plan_is_read_only_and_errors_are_explained(self):
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'bypass'})
        self.ask(plan=True)
        args = json.loads((self.root / 'bin/run.json').read_text())['args']
        self.assertEqual(args[args.index('--mode') + 1], 'plan'); self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertIn('太忙', self.ask(content='BUSY')['error'])

    def upload(self, name, data):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        c.request('POST', '/api/uploads', data, {'Authorization': 'Bearer ' + self.token, 'X-File-Name': quote(name), 'Content-Type': 'application/octet-stream'})
        r = c.getresponse(); d = r.read(); c.close(); self.assertEqual(r.status, 201, d); return json.loads(d)

    def test_a_read_only_turn_may_read_what_was_attached(self):
        doc = self.upload('報告.pdf', b'%PDF-1.4')
        self.ask(plan=True, attachments=[doc['id']])
        args = json.loads((self.root / 'bin/run.json').read_text())['args']
        rules = json.loads(args[args.index('--settings') + 1])['permissions']
        folder = (self.root / 'data/workspaces' / self.bot['id'] / 'attachments').resolve()
        self.assertNotIn('read_file(%s)' % folder, rules['allow'])
        self.assertTrue([r for r in rules['allow'] if r.startswith('read_file(') and r.endswith('-報告.pdf)')])
        self.assertIn('write_file(*)', rules['deny']); self.assertIn('command(*)', rules['deny'])
        key = self.upload('credentials.json', b'{}')
        self.ask(plan=True, attachments=[key['id']])
        args = json.loads((self.root / 'bin/run.json').read_text())['args']
        self.assertFalse([r for r in json.loads(args[args.index('--settings') + 1])['permissions']['allow'] if 'credentials' in r])  # never past Zook's key check
        self.req('PATCH', '/api/bots/' + self.bot['id'], {'permissionMode': 'bypass'}); self.ask(attachments=[doc['id']])
        args = json.loads((self.root / 'bin/run.json').read_text())['args']
        self.assertFalse([r for r in json.loads(args[args.index('--settings') + 1])['permissions']['allow'] if r.startswith('read_file(')])  # a turn that can write

    def test_a_reply_that_prints_nothing_is_stopped_and_explained(self):
        job = self.ask(content='HANG')
        self.assertEqual(job['status'], 'failed'); self.assertIn('沒有任何輸出', job['error'])
        pid = json.loads((self.root / 'bin/run.json').read_text())['pid']
        end = time.time() + 5
        while time.time() < end:
            try: os.kill(pid, 0)
            except OSError: break
            time.sleep(0.1)
        else: self.fail('agy was left running')


if __name__ == '__main__': unittest.main()
