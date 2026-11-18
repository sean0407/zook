# 產出: the files a Bot made or changed, for its detail panel. Listing only; nothing here widens what a Bot can reach.
# Loaded by backend/server.py into one shared namespace.
OUTPUT_LIMIT = 200
OUTPUT_PREVIEW = {'.txt': 'text', '.md': 'markdown', '.markdown': 'markdown', '.csv': 'text', '.json': 'text', '.log': 'text', '.py': 'text', '.js': 'text', '.ts': 'text', '.html': 'text', '.css': 'text',
                  '.swift': 'text', '.sh': 'text', '.yml': 'text', '.yaml': 'text', '.xml': 'text', '.sql': 'text', '.pdf': 'pdf'}
_OUTPUT_SKIP = ('attachments', 'node_modules', '__pycache__')


def _output_kind(name):
    suffix = pathlib.Path(name).suffix.lower()
    return 'image' if suffix in IMAGE_TYPES else OUTPUT_PREVIEW.get(suffix, 'file')


def bot_outputs(store, bot):
    """Files in the Bot's working folder, plus files elsewhere that its replies recorded changing. Newest first."""
    workspace = store.dir / 'workspaces' / bot['id']; found = {}
    def add(path):
        try:
            real = pathlib.Path(os.path.realpath(str(path))); info = os.lstat(str(real))
        except OSError: return
        if not stat.S_ISREG(info.st_mode) or real.name.startswith('.') or str(real) in found: return
        found[str(real)] = dict(id=hashlib.sha256(str(real).encode()).hexdigest()[:20], name=real.name, path=str(real), size=info.st_size, kind=_output_kind(real.name),
                                at=datetime.datetime.fromtimestamp(info.st_mtime, datetime.timezone.utc).isoformat())
    pending = [(workspace, 0)]; seen = 0
    while pending and seen < 2000:
        folder, depth = pending.pop()
        try: entries = list(os.scandir(str(folder)))
        except OSError: continue
        for entry in entries:
            seen += 1
            if entry.name.startswith('.') or entry.is_symlink(): continue  # a link could point anywhere
            if entry.is_dir(follow_symlinks=False):
                if depth < 3 and entry.name not in _OUTPUT_SKIP: pending.append((pathlib.Path(entry.path), depth + 1))
            elif entry.is_file(follow_symlinks=False): add(entry.path)
    with store.lock:
        wrote = [str((c.get('arguments') or {}).get('path') or '') for j in store.data['jobs'] if j.get('botId') == bot['id'] for c in j.get('toolCalls') or [] if c.get('name') == 'native_write']
        folder = bot.get('accessFolder') if bot.get('access') == 'folder' else ''
    for path in wrote[-400:]:
        if not path or len(path) >= 300: continue  # a cut-off path is not a real one
        if os.path.isabs(path): add(path)
        else:
            for base in [workspace] + ([pathlib.Path(folder)] if folder else []): add(base / path)
    return sorted(found.values(), key=lambda x: x['at'], reverse=True)[:OUTPUT_LIMIT]


def bot_output(store, bot, output_id):
    return next((x for x in bot_outputs(store, bot) if x['id'] == output_id), None)


def output_response(item):
    """(bytes, content type) for showing one file. Web pages and SVG are sent as plain text so they can never run in Zook's window."""
    if item['size'] > MAX_UPLOAD: raise ValueError('這個檔案超過 20 MB，請在 Finder 開啟。')
    with open(item['path'], 'rb') as f: data = f.read(MAX_UPLOAD + 1)
    suffix = pathlib.Path(item['name']).suffix.lower()
    if item['kind'] == 'image': return data, IMAGE_TYPES[suffix]
    if item['kind'] == 'pdf': return data, 'application/pdf'
    if item['kind'] in ('text', 'markdown'): return data, 'text/plain; charset=utf-8'
    return data, 'application/octet-stream'
