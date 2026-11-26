# -*- coding: utf-8 -*-
"""Part of zook_gate.py, read into its namespace (it uses _split, _strip, _secret_path … from there): where a command of a line runs
after its cd, pushd and chdir, what its variables hold, and the files xargs and parallel read their arguments from (queue #293)."""


def _folders():
    """Every folder a command of the line being read may run in, after each cd, pushd or chdir of it (in any order: one may fail);
    None when one cannot be known (a variable, cd -, popd, env -C, a name CDPATH may lead to keys)."""
    found, stack = [_CWD[0]], 0  # stack: pushd's of this line not yet undone; a popd goes back to a folder of this line only then
    for line in _LINES:
        for part in _split(_without_inner(line))[0]:
            raw = _redirects(part)[0]
            if re.search(r'(?:^|\s)(?:\S*/)?env(?:\s+(?:-\S*|\S*=\S*))*?\s+(?:-[^-\s]*C|--chdir)', ' '.join(raw)): return None  # env -C: elsewhere
            words = _strip(list(raw))
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


def _values(name):
    """What a variable of the line being read may hold: set on it on its own (NAME=value, export NAME=value) or a for loop's words;
    None when not known (set from outside, by read, by $( … ), or only for one command)."""
    if name == 'PWD': return _folders()
    found = []
    for line in _LINES:
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
            for v in values: out += _resolved(re.sub(r'\$\{?%s\}?' % n, lambda m: v, p), depth + 1) or [None]
        return None if None in out else [path] + out
    folders = [] if not p or os.path.isabs(p) else None if p.startswith('~') else _folders()  # ~-, ~+: the folder before, or now
    found = None if folders is None else [path] + [os.path.join(f, p) for f in folders]
    return found and found + [m for x in found[1:] or [p] if set(x) & set('*?[') for m in glob.glob(_expand(x))]


def _secret_any(path, unsure=True):
    """Where a key or sign-in is named, after the cds of this line; '' when none is. unsure: a path in a folder that cannot be known
    (cd "$VAR") counts too, as $PWD/…"""
    found = _resolved(path)
    if found is None: return _secret_path(path) and path or ((path if set(path) & set('$`') or GLUED in path else '$PWD/' + _expand(path)) if unsure else '')
    return next((x for x in found if _secret_path(x)), '')


def _read_file(path):
    """A file a command reads (-f FILE, xargs -a FILE): a key or sign-in, or a variable or {a,b} that may be one."""
    return _secret_any(path)


def _listed(files, prog, words=()):
    """xargs -a FILE, parallel :::: FILE: the file, and the paths in it handed to the command (read now: a short plain file only, never
    one that is a key, a link or a pipe); the file itself when what is in it cannot be read. echo and printf open nothing."""
    out = [x for x in map(_secret_any, files) if x]
    for f in [] if out or prog in ('echo', 'printf') else files:
        where = [x for x in _resolved(f) or [] if os.path.isfile(_abs(x))]
        try:
            fd = os.open(_abs(where[-1]), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK) if where else -1
            with os.fdopen(fd, 'rb') as h: text = h.read(65537).decode('utf-8', 'replace') if stat.S_ISREG(os.fstat(h.fileno()).st_mode) else None
        except (OSError, ValueError, IndexError): text = None
        odd = any(re.fullmatch(r'-[^-]*d.*|--delimiter(=.*)?|--colsep(=.*)?', w) for w in words)  # its own separator: not read here
        out += ['（%s 列出的檔案）' % f] if text is None or len(text) > 65536 or odd else [x for x in map(_secret_any, re.split(r'[\s\0]+', text)) if x]
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
        if os.path.basename(w) in ('xargs', 'parallel') and not tool and not _strip(words[:i]):  # in the place of the command
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
