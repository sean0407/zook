# -*- coding: utf-8 -*-
"""請其他成員查核 in the window: a failed check is shown under the reply with the reason and 再試一次, a refused check says why
right there (and asks there when only the same vendor can check), one button per reply, Office lock files never get a card, and
a check still running is read again until it ends even when the discussion's own polling stopped."""
import importlib.util, re, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_check_view', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def frontend(): return ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))


class CheckView(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load(); cls.js = frontend()

    def store(self, bots, jobs=()):
        return type('S', (), dict(data=dict(bots=bots, jobs=list(jobs)), find=lambda self, kind, x: next((b for b in self.data[kind] if b['id'] == x), None)))()

    def test_skipped_check_lands_under_the_reply(self):
        group = dict(messages=[]); bot = dict(id='b', name='Beta')
        self.m.group_skip_turn(group, bot, 'Beta 正在其他對話中工作。', dict(targetId='t1'))
        check = group['messages'][-1]
        self.assertEqual((check['checkOf'], check['status'], check['role'], check['error']), ('t1', 'failed', 'assistant', 'Beta 正在其他對話中工作。'))
        self.m.group_skip_turn(group, bot, ' 正在其他對話中工作，這次略過。', None)
        self.assertEqual((group['messages'][-1]['role'], group['messages'][-1]['content']), ('system', 'Beta 正在其他對話中工作，這次略過。'))

    def test_reason_nobody_can_check(self):
        bots = [dict(id='a', name='Alpha'), dict(id='b', name='Beta')]
        message = dict(id='t', botId='a')
        self.assertIn('沒有其他成員', self.m.verifier_missing(self.store(bots[:1]), dict(botIds=['a']), message))
        busy = self.store(bots, [dict(botId='b', status='running')])
        self.assertIn('Beta 正在其他對話中工作', self.m.verifier_missing(busy, dict(botIds=['a', 'b']), message))
        self.assertIn('無法查核', self.m.verifier_missing(self.store(bots), dict(botIds=['a', 'b']), message))

    def test_failed_check_shows_reason_and_try_again(self):
        self.assertIn('查核失敗', self.js); self.assertIn('c.error ||', self.js)
        self.assertRegex(self.js, r'othersIn\(g, m\)[^`]*`<button type="button" class="link" data-action="group-verify" [^>]*>再試一次')  # retry asks again like the first time, and only while someone can check
        self.assertIn("c.status === 'cancelled' ? '查核已停止。'", self.js)
        self.assertIn("case 'group-verify-anyway'", self.js); self.assertIn("case 'group-verify-dismiss'", self.js)

    def test_refusal_is_said_in_place_not_in_a_dialog(self):
        verify = self.js[self.js.index('async function verifyGroupMessage'):]
        verify = verify[:verify.index('\n  }\n')]
        self.assertNotIn('confirm(', verify); self.assertIn('state.verifyNotes[id]', verify); self.assertIn('needsConfirm', verify)

    def test_conclusion_after_a_passed_check_says_so(self):
        self.assertIn("${m.afterCheck ? ' <span class=\"muted\">· 查核通過後自動整理</span>' : ''}", self.js)  # #222

    def test_one_button_per_reply_and_none_without_another_member(self):
        button = self.js[self.js.index('const groupVerifyButton'):]
        button = button[:button.index('\n  };\n')]
        self.assertIn('!othersIn(g, m)', button); self.assertIn('x !== m.botId', self.js); self.assertIn("last.status === 'running' || checkFailed(last)", button)

    def test_one_card_per_file_name_in_a_group_reply(self):
        self.assertIn(".filter((f, i, all) => all.findIndex(x => x.name === f.name) === i)", self.js)

    def test_older_full_refresh_is_asked_again(self):
        self.assertIn("if (loads !== state.loads) data = await api('state');", self.js)

    def test_lock_files_get_no_card(self):
        self.assertIn(r"!/^(~\$|\.~lock\.)/.test(f.name)", self.js); self.assertIn(r"/[\w.\-$]/.test(before)", self.js)

    def test_running_check_is_read_again_until_it_ends(self):
        self.assertRegex(self.js, r"const groupNeedsPoll = g => g\.status === 'running' \|\| \(groupMsgs\(g\)\.some\(x => x\.checkOf && x\.status === 'running'\)"); self.assertRegex(self.js, r"setInterval\(\(\) => \{[^}]*groupNeedsPoll\(g\)\) pollGroup\(g\.id\)")  # a left-over check stops asking (#215②)
        self.assertIn('if (changed) state.loads = (state.loads || 0) + 1;', self.js)  # an older full refresh cannot undo what a poll brought


if __name__ == '__main__': unittest.main()
