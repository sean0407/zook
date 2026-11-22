# Each extra Antigravity account's own keychain. Loaded by backend/server.py into one shared namespace.
#
# agy saves its sign-in through /usr/bin/security into the default keychain, which macOS looks up under $HOME as
# Library/Keychains/login.keychain-db. An extra account's home (agyhome.py) had none, so macOS asked "a keychain cannot be found".
# Each extra account now has its own keychain there. Its random password is kept in the user's own login keychain
# (~/Library/Keychains/login.keychain-db, named explicitly) and only ever reaches `security` on stdin (`security -i`): never on a
# command line, in agy's environment, a file or a log. The user's search list and default keychain are never touched: every
# `security` call on the account keychain runs with HOME set to the account's folder.
# A keychain file named login.keychain-db cannot be unlocked with a password, so the real file has another name and
# login.keychain-db is a link to it, which is still what the default lookup finds.
# Setting up, and removing, an account's keychain happens under a lock shared by every Zook process, so two starts of the same
# account cannot each make their own password.
import pwd

AGY_KEYCHAIN_SERVICE = 'Zook Antigravity keychain'
AGY_KEYCHAIN = 'zook-agy.keychain-db'
AGY_KEYCHAIN_ERROR = '無法準備這個 Antigravity 帳號的鑰匙圈，請確認鑰匙圈已解鎖後再試一次。'
_agy_keychain_cache = {}


@contextlib.contextmanager
def agy_account_lock(account_id):
    if not ACCOUNT_ID.fullmatch(account_id or ''): raise ValueError('帳號無效。')
    base = _active['dir'] / 'accounts'; base.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(base / ('.' + account_id + '.lock')), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX); yield
    finally: os.close(fd)


def _agy_arg(value):
    """One argument for `security -i`, which understands double quotes but not shell quoting."""
    value = str(value)
    if any(c in value for c in '"\\\n\r\0'): raise RuntimeError(AGY_KEYCHAIN_ERROR)
    return '"%s"' % value


def _agy_security(command, home):
    """One `security -i` command for the account keychain, read from stdin, with HOME the account's folder. True when it worked."""
    try: p = subprocess.run(['/usr/bin/security', '-i'], input=(command + '\n').encode(), env=dict(os.environ, HOME=str(home)), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired): return False
    return p.returncode == 0


def agy_host_keychain():
    return os.path.join(pwd.getpwuid(os.getuid()).pw_dir, 'Library', 'Keychains', 'login.keychain-db')


def agy_host_ready():
    """Whether the user's login keychain is there and Zook can open the file: only then does "no such item" mean none."""
    path = agy_host_keychain()
    return os.path.isfile(path) and os.access(path, os.R_OK | os.W_OK)


