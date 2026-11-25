# -*- coding: utf-8 -*-
"""The usage page says things plainly (#90, #119): a limit with no reset time says 未提供重置時間, a five-hour limit stopped by a
used-up weekly one is greyed and says so instead of a green 100%, a used-up card has a badge, the reset time and what to do next,
the Gemini cards do not contradict each other, and token counts use one unit on the whole page."""
import json, re, shutil, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'frontend/js'



def part(text, start, end):
    i = text.index(start); return text[i:text.index(end, i)]


def run(script):
    """Runs the page's own functions in node with a tiny stand-in for the page."""
    models, cards, usage = (JS / '20-models.js').read_text(encoding='utf-8'), (JS / '32b-cards.js').read_text(encoding='utf-8'), (JS / '32-usage.js').read_text(encoding='utf-8')
    code = '\n'.join([
        "const esc = s => String(s ?? '').replace(/[&<>\"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;'})[c]); let state = {};",
        part(models, '  function fmtReset', '  const loadingBlock'), part(models, '  const quotaFor', '  function botUsageSection'),
        part(usage, '  const fmtTok', '  const OVERVIEW_METRICS'),
        part(cards, '  // Percent left in one limit', '  function loginButtons'), part(cards, '  function outNext', '  function accountRow'),
        script])
    done = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=20)
    if done.returncode: raise AssertionError(done.stderr)
    return json.loads(done.stdout)


@unittest.skipUnless(shutil.which('node'), 'node is needed to run the page code')
class UsageWords(unittest.TestCase):
    def test_no_reset_time_is_said(self):
        got = run("console.log(JSON.stringify(quotaRows([{label: '每週', usedPercent: 40, resetsAt: null}])))")
        self.assertIn('未提供重置時間', got)

    def test_weekly_used_up_greys_the_five_hours(self):
        later = "Date.now() / 1000 + 7200"
        got = run(f"console.log(JSON.stringify(quotaRows([{{label: '5 小時', usedPercent: 0, resetsAt: {later}}}, {{label: '每週', usedPercent: 100, resetsAt: {later}}}])))")
        five = got[:got.index('每週</span>')]
        self.assertIn('quota-row blocked', five); self.assertIn('被每週額度擋住', five); self.assertNotIn('剩餘 100%', five)
        self.assertIn('quota-bar off', five)
        short = run(f"console.log(JSON.stringify(quotaRows([{{label: '5 小時', usedPercent: 100, resetsAt: {later}}}, {{label: '每週', usedPercent: 40, resetsAt: {later}}}])))")
        self.assertNotIn('blocked', short); self.assertIn('剩餘 60%', short)  # a used-up five hours leaves the weekly figure alone, like the rings
        # Antigravity keeps limits per model: one model used up does not stop another
        agy = run(f"console.log(JSON.stringify(quotaRows([{{label: 'Gemini · 每週', usedPercent: 10, resetsAt: {later}}}, {{label: 'Claude · 每週', usedPercent: 100, resetsAt: {later}}}])))")
        self.assertNotIn('blocked', agy); self.assertIn('剩餘 90%', agy)

    def test_used_up_card_says_what_to_do(self):
        setup = """state = {accounts: {providers: [
          {id: 'grok', name: 'Grok', installed: true, status: 'logged_in', profiles: []},
          {id: 'codex', name: 'Codex（OpenAI）', installed: true, status: 'logged_in', profiles: [{id: 'w', name: 'Waifdance', type: 'login', status: 'logged_in'}]}]},
          quota: {providers: [
          {id: 'grok', quota: {windows: [{label: '每週', usedPercent: 100, resetsAt: null}], updatedAt: new Date().toISOString()}, profiles: []},
          {id: 'codex', quota: {windows: [{label: '每週', usedPercent: 30, resetsAt: Date.now() / 1000 + 9999}], updatedAt: new Date().toISOString()}, profiles: [{id: 'w', quota: {windows: [{label: '每週', usedPercent: 100, resetsAt: Date.now() / 1000 + 3600}], updatedAt: new Date().toISOString()}}]}]}};"""
        got = run(setup + """
          const P = state.accounts.providers, grok = accountLevel('grok', ''), w = accountLevel('codex', 'w');
          console.log(JSON.stringify({grok, w, grokNext: outNext(P[0], null, grok), wNext: outNext(P[1], P[1].profiles[0], w)}))""")
        self.assertEqual((got['grok']['level'], got['grok']['reset']), ('out', ''))  # the card then shows 未提供重置時間
        self.assertIn('沒有說何時重置', got['grokNext']); self.assertIn('改用「Codex」', got['grokNext'])
        self.assertIn('等到', got['wNext']); self.assertIn('重置後再用', got['wNext']); self.assertIn('改用「Codex」', got['wNext'])
        cards = (JS / '32b-cards.js').read_text(encoding='utf-8')
        self.assertIn("<span class=\"out-badge\">已用完</span>", cards); self.assertIn("lv.reset || '未提供重置時間'", cards)

    def test_one_token_unit(self):
        got = run("console.log(JSON.stringify([fmtTok(1234), fmtTok(32000), fmtTok(31760000), fmtTok(48500000), fmtTok(123000000)]))")
        self.assertEqual(got, ['1,234', '3.2 萬', '3,176 萬', '4,850 萬', '1.2 億'])
        upkeep = (JS / '39-upkeep.js').read_text(encoding='utf-8')
        self.assertIn('const fmtTokens = n => fmtTok(n)', upkeep)
        models = (JS / '20-models.js').read_text(encoding='utf-8')
        self.assertNotIn('訂閱內', models); self.assertIn('${fmtTok(r.input)}', models)


class GeminiWords(unittest.TestCase):
    def test_cards_do_not_contradict(self):
        src = (ROOT / 'backend/zook/accounts.py').read_text(encoding='utf-8')
        said = re.search(r"if 'ineligibletiererror'.*?\n\s+return '([^']+)'", src, re.S).group(1)
        self.assertIn('這個 Google 登入不能用', said); self.assertIn('用量頁 Gemini 卡片按「＋ 帳號」', said)
        cards = (JS / '32b-cards.js').read_text(encoding='utf-8')
        self.assertIn("const issue = a ? '' : p.issue", cards)          # an API-key card does not repeat the Google sign-in problem
        self.assertIn("if (!a && p.issue) return done;", cards)          # nor does the main card add 不提供額度資料 under it
        self.assertIn('<b>依用量計費</b>', cards)


if __name__ == '__main__': unittest.main()
