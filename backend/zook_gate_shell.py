# -*- coding: utf-8 -*-
"""Part of zook_gate.py, read into its namespace (it uses _split, _strip, _secret_path … from there): where a command of a line runs
after its cd, pushd and chdir, what its variables hold, and the files xargs and parallel read their arguments from (queue #293)."""


_AS_BEFORE = [False]  # read as before #344: eval and source taken as setting nothing (what was found then is still checked)


def _as_before(path):
    """Where the path leads as read before #344, for the checks that look at every place a path may be: a place found then is
    never lost because eval or source now make the rest unknown."""
    was, _AS_BEFORE[0] = _AS_BEFORE[0], True
    try: return _resolved(path)
    finally: _AS_BEFORE[0] = was


def _sources():
    """A command of the line being read runs eval, source or . : it may set any variable (queue #344)."""
    return not _AS_BEFORE[0] and any(_strip(_redirects(part)[0])[:1] in (['eval'], ['source'], ['.']) for line in _LINES for part in _split(_without_inner(line))[0])


def _folders():
    """Every folder a command of the line being read may run in, after each cd, pushd or chdir of it (in any order: one may fail);
    None when one cannot be known (a variable, cd -, popd, env -C, a name CDPATH may lead to keys, eval of what is not plain text)."""
    found, stack, lines = [_CWD[0]], 0, list(_LINES)  # stack: pushd's of this line not yet undone; a popd goes back to a folder of this line only then
    for line in lines:
        for part in _split(_without_inner(line))[0]:
            raw = _redirects(part)[0]
            if re.search(r'(?:^|\s)(?:\S*/)?env(?:\s+(?:-\S*|\S*=\S*))*?\s+(?:-[^-\s]*C|--chdir)', ' '.join(raw)): return None  # env -C: elsewhere
            words = _strip(list(raw))
            if words[:1] == ['eval']:  # eval 'cd ~': its text is a line of its own; what a variable or $( … ) gives it is not known
                text = ' '.join(words[1:])
                if set(text) & set('$`\\') or GLUED in text or len(lines) > 20:
                    if _AS_BEFORE[0]: continue
                    return None
                lines.append(text); continue
            if words[:1] == ['popd'] and (words[1:] not in ([], ['-q']) or not stack) or words[:1] == ['pushd'] and len(words) == 1: return None
            stack += {'pushd': 1, 'popd': -1}.get(words[0] if words else '', 0)
            if words[:1] in (['cd'], ['pushd'], ['chdir']):
                rest = [w for w in words[1:] if not re.fullmatch(r'-[LPeq@]+|--', w)]
                where = _expand(rest[0]) if rest else HOME
                if len(rest) > 1 or where[:1] in ('-', '+', '', '~') or set(where) & set('$`*?[]{}\\'): return None  # ~-: the folder before
                more = [x for f in found for x in (os.path.normpath(os.path.join(f, where)), os.path.realpath(os.path.join(f, where)))]  # cd -P: links first
                if not re.match(r'\.\.?(/|$)|/', where):  # a plain name: CDPATH may lead to a folder of that name elsewhere
                    if any(re.search(r'\bCDPATH\s*\+?=', x) for x in _LINES): return None  # set on this very line: where it leads is not known here
                    if any('/%s/' % os.path.normpath(where).strip('/') in s.rstrip('/') + '/' for d in SECRET_DIRS + CREDENTIALS + _accounts_folder() for s in (d, os.path.realpath(d))): return None
                    more += [os.path.normpath(os.path.join(f, _expand(c) or '.', where)) for c in os.environ.get('CDPATH', '').split(':') for f in found]
                found = list(dict.fromkeys(found + more))
                if len(found) > 40: return None  # too many to follow: not known
            elif len(words) == 1 and not set(words[0]) & set('$`*?[]{}\\') and os.path.isabs(_expand(words[0])) and os.path.isdir(_expand(words[0])):
                found.append(_expand(words[0]))  # zsh's AUTO_CD: a folder alone is a cd
    return list(dict.fromkeys(found))


def _in_quotes(text, at):
    """Whether the place is inside '…' or "…" (no backslash or $'…' in the line: _values asks that first)."""
    quote = ''
    for c in text[:at]: quote = ('' if quote == c else quote) if quote else c if c in '\'"' else ''
    return bool(quote)


