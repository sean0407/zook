# 產出: the files a Bot made or changed, for its detail panel. Listing only; nothing here widens what a Bot can reach.
# Loaded by backend/server.py into one shared namespace.
OUTPUT_LIMIT = 200
OUTPUT_PREVIEW = {'.txt': 'text', '.md': 'markdown', '.markdown': 'markdown', '.csv': 'text', '.json': 'text', '.log': 'text', '.py': 'text', '.js': 'text', '.ts': 'text', '.html': 'text', '.css': 'text',
                  '.swift': 'text', '.sh': 'text', '.yml': 'text', '.yaml': 'text', '.xml': 'text', '.sql': 'text', '.pdf': 'pdf'}
_OUTPUT_SKIP = ('attachments', 'node_modules', '__pycache__')


def scratch_name(name):
    """Office lock files (~$報告.pptx, .~lock.報告.odp#), temporary files and Finder's .DS_Store are never something a Bot handed over."""
    low = str(name).lower()
    return low.startswith(('~$', '.')) or low.endswith(('.tmp', '.temp', '.crdownload')) or low in ('thumbs.db', 'desktop.ini')


def _output_kind(name):
    suffix = pathlib.Path(name).suffix.lower()
    return 'image' if suffix in IMAGE_TYPES else OUTPUT_PREVIEW.get(suffix, 'file')


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
    pending = [(workspace, 0)]; seen = 0
    while pending and seen < 2000:
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
        said = [(j.get('content'), j.get('createdAt'), j.get('finishedAt')) for j in mine if j.get('content') and not j.get('plan')][-40:]  # a read-only plan makes nothing
        scope, chosen = bot_scope(bot)
        folder = os.path.realpath(chosen) if scope == 'folder' and chosen else ''
    attached = os.path.join(workspace, 'attachments')
    named = [(p, a, b) for text, a, b in said for p in named_paths(text) if not _inside(os.path.realpath(p), attached)]  # the user's own files are not outputs
    for path, started, finished in wrote[-400:] + named[-200:]:  # what a tool reported comes first
        if not path or len(path) >= 300 or not os.path.isabs(path) or '..' in pathlib.PurePosixPath(path).parts: continue  # cut off, relative, or climbing out
        try:
            since = datetime.datetime.fromisoformat(started).timestamp() - 2
            until = datetime.datetime.fromisoformat(finished).timestamp() + 5 if finished else since + JOB_TIMEOUT + 60
        except (TypeError, ValueError): continue
        # A reply only says it tried to write. The file counts when it really changed during that reply, in a place the Bot may use, and is not Zook's own data.
        real = os.path.realpath(path)
        if _inside(real, data_dir) and not _inside(real, workspace): continue
        if scope == 'workspace' and not _inside(real, workspace): continue
        if scope == 'folder' and not (_inside(real, workspace) or (folder and _inside(real, folder))): continue
        add(real, since, until)
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
    return data, 'application/octet-stream'
