# -*- coding: utf-8 -*-
"""#245 群組「做完才查」（併 #145、#170、#226）: a member whose role is checking (查核員) is asked only after the members who make
the work have handed it in, and only when the files they said they handed in are really there. A file said to be handed in but
missing goes back to that member first; nothing handed in means no check. The checker only reads, and a copy of a file that is
already among the group's files is not kept twice."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = r'''#!/usr/bin/env python3
import json, os, re, sys, time
a = sys.argv[1:]; kind = os.path.basename(sys.argv[0])
if a[:2] == ['login', 'status']: print('Logged in using ChatGPT'); sys.exit(0)
if a[:2] == ['auth', 'status']: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if 'app-server' in a or '--help' in a or '--version' in a: sys.exit(0)
began = time.time()
s = sys.stdin.read() if '--prompt-file' not in a else ''
flag = lambda x: os.path.exists(os.environ['GROUP_LOG'] + '.' + x)
name = re.search(r'現在輪到你（(.+?)）回覆', s); name = name.group(1) if name else 'solo'
role = next((r for r, mark in (('split_check', '輪到你查核'), ('split_resave', 'Zook 檢查到'), ('split_redo', '主持人驗收後退回你的部分'), ('split_plan', '你負責分工'),
                               ('split_work', '只完成分派給你'), ('split_remerge', '第二次彙整'), ('split_merge', '你負責彙整'), ('work', '先獨立完成主持人分派'),
                               ('moderate', '閱讀成員剛才的發言'), ('final', '討論到此結束'), ('kickoff', '本次目標與產出')) if mark in s), 'free')
folder = re.search(r'要給群組的產出請存到 (.+?)（只放', s)
text = name + ' ' + role
def save(): open(os.path.join(folder.group(1), '報價單.xlsx'), 'w').write('quote')
if name == '專員' and role in ('split_work', 'work', 'split_redo'):
    if flag('fail'): time.sleep(0.2); sys.exit(3)
    if not flag('claim') and folder: save()
    text = '已存到群組檔案：報價單.xlsx'
if name == '專員' and role == 'split_resave':
    if flag('resave') and folder: save()
    text = '已存到群組檔案：報價單.xlsx'
if name == '查核員': text = '【判定】同意\n看過報價單.xlsx'
if role == 'kickoff': text = '目標：報價\n@專員：做報價單\n@查核員：檢查報價單'
if role in ('split_merge', 'split_remerge', 'final', 'moderate'): text = '【結論】好\n【待你決定】無\n【行動項目】無\n【未解問題】無'
if role == 'split_merge' and flag('sendback'): text = '【退回】專員：合計改成公式\n' + text
if 'DUPWRITE' in s and folder: open(os.path.join(folder.group(1), name + '-copy.txt'), 'w').write('same content')
if role == 'free' and name == 'solo': text = 'ok'
shared = re.search(r'群組共用檔案在 [^：]+：(.+?)。', s)
time.sleep(0.2)
open(os.environ['GROUP_LOG'], 'a').write(json.dumps(dict(name=name, role=role, began=began, ended=time.time(), readonly='只能讀取' in s, fix='合計改成公式' in s,
                                                         sees=shared.group(1) if shared else '', saves=bool(folder)), ensure_ascii=False) + '\n')
if kind == 'claude': print(json.dumps({'type': 'result', 'result': text, 'is_error': False}))
else: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})); print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 50}}))
'''


class CheckAfterDone(unittest.TestCase):
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
        self.bots = {n: self.req('POST', '/api/bots', {'name': n, 'provider': p})[1] for n, p in (('Alpha', 'codex'), ('專員', 'claude'), ('查核員', 'codex'))}

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def flag(self, name): Path(str(self.log) + '.' + name).write_text('x')

    def group(self, mode='split', names=('Alpha', '專員', '查核員'), host='Alpha'):
        status, group = self.req('POST', '/api/groups', {'botIds': [self.bots[n]['id'] for n in names], 'hostId': self.bots[host]['id'] if host else '', 'mode': mode})
        self.assertEqual(status, 201, group); return group

    def say(self, group, text='做一份報價單'):
        status, body = self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': text}); self.assertEqual(status, 202, body)
        for _ in range(300):
            found = self.req('GET', '/api/groups/' + group['id'])[1]['group']
            if found['status'] != 'running': return found
            time.sleep(.1)
        self.fail('discussion did not finish')

    def runs(self): return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []
    def order(self): return [(r['name'], r['role']) for r in self.runs()]
    def said(self, group): return [m['content'] for m in group['messages'] if m['role'] == 'system']

    def test_split_checker_waits_for_the_file(self):
        self.say(self.group())
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('專員', 'split_work'), ('查核員', 'split_check'), ('Alpha', 'split_merge')])
        work, check = self.runs()[1], self.runs()[2]
        self.assertGreaterEqual(check['began'], work['ended'])  # #145: never at the same time as the work it checks
        self.assertIn('報價單.xlsx', check['sees'])
        self.assertTrue(check['readonly']); self.assertFalse(check['saves'])  # #170: it only reads, so it cannot save a second copy

    def test_missing_file_goes_back_before_the_check(self):
        self.flag('claim'); self.flag('resave')
        found = self.say(self.group())
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('專員', 'split_work'), ('專員', 'split_resave'), ('查核員', 'split_check'), ('Alpha', 'split_merge')])
        self.assertTrue(any('先退回給 專員' in x and '報價單.xlsx' in x for x in self.said(found)), self.said(found))
        self.assertIn('報價單.xlsx', self.runs()[3]['sees'])

    def test_still_missing_after_one_resave_is_not_checked(self):
        self.flag('claim')
        found = self.say(self.group())
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('專員', 'split_work'), ('專員', 'split_resave'), ('Alpha', 'split_merge')])
        self.assertTrue(any('查核員 這次不查核' in x for x in self.said(found)), self.said(found))

    def test_nothing_handed_in_means_no_check(self):
        self.flag('fail')
        found = self.say(self.group())
        self.assertNotIn('查核員', [n for n, _ in self.order()])
        self.assertTrue(any('還沒交出成果' in x and '查核員' in x for x in self.said(found)), self.said(found))

    def test_host_sending_work_back_is_checked_again(self):
        self.flag('sendback')
        self.say(self.group())
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('專員', 'split_work'), ('查核員', 'split_check'), ('Alpha', 'split_merge'),
                                        ('專員', 'split_redo'), ('查核員', 'split_check'), ('Alpha', 'split_remerge')])

    def test_estimate_counts_the_second_check(self):
        e = self.req('POST', '/api/groups/%s/estimate' % self.group()['id'], {'content': '', 'mode': 'split'})[1]
        self.assertEqual((e['replies'], e.get('most')), (4, 7))

    def test_free_discussion_with_a_host_checks_after_the_work(self):
        self.say(self.group(mode='free'))
        order = self.order()
        self.assertEqual(order[:3], [('Alpha', 'kickoff'), ('專員', 'work'), ('查核員', 'split_check')])
        self.assertGreaterEqual(self.runs()[2]['began'], self.runs()[1]['ended'])
        self.assertTrue(self.runs()[2]['readonly'])

    def test_without_a_checker_nothing_changes(self):
        other = self.req('POST', '/api/bots', {'name': '設計', 'provider': 'codex'})[1]; self.bots['設計'] = other
        self.say(self.group(names=('Alpha', '專員', '設計')))
        self.assertEqual(self.order()[0], ('Alpha', 'split_plan')); self.assertEqual({x for x in self.order()[1:3]}, {('專員', 'split_work'), ('設計', 'split_work')})

    def test_a_copy_of_a_shared_file_is_not_kept_twice(self):
        g = self.group(mode='free', names=('專員', '查核員'), host='')
        self.say(g, 'DUPWRITE')
        names = [f['name'] for f in self.req('GET', '/api/groups/%s/files' % g['id'])[1]['files']]
        self.assertEqual(len([n for n in names if n.endswith('-copy.txt')]), 1, names)


if __name__ == '__main__': unittest.main()
