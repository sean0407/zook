# Plain words for a command a CLI ran, for the activity list (#82 #144): what it did, in one line, never the command or the code in it.
# Loaded by backend/server.py into one shared namespace. Only fixed words, a file's own name, a site's name and the kind of program
# are kept: the safety boundaries zook_gate.py sees (刪除檔案、對外送出 …) by their name alone, no paths or arguments; the program text of
# a here-document (python3 - <<'PY' … PY) only tells what kind of file it makes; a program name Zook does not know is not shown.
import os, re, shlex

UNREADABLE = '執行一段 Zook 看不出內容的指令'
LANGUAGES = {'python': 'Python', 'node': 'JavaScript', 'nodejs': 'JavaScript', 'deno': 'JavaScript', 'bun': 'JavaScript', 'ruby': 'Ruby', 'perl': 'Perl',
             'php': 'PHP', 'swift': 'Swift', 'osascript': 'AppleScript', 'lua': 'Lua', 'Rscript': 'R'}
READERS = {'cat', 'head', 'tail', 'less', 'more', 'wc', 'file', 'stat', 'xxd', 'hexdump', 'od', 'strings', 'mdls', 'plutil', 'pdftotext', 'pdfinfo'}
PHRASES = {  # program -> what it does; {f} is the first file it names
    'ls': '查看資料夾內容', 'tree': '查看資料夾內容', 'du': '查看檔案大小', 'df': '查看磁碟空間',
    'find': '尋找檔案', 'fd': '尋找檔案', 'mdfind': '尋找檔案', 'locate': '尋找檔案',
    'grep': '搜尋檔案內容', 'egrep': '搜尋檔案內容', 'fgrep': '搜尋檔案內容', 'rg': '搜尋檔案內容', 'ag': '搜尋檔案內容', 'ack': '搜尋檔案內容',
    'sed': '整理文字資料', 'awk': '整理文字資料', 'sort': '整理文字資料', 'uniq': '整理文字資料', 'cut': '整理文字資料', 'tr': '整理文字資料',
    'jq': '整理文字資料', 'column': '整理文字資料', 'paste': '整理文字資料', 'iconv': '轉換文字編碼',
    'diff': '比對檔案', 'cmp': '比對檔案', 'comm': '比對檔案',
    'mkdir': '建立資料夾「{f}」', 'touch': '建立檔案「{f}」', 'cp': '複製檔案「{f}」', 'ditto': '複製檔案「{f}」', 'rsync': '複製檔案「{f}」',
    'mv': '移動或改名檔案「{f}」', 'ln': '建立捷徑「{f}」', 'tee': '寫入檔案「{f}」', 'chmod': '更改檔案權限', 'mktemp': '建立暫存檔',
    'zip': '壓縮檔案「{f}」', 'tar': '壓縮或解壓縮檔案「{f}」', 'unzip': '解壓縮檔案「{f}」', 'gzip': '壓縮檔案「{f}」', 'gunzip': '解壓縮檔案「{f}」',
    'open': '開啟「{f}」', 'sips': '處理圖片「{f}」', 'convert': '處理圖片「{f}」', 'magick': '處理圖片「{f}」', 'qlmanage': '產生預覽圖',
    'textutil': '轉換文件格式', 'pandoc': '轉換文件格式', 'soffice': '轉換文件格式', 'libreoffice': '轉換文件格式', 'ffmpeg': '處理影音檔', 'say': '朗讀文字',
    'curl': '從網路取得資料', 'wget': '從網路取得資料', 'git': '使用 git', 'gh': '使用 GitHub', 'pip': '查看 Python 套件', 'pip3': '查看 Python 套件',
    'brew': '查看已安裝的軟體', 'npm': '使用 npm', 'which': '確認程式是否已安裝', 'whereis': '確認程式是否已安裝', 'type': '確認程式是否已安裝',
    'pwd': '查看目前位置', 'whoami': '查看系統資訊', 'uname': '查看系統資訊', 'sw_vers': '查看系統資訊', 'date': '查看時間', 'kill': '結束程式', 'pkill': '結束程式',
    'defaults': '讀取系統設定', 'pbcopy': '複製到剪貼簿', 'pbpaste': '讀取剪貼簿', 'screencapture': '擷取螢幕畫面', 'shortcuts': '執行捷徑',
}
SILENT = {'cd', 'export', 'set', 'unset', 'true', 'false', ':', 'echo', 'printf', 'sleep', 'exit', 'return', 'source', '.', 'local', 'wait', 'trap', 'shopt',
          'test', '[', '[[', ']]', 'read', 'declare', 'typeset', 'alias', 'pushd', 'popd', 'builtin', 'let', 'break', 'continue', 'shift', 'setopt', 'ulimit', 'umask'}
