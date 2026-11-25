# -*- coding: utf-8 -*-
"""自動 (任務引擎) and 回合 (#174, decided by the user): the host writes down the goal and when it is done, the board shows it, the
run does not stop before it is reached, and every few rounds the host sums up first and the user says whether to go on."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
_spec = importlib.util.spec_from_file_location('task_engine_parts', Path(__file__).with_name('task_engine_test.py'))
parts = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(parts)  # the fake CLI and the tool calls it makes; not its tests
PLAN, WAKE, SUMMARY, create, done = parts.PLAN, parts.WAKE, parts.SUMMARY, parts.create, parts.done
CONVERGE = '這一輪先收斂'
RESUME = '使用者看過你整理的進度，選擇繼續'
BOUNDARY = {'name': 'zook_task_boundary', 'arguments': {'goal': '比較三家報價', 'done_when': '三家都比較過，選出一家並附理由'}}
ASK = {'name': 'zook_task_ask', 'arguments': {'question': '要比幾家？'}}
REPLY = {'name': 'zook_task_reply', 'arguments': {'number': '1', 'answer': '三家'}}
CARD = '【結論】做了一半\n【待你決定】要不要繼續\n【行動項目】甲：再比一家\n【未解問題】無'


class TaskRounds(unittest.TestCase):
    every = '3'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('claude', 'codex'): cli = self.root / 'bin' / name; cli.write_text(parts.CLAUDE); cli.chmod(0o755)
        self.rules([])
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0',
                   ZOOK_TASK_CHECK_EVERY=self.every)
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'provider': 'claude', 'permissionMode': 'auto', 'taskEngine': True})
        self.bots = {name: self.req('POST', '/api/bots', {'name': name, 'provider': 'claude'})[1] for name in ('主持', '甲', '乙')}
        self.group = self.req('POST', '/api/groups', {'name': '小組', 'botIds': [b['id'] for b in self.bots.values()], 'hostId': self.bots['主持']['id'], 'mode': 'auto'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def rules(self, rules): (self.root / 'bin/rules.json').write_text(json.dumps(rules, ensure_ascii=False), encoding='utf-8')
    def runs(self): return [json.loads(x) for x in (self.root / 'bin/runs.jsonl').read_text(encoding='utf-8').splitlines()] if (self.root / 'bin/runs.jsonl').exists() else []
    def get(self): return self.req('GET', '/api/groups/' + self.group['id'])[1]['group']

    def run_until(self, answers, seconds=90):
        """Send the goal; confirm the plan; answer each check in turn with the next of answers. Returns the group once it is idle."""
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '請比較三家報價', 'mode': 'auto'})[0], 202)
        answers, end = list(answers), time.time() + seconds
        while time.time() < end:
            group = self.get(); run = group.get('taskRun') or {}
            if group['status'] != 'running': return group
            if run.get('awaitingConfirm'):
                shown = [t['id'] for t in run['tasks'] if t.get('confirmed') is False and t['status'] in ('pending', 'ready', 'waiting')]
                self.req('POST', '/api/groups/%s/tasks/confirm' % self.group['id'], {'tasks': shown})
            for gate in [x for x in run.get('gates') or [] if x['status'] == 'pending' and x.get('kind') == 'checkpoint']:
                self.assertTrue(answers, 'asked more often than expected')
                self.assertEqual(self.req('POST', '/api/groups/%s/gates/%s' % (self.group['id'], gate['id']), {'answer': answers.pop(0)})[0], 200)
            time.sleep(0.1)
        self.fail('the group did not finish')

    def test_the_boundary_is_on_the_board(self):
        self.rules([{'match': PLAN, 'calls': [BOUNDARY, create(1, '甲')], 'reply': '分好了'}, {'match': WAKE, 'reply': SUMMARY},
                    {'match': '=== 工作', 'calls': [done()], 'reply': '完成'}])
        group = self.run_until([])
        run = group['taskRun']
        self.assertEqual((run['boundary']['goal'], run['boundary']['doneWhen']), ('比較三家報價', '三家都比較過，選出一家並附理由'))
        board = next(m for m in group['messages'] if m.get('taskBoard'))
        self.assertIn('目標：比較三家報價', board['content']); self.assertIn('完成條件：三家都比較過', board['content'])
        plan = next(r for r in self.runs() if r['match'] == PLAN)
        self.assertIn('zook_task_boundary', plan['tools']); self.assertFalse(plan['answers'][0]['error'], plan['answers'])
        self.assertIn('zook_task_boundary', plan['prompt'])
        wake = next(r for r in self.runs() if r['match'] == WAKE)
        self.assertIn('完成條件：三家都比較過', wake['prompt']); self.assertIn('不要寫總結', wake['prompt'])

    def test_no_boundary_written_shows_the_users_goal(self):
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': WAKE, 'reply': SUMMARY}, {'match': '=== 工作', 'calls': [done()]}])
        board = next(m for m in self.run_until([])['messages'] if m.get('taskBoard'))
        self.assertIn('目標：請比較三家報價', board['content'])

    def test_it_sums_up_every_few_rounds_and_goes_on_when_told(self):
        """Never stopped by a count of wakes; every 3 rounds (here) the host sums up, then the user decides: 繼續, later 到此為止."""
        self.rules([{'match': CONVERGE, 'reply': CARD}, {'match': RESUME, 'calls': [REPLY], 'reply': '接著做'},
                    {'match': PLAN, 'calls': [BOUNDARY, create(1, '甲')], 'reply': '分好了'}, {'match': WAKE, 'calls': [REPLY], 'reply': '回答了'},
                    {'match': '=== 工作', 'calls': [ASK], 'reply': '先問一下'}])
        group = self.run_until(['繼續', '到此為止'])
        run = group['taskRun']
        hosts = [r['match'] for r in self.runs() if r['match'] in (PLAN, WAKE, CONVERGE, RESUME)]
        self.assertEqual(hosts, [PLAN, WAKE, WAKE, CONVERGE, RESUME, WAKE, WAKE, CONVERGE], hosts)
        converge = [r for r in self.runs() if r['match'] == CONVERGE]
        self.assertNotIn('zook_task_create', [a['name'] for a in converge[0]['answers']])
        self.assertIn('已經進行 3 回合', converge[0]['prompt'])
        self.assertEqual(run['status'], 'stopped')
        gates = [g for g in run['gates'] if g.get('kind') == 'checkpoint']
        self.assertEqual([g['answer'] for g in gates], ['繼續', '到此為止'])
        said = [m['content'] for m in group['messages'] if m['role'] == 'system']
        self.assertTrue(any('你選擇繼續' in x for x in said), said); self.assertTrue(any('到此為止' in x for x in said), said)
        self.assertFalse(any('叫醒' in x for x in said), said)
        self.assertTrue(any(m.get('card') for m in group['messages'] if m.get('role') == 'assistant'))  # the summing up is a card

    def test_create_is_refused_while_the_user_decides(self):
        self.rules([{'match': CONVERGE, 'calls': [create(2, '乙')], 'reply': CARD}, {'match': PLAN, 'calls': [BOUNDARY, create(1, '甲')], 'reply': '分好了'},
                    {'match': WAKE, 'calls': [REPLY], 'reply': '回答了'}, {'match': '=== 工作', 'calls': [ASK], 'reply': '先問一下'}])
        group = self.run_until(['到此為止'])
        converge = next(r for r in self.runs() if r['match'] == CONVERGE)
        self.assertTrue(converge['answers'][0]['error']); self.assertIn('要不要繼續', converge['answers'][0]['text'])
        self.assertEqual(len(group['taskRun']['tasks']), 1)


class TaskRoundsTyped(TaskRounds):
    """「繼續」 typed in the chat while the check waits answers it, as the card would."""
    def run_until(self, answers, seconds=90):
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '請比較三家報價', 'mode': 'auto'})[0], 202)
        answers, end = list(answers), time.time() + seconds
        while time.time() < end:
            group = self.get(); run = group.get('taskRun') or {}
            if group['status'] != 'running': return group
            if run.get('awaitingConfirm'):
                shown = [t['id'] for t in run['tasks'] if t.get('confirmed') is False and t['status'] in ('pending', 'ready', 'waiting')]
                self.req('POST', '/api/groups/%s/tasks/confirm' % self.group['id'], {'tasks': shown})
            if [x for x in run.get('gates') or [] if x['status'] == 'pending' and x.get('kind') == 'checkpoint']:
                self.assertEqual(self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': answers.pop(0)})[0], 202)
            time.sleep(0.1)
        self.fail('the group did not finish')

    test_the_boundary_is_on_the_board = test_no_boundary_written_shows_the_users_goal = test_create_is_refused_while_the_user_decides = None


if __name__ == '__main__':
    unittest.main()
