# -*- coding: utf-8 -*-
"""#316 (with #301): on the usage page every account of every CLI has a card of its own, and every card has the same blocks in
the same order: the head (CLI, account, sign-in method, 預設), one status badge (可用／快用完／已用完／無法使用), the limit bars
(the same bars in the same order for every account of a CLI, 不提供 where an account has no figure), the reset times, a 下一步
line only when one is needed, 綁定 Bot, and at the foot 自動選用 and 詳細. API keys and CLIs without figures use the same card.
The cards of one CLI come together under a title row with ＋ 帳號 and a drag handle (#317: no sentence or help text on top;
the CLIs are put in order by dragging or with the arrow keys on the handle).
The saved order (usageCardOrder / usageCardSort) keeps working and stays a list of the same keys (#242)."""
import importlib.util, json, re, shutil, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'
SERVER = ROOT / 'backend/server.py'


def part(text, start, end):
    i = text.index(start); return text[i:text.index(end, i)]


def run(script):
    """Runs the whole cards file in node with a tiny stand-in for the page."""
    models = (JS / '20-models.js').read_text(encoding='utf-8')
    code = '\n'.join([
        "const esc = s => String(s ?? '').replace(/[&<>\"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;'})[c]); let state = {};",
        "const document = {addEventListener() {}, querySelectorAll: () => []}, window = {}, requestAnimationFrame = f => f(); let saved = null, shown = null;",
        "const render = () => {}, toast = () => {}, modal = (title, body) => { shown = {title, body}; }, refreshQuota = () => {}, post = async (path, body) => { saved = body; return Object.assign({}, state.data.settings, body); };",
        part(models, '  function fmtReset', '  function botUsageSection'), part(models, '  function dropdown', '  const toggle') + part(models, '  const toggle', '\n'),
        (JS / '32b-cards.js').read_text(encoding='utf-8'),
        script])
    done = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=20)
    if done.returncode: raise AssertionError(done.stderr)
    return json.loads(done.stdout)