KEYWORDS = {'do', 'then', 'else', 'elif', 'if', 'while', 'until', '!', '{', '}', 'time', 'coproc'}
SKIP_PARTS = {'for', 'select', 'case', 'esac', 'done', 'fi', 'function', 'in'}
KINDS_OF_FILE = (('Excel', r'openpyxl|xlsxwriter|\.xlsx\b|to_excel|read_excel|load_workbook|exceljs|\bxlsx\b'), ('Word 文件', r'\bdocx\b|\.docx\b'),
                 ('簡報', r'\bpptx\b|\.pptx\b|python-pptx'), ('PDF', r'\.pdf\b|reportlab|\bfitz\b|pypdf|pdfkit'), ('CSV', r'\.csv\b|\bcsv\.'),
                 ('圖片', r'matplotlib|savefig|\bPIL\b|\.png\b|\.jpe?g\b'), ('JSON', r'\.json\b|json\.dump'))
MAKES = re.compile(r'\.save\(|savefig|to_excel|to_csv|writeFile|\.write\(|json\.dump\(|open\([^)]*[\'"][wa]b?[\'"]|Document\(\)|Workbook\(\)|Presentation\(\)')
OVERLAP = {'send': ('從網路取得資料', '使用 git', '使用 GitHub', '使用 npm'), 'install': ('查看已安裝的軟體', '查看 Python 套件', '使用 npm'), 'system': ('讀取系統設定',)}
GATED = {'rm', 'rmdir', 'unlink', 'trash', 'srm', 'shred', 'mail', 'mailx', 'sendmail', 'msmtp', 'mutt', 'scp', 'sftp', 'ftp', 'ssh', 'nc', 'ncat', 'netcat',
         'socat', 'telnet', 'sudo', 'su', 'doas', 'security', 'ssh-keygen', 'ssh-add'}
HEREDOC = re.compile(r'<<(-?)\s*(?:\'([^\'\n]+)\'|"([^"\n]+)"|\\?([\w.-]+))')
OTHER = '執行其他程式'
LABELS_UNCLEAR = '執行無法判讀的指令'


def _heredocs(command):
    """(the command with every here-document's text taken out, those texts in order). Each body ends at a line holding only its marker."""
    lines, kept, bodies, i = command.split('\n'), [], [], 0
    while i < len(lines):
        line = lines[i]; kept.append(line); i += 1
        starts = [m.start() for m in re.finditer(r'(?<!<)<<(?!<)', line)]
        if any(not HEREDOC.match(line, at) for at in starts): return command, None  # a marker Zook cannot read (<<:EOF): not read at all
        for m in HEREDOC.finditer(line):
            if re.match(r'[^\s;&|<>)]', line[m.end():m.end() + 1]): return command, None  # a marker written in pieces (<<'END'E): not read
            marker, tabs, body = next(x for x in m.groups()[1:] if x), m.group(1) == '-', []
            while i < len(lines) and (lines[i].lstrip('\t') if tabs else lines[i]) != marker: body.append(lines[i]); i += 1  # as the shell ends it
            i += 1; bodies.append('\n'.join(body))
    return '\n'.join(kept), bodies


def _file_word(path):
    """A file's own name for the activity list: no folders, no '$', and an attachment without the id Zook put in front of it."""
    name = str(path or '').rstrip('/').split('/')[-1]
    name = re.sub(r'^[0-9a-f]{8}-(?=.)', '', name) if _attachment(path) else name
    return name if re.fullmatch(r'[^\s\'"`$<>|;&(){}\\]{1,76}\.[A-Za-z0-9]{1,8}', name) else ''  # a name with an extension; any other word may be code


def _attachment(path):
    """Inside a Bot's attachments folder (workspaces/<Bot>/attachments, or attachments/ where the Bot works): an upload."""
    return bool(re.search(r'(^|/)workspaces/[^/]+/attachments/|^(\./)?attachments/', str(path or '')))


def _clean(text):
    """Text that can always be saved: a broken character from the CLI's output becomes '?'."""
    return text.encode('utf-8', 'replace').decode('utf-8')


