# -*- coding: utf-8 -*-
import importlib.util, pathlib, tempfile, unittest

spec = importlib.util.spec_from_file_location('zook_defaults', pathlib.Path(__file__).resolve().parents[1] / 'backend/server.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class BotDefaults(unittest.TestCase):
    """A Bot follows 設定 unless its own 進階設定 says otherwise."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = m.Store(pathlib.Path(self.tmp.name)); self.settings = self.store.data['settings']; m._active['data'] = self.store.data
    def tearDown(self): self.tmp.cleanup()

    def test_the_old_built_in_guide_is_removed_but_an_edited_one_is_kept(self):
        import json
        folder = pathlib.Path(self.tmp.name) / 'old'; folder.mkdir()
        seed = lambda content: dict(id='k', title='swarmr 使用指南', content=content)
        for content, kept in (('swarmr 是本機 AI 工作空間。左上角 ＋ 可建立 Bot', 0), ('我自己改寫的筆記', 1)):
            store = m.Store(folder); store.data['knowledge'] = [seed(content)]; store.save()
            self.assertEqual(len(m.Store(folder).data['knowledge']), kept)

    def test_nothing_set_keeps_the_old_behaviour(self):
        self.assertEqual((m.bot_scope({}), m.bot_effort({})), (('full', ''), 'standard')); self.assertEqual(m.active_features({}, 'codex', True, False, 'full'), [])

    def test_bots_follow_the_defaults_and_their_own_choice_wins(self):
        m.update(self.settings, {'access': 'workspace', 'effort': 'deep', 'features': {'multi': True}}, 'settings')
        self.assertEqual((m.bot_scope({}), m.bot_effort({'effort': ''})), (('workspace', ''), 'deep')); self.assertEqual(m.active_features({}, 'codex', True, False, 'full'), ['multi'])
        own = {'access': 'full', 'effort': 'fast', 'features': {'multi': False}}
        self.assertEqual((m.bot_scope(own), m.bot_effort(own)), (('full', ''), 'fast')); self.assertEqual(m.active_features(own, 'codex', True, False, 'full'), [])
        self.assertEqual(m.active_features({}, 'codex', False, False, 'full'), [])   # still never in 謹慎

    def test_a_bot_can_go_back_to_the_default_but_settings_need_a_real_value(self):
        bot = {'access': 'full', 'effort': 'deep'}; m.update(bot, {'access': '', 'effort': ''}, 'bot'); self.assertEqual((bot['access'], bot['effort']), ('', ''))
        for bad in ({'access': ''}, {'effort': ''}, {'access': 'folder', 'accessFolder': '/no/such'}, {'features': {'nope': True}}): self.assertRaises(ValueError, m.update, self.settings, bad, 'settings')


if __name__ == '__main__': unittest.main()
