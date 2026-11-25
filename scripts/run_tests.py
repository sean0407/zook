#!/usr/bin/env python3
"""Run every test file at the same time, a few at once, instead of one after another.

    /usr/bin/python3 scripts/run_tests.py            # all of tests/*_test.py
    /usr/bin/python3 scripts/run_tests.py -j 4       # at most 4 files at once
    /usr/bin/python3 scripts/run_tests.py outline_test intro_test

Each test file runs in a process of its own (its own temporary folders and its own Zook servers on free ports), so files do
not share anything, and is loaded exactly as `unittest discover -s tests` always loaded it. The longest files start first.
A file passes only when unittest really ran tests in it and said OK; no tests, no summary, a crash or a timeout is a failure.
A file that fails is run once more on its own: if it passes then, it is listed as 不穩定 with the first failure printed, so a
busy machine does not fail the run but the flaky test is still seen. Exit code 0 when every file passed, 1 otherwise.
The same command runs on GitHub (.github/workflows/test.yml).
"""
import argparse, concurrent.futures, json, os, pathlib, re, signal, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIMES = ROOT / 'tests' / '.times.json'  # how long each file took last time, so the longest start first (not committed)
FILE_TIMEOUT = 900  # seconds one test file may take
# Switches a caller may have in its own environment that would change what a test checks; each test sets what it needs.
CLEAR_ENV = ('ZOOK_NO_INTRO',)


RUN_MARK = 'zt%d-%s' % (os.getpid(), os.urandom(4).hex())  # in the environment of everything a test file starts


def leftovers(mark):
    """Processes a test file started that are still running (servers, runners, stand-in CLIs): found by the mark in their
    environment, which only this user's own processes show (ps -E)."""
    try: lines = subprocess.run(['/bin/ps', '-E', '-axww', '-o', 'pid=,command='], capture_output=True, text=True, timeout=20).stdout.splitlines()
    except (OSError, subprocess.SubprocessError): return []
    pids = []
    for line in lines:
        pid, _, rest = line.strip().partition(' ')
        if 'ZOOK_TEST_RUN=' + mark + ' ' in rest + ' ' and pid.isdigit() and int(pid) != os.getpid(): pids.append(pid)
    if not pids: return []
    try: named = subprocess.run(['/bin/ps', '-ww', '-o', 'pid=,command=', '-p', ','.join(pids)], capture_output=True, text=True, timeout=20).stdout.splitlines()
    except (OSError, subprocess.SubprocessError): named = []
    def program(command):  # the program and its script only: never its arguments (a test may pass a password) or environment
        words = command.split(); name = os.path.basename(words[0]) if words else ''
        script = words[1] if len(words) > 1 and 'python' in name.lower() and words[1].endswith('.py') else ''  # a Python script's own name
        return (name + ' ' + os.path.basename(script)).strip()
    out = {int(l.split()[0]): program(l.strip().partition(' ')[2]) for l in named if l.strip()}
    return [(int(p), out.get(int(p), '')) for p in pids]


def sweep(mark):
    """End what a test file left running (a moment first: a runner may still be finishing), and say what it was."""
    end = time.monotonic() + 10
    while leftovers(mark) and time.monotonic() < end: time.sleep(0.5)
    left = leftovers(mark)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, _ in leftovers(mark):
            try: os.kill(pid, sig)
            except OSError: pass
        if sig == signal.SIGTERM: time.sleep(2)
    return left


