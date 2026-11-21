#!/usr/bin/env python3
"""Run every test file at the same time, a few at once, instead of one after another.

    /usr/bin/python3 scripts/run_tests.py            # all of tests/*_test.py
    /usr/bin/python3 scripts/run_tests.py -j 4       # at most 4 files at once
    /usr/bin/python3 scripts/run_tests.py outline_test grok_quota_test

Each test file runs in a process of its own (its own temporary folders and its own Zook servers on free ports), so files do
not share anything. The longest files start first. The output of a file is printed only when it fails. Exit code 0 when every
file passed, 1 otherwise. A file that fails is run once more on its own: if it passes then, it is listed as 不穩定 with the
first failure printed, so a busy machine does not fail the run but the flaky test is still seen. The same command runs on
GitHub (.github/workflows/test.yml).
"""
import argparse, concurrent.futures, json, os, pathlib, re, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIMES = ROOT / 'tests' / '.times.json'  # how long each file took last time, so the longest start first (not committed)


def run_one(name):
    started = time.monotonic()
    done = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', name + '.py'], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # loaded the way the whole suite always was
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    text = done.stdout.decode('utf-8', 'replace')
    ran = re.search(r'^Ran (\d+) tests?', text, re.M); skipped = re.search(r'skipped=(\d+)', text)
    return dict(name=name, ok=done.returncode == 0, ran=int(ran.group(1)) if ran else 0, skipped=int(skipped.group(1)) if skipped else 0,
                seconds=time.monotonic() - started, output=text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*', help='test files to run (without .py); all of them when left out')
    ap.add_argument('-j', type=int, default=0, help='files at once (default: the number of processors, at most 8)')
    args = ap.parse_args()
    names = args.names or sorted(p.stem for p in (ROOT / 'tests').glob('*_test.py'))
    try: past = json.loads(TIMES.read_text(encoding='utf-8'))
    except (OSError, ValueError): past = {}
    names.sort(key=lambda n: -float(past.get(n, 30)))  # the longest first, so one slow file does not finish last on its own
    workers = args.j or max(2, min(8, os.cpu_count() or 2))
    started = time.monotonic(); results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        first = list(pool.map(run_one, names))
    flaky = []
    for result in first:
        if not result['ok']:
            again = run_one(result['name'])  # alone, on a quieter machine
            print('\n==== %s %s（%.0f 秒）====\n%s' % (result['name'], '第一次失敗，單獨重跑通過：不穩定' if again['ok'] else '失敗', result['seconds'], (result if again['ok'] else again)['output'].rstrip()), flush=True)
            if again['ok']: flaky.append(result['name'])
            result = again
        results.append(result)
    try: TIMES.write_text(json.dumps(dict(past, **{r['name']: round(r['seconds'], 1) for r in results}), indent=0), encoding='utf-8')
    except OSError: pass
    failed = [r['name'] for r in results if not r['ok']]
    total, skipped = sum(r['ran'] for r in results), sum(r['skipped'] for r in results)
    slowest = sorted(results, key=lambda r: -r['seconds'])[:5]
    print('\nRan %d tests in %.0fs（%d 個檔案、同時 %d 個；最久：%s）' % (total, time.monotonic() - started, len(results), workers, '、'.join('%s %.0fs' % (r['name'], r['seconds']) for r in slowest)))
    if flaky: print('不穩定（重跑才通過）：' + ', '.join(flaky))
    print('FAILED: ' + ', '.join(failed) if failed else 'OK' + (' (skipped=%d)' % skipped if skipped else ''))
    return 1 if failed else 0


if __name__ == '__main__': sys.exit(main())
