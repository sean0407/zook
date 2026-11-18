# -*- coding: utf-8 -*-
"""A1: what each CLI can do, checked against the installed version."""
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_abilities', SERVER); server = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(server)
CLI = '#!/bin/sh\nif [ "$1" = "--help" ]; then echo "%s"; exit 0; fi\nexit 2\n'


class Abilities(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.store = server.Store(self.root / 'data')
        self.cli = self.root / 'agy'

    def tearDown(self): self.temp.cleanup()

    def write(self, options):
        self.cli.write_text(CLI % options); self.cli.chmod(0o755)

    def report(self, version):
        with mock.patch.object(server, 'find_cli', return_value=str(self.cli)), mock.patch.object(server, 'provider_version', return_value=dict(current=version)):
            return server.ability_view(self.store, 'antigravity')

    def test_a_new_version_is_checked_and_a_missing_option_turns_that_ability_off(self):
        everything = '--input-format --output-format --settings --mode --effort --conversation --print'
        self.write(everything)
        view = self.report('1.0.0')
        self.assertEqual({a['state'] for a in view['abilities']}, {'on'}); self.assertEqual(view['changed'], [])
        self.assertTrue(server.ability_on(self.store, 'antigravity', 'effort'))
        self.write(everything.replace('--effort', ''))
        self.assertEqual(self.report('1.0.0')['changed'], [])  # same version: not checked again
        view = self.report('1.1.0')
        self.assertEqual(view['changed'], ['思考強度'])
        self.assertFalse(server.ability_on(self.store, 'antigravity', 'effort')); self.assertTrue(server.ability_on(self.store, 'antigravity', 'chat'))

    def test_unreadable_help_changes_nothing(self):
        self.cli.write_text('#!/bin/sh\nexit 2\n'); self.cli.chmod(0o755)
        self.assertEqual(self.report('2.0.0')['changed'], [])
        self.assertTrue(server.ability_on(self.store, 'antigravity', 'plan'))

    def test_plain_clis_only_offer_chat(self):
        self.assertEqual([a['id'] for a in server.ability_view(self.store, 'gemini')['abilities']], ['chat'])


if __name__ == '__main__': unittest.main()


class Features(unittest.TestCase):
    def test_never_in_careful_or_plan_and_only_where_tried(self):
        on = dict(features=dict(multi=True, image=True))
        self.assertEqual(server.active_features(on, 'codex', True, False, 'workspace'), ['multi', 'image'])
        self.assertEqual(server.active_features(on, 'codex', False, False, 'full'), [])
        self.assertEqual(server.active_features(on, 'claude', True, True, 'full'), [])
        self.assertEqual(server.active_features(on, 'claude', True, False, 'full'), ['multi'])
        self.assertEqual(server.active_features(on, 'grok', True, False, 'workspace'), ['multi'])
        self.assertEqual(server.active_features(on, 'grok', True, False, 'full'), ['multi', 'image'])
        self.assertEqual(server.active_features(on, 'antigravity', True, False, 'full'), [])
        self.assertEqual(server.active_features({}, 'codex', True, False, 'full'), [])
        self.assertEqual(server.feature_support('generic'), [])

    def test_activity_shows_what_was_really_used(self):
        used = lambda *a: [e['arguments']['feature'] for e in server.feature_events(*a)]
        codex = json.dumps(dict(type='item.completed', item=dict(type='collab_tool_call')))
        claude = json.dumps(dict(type='assistant', message=dict(content=[dict(type='tool_use', name='Agent')])))
        self.assertEqual(used('codex', codex, ['multi'], '/nonexistent', 0), ['多代理協作'])
        self.assertEqual(used('claude', claude, ['multi'], '/nonexistent', 0), ['多代理協作'])
        self.assertEqual(used('codex', 'nothing', ['multi'], '/nonexistent', 0), [])
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'cat.png').write_bytes(b'x')
            self.assertEqual(used('grok', '', ['image'], d, 0), ['圖片生成'])
            self.assertEqual(used('grok', '', ['image'], d, 9999999999), [])
