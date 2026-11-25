# -*- coding: utf-8 -*-
"""#245 in 任務引擎: a task reported done with files that are not there goes back to its member to save them; it is not checked
by another vendor until they are."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import task_engine_test as base
from task_engine_test import PLAN, WAKE, SUMMARY, create

CHECK = '=== 要驗收的工作'


def handed(text, files):
    return {'name': 'zook_task_done', 'arguments': {'outcome': 'succeeded', 'summary': text, 'files': files}}


class CheckAfterDoneTask(base.TaskEngineTest):
    for _name in [n for n in dir(base.TaskEngineTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_reported_file_missing_goes_back_before_the_check(self):
        codex = self.req('POST', '/api/bots', {'name': '丁', 'provider': 'codex'})[1]
        self.group = self.req('POST', '/api/groups', {'name': '混合', 'botIds': [self.bots['主持']['id'], self.bots['甲']['id'], codex['id']], 'hostId': self.bots['主持']['id']})[1]
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': CHECK, 'calls': [{'name': 'zook_task_verdict', 'arguments': {'result': 'pass', 'reasons': '都對得上'}}]},
                    {'match': '這項工作上一次沒有完成', 'calls': [handed('這次只交文字。', [])]},
                    {'match': '=== 工作 1', 'calls': [handed('做好了。', ['報價單.xlsx'])]},
                    {'match': WAKE, 'reply': SUMMARY}])
        group = self.send()
        task = group['taskRun']['tasks'][0]
        self.assertEqual((task['status'], task['failures'], len(task['attempts'])), ('done', 1, 2))
        checks = [r for r in self.runs() if CHECK in r['prompt']]
        self.assertEqual(len(checks), 1)  # only the try whose files are there is checked
        redo = next(r for r in self.runs() if '這項工作上一次沒有完成' in r['prompt'])
        self.assertIn('報價單.xlsx', redo['prompt'])
        self.assertTrue(any('報價單.xlsx' in m.get('content', '') and '找不到' in m.get('content', '') for m in group['messages'] if m['role'] == 'system'))


    def test_a_check_task_must_wait_for_the_work(self):
        checker = self.req('POST', '/api/bots', {'name': '查核員', 'provider': 'claude'})[1]
        self.group = self.req('POST', '/api/groups', {'name': '查核', 'botIds': [self.bots['主持']['id'], self.bots['甲']['id'], checker['id']], 'hostId': self.bots['主持']['id']})[1]
        self.engine()
        check = create(2, '查核員'); late = dict(check, arguments=dict(check['arguments'], title='工作3', after=['1']))
        self.rules([{'match': PLAN, 'calls': [check, create(1, '甲'), late], 'reply': '分好了'},
                    {'match': '=== 工作', 'calls': [handed('做好了。', [])]}, {'match': WAKE, 'reply': SUMMARY}])
        group = self.send()
        answers = next(r for r in self.runs() if r['match'] == PLAN)['answers']
        self.assertTrue(answers[0]['error'] and 'after' in answers[0]['text'], answers[0])
        self.assertFalse(answers[2]['error'], answers[2])
        tasks = group['taskRun']['tasks']
        self.assertEqual([(t['title'], t.get('deps')) for t in tasks], [('工作1', []), ('工作3', [1])])

if __name__ == '__main__': unittest.main()
