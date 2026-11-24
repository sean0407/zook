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
# - Zook's own key lives in the macOS Keychain (one per Mac, made the first time) and never leaves Zook. Each run gets two secrets
#   made from it and a random salt kept with the reply: the CLI's tool token and the run's control key. So a later Zook can make
#   them again, and one run's secrets are no use for another. No secret is sent over a connection: requests are signed with
#   them (nonce and time), answers carry a proof over that nonce (runner.py). Group and task replies, and Zook's own internal
#   ones, still stop when Zook closes.
import hmac
import http.client
import urllib.parse
import select
import socket
import stat

RUNNER_SCRIPT = pathlib.Path(__file__).with_name('runner.py')  # __file__ is backend/server.py in this namespace
RUNNER_KEY_SERVICE = 'Zook runner key'  # its own Keychain service: never mistaken for an account's API key
RUNNER_VERSION = 2
BG_BEGAN = time.time()  # when this Zook started: a call signed before then was meant for an earlier one


def bg_sign(key, *parts):
    return hmac.new(key.encode(), b'\n'.join(p if isinstance(p, bytes) else str(p).encode() for p in parts), 'sha256').hexdigest()


def _bg_key_read():
    """('ok', key), ('missing', '') or ('error', ''): a Keychain that cannot be read right now is never taken for an empty one."""
    folder = os.environ.get('ZOOK_SECRETS_DIR')
    if folder:
        try: return 'ok', (pathlib.Path(folder) / 'runner-key').read_text().strip()
        except FileNotFoundError: return 'missing', ''
        except OSError: return 'error', ''
    try: p = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', RUNNER_KEY_SERVICE, '-a', 'runner', '-w'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired): return 'error', ''
    value = p.stdout.decode('utf-8', 'replace').strip()
    return ('ok', value) if p.returncode == 0 and value else ('missing', '') if p.returncode == 44 else ('error', '')