def _writes(f):
    """The file may be written by another command of the line (> f, cp … f, sed -i …), or is named inside $( … ): read it now is not enough."""
    for line in _LINES:
        if any(f in x for x in _inner(line) if x): return True
        for part in _split(_without_inner(line))[0]:
            words, _, written = _redirects(part); words = _strip(words)
            if f in written or words and os.path.basename(words[0]) in ('cp', 'mv', 'tee', 'install', 'ln', 'rsync', 'ditto', 'dd', 'sort', 'sed', 'gsed', 'perl', 'truncate', 'curl', 'wget', 'unzip', 'patch') + (TARS if any(re.fullmatch(r'-?[a-zA-Z]*x[a-zA-Z]*|--extract', w) for w in words[1:]) else ()) and any(f in w for w in words[1:]): return True
    return False


def _no_heredocs(text):
    """The line without what its here-documents hold: lines of text for a program, never commands or settings of the line."""
    out, i = '', 0
    for m in re.finditer(HEREDOC, text):  # each here-document: its text runs from the next line to the line holding only its marker
        nl = text.find('\n', m.end())
        if m.start() < i or nl < 0: continue
        end = re.search(r'\n\s*%s(?=\n|$)' % re.escape(next(g for g in m.groups() if g)), text[nl:])
        if not end: return out + text[i:nl]  # never ended: all the rest is its text
        out += text[i:nl] + '\n'; i = nl + end.end()
    return out + text[i:]


def _values(name):
    """What a variable of the line being read may hold: set on it on its own (NAME=value, export NAME=value) or a for loop's words;
    None when not known (set from outside, by read, by $( … ), or only for one command; any of them after eval or source)."""
    if _sources(): return None  # eval 'F=…', source FILE: may set it again before it is read (queue #344)
    if name == 'PWD': return None if any(re.search(r'\bPWD\+?=', x) for x in _LINES) else _folders()  # set by hand: not where it runs
    found = []
    for raw in _LINES:
        line = _no_heredocs(raw)
        if line != raw and (set(raw) & set('\\`#') or "$'" in raw or any(_in_quotes(raw, m.start()) for m in re.finditer(HEREDOC, raw))): return None  # a <<word in quotes is text
        use = min([m.start() for m in re.finditer(r'\$\{?%s\b' % re.escape(name), line)] or [len(line)])
        for m in re.finditer(r'(?<![\w-])(?:(?:export|local|declare|readonly|typeset)\s+)?%s\+?=|\bfor\s+%s\s+in\b' % (re.escape(name), re.escape(name)), line):
            ahead = re.sub(r'\$\(\s*mktemp[^()]*\)', '', line[:m.start()])  # only set for sure, before it is read: not in if, ||, ( … ), a function
            if m.start() > use or re.search(r'[|&(){}`]|\b(?:if|then|else|elif|while|until|do|case|function)\b', ahead): return None
        temp = re.findall(r'(?:^|[\s;&|(])%s=["\']?\$\(\s*mktemp(?:\s+-[dqu]+|\s+-t\s+[\w.-]+)*\s*\)' % re.escape(name), line)  # a new temporary file
        found += [os.path.join(os.environ.get('TMPDIR') or '/tmp', 'zook-mktemp')] if temp else []
        if sum(w == name + '=$ZOOKSUB' for part in _split(_without_inner(line))[0] for w in part) > len(temp): return None  # set from another $( … ) too
        for part in _split(_without_inner(line))[0]:
            lead = part[1:] if part[0] in ('export', 'local', 'declare', 'readonly', 'typeset') else part
            if all(re.fullmatch(r'\w+\+?=.*', w) for w in lead): found += [w.split('=', 1)[1] for w in lead if w.startswith(name + '=') and not (temp and w == name + '=$ZOOKSUB')]
            if any(w.startswith(name + '+=') for w in part) or part[0] in ('read', 'mapfile', 'readarray', 'getopts', 'select', 'printf') and name in part[1:]: return None
            if part[:3] == ['for', name, 'in']: found += part[3:]
    return found or None