LATER = 'Date.now() / 1000 + 7200'
ISSUE = '這個 Google 登入不能用：Google 已不開放個人免費方案使用 Gemini CLI。要用 Gemini，請在用量頁 Gemini 卡片按「＋ 帳號」加入 Gemini API 金鑰（依用量計費），再到 Bot 的進階設定選用它。'
SETUP = f"""
const fresh = new Date().toISOString(), w = (label, used, at = {LATER}) => ({{label, usedPercent: used, resetsAt: at}});
state = {{data: {{settings: {{provider: 'codex'}}, bots: [
  {{id: 'b1', name: '寫手', provider: 'codex', account: ''}}, {{id: 'b2', name: '跟著預設', provider: ''}}, {{id: 'b3', name: '工程師', provider: 'codex', account: 'w'}},
  {{id: 'b4', name: '還在配', provider: 'auto'}}, {{id: 'b5', name: '研究員', provider: 'antigravity', account: 'agw'}}]}},
  accounts: {{providers: [
  {{id: 'codex', name: 'Codex（OpenAI）', installed: true, canAddLogin: true, canAddKey: true, status: 'logged_in', email: 'a@x', method: 'ChatGPT 帳號',
    profiles: [{{id: 'w', name: 'Waifdance', type: 'login', status: 'logged_in', email: 'w@x', method: 'ChatGPT 帳號'}}, {{id: 'k', name: '金鑰', type: 'key', status: 'logged_in'}}, {{id: 'n', name: '新帳號', type: 'login', status: 'not_logged_in'}}]}},
  {{id: 'antigravity', name: 'Antigravity', installed: true, canAddLogin: true, status: 'logged_in', method: 'Google 帳號',
    profiles: [{{id: 'agw', name: 'Waifdance', type: 'login', status: 'logged_in', method: 'Google 帳號'}}]}},
  {{id: 'gemini', name: 'Gemini', installed: true, canAddKey: true, status: 'logged_in', method: 'Google 帳號', issue: {json.dumps(ISSUE, ensure_ascii=False)},
    profiles: [{{id: 'g1', name: 'sean@x', type: 'key', status: 'logged_in'}}]}},
  {{id: 'grok', name: 'Grok', installed: true, status: 'logged_in', profiles: []}},
  {{id: 'claude', name: 'Claude（Anthropic）', installed: true, status: 'logged_in', email: 'c@x', method: 'Claude 訂閱帳號', profiles: []}},
  {{id: 'cursor', name: 'Cursor', installed: true, status: 'logged_in', email: 's@x', profiles: []}}]}},
  quota: {{providers: [
  {{id: 'codex', autoOn: true, quota: {{windows: [w('5 小時', 5), w('每週', 52)], updatedAt: fresh}}, profiles: [
    {{id: 'w', autoOn: true, quota: {{windows: [w('5 小時', 100), w('每週', 66)], updatedAt: fresh}}}}, {{id: 'k', apiBilling: true, autoOn: false, autoBilled: true, quota: {{windows: [w('每週', 18)], updatedAt: fresh}}}}, {{id: 'n'}}]}},
  {{id: 'antigravity', autoOn: true, quota: {{windows: [w('Gemini 模型 · 每週', 100), w('Claude 與 GPT 模型 · 每週', 0)], updatedAt: fresh}}, profiles: [
    {{id: 'agw', autoOn: true, quota: {{windows: [w('Claude 與 GPT 模型 · 每週', 0), w('Gemini 模型 · 每週', 90.4), w('Gemini 模型 · 5 小時', 10)], updatedAt: fresh}}}}]}},
  {{id: 'gemini', autoOn: false, quota: {{windows: [], updatedAt: fresh}}, profiles: [{{id: 'g1', apiBilling: true, autoOn: false, autoBilled: true}}]}},
  {{id: 'grok', autoOn: true, quota: {{windows: [w('每週', 100, null)], updatedAt: fresh}}, profiles: []}},
  {{id: 'claude', autoOn: true, quota: {{windows: [w('每週', 85)], updatedAt: fresh}}, profiles: []}},
  {{id: 'cursor', autoOn: false, noQuotaApi: true, profiles: []}}]}}}};
const P = state.accounts.providers, keysOf = fams => fams.map(f => [f.key, f.rows.map(r => r.key)]);
const cardOf = (html, key) => {{ const i = html.indexOf('data-row-key="' + key + '"'); if (i < 0) throw new Error('no card ' + key); return html.slice(html.lastIndexOf('<article', i), html.indexOf('</article>', i)); }};
"""
KEYS = ['codex', 'codex::w', 'codex::k', 'codex::n', 'antigravity', 'antigravity::agw', 'gemini', 'gemini::g1', 'grok', 'claude', 'cursor']
BLOCKS = ['class="uc-head', 'class="uc-quota', 'class="uc-reset', 'class="uc-bots', 'class="account-foot']