def _agy_host(args, command=None):
    """`security` on the user's own login keychain: (exit code, output). A command with a secret goes on stdin."""
    try:
        if command is None: p = subprocess.run(['/usr/bin/security'] + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        else: p = subprocess.run(['/usr/bin/security', '-i'], input=(command + '\n').encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired): return -1, ''
    return p.returncode, p.stdout.decode('utf-8', 'replace') if p.stdout else ''


def _agy_secret_file(account_id):
    folder = os.environ.get('ZOOK_SECRETS_DIR')  # tests that start a whole Zook: a file instead of the user's keychain
    return pathlib.Path(folder) / ('agy-keychain-' + account_id) if folder else None


def agy_keychain_password(account_id):
    """The account keychain's password; '' when there surely is none. Raises when it cannot be read just now (the login keychain
    is locked, access was refused, `security` timed out), so nothing is replaced on a guess."""
    if account_id in _agy_keychain_cache: return _agy_keychain_cache[account_id]
    file = _agy_secret_file(account_id)
    if file:
        try: value = file.read_text().strip()
        except FileNotFoundError: value = ''
        except OSError: raise RuntimeError(AGY_KEYCHAIN_ERROR)
    else:
        code, out = _agy_host(['find-generic-password', '-s', AGY_KEYCHAIN_SERVICE, '-a', account_id, '-w', agy_host_keychain()])
        if code == 44 and agy_host_ready(): return ''  # errSecItemNotFound, from a login keychain that is really there
        if code != 0 or not out.strip(): raise RuntimeError(AGY_KEYCHAIN_ERROR)
        value = out.strip()
    if value: _agy_keychain_cache[account_id] = value
    return value


def _agy_keychain_store(account_id, password):
    _agy_keychain_cache.pop(account_id, None)
    file = _agy_secret_file(account_id)
    if file:
        fd = os.open(str(file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f: f.write(password)
    else:
        _agy_host(None, 'add-generic-password -U -s %s -a %s -w %s %s' % (_agy_arg(AGY_KEYCHAIN_SERVICE), account_id, password, _agy_arg(agy_host_keychain())))
    if agy_keychain_password(account_id) != password: raise RuntimeError(AGY_KEYCHAIN_ERROR)


def agy_keychain_forget(account_id):
    """Remove the account keychain's password from the user's login keychain. True when it is gone (or was never there)."""
    _agy_keychain_cache.pop(account_id, None)
    if not ACCOUNT_ID.fullmatch(account_id or ''): return False
    file = _agy_secret_file(account_id)
    if file:
        try: file.unlink()
        except FileNotFoundError: pass
        except OSError: return False
        return True
    return _agy_host(['delete-generic-password', '-s', AGY_KEYCHAIN_SERVICE, '-a', account_id, agy_host_keychain()])[0] in (0, 44)


def _agy_set_aside(path):
    """Keep a file Zook will not use beside it instead of deleting it."""
    n = 0
    while True:
        spare = path.with_name('%s.zook-old-%s%s' % (path.name, time.strftime('%Y%m%d%H%M%S'), '-%d' % n if n else ''))
        if not os.path.lexists(str(spare)): break
        n += 1
    os.rename(str(path), str(spare))


def agy_keychain(account_id, folder):
    """Lock held. Make sure the account's own keychain exists, is the default one under its home, and is unlocked with no
    auto-lock. An account made before this gets one. Raises when it cannot be done, so agy is not started into the dialog."""
    keychains = folder / 'Library' / 'Keychains'
    try:
        if keychains.is_symlink() or (os.path.lexists(str(keychains)) and not keychains.is_dir()): keychains.unlink()
        keychains.mkdir(mode=0o700, parents=True, exist_ok=True)
        real, link = keychains / AGY_KEYCHAIN, keychains / 'login.keychain-db'
        if real.is_symlink() or (os.path.lexists(str(real)) and not real.is_file()): real.unlink()  # never one of ours
        password = agy_keychain_password(account_id) if real.is_file() else ''
        if real.is_file() and not password: _agy_set_aside(real)  # surely no password: it cannot be opened again, but is kept
        if not password:
            password = secrets.token_hex(32)
            if not _agy_security('create-keychain -p %s %s' % (password, _agy_arg(real)), folder): raise RuntimeError(AGY_KEYCHAIN_ERROR)
            try: _agy_keychain_store(account_id, password)
            except Exception:
                real.unlink(); raise  # nothing half made: the next start begins again
        if link.is_symlink():
            if os.readlink(str(link)) != AGY_KEYCHAIN: link.unlink()
        elif os.path.lexists(str(link)): _agy_set_aside(link)  # one an earlier sign-in left: kept
        if not os.path.lexists(str(link)): os.symlink(AGY_KEYCHAIN, str(link))
        prefs = folder / 'Library' / 'Preferences' / 'com.apple.security.plist'
        if os.path.lexists(str(prefs)): _agy_set_aside(prefs)  # another default keychain or search list set in this home
        target = _agy_arg(real)
        if not (_agy_security('unlock-keychain -p %s %s' % (password, target), folder) and _agy_security('set-keychain-settings ' + target, folder)):
            raise RuntimeError(AGY_KEYCHAIN_ERROR)
        try: shown = subprocess.run(['/usr/bin/security', 'default-keychain'], env=dict(os.environ, HOME=str(folder)), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20).stdout.decode('utf-8', 'replace')
        except (OSError, subprocess.TimeoutExpired): shown = ''
        if str(real) not in shown and os.path.realpath(str(real)) not in shown: raise RuntimeError(AGY_KEYCHAIN_ERROR)
    except OSError: raise RuntimeError(AGY_KEYCHAIN_ERROR)


def _agy_alive(pid):
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except OSError: return True
    try: state = subprocess.run(['/bin/ps', '-o', 'stat=', '-p', str(pid)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10).stdout.decode().strip()
    except (OSError, subprocess.TimeoutExpired): return True
    return bool(state) and not state.startswith('Z')  # a zombie has already ended


def _agy_stop_in(folder):
    """End the processes working inside the account's folder (a Terminal sign-in runs there) and wait until they are gone.
    False when that cannot be checked or done."""
    top = os.path.realpath(str(folder))
    try: out = subprocess.run(['/usr/sbin/lsof', '-nP', '-w', '-d', 'cwd', '-Fpn'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30).stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.TimeoutExpired): return False
    if not out.strip(): return False  # it always sees at least Zook itself
    pids, pid = set(), None
    for line in out.splitlines():
        if line.startswith('p'): pid = int(line[1:]) if line[1:].isdigit() else None
        elif line.startswith('n') and pid and pid != os.getpid() and (line[1:] == top or line[1:].startswith(top + '/')): pids.add(pid)
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 3)):
        for pid in pids:
            try: os.kill(pid, sig)
            except OSError: pass
        end = time.monotonic() + wait
        while pids and time.monotonic() < end:
            pids = {p for p in pids if _agy_alive(p)}
            if pids: time.sleep(0.1)
        if not pids: return True
    return False


def agy_account_gone(account_id):
    """Set on disk when an account is removed, so another Zook still holding it in memory does not make it again."""
    return _active['dir'] / 'accounts' / ('.' + account_id + '.removed')


def agy_account_remove(app, account_id):
    """After the account left the list: end its agy (kept open or signing in), then remove its folder and its keychain password.
    '' when all of it is gone; otherwise why not, with everything as it was, and the caller puts the account back."""
    folder = _active['dir'] / 'accounts' / account_id; aside = folder.with_name('.' + account_id + '.removing')
    with agy_account_lock(account_id):
        gone = agy_account_gone(account_id); gone.touch(mode=0o600)
        guard = app.__dict__.get('live_lock')
        if guard:
            with guard:
                for cli in [c for c in app.lives.values() if getattr(c, 'home', '') == str(folder)]: live_close(app, cli, wait=3)
        problem = ''
        if not _agy_stop_in(folder): problem = '無法結束這個帳號正在執行的 Antigravity，帳號沒有移除，請關掉它的終端機視窗後再試一次。'
        else:
            try:
                if os.path.lexists(str(aside)): shutil.rmtree(str(aside))
                if os.path.lexists(str(folder)): os.rename(str(folder), str(aside))
            except OSError: problem = '無法刪除這個帳號的資料夾，帳號沒有移除，請稍後再試。'
            if not problem and not agy_keychain_forget(account_id):
                problem = '無法從鑰匙圈刪除這個帳號的密碼，帳號沒有移除。請確認鑰匙圈已解鎖後再試一次。'
                try:
                    if os.path.lexists(str(aside)): os.rename(str(aside), str(folder))  # its sign-in still opens
                except OSError: pass
        if problem:
            try: gone.unlink()
            except OSError: pass
            return problem
        shutil.rmtree(str(aside), ignore_errors=True)
    return ''
