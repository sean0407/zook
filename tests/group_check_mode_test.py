# -*- coding: utf-8 -*-
"""#296 群組「驗收方式」: the group form says who checks (自動請一位別家成員、不驗收、同家複查、指定查核員) instead of telling the
checker by its name (#245, kept for groups from before the form had it). #318①: in 輪流、比較、辯論 the check also waits for the
work to be handed in. #294: a new group with a name already taken is numbered, and the group's 長期指示 reach every reply."""
import http.client, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_check_mode', SERVER); server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)
CLI = r'''#!/usr/bin/env python3
import json, os, re, sys, time
a = sys.argv[1:]; kind = os.path.basename(sys.argv[0])
if a[:2] == ['login', 'status']: print('Logged in using ChatGPT'); sys.exit(0)
if a[:2] == ['auth', 'status']: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if 'app-server' in a or '--help' in a or '--version' in a: sys.exit(0)
s = sys.stdin.read() if '--prompt-file' not in a else ''
name = re.search(r'現在輪到你（(.+?)）回覆', s); name = name.group(1) if name else 'solo'
role = next((r for r, mark in (('check', '輪到你查核'), ('turn', '現在是輪流發言'), ('compare_diff', '比較他們的答案'), ('compare', '你看不到他們的內容'),
                               ('verdict', '裁定者'), ('debate', '這是一場辯論'), ('debate', '這是辯論的第二回合'), ('final', '討論到此結束')) if mark in s), 'free')
if os.path.exists(os.environ['GROUP_LOG'] + '.fail.' + name) and role != 'check': time.sleep(0.2); sys.exit(3)
time.sleep(0.2)
open(os.environ['GROUP_LOG'], 'a').write(json.dumps(dict(name=name, role=role, readonly='只能讀取' in s, standing='每週一交週報' in s, tagged='（查核員：' in s), ensure_ascii=False) + '\n')
text = '【判定】同意' if role == 'check' else '【結論】好\n【待你決定】無\n【行動項目】無\n【未解問題】無' if role in ('final', 'verdict', 'compare_diff') else name + ' 的看法'
if kind == 'claude': print(json.dumps({'type': 'result', 'result': text, 'is_error': False}))
else: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})); print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 50}}))
'''


class FakeStore:
    def __init__(self, bots): self.data = dict(bots=bots, settings={}); self.by = {b['id']: b for b in bots}
    def find(self, kind, x): return self.by.get(x)


