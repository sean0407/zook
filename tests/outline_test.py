# -*- coding: utf-8 -*-
"""The conversation outline beside the messages: one entry per question, with the start of the reply to it, the whole conversation."""
import importlib.util, sys, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_outline', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class OutlineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = load()

    def test_one_entry_per_question_with_the_first_reply(self):
        messages = [dict(id='u1', role='user', content='## 這個 logo\n感覺做不大**呀**', createdAt='2026-11-21T10:00:00+08:00'),
                    dict(id='a1', role='assistant', botId='b1', content='我會把命名方向改成「扶持新創成長」的品牌，' + '很長' * 100, createdAt='2026-11-21T10:01:00+08:00'),
                    dict(id='a2', role='assistant', botId='b2', content='第二位成員的回覆', createdAt='2026-11-21T10:02:00+08:00'),
                    dict(id='s1', role='system', content='提示'),
                    dict(id='u2', role='user', content='', attachments=[dict(name='a.png')], createdAt='2026-11-21T11:00:00+08:00'),
                    dict(id='u3', role='user', content='還沒回覆的問題', createdAt='2026-11-21T12:00:00+08:00'),
                    dict(id='a3', role='assistant', content='', status='running')]
        out = self.m.page_list(messages, {'outline': ['1']})
        self.assertEqual([x['id'] for x in out['outline']], ['u1', 'u2', 'u3'])
        first = out['outline'][0]
        self.assertEqual(first['title'], '這個 logo 感覺做不大呀')  # markdown marks and line breaks go
        self.assertTrue(first['reply'].startswith('我會把命名方向改成「扶持新創成長」的品牌')); self.assertLessEqual(len(first['reply']), 91)
        self.assertEqual((first['replyBy'], first['createdAt']), ('b1', '2026-11-21T10:00:00+08:00'))
        self.assertEqual(out['outline'][1]['title'], '（附件）')
        self.assertEqual(out['outline'][2]['reply'], '')  # nothing finished yet
        self.assertNotIn('messages', out)  # only the outline travels

    def test_long_questions_are_cut(self):
        out = self.m.page_list([dict(id='u', role='user', content='字' * 500)], {'outline': ['1']})
        self.assertEqual(len(out['outline'][0]['title']), 61); self.assertTrue(out['outline'][0]['title'].endswith('…'))


if __name__ == '__main__': unittest.main()