def run_one(name):
    started = time.monotonic()
    env = {k: v for k, v in os.environ.items() if k not in CLEAR_ENV}; env['PYTHONDONTWRITEBYTECODE'] = '1'
    mark = '%s-%s' % (RUN_MARK, name); env['ZOOK_TEST_RUN'] = mark
    proc = subprocess.Popen([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', name + '.py'], cwd=str(ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    try: out, _ = proc.communicate(timeout=FILE_TIMEOUT); why = ''
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid, signal.SIGKILL)  # the file and every server it started
        except OSError: pass
        out, _ = proc.communicate(); why = '超過 %d 秒，已停止' % FILE_TIMEOUT
    text = out.decode('utf-8', 'replace')
    left = sweep(mark)
    if left:  # a test that leaves processes behind fails: they pile up and end in crash reports later
        text += '\n\n留下沒關掉的程序（已結束它們）：\n' + '\n'.join('  %d %s' % x for x in left) + '\n'; why = why or '留下沒關掉的程序'
    # unittest's own summary is the last 「Ran N tests」 line followed by OK or FAILED; anything a test printed earlier does not count.
    summary = list(re.finditer(r'^Ran (\d+) tests? in [\d.]+s\s*\n\s*\n(OK|FAILED)(?: \(([^)]*)\))?\s*$', text, re.M))
    last = summary[-1] if summary else None
    ran = int(last.group(1)) if last else 0
    found = re.search(r'skipped=(\d+)', last.group(3) or '') if last else None
    skipped = int(found.group(1)) if found else 0
    if not why:
        why = ('程序異常結束（%s）' % proc.returncode) if proc.returncode < 0 else '沒有 unittest 的結果' if not last else '沒有載入任何測試' if ran == 0 else ''
    ok = not why and proc.returncode == 0 and last.group(2) == 'OK'
    return dict(name=name, ok=ok, ran=ran, skipped=skipped, seconds=time.monotonic() - started, output=text + ('\n（%s）' % why if why else ''))


def load_times():
    try: past = json.loads(TIMES.read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}
    if not isinstance(past, dict): return {}
    return {k: float(v) for k, v in past.items() if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*', help='test files to run (without .py); all of them when left out')
    ap.add_argument('-j', type=int, default=0, help='files at once (default: the number of processors, at most 8)')
    args = ap.parse_args()
    every = sorted(p.stem for p in (ROOT / 'tests').glob('*_test.py'))
    unknown = [n for n in args.names if n not in every]
    if unknown: print('找不到這些測試檔：' + ', '.join(unknown), file=sys.stderr); return 2
    names = list(args.names or every)
    if not names: print('沒有任何測試檔。', file=sys.stderr); return 2
    past = load_times()
    names.sort(key=lambda n: -past.get(n, 30.0))  # the longest first, so one slow file does not finish last on its own
    workers = args.j or max(2, min(8, os.cpu_count() or 2))
    started = time.monotonic(); results, flaky = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        first = list(pool.map(run_one, names))
    for result in first:
        if not result['ok']:
            again = run_one(result['name'])  # alone, on a quieter machine
            if again['ok']:
                flaky.append(result['name'])
                print('\n==== %s 第一次失敗，單獨重跑通過：不穩定（%.0f 秒）====\n%s' % (result['name'], result['seconds'], result['output'].rstrip()), flush=True)
            else:
                print('\n==== %s 失敗（兩次都失敗）====\n---- 第一次 ----\n%s\n---- 單獨重跑 ----\n%s' % (result['name'], result['output'].rstrip(), again['output'].rstrip()), flush=True)
            result = again
        results.append(result)
    try:
        fd, temp = tempfile.mkstemp(dir=str(TIMES.parent), prefix='.times-')
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(dict(past, **{r['name']: round(r['seconds'], 1) for r in results}), f, indent=0)
        os.replace(temp, str(TIMES))  # whole, so two runs at once never leave half a file
    except OSError: pass
    failed = [r['name'] for r in results if not r['ok']]
    total, skipped = sum(r['ran'] for r in results), sum(r['skipped'] for r in results)
    slowest = sorted(results, key=lambda r: -r['seconds'])[:5]
    print('\nRan %d tests in %.0fs（%d 個檔案、同時 %d 個；最久：%s）' % (total, time.monotonic() - started, len(results), workers, '、'.join('%s %.0fs' % (r['name'], r['seconds']) for r in slowest)))
    if flaky: print('不穩定（重跑才通過）：' + ', '.join(flaky))
    print('FAILED: ' + ', '.join(failed) if failed else 'OK' + (' (skipped=%d)' % skipped if skipped else ''))
    return 1 if failed else 0


if __name__ == '__main__': sys.exit(main())
