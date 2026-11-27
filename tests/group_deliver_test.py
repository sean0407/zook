# -*- coding: utf-8 -*-
"""群組回覆次數與交件判斷 (#312, #91⑥, #110⑥, #266, #327, #335, #319, #326, #291, #273④, #140③): a check asked for is paid from the
ask's rounds and the estimate counts checks; 「說交了但沒有」 only for a member saying it handed a file over; a deck's note belongs to
the member that saved it and a wide deck labelled 4:3 is not reported to the user; the place the user named reaches every member and
is looked at; a host asking the user first starts nobody; a check left 「正在查核」 is marked failed."""
import datetime, http.client, json, os, shutil, subprocess, sys, tempfile, time, unittest, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xlsxcheck_test import load  # noqa: E402

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
open(os.environ['GROUP_LOG'], 'a').write(json.dumps(dict(name=name, prompt=s)) + '\n')
said = json.load(open(os.environ['GROUP_SAY'])) if os.path.exists(os.environ['GROUP_SAY']) else {}
text = said.get(name) or (name + ' 的看法')
if kind == 'claude': print(json.dumps({'type': 'result', 'result': text, 'is_error': False}))
else: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})); print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 50}}))
'''
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
m = load()


def deck(path, size):
    with zipfile.ZipFile(str(path), 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('ppt/presentation.xml', '<?xml version="1.0"?><p:presentation xmlns:p="%s" xmlns:r="%s"><p:sldIdLst/>%s</p:presentation>' % (P, R, size))
        z.writestr('ppt/_rels/presentation.xml.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')


class Server(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'runs.log'; self.says = self.root / 'say.json'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', GROUP_LOG=str(self.log),
                   GROUP_SAY=str(self.says), ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
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

    def runs(self): return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []
    def estimate(self, g, content='', mode='free'): return self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': content, 'mode': mode})[1]

    def test_a_check_asked_for_is_paid_from_the_rounds_of_the_ask(self):
        """#266②, #273⑤: 請其他成員查核 is a reply of the same ask; it never starts the count again."""
        g = self.group(turnLimit=4); found = self.say(g)
        self.assertEqual(found['roundBudget']['used'], 3)
        reply = next(x for x in found['messages'] if x.get('botId') == self.bots['Alpha']['id'])
        status, body = self.req('POST', '/api/groups/%s/messages/%s/verify' % (g['id'], reply['id']), {'confirm': True}); self.assertEqual(status, 202, body)
        found = self.settle(g)
        self.assertEqual(found['roundBudget']['used'], 4)

    def test_estimate_counts_checks_and_redoing(self):
        """#312, #91⑥, #110⑥: a 分工 group with a checker says the range, with the check and a redo in it."""
        g = self.group(hostId=self.bots['Alpha']['id'], checkMode='pick', checkerId=self.bots['Gamma']['id'], turnLimit=4)
        e = self.estimate(g, '', 'split')
        self.assertEqual(e['replies'], 4)  # the host plans, Beta works, Gamma checks, the host merges
        self.assertEqual(e['most'], 9)  # Beta saves again and Gamma checks again; Beta redoes, Gamma checks again, the host merges again
        self.assertIn('預計 4–9 次回覆', e['text']); self.assertIn('含查核', e['text'])

    def test_estimate_for_auto_counts_the_checks(self):
        """#312: 自動 said 「預計至少 4 次，驗收與重做另計」; the checks are counted now."""
        self.assertEqual(self.req('PATCH', '/api/settings', {'taskEngine': True})[0], 200)
        g = self.group(hostId=self.bots['Alpha']['id'])
        e = self.estimate(g, 'x', 'auto')
        self.assertEqual(e['replies'], 6)  # the host plans, two members work, each work is checked by another vendor, the host sums up
        self.assertIn('含驗收', e['text']); self.assertNotIn('驗收和重做另計', e['text']); self.assertIn('30 次回覆', e['text'])

    def test_a_host_asking_the_user_first_starts_nobody(self):
        """#335: 「確認完再交給專員開工」 does not start the members."""
        self.says.write_text(json.dumps({'Alpha': '本次目標與產出：尾牙企劃\n日期和預算還不清楚，確認完再交給專員開工。\n1. 預算多少？'}))
        found = self.say(self.group(hostId=self.bots['Alpha']['id'], mode='split'), '幫我規劃尾牙')
        self.assertEqual([r['name'] for r in self.runs()], ['Alpha'])
        self.assertTrue(any('主持人要先問你' in (x.get('content') or '') for x in found['messages']))

    def test_a_host_named_alone_asking_first_hands_nothing_out(self):
        """#335: also when only the host is named in 分工, asking the user first starts nobody."""
        self.says.write_text(json.dumps({'Alpha': '【先問你】\n1. 預算多少？\n【派工】Beta：做報價單'}))
        found = self.say(self.group(hostId=self.bots['Alpha']['id'], mode='split'), '@Alpha 再補一份報價')
        self.assertEqual([r['name'] for r in self.runs()], ['Alpha'])
        self.assertTrue(any('主持人要先問你' in (x.get('content') or '') for x in found['messages']))

    def test_estimate_counts_the_check_of_named_work(self):
        """#312: naming the host alone, or one maker, still counts the check and the redo."""
        g = self.group(hostId=self.bots['Alpha']['id'], checkMode='pick', checkerId=self.bots['Gamma']['id'], turnLimit=4)
        e = self.estimate(g, '@Alpha 再改一下', 'split')
        self.assertEqual(e['most'], 9); self.assertIn('預計最多 9 次回覆', e['text'])
        e = self.estimate(g, '@Beta 改一下', 'split')
        self.assertEqual((e['replies'], e['most']), (2, 4)); self.assertIn('含查核', e['text'])  # Beta works, Gamma checks; Beta saves again, Gamma checks again

    def test_the_place_the_user_named_reaches_every_member(self):
        """#273④, #266①: every member is told where the user wants the results."""
        place = Path(tempfile.mkdtemp(dir='/tmp')) / '交件'  # a folder of the Mac's own (/var/folders) is never read as a place
        self.addCleanup(shutil.rmtree, str(place.parent))
        self.say(self.group(), '做一份報價單，存到 %s' % place)
        prompts = [r['prompt'] for r in self.runs()]
        self.assertEqual(len(prompts), 3)
        for p in prompts: self.assertIn('使用者指定的存檔位置：%s' % place, p)

    def test_the_host_adds_no_conditions_of_its_own(self):
        """#140③: the host hands out only what the user asked for."""
        self.say(self.group(hostId=self.bots['Alpha']['id'], mode='split'), '做一份名單')
        plan = next(r['prompt'] for r in self.runs() if r['name'] == 'Alpha')
        self.assertIn('使用者沒說的條件', plan); self.assertIn('【先問你】', plan)


class Units(unittest.TestCase):
    def setUp(self): self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))
    def tearDown(self): self.temp.cleanup()

    def test_only_a_member_saying_it_handed_a_file_over_is_held_to_it(self):
        """#319, #326, #340: naming a file while handing work out, asking or checking is not saying it was handed over."""
        self.assertEqual(m.delivery_claims('@專員：請做 報價單.xlsx，存到群組檔案。', ['專員'], 'split_plan'), '')
        self.assertEqual(m.delivery_claims('B-設計 交了 approval-card.jpg，我來查。', [], 'split_check'), '')
        self.assertEqual(m.delivery_claims('approval-card.jpg 要存到群組檔案。', [], None), '')
        self.assertEqual(m.delivery_claims('B-設計已存好 approval-card.jpg。', ['B-設計'], 'split_merge'), '')
        self.assertIn('報價單.xlsx', m.delivery_claims('我已存到群組檔案：報價單.xlsx。', [], 'split_work'))
        self.assertIn('報價單.xlsx', m.delivery_claims('已存好 報價單.xlsx，請 B-查核 看一下', ['B-查核'], 'split_work'))  # naming who checks next is still its own claim
        self.assertEqual(m.delivery_claims('報價單.xlsx 已交付，但尚未存到群組檔案。', [], 'split_work'), '')  # not done after all
        self.assertEqual(m.delivery_claims('報價單.xlsx 工作已完成。', [], 'split_work'), '')  # the work, not a file handed over
        self.assertEqual(m.delivery_claims('報價單.xlsx 已存好，但沒有成功。', [], 'split_work'), '')
        said = m.delivery_claims('已存到群組檔案：\n- 報價單.xlsx\n- 說明.docx\n\n後續請主持人確認 草稿.md', [], 'split_work')
        self.assertIn('說明.docx', said); self.assertNotIn('草稿.md', said)

    def test_a_wide_deck_labelled_four_three_is_not_reported_to_the_user(self):
        """#326②: a 16:9 deck from python-pptx keeps type="screen4x3"; it opens wide, so the user is not warned. The Bot still is."""
        path = self.root / 'a.pptx'; deck(path, '<p:sldSz cx="12191695" cy="6858000" type="screen4x3"/>')
        scan = m.pptx_scan(str(path))
        self.assertEqual(m.pptx_render([list(x) for x in scan]), [])
        self.assertIn('sldSz', ' '.join(m.pptx_render([list(x) for x in scan], for_bot=True)))
        deck(path, '<p:sldSz cx="7772400" cy="10058400" type="screen4x3"/>')  # named 4:3, drawn as a page: still said
        self.assertIn('投影片大小', ' '.join(m.pptx_render([list(x) for x in m.pptx_scan(str(path))])))

    def test_a_deck_copied_in_from_the_group_is_not_the_members(self):
        """#326②: the note goes under the member that saved the deck, not under every member Zook copied it to."""
        store = m.Store(self.root / 'data'); m._active['data'] = store.data
        bot = dict(id='c' * 32, name='B-查核', access='full'); store.data['bots'].append(bot)
        group = dict(id='g1', name='組', botIds=[bot['id']], messages=[], status='idle'); store.data['groups'].append(group)
        shared = m.group_files_dir(store, 'g1'); shared.mkdir(parents=True); deck(shared / '提案.pptx', '<p:sldSz cx="7772400" cy="10058400" type="screen4x3"/>')
        start = time.time() - 1
        copies = m.group_copy_folder(store, bot['id']); copies.mkdir(parents=True); (copies / '提案.pptx').write_bytes((shared / '提案.pptx').read_bytes())
        iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
        msg = dict(id='m1', role='assistant', botId=bot['id'], content='看過了', status='completed'); group['messages'].append(msg)
        job = dict(id='j1', botId=bot['id'], groupId='g1', messageId='m1', status='completed', content='看過了', createdAt=iso(start), finishedAt=iso(time.time() + 1), toolCalls=[])
        store.data['jobs'].append(job)
        m.group_copies_seen('j1', {'提案.pptx': m._file_hash(copies / '提案.pptx')})  # as Zook copied it in for this reply
        deck(shared / '提案.pptx', '<p:sldSz cx="7772400" cy="10058400" type="screen16x9"/>')  # another member changed the group's file meanwhile
        self.assertTrue(m.group_copy_unchanged(store, 'j1', bot['id'], str(copies / '提案.pptx')))
        m.xlsx_after_reply(store, 'j1')
        self.assertNotIn('pptxIssues', job); self.assertNotIn('note', msg)
        deck(copies / '提案.pptx', '<p:sldSz cx="7772400" cy="10058400" type="screen16x9"/>')  # changed by the member: its own
        self.assertFalse(m.group_copy_unchanged(store, 'j1', bot['id'], str(copies / '提案.pptx')))
        m.group_copies_seen('j1'); self.assertFalse(m.group_copy_unchanged(store, 'j1', bot['id'], str(copies / '提案.pptx')))

    def test_the_place_the_user_named_is_read_and_looked_at(self):
        home = os.path.expanduser('~')
        g = dict(messages=[dict(id='u', role='user', content='依 /tmp/zk-src/價目表.xlsx 做報價，存到/tmp/zk-place/尾牙企劃裡，另外也放一份到 ~/Desktop/交件/')])
        self.assertEqual(m.asked_places(g), ['/tmp/zk-place/尾牙企劃', home + '/Desktop/交件'])  # the file given to read is not a place to save to
        self.assertEqual(m.asked_places(dict(messages=[dict(id='u', role='user', content='做一份報價單')])), [])
        self.assertEqual(m.asked_places(dict(messages=[dict(id='u', role='user', content='存到「/tmp/zk place/Q4 報價」')])), ['/tmp/zk place/Q4 報價'])  # quoted: spaces kept
        self.assertEqual(m.asked_places(dict(messages=[dict(id='u', role='user', content='存到 /System/x/y')])), [])  # the Mac's own folders never
        self.assertEqual(m.asked_places(dict(messages=[dict(id='u', role='user', content='存到 /tmp/../etc/x')])), [])  # not by going up either
        link = self.root / 'sys'; os.symlink('/System', str(link))
        self.assertEqual(m.asked_places(dict(messages=[dict(id='u', role='user', content='存到 %s/Library' % link)])), [])  # nor through a link
        self.assertEqual(m.asked_places(dict(messages=[dict(id='u', role='user', content='存到「/tmp/我的資料夾」')])), ['/tmp/我的資料夾'])  # quoted: taken as it is
        rules = ' '.join(m.asked_place_rules(g, True, 'split_work'))
        self.assertIn('/tmp/zk-place/尾牙企劃', rules); self.assertIn('另存一份', rules); self.assertIn('不要說下一則再存', rules)
        self.assertIn('確認成品也存到', ' '.join(m.asked_place_rules(g, False, 'split_check')))

    def test_a_member_that_skipped_the_place_is_found(self):
        store = m.Store(self.root / 'data'); place = Path(tempfile.mkdtemp(dir='/tmp')) / '交件'; place.mkdir()
        self.addCleanup(shutil.rmtree, str(place.parent))
        group = dict(id='g1', name='組', botIds=[], status='idle', messages=[dict(id='u', role='user', content='存到 %s' % place)]); store.data['groups'].append(group)
        job = dict(id='j1', createdAt=datetime.datetime.fromtimestamp(time.time() - 2, datetime.timezone.utc).isoformat()); store.data['jobs'].append(job)
        turn = dict(job=job, role='split_work')
        self.assertEqual(m.asked_place_missed(store, 'g1', turn, ['報價單.xlsx']), str(place))
        (place / '別的.txt').write_text('x')  # some other file changing there is not this work
        self.assertEqual(m.asked_place_missed(store, 'g1', turn, ['報價單.xlsx']), str(place))
        (place / '舊版.xlsx').write_text('x')
        self.assertEqual(m.asked_place_missed(store, 'g1', dict(turn, kept=[('舊版.xlsx', '舊版.xlsx')]), []), '')  # kept as the group's file with the same content: still handed in
        (place / '報價單.xlsx').write_text('x')
        self.assertEqual(m.asked_place_missed(store, 'g1', turn, ['報價單.xlsx', '說明.docx']), str(place))  # one of the two is not there
        self.assertEqual(m.asked_place_missed(store, 'g1', turn, ['報價單.xlsx']), '')
        self.assertEqual(m.asked_place_missed(store, 'g1', turn, []), '')  # nothing handed in to the group: nothing to look for

    def test_a_host_asking_first_is_told_apart(self):
        for text in ('確認完再交給專員開工', '【先問你】\n1. 預算？', '等你回覆後再開始分工', '我先問你幾件事'):
            self.assertTrue(m.host_asks_first(text), text)
        for text in ('Beta：做報價單，完成後等你確認後再寄出', '專員：整理名單', '做完請你確認', '資料夠了，不用先問你，直接分工'):
            self.assertFalse(m.host_asks_first(text), text)

    def test_a_check_asked_for_after_a_pause_keeps_the_pause(self):
        """A check asked for after the ask paused at its rounds never takes the place of what 「繼續」 goes on with."""
        group = dict(paused=dict(kind='free', pending=[['a', False, None]]), messages=[])
        m.GroupRuns._pause_group(None, group, 4, dict(kind='steps', steps=[dict(role='check_final', bots=['h'])]))
        self.assertEqual(group['paused']['kind'], 'free'); self.assertIn('回合上限已用完', group['messages'][-1]['content'])

    def test_a_reply_still_running_is_not_marked_failed(self):
        store = m.Store(self.root / 'data')
        group = dict(id='g1', messages=[dict(id='c', role='assistant', status='running', checkOf='a'), dict(id='d', role='assistant', status='running')])
        store.data['jobs'].append(dict(id='j', messageId='c', status='running'))
        m.group_settle_running(store, group)
        self.assertEqual([x['status'] for x in group['messages']], ['running', 'failed'])

    def test_a_check_left_running_is_marked_failed(self):
        """#291: after a restart a check still marked 「正在查核」 with no reply running fails, and says so."""
        store = m.Store(self.root / 'data')
        store.data['groups'].append(dict(id='g1', name='組', botIds=[], status='idle', messages=[
            dict(id='a', role='assistant', botId='x', content='好', status='completed'), dict(id='c', role='assistant', botId='y', content='', status='running', checkOf='a')]))
        store.save(everything=True)
        again = m.Store(self.root / 'data')
        check = again.find('groups', 'g1')['messages'][1]
        self.assertEqual(check['status'], 'failed'); self.assertIn('查核', check['error'])

    def test_auto_sums_up_when_replies_reach_ten_rounds(self):
        """#312: in 自動 checks and redos count too: ten rounds of replies (every member answering once is one) also sum up first."""
        bots = [dict(id=x, name=x) for x in ('a', 'b', 'c')]
        class Store:
            data = {'bots': bots, 'jobs': [dict(taskRunId='r1') for _ in range(29)]}
            def find(self, kind, x): return next((b for b in bots if b['id'] == x), None)
        store, group, run = Store(), dict(botIds=['a', 'b', 'c']), dict(id='r1')
        self.assertFalse(m.task_replies_due(store, group, run))
        store.data['jobs'].append(dict(taskRunId='r1')); self.assertTrue(m.task_replies_due(store, group, run))
        run['replyMark'] = 30; self.assertFalse(m.task_replies_due(store, group, run))  # counted again from the last summing up
        self.assertTrue(m.task_round_ok(dict(run, wakes=0))); self.assertFalse(m.task_round_ok(dict(run, wakes=0, replyMark=-1)))

    def test_auto_starts_nothing_new_once_the_replies_are_used(self):
        """#312: with the replies of ten rounds used, a task waiting to start does not start; the host sums up first."""
        def look(replies):
            store = m.Store(self.root / ('data%d' % replies)); m._active['data'] = store.data
            for x in 'abc': store.data['bots'].append(dict(id=x * 32, name=x, provider='claude'))
            task = dict(id='t1', n=1, title='做', status='ready', assignee='b' * 32, attempts=[], spec='x', doneWhen='y', deps=[])
            run = dict(id='r1', status='running', tasks=[task], hostId='a' * 32, origin='user', wakes=0, attempts=0, batches=0, delivered=[])
            group = dict(id='g1', name='g', botIds=[x * 32 for x in 'abc'], messages=[], taskRun=run); store.data['groups'].append(group)
            store.data['jobs'] += [dict(id=str(i), taskRunId='r1', status='completed') for i in range(replies)]
            class App: notify = lambda *a, **k: None
            App._task_choose = m.App._task_choose
            return m.App._task_next(App(), store, group, run, False), run
        out, run = look(30)
        self.assertEqual((out['start'], out['wake']), ([], 'converge')); self.assertEqual(run['replyMark'], 30)
        out, run = look(5)
        self.assertEqual(out['start'], ['t1']); self.assertFalse(out['wake'])


if __name__ == '__main__': unittest.main()
