# -*- coding: utf-8 -*-
"""#217: deleting a member Bot no longer breaks its groups silently. Each group says who left; a group left with one member says
so and takes no message until someone is added; the delete question lists the groups it is in."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import choices_test

ROOT = Path(__file__).resolve().parents[1]


class DeletedMember(choices_test.ChoicesTest):
    for _name in [n for n in dir(choices_test.ChoicesTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_a_group_left_with_one_member_says_so(self):
        other = self.req('POST', '/api/bots', {'name': '專員', 'provider': 'claude'})[1]
        group = self.req('POST', '/api/groups', {'name': '行銷', 'botIds': [self.bot['id'], other['id']]})[1]
        self.assertEqual(self.req('DELETE', '/api/bots/' + other['id'])[0], 200)
        g = next(x for x in self.req('GET', '/api/state')[1]['groups'] if x['id'] == group['id'])
        self.assertEqual(g['botIds'], [self.bot['id']])
        self.assertIn('專員 已刪除，群組少了一位成員；只剩 1 位，要再加成員才能討論。', self.req('GET', '/api/groups/' + group['id'])[1]['group']['messages'][-1]['content'])
        status, out = self.req('POST', '/api/groups/%s/messages' % group['id'], {'content': '大家好'})
        self.assertEqual(status, 409); self.assertIn('只剩 1 位成員', out['error'])
        groups = (ROOT / 'backend/zook/groups.py').read_text(encoding='utf-8')
        self.assertEqual(groups.count('group_enough(self.store, group)'), 3)  # a message (any sender), 繼續, 整理結論

    def test_the_page_warns_before_and_after(self):
        actions = (ROOT / 'frontend/js/40-actions.js').read_text(encoding='utf-8'); chat = (ROOT / 'frontend/js/10-chat.js').read_text(encoding='utf-8')
        self.assertIn('它在這些群組裡', actions); self.assertIn('會只剩 1 位', actions)
        self.assertIn('成員不足：這個群組只剩', chat); self.assertIn("${short ? 'disabled' : ''}", chat)


if __name__ == '__main__': unittest.main()
