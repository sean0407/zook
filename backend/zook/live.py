# Keeping a CLI open between the messages of one conversation, so a reply does not begin by starting the CLI again.
# Loaded by backend/server.py into one shared namespace.
#
# Only what a reply would have started anyway is kept: the same program, the same arguments, the same folder and sign-in, and the
# same kind of turn (the user's own, a script's, a redo of a scheduled one). When any of those differ for the next message
# (another model, 先規劃, a new attachment folder, a changed tool list, another origin), the kept CLI is closed and a new one
# started. Every tool call goes to the reply that is running right now, with that reply's own approvals, origin and permission
# mode: the kept CLI holds an address of its own, and Zook looks up which reply it belongs to at each call.
#
# A kept CLI must be silent between messages. If it writes anything, or calls a tool, while no reply is running, it is doing
# something nobody is watching: it is marked and never used again.
try: LIVE_IDLE = max(1.0, float(os.environ.get('ZOOK_LIVE_IDLE') or 600))   # seconds a kept CLI may sit unused
except ValueError: LIVE_IDLE = 600.0
LIVE_MAX = 4      # kept CLIs at one time; the one unused longest makes room
LIVE_KINDS = ('claude',)
LIVE_LINE = 8 * 1024 * 1024  # one line of output; a longer one ends the reply as too large
LIVE_FAILS = 3    # after this many kept CLIs in a row that went away without a word, replies start the CLI the usual way until Zook restarts


def live_on(store): return store.data['settings'].get('keepCli') is not False


def live_able(app, provider):
    """Only a CLI whose own help says it reads messages one after another is kept open. Zook reads that help when it starts
    (live_learn) and whenever the usage page is opened; until it has, replies start the CLI the usual way."""
    with app.store.lock: report = (app.store.data.get('abilityChecks') or {}).get(provider)
    return report is not None and 'live' not in (report.get('missing') or {})


def live_learn(app):
    """At startup, off to the side: find out which installed CLIs can be kept open."""
    def look():
        for provider in LIVE_KINDS:
            try:
                if find_cli(provider): ability_report(app.store, provider)
            except Exception: pass
    threading.Thread(target=look, daemon=True).start()


class LiveLost(Exception):
    """The kept CLI went away before it wrote or did anything for this message: the message is sent again the usual way."""


class LiveCli:
    """One CLI process that stays open and answers one message at a time."""
    def __init__(self, key, args, cwd, env, mark, ident, token):
        self.key, self.mark, self.ident, self.token = key, mark, ident, token
        self.session, self.job_id, self.turn, self.used, self.turns, self.spoiled = '', None, None, time.monotonic(), 0, ''
        self.lock = threading.Lock(); self.err = bytearray(); self.cost = 0.0
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, cwd=str(cwd), env=env)
        for target in (self._read, self._read_err): threading.Thread(target=target, daemon=True).start()

    def alive(self): return self.proc.poll() is None

    def _read(self):
        try:
            while True:
                line = self.proc.stdout.readline(LIVE_LINE + 1)
                if not line: break
                with self.lock: turn = self.turn
                if b'"session_id"' in line and len(line) < 65536:
                    try: self.session = str(json.loads(line).get('session_id') or self.session)
                    except (ValueError, AttributeError): pass
                if turn is None: self.spoiled = self.spoiled or '在兩則訊息之間有輸出'; continue  # nobody asked it anything: not part of any reply, and not trusted again
                turn.take(line)
        except (OSError, ValueError): pass
        finally:
            with self.lock: turn = self.turn
            if turn is not None: turn.done.set()

    def _read_err(self):
        try:
            for chunk in iter(lambda: self.proc.stderr.read1(65536), b''):
                if len(self.err) < 200000: self.err += chunk
        except (OSError, ValueError): pass

    def begin(self, job_id, prompt, limit, on_output):
        turn = LiveTurn(self, limit, on_output)
        with self.lock: self.turn, self.job_id = turn, job_id
        del self.err[:]; self.turns += 1; self.used = time.monotonic()
        data = (json.dumps({'type': 'user', 'message': {'role': 'user', 'content': prompt}}, ensure_ascii=False) + '\n').encode('utf-8')
        def write():  # on its own: a CLI that is slow to read must not hold anything up
            try: self.proc.stdin.write(data); self.proc.stdin.flush()
            except (OSError, ValueError): turn.done.set()
        threading.Thread(target=write, daemon=True).start()
        return turn

    def end(self, turn):
        with self.lock:
            if self.turn is turn: self.turn, self.job_id = None, None
        self.used = time.monotonic()

    def close(self, wait=0):
        """End the CLI and everything it started. With wait, do not return until it is gone (Zook is closing)."""
        try: self.proc.stdin.close()
        except (OSError, ValueError): pass
        if self.alive(): terminate_tree(self.proc)
        if not wait: return
        try: self.proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            try: os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired: pass


