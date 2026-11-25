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
LIVE_KINDS = ('claude', 'antigravity')
INTERJECT_KINDS = ('claude',)  # can take a message in the middle of a reply (at its next step); Antigravity only reads it once the reply is over
LIVE_UNCLAIMED = 10.0  # seconds after an answer that came without this message being repeated, before the message is sent again the usual way
LIVE_UNREAD = 30.0  # seconds a CLI that has answered may stay quiet before an added message counts as not read
INTERJECT_MAX = 10  # messages added to one reply
INTERJECT_NOTE = '（使用者在你回覆途中補充，請依此調整接下來的做法）\n'
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
    def __init__(self, key, args, cwd, env, mark, ident, token, kind='claude', popen=None):
        self.key, self.mark, self.ident, self.token, self.kind = key, mark, ident, token, kind
        self.home = env.get('HOME', '')  # an extra Antigravity account's folder: closed when that account is removed
        self.session, self.job_id, self.turn, self.used, self.turns, self.spoiled = '', None, None, time.monotonic(), 0, ''
        self.lock = threading.Lock(); self.err = bytearray(); self.cost = 0.0; self.reading = False
        self.writes = queue.Queue()  # one writer, so messages reach the CLI in the order they were sent
        self.proc = popen(args, cwd, env) if popen else subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, cwd=str(cwd), env=dict(env, PWD=str(cwd)))  # PWD too: some CLIs take it as their folder
        for target in (self._write, self._read_err): threading.Thread(target=target, daemon=True).start()

    def alive(self): return self.proc.poll() is None

    def spoil(self, why):
        """Not trusted again. Between two messages nobody is watching it, so it is closed right away."""
        self.spoiled = self.spoiled or why
        with self.lock: idle = self.turn is None
        if idle: threading.Thread(target=self.close, daemon=True).start()

    def _read(self):
        try:
            while True:
                line = self.proc.stdout.readline(LIVE_LINE + 1)
                if not line: break
                with self.lock: turn = self.turn
                if (b'"session_id"' in line or b'"conversation_id"' in line) and len(line) < 65536:
                    try: value = json.loads(line); self.session = str(value.get('session_id') or value.get('conversation_id') or (value.get(value.get('event')) or {}).get('conversation_id') or self.session)
                    except (ValueError, AttributeError, TypeError): pass
                if turn is None:
                    # Nobody asked it anything: not part of any reply, and not trusted again. Claude's own status lines after a
                    # reply (a summary of what it did) are the one exception; anything it does shows up as other lines or a tool call.
                    if not (self.kind == 'claude' and line_kind(self.kind, line) == 'system'): self.spoil('在兩則訊息之間有輸出')
                    continue
                turn.take(line)
        except (OSError, ValueError): pass
        finally:
            with self.lock: turn = self.turn
            if turn is not None:
                if turn.answers and not turn.finished: turn.finished = True  # it ended before reading everything added: what it did answer is kept
                turn.done.set()

    def _read_err(self):
        try:
            for chunk in iter(lambda: self.proc.stderr.read1(65536), b''):
                if len(self.err) < 200000: self.err += chunk
        except (OSError, ValueError): pass

    def _write(self):
        while True:
            item = self.writes.get()
            if item is None: return
            data, turn = item
            try: self.proc.stdin.write(data); self.proc.stdin.flush()
            except (OSError, ValueError): turn.done.set(); return

    def begin(self, job_id, prompt, limit, on_output):
        turn = LiveTurn(self, limit, on_output, prompt)
        with self.lock: self.turn, self.job_id = turn, job_id
        del self.err[:]; self.turns += 1; self.used = time.monotonic()
        if not self.reading:  # only now: whatever it prints at startup belongs to this first message
            self.reading = True; threading.Thread(target=self._read, daemon=True).start()
        self.send(live_line(self.kind, prompt), turn)
        return turn

    def send(self, data, turn): self.writes.put((data, turn))

    def end(self, turn):
        with self.lock:
            if self.turn is turn: self.turn, self.job_id = None, None
        self.used = time.monotonic()

    def close(self, wait=0):
        """End the CLI and everything it started. With wait, do not return until it is gone (Zook is closing)."""
        self.writes.put(None)
        try: self.proc.stdin.close()
        except (OSError, ValueError): pass
        try:
            if self.alive(): terminate_tree(self.proc)
        except OSError: pass  # it ended on its own just now
        if not wait: return
        try: self.proc.wait(timeout=wait)
        except subprocess.TimeoutExpired: pass
        end = time.monotonic() + 5
        while group_alive(self.proc) and time.monotonic() < end:  # it, or a helper it started, is still there: ended by force
            kill_group(self.proc); time.sleep(0.05)
            try: self.proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired: pass


