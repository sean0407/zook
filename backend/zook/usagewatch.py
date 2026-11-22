# 偵測使用量: fresh limits for every signed-in account, from the button on the usage page or on its own every so often (自動偵測).
# Every path that sends Claude a request to read its limits (the button, the timer, opening the usage page, the refresh button,
# a paired phone reading the usage) takes the same lock, so two of them never run at once.
# Loaded by backend/server.py into one shared namespace.
USAGE_DETECT_CHOICES = (0, 15, 30, 60, 180)  # minutes between automatic detections; 0 is off (the default)
USAGE_DETECT_NAMES = {0: '關閉', 15: '每 15 分鐘', 30: '每 30 分鐘', 60: '每 1 小時', 180: '每 3 小時'}
_detect_guard = threading.Lock()


def usage_detect_every(store):
    """Minutes between automatic detections, 0 when 自動偵測 is off."""
    value = (store.data.get('settings') or {}).get('usageDetectEvery', 0)
    return value if not isinstance(value, bool) and value in USAGE_DETECT_CHOICES else 0


def usage_detect_gate(app):
    """One Claude limit read at a time, for every path alike."""
    with _detect_guard: return app.__dict__.setdefault('usage_detect_lock', threading.Lock())


def usage_detect_status(app):
    """What an open usage page needs to know whether to read the figures again. Runs no CLI."""
    with app.store.lock: every = usage_detect_every(app.store)
    return dict(usageDetectEvery=every, doneAt=getattr(app, 'usage_detect_done', 0), running=usage_detect_gate(app).locked())


def claude_subscription(view, extra=None):
    """Signed in, and the billing check knows it to be a subscription (an unknown or empty method counts as billed)."""
    return view.get('status') == 'logged_in' and not auto_state('claude', view['status'], view.get('method') or '', extra)['billed']


def claude_probe_targets(store):
    """Each Claude subscription once. Only sign-ins the billing check knows to be a subscription (an unknown or empty method counts as billed);
    the same account signed in on the default CLI and in a Zook profile is one subscription, told apart by its email."""
    if 'claude' not in P.active_ids(store.data): return []
    targets, seen = [], set()
    def add(extra, view):
        if not claude_subscription(view, extra): return
        key = str(view.get('email') or '').strip().lower() or 'profile:' + (extra['id'] if extra else '')
        if key not in seen: seen.add(key); targets.append(extra)
    try: add(None, account_status('claude'))
    except (OSError, ValueError, RuntimeError): pass
    for extra in [a for a in store.data.get('accounts') or [] if a.get('provider') == 'claude' and a.get('type') == 'login']:
        try: add(extra, account_view(extra))
        except (OSError, ValueError, RuntimeError): continue
    return targets


def _detect_usage_work(app):
    """Lock held. Clear the Codex limit cache and read Claude's limits. Claude only reports them with a reply, so each subscription gets one tiny request.
    Waits for every request to end (each has its own time limit), so the lock is never let go while one is still running."""
    store = app.store
    with store.lock: store.data['usageDetectedAt'] = time.time()  # the timer counts from the start, so it never starts a second one meanwhile
    app.__dict__.setdefault('codex_quota_caches', {}).clear()
    def probe(extra):
        try: app.record_quota('claude', claude_quota_probe(provider_env('claude', extra) if extra else None), extra['id'] if extra else '', 'probe')
        except (RuntimeError, OSError, subprocess.TimeoutExpired): pass
    try:
        threads = []
        for extra in claude_probe_targets(store):
            thread = threading.Thread(target=probe, args=(extra,), daemon=True)
            try: thread.start()
            except RuntimeError: probe(extra); continue  # no thread to be had: do it here instead
            threads.append(thread)
        for t in threads: t.join()
        app.claude_probe_at = time.time()
        with store.lock: store.save()
    finally: app.usage_detect_done = time.time()


def detect_usage_now(app):
    """偵測使用量 from any thread. When a detection is already running, wait for it instead of sending the Claude requests again.
    True when this call did the work."""
    gate = usage_detect_gate(app)
    if not gate.acquire(blocking=False):
        with gate: return False  # the one that was running has just read fresh figures
    try: _detect_usage_work(app)
    finally: gate.release()
    return True


