# -*- coding: utf-8 -*-
import importlib.util, json, pathlib, unittest

spec = importlib.util.spec_from_file_location('zook_native_actions', pathlib.Path(__file__).parents[1] / 'backend/server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
L = lambda *objs: '\n'.join(json.dumps(o, ensure_ascii=False) for o in objs)


class NativeActionsTest(unittest.TestCase):
    def test_codex_commands_and_file_changes(self):
        out = m.parse_cli_output('codex', L(
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': "/bin/zsh -lc 'printf hi > a.txt'", 'exit_code': 0}},
            {'type': 'item.completed', 'item': {'type': 'file_change', 'changes': [{'path': '/w/notes.md', 'kind': 'add'}]}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '好了'}}))
        self.assertEqual(out['content'], '好了')
        self.assertEqual(out['web'], [dict(name='native_command', category='code', arguments={'command': 'printf hi > a.txt'}),
                                      dict(name='native_write', category='internal', arguments={'path': '/w/notes.md'})])

    def test_claude_edits_listed_reads_not(self):
        out = m.parse_cli_output('claude', L(
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read', 'input': {'file_path': '/w/a.txt'}},
                                                          {'type': 'tool_use', 'name': 'Write', 'input': {'file_path': '/w/b.txt', 'content': 'x'}}]}},
            {'type': 'result', 'result': '完成', 'is_error': False}))
        self.assertEqual(out['web'], [dict(name='native_read', category='read', arguments={'path': '/w/a.txt'}), dict(name='native_write', category='internal', arguments={'path': '/w/b.txt'})])
        self.assertEqual([w for w in out['web'] if w['category'] not in ('read', 'external_read')], [out['web'][1]])  # only the write counts as having acted

    def test_grok_streaming_keeps_final_text_and_actions(self):
        out = m.parse_cli_output('grok', L(
            {'type': 'text', 'data': '我來建立檔案。'},
            {'type': 'tool_call', 'toolName': 'write', 'kind': 'write', 'rawInput': {'file_path': '/w/a.txt', 'content': 'hi'}},
            {'type': 'tool_call_update', 'status': 'completed'},
            {'type': 'text', 'data': '已'}, {'type': 'text', 'data': '建立。'},
            {'type': 'end', 'stopReason': 'end_turn', 'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 2},
             'total_cost_usd': 0.01, 'modelUsage': {'grok-x': {}}}))
        self.assertEqual(out['content'], '已建立。')
        self.assertEqual(out['web'], [dict(name='native_write', category='internal', arguments={'path': '/w/a.txt'})])
        self.assertEqual((out['usage']['input'], out['usage']['output'], out['usage']['model']), (12, 5, 'grok-x'))

    def test_codex_profile_limits_reads_and_writes_to_the_workspace(self):
        args = m.codex_permission_args('/opt/tools/bin/codex')
        self.assertEqual(args[:2], ['-c', 'default_permissions="zook"'])
        self.assertIn('":minimal"="read"', args[3]); self.assertIn('":project_roots"="write"', args[3]); self.assertIn('"/opt/tools/bin"="read"', args[3])
        self.assertNotIn('workspace-write', ' '.join(args)); self.assertNotIn('danger', ' '.join(args))

    def test_grok_single_json_document_still_works(self):
        out = m.parse_cli_output('grok', json.dumps({'text': 'hi', 'usage': {'input_tokens': 1, 'output_tokens': 1}}, indent=2))
        self.assertEqual(out['content'], 'hi')


if __name__ == '__main__': unittest.main()
