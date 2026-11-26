# -*- coding: utf-8 -*-
"""#295 知識庫第 2 版: a reply carries the passages of the whole knowledge base that match the question (Chinese and English), each saying
where it is from, within a length budget, only from items for every Bot or for this Bot; passages are made when an item changes, not at
every reply; a deleted item is not found. 試搜尋 on the 知識庫 page shows the same passages. No AI CLI needed (a fake one writes its prompt)."""
import http.client, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
FILLER = '這是一般的公司說明文字，介紹部門分工與日常作業流程。' * 40   # about 1,000 characters that match nothing asked below


def load():
    ns = {'__file__': str(SERVER)}
    for part in ('core', 'knowledge', 'knowsearch'):
        f = ROOT / 'backend/zook' / (part + '.py'); exec(compile(f.read_text(encoding='utf-8'), str(f), 'exec'), ns)
    return ns


class FakeStore:
    def __init__(self, items, bots=('me', 'other')):
        self.data = {'knowledge': items, 'bots': [{'id': b} for b in bots]}

    def find(self, kind, item_id):
        return next((x for x in self.data[kind] if x.get('id') == item_id), None)


def note(i, content, title=None, bot='', source=None):
    item = dict(id='%032x' % i, title=title or '筆記%d' % i, content=content, botId=bot)
    if source: item.update(source=source, status='ready')
    return item


