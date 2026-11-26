# -*- coding: utf-8 -*-
"""#84, #122, #123 知識庫: files can be added (txt, md, pdf, docx, xlsx …), each item says 處理中 / Bot 可使用 / 失敗（原因）, every Bot shares
it unless one Bot is picked in 「給誰用」, and a Bot's reply really carries the text read out of a file. Older items (typed text, tags)
keep working as they were. Needs only what macOS has (textutil, osascript); no AI CLI."""
import http.client, io, json, os, re, subprocess, sys, tempfile, time, unittest, zipfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = ROOT / 'frontend/js'


def pdf_bytes(text):
    stream = ('BT /F1 18 Tf 72 720 Td (%s) Tj ET' % text).encode() if text else b'q Q'
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
            b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1): offsets.append(len(out)); out += b'%d 0 obj\n' % i + o + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offsets)
    return out + b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)


def xlsx_bytes():
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('xl/workbook.xml', '<workbook %s><sheets><sheet name="價目表" sheetId="1" r:id="rId1"/></sheets></workbook>' % ns)
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr('xl/sharedStrings.xml', '<sst %s><si><t>品名</t></si><si><t>滑鼠 MX9</t></si></sst>' % ns)
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet %s><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>價格</t></is></c></row><row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>2990</v></c></row></sheetData></worksheet>' % ns)
    return buf.getvalue()


class KnowledgeFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir(); (self.root / 'assets/index.html').write_text('hello')
        (self.root / 'bin').mkdir()
        cli = self.root / 'bin/codex'  # writes down the prompt it was given
        cli.write_text('#!/usr/bin/env python3\nimport os,sys\ns=sys.stdin.read()\nopen(os.environ["PROMPT_FILE"],"a").write(s)\nprint("ok")\n'); cli.chmod(0o755)
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

    def upload(self, name, data, title='', bot=''):
        return self.request('POST', '/api/knowledge/file', raw=data, headers={'X-File-Name': quote(name), 'X-Title': quote(title), 'X-Bot-Id': quote(bot), 'Content-Type': 'application/octet-stream'})

    def item(self, item_id):
        return next(x for x in self.request('GET', '/api/state')[1]['knowledge'] if x['id'] == item_id)

    def settled(self, item_id):
        for _ in range(300):
            x = self.item(item_id)
            if x['status'] != 'processing': return x
            time.sleep(.05)
        self.fail('still processing')

    def test_files_are_read_and_say_how_it_went(self):
        status, item = self.upload('公司規定.md', '# 請假\n請假要提前三天申請。'.encode('utf-8'))
        self.assertEqual(status, 201); self.assertEqual(item['status'], 'processing'); self.assertEqual(item['title'], '公司規定'); self.assertEqual(item['botId'], '')
        done = self.settled(item['id'])
        self.assertEqual(done['status'], 'ready'); self.assertIn('請假要提前三天申請', done['content']); self.assertEqual(done['source'], '公司規定.md')
        self.assertTrue((self.root / 'data/knowledge' / item['id'] / 'source.md').is_file())
        pdf = self.settled(self.upload('manual.pdf', pdf_bytes('Return within 30 days'), title='退貨規定')[1]['id'])
        self.assertEqual(pdf['status'], 'ready'); self.assertIn('Return within 30 days', pdf['content']); self.assertEqual(pdf['title'], '退貨規定')
        sheet = self.settled(self.upload('價目.xlsx', xlsx_bytes())[1]['id'])
        self.assertEqual(sheet['status'], 'ready'); self.assertIn('滑鼠 MX9\t2990', sheet['content']); self.assertIn('價目表', sheet['content'])
        source = self.root / 'note.txt'; source.write_text('會議室在三樓', encoding='utf-8')
        subprocess.run(['/usr/bin/textutil', '-convert', 'docx', str(source), '-output', str(self.root / 'note.docx')], check=True)
        doc = self.settled(self.upload('note.docx', (self.root / 'note.docx').read_bytes())[1]['id'])
        self.assertEqual(doc['status'], 'ready'); self.assertIn('會議室在三樓', doc['content'])
        big5 = self.settled(self.upload('舊檔.txt', '繁體中文舊檔案'.encode('cp950'))[1]['id'])
        self.assertEqual(big5['content'], '繁體中文舊檔案')
        page = self.settled(self.upload('說明.html', '<html><head><script>steal()</script><img src="https://example.invalid/x.png"></head><body><h1>營業時間</h1><p>週一到週五 9 點</p></body></html>'.encode())[1]['id'])
        self.assertEqual(page['status'], 'ready'); self.assertIn('週一到週五 9 點', page['content']); self.assertNotIn('steal', page['content'])  # read here, never opened in WebKit
        # Failures say why.
        self.assertEqual(self.settled(self.upload('假的.rtf', b'<html>not rtf</html>')[1]['id'])['status'], 'failed')
        empty = self.settled(self.upload('scan.pdf', pdf_bytes(''))[1]['id'])
        self.assertEqual(empty['status'], 'failed'); self.assertIn('讀不到文字', empty['error'])
        broken = self.settled(self.upload('壞掉.docx', b'not a word file')[1]['id'])
        self.assertEqual(broken['status'], 'failed'); self.assertTrue(broken['error'])
        status, err = self.upload('photo.zip', b'PK\x03\x04')
        self.assertEqual(status, 400); self.assertIn('不支援', err['error']); self.assertIn('pdf', err['error'])

    def test_what_a_bot_reads(self):
        bots = self.request('GET', '/api/state')[1]['bots']; bot = bots[0]
        other = self.request('POST', '/api/bots', {'name': '另一個'})[1]
        self.request('PATCH', '/api/bots/' + bot['id'], {'provider': 'codex'})
        typed = self.request('POST', '/api/knowledge', {'title': '地址', 'content': '台北市信義路一段', 'tags': ['舊標籤']})[1]  # the way items were always made
        self.assertEqual(self.item(typed['id'])['status'], 'ready')
        ready = self.settled(self.upload('產品.txt', '旗艦款保固兩年'.encode())[1]['id'])
        failed = self.settled(self.upload('掃描.pdf', pdf_bytes(''))[1]['id'])
        mine = self.settled(self.upload('只給別人.txt', '這段只給另一個 Bot'.encode(), bot=other['id'])[1]['id'])
        self.assertEqual(mine['botId'], other['id'])
        reply = self.request('POST', '/api/chat', {'botId': bot['id'], 'content': '保固多久？'})[1]
        for _ in range(200):
            if self.request('GET', '/api/jobs/' + reply['jobId'])[1]['status'] != 'running': break
            time.sleep(.05)
        prompt = self.prompt.read_text(encoding='utf-8')
        self.assertIn('【出處：產品（檔案：產品.txt）】\n旗艦款保固兩年', prompt); self.assertIn('【出處：地址】\n台北市信義路一段', prompt)
        self.assertNotIn('這段只給另一個 Bot', prompt); self.assertNotIn(failed['title'], prompt)
        # Older tags stay when an item is changed without them; a file's text cannot be overwritten; a Bot that is not there is refused.
        self.assertEqual(self.request('PATCH', '/api/knowledge/' + typed['id'], {'title': '公司地址', 'botId': ''})[0], 200)
        self.assertEqual(self.item(typed['id'])['tags'], ['舊標籤'])
        status, err = self.request('PATCH', '/api/knowledge/' + ready['id'], {'content': '改掉'})
        self.assertEqual(status, 400); self.assertIn('重新上傳', err['error'])
        self.assertEqual(self.request('PATCH', '/api/knowledge/' + ready['id'], {'title': '保固', 'botId': bot['id']})[0], 200)
        self.assertEqual(self.request('POST', '/api/knowledge', {'title': 'x', 'content': 'y', 'botId': 'nobody'})[0], 400)
        self.assertEqual(self.upload('a.txt', b'x', bot='nobody')[0], 400)
        # Deleting a file's item removes the file too.
        self.assertEqual(self.request('DELETE', '/api/knowledge/' + ready['id'])[0], 200)
        self.assertFalse((self.root / 'data/knowledge' / ready['id']).exists())

    def test_long_name_keeps_its_type(self):
        item = self.settled(self.upload('很長的檔名' * 40 + '.md', '內容'.encode())[1]['id'])
        self.assertEqual(item['status'], 'ready'); self.assertTrue(item['source'].endswith('.md'))

    def test_file_count_limit(self):
        ids = [self.upload('f%d.txt' % i, b'x')[1]['id'] for i in range(50)]
        status, err = self.upload('one-more.txt', b'x')
        self.assertEqual(status, 400); self.assertIn('50', err['error'])
        self.request('DELETE', '/api/knowledge/' + ids[0])
        self.assertEqual(self.upload('one-more.txt', b'x')[0], 201)


