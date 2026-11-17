import importlib.util
from pathlib import Path
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'backend'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


server = load('zook_team_server', 'server.py')
runtime = load('zook_team_runtime', 'runtime.py')


class TeamToolsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = server.Store(Path(self.temp.name) / 'data')
        self.app = server.App(('127.0.0.1', 0), self.store, self.temp.name, 'token')
        self.admin = next(b for b in self.store.data['bots'] if b['name'] == '管理員')
        self.other = next(b for b in self.store.data['bots'] if b['name'] == '工程師')

    def tearDown(self):
        self.app.server_close(); self.temp.cleanup()

    def tools(self, bot):
        return {schema['name']: (handler, approval) for schema, handler, approval in self.app.app_tools(bot, runtime)}

    def test_migration_marks_chief_of_staff(self):
        self.assertTrue(self.admin['isAdmin'])
        self.assertFalse(self.other['isAdmin'])
        self.assertEqual(self.store.data['settings']['disabledSkills'], [])

    def test_only_admin_gets_team_tools(self):
        self.assertEqual(set(self.tools(self.other)), {'zook_remember'})
        tools = self.tools(self.admin)
        self.assertEqual(set(tools), {'zook_remember', 'zook_list_team', 'zook_create_bot', 'zook_create_group', 'zook_start_group_discussion'})
        self.assertFalse(tools['zook_list_team'][1])
        self.assertTrue(all(tools[n][1] for n in ('zook_create_bot', 'zook_create_group', 'zook_start_group_discussion')))

    def test_create_bot_group_and_kickoff(self):
        tools = self.tools(self.admin)
        tools['zook_create_bot'][0]({'name': '文案', 'instructions': '寫行銷文案'})
        with self.assertRaises(RuntimeError): tools['zook_create_bot'][0]({'name': '文案', 'instructions': 'dup'})
        tools['zook_create_group'][0]({'name': '行銷組', 'bot_names': ['文案', '研究助手']})
        with self.assertRaises(RuntimeError): tools['zook_create_group'][0]({'bot_names': ['文案', '不存在']})
        group = next(g for g in self.store.data['groups'] if g['name'] == '行銷組')
        self.assertEqual(len(group['botIds']), 2)
        team = tools['zook_list_team'][0]({})
        self.assertIn('文案', [b['name'] for b in team['bots']])
        self.assertEqual(team['groups'][0]['members'], ['文案', '研究助手'])
        self.app.start_group = lambda g, targets, broadcast: (g.update(status='running'), 'run')[1]
        tools['zook_start_group_discussion'][0]({'group_name': '行銷組', 'message': '@文案 寫標語'})
        self.assertEqual(group['messages'][-1]['author'], '管理員')
        with self.assertRaises(RuntimeError): tools['zook_start_group_discussion'][0]({'group_name': '行銷組', 'message': 'again'})

    def test_memory_scopes_and_prompt(self):
        remember = self.tools(self.other)['zook_remember'][0]
        self.assertTrue(remember({'content': '使用者偏好繁體中文', 'scope': 'shared'})['saved'])
        self.assertFalse(remember({'content': '使用者偏好繁體中文', 'scope': 'shared'})['saved'])
        remember({'content': '工程師專用：用 Python 3.9'})
        with self.assertRaises(RuntimeError): remember({'content': 'x', 'scope': 'team'})
        self.assertIn('偏好繁體中文', server.memory_block(self.store, self.admin))
        self.assertNotIn('Python 3.9', server.memory_block(self.store, self.admin))
        self.assertIn('Python 3.9', server.memory_block(self.store, self.other))
        group = dict(id='g', name='百分比 100%', botIds=[self.admin['id'], self.other['id']], messages=[])
        remember({'content': '進度 50% 完成', 'scope': 'shared'})
        self.assertIn('50%', server.group_prompt(self.store, group, self.other, False))

    def test_persona_and_isolation_in_prompts(self):
        self.other['persona'] = '說話直接、喜歡用比喻的資深工程師。'
        self.other['instructions'] = '負責程式審查。'
        block = server.identity_block(self.other)
        self.assertTrue(block.startswith('你是 工程師。'))
        self.assertIn('【人格】\n說話直接、喜歡用比喻的資深工程師。', block)
        self.assertIn('【工作指示】\n負責程式審查。', block)
        self.assertIn('AGENTS.md、CLAUDE.md', block)
        self.assertIn('不要提到內部工具名稱', block)
        self.assertRegex(block, r'現在時間：\d{4}-\d{2}-\d{2} \d{2}:\d{2}')
        self.assertIn('你沒有上網功能', block)
        self.store.data['settings']['webSearch'] = True
        self.assertIn('註明來源網站與資料時間', server.identity_block(self.other))
        self.assertNotIn('【人格】', server.identity_block(self.admin))  # empty persona adds nothing
        group = dict(id='g', name='審查 100%', botIds=[self.admin['id'], self.other['id']], messages=[])
        prompt = server.group_prompt(self.store, group, self.other, False)
        self.assertIn('【人格】', prompt); self.assertIn('群組「審查 100%」', prompt)
        self.assertIn('工程師：說話直接', prompt)  # roster uses the persona summary
        tools = self.tools(self.admin)
        tools['zook_create_bot'][0]({'name': '詩人', 'persona': '浪漫、愛押韻', 'instructions': '寫短詩'})
        self.assertEqual(next(b for b in self.store.data['bots'] if b['name'] == '詩人')['persona'], '浪漫、愛押韻')

    def test_shared_skills_respect_disabled_list(self):
        inventory = {'skills': [{'id': 'a'}, {'id': 'b'}]}
        self.assertEqual(server.shared_skill_ids(self.store, inventory), ['a', 'b'])
        self.store.data['settings']['disabledSkills'] = ['b']
        self.assertEqual(server.shared_skill_ids(self.store, inventory), ['a'])


class ExtraToolBrokerTest(unittest.TestCase):
    def test_extra_tool_requires_approval_and_records_events(self):
        events, decisions = [], []
        ran = []
        schema = runtime._schema('zook_demo_write', 'demo', {'value': {'type': 'string'}}, ['value'], False)
        with tempfile.TemporaryDirectory() as directory:
            session = runtime.RuntimeSession([], [], False, directory, lambda *a: decisions.append(a) or False, events.append,
                                             inventory={'skills': [], 'mcp': [], '_private': {}}, extra_tools=[(schema, lambda a: ran.append(a) or 'ok', True)])
            self.assertIn('zook_demo_write', [t['name'] for t in session.tools()])
            self.assertTrue(session.call('zook_demo_write', {'value': 'x'})['isError'])
            self.assertEqual(ran, [])
            self.assertEqual(len(decisions), 1)
            session.approval_callback = lambda *a: True
            self.assertFalse(session.call('zook_demo_write', {'value': 'y'}).get('isError'))
            self.assertEqual(ran, [{'value': 'y'}])
            self.assertTrue(session.call('zook_demo_write', {'other': 'z'})['isError'])
            self.assertIn('denied', [e['status'] for e in events])
            session.close()


if __name__ == '__main__': unittest.main()
