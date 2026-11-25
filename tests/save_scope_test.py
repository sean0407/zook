# -*- coding: utf-8 -*-
"""Saving outside what a reply may reach (巡檢 #86 #88): a group member was stopped writing /tmp with only 「系統說它無法判讀」 while
its host saved there; a single chat stopped at 「不在可動資料夾範圍」. The same Bot is held the same way as host or member, and a
refusal says where it was stopped, why, where to save instead, and what the user can do. Nothing here widens what a Bot may reach."""
import importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
sys.path.insert(0, str(ROOT / 'backend'))
import zook_gate  # noqa: E402


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_save_scope', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class RefusalSaysWhyTest(unittest.TestCase):
    def tearDown(self): zook_gate._CWD[0] = os.getcwd()

    def held(self, tmp, why, **more):
        return mock.patch.dict(os.environ, dict({'ZOOK_GATE_ROOTS': json.dumps([tmp]), 'ZOOK_GATE_SHELL': '1', 'ZOOK_GATE_WHY': why,
                                                 'ZOOK_GATE_SAVE': tmp + '/chat-files/c1'}, **more))

    def test_a_path_outside_says_where_why_and_what_to_do(self):
        with tempfile.TemporaryDirectory() as tmp, self.held(tmp, 'probe'):
            allowed, why = zook_gate.decide('Bash', {'command': 'cp 報表.xlsx /tmp/hr/報表.xlsx'}, home=tmp)
            self.assertFalse(allowed)
            self.assertIn('/tmp/hr/報表.xlsx', why)                 # where it was stopped
            self.assertIn('安全檢查', why); self.assertIn('下一則', why)  # why, and that it is only this reply
            self.assertIn(tmp + '/chat-files/c1', why)              # where it can save instead
            self.assertIn('告訴使用者', why)
            self.assertNotIn('（', why.split('不在')[0][-3:])         # never 「（無法判讀的指令） 不在裡面」
        with tempfile.TemporaryDirectory() as tmp, self.held(tmp, 'workspace'):
            allowed, why = zook_gate.decide('Write', {'file_path': '/tmp/hr/報表.xlsx', 'content': 'x'}, home=tmp)
            self.assertFalse(allowed)
            for word in ('只限 Bot 工作區', '編輯 Bot', '存取範圍', '使用者決定'):
                self.assertIn(word, why)
        with tempfile.TemporaryDirectory() as tmp, self.held(tmp, 'folder'):
            why = zook_gate.decide('Read', {'file_path': os.path.expanduser('~/Desktop/a.xlsx')}, home=tmp)[1]
            self.assertIn('指定資料夾', why); self.assertIn('編輯 Bot', why)

    def test_a_command_that_cannot_be_read_says_so_plainly(self):
        with tempfile.TemporaryDirectory() as tmp, self.held(tmp, 'probe'):
            allowed, why = zook_gate.decide('Bash', {'command': 'd=$(mktemp -d) && python3 make.py "$d"'}, home=tmp)
            self.assertFalse(allowed)
            self.assertNotIn('（無法判讀的指令） 不在裡面', why)
            self.assertIn('看不出', why); self.assertIn('完整路徑', why); self.assertIn('mktemp', why)
            self.assertIn(tmp + '/chat-files/c1', why)

    def test_a_read_only_reply_says_it_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'ZOOK_GATE_ROOTS': json.dumps([tmp + '/a.pdf']), 'ZOOK_GATE_DEFER': '1', 'ZOOK_GATE_WHY': 'plan'}):
            why = zook_gate.decide('Write', {'file_path': '/tmp/x.txt', 'content': 'x'}, home=tmp)[1]
            self.assertIn('只能讀', why)

    def test_without_a_reason_it_still_reads_plainly(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'ZOOK_GATE_ROOTS': json.dumps([tmp]), 'ZOOK_GATE_SHELL': '1'}):
            os.environ.pop('ZOOK_GATE_WHY', None); os.environ.pop('ZOOK_GATE_SAVE', None)
            allowed, why = zook_gate.decide('Bash', {'command': 'cp a /tmp/b'}, home=tmp)
            self.assertFalse(allowed); self.assertIn('/tmp/b', why); self.assertIn('告訴使用者', why)
        with tempfile.TemporaryDirectory() as tmp, self.held(tmp, 'probe'):  # inside is still allowed, as before
            self.assertTrue(zook_gate.decide('Bash', {'command': 'python3 make.py > out.csv'}, home=tmp)[0])


class SameBotSameRoomTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.store = self.m.Store(self.root / 'data')

    def tearDown(self): self.temp.cleanup()

    def env_for(self, job, scope, tools=('Read', 'Write', 'Bash')):
        work = self.store.dir / 'workspaces' / 'b1'; work.mkdir(parents=True, exist_ok=True)
        env = {}; self.m.claude_gate_env(self.store, env, list(tools), scope, work, work, job.get('attachments') or [], 'b1' if job.get('groupFiles') else None, job=job)
        return env, work

    def test_host_and_member_are_held_the_same_way(self):
        host = dict(id='j1', botId='b1', groupId='g1', groupFiles=True, gateProbe=True)
        member = dict(id='j2', botId='b1', groupId='g1', groupFiles=True, gateProbe=True, taskRole='worker')
        a, work = self.env_for(host, 'workspace'); b, _ = self.env_for(member, 'workspace')
        keys = ('ZOOK_GATE_ROOTS', 'ZOOK_GATE_SHELL', 'ZOOK_GATE_WHY', 'ZOOK_GATE_SAVE')
        self.assertEqual([a.get(k) for k in keys], [b.get(k) for k in keys])
        self.assertEqual(a['ZOOK_GATE_WHY'], 'probe')
        self.assertEqual(a['ZOOK_GATE_SAVE'], str(self.m.group_copy_folder(self.store, 'b1')))  # the group's files: inside what it may reach
        self.assertTrue(zook_gate._under(a['ZOOK_GATE_SAVE'], json.loads(a['ZOOK_GATE_ROOTS'])))

    def test_a_single_chat_saves_in_its_conversation_folder(self):
        env, work = self.env_for(dict(id='j3', botId='b1', chatId='c9'), 'workspace')
        self.assertEqual(env['ZOOK_GATE_SAVE'], str(self.m.chat_folder(self.store, 'b1', 'c9', make=False)))
        self.assertEqual(env['ZOOK_GATE_WHY'], 'workspace')
        self.assertTrue(zook_gate._under(env['ZOOK_GATE_SAVE'], json.loads(env['ZOOK_GATE_ROOTS'])))
        env, _ = self.env_for(dict(id='j4', botId='b1', chatId='c9', plan=True), 'workspace', tools=())
        self.assertEqual(env['ZOOK_GATE_WHY'], 'plan')
        env, _ = self.env_for(dict(id='j5', botId='b1', chatId='c9'), 'full')
        self.assertNotIn('ZOOK_GATE_ROOTS', env); self.assertNotIn('ZOOK_GATE_WHY', env)  # the whole Mac: nothing held, nothing to explain

    def test_the_prompt_says_where_to_save_and_what_the_user_can_do(self):
        m = self.m
        note = m.scope_save_note('workspace', Path('/w'), '/w/chat-files/c1', dict(chatId='c1'), 'claude')
        for word in ('/w/chat-files/c1', '編輯 Bot', '存取範圍', '使用者決定', 'mktemp'):
            self.assertIn(word, note)
        probe = m.scope_save_note('workspace', Path('/w'), '/w/chat-files/c1', dict(chatId='c1', gateProbe=True), 'claude')
        self.assertIn('下一則', probe); self.assertNotIn('編輯 Bot', probe)
        self.assertNotIn('mktemp', m.scope_save_note('workspace', Path('/w'), '/w', {}, 'codex'))  # Codex's own sandbox lets it use /tmp
        self.assertEqual(m.scope_save_note('full', Path.home(), '/w', {}, 'claude'), '')


    def test_the_whole_mac_note_keeps_its_pair(self):
        # review: a note put between 「if native」 and its 「else」 would tell a whole-Mac Bot to use only zook tools
        lines = (ROOT / 'backend/zook/app.py').read_text(encoding='utf-8').splitlines()
        at = next(i for i, x in enumerate(lines) if x.strip().startswith("if native: prompt += '\\n工具說明：'"))
        self.assertTrue(lines[at + 1].strip().startswith("else: prompt += '\\n工具說明：檔案讀寫與其他動作請使用 zook 工具"))

if __name__ == '__main__':
    unittest.main()
