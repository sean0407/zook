# 背景執行 (#35): a reply's CLI runs under backend/runner.py, a small program of its own, so closing Zook or installing an update
# does not stop it. Loaded by backend/server.py into one shared namespace.
#
# - Zook starts the runner and reads the CLI's output from the files the runner writes (HostedProc looks like the process Zook
#   used to start itself, so the code that waits for a reply, kept CLIs included, is unchanged).
# - Closing Zook with 「結束時繼續在背景跑」 on: a one-to-one reply under a runner is left running and stays 進行中 in the saved
#   data. An action waiting for approval is let go unanswered (the runner asks again later); nothing is approved on the way out.
# - Opening Zook again: such a reply is taken up where it is. Its CLI's output so far is read, then followed as it grows; tool
#   calls reach the new Zook through the runner; a reply that ended meanwhile is simply finished. A reply whose runner is gone
#   (the Mac restarted, it was ended by force) is left to 接著做 (resume.py).
# - The runner's key lives in the macOS Keychain (one per Mac, made the first time); Zook's tool token for a reply only in memory
#   and in the CLI's environment. Group and task replies, and Zook's own internal ones, still stop when Zook closes.
RUNNER_SCRIPT = pathlib.Path(__file__).with_name('runner.py')  # __file__ is backend/server.py in this namespace
RUNNER_KEY_ID = '7a35c0de' * 4  # the Keychain entry (accounts.py's own service) of the runner key
RUNNER_VERSION = 1


def bg_on(store): return store.data['settings'].get('backgroundRuns') is not False


def bg_fits(job):
    """Only a reply in a one-to-one conversation is left running: a group's and a task's flow live in Zook itself."""
    return bool(job.get('chatId')) and not job.get('groupId') and not job.get('internal')


def bg_key(store):
    """The key Zook uses to reach a runner, also after a restart. Zook's own data folder keeps it in the Keychain; a test's folder
    keeps it in memory, or in its own secrets folder (ZOOK_SECRETS_DIR)."""
    cached = store.__dict__.get('_bg_key')
    if cached: return cached
    real = str(store.dir).startswith(str(pathlib.Path.home() / 'Library' / 'Application Support') + os.sep)
    key = ''
    if real or os.environ.get('ZOOK_SECRETS_DIR'):
        key = secret_get(RUNNER_KEY_ID)
        if not key:
            try: secret_set(RUNNER_KEY_ID, secrets.token_urlsafe(32)); key = secret_get(RUNNER_KEY_ID)
            except (ValueError, RuntimeError, OSError): key = ''
    key = key or secrets.token_urlsafe(32)  # no Keychain: replies still run apart, they just cannot be taken up after a restart
    store.__dict__['_bg_key'] = key
    return key


class _NoInput:
    def write(self, data): return len(data)
    def flush(self): pass
    def close(self): pass


class TailFile:
    """The CLI's output as the runner writes it, read like the pipe it used to be: a read waits for more until the run has ended."""
    def __init__(self, path, owner, offset=0):
        self.path, self.owner, self.pos, self.f, self.closed, self.buf = path, owner, offset, None, False, b''

    def read1(self, n=65536):
        while not self.closed:
            ended = self.owner.poll() is not None
            if self.f is None:
                try: self.f = open(str(self.path), 'rb'); self.f.seek(self.pos)
                except OSError: self.f = None
            data = self.f.read(n) if self.f else b''
            if data or ended: return data
            time.sleep(0.05)
        return b''

    def readline(self, limit=-1):
        while True:
            at = self.buf.find(b'\n')
            if at >= 0 or 0 < limit <= len(self.buf):
                cut = at + 1 if at >= 0 else limit
                if limit > 0: cut = min(cut, limit)
                line, self.buf = self.buf[:cut], self.buf[cut:]; return line
            chunk = self.read1()
            if not chunk: line, self.buf = self.buf, b''; return line
            self.buf += chunk

    def close(self):
        self.closed = True
        try:
            if self.f: self.f.close()
        except OSError: pass


