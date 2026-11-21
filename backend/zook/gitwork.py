# 提交到 git: a Codex Bot that works in a chosen folder cannot write the folder's .git (Codex's sandbox keeps it read-only, and
# Zook's own file tools refuse it), so Zook makes the commit for it, outside the sandbox, as the user.
# Running git there must not run anything planted in the repository: hooks are switched off, and Zook refuses (so the user commits)
# when the repository's own settings hold anything but a short list of plain ones, when anything inside .git is a link (git would
# write through it), when a nested repository is added, or when the repository is shared or borrows another one's data.

GIT_PLAIN = re.compile(r'^(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks|autocrlf|eol|safecrlf|'
                       r'quotepath|untrackedcache|checkstat|trustctime)|extensions\.(objectformat|refstorage)|user\.(name|email)|init\.defaultbranch|'
                       r'remote\..+\.(url|pushurl|fetch)|branch\..+\.(remote|merge|rebase)|pull\.(rebase|ff)|gc\.auto)$', re.I)  # nothing here runs a program
GIT_ODD = ('commondir', 'config.worktree', 'worktrees', 'objects/info/alternates')  # shared or borrowed repository data: not a plain repository
GIT_KINDS = ('codex',)  # CLIs whose own tools cannot write .git in a chosen folder (others can, so Zook does not run git after them)


def git_repo(folder):
    """The folder's own .git, when it is a plain repository Zook may commit in; otherwise None."""
    if not folder: return None
    git = pathlib.Path(folder) / '.git'
    try:
        if git.is_symlink() or not git.is_dir() or not (git / 'HEAD').is_file(): return None
    except OSError: return None
    return git


def git_env(folder, git):
    """Only what git needs: no GIT_* from outside, never a prompt, the repository given exactly (git does not look upwards)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_DIR=str(git), GIT_WORK_TREE=str(folder), GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
    return env


GIT_SAFE = ['-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-c', 'commit.gpgSign=false', '-c', 'gc.auto=0']


def git_links(git):
    """A link anywhere inside .git, or a file there that is also somewhere else (a hard link): git would write through it."""
    for top, dirs, files in os.walk(str(git), followlinks=False):
        for name in dirs + files:
            path = os.path.join(top, name)
            try: st = os.lstat(path)
            except OSError: return path
            if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)): return path
            # git never rewrites an object in place, so objects shared with a local clone are fine; anything else it may append to
            if stat.S_ISREG(st.st_mode) and st.st_nlink > 1 and os.path.relpath(path, str(git)).split(os.sep)[0] != 'objects': return path
    return ''


def git_refusal(git):
    """Why Zook will not run git in this repository, or ''. Reads its settings as a file; nothing in them runs."""
    if any(os.path.lexists(str(git / x)) for x in GIT_ODD): return '這個專案的 git 是共用或借用的（worktree、alternates），請你自己 commit。'
    linked = git_links(git)
    if linked: return '這個專案的 .git 裡有捷徑或連結（%s），為了安全請你自己 commit。' % os.path.relpath(linked, str(git))
    path = git / 'config'
    if path.exists():
        out = subprocess.run(['git', 'config', '--file', str(path), '--no-includes', '--name-only', '--list'], capture_output=True, text=True, timeout=20,
                             env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')}, stdin=subprocess.DEVNULL)
        if out.returncode: return '讀不懂這個專案的 git 設定，請你自己 commit。'
        other = sorted({k for k in out.stdout.split() if not GIT_PLAIN.match(k)})
        if other: return '這個專案的 git 設定有 Zook 不代為處理的項目（%s），為了安全請你自己 commit。' % '、'.join(other[:5])
    return ''


def git_commit(folder, message):
    """git add -A and git commit -m in folder. Returns what was committed, or why nothing was."""
    git = git_repo(folder)
    if not git: raise RuntimeError('這個資料夾不是 git 專案（或 .git 是捷徑、worktree），無法提交。')
    message = str(message or '').strip()
    if not message or len(message) > 2000: raise RuntimeError('commit 訊息需要 1–2000 字。')
    env = git_env(folder, git)
    def check():
        why = git_refusal(git)
        if why: raise RuntimeError(why)
    def run(*args, ok=False):
        try: out = subprocess.run(['git'] + GIT_SAFE + list(args), capture_output=True, text=True, timeout=60, env=env, cwd=str(folder), stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired: raise RuntimeError('git %s 超過 60 秒沒有完成。' % args[0])
        if out.returncode and not ok: raise RuntimeError('git %s 失敗：%s' % (args[0], (out.stderr or out.stdout).strip()[-400:]))
        return out.stdout
    check()
    run('add', '-A')
    raw = run('diff', '--cached', '--raw', '--no-renames', '-z').split('\0')
    metas, paths = raw[0::2], [x for x in raw[1::2]]
    if any(m.startswith(':') and '160000' in m.lstrip(':').split()[:2] for m in metas):  # a nested repository: its own .git may point anywhere
        run('reset', '-q', ok=True)
        raise RuntimeError('變更裡有另一個 git 專案（子模組或巢狀 .git），為了安全請你自己 commit。')
    staged = [p for p in paths if p]
    if not staged: return {'committed': False, 'reason': '沒有變更可以提交。'}
    check()  # once more right before the commit
    run('commit', '-q', '--no-verify', '-m', message)
    head = run('log', '-1', '--format=%h%x00%an%x00%s').split('\0')
    branch = run('rev-parse', '--abbrev-ref', 'HEAD', ok=True).strip()
    return {'committed': True, 'commit': head[0], 'author': head[1] if len(head) > 1 else '', 'branch': branch, 'files': staged[:50], 'fileCount': len(staged)}


def git_tools(store, bot, scope, root, runtime, kind=''):
    """提交到 git, for a Codex Bot that works in a chosen folder (or its own workspace) that is a git repository. With the whole Mac
    its CLI runs git itself. Asking first follows the Bot's 主動性, like any other change it makes."""
    if scope == 'full' or kind not in GIT_KINDS or not git_repo(root): return []
    def commit(args):
        result = git_commit(root, args.get('message'))
        if result.get('committed'): log_activity(store, 'bot', '%s 提交了 git：%s（%s）' % (bot.get('name', 'Bot'), result['commit'], str(args.get('message'))[:60]))
        return result
    return [(runtime._schema('zook_git_commit', 'Commit all current changes in your working folder to its git repository (git add -A, then git commit) '
                             'as the user. Use this instead of running git commit yourself; you cannot write the .git folder. Hooks do not run.',
                             {'message': {'type': 'string', 'description': 'The commit message, clear and specific'}}, ['message'], False), commit, True)]
