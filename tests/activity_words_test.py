# -*- coding: utf-8 -*-
"""#82 #144: the activity list says in plain words what a command did; never words of code, internal codes or 「無法判讀」."""
import importlib.util, json, pathlib, shlex, tempfile, unittest

spec = importlib.util.spec_from_file_location('zook_activity_words', pathlib.Path(__file__).parents[1] / 'backend/server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
codex = lambda script: '/bin/zsh -lc ' + shlex.quote(script)  # how Codex reports a command
UNREADABLE = '執行一段 Zook 看不出內容的指令'
FRAGMENTS = ('leakword', 'magicword', 'zzword', 'secret-folder', 'hunter2', 'abc.def', 'from', 'print', 'wf.sheetnames', 'PY', 'import', 'def', 'for', 'do', 'done', 'console.log', 'DOCX_MODULE_MISSING', '無法判讀', '引號')

EXCEL = """python3 - <<'PY'
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
for r in range(3): ws.append([r, "it's"])
print(wb.sheetnames)
wb.save('/w/報表.xlsx')
PY"""


class ActivityWordsTest(unittest.TestCase):
    def say(self, command):
        text = m.command_summary(command)
        for word in FRAGMENTS:
            self.assertNotRegex(text, r'(^|[：、；\s])%s($|[、；\s])' % word if word.isascii() else word, '%r -> %s' % (command, text))
        return text

    def test_python_heredoc_is_one_plain_step(self):
        self.assertEqual(self.say(EXCEL), '執行 Python 程式（產生 Excel）')
        self.assertEqual(self.say(codex(EXCEL)), '執行 Python 程式（產生 Excel）')
        self.assertEqual(self.say("python3 - <<'PY'\nimport openpyxl\nwf = openpyxl.load_workbook('a.xlsx')\nprint(wf.sheetnames)\nPY"), '執行 Python 程式（讀取 Excel）')
        self.assertEqual(self.say('python3 -c "import docx" 2>/dev/null || echo DOCX_MODULE_MISSING'), '執行 Python 程式（讀取 Word 文件）')
        self.assertEqual(self.say('node <<EOF\nconst e = require("exceljs");\nconsole.log(e)\nEOF'), '執行 JavaScript 程式（讀取 Excel）')

    def test_temp_file_then_cat_heredoc(self):
        text = self.say('T=$(mktemp)\ncat > "$T" <<\'EOF\'\nimport json\ndef filename(): return 1\nworkbook = 2\nEOF\npython3 "$T"')
        self.assertEqual(text, '建立暫存檔、執行 Python 程式')

    def test_loops_and_files(self):
        self.assertEqual(self.say('for f in *.png; do sips -Z 100 "$f"; done'), '處理圖片')
        self.assertEqual(self.say('cat /d/workspaces/b1/attachments/ae1f6faf-C02-上週客服工單.csv | head -5'), '讀取你上傳的附件「C02-上週客服工單.csv」')
        self.assertEqual(self.say('ls -la && grep -n x notes.txt'), '查看資料夾內容、搜尋檔案內容')
        self.assertEqual(self.say('echo hi > /w/out.md'), '寫入檔案「out.md」')
        self.assertEqual(self.say('find . -name "*.xlsx" 2>/dev/null | head'), '尋找檔案')
        self.assertEqual(self.say('cd /w && python3 make_report.py'), '執行 Python 程式「make_report.py」')

    def test_unreadable_says_so_plainly_and_safety_lines_stay(self):
        self.assertEqual(self.say('$RUN --go'), '執行一段 Zook 看不出內容的指令')
        self.assertEqual(self.say('rm -rf /w/old'), '刪除檔案')  # the boundary by its name: no paths or arguments
        text = self.say("python3 - <<'PY'\nimport shutil\nshutil.rmtree('/w/tmp')\nPY")
        self.assertEqual(text, '執行 Python 程式')
        text = self.say('curl -H "Authorization: Bearer SECRET-77" https://api.example.com/x?token=abc')
        self.assertEqual(text, '從網路取得資料'); self.assertNotIn('SECRET', text)

    def test_nothing_of_the_command_leaks(self):
        self.assertEqual(self.say("cat > /w/note.txt <<'EOF'\nrm -rf /w/secret-folder\nEOF"), '寫入檔案「note.txt」')  # a here-document is data
        self.assertEqual(self.say("cat > /w/a.txt <<123\nmagicword one\n123\n"), '寫入檔案「a.txt」')
        self.assertEqual(self.say("python3 - <<PY\nprint(1)\n  PY\nzzword\nPY"), '執行 Python 程式')  # only a line that is exactly the marker ends it
        for command in ('curl --oauth2-bearer abc.def.ghi https://api.example.com/x', 'wget --password hunter2.example.com https://api.example.com/x'):
            self.assertEqual(self.say(command), '從網路取得資料')
        self.assertEqual(self.say('python3 -c "x = `leakword`; print(\'leakword\')"'), '執行 Python 程式')
        self.assertEqual(self.say("bash -c \"bash -c 'bash -c \\\"bash -c leakword\\\"'\""), UNREADABLE)
        self.assertEqual(self.say('leakword --go'), '執行其他程式')  # a name Zook does not know is not shown
        self.assertEqual(self.say('cat README.md && wc < notes.txt'), '讀取檔案「README.md」、讀取檔案「notes.txt」')
        self.assertEqual(self.say("perl -E 'say \"leakword\"'"), '執行 Perl 程式')
        self.assertEqual(self.say("php -r 'echo \"leakword\";'"), '執行 PHP 程式')
        self.assertEqual(self.say("sed -i '' 's/old/leakword/' report.txt"), '修改檔案「report.txt」')
        self.assertNotIn('leakword', m.command_summary("printf %s '>' leakword"))
        self.assertEqual(self.say("cat <<'END'E\nleakword one\nEND\nENDE"), UNREADABLE)
        self.assertEqual(self.say('cat /tmp/project/attachments/deadbeef-notes.txt'), '讀取檔案「deadbeef-notes.txt」')
        self.assertEqual(self.say('unzip -P leakword.pass data.zip'), '解壓縮檔案「data.zip」')
        self.assertEqual(self.say('pdftotext -upw leakword.pass in.pdf out.txt'), '讀取檔案「in.pdf」')
        self.assertEqual(self.say('ruby -ne STDIN.leakword'), '執行 Ruby 程式')
        self.assertEqual(self.say('python3 -m leakword.tool'), '執行 Python 模組')
        self.assertNotIn('leakword', m.command_summary("printf %s '>' leakword.pass"))  # a '>' in quotes is not a redirection
        self.assertNotIn('leakword', m.command_summary('echo ok # > leakword.pass'))
        self.assertEqual(self.say('cat <<:EOF\ncat leakword.pass\n:EOF'), UNREADABLE)
        self.assertEqual(m.plain_old_summary('一個 curl 指令裡有多次傳送（2 個目的地、0 個檔案）；刪除檔案 /x/leakword'), '一次做了好幾次傳送；刪除檔案')
        self.assertEqual(self.say('cat /w/deadbeef-plan.txt'), '讀取檔案「deadbeef-plan.txt」')  # only an attachment loses the id
        self.assertEqual(m.command_summary('cat /w/\udcff.txt').encode('utf-8').decode('utf-8'), '讀取檔案「?.txt」')

    def test_old_records_are_put_in_plain_words(self):
        self.assertEqual(m.plain_old_summary('執行指令：python3、from、print、wf.sheetnames、for、PY'), '執行 Python 程式')
        self.assertEqual(m.plain_old_summary('執行無法判讀的指令（要執行的程式是變數）（共 4 次）'), '執行一段 Zook 看不出內容的指令')
        self.assertEqual(m.plain_old_summary('刪除檔案 ~/a；執行無法判讀的指令（引號沒有成對）'), '刪除檔案')
        self.assertEqual(m.plain_old_summary('對外送出 檔案 /tmp/a.json 到 api.example.com'), '對外送出')
        self.assertEqual(m.plain_old_summary('執行指令：mktemp、echo、cat、import、def'), '建立暫存檔')
        self.assertEqual(m.plain_old_summary('上網搜尋'), '上網搜尋')
        self.assertEqual(m.plain_old_summary('讀取檔案「a；b.txt」'), '讀取檔案「a；b.txt」')  # today's words are left alone
        self.assertEqual(m.plain_old_summary('刪除檔案 /tmp/old；leakword'), '刪除檔案')
        store = type('S', (), {})(); store.data = {'jobs': [{'toolCalls': [{'name': 'native_command', 'arguments': {'summary': '執行指令：node、console.log、e'}},
                                                                           {'name': 'native_command', 'arguments': {'command': 'ls'}}, {'name': 'native_command', 'arguments': 'x'}, None]}, {'toolCalls': 'x'}]}
        m.plain_old_records(store)
        self.assertEqual(store.data['jobs'][1]['toolCalls'], [])  # a list the screens can read
        self.assertEqual([c['arguments'] for c in store.data['jobs'][0]['toolCalls']], [{'summary': '執行 JavaScript 程式'}, {'summary': '查看資料夾內容'}, {'summary': '執行指令'}])
        with tempfile.TemporaryDirectory() as d:  # a data file from an earlier version or a restored backup is put in plain words when it is opened
            (pathlib.Path(d) / 'swarmr.json').write_text(json.dumps({'bots': [], 'jobs': [{'id': 'j', 'status': 'completed', 'toolCalls': [{'name': 'native_command', 'arguments': {'command': 'echo hunter2 | pbcopy'}}]}]}), encoding='utf-8')
            self.assertEqual(m.Store(d).data['jobs'][0]['toolCalls'][0]['arguments'], {'summary': '複製到剪貼簿'})

    def test_codex_output_and_mobile_use_the_plain_line(self):
        out = m.parse_cli_output('codex', '\n'.join(json.dumps(o, ensure_ascii=False) for o in (
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': codex(EXCEL), 'exit_code': 0}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '好了'}})))
        self.assertEqual(out['web'][0]['arguments'], {'summary': '執行 Python 程式（產生 Excel）'})
        self.assertEqual(m.describe_call(out['web'][0]), '執行 Python 程式（產生 Excel）')
        self.assertEqual(m.describe_call(dict(name='native_command', arguments={'summary': '執行指令'})), '在工作資料夾執行指令')


class FrontendTest(unittest.TestCase):
    def test_timeline_strips_the_attachment_id_and_says_why_a_step_failed(self):
        js = ''.join(p.read_text(encoding='utf-8') for p in sorted((pathlib.Path(__file__).parents[1] / 'frontend/js').glob('*.js')))
        self.assertTrue('[0-9a-f]{8}-' in js)  # fileName drops the id Zook puts in front of an uploaded file
        self.assertTrue('evNote(' in js)
        self.assertFalse('arguments.command' in js)  # a tooltip never shows a command kept by an old version
        self.assertTrue('last.label === r.label' in js)  # red steps with different reasons are not merged  # a red step says in words why (你沒有允許／沒有成功), not only by its color


if __name__ == '__main__':
    unittest.main()
