# -*- coding: utf-8 -*-
"""#242 (with #199): the usage page puts the accounts of one CLI in one family card, one row per account (Codex's default account
and Waifdance under one Codex card); an API-key account shows 依用量計費 instead of a weekly limit, also when the CLI's own sign-in
is an API key; the saved order (usageCardOrder / usageCardSort) keeps working and stays a list of the same keys."""
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
        "const document = {addEventListener() {}, querySelectorAll: () => []}, window = {}, requestAnimationFrame = f => f(); let saved = null;",
        "const render = () => {}, toast = () => {}, modal = () => {}, refreshQuota = () => {}, post = async (path, body) => { saved = body; return Object.assign({}, state.data.settings, body); };",
        part(models, '  function fmtReset', '  function botUsageSection'), part(models, '  function dropdown', '  const toggle') + part(models, '  const toggle', '\n'),
        (JS / '32b-cards.js').read_text(encoding='utf-8'),
        script])
    done = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=20)
    if done.returncode: raise AssertionError(done.stderr)
    return json.loads(done.stdout)


LATER = 'Date.now() / 1000 + 7200'
SETUP = f"""
const fresh = new Date().toISOString(), w = (label, used) => ({{label, usedPercent: used, resetsAt: {LATER}}});
state = {{data: {{settings: {{}}}}, accounts: {{providers: [
  {{id: 'claude', name: 'Claude（Anthropic）', installed: true, status: 'logged_in', method: 'API 金鑰', profiles: [{{id: 'sub', name: '訂閱', type: 'login', status: 'logged_in', email: 'me@x'}}]}},
  {{id: 'codex', name: 'Codex（OpenAI）', installed: true, canAddLogin: true, status: 'logged_in', email: 'a@x', profiles: [{{id: 'w', name: 'Waifdance', type: 'login', status: 'logged_in', email: 'w@x'}}, {{id: 'k', name: '金鑰', type: 'key', status: 'logged_in', method: 'API 金鑰'}}]}},
  {{id: 'grok', name: 'Grok', installed: true, status: 'logged_in', profiles: []}}]}},
  quota: {{providers: [
  {{id: 'claude', apiBilling: true, quota: {{windows: [w('5 小時', 10), w('每週', 18)], updatedAt: fresh}}, profiles: [{{id: 'sub', quota: {{windows: [w('每週', 50)], updatedAt: fresh}}}}]}},
  {{id: 'codex', quota: {{windows: [w('5 小時', 90), w('每週', 40)], updatedAt: fresh}}, profiles: [{{id: 'w', quota: {{windows: [w('5 小時', 20), w('每週', 30)], updatedAt: fresh}}}}, {{id: 'k', apiBilling: true, quota: {{windows: [w('每週', 18)], updatedAt: fresh}}}}]}},
  {{id: 'grok', quota: {{windows: [w('每週', 50)], updatedAt: fresh}}, profiles: []}}]}}}};
const P = state.accounts.providers, keysOf = fams => fams.map(f => [f.key, f.rows.map(r => r.key)]);
"""


