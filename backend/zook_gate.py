#!/usr/bin/env python3
"""The shared 「先問」 gate for a CLI's own tools (Claude's PreToolUse hook; cursor_guard.py uses it for Cursor).

A Bot whose CLI has the whole Mac works without asking, except at the safety boundaries the user named:
  delete   deleting files (rm, trash, find -delete, moving to the Trash or into the scratch folders, a Write or Edit that empties a
           file), anywhere but the Bot's own scratch files (decisions #28): see _scratch_line
  send     sending something out (mail, posting with curl/wget, scp/rsync/ssh to another machine, git push, gh create/merge/comment)
  secret   keys, passwords and accounts (~/.ssh, ~/.aws, ~/.config/gh, .env, the Keychain, the security command), reading too,
           and searching a folder that holds them
  install  installing software;  system  changing system settings (sudo, defaults write, launchctl, …)
  guard    changing Zook's own safety checks: the app itself, and the hooks and settings Zook writes for a CLI
  unclear  a command that cannot be read reliably (a variable as the command, broken quoting, inline code that may do any of the above)
Every boundary in one tool call is listed on one approval card, one line each; the card holds what is done and where, never the
command itself (it may hold a password). The answer comes from Zook through the reply's worker address and token
(ZOOK_WORKER_URL, ZOOK_WORKER_TOKEN). Anything else is let through. Anything unexpected (no address, no answer, an error, a
timeout) is a refusal.

This is a careful reading of what the CLI asked for, not a sandbox: a program written to a file and run later is not read.
"""
import hmac, json, os, re, shlex, shutil, stat, sys, time, urllib.error, urllib.parse, urllib.request

MAX_INPUT = 4 * 1024 * 1024
HOME = os.path.expanduser('~')
HERE = os.path.dirname(os.path.realpath(__file__))
LABELS = {'split': '一次做了好幾次傳送', 'delete': '刪除檔案', 'send': '對外送出', 'secret': '動到金鑰或密碼', 'install': '安裝軟體', 'system': '改系統設定',
          'guard': '改動 Zook 的安全檢查', 'unclear': '執行無法判讀的指令'}
KINDS = tuple(LABELS)
MAX_ACTIONS = 10   # what one card shows in full; more than this, or a line too long to show whole, is refused: the Bot does them one at a time
MAX_TITLE = 200

# ---- what counts as a boundary
DELETE_COMMANDS = {'rm', 'rmdir', 'unlink', 'trash', 'srm', 'shred'}
MAIL_COMMANDS = {'mail', 'mailx', 'sendmail', 'msmtp', 'mutt'}
COPY_OUT = {'scp', 'sftp', 'rsync', 'ftp'}
CONNECT = {'ssh', 'nc', 'ncat', 'netcat', 'socat', 'telnet'}
SYSTEM_COMMANDS = {'sudo', 'su', 'doas', 'launchctl', 'systemsetup', 'networksetup', 'pmset', 'nvram', 'csrutil', 'spctl', 'softwareupdate',
                   'installer', 'kextload', 'kextunload', 'scutil', 'dscl', 'chsh', 'crontab', 'diskutil', 'tmutil', 'fdesetup', 'profiles'}
INSTALLERS = {'brew': {'install', 'uninstall', 'remove', 'rm', 'reinstall', 'upgrade', 'tap', 'untap', 'link', 'unlink', 'services', 'autoremove', 'cleanup', 'update', 'pin', 'unpin'},
              'port': {'install', 'uninstall', 'upgrade', 'selfupdate'}, 'mas': {'install', 'uninstall', 'upgrade'},
              'gem': {'install', 'uninstall', 'update'}, 'cargo': {'install', 'uninstall'}, 'pipx': {'install', 'uninstall', 'upgrade', 'reinstall', 'inject'},
              'pip': {'install', 'uninstall', 'download'}, 'pip3': {'install', 'uninstall', 'download'}, 'conda': {'install', 'remove', 'update', 'create'},
              'go': {'install'}}
NODE_INSTALLERS = {'npm', 'pnpm', 'yarn', 'bun'}
SECRET_DIRS = [os.path.join(HOME, p) for p in ('.ssh', '.aws', '.config/gh', '.gnupg', 'Library/Keychains', '.docker', '.kube', '.netrc', '.config/gcloud', '.git-credentials', '.npmrc', '.pypirc')] + ['/Library/Keychains']
# The sign-ins of the CLIs Zook runs (providers.py) and Zook's own extra accounts: reading them is reading a password.
CREDENTIALS = [os.path.join(HOME, p) for p in ('.codex/auth.json', '.gemini/oauth_creds.json', '.gemini/google_accounts.json', '.claude/.credentials.json',
                                               '.grok', '.config/cursor', '.cursor/cli-config.json', '.cursor/auth.json', '.config/anthropic', '.antigravity/auth')]
CREDENTIAL_NAMES = re.compile(r'(?i)^(?:\.env(?:\..*)?|\.netrc|\.npmrc|\.pypirc|\.git-credentials|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|.*\.(?:pem|p12|pfx|key|keychain|keychain-db)|'
                              r'credentials(?:\.json)?|\.credentials\.json|oauth_creds\.json|auth\.json|client_secret.*\.json|service[-_]account.*\.json)$')
SYSTEM_DIRS = ('/System', '/Library', '/usr', '/bin', '/sbin', '/etc', '/private', '/Applications', '/opt', '/var', os.path.join(HOME, 'Library/LaunchAgents'))
TEMP_DIRS = ['/tmp', '/private/tmp', '/var/folders', '/private/var/folders']
# The folders a CLI loads hooks, settings, Skills and plugins from, wherever they are (the home folder or a Bot's workspace).
CLI_FOLDERS = {'.claude', '.cursor', '.codex', '.grok', '.gemini', '.antigravity', 'cursor-config'}
WRAPPERS = {'env', 'nohup', 'time', 'command', 'builtin', 'exec', 'nice', 'caffeinate', 'timeout', 'xargs', 'stdbuf', 'arch', 'noglob', 'nocorrect'}
WRAPPER_VALUED = {'env': {'-u', '-P', '-C'}, 'nice': {'-n'}, 'timeout': {'-s', '-k', '--signal', '--kill-after'}, 'caffeinate': {'-t', '-w'},
                  'xargs': {'-I', '-J', '-L', '-n', '-P', '-R', '-S', '-s', '-E', '-d', '-a'}, 'stdbuf': {'-i', '-o', '-e'}, 'time': {'-o', '-f'}, 'exec': {'-a'}}
SHELL_WORDS = {'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until', '!', '{', '}', 'coproc'}  # what runs after them is a command too
SHELLS = {'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish'}
INTERPRETERS = {'python', 'python3', 'python2', 'node', 'nodejs', 'perl', 'ruby', 'php', 'deno', 'bun', 'osascript', 'lua', 'Rscript', 'swift'}
INLINE_FLAGS = {'-c', '-e', '-E', '--eval', '-p', '--print', '-r'}
CURL_SEND = {'-d', '--data', '--data-raw', '--data-binary', '--data-urlencode', '--data-ascii', '-F', '--form', '--form-string', '-T', '--upload-file', '--json',
             '-K', '--config', '--mail-rcpt', '--mail-from'}
WGET_SEND = ('--post-data', '--post-file', '--method', '--body-data', '--body-file')
GH_ACTIONS = {'create', 'merge', 'comment', 'review', 'close', 'reopen', 'delete', 'edit', 'upload', 'publish', 'fork', 'transfer', 'archive', 'lock', 'ready', 'set', 'sync', 'deploy', 'run', 'cancel', 'rerun'}
GH_VALUED = {'-R', '--repo', '--hostname', '-b', '--body', '-t', '--title', '-F', '--body-file', '-B', '--base', '-H', '--head', '-a', '--assignee', '-l', '--label',
             '-m', '--milestone', '-p', '--project', '-r', '--reviewer', '-X', '--method', '-f', '--raw-field', '--field', '--input', '-q', '--jq', '--template',
             '--json', '-L', '--limit', '-s', '--state', '-A', '--author', '-S', '--search', '-o', '--output', '-e', '--env', '-n', '--notes', '-c'}
