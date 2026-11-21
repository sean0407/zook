# -*- coding: utf-8 -*-
"""Grok's weekly limit: from `grok usage --json` once it works, until then from the foot of Grok's own screen. Nothing is left running."""
import importlib.util, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'
FAKE = r'''#!/usr/bin/env python3
import os, subprocess, sys, time
log = os.environ['FAKE_LOG']
if sys.argv[1:] == ['usage', '--json']:
    open(log, 'a').write('json\n')
    print(os.environ.get('FAKE_JSON') or "Error: `grok usage` can't show your plan's usage here yet. Run /usage inside grok instead."); sys.exit(0)
open(log, 'a').write('screen %s %s %s\n' % (os.isatty(0), os.getcwd(), os.environ.get('PWD')))
child = subprocess.Popen(['/bin/sleep', '60'])
open(log, 'a').write('child %d\n' % child.pid)
sys.stdout.write('\x1b[?25l\x1b[2J╭──╮ Grok Build\r\n')
if os.environ.get('FAKE_TRUST'):
    sys.stdout.write('Do you trust the contents of this directory?\r\n  %s\r\n  Yes, proceed  y\r\n  No, quit  n\r\n' % os.getcwd()); sys.stdout.flush()
    import termios, tty; tty.setraw(0, termios.TCSANOW); key = os.read(0, 1)
    open(log, 'a').write('typed %r\n' % key)
    if key != b'y': time.sleep(60)
sys.stdout.write(os.environ.get('FAKE_SCREEN', '│ ❯  │\r\n╰── \x1b[38;5;245mWeekly limit left: 37% · Grok 4.7 (high)\x1b[0m ─╯\r\n')); sys.stdout.flush()
sys.stdin.read(1)  # waits for keys that never come
time.sleep(60)
'''


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_grok_quota', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def alive(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False


class GrokQuotaTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.cli = self.root / 'grok'; self.cli.write_text(FAKE); self.cli.chmod(0o755); self.log = self.root / 'log.txt'
        self.env = dict(os.environ, FAKE_LOG=str(self.log)); self.folder = self.root / 'screen'

    def tearDown(self): self.temp.cleanup()

    def lines(self): return self.log.read_text().splitlines() if self.log.exists() else []

    def test_reads_the_screen_without_typing_and_closes_everything(self):
        started = time.time()
        snap = self.m.grok_quota(str(self.cli), self.env, self.folder)
        self.assertLess(time.time() - started, 15)
        self.assertEqual(snap['windows'], [dict(label='每週', usedPercent=63.0, resetsAt=None)]); self.assertEqual(snap['source'], 'live')
        log = self.lines(); self.assertEqual(log[0], 'json')
        self.assertEqual(log[1], 'screen True %s %s' % (os.path.realpath(self.folder), self.folder))  # a real terminal, in Zook's own empty folder
        child = int(log[2].split()[1]); time.sleep(.3)
        self.assertFalse(alive(child))  # Grok and what it started are gone

    def test_only_the_trust_question_for_its_own_folder_is_answered(self):
        self.env['FAKE_TRUST'] = '1'
        snap = self.m.grok_quota(str(self.cli), self.env, self.folder)
        self.assertEqual(snap['windows'][0]['usedPercent'], 63.0)
        self.assertIn("typed b'y'", self.lines())
        self.assertEqual(len([x for x in self.lines() if x.startswith('typed')]), 1)

    def test_usage_json_is_used_as_soon_as_it_reports_a_figure(self):
        self.env['FAKE_JSON'] = '{"plan": {"weekly": {"remainingPercent": 81.5}}}'
        snap = self.m.grok_quota(str(self.cli), self.env, self.folder)
        self.assertEqual(snap['windows'][0]['usedPercent'], 18.5); self.assertEqual(self.lines(), ['json'])  # no screen opened

    def test_unknown_json_and_unknown_screen_are_not_guessed(self):
        self.env['FAKE_JSON'] = '{"tokens": 12345, "percent": 50}'
        self.env['FAKE_SCREEN'] = '│ Weekly limit: 40 units │\r\n'
        self.m.GROK_SCREEN_WAIT = 3
        self.assertIsNone(self.m.grok_quota(str(self.cli), self.env, self.folder))
        child = int(next(x for x in self.lines() if x.startswith('child')).split()[1]); time.sleep(.3)
        self.assertFalse(alive(child))

    def test_quota_rules_now_cover_grok(self):
        store = self.m.Store(self.root / 'data')
        store.data['quota'] = {'grok': dict(self.m.grok_quota(str(self.cli), self.env, self.folder), windows=[dict(label='每週', usedPercent=95, resetsAt=None)])}
        store.data['settings']['addedProviders'] = ['codex', 'claude', 'grok']
        self.assertTrue(self.m.auto_quota_low(store, 'grok'))
        ring = next(r for r in self.m.usage_rings(store) if r['id'] == 'grok')
        self.assertEqual((ring['week'], ring['left']), (5, 5))


if __name__ == '__main__': unittest.main()