class LiveTurn:
    """One message to a kept CLI. To the code that waits for a reply it looks like the process and its pipes in one."""
    def __init__(self, cli, limit, on_output):
        self.cli, self.limit, self.on_output, self.out, self.done, self.finished, self.last = cli, limit, on_output, bytearray(), threading.Event(), False, time.monotonic()
        self.pid = cli.proc.pid; self.echoed = False

    def take(self, line):
        self.last = time.monotonic()
        if len(line) > LIVE_LINE: self.out += b'x' * (self.limit + 1 - min(len(self.out), self.limit)); self.done.set(); return  # counted as over the size limit
        kind = b''
        if b'"type"' in line:
            try: kind = str(json.loads(line).get('type') or '').encode()
            except (ValueError, AttributeError): kind = b''
        # The CLI repeats each message it reads. Until this message has been repeated, what arrives is the tail of something
        # older (it cannot be told apart otherwise) and must not be taken for this reply.
        if not self.echoed:
            if kind == b'user': self.echoed = True
            elif kind != b'system': self.cli.spoiled = self.cli.spoiled or '上一則結束後還有輸出'
            return
        if len(self.out) <= self.limit: self.out += line
        if self.on_output:
            try: self.on_output(line)
            except Exception: pass
        if kind == b'result': self.finished = True; self.done.set()

    @property
    def returncode(self):
        """0 for a message that got its answer; otherwise what the process ended with (or 1 when it was stopped)."""
        return 0 if self.finished else (self.cli.proc.poll() or 1)

    def wait(self, timeout=None):
        if not self.done.wait(timeout): return False
        self.cli.end(self)
        return True

    def result(self): return bytes(self.out), bytes(self.cli.err)

    def lost(self): return not self.finished and not self.out


def live_mark(args, cwd, env, origin):
    """Everything a kept CLI was started with, except what only matters at the start (which conversation to pick up) and its own
    address; and who started the turn, so a turn nobody typed never shares a CLI with one the user did."""
    kept = []; skip = False
    for a in args:
        if skip: skip = False; continue
        if a == '--resume': skip = True; continue
        kept.append(a)
    return hashlib.sha256(json.dumps([kept, str(cwd), origin, sorted((k, v) for k, v in env.items() if k not in ('ZOOK_WORKER_URL', 'ZOOK_WORKER_TOKEN'))], ensure_ascii=False).encode('utf-8', 'replace')).hexdigest()


def live_close(app, cli, wait=0):
    """Lock on app.live_lock held, or the CLI is no longer listed."""
    app.lives.pop(cli.key, None); app.live_ids.pop(cli.ident, None)
    if wait: cli.close(wait)
    else: threading.Thread(target=cli.close, daemon=True).start()


def live_turn(app, job, provider, kind, args, cwd, env, resume, prompt, on_output):
    """Send this message to the conversation's kept CLI, starting one when there is none that fits. None means: start the CLI the
    usual way (the switch is off, this kind of reply is not kept, or everything that could be kept is busy)."""
    store = app.store
    if kind not in LIVE_KINDS or not live_on(store) or app.__dict__.get('closing') or not job.get('chatId') or job.get('groupId') or job.get('internal') or job.get('liveOff') or '--no-session-persistence' in args: return None
    if app.__dict__.get('live_fails', 0) >= LIVE_FAILS or not live_able(app, provider): return None
    lives = app.__dict__.setdefault('lives', {}); ids = app.__dict__.setdefault('live_ids', {}); guard = app.__dict__.setdefault('live_lock', threading.Lock())
    key = (job['botId'], job['chatId']); mark = live_mark(args, cwd, env, job.get('origin') or 'user')
    with guard:
        cli = lives.get(key)
        if cli and (not cli.alive() or cli.spoiled or cli.mark != mark or cli.turn is not None or not resume or cli.session != resume): live_close(app, cli); cli = None
        if cli is None:
            if len(lives) >= LIVE_MAX:
                idle = sorted((c for c in lives.values() if c.turn is None), key=lambda c: c.used)
                if not idle: return None
                live_close(app, idle[0])
            ident = 'live-' + secrets.token_hex(12); token = secrets.token_urlsafe(32)
            started = [a for a in args] + ['--input-format', 'stream-json', '--replay-user-messages']
            cli = LiveCli(key, started, cwd, dict(env, ZOOK_WORKER_URL='http://127.0.0.1:%d/api/worker/%s' % (app.server_address[1], ident), ZOOK_WORKER_TOKEN=token), mark, ident, token)
            lives[key] = cli; ids[ident] = cli
        else: job['kept'] = True  # this reply did not have to start the CLI
        return cli.begin(job['id'], prompt, MAX_CLI_OUTPUT, on_output)


def live_usage(turn, usage):
    """A kept CLI may report what the whole run has cost so far. Each reply is given only its own part."""
    cost = (usage or {}).get('costUsd')
    if not isinstance(turn, LiveTurn) or not isinstance(cost, (int, float)) or isinstance(cost, bool): return usage
    before, turn.cli.cost = turn.cli.cost, max(turn.cli.cost, float(cost))
    return dict(usage, costUsd=round(cost - before, 6)) if cost >= before > 0 else usage


def live_worker(app, ident, auth):
    """Lock held. (worker, job) for a tool call that came from a kept CLI: the reply it is answering right now, or (None, None).
    A call while it is answering nothing means it is working on its own: refused, and that CLI is not used again."""
    cli = app.__dict__.get('live_ids', {}).get(ident)
    if not cli or not secrets.compare_digest(auth, 'Bearer ' + cli.token): return None, None
    if not cli.job_id: cli.spoiled = cli.spoiled or '在兩則訊息之間呼叫工具'; return None, None
    return app.workers.get(cli.job_id), app.store.find('jobs', cli.job_id)


def live_tidy(app, everything=False):
    """Close kept CLIs that have not been used for a while, that ended on their own, that are no longer trusted, whose Bot or
    conversation is gone, or (everything=True) all of them. One that is answering is left alone unless Zook is closing."""
    guard = app.__dict__.get('live_lock')
    if not guard: return 0
    with app.store.lock: here = {(b['id'], c['id']) for b in app.store.data['bots'] for c in b.get('chats') or []}; on = live_on(app.store)
    with guard:
        now = time.monotonic()
        gone = [c for c in app.lives.values() if everything or not c.alive() or (c.turn is None and (now - c.used > LIVE_IDLE or c.spoiled or not on or c.key not in here))]
        for cli in gone: live_close(app, cli, wait=3 if everything else 0)
    return len(gone)
