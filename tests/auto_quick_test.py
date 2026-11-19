# -*- coding: utf-8 -*-
"""自動選擇 answers a short question with the faster models and a lighter thinking level."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_model_test, auto_role_test


class QuickPick(auto_role_test.AutoRoleTest):
    test_role_is_read_from_the_name_then_the_persona = test_plain_question_follows_the_bots_role = None

    def test_short_question_goes_to_the_fast_models_and_grok_is_last(self):
        self.assertEqual(self.m.AUTO_TASKS['quick'][1][0], 'claude'); self.assertEqual(self.m.AUTO_TASKS['quick'][1][-1], 'grok')
        self.assertEqual(self.pick('現在幾點')[0], 'claude')

    def test_lighter_thinking_only_when_nobody_chose_a_level(self):
        quick = self.m.auto_quick_effort; store = self.store
        self.assertEqual(quick(store, dict(name='助理'), '現在幾點'), 'fast')
        self.assertIsNone(quick(store, dict(name='助理', effort='deep'), '現在幾點'))  # the Bot's own level wins
        self.assertIsNone(quick(store, dict(name='助理', effort='standard'), '現在幾點'))
        self.assertIsNone(quick(store, dict(name='助理'), '現在幾點', given='standard'))  # so does the level picked for this message
        self.assertIsNone(quick(store, dict(name='助理'), '請分析這兩個方案的優缺點'))
        self.assertIsNone(quick(store, dict(name='助理'), '看一下', names=['a.pdf']))
        self.assertIsNone(quick(store, dict(name='財務長'), '現在幾點'))  # a Bot with a careful role keeps its normal level
        store.data['settings']['effort'] = 'deep'
        self.assertIsNone(quick(store, dict(name='助理'), '現在幾點'))


class QuickChat(auto_model_test.AutoModelTest):
    for _name in [n for n in dir(auto_model_test.AutoModelTest) if n.startswith('test_')]: locals()[_name] = None
    del _name

    def test_reply_says_which_level_was_used(self):
        reply = self.send('現在幾點')
        self.assertEqual(reply['effort'], 'fast'); self.assertIn('較快的思考強度', reply['autoWhy']); self.assertEqual(reply['auto'], 'Claude simple')
        reply = self.send('請分析這兩個方案的優缺點')
        self.assertNotIn('effort', reply); self.assertNotIn('較快', reply['autoWhy'])

    def test_a_level_picked_for_the_message_is_kept(self):
        status, job = self.req('POST', '/api/chat', {'botId': self.bot['id'], 'content': '現在幾點', 'effort': 'deep'})
        self.assertLess(status, 300, job)
        self.assertEqual(self.req('GET', '/api/jobs/' + job['jobId'])[1]['effort'], 'deep')

    def test_named_model_bot_keeps_the_standard_level(self):
        bot = self.req('POST', '/api/bots', {'name': 'Fixed', 'provider': 'codex'})[1]
        status, job = self.req('POST', '/api/chat', {'botId': bot['id'], 'content': '現在幾點'})
        self.assertEqual(self.req('GET', '/api/jobs/' + job['jobId'])[1]['effort'], 'standard')


if __name__ == '__main__': unittest.main()
