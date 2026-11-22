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
    one of those names is left alone; a link pointing anywhere else is put back. Also the account's own keychain (agykeychain.py).
    An account that was just removed is not made again."""
    with agy_account_lock(account_id):
        if not find_account(account_id, 'antigravity') or agy_account_gone(account_id).exists(): raise RuntimeError('找不到這個帳號。')
        return _agy_account_home(account_id, home)


def _agy_account_home(account_id, home):
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
