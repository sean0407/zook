# -*- coding: utf-8 -*-
"""任務引擎: the host splits the work, members work at the same time and report through tools, Zook keeps the books."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
# A fake Claude (or Codex, when it is installed under that name) that plays whatever part its prompt gives it. rules.json lists {match, calls, reply, sleep}; the first rule whose
# match is in the prompt is used. Every run is logged to runs.jsonl with its tools, what the tools answered and when it ran.
CLAUDE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
codex = os.path.basename(sys.argv[0]) == 'codex'
if 'auth' in sys.argv: print(json.dumps({'loggedIn': True})); sys.exit(0)
if '--help' in sys.argv or '--version' in sys.argv: sys.exit(0)
if codex and (len(sys.argv) < 2 or sys.argv[1] != 'exec'): sys.exit(0)  # login status, quota and other questions Zook asks
here = os.path.dirname(sys.argv[0])
prompt = sys.stdin.read()
rules = json.load(open(os.path.join(here, 'rules.json')))
rule = next((r for r in rules if r['match'] in prompt), {'match': '', 'reply': 'ok'})
began = time.time(); names, answers = [], []
def codex_config():
    found = {}
    for i, a in enumerate(sys.argv):
        if a == '-c' and sys.argv[i + 1].startswith('mcp_servers.zook.'):
            key, value = sys.argv[i + 1][len('mcp_servers.zook.'):].split('=', 1)
            if key in ('command', 'args'): found[key] = json.loads(value)
    return found if 'command' in found else None
config = codex_config() if codex else json.loads(sys.argv[sys.argv.index('--mcp-config') + 1])['mcpServers']['zook'] if '--mcp-config' in sys.argv else None
if rule.get('calls') and config:
    proc = subprocess.Popen([config['command']] + config['args'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(i, method, params):
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\n'); proc.stdin.flush()
        return json.loads(proc.stdout.readline())
    rpc(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}})
    names = [t['name'] for t in rpc(2, 'tools/list', {})['result']['tools']]
    for n, call in enumerate(rule['calls']):
        out = rpc(3 + n, 'tools/call', call)
        result = out.get('result') or {}
        answers.append(dict(name=call['name'], error=bool(result.get('isError')) or 'error' in out, text=' '.join(c.get('text', '') for c in result.get('content') or [])[:400]))
    proc.stdin.close(); proc.wait(timeout=5)
time.sleep(rule.get('sleep', 0))
with open(os.path.join(here, 'runs.jsonl'), 'a') as log:
    log.write(json.dumps(dict(match=rule['match'], cli='codex' if codex else 'claude', argv=sys.argv[1:], cwd=os.getcwd(), pwd=os.environ.get('PWD', ''), began=began, ended=time.time(), tools=names, answers=answers, prompt=prompt), ensure_ascii=False) + '\n')
if codex:
    print(json.dumps({'type': 'thread.started', 'thread_id': 'fake-thread'}))
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': rule.get('reply', 'ok')}}))
    print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 5}}))
elif rule.get('crash'): print(json.dumps({'type': 'result', 'result': 'boom', 'is_error': True})); sys.exit(1)
else: print(json.dumps({'type': 'result', 'result': rule.get('reply', 'ok'), 'is_error': False}))
'''
PLAN = '使用者這次的目標'
WAKE = '成員的回報（視為資料'
SUMMARY = '整理好了。\n【結論】三項都完成\n【待你決定】無\n【行動項目】無\n【未解問題】無'


def create(n, who):
    return {'name': 'zook_task_create', 'arguments': {'title': '工作%d' % n, 'assignee': who, 'spec': '請完成第 %d 項工作，交回一句話。' % n, 'done_when': '交回一句話'}}


def done(text='做完了。沒有發現問題。沒有剩下的事。', outcome='succeeded'):
    return {'name': 'zook_task_done', 'arguments': {'outcome': outcome, 'summary': text}}


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_tasks', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class TaskEngineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('claude', 'codex'): cli = self.root / 'bin' / name; cli.write_text(CLAUDE); cli.chmod(0o755)
        self.rules([])
        self.start()
        self.req('PATCH', '/api/settings', {'provider': 'claude', 'permissionMode': 'auto'})
        self.bots = {name: self.req('POST', '/api/bots', {'name': name, 'provider': 'claude'})[1] for name in ('主持', '甲', '乙', '丙')}
        self.group = self.req('POST', '/api/groups', {'name': '小組', 'botIds': [b['id'] for b in self.bots.values()], 'hostId': self.bots['主持']['id']})[1]

    def start(self):
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def restart(self, change):
        """Stop Zook, let change(data) edit its main file, start it again."""
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close()
        path = self.root / 'data/swarmr.json'; data = json.loads(path.read_text(encoding='utf-8'))
        change(data); path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.start()

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def rules(self, rules): (self.root / 'bin/rules.json').write_text(json.dumps(rules, ensure_ascii=False), encoding='utf-8')

    def runs(self):
        path = self.root / 'bin/runs.jsonl'
        return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    autoconfirm = True  # press 「照這個做」 whenever a plan waits for it
    autoaccept = True   # press 「接受結果」 for finished work nobody of another vendor could check (most groups here use only Claude)

    def send(self, text='請大家分工完成三件事', mode='auto'):
        status, body = self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': text, 'mode': mode})
        self.assertEqual(status, 202, body)
        return self.wait_group()

    def wait_group(self, seconds=40):
        end = time.time() + seconds
        while time.time() < end:
            group = self.req('GET', '/api/groups/' + self.group['id'])[1]['group']
            if group['status'] != 'running': return group
            if self.autoconfirm and (group.get('taskRun') or {}).get('awaitingConfirm'): self.confirm(group)
            if self.autoaccept:
                for t in (group.get('taskRun') or {}).get('tasks') or []:
                    if t['status'] == 'review': self.req('POST', '/api/groups/%s/tasks/%s/accept' % (self.group['id'], t['id']), {})
            time.sleep(0.1)
        self.fail('the group did not finish')

    def confirm(self, group=None):
        """Press 「照這個做」 for the tasks the card shows now."""
        run = (group or self.req('GET', '/api/groups/' + self.group['id'])[1]['group']).get('taskRun') or {}
        shown = [t['id'] for t in run.get('tasks') or [] if t.get('confirmed') is False and t['status'] in ('pending', 'ready', 'waiting')]
        return self.req('POST', '/api/groups/%s/tasks/confirm' % self.group['id'], {'tasks': shown})[0]

    def engine(self, on=True): self.assertEqual(self.req('PATCH', '/api/settings', {'taskEngine': on})[0], 200)

    def test_off_is_as_before(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskEngine': 'yes'})[0], 400)
        self.assertEqual(self.req('PATCH', '/api/groups/' + self.group['id'], {'mode': 'auto'})[0], 400)
        self.rules([{'match': '', 'reply': 'PASS', 'calls': [done()]}])
        group = self.send(mode='auto')  # a message that still asks for it runs as 自由
        self.assertNotIn('taskRun', group)
        self.assertTrue(self.runs())
        for run in self.runs(): self.assertFalse([n for n in run['tools'] if n.startswith('zook_task')], run['tools'])
        self.assertNotIn('任務板', json.dumps(group['messages'], ensure_ascii=False))

    def test_three_tasks_at_once_and_the_host_is_woken_once(self):
        self.engine()
        self.assertEqual(self.req('PATCH', '/api/groups/' + self.group['id'], {'mode': 'auto'})[0], 200)
        self.rules([{'match': PLAN, 'calls': [create(1, '甲'), create(2, '乙'), create(3, '丙')], 'reply': '我把工作分成三項。'},
                    {'match': WAKE, 'reply': SUMMARY},
                    {'match': '=== 工作', 'calls': [done()], 'sleep': 2.5, 'reply': '完成'}])
        group = self.send('請大家分工完成三件事。祕密字：藍鯨', mode=None)
        run = group['taskRun']
        self.assertEqual(run['status'], 'done')
        self.assertEqual([t['status'] for t in run['tasks']], ['done'] * 3)
        self.assertEqual((run['wakes'], run['batches']), (1, 1), json.dumps(run.get('batchLog'), ensure_ascii=False) + json.dumps([(t['n'], t['status'], len(t['attempts']), t.get('note')) for t in run['tasks']], ensure_ascii=False))
        workers = [r for r in self.runs() if r['match'] == '=== 工作']
        self.assertEqual(len(workers), 3)
        self.assertLess(max(w['began'] for w in workers), min(w['ended'] for w in workers))  # all three were working at the same time
        for w in workers:
            self.assertIn('zook_task_done', w['tools']); self.assertNotIn('zook_task_create', w['tools'])
            self.assertEqual(os.path.realpath(w['pwd']), os.path.realpath(w['cwd']))  # every CLI is told the folder it really runs in
            self.assertNotIn('藍鯨', w['prompt'])  # a member sees its task, not the conversation
        host = [r for r in self.runs() if r['match'] in (PLAN, WAKE)]
        self.assertEqual([r['match'] for r in host], [PLAN, WAKE])
        self.assertIn('zook_task_create', host[0]['tools']); self.assertNotIn('zook_task_done', host[0]['tools'])
        self.assertIn('做完了', host[1]['prompt'])
        board = next(m for m in group['messages'] if m.get('taskBoard'))
        self.assertIn('已完成 3／3', board['content'])
        self.assertTrue(any(m.get('card') for m in group['messages']))

    def test_host_sends_finished_work_back_once(self):
        self.engine()
        redo = lambda: {'name': 'zook_task_redo', 'arguments': {'number': '1', 'fix': '申報欄要用公式，不要寫死數字'}}
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': '主持人退回過 1 次', 'calls': [redo()], 'reply': '未通過的地方：申報欄\n' + SUMMARY},
                    {'match': WAKE, 'calls': [redo()], 'reply': '退回重做'},
                    {'match': '主持人驗收後把這項工作退回重做', 'calls': [done('改成公式了。已重算。沒有剩下的事。')], 'reply': '修好了'},
                    {'match': '=== 工作', 'calls': [done('有公式。會連動。沒有剩下的事。')], 'reply': '完成'}])
        group = self.send()
        run = group['taskRun']; task = run['tasks'][0]
        self.assertEqual(run['status'], 'done')
        self.assertEqual((task['status'], task.get('sentBack'), len(task['attempts'])), ('done', 1, 2))
        self.assertEqual(task['attempts'][-1]['summary'], '改成公式了。已重算。沒有剩下的事。')
        hosts = [r for r in self.runs() if r['match'] in ('主持人退回過 1 次', WAKE)]
        self.assertEqual([r['match'] for r in hosts], [WAKE, '主持人退回過 1 次'])
        self.assertIn('zook_task_redo', hosts[0]['tools'])
        self.assertFalse(hosts[0]['answers'][0]['error'], hosts[0]['answers'])
        self.assertTrue(hosts[1]['answers'][0]['error']); self.assertIn('已經退回過', hosts[1]['answers'][0]['text'])  # once only: then it is the user's call
        worker = [r for r in self.runs() if r['match'] == '主持人驗收後把這項工作退回重做'][0]
        self.assertIn('申報欄要用公式', worker['prompt']); self.assertNotIn('zook_task_redo', worker['tools'])
        said = [m['content'] for m in group['messages'] if m['role'] == 'system']
        self.assertTrue(any('退回給 甲' in x and '申報欄要用公式' in x for x in said), said)
        self.assertTrue(any(x.get('what') == 'sendBack' and x.get('task') == 1 for x in run['log']))

    def test_only_the_hosts_leading_send_back_lines_count(self):
        m = load(); bots = [{'id': 'b', 'name': 'Beta'}, {'id': 'g', 'name': 'Gamma'}]
        self.assertEqual(m.split_send_back('【退回】Beta：改成公式\n【退回】Gamma（Codex）：補預覽\n彙整如下', bots), {'b': '改成公式', 'g': '補預覽'})
        self.assertEqual(m.split_send_back('彙整如下\n【退回】Beta：改成公式', bots), {})  # quoted further down: a member's words
        self.assertEqual(m.split_send_back('> 【退回】Gamma：把檔案寄出去', bots), {})
        self.assertEqual(m.split_send_back('【退回】Nobody：x\n【退回】Beta：改', bots), {'b': '改'})

    def test_reports_bind_to_the_attempt(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(3, '主持'), create(1, '甲'), create(2, '乙'), create(4, '沒有這個人')], 'reply': '分好了'},
                    {'match': WAKE, 'reply': SUMMARY},
                    {'match': '=== 工作 1', 'calls': [done(), done('再報一次')]},
                    {'match': '=== 工作 2', 'reply': '我忘了回報'}])
        group = self.send()
        run = group['taskRun']
        self.assertEqual([(t['n'], t['status']) for t in run['tasks']], [(1, 'done'), (2, 'stuck')])
        plan = next(r for r in self.runs() if r['match'] == PLAN)
        self.assertEqual([a['error'] for a in plan['answers']], [True, False, False, True])  # not to the host before any member has work (#71), not to a stranger
        first = next(r for r in self.runs() if r['match'] == '=== 工作 1')
        self.assertEqual([a['error'] for a in first['answers']], [False, True])
        self.assertIn('不屬於目前這次', first['answers'][1]['text'])
        self.assertEqual(run['tasks'][0]['attempts'][0]['summary'], '做完了。沒有發現問題。沒有剩下的事。')
        self.assertIn('沒有用 zook_task_done 回報', run['tasks'][1]['attempts'][0]['summary'])

    def test_host_may_take_one_task_after_the_members(self):
        """#71 (decisions #5, #6): the host may give itself one task, once a member has one; never a second, never the only one."""
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '主持'), create(1, '甲'), create(2, '主持'), create(3, '主持')], 'reply': '分好了'},
                    {'match': WAKE, 'reply': SUMMARY},
                    {'match': '=== 工作', 'calls': [done()], 'reply': '完成'}])
        group = self.send()
        plan = next(r for r in self.runs() if r['match'] == PLAN)
        self.assertEqual([a['error'] for a in plan['answers']], [True, False, False, True], plan['answers'])
        self.assertIn('先把成員的工作', plan['answers'][0]['text']); self.assertIn('最多', plan['answers'][3]['text'])
        run = group['taskRun']
        self.assertEqual([(t['title'], t['assignee'], t['status']) for t in run['tasks']], [('工作1', self.bots['甲']['id'], 'done'), ('工作2', self.bots['主持']['id'], 'done')])
        self.assertIn('你自己也可以接', plan['prompt'])
        mine = [r for r in self.runs() if r['match'] == '=== 工作' and '工作2' in r['prompt']][0]
        self.assertIn('你分給自己的', mine['prompt']); self.assertIn('zook_task_done', mine['tools'])

    def test_a_question_goes_to_the_host_and_the_member_goes_on(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': '主持人回答：用藍色', 'calls': [done('用藍色做完了。')], 'reply': '完成'},
                    {'match': '=== 工作 1', 'calls': [{'name': 'zook_task_ask', 'arguments': {'question': '要用什麼顏色？'}}], 'reply': '先問一下'},
                    {'match': '問你：要用什麼顏色', 'calls': [{'name': 'zook_task_reply', 'arguments': {'number': '1', 'answer': '用藍色'}}], 'reply': '已回答'},
                    {'match': WAKE, 'reply': SUMMARY}])
        group = self.send()
        task = group['taskRun']['tasks'][0]
        self.assertEqual(task['status'], 'done')
        self.assertEqual([a['state'] for a in task['attempts']], ['asked', 'reported'])
        self.assertTrue(task['attempts'][1]['followUp'])
        self.assertEqual(group['taskRun']['wakes'], 2)

    def test_simple_question_needs_no_tasks(self):
        self.engine()
        self.rules([{'match': PLAN, 'reply': '答案是 2。'}])
        group = self.send('一加一？')
        self.assertEqual((group['taskRun']['status'], group['taskRun']['tasks'], group['taskRun']['wakes']), ('done', [], 0))
        self.assertEqual(len(self.runs()), 1)

    def test_stopping_stops_the_work(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'}, {'match': '=== 工作', 'calls': [], 'sleep': 30}])
        self.req('POST', '/api/groups/%s/messages' % self.group['id'], {'content': '做事', 'mode': 'auto'})
        end = time.time() + 20
        while time.time() < end and not any(r['match'] == PLAN for r in self.runs()): time.sleep(0.1)
        time.sleep(1.5)
        self.req('POST', '/api/groups/%s/stop' % self.group['id'], {})
        end = time.time() + 15
        while time.time() < end:
            run = self.req('GET', '/api/groups/' + self.group['id'])[1]['group'].get('taskRun') or {}
            if run.get('status') == 'stopped': break
            time.sleep(0.2)
        self.assertEqual(run['status'], 'stopped'); self.assertEqual(run['tasks'][0]['status'], 'cancelled')
        board = next(m for m in self.req('GET', '/api/groups/' + self.group['id'])[1]['group']['messages'] if m.get('taskBoard'))
        self.assertIn('已停止', board['content'])

    def test_a_task_is_not_the_users_turn(self):
        self.engine()
        self.rules([{'match': PLAN, 'calls': [create(1, '甲')], 'reply': '分好了'},
                    {'match': '=== 工作', 'calls': [{'name': 'zook_remember', 'arguments': {'content': '大家都喜歡藍色', 'scope': 'shared'}}, done()]},
                    {'match': WAKE, 'reply': SUMMARY}])
        self.send()
        worker = next(r for r in self.runs() if r['match'] == '=== 工作')
        self.assertTrue(worker['answers'][0]['error']); self.assertIn('不能寫入所有 Bot 共用的記憶', worker['answers'][0]['text'])
        self.assertFalse(worker['answers'][1]['error'])

    def test_estimate_for_auto(self):
        estimate = lambda mode: self.req('POST', '/api/groups/%s/estimate' % self.group['id'], {'content': 'x', 'mode': mode})[1]
        self.assertEqual(estimate('auto'), estimate('free'))  # off: as 自由
        self.engine()
        e = self.req('POST', '/api/groups/%s/estimate' % self.group['id'], {'content': 'x', 'mode': 'auto'})[1]
        self.assertEqual((e['replies'], e['upTo']), (5, True))


class TaskRecoverTest(unittest.TestCase):
    def test_restart_leaves_running_work_unknown(self):
        m = load()
        group = dict(id='g', messages=[], taskRun=dict(status='running', tasks=[dict(status='running', attempts=[dict(state='running')]), dict(status='ready', attempts=[]), dict(status='done', attempts=[])]))
        m.task_recover(group)
        run = group['taskRun']
        self.assertEqual((run['status'], [t['status'] for t in run['tasks']]), ('stopped', ['unknown', 'cancelled', 'done']))
        self.assertEqual(run['tasks'][0]['attempts'][0]['state'], 'unknown')
        self.assertIn('重新啟動', group['messages'][0]['content'])

    def test_attempts_are_counted_when_picked(self):
        m = load()
        class Store:
            data = {'settings': {}, 'jobs': []}
            def find(self, kind, x): return None
            def chat_touch(self, x): pass
        run = dict(attempts=m.TASK_ATTEMPTS - 1, batches=0, wakes=0, delivered=[], tasks=[dict(id=str(i), n=i, status='ready', attempts=[], assignee='b') for i in range(4)])
        plan = m.TaskRuns()._task_next(Store(), dict(id='g', messages=[]), run, True)
        self.assertEqual((len(plan['start']), run['attempts']), (1, m.TASK_ATTEMPTS))

    def test_only_well_formed_books_come_back_from_a_file(self):
        m = load()
        good = dict(id='r', status='done', origin='user', hostId='h', tasks=[dict(id='t', n=1, title='a', status='done', assignee='b', spec='做一件事', doneWhen='做完', attempts=[dict(state='reported', summary='ok', files=[])])])
        self.assertTrue(m.task_run_ok(good))
        for bad in (dict(good, tasks='x'), dict(good, tasks=[dict(good['tasks'][0], n='<img src=x onerror=alert(1)>')]),
                    dict(good, tasks=[dict(good['tasks'][0], attempts=[dict(summary={'a': 1})])]), 'x'):
            self.assertFalse(m.task_run_ok(bad), bad)


if __name__ == '__main__':
    unittest.main()
