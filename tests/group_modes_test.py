# -*- coding: utf-8 -*-
import http.client, json, os, re, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from urllib.parse import quote

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
CLI = r'''#!/usr/bin/env python3
import json, os, re, sys
a = sys.argv[1:]; kind = os.path.basename(sys.argv[0])
if a[:2] == ['login', 'status']: print('Logged in using ChatGPT'); sys.exit(0)
if a[:2] == ['auth', 'status']: print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'})); sys.exit(0)
if 'app-server' in a or '--help' in a or '--version' in a: sys.exit(0)
s = sys.stdin.read() if '--prompt-file' not in a else ''
name = re.search(r'現在輪到你（(.+?)）回覆', s); name = name.group(1) if name else 'solo'
role = next((r for r, mark in (('split_follow', '使用者這次只點名你'), ('check_final', '查核已通過'), ('verdict', '裁定者'), ('pro_open', '你是正方：'), ('con_open', '你是反方：'), ('pro_rebut', '第二回合，你是正方'), ('con_rebut', '第二回合，你是反方'), ('split_plan', '你負責分工'), ('split_redo', '主持人驗收後退回你的部分'), ('split_work', '只完成分派給你'), ('split_remerge', '第二次彙整'), ('split_merge', '你負責彙整'), ('compare_diff', '比較他們的答案'), ('compare', '你看不到他們的內容'), ('turn', '現在是輪流發言'), ('verify', '你負責查核'), ('final', '討論到此結束'), ('kickoff', '本次目標與產出')) if mark in s), 'free')
open(os.environ['GROUP_LOG'], 'a').write(json.dumps(dict(name=name, role=role, kind=kind, readonly='只能讀取' in s, fix='申報欄改成公式' in s, own='自己那一份' in s, task='做預算表' in s, args=a)) + '\n')
text = name + ' ' + role
if role in ('verdict', 'split_merge', 'compare_diff', 'final', 'check_final'): text = '【結論】採用甲案\n【待你決定】無\n【行動項目】Alpha：寫計畫\n【未解問題】缺成本資料'
if role in ('split_merge', 'split_remerge') and os.path.exists(os.environ['GROUP_LOG'] + '.sendback'): text = '【退回】Beta：申報欄改成公式\n' + text
if role in ('split_merge', 'final') and os.path.exists(os.environ['GROUP_LOG'] + '.mention'): text += '\n@Beta 請修正申報欄'
if role == 'split_follow' and os.path.exists(os.environ['GROUP_LOG'] + '.dispatch'): text = '【派工】Beta：做預算表\n' + text
if role == 'verify': text = '【判定】同意\n數字都對得上' if os.path.exists(os.environ['GROUP_LOG'] + '.pass') else '【判定】有疑慮\n數字沒有來源'
if role == 'verify' and os.path.exists(os.environ['GROUP_LOG'] + '.fail'): sys.stderr.write('boom\n'); sys.exit(3)
if name == 'solo' and os.path.exists(os.environ['GROUP_LOG'] + '.slow'): import time; time.sleep(4)
found = re.search(r'要給群組的產出請存到 (.+?)（只放', s)
if 'WRITEFILE' in s and found: open(os.path.join(found.group(1), name + '.txt'), 'w').write('from ' + name)
if kind == 'claude': print(json.dumps({'type': 'result', 'result': text, 'is_error': False}))
else: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})); print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 50}}))
'''


PAUSING = {'test_turn_limit_pauses_and_continues', 'test_paused_discussion_can_be_ended', 'test_turn_limit_is_never_exceeded_and_answers_stay_independent',
           'test_refused_continue_keeps_the_paused_discussion', 'test_verdict_moves_when_the_closer_leaves_during_a_pause'}


