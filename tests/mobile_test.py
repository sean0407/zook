# -*- coding: utf-8 -*-
import importlib.util, pathlib, tempfile, unittest

spec = importlib.util.spec_from_file_location('zook_mobile', pathlib.Path(__file__).parents[1] / 'backend/server.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class MobileViewsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = m.Store(pathlib.Path(self.tmp.name)); d = self.store.data
        self.bot = d['bots'][0]; other = d['bots'][1]
        self.bot['messages'] = [dict(id='u1', role='user', content='你好', createdAt='t1'), dict(id='a1', role='assistant', content='嗨\n第二行', status='completed', createdAt='t2', note='這次改用 Claude（Codex 額度已用完）')]
        d['groups'].append(dict(id='g1', name='研究室', botIds=[self.bot['id'], other['id']], status='running', messages=[dict(id='m1', role='assistant', botId=other['id'], content='我的看法', createdAt='t3')]))
        d['jobs'] += [
            dict(id='j1', botId=self.bot['id'], status='running', messageId='a1', approvals=[dict(id='ap1', status='pending', category='internal', name='zook_create_bot', arguments={'name': '詩人'})],
                 toolCalls=[dict(id='c1', name='web_search', arguments={'query': 'BTC'}, status='completed'), dict(id='c2', name='zook_create_bot', arguments={'name': '詩人'}, status='waiting_approval')]),
            dict(id='j2', botId=other['id'], groupId='g1', status='running', messageId='m1', approvals=[], toolCalls=[dict(id='c3', name='native_write', arguments={'path': '/w/report.md'}, status='completed')]),
            dict(id='j3', botId=self.bot['id'], status='failed', messageId='x', approvals=[dict(id='old', status='pending', name='zook_remember', arguments={})],
                 toolCalls=[dict(id='c4', name='native_command', arguments={'command': 'ls'}, status='running')])]

    def tearDown(self): self.tmp.cleanup()

    def test_home_lists_previews_without_conversations(self):
        home = m.mobile_home(self.store); bot = next(b for b in home['bots'] if b['id'] == self.bot['id'])
        self.assertEqual((bot['preview'], bot['running'], bot['pending']), ('嗨 第二行', True, 1))
        self.assertNotIn('messages', bot); self.assertNotIn('persona', bot)
        self.assertEqual((home['groups'][0]['name'], home['groups'][0]['running'], home['groups'][0]['preview']), ('研究室', True, '我的看法'))
        self.assertEqual(home['pending'], 1)   # the approval of the job that already ended is not counted

    def test_bot_view_has_messages_approvals_and_plain_activity(self):
        view = m.mobile_bot(self.store, self.bot)
        self.assertEqual([x['content'] for x in view['messages']], ['你好', '嗨\n第二行']); self.assertIn('改用 Claude', view['messages'][1]['note'])
        self.assertEqual(view['approvals'], [dict(id='ap1', jobId='j1', botId=self.bot['id'], botName=self.bot['name'], category='internal', text=self.bot['name'] + ' 想要新增 Bot「詩人」')])
        texts = {a['text']: a['state'] for a in view['activity']}
        self.assertEqual(texts, {'上網搜尋「BTC」': 'done', '新增 Bot「詩人」': 'waiting', '在工作資料夾執行指令': 'failed'})   # no command text; an unfinished step of an ended reply is failed
        self.assertTrue(view['running']); self.assertEqual(view['activeJobId'], 'j1')

    def test_group_view_and_group_work_shows_in_the_bots_own_activity(self):
        group = m.mobile_group(self.store, self.store.data['groups'][0])
        self.assertEqual((group['messages'][0]['botName'], group['running'], group['speaking']), (self.store.data['bots'][1]['name'], True, [self.store.data['bots'][1]['name']]))
        other = m.mobile_bot(self.store, self.store.data['bots'][1])
        self.assertEqual([(a['text'], a.get('where')) for a in other['activity']], [('修改檔案「report.md」', '研究室')])

    def test_devices_may_read_these_views(self):
        for path in ('/api/mobile/home', '/api/mobile/bots/abc', '/api/mobile/groups/abc'): self.assertTrue(m.device_may('GET', path))
        self.assertFalse(m.device_may('POST', '/api/mobile/home'))

    def test_access_scope_is_per_bot_defaults_to_the_whole_mac_and_cannot_be_set_from_the_phone(self):
        ws = pathlib.Path(self.tmp.name) / 'ws'; ws.mkdir(); bot = dict(self.bot)
        self.assertEqual(m.bot_access(bot, ws), ('full', pathlib.Path.home()))          # nothing chosen yet: like using the CLI directly
        m.update(bot, {'access': 'workspace'}, 'bot'); self.assertEqual(m.bot_access(bot, ws), ('workspace', ws))
        m.update(bot, {'access': 'folder', 'accessFolder': self.tmp.name}, 'bot')
        self.assertEqual(m.bot_access(bot, ws), ('folder', pathlib.Path(self.tmp.name).resolve()))
        for bad in ({'access': 'everything'}, {'access': 'folder', 'accessFolder': ''}, {'access': 'folder', 'accessFolder': 'relative/dir'}, {'access': 'folder', 'accessFolder': self.tmp.name + '/missing'}):
            with self.assertRaises(ValueError): m.update(dict(self.bot), bad, 'bot')
        m.update(bot, {'access': 'full'}, 'bot'); self.assertEqual(bot['accessFolder'], '')
        gone = dict(self.bot, access='folder', accessFolder=self.tmp.name + '/missing')
        with self.assertRaises(RuntimeError): m.bot_access(gone, ws)                      # a missing folder stops the Bot instead of widening its reach
        self.assertFalse(m.device_may('POST', '/api/choose-folder')); self.assertFalse(m.device_may('PATCH', '/api/bots/' + self.bot['id']))
        made = m.mobile_create_bot(self.store, dict(name='手機 Bot', access='workspace', accessFolder='/'))
        self.assertEqual((made['access'], made['localLimit']), ('workspace', True)); self.assertNotIn('accessFolder', made)  # held in until the Mac widens it
        self.assertIn('Desktop', m.access_note('full', pathlib.Path.home(), True)); self.assertIn(self.tmp.name, m.access_note('folder', self.tmp.name, False))

    def test_plain_clis_get_their_own_run_everything_switch_only_with_the_whole_mac(self):
        spec = dict(m.P.CATALOG['gemini'], command='/bin/echo')
        self.assertIn('--yolo', m.P.command_args(spec, '/tmp/p', 'hi', '', full=True)[0])
        self.assertNotIn('--yolo', m.P.command_args(spec, '/tmp/p', 'hi', '')[0])
        self.assertEqual(m.P.command_args(dict(command='/bin/echo', args='{prompt}'), '/tmp/p', 'hi', '', full=True)[0], ['/bin/echo', 'hi'])   # a custom CLI keeps exactly the arguments the user wrote

    def test_settings_view_is_read_only_and_has_no_secrets(self):
        inventory = dict(mcp=[dict(id='builtin:workspace', name='Bot workspace'), dict(id='m1', name='Gmail', env={'TOKEN': 'secret-xyz'})], skills=[dict(id='s1', name='docx')])
        self.store.data['settings']['sharedMcp'] = ['m1']; self.store.data['remoteDevices'] = [dict(id='d1', name='iPhone', publicKey='PUBKEY', lastSeenAt='t')]
        view = m.mobile_settings(self.store, inventory)
        self.assertEqual([(c['name'], c['on']) for c in view['connectors']], [('Bot 工作區', False), ('Gmail', True)])
        self.assertEqual(view['skills'], [dict(id='s1', name='docx', on=True)]); self.assertEqual(view['devices'], [dict(id='d1', name='iPhone', lastSeenAt='t')])
        self.assertNotIn('secret-xyz', str(view)); self.assertNotIn('PUBKEY', str(view))
        self.assertTrue(m.device_may('GET', '/api/mobile/settings')); self.assertFalse(m.device_may('POST', '/api/mobile/settings'))

    def test_phone_can_add_a_bot_but_only_sets_name_instructions_and_provider(self):
        self.assertTrue(m.device_may('POST', '/api/mobile/bots')); self.assertFalse(m.device_may('POST', '/api/bots')); self.assertFalse(m.device_may('DELETE', '/api/mobile/bots'))
        before = len(self.store.data['bots'])
        bot = m.mobile_create_bot(self.store, dict(name='  詩人 ', instructions='寫詩', enabledMcp=['x'], allowCommands=False, permissionMode='auto', persona='p'))
        self.assertEqual((bot['name'], bot['instructions'], bot['provider'], bot['enabledMcp'], bot['allowCommands'], bot['persona']), ('詩人', '寫詩', '', [], True, ''))
        self.assertEqual((bot['permissionMode'], bot['localLimit']), ('manual', True)); self.assertEqual(len(self.store.data['bots']), before + 1)
        looks = m.mobile_create_bot(self.store, dict(name='紅心', color='#FF284B', shape='8')); self.assertEqual((looks['color'], looks['shape']), ('#ff284b', '8'))
        for bad in ({'name': 'x', 'color': 'red'}, {'name': 'x', 'color': '#12345'}, {'name': 'x', 'shape': '13'}, {'name': 'x', 'shape': 'url(x)'}):
            with self.assertRaises(ValueError): m.mobile_create_bot(self.store, bad)
        self.store.data['bots'].remove(looks)
        self.assertIn('詩人', [b['name'] for b in m.mobile_home(self.store)['bots']])
        for bad in ({}, {'name': '   '}, {'name': 'x' * 101}, {'name': '好', 'instructions': 5}):
            with self.assertRaises(ValueError): m.mobile_create_bot(self.store, bad)
        self.assertEqual(len(self.store.data['bots']), before + 1)


if __name__ == '__main__': unittest.main()


class MobileScheduleApprovalTest(unittest.TestCase):
    def test_phone_card_spells_out_the_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = m.Store(pathlib.Path(tmp)); bot = store.data['bots'][0]
            text = '建立排程：每天 10:00，在「%s」執行「提醒我喝水」' % bot['name']
            store.data['jobs'].append(dict(id='j', botId=bot['id'], status='running', messageId='x', toolCalls=[],
                                           approvals=[dict(id='a', status='pending', category='danger', name='zook_create_schedule', arguments={'content': '提醒我喝水'}, text=text)]))
            self.assertEqual(m.mobile_bot(store, bot)['approvals'][0]['text'], bot['name'] + ' 想要' + text)
