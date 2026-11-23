# -*- coding: utf-8 -*-
"""The gate's local rules (2026-11-22 review): what this Mac allows a Bot, backups, sync, the approval card, the CLIs' hook files,
and 自動選擇 matching that never runs on API billing."""
import importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
sys.path.insert(0, str(ROOT / 'backend'))
import runtime  # noqa: E402


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_gate_local', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


class LocalRulesTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.store = self.m.Store(self.root / 'data')
        self.store.data['settings'].update(permissionMode='bypass', access='full'); self.store.data['bots'].clear()  # the widest the other CLIs could have

    def tearDown(self): self.temp.cleanup()

    def test_only_this_mac_lets_a_bot_use_the_whole_mac(self):
        m, store = self.m, self.store
        made = dict(id='b1', name='a', provider='claude'); m.set_gate_full(made)
        self.assertTrue(made['gateFull'])
        self.assertEqual((m.permission_mode(store, made, 'claude'), m.bot_scope(made, 'claude')), ('auto', ('full', '')))
        synced = dict(id='b2', name='b', provider='cursor', permissionMode='manual', access='workspace')  # arrived from another Mac
        self.assertEqual((m.permission_mode(store, synced, 'cursor'), m.bot_scope(synced, 'cursor')), ('manual', ('workspace', '')))
        other = dict(id='b3', name='c', provider='codex', gateFull=True); m.set_gate_full(other)
        self.assertNotIn('gateFull', other)

    def test_a_backup_without_the_gate_is_held_in(self):
        m, store = self.m, self.store
        bot = dict(id='b1', name='a', provider='claude', gateFull=True, permissionMode='bypass', access='full')
        for kind in ('codex', 'grok', 'antigravity', 'generic'):
            self.assertEqual(m.permission_mode(store, bot, kind), 'manual', kind)
            self.assertEqual(m.bot_scope(bot, kind), ('workspace', ''), kind)
        self.assertEqual(m.bot_scope(dict(id='x', name='x', provider='codex', access='full'), 'codex'), ('full', ''))  # others keep their own

    def test_sync_never_carries_or_widens_it(self):
        m, store = self.m, self.store
        bot = dict(id='b1', name='a', provider='claude', gateFull=True, messages=[], chats=[])
        store.data['bots'].append(bot)
        value = m.sync_clean('bots:b1', dict(name='a', provider='claude', gateFull=True, model=''))
        self.assertNotIn('gateFull', value)
        self.assertTrue(m.sync_put(store, 'bots:b1', value)); self.assertTrue(bot['gateFull'])  # the same model: unchanged
        self.assertTrue(m.sync_put(store, 'bots:b1', dict(value, provider='cursor'))); self.assertNotIn('gateFull', bot)
        self.assertTrue(m.sync_put(store, 'bots:b2', dict(value, provider='claude')))
        self.assertNotIn('gateFull', store.find('bots', 'b2'))  # a new Bot from another Mac: its own 主動性 and 存取範圍 apply

    def test_migration_once(self):
        m, store = self.m, self.store
        store.data['bots'] += [dict(id='c', name='c', provider='claude', scripts=True), dict(id='d', name='d', provider='codex', scripts=True), dict(id='e', name='e', provider='cursor')]
        m.local_migrate(store)
        self.assertEqual([b.get('scripts') for b in store.data['bots']], [False, False, False])
        self.assertEqual([b.get('gateFull') for b in store.data['bots']], [True, None, True])
        store.data['bots'][1]['scripts'] = True  # turned on again on purpose later: not undone
        m.local_migrate(store); self.assertTrue(store.data['bots'][1]['scripts'])

    def test_claude_hook_blocks_on_failure_and_policy_is_checked(self):
        m = self.m
        hook = json.loads(m.claude_gate_settings(600))['hooks']['PreToolUse'][0]
        self.assertEqual((hook['hooks'][0]['onFailure'], hook['hooks'][0]['timeout']), ('block', 660))
        for tool in ('Bash', 'Read', 'Glob', 'Grep', 'Write', 'Edit', 'Task'): self.assertRegex(tool, '^(%s)$' % hook['matcher'])
        policy = self.root / 'policy'; policy.mkdir()
        self.assertTrue(m.claude_hooks_allowed(policy))
        (policy / 'managed-settings.json').write_text(json.dumps({'allowManagedHooksOnly': True}))
        self.assertFalse(m.claude_hooks_allowed(policy))
        (policy / 'managed-settings.json').write_text('{broken')
        self.assertFalse(m.claude_hooks_allowed(policy))

    def test_cursor_hook_waits_as_long_as_the_card(self):
        work = self.root / 'ws'; work.mkdir()
        self.m.prepare_cursor_folder(work, str(ROOT / 'backend/zook/tool_server.py'), True, 660)
        hook = json.loads((work / '.cursor/hooks.json').read_text())['hooks']['preToolUse'][0]
        self.assertEqual((hook['failClosed'], hook['timeout']), (True, 720))

    def test_auto_matched_bots_never_run_on_api_billing(self):
        m, store = self.m, self.store
        now = __import__('time').time()
        store.data['autoStatus'] = {'codex': dict(signedIn=True, billed=False, checkedAt=now), 'claude': dict(signedIn=True, billed=True, checkedAt=now)}
        self.assertEqual(m.auto_billing_problem(store, 'codex', ''), '')
        self.assertEqual(m.auto_billing_problem(store, 'claude', ''), 'API 計費不會被自動選用')
        self.assertEqual(m.auto_billing_problem(store, 'codex', 'gone'), '帳號已移除')
        store.data['autoStatus']['codex'] = dict(signedIn=None, billed=False, checkedAt=now - 3600)  # the last check could not finish: an old result
        self.assertEqual(m.auto_billing_problem(store, 'codex', ''), '最近沒能確認是訂閱帳號')
        self.assertTrue(m.auto_billing_stale(store, ['codex'])); self.assertFalse(m.auto_billing_stale(store, ['claude']))
        bot = dict(id='x', provider='codex', account='')
        self.assertEqual(m.auto_billing_keys(store, bot, [('codex', '', None, False), ('claude', '', '', False)]), ['codex', 'claude'])
        store.data.pop('autoStatus')
        self.assertEqual(m.auto_billing_problem(store, 'codex', ''), '最近沒能確認是訂閱帳號')
        # a check marks the time only when it finished
        with mock.patch.object(m, 'auto_status', side_effect=[dict(signedIn=True, billed=False), dict(signedIn=None, billed=True)]), \
             mock.patch.object(m, 'find_cli', return_value='/bin/true'), mock.patch.object(m, 'auto_accounts', return_value=[]):
            store.data['autoStatus'] = {}
            with mock.patch.object(m, 'AUTO_MODELS', ('codex', 'claude')): m.refresh_auto_status(store, wait=True)
        self.assertIn('checkedAt', store.data['autoStatus']['codex']); self.assertNotIn('checkedAt', store.data['autoStatus']['claude'])

    def test_auto_matched_marker_travels_and_only_its_bots_are_checked(self):
        m, store = self.m, self.store
        bot = dict(id='b1', name='a', provider='codex', autoAssigned=True, messages=[], chats=[])
        store.data['bots'].append(bot)
        value = m.sync_clean('bots:b1', dict(name='a', provider='codex', model='gpt-5.5', fixedModel=True))
        self.assertTrue(value['fixedModel'])
        self.assertTrue(m.sync_put(store, 'bots:b2', dict(value)))
        self.assertTrue(store.find('bots', 'b2')['syncedModel']); self.assertNotIn('fixedModel', store.find('bots', 'b2'))
        self.assertTrue(m.sync_put(store, 'bots:b3', m.sync_clean('bots:b3', dict(name='c', provider='codex', model='x'))))
        self.assertNotIn('syncedModel', store.find('bots', 'b3'))  # chosen by hand on the other Mac: its own account as usual

    def test_each_waiting_bot_is_matched_when_it_can_be_and_keeps_its_model(self):
        m, store = self.m, self.store
        store.data['settings'].update(autoModels=['codex', 'claude'], provider='codex', model='')
        store.data['bots'] += [dict(id='a', name='寫程式的', provider='auto', instructions='你是工程師'), dict(id='b', name='分析的', provider='auto', persona='細心的分析師')]
        with mock.patch.object(m, 'find_cli', return_value='/bin/true'), mock.patch.object(m, 'ability_on', return_value=True), \
             mock.patch.object(m, 'codex_default_model', return_value=''), mock.patch.object(m, 'log_activity'):
            store.data['autoStatus'] = {}
            for b in store.data['bots']: b['autoPending'] = True
            m.auto_retry(store)
            self.assertEqual([b['provider'] for b in store.data['bots']], ['auto', 'auto'])  # nothing can be picked yet: both wait
            self.assertTrue(all(b['autoPending'] for b in store.data['bots']))
            store.data['autoStatus'] = {'codex': dict(signedIn=True, billed=False)}
            store.data['jobs'].append(dict(id='j', status='completed', usage=dict(provider='codex', account='', model='gpt-5.5')))  # another Bot's reply
            m.auto_retry(store)
            a, b = store.data['bots']
            self.assertEqual((a['provider'], a['model'], a.get('autoPending'), a['autoModelPending']), ('codex', '', None, True))  # never another Bot's model
            self.assertEqual((b['provider'], b['model']), ('codex', ''))
            with mock.patch.object(m, 'codex_default_model', return_value='gpt-5.6'):
                d = dict(id='d', name='寫程式', provider='auto', instructions='你是工程師'); m.auto_on_create(store, d)
            self.assertEqual((d['provider'], d['model']), ('codex', 'gpt-5.6'))  # the CLI's own default model
            store.data['jobs'].clear(); store.data['autoStatus']['claude'] = dict(signedIn=True, billed=False)
            c = dict(id='c', name='新的', provider='auto', persona='細心的分析師'); m.auto_on_create(store, c, grant=True)  # made by the user here
            self.assertEqual((c['provider'], c['model'], c['autoModelPending'], c['gateFull']), ('claude', '', True, True))
            store.data['bots'].append(c)
            m.auto_pin_model(store, 'c', 'claude', dict(model='claude-opus-5-5'))
            self.assertEqual((c['model'], c.get('autoModelPending')), ('claude-opus-5-5', None))


    def test_edits_backups_and_sync_never_widen_it(self):
        m, store = self.m, self.store
        synced = dict(id='s', name='s', provider='claude', permissionMode='bypass', access='full')
        after = dict(synced, name='新名字'); m.local_choice(synced, after, dict(name='新名字', provider='claude', access=''))
        self.assertNotIn('gateFull', after)  # a name edit is not choosing Claude here
        after = dict(synced); after['provider'] = 'cursor'; m.local_choice(synced, after, dict(provider='cursor'))
        self.assertTrue(after['gateFull'])  # picking it here is
        moved = dict(id='g', name='g', provider='claude', gateFull=True, permissionMode='bypass', access='full', messages=[], chats=[])
        store.data['bots'].append(moved)
        self.assertTrue(m.sync_put(store, 'bots:g', m.sync_clean('bots:g', dict(name='g', provider='codex', model=''))))
        self.assertEqual((moved.get('gateFull'), moved['localLimit']), (None, True))
        self.assertEqual((m.permission_mode(store, moved, 'codex'), m.bot_scope(moved, 'codex')), ('manual', ('workspace', '')))  # not its old 全部允許
        after = dict(moved, name='x'); m.local_choice(moved, after, dict(name='x', access='workspace', permissionMode='manual')); self.assertTrue(after['localLimit'])  # the form sends what it has
        after = dict(moved); m.local_choice(moved, after, dict(access='folder')); self.assertNotIn('localLimit', after)  # changed here by the user
        data = dict(bots=[dict(id='b', name='b', provider='claude', gateFull=True, scripts=True)], settings={}, deletedBots=[dict(id='d', name='d', provider='codex', scripts=True)])
        m.backup_check(data)
        self.assertEqual((data['bots'][0].get('gateFull'), data['bots'][0]['localLimit'], data['bots'][0]['scripts'], data['deletedBots'][0]['scripts']), (None, True, False, False))
        self.assertTrue(data['settings']['gateFullSet'] and data['settings']['scriptsOff'])  # the one-time upgrade cannot grant it afterwards
        chain = [('claude', '', None, False), ('custom-x', '', None, False), ('codex', '', None, False)]
        self.assertEqual([x[0] for x in m.held_backups(dict(provider='claude'), 'claude', chain)], ['claude', 'codex'])
        self.assertEqual(len(m.held_backups(dict(provider='codex'), 'codex', chain)), 3)

    def test_deleted_and_recalled_bots_have_scripts_off(self):
        m, store = self.m, self.store
        store.data['deletedBots'] = [dict(id='d', name='舊的', provider='codex', scripts=True, messages=[], chats=[])]
        store.data['settings'].pop('scriptsOff', None)
        m.local_migrate(store); self.assertFalse(store.data['deletedBots'][0]['scripts'])
        store.data['deletedBots'][0]['scripts'] = True
        m.restore_bot(store, 'd'); self.assertFalse(store.find('bots', 'd')['scripts'])

    def test_claude_policies_are_looked_for_everywhere_this_mac_keeps_them(self):
        m = self.m; import plistlib
        policy, config = self.root / 'p', self.root / 'c'; policy.mkdir(); config.mkdir()
        plist = self.root / 'com.anthropic.claudecode.plist'
        with mock.patch.dict(os.environ, {'ZOOK_CLAUDE_MDM': json.dumps([str(plist)])}):
            self.assertTrue(m.claude_hooks_allowed(policy, env={'CLAUDE_CONFIG_DIR': str(config)}))
            (config / 'remote-settings.json').write_text(json.dumps({'disableAllHooks': True}))  # the organization's server policy
            self.assertFalse(m.claude_hooks_allowed(policy, env={'CLAUDE_CONFIG_DIR': str(config)}))
            (config / 'remote-settings.json').unlink()
            plist.write_bytes(plistlib.dumps({'Settings': json.dumps({'allowManagedHooksOnly': True})}))  # a configuration profile
            self.assertFalse(m.claude_hooks_allowed(policy, env={'CLAUDE_CONFIG_DIR': str(config)}))
            plist.write_bytes(plistlib.dumps({'Settings': {'model': 'x'}}))
            self.assertTrue(m.claude_hooks_allowed(policy, env={'CLAUDE_CONFIG_DIR': str(config)}))
            plist.write_bytes(b'not a plist')
            self.assertFalse(m.claude_hooks_allowed(policy, env={'CLAUDE_CONFIG_DIR': str(config)}))

    def test_form_keeps_what_a_bot_set_itself(self):
        page = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))
        self.assertIn("const ownAccess = ACCESS.some(x => x.id === b.access) ? b.access : '';", page)
        self.assertIn("const featureChoice = key => b.features && key in b.features ? (b.features[key] ? 'on' : 'off') : '';", page)
        self.assertIn("return [{id: '', name: d.name + '（預設）', hint: d.hint || ''}, ...options]; };", page)  # a value equal to the default stays choosable
        self.assertIn('盡力攔下', page)  # the limit of reading commands is said plainly