class Picking(unittest.TestCase):
    def store(self, *providers, names=None):
        return FakeStore([dict(id='b%d' % i, name=(names or {}).get(i, 'B%d' % i), provider=p) for i, p in enumerate(providers)])

    def test_auto_asks_a_member_of_another_vendor(self):
        store = self.store('codex', 'codex', 'claude')
        self.assertEqual(server.group_checkers(store, dict(botIds=['b0', 'b1', 'b2'], hostId='', checkMode='auto')), ['b2'])
        self.assertEqual(server.group_checkers(store, dict(botIds=['b2', 'b0', 'b1'], hostId='b2', checkMode='auto')), ['b1'])  # never the host; the later one on a tie

    def test_auto_with_one_vendor_has_no_checker_and_same_vendor_has(self):
        store = self.store('codex', 'codex', 'codex')
        group = dict(botIds=['b0', 'b1', 'b2'], hostId='b0')
        self.assertEqual(server.group_checkers(store, dict(group, checkMode='auto')), [])
        self.assertEqual(server.group_checkers(store, dict(group, checkMode='same')), ['b2'])

    def test_pick_none_and_too_few(self):
        store = self.store('codex', 'claude', 'codex', names={2: '查核員'})
        group = dict(botIds=['b0', 'b1', 'b2'], hostId='b0')
        self.assertEqual(server.group_checkers(store, dict(group, checkMode='pick', checkerId='b2')), ['b2'])
        self.assertEqual(server.group_checkers(store, dict(group, checkMode='pick', checkerId='gone')), ['b1'])  # left the group: picked as 自動
        self.assertEqual(server.group_checkers(store, dict(group, checkMode='none')), [])  # 「查核員」 by name is a maker now
        self.assertEqual(server.group_checkers(store, dict(group)), ['b2'])  # from before 驗收方式: by its name, as #245 did
        self.assertEqual(server.group_checkers(store, dict(botIds=['b0', 'b1'], hostId='b0', checkMode='auto')), ['b1'])  # the host makes the work, the other vendor checks it
        self.assertEqual(server.group_checkers(store, dict(botIds=['b0', 'b1'], hostId='b0', checkMode='same')), [])  # no member of the same vendor
        self.assertEqual(server.group_checkers(store, dict(botIds=['b0', 'b1', 'b2'], hostId='', checkMode='same')), ['b2'])  # the same vendor as the most others
        self.assertEqual(server.group_checkers(store, dict(botIds=['b1', 'b0', 'b2'], hostId='', checkMode='same')), ['b2'])
        self.assertEqual(server.group_checkers(store, dict(botIds=['b0'], hostId='', checkMode='auto')), [])  # nobody left to make the work
        self.assertEqual(server.group_checkers(store, dict(group, checkMode='auto'), engine=True), [])  # 任務引擎 checks every task by another vendor already
        self.assertEqual(server.group_checkers(store, dict(group, checkMode='pick', checkerId='b2'), engine=True), ['b2'])

    def test_a_paused_check_goes_to_who_checks_now(self):
        store = self.store('codex', 'codex', 'claude', 'claude')
        paused = dict(kind='steps', steps=[dict(role='split_check', bots=['b2'], gate=['b0', 'b1']), dict(role='final', bots=['b0'])])
        group = dict(botIds=['b0', 'b1', 'b2', 'b3'], hostId='b0')
        self.assertEqual([s['role'] for s in server.current_paused(store, dict(group, checkMode='none'), paused)['steps']], ['final'])
        self.assertEqual(server.current_paused(store, dict(group, checkMode='pick', checkerId='b3'), paused)['steps'][0]['bots'], ['b3'])
        self.assertEqual(server.current_paused(store, dict(group, checkMode='auto'), paused)['steps'][0]['bots'], ['b3'])

    def test_check_mode_cannot_change_mid_discussion(self):
        store = self.store('codex', 'claude', 'codex')
        group = dict(botIds=['b0', 'b1', 'b2'], hostId='b0', status='running', checkMode='auto', name='g')
        with self.assertRaises(ValueError): server.set_group_fields(store, group, {'checkMode': 'none'})
        server.set_group_fields(store, group, {'checkMode': 'auto', 'checkerId': ''})  # unchanged: fine
        legacy = dict(group); legacy.pop('checkMode'); server.set_group_fields(store, legacy, {'checkMode': 'name'})

    def test_numbered_name(self):
        self.assertEqual(server.numbered_name('週會', ['週會', '週會（2）']), '週會（3）')
        self.assertEqual(server.numbered_name('週會', ['其他']), '週會')
        self.assertEqual(len(server.numbered_name('長' * 100, ['長' * 100])), 100)