class GroupModes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'runs.log'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', GROUP_LOG=str(self.log), ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        env.pop('ZOOK_GROUP_REPLY_CAP', None)
        if self._testMethodName in PAUSING: env['ZOOK_GROUP_REPLY_CAP'] = '4'  # 4 rounds hold 12 replies here (#174): these test the pause itself, at 4
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bots = {n: self.req('POST', '/api/bots', {'name': n, 'provider': p})[1] for n, p in (('Alpha', 'codex'), ('Beta', 'claude'), ('Gamma', 'codex'))}

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.temp.cleanup()

    def req(self, method, path, body=None, raw=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        conn.request(method, path, raw if raw is not None else json.dumps(body).encode() if body is not None else None, dict({'Authorization': 'Bearer ' + self.token}, **(headers or {})))
        resp = conn.getresponse(); data = resp.read(); conn.close()
        try: return resp.status, json.loads(data)
        except ValueError: return resp.status, data

    def group(self, names=('Alpha', 'Beta', 'Gamma'), **fields):
        status, group = self.req('POST', '/api/groups', dict({'botIds': [self.bots[n]['id'] for n in names]}, **fields)); self.assertEqual(status, 201, group); return group

    def settle(self, group):
        for _ in range(150):
            found = self.req('GET', '/api/groups/' + group['id'])[1]['group']
            if found['status'] != 'running': return found
            time.sleep(.1)
        self.fail('discussion did not finish')

    def say(self, group, text='討論這件事', **fields):
        status, body = self.req('POST', '/api/groups/%s/messages' % group['id'], dict({'content': text}, **fields)); self.assertEqual(status, 202, body)
        return self.settle(group)

    def runs(self): return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []
    def order(self): return [(r['name'], r['role']) for r in self.runs()]

    def test_chosen_host_opens_and_closes(self):
        g = self.group(hostId=self.bots['Beta']['id']); self.say(g)
        self.assertEqual(self.order()[0], ('Beta', 'kickoff')); self.assertEqual(self.order()[-1][0], 'Beta')

    def test_no_host_keeps_members_answering(self):
        self.say(self.group(hostId='')); self.assertEqual({r for _, r in self.order()}, {'free'})

    def test_removed_host_is_cleared_with_a_notice(self):
        g = self.group(hostId=self.bots['Gamma']['id'])
        found = self.req('PATCH', '/api/groups/' + g['id'], {'botIds': [self.bots['Alpha']['id'], self.bots['Beta']['id']]})[1]
        self.assertEqual(found['hostId'], ''); self.assertIn('主持人', found['messages'][-1]['content'])
        self.assertEqual(self.req('PATCH', '/api/groups/' + g['id'], {'hostId': self.bots['Gamma']['id']})[0], 400)

    def test_deleted_host_is_cleared(self):
        g = self.group(hostId=self.bots['Gamma']['id']); self.req('DELETE', '/api/bots/' + self.bots['Gamma']['id'])
        self.assertEqual(self.req('GET', '/api/groups/' + g['id'])[1]['group']['hostId'], '')

    def test_turns_mode_speaks_in_member_order(self):
        self.say(self.group(hostId='', mode='turns')); self.assertEqual(self.order(), [('Alpha', 'turn'), ('Beta', 'turn'), ('Gamma', 'turn')])

    def test_debate_has_two_rounds_and_a_verdict(self):
        found = self.say(self.group(hostId='', mode='debate'))
        self.assertEqual(self.order(), [('Beta', 'pro_open'), ('Gamma', 'con_open'), ('Beta', 'pro_rebut'), ('Gamma', 'con_rebut'), ('Alpha', 'verdict')])
        self.assertEqual(found['messages'][-1]['card']['conclusion'], '採用甲案'); self.assertEqual(found['messages'][-1]['card']['decisions'], '')

    def test_split_mode_plans_works_and_merges(self):
        self.say(self.group(hostId='', mode='split')); roles = self.order()
        self.assertEqual(roles[0], ('Alpha', 'split_plan')); self.assertEqual({x for x in roles[1:3]}, {('Beta', 'split_work'), ('Gamma', 'split_work')}); self.assertEqual(roles[-1], ('Alpha', 'split_merge'))

    def test_split_host_sends_work_back_once(self):
        Path(str(self.log) + '.sendback').write_text('x')
        found = self.say(self.group(hostId='', mode='split')); roles = self.order()
        self.assertEqual(roles[0], ('Alpha', 'split_plan')); self.assertEqual({x for x in roles[1:3]}, {('Beta', 'split_work'), ('Gamma', 'split_work')})
        self.assertEqual(roles[3:], [('Alpha', 'split_merge'), ('Beta', 'split_redo'), ('Alpha', 'split_remerge')])  # sent back once, never twice
        redo = [r for r in self.runs() if r['role'] == 'split_redo'][0]
        self.assertTrue(redo['fix']); self.assertFalse(redo['readonly'])
        said = [m['content'] for m in found['messages'] if m['role'] == 'system']
        self.assertTrue(any('退回給 Beta' in x and '申報欄改成公式' in x for x in said), said)
        self.assertTrue(any('已經自動退回過 1 次' in x for x in said), said)
        work = next(m for m in found['messages'] if m.get('botId') == self.bots['Beta']['id'] and m['role'] == 'assistant')
        self.assertEqual(work.get('sentBack'), '申報欄改成公式')

    def test_compare_mode_can_be_chosen_for_one_message(self):
        g = self.group(hostId=''); self.say(g, mode='compare'); roles = self.order()
        self.assertEqual({x[1] for x in roles[:3]}, {'compare'}); self.assertEqual(roles[-1], ('Alpha', 'compare_diff'))
        self.log.unlink(); self.say(g); self.assertEqual({r for _, r in self.order()}, {'free'})

    def test_split_host_plans_and_does_its_own_share(self):
        """#71 (decisions #5, #6): the host's plan gives it a share too, and it does that share in the same reply, able to save files."""
        self.req('PATCH', '/api/bots/' + self.bots['Alpha']['id'], {'permissionMode': 'auto'})
        self.say(self.group(hostId=self.bots['Alpha']['id'], mode='split')); plan = self.runs()[0]
        self.assertEqual((plan['name'], plan['role']), ('Alpha', 'split_plan'))
        self.assertTrue(plan['own']); self.assertFalse(plan['readonly'])
        self.assertTrue(next(r for r in self.runs() if r['role'] == 'split_merge')['own'])  # the merge counts the host's own share in

    def test_busy_member_is_filled_in_when_it_is_free(self):
        """#71: a member busy in another conversation is not skipped: the others go first, it does its share once free, then the merge."""
        Path(str(self.log) + '.slow').write_text('1')
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.bots['Beta']['id'], 'content': '你好'})[0], 202)
        found = self.say(self.group(hostId=self.bots['Alpha']['id'], mode='split'))
        roles = [x for x in self.order() if x[0] != 'solo']
        self.assertEqual(roles, [('Alpha', 'split_plan'), ('Gamma', 'split_work'), ('Beta', 'split_work'), ('Alpha', 'split_merge')])
        said = [m['content'] for m in found['messages'] if m['role'] == 'system']
        self.assertTrue(any('Beta' in x and '有空再補上' in x for x in said), said)
        self.assertFalse(any('這次略過' in x for x in said), said)

    def test_host_named_later_hands_out_work_by_the_plan(self):
        """#71: in 主持人分工, a later message naming only the host does not let it do everything: the work it hands out (【派工】)
        goes to those members, then it merges. A plain question is just answered."""
        g = self.group(hostId=self.bots['Alpha']['id'], mode='split')
        self.say(g, '@Alpha 檔案在哪裡？'); self.assertEqual(self.order(), [('Alpha', 'split_follow')])
        self.log.unlink(); Path(str(self.log) + '.dispatch').write_text('1')
        self.say(g, '@Alpha 請繼續把報告做完'); roles = self.order()
        self.assertEqual(roles, [('Alpha', 'split_follow'), ('Beta', 'split_work'), ('Alpha', 'split_merge')])
        self.assertTrue(next(r for r in self.runs() if r['role'] == 'split_work')['task'])  # the member is given what the host handed out
        self.log.unlink(); self.say(self.group(hostId='', mode='split'), '@Alpha 你怎麼看'); self.assertEqual(self.order(), [('Alpha', 'free')])  # no host: as before

    def test_naming_a_member_skips_the_mode(self):
        self.say(self.group(hostId='', mode='debate'), '@Beta 你怎麼看'); self.assertEqual(self.order(), [('Beta', 'free')])

    def test_turn_limit_pauses_and_continues(self):
        g = self.group(hostId='', mode='debate', turnLimit=4); found = self.say(g)
        self.assertEqual(len(self.runs()), 4); self.assertEqual(found['paused']['kind'], 'steps'); self.assertIn('按「繼續」', found['messages'][-1]['content'])
        self.assertEqual(self.req('POST', '/api/groups/%s/continue' % g['id'], {})[0], 202); found = self.settle(g)
        self.assertEqual(self.order()[-1], ('Alpha', 'verdict')); self.assertNotIn('paused', found)

    def test_paused_discussion_can_be_ended(self):
        g = self.group(hostId='', mode='debate', turnLimit=4); self.say(g)
        self.assertNotIn('paused', self.req('POST', '/api/groups/%s/continue' % g['id'], {'discard': True})[1])
        self.assertEqual(self.req('POST', '/api/groups/%s/continue' % g['id'], {})[0], 400)

    def test_turn_limit_is_never_exceeded_and_answers_stay_independent(self):
        g = self.group(hostId='', mode='compare', turnLimit=4); self.bots['Delta'] = self.req('POST', '/api/bots', {'name': 'Delta', 'provider': 'codex'})[1]; self.bots['Eps'] = self.req('POST', '/api/bots', {'name': 'Eps', 'provider': 'codex'})[1]
        self.req('PATCH', '/api/groups/' + g['id'], {'botIds': [self.bots[n]['id'] for n in ('Alpha', 'Beta', 'Gamma', 'Delta', 'Eps')]}); found = self.say(g)
        self.assertEqual(len(self.runs()), 4); self.assertEqual(found['paused']['steps'][0]['bots'], [self.bots['Eps']['id']])
        self.req('POST', '/api/groups/%s/continue' % g['id'], {}); self.settle(g)
        self.assertEqual([r for r in self.order()][4:], [('Eps', 'compare'), ('Alpha', 'compare_diff')])

    def test_refused_continue_keeps_the_paused_discussion(self):
        g = self.group(hostId='', mode='debate', turnLimit=4); self.say(g); self.req('POST', '/api/groups/%s/summarize' % g['id'], {})
        self.assertEqual(self.req('POST', '/api/groups/%s/continue' % g['id'], {})[0], 409); found = self.settle(g); self.assertIn('paused', found)

    def test_verdict_moves_when_the_closer_leaves_during_a_pause(self):
        g = self.group(hostId=self.bots['Alpha']['id'], mode='debate', turnLimit=4); self.say(g)
        self.req('PATCH', '/api/groups/' + g['id'], {'botIds': [self.bots['Beta']['id'], self.bots['Gamma']['id']], 'hostId': self.bots['Beta']['id']})
        self.req('POST', '/api/groups/%s/continue' % g['id'], {}); self.settle(g); self.assertEqual(self.order()[-1], ('Beta', 'verdict'))

    def test_host_removed_in_the_form_gets_a_notice(self):
        g = self.group(hostId=self.bots['Gamma']['id'])
        found = self.req('PATCH', '/api/groups/' + g['id'], {'botIds': [self.bots['Alpha']['id'], self.bots['Beta']['id']], 'hostId': ''})[1]
        self.assertIn('主持人', found['messages'][-1]['content'])

    def test_invalid_settings_are_refused(self):
        g = self.group(hostId='')
        for field in ({'mode': 'chaos'}, {'turnLimit': 99}, {'hostId': 'nobody'}): self.assertEqual(self.req('PATCH', '/api/groups/' + g['id'], field)[0], 400, field)

    def test_estimate_counts_replies_without_running_anything(self):
        g = self.group(hostId='')
        self.assertEqual(self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': '', 'mode': 'debate'})[1]['replies'], 5)
        self.assertEqual(self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': '@Beta 看一下', 'mode': 'debate'})[1]['replies'], 1)
        self.assertFalse(self.log.exists()); self.say(g, mode='turns')
        self.assertGreater(self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': '', 'mode': 'turns'})[1]['tokens'], 0)

    def test_estimate_says_how_many_more_a_send_back_takes(self):
        """#68⑦: 分工 with two members is 3 replies, but the host's check can send work back (fix, then merge again): up to 5."""
        g = self.group(names=('Alpha', 'Beta'), hostId='')
        e = self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': '', 'mode': 'split'})[1]
        self.assertEqual((e['replies'], e['most']), (3, 5))
        e = self.req('POST', '/api/groups/%s/estimate' % self.group(hostId='')['id'], {'content': '', 'mode': 'split'})[1]
        self.assertEqual((e['replies'], e['most']), (4, 7))
        self.assertNotIn('most', self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': '', 'mode': 'debate'})[1])
        Path(str(self.log) + '.sendback').write_text('x'); self.say(g, mode='split'); self.assertEqual(len(self.runs()), 5)  # what the estimate said

    def test_a_closing_mention_is_said_not_to_start_anyone(self):
        """#68④: a host's 「@成員 請修」 in a closing reply never starts that member; Zook says so, with how to ask."""
        Path(str(self.log) + '.mention').write_text('x')
        found = self.say(self.group(hostId='', mode='split')); roles = self.order()
        self.assertEqual(roles[-1], ('Alpha', 'split_merge'))  # nobody after the merge
        said = [m['content'] for m in found['messages'] if m['role'] == 'system']
        self.assertTrue(any('Beta' in x and '不會自動' in x and '@Beta' in x for x in said), said)
        self.log.unlink(); Path(str(self.log) + '.sendback').write_text('x')
        found = self.say(self.group(hostId='', mode='split'))  # sent back: Beta is started by the send-back, nothing else to say
        self.assertFalse(any('不會自動' in m['content'] for m in found['messages'] if m['role'] == 'system'))

    def test_summary_on_request_is_read_only_and_makes_a_card(self):
        g = self.group(hostId=''); self.say(g, mode='turns')
        self.assertEqual(self.req('POST', '/api/groups/%s/summarize' % g['id'], {})[0], 202); found = self.settle(g)
        self.assertEqual(self.order()[-1], ('Alpha', 'final')); self.assertTrue(self.runs()[-1]['readonly']); self.assertEqual(found['messages'][-1]['card']['actions'], 'Alpha：寫計畫')

    def test_check_goes_to_another_vendor_and_shows_a_verdict(self):
        g = self.group(hostId=''); found = self.say(g, mode='turns'); target = next(m for m in found['messages'] if m.get('botId') == self.bots['Alpha']['id'])
        self.assertEqual(self.req('POST', '/api/groups/%s/messages/%s/verify' % (g['id'], target['id']), {})[0], 202); found = self.settle(g)
        run = self.runs()[-1]; self.assertEqual((run['name'], run['role'], run['kind'], run['readonly']), ('Beta', 'verify', 'claude', True))
        check = found['messages'][-1]; self.assertEqual((check['checkOf'], check['verdict']), (target['id'], '有疑慮'))

    def test_check_within_one_vendor_asks_first(self):
        g = self.group(('Alpha', 'Gamma'), hostId=''); found = self.say(g, mode='turns'); target = next(m for m in found['messages'] if m.get('botId') == self.bots['Alpha']['id'])
        path = '/api/groups/%s/messages/%s/verify' % (g['id'], target['id']); status, body = self.req('POST', path, {})
        self.assertEqual((status, body['needsConfirm']), (409, True)); self.assertIn('沒有別家的 Bot', body['error'])  # refused until confirmed: never 200 with nothing started
        self.assertEqual(self.req('POST', path, {'confirm': True})[0], 202); self.settle(g)
        self.assertEqual(self.runs()[-1]['name'], 'Gamma')

    def test_failed_check_says_why_under_the_reply_and_can_be_tried_again(self):
        g = self.group(('Alpha', 'Beta'), hostId=''); found = self.say(g, mode='turns'); target = next(m for m in found['messages'] if m.get('botId') == self.bots['Alpha']['id'])
        path = '/api/groups/%s/messages/%s/verify' % (g['id'], target['id']); Path(str(self.log) + '.fail').write_text('1')
        self.assertEqual(self.req('POST', path, {})[0], 202); self.settle(g)
        check = self.req('GET', '/api/groups/' + g['id'])[1]['group']['messages'][-1]  # read again, as after a reload
        self.assertEqual((check['checkOf'], check['status'], check['botId']), (target['id'], 'failed', self.bots['Beta']['id']))
        self.assertTrue(check['error']); self.assertNotIn('boom', check['error'])  # the plain reason, not what the CLI printed
        os.remove(str(self.log) + '.fail'); self.assertEqual(self.req('POST', path, {})[0], 202); found = self.settle(g)
        self.assertEqual([(m['status'], m.get('verdict')) for m in found['messages'] if m.get('checkOf') == target['id']], [('failed', None), ('completed', '有疑慮')])

    def test_check_nobody_can_do_is_refused_with_the_reason(self):
        g = self.group(('Alpha', 'Beta'), hostId=''); found = self.say(g, mode='turns'); target = next(m for m in found['messages'] if m.get('botId') == self.bots['Alpha']['id'])
        path = '/api/groups/%s/messages/%s/verify' % (g['id'], target['id']); Path(str(self.log) + '.slow').write_text('1')
        self.assertEqual(self.req('POST', '/api/chat', {'botId': self.bots['Beta']['id'], 'content': '你好'})[0], 202)
        status, body = self.req('POST', path, {}); self.assertEqual(status, 409, body); self.assertIn('Beta 正在其他對話中工作', body['error'])
        self.assertFalse([r for r in self.runs() if r['role'] == 'verify'])
        self.assertFalse([m for m in self.req('GET', '/api/groups/' + g['id'])[1]['group']['messages'] if m.get('checkOf')])

    def check_alpha(self, group, ask='@Alpha 做一份報表', **fields):
        found = self.say(group, ask, **fields); target = next(m for m in found['messages'] if m.get('botId') == self.bots['Alpha']['id'])
        self.assertEqual(self.req('POST', '/api/groups/%s/messages/%s/verify' % (group['id'], target['id']), {})[0], 202); return self.settle(group)

    def test_passed_check_gets_the_hosts_conclusion(self):
        """#222: a check that passes is wrapped up by the host at once (one more reply), marked as such, read-only, as a card."""
        Path(str(self.log) + '.pass').write_text('1')
        found = self.check_alpha(self.group(hostId=self.bots['Gamma']['id']))
        self.assertEqual(self.order()[-2:], [('Beta', 'verify'), ('Gamma', 'check_final')]); self.assertTrue(self.runs()[-1]['readonly'])
        last = found['messages'][-1]
        self.assertEqual((last['botId'], last.get('afterCheck'), last['card']['conclusion']), (self.bots['Gamma']['id'], True, '採用甲案'))
        self.assertFalse(last.get('checkOf'))

    def test_no_conclusion_after_a_doubt_without_a_host_or_when_one_exists(self):
        self.check_alpha(self.group(hostId=self.bots['Gamma']['id']))  # 有疑慮: the user decides
        self.assertEqual(self.order()[-1], ('Beta', 'verify'))
        Path(str(self.log) + '.pass').write_text('1'); self.log.unlink()
        found = self.check_alpha(self.group(hostId=''))  # no host: the 整理結論 button stays
        self.assertEqual(self.order()[-1], ('Beta', 'verify')); self.assertFalse(any(m.get('afterCheck') for m in found['messages']))
        self.log.unlink(); g = self.group(hostId=self.bots['Gamma']['id'])
        found = self.check_alpha(g, '討論這件事', mode='turns')  # the host already closed this round with a conclusion: not a second one
        self.assertEqual([r for _, r in self.order()].count('final'), 1); self.assertEqual(self.order()[-1], ('Beta', 'verify'))

    def upload(self, group, name, data=b'hello'):
        return self.req('POST', '/api/groups/%s/files' % group['id'], raw=data, headers={'X-File-Name': quote(name), 'Content-Type': 'application/octet-stream'})

    def test_files_upload_list_download_delete(self):
        g = self.group(hostId=''); self.assertEqual(self.upload(g, '報告.txt')[0], 201); self.assertEqual(self.upload(g, '報告.txt')[1]['name'], '報告 (2).txt')
        files = self.req('GET', '/api/groups/%s/files' % g['id'])[1]['files']; self.assertEqual([f['name'] for f in files], ['報告 (2).txt', '報告.txt']); self.assertEqual(files[1]['by'], '你')
        self.assertEqual(self.req('GET', '/api/groups/%s/files/%s' % (g['id'], quote('報告.txt')))[1], b'hello')
        self.assertEqual(self.req('DELETE', '/api/groups/%s/files/%s' % (g['id'], quote('報告.txt')))[0], 200)
        self.assertEqual(self.req('GET', '/api/groups/%s/files/%s' % (g['id'], quote('../../swarmr.json')))[0], 404)

    def test_upload_names_cannot_leave_the_folder(self):
        g = self.group(hostId=''); self.assertEqual(self.upload(g, '../../evil.txt')[1]['name'], 'evil.txt')
        self.assertFalse((self.root / 'data/evil.txt').exists())

    def test_member_output_comes_back_only_when_allowed(self):
        g = self.group(('Alpha', 'Gamma'), hostId='')  # both Codex: 主動性 still applies to them (a Claude Bot always may, 2026-11-22)
        self.req('PATCH', '/api/bots/' + self.bots['Alpha']['id'], {'permissionMode': 'auto'}); self.req('PATCH', '/api/bots/' + self.bots['Gamma']['id'], {'permissionMode': 'manual'})
        found = self.say(g, 'WRITEFILE', mode='turns')
        self.assertEqual([f['name'] for f in self.req('GET', '/api/groups/%s/files' % g['id'])[1]['files']], ['Alpha.txt'])
        self.assertTrue(any('Alpha 存了共用檔案' in (m.get('content') or '') for m in found['messages']))
        self.assertTrue(next(r for r in self.runs() if r['name'] == 'Gamma')['readonly'])


if __name__ == '__main__': unittest.main()
