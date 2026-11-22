# -*- coding: utf-8 -*-
"""Backups with less than 20% left are tried last: a nearly used-up account answers only when nothing else can (使用者 2026-11-22)."""
import importlib.util, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_backup_room', SERVER); m = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(m)


class BackupRoom(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = m.Store(Path(self.temp.name) / 'data'); m._active['data'] = self.store.data

    def tearDown(self): self.temp.cleanup()

    def used(self, key, percent):
        self.store.data.setdefault('quota', {})[key] = {'windows': [{'label': '每週', 'usedPercent': percent, 'resetsAt': int(time.time()) + 86400}], 'updatedAt': m.NOW()}

    def test_nearly_used_up_goes_last(self):
        self.used('claude', 85); self.used('grok', 30)
        chain = [('claude', '', None, False), ('grok', '', None, False), ('antigravity', '', None, False)]
        self.assertEqual([x[0] for x in m.backups_with_room(self.store, {}, chain)], ['grok', 'antigravity', 'claude'])

    def test_all_low_keeps_the_order(self):
        self.used('claude', 90); self.used('grok', 95)
        chain = [('claude', '', None, False), ('grok', '', None, False)]
        self.assertEqual([x[0] for x in m.backups_with_room(self.store, {}, chain)], ['claude', 'grok'])

    def test_an_extra_account_is_judged_by_its_own_quota(self):
        self.used('codex', 95); self.used('codex@' + 'a' * 32, 10); self.used('claude', 50)
        chain = [('codex', '', 'a' * 32, True), ('claude', '', None, False)]
        self.assertEqual([x[0] for x in m.backups_with_room(self.store, {}, chain)], ['codex', 'claude'])


    def test_antigravity_is_judged_by_gemini(self):
        now = int(time.time()) + 86400
        self.store.data.setdefault('quota', {})['antigravity'] = {'windows': [{'label': 'Gemini Models · 每週', 'usedPercent': 20, 'resetsAt': now}, {'label': 'Claude and GPT models · 每週', 'usedPercent': 95, 'resetsAt': now}], 'updatedAt': m.NOW()}
        self.assertFalse(m.backup_low(self.store, 'antigravity'))


if __name__ == '__main__': unittest.main()