class LiveTurn:
    """One message to a kept CLI. To the code that waits for a reply it looks like the process and its pipes in one."""
    def __init__(self, cli, limit, on_output, prompt=''):
        self.cli, self.limit, self.on_output, self.out, self.done, self.finished, self.last = cli, limit, on_output, bytearray(), threading.Event(), False, time.monotonic()
        self.pid = cli.proc.pid; self.echoed = False; self.prompt = prompt; self.unclaimed = False  # an answer came that cannot be told to be this one's
        self.added, self.pending, self.answers, self.kept_bytes = 0, [], [], 0  # messages added during the reply; those the CLI has not read yet; each answer

    def heard(self, said, sent):
        """Whether the message the CLI repeated is the one sent. Antigravity does not repeat the text, only that it read one."""
        if self.cli.kind != 'claude': return True
        said = (said or '').strip()
        return bool(said) and sent.strip().startswith(said)

    def take(self, line):
        self.last = time.monotonic()
        if len(line) > LIVE_LINE: self.out += b'x' * (self.limit + 1 - min(len(self.out), self.limit)); self.done.set(); return  # counted as over the size limit
        kind = line_kind(self.cli.kind, line)
        said = user_text(line) if kind == 'user' and self.cli.kind == 'claude' else None
        # The CLI repeats each message it reads. Until this message has been repeated, what arrives is the tail of something
        # older (it cannot be told apart otherwise) and must not be taken for this reply.
        if not self.echoed:
            if kind == 'user' and self.heard(said, self.prompt): self.echoed = True
            elif kind not in ('system', 'init'):
                self.cli.spoil('上一則結束後還有輸出')
                if kind == 'result': self.unclaimed = True
            return
        if kind == 'user':
            with self.cli.lock:
                if self.pending and self.heard(said, self.pending[0]): self.pending.pop(0)  # a message added during the reply has been read
        if len(self.out) <= self.limit: self.out += line
        if self.on_output:
            try: self.on_output(line)
            except Exception: pass
        if kind == 'result':
            if self.kept_bytes + len(line) <= self.limit: self.answers.append(line); self.kept_bytes += len(line)
            with self.cli.lock:
                # A message added too late for this answer is answered next, still as part of this reply.
                if not self.pending: self.finished = True; self.done.set()

    def add(self, text):
        """Tell the CLI something while it is answering. '' when it was sent; otherwise why not (the message then waits in line)."""
        sent = INTERJECT_NOTE + text
        with self.cli.lock:
            if self.finished or self.done.is_set() or self.cli.turn is not self or not self.cli.alive(): return '它剛好回覆完了'
            if self.added >= INTERJECT_MAX: return '這則回覆已經補充 %d 次' % INTERJECT_MAX
            self.added += 1; self.pending.append(sent)
        self.cli.send(live_line(self.cli.kind, sent), self)
        return ''

    @property
    def returncode(self):
        """0 for a message that got its answer; otherwise what the process ended with (or 1 when it was stopped)."""
        return 0 if self.finished else (self.cli.proc.poll() or 1)

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            if self.unclaimed and not self.echoed and time.monotonic() - self.last > LIVE_UNCLAIMED:
                # It answered without repeating this message first, then went quiet: the message was not seen being read. Nothing of
                # it is taken; the CLI is closed and the message is sent again the usual way (a reply with no output counts as lost).
                threading.Thread(target=self.cli.close, daemon=True).start(); self.done.set(); self.cli.end(self)
                return True
            with self.cli.lock: stuck = bool(self.answers and self.pending) and time.monotonic() - self.last > LIVE_UNREAD
            if not stuck: return False
            # It answered, then went quiet without reading what was added: the reply keeps that answer, and the CLI (which may
            # still act on the message later, with nobody watching) is closed.
            self.finished = True; self.cli.spoiled = self.cli.spoiled or '沒有讀到回覆途中補充的訊息'
            threading.Thread(target=self.cli.close, daemon=True).start(); self.done.set()
        self.cli.end(self)
        return True

    def result(self): return bytes(self.out), bytes(self.cli.err)

    def lost(self): return not self.finished and not self.out


