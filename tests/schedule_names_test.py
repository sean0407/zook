# -*- coding: utf-8 -*-
"""#97: a schedule has a name (may be empty: the first words of what it does stand in), the list says 已啟用／已關閉 and when it
runs next; #166/#168: the form catches a time that has passed and long text folds to a few lines."""
import datetime, importlib.util, json, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'backend/server.py'
spec = importlib.util.spec_from_file_location('zook_schedule_names', SERVER); server = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(server)
JS = {p.name: p.read_text(encoding='utf-8') for p in (ROOT / 'frontend/js').glob('*.js')}


def snippet(name, pattern):
    found = re.search(pattern, JS[name], re.S)
    if not found: raise AssertionError('not found in %s: %s' % (name, pattern))
    return found.group(0)


def run_js(code):
    out = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=30)
    if out.returncode: raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class Name(unittest.TestCase):
    def fields(self, body, record=None):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); bot = store.data['bots'][0]
            base = dict(id='s', botId=bot['id'], content='整理今天的信', time='10:00', repeat='daily', on=True)
            return server.schedule_fields(store, body, dict(base, **(record or {})))

    def test_name_is_kept_trimmed_and_may_be_empty(self):
        self.assertEqual(self.fields({'name': '  早上整理信件 '})['name'], '早上整理信件')
        self.assertEqual(self.fields({'name': ''})['name'], '')
        self.assertNotIn('name', self.fields({}))  # an old schedule stays as it was
        self.assertEqual(self.fields({}, {'name': '舊名'})['name'], '舊名')

    def test_bad_names_are_refused(self):
        with self.assertRaises(ValueError): self.fields({'name': 'x' * 61})
        with self.assertRaises(ValueError): self.fields({'name': 5})

    def test_title_falls_back_to_the_first_words(self):
        title = server.schedule_title
        self.assertEqual(title(dict(name='週報', content='很長的內容')), '週報')
        self.assertEqual(title(dict(name='', content='## 整理今天的行事曆和未讀信件，列出三件最重要的事')), '整理今天的行事曆和未讀信件，列出三件…')
        self.assertEqual(title(dict(content='看新聞')), '看新聞')

    def test_bots_and_the_phone_see_the_name(self):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); bot = store.data['bots'][0]
            store.data['schedules'].append(dict(id='s', botId=bot['id'], name='週報', content='寫週報', time='10:00', repeat='daily', on=True))
            self.assertEqual(server.mobile_schedules(store)['schedules'][0]['name'], '週報')


@unittest.skipUnless(shutil.which('node'), 'needs node')
class Page(unittest.TestCase):
    def js(self, expr):
        code = '\n'.join([snippet('20-models.js', r"const REPEATS = .*?\n"), snippet('20-models.js', r"const repeatName = .*?\n"),
                          snippet('20-models.js', r"const WEEKDAY = .*?\n"), snippet('20-models.js', r"const dayLabel = .*?\n"),
                          snippet('20-models.js', r"function scheduleTitle\(.*?\n  }\n"), snippet('20-models.js', r"function scheduleNext\(.*?\n  }\n")])
        return run_js(code + '\nconsole.log(JSON.stringify(%s))' % expr)

    def next(self, item, now):
        return self.js('(d => d && [d.getFullYear(), d.getMonth() + 1, d.getDate(), d.getHours(), d.getMinutes()])(scheduleNext(%s, new Date(%s)))'
                       % (json.dumps(dict(dict(on=True, trigger='time'), **item)), ', '.join(str(x) for x in now)))

    def test_next_run(self):
        wed = (2026, 10, 18, 10, 0, 30)  # Wednesday 2026-11-18 10:00:30 (JS months start at 0)
        self.assertEqual(self.next(dict(time='10:00', repeat='daily'), wed), [2026, 11, 19, 10, 0])
        self.assertEqual(self.next(dict(time='10:01', repeat='daily'), wed), [2026, 11, 18, 10, 1])
        self.assertEqual(self.next(dict(time='09:00', repeat='mon'), wed), [2026, 11, 23, 9, 0])
        self.assertEqual(self.next(dict(time='09:00', repeat='weekdays'), (2026, 10, 20, 12, 0)), [2026, 11, 23, 9, 0])  # Friday noon
        self.assertEqual(self.next(dict(time='09:00', repeat='sun'), wed), [2026, 11, 22, 9, 0])
        self.assertEqual(self.next(dict(time='00:15', repeat='hourly'), wed), [2026, 11, 18, 10, 15])
        self.assertEqual(self.next(dict(time='00:00', repeat='hourly'), wed), [2026, 11, 18, 11, 0])
        self.assertEqual(self.next(dict(time='11:00', repeat='once', date='2026-11-18'), wed), [2026, 11, 18, 11, 0])
        self.assertIsNone(self.next(dict(time='09:00', repeat='once', date='2026-11-18'), wed))
        self.assertEqual(self.next(dict(time='08:00', repeat='monthly', day=18), wed), [2026, 12, 18, 8, 0])
        self.assertEqual(self.next(dict(time='08:00', repeat='monthly', day=31), wed), [2026, 11, 30, 8, 0])
        self.assertEqual(self.next(dict(time='08:00', repeat='monthly', day=31), (2027, 0, 31, 9, 0)), [2027, 2, 28, 8, 0])
        self.assertIsNone(self.next(dict(time='10:00', repeat='daily', on=False), wed))  # off: it does not run
        self.assertIsNone(self.next(dict(time='10:00', repeat='daily', trigger='folder'), wed))  # waits for a file, not a time

    def test_title(self):
        self.assertEqual(self.js("scheduleTitle({name: '週報', content: 'x'})"), '週報')
        self.assertEqual(self.js("scheduleTitle({name: '', content: '## 整理今天的行事曆和未讀信件，列出三件最重要的事'})"), '整理今天的行事曆和未讀信件，列出三件…')

    def test_card_says_on_or_off_and_folds_long_text(self):
        page = snippet('20-models.js', r'function schedulesPage\(.*?\n  }\n')
        for text in ('已啟用', '已關閉', '下次執行', 'scheduleTitle(x)', 'sched-content', 'sched-more'):
            self.assertIn(text, page)

    def test_form_has_a_name_and_checks_past_times(self):
        form = snippet('30-pages.js', r'function scheduleModal\(.*?\n  }\n')
        self.assertIn('name="name"', form)
        self.assertIn('x.on !== false', form)  # a new schedule is still on by default
        save = snippet('50-forms.js', r"form.id === 'schedule-form'.*?toast\(")
        self.assertIn('name:', save)
        self.assertIn('這個時間已經過了', save)


if __name__ == '__main__':
    unittest.main()
