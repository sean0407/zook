# Grok's plan limit. Loaded by backend/server.py into one shared namespace.
# `grok usage --json` is meant to report it, but up to 1.0.89 it only answers that the plan's usage can't be shown there yet.
# So Zook tries that first (it costs nothing), and otherwise opens Grok's own screen out of sight, in a pseudo-terminal in an empty
# folder of Zook's, reads the 「Weekly limit left: N%」 line at its foot and closes it again. The one thing ever typed is 「y」 when Grok
# asks whether to trust that same empty folder (it asks once per folder); any other question, such as data sharing, is never answered.
# Only a figure in exactly that form counts; anything else is 讀不到.
import fcntl as _fcntl, pty as _pty, select as _select, signal as _signal, struct as _struct, termios as _termios

GROK_LEFT = re.compile(r'Weekly limit left:\s*(\d{1,3}(?:\.\d+)?)\s*%')
GROK_SCREEN_WAIT = 12  # seconds Grok gets to draw its screen (it takes about one)
GROK_TRUST = 'Do you trust the contents of this directory?'
# Every terminal code Grok sends, including the ones ended by ESC \ that the ANSI pattern elsewhere does not expect.
GROK_CODES = re.compile(r'\x1b\[[0-9;?<>=!]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1bP[^\x1b]*\x1b\\|\x1b[()][A-Za-z0-9]|\x1b[=>78]')
_GROK_LEFT_KEYS = ('remainingPercent', 'remaining_percent', 'percentRemaining', 'percent_remaining', 'leftPercent', 'left_percent', 'percentLeft', 'percent_left')
_GROK_USED_KEYS = ('usedPercent', 'used_percent', 'percentUsed', 'percent_used')
_grok_reading = threading.Lock()
_grok_screen = threading.Lock()
_grok_keys = {}  # one lock per account, so the usage page and 自動選擇 never read the same account twice at once
# On the trust question, the screen may hold only these besides the folder's own path: anything else and nothing is typed.
GROK_TRUST_WORDS = ('Grok Build may run or modify contents in this directory,', 'posing security risks.', 'Yes, proceed', 'No, quit', 'Grok Build')
GROK_JSON_LIMIT = 65536  # bytes of `grok usage --json` output read at most
GROK_JSON_WAIT = 20  # seconds it gets
# What a Grok started only to read its limit gets from Zook's environment: where its own sign-in is, the language, the network
# proxy and temporary folder. Keys and tokens for other services stay behind.
GROK_ENV_KEEP = ('HOME', 'PATH', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'TMPDIR', 'GROK_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME',
                 '__CF_USER_TEXT_ENCODING', 'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
# Grok reads keys only from its own terminal, so it starts as the leader of a new session with the pseudo-terminal as that terminal.
# The helper replaces itself with Grok, so Grok keeps its process id and closing its session closes everything it started.
_GROK_BOOT = 'import fcntl, os, sys, termios; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0); os.execv(sys.argv[1], sys.argv[1:])'


def _grok_percent(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100 else None


def grok_probe_env(env):
    return {k: v for k, v in env.items() if k in GROK_ENV_KEEP or k.startswith('LC_')}


def _grok_close(proc, pause=0):
    """End a probe and everything in its process group. The group is signalled before the leader is reaped, while its number
    is still certainly Grok's; only then is the leader waited for."""
    if pause: time.sleep(pause)  # a moment to quit on its own after its terminal went away
    try: os.killpg(proc.pid, _signal.SIGKILL)
    except OSError: pass
    try: proc.wait(10)
    except subprocess.TimeoutExpired: pass


def grok_usage_json(path, env):
    """Percent left from `grok usage --json`, or None while that command cannot report it (or reports it in a form Zook does not know)."""
    try: proc = subprocess.Popen([path, 'usage', '--json'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=grok_probe_env(env), start_new_session=True)
    except OSError: return None
    out, ended, end = b'', False, time.monotonic() + GROK_JSON_WAIT
    try:
        fd = proc.stdout.fileno()
        while time.monotonic() < end and len(out) <= GROK_JSON_LIMIT:
            if not _select.select([fd], [], [], 0.2)[0]: continue
            chunk = os.read(fd, 65536)
            if not chunk: ended = True; break
            out += chunk
    except OSError: pass
    finally:
        proc.stdout.close(); _grok_close(proc)
    text = out.decode('utf-8', 'replace').strip()
    if not ended or proc.returncode != 0 or len(out) > GROK_JSON_LIMIT or not text.startswith('{'): return None
    try: data = json.loads(text)
    except (ValueError, RecursionError): return None
    found = []
    def walk(node, depth=0):
        if depth > 20: return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _GROK_LEFT_KEYS and _grok_percent(value) is not None: found.append(_grok_percent(value))
                elif key in _GROK_USED_KEYS and _grok_percent(value) is not None: found.append(100 - _grok_percent(value))
                else: walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node: walk(value, depth + 1)
    walk(data)
    return found[0] if len(found) == 1 else None  # more than one figure: which one is the weekly limit is not known, so none is used


def grok_only_trust_question(screen, folder):
    """True when the screen, from the last trust question on, holds that question for this very folder and nothing else."""
    at = screen.rfind(GROK_TRUST)
    if at < 0: return False
    rest, names = screen[at + len(GROK_TRUST):], {str(folder), os.path.realpath(str(folder))}
    if not any(n in rest for n in names): return False
    for word in sorted(names | set(GROK_TRUST_WORDS), key=len, reverse=True): rest = rest.replace(word, ' ')
    return all(t in ('y', 'n') or re.fullmatch(r'\d+(?:\.\d+)*', t) or re.fullmatch(r'[⠀-⣿─-╿]+', t) or (t.startswith('/') and t.endswith('/' + folder.name))
               for t in rest.split())  # the logo, frame lines, the version and Grok's shortened form of the same path


def grok_screen_left(path, env, folder, wait=None):
    """Percent left as Grok's own screen shows it, or None. Grok and everything it started are closed before this returns."""
    folder = pathlib.Path(folder)
    try: folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError: return None
    try: info = os.lstat(str(folder))
    except OSError: return None
    # Only an empty folder that is Zook's own (not a link, only this user may enter) is ever opened in Grok.
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or any(folder.iterdir()): return None
    master, slave = _pty.openpty()
    try: _fcntl.ioctl(slave, _termios.TIOCSWINSZ, _struct.pack('HHHH', 40, 140, 0, 0))
    except OSError: pass
    screen_env = dict(grok_probe_env(env), TERM='xterm-256color', COLUMNS='140', LINES='40', PWD=str(folder))
    try: proc = subprocess.Popen([sys.executable, '-I', '-c', _GROK_BOOT, path], stdin=slave, stdout=slave, stderr=slave, cwd=str(folder), env=screen_env, close_fds=True)
    except OSError:
        os.close(master); os.close(slave); return None
    os.close(slave)
    seen, left, end = b'', None, time.monotonic() + (wait or GROK_SCREEN_WAIT)
    sent, quiet_since = False, time.monotonic()
    try:
        while time.monotonic() < end and left is None:
            if not _select.select([master], [], [], 0.3)[0]:
                # Once, on a still screen that holds only the trust question for this folder: 「y」. Nothing else is ever typed.
                if not sent and time.monotonic() - quiet_since > 0.8 and grok_only_trust_question(GROK_CODES.sub('', seen.decode('utf-8', 'replace')), folder):
                    os.write(master, b'y'); sent = True
                continue
            try: chunk = os.read(master, 65536)
            except OSError: break  # Grok closed its terminal
            if not chunk: break
            quiet_since = time.monotonic()
            seen = (seen + chunk)[-200000:]
            found = GROK_LEFT.findall(GROK_CODES.sub('', seen.decode('utf-8', 'replace')))
            if found: left = _grok_percent(float(found[-1]))  # the newest figure on the screen
    finally:
        try: os.close(master)  # Grok's terminal goes away, which ends its session
        except OSError: pass
        _grok_close(proc, 0.5)
    return left


def grok_quota(path, env, folder):
    """Grok's plan limit as a quota snapshot, or None when it cannot be read."""
    if not path or not _grok_screen.acquire(timeout=15): return None  # one Grok at a time; nobody waits long for another read
    try:
        left = grok_usage_json(path, env)
        if left is None: left = grok_screen_left(path, env, folder)
    finally: _grok_screen.release()
    if left is None: return None
    return dict(windows=[dict(label='每週', usedPercent=round(100 - left, 1), resetsAt=None)], plan='', limitReached=None, credits={}, resetCredits=None, updatedAt=NOW(), source='live')


def grok_live_quota(app, account=None):
    """Grok's limit for the usage page and 自動選擇, at most once a minute per account. Saved like the other CLIs' limits.
    While the same account is being read, a second request gets the last answer at once instead of waiting."""
    store = app.store; key = 'grok' + ('@' + account['id'] if account else '')
    caches = app.__dict__.setdefault('codex_quota_caches', {})
    with _grok_reading: lock = _grok_keys.setdefault(key, threading.Lock())
    hit = caches.get(key)
    if hit and time.time() - hit[0] < (60 if hit[1] else 600): return hit[1]  # a failed read waits ten minutes, so the page never keeps waiting on it
    if not lock.acquire(blocking=False): return hit[1] if hit else None
    try:
        try: live = grok_quota(find_cli('grok'), provider_env('grok', account), store.dir / 'grok-usage')
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError): live = None
        caches[key] = (time.time(), live)
    finally: lock.release()
    if live:
        with store.lock: store.data.setdefault('quota', {})[key] = live; store.save()
    return live
