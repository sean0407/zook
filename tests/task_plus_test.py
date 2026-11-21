# -*- coding: utf-8 -*-
"""任務引擎, 0.17.3: work goes to the vendor whose checks pass more often for that kind of work, with the reason on the board;
a member may hand part of its task to a helper, two layers at most."""
import json, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import task_engine_test as base
from task_engine_test import PLAN, WAKE, SUMMARY, create, done
from task_check_test import CHECK, verdict

HELPER = '你是助手，自己完成'
BACK = '你先前把一部分交給助手了'


def delegate(who, title='查資料', changes='none'):
    return {'name': 'zook_task_delegate', 'arguments': {'title': title, 'assignee': who, 'spec': '查一下這件事的背景，交回三句話。', 'done_when': '交回三句話', 'changes': changes}}


class TaskPlusTest(base.TaskEngineTest):
    for _name in [n for n in dir(base.TaskEngineTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_a_helper_does_part_and_the_task_goes_on_with_its_report(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': HELPER, 'calls': [delegate('丙'), done('背景查好了，重點有三個。')]},  # a helper's helper: layer 3
                    {'match': BACK, 'calls': [done('主工作完成。')]},
                    {'match': '=== 工作 1', 'calls': [delegate('乙', changes='external'), delegate('乙')]},
                    {'match': WAKE, 'reply': SUMMARY}])
        run = self.send()['taskRun']
        first, helper = run['tasks']
        self.assertEqual((helper['depth'], helper['parent'], helper['assignee'], helper['status']), (2, 1, self.bots['乙']['id'], 'done'))
        self.assertIn('甲 派的助手', helper['basis'])
        self.assertEqual((first['status'], [a['state'] for a in first['attempts']]), ('done', ['delegated', 'reported']))
        self.assertEqual(first['deps'], [2])
        runs = self.runs()
        asked = next(r for r in runs if '=== 工作 1' in r['prompt'] and BACK not in r['prompt'])
        self.assertTrue(asked['answers'][0]['error']); self.assertIn('助手能做的不能比你這項工作多', asked['answers'][0]['text'])  # files → external: refused
        self.assertFalse(asked['answers'][1]['error'])
        deeper = next(r for r in runs if HELPER in r['prompt'])
        self.assertTrue(deeper['answers'][0]['error']); self.assertIn('最多兩層', deeper['answers'][0]['text'])
        self.assertEqual(len(run['tasks']), 2)  # nothing at layer 3
        back = next(r for r in runs if BACK in r['prompt'])
        self.assertIn('背景查好了', back['prompt'])

    def test_work_moves_from_a_vendor_whose_checks_keep_failing(self):
        codex = self.req('POST', '/api/bots', {'name': '丁', 'provider': 'codex'})[1]
        self.group = self.req('POST', '/api/groups', {'name': '混合', 'botIds': [self.bots['主持']['id'], self.bots['甲']['id'], codex['id']], 'hostId': self.bots['主持']['id']})[1]
        self.engine()
        self.restart(lambda d: d.update(taskStats={'claude': {'quick': [1, 5]}, 'codex': {'quick': [4, 4]}}))
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': CHECK, 'calls': [verdict('pass')]},
                    {'match': '=== 工作 1', 'calls': [done('做完了。')]},
                    {'match': WAKE, 'reply': SUMMARY}])
        task = self.send()['taskRun']['tasks'][0]
        self.assertEqual((task['assignee'], task['suggested'], task['kind'], task['status']), (codex['id'], '甲', 'quick', 'done'))
        self.assertIn('依過去的驗收紀錄改派', task['basis']); self.assertIn('1／5', task['basis']); self.assertIn('4／4', task['basis'])
        board = next(m for m in self.req('GET', '/api/groups/' + self.group['id'])[1]['group']['messages'] if m.get('taskBoard'))
        self.assertIn('依過去的驗收紀錄改派', board['content'])
        seen = {}
        self.restart(lambda d: seen.update(d.get('taskStats') or {}))
        self.assertEqual(seen['codex']['quick'], [5, 5])  # the check counted for the vendor that did the work
        # Turned off: the host's pick stands.
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskLearn': 'no'})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskLearn': False})[0], 200)
        mine = create(1, '甲'); mine['arguments']['reason'] = '它熟悉\n這個主題'
        self.rules([{'match': PLAN, 'calls': [mine], 'reply': '分好了'}, {'match': CHECK, 'calls': [verdict('pass')]},
                    {'match': '=== 工作 1', 'calls': [done('做完了。')]}, {'match': WAKE, 'reply': SUMMARY}])
        task = self.send()['taskRun']['tasks'][0]
        self.assertEqual((task['assignee'], task['basis']), (self.bots['甲']['id'], '主持人：它熟悉 這個主題'))
        board = [m for m in self.req('GET', '/api/groups/' + self.group['id'])[1]['group']['messages'] if m.get('taskBoard')][-1]
        self.assertIn('派工依據：主持人：它熟悉 這個主題', board['content'])

    def group_now(self): return self.req('GET', '/api/groups/' + self.group['id'])[1]['group']

    def until(self, test, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            group = self.group_now()
            if test(group): return group
            time.sleep(0.1)
        self.fail('waited too long')

    def test_a_helper_starts_only_after_the_turn_that_asked_for_it_ended_well(self):
        self.engine(); self.assertEqual(self.req('PATCH', '/api/settings', {'taskExecution': 'lowrisk'})[0], 200)
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': HELPER, 'calls': [done('查好了。')]},
                    {'match': BACK, 'calls': [done('主工作完成了。')]}, {'match': '=== 工作 1', 'calls': [delegate('乙')], 'sleep': 1.5}, {'match': WAKE, 'reply': SUMMARY}])
        run = self.send()['taskRun']
        self.assertEqual([t['status'] for t in run['tasks']], ['done', 'done'])
        asked = next(r for r in self.runs() if '=== 工作 1' in r['prompt'] and BACK not in r['prompt']); helper = next(r for r in self.runs() if HELPER in r['prompt'])
        self.assertGreaterEqual(helper['began'], asked['ended'] - 0.05)  # read-only helpers start by themselves here, but not before
        # The turn fails after asking: the helper never starts, and the task is tried again like any try that did not finish.
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': HELPER, 'calls': [done('查好了。')]},
                    {'match': '這項工作上一次沒有完成', 'calls': [done('自己做完了。')]}, {'match': '=== 工作 1', 'calls': [delegate('乙')], 'crash': True},
                    {'match': WAKE, 'reply': SUMMARY}])
        before = len([r for r in self.runs() if HELPER in r['prompt']])
        run = self.send()['taskRun']
        first, helper = run['tasks']
        self.assertEqual((helper['status'], first['status'], first['deps'], first['failures']), ('cancelled', 'done', [], 1))
        self.assertEqual(len([r for r in self.runs() if HELPER in r['prompt']]), before)

    def test_retrying_a_helper_never_skips_the_users_confirmation(self):
        self.engine(); self.autoconfirm = False
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': HELPER, 'calls': [done('查好了。')]},
                    {'match': '=== 工作 1', 'calls': [delegate('乙')]}, {'match': WAKE, 'reply': SUMMARY}])
        self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '做事', 'mode': 'auto'})
        self.confirm(self.until(lambda g: (g.get('taskRun') or {}).get('awaitingConfirm')))
        self.until(lambda g: len(g['taskRun']['tasks']) == 2 and g['taskRun'].get('awaitingConfirm'))  # the helper waits for 「照這個做」 too
        self.req('POST', '/api/groups/%s/stop' % self.group['id'], {})
        run = self.until(lambda g: g['status'] != 'running')['taskRun']
        helper = run['tasks'][1]
        self.assertEqual(self.req('POST', '/api/groups/%s/tasks/%s/retry' % (self.group['id'], helper['id']), {})[0], 202)
        run = self.until(lambda g: (g.get('taskRun') or {}).get('awaitingConfirm'))['taskRun']
        self.assertIs(run['tasks'][1]['confirmed'], False)
        time.sleep(1); self.assertEqual([r for r in self.runs() if HELPER in r['prompt']], [])
        self.req('POST', '/api/groups/%s/stop' % self.group['id'], {})

    def test_no_helper_when_its_member_cannot_deliver(self):
        self.engine()
        self.req('PATCH', '/api/bots/' + self.bots['乙']['id'], {'permissionMode': 'manual'})
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': '=== 工作 1', 'calls': [delegate('乙', changes='files'), delegate('甲'), done('自己做完了。')]}, {'match': WAKE, 'reply': SUMMARY}])
        run = self.send()['taskRun']
        answers = next(r for r in self.runs() if '=== 工作 1' in r['prompt'])['answers']
        self.assertTrue(answers[0]['error']); self.assertIn('謹慎', answers[0]['text'])
        self.assertTrue(answers[1]['error'])  # not itself
        self.req('PATCH', '/api/bots/' + self.bots['丙']['id'], {'provider': 'auto'})
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': '=== 工作 1', 'calls': [delegate('丙'), done('自己做完了。')]}, {'match': WAKE, 'reply': SUMMARY}])
        self.send()
        answers = [r for r in self.runs() if '=== 工作 1' in r['prompt']][-1]['answers']
        self.assertTrue(answers[0]['error']); self.assertIn('自動選擇', answers[0]['text'])
        self.assertEqual(len(run['tasks']), 1)

    def test_a_helper_stopped_before_its_turn_ended_never_runs(self):
        self.engine(); self.assertEqual(self.req('PATCH', '/api/settings', {'taskExecution': 'lowrisk'})[0], 200)
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': HELPER, 'calls': [done('查好了。')]},
                    {'match': '=== 工作 1', 'calls': [delegate('乙')], 'sleep': 4}, {'match': WAKE, 'reply': SUMMARY}])
        self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '做事', 'mode': 'auto'})
        self.until(lambda g: ((g.get('taskRun') or {}).get('awaitingConfirm') and self.confirm(g) and False) or len((g.get('taskRun') or {}).get('tasks') or []) == 2)
        self.req('POST', '/api/groups/%s/stop' % self.group['id'], {})
        run = self.until(lambda g: g['status'] != 'running')['taskRun']
        first, helper = run['tasks']
        self.assertEqual((helper['status'], helper.get('aborted'), first['deps']), ('cancelled', True, []))
        self.assertEqual(self.req('POST', '/api/groups/%s/tasks/%s/retry' % (self.group['id'], helper['id']), {})[0], 409)
        time.sleep(1); self.assertEqual([r for r in self.runs() if HELPER in r['prompt']], [])
        # Zook restarted with a helper still waiting for its member's turn: the same.
        def staged(d):
            run = next(g for g in d['groups'] if g['id'] == self.group['id'])['taskRun']
            run['status'] = 'running'; run['tasks'][0]['status'] = 'running'; run['tasks'][0]['deps'] = [2]
            run['tasks'][1].update(status='ready', staged=True); run['tasks'][1].pop('aborted', None)
        self.restart(staged)
        run = self.group_now()['taskRun']
        self.assertEqual((run['tasks'][1]['status'], run['tasks'][1].get('aborted'), run['tasks'][0]['deps']), ('cancelled', True, []))


class TaskPlusRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = base.load()

    def test_a_record_counts_only_after_three_checks_and_a_clear_gap(self):
        m = self.m
        class Store: data = {}
        store = Store()
        store.data = {'taskStats': {'claude': {'code': [0, 2]}, 'codex': {'code': 'x'}}}
        self.assertEqual(m.task_rate(store, 'claude', 'code'), (0, 2))
        self.assertEqual(m.task_rate(store, 'codex', 'code'), (0, 0))  # a damaged entry counts as nothing
        self.assertEqual(m.task_rate(store, 'gemini', 'code'), (0, 0))
        self.assertTrue(m.task_run_ok({'id': 'r', 'status': 'done', 'origin': 'user', 'hostId': 'h', 'tasks': [
            {'id': 't', 'n': 1, 'title': 'a', 'status': 'done', 'assignee': 'b', 'spec': 's', 'doneWhen': 'd', 'attempts': [], 'depth': 2, 'parent': 1, 'basis': 'x', 'kind': 'code'}]}))
        self.assertFalse(m.task_run_ok({'id': 'r', 'status': 'done', 'origin': 'user', 'hostId': 'h', 'tasks': [
            {'id': 't', 'n': 1, 'title': 'a', 'status': 'done', 'assignee': 'b', 'spec': 's', 'doneWhen': 'd', 'attempts': [], 'depth': True}]}))
        for damaged in ([], None, {'claude': 'x'}, {'claude': {'code': [-1, 2]}}, {'claude': {'code': [3, 2]}}):
            store.data = {'taskStats': damaged}
            self.assertEqual(m.task_rate(store, 'claude', 'code'), (0, 0))

    def test_handoffs_that_did_not_happen_are_dropped_and_released_ones_bring_their_room(self):
        m = self.m
        def fresh():
            return {'tasks': [{'n': 1, 'status': 'running', 'deps': [2], 'attempts': [{'state': 'delegated'}]},
                              {'n': 2, 'status': 'ready', 'parent': 1, 'staged': True, 'attempts': []}, {'n': 3, 'status': 'ready', 'attempts': []}]}
        run = fresh()
        m.task_handoff_orphans(run); self.assertTrue(run['tasks'][1]['staged'])  # its member's turn is still running
        run['tasks'][0]['status'] = 'stuck'; m.task_handoff_orphans(run)  # an internal error ended it
        self.assertEqual((run['tasks'][1]['status'], run['tasks'][1]['aborted'], run['tasks'][0]['deps']), ('cancelled', True, []))
        for job, published, want in (({'status': 'completed'}, True, 'pending'), ({'status': 'completed'}, False, 'ready'), ({'status': 'failed', 'error': 'x'}, True, 'ready'), ({'status': 'cancelled'}, True, 'cancelled')):
            run = fresh(); m.task_handoff_end(run['tasks'][0], run, job, published)
            self.assertEqual(run['tasks'][0]['status'], want)
            self.assertEqual(run['tasks'][1]['status'], 'ready' if want == 'pending' else 'cancelled')
            self.assertNotIn('staged', run['tasks'][1])
            self.assertEqual(run.get('bonusAttempts', 0), 2 if want == 'pending' else 0)  # the helper's start and the task going on afterwards

    def test_numbers_win_over_titles_and_the_host_can_name_image_work(self):
        m = self.m
        run = {'tasks': [{'n': 1, 'title': '3'}, {'n': 2, 'title': 'b'}, {'n': 3, 'title': 'c'}]}
        self.assertEqual(m.task_find(run, '3')['n'], 3); self.assertEqual(m.task_find(run, 'b')['n'], 2)
        self.assertEqual(m.task_kind_of('把這張圖去背', 'IMAGE'), 'image'); self.assertEqual(m.task_kind_of('x', 'other'), 'quick')


if __name__ == '__main__': unittest.main()
