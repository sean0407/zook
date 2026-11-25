# -*- coding: utf-8 -*-
"""#99/#202: a date written with a weekday that does not match is caught before the Bots read it. The user's words stay as
written; a plain line under the message says what is wrong, and every Bot (one Bot, a group member, the 任務 host) reads a
Zook note asking it to check with the user first instead of copying it."""
import datetime, importlib.util, json, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import choices_test

ROOT = Path(__file__).resolve().parents[1]
TODAY = datetime.date(2026, 11, 25)  # a Wednesday


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_date_check', ROOT / 'backend/server.py')
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(ROOT / 'backend')); spec.loader.exec_module(module)
    return module


class DateCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def check(self, text): return self.m.date_check(text, TODAY)

    def test_the_two_cases_from_the_inspections(self):
        notes = self.check('尾牙訂在 1/23 禮拜五晚上，幫我排流程')
        self.assertEqual(len(notes), 1)
        self.assertIn('2027/1/23 是週六，不是週五', notes[0]); self.assertIn('2026/1/23 才是週五（已經過了）', notes[0]); self.assertIn('1/23 禮拜五', notes[0])
        notes = self.check('下週一 12/1 早上十點開會，請通知大家')
        self.assertEqual(len(notes), 1); self.assertIn('2026/12/1 是週二，不是週一', notes[0]); self.assertIn('下週一 12/1', notes[0])

    def test_formats(self):
        wrong = ('2027/1/23 週五', '2027-1-23（星期五）', '2027年1月23日 禮拜五', '1月23日(五)', '1/23 Fri', '1/23 (Friday)', 'Fri 1/23', '星期五，1/23', '12月1日 周一')
        for text in wrong: self.assertEqual(len(self.check(text)), 1, text)
        right = ('2027/1/23 週六', '2027-1-23（星期六）', '2027年1月23日 禮拜六', '1月23日(六)', '1/23 Sat', '1/23 (Saturday)', 'Sat 1/23', '星期六，1/23', '12月1日 周二', '12/6 禮拜天')
        for text in right: self.assertEqual(self.check(text), [], text)

    def test_nothing_to_check(self):
        for text in ('1/23 晚上', '週五晚上見', '每週五 12/4 開始', '12/1-12/5 週一到週五上班', '分數 3/4', '版本 2.1.23', 'https://x.com/a/1/23 週五', '我的螢幕 monitor 12/1', '12/1 19:00 週一', ''):
            self.assertEqual(self.check(text), [], text)

    def test_past_and_uncertain(self):
        self.assertEqual(self.check('上週五 11/20 的會議紀錄'), [])  # 2026/11/20 is a Friday
        self.assertEqual(self.check('11/20 週五那場會'), [])  # within the last month: the one that just went
        notes = self.check('上週四 11/20 的會議紀錄')
        self.assertEqual(len(notes), 1); self.assertIn('2026/11/20 是週五，不是週四', notes[0])
        notes = self.check('去年 1/23 週六的活動')  # talking about the past: the last 1/23, a Friday (the coming one is a Saturday, but that is not what was meant)
        self.assertIn('2026/1/23 是週五，不是週六', notes[0]); self.assertNotIn('2027', notes[0])
        self.assertNotIn('2025', self.check('下週一 12/1 開會')[0])  # 下週 is the coming one: no talk of a past year

    def test_days_that_do_not_exist(self):
        self.assertIn('沒有 2027/2/30 這一天', self.check('2027/2/30 週二')[0])
        self.assertIn('沒有 2/30 這一天', self.check('2/30 週二')[0])
        self.assertEqual(self.check('2/29 週二'), [])  # 2028/2/29 is a Tuesday

    def test_several_and_capped(self):
        text = '、'.join('2027/1/%d 週一' % d for d in range(2, 30))
        self.assertEqual(len(self.check(text)), self.m.DATE_CHECK_MAX)
        self.assertEqual(len(self.check('1/23 週五、1/24 週六、1/25 週一')), 2)

    def test_marks_the_message_and_tells_the_bots(self):
        message = dict(content='1/23 禮拜五')
        self.m.date_check_message(message, TODAY)
        self.assertEqual(message['content'], '1/23 禮拜五')  # the user's words are never changed
        note = self.m.date_check_note(message)
        self.assertIn('Zook 檢查日期', note); self.assertIn('請先向使用者確認', note); self.assertIn('2027/1/23 是週六', note)
        self.assertEqual(self.m.date_check_note(dict(content='hi')), '')
        self.assertIn('date_check_note', self.m.conversation_context.__code__.co_names)
        line = self.m.conversation_context([dict(role='user', content='1/23 禮拜五', dateCheck=message['dateCheck'])])
        self.assertIn('Zook 檢查日期', line)

    def test_every_place_a_bot_reads_the_users_words(self):
        for name in ('groups.py', 'tasks.py', 'sessions.py'):
            self.assertIn('date_check_note(m)', (ROOT / 'backend/zook' / name).read_text(encoding='utf-8'), name)
        groups = (ROOT / 'backend/zook/groups.py').read_text(encoding='utf-8')
        self.assertEqual(groups.count('date_check_message(message)'), 2)  # a new round and 插話
        self.assertIn("'datecheck'", (ROOT / 'backend/server.py').read_text(encoding='utf-8'))

    def test_the_page_shows_the_note_under_the_users_message(self):
        js = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))
        self.assertIn('window.dateNote', js)
        chat = (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8')
        self.assertEqual(chat.count('dateNote(m)'), 2)  # one Bot, and a group


class DateCheckLive(choices_test.ChoicesTest):
    for _name in [n for n in dir(choices_test.ChoicesTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_one_bot_reads_the_note_and_the_page_gets_it(self):
        self.finish(self.send('2027/1/23 禮拜五 尾牙'))
        self.assertIn('Zook 檢查日期', self.prompt()); self.assertIn('2027/1/23 是週六，不是週五', self.prompt())
        asked = [m for m in next(b for b in self.req('GET', '/api/state')[1]['bots'] if b['id'] == self.bot['id'])['messages'] if m['role'] == 'user'][-1]
        self.assertEqual(asked['content'], '2027/1/23 禮拜五 尾牙')
        self.assertEqual(len(asked['dateCheck']), 1)
        self.finish(self.send('2027/1/23 禮拜六 尾牙'))
        self.assertNotIn('Zook 檢查日期：「2027/1/23 禮拜六', self.prompt())

    def test_a_group_member_reads_the_note(self):
        other = self.req('POST', '/api/bots', {'name': '專員', 'provider': 'claude'})[1]
        group = self.req('POST', '/api/groups', {'name': '行銷', 'botIds': [self.bot['id'], other['id']]})[1]
        self.assertEqual(self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '2027/1/23 禮拜五 尾牙，大家看一下'})[0], 202)
        end = time.time() + 20
        while time.time() < end:
            g = self.req('GET', '/api/groups/' + group['id'])[1]['group']
            if g['status'] != 'running': break
            time.sleep(0.1)
        asked = next(m for m in g['messages'] if m['role'] == 'user')
        self.assertEqual(asked['content'], '2027/1/23 禮拜五 尾牙，大家看一下'); self.assertEqual(len(asked['dateCheck']), 1)
        self.assertIn('Zook 檢查日期', self.prompt()); self.assertIn('2027/1/23 是週六', self.prompt())


if __name__ == '__main__': unittest.main()