def _resolved(path, depth=0):
    """The path, and where it is from each folder a cd of this line may have led to (a relative path), with what a wildcard matches
    there and what a variable set on the line holds; None when one cannot be known."""
    p = _expand(path)
    brace = re.search(r'\{([^{}]*)\}', p)
    if brace and re.search(r',|\.\.', brace.group(1)):  # {a,b}: each of them; {1..9}: not followed
        if '..' in brace.group(1) or depth > 2: return None
        out = [_resolved(p[:brace.start()] + v + p[brace.end():], depth + 1) for v in brace.group(1).split(',')]
        return None if None in out else [path] + [x for f in out for x in f[1:] or f]
    if GLUED in p or re.search(r'\$\{(?!\w+\})|\$\w+\[', p): return None  # finished by what $( … ) prints; ${F:-…}, ${#F}, $F[1]: not followed
    names = re.findall(r'\$\{?(\w+)', p)
    if names or '`' in p:
        held = [_values(n) for n in names]
        if '`' in p or None in held or depth > 2: return None
        out = []
        for n, values in zip(names, held):
            for v in values:  # unquoted, a value with spaces is several words: each is checked too
                for one in [v] + (v.split() if re.search(r'\s', v) else []): out += _resolved(re.sub(r'\$\{?%s\}?' % n, lambda m: one, p), depth + 1) or [None]
        return None if None in out else [path] + out
    folders = [] if not p or os.path.isabs(p) else None if p.startswith('~') else _folders()  # ~-, ~+: the folder before, or now
    found = None if folders is None else [path] + [os.path.join(f, p) for f in folders]
    return found and found + [m for x in found[1:] or [p] if set(x) & set('*?[') for m in glob.glob(_expand(x))]


def _secret_any(path, unsure=True):
    """Where a key or sign-in is named, after the cds of this line; '' when none is. unsure: a path in a folder that cannot be known
    (cd "$VAR") counts too, as $PWD/…"""
    found = _resolved(path)
    found = _as_before(path) if found is None and not unsure else found  # echo $F: a key found as before is still a key
    if found is None:  # a variable is shown by its name only: never the rest of the word, which may be anything
        named = re.search(r'\$\{?\w+\}?', path); named = '$ZOOKSUB' if GLUED in path or '`' in path else named.group() if named else ''
        return _secret_path(path) and path or ((named or '$PWD/' + _expand(path)) if unsure else '')
    return next((x for x in found if _secret_path(x)), '')


def _read_file(path):
    """A file a command reads (-f FILE, xargs -a FILE): a key or sign-in, or a variable or {a,b} that may be one."""
    return _secret_any(path)


def _listed(files, prog, words=(), bases=None):
    """xargs -a FILE, parallel :::: FILE: the file, and the paths in it handed to the command (read now: a short plain file only, never
    one that is a key, a link or a pipe); the file itself when what is in it cannot be read. echo and printf open nothing."""
    out = [x for x in map(_secret_any, files) if x]
    marks = [v for i, w in enumerate(words) for v in [w.split('=', 1)[1] if w.startswith(('--delimiter=', '--colsep=')) else ''.join(words[i + 1:i + 2]) if w in ('--delimiter', '--colsep') else _short_value(words, i, set(), 'dC')] if v is not None]
    out += ['（%s 列出的檔案）' % f for f in files if _writes(f)]  # written first on the line: what is in it now is not what is read
    for f in [] if out or prog in ('echo', 'printf') else files:
        where = [x for x in _resolved(f) or [] if os.path.isfile(_abs(x))]
        for one in where or [None]:  # every folder the line may run in: the list there
            try:
                fd = os.open(_abs(one), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK) if one else -1
                with os.fdopen(fd, 'rb') as h: raw = h.read(65537) if stat.S_ISREG(os.fstat(h.fileno()).st_mode) else None
                text = raw.decode('utf-8', 'replace') if raw is not None and len(raw) <= 65536 else None  # longer: not all of it is seen
                if any(w.startswith('--colsep') for w in words): raise ValueError('a pattern')  # parallel --colsep: not followed here
                null = any(w in ('-0', '--null', '--from0') or re.fullmatch(r'-[^-]*0\w*', w) for w in words)
                parts = set(text.split('\0') if null else [p for m in marks for p in text.split(m.encode().decode('unicode_escape') if len(m) <= 2 else m)] if marks else text.splitlines() + text.split() + (shlex.split(text) if set(text) & set('\'"\\') else []))  # as the tool splits it; xargs takes quotes and \\ away
                if prog in TARS and any(x.startswith('-') for x in parts): parts = None  # tar -T: a line may be an option (-C ~): not followed here
                parts = parts if bases is None else parts | {os.path.join(b, x.lstrip('/')) for b in bases for x in parts}  # rsync --files-from: under each source
            except (OSError, ValueError, IndexError, TypeError, AttributeError, re.error): parts = None
            out += ['（%s 列出的檔案）' % f] if parts is None else [x for x in map(_secret_any, parts) if x]
    return out


