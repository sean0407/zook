# -*- coding: utf-8 -*-
"""What a member did for each of its turns in a group (Skills, connectors, tools, pages read, its thinking) shows in its own
conversation list, while the group gets what it concluded."""
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_group_work', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class GroupWorkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def test_codex_thinking_is_kept(self):
        lines = [{'type': 'item.completed', 'item': {'type': 'reasoning', 'text': '**比較兩條路線**\n先看成本，再看法規。'}},
                 {'type': 'item.completed', 'item': {'type': 'web_search', 'query': '台灣 化粧品 廣告 規範'}},
                 {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '結論：走路線 A。'}}]
        out = self.m.parse_cli_output('codex', '\n'.join(json.dumps(x, ensure_ascii=False) for x in lines))
        self.assertEqual(out['content'], '結論：走路線 A。')
        self.assertEqual(out['thinking'], ['比較兩條路線 先看成本，再看法規。'])
        self.assertEqual([w['name'] for w in out['web']], ['web_search'])

    def test_claude_thinking_reads_and_skills_are_kept(self):
        blocks = [{'type': 'thinking', 'thinking': '使用者要的是成本比較。'}, {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': '/w/報價.md'}},
                  {'type': 'tool_use', 'name': 'Grep', 'input': {'pattern': '定價', 'path': '/w'}}, {'type': 'tool_use', 'name': 'Skill', 'input': {'skill': 'pptx'}},
                  {'type': 'tool_use', 'name': 'WebFetch', 'input': {'url': 'https://example.com/rule'}}]
        lines = [{'type': 'assistant', 'message': {'content': blocks}}, {'type': 'result', 'result': '完成', 'is_error': False}]
        out = self.m.parse_cli_output('claude', '\n'.join(json.dumps(x, ensure_ascii=False) for x in lines))
        self.assertEqual(out['thinking'], ['使用者要的是成本比較。'])
        self.assertEqual([(w['name'], w.get('category')) for w in out['web']], [('native_read', 'read'), ('native_read', 'read'), ('native_skill', 'read'), ('web_fetch', None)])
        self.assertEqual(out['web'][0]['arguments'], {'path': '/w/報價.md'}); self.assertEqual(out['web'][2]['arguments'], {'name': 'pptx'})

    def test_thinking_is_capped(self):
        lines = [{'type': 'item.completed', 'item': {'type': 'reasoning', 'text': '想' * 5000}} for _ in range(10)]
        thinking = self.m.parse_cli_output('codex', '\n'.join(json.dumps(x, ensure_ascii=False) for x in lines))['thinking']
        self.assertLessEqual(sum(len(t) for t in thinking), 8000); self.assertLessEqual(max(len(t) for t in thinking), 2001)

    def test_member_turns_carry_their_work_and_the_window_state_does_not(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        store = self.m.Store(Path(temp.name) / 'data')
        group = dict(id='g', name='團隊', botIds=['b1'], messages=[dict(id='u1', role='user', content='請比較路線'),
                     dict(id='a1', role='assistant', botId='b1', content='路線 A 較好', status='completed')])
        calls = [dict(id='c1', name='zook_read_skill', arguments={'skill_id': 's'}, status='completed'), dict(id='c2', name='web_search', arguments={'query': 'q'}, status='completed')]
        store.data['jobs'].append(dict(id='j1', botId='b1', groupId='g', messageId='a1', status='completed', toolCalls=calls, thinking=['先比成本'], createdAt='2026-11-21T10:00:00+08:00'))
        turn = self.m.page_group_messages(group, {'member': ['b1']}, store)['turns'][0]
        self.assertEqual(turn['work'], dict(thinking=['先比成本'], calls=calls))
        self.assertEqual(turn['asked']['content'], '請比較路線')
        self.assertNotIn('thinking', self.m.state_view(store)['jobs'][0])  # it is fetched with the member's work only
        self.assertNotIn('thinking', self.m.job_view(store.data['jobs'][0]))


if __name__ == '__main__': unittest.main()
