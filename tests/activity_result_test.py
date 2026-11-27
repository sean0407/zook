# -*- coding: utf-8 -*-
"""#61 #247 #252 #253: each activity line says how it ended (成功／失敗／等核准…), opens to the reason and what to do next, can be
filtered by that result, says why a filter is empty; the Bot form's 釘選 is a switch with words. Nothing of a command, a key or a path is added."""
import importlib.util, pathlib, tempfile, threading, unittest

ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('zook_activity_result', ROOT / 'backend/server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
JS = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


class FakeStore:
    def __init__(self, directory):
        self.dir, self.lock = pathlib.Path(directory), threading.RLock()
        self.data = {'bots': [{'id': 'b1', 'name': '小幫手'}], 'groups': [], 'jobs': []}

    def find(self, kind, item_id): return next((x for x in self.data.get(kind) or [] if x.get('id') == item_id), None)


class ActivityResultTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = FakeStore(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def items(self, **kw): return m.activity_list(self.store, **kw)['items']

    def test_every_line_says_how_it_ended(self):
        m.log_activity(self.store, 'bot', '新增 Bot「小幫手」')
        m.log_activity(self.store, 'approval', '拒絕：刪除檔案（小幫手）')
        m.log_activity(self.store, 'backup', '對話檔 chats/a.json 寫不進去（磁碟已滿），之後每次存檔都會再試', by='Zook')
        by_text = {x['text']: x for x in self.items()}
        self.assertEqual(by_text['新增 Bot「小幫手」']['result'], 'ok')
        self.assertEqual(by_text['新增 Bot「小幫手」']['resultName'], '成功')
        self.assertEqual(by_text['拒絕：刪除檔案（小幫手）']['resultName'], '已拒絕')
        failed = by_text['對話檔 chats/a.json 寫不進去（磁碟已滿），之後每次存檔都會再試']
        self.assertEqual((failed['result'], failed['resultName']), ('failed', '失敗'))
        self.assertTrue(failed['why'] and failed['next'])  # the reason and the next step, in words
        self.assertEqual({r['id'] for r in m.activity_list(self.store)['results']}, {'ok', 'failed', 'stopped', 'waiting', 'denied', 'warn'})

    def test_filter_by_result(self):
        m.log_activity(self.store, 'bot', '新增 Bot「小幫手」')
        m.log_activity(self.store, 'backup', '資料檔無法讀取，也沒有可用的備份，從全新狀態開始（損壞的檔案留存為 無法留存）', by='Zook')
        self.assertEqual([x['result'] for x in self.items(result='failed')], ['failed'])
        self.assertEqual(self.items(kind='bot', result='failed'), [])
        self.assertEqual(len(self.items(result='nonsense')), 2)  # an unknown result is no filter

    def test_waiting_approvals_are_listed_without_the_command(self):
        self.store.data['jobs'] = [{'id': 'j1', 'botId': 'b1', 'status': 'running', 'approvals': [
            {'id': 'a1', 'name': 'native_command', 'status': 'pending', 'createdAt': '2026-11-25T08:00:00', 'arguments': {'summary': '刪除檔案', 'command': 'rm -rf /Users/x/secret', 'token': 'sk-SECRET'}},
            {'id': 'a2', 'name': 'native_command', 'status': 'approved', 'arguments': {'summary': '查看資料夾內容'}}]},
            {'id': 'j2', 'botId': 'b1', 'status': 'done', 'approvals': [{'id': 'a3', 'name': 'native_command', 'status': 'pending', 'arguments': {'summary': '寫入檔案'}}]}]
        waiting = self.items(result='waiting')
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]['text'], '等你核准：刪除檔案（小幫手）')
        self.assertEqual(waiting[0]['kind'], 'approval')
        self.assertEqual(waiting[0]['botId'], 'b1')
        self.assertIn('允許', waiting[0]['next'])
        shown = repr(waiting)
        for word in ('rm -rf', '/Users/x', 'sk-SECRET', 'arguments', 'command'):
            self.assertNotIn(word, shown)
        self.assertEqual(self.items(kind='bot'), [])  # only under 核准 and 全部
        self.assertEqual(len(self.items(kind='approval')), 1)

    def test_page_text_and_filters(self):
        self.assertTrue('這個分類目前沒有紀錄' in JS, '這個分類目前沒有紀錄')  # #61②
        self.assertTrue('data-activity-result' in JS, 'data-activity-result')  # 結果 dropdown
        self.assertTrue("data-up=\"act-open\"" in JS)  # a line opens to its detail
        self.assertTrue('下一步' in JS, '下一步')

    def test_pin_is_a_switch_with_words(self):
        form = JS[JS.index("modal(editing ? '編輯 Bot' : '新增 Bot'"):]
        form = form[:form.index('</form>')]
        self.assertFalse('type="checkbox" name="pinned"' in form or '📌' in form)
        self.assertTrue('釘選在左側最上方' in form and "toggle('name=\"pinned\"'" in form)


if __name__ == '__main__':
    unittest.main()
