# -*- coding: utf-8 -*-
"""queue #130, #223②③⑤: the task board says why work stopped and what happens next; small group things.

#130: when the host does not finish a turn, the chat says why (the reply's own error) and what Zook does next; when the run
stops by itself, the reason is kept on the run (stopWhy) so the board's 「下一步」 and a member's 「已停止回覆」 can say it.
#223②: a group set to 自動 while the task engine is off is not quietly saved as 自由 when the user edits something else.
#223③: deleting a group says its task board goes too.
#223⑤: a group name that is too long says the limit (100) instead of 「名稱無效」."""
import importlib.util, re, sys, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'
sys.path.insert(0, str(ROOT / 'tests'))
import task_engine_test as base  # noqa: E402


def source(name): return (JS / name).read_text(encoding='utf-8')


class HostMissSaysWhy(base.TaskEngineTest):
    def test_a_host_that_fails_says_why_and_the_stop_is_kept(self):
        self.engine()
        self.rules([{'match': base.PLAN, 'crash': True}])
        status, body = self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '請大家分工完成三件事', 'mode': 'auto'})
        self.assertEqual(status, 202, body)
        group = self.wait_group(60)
        notes = [m['content'] for m in group['messages'] if m.get('role') == 'system']
        missed = [x for x in notes if x.startswith('主持人沒有完成這一輪')]
        self.assertTrue(missed, notes)
        self.assertNotEqual(missed[0], '主持人沒有完成這一輪。')  # a reason and what happens next, not the bare line
        self.assertRegex(missed[0], r'主持人沒有完成這一輪：.+。')
        self.assertIn('在下方再送一次訊息', missed[0])  # nothing planned: the run ends, Zook does not promise another try
        self.assertEqual(group['taskRun']['status'], 'done')

    def test_a_second_miss_stops_and_keeps_the_reason(self):
        self.engine()
        self.rules([{'match': base.PLAN, 'calls': [base.create(1, '甲')], 'reply': '分好了'}, {'match': '=== 工作', 'calls': [base.done()], 'reply': '好了'},
                    {'match': base.WAKE, 'crash': True}])
        status, body = self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '請大家分工完成三件事', 'mode': 'auto'})
        self.assertEqual(status, 202, body)
        group = self.wait_group(60)
        notes = [m['content'] for m in group['messages'] if m.get('role') == 'system']
        missed = [x for x in notes if x.startswith('主持人沒有完成這一輪')]
        run = group['taskRun']
        self.assertEqual(run['status'], 'stopped', notes)
        self.assertEqual(run.get('stopWhy'), '主持人連續兩次沒有完成，任務先停在這裡。')
        self.assertIn(run['stopWhy'], notes)
        self.assertEqual(len(missed), 2, notes)
        self.assertIn('Zook 會再請他一次', missed[0]); self.assertNotIn('再請他一次', missed[1])


for _name in [n for n in dir(base.TaskEngineTest) if n.startswith('test_')]: setattr(HostMissSaysWhy, _name, None)  # only this file's own test runs here


class StopWhyKept(unittest.TestCase):
    def test_user_stop_and_book_check(self):
        module = base.load()
        run = dict(id='r1', status='running', origin='user', hostId='h', tasks=[])

        class Store:
            def find(self, kind, x): return None
            def chat_touch(self, x): pass
        group = dict(id='g', messages=[], taskRun=run)
        module.task_stop(Store(), group)
        self.assertEqual(run['stopWhy'], '你按了停止。')
        self.assertTrue(module.task_run_ok(run))
        self.assertFalse(module.task_run_ok(dict(run, stopWhy=['x'])))  # a file's odd value is dropped


class BoardWords(unittest.TestCase):
    def test_board_and_member_reply_use_the_reason(self):
        tasks, chat = source('41-tasks.js'), source('10-chat.js')
        self.assertIn('run.stopWhy', tasks)
        self.assertIn('stopWhy', chat)  # a member's 「已停止回覆」 in a stopped run says why

    def test_auto_group_kept_while_engine_off(self):
        forms, groups = source('50-forms.js'), source('35-groups.js')
        self.assertIn('keepAuto', forms)
        self.assertIn('任務引擎已關閉', groups)

    def test_delete_says_the_board_goes(self):
        actions = source('40-actions.js')
        line = next(x for x in actions.splitlines() if '刪除這個群組？' in x)
        self.assertIn('任務板', line)


class NameTooLong(unittest.TestCase):
    def test_says_the_limit(self):
        module = base.load()

        class Store:
            data = {'settings': {}}
            def find(self, kind, x): return {'id': x, 'name': 'B' + x}
        group = dict(id='g', botIds=['a', 'b'], name='x')
        with self.assertRaises(ValueError) as caught:
            module.set_group_fields(Store(), group, {'name': '長' * 101})
        self.assertIn('100', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