class RoundThreeTest(unittest.TestCase):
    """Nothing automatic widens what a Bot may reach; reads are checked against real paths; one judgement of key files; billing checks."""
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.store = self.m.Store(self.root / 'data'); self.store.data['bots'].clear()
        self.store.data['settings'].update(permissionMode='bypass', access='full', autoModels=['codex', 'claude'])
        now = __import__('time').time()
        self.store.data['autoStatus'] = {p: dict(signedIn=True, billed=False, checkedAt=now) for p in ('codex', 'claude')}
        self.patches = [mock.patch.object(self.m, 'find_cli', return_value='/bin/true'), mock.patch.object(self.m, 'ability_on', return_value=True),
                        mock.patch.object(self.m, 'codex_default_model', return_value=''), mock.patch.object(self.m, 'log_activity')]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def test_matching_never_widens(self):
        m, store = self.m, self.store
        had = dict(id='a', name='a', provider='claude', account='', gateFull=True, autoAssigned=True, instructions='幫忙寫報告', permissionMode='bypass', access='full')
        after = dict(had, instructions='你是工程師，負責寫程式'); m.auto_on_edit(store, had, after, dict(instructions=after['instructions']))
        self.assertEqual((after['provider'], after.get('gateFull'), after['localLimit']), ('codex', None, True))  # moved off the gate: held in
        self.assertEqual((m.permission_mode(store, after, 'codex'), m.bot_scope(after, 'codex')), ('manual', ('workspace', '')))
        waiting = dict(id='b', name='b', provider='auto', persona='細心的分析師', autoPending=True); store.data['bots'].append(waiting)
        m.auto_retry(store)  # in the background, after a restore or at start
        self.assertEqual((waiting['provider'], waiting.get('gateFull'), waiting['localLimit']), ('claude', None, True))
        made = dict(id='c', name='c', provider='auto', persona='細心的分析師'); m.auto_on_create(store, made, grant=True)  # the user, here, now
        self.assertEqual((made['provider'], made['gateFull']), ('claude', True))
        restored = dict(id='d', name='d', provider='auto', persona='細心的分析師', localLimit=True); m.auto_on_create(store, restored, grant=True)
        self.assertNotIn('gateFull', restored)  # a limit from a restore lasts until the user changes it
        tool = dict(id='e', name='e', provider='claude'); m.hold_in(tool)
        self.assertEqual((tool.get('gateFull'), tool['localLimit']), (None, True))  # made by another Bot

    def test_claude_gets_the_whole_mac_only_after_its_hook_was_seen(self):
        m, store = self.m, self.store
        env = {'CLAUDE_CONFIG_DIR': str(self.root / 'claude')}; work = self.root / 'ws'
        bot = dict(id='a', provider='claude', account='')
        with mock.patch.object(m, 'provider_env', return_value=env):
            self.assertEqual(m.claude_scope(store, 'claude', bot, 'full', Path.home(), work), ('workspace', work))
            gate = m.claude_gate_env(store, dict(env), ['Read'], 'full', Path.home(), work)
            m.claude_gate_after(store, env, gate, used_tools=False)
            self.assertEqual(m.claude_scope(store, 'claude', bot, 'full', Path.home(), work), ('workspace', work))  # nothing seen yet
            Path(gate[0]).write_text('someone-else\n')  # another program writing the file is not this CLI's hook
            self.assertFalse(m.claude_gate_after(store, env, gate, used_tools=True))
            with open(gate[0], 'a') as f: f.write(gate[1] + ':start\n')  # Claude started: no tool was checked
            self.assertFalse(m.claude_gate_after(store, env, gate, used_tools=True))
            with open(gate[0], 'a') as f: f.write(gate[1] + ':tool\n')  # this CLI's own word, before a tool
            self.assertTrue(m.claude_gate_after(store, env, gate, used_tools=True))
            self.assertEqual(m.claude_scope(store, 'claude', bot, 'full', Path.home(), work)[0], 'full')
            self.assertFalse(m.claude_gate_after(store, env, gate, used_tools=True))  # the next turn of a kept CLI: an old line proves nothing
            self.assertEqual(m.claude_scope(store, 'claude', bot, 'full', Path.home(), work)[0], 'workspace')  # a tool ran without the hook: taken back
            other = m.claude_gate_env(store, dict(env), ['Read'], 'full', Path.home(), work)
            self.assertNotEqual((other[0], other[1]), (gate[0], gate[1]))  # every CLI start has its own file and word
        self.assertIn('SessionStart', json.loads(m.claude_gate_settings(600))['hooks'])
        files = [str(work / 'attachments/1a2b3c4d-報告.pdf')]
        env = {}; m.claude_gate_env(store, env, [], 'workspace', work, work, files)
        self.assertEqual((json.loads(env['ZOOK_GATE_ROOTS']), env['ZOOK_GATE_DEFER']), (files, '1'))  # this reply's files one by one, not the folder
        env = {}; m.claude_gate_env(store, env, ['Read'], 'full', Path.home(), work)
        self.assertNotIn('ZOOK_GATE_ROOTS', env)

    def test_records_say_who_allowed_and_whether_it_worked(self):
        m = self.m
        job = dict(approvals=[dict(name='zook_native_gate', status='approved', arguments=dict(toolUseId='t1')), dict(name='zook_native_gate', status='denied', arguments=dict(toolUseId='t2'))])
        a = m.native_record(job, dict(name='native_command', arguments={}, _ref='t1', status='completed'))
        b = m.native_record(job, dict(name='native_command', arguments={}, _ref='t3', status='completed'))
        c = m.native_record(job, dict(name='native_command', arguments={}, _ref='t2', status='denied'))
        self.assertEqual([(x['approvedBy'], x['autoApproved'], x['status']) for x in (a, b, c)], [('user', False, 'completed'), ('auto', True, 'completed'), ('auto', False, 'denied')])
        self.assertNotIn('_ref', a)
        page = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))
        self.assertIn("c.approvedBy === 'user' ? '你允許後完成'", page)

    def test_unwatched_sign_ins_are_asked_of_the_cli_before_use(self):
        m, store = self.m, self.store
        store.data['autoStatus']['claude']['checkedAt'] -= 120  # two minutes ago: Claude's sign-in may have changed in the Keychain since
        self.assertEqual(m.auto_billing_problem(store, 'claude', ''), '最近沒能確認是訂閱帳號')
        self.assertEqual(m.auto_billing_problem(store, 'codex', ''), '')
        store.data['autoStatus']['codex']['checkedAt'] -= 120
        self.assertEqual(m.auto_billing_problem(store, 'codex', ''), '')  # its sign-in file is watched: the usual ten minutes
        with mock.patch.object(m, 'auto_status', return_value=dict(signedIn=True, billed=True)):  # switched to Console billing
            m.auto_recheck(store, ['claude'])
        self.assertEqual(m.auto_billing_problem(store, 'claude', ''), 'API 計費不會被自動選用')
        with mock.patch.object(m, 'auto_status', return_value=dict(signedIn=None, billed=False)):  # the CLI could not say
            m.auto_recheck(store, ['claude'])
        self.assertTrue(m.auto_billing_problem(store, 'claude', ''))
        bot = dict(id='g', name='g', provider='claude', account='')
        self.assertEqual(m.intro_keys(store, bot), ['claude'])
        with mock.patch.object(m, 'auto_status', return_value=dict(signedIn=True, billed=False)) as asked:  # before every request: no cached answer
            m.auto_recheck_live(store, bot, 'claude', None); m.auto_recheck_live(store, bot, 'claude', None); m.auto_recheck_live(store, bot, 'codex', None)
        self.assertEqual(asked.call_count, 2)  # Claude each time; Codex's sign-in file is watched instead
        self.assertEqual(m.auto_billing_problem(store, 'claude', ''), '')
        self.assertLessEqual(m.AUTO_LIVE, 10)

    def test_billing_is_checked_again_when_a_sign_in_changes(self):
        m, store = self.m, self.store
        self.assertEqual(m.auto_billing_problem(store, 'codex', ''), '')
        m.auto_status_forget(store, 'codex')  # signing in or out in Zook
        self.assertEqual(m.auto_billing_problem(store, 'codex', ''), '最近沒能確認是訂閱帳號')
        self.assertEqual(m.auto_billing_problem(store, 'claude', ''), '')
        store.data['autoStatus']['claude']['signIn'] = [['/x', 1.0]]  # its sign-in files changed outside Zook since the check
        self.assertEqual(m.auto_billing_problem(store, 'claude', ''), '最近沒能確認是訂閱帳號')
        bot = dict(id='g', name='g', provider='codex', account='')
        self.assertEqual(m.intro_blocked(store, bot, 'codex', ''), '最近沒能確認是訂閱帳號')  # a greeting is a request too
        store.data['autoStatus']['codex'].update(checkedAt=__import__('time').time())
        store.data['autoStatus']['codex'].pop('signIn', None)
        self.assertEqual(m.intro_blocked(store, bot, 'codex', ''), '')

    def test_group_files_use_the_same_judgement(self):
        need = self.m.group_file_tool(self.store, 'g', runtime)[2]
        self.assertEqual((need({'name': 'credentials.json'}), need({'name': '.env'}), need({'name': '報告.md'})), ('always', 'always', False))

    def test_form_keeps_an_explicit_empty_backup_list(self):
        page = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'frontend/js').glob('*.js')))
        self.assertIn("b.fallbacks.length ? b.fallbacks[0] : '__none';", page)
        self.assertIn("{id: '__none', name: '不自動換'}, ...providerList()]", page)