def user_text(line):
    """The text of a message Claude repeated: plain text, or text blocks. None for a tool's result."""
    try: value = json.loads(line)
    except ValueError: return None
    content = (value.get('message') or {}).get('content') if isinstance(value, dict) and isinstance(value.get('message'), dict) else None
    if isinstance(content, str): return content
    if isinstance(content, list) and content and all(isinstance(b, dict) and b.get('type') == 'text' for b in content): return ''.join(str(b.get('text') or '') for b in content)
    return None


def line_kind(kind, line):
    """What a line of output is: user (a message read), result (an answer is complete), system/init (status), or ''."""
    if kind == 'antigravity':
        if b'"event"' not in line: return ''
        try: value = json.loads(line)
        except ValueError: return ''
        if not isinstance(value, dict): return ''
        event = value.get('event')
        if event == 'step_update' and isinstance(value.get('step_update'), dict) and value['step_update'].get('step_type') == 'user_input': return 'user'
        return event if event in ('result', 'init') else 'step'
    if b'"type"' not in line: return ''
    try: value = json.loads(line)
    except ValueError: return ''
    if not isinstance(value, dict): return ''
    if value.get('type') == 'user': return 'user' if user_text(line) is not None else 'tool'  # a tool's result is also sent as a "user" line
    return str(value.get('type') or '')


def live_line(kind, prompt):
    """One message as the CLI reads it. Antigravity's is already made by the code that builds its run."""
    if kind == 'antigravity': return prompt.encode('utf-8') if prompt.endswith('\n') else (json.dumps({'event': 'user', 'message': {'content': prompt}}, ensure_ascii=False) + '\n').encode('utf-8')
    return (json.dumps({'type': 'user', 'message': {'role': 'user', 'content': prompt}}, ensure_ascii=False) + '\n').encode('utf-8')


def agy_touched(workspace):
    """Whether anything other than the tool settings Zook wrote is in the places agy loads hooks, tools and skills from. A kept agy
    may have loaded it already, so it is not used again."""
    for name in AGY_ROOTS:
        place = pathlib.Path(workspace) / name
        if not os.path.lexists(str(place)): continue
        if name != '.agents' or place.is_symlink() or not place.is_dir(): return True
        if sorted(str(p.relative_to(place)) for p in place.rglob('*')) != ['mcp_config.json']: return True
    return False


def live_mark(args, cwd, env, origin, extra=''):
    """Everything a kept CLI was started with, except what only matters at the start (which conversation to pick up) and its own
    address; and who started the turn, so a turn nobody typed never shares a CLI with one the user did."""
    kept = []; skip = False
    for a in args:
        if skip: skip = False; continue
        if a in ('--resume', '--conversation'): skip = True; continue
        kept.append(a)
    return hashlib.sha256(json.dumps([kept, str(cwd), origin, extra, sorted((k, v) for k, v in env.items() if k not in ('ZOOK_WORKER_URL', 'ZOOK_WORKER_TOKEN', 'ZOOK_GATE_MARK', 'ZOOK_GATE_NONCE'))], ensure_ascii=False).encode('utf-8', 'replace')).hexdigest()


def live_close(app, cli, wait=0):
    """Lock on app.live_lock held, or the CLI is no longer listed."""
    app.lives.pop(cli.key, None); app.live_ids.pop(cli.ident, None)
    if wait: cli.close(wait)
    else: threading.Thread(target=cli.close, daemon=True).start()


def live_drop_bot(app, bot_id, job):
    """One agy per Bot. Every Antigravity run of a Bot starts in the same workspace and rewrites the same tool settings there, so
    a kept agy of another conversation, left idle next to a group turn, was seen with the group member stuck at 正在思考. Before
    an Antigravity reply starts (and before a group turn copies files in), the Bot's other kept agy CLIs are closed and waited for,
    and so is any agy of a reply that was stopped but has not ended yet. A group turn never uses a kept one, so for it every one
    of them goes. Raises when one cannot be ended."""
    store = getattr(app, 'store', None); running = set()
    if store and job.get('id'): agy_hold(app, bot_id, job['id'])
    if store:
        with store.lock: running = {j['id'] for j in store.data['jobs'] if j.get('botId') == bot_id and j['status'] == 'running'}
    guard = app.__dict__.get('live_lock'); gone = []
    keep = (bot_id, job.get('chatId')) if job.get('chatId') and not job.get('groupId') and not job.get('internal') else None
    if guard:
        with guard:
            gone = [c for c in app.lives.values() if c.kind == 'antigravity' and c.key[0] == bot_id and (c.turn is None and c.key != keep or c.turn is not None and c.job_id not in running)]
            for cli in gone: app.lives.pop(cli.key, None); app.live_ids.pop(cli.ident, None)
    for cli in gone: cli.close(wait=3)
    if store and not agy_wait_gone(app, bot_id, running): raise RuntimeError('這個 Bot 上一次的 Antigravity 還沒結束，這次先不執行。請稍後再試一次。')
    return len(gone)