def _rooted(starts):
    """(the folders a search starts from, after the cds of its line; whether one cannot be known: a variable, or an unknown cd)."""
    found = [_resolved(s) for s in starts]
    return [_abs(x) for f in found for x in f or []], None in found  # not normalized: a/link/.. is where the link leads


def _short_value(args, i, valued, letters):
    """The value of the first of these short options in args[i] (-fFILE, -if FILE), or None: another option's value ends the search."""
    for k, ch in enumerate(args[i][1:] if re.match(r'-[^-]', args[i]) else '', 2):
        if ch in letters: return args[i][k:] or (args[i + 1] if i + 1 < len(args) else '')
        if '-' + ch in valued: return None


def _takes_next(a, valued):
    """The option takes the next word as its value: itself, or the first letter taking a value is its last (-tn 1, not -aFILE)."""
    first = next((k for k, ch in enumerate(a[1:], 2) if '-' + ch in valued), 0) if re.fullmatch(r'-[A-Za-z0-9]+', a) else 0
    return a in valued or bool(first) and not a[first:]


def _arg_files(words):
    """The files xargs (-a, --arg-file) and GNU parallel (-a, --arg-file, :::: and ::::+) read their arguments from."""
    out, tool, listing, done = [], '', False, False
    for i, w in enumerate(words):
        if os.path.basename(w) in ('xargs', 'parallel') and not tool and (_strip(words[:i]) or ['sudo'])[0] in ('sudo', 'doas'):  # in the place of the command
            tool = os.path.basename(w); continue
        if not tool: continue
        if not done and os.path.basename(w) in ('xargs', 'parallel') and not _takes_next(words[i - 1], WRAPPER_VALUED[tool]):  # xargs … parallel …: its own lists too
            tool, listing = os.path.basename(w), False; continue
        done = done or not w.startswith('-') and not _takes_next(words[i - 1], WRAPPER_VALUED[tool]) and not listing and not w.startswith(':::')
        if w in ('::::', '::::+'): listing = True
        elif w.startswith(':::'): listing = False
        elif listing: out.append(w)
        elif done: continue  # the command's own words
        elif w in ('-a', '--arg-file') or w.startswith('--arg-file='): out += [w.split('=', 1)[1]] if '=' in w else words[i + 1:i + 2]
        elif _short_value(words, i, WRAPPER_VALUED[tool], 'a') is not None: out.append(_short_value(words, i, WRAPPER_VALUED[tool], 'a'))
    return out


# ---- queue #344: what a shell -c or eval script holds once the outer shell has filled it in, and file names handed on through a pipe
TRUSTED_ENV = ('HOME', 'TMPDIR', 'USER', 'LOGNAME')  # set by macOS for the user, not by the Bot on this line
REQUOTE = set('\'"\\`$;&|<>(){}#\n')  # in a value put into a script, what may close its quotes or start another command


def _quoted_parts(text):
    """The text inside each '…' and "…" of a script, as it is written."""
    out, quote, start, j = [], '', 0, 0
    while j < len(text):
        c = text[j]
        if quote == '"' and c == '\\': j += 1
        elif quote and c == quote: out.append(text[start:j]); quote = ''
        elif not quote and c == '\\': j += 1
        elif not quote and c in '\'"': quote, start = c, j + 1
        j += 1
    return out + ([text[start:]] if quote else [])