class HostedProc:
    """A CLI under a runner, with the parts of a subprocess.Popen that Zook uses. pid is the CLI's own (its process group)."""
    def __init__(self, folder, info, key, runner=None, offset=0):
        self.folder, self.key, self.runner = pathlib.Path(folder), key, runner
        self.pid, self.runner_pid, self.port = int(info['cli']), int(info['runner']), int(info['port'])
        self.returncode, self.stopped, self.checked = None, '', 0.0
        self.stdin = runner.stdin if runner else _NoInput()
        self.stdout, self.stderr = TailFile(self.folder / 'out', self, offset), TailFile(self.folder / 'err', self)

    def poll(self):
        if self.returncode is not None: return self.returncode
        if self.runner: self.runner.poll()  # collected, so it does not stay behind as a zombie
        try: ended = json.loads((self.folder / 'exit').read_text())
        except (OSError, ValueError): ended = None
        if isinstance(ended, dict):
            self.returncode, self.stopped = int(ended.get('code') if isinstance(ended.get('code'), int) else 1), str(ended.get('stopped') or '')
        elif time.monotonic() - self.checked > 1:
            self.checked = time.monotonic()
            gone = self.runner.poll() is not None if self.runner else not pid_alive(self.runner_pid)  # who it is was checked when it was taken up
            if gone and not (self.folder / 'exit').exists() and not pid_alive(self.pid): self.returncode = -9  # ended by force, with its CLI
        return self.returncode

    def wait(self, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if end is not None and time.monotonic() >= end: raise subprocess.TimeoutExpired('zook-runner', timeout)
            time.sleep(0.05)
        return self.returncode

    def control(self, value):
        req = urllib.request.Request('http://127.0.0.1:%d/control' % self.port, data=json.dumps(value).encode(), headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as response: return json.loads(response.read(65536) or b'{}')

    def size(self):
        try: return (self.folder / 'out').stat().st_size
        except OSError: return 0


def pid_alive(pid):
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except OSError: return True


def runner_alive(folder, pid):
    """The runner of this folder is still running: that pid, started for this folder (a recycled pid has another command line)."""
    if not pid_alive(pid): return False
    return str(folder) in (process_started(pid)[1] or '')


def bg_info(folder):
    try: info = json.loads((pathlib.Path(folder) / 'info').read_text())
    except (OSError, ValueError): return None
    ok = isinstance(info, dict) and info.get('v') == RUNNER_VERSION and all(isinstance(info.get(k), int) and not isinstance(info.get(k), bool) for k in ('cli', 'runner', 'port'))
    return info if ok else None


def bg_popen(app, job, args, cwd, env, use_stdin, kind, live=False, name=None):
    """Lock held. The CLI for this reply: under a runner when it may go on while Zook is closed, otherwise started as before.
    A reply being taken up after a restart gets its running CLI back instead."""
    store = app.store
    if job.get('reattach') and job.get('runner'): return bg_adopt(app, job)
    if not bg_on(store) or not bg_fits(job) or not RUNNER_SCRIPT.is_file():
        return subprocess.Popen(args, stdin=subprocess.PIPE if use_stdin or live else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, cwd=str(cwd), env=dict(env, PWD=str(cwd)))
    base = store.dir / 'runs'; base.mkdir(mode=0o700, exist_ok=True); os.chmod(str(base), 0o700)
    folder = base / (name or job['id'])
    if folder.exists(): shutil.rmtree(str(folder), ignore_errors=True)
    folder.mkdir(mode=0o700)
    url = env.get('ZOOK_WORKER_URL') or ''; long = bool(job.get('long'))
    cfg = dict(dir=str(folder), args=[str(a) for a in args], cwd=str(cwd), env=dict(env, PWD=str(cwd)), stdin=bool(use_stdin or live), live=live,
               key=bg_key(store), token=env.get('ZOOK_WORKER_TOKEN') or '', ident=url.rsplit('/', 1)[-1] if url else '', url=url,
               quiet=LONG_JOB_TIMEOUT if long else agy_quiet(kind, JOB_TIMEOUT), limit=LONG_JOB_TIMEOUT if long else max(JOB_HARD_TIMEOUT, JOB_TIMEOUT),
               hold=int(env.get('ZOOK_TOOL_WAIT') or tool_wait(False)) + 60, max_out=MAX_CLI_OUTPUT + 65536)
    log = os.open(str(folder / 'log'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try: runner = subprocess.Popen([sys.executable, '-I', str(RUNNER_SCRIPT), str(folder)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True, cwd=str(folder))
    finally: os.close(log)
    try: runner.stdin.write(json.dumps(cfg, ensure_ascii=False).encode('utf-8') + b'\n'); runner.stdin.flush()
    except OSError: pass
    end = time.monotonic() + 15
    while True:
        info = bg_info(folder)
        if info: break
        if (folder / 'exit').exists() or runner.poll() is not None or time.monotonic() > end:
            try: os.killpg(runner.pid, signal.SIGKILL)
            except OSError: pass
            shutil.rmtree(str(folder), ignore_errors=True); raise FileNotFoundError('無法啟動 CLI。')
        time.sleep(0.01)
    proc = HostedProc(folder, info, cfg['key'], runner)
    if not live: bg_note(store, job, proc, False)
    return proc


def bg_note(store, job, proc, live):
    """Lock held. What a later Zook needs to take this reply up again. A kept CLI's output starts where this reply's does."""
    if not isinstance(proc, HostedProc): job.pop('runner', None); return
    job['runner'] = dict(dir=proc.folder.name, live=bool(live), offset=proc.size() if live else 0)


def bg_folder(store, job):
    name = str((job.get('runner') or {}).get('dir') or '')
    return store.dir / 'runs' / name if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name) else None


def bg_alive(store, job):
    """At start: whether this reply's runner is still there (or ended with its output kept), so the reply can be taken up."""
    folder = bg_folder(store, job); info = bg_info(folder) if folder else None
    if not info: return False
    return (folder / 'exit').exists() or runner_alive(folder, info['runner'])


def bg_adopt(app, job):
    """Lock held. The running CLI of a reply that is being taken up, told where Zook is now."""
    store = app.store; folder = bg_folder(store, job); info = bg_info(folder) if folder else None
    job.pop('reattach', None)
    if not info: raise FileNotFoundError('無法接回背景中的回覆。')
    proc = HostedProc(folder, info, bg_key(store), None, int(job['runner'].get('offset') or 0)); proc.live = bool(job['runner'].get('live'))
    worker = app.workers.get(job['id'])
    if proc.poll() is None and worker:
        try: proc.control({'action': 'attach', 'url': 'http://127.0.0.1:%d/api/worker/%s' % (app.server_address[1], job['id']), 'token': worker['token']})
        except (OSError, ValueError): pass  # it may have just ended; its output is read either way
    job['adopted'] = True
    return proc


class AdoptedCli(LiveCli):
    """A kept CLI that was answering when Zook closed. It finishes this one reply and is not used again."""
    def __init__(self, proc, kind):
        self.key = self.mark = self.ident = self.token = None; self.kind = kind; self.home = ''
        self.session, self.job_id, self.turn, self.used, self.turns, self.spoiled = '', None, None, time.monotonic(), 0, '已接回'
        self.lock = threading.Lock(); self.err = bytearray(); self.cost = 0.0; self.reading = True
        self.writes = queue.Queue(); self.proc = proc

    def end(self, turn):
        super().end(turn); threading.Thread(target=self.close, daemon=True).start()


def bg_turn(proc, kind, feed):
    """For a kept CLI that was taken up: its reply, read from where it started, ends with its answer (as a kept CLI's would)."""
    if not isinstance(proc, HostedProc) or not proc.__dict__.get('live'): return None
    cli = AdoptedCli(proc, kind)
    turn = LiveTurn(cli, MAX_CLI_OUTPUT, feed); turn.echoed = True  # its message was read before Zook closed
    with cli.lock: cli.turn, cli.job_id = turn, 'adopted'
    for target in (cli._write, cli._read_err, cli._read): threading.Thread(target=target, daemon=True).start()
    return turn


def bg_closing(app):
    """Lock held, Zook is closing. The replies that go on under their runner (their ids). An approval or a question waiting for
    one of them is let go unanswered: the runner asks again once Zook is back (bg_answer), so nothing is decided on the way out."""
    store = app.store
    if not bg_on(store): return set()
    spare = set()
    for job_id, proc in list(app.processes.items()):
        job = store.find('jobs', job_id)
        hosted = getattr(getattr(proc, 'cli', None), 'proc', None) or proc
        if job and job['status'] == 'running' and job.get('runner') and isinstance(hosted, HostedProc) and bg_fits(job): spare.add(job_id)
    released = 0
    for job_id in spare:
        job = store.find('jobs', job_id); job['detachedAt'] = NOW()
        for item, events in [(a, app.approval_events) for a in job.get('approvals') or []] + [(q, app.__dict__.get('question_events', {})) for q in job.get('questions') or []]:
            if item.get('status') != 'pending': continue
            item.update(status='expired', withdrawn=True, detached=True); event = events.get(item['id'])
            if event: event.set(); released += 1
    app.detaching = spare; app.bg_released = released
    return spare


def bg_settle(app, spare):
    """Outside the lock: give the calls let go above a moment to tell their runner to ask again."""
    end = time.monotonic() + 3
    while app.__dict__.get('bg_answered', 0) < app.__dict__.get('bg_released', 0) and time.monotonic() < end: time.sleep(0.05)
    return spare


def bg_mark(item):
    """An approval or a question let go because Zook is closing: the tool call that waited for it is to be asked again."""
    if item.get('detached'): threading.current_thread().zook_retry = True


def bg_answer(handler, result):
    """A tool call's answer to the CLI, or (let go while closing) 503 retry, which tells its runner to ask the next Zook."""
    if threading.current_thread().__dict__.pop('zook_retry', False):
        app = handler.server; app.bg_answered = app.__dict__.get('bg_answered', 0) + 1
        return handler.respond(503, {'retry': True})
    return handler.respond(200, result)


def bg_reattach(app):
    """At start: take up each reply that went on while Zook was closed (Store marked them, bg_alive)."""
    store = app.store
    with store.lock:
        jobs = [j for j in store.data['jobs'] if j.get('reattach') and j['status'] == 'running']
        for job in [j for j in jobs if not (j.get('ran') or [''])[0]]:  # cannot tell which CLI: as if it had been cut off
            job.pop('reattach', None); jobs.remove(job)
            job.update(status='failed', error='服務重新啟動，工作已中斷。'); interrupted_at(job, store.stopped_at); store.finish_message(job, '', 'failed')
        if jobs: store.save()
    for job in jobs: app.start_job(job, '', job['ran'][0], job['ran'][1])
    return len(jobs)


def bg_sweep(app):
    """The folders of runs that are over and no longer needed (a kept CLI's while it is open, a running reply's, stay)."""
    store = app.store; base = store.dir / 'runs'
    if not base.is_dir(): return 0
    with store.lock: used = {(j.get('runner') or {}).get('dir') for j in store.data['jobs'] if j['status'] == 'running'}
    guard = app.__dict__.get('live_lock')
    if guard:
        with guard: used |= {c.ident for c in (app.__dict__.get('lives') or {}).values()}
    gone = 0
    for folder in base.iterdir():
        if folder.name in used or not folder.is_dir(): continue
        info = bg_info(folder)
        if info and not (folder / 'exit').exists() and runner_alive(folder, info['runner']): continue
        if not info and time.time() - folder.stat().st_mtime < 60: continue  # still starting
        shutil.rmtree(str(folder), ignore_errors=True); gone += 1
    return gone


def bg_busy(app):
    """Whether an update has to wait: a reply is running that would stop with Zook."""
    return any(j.get('status') == 'running' and not (bg_on(app.store) and j.get('runner') and bg_fits(j)) for j in app.store.data['jobs'])


def bg_stop(app, job):
    """A reply that was to be taken up but will not be (stopped, or it failed before its CLI was reached): its CLI is ended."""
    if not job.get('reattach'): return
    store = app.store
    with store.lock: job.pop('reattach', None); folder = bg_folder(store, job); info = bg_info(folder) if folder else None
    if not info or not runner_alive(folder, info['runner']): return
    try: HostedProc(folder, info, bg_key(store)).control({'action': 'stop'})
    except (OSError, ValueError):
        try: os.killpg(info['cli'], signal.SIGTERM)
        except OSError: pass
