# 產出: the files a Bot made or changed, for its detail panel. Listing only; nothing here widens what a Bot can reach.
# Loaded by backend/server.py into one shared namespace.
OUTPUT_LIMIT = 200
OUTPUT_SECONDS = 4  # 產出 answers within this, with what it found by then
OUTPUT_PREVIEW = {'.txt': 'text', '.md': 'markdown', '.markdown': 'markdown', '.csv': 'text', '.json': 'text', '.log': 'text', '.py': 'text', '.js': 'text', '.ts': 'text', '.html': 'text', '.css': 'text',
                  '.swift': 'text', '.sh': 'text', '.yml': 'text', '.yaml': 'text', '.xml': 'text', '.sql': 'text', '.pdf': 'pdf'}
_OUTPUT_SKIP = ('attachments', 'node_modules', '__pycache__')


def scratch_name(name):
    """Office lock files (~$報告.pptx, .~lock.報告.odp#), temporary files and Finder's .DS_Store are never something a Bot handed over."""
    low = str(name).lower()
    return low.startswith(('~$', '.')) or low.endswith(('.tmp', '.temp', '.crdownload')) or low in ('thumbs.db', 'desktop.ini')


def _output_kind(name):
    suffix = pathlib.Path(name).suffix.lower()
    return 'image' if suffix in IMAGE_TYPES else 'office' if suffix in OFFICE_TYPES else OUTPUT_PREVIEW.get(suffix, 'file')  # office: pictures of its pages (officeview.py)


def _inside(path, folder):
    """Whether a real path is inside a real folder. The Mac's disk ignores letter case, so the comparison does too."""
    return path.casefold().startswith(folder.rstrip(os.sep).casefold() + os.sep)


NAMED_SPLIT = re.compile(r'[\s`\'"<>()（）\[\]「」『』，、。：；！？*|]+')  # one pass, no backtracking
NAMED_FILE = re.compile(r'[^/]+\.[A-Za-z0-9]{1,8}')


def named_paths(text):
    """Absolute file paths a reply names, e.g. 「已存到 /tmp/x/報表.xlsx」: whole words only, so 「sales.xlsx-old」 is not read as 「sales.xlsx」.
    Only a hint: the file still has to have changed during that reply."""
    found = []
    for word in NAMED_SPLIT.split(str(text or '')[:20000]):
        word = word.rstrip('。，.,:：;')
        if word.startswith('/') and not word.startswith('//') and len(word) < 300 and NAMED_FILE.fullmatch(word.rsplit('/', 1)[-1]) and word not in found:
            found.append(word)
            if len(found) >= 30: break
    return found


def named_folders(text):
    """Absolute folders a message names, e.g. 「放 /tmp/zook-inspect/A/」: a Bot that writes with a command (a script, swift, cp) leaves
    no record of the file, so the files that changed in the folder the work was sent to stand in for it. Only a hint, like named_paths."""
    found = []
    for word in NAMED_SPLIT.split(str(text or '')[:20000]):
        word = word.rstrip('。，.,:：;')
        if word.startswith('file:///'): word = word[7:]
        if not word.startswith('/') or word.startswith('//') or len(word) >= 300 or NAMED_FILE.fullmatch(word.rstrip('/').rsplit('/', 1)[-1]): continue
        word = word.rstrip('/')
        if word.count('/') >= 2 and word not in found and not _folder_never(word):
            found.append(word)
            if len(found) >= 10: break
    return found


FOLDER_NEVER = ('/var/', '/private/', '/System/', '/Library/', '/usr/', '/bin/', '/sbin/', '/etc/', '/dev/', '/opt/', '/cores/', '/Volumes/Macintosh HD/')  # the Mac's own and its scratch space (/private/tmp is let through below)
FOLDER_OK = ('/tmp/', '/private/tmp/')


def _folder_never(path):
    p = path.rstrip('/').casefold() + '/'
    return not p.startswith(tuple(x.casefold() for x in FOLDER_OK)) and p.startswith(tuple(x.casefold() for x in FOLDER_NEVER))
FOLDER_FILES = 50


