# -*- coding: utf-8 -*-
import importlib.util, pathlib, re, tempfile, unittest

spec = importlib.util.spec_from_file_location('zook_icons', pathlib.Path(__file__).parents[1] / 'backend/server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def key(name):
    return next((k for k, p in m.ICON_RULES if re.search(p, name.lower())), None)


class IconTest(unittest.TestCase):
    def test_names_map_to_official_apps(self):
        cases = {'docx': 'word', 'logi-pptx': 'powerpoint', 'xlsx': 'excel', 'Google Sheets': 'gsheets', 'logi-slides': 'gslides',
                 'Gdrive': 'gdrive', 'Zoom': 'zoom', 'obsidian-wiki': 'obsidian', 'figma:figma-use': 'figma',
                 'canvas-design': None, 'Gmail': 'gmail', 'Google Calendar': 'gcalendar', 'Google People': 'gcontacts', 'Perplexity': 'perplexity',
                 'node_repl': 'nodejs', 'notebooklm-studio': 'notebooklm', 'gemini-notebook-mcp': 'gemini', 'logi-asana-demo-request': 'asana', 'Web Search': None}
        for name, want in cases.items(): self.assertEqual(key(name), want, name)

    def test_bundled_icons_exist(self):
        root = pathlib.Path(__file__).parents[1] / 'frontend/icons'
        for k in m.BUNDLED_ICONS: self.assertTrue((root / (k + '.png')).is_file(), k)
        self.assertEqual(m.icon_for('Gmail'), '/icons/gmail.png')

    def test_unknown_key_and_missing_tool_give_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            store = m.Store(pathlib.Path(d))
            self.assertIsNone(m.icon_png(store, '../etc'))
            self.assertIsNone(m.icon_png(store, 'nope'))


if __name__ == '__main__':
    unittest.main()
