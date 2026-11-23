# -*- coding: utf-8 -*-
"""自動偵測使用量: the setting, the timer in the schedule loop, and one detection at a time."""
import importlib.util, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))
spec = importlib.util.spec_from_file_location('zook_usage_auto', BACKEND / 'server.py'); server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)


class AutoDetect(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.store = server.Store(Path(self.temp.name))
        self.app = server.App(('127.0.0.1', 0), self.store, self.temp.name, 't')
        self.calls = []
        self.release = threading.Event(); self.release.set()
        def probe(env=None):
            self.calls.append(env); self.release.wait(5)
            return {}
        self.main = dict(status='logged_in', method='Claude 訂閱帳號', email='me@example.com')
        self.views = {}  # extra account id -> what its CLI reports
        self.patches = [mock.patch.dict(server.__dict__, claude_quota_probe=probe, account_status=lambda provider, account=None: self.main,
                                        account_view=lambda account: self.views[account['id']])]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in self.patches: p.stop()
        self.app.server_close(); self.temp.cleanup()

    def wait_idle(self):
        gate = server.usage_detect_gate(self.app)
        with gate: pass

    def test_setting_is_off_by_default_and_saved(self):
        self.assertEqual(server.usage_detect_every(self.store), 0)
        self.assertEqual(server.set_usage_detect(self.store, 30), {'usageDetectEvery': 30})
        again = server.Store(Path(self.temp.name))  # after Zook restarts
        self.assertEqual(server.usage_detect_every(again), 30)

    def test_only_offered_intervals_are_accepted(self):
        for bad in (5, 45, -15, '15', True, None, 15.5, [15]):
            with self.assertRaises(ValueError, msg=repr(bad)): server.set_usage_detect(self.store, bad)
        with self.assertRaises(ValueError): server.update(self.store.data['settings'], {'usageDetectEvery': 7}, 'settings')
        self.assertEqual(server.usage_detect_every(self.store), 0)
        for good in (0, 15, 30, 60, 180):
            self.assertEqual(server.set_usage_detect(self.store, good)['usageDetectEvery'], good)

    def test_quota_view_reports_the_setting(self):
        server.set_usage_detect(self.store, 60)
        handler = server.Handler.__new__(server.Handler); handler.server = self.app; handler.device = None
        with mock.patch.dict(server.__dict__, account_status=lambda provider: dict(status='logged_out', method='', name=provider, plan='', email='')):
            self.assertEqual(handler.quota()['usageDetectEvery'], 60)

    def test_off_never_detects(self):
        self.assertFalse(server.usage_detect_tick(self.app, now=time.time() + 10 ** 6))
        server.set_usage_detect(self.store, 15); server.set_usage_detect(self.store, 0)
        self.assertFalse(server.usage_detect_tick(self.app, now=time.time() + 10 ** 6))
        self.assertEqual(self.calls, [])

    def test_detects_when_the_interval_has_passed(self):
        server.set_usage_detect(self.store, 15)
        now = time.time()
        self.assertTrue(server.usage_detect_tick(self.app, now=now))  # never detected before
        self.wait_idle(); self.assertEqual(len(self.calls), 1)
        last = self.store.data['usageDetectedAt']
        self.assertFalse(server.usage_detect_tick(self.app, now=last + 14 * 60))  # not yet
        self.assertTrue(server.usage_detect_tick(self.app, now=last + 15 * 60))
        self.wait_idle(); self.assertEqual(len(self.calls), 2)
        self.assertIsNone(self.app.codex_quota_caches.get('codex'))

    def test_the_button_also_resets_the_timer(self):
        server.set_usage_detect(self.store, 60)
        self.assertTrue(server.detect_usage_now(self.app))
        self.assertFalse(server.usage_detect_tick(self.app, now=time.time() + 30 * 60))
        self.assertEqual(len(self.calls), 1)

    def test_only_one_detection_at_a_time(self):
        server.set_usage_detect(self.store, 15)
        self.release.clear()
        results = []
        first = threading.Thread(target=lambda: results.append(server.detect_usage_now(self.app))); first.start()
        for _ in range(200):
            if self.calls: break
            time.sleep(0.01)
        self.assertFalse(server.usage_detect_tick(self.app, now=time.time() + 10 ** 6))  # the timer skips while the button's is running
        second = threading.Thread(target=lambda: results.append(server.detect_usage_now(self.app))); second.start()
        time.sleep(0.1); self.release.set(); first.join(5); second.join(5)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sorted(results), [False, True])

    def add_profile(self, name, **view):
        account_id = name[0] * 32 if name[0] in 'abcdef' else {'noemail': 'd' * 31 + 'e'}[name]
        self.store.data.setdefault('accounts', []).append(dict(id=account_id, provider='claude', type='login', name=account_id))
        self.views[account_id] = dict(dict(status='logged_in', method='Claude 訂閱帳號', email=''), **view)

    def stale_snapshot(self):
        with self.store.lock: self.store.data.setdefault('quota', {})['claude'] = dict(updatedAt='2000-01-01T00:00:00+00:00')
        self.app.claude_probe_at = 0

    # ---- P1: opening the usage page (also from a paired phone) shares the lock
    def test_opening_the_page_still_reads_claude_when_off(self):
        self.stale_snapshot()
        self.app.auto_claude_quota()
        self.assertEqual(len(self.calls), 1)  # the page-open read stays as it was, whatever 自動偵測 is set to

    def test_opening_the_page_never_overlaps_a_detection(self):
        self.stale_snapshot()
        gate = server.usage_detect_gate(self.app); gate.acquire()
        try: self.app.auto_claude_quota()
        finally: gate.release()
        self.assertEqual(self.calls, [])
        self.release.clear()
        opener = threading.Thread(target=self.app.auto_claude_quota); opener.start()
        for _ in range(200):
            if self.calls: break
            time.sleep(0.01)
        self.assertTrue(gate.locked())  # the page-open read holds it while its request runs
        server.set_usage_detect(self.store, 15)
        self.assertFalse(server.usage_detect_tick(self.app, now=time.time() + 10 ** 6))  # so the timer does not send another
        self.release.set(); opener.join(5)
        self.assertEqual(len(self.calls), 1)

    def test_phone_quota_read_goes_through_the_lock(self):
        source = (BACKEND / 'zook' / 'handler.py').read_text(encoding='utf-8')
        route = source[source.index("if path == '/api/quota' and self.command == 'GET'"):source.index("if path == '/api/usage/overview'")]
        self.assertIn('auto_claude_quota()', route); self.assertIn("claude_probe_default(self.server, 'probe')", route)
        self.assertNotIn('claude_quota_probe(', route)
        app_source = (BACKEND / 'zook' / 'app.py').read_text(encoding='utf-8')
        body = app_source[app_source.index('def auto_claude_quota'):app_source.index('def live_permission')]
        self.assertIn("claude_probe_default(self, 'auto')", body); self.assertNotIn('claude_quota_probe(', body)
        self.assertTrue(server.device_may('GET', '/api/quota')); self.assertTrue(server.device_may('GET', '/api/quota/auto'))

    def test_refresh_button_waits_for_a_running_detection(self):
        gate = server.usage_detect_gate(self.app); gate.acquire()
        done = []
        t = threading.Thread(target=lambda: done.append(server.claude_probe_default(self.app, 'probe'))); t.start()
        time.sleep(0.1); self.assertEqual(done, []); gate.release(); t.join(5)
        self.assertEqual(done, [False]); self.assertEqual(self.calls, [])

    # ---- P2
    def test_timer_reads_the_last_time_again_once_it_has_the_lock(self):
        server.set_usage_detect(self.store, 15)
        test = self
        class Sneaky:  # a manual detection ends between the check and the lock
            def __init__(self): self.inner = threading.Lock()
            def acquire(self, blocking=True):
                with test.store.lock: test.store.data['usageDetectedAt'] = time.time()
                return self.inner.acquire(blocking)
            def release(self): self.inner.release()
            def locked(self): return self.inner.locked()
            def __enter__(self): self.acquire(); return self
            def __exit__(self, *a): self.release()
        self.app.usage_detect_lock = Sneaky()
        self.assertFalse(server.usage_detect_tick(self.app))
        self.assertFalse(self.app.usage_detect_lock.locked()); self.assertEqual(self.calls, [])

    def test_timer_sees_off_saved_just_before_it_has_the_lock(self):
        server.set_usage_detect(self.store, 15)
        test = self
        inner = threading.Lock()
        class Lock:
            def acquire(self, blocking=True):
                server.set_usage_detect(test.store, 0); return inner.acquire(blocking)
            def release(self): inner.release()
            def locked(self): return inner.locked()
        self.app.usage_detect_lock = Lock()
        self.assertFalse(server.usage_detect_tick(self.app, now=time.time() + 10 ** 6))
        self.assertFalse(inner.locked()); self.assertEqual(self.calls, [])

    def test_failed_save_leaves_the_setting_as_it_was(self):
        with mock.patch.object(self.store, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): server.set_usage_detect(self.store, 15)
        self.assertEqual(server.usage_detect_every(self.store), 0); self.assertNotIn('usageDetectEvery', self.store.data['settings'])
        self.assertFalse(server.usage_detect_tick(self.app, now=time.time() + 10 ** 6))
        server.set_usage_detect(self.store, 60)
        with mock.patch.object(self.store, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): server.set_usage_detect(self.store, 0)
        self.assertEqual(server.usage_detect_every(self.store), 60)

    def test_restoring_a_backup_keeps_this_macs_setting_and_clock(self):
        with self.store.lock:
            server.set_usage_detect(self.store, 15); self.store.data['usageDetectedAt'] = 1000.0
            name = server.backup_write(self.store, 'manual', self.store.data)
            server.set_usage_detect(self.store, 0); self.store.data['usageDetectedAt'] = 2000.0; self.store.save()
            server.backup_restore(self.app, name)
        data = self.app.store.data
        self.assertEqual(server.usage_detect_every(self.app.store), 0); self.assertEqual(data['usageDetectedAt'], 2000.0)
        new = dict(settings={'usageDetectEvery': 30}, usageDetectedAt=5.0)
        server.usage_detect_keep_local(dict(settings={}), new)
        self.assertEqual(new, dict(settings={}))

    def test_claude_is_probed_only_when_known_to_be_a_subscription(self):
        for method in ('', 'Anthropic Console', 'something new', 'API 金鑰'):
            self.main = dict(status='logged_in', method=method, email='me@example.com')
            self.assertEqual(server.claude_probe_targets(self.store), [], method)
        self.main = dict(status='logged_in', method='Claude 訂閱帳號', email='me@example.com')
        self.add_profile('bad', method='')
        self.assertEqual(server.claude_probe_targets(self.store), [None])
        self.stale_snapshot(); self.main = dict(status='logged_in', method='', email='')
        self.app.auto_claude_quota(); self.assertEqual(self.calls, [])  # opening the page follows the same rule

    def test_each_subscription_is_probed_once(self):
        self.add_profile('a-same', email='ME@example.com')  # the default sign-in again, in a Zook profile
        self.add_profile('b-other', email='other@example.com')
        self.add_profile('c-other-again', email='other@example.com')
        self.add_profile('noemail')
        targets = server.claude_probe_targets(self.store)
        self.assertEqual([t['id'] if t else None for t in targets], [None, 'b' * 32, 'd' * 31 + 'e'])
        server.detect_usage_now(self.app); self.assertEqual(len(self.calls), 3)

    def test_quota_auto_route_answers_what_the_mac_has(self):
        server.set_usage_detect(self.store, 60)
        status = server.usage_detect_status(self.app)
        self.assertEqual((status['usageDetectEvery'], status['doneAt'], status['running']), (60, 0, False))

    # ---- P3
    def test_open_page_learns_a_detection_has_ended(self):
        before = server.usage_detect_status(self.app)['doneAt']
        server.set_usage_detect(self.store, 15); self.assertTrue(server.usage_detect_tick(self.app)); self.wait_idle()
        self.assertGreater(server.usage_detect_status(self.app)['doneAt'], before)
        js = (BACKEND.parent / 'frontend' / 'js' / '32-usage.js').read_text(encoding='utf-8')
        self.assertIn("api('quota/auto')", js); self.assertIn('refreshQuota()', js)

    def test_thread_that_cannot_start_lets_go_of_the_lock(self):
        server.set_usage_detect(self.store, 15)
        with mock.patch.object(server.threading.Thread, 'start', side_effect=RuntimeError("can't start new thread")):
            with self.assertRaises(RuntimeError): server.usage_detect_tick(self.app, now=time.time() + 10 ** 6)
        self.assertFalse(server.usage_detect_gate(self.app).locked())
        self.assertTrue(server.detect_usage_now(self.app))  # the button still works

    def test_lock_is_held_until_every_probe_has_ended(self):
        self.release.clear()
        t = threading.Thread(target=server.detect_usage_now, args=(self.app,)); t.start()
        for _ in range(200):
            if self.calls: break
            time.sleep(0.01)
        source = (BACKEND / 'zook' / 'usagewatch.py').read_text(encoding='utf-8')
        self.assertNotIn('join(100)', source)
        time.sleep(0.2); self.assertTrue(server.usage_detect_gate(self.app).locked())
        self.release.set(); t.join(5); self.assertFalse(server.usage_detect_gate(self.app).locked())

    def test_clock_going_back_does_not_run_early(self):
        server.set_usage_detect(self.store, 15)
        now = time.time()
        with self.store.lock: self.store.data['usageDetectedAt'] = now + 3600  # the clock was moved back an hour since
        self.assertFalse(server.usage_detect_tick(self.app, now=now))
        self.assertEqual(self.store.data['usageDetectedAt'], now)
        self.assertFalse(server.usage_detect_tick(self.app, now=now + 14 * 60))
        self.assertTrue(server.usage_detect_tick(self.app, now=now + 15 * 60)); self.wait_idle()
        self.assertEqual(len(self.calls), 1)

    def test_change_from_the_phone_is_in_the_activity_log(self):
        handler = server.Handler.__new__(server.Handler); handler.server = self.app; handler.command = 'POST'; handler.path = '/api/quota/auto'
        handler.device = dict(id='d1', name='Sean 的 iPhone'); handler.last_body = {'every': 15}; handler.hint = ''
        server.note_request(handler, 200, {'usageDetectEvery': 15})
        items = server.activity_list(self.store)['items']
        self.assertEqual(items[0]['by'], '手機：Sean 的 iPhone'); self.assertIn('自動偵測使用量（每 15 分鐘）', items[0]['text'])

    def test_schedule_loop_runs_the_timer(self):
        source = (BACKEND / 'zook' / 'scheduling.py').read_text(encoding='utf-8')
        loop = source[source.index('def schedule_loop'):]
        self.assertIn('usage_detect_tick(self)', loop)


if __name__ == '__main__': unittest.main()