@unittest.skipUnless(shutil.which('node'), 'node is needed to run the page code')
class Cards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = run(SETUP + "console.log(JSON.stringify(accountCards()))")
        cls.cards = run(SETUP + f"const html = accountCards(); console.log(JSON.stringify(Object.fromEntries({json.dumps(KEYS)}.map(k => [k, cardOf(html, k)]))))")

    def test_one_card_per_account_grouped_by_cli(self):
        self.assertEqual(self.html.count('<article'), len(KEYS))
        self.assertEqual(re.findall(r'data-row-key="([^"]+)"', self.html), KEYS)
        self.assertNotIn('family-card', self.html); self.assertNotIn('acct-row', self.html)  # no more cards with several accounts in them (#242)
        self.assertEqual(re.findall(r'class="usage-family" data-card-key="([^"]+)"', self.html), ['codex', 'antigravity', 'gemini', 'grok', 'claude', 'cursor'])

    def test_every_card_has_the_same_blocks_in_the_same_order(self):
        for key, card in self.cards.items():
            at = [card.find(b) for b in BLOCKS]
            self.assertTrue(all(i >= 0 for i in at), (key, at))
            self.assertEqual(at, sorted(at), key)
            self.assertEqual(card.count('class="status-badge'), 1, key)
            # the badge sits beside the account name in the head, not on a row of its own (#316 follow-up)
            name_row = re.search(r'<div class="uc-name-row">(.*?)</div>', card).group(1)
            self.assertIn('class="uc-name"', name_row); self.assertIn('class="status-badge', name_row)
            self.assertLess(card.index('class="status-badge'), card.index('</header>')); self.assertNotIn('uc-status', card)
            self.assertEqual(card.count('role="switch"'), 1, key)  # 自動選用 on every card, also where it cannot be turned on
            self.assertEqual(card.count('data-action="account-detail"'), 1, key)
            self.assertNotIn('data-action="profile-add"', card)  # ＋ 帳號 is on the CLI's title row
            nxt = card.find('class="uc-next')
            if nxt >= 0: self.assertTrue(card.find('class="uc-reset') < nxt < card.find('class="uc-bots'), key)

    def test_status_badges(self):
        badge = {k: re.search(r'class="status-badge [a-z]+"[^>]*>([^<]+)<', c).group(1) for k, c in self.cards.items()}
        self.assertEqual(badge, {'codex': '可用', 'codex::w': '已用完', 'codex::k': '可用', 'codex::n': '無法使用', 'antigravity': '已用完', 'antigravity::agw': '快用完',
                                 'gemini': '無法使用', 'gemini::g1': '可用', 'grok': '已用完', 'claude': '快用完', 'cursor': '可用'})
        for k in ('codex::w', 'grok', 'codex::n', 'gemini'): self.assertIn('class="uc-next', self.cards[k], k)  # used up: what to do next
        for k in ('codex', 'claude', 'cursor', 'codex::k'): self.assertNotIn('class="uc-next', self.cards[k], k)  # only when needed

    def test_head_says_cli_account_method_and_default(self):
        c = self.cards
        self.assertIn('Codex', c['codex::w']); self.assertIn('Waifdance', c['codex::w']); self.assertIn('ChatGPT 帳號', c['codex::w'])
        self.assertIn('預設', c['codex']); self.assertNotIn('uc-default', c['codex::w'])
        self.assertIn('API 金鑰', c['codex::k']); self.assertIn('Google 帳號', c['antigravity::agw'])

    def test_same_bars_in_the_same_order_for_one_cli(self):
        bars = lambda card: re.findall(r'class="quota-row[^"]*"><div class="quota-label"><span>([^<]+)</span>', card)
        self.assertEqual(bars(self.cards['codex']), ['5 小時', '每週']); self.assertEqual(bars(self.cards['codex::w']), ['5 小時', '每週'])
        agy = bars(self.cards['antigravity'])
        self.assertEqual(agy, bars(self.cards['antigravity::agw']))
        self.assertEqual(agy, ['Gemini 模型 · 5 小時', 'Gemini 模型 · 每週', 'Claude 與 GPT 模型 · 每週'])
        first = part(self.cards['antigravity'], 'Gemini 模型 · 5 小時', 'Gemini 模型 · 每週')
        self.assertIn('不提供', first)  # the default account has no five-hour figure for Gemini: said, not left out

    def test_api_keys_and_cursor_use_the_same_card(self):
        key = self.cards['codex::k']
        self.assertIn('依用量計費', key); self.assertNotIn('quota-row', key); self.assertIn('API 計費，不會自動選用', key)
        cur = self.cards['cursor']
        self.assertIn('這個 CLI 不提供額度資料', cur); self.assertNotIn('quota-row', cur)
        self.assertIn('依用量計費', self.cards['gemini::g1'])

    def test_gemini_says_one_line_and_explains_in_detail(self):
        g = self.cards['gemini']
        self.assertNotIn('Google 已不開放', g)  # the long explanation is not on the card
        self.assertIn('這個 Google 登入不能用', g)
        self.assertNotIn('Google 已不開放', self.cards['gemini::g1'])
        shown = run(SETUP + "accountDetail('gemini', ''); console.log(JSON.stringify(shown))")
        self.assertIn('Google 已不開放個人免費方案使用 Gemini CLI', shown['body'])

    def test_add_account_is_on_the_cli_title_row(self):
        head = part(self.html, 'data-card-key="codex"', '<article')
        self.assertIn('data-action="profile-add" data-id="codex"', head); self.assertIn('4 個帳號', head)
        self.assertEqual(self.html.count('data-action="profile-add"'), 3)  # codex, antigravity, gemini can add accounts

    def test_bound_bots(self):
        c = self.cards
        self.assertIn('綁定 Bot：2 個', c['codex']); self.assertIn('寫手', c['codex']); self.assertIn('跟著預設', c['codex'])  # a Bot without its own model follows the default
        self.assertIn('data-action="select-bot" data-id="b1"', c['codex'])
        self.assertIn('綁定 Bot：1 個', c['codex::w']); self.assertIn('綁定 Bot：1 個', c['antigravity::agw'])
        self.assertIn('綁定 Bot：0 個', c['claude']); self.assertNotIn('還在配', self.html)  # 自動選擇 is not bound to an account

    def test_no_summary_or_help_text_on_top(self):  # #317: the user took out the overview sentence and the paragraph under it
        for gone in ('usage-summary', 'usage-help', '現在能用', '一個帳號一張卡', '自動選用」打開時'): self.assertNotIn(gone, self.html, gone)
        cards = (JS / '32b-cards.js').read_text(encoding='utf-8')
        self.assertNotIn('usageSummary', cards); self.assertNotIn('一個帳號一張卡', cards)
        self.assertIn('綁定 Bot：', self.cards['codex'])

    def test_each_cli_has_a_drag_handle_that_takes_the_keyboard(self):  # #317
        heads = re.findall(r'<div class="usage-family-head"[^>]*>(.*?)<h3', self.html)
        self.assertEqual(len(heads), 6)
        for h in heads:
            self.assertIn('class="drag-handle"', h); self.assertIn('tabindex="0"', h); self.assertIn('role="button"', h); self.assertIn('上下鍵', h)
        fams = "const fams = [{key: 'claude', rows: ['claude', 'claude::sub']}, {key: 'codex', rows: ['codex', 'codex::w']}, {key: 'grok', rows: ['grok']}];"
        got = run(SETUP + fams + """console.log(JSON.stringify([usageOrderStep(fams, 'codex', -1), usageOrderStep(fams, 'codex', 1),
          usageOrderStep(fams, 'claude', -1), usageOrderStep(fams, 'grok', 1), usageOrderStep(fams, 'gone', 1)]))""")
        self.assertEqual(got[0], ['codex', 'codex::w', 'claude', 'claude::sub', 'grok'])
        self.assertEqual(got[1], ['claude', 'claude::sub', 'grok', 'codex', 'codex::w'])
        self.assertEqual(got[2:], [None, None, None])  # already first / last / not shown: nothing to save

    def test_a_new_cli_comes_last(self):  # #317: a CLI added after the order was saved goes after the saved ones
        got = run(SETUP + "state.data.settings = {usageCardOrder: ['claude', 'codex', 'codex::w', 'codex::k', 'codex::n', 'grok', 'gemini', 'gemini::g1', 'antigravity', 'antigravity::agw']}; console.log(JSON.stringify(keysOf(usageFamilies(P)).map(f => f[0])))")
        self.assertEqual(got, ['claude', 'codex', 'grok', 'gemini', 'antigravity', 'cursor'])

    def test_saved_order_and_auto_sort_still_apply(self):
        got = run(SETUP + "state.data.settings = {usageCardOrder: ['grok', 'codex::w', 'claude', 'codex', 'gone::x'], usageCardSort: 'custom'}; console.log(JSON.stringify(keysOf(usageFamilies(P)).slice(0, 3)))")
        self.assertEqual(got, [['grok', ['grok']], ['codex', ['codex::w', 'codex', 'codex::k', 'codex::n']], ['claude', ['claude']]])
        got = run(SETUP + "state.data.settings = {usageCardSort: 'auto'}; console.log(JSON.stringify(keysOf(usageFamilies(P)).map(f => f[0])))")
        self.assertEqual(got[:3], ['codex', 'antigravity', 'claude'])  # five hours: Codex 95% left, Antigravity's Waifdance 90%; Claude's week 15%

    def test_dragging_saves_the_same_list_of_keys(self):
        fams = "const fams = [{key: 'claude', rows: ['claude', 'claude::sub']}, {key: 'codex', rows: ['codex', 'codex::w', 'codex::k']}, {key: 'grok', rows: ['grok']}];"
        got = run(SETUP + fams + """console.log(JSON.stringify([
          usageOrderAfterMove(fams, 'card', 'grok', 'claude', false), usageOrderAfterMove(fams, 'row', 'codex::k', 'codex', false), usageOrderAfterMove(fams, 'row', 'codex::k', 'claude', true)]))""")
        self.assertEqual(got[0], ['grok', 'claude', 'claude::sub', 'codex', 'codex::w', 'codex::k'])
        self.assertEqual(got[1], ['claude', 'claude::sub', 'codex::k', 'codex', 'codex::w', 'grok'])
        self.assertIsNone(got[2])  # an account does not move to another CLI
        self.assertIn('draggable="true"', self.cards['codex::w'])  # a CLI with several accounts: its cards can be dragged
        self.assertNotIn('draggable="true"', self.cards['grok'])

    def test_layout_is_an_even_grid(self):
        css = (ROOT / 'frontend/style.css').read_text(encoding='utf-8')
        grid = re.search(r'\.usage-grid \{([^}]*)\}', css).group(1)
        self.assertIn('grid-template-columns:repeat(auto-fill, minmax(', grid); self.assertNotIn('align-items:start', grid)
        self.assertRegex(css, r'@media \(max-width: *\d+px\) \{ *\.usage-grid \{ *grid-template-columns: *1fr')
        self.assertRegex(css, r'\.usage-family-head \{[^}]*grid-column: *1 */ *-1')
        fam = re.search(r'\.usage-family \{([^}]*)\}', css).group(1)  # #317: a CLI is one box, so the drop mark goes above or below the whole group
        self.assertNotIn('display:contents', fam.replace(' ', '')); self.assertIn('subgrid', fam)
        self.assertRegex(css, r'\.usage-family\.drop-before'); self.assertRegex(css, r'\.usage-family\.drop-after')
        cards = (JS / '32b-cards.js').read_text(encoding='utf-8')
        self.assertNotIn('<select', cards); self.assertIn("dropdown('usageCardSort'", cards)


class BackendBilling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('zook_server_for_cards', SERVER)
        cls.m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(cls.m)

    def test_api_key_sign_ins_count_as_billed(self):
        for method in ('API 金鑰', 'Anthropic Console', 'api_key'): self.assertTrue(self.m.api_billed_method(method), method)
        for method in ('Claude 訂閱帳號', 'ChatGPT 帳號', '', None): self.assertFalse(self.m.api_billed_method(method), method)
        src = (ROOT / 'backend/zook/accounts.py').read_text(encoding='utf-8')
        self.assertRegex(src, r"'api_key': 'API 金鑰'")
        handler = (ROOT / 'backend/zook/handler.py').read_text(encoding='utf-8')
        self.assertNotIn("in ('Anthropic Console', 'API 金鑰')", handler)

    def test_phone_order_puts_billed_after_figures_even_with_old_limits(self):
        import time
        billed = dict(id='claude', status='logged_in', apiBilling=True, quota=dict(windows=[dict(label='每週', usedPercent=100, resetsAt=time.time() + 3600)], updatedAt='2026-11-25T00:00:00+00:00'))
        self.assertEqual(self.m.usage_card_focus(billed), (1, 0.0))


if __name__ == '__main__': unittest.main()
