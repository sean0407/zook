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
    if flag('fail') or (role == 'split_redo' and flag('redofail')): time.sleep(0.2); sys.exit(3)
    if flag('slow'): time.sleep(3)
    if not flag('claim') and not flag('vague') and not (role == 'split_redo' and flag('redonosave')) and folder: save() if role != 'split_redo' else open(os.path.join(folder.group(1), '報價單.xlsx'), 'w').write('quote v2')
    text = ('已存好了。' if flag('vague') else '已存到群組檔案：報價單.xlsx') + ('\n@查核員 請幫我看' if flag('mention') else '')
if name == '設計' and role in ('split_work', 'work') and flag('designfail'): time.sleep(0.2); sys.exit(3)
if name == '專員' and role == 'split_resave':
    if flag('resave') and folder: open(os.path.join(folder.group(1), '報價單.xlsx'), 'w').write('quote resaved')
    text = '已存到群組檔案：報價單.xlsx' if not flag('cannot') else '這次存不了，權限不足。'
if name == '查核員': text = '【判定】同意\n看過報價單.xlsx'
if role == 'kickoff': text = '目標：報價\n@查核員：檢查使用者給的報價單' if flag('onlycheck') else '目標：報價\n@專員：做報價單' + ('' if flag('nocheck') else '\n@查核員：檢查報價單')
if role in ('split_merge', 'split_remerge', 'final', 'moderate'): text = '【結論】好\n【待你決定】無\n【行動項目】無\n【未解問題】無'
if role == 'split_merge' and flag('sendback'): text = '【退回】專員：合計改成公式\n' + text
if 'DUPWRITE' in s and folder: open(os.path.join(folder.group(1), name + '-copy.txt'), 'w').write('same content')
if role == 'free' and name == 'solo': text = 'ok'
shared = re.search(r'群組共用檔案在 [^：]+：(.+?)。', s)
time.sleep(0.2)
open(os.environ['GROUP_LOG'], 'a').write(json.dumps(dict(name=name, role=role, began=began, ended=time.time(), readonly='只能讀取' in s, fix='合計改成公式' in s,
                                                         sees=shared.group(1) if shared else '', saves=bool(folder), args=' '.join(a)), ensure_ascii=False) + '\n')
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

    def test_a_resave_that_does_not_name_the_file_is_still_looked_for(self):
        self.flag('claim'); self.flag('cannot')
        self.say(self.group())
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('專員', 'split_work'), ('專員', 'split_resave'), ('Alpha', 'split_merge')])

    def test_a_failed_redo_is_not_checked_as_the_old_version(self):
        self.flag('sendback'); self.flag('redofail')
        found = self.say(self.group())
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('專員', 'split_work'), ('查核員', 'split_check'), ('Alpha', 'split_merge'), ('Alpha', 'split_remerge')])  # the redo failed (it logs nothing): no check of the old version
        self.assertTrue(any('還沒交出成果' in x for x in self.said(found)), self.said(found))

    def test_the_check_runs_read_only_where_the_cli_can(self):
        self.say(self.group())
        check = next(r for r in self.runs() if r['role'] == 'split_check'); plan = next(r for r in self.runs() if r['role'] == 'split_plan')  # both Codex
        self.assertIn('read-only', check['args']); self.assertNotIn('read-only', plan['args'])

    def test_one_member_not_handing_in_holds_the_whole_check(self):
        self.flag('designfail'); self.bots['設計'] = self.req('POST', '/api/bots', {'name': '設計', 'provider': 'codex'})[1]
        found = self.say(self.group(names=('Alpha', '專員', '設計', '查核員')))
        self.assertNotIn('查核員', [n for n, _ in self.order()])
        self.assertTrue(any('設計 還沒交出成果' in x for x in self.said(found)), self.said(found))

    def test_a_member_naming_the_checker_does_not_start_it_early(self):
        self.flag('mention')
        self.say(self.group(mode='free'))
        self.assertEqual([r for n, r in self.order() if n == '查核員'], ['split_check'])
        self.assertEqual(self.order()[:3], [('Alpha', 'kickoff'), ('專員', 'work'), ('查核員', 'split_check')])

    def test_a_checker_named_only_later_still_waits_for_the_check(self):
        self.flag('mention'); self.flag('nocheck')
        self.say(self.group(mode='free'))
        self.assertEqual(self.order()[:3], [('Alpha', 'kickoff'), ('專員', 'work'), ('查核員', 'split_check')])
        self.assertEqual([r for n, r in self.order() if n == '查核員'], ['split_check'])

    def test_a_persona_that_says_it_does_not_check_is_a_maker(self):
        self.bots['報價'] = self.req('POST', '/api/bots', {'name': '報價', 'provider': 'codex', 'persona': '我不是負責查核的，主要做報價單。'})[1]
        self.bots['審'] = self.req('POST', '/api/bots', {'name': '小審', 'provider': 'codex', 'persona': '負責驗收其他成員的成果。'})[1]
        self.bots['驗'] = self.req('POST', '/api/bots', {'name': '小驗', 'provider': 'codex', 'persona': '你擔任驗收角色，看別人的成果。'})[1]
        g = self.req('POST', '/api/groups', {'botIds': [self.bots[n]['id'] for n in ('Alpha', '報價', '審', '驗')], 'hostId': self.bots['Alpha']['id'], 'mode': 'split'})[1]
        self.say(g)
        order = [x[0] for x in self.order()]
        self.assertEqual((order[:2], set(order[2:4]), order[4:]), (['Alpha', '報價'], {'小審', '小驗'}, ['Alpha']))

    def test_saying_saved_with_nothing_saved_goes_back_first(self):
        self.flag('vague'); self.flag('resave')
        found = self.say(self.group())
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('專員', 'split_work'), ('專員', 'split_resave'), ('查核員', 'split_check'), ('Alpha', 'split_merge')])
        self.assertTrue(any('先退回給 專員' in x for x in self.said(found)), self.said(found))

    def test_a_checker_named_alone_still_only_reads(self):
        self.flag('onlycheck')
        self.say(self.group(mode='free'))
        self.assertEqual(self.order()[:2], [('Alpha', 'kickoff'), ('查核員', 'split_check')])
        self.assertNotIn(('專員', 'work'), self.order())
        self.assertIn('read-only', self.runs()[1]['args'])

    def test_a_cli_that_cannot_only_read_does_not_check(self):
        cli = self.root / 'bin/echo-cli'; cli.write_text('#!/bin/sh\necho custom >> "$GROUP_LOG.custom"\necho ok\n'); cli.chmod(0o755)
        status, item = self.req('POST', '/api/accounts/custom', {'name': 'Echo CLI', 'command': 'echo-cli', 'status': 'echo-cli'}); self.assertEqual(status, 201, item)
        self.assertEqual(self.req('PATCH', '/api/bots/' + self.bots['查核員']['id'], {'provider': item['id']})[0], 200)
        found = self.say(self.group())
        self.assertFalse(Path(str(self.log) + '.custom').exists())  # never started: it could have changed files
        self.assertTrue(any('查核員' in x and '只讀' in x for x in self.said(found)), self.said(found))

    def test_host_and_a_checker_only(self):
        self.say(self.group(names=('Alpha', '查核員')))
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('查核員', 'split_check'), ('Alpha', 'split_merge')])
        self.assertIn('read-only', self.runs()[1]['args'])

    def test_redone_work_must_save_the_new_version(self):
        self.flag('sendback'); self.flag('redonosave'); self.flag('resave')
        self.say(self.group())
        self.assertEqual(self.order(), [('Alpha', 'split_plan'), ('專員', 'split_work'), ('查核員', 'split_check'), ('Alpha', 'split_merge'),
                                        ('專員', 'split_redo'), ('專員', 'split_resave'), ('查核員', 'split_check'), ('Alpha', 'split_remerge')])

    def test_the_user_naming_the_checker_mid_work_waits_for_the_check(self):
        self.flag('slow'); g = self.group(mode='free')
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '做一份報價單'})[0], 202)
        for _ in range(100):
            found = self.req('GET', '/api/groups/' + g['id'])[1]['group']
            if any(m.get('botId') == self.bots['專員']['id'] and m.get('status') == 'running' for m in found['messages']): break
            time.sleep(.1)
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % g['id'], {'content': '@查核員 先看一下'})[0], 202)
        for _ in range(300):
            if self.req('GET', '/api/groups/' + g['id'])[1]['group']['status'] != 'running': break
            time.sleep(.1)
        self.assertEqual([r for n, r in self.order() if n == '查核員'], ['split_check'])
        work = next(r for r in self.runs() if r['name'] == '專員'); check = next(r for r in self.runs() if r['name'] == '查核員')
        self.assertGreaterEqual(check['began'], work['ended'])

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
