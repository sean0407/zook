# -*- coding: utf-8 -*-
"""The words of an approval card for a CLI's own command (#234), for zook_gate.py: what a variable set on the same line holds, Zook's
own folders and the Mac's temporary folder by name, and what a command does in the activity list's plain words. Only words: nothing
here decides what is asked."""
import os, re

MADE_TEMP = '\x01temp'  # a variable that holds what mktemp made on the same line


QUOTED = re.compile(r'\'[^\']*\'|"(?:[^"\\]|\\.)*"')


def _unquoted(command):
    """(the line with the text inside quotes left out, the script of sh -c '…' when the whole line is just that). A value right after
    NAME= keeps its quotes; a double-quoted word keeps only its $NAME uses; other quoted text (echo "D=/x", here-strings) is data."""
    out, scripts, pos = [], [], 0
    for m in QUOTED.finditer(command):
        before, word = command[:m.start()], m.group(0)
        if re.search(r'(?:^|\s)-[A-Za-z]*c\s*$', before):
            inner = word[1:-1]
            scripts.append(re.sub(r'\\([$"`\\])', r'\1', inner) if word[0] == '"' else inner); keep = ' _ '
        elif before.endswith('='): keep = word
        elif word[0] == '"': keep = '"%s"' % ' '.join(re.findall(r'\$\{?[A-Za-z_]\w*\}?', word))
        else: keep = '_'
        out.append(command[pos:m.start()] + keep); pos = m.end()
    out.append(command[pos:])
    return ''.join(out), scripts


def line_vars(command, depth=0):
    """The variables a command line plainly sets to something readable, for the card's words only: a statement of its own NAME=value
    (also after export/local …), a value made of other such variables, or $(mktemp …). Nothing is known when the line could set it
    otherwise or only sometimes (if, for, read, ||, && before it, a here-document, braces, a subshell), when it is used before it is set,
    when the name appears as a bare word, when it is set twice to different things, or when a relative value meets a cd: then the
    card says a variable decides. A line that is only sh -c '…' is read through its script; with anything else around it, nothing is known."""
    text = re.split(r'<<(?!<)', command)[0]  # what follows a here-document marker may be its text, not commands
    text, scripts = _unquoted(text)
    if scripts:
        wrapper = re.sub(r'(?:^|(?<=\s))(?:/\S*/)?(?:sh|bash|zsh|dash|ksh)\s+-[A-Za-z]*c\s+_', '', text, count=1).strip()
        return line_vars(scripts[0], depth + 1) if len(scripts) == 1 and not wrapper and depth < 3 else {}
    rest = re.sub(r'\$\(\s*mktemp\b[^()`]*\)|\$\{[A-Za-z_]\w*\}', '', text)
    if re.search(r'\b(?:if|then|else|elif|fi|for|while|until|do|done|case|esac|select|function|coproc|read|unset|mapfile|readarray|getopts|eval|source|let)\b|\|\||[(){}`]|&&\s*(?:export\s+|local\s+)?[A-Za-z_]\w*=', rest):
        return {}
    moves = re.search(r'(?:^|[\s;&|])(?:cd|pushd|popd|chdir)\b', rest)
    found, at = {}, {}
    for m in re.finditer(r'(?:^|[;\n]|&&)\s*(?:(?:export|local|readonly|typeset|declare)(?:\s+-\w+)*\s+)?([A-Za-z_]\w*)=(\$\(\s*mktemp\b[^()`]*\)|"\$\(\s*mktemp\b[^()`"]*\)"|"[^"`]*"|\'[^\']*\'|[^\s;&|()`"\']*)(?=\s*(?:;|&&|\n|$))', text):
        name, value = m.group(1), m.group(2)
        if re.match(r'"?\$\(\s*mktemp\b', value): value = MADE_TEMP
        elif value[:1] in '"\'' and len(value) >= 2:
            value = value[1:-1] if value[0] == '"' else value[1:-1].replace('$', '\0')  # nothing expands in single quotes
            if value.startswith('~'): value = None  # ~ in quotes is a folder named ~, not home
        if value is not None and ('$(' in value or '`' in value): value = None
        if value is not None and moves and value != MADE_TEMP and not value.startswith(('/', '~', '$HOME', '${HOME}', '$TMPDIR', '${TMPDIR}')): value = None  # relative, after a cd
        found[name] = value if found.get(name, value) == value else None
        at.setdefault(name, []).append((m.start(1), m.end()))
    for name in list(found):
        used = [u.start() for u in re.finditer(r'\$(?:\{%s\}|%s(?!\w))' % (name, name), text)]
        bare = [b.start() for b in re.finditer(r'(?<![\w$])%s(?!\w)' % name, text) if not (b.start() > 0 and text[b.start() - 1] == '{' and text[b.start() - 2:b.start()] == '${')]
        if (used and min(used) < at[name][0][0]) or any(not any(a <= b < e for a, e in at[name]) for b in bare): found[name] = None
    return found


