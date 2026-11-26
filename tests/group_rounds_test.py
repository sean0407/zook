# -*- coding: utf-8 -*-
"""回合 (#174, #133, #212, #219, #229): a round is every member an ask needs answering once; handing on and follow-ups are paid
from the same total; 「繼續」 gives the rounds again; the estimate says so."""
import http.client, importlib.util, json, os, re, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
CLI = r'''#!/usr/bin/env python3
import json, os, re, sys
a = sys.argv[1:]; kind = os.path.basename(sys.argv[0])
if a[:2] == ['login', 'status']: print('Logged in using ChatGPT'); sys.exit(0)
if a[:2] == ['auth', 'status']: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if 'app-server' in a or '--help' in a or '--version' in a: sys.exit(0)
s = sys.stdin.read() if '--prompt-file' not in a else ''
name = re.search(r'現在輪到你（(.+?)）回覆', s); name = name.group(1) if name else 'solo'
open(os.environ['GROUP_LOG'], 'a').write(json.dumps(dict(name=name)) + '\n')
order = ['Alpha', 'Beta', 'Gamma']
text = name + ' 的看法'
if name in order and os.path.exists(os.environ['GROUP_LOG'] + '.pingpong'):
    text = '@%s 請接著看' % order[(order.index(name) + 1) % 3] if name != 'Gamma' or not os.path.exists(os.environ['GROUP_LOG'] + '.two') else '@Beta 請接著看'
if kind == 'claude': print(json.dumps({'type': 'result', 'result': text, 'is_error': False}))
else: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})); print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 50}}))
'''


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_rounds', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class GroupRounds(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'runs.log'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', GROUP_LOG=str(self.log), ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        env.pop('ZOOK_GROUP_REPLY_CAP', None)
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bots = {n: self.req('POST', '/api/bots', {'name': n, 'provider': p})[1] for n, p in (('Alpha', 'codex'), ('Beta', 'claude'), ('Gamma', 'codex'))}

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def group(self, **fields):
        status, group = self.req('POST', '/api/groups', dict({'botIds': [self.bots[n]['id'] for n in ('Alpha', 'Beta', 'Gamma')], 'hostId': '', 'checkMode': 'none'}, **fields)); self.assertEqual(status, 201, group); return group

    def settle(self, group):
        for _ in range(300):
            found = self.req('GET', '/api/groups/' + group['id'])[1]['group']
            if found['status'] != 'running': return found
            time.sleep(.1)
        self.fail('discussion did not finish')

    def say(self, group, text='大家看一下', **fields):
        status, body = self.req('POST', '/api/groups/%s/messages' % group['id'], dict({'content': text}, **fields)); self.assertEqual(status, 202, body)
        return self.settle(group)

    def runs(self): return [json.loads(x)['name'] for x in self.log.read_text().splitlines()] if self.log.exists() else []
    def estimate(self, g, content='', mode='free'): return self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': content, 'mode': mode})[1]

    def test_a_round_is_everyone_answering_once(self):
        """Three members, 4 rounds: up to 12 replies, members handing on to each other included; then it pauses and says so in rounds."""
        Path(str(self.log) + '.pingpong').write_text('1')
        found = self.say(self.group(turnLimit=4))
        self.assertEqual(len(self.runs()), 12, self.runs())
        self.assertEqual(sorted(self.runs()[:3]), ['Alpha', 'Beta', 'Gamma'])  # round 1: each of them once
        self.assertIn('paused', found)
        said = found['messages'][-1]['content']
        self.assertIn('4 回合上限', said); self.assertIn('自動轉交', said); self.assertIn('再進行 4 回合', said)

    def test_handing_on_is_paid_from_the_same_total(self):
        """#212, #174: naming one member is a round of one reply; its @ to another member is the next reply of the same ask."""
        Path(str(self.log) + '.pingpong').write_text('1')
        g = self.group(turnLimit=4); found = self.say(g, '@Beta 改一下')
        self.assertEqual(self.runs(), ['Beta', 'Gamma', 'Alpha', 'Beta'])
        self.assertIn('4 回合上限', found['messages'][-1]['content'])
        self.assertEqual(self.req('POST', '/api/groups/%s/continue' % g['id'], {})[0], 202); found = self.settle(g)
        self.assertEqual(len(self.runs()), 8)  # 繼續: another 4 rounds of the same ask
        self.assertIn('paused', found)

    def test_a_new_ask_starts_afresh(self):
        g = self.group(turnLimit=4); self.say(g); self.say(g)
        self.assertEqual(len(self.runs()), 6)
        self.assertEqual(self.req('GET', '/api/groups/' + g['id'])[1]['group']['roundBudget']['used'], 3)

    def test_five_rounds_can_be_chosen(self):
        g = self.group()
        self.assertEqual(self.req('PATCH', '/api/groups/' + g['id'], {'turnLimit': 5})[0], 200)
        self.assertEqual(self.req('PATCH', '/api/groups/' + g['id'], {'turnLimit': 6})[0], 400)
        self.assertEqual(self.estimate(g)['rounds'], 5)

    def test_estimate_says_rounds_and_the_most_it_may_use(self):
        """#219: a limit of 8 is 8 rounds; the line says what one round is and the most the ask may use."""
        g = self.group(turnLimit=8)
        e = self.estimate(g)
        self.assertEqual((e['replies'], e['rounds'], e['responders'], e['cap']), (3, 8, 3, 24))
        self.assertIn('預計 3 次回覆（3 位各 1 次）', e['text']); self.assertIn('上限 8 回合，最多 24 次', e['text'])
        e = self.estimate(g, '@Beta 看一下')
        self.assertEqual((e['replies'], e['cap']), (1, 8)); self.assertIn('最多 8 次', e['text']); self.assertIn('自動轉交', e['text'])
        e = self.estimate(g, '', 'split')
        self.assertIn('主持人退回修正時最多', e['text'])

    def test_estimate_for_auto_says_it_goes_on_until_done(self):
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskEngine': True})[0], 200)
        g = self.group(hostId=self.bots['Alpha']['id'])
        e = self.estimate(g, 'x', 'auto')
        self.assertIn('做到達成為止', e['text']); self.assertIn('每 10 回合', e['text']); self.assertIn('要不要繼續', e['text'])

    def test_the_form_offers_rounds(self):
        js = (ROOT / 'frontend/js/35-groups.js').read_text(encoding='utf-8')
        self.assertIn('[4, 5, 8, 12, 16]', js); self.assertIn("n + ' 回合'", js); self.assertIn('e.text', js)