class KnowledgeSearch(unittest.TestCase):
    def setUp(self):
        self.ns = load()
        manual = '\n'.join(['# 公司簡介', FILLER, FILLER, '# 保固與退貨', '旗艦款滑鼠保固兩年，七天內可以無條件退貨，請附上發票。', FILLER, FILLER, FILLER])
        english = '\n\n'.join([FILLER, 'Shipping policy: orders over 1000 dollars ship free within Taiwan. Overseas shipping takes ten days.', FILLER])
        self.items = [note(i, FILLER * 2) for i in range(1, 21)]  # many items: the old way read only the newest ten, first 4,000 characters each
        self.items[0:0] = [note(100, manual, title='產品手冊', source='手冊.pdf'), note(101, english, title='Shipping')]
        self.items.append(note(102, '只給另一個 Bot 的機密：旗艦款滑鼠的進貨成本是 300 元。', title='成本', bot='other'))
        self.store = FakeStore(self.items)

    def pick(self, query, bot='me'):
        return self.ns['knowledge_pick'](self.store, bot, query)

    def test_chinese_question_finds_the_passage_deep_in_an_old_file(self):
        mode, found = self.pick('旗艦款滑鼠的保固多久？可以退貨嗎')
        self.assertEqual(mode, 'match')
        self.assertIn('保固兩年', found[0]['text'])  # beyond the first 4,000 characters of the oldest item: never read before
        lines = self.ns['knowledge_lines'](found)
        self.assertIn('【出處：產品手冊（檔案：手冊.pdf） › 保固與退貨】', lines)
        self.assertNotIn('進貨成本', lines)  # only for another Bot

    def test_english_question(self):
        mode, found = self.pick('How long does overseas shipping take?')
        self.assertEqual(mode, 'match'); self.assertIn('Overseas shipping takes ten days', found[0]['text']); self.assertEqual(found[0]['title'], 'Shipping')
        self.assertIn('Overseas', self.pick('ＳＨＩＰＰＩＮＧ policy')[1][0]['text'])  # full-width and capitals fold

    def test_scope_every_bot_or_this_one(self):
        self.assertIn('進貨成本', self.ns['knowledge_lines'](self.pick('旗艦款滑鼠的進貨成本', bot='other')[1]))
        self.assertNotIn('進貨成本', self.ns['knowledge_lines'](self.pick('旗艦款滑鼠的進貨成本', bot='me')[1]))
        self.assertNotIn('進貨成本', self.ns['knowledge_lines'](self.pick('旗艦款滑鼠的進貨成本', bot='')[1]))  # 試搜尋 for 所有 Bot

    def test_length_budget_and_passage_size(self):
        long = note(200, '\n'.join('第%d條：員工請假規定，病假需附證明。' % i + FILLER for i in range(120)), title='員工手冊')
        self.store.data['knowledge'].append(long)
        mode, found = self.pick('請假規定 病假 證明')
        self.assertEqual(mode, 'match')
        self.assertLessEqual(sum(self.ns['_kcost'](p) for p in found), self.ns['KNOWLEDGE_BUDGET'])  # labels included (review)
        self.assertLessEqual(len(self.ns['knowledge_lines'](found)), self.ns['KNOWLEDGE_BUDGET'] + 100)
        self.assertLessEqual(len(found), self.ns['KNOWLEDGE_PIECES'])
        for _, text in self.ns['knowledge_passages'](long['content']): self.assertLessEqual(len(text), self.ns['KNOWLEDGE_PIECE_MAX'])
        short = self.ns['knowledge_passages']('# 甲章\n短。\n# 乙章\n也短。')  # short sections share a passage, labelled with both (review)
        self.assertEqual(short, [('甲章、乙章', '# 甲章\n短。\n# 乙章\n也短。')])
        one_line = self.ns['knowledge_passages']('字' * 10000)  # a file without line breaks is still cut
        self.assertTrue(all(len(t) <= 1500 for _, t in one_line)); self.assertEqual(sum(len(t) for _, t in one_line), 10000)

    def test_deleted_item_is_not_found(self):
        self.assertIn('Overseas', self.pick('overseas shipping')[1][0]['text'])
        self.store.data['knowledge'] = [x for x in self.store.data['knowledge'] if x['title'] != 'Shipping']
        self.ns['knowledge_index_touch'](self.store, '%032x' % 101)
        mode, found = self.pick('overseas shipping')
        self.assertNotIn('Overseas', self.ns['knowledge_lines'](found))
        self.assertNotIn('%032x' % 101, self.ns['_KINDEX'][self.store])

    def test_passages_made_once_and_again_when_changed(self):
        made = []
        real = self.ns['_kitem']
        self.ns['_kitem'] = lambda item: made.append(item['id']) or real(item)
        self.pick('保固'); first = len(made)
        self.assertEqual(first, len(self.items) - 1)  # every item this Bot may use, once (older data is cut the first time)
        self.pick('退貨'); self.pick('shipping')
        self.assertEqual(len(made), first)  # not again at the next reply
        self.items[1]['content'] = self.items[1]['content'].replace('ten days', 'two weeks')  # changed (here, synced or restored)
        self.assertIn('two weeks', self.pick('overseas shipping')[1][0]['text'])
        self.assertEqual(made[first:], ['%032x' % 101])

    def test_small_knowledge_base_is_given_whole_and_nothing_matching_falls_back(self):
        small = FakeStore([note(1, '寫給客戶的信一律用敬語。', title='語氣')])
        self.assertEqual(self.ns['knowledge_pick'](small, 'me', '幫我寫報價單')[0], 'all')
        one = FakeStore([note(1, '\n'.join([FILLER] * 9), title='一份')])  # under the budget, still given as passages of at most 1,500 (review)
        mode, whole = self.ns['knowledge_pick'](one, 'me', 'x')
        self.assertEqual(mode, 'all'); self.assertGreater(len(whole), 1); self.assertTrue(all(len(p['text']) <= 1500 for p in whole))
        mode, found = self.pick('你好')
        self.assertEqual(mode, 'recent'); self.assertTrue(found)
        self.assertLessEqual(sum(len(p['text']) for p in found), self.ns['KNOWLEDGE_BUDGET'])
        self.assertEqual(self.ns['knowledge_pick'](FakeStore([]), 'me', '保固')[0], 'none')
        self.assertEqual(self.ns['knowledge_lines']([]), '')

    def test_terms(self):
        terms = self.ns['knowledge_terms']('請問 Zook 的保固怎麼算？')
        self.assertIn(' zook', terms); self.assertIn('保固', terms); self.assertNotIn('怎麼', terms); self.assertNotIn('請問', terms)

    def test_speed(self):
        big = FakeStore([note(i, ('第%d份資料，產品規格與價格說明。' % i + FILLER) * 95) for i in range(50)])  # 50 files of about 100,000 characters
        self.ns['knowledge_pick'](big, 'me', '暖身')
        start = time.time(); self.ns['knowledge_pick'](big, 'me', '第37份資料的產品規格和價格是多少')
        self.assertLess(time.time() - start, 2.0)

    def test_group_question(self):
        group = {'messages': [dict(role='user', content='舊的問題'), dict(role='system', content='系統'), dict(role='assistant', content='保固兩年'), dict(role='user', content='退貨呢？')]}
        ask = self.ns['knowledge_group_ask'](group, dict(content='要查核的回覆'), '改價格')
        for part in ('舊的問題', '保固兩年', '退貨呢？', '改價格', '要查核的回覆'): self.assertIn(part, ask)
        self.assertNotIn('系統', ask)
        group['messages'][0]['id'] = 'secret'  # another member's answer in a blind round (review)
        self.assertNotIn('舊的問題', self.ns['knowledge_group_ask'](group, None, '', hidden={'secret'}))
        group['messages'].append(dict(role='user', content='雜' * 3000))  # a long message does not use up the terms (review)
        self.assertIn('查核', self.ns['knowledge_terms'](self.ns['knowledge_group_ask'](group, dict(content='要查核的回覆'), '改價格')))