def _purpose(code):
    """What kind of file a program makes or reads, from its text: 「產生 Excel」, or ''."""
    kinds = [k for k, pattern in KINDS_OF_FILE if re.search(pattern, code or '', re.I)][:2]
    return ('%s %s' % ('產生' if MAKES.search(code) else '讀取', '、'.join(kinds))) if kinds else ''


def _program(name, args, code):
    """How one program run reads: 「執行 Python 程式「make.py」（產生 Excel）」."""
    lang = LANGUAGES.get('python' if re.fullmatch(r'python[\d.]*', name) else name)
    inline = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in _gate().INLINE_FLAGS or re.fullmatch(r'-[a-zA-Z]*[ceEr][a-zA-Z]*', a)), None)  # also -ne, -pe …
    script = '' if inline is not None else next((a for a in args if not a.startswith('-')), '')
    if lang == 'Python' and '-m' in args: return '執行 Python 模組'
    file = _file_word(script) if script and script != '-' else ''  # a program file is named, not opened
    purpose = _purpose(inline if inline is not None else code)
    return '執行 %s 程式%s%s' % (lang, '「%s」' % file if file else '', '（%s）' % purpose if purpose else '')


def _gate():
    return gate_module()


def _describe(command, depth=0):
    """The plain steps of one command line, in order (duplicates kept for the caller to drop), and whether it could be read."""
    gate = _gate()
    text, bodies = _heredocs(command)
    if bodies is None: return [UNREADABLE], False
    parts, clear = gate._split(gate._without_inner(text))
    steps = []
    if not clear: parts = parts[:1]  # broken quoting: words after the first program may be code, not programs
    for inner in gate._inner(text):  # $( … ) may also be words inside quotes: only steps Zook knows are kept from it
        if depth < 3: steps += [s for s in _describe(inner, depth + 1)[0] if s not in (OTHER, UNREADABLE)]
    body = iter(bodies)
    for argv in parts:
        words = gate._strip(gate._redirects(argv)[0])
        while words and words[0] in KEYWORDS: words = words[1:]
        words = gate._strip(words)
        code = next(body, '') if any(w.startswith('<<') for w in argv) and '<<<' not in ' '.join(argv) else ''
        if not words or words[0] in SKIP_PARTS: continue
        word = words[0]; name = os.path.basename(word); args = words[1:]
        if word == '_' and not args: continue  # where a $( … ) stood: what ran inside it was read above
        if '$' in word or '`' in word or word == '_': steps.append(UNREADABLE); continue
        if name in GATED: continue  # always a safety line of its own (刪除檔案、對外送出 …), said above
        if name in gate.SHELLS or name == 'eval':
            script = next((args[i + 1] for i, a in enumerate(args[:-1]) if re.fullmatch(r'-[a-z]*c[a-z]*', a)), None) if name != 'eval' else ' '.join(args)
            if script is not None or name == 'eval':
                steps += _describe(script, depth + 1)[0] if script and depth < 3 else [UNREADABLE]; continue
            file = next((_file_word(a) for a in args if not a.startswith('-')), '')
            steps.append('執行指令檔「%s」' % file if file else '執行指令檔'); continue
        if name in SILENT or re.fullmatch(r'[A-Za-z_]\w*\+?=.*', word): continue
        files = [a for i, a in enumerate(args) if not a.startswith('-') and not re.fullmatch(r'[\d.]+', a) and '://' not in a
                 and (i == len(args) - 1 or i == 0 or not re.fullmatch(r'-[^=]+', args[i - 1]))]  # the word after an option may be its value (a password)
        first = _file_word(files[0]) if files else ''
        if name in LANGUAGES or re.fullmatch(r'python[\d.]*', name): steps.append(_program(name, args, code)); continue
        if name in READERS:
            if first: steps.append(('讀取你上傳的附件「%s」' if _attachment(files[0]) else '讀取檔案「%s」') % first)
            continue  # without a file it reads what came before it in a pipe, or writes a here-document (said by the redirect)
        if name in ('sed', 'perl') and any(a.startswith('-i') for a in args):  # the expression comes first: the file is the last word
            steps.append('修改檔案「%s」' % _file_word(args[-1]) if _file_word(args[-1]) else '修改檔案'); continue
        phrase = PHRASES.get(name)
        if phrase: steps.append(phrase.replace('「{f}」', '「%s」' % first if first else '').replace('{f}', first)); continue
        steps.append(OTHER)  # a name Zook does not know may be a word of code: not shown
    return steps + _redirect_steps(text), clear