def _requoted(script):
    """A shell -c or eval script the shell running it may read otherwise than it is read here: the outer shell may have put in what
    $( … ) or `…` prints, a variable set on this line to quotes, ; or | (or set where its value is not known, or after eval or source),
    or a variable not known here inside quotes that keep ; | <( … ) or $( … ) from running (a ' in it ends the quotes)."""
    if GLUED in script or '$ZOOKSUB' in script: return True
    names = set(re.findall(r'\$\{?([A-Za-z_]\w*)', script))
    if not names and '$' not in script: return False
    if _sources(): return True
    for n in names:
        held = _values(n)
        if held is not None and any(set(v) & REQUOTE for v in held): return True
        if held is None and any(re.search(r'(?<![\w$])%s(?!\w)' % n, re.sub(r'\$\{?%s(?!\w)' % n, '', x.replace(script, ' '))) for x in _LINES): return True  # set on the line (not by the script itself), value not known
    for part in _quoted_parts(script):
        if re.search(r'[;&|<>()`\n]', part) and any(n not in TRUSTED_ENV and _values(n) is None for n in re.findall(r'\$\{?(\w+|[@*#?!-])', part)): return True
    return False


LISTERS = {'find', 'gfind', 'ls', 'gls', 'fd', 'fdfind', 'tree', 'rg', 'ripgrep', 'ag', 'ack', 'ugrep', 'pt', 'grep', 'egrep', 'fgrep', 'ggrep'}
EVERYWHERE = {'locate', 'glocate', 'mlocate', 'plocate', 'mdfind'}  # names from the whole disk
NOT_OPENED = {'echo', 'printf', 'basename', 'dirname', 'true', 'false', ':', 'test', '[', 'mkdir', 'touch', 'realpath', 'readlink'}


def _reaches(argv):
    """The command lists or searches file names in a folder that is, or holds, keys or a sign-in (the home folder), or in one that
    cannot be known."""
    words = _strip(_redirects(argv)[0])
    name = os.path.basename(words[0]) if words else ''
    if name in EVERYWHERE: return True
    if name not in LISTERS: return False
    starts = (_positional(words[1:], set()) or ['.']) if name in ('ls', 'gls') else _search_roots('find' if name == 'gfind' else name, words[1:])[0]
    rooted, unknown = _rooted(starts)
    return unknown or any(_secret_path(s) or _holds_secrets(s) for s in rooted + starts)


def _all_inner(text, depth=0):
    """Every command line inside $( … ), <( … ), >( … ) and `…` of the text, those inside them too."""
    found = [x for x in _inner(text) if x]
    return found + [y for x in found for y in (_all_inner(x, depth + 1) if depth < 4 else [x])]


def _piped_names(parts, n, piped, words, read, stripped, command):
    """File names a command opens that another command of the line lists (queue #344): … | xargs cat, xargs cat < <(find ~),
    find ~ | cpio -o, zip -@. Asked when what lists them reaches the home folder's keys, or the list file names one."""
    before = [os.path.basename(w) for w in words[:len(words) - len(stripped)]]
    prog = os.path.basename(stripped[0]) if stripped else ''
    opens = ('xargs' in before or 'parallel' in before) and prog and prog not in NOT_OPENED | DELETE_COMMANDS
    opens = opens or prog == 'cpio' and any(re.fullmatch(r'-[a-zA-Z]*o[a-zA-Z]*|--create', a) for a in stripped[1:]) or prog == 'zip' and '-@' in stripped
    if not opens: return []
    feeders, k = [], n
    while k in piped and k > 0: k -= 1; feeders.append(parts[k])  # every command before it in the pipe
    if read or any(w.startswith('<<') for w in parts[n]):  # < <( … ), <<< "$( … )": a command inside the line hands the names on
        feeders += [p for x in _all_inner(command) for p in _split(_without_inner(x))[0]]
    files = [r for r in read if not re.fullmatch(r'/dev/fd/\d+|/dev/stdin|-', r)]
    listed = _listed(files, prog, words) if files else []  # xargs cat < list.txt: the names in the list, as xargs -a list.txt
    if listed: return [_hit('secret', '讀取 ' + _names(listed))]
    return [_hit('secret', '讀取 （另一個指令列出的檔案，範圍包含家目錄）')] if any(map(_reaches, feeders)) else []
