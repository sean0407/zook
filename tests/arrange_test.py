# -*- coding: utf-8 -*-
import importlib.util, pathlib, tempfile, unittest

spec = importlib.util.spec_from_file_location('zook_arrange', pathlib.Path(__file__).parents[1] / 'backend/server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class ArrangeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = m.Store(pathlib.Path(self.tmp.name))
    def tearDown(self): self.tmp.cleanup()

    def test_reorders_moves_and_keeps_empty_groups(self):
        ids = [b['id'] for b in self.store.data['bots']]
        order = [dict(id=i, section='研究') for i in reversed(ids)]
        order[0]['pinned'] = True
        m.arrange_bots(self.store, dict(sections=['研究', '空的'], bots=order))
        self.assertEqual([b['id'] for b in self.store.data['bots']], list(reversed(ids)))
        self.assertTrue(self.store.data['bots'][0]['pinned'])
        self.assertTrue(all(b['section'] == '研究' for b in self.store.data['bots'][1:]))
        self.assertEqual(self.store.data['settings']['sections'], ['研究', '空的'])

    def test_rejects_missing_bot_or_unknown_group(self):
        ids = [b['id'] for b in self.store.data['bots']]
        with self.assertRaises(ValueError): m.arrange_bots(self.store, dict(sections=['a'], bots=[dict(id=ids[0], section='a')]))
        with self.assertRaises(ValueError): m.arrange_bots(self.store, dict(sections=['a'], bots=[dict(id=i, section='b') for i in ids]))


if __name__ == '__main__':
    unittest.main()
