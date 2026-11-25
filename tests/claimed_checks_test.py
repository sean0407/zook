# -*- coding: utf-8 -*-
"""#68①: a member says it looked at every page as pictures, but its reply never turned a page into one. Zook says so under the
reply, and the host sees it in its next turn (as with #109's files that were not saved)."""
import importlib.util, sys, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_claimed_checks', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)


def ran(command, status='completed'): return dict(m.native_action('command', command), status=status)


class ClaimedChecks(unittest.TestCase):
    def setUp(self): m._active['data'] = {'settings': {}, 'rules': []}

    def test_a_command_that_turns_pages_into_pictures_is_marked(self):
        self.assertTrue(m.native_action('command', '/usr/bin/python3 "/Applications/Zook.app/backend/pagepics.py" a.pptx /tmp/x').get('rendered'))
        self.assertTrue(m.native_action('command', "/bin/zsh -lc 'qlmanage -t -s 1600 -o /tmp/p ~/a.docx'").get('rendered'))
        self.assertTrue(m.native_action('command', 'cd /tmp && /usr/bin/python3 "/Users/me/Zook App/backend/pagepics.py" "簡報 v2.pptx" /tmp/o').get('rendered'))
        self.assertTrue(m.native_action('command', 'pdftoppm -png a.pdf /tmp/p/page').get('rendered'))
        self.assertFalse(m.native_action('command', 'ls -la /tmp').get('rendered'))
        self.assertTrue(m.native_action('command', 'python3.11 pagepics.py a.pdf /tmp/o').get('rendered'))
        self.assertTrue(m.native_action('command', 'soffice --headless --convert-to png a.docx').get('rendered'))
        self.assertFalse(m.native_action('command', 'cat notes.txt | grep pagepics').get('rendered'))  # only mentions it
        self.assertFalse(m.native_action('command', 'which pdftoppm || brew install poppler').get('rendered'))
        self.assertFalse(m.native_action('command', 'command -v qlmanage').get('rendered'))

    def test_a_claim_without_any_picture_made(self):
        said = '已完成簡報，無延伸內容、已逐頁渲染檢查。'
        self.assertTrue(m.claimed_unrendered(said, [ran('ls')], 'antigravity'))
        self.assertTrue(m.claimed_unrendered('每一頁都轉成圖片看過，文字清楚。', [], 'codex'))
        self.assertFalse(m.claimed_unrendered(said, [ran('python3 pagepics.py a.pptx /tmp/o')], 'antigravity'))  # it did
        self.assertTrue(m.claimed_unrendered(said, [ran('python3 pagepics.py a.pptx /tmp/o', 'denied')], 'antigravity'))  # refused: not done
        self.assertFalse(m.claimed_unrendered('這次沒有逐頁渲染檢查，只讀了文字內容。', [], 'codex'))  # it says it did not
        self.assertFalse(m.claimed_unrendered('建議之後再逐頁渲染檢查一次。', [], 'codex'))  # a suggestion, not a claim
        self.assertFalse(m.claimed_unrendered('簡報已存好。', [], 'codex'))  # nothing claimed
        self.assertFalse(m.claimed_unrendered('已修好表格渲染，並確認樣式正確。', [], 'codex'))  # code, not pages
        self.assertFalse(m.claimed_unrendered('逐頁渲染檢查尚未完成。', [], 'codex'))
        self.assertFalse(m.claimed_unrendered('設計專員已逐頁渲染檢查，通過。', [], 'claude', ['設計專員']))  # the host quoting a member
        self.assertFalse(m.claimed_unrendered(said, [], 'gemini'))  # this CLI does not report its commands to Zook: unknown, so nothing said

    def test_the_host_sees_it_in_its_next_turn(self):
        store = type('S', (), {})(); store.dir = Path('/nonexistent'); store.data = {'bots': [], 'knowledge': [], 'memories': [], 'jobs': []}
        store.find = lambda kind, key: next((x for x in store.data[kind] if x['id'] == key), None)
        host = dict(id='h' * 32, name='主持人'); maker = dict(id='d' * 32, name='設計專員'); store.data['bots'] += [host, maker]
        group = dict(id='g1', name='行銷', botIds=[host['id'], maker['id']], messages=[dict(id='r1', role='assistant', botId=maker['id'], content='已逐頁渲染檢查', unrenderedClaim=True)])
        self.assertIn('Zook 檢查：這則回覆說逐頁看過版面，但這次沒有執行任何轉成圖片的指令', m.group_prompt(store, group, host, False))

    def test_the_turn_checks_and_tells_the_user(self):
        source = (Path(__file__).resolve().parents[1] / 'backend/zook/groups.py').read_text(encoding='utf-8')
        self.assertIn('claimed_unrendered(', source); self.assertIn("said_msg['unrenderedClaim'] = True", source)


if __name__ == '__main__': unittest.main()