GIT_VALUED = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env', '--exec-path', '--list-cmds', '--attr-source'}
GIT_FLAGS = {'-p', '--paginate', '-P', '--no-pager', '--bare', '--no-replace-objects', '--literal-pathspecs', '--glob-pathspecs', '--noglob-pathspecs',
             '--icase-pathspecs', '--no-optional-locks', '--html-path', '--man-path', '--info-path', '--version', '--help', '-v', '-h', '--no-lazy-fetch', '--no-advice'}
GREP_VALUED = {'-e', '-f', '-m', '-A', '-B', '-C', '--regexp', '--file', '--max-count', '--include', '--exclude', '--exclude-dir', '--context', '--after-context',
               '--before-context', '--label', '-g', '--glob', '-t', '--type', '-T', '--type-not', '-M', '--max-columns', '--max-depth', '-j', '--threads', '--iglob'}
# Inline code (python -c, node -e, a here-document) that may delete, send, run commands or touch keys: it cannot be read reliably.
CODE_HINTS = re.compile(r'\b(?:os\.(?:remove|unlink|rmdir|removedirs|system|popen|exec\w*|spawn\w*|rename|replace)|shutil\.(?:rmtree|move)|subprocess|send2trash|'
                        r'unlink(?:Sync)?|rmSync|renameSync|moveItem|removeItem|File\.rename|FileUtils|rmdirSync|rm_rf|child_process|execSync|spawnSync|requests\.|httpx|urlopen|urllib|http\.client|smtplib|ftplib|'
                        r'paramiko|socket|fetch\s*\(|XMLHttpRequest|keyring|Keychain|system\s*\(|exec\s*\(|eval\s*\(|IO\.popen|File\.delete|Net::|LWP|'
                        r'do shell script|delete\b|trash\b)|\.ssh\b|\.aws\b|\.env\b|id_rsa|id_ed25519|password|passwd|`', re.I)


# ---- the Bot's own scratch files (decisions #28): deleted without asking
# Only a file that really is (after links) in /tmp or the Mac's temporary folder, or one in a folder $(mktemp …) made in the same
# command line. Never the folder itself, a wildcard, a .., a link, a file with another name (hard link), or one under sudo, sh -c, $( ),
# find or xargs. The line may hold only commands that cannot move, link or rename anything (so nothing in it can swap where a path
# leads between this check and the delete), and moving a file into the scratch folders is asked as a delete.
SCRATCH = re.compile(r'(?:/private/tmp|/private/var/folders/[^/]+/[^/]+/T)/')
SCRATCH_COMPANIONS = {'rm', 'unlink', 'echo', 'printf', 'cat', 'ls', 'test', '[', '[[', 'true', 'false', ':', 'sleep', 'mkdir', 'touch', 'wc',
                      'head', 'tail', 'grep', 'file', 'stat', 'du', 'date', 'pwd', 'mktemp', 'sort', 'uniq', 'cut', 'tr', 'diff', 'cmp', 'shasum', 'md5'}
SCRATCH_RUNNERS = {'python', 'python3', 'node', 'ruby', 'swift'}  # running a file: what a program does is never read (see the top)
MKTEMP_SET = re.compile(r'(?:^|(?<=[;\n]))[ \t]*([A-Za-z_]\w*)=("?)\$\(mktemp((?:[ \t]+[\w./+-]+)*)[ \t]*\)\2[ \t]*(?=$|[;&|\n])')
SHELL_VARS = {'PATH', 'HOME', 'PWD', 'OLDPWD', 'IFS', 'TMPDIR', 'CDPATH', 'ENV', 'BASH_ENV', 'SHELL', 'ZDOTDIR', 'FPATH', 'PS4', 'PROMPT_COMMAND',
              'REPLY', 'reply', 'path', 'cdpath', 'fpath', 'manpath', 'module_path', 'mailpath', 'fignore', 'psvar', 'argv', 'status',
              'pipestatus', 'options', 'parameters', 'functions', 'aliases', 'commands', 'builtins'}


def _scratch_place(path):
    """Whether a path really is (after links) in /tmp or the Mac's temporary folder; the folder itself counts."""
    p = _expand(path)
    if not p or '$' in p or '`' in p: return False
    return bool(SCRATCH.match(os.path.realpath(_abs(p)).rstrip('/') + '/'))


def _into_scratch(dest, whole):
    """A move's destination is, or may be, a scratch folder: only a written-out path, read against a folder the line does not change,
    is surely elsewhere (a variable, a wildcard, {a,b}, or cd / pushd / env -C in the line may lead into /tmp)."""
    if not dest or set(dest) & set('$`*?[]{}\\'): return True
    if not os.path.isabs(_expand(dest)) and _moves_folder(whole): return True
    return _scratch_place(dest)


def _moves_folder(whole):
    """The line changes the folder it runs in to one that may be a scratch folder (cd to a variable, a link, a relative path, cd -)."""
    if re.search(r'\benv\b[^;&|\n]*\s(?:-C|--chdir)', whole): return True
    for part in _split(_without_inner(whole))[0]:
        words = _strip(_redirects(part)[0])
        if words and words[0] in ('cd', 'pushd', 'popd', 'chdir'):
            where = next((w for w in words[1:] if not w.startswith('-')), None)
            if words[0] == 'popd' or where is None or set(where) & set('$`*?[]{}\\') or not os.path.isabs(_expand(where)) or _scratch_place(where): return True
    return False


def _scratch_line(command):
    """(the mktemp folders' variable names, whether a $ in a path can be read as written) when this command line may delete scratch files
    without asking; None when it may not: something in it could move, link or rename files, change a variable, or cannot be read."""
    if not isinstance(command, str) or len(command) > 4000: return None
    sets = list(MKTEMP_SET.finditer(command))
    names = [m.group(1) for m in sets]
    for m in sets:
        flags = m.group(3).split()
        if names.count(m.group(1)) != 1 or m.group(1) in os.environ or m.group(1) in SHELL_VARS: return None
        if command[:m.start()].count('"') % 2: return None  # inside a quoted text: never really set
        for i, f in enumerate(flags):  # mktemp -d [-q] [-t prefix] only: a template could name any folder (never -u: no folder made)
            if re.fullmatch(r'-[dq]+|--directory|--quiet', f): continue
            if re.fullmatch(r'-[dq]*t', f) and i + 1 < len(flags) and re.fullmatch(r'[\w.+-]+', flags[i + 1]) and flags[i + 1] not in ('.', '..'): continue
            if i and re.fullmatch(r'-[dq]*t', flags[i - 1]): continue
            return None
    rest = command
    for m in reversed(sets): rest = rest[:m.start()] + ' ; ' + rest[m.end():]
    plain = re.sub(r'\$\{(?:%s)\}' % '|'.join(['TMPDIR'] + names), '', rest)
    if re.search(r'[`(){}#]|<<', plain) or re.search(r'(?<!\$)\bTMPDIR\b', plain): return None  # $( ), a function, a comment; TMPDIR changed
    for name in names:
        for m in re.finditer(r'(?<!\w)%s(?!\w)' % name, rest):
            i, j = m.start(), m.end()
            read = rest[i - 1:i] == '$' and rest[i - 2:i - 1] != '$' or rest[i - 2:i] == '${' and rest[j:j + 1] == '}'
            if not read and rest[i - 1:i] not in ('-', '/', '.'): return None  # read, export, printf -v, d+=, for d in …: it may change
    parts, clear = _split(_without_inner(command))
    if not clear: return None
    for part in parts:
        words, _, written = _redirects(part)
        for t in written:  # rm x > ~/a empties ~/a: only /dev/null, a written-out scratch path, or a file in this line's mktemp folder
            m = re.fullmatch(r'\$(?:\{(\w+)\}|(\w+))/[^/]+', t)
            if t != '/dev/null' and not (m and (m.group(1) or m.group(2)) in names) and not ('$' not in t and os.path.isabs(_expand(t)) and _scratch_place(t)): return None
        while words and words[0] in SHELL_WORDS: words = words[1:]
        if not words or len(words) == 1 and re.fullmatch(r'([A-Za-z_]\w*)=\$_', words[0]) and words[0][:-3] in names: continue  # d=$(mktemp …)
        word = words[0]; name = os.path.basename(word)
        if '/' in word and os.path.dirname(word) not in ('/bin', '/usr/bin'): return None
        if name in SCRATCH_COMPANIONS: continue
        if (name in SCRATCH_RUNNERS or re.fullmatch(r'python3\.\d+', name)) and len(words) > 1 and not words[1].startswith('-'): continue
        return None
    return set(names), "'" not in command and '\\' not in command


