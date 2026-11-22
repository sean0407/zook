# Files a group shares. Each Bot gets its own copy for a turn, so no Bot's access is widened. Loaded by backend/server.py into one shared namespace.
GROUP_FILES_TOTAL = 200 * 1024 * 1024
GROUP_FILES_FOLDER = 'group-files'  # inside a Bot's workspace attachments folder
_group_files_lock = threading.Lock()  # choosing a name and saving a file happen as one step


def group_files_dir(store, group_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(group_id)): raise ValueError('群組無效。')
    return store.dir / 'group-files' / group_id


def _plain_files(folder):
    """Ordinary visible files directly in this folder; links, folders, lock and temporary files are ignored."""
    try:
        with os.scandir(str(folder)) as found:
            return sorted([e for e in found if e.is_file(follow_symlinks=False) and not scratch_name(e.name)], key=lambda e: e.name)
    except OSError: return []


def _file_hash(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): digest.update(chunk)
    return digest.hexdigest()


def list_group_files(store, group):
    info = group.get('fileInfo') or {}
    return [dict(name=e.name, kind=_output_kind(e.name), size=e.stat(follow_symlinks=False).st_size, at=datetime.datetime.fromtimestamp(e.stat(follow_symlinks=False).st_mtime, datetime.timezone.utc).isoformat(), by=(info.get(e.name) or {}).get('by', '')) for e in _plain_files(group_files_dir(store, group['id']))]


def group_files_size(store, group_id, skip=''):
    return sum(e.stat(follow_symlinks=False).st_size for e in _plain_files(group_files_dir(store, group_id)) if e.name != skip)


def _short_name(name):
    """A safe file name of at most 120 characters that keeps its extension."""
    raw = str(name or '').replace('\\', '/').split('/')[-1]; suffix = pathlib.Path(raw).suffix if len(pathlib.Path(raw).suffix) <= 16 else ''
    stem = upload_name(raw[:len(raw) - len(suffix)] if suffix else raw); suffix = '.' + upload_name(suffix) if suffix else ''
    return stem[:120 - len(suffix)] + suffix


def free_group_file_name(folder, name, owner=''):
    """A name not in use yet: 報告.pdf, then 報告（Alpha）.pdf or 報告 (2).pdf."""
    name = _short_name(name)
    if not os.path.lexists(str(folder / name)): return name
    path = pathlib.Path(name); stem, suffix = path.stem[:80], path.suffix
    candidates = (['%s（%s）%s' % (stem, owner[:20], suffix)] if owner else []) + ['%s (%d)%s' % (stem, n, suffix) for n in range(2, 1000)]
    return next((c for c in map(_short_name, candidates) if not os.path.lexists(str(folder / c))), ID()[:12] + suffix)


def add_group_file(store, group, name, source, size, by):
    """Move an uploaded temporary file into the group's files. The name it was uploaded with is kept (origName): a key file stays known."""
    original = upload_original(name)
    if size > MAX_UPLOAD: raise ValueError('單一檔案不能超過 20 MB。')
    if scratch_name(_short_name(name)): raise ValueError('這個檔名會被當成暫存檔或鎖檔（例如 .tmp、~$ 開頭），放進群組後看不到。請改檔名再上傳。')  # it would be stored but never listed
    with _group_files_lock:
        if group_files_size(store, group['id']) + size > GROUP_FILES_TOTAL: raise ValueError('這個群組的檔案已達 200 MB 上限，請先刪除一些。')
        folder = group_files_dir(store, group['id']); folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = free_group_file_name(folder, name); os.replace(str(source), str(folder / name))
    group.setdefault('fileInfo', {})[name] = dict(by=by, **({'origName': original} if original and original != name else {}))
    return name


def group_original(store, group_id, name):
    """Lock held. The name a shared file was uploaded with, when it differs from the name kept."""
    group = next((g for g in ((getattr(store, 'data', None) or {}).get('groups') or []) if isinstance(g, dict) and g.get('id') == group_id), {})
    return ((group.get('fileInfo') or {}).get(name) or {}).get('origName') or ''


def group_file_path(store, group, name):
    """The file with exactly this name, or None."""
    return next((pathlib.Path(e.path) for e in _plain_files(group_files_dir(store, group['id'])) if e.name == name), None)


