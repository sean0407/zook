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
role = next((r for r, mark in (('verdict', '裁定者'), ('pro_open', '你是正方：'), ('con_open', '你是反方：'), ('pro_rebut', '第二回合，你是正方'), ('con_rebut', '第二回合，你是反方'), ('split_plan', '你負責分工'), ('split_work', '只完成分派給你'), ('split_merge', '你負責彙整'), ('compare_diff', '比較他們的答案'), ('compare', '你看不到他們的內容'), ('turn', '現在是輪流發言'), ('verify', '你負責查核'), ('final', '討論到此結束'), ('kickoff', '本次目標與產出')) if mark in s), 'free')
open(os.environ['GROUP_LOG'], 'a').write(json.dumps(dict(name=name, role=role, kind=kind, readonly='只能讀取' in s, args=a)) + '\n')
text = name + ' ' + role
if role in ('verdict', 'split_merge', 'compare_diff', 'final'): text = '【結論】採用甲案\n【待你決定】無\n【行動項目】Alpha：寫計畫\n【未解問題】缺成本資料'
if role == 'verify': text = '【判定】有疑慮\n數字沒有來源'
found = re.search(r'要給群組的產出請存到 (.+?)（只放', s)
if 'WRITEFILE' in s and found: open(os.path.join(found.group(1), name + '.txt'), 'w').write('from ' + name)
if kind == 'claude': print(json.dumps({'type': 'result', 'result': text, 'is_error': False}))
else: print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})); print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 50}}))
'''


class GroupModes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.log = self.root / 'runs.log'
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        for name in ('codex', 'claude'):
            cli = self.root / 'bin' / name; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', GROUP_LOG=str(self.log), ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
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

    def test_compare_mode_can_be_chosen_for_one_message(self):
        g = self.group(hostId=''); self.say(g, mode='compare'); roles = self.order()
        self.assertEqual({x[1] for x in roles[:3]}, {'compare'}); self.assertEqual(roles[-1], ('Alpha', 'compare_diff'))
        self.log.unlink(); self.say(g); self.assertEqual({r for _, r in self.order()}, {'free'})

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

    def test_invalid_settings_are_refused(self):
        g = self.group(hostId='')
        for field in ({'mode': 'chaos'}, {'turnLimit': 99}, {'hostId': 'nobody'}): self.assertEqual(self.req('PATCH', '/api/groups/' + g['id'], field)[0], 400, field)

    def test_estimate_counts_replies_without_running_anything(self):
        g = self.group(hostId='')
        self.assertEqual(self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': '', 'mode': 'debate'})[1]['replies'], 5)
        self.assertEqual(self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': '@Beta 看一下', 'mode': 'debate'})[1]['replies'], 1)
        self.assertFalse(self.log.exists()); self.say(g, mode='turns')
        self.assertGreater(self.req('POST', '/api/groups/%s/estimate' % g['id'], {'content': '', 'mode': 'turns'})[1]['tokens'], 0)

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
        self.assertEqual((status, body['needsConfirm']), (200, True)); self.assertEqual(self.req('POST', path, {'confirm': True})[0], 202); self.settle(g)
        self.assertEqual(self.runs()[-1]['name'], 'Gamma')

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
        g = self.group(('Alpha', 'Beta'), hostId='')
        self.req('PATCH', '/api/bots/' + self.bots['Alpha']['id'], {'permissionMode': 'auto'}); self.req('PATCH', '/api/bots/' + self.bots['Beta']['id'], {'permissionMode': 'manual'})
        found = self.say(g, 'WRITEFILE', mode='turns')
        self.assertEqual([f['name'] for f in self.req('GET', '/api/groups/%s/files' % g['id'])[1]['files']], ['Alpha.txt'])
        self.assertTrue(any('Alpha 存了共用檔案' in (m.get('content') or '') for m in found['messages']))
        self.assertTrue(next(r for r in self.runs() if r['name'] == 'Beta')['readonly'])


if __name__ == '__main__': unittest.main()