class KnowledgeSearchServer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('hello')
        (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'
        cli.write_text('#!/usr/bin/env python3\nimport os,sys\ns=sys.stdin.read()\nopen(os.environ["PROMPT_FILE"],"w").write(s)\nprint("ok")\n'); cli.chmod(0o755)
        self.prompt = self.root / 'prompt.txt'
        env = dict(os.environ, PATH=str(self.root / 'bin') + os.pathsep + os.environ['PATH'], PROMPT_FILE=str(self.prompt), ZOOK_NO_INTRO='1', ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SHELL_ENV='0')
        self.proc = subprocess.Popen([sys.executable, str(SERVER), '--port', '0', '--data-dir', str(self.root / 'data'), '--assets', str(self.root / 'assets')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.port, self.token = ready['port'], ready['token']

    def tearDown(self):
        self.proc.terminate(); self.proc.wait(timeout=5); self.proc.stdout.close(); self.proc.stderr.close(); self.temp.cleanup()

    def request(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        h = {'Authorization': 'Bearer ' + self.token}; h.update(headers or {})
        conn.request(method, path, raw if raw is not None else (json.dumps(body).encode() if body is not None else None), h)
        resp = conn.getresponse(); data = resp.read(); conn.close()
        try: return resp.status, json.loads(data)
        except ValueError: return resp.status, data

    def test_reply_and_try_search(self):
        bot = self.request('GET', '/api/state')[1]['bots'][0]
        self.request('PATCH', '/api/bots/' + bot['id'], {'provider': 'codex'})
        for i in range(15): self.request('POST', '/api/knowledge', {'title': '雜項%d' % i, 'content': FILLER})
        upload = self.request('POST', '/api/knowledge/file', raw=('# 退貨\n' + FILLER + '\n# 保固\n旗艦款保固兩年。').encode(), headers={'X-File-Name': quote('規定.md'), 'Content-Type': 'application/octet-stream'})[1]
        for _ in range(200):
            if next(x for x in self.request('GET', '/api/state')[1]['knowledge'] if x['id'] == upload['id'])['status'] != 'processing': break
            time.sleep(.05)
        for _ in range(3): self.request('POST', '/api/knowledge', {'title': '最新%d' % _, 'content': FILLER})  # the file is no longer among the newest ten
        reply = self.request('POST', '/api/chat', {'botId': bot['id'], 'content': '旗艦款保固多久？'})[1]
        for _ in range(200):
            if self.request('GET', '/api/jobs/' + reply['jobId'])[1]['status'] != 'running': break
            time.sleep(.05)
        prompt = self.prompt.read_text(encoding='utf-8')
        self.assertIn('【出處：規定（檔案：規定.md） › 保固】', prompt); self.assertIn('旗艦款保固兩年', prompt)
        status, found = self.request('POST', '/api/knowledge/search', {'query': '旗艦款保固多久', 'botId': ''})
        self.assertEqual(status, 200); self.assertEqual(found['mode'], 'match'); self.assertIn('保固兩年', found['passages'][0]['text'])
        self.assertEqual(found['passages'][0]['label'], '規定（檔案：規定.md） › 保固')
        self.assertEqual(self.request('POST', '/api/knowledge/search', {'query': '', 'botId': ''})[0], 400)
        self.assertEqual(self.request('POST', '/api/knowledge/search', {'query': 'x', 'botId': 'nobody'})[0], 400)
        self.assertEqual(self.request('POST', '/api/knowledge/search', {'query': 'x', 'botId': 0})[0], 400)
        self.request('DELETE', '/api/knowledge/' + upload['id'])
        found = self.request('POST', '/api/knowledge/search', {'query': '旗艦款保固多久', 'botId': ''})[1]
        self.assertNotIn('保固兩年', json.dumps(found, ensure_ascii=False))


class KnowledgeSearchPage(unittest.TestCase):
    def test_try_search_box_and_detail_default(self):
        js = '\n'.join(f.read_text(encoding='utf-8') for f in sorted((ROOT / 'frontend/js').glob('*.js')))
        self.assertIn('id="know-search-form"', js); self.assertIn("post('knowledge/search'", js); self.assertIn("form.id === 'know-search-form'", js)
        self.assertIn("dropdown('botId', ks.botId", js)  # choices as a dropdown
        start = js.index("case 'new-note':"); self.assertIn('noteModal();', js[start:js.index('break;', start)])  # from a Bot's details too: 所有 Bot
        self.assertIn("dropdown('botId', n.botId || ''", js)
        self.assertNotIn('Bot 會讀最新的', js)


if __name__ == '__main__': unittest.main()