def _scratch_file(arg, line):
    """This rm target is one of the Bot's own scratch files: see _scratch_line."""
    names, quoted_right = line
    if '$' in arg:
        if not quoted_right: return False  # '$d/x' or \$d/x is a file called $d…, not the folder
        m = re.fullmatch(r'\$(?:\{(\w+)\}|(\w+))/([^/]+)', arg)
        if m and (m.group(1) or m.group(2)) in names: return m.group(3) not in ('.', '..') and not set(m.group(3)) & set('*?[]{}$`~\\')
        tmp = os.environ.get('TMPDIR', '')
        if not os.path.isabs(tmp): return False
        arg = re.sub(r'\$\{TMPDIR\}|\$TMPDIR\b', lambda _: tmp, arg)
        if '$' in arg: return False
    if not os.path.isabs(arg) or set(arg) & set('*?[]{}`') or arg.endswith('/') or '..' in arg.split('/'): return False
    try: info = os.lstat(arg)
    except OSError: return False
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid(): return False  # a link, a folder, a second name
    return bool(SCRATCH.match(os.path.realpath(arg)))


def _scratch_only(name, args, line):
    """rm or unlink of nothing but the Bot's own scratch files: not asked."""
    if line is None or name not in ('rm', 'unlink'): return False
    targets, done = [], False
    for a in args:
        if not done and a == '--': done = True; continue
        if not done and a.startswith('-'):
            if name == 'rm' and re.fullmatch(r'-[fiv]+', a): continue
            return False  # -r, -d, -P (overwrites): never
        targets.append(a)
    return bool(targets) and all(_scratch_file(t, line) for t in targets)


def _expand(path):
    path = str(path or '').strip().strip('"\'')
    if path.startswith('@'): path = path[1:]  # curl's @file
    if path.startswith('~'): path = os.path.expanduser(path)
    path = path.replace('${HOME}', HOME).replace('$HOME', HOME)
    tmp = os.environ.get('TMPDIR', '')
    if tmp: path = path.replace('${TMPDIR}', tmp.rstrip('/')).replace('$TMPDIR', tmp.rstrip('/'))
    return path


_CWD = [os.getcwd()]


def _abs(path):
    p = _expand(path)
    return p if os.path.isabs(p) else os.path.join(_CWD[0], p)


def _under(path, folders):
    real = os.path.realpath(_abs(path)) if path else ''
    low = real.lower()
    return any(low == f.lower() or low.startswith(f.lower().rstrip('/') + '/') for f in {x for g in folders for x in (g, os.path.realpath(g))})


def _holds_secrets(path):
    """The folder is, or holds, a folder of keys or a sign-in: a search from it reads them."""
    real = os.path.realpath(_abs(path)).rstrip('/') or '/'
    return any(s == real or s.startswith(real.rstrip('/') + '/') for d in SECRET_DIRS + CREDENTIALS + _accounts_folder() for s in {d, os.path.realpath(d)})


def _accounts_folder():
    data = os.environ.get('ZOOK_DATA_DIR', '')
    return [os.path.join(data, 'accounts')] if data else []


def _secret_path(path):
    if not isinstance(path, str) or not path.strip(): return False
    if (os.path.normpath(_abs(path)) + os.sep).startswith(os.path.join(HOME, '.grok', 'bin') + os.sep): return False  # the program itself, not its sign-in
    return _under(path, SECRET_DIRS + CREDENTIALS + _accounts_folder()) or secret_name(path)


ATTACHED = re.compile(r'^[0-9A-Za-z]{8}-(.+)$')  # an attachment is kept as 「8 characters of its id」-「the name it was uploaded with」


