# -*- coding: utf-8 -*-
"""Conversations live in their own files: moving older data over, saving only what changed, and what happens when a file is lost."""
import copy, gzip, importlib.util, json, os, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_chatfiles', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def msgs(prefix, n): return [dict(id='%s%d' % (prefix, i), role='user' if i % 2 == 0 else 'assistant', content='%s 第 %d 則' % (prefix, i), status='completed', createdAt='2026-11-01T00:00:%02d+00:00' % i) for i in range(n)]


def old_data():
    """Data as Zook wrote it before: every conversation inside the one file."""
    return dict(bots=[dict(id='b1', name='甲', chatId='c2', messages=msgs('b1c2-', 4), chats=[dict(id='c1', title='舊對話', messages=msgs('b1c1-', 3)), dict(id='c2', title='現在的對話')]),
                      dict(id='b2', name='乙', chatId='c9', messages=msgs('b2c9-', 2), chats=[dict(id='c9', title='唯一')])],
                groups=[dict(id='g1', name='群組', botIds=['b1', 'b2'], status='idle', messages=msgs('g1-', 5))],
                deletedBots=[dict(id='b0', name='已刪除', chatId='cx', messages=msgs('b0-', 2), chats=[dict(id='cx', title='留著')]), dict(id='b9', name='很久以前刪除的', messages=msgs('b9-', 2))],
                jobs=[], settings=dict(onboarded=True, trashSeeded=True), knowledge=[], memories=[], schedules=[], skills=[], connectors=[], accounts=[])


def talk(m, store):
    """Every conversation with its messages, however the data is stored."""
    return {key: copy.deepcopy(messages) for key, rel, messages, _ in m.chat_conversations(store.data)}


class ChatFilesTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.dir = Path(self.temp.name) / 'data'; self.dir.mkdir()
        self.main = self.dir / 'swarmr.json'; self.main.write_text(json.dumps(old_data(), ensure_ascii=False), encoding='utf-8')
        self.want = {('b1', 'c1'): msgs('b1c1-', 3), ('b1', 'c2'): msgs('b1c2-', 4), ('b2', 'c9'): msgs('b2c9-', 2), ('b0', 'cx'): msgs('b0-', 2), ('b9', 'main'): msgs('b9-', 2), ('g1', ''): msgs('g1-', 5)}

    def tearDown(self): self.temp.cleanup()

    def open(self): return self.m.Store(self.dir)
    def file(self, rel): return self.dir / 'chats' / rel
    def on_disk(self): return json.loads(self.main.read_text(encoding='utf-8'))

    def test_older_data_is_moved_into_files_and_nothing_changes(self):
        store = self.open()
        self.assertEqual(talk(self.m, store), self.want)
        main = self.on_disk()
        self.assertEqual(main['layout'], 2); self.assertNotIn('第', self.main.read_text(encoding='utf-8'))  # no message is left in the main file
        self.assertEqual([c['stored'] for c in main['bots'][0]['chats']], [3, 4]); self.assertEqual(main['groups'][0]['stored'], 5)
        self.assertEqual(sorted(str(p.relative_to(self.dir / 'chats')) for p in (self.dir / 'chats').rglob('*.json')), ['b0/cx.json', 'b1/c1.json', 'b1/c2.json', 'b2/c9.json', 'b9/main.json', 'group.g1.json'])
        self.assertEqual(json.loads(self.file('b1/c1.json').read_text(encoding='utf-8'))['messages'], msgs('b1c1-', 3))
        self.assertEqual(json.loads((self.dir / 'swarmr-before-split.json').read_text(encoding='utf-8'))['bots'][0]['messages'], msgs('b1c2-', 4))  # the data as it was is kept
        self.assertEqual(len(list((self.dir / 'backups').glob('zook-safety-*.json.gz'))), 1)
        self.assertNotIn('layout', store.data); self.assertNotIn('stored', store.data['groups'][0])
        again = self.open()
        self.assertEqual(talk(self.m, again), self.want); self.assertEqual(len(list((self.dir / 'backups').glob('zook-safety-*'))), 1)  # opening again moves nothing

    def test_only_the_conversation_that_changed_is_written(self):
        store = self.open()
        before = {p: p.stat().st_ino for p in (self.dir / 'chats').rglob('*.json')}
        store.data['jobs'].append(dict(id='j', botId='b1', chatId='c2', messageId='none', status='running'))
        store.data['bots'][0]['messages'].append(dict(id='new', role='user', content='新訊息', status='completed'))
        with mock.patch.object(self.m, 'chat_strip', wraps=self.m.chat_strip) as strip:
            store.save(); self.assertEqual(strip.call_count, 1)
        changed = [str(p.relative_to(self.dir / 'chats')) for p, ino in before.items() if p.stat().st_ino != ino]
        self.assertEqual(changed, ['b1/c2.json'])
        self.assertEqual(talk(self.m, self.open())[('b1', 'c2')][-1]['content'], '新訊息')

    def test_a_reply_being_written_is_checked_in_full(self):
        store = self.open(); store.data['jobs'].append(dict(id='j', botId='b1', chatId='c2', messageId='none', status='running')); store.save()
        store.data['bots'][0]['messages'][0]['effort'] = 'deep'; store.data['bots'][0]['messages'][0].pop('createdAt')  # same length, same text: only a full look sees it
        store.save()
        self.assertEqual(self.open().data['bots'][0]['messages'][0].get('effort'), 'deep')

    def test_a_change_nobody_announced_is_still_saved(self):
        store = self.open(); count = lambda rel: len(json.loads(self.file(rel).read_text(encoding='utf-8'))['messages'])
        store.data['groups'][0]['messages'].append(dict(id='late', role='assistant', content='沒人通知的一則', status='completed'))
        store._chat_swept = time.monotonic(); store.save()
        self.assertEqual(count('group.g1.json'), 6)  # a message more or less is seen at every save
        store.data['groups'][0]['messages'][0]['content'] = '原地改寫'; store._chat_swept = time.monotonic(); store.save()
        self.assertNotIn('原地改寫', self.file('group.g1.json').read_text(encoding='utf-8'))  # a rewrite in place waits for the regular look
        store._chat_swept = time.monotonic() - 61; store.save()
        self.assertIn('原地改寫', self.file('group.g1.json').read_text(encoding='utf-8'))
        store.data['bots'][1]['messages'][0]['effort'] = 'deep'; store.data['bots'][1]['messages'][0].pop('createdAt')
        store._chat_swept = time.monotonic(); store.chat_touch('b2'); store.save()
        self.assertIn('deep', self.file('b2/c9.json').read_text(encoding='utf-8'))  # an owner a request named is compared in full

    def test_missing_main_file_does_not_cost_the_conversations(self):
        store = self.open(); name = self.m.backup_write(store, 'manual', store.data)
        store.data['bots'][0]['messages'].append(dict(id='newer', role='user', content='備份之後才說的', status='completed')); store.save(everything=True)
        self.main.unlink()
        store = self.open(); got = talk(self.m, store)
        self.assertTrue(store.data['settings']['recovered']['backup'].startswith('zook-')); self.assertEqual(got[('b1', 'c2')][-1]['content'], '備份之後才說的')
        self.assertEqual(got[('g1', '')], self.want[('g1', '')])
        # With no backup at all nothing can be listed, but every file is still on disk.
        for p in (self.dir / 'backups').glob('zook-*'): p.unlink()
        self.main.unlink(); store = self.open()
        aside = [p for p in self.dir.iterdir() if p.name.startswith('chats.unlisted-')]
        self.assertEqual(len(aside), 1); self.assertEqual(len(list(aside[0].rglob('*.json'))), 6)

    def test_an_older_main_file_put_back_by_hand_keeps_the_newer_conversations(self):
        self.open(); stale = self.main.read_bytes()
        store = self.open(); bot = store.data['bots'][0]
        bot['chats'].append(dict(id='c3', title='之後才開的', createdAt='2026-11-02T00:00:00+00:00', updatedAt='2026-11-02T00:00:00+00:00', messages=[dict(id='n1', role='user', content='之後才開的對話', status='completed')]))
        store.data['bots'].append(dict(id='b7', name='之後才有的 Bot', chatId='k', messages=msgs('b7-', 2), chats=[dict(id='k', title='x')])); store.save(everything=True)
        self.main.write_bytes(stale)
        store = self.open(); got = talk(self.m, store)
        self.assertEqual(got[('b1', 'c3')][0]['content'], '之後才開的對話')  # put back into its Bot
        aside = [p for p in self.dir.iterdir() if p.name.startswith('chats.unlisted-')]
        self.assertTrue((aside[0] / 'b7' / 'k.json').exists())  # and the unknown Bot's file is moved aside, not deleted

    def test_a_bot_listed_twice_keeps_the_live_conversation(self):
        data = old_data(); data['deletedBots'].append(dict(id='b1', name='甲（舊）', chatId='c2', messages=msgs('stale-', 9), chats=[dict(id='c2', title='舊')]))
        self.main.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        store = self.open()
        self.assertEqual(talk(self.m, store)[('b1', 'c2')], self.want[('b1', 'c2')]); self.assertEqual([b['id'] for b in store.data['deletedBots']].count('b1'), 1)
        store.data['bots'][0]['messages'].append(dict(id='x', role='user', content='活著的 Bot 說的', status='completed')); store.save(everything=True)
        again = self.open()
        self.assertEqual(talk(self.m, again)[('b1', 'c2')][-1]['content'], '活著的 Bot 說的'); self.assertNotIn('b1', [b['id'] for b in again.data['deletedBots']])

    def test_main_file_without_conversations_is_not_taken_for_a_backup(self):
        store = self.open(); app = mock.Mock(store=store)
        self.assertRaises(ValueError, self.m.backup_check, self.on_disk())
        plain = 'zook-auto-20200101-000000.json'; (self.dir / 'backups' / plain).write_text(self.main.read_text(encoding='utf-8'), encoding='utf-8')  # what an older Zook would write as its daily copy of this data
        self.assertRaises(ValueError, self.m.backup_restore, app, plain)
        self.assertEqual(talk(self.m, store), self.want); self.assertEqual(talk(self.m, self.open()), self.want)

    def test_restore_that_fails_changes_nothing(self):
        store = self.open(); app = mock.Mock(store=store)
        store.data['bots'][0]['messages'].append(dict(id='mine', role='user', content='還原失敗後還要在', status='completed')); store.save(everything=True)
        want = talk(self.m, store); main = self.main.read_bytes()
        name = 'zook-manual-20200101-000000.json'; (self.dir / 'backups' / name).write_text(json.dumps(old_data(), ensure_ascii=False), encoding='utf-8')
        real = self.m.Store.save_chats
        def fail_late(this, everything=False):
            if this is not store: raise OSError('disk full')
            return real(this, everything)
        with mock.patch.object(self.m.Store, 'save_chats', fail_late):
            self.assertRaises(ValueError, self.m.backup_restore, app, name)
        unsaved = lambda raw: dict(json.loads(raw), savedAt=None)  # only the time of the last save may differ (resume.py reads it)
        self.assertEqual(unsaved(self.main.read_bytes()), unsaved(main)); self.assertEqual(talk(self.m, store), want)
        self.assertFalse((self.dir / 'chats.old').exists())
        self.assertEqual(talk(self.m, self.open()), want)
        bad = old_data(); bad['bots'][0]['messages'][0]['content'] = ['not', 'text']  # a file from elsewhere with a field of the wrong kind
        (self.dir / 'backups' / name).write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')
        self.assertRaises(ValueError, self.m.backup_restore, app, name); self.assertEqual(talk(self.m, self.open()), want)

    def test_one_file_that_cannot_be_written_does_not_stop_the_rest(self):
        store = self.open()
        self.file('b2/c9.json').unlink(); self.file('b2/c9.json').mkdir()  # something is in the way
        store.data['bots'][1]['messages'].append(dict(id='stuck', role='user', content='寫不進去', status='completed'))
        store.data['bots'][0]['messages'].append(dict(id='fine', role='user', content='照常寫入', status='completed'))
        store.data['settings']['rules'] = '主檔照常存'
        store.save()
        self.assertEqual(self.on_disk()['settings']['rules'], '主檔照常存'); self.assertIn('照常寫入', self.file('b1/c2.json').read_text(encoding='utf-8'))
        self.file('b2/c9.json').rmdir(); store.save()
        self.assertIn('寫不進去', self.file('b2/c9.json').read_text(encoding='utf-8'))  # tried again, and it went through

    def test_deleted_conversations_lose_their_files_and_a_kept_bot_does_not(self):
        store = self.open(); bot = store.data['bots'][0]
        bot['chats'] = [c for c in bot['chats'] if c['id'] != 'c1']; store.chat_touch('b1'); store.save()
        self.assertFalse(self.file('b1/c1.json').exists()); self.assertTrue(self.file('b1/c2.json').exists())
        self.m.trash_bot(store, store.data['bots'][1]); store.data['bots'].pop(1); store.chat_touch('b2'); store.save()
        self.assertTrue(self.file('b2/c9.json').exists())  # kept aside, so its conversation stays
        store.data['groups'].clear(); store.chat_touch('g1'); store.save()
        self.assertFalse(self.file('group.g1.json').exists())
        store.data['deletedBots'].clear(); store.save(everything=True)
        self.assertEqual(sorted(p.name for p in (self.dir / 'chats').iterdir()), ['b1'])

    def test_stopping_halfway_through_the_move_loses_nothing(self):
        raw = self.main.read_bytes()
        # 1. stopped while the files were being written
        (self.dir / 'chats.new').mkdir(); (self.dir / 'chats.new' / 'half.json').write_text('{"mess')
        self.assertEqual(talk(self.m, self.open()), self.want); self.assertFalse((self.dir / 'chats.new').exists())
        # 2. stopped after the files were in place but before the main file changed form
        self.main.write_bytes(raw); self.file('b1/c2.json').write_text(json.dumps(dict(owner='b1', id='c2', messages=msgs('wrong-', 9))))
        self.assertEqual(talk(self.m, self.open()), self.want)  # the main file still had everything, so it decides
        # 3. the main file cannot be written at the last step
        self.main.write_bytes(raw)
        import shutil; shutil.rmtree(str(self.dir / 'chats'))
        with mock.patch.object(self.m.Store, 'save_main', side_effect=OSError('disk full')):
            self.assertRaises(OSError, self.open)
        self.assertEqual(self.main.read_bytes(), raw); self.assertFalse((self.dir / 'chats').exists()); self.assertFalse((self.dir / 'chats.new').exists())
        self.assertEqual(talk(self.m, self.open()), self.want)

    def test_one_damaged_file_only_costs_that_conversation(self):
        store = self.open(); self.m.backup_write(store, 'manual', store.data)
        store.data['bots'][0]['chats'][0]['messages'].append(dict(id='after', role='user', content='備份之後', status='completed')); store.save(everything=True)
        self.file('b1/c1.json').write_text('{"owner": "b1", "id": "c1", "messa'); self.file('b2/c9.json').unlink()
        (self.dir / 'backups').joinpath(next(p.name for p in (self.dir / 'backups').glob('zook-safety-*'))).unlink()
        store = self.open(); got = talk(self.m, store)
        self.assertEqual(got[('b1', 'c2')], self.want[('b1', 'c2')]); self.assertEqual(got[('g1', '')], self.want[('g1', '')])  # the others are untouched
        self.assertEqual(got[('b1', 'c1')], self.want[('b1', 'c1')]); self.assertEqual(got[('b2', 'c9')], self.want[('b2', 'c9')])  # these two come from the backup
        note = store.data['settings']['recovered']
        self.assertTrue(note['chatsOnly']); self.assertEqual(sorted(c['name'] for c in note['chats']), ['乙 · 唯一', '甲 · 舊對話']); self.assertTrue(all(c['backup'].startswith('zook-manual-') for c in note['chats']))
        self.assertTrue((self.dir / 'chats/b1/c1.json.damaged').exists())
        self.assertEqual(talk(self.m, self.open())[('b1', 'c1')], self.want[('b1', 'c1')])  # and it was written back
        # Without any backup the conversation is empty and the user is told so.
        for p in (self.dir / 'backups').glob('zook-*'): p.unlink()
        self.file('group.g1.json').write_text('[]')
        store = self.open()
        self.assertEqual(talk(self.m, store)[('g1', '')], []); self.assertEqual([(c['name'], c['backup']) for c in store.data['settings']['recovered']['chats']], [('群組', '')])

    def test_damaged_main_file_keeps_the_newer_conversations(self):
        store = self.open(); name = self.m.backup_write(store, 'manual', store.data)
        bot = store.data['bots'][0]
        bot['messages'].append(dict(id='newer', role='user', content='備份之後才說的', status='completed'))
        bot['chats'].append(dict(id='c3', title='備份之後才開的', createdAt='2026-11-02T00:00:00+00:00', updatedAt='2026-11-02T00:00:00+00:00', messages=[dict(id='n1', role='user', content='新對話的第一句', status='completed', createdAt='2026-11-02T00:00:00+00:00')]))
        store.data['bots'].append(dict(id='b7', name='備份之後才有的 Bot', chatId='k', messages=msgs('b7-', 2), chats=[dict(id='k', title='x')]))
        store.save(everything=True)
        self.main.write_bytes(b'{"bots": [{"id": "b1", "na')
        store = self.open(); got = talk(self.m, store); note = store.data['settings']['recovered']
        self.assertTrue(note['backup'].startswith('zook-')); self.assertEqual((note['chatsKept'], note['adopted']), (True, 1))  # (the copy made at the move and this one carry the same second)
        self.assertEqual(got[('b1', 'c2')][-1]['content'], '備份之後才說的')  # the file is newer than the backup and wins
        self.assertEqual(got[('b1', 'c3')][0]['content'], '新對話的第一句'); self.assertEqual(next(c for c in store.data['bots'][0]['chats'] if c['id'] == 'c3')['title'], '新對話的第一句')
        self.assertNotIn('b7', [b['id'] for b in store.data['bots']])
        aside = [p for p in self.dir.iterdir() if p.name.startswith('chats.unlisted-')]
        self.assertEqual(len(aside), 1); self.assertTrue((aside[0] / 'b7' / 'k.json').exists())  # an unknown Bot's conversations are moved aside, never deleted
        self.assertEqual(talk(self.m, self.open()), got)

    def test_backup_is_one_file_and_both_kinds_can_be_put_back(self):
        store = self.open(); app = mock.Mock(store=store)
        name = self.m.backup_write(store, 'manual', store.data)
        with gzip.open(str(self.dir / 'backups' / name), 'rt', encoding='utf-8') as f: packed = json.load(f)
        self.assertEqual(packed['bots'][0]['chats'][0]['messages'], msgs('b1c1-', 3)); self.assertEqual(packed['groups'][0]['messages'], msgs('g1-', 5)); self.assertNotIn('layout', packed)
        plain = 'zook-manual-20200101-000000.json'; (self.dir / 'backups' / plain).write_text(json.dumps(old_data(), ensure_ascii=False), encoding='utf-8')  # a backup from before
        self.assertEqual({b['name'] for b in self.m.backup_list(store)} >= {name, plain}, True)
        for which in (name, plain):
            store.data['bots'][0]['messages'].append(dict(id='gone', role='user', content='還原後不該在', status='completed'))
            store.data['bots'][0]['chats'] = [c for c in store.data['bots'][0]['chats'] if c['id'] != 'c1']; store.save(everything=True)
            self.assertFalse(self.file('b1/c1.json').exists())
            self.m.backup_restore(app, which)
            self.assertEqual(talk(self.m, store), self.want, which)
            self.assertEqual(talk(self.m, self.open()), self.want, which); self.assertEqual(self.on_disk()['layout'], 2)
            self.assertEqual(json.loads(self.file('b1/c1.json').read_text(encoding='utf-8'))['messages'], msgs('b1c1-', 3))

    def test_messages_an_older_zook_wrote_into_the_main_file_are_kept(self):
        self.open(); main = self.on_disk()
        main['bots'][0]['messages'] = [dict(id='old-app', role='user', content='舊版寫的', status='completed')]
        self.main.write_text(json.dumps(main, ensure_ascii=False), encoding='utf-8')
        got = talk(self.m, self.open())[('b1', 'c2')]
        self.assertEqual([m['id'] for m in got], [m['id'] for m in self.want[('b1', 'c2')]] + ['old-app'])

    def test_odd_ids_never_leave_the_folder(self):
        data = old_data(); data['bots'][0]['id'] = '../../escape'; data['bots'][0]['chats'][0]['id'] = 'a/b'; data['groups'][0]['id'] = '..'
        self.main.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        store = self.open(); root = (self.dir / 'chats').resolve()
        files = [p.resolve() for p in root.rglob('*.json')]
        self.assertEqual(len(files), 6); self.assertTrue(all(root in p.parents for p in files)); self.assertFalse((self.dir.parent / 'escape').exists())
        self.assertEqual(len(talk(self.m, self.open())[('../../escape', 'a/b')]), 3)


if __name__ == '__main__': unittest.main()