class KnowledgeUnits(unittest.TestCase):
    def setUp(self):
        self.ns = {'__file__': str(ROOT / 'backend/server.py')}
        for part in ('core', 'knowledge', 'knowsearch'):
            f = ROOT / 'backend/zook' / (part + '.py'); exec(compile(f.read_text(encoding='utf-8'), str(f), 'exec'), self.ns)

    def test_only_ready_items_newest_ten_when_nothing_matches(self):
        class S: data = {'knowledge': [dict(id=str(i), title='t%d' % i, content='c' * 5000, botId='') for i in range(12)]
                                       + [dict(id='p', title='p', content='', status='processing', botId=''), dict(id='f', title='f', content='', status='failed', botId=''),
                                          dict(id='o', title='o', content='x', botId='other')]}
        S.find = lambda kind, item_id: None
        picked = self.ns['knowledge_for'](S, {'id': 'me'}, '你好')  # #295: nothing matches → the newest items in short, within the budget
        self.assertEqual([x['id'] for x in picked], [str(i) for i in range(11, 4, -1)])  # labels count against the budget too
        self.assertLessEqual(sum(len(x['text']) for x in picked), self.ns['KNOWLEDGE_BUDGET'])
        self.assertIn('【出處：t11】\n' + 'c' * 1500, self.ns['knowledge_lines'](picked[:1]))

    def test_review_findings(self):
        import tempfile as _t
        with _t.TemporaryDirectory() as d:
            d = Path(d)
            ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            with zipfile.ZipFile(d / 'gap.xlsx', 'w') as z:  # B is left out: the price stays in column C
                z.writestr('xl/worksheets/sheet1.xml', '<worksheet %s><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>品名</t></is></c><c r="C1"><v>99</v></c></row></sheetData></worksheet>' % ns)
            self.assertIn('品名\t\t99', self.ns['knowledge_extract'](d / 'gap.xlsx'))
            with zipfile.ZipFile(d / 'bomb.xlsx', 'w', zipfile.ZIP_DEFLATED) as z:  # one shared string used many times stops at the limit
                z.writestr('xl/sharedStrings.xml', '<sst %s><si><t>%s</t></si></sst>' % (ns, 'x' * 5000))
                z.writestr('xl/worksheets/sheet1.xml', '<worksheet %s><sheetData><row r="1">%s</row></sheetData></worksheet>' % (ns, '<c t="s"><v>0</v></c>' * 5000))
            self.assertLessEqual(len(self.ns['knowledge_extract'](d / 'bomb.xlsx')), self.ns['KNOWLEDGE_TEXT'] + 10)
            with zipfile.ZipFile(d / 'empty.pptx', 'w') as z:
                z.writestr('ppt/slides/slide1.xml', '<p:sld xmlns:p="x"/>')
            self.assertEqual(self.ns['knowledge_extract'](d / 'empty.pptx'), '')  # page headings alone are not content: the item fails
            (d / 'outside').mkdir(); (d / 'data').mkdir(); (d / 'data/knowledge').symlink_to(d / 'outside')
            class S: dir = d / 'data'
            self.assertIsNone(self.ns['_knowledge_folder'](S, 'a' * 32))  # a linked knowledge folder is never written to or emptied

    def test_synced_file_name_is_checked(self):
        ns = {'__file__': str(ROOT / 'backend/server.py')}
        for part in ('core', 'knowledge', 'sync'):
            f = ROOT / 'backend/zook' / (part + '.py'); exec(compile(f.read_text(encoding='utf-8'), str(f), 'exec'), ns)
        clean = lambda source: ns['sync_clean']('knowledge:' + 'a' * 32, dict(title='t', content='c', botId='', tags=[], source=source))
        self.assertEqual(clean('手冊.pdf')['source'], '手冊.pdf')
        for bad in ('\x85.pdf', '\ud800.pdf', 'a/b.pdf', 'a\nb.pdf', 5): self.assertIsNone(clean(bad), bad)

    def test_prompts_use_the_shared_choice(self):
        for name in ('app.py', 'groups.py'):
            text = (ROOT / 'backend/zook' / name).read_text(encoding='utf-8')
            self.assertIn('knowledge_for(store, bot, ', text); self.assertIn('knowledge_lines(knowledge)', text)
            self.assertNotIn("store.data['knowledge'] if", text)


class KnowledgePage(unittest.TestCase):
    def setUp(self):
        self.js = '\n'.join(f.read_text(encoding='utf-8') for f in sorted(JS.glob('*.js')))
        self.maxDiff = 200
        self.assertIn = lambda part, whole: self.assertTrue(part in whole, 'missing: ' + part)
        self.assertNotIn = lambda part, whole: self.assertFalse(part in whole, 'still there: ' + part)

    def test_form(self):
        self.assertNotIn('標籤（以逗號分隔）', self.js); self.assertNotIn('關聯 Bot', self.js)
        self.assertIn('給誰用', self.js); self.assertIn("dropdown('botId'", self.js); self.assertIn("dropdown('source'", self.js)
        self.assertIn('所有 Bot', self.js); self.assertIn('/api/knowledge/file', self.js)

    def test_one_name(self):
        self.assertNotIn('>資料庫<', self.js); self.assertNotIn('共用知識', self.js); self.assertNotIn('新增筆記', self.js)
        self.assertRegex(self.js, r'data-id="database"[^>]*>知識庫<')

    def test_card_and_delete(self):
        self.assertIn('Bot 可使用', self.js); self.assertIn('處理中', self.js); self.assertIn('失敗：', self.js)
        self.assertIn('KNOW_BUDGET = 12000', self.js); self.assertNotIn('Bot 只會讀前', self.js)  # #295: the same budget as the reply (knowsearch.py)
        self.assertIn('KNOWLEDGE_BUDGET = 12000', (ROOT / 'backend/zook/knowsearch.py').read_text(encoding='utf-8'))
        start = self.js.index("case 'delete-note':"); body = self.js[start:self.js.index('break;', start)]
        self.assertIn('ask(', body); self.assertIn('.title', body)


if __name__ == '__main__': unittest.main()