def _folder_files(path, since, until):
    """The files directly in a folder (not inside its sub-folders) that changed between since and until, newest first, at most FOLDER_FILES. Links are left out."""
    changed = []
    try:
        with os.scandir(path) as entries:
            for n, e in enumerate(entries):
                if n >= 5000: break
                if e.name.startswith('.') or e.is_symlink() or not e.is_file(follow_symlinks=False): continue
                try: when = e.stat(follow_symlinks=False).st_mtime
                except OSError: continue
                if since <= when <= until: changed.append((when, e.path))
    except OSError: return []
    return [p for _, p in sorted(changed, reverse=True)[:FOLDER_FILES]]


def bot_outputs(store, bot):
    """Files in the Bot's working folder, plus files elsewhere that one of its replies really changed. Newest first."""
    workspace = os.path.realpath(str(store.dir / 'workspaces' / bot['id'])); data_dir = os.path.realpath(str(store.dir)); found = {}
    def add(path, since=None, until=None):
        # Only the real location is ever used: the same one that is checked is the one that is listed and served.
        if os.path.realpath(path) != path: return
        try: info = os.lstat(path)
        except OSError: return
        name = os.path.basename(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or scratch_name(name) or path in found: return  # hard links could show another file
        if since is not None and not since <= info.st_mtime <= until: return
        found[path] = dict(id=hashlib.sha256(path.encode()).hexdigest()[:20], name=name, path=path, size=info.st_size, kind=_output_kind(name),
                           at=datetime.datetime.fromtimestamp(info.st_mtime, datetime.timezone.utc).isoformat())
    pending = [(workspace, 0)]; seen = 0; deadline = time.monotonic() + OUTPUT_SECONDS  # a slow disk or huge folders: list what was found in time
    while pending and seen < 2000 and time.monotonic() < deadline:
        folder, depth = pending.pop()
        try: entries = list(os.scandir(folder))
        except OSError: continue
        for entry in entries:
            seen += 1
            if entry.name.startswith('.') or entry.is_symlink(): continue  # a link could point anywhere
            if entry.is_dir(follow_symlinks=False):
                if depth < 3 and entry.name not in _OUTPUT_SKIP: pending.append((entry.path, depth + 1))
            elif entry.is_file(follow_symlinks=False): add(entry.path)
    with store.lock:  # only copied here; reading the replies' words happens after the lock is let go
        mine = [j for j in store.data['jobs'] if j.get('botId') == bot['id']]
        wrote = [(str((c.get('arguments') or {}).get('path') or ''), j.get('createdAt'), j.get('finishedAt')) for j in mine
                 for c in (j.get('toolCalls') or []) + [dict(name='native_write', arguments={'path': p}) for p in j.get('wrote') or []] if c.get('name') == 'native_write']
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()  # #53: written so far, before the reply ends; changed up to now
        wrote += [(p, j.get('createdAt'), now) for j in mine if j.get('status') == 'running' for p in list((PROGRESS.get(j['id']) or {}).get('paths') or [])]
        said = [(j.get('content'), j.get('createdAt'), j.get('finishedAt')) for j in mine if j.get('content') and not j.get('plan')][-40:]  # a read-only plan makes nothing
        asked = []  # the folder the user sent the work to
        for j in mine[-40:]:
            if j.get('plan') or not j.get('chatId'): continue
            try: messages = chat_messages(bot, j['chatId'])
            except Exception: continue
            at = next((i for i, m in enumerate(messages) if m.get('id') == j.get('messageId')), 0)
            ask = next((m for m in reversed(messages[:at]) if m.get('role') == 'user'), None)
            if ask: asked.append((ask.get('content'), j.get('createdAt'), j.get('finishedAt')))
        kept = [(p, j.get('createdAt'), j.get('finishedAt')) for j in mine for p in j.get('namedFolders') or []]  # from replies whose words were trimmed
        scope, chosen = bot_scope(bot)
        folder = os.path.realpath(chosen) if scope == 'folder' and chosen else ''
    attached = os.path.join(workspace, 'attachments')
    named = [(p, a, b) for text, a, b in said for p in named_paths(text) if not _inside(os.path.realpath(p), attached)]  # the user's own files are not outputs
    for path, started, finished in wrote[-400:] + named[-200:]:  # what a tool reported comes first
        if time.monotonic() > deadline: break
        if not path or len(path) >= 300 or not os.path.isabs(path) or '..' in pathlib.PurePosixPath(path).parts: continue  # cut off, relative, or climbing out
        try:
            since = datetime.datetime.fromisoformat(started).timestamp() - 2
            until = datetime.datetime.fromisoformat(finished).timestamp() + 5 if finished else since + JOB_TIMEOUT + 60
        except (TypeError, ValueError): continue
        # A reply only says it tried to write. The file counts when it really changed during that reply, in a place the Bot may use, and is not Zook's own data.
        real = os.path.realpath(path)
        if _inside(real, data_dir) and not _inside(real, workspace): continue
        if _inside(real, attached): continue  # the user's own files are not outputs, however a reply reported them
        if scope == 'workspace' and not _inside(real, workspace): continue
        if scope == 'folder' and not (_inside(real, workspace) or (folder and _inside(real, folder))): continue
        add(real, since, until)
    # The folder the work was sent to, or that the reply named: files a command wrote there leave no other trace.
    home = os.path.realpath(os.path.expanduser('~')).casefold()
    for path, started, finished in ([(p, a, b) for text, a, b in said + asked for p in named_folders(text)] + kept)[-100:]:
        if time.monotonic() > deadline: break
        try:
            since = datetime.datetime.fromisoformat(started).timestamp() - 2
            until = datetime.datetime.fromisoformat(finished).timestamp() + 5 if finished else since + JOB_TIMEOUT + 60
        except (TypeError, ValueError): continue
        real = os.path.realpath(path); low = real.casefold()
        if not os.path.isdir(real) or _folder_never(real) or low in (workspace.casefold(), home): continue  # the working folder is listed already; home is too broad
        if low == data_dir.casefold() or _inside(real, data_dir): continue  # never Zook's own data
        if scope == 'workspace' and not _inside(real, workspace): continue
        if scope == 'folder' and not (_inside(real, workspace) or (folder and (low == folder.casefold() or _inside(real, folder)))): continue
        for child in _folder_files(real, since, until):
            if not _inside(os.path.realpath(child), attached): add(os.path.realpath(child), since, until)
    return sorted(found.values(), key=lambda x: x['at'], reverse=True)[:OUTPUT_LIMIT]


def bot_output(store, bot, output_id):
    return next((x for x in bot_outputs(store, bot) if x['id'] == output_id), None)


def output_response(item):
    """(bytes, content type) for showing one file. Web pages and SVG are sent as plain text so they can never run in Zook's window."""
    if item['size'] > MAX_UPLOAD: raise ValueError('這個檔案超過 20 MB，請在 Finder 開啟。')
    if os.path.realpath(item['path']) != item['path']: raise OSError('moved')
    fd = os.open(item['path'], os.O_RDONLY | os.O_NOFOLLOW)  # the file that was listed, not a link put in its place afterwards
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise OSError('changed')
        data = f.read(MAX_UPLOAD + 1)
    suffix = pathlib.Path(item['name']).suffix.lower()
    if item['kind'] == 'image': return data, IMAGE_TYPES[suffix]
    if item['kind'] == 'pdf': return data, 'application/pdf'
    if item['kind'] in ('text', 'markdown'): return data, 'text/plain; charset=utf-8'
    return data, OFFICE_TYPES.get(suffix, 'application/octet-stream')  # #201: a Word file downloads as one


# 這段對話的資料夾 (#241): where a conversation's files go when the user names no place, instead of the real Desktop. Inside the
# Bot's own workspace, so every access setting may write there and 產出 lists it.
CHAT_FILES = 'chat-files'
CHAT_FOLDER_NOTE = '使用者沒指定存放位置時，交出的檔案存到這段對話的資料夾：%s（不要存到桌面、下載或家目錄）。使用者指定了位置就照指定的存。'


def chat_folder(store, bot_id, chat_id, make=True):
    name = re.sub(r'[^A-Za-z0-9_-]', '', str(chat_id or ''))[:64] or 'default'
    folder = store.dir / 'workspaces' / re.sub(r'[^A-Za-z0-9_-]', '', str(bot_id)) / CHAT_FILES / name
    if make: folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder
