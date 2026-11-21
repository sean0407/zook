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
GROK_OTHER_QUESTIONS = ('Help improve', 'Opt in', 'Opt out', 'Privacy', 'Terms')  # never answered: if one shows, nothing is typed
# Grok reads keys only from its own terminal, so it starts as the leader of a new session with the pseudo-terminal as that terminal.
# The helper replaces itself with Grok, so Grok keeps its process id and closing its session closes everything it started.
_GROK_BOOT = 'import fcntl, os, sys, termios; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0); os.execv(sys.argv[1], sys.argv[1:])'


def _grok_percent(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100 else None


def grok_usage_json(path, env):
    """Percent left from `grok usage --json`, or None while that command cannot report it (or reports it in a form Zook does not know)."""
    try: proc = subprocess.Popen([path, 'usage', '--json'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    except OSError: return None
    try: out, _ = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired: out = None
    finally:
        try: os.killpg(proc.pid, _signal.SIGKILL)  # whatever it started goes too; its group is still its own until it is reaped
        except OSError: pass
        try: proc.wait(5)
        except subprocess.TimeoutExpired: pass
    text = (out or b'').decode('utf-8', 'replace').strip()
    if out is None or proc.returncode != 0 or not text.startswith('{'): return None
    try: data = json.loads(text)
    except ValueError: return None
    found = []
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _GROK_LEFT_KEYS and _grok_percent(value) is not None: found.append(_grok_percent(value))
                elif key in _GROK_USED_KEYS and _grok_percent(value) is not None: found.append(100 - _grok_percent(value))
                else: walk(value)
        elif isinstance(node, list):
            for value in node: walk(value)
    walk(data)
    return found[0] if len(found) == 1 else None  # more than one figure: which one is the weekly limit is not known, so none is used


def grok_screen_left(path, env, folder, wait=None):
    """Percent left as Grok's own screen shows it, or None. Grok and everything it started are closed before this returns."""
    folder = pathlib.Path(folder)
    if folder.is_symlink(): return None
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    empty = not any(folder.iterdir())  # only an empty folder of Zook's own is ever trusted
    master, slave = _pty.openpty()
    try: _fcntl.ioctl(slave, _termios.TIOCSWINSZ, _struct.pack('HHHH', 40, 140, 0, 0))
    except OSError: pass
    screen_env = dict(env, TERM='xterm-256color', COLUMNS='140', LINES='40', PWD=str(folder))
    try: proc = subprocess.Popen([sys.executable, '-I', '-c', _GROK_BOOT, path], stdin=slave, stdout=slave, stderr=slave, cwd=str(folder), env=screen_env, close_fds=True)
    except OSError:
        os.close(master); os.close(slave); return None
    os.close(slave)
    seen, left, end = b'', None, time.time() + (wait or GROK_SCREEN_WAIT)
    names = {str(folder), os.path.realpath(str(folder))}
    sent, settled, quiet_since = None, False, time.time()  # when 「y」 went out, whether Grok reacted, since when nothing new arrived
    try:
        while time.time() < end and left is None:
            ready, _, _ = _select.select([master], [], [], 0.3)
            if not ready:
                if proc.poll() is not None: break
                # Answer only on a still screen whose last question is the trust question for this very folder, never twice
                # once Grok has reacted, and never when anything else (such as data sharing) shows after it.
                screen = GROK_CODES.sub('', seen.decode('utf-8', 'replace'))
                last = screen[screen.rfind(GROK_TRUST):] if GROK_TRUST in screen else ''
                if (empty and last and not settled and (sent is None or time.time() - sent > 1.5) and time.time() - quiet_since > 0.8 and
                        any(n in last for n in names) and 'Yes, proceed' in last and not any(q in last for q in GROK_OTHER_QUESTIONS)):
                    if sent is not None and time.time() - sent > 6: break  # it never took the answer: give up rather than keep typing
                    os.write(master, b'y'); sent = time.time()
                continue
            try: chunk = os.read(master, 65536)
            except OSError: break
            if not chunk: break
            quiet_since = time.time()
            if sent: settled = True
            seen = (seen + chunk)[-200000:]
            found = GROK_LEFT.findall(GROK_CODES.sub('', seen.decode('utf-8', 'replace')))
            if found: left = _grok_percent(float(found[-1]))  # the newest figure on the screen
    finally:
        try: os.close(master)  # Grok's terminal goes away, which ends its session
        except OSError: pass
        deadline = time.time() + 2
        while time.time() < deadline:
            try:
                if os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT): break  # exited; not reaped yet
            except (OSError, AttributeError): break
            time.sleep(0.1)
        try: os.killpg(proc.pid, _signal.SIGKILL)  # anything left in Grok's group; the group is still Grok's until it is reaped below
        except OSError: pass
        try: proc.wait(5)
        except subprocess.TimeoutExpired: pass
    return left


def grok_quota(path, env, folder):
    """Grok's plan limit as a quota snapshot, or None when it cannot be read."""
    if not path: return None
    with _grok_screen:  # one Grok screen at a time
        left = grok_usage_json(path, env)
        if left is None: left = grok_screen_left(path, env, folder)
    if left is None: return None
    return dict(windows=[dict(label='每週', usedPercent=round(100 - left, 1), resetsAt=None)], plan='', limitReached=None, credits={}, resetCredits=None, updatedAt=NOW(), source='live')


def grok_live_quota(app, account=None):
    """Grok's limit for the usage page and 自動選擇, at most once a minute per account. Saved like the other CLIs' limits."""
    store = app.store; key = 'grok' + ('@' + account['id'] if account else '')
    caches = app.__dict__.setdefault('codex_quota_caches', {})
    with _grok_reading: lock = _grok_keys.setdefault(key, threading.Lock())
    with lock:  # a second request for the same account waits for the first and takes its answer
        hit = caches.get(key)
        if hit and time.time() - hit[0] < (60 if hit[1] else 600): return hit[1]  # a failed read waits ten minutes, so the page never keeps waiting on it
        try: live = grok_quota(find_cli('grok'), provider_env('grok', account), store.dir / 'grok-usage')
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError): live = None
        caches[key] = (time.time(), live)
    if live:
        with store.lock: store.data.setdefault('quota', {})[key] = live; store.save()
    return live