@unittest.skipUnless(shutil.which('node'), 'node is needed to run the page code')
class Families(unittest.TestCase):
    def test_one_card_per_cli_with_a_row_per_account(self):
        got = run(SETUP + "console.log(JSON.stringify({fams: keysOf(usageFamilies(P)), html: accountCards()}))")
        self.assertEqual(got['fams'], [['claude', ['claude', 'claude::sub']], ['codex', ['codex', 'codex::w', 'codex::k']], ['grok', ['grok']]])
        html = got['html']
        self.assertEqual(html.count('class="left-card account-card family-card'), 3)
        codex = part(html, 'data-card-key="codex"', '</article>')
        self.assertEqual(codex.count('data-row-key='), 3); self.assertIn('Waifdance', codex); self.assertIn('預設帳號', codex)
        self.assertIn('3 個帳號', codex)
        self.assertEqual(codex.count('data-action="profile-add"'), 1)  # ＋ 帳號 once, on the family
        self.assertEqual(codex.count('data-action="account-detail"'), 3)  # 詳細 on every account
        self.assertIn('draggable="true" data-row-key="codex::w"', codex)  # rows of a family with several accounts can be dragged
        grok = part(html, 'data-card-key="grok"', '</article>')
        self.assertNotIn('draggable="true" data-row-key', grok)  # a lone row is not

    def test_api_key_rows_say_billed_by_use_not_weekly(self):
        got = run(SETUP + "console.log(JSON.stringify(accountCards()))")
        key = part(got, 'data-row-key="codex::k"', '</section>')
        self.assertIn('依用量計費', key); self.assertNotIn('剩餘', key); self.assertNotIn('quota-row', key)
        main = part(got, 'data-row-key="claude"', '</section>')  # the CLI's own sign-in is an API key (#199): no weekly figure either
        self.assertIn('依用量計費', main); self.assertNotIn('quota-row', main); self.assertNotIn('剩不到 20%', main)
        sub = part(got, 'data-row-key="claude::sub"', '</section>')
        self.assertIn('每週', sub); self.assertIn('剩餘 50%', sub)

    def test_old_saved_order_still_applies(self):
        # saved before families: single cards in any order. Families follow their first account; accounts keep their order inside.
        got = run(SETUP + "state.data.settings = {usageCardOrder: ['grok', 'codex::w', 'claude', 'codex', 'gone::x'], usageCardSort: 'custom'}; console.log(JSON.stringify(keysOf(usageFamilies(P))))")
        self.assertEqual(got, [['grok', ['grok']], ['codex', ['codex::w', 'codex', 'codex::k']], ['claude', ['claude', 'claude::sub']]])

    def test_auto_sort_puts_the_family_with_most_left_first(self):
        got = run(SETUP + "state.data.settings = {usageCardSort: 'auto', usageCardOrder: ['codex', 'grok', 'claude']}; console.log(JSON.stringify(keysOf(usageFamilies(P))))")
        # Claude's subscription row has 50% (weekly only); Grok 50%; Codex's best is 5 小時 80% left. API keys have no figure: after.
        self.assertEqual(got, [['codex', ['codex::w', 'codex', 'codex::k']], ['grok', ['grok']], ['claude', ['claude::sub', 'claude']]])

    def test_dragging_saves_the_same_list_of_keys(self):
        fams = "const fams = [{key: 'claude', rows: ['claude', 'claude::sub']}, {key: 'codex', rows: ['codex', 'codex::w', 'codex::k']}, {key: 'grok', rows: ['grok']}];"
        got = run(SETUP + fams + """console.log(JSON.stringify([
          usageOrderAfterMove(fams, 'card', 'grok', 'claude', false), usageOrderAfterMove(fams, 'card', 'claude', 'codex', true),
          usageOrderAfterMove(fams, 'row', 'codex::k', 'codex', false), usageOrderAfterMove(fams, 'row', 'codex::k', 'claude', true)]))""")
        self.assertEqual(got[0], ['grok', 'claude', 'claude::sub', 'codex', 'codex::w', 'codex::k'])
        self.assertEqual(got[1], ['codex', 'codex::w', 'codex::k', 'claude', 'claude::sub', 'grok'])
        self.assertEqual(got[2], ['claude', 'claude::sub', 'codex::k', 'codex', 'codex::w', 'grok'])
        self.assertIsNone(got[3])  # an account does not move into another family

    def test_the_page_keeps_the_sort_dropdown(self):
        cards = (JS / '32b-cards.js').read_text(encoding='utf-8')
        self.assertIn("dropdown('usageCardSort'", cards); self.assertIn("saveCardOrder({usageCardOrder: keys, usageCardSort: 'custom'})", cards)
        self.assertNotIn('<select', cards)


class BackendBilling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('zook_server_for_families', SERVER)
        cls.m = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(cls.m)

    def test_api_key_sign_ins_count_as_billed(self):
        for method in ('API 金鑰', 'Anthropic Console', 'api_key'): self.assertTrue(self.m.api_billed_method(method), method)
        for method in ('Claude 訂閱帳號', 'ChatGPT 帳號', '', None): self.assertFalse(self.m.api_billed_method(method), method)
        src = (ROOT / 'backend/zook/accounts.py').read_text(encoding='utf-8')
        self.assertRegex(src, r"'api_key': 'API 金鑰'")  # Claude's auth status says api_key; the page says API 金鑰
        handler = (ROOT / 'backend/zook/handler.py').read_text(encoding='utf-8')
        self.assertNotIn("in ('Anthropic Console', 'API 金鑰')", handler)

    def test_phone_order_puts_billed_after_figures_even_with_old_limits(self):
        import time
        later = time.time() + 3600
        billed = dict(id='claude', status='logged_in', apiBilling=True, quota=dict(windows=[dict(label='每週', usedPercent=100, resetsAt=later)], updatedAt='2026-11-25T00:00:00+00:00'))
        self.assertEqual(self.m.usage_card_focus(billed), (1, 0.0))  # a subscription's old limit does not make an API key look used up


if __name__ == '__main__': unittest.main()
