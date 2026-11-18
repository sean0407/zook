# Files a group shares. Each Bot gets its own copy for a turn, so no Bot's access is widened. Loaded by backend/server.py into one shared namespace.
GROUP_FILES_TOTAL = 200 * 1024 * 1024
GROUP_FILES_FOLDER = 'group-files'  # inside a Bot's workspace attachments folder


def group_files_dir(store, group_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(group_id)): raise ValueError('群組無效。')
    return store.dir / 'group-files' / group_id


def _plain_files(folder):
    """Ordinary visible files directly in this folder; links and folders are ignored."""
    try:
        with os.scandir(str(folder)) as found:
            return sorted([e for e in found if e.is_file(follow_symlinks=False) and not e.name.startswith('.')], key=lambda e: e.name)
    except OSError: return []


def _file_hash(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): digest.update(chunk)
    return digest.hexdigest()


def list_group_files(store, group):
    info = group.get('fileInfo') or {}
    return [dict(name=e.name, size=e.stat(follow_symlinks=False).st_size, at=datetime.datetime.fromtimestamp(e.stat(follow_symlinks=False).st_mtime, datetime.timezone.utc).isoformat(), by=(info.get(e.name) or {}).get('by', '')) for e in _plain_files(group_files_dir(store, group['id']))]


def group_files_size(store, group_id, skip=''):
    return sum(e.stat(follow_symlinks=False).st_size for e in _plain_files(group_files_dir(store, group_id)) if e.name != skip)


def free_group_file_name(folder, name, owner=''):
    """A name not in use yet: 報告.pdf, then 報告（Alpha）.pdf or 報告 (2).pdf."""
    path = pathlib.Path(name); stem, suffix = path.stem, path.suffix
    candidates = (['%s（%s）%s' % (stem, owner, suffix)] if owner else []) + ['%s (%d)%s' % (stem, n, suffix) for n in range(2, 1000)]
    if not os.path.lexists(str(folder / name)): return name
    return next(upload_name(x) for x in candidates if not os.path.lexists(str(folder / upload_name(x))))


def add_group_file(store, group, name, source, size, by):
    """Move an uploaded temporary file into the group's files."""
    if size > MAX_UPLOAD: raise ValueError('單一檔案不能超過 20 MB。')
    if group_files_size(store, group['id']) + size > GROUP_FILES_TOTAL: raise ValueError('這個群組的檔案已達 200 MB 上限，請先刪除一些。')
    folder = group_files_dir(store, group['id']); folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = free_group_file_name(folder, upload_name(name)); os.replace(str(source), str(folder / name))
    group.setdefault('fileInfo', {})[name] = dict(by=by)
    return name


def group_file_path(store, group, name):
    """The file with exactly this name, or None."""
    return next((pathlib.Path(e.path) for e in _plain_files(group_files_dir(store, group['id'])) if e.name == name), None)


def group_copy_folder(store, bot_id):
    return store.dir / 'workspaces' / bot_id / 'attachments' / GROUP_FILES_FOLDER


def sync_group_files_in(store, group_id, bot_id):
    """Give this Bot a fresh copy for its turn. Returns what the copy looked like."""
    folder = group_copy_folder(store, bot_id)
    if folder.is_symlink(): folder.unlink()
    elif folder.exists(): shutil.rmtree(str(folder), ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700); seen = {}
    for entry in _plain_files(group_files_dir(store, group_id)):
        clone_file(entry.path, folder / entry.name); seen[entry.name] = _file_hash(entry.path)
    return seen


def sync_group_files_out(store, group_id, bot_name, bot_id, seen):
    """Bring back what the Bot added or changed. A file someone else changed meanwhile is kept, and this version gets its own name."""
    shared = group_files_dir(store, group_id); shared.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved, skipped = [], []
    for entry in _plain_files(group_copy_folder(store, bot_id)):
        size = entry.stat(follow_symlinks=False).st_size; digest = _file_hash(entry.path); name = upload_name(entry.name)
        if seen.get(entry.name) == digest: continue
        if size > MAX_UPLOAD or group_files_size(store, group_id, name) + size > GROUP_FILES_TOTAL: skipped.append(name); continue
        current = shared / name
        moved = os.path.lexists(str(current)) and _file_hash(current) != seen.get(entry.name)
        if moved: name = free_group_file_name(shared, name, bot_name)
        temp = shared / ('.incoming-' + ID()); clone_file(entry.path, temp); os.replace(str(temp), str(shared / name)); saved.append(name)
    return saved, skipped


def group_file_tool(store, group_id, runtime):
    """Reads a shared text file for a Bot whose own file tools cannot reach it, such as in 謹慎."""
    def read(args):
        with store.lock:
            group = store.find('groups', group_id)
            found = group_file_path(store, group, args['name']) if group else None
        if not found: raise RuntimeError('找不到這個共用檔案。')
        if found.stat().st_size > runtime.MAX_TEXT: raise RuntimeError('這個檔案超過 128 KB，無法用這個工具讀取。')
        try: return {'name': args['name'], 'content': found.read_text(encoding='utf-8')}
        except UnicodeDecodeError: raise RuntimeError('這個檔案不是文字檔，無法用這個工具讀取。')
    return (runtime._schema('zook_group_file_read', "Read a text file from this group's shared files by its exact name.", {'name': {'type': 'string', 'description': 'Exact file name'}}, ['name']), read, False)