def agy_hold(app, bot_id, job_id):
    """One agy of a Bot at a time, also when two replies of it would run together (two conversations, a conversation and a group):
    the later one waits here until the earlier reply is over (agy_release). Raises when this reply was stopped while waiting."""
    cond = app.__dict__.setdefault('agy_cond', threading.Condition()); slots = app.__dict__.setdefault('agy_slots', {})
    with cond:
        while slots.get(bot_id) not in (None, job_id):
            with app.store.lock: waiting = (app.store.find('jobs', job_id) or {}).get('status') == 'running'
            if not waiting: raise RuntimeError('已停止。')
            cond.wait(0.5)
        slots[bot_id] = job_id


def agy_release(app, job_id):
    cond = app.__dict__.get('agy_cond')
    if not cond: return
    with cond:
        for bot_id in [b for b, j in app.agy_slots.items() if j == job_id]: del app.agy_slots[bot_id]
        cond.notify_all()


def agy_wait_gone(app, bot_id, running, limit=8.0):
    """Wait until no agy of this Bot is left from a reply that is no longer running (a stopped one ends in a moment); one that
    does not is ended by force. False when something is still there after that."""
    store = app.store; end = time.monotonic() + limit; forced = False
    while True:
        with store.lock:
            procs = [getattr(getattr(p, 'cli', None), 'proc', None) or p for j, p in list((app.__dict__.get('processes') or {}).items())
                     if j not in running and ((store.find('jobs', j) or {}).get('botId'), (store.find('jobs', j) or {}).get('runKind')) == (bot_id, 'antigravity')]
        left = [p for p in procs if group_alive(p)]
        if not left: return True
        if time.monotonic() >= end: return False
        if not forced and time.monotonic() >= end - limit / 2:
            for p in left: kill_group(p)
            forced = True
        time.sleep(0.1)


def live_settle(app, job, kind, args, cwd, env, resume):
    """Before a kept agy is replaced (先規劃, another model, other settings), it is ended and waited for, so two never overlap."""
    if kind != 'antigravity' or not job.get('chatId') or job.get('groupId'): return
    guard = app.__dict__.get('live_lock'); lives = app.__dict__.get('lives') or {}
    if not guard: return
    mark = live_mark(args, cwd, env, job.get('origin') or 'user', agy_config(kind, cwd))
    with guard:
        cli = lives.get((job['botId'], job['chatId']))
        if not cli or live_fits(cli, mark, resume): return
        lives.pop(cli.key, None); app.live_ids.pop(cli.ident, None)
    cli.close(wait=3)


def live_fits(cli, mark, resume):
    return cli.alive() and not cli.spoiled and cli.mark == mark and cli.turn is None and bool(resume) and cli.session == resume


def agy_config(kind, cwd):
    """Antigravity's tool settings (how long a tool may take): a kept agy is used again only with the same ones."""
    if kind != 'antigravity': return ''
    try: return (pathlib.Path(cwd) / '.agents' / 'mcp_config.json').read_text(encoding='utf-8')
    except OSError: return ''