def _detect_usage_due(app, now):
    """Lock held. Whether 自動偵測 is on and the last detection (button or timer) is older than the chosen interval.
    When the clock has gone back since then, it counts again from now instead of running early."""
    store = app.store
    with store.lock:
        every = usage_detect_every(store)
        if not every: return False
        last = store.data.get('usageDetectedAt')
        if not isinstance(last, (int, float)) or isinstance(last, bool): return True
        if now < last: store.data['usageDetectedAt'] = now; return False
        return now - last >= every * 60


def _detect_usage_held(app, gate, now):
    try:
        if _detect_usage_due(app, now): _detect_usage_work(app)
    except Exception: pass
    finally: gate.release()


def usage_detect_tick(app, now=None):
    """From the schedule loop: start a detection when it is due. The interval and the last time are read again once the lock is held,
    so a detection that just ended or 自動偵測 just turned off is seen. The work runs on a short-lived thread, so the loop is never
    held up by the Claude requests. True when one was started."""
    if not usage_detect_every(app.store): return False
    gate = usage_detect_gate(app)
    if not gate.acquire(blocking=False): return False  # one is running now
    now = time.time() if now is None else now
    try:
        if not _detect_usage_due(app, now): gate.release(); return False
        threading.Thread(target=_detect_usage_held, args=(app, gate, now), daemon=True).start()
    except BaseException: gate.release(); raise
    return True


def claude_probe_default(app, source):
    """The Claude limit read that opening the usage page ('auto', when the figures are old) or its refresh button ('probe') sends for the
    default account, whatever 自動偵測 is set to. Shares the lock with 偵測使用量: while one is running, opening the page skips and the
    button waits for it (it reads the same figures). Raises what the probe raised; False when nothing was sent."""
    gate = usage_detect_gate(app)
    if not gate.acquire(blocking=False):
        if source == 'auto': return False
        with gate: return False
    try:
        if source == 'auto':  # only when the figures are old, the last read was a while ago, and the default sign-in is known to be a subscription
            with app.store.lock: snap = app.store.data.get('quota', {}).get('claude') or {}
            try: age = time.time() - datetime.datetime.fromisoformat(snap['updatedAt']).timestamp()
            except (KeyError, ValueError, TypeError): age = float('inf')
            if age < app.CLAUDE_QUOTA_STALE or 0 <= time.time() - getattr(app, 'claude_probe_at', 0) < app.CLAUDE_PROBE_MIN_GAP: return False
            if 'claude' not in P.active_ids(app.store.data) or not claude_subscription(account_status('claude')): return False
        app.claude_probe_at = time.time()
        app.record_quota('claude', claude_quota_probe())
        with app.store.lock:
            if 'claude' in app.store.data.get('quota', {}): app.store.data['quota']['claude']['source'] = source
            app.store.save()
        return True
    finally:
        app.usage_detect_done = time.time(); gate.release()


def usage_detect_keep_local(old, new):
    """A restored backup never turns 自動偵測 on or moves its clock: both belong to this Mac."""
    if 'usageDetectEvery' in (old.get('settings') or {}): new['settings']['usageDetectEvery'] = old['settings']['usageDetectEvery']
    else: new['settings'].pop('usageDetectEvery', None)
    if 'usageDetectedAt' in old: new['usageDetectedAt'] = old['usageDetectedAt']
    else: new.pop('usageDetectedAt', None)


def set_usage_detect(store, every):
    """自動偵測's interval, from the usage page on the Mac or a paired phone. Raises ValueError for anything but the offered choices.
    Takes effect only once saved: a failed save puts the old value back."""
    with store.lock:
        settings = store.data['settings']
        had, before = 'usageDetectEvery' in settings, settings.get('usageDetectEvery')
        update(settings, {'usageDetectEvery': every}, 'settings')
        try: store.save()
        except BaseException:
            if had: settings['usageDetectEvery'] = before
            else: settings.pop('usageDetectEvery', None)
            raise
        return {'usageDetectEvery': usage_detect_every(store)}