def _uploaded_names(path):
    """The list Zook keeps next to a Bot's attachments folder (.zook-uploads.json): each attachment's name as the user uploaded it.
    Read only when it is a plain file of its own: never through a link, never a pipe that could keep the check waiting."""
    parts = os.path.normpath(path).split(os.sep)
    if 'attachments' not in parts: return {}
    base = os.sep.join(parts[:len(parts) - 1 - parts[::-1].index('attachments')]) or os.sep
    try:
        fd = os.open(os.path.join(base, '.zook-uploads.json'), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: return {}
            found = json.loads(f.read(1 << 20))
    except (OSError, ValueError): return {}
    return {str(k): str(v) for k, v in found.items()} if isinstance(found, dict) else {}


def secret_name(path, original=None):
    """Whether a file is a key, password or sign-in by its name: the name asked for, the name of what it really is (after links), and
    an attachment's name as the user uploaded it. The one judgement for the CLIs' tools and Zook's own file tools (runtime.py)."""
    names = [os.path.basename(_expand(path).rstrip('/'))]
    try: full = os.path.realpath(_abs(path)); names.append(os.path.basename(full))
    except (OSError, ValueError): full = ''
    if original: names.append(os.path.basename(str(original)))
    if 'attachments' in os.path.normpath(_abs(path)).split(os.sep) + full.split(os.sep):
        names += [m.group(1) for m in map(ATTACHED.match, list(names)) if m]
        for one in {_abs(path), full}:
            names.append(_uploaded_names(one).get(os.path.basename(one), ''))  # the name the user uploaded it with (Zook keeps a list)
        names += ['.' + n for n in list(names) if n and not n.startswith('.')]  # a name whose leading dot an upload dropped (.env kept as env)
    return any(CREDENTIAL_NAMES.match(n) for n in names if n)


def _system_path(path):
    if not isinstance(path, str) or not path.strip(): return False
    p = _abs(path)
    return _under(p, SYSTEM_DIRS) and not _under(p, TEMP_DIRS)


def _app_folders():
    """Zook itself: the backend these checks run from (and the whole app when it is one), and Zook's data outside the Bots' workspaces."""
    found = [HERE]
    parts = HERE.split(os.sep)
    for i in range(len(parts), 0, -1):
        if parts[i - 1].endswith('.app'): found.append(os.sep.join(parts[:i])); break
    return found


def _guard_path(path):
    """Writing or deleting here changes what checks the Bot: Zook's app, Zook's data, or a CLI's hooks and settings."""
    if not isinstance(path, str) or not path.strip(): return False
    real = os.path.realpath(_abs(path))
    parts = [p.lower() for p in real.split(os.sep)]
    if re.search(r'/\.cursor/projects/[^/]+/agent-tools(/|$)', '/'.join(parts)): return False  # Cursor's own long tool results, not settings
    if os.path.basename(real) == '.claude.json' or set(parts) & CLI_FOLDERS: return True
    if _under(real, _app_folders()): return True
    data = os.environ.get('ZOOK_DATA_DIR', '')
    if data and _under(real, [data]):
        rest = os.path.relpath(real, os.path.realpath(data)).split(os.sep)
        return not (rest[0] == 'workspaces' and len(rest) > 2)  # a Bot's own files are its work; the rest is Zook's
    return False


def _short(text, most=60):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= most else text[:most - 1] + '…'


def _where(path):
    """Where a file is, whole, so two files of the same name are told apart: ~/… inside the home folder. A web address: its site only."""
    if '$' in str(path) or '`' in str(path): return '「%s」指向的位置' % _short(str(path).strip('"\''), 40)  # a variable: where it points is not known here
    if str(path).lower().startswith('file://'): path = _file_url(str(path))
    elif '://' in str(path): return _host(path) or '網址'
    full = os.path.normpath(_abs(path))
    if full == HOME: return '家目錄'
    return '~' + full[len(HOME):] if full.startswith(HOME + os.sep) else full


def _names(paths):
    return '、'.join(dict.fromkeys(_where(p) for p in paths if p))


def _word(text):
    """A plain name (a subcommand, a package, a remote) for a card; anything else is left out."""
    return text if isinstance(text, str) and re.fullmatch(r'[\w@.+/=-]{1,60}', text) and ':' not in text and not text.startswith('-') else ''


def _host(arg):
    """Where a URL or host:path goes: the host only (a password in the URL is never kept)."""
    arg = str(arg or '')
    if '://' in arg:
        try: return urllib.parse.urlsplit(arg).hostname or ''
        except ValueError: return ''
    if arg.startswith('-'): return ''
    web = re.match(r'^(?:[^@/\s]+@)?([\w-]+(?:\.[\w-]+)+)(?::\d+)?/', arg)  # example.com/a/b: the site only, never the path
    if web: return web.group(1)
    m = re.match(r'^(?:[^@/\s]+@)?([\w.-]+)(?::|$)', arg)
    return m.group(1) if m else ''


CURL_VALUED = CURL_SEND | {'-H', '--header', '-o', '--output', '-u', '--user', '-A', '--user-agent', '-e', '--referer', '-X', '--request', '-b', '--cookie',
                           '-c', '--cookie-jar', '-w', '--write-out', '-x', '--proxy', '-m', '--max-time', '--connect-timeout', '-r', '--range', '-E', '--cert',
                           '--key', '--cacert', '-U', '--proxy-user', '--retry', '--limit-rate', '-z', '--time-cond', '--resolve', '--connect-to', '-D',
                           '--dump-header', '-C', '--continue-at', '-Y', '-y', '--speed-limit', '--speed-time', '--max-redirs', '--interface', '--oauth2-bearer'}


def _file_url(arg):
    try: return urllib.parse.unquote(urllib.parse.urlsplit(arg).path) or '/'
    except ValueError: return arg


def _curl_addresses(args):
    """Every address curl is given: what is not an option or an option's value, and --url's value. With or without https://."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ('--url',): out += args[i + 1:i + 2]; i += 2; continue
        if a.startswith('--url='): out.append(a.split('=', 1)[1]); i += 1; continue
        if a.startswith('-') and a != '-':
            i += 2 if a in CURL_VALUED or (re.fullmatch(r'-[a-zA-Z]*[dFTHouAeXbcwxmrECUzDY]', a) and not a.startswith('--')) else 1
            continue
        out.append(a); i += 1
    return out


def _destination(url):
    """Where one send goes: the site only. A path or query may carry a token (a webhook's address often does), so neither is kept."""
    return _host(url)


def _url_hosts(args):
    """The sites a curl or wget command talks to: from its addresses only, never from a header or a value."""
    hosts = [_host(a) for a in args if '://' in a or re.fullmatch(r'[\w-]+(\.[\w-]+)+(:\d+)?(/\S*)?', a)]
    return '、'.join(dict.fromkeys(h for h in hosts if h))


def _hit(kind, what):
    return (kind, ('%s %s' % (LABELS[kind], what)).strip())


# ---- reading a shell command
def _inner(command):
    """Commands inside $( … ) and backticks, which run too."""
    found = re.findall(r'`([^`]*)`', command)
    i = 0
    while True:
        start = command.find('$(', i)
        if start < 0: break
        depth, j = 1, start + 2
        while j < len(command) and depth:
            depth += {'(': 1, ')': -1}.get(command[j], 0); j += 1
        found.append(command[start + 2:j - 1]); i = start + 2
    return found


def _split(command):
    """(simple commands, whether the quoting could be read). A simple command is a list of words; redirections stay in it."""
    clear = True
    command = re.sub(r'(^|[\s;&|(])\d+(?=[<>])', r'\1', command)  # the 2 of 2>/dev/null is which output, not a file: only when written right before it
    try:
        lex = shlex.shlex(command.replace('\n', ' ; '), posix=True, punctuation_chars=';&|()<>')
        lex.whitespace_split = True; lex.commenters = ''
        words = list(lex)
    except ValueError:  # unbalanced quotes: read it word by word, and ask
        clear = False
        words = re.split(r'\s+|(?=[;&|()<>])|(?<=[;&|()<>])', command)
    parts, current = [], []
    for w in words:
        if not w: continue
        if set(w) <= set(';&|()<>') and not set(w) & set('<>'): parts.append(current); current = []
        else: current.append(w)
    parts.append(current)
    return [p for p in parts if p], clear


def _redirects(argv):
    """(the words without redirections, files read with <, files written with > or >>)."""
    words, read, written, i = [], [], [], 0
    while i < len(argv):
        w = argv[i]
        if set(w) <= set('<>&|') and set(w) & set('<>'):
            target = argv[i + 1] if i + 1 < len(argv) else ''
            i += 2
            if w.startswith('<<') or not target or re.fullmatch(r'\d+|-', target): continue  # a here-document, or another output stream
            (read if w in ('<', '<&') else written).append(target)
            if w == '<>': written.append(target)
            continue
        words.append(w); i += 1
    return words, read, written


def _strip(argv):
    """The command itself, after VAR=value, wrappers like env/nohup/xargs and their options. sudo is kept: it is a boundary."""
    argv = list(argv)
    while argv:
        word = argv[0]
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', word): argv.pop(0); continue
        if word == 'coproc' and len(argv) > 2 and re.fullmatch(r'\w+', argv[1]) and not shutil.which(argv[1]): del argv[:2]; continue  # coproc NAME …
        if word in SHELL_WORDS: argv.pop(0); continue
        if word == 'repeat' or word == 'function': del argv[:2]; continue  # zsh: repeat N command; function name { … }
        name = os.path.basename(word)
        if name in WRAPPERS:
            argv.pop(0)
            while argv and (argv[0].startswith('-') or (name == 'timeout' and re.fullmatch(r'[\d.]+[smhd]?', argv[0]))):
                option = argv.pop(0)
                if name == 'env' and (option.split('=', 1)[0] == '--split-string' or re.fullmatch(r'-[^-]*S.*', option)): return ['$env -S']  # a command line in one word
                if option in WRAPPER_VALUED.get(name, ()) and argv: argv.pop(0)
            continue
        break
    return argv


def _remote(arg):
    """host:path or user@host:path, not a local path with a colon."""
    return bool(re.match(r'^(?:[\w.-]+@)?[\w.-]+:(?!//)', arg)) and not arg.startswith('/') and not os.path.exists(_abs(arg))


def command_boundaries(command, depth=0):
    """Every boundary in a shell command line, in order, as (kind, title)."""
    if not isinstance(command, str): return []
    if depth > 4: return [_hit('unclear', '（指令包了太多層）')]
    found = []
    for inner in _inner(command): found += command_boundaries(inner, depth + 1)
    parts, clear = _split(_without_inner(command))  # what runs inside $( … ) was read above, and is counted once
    if not clear: found.append(_hit('unclear', '（引號沒有成對）'))
    scratch = _scratch_line(command) if depth == 0 else None  # only the line as written: never inside sh -c, $( ) or sudo
    for argv in parts:
        words, read, written = _redirects(argv)
        stripped = _strip(words)
        found += _redirect_hits(read, written, empty=not stripped or os.path.basename(stripped[0]) in (':', 'true') and len(stripped) == 1 and not read or stripped[:2] == ['cat', '/dev/null'])
        found += _argv_boundaries(stripped, command, depth, scratch)
    return found


def _without_inner(command):
    """The line with each $( … ) and `…` as $_: what it prints is not known here (as the program to run, it is a variable)."""
    out, i = re.sub(r'`[^`]*`', '$_', command), 0
    while True:
        start = out.find('$(', i)
        if start < 0: return out
        depth, j = 1, start + 2
        while j < len(out) and depth:
            depth += {'(': 1, ')': -1}.get(out[j], 0); j += 1
        out = out[:start] + '$_' + out[j:]; i = start


def merged(found):
    """One line for each different action, and how many times one is done: two uploads of the same file to the same site are 「共 2 次」."""
    counts = {}
    for hit in found: counts[hit] = counts.get(hit, 0) + 1
    return [(k, t if n == 1 else '%s（共 %d 次）' % (t, n)) for (k, t), n in counts.items()]


def command_boundary(command, depth=0):
    """The first boundary in a command line, or None."""
    found = command_boundaries(command, depth)
    return found[0] if found else None


def _redirect_hits(read, written, empty=False):
    out = []
    if empty and any(_nonempty(t) for t in written): out.append(_hit('delete', '清空 %s 的內容' % _names([t for t in written if _nonempty(t)])))
    if any(_secret_path(t) for t in read + written): out.append(_hit('secret', _names([t for t in read + written if _secret_path(t)])))
    if any(_guard_path(t) for t in written): out.append(_hit('guard', '寫入 ' + _names([t for t in written if _guard_path(t)])))
    elif any(_system_path(t) for t in written): out.append(_hit('system', '寫入 ' + _names([t for t in written if _system_path(t)])))
    return out


def _nonempty(path):
    try: return os.path.isfile(_abs(path)) and os.path.getsize(_abs(path)) > 0
    except OSError: return False


def _positional(args, valued):
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a.startswith('-') and a != '-':
            i += 2 if a in valued else 1
            continue
        out.append(a); i += 1
    return out


def _git(args):
    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith('-'): break
        if a in GIT_VALUED: i += 2; continue
        if a in GIT_FLAGS or (a.split('=', 1)[0] in GIT_VALUED and '=' in a): i += 1; continue
        return [_hit('unclear', '（git 的選項 %s 看不懂）' % _word(a.split('=', 1)[0].lstrip('-')))]
    if i >= len(args): return []
    sub, rest = args[i], args[i + 1:]
    plain = [a for a in rest if not a.startswith('-')]
    if sub == 'push':
        where = _host(plain[0]) if plain and ('://' in plain[0] or '@' in plain[0]) else _word(plain[0]) if plain else ''
        return [_hit('send', 'git push 到 %s' % (where or '預設的遠端'))]
    if sub == 'send-email': return [_hit('send', 'git send-email')]
    if sub == 'clean' and any(re.fullmatch(r'-\w*f\w*', a) or a == '--force' for a in rest): return [_hit('delete', '（git clean）')]
    if sub == 'credential' or sub.startswith('credential-'): return [_hit('secret', 'git ' + _word(sub))]
    return []


def _gh(args):
    subs = _positional(args, GH_VALUED)
    if subs[:1] == ['auth'] and subs[1:2] and subs[1] in ('token', 'login', 'logout', 'refresh', 'setup-git'): return [_hit('secret', 'gh auth ' + subs[1])]
    if subs[:1] == ['api']:
        if any(a in ('-f', '-F', '--field', '--raw-field', '--input') for a in args) or any(re.fullmatch(r'(-X|--method)=?(POST|PUT|PATCH|DELETE)?', a, re.I) for a in args):
            return [_hit('send', 'gh api %s' % _short(_word(subs[1]) if subs[1:2] else '', 50))]
        return []
    repo = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ('-R', '--repo')), '') or next((a.split('=', 1)[1] for a in args if a.startswith('--repo=')), '')
    if any(a in GH_ACTIONS for a in subs[1:4]):
        action = ' '.join(_word(a) for a in subs[:2] if _word(a))
        return [_hit('send', 'gh %s%s' % (action, (' 到 ' + _word(repo)) if _word(repo) else ''))]
    return []


