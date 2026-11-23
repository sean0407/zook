# -*- coding: utf-8 -*-
import base64, importlib.util, pathlib, tempfile, unittest

spec = importlib.util.spec_from_file_location('zook_mobile_more', pathlib.Path(__file__).resolve().parents[1] / 'backend/server.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
JPEG = b'\xff\xd8\xff\xe0' + b'0' * 200


class MobileMore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = m.Store(pathlib.Path(self.tmp.name)); self.bot = self.store.data['bots'][0]
        self.store.data['schedules'].append(dict(id='s1', botId=self.bot['id'], content='每天整理信件', time='09:00', repeat='daily', on=True))

    def tearDown(self): self.tmp.cleanup()

    def test_phone_routes_are_limited(self):
        allowed = [('GET', '/api/mobile/schedules'), ('POST', '/api/mobile/schedules/s1'), ('POST', '/api/mobile/photos'), ('POST', '/api/mobile/bots/b1/chats'), ('GET', '/api/notifications')]
        refused = [('POST', '/api/schedules'), ('PATCH', '/api/schedules/s1'), ('DELETE', '/api/schedules/s1'), ('POST', '/api/uploads'), ('GET', '/api/bots/b1/outputs'), ('GET', '/api/bots/b1/outputs/x'),
                   ('POST', '/api/google'), ('POST', '/api/connectors/c1/login'), ('GET', '/api/groups/g1/files')]
        for method, path in allowed: self.assertTrue(m.device_may(method, path), path)
        for method, path in refused: self.assertFalse(m.device_may(method, path), path)

    def test_schedules_can_be_paused_resumed_and_deleted_only(self):
        view = m.mobile_schedules(self.store)['schedules'][0]; self.assertEqual((view['content'], view['on'], view['target']), ('每天整理信件', True, self.bot['name']))
        m.mobile_schedule_action(self.store, 's1', 'pause'); self.assertFalse(self.store.data['schedules'][0]['on'])
        self.assertRaises(ValueError, m.mobile_schedule_action, self.store, 's1', 'resume'); self.assertFalse(self.store.data['schedules'][0]['on'])  # turned on again only on the Mac
        self.assertRaises(ValueError, m.mobile_schedule_action, self.store, 's1', 'edit'); self.assertRaises(LookupError, m.mobile_schedule_action, self.store, 'nope', 'pause')
        m.mobile_schedule_action(self.store, 's1', 'delete'); self.assertEqual(self.store.data['schedules'], [])

    def test_photos_must_be_small_images(self):
        meta = m.mobile_photo(self.store, {'data': base64.b64encode(JPEG).decode()}); self.assertEqual(meta['kind'], 'image'); self.assertTrue(meta['name'].endswith('.jpg'))
        self.assertEqual(m.attachments_for(self.store, [meta['id']])[0]['size'], len(JPEG))
        for bad in ({'data': base64.b64encode(b'#!/bin/sh').decode()}, {'data': 'not base64!'}, {'data': base64.b64encode(JPEG + b'0' * m.MOBILE_PHOTO_BYTES).decode()}, {}):
            self.assertRaises(ValueError, m.mobile_photo, self.store, bad)

    def test_switching_conversations(self):
        self.bot['messages'] = [dict(id='u1', role='user', content='第一段', createdAt='t1')]; m.ensure_chats(self.bot); first = self.bot['chatId']
        m.mobile_chat_switch(self.store, self.bot, {'new': True}); self.assertNotEqual(self.bot['chatId'], first); self.assertEqual(self.bot['messages'], [])
        chats = m.mobile_bot(self.store, self.bot)['chats']; self.assertEqual(len(chats), 2); self.assertEqual(sum(c['open'] for c in chats), 1)
        m.mobile_chat_switch(self.store, self.bot, {'chatId': first}); self.assertEqual(self.bot['messages'][0]['content'], '第一段')
        self.assertRaises(ValueError, m.mobile_chat_switch, self.store, self.bot, {'chatId': 'nope'})
        self.store.data['jobs'].append(dict(id='j', botId=self.bot['id'], status='running')); self.assertRaises(RuntimeError, m.mobile_chat_switch, self.store, self.bot, {'new': True})

    def test_phone_sees_no_secrets_in_its_views(self):
        self.store.data['settings']['google'] = dict(secretId='a' * 32, clientId='cid', email='me@example.com')
        text = repr(m.mobile_home(self.store)) + repr(m.mobile_bot(self.store, self.bot)) + repr(m.mobile_schedules(self.store))
        self.assertNotIn('secretId', text); self.assertNotIn('a' * 32, text)


if __name__ == '__main__': unittest.main()
