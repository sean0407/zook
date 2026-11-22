# Extra Antigravity accounts. Loaded by backend/server.py into one shared namespace.
#
# agy keeps its sign-in under $HOME (~/.gemini/antigravity-cli) and no other variable moves it, so an extra account runs agy with
# HOME set to the account's own folder (accounts/<id>). The user's everyday folders are linked into it, so ~/Desktop and the like
# still mean the user's own files. Nothing that holds keys or settings is linked: not ~/.ssh, not ~/.config, not ~/Library as a
# whole (only iCloud Drive inside it).
#
# Only agy sees that folder as home. Every check Zook makes (access scope, approvals, prepare_antigravity_folder, read-only rules,
# 整台 Mac) runs in Zook itself, which keeps the user's real home folder, and the paths Zook hands agy are absolute.
AGY_LINKED = ('Desktop', 'Documents', 'Downloads', 'Pictures', 'Movies', 'Music', 'Library/Mobile Documents')


def agy_link_target(home, name):
    """The user's folder to link, or None when it is missing or really leads somewhere it must not (home itself, ~/Library as a
    whole, or a folder of keys), so a renamed link cannot bring those in."""
    target = home / name
    if not target.is_dir(): return None
    real, top = os.path.realpath(str(target)), os.path.realpath(str(home))
    if real in ('/', top) or real == os.path.join(top, 'Library'): return None
    if any(real == x or real.startswith(x + '/') for x in (os.path.join(top, d) for d in AGY_NEVER)): return None
    return target


AGY_NEVER = ('.ssh', '.config', '.aws', '.gnupg', '.docker', '.kube', 'Library/Keychains', 'Library/Application Support', 'Library/Preferences')


def agy_account_home(account_id, home=None):
    """The folder agy uses as home for one extra account, with the user's everyday folders linked in. A real folder agy made at
    one of those names is left alone; a link pointing anywhere else is put back."""
    folder = account_dir(account_id); home = pathlib.Path(home or pathlib.Path.home())
    if folder.is_symlink() or folder.parent.is_symlink(): raise RuntimeError('帳號資料夾不正確，請移除這個帳號後重新新增。')
    library = folder / 'Library'
    if library.is_symlink() or (os.path.lexists(str(library)) and not library.is_dir()): library.unlink()  # never the user's whole Library
    for name in AGY_LINKED:
        target, link = agy_link_target(home, name), folder / name
        if link.parent != folder: link.parent.mkdir(mode=0o700, exist_ok=True)
        if link.is_symlink():
            if target and os.readlink(str(link)) == str(target): continue
            link.unlink()
        elif os.path.lexists(str(link)): continue
        if target: os.symlink(str(target), str(link))
    agy_keychain(account_id, folder)
    return folder


# agy saves its sign-in through /usr/bin/security into the default keychain, which macOS looks up under $HOME as
# Library/Keychains/login.keychain-db. The account's home has none, so macOS asks "a keychain cannot be found". Each extra account
# gets its own keychain there instead; its random password lives in the user's own login keychain and only ever reaches `security`
# on stdin (`security -i`), never on a command line, in the environment, a file or a log. The user's search list and default
# keychain are never touched: every `security` call on the account keychain runs with HOME set to the account's folder.
# A keychain file named login.keychain-db cannot be unlocked with a password, so the real file has another name and
# login.keychain-db is a link to it, which is still what the default lookup finds.
AGY_KEYCHAIN_SERVICE = 'Zook Antigravity keychain'
AGY_KEYCHAIN = 'zook-agy.keychain-db'
_agy_keychain_cache = {}