def _search_roots(name, args):
    """(starting folders, whether it reads what is under them) for find and the grep family; None for other commands."""
    if name == 'find':
        starts = []
        for a in args:
            if a.startswith(('-', '(', '!')) or a in ('(', '!'): break
            starts.append(a)
        return starts or ['.'], any(a in ('-exec', '-execdir', '-ok', '-okdir') for a in args)
    if name in ('grep', 'egrep', 'fgrep', 'ggrep'):
        recursive = any(a in ('-r', '-R', '--recursive', '--dereference-recursive') or re.fullmatch(r'-[a-zA-Z]*[rR][a-zA-Z]*', a) or a.startswith('--directories=recurse') for a in args)
        plain = _positional(args, GREP_VALUED)
        if not any(a in ('-e', '-f', '--regexp', '--file') or a.startswith(('--regexp=', '--file=')) for a in args): plain = plain[1:]  # the first is the pattern
        return (plain or (['.'] if recursive else [])), recursive
    if name in ('rg', 'ag', 'ack', 'ugrep', 'ripgrep', 'pt', 'fd', 'fdfind', 'tree', 'zip', 'tar', 'cp', 'ditto'):
        if name in ('cp',) and not any(re.fullmatch(r'-[a-zA-Z]*[rRa][a-zA-Z]*', a) for a in args): return None
        if name == 'zip' and not any(re.fullmatch(r'-[a-zA-Z]*r[a-zA-Z]*', a) for a in args): return None
        plain = _positional(args, GREP_VALUED | {'-f', '--file', '-C', '--directory'})
        if name in ('rg', 'ag', 'ack', 'ugrep', 'ripgrep', 'pt') and not any(a in ('-e', '-f', '--regexp', '--file', '--files') for a in args): plain = plain[1:]
        if name in ('tar', 'zip', 'cp', 'ditto'): plain = plain[1:] if name in ('tar', 'zip') else plain[:-1]
        return (plain or ['.']), name not in ('fd', 'fdfind', 'tree')
    return None