def _bg_key_make(value):
    """A new key, on stdin only (security -i); never replaces one that is there."""
    folder = os.environ.get('ZOOK_SECRETS_DIR')
    if folder:
        fd = os.open(str(pathlib.Path(folder) / 'runner-key'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f: f.write(value)
        return
    subprocess.run(['/usr/bin/security', '-i'], input=('add-generic-password -s "%s" -a runner -w %s\n' % (RUNNER_KEY_SERVICE, value)).encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


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
        state, key = _bg_key_read()
        if state == 'missing':
            try: _bg_key_make(secrets.token_urlsafe(32))
            except (OSError, subprocess.TimeoutExpired): pass
            state, key = _bg_key_read()
        if state != 'ok': key = ''
    key = key or secrets.token_urlsafe(32)  # no Keychain: replies still run apart, they just cannot be taken up after a restart
    store.__dict__['_bg_key'] = key
    return key


def bg_secret(store, kind, name, salt):
    """One run's secret (kind 'worker' or 'control'), made again the same from Zook's key, the run's folder name and salt."""
    return bg_sign(bg_key(store), 'run', kind, name, salt)


def bg_token(app, job, name=None):
    """Lock held, before the CLI's tool token is made. The token for a reply that runs (or ran) under a runner, or None: taken up
    after a restart, the one its CLI already has; a new run, a fresh salt kept with the reply."""
    store = app.store; known = job.get('runner') or {}
    if job.get('reattach') and known.get('dir'): return bg_secret(store, 'worker', known['dir'], str(known.get('salt') or ''))
    if not bg_on(store) or not bg_fits(job): return None
    if name: return bg_secret(store, 'worker', name, '')  # a kept CLI: its name is new and random already
    job['runnerSalt'] = secrets.token_hex(8)
    return bg_secret(store, 'worker', job['id'], job['runnerSalt'])


def bg_signed(app, headers, token, raw, path):
    """Whether a tool call is signed with this token for this very address (Zook's port and the path), once and recently."""
    nonce, when = headers.get('X-Zook-Nonce') or '', headers.get('X-Zook-Time') or ''
    target = '%d%s' % (app.server_address[1], path)
    if not token or not hmac.compare_digest(headers.get('X-Zook-Sig') or '', bg_sign(token, 'call', nonce, when, target, raw)): return False
    try: when = int(when)
    except ValueError: return False
    now = time.time(); seen = app.__dict__.setdefault('bg_nonces', {}); began = BG_BEGAN
    # Signed before this Zook started: it was for an earlier one (the runner signs a held call again when it sends it).
    if not re.fullmatch(r'[0-9a-f]{32}', nonce) or abs(now - when / 1000) > 300 or when / 1000 < began or nonce in seen: return False  # milliseconds
    for old in [n for n, t in seen.items() if now - t > 900]: del seen[old]
    seen[nonce] = now; return True


def bg_worker(handler, ident):
    """(worker, job, body) for a tool call that proves it holds the reply's token (signed, or the token itself as before), else
    None. Read before the store lock is taken, so the time the call may wait is counted from when it came."""
    app = handler.server; bg_left(handler)
    try: size = int(handler.headers.get('Content-Length') or 0)
    except ValueError: size = 0
    raw = handler.rfile.read(size) if 0 < size <= MAX_BODY else b''
    auth = handler.headers.get('Authorization', '')
    path = urllib.parse.urlsplit(handler.path).path
    check = lambda token: bool(token) and (bg_signed(app, handler.headers, token, raw, path) or hmac.compare_digest(auth, 'Bearer ' + token))
    with app.store.lock:
        if ident.startswith('live-'):  # a CLI kept open between messages: the reply it is answering right now
            worker, job = live_worker(app, ident, check); token = getattr(app.__dict__.get('live_ids', {}).get(ident), 'token', None)
        else:
            worker = app.workers.get(ident); job = app.store.find('jobs', ident); token = (worker or {}).get('token')
            worker = worker if worker and check(token) else None
        if not (worker and job and job['status'] == 'running'): return None
    me = threading.current_thread()
    if (me.zook_deadline and time.monotonic() >= me.zook_deadline) or client_gone(handler.connection): raise ValueError('呼叫的 CLI 已不再等待。')  # nothing is done for it
    me.zook_token = token  # its answer is proved with it (bg_answer)
    try: body = json.loads(raw)
    except ValueError: raise ValueError('無效或過大的 JSON。')
    if not isinstance(body, dict): raise ValueError('無效或過大的 JSON。')
    handler.last_body = body
    return worker, job, body


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
    def __init__(self, folder, info, key, runner=None, offset=0, salt='', started=''):
        self.folder, self.key, self.runner, self.salt, self.started = pathlib.Path(folder), key, runner, salt, started  # key: this run's control key
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
            gone = self.runner.poll() is not None if self.runner else not runner_alive(self.folder, self.runner_pid, self.started)
            if gone and not (self.folder / 'exit').exists() and not pid_alive(self.pid): self.returncode = -9  # ended by force, with its CLI
        return self.returncode

    def wait(self, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if end is not None and time.monotonic() >= end: raise subprocess.TimeoutExpired('zook-runner', timeout)
            time.sleep(0.05)
        return self.returncode

    def control(self, value):
        """Signed with the runner key (the key itself is never sent); the answer must prove it came from the runner."""
        body, nonce, when = json.dumps(value).encode(), secrets.token_hex(16), str(int(time.time() * 1000))
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.request('POST', '/control', body, {'Content-Type': 'application/json', 'X-Zook-Nonce': nonce, 'X-Zook-Time': when, 'X-Zook-Sig': bg_sign(self.key, 'control', nonce, when, self.folder.name, body)})
            response = conn.getresponse(); data = response.read(65536)
            if response.status != 200 or not hmac.compare_digest(response.getheader('X-Zook-Proof') or '', bg_sign(self.key, 'runner', nonce, response.status, data)): raise OSError('not the runner')
            return json.loads(data or b'{}')
        finally: conn.close()

    def signal(self, sig):
        """Through the runner, which ends the CLI's whole group while the CLI is not collected yet (so its number is still its own).
        A runner that cannot be reached is asked to end it with SIGTERM, when it is still that runner (pid and start time). The
        CLI's own number is never signalled from here. Nothing once it ended."""
        if self.poll() is not None: return False
        try: return bool(self.control({'action': 'signal', 'sig': int(sig)}).get('sent'))
        except (OSError, ValueError, http.client.HTTPException): return bg_kill_runner(self.folder, self.runner_pid, self.started)

    def size(self):
        try: return (self.folder / 'out').stat().st_size
        except OSError: return 0


def pid_alive(pid):
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except OSError: return True


def runner_alive(folder, pid, started=''):
    """The runner of this folder is still running: that pid, started when it was (a recycled pid has another start time), for
    this folder."""
    return runner_state(folder, pid, started) == 'yes'


def runner_state(folder, pid, started):
    """'yes' (that runner), 'no' (gone, or the number is someone else's now) or 'unsure' (alive, but ps could not say who)."""
    if not pid_alive(pid): return 'no'
    when, command = process_started(pid)
    if not when: return 'unsure'
    return 'yes' if started and when == started and str(folder) in (command or '') else 'no'


def bg_kill_runner(folder, pid, started):
    """Ask a runner that cannot be reached to stop: its SIGTERM ends its CLI's whole group (runner.py). Only that very runner."""
    if not runner_alive(folder, pid, started): return False
    try: os.kill(int(pid), signal.SIGTERM); return True
    except OSError: return False


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
    base = store.dir / 'runs'
    if not bg_on(store) or not bg_fits(job) or not RUNNER_SCRIPT.is_file() or base.is_symlink() or not base.is_dir():
        return subprocess.Popen(args, stdin=subprocess.PIPE if use_stdin or live else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, cwd=str(cwd), env=dict(env, PWD=str(cwd)))
    os.chmod(str(base), 0o700)
    folder = base / (name or job['id'])
    if os.path.lexists(str(folder)): bg_remove(folder)
    folder.mkdir(mode=0o700); (folder / '.zook-run').write_text('')  # Zook's own: the only kind of folder bg_sweep removes
    url = env.get('ZOOK_WORKER_URL') or ''; long = bool(job.get('long')); salt = '' if live else (job.pop('runnerSalt', '') or secrets.token_hex(8))
    cfg = dict(dir=str(folder), args=[str(a) for a in args], cwd=str(cwd), env=dict(env, PWD=str(cwd)), stdin=bool(use_stdin or live), live=live,
               key=bg_secret(store, 'control', folder.name, salt), token=env.get('ZOOK_WORKER_TOKEN') or '', ident=url.rsplit('/', 1)[-1] if url else '', url=url,
               quiet=LONG_JOB_TIMEOUT if long else agy_quiet(kind, JOB_TIMEOUT), limit=LONG_JOB_TIMEOUT if long else max(JOB_HARD_TIMEOUT, JOB_TIMEOUT),
               wait=int(env.get('ZOOK_TOOL_WAIT') or tool_wait(False)), hold=int(env.get('ZOOK_TOOL_WAIT') or tool_wait(False)) + 60, zook_pid=os.getpid(),
               max_out=MAX_CLI_OUTPUT * (16 if live else 1) + 65536)  # a kept CLI's file holds every reply it gave
    log = os.open(str(folder / 'log'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try: runner = subprocess.Popen([sys.executable, '-I', str(RUNNER_SCRIPT), str(folder)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True, cwd=str(folder))
    finally: os.close(log)
    # On disk before the runner gets its settings, so before the CLI can do anything: a crash from here on finds the run again.
    started = process_started(runner.pid)[0]
    if not started:  # it could not be told apart from another process later: this reply runs the usual way instead
        runner.kill(); runner.wait(); bg_remove(folder)
        return subprocess.Popen(args, stdin=subprocess.PIPE if use_stdin or live else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, cwd=str(cwd), env=dict(env, PWD=str(cwd)))
    job['runner'] = dict(dir=folder.name, salt=salt, live=bool(live), offset=0, cost=0.0, pid=runner.pid, started=started); store.save()
    def send():
        try: runner.stdin.write(json.dumps(cfg, ensure_ascii=False).encode('utf-8') + b'\n'); runner.stdin.flush()
        except (OSError, ValueError): pass
    threading.Thread(target=send, daemon=True).start()  # a runner that does not read never holds Zook here: the time below still runs
    end = time.monotonic() + 15
    while True:
        info = bg_info(folder)
        if info: break
        if (folder / 'exit').exists() or runner.poll() is not None or time.monotonic() > end:
            # The CLI may have started: the runner ends it (SIGTERM), or its placeholder does once the runner is gone.
            try: runner.send_signal(signal.SIGTERM); runner.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try: runner.kill(); runner.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired): pass
            job['mayHaveActed'] = not (folder / 'exit').exists() or bool(bg_info(folder))  # not tried on another model unless it never started
            bg_remove(folder); job.pop('runner', None); raise FileNotFoundError('無法啟動 CLI。')
        time.sleep(0.01)
    return HostedProc(folder, info, cfg['key'], runner, 0, salt, started)


def bg_note(store, job, proc, live, cost=0.0):
    """Lock held. What a later Zook needs to take this reply up again. A kept CLI's output starts where this reply's does, and
    what it reports it has cost so far is counted for the replies before."""
    if not isinstance(proc, HostedProc): job.pop('runner', None); job.pop('runnerSalt', None); return
    job['runner'] = dict(dir=proc.folder.name, salt=proc.salt, live=bool(live), offset=proc.size() if live else 0, cost=float(cost or 0), pid=proc.runner_pid, started=proc.started)


def bg_remove(folder):
    """Only a run folder Zook made (its mark inside), never through a link."""
    folder = pathlib.Path(folder)
    if folder.is_symlink(): folder.unlink(); return
    if bg_ours(folder): shutil.rmtree(str(folder), ignore_errors=True)


def bg_ours(folder):
    """A real folder (not a link) of this user, with Zook's mark in it as a real file (not a link to one)."""
    try: here, mark = os.lstat(str(folder)), os.lstat(str(pathlib.Path(folder) / '.zook-run'))
    except OSError: return False
    return stat.S_ISDIR(here.st_mode) and stat.S_ISREG(mark.st_mode) and here.st_uid == mark.st_uid == os.getuid()


def bg_folder(store, job):
    name = str((job.get('runner') or {}).get('dir') or '')
    return store.dir / 'runs' / name if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name) else None


def bg_alive(store, job):
    """At start: whether this reply's runner is still there (or ended with its output kept), so the reply can be taken up."""
    folder = bg_folder(store, job); info = bg_info(folder) if folder else None; known = job.get('runner') or {}
    if not folder or not known.get('pid'): return False
    if info and info['runner'] != known['pid']: return False
    if info and (folder / 'exit').exists(): return True
    # Running, or still starting its CLI (no info yet). Unsure (ps could not say) counts too: taking it up proves who it is
    # (only that run's runner can answer its signed control requests), while starting it again could run the work twice.
    if runner_state(folder, known['pid'], known.get('started') or '') != 'no': return True
    return bool(bg_info(folder)) and (folder / 'exit').exists()  # it wrote how it ended and left just now


def bg_adopt(app, job):
    """Lock held. The CLI of a reply that is being taken up. One that ended meanwhile is only read. A running one is told where
    Zook is now, once it has proved it is that reply's runner (off to the side: the lock is held here)."""
    store = app.store; folder = bg_folder(store, job); info = bg_info(folder) if folder else None; known = job['runner']
    job.pop('reattach', None)
    if not bg_alive(store, job): job['mayHaveActed'] = True; raise FileNotFoundError('無法接回背景中的回覆。')
    end = time.monotonic() + 10
    while not info and time.monotonic() < end: time.sleep(0.1); info = bg_info(folder)  # a runner still starting its CLI
    if not info:  # it never got there: ended, and the reply is not tried again elsewhere (the CLI may have begun)
        bg_kill_runner(folder, known['pid'], known.get('started') or ''); job['mayHaveActed'] = True
        raise FileNotFoundError('無法接回背景中的回覆。')
    salt = str(known.get('salt') or '')
    proc = HostedProc(folder, info, bg_secret(store, 'control', folder.name, salt), None, int(known.get('offset') or 0), salt, known.get('started') or ''); proc.live = bool(known.get('live'))
    if proc.poll() is None and app.workers.get(job['id']):
        attach = {'action': 'attach', 'url': 'http://127.0.0.1:%d/api/worker/%s' % (app.server_address[1], job['id']), 'pid': os.getpid()}  # no secret in it
        def tell():
            for _ in range(10):
                if proc.poll() is not None: return
                try: proc.control(attach); return
                except (OSError, ValueError, http.client.HTTPException): time.sleep(1)
            with store.lock: job['attachFailed'] = True  # its output is still read; its tool calls cannot reach this Zook
        threading.Thread(target=tell, daemon=True).start()
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


def bg_turn(proc, kind, feed, job):
    """For a kept CLI that was taken up: its reply, read from where it started, ends with its answer (as a kept CLI's would).
    A message the user added during it may not have been read before Zook closed: the reply then says so."""
    if not isinstance(proc, HostedProc) or not proc.__dict__.get('live'): return None
    cli = AdoptedCli(proc, kind); cli.cost = float((job.get('runner') or {}).get('cost') or 0)
    turn = LiveTurn(cli, MAX_CLI_OUTPUT, feed); turn.echoed = True  # its message was read before Zook closed
    turn.unsure = bool(job.get('added'))
    with cli.lock: cli.turn, cli.job_id = turn, 'adopted'
    for target in (cli._write, cli._read_err, cli._read): threading.Thread(target=target, daemon=True).start()
    return turn


def bg_closing(app):
    """Lock held, Zook is closing. The replies that go on under their runner (their ids). An approval or a question waiting for
    one of them is let go unanswered: the runner asks again once Zook is back (bg_answer), so nothing is decided on the way out."""
    store = app.store
    if not bg_on(store):  # switched off: a reply not taken up yet is still taken up next time (its answer may be done), never started again
        pending = {j['id'] for j in store.data['jobs'] if j['status'] == 'running' and j.get('reattach') and j.get('runner')}
        app.detaching = pending; return pending
    spare = {j['id'] for j in store.data['jobs'] if j['status'] == 'running' and j.get('reattach') and j.get('runner') and bg_fits(j)}  # not taken up yet: still for next time
    for job_id, proc in list(app.processes.items()):
        job = store.find('jobs', job_id)
        hosted = getattr(getattr(proc, 'cli', None), 'proc', None) or proc
        if job and job['status'] == 'running' and job.get('runner') and isinstance(hosted, HostedProc) and bg_fits(job): spare.add(job_id)
    app.detaching = spare  # a card asked for from now on is let go at once (bg_hold)
    released = 0
    for job_id in spare:
        job = store.find('jobs', job_id); job['detachedAt'] = NOW()
        for item, events in [(a, app.approval_events) for a in job.get('approvals') or []] + [(q, app.__dict__.get('question_events', {})) for q in job.get('questions') or []]:
            if item.get('status') != 'pending': continue
            item.update(status='expired', withdrawn=True, detached=True); event = events.get(item['id'])
            if event: event.set(); released += 1
    app.bg_released = released
    return spare


def bg_settle(app, spare):
    """Outside the lock: give the calls let go above a moment to tell their runner to ask again."""
    end = time.monotonic() + 3
    while app.__dict__.get('bg_answered', 0) < app.__dict__.get('bg_released', 0) and time.monotonic() < end: time.sleep(0.05)
    return spare


def bg_mark(item):
    """An approval or a question let go because Zook is closing: the tool call that waited for it is to be asked again."""
    if item.get('detached'): threading.current_thread().zook_retry = True


def bg_hold(app, job_id, item):
    """Lock held, as a card is put up. True when Zook is already closing for this reply: the card is let go at once."""
    if job_id not in app.__dict__.get('detaching', ()): return False
    item.update(status='expired', withdrawn=True, detached=True); bg_mark(item)
    app.bg_released = app.__dict__.get('bg_released', 0) + 1
    return True


def bg_await(event, seconds):
    """Wait for a card's answer: no longer than the CLI still waits for this call (its runner said how long, counted from when
    the call came), and not once the CLI has stopped waiting (its connection closed): the card then expires."""
    me = threading.current_thread().__dict__; end = time.monotonic() + seconds
    if me.get('zook_deadline'): end = min(end, me['zook_deadline'])
    conn = me.get('zook_conn')
    while True:
        left = end - time.monotonic()
        if left <= 0 or event.wait(min(1, left)): break
        if conn is not None and client_gone(conn): return True  # the CLI gave up: the card is withdrawn
    # Answered or out of time: the answer counts only while the CLI still waits for it.
    return bool(me.get('zook_deadline') and time.monotonic() >= me['zook_deadline']) or (conn is not None and client_gone(conn))


def client_gone(sock):
    try:
        readable = select.select([sock], [], [], 0)[0]
        return bool(readable) and not sock.recv(1, socket.MSG_PEEK)
    except (OSError, ValueError): return True


def bg_left(handler):
    """Read as each tool call comes: how long its CLI still waits for it (from its runner), and its connection."""
    try: left = int(handler.headers.get('X-Zook-Left') or 0)
    except ValueError: left = 0
    me = threading.current_thread(); me.zook_deadline = time.monotonic() + max(1, left) if left > 0 else None; me.zook_conn = handler.connection


def bg_answer(handler, result):
    """A tool call's answer to the CLI, or (let go while closing) 503 retry, which tells its runner to ask the next Zook. A runner
    is shown that the answer is this Zook's (X-Zook-Proof): another program on an old address cannot answer in its place."""
    status = 200
    if threading.current_thread().__dict__.pop('zook_retry', False):
        app = handler.server; app.bg_answered = app.__dict__.get('bg_answered', 0) + 1; status, result = 503, {'retry': True}
    raw = json.dumps(result, ensure_ascii=False).encode(); nonce = handler.headers.get('X-Zook-Nonce') or ''
    token = threading.current_thread().__dict__.pop('zook_token', None)
    note_request(handler, status, result)
    handler.send_response(status); handler.send_header('Content-Type', 'application/json; charset=utf-8'); handler.send_header('Content-Length', str(len(raw))); handler.send_header('Cache-Control', 'no-store')
    if token and re.fullmatch(r'[0-9a-f]{32}', nonce): handler.send_header('X-Zook-Proof', bg_sign(token, 'answer', nonce, status, raw))
    handler.end_headers(); handler.wfile.write(raw)


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
    """The folders of runs that are over and no longer needed (a kept CLI's while it is open, a running reply's, stay). Decided
    and removed under the store lock, which a new run's folder is made and recorded under."""
    store = app.store; base = store.dir / 'runs'
    try: here = os.lstat(str(base))
    except OSError: return 0
    if not stat.S_ISDIR(here.st_mode) or here.st_uid != os.getuid() or stat.S_IMODE(here.st_mode) != 0o700: return 0  # only Zook's own private folder
    guard = app.__dict__.get('live_lock') or threading.Lock(); gone = 0
    try: base_fd = os.open(str(base), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)  # this very folder, even if the name is replaced
    except OSError: return 0
    try:
        held = os.fstat(base_fd)
        if (held.st_dev, held.st_ino) != (here.st_dev, here.st_ino): return 0
        return _bg_sweep_in(app, store, base, base_fd, guard)
    finally: os.close(base_fd)


def _remove_at(dir_fd, name):
    """Remove name inside an open folder, never following a link."""
    st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    if not stat.S_ISDIR(st.st_mode): os.unlink(name, dir_fd=dir_fd); return
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        for inner in os.listdir(fd): _remove_at(fd, inner)
    finally: os.close(fd)
    os.rmdir(name, dir_fd=dir_fd)


def _ours_at(dir_fd, name):
    """bg_ours, inside an open folder: a real folder of this user with Zook's mark as a real file, no link followed."""
    try:
        here = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if not stat.S_ISDIR(here.st_mode) or here.st_uid != os.getuid(): return False
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
        try: mark = os.stat('.zook-run', dir_fd=fd, follow_symlinks=False)
        finally: os.close(fd)
    except OSError: return False
    return stat.S_ISREG(mark.st_mode) and mark.st_uid == os.getuid()


def _bg_sweep_in(app, store, base, base_fd, guard):
    gone = 0
    with store.lock, guard:
        used = {(j.get('runner') or {}).get('dir') for j in store.data['jobs'] if j['status'] == 'running'} | {c.ident for c in (app.__dict__.get('lives') or {}).values()}
        for name in os.listdir(base_fd):
            if name in used or not re.fullmatch(r'(live-)?[0-9a-f]{24,32}', name) or not _ours_at(base_fd, name): continue
            folder = base / name; info = bg_info(folder)
            if info and not (folder / 'exit').exists() and (pid_alive(info['runner']) and str(folder) in (process_started(info['runner'])[1] or '')): continue  # still running
            if not info and time.time() - os.stat(name, dir_fd=base_fd, follow_symlinks=False).st_mtime < 60: continue  # still starting
            try: _remove_at(base_fd, name); gone += 1
            except OSError: pass
    return gone


def bg_busy(app):
    """Whether an update has to wait: a reply is running that would stop with Zook."""
    return any(j.get('status') == 'running' and not (bg_on(app.store) and j.get('runner') and bg_fits(j)) for j in app.store.data['jobs'])


def bg_stop(app, job):
    """A reply that was to be taken up but will not be (stopped, or it failed before its CLI was reached): its CLI is ended.
    False when it could not be told whether that worked (the runner may still be there)."""
    if not job.get('reattach'): return True
    store = app.store
    with store.lock:
        job.pop('reattach', None); folder = bg_folder(store, job); info = bg_info(folder) if folder else None; known = job.get('runner') or {}
    if folder and info and (folder / 'exit').exists(): return False  # it finished: its answer is on disk, to be read next time
    if not folder or not known.get('pid'): return True
    state = runner_state(folder, known['pid'], known.get('started') or '')
    if state != 'yes': return state == 'no' and not (bg_info(folder) and (folder / 'exit').exists())  # unsure: kept for next time
    if not info or info['runner'] != known['pid']: return bg_kill_runner(folder, known['pid'], known.get('started') or '')  # still starting: it never starts its CLI
    salt = str(known.get('salt') or '')
    return HostedProc(folder, info, bg_secret(store, 'control', folder.name, salt), None, 0, salt, known.get('started') or '').signal(signal.SIGTERM)


def bg_end(processes):
    """Zook is closing and these replies stop with it. A CLI under a runner is ended through its runner (never by its number);
    one Zook started itself, by its process group."""
    hosted = lambda p: isinstance(getattr(getattr(p, 'cli', None), 'proc', None) or p, HostedProc)
    for proc in processes:
        if hosted(proc): signal_group(proc, signal.SIGTERM); continue
        try: os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError: pass
    for proc in processes:
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: pass
        if hosted(proc): continue  # its runner ends what is left of the group
        try: os.killpg(proc.pid, signal.SIGKILL)  # the leader may exit before its descendants
        except ProcessLookupError: pass