def live_turn(app, job, provider, kind, args, cwd, env, resume, prompt, on_output):
    """Send this message to the conversation's kept CLI, starting one when there is none that fits. None means: start the CLI the
    usual way (the switch is off, this kind of reply is not kept, or everything that could be kept is busy)."""
    store = app.store
    if kind not in LIVE_KINDS or not live_on(store) or app.__dict__.get('closing') or not job.get('chatId') or job.get('groupId') or job.get('internal') or job.get('liveOff') or job.get('reattach') or '--no-session-persistence' in args: return None
    if app.__dict__.get('live_fails', 0) >= LIVE_FAILS or not live_able(app, provider): return None
    lives = app.__dict__.setdefault('lives', {}); ids = app.__dict__.setdefault('live_ids', {}); guard = app.__dict__.setdefault('live_lock', threading.Lock())
    key = (job['botId'], job['chatId'])
    mark = live_mark(args, cwd, env, job.get('origin') or 'user', agy_config(kind, cwd))
    with guard:
        cli = lives.get(key)
        if cli and not live_fits(cli, mark, resume): live_close(app, cli); cli = None
        if cli is None:
            if len(lives) >= LIVE_MAX:
                idle = sorted((c for c in lives.values() if c.turn is None), key=lambda c: c.used)
                if not idle: return None
                live_close(app, idle[0])
            ident = 'live-' + secrets.token_hex(12); token = bg_token(app, job, ident) or secrets.token_urlsafe(32)  # made again from Zook's key after a restart
            started = list(args) + (['--input-format', 'stream-json', '--replay-user-messages'] if kind == 'claude' else [])  # Antigravity's run already reads messages this way
            cli = LiveCli(key, started, cwd, dict(env, ZOOK_WORKER_URL='http://127.0.0.1:%d/api/worker/%s' % (app.server_address[1], ident), ZOOK_WORKER_TOKEN=token), mark, ident, token, kind, popen=lambda a, c, e: bg_popen(app, job, a, c, e, True, kind, live=True, name=ident))
            cli.gate = [env.get('ZOOK_GATE_MARK'), env.get('ZOOK_GATE_NONCE'), 0] if env.get('ZOOK_GATE_NONCE') else None  # its own word (gate.py)
            lives[key] = cli; ids[ident] = cli
        else: job['kept'] = True  # this reply did not have to start the CLI
        bg_note(store, job, cli.proc, True, cli.cost); store.save()  # where this reply's output starts, on disk before the CLI gets the message (background.py)
        return cli.begin(job['id'], prompt, MAX_CLI_OUTPUT, on_output)


def live_usage(turn, usage):
    """A kept Claude reports what the whole run has cost so far. Each reply is given only its own part. (Antigravity's tokens are
    counted from each step of the reply, which are its own.)"""
    cost = (usage or {}).get('costUsd')
    if not isinstance(turn, LiveTurn) or not isinstance(cost, (int, float)) or isinstance(cost, bool): return usage
    before, turn.cli.cost = turn.cli.cost, max(turn.cli.cost, float(cost))
    return dict(usage, costUsd=round(cost - before, 6)) if cost >= before > 0 else usage


def live_answers(turn, parsed):
    """A reply that got more than one answer (a message added during it was read only after the first): all of them, in order."""
    if not isinstance(turn, LiveTurn) or len(turn.answers) < 2 or turn.cli.kind != 'claude': return parsed
    texts, totals, model = [], dict(input=0, cachedInput=0, cacheWrite=0, output=0), ''
    for line in turn.answers:
        part = parse_cli_output('claude', line.decode('utf-8', 'replace'))
        if part['content']: texts.append(part['content'])
        model = (part['usage'] or {}).get('model') or model
        for k in totals: totals[k] += (part['usage'] or {}).get(k) or 0
    parsed = dict(parsed, content='\n\n'.join(texts) or parsed['content'])
    if any(totals.values()): parsed['usage'] = dict(parsed.get('usage') or dict(model=model or '預設模型', costUsd=None), **totals)
    return parsed


def live_interject(app, job, text):
    """Lock on store held. Add the user's message to the reply that is running now. '' when it was added; otherwise why it could not be."""
    turn = app.processes.get(job['id'])
    if not isinstance(turn, LiveTurn) or turn.cli.kind not in INTERJECT_KINDS: return '這個模型無法在回覆途中接收訊息'
    if isinstance(turn.cli, AdoptedCli): return '這則回覆是 Zook 重開後接回的'  # its input stayed with the Zook that closed (background.py)
    if (job.get('origin') or 'user') != 'user': return '這則回覆不是你發起的'
    return turn.add(text)


# Sent while a Bot is answering: Zook decides by rule, without asking a model, whether the message changes the reply that is
# running (插話) or is something new that waits its turn (排在後面). A correction or an addition to the current work joins it:
# a short message that is not a new question, one that starts with words like 等等、不要、改成、另外, or one that clearly points
# at what is being done. Anything else waits.
INTERJECT_STARTS = ('等等', '等一下', '等下', '不要', '別', '改成', '改用', '改', '換成', '另外', '還有', '順便', '對了', '停', '先停', '暫停', '補充',
                    '剛剛', '剛才', '其實', '不對', '錯了', '再加', '加上', '也要', '記得', '但是', '可是', '不過', '算了')