def _argv_boundaries(argv, whole, depth, scratch=None):
    if not argv: return []
    word = argv[0]; name = os.path.basename(word); args = argv[1:]
    if '$' in word and word != '$' or '`' in word: return [_hit('unclear', '（要執行的程式是變數）')]
    if word == '$': return []
    plain = [a for a in args if not a.startswith('-')]
    found = []
    if name in SHELLS or name == 'eval':
        script = next((args[i + 1] for i, a in enumerate(args[:-1]) if re.fullmatch(r'-[a-z]*c[a-z]*', a)), None) if name in SHELLS else ' '.join(args)
        if script: return command_boundaries(script, depth + 1)
    if name in INTERPRETERS or re.fullmatch(r'python3(\.\d+)?', name):
        code = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in INLINE_FLAGS), None)
        if code is None and ('-' in args or not plain) and '<<' in whole: code = whole  # the program comes from a here-document
        if code is not None and CODE_HINTS.search(code): found.append(_hit('unclear', '（%s 的程式碼可能刪檔、對外送出或讀取金鑰）' % _word(name)))
        if name == 'osascript' and re.search(r'\bdelete\b|\btrash\b|move .* to trash', ' '.join(args), re.I): found.append(_hit('delete', '（用 AppleScript）'))
        elif name == 'osascript' and re.search(r'\bmove\b', ' '.join(args), re.I) and re.search(r'tmp|temporary|/var/folders', ' '.join(args), re.I):
            found.append(_hit('delete', '（用 AppleScript 移到暫存區）'))
    if name in ('sudo', 'su', 'doas'):
        rest, i = list(args), 0
        while i < len(rest) and rest[i].startswith('-'): i += 2 if rest[i] in ('-u', '-g', '-C', '-h', '-p', '-U', '-c', '-s') and name != 'sudo' or rest[i] in ('-u', '-g', '-C', '-h', '-p', '-U') else 1
        inner = _strip(rest[i:]) if name != 'su' else []
        program = os.path.basename(inner[0]) if inner and shutil.which(inner[0]) else ''  # a program's name, never a word that might be a password
        found.append(_hit('system', '用 %s 執行 %s' % (name, _word(program))))
        if inner: found += _argv_boundaries(inner, whole, depth + 1)
    if name in DELETE_COMMANDS and not _scratch_only(name, args, scratch): found.append(_hit('delete', _names(plain) or '（%s）' % name))
    roots = _search_roots(name, args)
    if roots is not None:
        starts, reads = roots
        if name == 'find' and ('-delete' in args or any(a in ('-exec', '-execdir', '-ok', '-okdir') and i + 1 < len(args) and os.path.basename(args[i + 1]) in DELETE_COMMANDS for i, a in enumerate(args))):
            found.append(_hit('delete', '（find 在 %s 裡找到的檔案）' % (_names(starts) or '目前資料夾')))
        if any(_secret_path(s) for s in starts): found.append(_hit('secret', '讀取 ' + _names([s for s in starts if _secret_path(s)])))
        elif reads and any(_holds_secrets(s) for s in starts): found.append(_hit('secret', '（搜尋 %s，範圍包含 ~/.ssh 等金鑰資料夾）' % _names([s for s in starts if _holds_secrets(s)])))
        if name == 'find':
            for i, a in enumerate(args):
                if a in ('-exec', '-execdir', '-ok', '-okdir'):
                    sub = args[i + 1:]; sub = sub[:next((j for j, x in enumerate(sub) if x in (';', '+', '{}+')), len(sub))]
                    if sub and os.path.basename(sub[0]) not in DELETE_COMMANDS: found += _argv_boundaries(_strip(sub), whole, depth + 1)
    if name == 'mv' and plain and ('.Trash' in plain[-1] or plain[-1].rstrip('/').endswith('/Trash')):
        found.append(_hit('delete', '%s（移到垃圾桶）' % _names(plain[:-1])))
    moved = _positional(args, {'-t', '--target-directory'} if name in ('mv', 'gmv') else set()) if name in ('mv', 'gmv') or name == 'rsync' and any(a.startswith('--remove-s') for a in args) else \
        plain[1:] + plain[:1] if name == 'zip' and any(a in ('-m', '--move') or re.fullmatch(r'-[a-zA-Z0-9]*m[a-zA-Z0-9]*', a) for a in args) else []
    into = next((args[i + 1] for i, a in enumerate(args[:-1]) if name in ('mv', 'gmv') and re.fullmatch(r'-[a-zA-Z]*t|--target-directory', a)), None) or \
        next((a.split('=', 1)[1] for a in args if name in ('mv', 'gmv') and a.startswith('--target-directory=')), None)
    if into is not None: moved = [m for m in moved if m != into] + [into]  # mv -t folder files…
    if into is not None and len(moved) == 1 and _into_scratch(into, whole): found.append(_hit('delete', '（xargs 等傳來的檔案，移到暫存區）'))
    if name in ('tar', 'gtar', 'gnutar', 'bsdtar') and any(a.startswith('--remove') for a in args): found.append(_hit('delete', '（tar 打包後刪除原檔）'))
    if name == 'rsync' and any(a.startswith('--delete') for a in args): found.append(_hit('delete', '（rsync 刪除目的地多出來的檔案）'))
    held = lambda s: '$' not in s and os.path.isabs(_expand(s)) and not _moves_folder(whole) and _scratch_place(s)  # surely already scratch
    if len(moved) > 1 and _into_scratch(moved[-1], whole) and any(not held(s) for s in moved[:-1]):  # scratch files are deleted without asking
        found.append(_hit('delete', '%s（移到暫存區）' % _names([s for s in moved[:-1] if not held(s)])))
    if name == 'git': found += _git(args)
    if name == 'gh' and args: found += _gh(args)
    if name == 'curl':
        sends = False
        for i, a in enumerate(args):
            key = a.split('=', 1)[0]
            if key in ('-X', '--request'):
                method = (a.split('=', 1)[1] if '=' in a else args[i + 1] if i + 1 < len(args) else '').upper()
                if method not in ('GET', 'HEAD', ''): sends = True
            elif key in CURL_SEND or (re.fullmatch(r'-[a-zA-Z]*[dFTK][a-zA-Z]*', a) and not a.startswith('--')): sends = True
        files = [a for i, a in enumerate(args) if i and args[i - 1] in ('-T', '--upload-file')]
        files += [v[1:].split(';')[0] for i, a in enumerate(args) for v in [a.split('=', 1)[1] if a.startswith('--') and '=' in a and a.split('=', 1)[0] in CURL_SEND else args[i + 1] if a in CURL_SEND and i + 1 < len(args) else '']
                  if '@' in v and v.split('=', 1)[-1].startswith('@') for v in [v.split('=', 1)[-1]]]
        urls = _curl_addresses(args)
        globbed = any(set(u) & set('{}[]') for u in urls)  # curl may turn it into many addresses (host or path); -g can be undone by a later option
        if sends and any(a in ('-K', '--config') or a.startswith('--config=') or re.fullmatch(r'-[a-zA-Z]*K.*', a) and not a.startswith('--') for a in args):
            found.append(('split', '這個 curl 指令從設定檔讀取要傳的內容和目的地，看不出會傳幾次、傳到哪裡'))
        elif sends and globbed: found.append(('split', '這個 curl 的網址是一個樣式（例如 {a,b} 或 [1-3]），會展開成好幾個目的地'))
        elif sends and (len(urls) > 1 or len(files) > 1 or '--next' in args or '-:' in args):  # several sends in one call: each must be shown on its own
            found.append(('split', '一個 curl 指令裡有多次傳送（%d 個目的地、%d 個檔案）' % (len(urls), len(files))))
        elif sends: found.append(_hit('send', '%s到 %s' % (('檔案 %s ' % _names(files)) if files else '', _destination(urls[0]) if urls else '網路')))
    if name == 'wget' and any(a.startswith(WGET_SEND) for a in args): found.append(_hit('send', '到 %s' % (_url_hosts(args) or '網路')))
    if name in COPY_OUT and (name in ('sftp', 'ftp') or any(_remote(a) for a in plain)):
        local = [a for a in plain if not _remote(a)] if name in ('scp', 'rsync') else []
        found.append(_hit('send', '%s到 %s' % (('檔案 %s ' % _names(local)) if local else '', '、'.join(dict.fromkeys(_host(a) for a in plain if _remote(a) or name in ('sftp', 'ftp'))) or '其他電腦')))
    if name in CONNECT and plain: found.append(_hit('send', '連到 %s' % (_host(plain[0]) or '其他電腦')))
    if name in MAIL_COMMANDS: found.append(_hit('send', '寄信給 %s' % ('、'.join(a for a in plain if re.fullmatch(r'[^@\s]+@[\w.-]+', a)) or '收件人')))
    if name == 'security': found.append(_hit('secret', '（鑰匙圈）security %s' % _word(plain[0] if plain else '')))
    if name in ('ssh-keygen', 'ssh-add'): found.append(_hit('secret', name))
    packages = lambda items: ' '.join(w for w in map(_word, items) if w)[:80]
    if name in INSTALLERS and plain and plain[0] in INSTALLERS[name]: found.append(_hit('install', '%s %s' % (name, packages(plain[:6]))))
    if name.startswith('python') and args[:2] == ['-m', 'pip'] and len(args) > 2 and args[2] in INSTALLERS['pip']: found.append(_hit('install', 'pip ' + packages(args[2:8])))
    if name in NODE_INSTALLERS and (plain and any(a in ('-g', '--global', '--location=global') for a in args) or plain[:1] == ['global']):
        found.append(_hit('install', '%s %s' % (name, packages(plain[:6]))))
    if name == 'defaults' and plain and plain[0] in ('write', 'delete', 'import', 'rename'): found.append(_hit('system', 'defaults %s %s' % (plain[0], _word(plain[1]) if len(plain) > 1 else '')))
    if name in SYSTEM_COMMANDS and name not in ('sudo', 'su', 'doas') and not (name == 'launchctl' and plain[:1] in (['list'], ['print'])) and not (name == 'diskutil' and plain[:1] in (['list'], ['info'])) and not (name == 'tmutil' and plain[:1] in (['status'], ['listbackups'])):
        found.append(_hit('system', '%s %s' % (name, _word(plain[0]) if plain else '')))
    # Writing: where a command puts files.
    targets = []
    if name in ('cp', 'ln', 'install', 'ditto', 'rsync') and plain: targets = plain[-1:]
    elif name == 'mv' and plain: targets = plain  # moving Zook's checks away changes them too
    elif name in ('tee', 'touch', 'mkdir', 'truncate', 'chmod', 'chown', 'chgrp', 'chflags', 'xattr', 'patch'): targets = plain
    elif name in ('sed', 'gsed', 'perl') and any(a.startswith('-i') or a == '--in-place' or re.fullmatch(r'-[a-zA-Z]*i[a-zA-Z]*', a) for a in args): targets = plain[1:] if name != 'perl' else plain
    elif name == 'dd': targets = [a[3:] for a in args if a.startswith('of=')]
    if name == 'truncate' and any(re.fullmatch(r'(-s|--size=?)0?', a) or a in ('-s0', '--size=0') for a in args) and ('0' in args or any(a.endswith('0') for a in args)):
        found.append(_hit('delete', '清空 %s 的內容' % _names([a for a in plain if a != '0'])))
    if name in ('cp', 'mv') and plain[:1] == ['/dev/null'] and len(plain) == 2 and _nonempty(plain[1]): found.append(_hit('delete', '清空 %s 的內容' % _names(plain[1:])))
    if any(_guard_path(t) for t in targets): found.append(_hit('guard', '修改 ' + _names([t for t in targets if _guard_path(t)])))
    elif name not in DELETE_COMMANDS and any(_system_path(t) for t in targets) and name not in ('touch', 'mkdir'): found.append(_hit('system', '寫入 ' + _names([t for t in targets if _system_path(t)])))
    if name in DELETE_COMMANDS and any(_guard_path(t) for t in plain): found.append(_hit('guard', '刪除 ' + _names([t for t in plain if _guard_path(t)])))
    local = [_file_url(a) if a.lower().startswith('file://') else a for a in args]  # file:// is a file on this Mac, checked like one
    web = set(_curl_addresses(args)) if name in ('curl', 'wget') else set()  # an address without https:// is still not a file here
    touched = [a for a in local if '://' not in a and a not in web and (a.startswith(('/', '~', '$HOME', '${HOME}', '.', '@')) or '/' in a or os.path.basename(a).startswith('.env'))]
    touched += [a.split('=', 1)[1] for a in args if a.startswith('--') and '=' in a]
    if not any(k == 'secret' for k, _ in found) and any(_secret_path(a) for a in touched): found.append(_hit('secret', _names([a for a in touched if _secret_path(a)])))
    return found


