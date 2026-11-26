# -*- coding: utf-8 -*-
"""queue #57①, #83①, #64③, #79⑤, #91⑦, #327, #310③, #320 (內部路徑), #269 (成品／中間檔), #194 (群組做的檔案進產出).

- A reply shows a file's name, not where Zook or the Bot keeps it: group-files, /private/tmp, /var/folders and .zook-scratch
  paths become the name (a group's file: 「X（群組檔案）」), still a button that opens the preview. A path the user named
  themselves stays as written. A stray 「**」 left at the end is gone. Only what is shown changes; the saved words stay.
- 產出 has 成品 and 中間檔: the script a Bot made its files with and its scratch files are 中間檔, folded away at first.
- A file a member made in a group is in that member's own 產出, marked with the group's name.
"""
import datetime, importlib.util, json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
JS = {p.name: p.read_text(encoding='utf-8') for p in (ROOT / 'frontend/js').glob('*.js')}
NODE = shutil.which('node') or next((p for p in [os.path.expanduser('~/.local/bin/node'), '/opt/homebrew/bin/node', '/usr/local/bin/node'] if os.access(p, os.X_OK)), None)


def load():
    spec = importlib.util.spec_from_file_location('zook_paths_outputs_57', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def run(code):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'h.js'; f.write_text(code, encoding='utf-8')
        out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    if out.returncode: raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, 'needs node to run the page code')
class InnerPaths(unittest.TestCase):
    def hide(self, texts, said=()):
        code = JS.get('35b-paths.js', '')
        self.assertIn('function hidePrivatePaths', code)
        return run(code + '\nconsole.log(JSON.stringify(%s.map(t => hidePrivatePaths(t, %s))));' % (json.dumps(texts, ensure_ascii=False), json.dumps([dict(role='user', content=x) for x in said] + [dict(role='assistant', content='/tmp/other/')], ensure_ascii=False)))

    def test_group_files_and_scratch_paths_become_names(self):
        g = '/Users/x/Library/Application Support/swarmr/group-files/g1/報價單.xlsx'
        t = '/private/tmp/zook-test/group-files/g1/簡報.pptx'
        got = self.hide([
            '已存到 %s，請查看。' % g,
            '最終版：**%s**' % t,
            '我在 `/private/tmp/tmp.Ab12/build.py` 產生了 `/private/tmp/tmp.Ab12/out/報告.pdf`',
            '驗收用的暫存：/Users/x/Library/Application Support/swarmr/workspaces/%s/.zook-scratch/pv/1.png' % ('c' * 32),
            '暫存在 /var/folders/ab/xyz/T/tmp9/圖.png',
            '群組檔案：%s' % g,
            '已完成：報價單.xlsx（%s）' % g,
        ])
        self.assertEqual(got[0], '已存到 [報價單.xlsx](<%s>)（群組檔案），請查看。' % g)
        self.assertEqual(got[1], '最終版：**[簡報.pptx](<%s>)（群組檔案）**' % t)
        self.assertEqual(got[2], '我在 [build.py](</private/tmp/tmp.Ab12/build.py>) 產生了 [報告.pdf](</private/tmp/tmp.Ab12/out/報告.pdf>)')
        self.assertEqual(got[3], '驗收用的暫存：[1.png](</Users/x/Library/Application Support/swarmr/workspaces/%s/.zook-scratch/pv/1.png>)' % ('c' * 32))
        self.assertEqual(got[4], '暫存在 [圖.png](</var/folders/ab/xyz/T/tmp9/圖.png>)')
        self.assertEqual(got[5], '群組檔案：[報價單.xlsx](<%s>)' % g)
        self.assertEqual(got[6], '已完成：[報價單.xlsx](<%s>)（群組檔案）' % g)  # named once
        for text in got: self.assertNotIn('/private/tmp/tmp.Ab12/out/報告.pdf ', text)

    def test_a_folder_says_what_it_is(self):
        got = self.hide(['檔案都在 /private/tmp/zook-ab12/ 裡', '放在 /Users/x/Library/Application Support/swarmr/group-files/g1/ 了'])
        self.assertEqual(got, ['檔案都在 暫存資料夾 裡', '放在 群組檔案 了'])
        g = '/Users/x/Library/Application Support/swarmr/group-files/g1/LICENSE'
        self.assertEqual(self.hide(['看 %s' % g]), ['看 [LICENSE](<%s>)（群組檔案）' % g])  # a file without an extension is still a file

    def test_a_place_the_user_named_stays(self):
        said = ['請存到 /tmp/zook-inspect/A/ 給我']
        got = self.hide(['已存到 /tmp/zook-inspect/A/報表.xlsx', '已存到 /private/tmp/zook-inspect/A/報表.xlsx', '另外 /tmp/other/x.png'], said)
        self.assertEqual(got[:2], ['已存到 /tmp/zook-inspect/A/報表.xlsx', '已存到 /private/tmp/zook-inspect/A/報表.xlsx'])
        self.assertEqual(got[2], '另外 [x.png](</tmp/other/x.png>)')

    def test_other_text_and_links_stay(self):
        texts = ['看 /Users/x/Desktop/報告.pdf', '[報告](https://example.com/tmp/a.pdf)', '路徑 /tmp 是系統的', '一般文字 **重點** 結束']
        self.assertEqual(self.hide(texts), texts)

    def test_a_link_keeps_its_target_but_not_a_path_as_its_words(self):
        t = '/private/tmp/x/報告.pdf'
        got = self.hide(['[%s](%s)' % (t, t), '[報告](%s)' % t, '```\ncp %s ~/Desktop\n```' % t])
        self.assertEqual(got, ['[報告.pdf](%s)' % t, '[報告](%s)' % t, '```\ncp 報告.pdf ~/Desktop\n```'])

    def test_a_stray_bold_mark_at_the_end_goes(self):
        got = self.hide(['完成，檔案已交付。**', '**重點**', '第一行\n結論：都好了 **'])
        self.assertEqual(got, ['完成，檔案已交付。', '**重點**', '第一行\n結論：都好了'])

    def test_group_and_chat_replies_use_it_and_keep_the_saved_words(self):
        self.assertIn('hidePrivatePaths(hideInnerPaths(m.content), g.messages)', JS['10-chat.js'])
        self.assertIn('hidePrivatePaths(m.content, b.messages)', JS['10-chat.js'])  # a Bot's own chat too (#310③)
        self.assertIn('markdown(hidePrivatePaths(partialFor(m), b.messages))', JS['10-chat.js'])  # and while the words come in
        self.assertIn('markdown(hidePrivatePaths(hideInnerPaths(partialFor(m)), g.messages))', JS['10-chat.js'])
        self.assertIn('\\/workspaces\\/[0-9a-f]{32}\\/(?:[^\\s`\'"<>()（）「」，、*]*\\/)?([^\\s`\'"<>()（）「」，、\\/*]+)/g', JS['10-chat.js'])  # 「x.pptx**」 is not one name


class Outputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(os.path.realpath(self.temp.name))
        self.store = self.m.Store(self.root / 'data'); self.m._active['data'] = self.store.data
        self.bot = dict(id='b' * 32, name='設計師', access='full'); self.store.data['bots'].append(self.bot)
        self.other = dict(id='o' * 32, name='企劃', access='full'); self.store.data['bots'].append(self.other)

    def tearDown(self): self.m.PROGRESS.clear(); self.temp.cleanup()

    def job(self, job_id, content, ago=5):
        start = datetime.datetime.fromtimestamp(time.time() - ago, datetime.timezone.utc).isoformat()
        end = datetime.datetime.fromtimestamp(time.time() + 1, datetime.timezone.utc).isoformat()
        self.store.data['jobs'].append(dict(id=job_id, botId=self.bot['id'], status='completed', content=content, createdAt=start, finishedAt=end, toolCalls=[]))

    def test_scripts_and_scratch_files_are_work_files(self):
        ws = self.store.dir / 'workspaces' / self.bot['id']; ws.mkdir(parents=True)
        (ws / '報告.docx').write_bytes(b'x'); (ws / 'build.py').write_text('print(1)')
        scratch = Path('/private/tmp') / ('zook57-' + os.urandom(4).hex()); scratch.mkdir()
        self.addCleanup(shutil.rmtree, str(scratch), True)
        (scratch / 'pv.png').write_bytes(b'x')
        self.job('j1', '預覽圖在 %s' % (scratch / 'pv.png'))
        got = {o['name']: o.get('stage') for o in self.m.bot_outputs_all(self.store, self.bot)}
        self.assertEqual(got, {'報告.docx': 'final', 'build.py': 'work', 'pv.png': 'work'})

    def test_a_scratch_place_the_user_asked_for_is_final(self):
        asked = Path('/private/tmp') / ('zook57-' + os.urandom(4).hex()); asked.mkdir()
        self.addCleanup(shutil.rmtree, str(asked), True)
        (asked / '報表.xlsx').write_bytes(b'x')
        self.bot.update(chatId='c1', chats=[dict(id='c1', title='')], messages=[dict(id='u1', role='user', content='做好存到 %s/' % asked), dict(id='a1', role='assistant', content='')])
        self.job('j2', '好了')
        self.store.data['jobs'][-1].update(chatId='c1', messageId='a1')
        got = {o['name']: o.get('stage') for o in self.m.bot_outputs_all(self.store, self.bot)}
        self.assertEqual(got.get('報表.xlsx'), 'final')

    def test_a_file_made_in_a_group_is_in_the_makers_outputs(self):
        folder = self.store.dir / 'group-files' / 'g1'; folder.mkdir(parents=True)
        for n in ('海報.pptx', '企劃.docx', '上傳.pdf', '舊的.png'): (folder / n).write_bytes(b'x')
        self.store.data['groups'] = [dict(id='g1', name='行銷小組', botIds=[self.bot['id'], self.other['id']], messages=[], fileInfo={
            '海報.pptx': {'by': '設計師', 'byId': self.bot['id']}, '企劃.docx': {'by': '企劃', 'byId': self.other['id']},
            '上傳.pdf': {'by': '你'}, '舊的.png': {'by': '設計師'}})]
        mine = {o['name']: o for o in self.m.bot_outputs_all(self.store, self.bot)}
        self.assertEqual(sorted(mine), ['海報.pptx', '舊的.png'])
        self.assertEqual(mine['海報.pptx']['group'], '行銷小組'); self.assertEqual(mine['海報.pptx']['stage'], 'final')
        item = self.m.bot_output(self.store, self.bot, mine['海報.pptx']['id'])  # it opens and downloads like any other output
        self.assertEqual(self.m.output_response(item)[0], b'x')
        self.assertNotIn('海報.pptx', [o['name'] for o in self.m.bot_outputs_all(self.store, self.other)])

    def test_a_link_in_the_group_folder_is_not_listed(self):
        folder = self.store.dir / 'group-files' / 'g1'; folder.mkdir(parents=True)
        secret = self.root / 'secret.txt'; secret.write_text('s'); os.symlink(str(secret), str(folder / '海報.pptx'))
        self.store.data['groups'] = [dict(id='g1', name='行銷小組', botIds=[self.bot['id']], messages=[], fileInfo={'海報.pptx': {'by': '設計師', 'byId': self.bot['id']}})]
        self.assertEqual([o['name'] for o in self.m.bot_outputs_all(self.store, self.bot)], [])

    def test_a_group_folder_that_is_a_link_is_not_listed(self):
        away = self.root / 'away'; away.mkdir(); (away / '海報.pptx').write_bytes(b'x')
        (self.store.dir / 'group-files').mkdir(parents=True); os.symlink(str(away), str(self.store.dir / 'group-files' / 'g1'))
        self.store.data['groups'] = [dict(id='g1', name='行銷小組', botIds=[self.bot['id']], messages=[], fileInfo={'海報.pptx': {'by': '設計師', 'byId': self.bot['id']}})]
        self.assertEqual([o['name'] for o in self.m.bot_outputs_all(self.store, self.bot)], [])


class Panel(unittest.TestCase):
    def test_final_and_work_files(self):
        src = JS['36-outputs.js']
        for words in ('成品', '中間檔', '顯示中間檔', '來自群組'): self.assertIn(words, src)
        self.assertNotIn('顯示製作用的程式', src)
        handler = (ROOT / 'backend/zook/handler.py').read_text(encoding='utf-8')
        self.assertIn("{'outputs': bot_outputs_all(store, bot)}", handler)


if __name__ == '__main__': unittest.main()
