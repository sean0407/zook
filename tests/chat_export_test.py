# -*- coding: utf-8 -*-
"""「↑ 匯出對話」: only the open conversation, with its title and dates; who said each message and when, the model of each reply,
failed and stopped replies marked, and the reply's own headings kept below the file's title. A group's discussion the same way."""
import importlib.util, sys, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_export', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def at(hour, minute=0): return '2026-11-23T%02d:%02d:00+00:00' % (hour, minute)


class ChatExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def local(self, stamp): return self.m.export_time(stamp)

    def setUp(self):
        self.open = [dict(id='u1', role='user', content='幫我整理週報', createdAt=at(6), attachments=[dict(id='f1', name='銷售.xlsx', kind='file')]),
                     dict(id='a1', role='assistant', status='completed', createdAt=at(6, 1), note='這次改用 Claude（Codex 額度已用完）',
                          content='# 週報\n\n## 重點\n\n```\n# 這不是標題\n```\n內文'),
                     dict(id='u2', role='user', content='再改一次', createdAt=at(7)),
                     dict(id='a2', role='assistant', status='failed', content='', createdAt=at(7, 1)),
                     dict(id='u3', role='user', content='算了', createdAt=at(8)),
                     dict(id='a3', role='assistant', status='cancelled', content='寫到一半', createdAt=at(8, 1))]
        self.bot = dict(id='b1', name='管理員', chatId='c2', messages=self.open,
                        chats=[dict(id='c1', title='舊的對話', messages=[dict(id='o1', role='user', content='很久以前的問題', createdAt=at(1))]),
                               dict(id='c2', title='週報整理', createdAt=at(6))])
        self.data = dict(bots=[self.bot], jobs=[dict(id='j1', botId='b1', messageId='a1', status='completed', usage=dict(model='claude-sonnet-4-5', provider='claude')),
                                                dict(id='j2', botId='b1', messageId='a2', status='failed', error='額度用完了', ran=['codex', 'gpt-5.5', ''])])

    def test_only_the_open_conversation_with_title_and_dates(self):
        out = self.m.export_chat(self.data, self.bot, 'c2', now=at(9))
        text = out['markdown']
        self.assertNotIn('很久以前的問題', text)  # another conversation of the same Bot stays out
        self.assertTrue(text.startswith('# 管理員 · 週報整理\n'))
        self.assertIn(self.local(at(6)), text)  # when it started
        self.assertIn(self.local(at(8, 1)), text)  # and its last message
        self.assertEqual(out['name'], '管理員-週報整理-%s.md' % self.local(at(9))[:10])

    def test_speaker_time_model_and_failures(self):
        text = self.m.export_chat(self.data, self.bot, 'c2', now=at(9))['markdown']
        self.assertIn('**我** · %s' % self.local(at(6)), text)
        self.assertIn('**管理員** · %s · Claude claude-sonnet-4-5' % self.local(at(6, 1)), text)
        self.assertIn('這次改用 Claude（Codex 額度已用完）', text)
        self.assertIn('**管理員** · %s · Codex gpt-5.5 · ⚠️ 回覆失敗' % self.local(at(7, 1)), text)
        self.assertIn('額度用完了', text)  # the reason, since the reply itself is empty
        self.assertIn('**管理員** · %s · ⏹ 已停止' % self.local(at(8, 1)), text)
        self.assertIn('寫到一半', text)
        self.assertIn('銷售.xlsx', text)  # attachments are named, and said not to be in the file
        self.assertIn('沒有帶入', text)
        self.assertNotIn('## 我', text)

    def test_reply_headings_sit_below_the_file_title(self):
        text = self.m.export_chat(self.data, self.bot, 'c2', now=at(9))['markdown']
        self.assertEqual([line for line in text.splitlines() if line.startswith('# ')], ['# 管理員 · 週報整理', '# 這不是標題'])  # one top title; the other is inside a code block
        self.assertIn('\n### 週報\n', text); self.assertIn('\n#### 重點\n', text)
        self.assertIn('```\n# 這不是標題\n```', text)  # code is left as it is
        self.assertEqual(self.m.demote_headings('###### 六級'), '###### 六級')  # never past the deepest level

    def test_empty_conversation_says_so(self):
        bot = dict(id='b2', name='新 Bot', chatId='c9', messages=[], chats=[dict(id='c9', title='')])
        out = self.m.export_chat(dict(bots=[bot], jobs=[]), bot, 'c9', now=at(9))
        self.assertIn('還沒有內容', out['markdown'])
        self.assertEqual(out['name'], '新 Bot-新對話-%s.md' % self.local(at(9))[:10])
        self.assertTrue(out['empty'])

    def test_unsafe_file_name_characters_are_replaced(self):
        self.bot['chats'][1]['title'] = 'a/b:c'
        self.assertEqual(self.m.export_chat(self.data, self.bot, 'c2', now=at(9))['name'], '管理員-a_b_c-%s.md' % self.local(at(9))[:10])

    def test_group_discussion(self):
        b2 = dict(id='b2', name='查核員', messages=[])
        group = dict(id='g1', name='報價小組', botIds=['b1', 'b2'], messages=[
            dict(id='gu', role='user', content='做報價', createdAt=at(6)),
            dict(id='ga', role='assistant', botId='b1', status='completed', content='## 報價\n內容', createdAt=at(6, 2)),
            dict(id='gs', role='system', content='存了共用檔案 報價.xlsx', createdAt=at(6, 3)),
            dict(id='gc', role='assistant', botId='b2', status='failed', content='', checkOf='ga', createdAt=at(6, 4))])
        data = dict(bots=[self.bot, b2], jobs=[dict(id='j9', botId='b1', groupId='g1', messageId='ga', usage=dict(model='gpt-5.5', provider='codex'))])
        out = self.m.export_group(data, group, now=at(9))
        text = out['markdown']
        self.assertTrue(text.startswith('# 報價小組\n'))
        self.assertIn('**我** · %s' % self.local(at(6)), text)
        self.assertIn('**管理員** · %s · Codex gpt-5.5' % self.local(at(6, 2)), text)
        self.assertIn('\n#### 報價\n', text)
        self.assertIn('> 存了共用檔案 報價.xlsx', text)
        self.assertIn('**查核員**（驗收） · %s · ⚠️ 回覆失敗' % self.local(at(6, 4)), text)
        self.assertEqual(out['name'], '報價小組-群組對話-%s.md' % self.local(at(9))[:10])

    def test_code_blocks_quotes_and_underlined_headings(self):
        d = self.m.demote_headings
        self.assertEqual(d('```\n``` not the end\n# kept\n```'), '```\n``` not the end\n# kept\n```')
        self.assertEqual(d('```py\nx = 1'), '```py\nx = 1\n```')  # an open block is closed so it cannot swallow later messages
        self.assertEqual(d('> # 引用標題'), '> ### 引用標題')
        self.assertEqual(d('大標\n===\n\n小標\n---'), '### 大標\n\n#### 小標')
        self.assertEqual(d('- 項目\n---'), '- 項目\n---')  # a rule after a list stays a rule

    def test_group_task_check_verdict_reason_and_times(self):
        group = dict(id='g1', name='小組', botIds=['b1'], taskRun=dict(tasks=[dict(id='t1', verify=dict(jobId='jv', verdict='fail', reasons='少了價格'))]), messages=[
            dict(id='gu', role='user', content='開始', createdAt=at(6, 5)),
            dict(id='gv', role='assistant', botId='b1', status='completed', content='', taskId='t1', taskCheck=True, createdAt=at(6, 1)),
            dict(id='gx', role='assistant', botId='b1', status='failed', content='', error='成員正在忙', createdAt=at(6, 2)),
            dict(id='gs', role='system', content='存了共用檔案', createdAt=at(6, 3))])
        data = dict(bots=[self.bot], jobs=[dict(id='jv', botId='b1', groupId='g1', messageId='gv', usage=dict(model='預設模型', provider='claude'))])
        text = self.m.export_group(data, group, now=at(9))['markdown']
        self.assertIn('**管理員**（驗收） · %s · Claude（預設模型）' % self.local(at(6, 1)), text)
        self.assertIn('驗收判定：不通過。少了價格', text)
        self.assertIn('（此回覆失敗：成員正在忙）', text)
        self.assertIn('> *Zook · %s*\n> 存了共用檔案' % self.local(at(6, 3)), text)
        self.assertIn('- 期間：%s ～ %s' % (self.local(at(6, 1)), self.local(at(6, 5))), text)  # earliest to latest, not first to last


if __name__ == '__main__': unittest.main()
