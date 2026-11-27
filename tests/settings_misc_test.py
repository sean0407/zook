# -*- coding: utf-8 -*-
"""#80 #158 #166② #168③ #138 #69①: a Bot whose model cannot answer says so (sidebar, chat, details, Bot form, schedules) and what
its backup then does; the sidebar ring agrees with the usage page about a used-up Grok; each page keeps its address on reload;
listing file names with rg --files is not called touching keys; the Bot usage table scrolls in a narrow window."""
import datetime, importlib.util, os, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_settings_misc', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def js(): return ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


def ago(hours): return (datetime.datetime.now().astimezone() - datetime.timedelta(hours=hours)).isoformat()


class RingsAgree(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.store = self.m.Store(Path(self.temp.name) / 'data')
        self.store.data['settings']['addedProviders'] = ['codex', 'claude', 'grok', 'gemini']

    def tearDown(self): self.temp.cleanup()

    def rings(self): return {r['id']: r for r in self.m.usage_rings(self.store)}

    def test_grok_used_up_without_a_reset_time_is_not_full_again(self):
        # #158④: the ring said 每週剩餘 100% six hours after Grok reported 100% used, while the menu said 已用完.
        # #323: such an old reading is 無法確定 on the ring, the cards and for the replies alike, never 100%.
        self.store.data['quota'] = {'grok': {'windows': [{'label': '每週', 'usedPercent': 100, 'resetsAt': None}], 'updatedAt': ago(6)}}
        ring = self.rings()['grok']
        self.assertEqual((ring['week'], ring['left'], ring['unknown']), (None, None, True))
        self.store.data['quota']['grok']['updatedAt'] = ago(1)  # a recent one still says used up
        self.assertEqual((self.rings()['grok']['week'], self.rings()['grok']['left']), (0, 0))

    def test_a_limit_with_a_passed_reset_is_still_full_again(self):
        self.store.data['quota'] = {'codex': {'windows': [{'label': '每週', 'usedPercent': 100, 'resetsAt': time.time() - 60}], 'updatedAt': ago(1)}}
        self.assertEqual(self.rings()['codex']['left'], 100)

    def test_a_reported_reached_limit_is_used_up(self):
        self.store.data['quota'] = {'codex': {'windows': [{'label': '每週', 'usedPercent': 40, 'resetsAt': time.time() + 3600}], 'limitReached': 'usage_limit_reached', 'updatedAt': ago(0)}}
        self.assertEqual(self.rings()['codex']['left'], 0)

    def test_sign_in_and_problem_come_with_the_rings(self):
        self.store.data['autoStatus'] = {'claude': dict(signedIn=False, billed=False), 'codex': dict(signedIn=True, billed=False)}
        self.store.data['providerIssues'] = {'codex': dict(issue='工作區的點數用完了')}
        rings = self.rings()
        self.assertIs(rings['claude']['signedIn'], False); self.assertIs(rings['codex']['signedIn'], True); self.assertIsNone(rings['gemini']['signedIn'])
        self.assertEqual(rings['codex']['issue'], '工作區的點數用完了'); self.assertEqual(rings['claude']['issue'], '')

    def test_quota_answer_carries_the_sign_in_problem(self):
        self.assertIn("issue=((store.data.get('providerIssues') or {}).get(provider) or {}).get('issue', '') if account['status'] == 'logged_in' else ''", (ROOT / 'backend/zook/handler.py').read_text(encoding='utf-8'))


class ListingFilesIsNotKeys(unittest.TestCase):
    """#138: Codex listed files with `rg --files` from the home folder to find an upload; the activity said 動到金鑰或密碼."""
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.cwd = os.getcwd(); os.chdir(os.path.expanduser('~'))
        self.gate = self.m._gate(); self.was = self.gate._CWD[0]; self.gate._CWD[0] = os.path.expanduser('~')  # commands run in the home folder

    def tearDown(self): os.chdir(self.cwd); self.gate._CWD[0] = self.was

    def test_rg_files_only_lists_names(self):
        gate = self.m._gate()
        self.assertNotIn('secret', [k for k, _ in gate.command_boundaries('rg --files')])
        self.assertNotIn('secret', [k for k, _ in gate.command_boundaries('rg --files Documents')])
        self.assertEqual(self.m.command_summary('rg --files'), '尋找檔案')

    def test_searching_contents_from_home_still_counts(self):
        gate = self.m._gate()
        self.assertIn('secret', [k for k, _ in gate.command_boundaries('rg -n 退貨')])
        self.assertIn('secret', [k for k, _ in gate.command_boundaries('grep -rn 退貨 .')])
        self.assertIn('secret', [k for k, _ in gate.command_boundaries('rg --files ~/.ssh')])  # a key folder named outright
        for line in ('rg --hidden -e --files .', 'rg --files --files-with-matches --hidden -e . .', 'rg --files --hidden | xargs -n1 cat',
                     'rg --files -z', 'rg -g --files', 'rg --files -- .', 'rg --files | rg 客訴', 'rg --files --hidden --no-ignore > /tmp/p; xargs cat < /tmp/p', 'rg --files; cat x', 'RIPGREP_CONFIG_PATH=/tmp/rg.conf rg --files', './rg --files', 'env rg --files'):  # a search after all, or names handed on (review)
            self.assertIn('secret', [k for k, _ in gate.command_boundaries(line)], line)
        self.assertNotEqual(self.m.command_summary('rg --hidden -e --files .'), '尋找檔案')
        self.assertNotIn('尋找檔案', self.m.command_summary('rg --files | xargs cat'))

    def test_only_the_plainest_form_is_a_listing(self):
        gate = self.m._gate()
        import shlex
        for line in ('rg --files --hidden -g "*.txt" Downloads', 'rg --files --hidden', 'rg --files "My Docs"', 'rg --files *', 'rg --files ~/x#y'):
            self.assertFalse(gate._rg_list_only(shlex.split(line)[1:], line), line)  # anything more than rg --files and folders: read as a search
        self.assertFalse(gate._rg_list_only(['--files'], 'rg --files', 1))  # inside $( … ), a shell's -c or eval
        self.assertTrue(gate._rg_list_only(['--files', 'Documents'], 'rg --files Documents'))
        self.assertIn('secret', [k for k, _ in gate.command_boundaries('rg --files --hidden')])
        self.assertIn('secret', [k for k, _ in gate.command_boundaries('/bin/zsh -lc "rg --files"')])

    def test_review_of_pr_111(self):
        """The three ways the final review of PR #111 found to read keys while the exemption applied."""
        gate = self.m._gate()
        for line in ('rg --hidden --no-ignore API_KEY . # --files',  # a --files in a comment
                     "cat $(rg --hidden --no-ignore --files -g '*id_rsa*')",  # names handed to cat through $( … )
                     'rg --hidden --no-ignore --pre /bin/cat -e TOKEN'):  # --pre's value read as the folder searched (also on main)
            self.assertIn('secret', [k for k, _ in gate.command_boundaries(line)], line)
            self.assertNotIn('尋找檔案', self.m.command_summary(line), line)
        self.assertIn('secret', [k for k, _ in gate.command_boundaries('rg --sort path -e KEY')])
        self.assertIn('secret', [k for k, _ in gate.command_boundaries('rg -d 3 KEY')])
        self.assertNotIn('secret', [k for k, _ in gate.command_boundaries('grep -E KEY notes.txt')])  # grep's -E takes no value


class SearchRootsFromASafeFolder(unittest.TestCase):
    """Run from a folder without keys, so a root misread as the current folder is not hidden by it being the home folder."""
    @classmethod
    def setUpClass(cls): cls.m = load()

    def setUp(self):
        self.gate = self.m._gate(); self.was = self.gate._CWD[0]; self.temp = tempfile.TemporaryDirectory(); self.gate._CWD[0] = self.temp.name  # the folder commands run in

    def tearDown(self): self.gate._CWD[0] = self.was; self.temp.cleanup()

    def kinds(self, line): return [k for k, _ in self.m._gate().command_boundaries(line)]

    def test_home_named_after_the_options_is_searched(self):
        for line in ('rg --hidden --no-ignore -e KEY -- --pre ~',  # after --, --pre is a path, not an option taking ~
                     'rg --hidden --no-ignore --pre /bin/cat -e TOKEN ~', 'rg --hidden --no-ignore --regexp=KEY ~', 'rg --hidden --no-ignore -eKEY ~',
                     'rg -gfoo KEY ~', 'rg KEY ~', 'rg --hidden --no-ignore --in /tmp/files.txt TOKEN', 'rg --in0=/tmp/f TOKEN', 'grep -r --regexp=KEY ~', 'grep -reKEY ~', 'grep -r -- KEY ~', 'rg --sort path KEY ~'):
            self.assertIn('secret', self.kinds(line), line)
        self.gate._CWD[0] = os.path.expanduser('~')  # these search the current folder: from home it holds keys
        for line in ('rg -- --files', 'rg -- --regexp=KEY', 'grep -r -- --regexp=KEY', 'rg --maxdepth 1 TOKEN', 'ggrep -d recurse TOKEN',
                     'ggrep --directories recurse TOKEN', 'ggrep -D skip -r TOKEN', 'grep -drecurse TOKEN',
                     'rg --hidden --no-ignore --max-depth 2 TOKEN', "rg --hidden --no-ignore -G '*.txt' TOKEN", 'rg --glob-not x TOKEN', 'rg --max-bytes 10 TOKEN',
                     'ugrep -r --hidden --exclude-from /tmp/excludes needle', 'ugrep -r --include-from /tmp/inc needle', 'ugrep -r -D skip needle'):
            self.assertIn('secret', self.kinds(line), line)

    def test_other_tools_keep_their_folders(self):
        for line in ('tree -d ~/.ssh', 'tree -d -L 2 ~/.ssh'):
            self.assertIn('secret', self.kinds(line), line)

    def test_safe_folder_alone_is_fine(self):
        for line in ('rg KEY', 'rg -e KEY', 'rg --pre /bin/cat -e TOKEN', 'grep -rn KEY .', 'rg --files'):
            self.assertNotIn('secret', self.kinds(line), line)


class TroubleInTheInterface(unittest.TestCase):
    def setUp(self): self.code = js()

    def test_sidebar_chat_and_details_show_it(self):
        self.assertIn("${troubleBadge(b)}</span><span class=\"side-preview\">", self.code)  # sidebar card
        self.assertIn('</header>${troubleBanner(b)}', self.code)  # the chat
        self.assertIn('<p>${esc(botModelLine(b))}${troubleBadge(b)}</p>', self.code)  # 詳情

    def test_words_follow_the_backup(self):
        self.assertIn("傳訊息時會先試 ${backup}（只用訂閱帳號），回覆裡會註明。", self.code)  # #132: what really runs next (nextBackup)
        self.assertIn('現在傳訊息會失敗。可以在「備用模型」選一家', self.code)
        self.assertIn("said = warn ? formTroubleText(form, choice) || quotaWarnText(choice) : ''", self.code)
        self.assertIn("['providerChoice', 'fallbackChoice'].includes(e.target.name)", self.code)  # a backup picked in the form changes the line

    def test_backup_menus_are_marked(self):
        self.assertIn("base + (troubleMark(modelTrouble(value, '')) || levelMark(accountLevel(value, '')))", self.code)  # Bot form
        self.assertIn("name: p.name + troubleMark(modelTrouble(p.id, ''))", self.code)  # 設定
        self.assertIn('剩不到 20% 的帳號排最後，API 計費或還沒確認是訂閱的不會換上', self.code); self.assertIn('都選「不使用」就不換別家', self.code)  # #33, 2026-11-27

    def test_antigravity_is_never_called_used_up_as_a_whole(self):
        self.assertEqual(self.code.count("provider !== 'antigravity'"), 2)

    def test_signed_out_only_from_a_check(self):
        self.assertIn("if (r.signedIn === false) return {kind: 'login', tag: '尚未登入'}", self.code)

    def test_schedule_target_warns(self):
        self.assertIn('data-target-warn hidden', self.code)
        self.assertIn("if (e.target.name === 'target' && e.target.closest('#schedule-form')) scheduleTargetWarn(", self.code)
        self.assertIn("scheduleTargetWarn($('#schedule-form'))", self.code)
        self.assertIn("${x.botId && x.on ? scheduleTroubleLine(x) : ''}", self.code)


class PagesKeepTheirAddress(unittest.TestCase):
    def test_schedules_page_has_an_address(self):
        code = js()
        self.assertRegex(code, r"PAGE_HASHES = \[[^\]]*'schedules'")
        self.assertIn('const page = location.hash.slice(1); if (PAGE_HASHES.includes(page))', code)

    def test_address_comes_before_the_kept_page(self):
        """A page in the address (#168③) is opened first; the Skills or connectors page kept from before (#97) only when the
        reload is on the chat, so the two never fight over which page shows."""
        code = js()
        after_reload = code[code.index('restoreLastOpen();'):]
        self.assertLess(after_reload.index('PAGE_HASHES.includes(page)) { state.page = page;'), after_reload.index('restorePage();'))
        self.assertIn("if (KEPT_PAGES.includes(page) && state.page === 'chat') loadPage(page)", code)
        for page in ('skills', 'mcp', 'plugins'): self.assertRegex(code, r"PAGE_HASHES = \[[^\]]*'%s'" % page)  # the kept pages have an address too


class UsageCardsSayNotSignedIn(unittest.TestCase):
    def test_card_badge_uses_the_last_sign_in_check(self):
        """#116's one card per account shows the sign-in check #111 added: 無法使用 with 尚未登入 on the badge."""
        code = js()
        self.assertIn("(state.data?.rings || []).find(x => x.id === p.id)?.signedIn === false) return {cls: 'off', text: '無法使用', note: '尚未登入'}", code)


class NarrowUsageTable(unittest.TestCase):
    def test_scrolls_sideways(self):
        css = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
        self.assertIn('.bot-usage-scroll { overflow-x:auto;', css)  # #69①: main's own wrapper (#116) scrolls it sideways; no second scroll inside
        self.assertNotIn('.bot-usage { overflow-x: auto; }', css)


if __name__ == '__main__': unittest.main()
