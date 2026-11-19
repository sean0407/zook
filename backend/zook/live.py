# Keeping a CLI open between the messages of one conversation, so a reply does not begin by starting the CLI again.
# Loaded by backend/server.py into one shared namespace.
#
# Only what a reply would have started anyway is kept: the same program, the same arguments, the same folder and sign-in. When any
# of those differ for the next message (another model, 先規劃, a new attachment folder, a changed tool list), the kept CLI is closed
# and a new one started. Every tool call still goes to the reply that is running right now, with that reply's own approvals,
# origin and permission mode: the kept CLI holds an address of its own, and Zook looks up which reply it belongs to at each call.
LIVE_IDLE = 600   # seconds a kept CLI may sit unused
LIVE_MAX = 4      # kept CLIs at one time; the one unused longest makes room
LIVE_KINDS = ('claude',)


def live_on(store): return store.data['settings'].get('keepCli') is not False


class LiveLost(Exception):
    """The kept CLI went away before it wrote anything for this message: the message is sent again the usual way."""


class LiveCli:
    """One CLI process that stays open and answers one message at a time."""
    def __init__(self, key, args, cwd, env, mark, ident, token):
        self.key, self.mark, self.ident, self.token = key, mark, ident, token
        self.session, self.job_id, self.turn, self.used, self.turns = '', None, None, time.monotonic(), 0
        self.lock = threading.Lock(); self.err = bytearray()
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, cwd=str(cwd), env=env)
        for target in (self._read, self._read_err): threading.Thread(target=target, daemon=True).start()

    def alive(self): return self.proc.poll() is None

    def _read(self):
        try:
            for line in iter(self.proc.stdout.readline, b''):
                with self.lock: turn = self.turn
                if b'"session_id"' in line:
                    try: self.session = str(json.loads(line).get('session_id') or self.session)
                    except (ValueError, AttributeError): pass
                if turn is None: continue  # between messages: what the CLI says to itself is not part of any reply
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
        try:
            self.proc.stdin.write((json.dumps({'type': 'user', 'message': {'role': 'user', 'content': prompt}}, ensure_ascii=False) + '\n').encode('utf-8')); self.proc.stdin.flush()
        except (OSError, ValueError): turn.done.set()
        return turn

    def end(self, turn):
        with self.lock:
            if self.turn is turn: self.turn, self.job_id = None, None
        self.used = time.monotonic()

    def close(self):
        try: self.proc.stdin.close()
        except (OSError, ValueError): pass
        if self.alive(): terminate_tree(self.proc)


class LiveTurn:
    """One message to a kept CLI. To the code that waits for a reply it looks like the process and its pipes in one."""
    def __init__(self, cli, limit, on_output):
        self.cli, self.limit, self.on_output, self.out, self.done, self.finished, self.last = cli, limit, on_output, bytearray(), threading.Event(), False, time.monotonic()
        self.pid = cli.proc.pid

    def take(self, line):
        self.last = time.monotonic()
        if len(self.out) <= self.limit: self.out += line
        if self.on_output:
            try: self.on_output(line)
            except Exception: pass
        if b'"type":"result"' in line.replace(b' ', b'')[:400] or line.lstrip().startswith(b'{"type":"result"'):
            try: ended = json.loads(line).get('type') == 'result'
            except (ValueError, AttributeError): ended = False
            if ended: self.finished = True; self.done.set()

    @property
    def returncode(self):
        """0 for a message that got its answer; otherwise what the process ended with (or 1 when it was stopped)."""
        return 0 if self.finished else (self.cli.proc.poll() or 1)

    def wait(self, seconds):
        if not self.done.wait(seconds): return False
        self.cli.end(self)
        return True

    def result(self): return bytes(self.out), bytes(self.cli.err)

    def lost(self): return not self.finished and not self.out


def live_mark(args, cwd, env):
    """Everything a kept CLI was started with, except what only matters at the start (which conversation to pick up) and its own address."""
    kept = []; skip = False
    for a in args:
        if skip: skip = False; continue
        if a == '--resume': skip = True; continue
        kept.append(a)
    return hashlib.sha256(json.dumps([kept, str(cwd), sorted((k, v) for k, v in env.items() if k not in ('ZOOK_WORKER_URL', 'ZOOK_WORKER_TOKEN'))], ensure_ascii=False).encode('utf-8', 'replace')).hexdigest()


def live_close(app, cli):
    """Lock on app.live_lock held, or the CLI is no longer listed."""
    app.lives.pop(cli.key, None); app.live_ids.pop(cli.ident, None)
    threading.Thread(target=cli.close, daemon=True).start()


def live_turn(app, job, kind, args, cwd, env, resume, prompt, on_output):
    """Send this message to the conversation's kept CLI, starting one when there is none that fits. None means: start the CLI the
    usual way (the switch is off, this kind of reply is not kept, or everything that could be kept is busy)."""
    store = app.store
    if kind not in LIVE_KINDS or not live_on(store) or not job.get('chatId') or job.get('groupId') or job.get('internal') or job.get('liveOff') or '--no-session-persistence' in args: return None
    lives = app.__dict__.setdefault('lives', {}); ids = app.__dict__.setdefault('live_ids', {}); guard = app.__dict__.setdefault('live_lock', threading.Lock())
    key = (job['botId'], job['chatId']); mark = live_mark(args, cwd, env)
    with guard:
        cli = lives.get(key)
        if cli and (not cli.alive() or cli.mark != mark or cli.turn is not None or not resume or cli.session != resume): live_close(app, cli); cli = None
        if cli is None:
            if len(lives) >= LIVE_MAX:
                idle = sorted((c for c in lives.values() if c.turn is None), key=lambda c: c.used)
                if not idle: return None
                live_close(app, idle[0])
            ident = 'live-' + secrets.token_hex(12); token = secrets.token_urlsafe(32)
            started = [a for a in args] + ['--input-format', 'stream-json']
            cli = LiveCli(key, started, cwd, dict(env, ZOOK_WORKER_URL='http://127.0.0.1:%d/api/worker/%s' % (app.server_address[1], ident), ZOOK_WORKER_TOKEN=token), mark, ident, token)
            lives[key] = cli; ids[ident] = cli
        else: job['kept'] = True  # this reply did not have to start the CLI
        return cli.begin(job['id'], prompt, MAX_CLI_OUTPUT, on_output)


def live_worker(app, ident, auth):
    """Lock held. (worker, job) for a tool call that came from a kept CLI: the reply it is answering right now, or (None, None)."""
    cli = app.__dict__.get('live_ids', {}).get(ident)
    if not cli or not secrets.compare_digest(auth, 'Bearer ' + cli.token) or not cli.job_id: return None, None
    return app.workers.get(cli.job_id), app.store.find('jobs', cli.job_id)


def live_tidy(app, everything=False):
    """Close kept CLIs that have not been used for a while, that ended on their own, or (everything=True) all of them."""
    guard = app.__dict__.get('live_lock')
    if not guard: return 0
    with guard:
        now = time.monotonic(); gone = [c for c in app.lives.values() if everything or not c.alive() or (c.turn is None and now - c.used > LIVE_IDLE) or not live_on(app.store)]
        for cli in gone: live_close(app, cli)
    return len(gone)
