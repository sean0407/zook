import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / 'backend'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


runtime = load('zook_plugin_runtime', 'runtime.py')
server = load('zook_plugin_server', 'server.py')


def plugin(root, name, manifest=None, skills=(), mcp=None):
    (root / '.claude-plugin').mkdir(parents=True)
    (root / '.claude-plugin/plugin.json').write_text(json.dumps(manifest or {'name': name, 'version': '1.0.0', 'description': name + ' plugin'}))
    for skill in skills:
        (root / 'skills' / skill).mkdir(parents=True)
        (root / 'skills' / skill / 'SKILL.md').write_text('---\nname: %s\ndescription: %s skill\n---\nBody' % (skill, skill))
    if mcp is not None: (root / '.mcp.json').write_text(json.dumps(mcp))


class PluginDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name) / 'home'; cache = self.home / '.claude/plugins/cache'
        cc = self.home / '.claude/plugins/cache/m/alpha/1.0.0'
        plugin(cc, 'alpha', skills=['draw'], mcp={'mcpServers': {'alpha-srv': {'command': 'sh', 'args': ['${CLAUDE_PLUGIN_ROOT}/bin/run.sh'], 'env': {'API_TOKEN': 'secret-value-123'}}}})
        (self.home / '.claude/plugins').mkdir(parents=True, exist_ok=True)
        plugin(cache / 'n/alpha/1-0-0', 'alpha', skills=['dupe'])  # same name from another marketplace: the first copy wins
        plugin(cache / 'n/hooks-only/2-0-0', 'hooks-only'); (cache / 'n/hooks-only/2-0-0/hooks').mkdir()
        bundled = self.knowledge = cache / 'n/knowledge/1.0.0'
        (self.home / '.claude/plugins/installed_plugins.json').write_text(json.dumps({'plugins': {
            'alpha@m': [{'installPath': str(cc)}], 'alpha@n': [{'installPath': str(cache / 'n/alpha/1-0-0')}], 'hooks-only@n': [{'installPath': str(cache / 'n/hooks-only/2-0-0')}],
            'knowledge@n': [{'installPath': str(bundled)}], 'escape@n': [{'installPath': str(cache / 'n/escape/1.0.0')}]}}))
        plugin(bundled, 'knowledge', manifest={'name': 'knowledge', 'skills': './skills/', 'mcpServers': './.mcp.json', 'interface': {'displayName': 'Knowledge', 'shortDescription': 'Remember things'}},
               skills=['capture', 'context'], mcp={'mcpServers': {'knowledge': {'command': 'sh', 'args': ['${CLAUDE_PLUGIN_ROOT}/bin/k.sh']}}})
        plugin(cache / 'n/escape/1.0.0', 'escape', manifest={'name': 'escape', 'skills': '../../../../home', 'mcpServers': '../../outside.json'})

    def tearDown(self): self.temp.cleanup()

    def test_discovers_plugins_skills_and_mcp(self):
        d = runtime.discover(self.home)
        plugins = {p['id']: p for p in d['plugins']}
        self.assertEqual(set(plugins), {'plugin:alpha', 'plugin:hooks-only', 'plugin:knowledge', 'plugin:escape'})
        self.assertEqual((plugins['plugin:alpha']['source'], plugins['plugin:alpha']['skillCount'], plugins['plugin:alpha']['mcpCount']), ('claude-code', 1, 1))
        self.assertEqual((plugins['plugin:knowledge']['displayName'], plugins['plugin:knowledge']['skillCount']), ('Knowledge', 2))
        self.assertTrue(plugins['plugin:hooks-only']['hasHooks'])
        self.assertEqual((plugins['plugin:escape']['skillCount'], plugins['plugin:escape']['mcpCount']), (0, 0))
        self.assertNotIn('dupe', [s['name'] for s in d['skills']])
        self.assertEqual({s['name'] for s in d['skills'] if s.get('plugin')}, {'draw', 'capture', 'context'})
        srv = next(x for x in d['mcp'] if x['name'] == 'knowledge')
        self.assertEqual(d['_private']['mcp'][srv['id']]['args'], [str(self.knowledge.resolve()) + '/bin/k.sh'])
        self.assertNotIn('secret-value-123', json.dumps({k: v for k, v in d.items() if k != '_private'}))

    def test_disabled_plugin_is_removed_everywhere(self):
        with tempfile.TemporaryDirectory() as data:
            store = server.Store(Path(data))
            store.data['settings']['disabledPlugins'] = ['plugin:knowledge']
            real = runtime.discover
            with mock.patch.object(server, 'runtime_module', return_value=mock.Mock(discover=lambda: real(self.home))):
                inv = server.inventory_for(store)
            self.assertFalse(next(p for p in inv['plugins'] if p['id'] == 'plugin:knowledge')['enabled'])
            self.assertNotIn('capture', [s['name'] for s in inv['skills']])
            self.assertNotIn('knowledge', [m['name'] for m in inv['mcp']])
            self.assertFalse(any('knowledge' in str(v) for v in inv['_private']['mcp'].values()))
            self.assertIn('draw', [s['name'] for s in inv['skills']])
            self.assertEqual(server.shared_skill_ids(store, inv), [s['id'] for s in inv['skills']])


if __name__ == '__main__': unittest.main()
