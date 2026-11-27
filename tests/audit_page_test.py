# -*- coding: utf-8 -*-
"""#304 #247 (decisions 2026-11-26 #12 #27): the activity record is an audit page of what Zook did for you. Every finished reply of a
Bot or a group has one line: when, which Bot or group, what it did in one plain sentence, how it ended (成功／失敗／已停止; 等核准 while
it waits), which CLI and model, and for a failure why and what to do next. It can be filtered by Bot, group, result and date and
searched; it is read a page at a time; it keeps at most 5000 lines and 90 days; it never keeps the message, a key or a whole path.
Settings changes and approvals stay, under one category; the same change made several times in a row reads as one line."""
import datetime, http.client, importlib.util, json, os, pathlib, subprocess, sys, tempfile, threading, time, unittest

ROOT = pathlib.Path(__file__).parents[1]
SERVER = ROOT / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_audit_page', SERVER)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
JS = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))
CLI = '''#!/usr/bin/env python3
import json, sys
s = sys.stdin.read()
if 'PLEASE-FAIL' in s:
    sys.stderr.write('You have hit your usage limit.\\n'); sys.exit(1)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'done'}}))
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 5}}))
'''


class FakeStore:
    def __init__(self, directory):
        self.dir, self.lock = pathlib.Path(directory), threading.RLock()
        self.data = {'bots': [{'id': 'b1', 'name': '小幫手', 'provider': 'codex', 'model': ''}, {'id': 'b2', 'name': '研究員', 'provider': 'claude', 'model': 'sonnet'}],
                     'groups': [{'id': 'g1', 'name': '行銷組', 'botIds': ['b1', 'b2']}], 'jobs': [], 'settings': {}}

    def find(self, kind, item_id): return next((x for x in self.data.get(kind) or [] if x.get('id') == item_id), None)


class AuditRecordTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = FakeStore(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def items(self, **kw): return m.activity_list(self.store, **kw)['items']

    def job(self, **kw):
        return dict(dict(id=m.ID(), botId='b1', chatId='c1', messageId='m1', status='completed', createdAt=m.NOW(), toolCalls=[], approvals=[]), **kw)

    def test_a_finished_reply_is_one_line_with_result_and_model(self):
        job = self.job(ran=['claude', 'sonnet', ''], botId='b2', toolCalls=[
            {'name': 'native_write', 'arguments': {'path': '/Users/someone/Secret Folder/報價.xlsx', 'content': 'TOP-SECRET-CONTENT'}},
            {'name': 'native_command', 'arguments': {'summary': '執行 Python 程式「make.py」（產生 Excel）；寫入檔案「總表.csv」'}},
            {'name': 'web_search', 'arguments': {'query': '客戶的私人問題'}}])
        m.audit_job(self.store, job, 'completed')
        work = self.items(kind='work')
        self.assertEqual(len(work), 1)
        x = work[0]
        self.assertEqual((x['result'], x['resultName']), ('ok', '成功'))
        self.assertEqual((x['botId'], x['chatId'], x['messageId'], x['by']), ('b2', 'c1', 'm1', '研究員'))
        self.assertIn('回覆你的訊息', x['text']); self.assertIn('3 個工具', x['text'])
        self.assertIn('報價.xlsx', x['text']); self.assertIn('總表.csv', x['text'])
        self.assertEqual(x['model'], 'sonnet'); self.assertTrue(x['providerName'])
        saved = (pathlib.Path(self.temp.name) / 'activity.jsonl').read_text(encoding='utf-8')
        for word in ('/Users/someone', 'Secret Folder', 'TOP-SECRET-CONTENT', '客戶的私人問題'):
            self.assertNotIn(word, saved)
        m.audit_job(self.store, job, 'completed')  # finished twice (a redo) is still one line
        self.assertEqual(len(self.items(kind='work')), 1)

    def test_failed_and_stopped_say_why_and_what_next(self):
        m.audit_job(self.store, self.job(status='failed', error='Codex 的額度已用完，或已達使用上限。請等額度重置，或改用其他模型。 /Users/someone/x/y.txt sk-abcdefabcdefabcdefabcdef'), 'failed')
        m.audit_job(self.store, self.job(status='cancelled', messageId='m2'), 'cancelled')
        m.audit_job(self.store, self.job(status='failed', messageId='m3', error='讀不到 /Users/someone/Private Folder/plan b.txt，請確認。'), 'failed')
        spaced = next(x for x in self.items(result='failed') if x['messageId'] == 'm3')
        self.assertNotIn('Private', spaced['why']); self.assertNotIn('plan b', spaced['why']); self.assertIn('請確認', spaced['why'])
        failed = next(x for x in self.items(result='failed') if x['messageId'] == 'm1'); stopped, = self.items(result='stopped')
        self.assertEqual(failed['resultName'], '失敗'); self.assertIn('額度', failed['why']); self.assertTrue(failed['next'])
        self.assertNotIn('/Users/someone', failed['why']); self.assertNotIn('y.txt', failed['why']); self.assertNotIn('abcdefabcdef', json.dumps(failed, ensure_ascii=False))
        self.assertEqual(stopped['resultName'], '已停止'); self.assertTrue(stopped['why'])
        self.assertIn('stopped', {r['id'] for r in m.activity_list(self.store)['results']})

    def test_the_model_the_cli_reported(self):
        m.audit_job(self.store, self.job(ran=['claude', '', ''], botId='b2', usage={'provider': 'claude', 'model': 'claude-opus-5-5'}), 'completed')
        self.assertEqual(self.items(kind='work')[0]['model'], 'claude-opus-5-5')

    def test_group_reply_and_helpers(self):
        m.audit_job(self.store, self.job(groupId='g1', messageId='gm1'), 'completed')
        m.audit_job(self.store, self.job(messageId='', internal='summary'), 'completed')  # Zook's own helper: not the user's work
        x, = self.items(kind='work')
        self.assertEqual((x['groupId'], x['by']), ('g1', '行銷組'))
        self.assertIn('小幫手', x['text'])

    def test_filters_search_and_pages(self):
        for i in range(7): m.audit_job(self.store, self.job(messageId='a%d' % i), 'completed')
        m.audit_job(self.store, self.job(botId='b2', messageId='b'), 'completed')
        m.audit_job(self.store, self.job(groupId='g1', messageId='g'), 'completed')
        m.log_activity(self.store, 'setting', '變更設定：主動性')
        self.assertEqual(len(self.items(bot='b2')), 1)
        self.assertEqual(len(self.items(group='g1')), 1)
        self.assertEqual([x['text'] for x in self.items(kind='admin')], ['變更設定：主動性'])
        self.assertEqual(len(self.items(q='研究員')), 1)
        self.assertEqual(len(self.items(q='主動性')), 1)
        page = m.activity_list(self.store, limit=4)
        self.assertEqual((len(page['items']), page['total'], page['more']), (4, 10, True))
        last = m.activity_list(self.store, offset=8, limit=4)
        self.assertEqual((len(last['items']), last['more']), (2, False))
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()
        with (pathlib.Path(self.temp.name) / 'activity.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(id='old', at=old, kind='setting', text='很久以前', by='這台 Mac'), ensure_ascii=False) + '\n')
        self.assertNotIn('很久以前', [x['text'] for x in self.items(range='7d')])
        self.assertIn('很久以前', [x['text'] for x in self.items(range='30d')])
        self.assertEqual({r['id'] for r in m.activity_list(self.store)['ranges']}, {'today', '7d', '30d', '90d'})

    def test_same_change_in_a_row_reads_as_one(self):
        for name in ('甲', '乙', '丙'):
            m.log_activity(self.store, 'bot', 'Bot「%s」改依工作內容配模型，改配 Codex（寫程式多）。可以在編輯 Bot 改。' % name, by='Zook')
        m.log_activity(self.store, 'setting', '變更設定：主動性')
        m.log_activity(self.store, 'setting', '變更設定：主動性')
        merged = self.items(merge=True)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]['count'], 2); self.assertEqual(merged[1]['count'], 3)
        self.assertEqual(len(merged[1]['more']), 3)
        self.assertEqual(len(self.items()), 5)  # read one by one when asked
        m.log_activity(self.store, 'bot', '新增 Bot「甲」'); m.log_activity(self.store, 'bot', '新增 Bot「乙」')
        self.assertEqual([x['count'] for x in self.items(merge=True)[:2]], [1, 1])  # two things you did yourself stay two lines

    def test_keeps_5000_lines_and_90_days(self):
        path = pathlib.Path(self.temp.name) / 'activity.jsonl'
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=91)).isoformat()
        now = m.NOW()
        with path.open('w', encoding='utf-8') as f:
            f.write(json.dumps(dict(id='x', at=old, kind='setting', text='太舊', by='這台 Mac'), ensure_ascii=False) + '\n')
            for i in range(5100): f.write(json.dumps(dict(id='n%d' % i, at=now, kind='setting', text='第 %d 筆' % i, by='這台 Mac'), ensure_ascii=False) + '\n')
        self.assertNotIn('太舊', [x['text'] for x in self.items()])  # older than 90 days is never shown
        m.activity_prune(self.store)
        lines = path.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 5000)
        self.assertNotIn('太舊', path.read_text(encoding='utf-8'))
        self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')
        self.assertEqual((m.ACTIVITY_KEEP, m.ACTIVITY_DAYS), (5000, 90))
        for i in range(150): m.log_activity(self.store, 'setting', '之後的第 %d 筆' % i)  # each new line keeps the file within 5000
        self.assertLessEqual(len(path.read_text(encoding='utf-8').splitlines()), 5000)
        self.assertIn('之後的第 149 筆', path.read_text(encoding='utf-8'))

    def test_store_finishing_a_reply_writes_the_line(self):
        self.assertTrue(any(c.__name__ == 'AuditTrail' for c in m.Store.__mro__))