def mid(text, most=90):
    """Long text with its middle left out, so the start and the file name both stay."""
    text = str(text)
    return text if len(text) <= most else text[:most // 2 - 1] + '…' + text[-(most - most // 2):]


ATTACHED_ID = re.compile(r'^[0-9A-Za-z]{8}-(?=.)')


def place(full, temp, data, scratch_part):
    """Zook's own folders (and, with temp, the Mac's temporary folder) in words: never the path inside Zook's data or /var/folders."""
    for one in (full,):  # already where it really is (zook_gate._where): never named by a link on the way
        base = next((d for d in dict.fromkeys((data, os.path.realpath(data) if data else '')) if d and under_plain(one, d)), '')
        if base:
            rest = [p for p in os.path.relpath(one, base).split(os.sep) if p and p != '.']
            if rest[:1] == ['workspaces'] and len(rest) > 2:
                inside = rest[2:]
                if inside[0] == '.zook-scratch': return 'Bot 的暫存資料夾' + ('裡的 %s' % '/'.join(inside[1:]) if inside[1:] else '')
                if inside[:2] == ['attachments', 'group-files'] and inside[2:]: return '群組共用檔案「%s」' % '/'.join(inside[2:])
                if inside[0] == 'attachments' and inside[1:]: return '你上傳的附件「%s」' % ATTACHED_ID.sub('', '/'.join(inside[1:]))
                return 'Bot 工作資料夾裡的 %s' % '/'.join(inside)
            if rest[:1] == ['workspaces'] and len(rest) == 2: return 'Bot 工作資料夾'
            return 'Zook 的資料' + ('「%s」' % '/'.join(rest) if rest else '')
        if scratch_part.search(one):
            inside = one.split('/.zook-scratch', 1)[1].strip('/')
            return 'Bot 的暫存資料夾' + ('裡的 %s' % inside if inside else '')
        m = temp and re.match(r'^(?:/private)?/var/folders/[^/]+/[^/]+/T(?:/(.*))?$', one)
        if m: return '系統暫存資料夾' + ('裡的 %s' % m.group(1) if m.group(1) else '')
        if temp and (one == '/private/tmp' or one.startswith('/private/tmp/')): return one[len('/private'):]
    return ''


def under_plain(path, folder):
    folder = folder.rstrip('/')
    return bool(folder) and (path == folder or path.startswith(folder + '/'))


def resolve(text, known, expand, depth=0):
    """The text with $NAME and ${NAME} put in from the variables of this line (and $HOME, $TMPDIR, ~); None when one is not known."""
    text = expand(text)
    def put(m):
        value = known.get(m.group(1) or m.group(2))
        if value is None or depth > 5: raise KeyError
        value = resolve(value, known, expand, depth + 1) if '$' in value else value
        if value is None: raise KeyError
        return value
    try: out = re.sub(r'\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)', put, text)
    except KeyError: return None
    if '$' in out or '`' in out: return None
    out = out.replace('\0', '$')
    if MADE_TEMP in out[1:]: return None  # a made folder in the middle of a path: not a place
    return out


_WORDS = {}  # actwords.py, loaded once


def plain_steps(command, gate, here):
    """What a command does, in the activity list's plain words (actwords.py: fixed words, a file's own name, the kind of program; never
    the command or code). Loaded from Zook's backend next to this file; [] when it is not there."""
    if 'describe' not in _WORDS:
        _WORDS['describe'] = None
        try:
            space = {'gate_module': lambda: gate, '__name__': 'zook_gate_actwords'}
            with open(os.path.join(here, 'zook', 'actwords.py'), encoding='utf-8') as f: exec(compile(f.read(), 'actwords.py', 'exec'), space)
            _WORDS['describe'] = space
        except Exception: pass
    space = _WORDS['describe']
    if not space: return []
    try: steps, _ = space['_describe'](space['shell_inner'](command))
    except Exception: return []
    return [x for x in dict.fromkeys(steps) if x not in (space['OTHER'], space['UNREADABLE'])]