def command_summary(command):
    """What the activity record keeps of a command: the same lines as an approval card, or the programs it runs; never the command."""
    found = merged(command_boundaries(command))
    if found: return '；'.join(t for _, t in found)[:600]
    parts, _ = _split(command if isinstance(command, str) else '')
    names = [n for n in (_word(os.path.basename(_strip(_redirects(p)[0])[0])) for p in parts if _strip(_redirects(p)[0])) if n]
    return ('執行指令：' + '、'.join(dict.fromkeys(names))[:200]) if names else '執行指令'


# ---- the CLI's own tools
SHELL_TOOLS = {'bash', 'shell', 'terminal', 'runterminalcommand', 'run_terminal_cmd'}
READ_TOOLS = {'read', 'grep', 'glob', 'ls', 'listdir', 'list_dir', 'notebookread', 'readlints', 'filesearch', 'semanticsearch', 'codebasesearch'}
WRITE_TOOLS = {'write', 'edit', 'multiedit', 'notebookedit', 'editnotebook', 'strreplace', 'str_replace', 'applypatch', 'apply_patch'}
PATH_KEYS = ('file_path', 'path', 'notebook_path', 'target_file', 'target_directory', 'directory', 'paths', 'files', 'target_directories')


def _paths(data):
    for key in PATH_KEYS:
        value = data.get(key)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and item: yield item


def _emptied(path, data, tool):
    """A Write that leaves an existing file empty, or an Edit that removes everything in it."""
    if not os.path.isfile(_expand(path)): return False
    try: size = os.path.getsize(_expand(path))
    except OSError: return False
    if size == 0: return False
    if tool == 'write':
        content = data.get('content', data.get('contents', data.get('file_text')))
        return isinstance(content, str) and not content.strip()
    if tool in ('edit', 'strreplace', 'str_replace'):
        old, new = data.get('old_string', data.get('old_str')), data.get('new_string', data.get('new_str'))
        if not isinstance(old, str) or not isinstance(new, str) or new.strip(): return False
        try:
            with open(_expand(path), encoding='utf-8', errors='replace') as f: text = f.read(2 * 1024 * 1024)
        except OSError: return False
        return old.strip() == text.strip() or (data.get('replace_all') is True and not text.replace(old, '').strip())
    return False


def boundaries(tool, data, home=''):
    """Every boundary this tool call crosses, as (kind, title); [] when none. tool is the CLI's own tool name."""
    low = str(tool or '').lower(); data = data if isinstance(data, dict) else {}
    if low.startswith('mcp'): return []  # Zook's own tools are checked by Zook itself
    _CWD[0] = home or os.getcwd()
    if low in SHELL_TOOLS or (isinstance(data.get('command'), str) and low not in READ_TOOLS | WRITE_TOOLS):
        return command_boundaries(data.get('command') or '')
    paths = [_abs(p) for p in _paths(data)]
    if low == 'delete': return [_hit('delete', _names(paths) or '檔案')] + ([_hit('guard', '刪除 ' + _names([p for p in paths if _guard_path(p)]))] if any(_guard_path(p) for p in paths) else [])
    if low == 'glob' and isinstance(data.get('pattern'), str): paths.append(data['pattern'] if os.path.isabs(_expand(data['pattern'])) else os.path.join(paths[0] if paths else _CWD[0], data['pattern']))
    found = []
    secret = [p for p in paths if _secret_path(p)]
    if secret: found.append(_hit('secret', '%s %s' % ('讀取' if low in READ_TOOLS else '修改', _names(secret))))
    elif low in ('grep', 'semanticsearch', 'codebasesearch', 'filesearch') and any(_holds_secrets(p) for p in (paths or [_CWD[0]])):
        found.append(_hit('secret', '（搜尋 %s，範圍包含 ~/.ssh 等金鑰資料夾）' % _names([p for p in (paths or [_CWD[0]]) if _holds_secrets(p)])))
    if low in WRITE_TOOLS:
        for p in paths:
            if _guard_path(p): found.append(_hit('guard', '修改 ' + _names([p])))
            elif _system_path(p): found.append(_hit('system', '修改 ' + _names([p])))
            if _emptied(p, data, low): found.append(_hit('delete', '清空 %s 的內容' % _names([p])))
    return found


def boundary(tool, data, home=''):
    """The first boundary of a tool call, or None."""
    found = boundaries(tool, data, home)
    return found[0] if found else None


# ---- asking the user through Zook
def ask(actions):
    """True only when the user allowed every one of these on Zook's approval card. Only what is done and where is sent."""
    url, token = os.environ.get('ZOOK_WORKER_URL', ''), os.environ.get('ZOOK_WORKER_TOKEN', '')
    if not url.startswith('http://127.0.0.1:') or not token: return False
    try: wait = max(30, int(os.environ.get('ZOOK_TOOL_WAIT') or 660))
    except ValueError: wait = 660
    items = [{'kind': k, 'title': t} for k, t in actions]
    body = json.dumps({'method': 'gate', 'params': dict({'actions': items}, **({'toolUseId': _TOOL_USE[0]} if _TOOL_USE[0] else {}))}).encode()
    # The token is never sent: the request is signed with it, and only an answer proved with it for this very request counts
    # (another program on that port can neither learn it nor approve in Zook's place).
    nonce, when = os.urandom(16).hex(), str(int(time.time() * 1000))
    where = urllib.parse.urlsplit(url); target = '%s%s' % (where.port, where.path)  # for this address only: not usable at another
    sig = hmac.new(token.encode(), b'\n'.join(x if isinstance(x, bytes) else x.encode() for x in ('call', nonce, when, target, body)), 'sha256').hexdigest()
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json', 'X-Zook-Nonce': nonce, 'X-Zook-Time': when, 'X-Zook-Sig': sig})
    try:
        with urllib.request.urlopen(req, timeout=wait) as response:
            raw = response.read(65536); proof = response.headers.get('X-Zook-Proof') or ''; status = response.status
        answer = json.loads(raw)
    except (urllib.error.URLError, ValueError, OSError):
        return False
    expected = hmac.new(token.encode(), b'\n'.join(x if isinstance(x, bytes) else str(x).encode() for x in ('answer', nonce, status, raw)), 'sha256').hexdigest()
    return hmac.compare_digest(proof, expected) and isinstance(answer, dict) and answer.get('approved') is True