class UploadNameTest(unittest.TestCase):
    def test_the_uploaded_name_is_kept_for_the_key_check(self):
        m = load(); temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        store = m.Store(Path(temp.name) / 'data')
        self.assertEqual((m.upload_name('.env'), m.upload_original('.env')), ('env', '.env'))
        uid = 'a' * 32; folder = store.dir / 'uploads' / uid; folder.mkdir(parents=True); (folder / 'file').write_text('K=1')
        (folder / 'meta.json').write_text(json.dumps(dict(id=uid, name='secrets', origName='prod.pem', size=3, kind='file')))
        placed = m.place_attachments(store, 'b1', m.attachments_for(store, [uid]))
        self.assertTrue(runtime.secret_name(str(placed[0])))  # known by its uploaded name
        self.assertTrue(json.loads((placed[0].parent.parent / '.zook-uploads.json').read_text())[placed[0].name] == 'prod.pem')
        self.assertEqual([p.name for p in placed[0].parent.iterdir()], [placed[0].name])  # nothing else among the attachments


class FinalReviewTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.store = self.m.Store(self.root / 'data')

    def tearDown(self): self.temp.cleanup()

    def test_the_upload_list_is_never_written_through(self):
        m, store = self.m, self.store
        work = store.dir / 'workspaces' / 'b1'; work.mkdir(parents=True)
        outside = self.root / 'outside.txt'; outside.write_text('keep me')
        os.link(str(outside), str(work / '.zook-uploads.json'))  # a second name for a file outside
        m.remember_uploaded_names(store, 'b1', {'1a2b3c4d-env': '.env'})
        self.assertEqual(outside.read_text(), 'keep me')
        self.assertEqual(json.loads((work / '.zook-uploads.json').read_text()), {'1a2b3c4d-env': '.env'})
        (work / '.zook-uploads.json').unlink(); (work / '.zook-uploads.json').symlink_to(outside)
        m.remember_uploaded_names(store, 'b1', {'x': 'y'}); self.assertEqual(outside.read_text(), 'keep me')
        self.assertFalse((work / '.zook-uploads.json').is_symlink())
        (work / '.zook-uploads.json').unlink(); os.mkfifo(str(work / '.zook-uploads.json'))
        done = __import__('threading').Thread(target=m.remember_uploaded_names, args=(store, 'b1', {'a': 'b'}), daemon=True); done.start(); done.join(5)
        self.assertFalse(done.is_alive())  # a pipe is never waited on
        self.assertEqual(zook_gate_names(work / 'attachments/x'), {'a': 'b'})
        self.assertEqual([p.name for p in work.iterdir()], ['.zook-uploads.json'])  # no leftover new file

    def test_group_files_keep_the_name_they_were_uploaded_with(self):
        m, store = self.m, self.store
        group = dict(id='g1', name='g', botIds=[], messages=[]); store.data['groups'].append(group)
        temp = self.root / 'up'; temp.write_text('K=secret')
        name = m.add_group_file(store, group, '.env', temp, 8, '你')
        self.assertEqual((name, group['fileInfo'][name]['origName']), ('env', '.env'))
        need = m.group_file_tool(store, 'g1', runtime)[2]
        self.assertEqual(need({'name': 'env'}), 'always')  # asked by the name it was uploaded with
        events = []
        s = runtime.RuntimeSession([], [], False, self.root, lambda *a: True, events.append, {'skills': [], 'mcp': []}, extra_tools=[m.group_file_tool(store, 'g1', runtime)])
        s.tools(); s.call('zook_group_file_read', {'name': 'env'}); s.close()
        self.assertNotIn('K=secret', json.dumps(events, ensure_ascii=False))
        page = (ROOT / 'backend/zook/groups.py').read_text(encoding='utf-8')
        self.assertIn("if k == 'origName'})  # the uploaded name stays known", page)  # a Bot saving the file back keeps it

    def test_a_reply_sent_again_is_checked_again(self):
        m, store = self.m, self.store
        bot = dict(id='b', name='b', provider='claude', account='', autoAssigned=True)
        job = dict(id='j', botId='b', status='running', messageId='x'); store.data['jobs'].append(job)
        with mock.patch.object(m, 'auto_status', return_value=dict(signedIn=True, billed=False)), mock.patch.object(m, 'find_cli', return_value='/bin/true'):
            self.assertTrue(m.billing_still_ok(store, 'j', bot, 'claude', None, True))
        with mock.patch.object(m, 'auto_status', return_value=dict(signedIn=True, billed=True)), mock.patch.object(m, 'find_cli', return_value='/bin/true'), \
             mock.patch.object(store, 'finish_message'):
            self.assertFalse(m.billing_still_ok(store, 'j', bot, 'claude', None, True))  # switched to API billing between the tries
        self.assertEqual(job['status'], 'failed'); self.assertIn('沒有重送', job['error'])
        self.assertTrue(m.billing_still_ok(store, 'j', dict(bot, autoAssigned=False), 'claude', None, False))
        app = (ROOT / 'backend/zook/app.py').read_text(encoding='utf-8')
        self.assertEqual(app.count('billing_still_ok(store, job_id, bot, p, a, fixed)'), 3)  # after a summary too, right before it is sent again