class Budget(unittest.TestCase):
    """插話 answered after the round pays from what the ask has left; a new message starts a new ask."""
    def setUp(self):
        self.m = load()
        bots = [dict(id=x, name=x) for x in ('a', 'b', 'c')]
        class Store:
            data = {'bots': bots, 'settings': {}}
            def find(self, kind, x): return next((b for b in bots if b['id'] == x), None)
        self.store = Store()
        self.group = dict(botIds=['a', 'b', 'c'], hostId='', turnLimit=4, messages=[dict(id='u1', role='user', content='hi')])

    def test_same_ask_keeps_what_was_used(self):
        b = self.m.group_round_budget(self.store, self.group, ['a', 'b', 'c'], True, 'free')
        self.assertEqual((b['responders'], self.m.round_cap(b['rounds'], b['responders']), b['used']), (3, 12, 0))
        self.m.round_spend(self.group, b, 7)
        self.group['messages'].append(dict(id='u2', role='user', content='@b 補一句', interjected=True))
        b = self.m.group_round_budget(self.store, self.group, ['b'], False, 'free')
        self.assertEqual((b['used'], b['responders']), (7, 3))
        self.m.round_continue(self.group)
        self.assertEqual(self.m.group_round_budget(self.store, self.group, ['b'], False, 'free')['used'], 0)

    def test_late_interjection_never_makes_the_total_bigger(self):
        b = self.m.group_round_budget(self.store, self.group, ['b'], False, 'free'); self.m.round_spend(self.group, b, 2)
        self.group['messages'].append(dict(id='u2', role='user', content='@所有人 也看看', interjected=True))
        b = self.m.group_round_budget(self.store, self.group, ['a', 'b', 'c'], True, 'free')
        self.assertEqual((b['used'], b['responders']), (2, 1))

    def test_books_from_a_file_cannot_put_the_check_far_off(self):
        run = dict(id='r', status='done', origin='user', hostId='h', tasks=[], wakes=3)
        self.assertTrue(self.m.task_run_ok(dict(run, roundCap=4 + self.m.TASK_CHECK_EVERY, boundary=dict(goal='g', doneWhen='d'), checkpoint=dict(state='asked', gate='x'))))
        for bad in (dict(run, roundCap=10 ** 6), dict(run, boundary='x'), dict(run, checkpoint=dict(state=5)), dict(run, goOn='yes'), dict(run, continued=-1)):
            self.assertFalse(self.m.task_run_ok(bad), bad)

    def test_a_new_message_and_own_runs(self):
        b = self.m.group_round_budget(self.store, self.group, ['b'], False, 'free'); self.m.round_spend(self.group, b, 4)
        self.group['messages'].append(dict(id='u3', role='user', content='新的問題'))
        self.assertEqual(self.m.group_round_budget(self.store, self.group, ['a', 'b', 'c'], True, 'free')['used'], 0)
        self.assertIsNone(self.m.group_round_budget(self.store, self.group, [], True, 'free', dict(own=True)))


if __name__ == '__main__':
    unittest.main()
