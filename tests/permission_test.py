import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'backend'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


runtime = load('zook_perm_runtime', 'runtime.py')
server = load('zook_perm_server', 'server.py')
INVENTORY = {'skills': [{'id': 'skill:x', 'name': 'X'}], 'mcp': [], '_private': {'skills': {'skill:x': {'path': '/dev/null', 'root': '/tmp'}}, 'mcp': {}}}


class PermissionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def session(self, mode, asked):
        create = runtime._schema('zook_create_bot', 'create', {'name': {'type': 'string'}}, ['name'], False)
        listing = runtime._schema('zook_list_team', 'list', {})
        s = runtime.RuntimeSession(['skill:x'], ['builtin:workspace'], True, self.temp.name, lambda *a: asked.append(a[1]) or True, lambda e: None,
                                   inventory=INVENTORY, extra_tools=[(create, lambda a: 'ok', True), (listing, lambda a: 'ok', False)], permission_mode=mode)
        s.tools()
        s.routes.update({'ext_read': ('m', 'search_files'), 'ext_write': ('m', 'create_file'), 'ext_del': ('m', 'trash_file'),
                         'ext_send': ('m', 'sendMessage'), 'ext_share': ('m', 'share_file'), 'ext_sendmail': ('m', 'sendmail'), 'ext_draft': ('m', 'senddraft')})
        s.annotations.update({'ext_read': {'readOnlyHint': True}, 'ext_write': {'readOnlyHint': False}, 'ext_del': {'readOnlyHint': True}})
        return s

    def test_classification(self):
        s = self.session('manual', [])
        cases = [('zook_workspace_read', {}, 'read'), ('zook_list_team', {}, 'read'), ('zook_workspace_write', {}, 'internal'),
                 ('zook_create_bot', {}, 'internal'), ('ext_read', {}, 'external_read'), ('ext_write', {}, 'external_write'),
                 ('ext_del', {}, 'danger'), ('ext_send', {}, 'danger'), ('ext_share', {}, 'danger'), ('ext_sendmail', {}, 'danger'), ('ext_draft', {}, 'danger'),
                 ('zook_run_skill_helper', {'argv': ['python3', 'build.py']}, 'code'),
                 ('zook_run_skill_helper', {'argv': ['rm', '-rf', 'out']}, 'danger'),
                 ('zook_run_skill_helper', {'argv': ['/usr/bin/curl', 'x']}, 'danger')]
        for name, args, expected in cases:
            self.assertEqual(s.classify(name, args), expected, name)
        s.close()

    def test_which_categories_ask_in_each_mode(self):
        ask = runtime.ASK_IN_MODE
        self.assertEqual(ask['manual'], {'internal', 'external_read', 'code', 'external_write', 'danger'})
        self.assertEqual(ask['auto'], {'code', 'external_write', 'danger'})
        self.assertEqual(ask['bypass'], {'danger'})
        self.assertTrue(all('read' not in v for v in ask.values()))

    def test_internal_change_runs_without_asking_in_auto_and_is_marked(self):
        for mode, expect_ask in (('manual', True), ('auto', False), ('bypass', False)):
            asked, events = [], []
            s = self.session(mode, asked)
            s.event_callback = events.append
            self.assertFalse(s.call('zook_create_bot', {'name': 'A'}).get('isError'))
            self.assertEqual(bool(asked), expect_ask, mode)
            self.assertEqual(any(e.get('autoApproved') for e in events), not expect_ask, mode)
            self.assertEqual(events[0]['category'], 'internal')
            s.close()

    def test_mode_is_read_on_every_call(self):
        asked, mode = [], {'v': 'manual'}
        s = self.session(lambda: mode['v'], asked)
        s.call('zook_create_bot', {'name': 'A'}); self.assertEqual(len(asked), 1)
        mode['v'] = 'bypass'
        s.call('zook_create_bot', {'name': 'B'}); self.assertEqual(len(asked), 1)  # switched mid-reply: no prompt
        mode['v'] = 'nonsense'
        s.call('zook_create_bot', {'name': 'C'}); self.assertEqual(len(asked), 2)  # unknown -> manual
        s.close()

    def test_switching_mode_releases_waiting_approvals(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); app = server.App(('127.0.0.1', 0), store, d, 't')
            try:
                bot = store.data['bots'][0]
                store.data['settings']['permissionMode'] = 'manual'
                store.data['jobs'].append(dict(id='j', botId=bot['id'], status='running', toolCalls=[
                    dict(id='c1', name='zook_create_bot', category='internal', arguments={}), dict(id='c2', name='x', category='danger', arguments={})], approvals=[]))
                results = {}
                def ask(call_id, cat):
                    store.data['jobs'][0]['toolCalls'][[c['id'] for c in store.data['jobs'][0]['toolCalls']].index(call_id)]['category'] = cat
                    results[call_id] = app.approve('j', call_id, 'zook_create_bot', {}, 'builtin:zook')
                t1 = threading.Thread(target=ask, args=('c1', 'internal')); t2 = threading.Thread(target=ask, args=('c2', 'danger'))
                t1.start(); t2.start()
                for _ in range(50):
                    if len(store.data['jobs'][0]['approvals']) == 2: break
                    threading.Event().wait(0.02)
                store.data['settings']['permissionMode'] = 'bypass'
                self.assertEqual(app.release_approvals(), 1)
                t1.join(2)
                self.assertTrue(results.get('c1'))
                approvals = {a['toolCallId']: a for a in store.data['jobs'][0]['approvals']}
                self.assertEqual((approvals['c1']['status'], approvals['c1'].get('autoApproved')), ('approved', True))
                self.assertEqual(approvals['c2']['status'], 'pending')  # dangerous actions still wait for a person
                store.data['jobs'][0]['status'] = 'cancelled'; app.expire_job('j'); t2.join(2)
            finally: app.server_close()

    def test_unknown_mode_falls_back_to_manual(self):
        s = self.session('yolo', [])
        self.assertEqual(s.permission_mode, 'manual'); s.close()

    def test_bot_overrides_global_default(self):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d))
            self.assertEqual(store.data['settings']['permissionMode'], 'manual')
            store.data['settings']['permissionMode'] = 'auto'
            self.assertEqual(server.permission_mode(store, {'permissionMode': ''}), 'auto')
            self.assertEqual(server.permission_mode(store, {'permissionMode': 'bypass'}), 'bypass')
            with self.assertRaises(ValueError): server.update({}, {'permissionMode': 'yolo'}, 'settings')
            with self.assertRaises(ValueError): server.update({}, {'permissionMode': ''}, 'settings')
            target = {}; server.update(target, {'permissionMode': ''}, 'bot'); self.assertEqual(target, {'permissionMode': ''})


if __name__ == '__main__': unittest.main()
