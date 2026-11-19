#!/usr/bin/env python3
"""Acceptance check with the real CLIs on this Mac.

Starts Zook's backend on an empty data folder, sends real messages and prints one line per check.
Exit code 0 means every check passed. Run it before a change to get the baseline and after each change to compare:

    python3 scripts/acceptance.py                 # all checks
    python3 scripts/acceptance.py --save base.json
    python3 scripts/acceptance.py --compare base.json   # fails if a check that passed in base.json fails now

It uses the CLIs' own sign-ins and a small amount of their quota. It never touches Zook's real data."""
import argparse, concurrent.futures, json, os, pathlib, subprocess, sys, tempfile, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROVIDERS = ('codex', 'claude', 'grok', 'antigravity')
NAMES = dict(codex='Codex', claude='Claude', grok='Grok', antigravity='Antigravity')


class Zook:
    def __init__(self, folder, port):
        env = dict(os.environ, PATH=os.pathsep.join([os.path.expanduser('~/.local/bin'), os.path.expanduser('~/.grok/bin'), '/usr/bin', '/bin', os.environ.get('PATH', '')]),
                   ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_NO_BROWSER='1', ZOOK_SCHEDULE_TICK='2', ZOOK_TRIGGER_EVERY='2', ZOOK_SECRETS_DIR=str(folder / 'secrets'))
        (folder / 'secrets').mkdir()
        self.proc = subprocess.Popen([sys.executable, str(ROOT / 'backend/server.py'), '--port', str(port), '--data-dir', str(folder / 'data'), '--assets', str(ROOT / 'frontend')],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = json.loads(self.proc.stdout.readline()); self.base, self.token = 'http://127.0.0.1:%d/api/' % ready['port'], ready['token']

    def req(self, method, path, body=None):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                         headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=60) as response: return json.load(response)
        except urllib.error.HTTPError as exc:
            try: return dict(json.load(exc), httpStatus=exc.code)
            except ValueError: return dict(error=str(exc), httpStatus=exc.code)

    def ask(self, bot_id, text, wait=240, on_running=None, **more):
        sent = self.req('POST', 'chat', dict(dict(botId=bot_id, content=text), **more))
        if 'jobId' not in sent: return dict(status='refused', error=str(sent.get('error')))
        end = time.time() + wait
        while time.time() < end:
            job = self.req('GET', 'jobs/' + sent['jobId'])
            if job.get('status') != 'running': return job
            if on_running: on_running(job)
            time.sleep(1)
        return dict(status='timeout', error='no reply in %d seconds' % wait)

    def close(self):
        self.proc.terminate()
        try: self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired: self.proc.kill()
        self.proc.stdout.close()


def check_provider(z, provider):
    """One reply with usage figures, then a second one that must remember the first."""
    out = {}
    bot = z.req('POST', 'bots', dict(name='驗收-' + provider, provider=provider))
    first = z.ask(bot['id'], '請記住這個數字：4827。只回覆「好」。')
    if first.get('errorKind') == 'quota' or '額度' in str(first.get('error') or ''):  # nothing to check until the limit resets; not a fault in Zook
        return {'%s %s' % (NAMES[provider], part): (None, '額度已用完，這次無法檢查') for part in ('回覆', '用量數字', '接續對話')}
    ok = first.get('status') == 'completed' and bool(first.get('content'))
    out['%s 回覆' % NAMES[provider]] = (ok, first.get('error') or '')
    usage = first.get('usage') or {}
    out['%s 用量數字' % NAMES[provider]] = (isinstance(usage.get('input'), int) and usage['input'] > 0 and isinstance(usage.get('output'), int) and usage['output'] > 0, json.dumps(usage)[:120])
    second = z.ask(bot['id'], '我剛才請你記住的數字是多少？只回覆數字。') if ok else {}
    out['%s 接續對話' % NAMES[provider]] = ('4827' in str(second.get('content') or ''), str(second.get('content') or second.get('error') or '沒有進行')[:80])
    return out


def check_approval(z):
    """Creating a schedule always needs the user's approval: it must be asked first, and only exist after the yes."""
    bot = z.req('POST', 'bots', dict(name='驗收-核准', provider='codex'))
    count = lambda: len([x for x in z.req('GET', 'state')['schedules'] if x.get('botId') == bot['id']])
    seen = {}
    def answer(job):
        for a in job.get('approvals') or []:
            if a['status'] == 'pending' and a['id'] not in seen:
                seen[a['id']] = a.get('name'); seen['before'] = count()
                z.req('POST', 'approvals/' + a['id'], dict(decision='approve'))
    job = z.ask(bot['id'], '請幫我建立一個排程：每天早上 09:00 提醒我喝水。建立後只回覆「已建立」。', on_running=answer)
    asked = any(v == 'zook_create_schedule' for k, v in seen.items() if k != 'before')
    return {'核准：動作前先問': (asked and seen.get('before') == 0, '有詢問=%s，詢問時已有排程=%s' % (asked, seen.get('before'))),
            '核准：核准後才執行': (job.get('status') == 'completed' and count() == 1, str(job.get('error') or '排程數 %d' % count())[:100])}


def wait_run(z, schedule_id, wait=200):
    end = time.time() + wait
    while time.time() < end:
        item = next((x for x in z.req('GET', 'state')['schedules'] if x['id'] == schedule_id), {})
        runs = item.get('runs') or []
        if runs and runs[-1].get('status') != 'running': return runs[-1]
        time.sleep(2)
    return {}