def _agy_security(command, home):
    """One `security -i` command read from stdin, so nothing secret is on a command line. True when it worked."""
    env = dict(os.environ, HOME=str(home))
    try: p = subprocess.run(['/usr/bin/security', '-i'], input=(command + '\n').encode(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired): return False
    return p.returncode == 0


def _agy_secret_file(account_id):
    folder = os.environ.get('ZOOK_SECRETS_DIR')  # tests: a file instead of the user's keychain
    return pathlib.Path(folder) / ('agy-keychain-' + account_id) if folder else None


def _agy_keychain_password(account_id, new=None):
    """The account keychain's password from the user's login keychain; with `new`, store it first."""
    file = _agy_secret_file(account_id)
    if new is not None:
        _agy_keychain_cache.pop(account_id, None)
        if file:
            fd = os.open(str(file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f: f.write(new)
        elif not _agy_security('add-generic-password -U -s %s -a %s -w %s' % (shlex.quote(AGY_KEYCHAIN_SERVICE), account_id, new), pathlib.Path.home()): return ''
    if account_id in _agy_keychain_cache: return _agy_keychain_cache[account_id]
    if file:
        try: value = file.read_text().strip()
        except OSError: value = ''
    else:
        try: p = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', AGY_KEYCHAIN_SERVICE, '-a', account_id, '-w'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.TimeoutExpired): return ''
        value = p.stdout.decode('utf-8', 'replace').strip() if p.returncode == 0 else ''
    if value: _agy_keychain_cache[account_id] = value
    return value


def agy_keychain(account_id, folder):
    """Make sure the account's own keychain exists, is the default one under its home, and is unlocked with no auto-lock.
    An account made before this (or whose password went missing) gets a new one. Problems are not fatal: agy then falls back
    to its own files, as it did before."""
    keychains = folder / 'Library' / 'Keychains'
    try:
        if keychains.is_symlink() or (os.path.lexists(str(keychains)) and not keychains.is_dir()): keychains.unlink()
        keychains.mkdir(mode=0o700, parents=True, exist_ok=True)
        real, link = keychains / AGY_KEYCHAIN, keychains / 'login.keychain-db'
        if real.is_symlink(): real.unlink()
        password = _agy_keychain_password(account_id) if real.is_file() else ''
        if not password:
            for path in (real, link):
                if os.path.lexists(str(path)): path.unlink()
            password = secrets.token_hex(32)
            if not _agy_keychain_password(account_id, password): return False
            if not _agy_security('create-keychain -p %s %s' % (password, shlex.quote(str(real))), folder): return False
        if not link.is_symlink() or os.readlink(str(link)) != AGY_KEYCHAIN:
            if os.path.lexists(str(link)): link.unlink()
            os.symlink(AGY_KEYCHAIN, str(link))
        target = shlex.quote(str(real))
        return _agy_security('unlock-keychain -p %s %s' % (password, target), folder) and _agy_security('set-keychain-settings ' + target, folder)
    except OSError: return False


def agy_keychain_forget(account_id):
    """When an extra account is removed, its keychain password goes too; the keychain file goes with the account's folder."""
    _agy_keychain_cache.pop(account_id, None)
    if not ACCOUNT_ID.fullmatch(account_id or ''): return
    file = _agy_secret_file(account_id)
    if file:
        try: file.unlink()
        except OSError: pass
        return
    try: subprocess.run(['/usr/bin/security', 'delete-generic-password', '-s', AGY_KEYCHAIN_SERVICE, '-a', account_id],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired): pass


def can_add_login(provider):
    """Whether another sign-in can be added: the CLI keeps a whole account in one folder and has a way to sign in to it."""
    return provider in ACCOUNT_HOME and bool(login_methods(provider) or provider == 'antigravity')  # agy signs in only in Terminal


def terminal_login_script(provider, account=None):
    """A small script that opens the CLI's own sign-in in Terminal. For an extra Antigravity account it runs agy in that account's home."""
    path = find_cli(provider); s = P.spec(_active['data'], provider) or {}
    if not path or not s.get('terminal_login'): raise ValueError('這個模型不能用終端機登入。')
    if account and (provider != 'antigravity' or account.get('type') != 'login'): raise ValueError('這個帳號不能用終端機登入。')
    folder = _active['dir'] / 'tools'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    script = folder / (provider + ('-' + account['id'] if account else '') + '-login.command')
    lines = ['#!/bin/sh']
    if account:
        home = agy_account_home(account['id']); start = home / '.zook-login'  # an empty folder: agy does not look through the linked ones
        if start.is_symlink() or (os.path.lexists(str(start)) and not start.is_dir()): start.unlink()
        start.mkdir(mode=0o700, exist_ok=True)
        lines += ['export HOME=%s' % shlex.quote(str(home)), 'cd %s || exit 1' % shlex.quote(str(start))]
    lines.append('exec ' + ' '.join(shlex.quote(x) for x in [path] + list(s.get('terminal_args') or [])))
    if os.path.lexists(str(script)): script.unlink()  # written fresh, never through a link left in its place
    fd = os.open(str(script), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o700)
    with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write('\n'.join(lines) + '\n')
    _agy_status.clear()
    return script