def _redirect_steps(text):
    """Files read with < and written with > or >>, from the command with its quoted words and comments blanked out: a '>' in quotes or
    after # is not a redirection."""
    masked = re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", 'Q', text)
    masked = re.sub(r'(^|[\s;&|])#[^\n]*', r'\1', masked)
    steps = []
    for m in re.finditer(r'(?<![<>&])(>>?|<)(?![<>&(])\s*([^\s;&|<>()]+)', masked):
        name = _file_word(m.group(2))
        if not name or m.group(2).startswith('/dev/'): continue
        steps.append(('讀取你上傳的附件「%s」' if _attachment(m.group(2)) else '讀取檔案「%s」') % name if m.group(1) == '<' else '寫入檔案「%s」' % name)
    return steps


def shell_inner(command):
    """The command itself, without the shell around it: how Codex reports a command (/bin/zsh -lc '<command>')."""
    if re.match(r'^/bin/(?:zsh|bash|sh) -l?c ', command):
        try: words = shlex.split(command)
        except ValueError: words = []
        if len(words) == 3: return words[2]
    return command


def plain_command_summary(command):
    """One plain line for a command the activity list keeps: its safety lines as on an approval card (without the 看不懂 ones), then
    what it did. Never the command, never code, never a word from a here-document."""
    if not isinstance(command, str) or not command.strip(): return '執行指令'
    gate = _gate()
    command = shell_inner(command)
    try:
        kinds = [k for k, _ in gate.command_boundaries(_heredocs(command)[0]) if k != 'unclear']  # a here-document's text is data, not commands
        steps, _ = _describe(command)
    except Exception:
        return '執行指令'
    kinds = list(dict.fromkeys(kinds))
    lines, said = [gate.LABELS[k] for k in kinds], tuple(w for k in kinds for w in OVERLAP.get(k, ()))
    steps = [s for s in dict.fromkeys(steps) if not (said and s.startswith(said))]  # 對外送出 already says the curl
    for vague in (OTHER, UNREADABLE):
        if len(steps) > 1 and vague in steps: steps.remove(vague)
    shown = steps[:3] + (['等 %d 個步驟' % (len(steps) - 3)] if len(steps) > 3 else [])
    text = '；'.join(lines + (['、'.join(shown)] if shown else []))
    return _clean(hide_command_secrets(text))[:600] if text else '執行指令'


def plain_old_summary(summary):
    """An activity line saved by an earlier version, in today's words: 「執行指令：python3、from、print」 kept only the program names it
    knows (the rest may be words of code), and a 「執行無法判讀的指令」 line is said plainly."""
    if not isinstance(summary, str): return '執行指令'
    labels = list(_gate().LABELS.values())
    old = summary.startswith(('執行指令：', '這個 curl', '一個 curl')) or any(summary.startswith(x + ' ') or summary.startswith(x + '（') for x in labels)
    if not old: return summary  # today's words (an earlier version wrote either the programs or approval lines, nothing else)
    lines = []
    for line in summary.split('；'):
        if line.startswith('執行指令：'):
            names = [n for n in line[5:].split('、') if n]
            lines += [s for s in (_describe(n)[0] for n in names if n in PHRASES or n in LANGUAGES or re.fullmatch(r'python[\d.]*', n)) for s in s]
        else:
            label = _gate().LABELS['split'] if line.startswith(('這個 curl', '一個 curl')) else next((x for x in labels if line.startswith(x)), None)  # an approval card's line: its name, without paths
            if label and label != LABELS_UNCLEAR: lines.append(label)
    lines = list(dict.fromkeys(lines))
    return '、'.join(lines) if lines and not any(x in labels for x in lines) else '；'.join(lines) if lines else UNREADABLE


def plain_old_records(store):
    """Activity saved by earlier versions: a command kept whole becomes its summary; an old summary is put in today's words."""
    for job in store.data.get('jobs') or []:
        if not isinstance(job, dict): continue
        if 'toolCalls' in job and not isinstance(job['toolCalls'], list): job['toolCalls'] = []
        if job.get('toolCalls'): job['toolCalls'] = [c for c in job['toolCalls'] if isinstance(c, dict)]
        for call in job.get('toolCalls') or []:
            if call.get('name') != 'native_command': continue
            a = call.get('arguments')
            if not isinstance(a, dict): call['arguments'] = {'summary': '執行指令'}; continue
            if isinstance(a.get('command'), str): call['arguments'] = {'summary': command_summary(a['command'])}
            elif isinstance(a.get('summary'), str): a['summary'] = plain_old_summary(a['summary'])