def check_schedules(z, folder):
    bot = z.req('POST', 'bots', dict(name='驗收-排程', provider='claude'))
    manual = z.req('POST', 'schedules', dict(botId=bot['id'], content='只回覆「排程正常」四個字。', time='00:00', repeat='daily', on=False))
    z.req('POST', 'schedules/%s/run' % manual['id'], {})
    run = wait_run(z, manual['id'])
    out = {'排程：手動執行': (run.get('status') == 'done' and bool(run.get('summary')), str(run.get('reason') or run.get('summary') or '沒有結果')[:80])}
    inbox = folder / 'inbox'; inbox.mkdir()
    watched = z.req('POST', 'schedules', dict(botId=bot['id'], content='告訴我新檔案的檔名，只回檔名。', time='00:00', repeat='daily', trigger='folder', watchFolder=str(inbox)))
    path = inbox / '驗收報價單.txt'; path.write_text('x'); old = time.time() - 10; os.utime(path, (old, old))
    run = wait_run(z, watched.get('id', ''))
    out['排程：資料夾有新檔案時執行'] = (run.get('status') == 'done' and '驗收報價單' in str(run.get('summary')), str(run.get('reason') or run.get('summary') or watched.get('error') or '沒有結果')[:80])
    return out


def check_group(z):
    a = z.req('POST', 'bots', dict(name='驗收-甲', provider='codex')); b = z.req('POST', 'bots', dict(name='驗收-乙', provider='claude'))
    group = z.req('POST', 'groups', dict(name='驗收群組', botIds=[a['id'], b['id']], mode='turns', turnLimit=4))
    z.req('POST', 'groups/%s/messages' % group['id'], dict(content='各用一句話說明你最擅長什麼，不要使用任何工具。'))
    end = time.time() + 300; data = {}
    while time.time() < end:
        data = z.req('GET', 'groups/' + group['id'])
        if data.get('group', {}).get('status') != 'running': break
        time.sleep(3)
    replies = [m for m in data.get('group', {}).get('messages', []) if m.get('role') == 'assistant' and m.get('status') == 'completed' and m.get('content')]
    return {'群組：兩個成員都有回覆': ({m.get('botId') for m in replies} == {a['id'], b['id']}, '完成 %d 則，狀態 %s' % (len(replies), data.get('group', {}).get('status')))}


def check_fallback_and_stop(z):
    bot = z.req('POST', 'bots', dict(name='驗收-備用', provider='codex', model='zz-no-such-model', fallbacks=['claude']))
    job = z.ask(bot['id'], '只回覆「備用模型正常」。')
    out = {'備用模型：主要模型失敗時接手': (job.get('status') == 'completed' and (job.get('fallback') or {}).get('provider') == 'claude', str(job.get('error') or job.get('fallback') or job.get('status'))[:100])}
    stopper = z.req('POST', 'bots', dict(name='驗收-停止', provider='codex'))
    sent = z.req('POST', 'chat', dict(botId=stopper['id'], content='請寫一篇三千字的文章，主題是海洋。'))
    time.sleep(4)
    z.req('POST', 'jobs/%s/cancel' % sent.get('jobId'), {})
    end = time.time() + 30; job = {}
    while time.time() < end:
        job = z.req('GET', 'jobs/' + str(sent.get('jobId')))
        if job.get('status') != 'running': break
        time.sleep(1)
    out['停止回覆'] = (job.get('status') == 'cancelled', str(job.get('status')))
    return out


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--save'); parser.add_argument('--compare'); parser.add_argument('--port', type=int, default=8788)
    args = parser.parse_args()
    results, started = {}, time.time()
    with tempfile.TemporaryDirectory() as directory:
        folder = pathlib.Path(directory); z = Zook(folder, args.port)
        try:
            z.req('PATCH', 'settings', dict(permissionMode='auto', onboarded=True))
            with concurrent.futures.ThreadPoolExecutor(8) as pool:
                jobs = [pool.submit(check_provider, z, p) for p in PROVIDERS] + [pool.submit(check_schedules, z, folder), pool.submit(check_group, z), pool.submit(check_fallback_and_stop, z)]
                for job in jobs:
                    try: results.update(job.result())
                    except Exception as exc: results['檢查本身出錯：%s' % type(exc).__name__] = (False, str(exc)[:120])
            try: results.update(check_approval(z))  # changes the permission mode, so it runs alone
            except Exception as exc: results['檢查本身出錯：核准'] = (False, str(exc)[:120])
            quota = (z.req('GET', 'state').get('quota') or {}).get('claude') or {}
            results['Claude 額度資訊（從回覆取得）'] = (bool(quota.get('windows')), '視窗數 %d' % len(quota.get('windows') or []))
        finally: z.close()
    for name, (ok, detail) in results.items(): print('%s  %s%s' % ('略過' if ok is None else '通過' if ok else '失敗', name, '' if ok else '：' + detail))
    failed = [n for n, (ok, _) in results.items() if ok is False]; skipped = [n for n, (ok, _) in results.items() if ok is None]
    print('\n%d 項通過，%d 項失敗，%d 項略過，用時 %d 秒' % (len(results) - len(failed) - len(skipped), len(failed), len(skipped), time.time() - started))
    if args.save: pathlib.Path(args.save).write_text(json.dumps({n: ok for n, (ok, _) in results.items()}, ensure_ascii=False, indent=1), encoding='utf-8')
    worse = []
    if args.compare:
        base = json.loads(pathlib.Path(args.compare).read_text(encoding='utf-8'))
        worse = [n for n, ok in base.items() if ok and results.get(n, (False,))[0] is False]  # a skipped check is neither better nor worse
        print('和基準相比：' + ('沒有變差' if not worse else '變差的有 ' + '、'.join(worse)))
        sys.exit(1 if worse else 0)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