class AuditPageTest(unittest.TestCase):
    def test_page_has_dropdowns_search_paging_and_going_back(self):
        for word in ('data-activity-bot', 'data-activity-group', 'data-activity-result', 'data-activity-range', 'id="act-search"', '載入更多',
                     'data-up="act-go"', 'openConversation(', 'zook-activity-filters', '設定與核准'):
            self.assertTrue(word in JS, word)
        self.assertIn("'activity'", JS[JS.index('const LAST_PAGE_KEY'):][:200])  # a reload stays on the activity page (#247⑥)


class AuditServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = pathlib.Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('x'); (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'; cli.write_text(CLI); cli.chmod(0o755)
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + '/usr/bin:/bin', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_INTRO='1', ZOOK_SCHEDULE_TICK='3600', ZOOK_SHELL_ENV='0', ZOOK_SECRETS_DIR=str(self.root / 'secrets'))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']
        self.bot = self.req('POST', '/api/bots', {'name': '小幫手', 'provider': 'codex'})[1]

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, {'Authorization': 'Bearer ' + self.token})
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, json.loads(data)

    def ask(self, text):
        job_id = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': text})[1]['jobId']
        end = time.time() + 15
        while time.time() < end:
            if self.req('GET', '/api/jobs/' + job_id)[1]['status'] != 'running': return job_id
            time.sleep(0.1)
        self.fail('no reply')

    def work(self, query=''):
        end = time.time() + 5
        while time.time() < end:
            out = self.req('GET', '/api/activity?kind=work' + query)[1]
            if out['items']: return out
            time.sleep(0.1)
        return out

    def test_each_reply_is_recorded_without_its_words(self):
        self.ask('這句話不該出現在紀錄裡')
        self.ask('PLEASE-FAIL 這句也不該')
        out = self.work()
        self.assertEqual([x['result'] for x in out['items']], ['failed', 'ok'])
        self.assertTrue(all(x['botId'] == self.bot['id'] and x['messageId'] and x['by'] == '小幫手' for x in out['items']))
        self.assertIn('額度', out['items'][0]['why'])
        saved = (self.root / 'data/activity.jsonl').read_text(encoding='utf-8')
        self.assertNotIn('這句話', saved); self.assertNotIn('這句也', saved)
        self.assertEqual(len(self.req('GET', '/api/activity?kind=work&result=ok')[1]['items']), 1)
        mine = [x['text'] for x in self.req('GET', '/api/activity?bot=' + self.bot['id'])[1]['items']]
        self.assertEqual(len(mine), 3); self.assertEqual(mine[-1], '新增 Bot「小幫手」')  # a line from before #304 names the Bot in its words
        paged = self.req('GET', '/api/activity?limit=1')[1]
        self.assertEqual(len(paged['items']), 1); self.assertTrue(paged['more'])
        self.assertTrue(self.req('GET', '/api/activity')[1]['bots'])


if __name__ == '__main__':
    unittest.main()
