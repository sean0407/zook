# -*- coding: utf-8 -*-
"""任務引擎, 0.17.1: tasks that wait for others, how many run at once, and who takes a task when a member's quota is low."""
import json, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import task_engine_test as base
from task_engine_test import PLAN, WAKE, SUMMARY, create, done


def after(n, who, deps):
    call = create(n, who); call['arguments']['after'] = deps
    return call


class TaskOrderTest(base.TaskEngineTest):
    for _name in [n for n in dir(base.TaskEngineTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def workers(self, n): return [r for r in self.runs() if r['match'] == '=== 工作 %d' % n]

    def test_a_task_waits_for_the_one_it_needs_and_gets_its_report(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲'), after(2, '乙', ['1']), create(3, '丙')], 'reply': '分好了'},
                    {'match': '=== 工作 1', 'calls': [done('景點是故宮。沒有問題。沒有剩下的事。')], 'sleep': 1.5},
                    {'match': '=== 工作 2', 'calls': [done()]},
                    {'match': '=== 工作 3', 'calls': [done()], 'sleep': 1.5},
                    {'match': WAKE, 'reply': SUMMARY}])
        group = self.send()
        run = group['taskRun']
        self.assertEqual([t['status'] for t in run['tasks']], ['done'] * 3)
        self.assertEqual(run['tasks'][1]['deps'], [1])
        one, two, three = self.workers(1)[0], self.workers(2)[0], self.workers(3)[0]
        self.assertGreaterEqual(two['began'], one['ended'])          # 2 started after 1 finished
        self.assertLess(three['began'], one['ended'])               # 3 did not wait
        self.assertIn('景點是故宮', two['prompt']); self.assertIn('前面完成的工作', two['prompt'])
        self.assertNotIn('景點是故宮', three['prompt'])
        self.assertEqual((run['batches'], run['wakes']), (1, 1))

    def test_a_task_after_one_that_failed_does_not_start(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲'), after(2, '乙', ['1']), after(3, '丙', ['9'])], 'reply': '分好了'},
                    {'match': '=== 工作 1', 'calls': [done('做不到。', 'failed')]},
                    {'match': WAKE, 'reply': SUMMARY}])
        run = self.send()['taskRun']
        self.assertEqual([t['status'] for t in run['tasks']], ['failed', 'failed'])
        self.assertIn('前面的工作沒有完成', run['tasks'][1]['note']); self.assertFalse(self.workers(2))
        plan = next(r for r in self.runs() if r['match'] == PLAN)
        self.assertEqual([a['error'] for a in plan['answers']], [False, False, True])  # it can only wait for a task that exists

    def test_one_cli_at_a_time_when_set(self):
        self.engine()
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskMax': 7})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskCliLimits': {'claude': 9}})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskCliLimits': {'claude': 1}})[0], 200)
        self.rules([{'match': PLAN, 'calls': [create(1, '甲'), create(2, '乙'), create(3, '丙')], 'reply': '分好了'},
                    {'match': '=== 工作', 'calls': [done()], 'sleep': 0.8},
                    {'match': WAKE, 'reply': SUMMARY}])
        run = self.send()['taskRun']
        self.assertEqual([t['status'] for t in run['tasks']], ['done'] * 3)
        work = sorted((r for r in self.runs() if r['match'] == '=== 工作'), key=lambda r: r['began'])
        for earlier, later in zip(work, work[1:]): self.assertGreaterEqual(later['began'], earlier['ended'] - 0.05)
        self.assertEqual((run['batches'], run['wakes']), (1, 1))

    def test_a_member_low_on_quota_hands_the_task_to_another(self):
        codex = self.req('POST', '/api/bots', {'name': '丁', 'provider': 'codex'})[1]
        group = self.req('POST', '/api/groups', {'name': '混合', 'botIds': [self.bots['主持']['id'], self.bots['甲']['id'], codex['id']], 'hostId': self.bots['主持']['id']})[1]
        self.engine()
        later = time.time() + 86400
        self.restart(lambda data: data.setdefault('quota', {}).update(claude=dict(windows=[dict(label='每週', usedPercent=96, resetsAt=later)], updatedAt='2099-01-01T00:00:00+00:00')))
        self.group = group
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': '=== 工作', 'calls': [done()]},
                    {'match': WAKE, 'reply': SUMMARY}])
        task = self.send()['taskRun']['tasks'][0]
        self.assertEqual((task['assignee'], task['suggested'], task['status']), (codex['id'], '甲', 'done'))
        self.assertIn('改派給 丁', task['why'])
        plan = next(r for r in self.runs() if r['match'] == PLAN)
        self.assertIn('改派', plan['answers'][0]['text'])
        self.assertEqual(self.workers_any()[0]['cli'], 'codex')

    def test_a_member_that_reports_and_says_nothing_more_did_not_fail(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': '=== 工作', 'calls': [done('景點是故宮。')], 'reply': ''},
                    {'match': WAKE, 'reply': SUMMARY}])
        group = self.send()
        reply = next(m for m in group['messages'] if m.get('taskId'))
        self.assertEqual((reply['status'], reply['content']), ('completed', '景點是故宮。'))
        self.assertEqual(group['taskRun']['tasks'][0]['status'], 'done')

    def test_a_crash_after_the_report_is_not_a_finished_task(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲'), after(2, '乙', ['1'])], 'reply': '分好了'},
                    {'match': '=== 工作 1', 'calls': [done()], 'crash': True},
                    {'match': WAKE, 'reply': SUMMARY}])
        run = self.send()['taskRun']
        self.assertEqual([t['status'] for t in run['tasks']], ['failed', 'failed'])
        self.assertIn('回報後 CLI 出錯', run['tasks'][0]['attempts'][0]['summary'])
        self.assertFalse(self.workers(2))  # what came after it did not start

    def test_silence_without_a_report_still_fails(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': '=== 工作', 'reply': ''}, {'match': WAKE, 'reply': SUMMARY}])
        group = self.send()
        self.assertEqual(group['taskRun']['tasks'][0]['status'], 'failed')
        self.assertEqual(next(m for m in group['messages'] if m.get('taskId'))['status'], 'failed')

    def test_after_means_a_task_number_even_when_a_title_is_a_number(self):
        self.engine()
        first = create(1, '甲'); first['arguments']['title'] = '2'
        self.rules([{'match': PLAN, 'calls': [first, create(2, '乙'), after(3, '丙', ['2'])], 'reply': '分好了'},
                    {'match': '=== 工作', 'calls': [done()]}, {'match': WAKE, 'reply': SUMMARY}])
        self.assertEqual(self.send()['taskRun']['tasks'][2]['deps'], [2])

    def test_a_busy_member_does_not_hold_up_the_others(self):
        self.engine()
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskMax': 2})[0], 200)
        self.rules([{'match': PLAN, 'calls': [create(1, '甲'), create(2, '甲'), create(3, '乙')], 'reply': '分好了'},
                    {'match': '=== 工作', 'calls': [done()], 'sleep': 1.5}, {'match': WAKE, 'reply': SUMMARY}])
        run = self.send()['taskRun']
        self.assertEqual([t['status'] for t in run['tasks']], ['done'] * 3)
        work = lambda n: next(r for r in self.runs() if '=== 工作 %d：' % n in r['prompt'])
        self.assertLess(work(3)['began'], work(1)['ended'])  # 乙 did not wait behind 甲's second task

    def test_the_host_hears_about_what_its_silence_ended(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲'), after(2, '乙', ['1'])], 'reply': '分好了'},
                    {'match': '=== 工作 1', 'calls': [{'name': 'zook_task_ask', 'arguments': {'question': '哪一天？'}}], 'reply': '先問'},
                    {'match': WAKE, 'reply': SUMMARY}])
        run = self.send()['taskRun']
        self.assertEqual([t['status'] for t in run['tasks']], ['failed', 'failed'])
        wakes = [r for r in self.runs() if r['match'] == WAKE]
        self.assertEqual(len(wakes), 2); self.assertIn('主持人沒有回答', wakes[1]['prompt']); self.assertIn('前面的工作沒有完成', wakes[1]['prompt'])

    def test_files_put_back_keep_only_valid_task_settings(self):
        m = base.load()
        settings = dict(taskEngine=True, taskMax=True, taskCliLimits=['claude'])
        m.task_settings_clean(settings)
        self.assertEqual(settings, dict(taskEngine=True))
        good = dict(taskMax=3, taskCliLimits={'claude': 2}); m.task_settings_clean(good)
        self.assertEqual(good, dict(taskMax=3, taskCliLimits={'claude': 2}))

    def workers_any(self): return [r for r in self.runs() if r['match'] == '=== 工作']


if __name__ == '__main__':
    unittest.main()