def zook_gate_names(path):
    import zook_gate
    return zook_gate._uploaded_names(str(path))


class CardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); (self.root / 'workspace').mkdir()
        self.asked, self.events = [], []
        self.session = runtime.RuntimeSession([], ['builtin:workspace'], False, self.root / 'workspace', lambda *a: self.asked.append(a) or True, self.events.append, {'skills': [], 'mcp': []})
        self.session.tools()

    def tearDown(self): self.session.close(); self.temp.cleanup()

    def test_one_card_every_action_and_no_command(self):
        ok = self.session.gate({'actions': [{'kind': 'delete', 'title': '刪除檔案 a.txt'}, {'kind': 'send', 'title': '對外送出 到 api.example.com'}], 'command': 'curl -H "x: SECRET"'})
        self.assertTrue(ok)
        args = self.asked[0][2]
        self.assertEqual(args, {'title': '刪除檔案 a.txt 等 2 件事', 'actions': [{'kind': 'delete', 'title': '刪除檔案 a.txt'}, {'kind': 'send', 'title': '對外送出 到 api.example.com'}]})
        self.assertNotIn('SECRET', json.dumps(self.events, ensure_ascii=False))
        for bad in ({'actions': []}, {'actions': [{'kind': 'rm', 'title': 'x'}]}, {'kind': 'delete', 'title': 'x'}, {'actions': [{'kind': 'delete'}]},
                    {'actions': [{'kind': 'delete', 'title': 'x%d' % i} for i in range(11)]}, {'actions': [{'kind': 'delete', 'title': '刪除檔案 ' + 'a' * 300}]}):
            self.assertFalse(self.session.gate(bad), bad)

    def test_workspace_write_never_reaches_cli_settings(self):
        for path in ('.cursor/hooks.json', '.claude/settings.json', 'sub/.grok/config.toml'):
            out = self.session.call('zook_workspace_write', {'path': path, 'content': '{}'})
            self.assertTrue(out.get('isError'), path)
        self.assertFalse((self.root / 'workspace/.cursor/hooks.json').exists())
        self.assertFalse(self.session.call('zook_workspace_write', {'path': '報告.md', 'content': 'ok'}).get('isError'))

    def test_workspace_keys_and_emptying_ask(self):
        (self.root / 'workspace/.env').write_text('KEY=1'); (self.root / 'workspace/報告.md').write_text('內容')
        s = self.session; s.permission_mode = lambda: 'bypass'
        self.assertEqual(s.classify('zook_workspace_read', {'path': '.env'}), 'danger')
        self.assertEqual(s.classify('zook_workspace_read', {'path': 'keys/id_ed25519'}), 'danger')
        self.assertEqual(s.classify('zook_workspace_read', {'path': '報告.md'}), 'read')
        self.assertEqual(s.classify('zook_workspace_write', {'path': '報告.md', 'content': '  '}), 'danger')
        self.assertEqual(s.classify('zook_workspace_write', {'path': '新的.md', 'content': ''}), 'internal')
        self.asked.clear(); s.call('zook_workspace_read', {'path': '.env'}); self.assertEqual(len(self.asked), 1)  # asked even when everything else is allowed
        self.assertEqual(s.classify('zook_workspace_write', {'path': '.env', 'content': 'KEY=2'}), 'danger')  # writing keys asks too
        self.asked.clear(); self.events.clear(); s.call('zook_workspace_write', {'path': '.env', 'content': 'KEY=hunter2'}); s.call('zook_workspace_read', {'path': '.env'})
        self.assertEqual(len(self.asked), 2)
        self.assertNotIn('hunter2', json.dumps(self.events, ensure_ascii=False))  # the record keeps the action and the file name only
        self.assertEqual({tuple(e['arguments']) for e in self.events}, {('path',)})
        tool = __import__('importlib').util  # the group's shared files use the same judgement
        self.assertTrue(runtime.secret_name('credentials.json')); self.assertTrue(runtime.secret_name('a/.env.local')); self.assertFalse(runtime.secret_name('報告.md'))
        (self.root / 'workspace/attachments').mkdir(); (self.root / 'workspace/attachments/1a2b3c4d-credentials.json').write_text('{"k": "hunter3"}')
        self.assertEqual(s.classify('zook_workspace_read', {'path': 'attachments/1a2b3c4d-credentials.json'}), 'danger')  # by the name it was uploaded with
        (self.root / 'workspace/notes.txt').symlink_to(self.root / 'workspace/.env')
        self.assertEqual(s.classify('zook_workspace_read', {'path': 'notes.txt'}), 'danger')  # by what the link really is
        self.events.clear(); s.call('zook_workspace_read', {'path': 'attachments/1a2b3c4d-credentials.json'})
        self.assertNotIn('hunter3', json.dumps(self.events, ensure_ascii=False))  # the record is masked by the same judgement

    def test_workspace_tools_reach_only_this_replys_attachments(self):
        box = self.root / 'workspace/attachments'; box.mkdir(); (box / 'mine.txt').write_text('mine'); (box / 'other.txt').write_text('other chat')
        (self.root / 'workspace/報告.md').write_text('work')
        s = self.session; s.permission_mode = 'bypass'; s.attachment_files = [str(box / 'mine.txt')]
        self.assertFalse(s.call('zook_workspace_read', {'path': 'attachments/mine.txt'}).get('isError'))
        self.assertTrue(s.call('zook_workspace_read', {'path': 'attachments/other.txt'}).get('isError'))
        self.assertFalse(s.call('zook_workspace_read', {'path': '報告.md'}).get('isError'))  # the Bot's own work stays readable
        listed = json.loads(s.call('zook_workspace_list', {'path': 'attachments'})['content'][0]['text'])['entries']
        self.assertEqual([e['name'] for e in listed], ['mine.txt'])
        self.assertTrue(s.call('zook_workspace_read', {'path': 'ATTACHMENTS/other.txt'}).get('isError'))  # the disk ignores case, and so does the check
        self.assertFalse(s.call('zook_workspace_read', {'path': 'Attachments/MINE.txt'}).get('isError'))  # the same file, by the file itself


if __name__ == '__main__': unittest.main()