def _command_paths(command):
    """Every file or folder a command line names (its words that look like paths, and where it redirects), for holding it to folders.
    A command that cannot be read is outside. A program run from a file is not read: the same limit as everywhere in this gate."""
    parts, clear = _split(_without_inner(command))
    if not clear or _inner(command): return ['（無法判讀的指令）']
    found = []
    for argv in parts:
        words, read, written = _redirects(argv)
        words = _strip(words)
        if words and ('$' in words[0] or os.path.basename(words[0]) in SHELLS | {'eval'}): return ['（無法判讀的指令）']
        for w in words[1:] + read + written:
            if w.lower().startswith('file://'): w = _file_url(w)
            if '://' in w: continue
            if w.startswith(('/', '~', '$HOME', '${HOME}', '..')) or '/' in w or w in ('.', '..'): found.append(_abs(w.split('=', 1)[-1] if w.startswith('--') else w))
        if words and os.path.basename(words[0]) == 'cd' and len(words) == 1: found.append(HOME)
    return found


def outside_roots(tool, data, home=''):
    """When Zook limits this reply to some folders (ZOOK_GATE_ROOTS): the paths this call would reach outside them. A command line
    cannot be held to folders, so any command is outside."""
    try: roots = json.loads(os.environ.get('ZOOK_GATE_ROOTS') or 'null')
    except ValueError: return ['（設定無法讀取）']
    if roots is None: return []
    low = str(tool or '').lower(); data = data if isinstance(data, dict) else {}
    if low.startswith('mcp') or low in ('task', 'agent', 'todowrite'): return []
    _CWD[0] = home or os.getcwd()
    if low in SHELL_TOOLS or isinstance(data.get('command'), str):
        if os.environ.get('ZOOK_GATE_SHELL') != '1' or not isinstance(roots, list): return ['（指令）']
        named = _command_paths(data.get('command') or '')
        return [p for p in named if p.startswith('（') or not _under(p, [str(r) for r in roots if isinstance(r, str) and r])]
    paths = [_abs(p) for p in _paths(data)]
    if low == 'glob' and isinstance(data.get('pattern'), str): paths.append(data['pattern'] if os.path.isabs(_expand(data['pattern'])) else os.path.join(paths[0] if paths else _CWD[0], data['pattern']))
    if low in ('grep', 'glob', 'ls', 'listdir', 'list_dir') and not paths: paths = [_CWD[0]]  # its default: where it started
    if not paths and low not in READ_TOOLS | WRITE_TOOLS | {'delete'}: return []
    return [p for p in (paths or ['（沒有路徑）']) if not (isinstance(roots, list) and _under(re.split(r'[*?\[{]', p)[0] or '/', [str(r) for r in roots if isinstance(r, str) and r]))]


# Why a reply is held to folders (ZOOK_GATE_WHY, set by Zook for this reply) and what the user can do about it. Only explains: what
# the reply may reach is decided by Zook before the CLI starts, never here (巡檢 #86 #88: 「系統說它無法判讀」, 「不在可動資料夾範圍」).
HELD = {'probe': ('Zook 還在確認這個 Claude 帳號的安全檢查有沒有生效，確認前這一則只能用 Bot 自己的資料夾',
                  '這一則用過工具就會確認，使用者下一則再交辦一次就能存到原本要的位置'),
        'workspace': ('這個 Bot 的存取範圍是「只限 Bot 工作區」',
                      '使用者要存到別處，可以自己到「編輯 Bot」→「進階設定」→「存取範圍」改成「整台 Mac」或「指定資料夾」；要不要放寬由使用者決定'),
        'folder': ('這個 Bot 的存取範圍是「指定資料夾」，只能動那個資料夾',
                   '使用者要存到別處，可以自己到「編輯 Bot」→「進階設定」→「存取範圍」換資料夾或改成「整台 Mac」；要不要放寬由使用者決定'),
        'plan': ('這一則是只能讀的回覆（例如查核或規劃），只能讀這次附上的檔案', '要存檔請使用者交給負責做事的回覆'),
        'careful': ('這個 Bot 的主動性是「謹慎」，內建工具只能讀這次附上的檔案', '存檔改用 zook 工具（會先問使用者）')}


def held_refusal(away):
    """The refusal for a path outside what this reply may reach: where it was stopped, why, where to save instead, what the user can do."""
    reason, then = HELD.get(os.environ.get('ZOOK_GATE_WHY') or '', ('這一則只能動到 Zook 允許的資料夾', '使用者可以在「編輯 Bot」查看這個 Bot 的存取範圍'))
    save = os.environ.get('ZOOK_GATE_SAVE') or ''
    instead = '請改存到 %s，回覆時寫出實際位置；' % save if save else ''
    tell = '直接告訴使用者擋在哪裡、為什麼（%s），以及：%s。不要改用別的方法繞過。' % (reason, then)
    named = _names([p for p in away if not p.startswith('（')])
    if not named and away and away[0] == '（無法判讀的指令）':
        return ('沒有做：這個指令用了變數、$( )、內嵌程式或另一個 shell，Zook 看不出它會動到哪些檔案，而這一則只能動到允許的資料夾，所以擋下了。'
                '改用寫出完整路徑的簡單指令或寫檔工具；暫存檔也放在允許的資料夾裡，不要用 mktemp、/tmp 或 $變數。%s%s' % (instead, tell))
    return '沒有做：%s 不在這一則可以動的範圍，擋在 Zook 的存取範圍（不是檔案本身的問題）。%s%s' % (named or away[0], instead, tell)


def decide(tool, data, home=''):
    """(allowed, why) for one tool call."""
    away = outside_roots(tool, data, home)
    if away: return False, held_refusal(away)
    raw = boundaries(tool, data, home)
    if not raw: return True, ''
    split = [t for k, t in raw if k == 'split']
    if split: return False, '%s。請拆成幾個指令，每次一個檔案、一個目的地，讓使用者逐一確認。' % split[0]
    found = merged(raw)
    if len(raw) > MAX_ACTIONS or any(len(t) > MAX_TITLE for _, t in found):  # one card could not show all of it: never approved as a batch
        return False, '這一步同時要做 %d 件需要核准的事，或目標太長，一張核准卡放不下。請分成幾個較小的步驟，一次一件，讓使用者逐一確認。' % len(raw)
    if ask(found): return True, ''
    return False, '使用者沒有允許：%s。不要改用其他方法做這件事，直接告訴使用者沒有做。' % '；'.join(t for _, t in found)


_TOOL_USE = ['']


def _mark(what):
    """Leave Zook a sign that this hook really runs in this very CLI: the random word Zook gave this CLI when it started
    (ZOOK_GATE_NONCE), added to its file (ZOOK_GATE_MARK). Nothing else knows the word, so no other Bot or program can leave it."""
    mark, nonce = os.environ.get('ZOOK_GATE_MARK'), os.environ.get('ZOOK_GATE_NONCE')
    if not mark or not nonce: return
    try:
        fd = os.open(mark, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try: os.write(fd, ('%s:%s\n' % (nonce, what)).encode())
        finally: os.close(fd)
    except OSError: pass


def main():
    """Claude Code's PreToolUse hook. Always answers allow or deny: Zook gives Claude no tool in advance, so a tool runs only on this
    answer. Exits 2 on any failure, and the hook is set to block on failure too."""
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT: raise ValueError('too large')
        event = json.loads(raw.decode('utf-8'))
        if not isinstance(event, dict): raise ValueError('not an object')
        if event.get('hook_event_name') == 'SessionStart': _mark('start'); return 0  # only that Claude started: not that a tool was checked
        _mark('tool')
        data = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
        _TOOL_USE[0] = str(event.get('tool_use_id') or '')[:100]  # so the record of this call can say the user allowed it
        allowed, why = decide(event.get('tool_name'), data, str(event.get('cwd') or ''))
        if allowed and os.environ.get('ZOOK_GATE_DEFER') == '1': return 0  # a read-only reply: Claude's own rules decide what is inside the folders
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'allow' if allowed else 'deny',
                                                 'permissionDecisionReason': 'Zook 的安全檢查允許了這次動作。' if allowed else why}}, ensure_ascii=False))
        return 0
    except Exception:
        sys.stderr.write('Zook 的安全檢查出錯，所以擋下了這個動作。請直接告訴使用者。\n')
        return 2


if __name__ == '__main__':
    sys.exit(main())