class GroupForm(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'runs.log'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', GROUP_LOG=str(self.log), ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        env.pop('ZOOK_GROUP_REPLY_CAP', None)
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.req('PATCH', '/api/settings', {'permissionMode': 'auto'})
        self.bots = {n: self.req('POST', '/api/bots', {'name': n, 'provider': p})[1] for n, p in (('甲', 'codex'), ('乙', 'codex'), ('丙', 'claude'), ('查核員', 'codex'))}

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def group(self, mode, names=('甲', '乙', '丙'), **more):
        status, group = self.req('POST', '/api/groups', dict({'botIds': [self.bots[n]['id'] for n in names], 'hostId': '', 'mode': mode, 'checkMode': 'auto'}, **more))
        self.assertEqual(status, 201, group); return group

    def say(self, group, text='週末去哪裡好'):
        status, body = self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': text}); self.assertEqual(status, 202, body)
        for _ in range(300):
            found = self.req('GET', '/api/groups/' + group['id'])[1]['group']
            if found['status'] != 'running': return found
            time.sleep(.1)
        self.fail('discussion did not finish')

    def runs(self): return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []
    def order(self): return [(r['name'], r['role']) for r in self.runs()]

    def test_turns_checked_by_the_other_vendor_after_the_work(self):
        self.say(self.group('turns', names=('丙', '甲', '乙')))
        self.assertEqual(self.order(), [('甲', 'turn'), ('乙', 'turn'), ('丙', 'check')])
        self.assertTrue(self.runs()[2]['readonly']); self.assertTrue(self.runs()[0]['tagged'])  # everyone knows who checks

    def test_turns_with_a_member_failing_is_not_checked(self):  # #318①
        Path(str(self.log) + '.fail.乙').write_text('x')
        found = self.say(self.group('turns'))
        self.assertNotIn(('丙', 'check'), self.order())
        self.assertTrue(any('不用查核' in m['content'] for m in found['messages'] if m['role'] == 'system'))

    def test_compare_checks_before_the_comparison(self):
        g = self.group('compare', names=('甲', '乙', '丙', '查核員'), hostId=self.bots['甲']['id'])
        self.say(g)
        order = self.order()
        self.assertEqual(order[-2:], [('丙', 'check'), ('甲', 'compare_diff')])
        self.assertEqual(sorted(order[:3]), [('乙', 'compare'), ('查核員', 'compare'), ('甲', 'compare')])  # 不看名稱：「查核員」 makes the work

    def test_compare_with_a_member_failing_is_not_checked(self):  # #318①
        Path(str(self.log) + '.fail.乙').write_text('x')
        self.say(self.group('compare', names=('甲', '乙', '丙', '查核員'), hostId=self.bots['甲']['id']))
        self.assertNotIn(('丙', 'check'), self.order())

    def test_debate_checks_before_the_verdict(self):
        self.say(self.group('debate', names=('甲', '乙', '查核員', '丙'), hostId=self.bots['甲']['id']))
        order = self.order()
        self.assertEqual(order[-2:], [('丙', 'check'), ('甲', 'verdict')])
        self.assertNotIn('丙', [n for n, r in order if r == 'debate'])

    def test_no_check_and_the_name_no_longer_decides(self):
        self.say(self.group('turns', names=('甲', '查核員', '丙'), checkMode='none'))
        self.assertEqual(self.order(), [('甲', 'turn'), ('查核員', 'turn'), ('丙', 'turn')])
        self.assertFalse(any(r['readonly'] for r in self.runs() if r['name'] == '查核員'))

    def test_picked_checker_and_its_checks(self):
        ids = {n: b['id'] for n, b in self.bots.items()}
        self.assertEqual(self.req('POST', '/api/groups', {'botIds': [ids['甲'], ids['乙']], 'checkMode': 'pick', 'checkerId': ids['丙']})[0], 400)
        self.assertEqual(self.req('POST', '/api/groups', {'botIds': [ids['甲'], ids['乙']], 'hostId': ids['乙'], 'checkMode': 'pick', 'checkerId': ids['乙']})[0], 400)
        self.assertEqual(self.req('POST', '/api/groups', {'botIds': [ids['甲'], ids['乙']], 'checkMode': 'later'})[0], 400)
        g = self.group('turns', names=('甲', '乙', '丙'), checkMode='pick', checkerId=ids['甲'])
        self.say(g); self.assertEqual(self.order(), [('乙', 'turn'), ('丙', 'turn'), ('甲', 'check')])

    def test_same_name_is_numbered_and_standing_instructions_reach_replies(self):
        first = self.group('turns', name='週會'); second = self.group('turns', name='週會'); third = self.group('turns', name='週會')
        self.assertEqual([first['name'], second['name'], third['name']], ['週會', '週會（2）', '週會（3）'])
        status, saved = self.req('PATCH', '/api/groups/' + first['id'], {'instructions': '每週一交週報', 'checkMode': 'none', 'name': '週會'})
        self.assertEqual(status, 200, saved); self.assertEqual((saved['instructions'], saved['checkMode'], saved['name']), ('每週一交週報', 'none', '週會'))
        self.assertEqual(self.req('PATCH', '/api/groups/' + first['id'], {'instructions': 'x' * 4001})[0], 400)
        self.say(first)
        self.assertTrue(self.runs() and all(r['standing'] for r in self.runs()))


if __name__ == '__main__': unittest.main()