def read_group_file(path):
    """The bytes of one shared file, or None when it is gone or no longer a plain file of its own."""
    try: fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError: return None
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: return None
        return f.read()


def group_copy_folder(store, bot_id):
    return store.dir / 'workspaces' / bot_id / 'attachments' / GROUP_FILES_FOLDER


def sync_group_files_in(store, group_id, bot_id, skip=()):
    """Give this Bot a fresh copy for its turn. Returns what the copy looked like."""
    seen = {}
    with bot_folder(store, bot_id, 'attachments', GROUP_FILES_FOLDER) as fd:
        clear_folder(fd)
        for entry in _plain_files(group_files_dir(store, group_id)):
            if entry.name in skip: continue
            with open(entry.path, 'rb') as source: write_into_folder(fd, entry.name, source)
            seen[entry.name] = _file_hash(entry.path)
    remember_uploaded_names(store, bot_id, {n: group_original(store, group_id, n) for n in seen if group_original(store, group_id, n)})  # for the key-file check
    return seen


def _read_bot_file(folder_fd, name, target):
    """Copy one regular file out of the Bot's folder, refusing links. Returns (size, hash), or None when it is not a plain file."""
    try: source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
    except OSError: return None
    if not stat.S_ISREG(os.fstat(source).st_mode): os.close(source); return None
    digest = hashlib.sha256(); size = 0
    with os.fdopen(source, 'rb') as f, open(str(target), 'wb') as out:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            size += len(chunk)
            if size > MAX_UPLOAD: return (size, '')
            digest.update(chunk); out.write(chunk)
    return size, digest.hexdigest()


def sync_group_files_out(store, group_id, bot_name, bot_id, seen):
    """Bring back what the Bot added or changed. A file someone else changed meanwhile is kept, and this version gets its own name."""
    shared = group_files_dir(store, group_id); shared.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with bot_folder(store, bot_id) as workspace:
            attachments = os.open('attachments', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=workspace)
            try: folder_fd = os.open(GROUP_FILES_FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=attachments)
            finally: os.close(attachments)
    except OSError: return [], []
    saved, skipped = [], []
    try:
        for entry_name in sorted(os.listdir(folder_fd)):
            if scratch_name(entry_name): continue  # e.g. PowerPoint's ~$ lock file is not a shared file
            temp =shared / ('.incoming-' + ID())
            try:
                try: copied = _read_bot_file(folder_fd, entry_name, temp)
                except OSError: skipped.append(_short_name(entry_name)); continue
                if copied is None or copied[1] == seen.get(entry_name): continue
                size, digest = copied
                with _group_files_lock:
                    name = _short_name(entry_name); current = shared / name
                    if os.path.lexists(str(current)) and _file_hash(current) != seen.get(entry_name): name = free_group_file_name(shared, name, bot_name)
                    if size > MAX_UPLOAD or group_files_size(store, group_id, name) + size > GROUP_FILES_TOTAL: skipped.append(name); continue
                    os.replace(str(temp), str(shared / name)); saved.append(name)
            finally:
                if os.path.lexists(str(temp)): temp.unlink()
    finally: os.close(folder_fd)
    return saved, skipped


def group_file_tool(store, group_id, runtime):
    """Reads a shared text file for a Bot whose own file tools cannot reach it, such as in 謹慎."""
    def read(args):
        with store.lock:
            group = store.find('groups', group_id)
            found = group_file_path(store, group, args['name']) if group else None
        if not found: raise RuntimeError('找不到這個共用檔案。')
        if found.stat().st_size > runtime.MAX_TEXT: raise RuntimeError('這個檔案超過 128 KB。謹慎模式讀不到，請把這個 Bot 的主動性改成自動後再試。')
        try: return {'name': args['name'], 'content': found.read_text(encoding='utf-8')}
        except UnicodeDecodeError: raise RuntimeError('這個檔案不是文字檔。謹慎模式讀不到，請把這個 Bot 的主動性改成自動後再試。')
    return (runtime._schema('zook_group_file_read', "Read a text file from this group's shared files by its exact name.", {'name': {'type': 'string', 'description': 'Exact file name'}}, ['name']), read, lambda args: 'always' if runtime.secret_name(args.get('name'), group_original(store, group_id, args.get('name'))) else False)  # keys and sign-ins, by the uploaded name too
