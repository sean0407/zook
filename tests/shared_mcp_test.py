# -*- coding: utf-8 -*-
import importlib.util, json, pathlib, tempfile, unittest

spec = importlib.util.spec_from_file_location('zook_shared_mcp', pathlib.Path(__file__).parents[1] / 'backend/server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class SharedMcpTest(unittest.TestCase):
    def test_existing_choices_become_shared(self):
        with tempfile.TemporaryDirectory() as d:
            data = m.seeds(); data.setdefault('settings', {})
            data['bots'][0]['enabledMcp'] = ['a', 'b']; data['bots'][1]['enabledMcp'] = ['b', 'c']
            pathlib.Path(d, 'swarmr.json').write_text(json.dumps(data), encoding='utf-8')
            store = m.Store(pathlib.Path(d))
            self.assertEqual(store.data['settings']['sharedMcp'], ['a', 'b', 'c'])

    def test_only_detected_connectors_are_used(self):
        with tempfile.TemporaryDirectory() as d:
            store = m.Store(pathlib.Path(d)); store.data['settings']['sharedMcp'] = ['builtin:workspace', 'gone']
            inventory = {'skills': [], 'mcp': [{'id': 'builtin:workspace'}, {'id': 'other'}]}
            self.assertEqual(m.shared_mcp_ids(store, inventory), ['builtin:workspace'])

    def test_settings_accept_shared_list(self):
        t = {}; m.update(t, {'sharedMcp': ['x', 'x', 'y']}, 'settings'); self.assertEqual(t['sharedMcp'], ['x', 'y'])


if __name__ == '__main__':
    unittest.main()
