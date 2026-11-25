# -*- coding: utf-8 -*-
"""#94: 插話 during a 任務 goes to the host at once (decided by the user: 即時插入), also while a result waits for 「接受結果」.
A question is not an acceptance: the card stays until the user presses it."""
import sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import task_engine_test as base
from task_engine_test import PLAN, WAKE, SUMMARY, create, done
from task_order_test import after

ASKED = '使用者在任務進行中說的話'


class TaskInterjectTest(base.TaskEngineTest):
    for _name in [n for n in dir(base.TaskEngineTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def until(self, test, what, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            group = self.req('GET', '/api/groups/' + self.group['id'])[1]['group']
            if (group.get('taskRun') or {}).get('awaitingConfirm'): self.confirm(group)
            if test(group): return group
            time.sleep(0.1)
        self.fail(what)

    def test_a_question_while_a_result_waits_is_answered_by_the_host_now(self):
        self.engine(); self.autoaccept = False
        self.rules([{'match': ASKED, 'reply': '含稅，報價單第二頁有寫。'}, {'match': PLAN, 'calls': [create(1, '甲'), after(2, '乙', ['1'])], 'reply': '分好了'},
                    {'match': '=== 工作', 'calls': [done()]}, {'match': WAKE, 'reply': SUMMARY}])
        self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '做報價', 'mode': 'auto'})
        group = self.until(lambda g: ((g.get('taskRun') or {}).get('tasks') or [{}])[0].get('status') == 'review', 'no result waited for the user')
        status, body = self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '這份報價含稅嗎？'})
        self.assertEqual(status, 202, body)
        self.assertEqual((body['interjected'], body['queued'], body['waiting'], body['to']), (True, False, False, '主持'))
        group = self.until(lambda g: any(m.get('content') == '含稅，報價單第二頁有寫。' for m in g['messages']), 'the host did not answer before 接受結果')
        self.assertEqual(group['status'], 'running')
        self.assertEqual([t['status'] for t in group['taskRun']['tasks']], ['review', 'pending'])  # not accepted by the question: the card stays
        said = next(m for m in group['messages'] if m.get('content') == '這份報價含稅嗎？')
        self.assertTrue(said.get('interjected')); self.assertEqual(said.get('heardBy'), '主持'); self.assertNotIn('waiting', said)
        asked = [r for r in self.runs() if r['match'] == ASKED]
        self.assertEqual(len(asked), 1); self.assertIn('這份報價含稅嗎？', asked[0]['prompt']); self.assertIn('不是接受結果', asked[0]['prompt'])
        self.assertEqual(self.req('POST', '/api/groups/%s/tasks/%s/accept' % (self.group['id'], group['taskRun']['tasks'][0]['id']), {})[0], 202)
        self.autoaccept = True
        found = self.wait_group()
        self.assertEqual([t['status'] for t in found['taskRun']['tasks']], ['done', 'done'])
        time.sleep(1)
        self.assertEqual(len([r for r in self.runs() if r['match'] == ASKED]), 1)  # answered once: no new round for it after the run

    def test_work_that_starts_later_reads_what_the_user_added(self):
        self.engine()
        self.rules([{'match': ASKED, 'reply': '好，照新預算。'}, {'match': PLAN, 'calls': [create(1, '甲'), after(2, '乙', ['1'])], 'reply': '分好了'},
                    {'match': '請完成第 1 項', 'calls': [done()], 'sleep': 2}, {'match': '=== 工作', 'calls': [done()]}, {'match': WAKE, 'reply': SUMMARY}])
        self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '辦活動', 'mode': 'auto'})
        self.until(lambda g: any(t['status'] == 'running' for t in (g.get('taskRun') or {}).get('tasks') or []), 'work did not start')
        self.assertTrue(self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '桌菜預算改 3500'})[1]['interjected'])
        self.wait_group()
        second = [r for r in self.runs() if '請完成第 2 項' in r['prompt']]
        self.assertTrue(second and '桌菜預算改 3500' in second[0]['prompt'])  # the member's task has it
        asked = [r for r in self.runs() if r['match'] == ASKED]
        self.assertEqual(len(asked), 1)  # the host answered it while the work went on


if __name__ == '__main__': unittest.main()