INTERJECT_STARTS_EN = ('wait', 'stop', 'actually', 'also', 'and ', 'but ', 'no ', 'no,', "don't", 'dont', 'instead', 'oops', 'make it', 'change ', 'skip', 'plus ')
INTERJECT_POINTS = ('改成', '換成', '改用', '不要用', '別用', '剛剛', '剛才', '上面那', '你正在', '目前這', '這份', '這段', '這一步', '這裡的')
INTERJECT_SHORT = 12  # units: one per Chinese character, two per word in other languages


def interject_wanted(text, names=()):
    """Whether a message sent while a reply runs should join that reply. names: group members, so @mentions are left out."""
    if not isinstance(text, str): return False
    s = text.strip()
    for _ in range(5):  # leading @mentions say who answers, not what is said
        lead = next((n for n in sorted(names, key=len, reverse=True) if n and s.lower().startswith('@' + n.lower())), None)
        if lead: s = s[len(lead) + 1:].lstrip(' ，,：:')
        elif s.startswith('@'): s = re.sub(r'^@\S+\s*', '', s)
        else: break
    if not s: return False
    low = s.lower().lstrip('，,。.!！ ')
    if low.startswith(INTERJECT_STARTS) or low.startswith(INTERJECT_STARTS_EN): return True
    if any(p in s for p in INTERJECT_POINTS): return True
    units = len(re.findall(r'[㐀-鿿豈-﫿]', s)) + 2 * len(re.findall(r'[A-Za-z0-9]+', s))
    question = bool(re.search(r'[?？]\s*$|[嗎呢]\s*$|如何|什麼|為什麼|怎麼|哪裡|哪個|哪些', s))
    return units <= INTERJECT_SHORT and not question


def interject_send(app, bot, body, by=''):
    """Lock held. A message the user wants the Bot to hear while it is still answering. Returns (job, '') when it was added to the
    running reply, (None, '') when the Bot is not answering anything, or (None, why) when it has to wait in line instead."""
    store = app.store
    job = next((j for j in store.data['jobs'] if j['botId'] == bot['id'] and j['status'] == 'running'), None)
    if not job: return None, ''
    content = body.get('content')
    if not isinstance(content, str) or not content.strip() or len(content) > 30000: return None, '訊息內容無效'
    if body.get('attachments') or body.get('plan') or body.get('long'): return None, '附件、先規劃和長任務要等它回覆完才能送'
    if job.get('groupId'): return None, '它正在群組裡回覆'
    if job.get('chatId') != bot.get('chatId'): return None, '它正在另一個對話回覆'
    reason = live_interject(app, job, content.strip())
    if reason: return None, reason
    messages = chat_messages(bot, job['chatId'])
    at = next((i for i, m in enumerate(messages) if m['id'] == job.get('messageId')), len(messages))
    message = dict(id=ID(), role='user', content=content.strip(), createdAt=NOW(), interjected=True)
    if by: message['author'] = by
    messages.insert(at, message)  # above the reply it changes, which is still being written
    job.setdefault('added', []).append(message['id']); job.setdefault('addedText', []).append(content.strip()); store.save()
    log_activity(store, 'chat', '在回覆途中補充訊息（%s）' % bot.get('name', ''))
    return job, ''


def live_worker(app, ident, check):
    """Lock held. (worker, job) for a tool call that came from a kept CLI: the reply it is answering right now, or (None, None).
    A call while it is answering nothing means it is working on its own: refused, and that CLI is not used again."""
    cli = app.__dict__.get('live_ids', {}).get(ident)
    if not cli or not check(cli.token): return None, None  # signed with its token (background.py bg_worker)
    if not cli.job_id: cli.spoiled = cli.spoiled or '在兩則訊息之間呼叫工具'; return None, None
    return app.workers.get(cli.job_id), app.store.find('jobs', cli.job_id)


def live_tidy(app, everything=False, spare=()):
    """Close kept CLIs that have not been used for a while, that ended on their own, that are no longer trusted, whose Bot or
    conversation is gone, or (everything=True) all of them. One that is answering is left alone unless Zook is closing."""
    guard = app.__dict__.get('live_lock')
    if not guard: return 0
    with app.store.lock: here = {(b['id'], c['id']) for b in app.store.data['bots'] for c in b.get('chats') or []}; on = live_on(app.store)
    with guard:
        now = time.monotonic()
        gone = [c for c in app.lives.values() if c.job_id not in spare and everything or c.job_id not in spare and not c.alive() or (c.turn is None and (now - c.used > LIVE_IDLE or c.spoiled or not on or c.key not in here))]
        for cli in gone: live_close(app, cli, wait=3 if everything else 0)
    return len(gone)
