# Office 預覽 (#239): Excel, Word and PowerPoint files shown as pictures of their pages in Zook's preview window. pagepics.py
# (Quick Look and macOS's own drawing, no app window) makes them from a private copy of a file the caller has already found the
# Bot or group may show. The pictures stay in data/previews/<key> until the file changes or is deleted. Loaded by
# backend/server.py into one shared namespace.
import zipfile
OFFICE_TYPES = {'.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}
PREVIEW_SECONDS = 150    # one file's pictures; a longer wait says so instead of 「正在產生預覽…」 for ever
PREVIEW_PAGES = 80       # pictures kept and shown for one file
PREVIEW_KEEP = 60        # files whose pictures are kept; the oldest go first
PREVIEW_RETRY = 600      # a failed preview is tried again after this many seconds (the Mac may just have been busy)
PREVIEW_SWEEP_EVERY = 3600
PREVIEW_WAITING = 3      # files waiting for pictures at once; more are asked to try again shortly
PREVIEW_UNPACKED = 400 * 1024 * 1024  # an Office file is a ZIP: one that unpacks to more than this, or into more than 5000 parts, is not pictured
_preview_lock = threading.Lock()
_preview_running = set()
_preview_slot = threading.Semaphore(1)  # one file at a time: Quick Look is heavy
_preview_swept = [0.0]


def previews_root(store):
    """data/previews, or None when it (or the data folder) is a link: nothing is written or deleted through one."""
    root = pathlib.Path(str(store.dir)) / 'previews'
    return None if root.is_symlink() or pathlib.Path(str(store.dir)).is_symlink() else root


def _remove_in(parent_fd, name):
    """Delete one entry of an already opened folder, its contents first. Every step is relative to an open folder and never
    follows a link, so a link put anywhere on the way removes only the link, never what it points at."""
    try: fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=parent_fd)
    except OSError:
        try: os.unlink(name, dir_fd=parent_fd)  # a file or a link
        except OSError: pass
        return
    try:
        for entry in list(os.scandir(fd)): _remove_in(fd, entry.name)
    finally: os.close(fd)
    try: os.rmdir(name, dir_fd=parent_fd)
    except OSError: pass


def _remove_preview(store, name):
    """Remove data/previews/<name>: 1 when it was there. data/previews is opened once without following a link."""
    if previews_root(store) is None or '/' in name or name in ('', '.', '..'): return 0
    try: root_fd = os.open(str(previews_root(store)), os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    except OSError: return 0
    try:
        try: os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except OSError: return 0
        _remove_in(root_fd, name); return 1
    finally: os.close(root_fd)


def _preview_key(path, info):
    """Changes whenever the file does: where it is, its size, when it last changed, and when it was last written at all (ctime:
    a file rewritten with its old modification time put back still counts as changed)."""
    return hashlib.sha256(('%s\0%d\0%d\0%d' % (path, info.st_size, info.st_mtime_ns, info.st_ctime_ns)).encode()).hexdigest()[:32]


def _preview_open(path, strict):
    """(fd, key) for one file the caller already found shareable. Only an ordinary file of its own: a link put in its place, a
    folder or a hard link to another file is refused (OSError). strict: the path must be the file's real place (產出)."""
    if pathlib.Path(path).suffix.lower() not in OFFICE_TYPES: raise OSError('not an office file')
    if strict and os.path.realpath(path) != path: raise OSError('moved')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)  # a pipe put in its place cannot make Zook wait
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: os.close(fd); raise OSError('changed')
    return fd, _preview_key(path, info), info


def _cache_read(store, key, name):
    """The bytes of data/previews/<key>/<name>, or None. No step follows a link: a link planted as a cache folder or file reads nothing."""
    root = previews_root(store)
    if root is None: return None
    try: root_fd = os.open(str(root), os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    except OSError: return None
    try:
        folder_fd = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=root_fd)
        try: fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
        finally: os.close(folder_fd)
    except OSError: return None
    finally: os.close(root_fd)
    with os.fdopen(fd, 'rb') as f:
        return f.read(MAX_UPLOAD) if stat.S_ISREG(os.fstat(f.fileno()).st_mode) else None


def _preview_json(store, key, name):
    try: found = json.loads(_cache_read(store, key, name) or b'')
    except ValueError: return None
    return found if isinstance(found, dict) else None


def _preview_write_json(path, value):
    temp = str(path) + '.tmp'
    with open(temp, 'w', encoding='utf-8') as f: json.dump(value, f, ensure_ascii=False)
    os.replace(temp, str(path))


def office_preview(store, path, strict=False):
    """{'status': 'ready', 'pages': n, 'version': key} | {'status': 'working'} | {'status': 'failed', 'reason': …}.
    The first call for a file (or a changed file) starts making its pictures in the background."""
    root = previews_root(store)
    fd, key, info = _preview_open(path, strict)
    try:
        if root is None: return dict(status='failed', reason='無法產生預覽，可以下載後用其他程式開啟。')
        done = _preview_json(store, key, 'done.json')
        pages, total = done and done.get('pages'), done and done.get('total')
        if type(pages) is int and 1 <= pages <= PREVIEW_PAGES:
            return dict(status='ready', pages=pages, total=total if type(total) is int and pages <= total <= 100000 else pages, note=str(done.get('note') or '')[:200], version=key)
        failed = _preview_json(store, key, 'failed.json')
        at = failed and failed.get('at')
        if type(at) in (int, float) and 0 <= time.time() - at < PREVIEW_RETRY: return dict(status='failed', reason=str(failed.get('reason') or ''))
        if info.st_size > MAX_UPLOAD: return dict(status='failed', reason='這個檔案超過 20 MB，無法在 Zook 裡預覽，請在 Finder 開啟。')
        with _preview_lock:
            if key in _preview_running: return dict(status='working')
            if len(_preview_running) >= PREVIEW_WAITING: return dict(status='failed', reason='Zook 正在產生其他檔案的預覽，請過一會兒再開一次。')
            _preview_running.add(key)
        try:
            with os.fdopen(os.dup(fd), 'rb') as f: data = f.read(MAX_UPLOAD + 1)
            threading.Thread(target=_make_preview, args=(store, root, key, path, pathlib.Path(path).suffix.lower(), data), daemon=True).start()
        except Exception:
            with _preview_lock: _preview_running.discard(key)
            raise
        return dict(status='working')
    finally: os.close(fd)


def office_render(source, out):
    """([pictures of its first PREVIEW_PAGES pages, in order], a note when some are missing, how many pages it has). Tests put a fake in its place: CI has no dependable Quick Look."""
    if not os.path.exists('/usr/bin/qlmanage'): raise RuntimeError('這台 Mac 沒有 Quick Look，無法產生預覽，可以下載後用其他程式開啟。')
    proc = subprocess.Popen([sys.executable, PAGEPICS, source, out, '--pages', str(PREVIEW_PAGES)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    try: said = proc.communicate(timeout=PREVIEW_SECONDS)[0].decode('utf-8', 'replace')
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):  # pagepics and the Quick Look it started
            try: os.killpg(proc.pid, sig)
            except OSError: pass
            try: proc.wait(timeout=5); break
            except subprocess.TimeoutExpired: continue
        raise RuntimeError('這份檔案太大或太複雜，預覽逾時。可以下載後用其他程式開啟。')
    number = lambda name: [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', name)]
    try: made = sorted((n for n in os.listdir(out) if n.lower().endswith('.png')), key=number)
    except OSError: made = []
    if not made: raise RuntimeError('這份檔案沒辦法轉成預覽圖，可能已損壞或用了特殊格式。可以下載後用其他程式開啟。')
    note = '有幾頁沒有轉出預覽圖，完整內容請下載後查看。' if proc.returncode else '只預覽了第一頁，完整內容請下載後查看。' if '只能轉第一頁' in said else ''  # pagepics ends with 1 when pages are missing
    if source.lower().endswith('.xlsx'): note = '試算表只能預覽第一個工作表的開頭，完整內容請下載後查看。'  # Quick Look pictures one sheet's first screen
    whole = re.search(r'共 (\d+) 頁，只轉了前', said)  # a longer file: only its first PREVIEW_PAGES pages were pictured
    return [os.path.join(out, n) for n in made], note, int(whole.group(1)) if whole else len(made)


def _unpacks_safely(path):
    """An Office file whose parts unpack to a sensible size: a small ZIP that unpacks to gigabytes would fill the Mac's memory."""
    try:
        with zipfile.ZipFile(path) as z: parts = z.infolist()
    except (OSError, zipfile.BadZipFile, ValueError): return True  # not a ZIP: Quick Look says it cannot read it
    return len(parts) <= 5000 and sum(p.file_size for p in parts) <= PREVIEW_UNPACKED


def _make_preview(store, root, key, path, suffix, data):
    folder = root / key
    try:
        with _preview_slot:
            root.mkdir(mode=0o700, exist_ok=True)
            work = pathlib.Path(tempfile.mkdtemp(prefix='.work-', dir=str(root)))
            try:
                copy = work / ('preview' + suffix)
                fd = os.open(str(copy), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as f: f.write(data)
                try:
                    if not _unpacks_safely(str(copy)): raise RuntimeError('這份檔案解開後太大，無法產生預覽，請下載後開啟。')
                    (pages, note, total), reason = office_render(str(copy), str(work / 'pages')), ''
                except RuntimeError as exc: pages, note, total, reason = [], '', 0, str(exc)
                except Exception: pages, note, total, reason = [], '', 0, '無法產生預覽，可以下載後用其他程式開啟。'
                _remove_preview(store, key); folder.mkdir(mode=0o700)
                for n, picture in enumerate(pages[:PREVIEW_PAGES], 1): os.replace(picture, str(folder / ('%d.png' % n)))
                if pages: _preview_write_json(folder / 'done.json', dict(pages=min(len(pages), PREVIEW_PAGES), total=max(total, len(pages)), note=note, path=path))
                else: _preview_write_json(folder / 'failed.json', dict(reason=reason, path=path, at=time.time()))
            finally: _remove_preview(store, work.name)
    except OSError: pass  # the disk is full or the folder went away: the next look tries again
    finally:
        with _preview_lock: _preview_running.discard(key)
        sweep_previews(store, force=True)


def sweep_previews_later(store, force=False):
    """sweep_previews beside the caller, which may hold the store lock."""
    threading.Thread(target=sweep_previews, args=(store, force), daemon=True).start()


def preview_page(store, path, number, strict=False):
    """The picture of one page of a file's finished preview, or None."""
    root = previews_root(store)
    if root is None or not re.fullmatch(r'[1-9]\d{0,3}', str(number)): return None
    fd, key, _ = _preview_open(path, strict); os.close(fd)
    return _cache_read(store, key, '%s.png' % number)


def sweep_previews(store, force=False):
    """Pictures of a file that was deleted, moved or changed are removed; beyond PREVIEW_KEEP files, the oldest too."""
    now = time.time()
    if not force and now - _preview_swept[0] < PREVIEW_SWEEP_EVERY: return 0
    _preview_swept[0] = now
    root = previews_root(store)
    if root is None or not root.is_dir(): return 0
    with _preview_lock: busy = set(_preview_running)
    drop = lambda folder: _remove_preview(store, os.path.basename(folder))
    kept, removed = [], 0
    for entry in list(os.scandir(str(root))):
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False): continue
        if entry.name in busy: continue
        try: age = now - entry.stat(follow_symlinks=False).st_mtime
        except OSError: continue
        if entry.name.startswith('.work-'):
            if age > PREVIEW_SECONDS * 2: removed += drop(entry.path)  # left behind by a Zook that quit; a newer one may be in use
            continue
        meta = _preview_json(store, entry.name, 'done.json') or _preview_json(store, entry.name, 'failed.json') or {}
        if not meta and age < 60: continue  # being written right now
        try: info = os.lstat(str(meta.get('path') or ''))
        except (OSError, ValueError): info = None
        if info is None or not stat.S_ISREG(info.st_mode) or _preview_key(meta['path'], info) != entry.name:
            removed += drop(entry.path)
        else: kept.append((entry.stat(follow_symlinks=False).st_mtime, entry.path))
    for _, old in sorted(kept, reverse=True)[PREVIEW_KEEP:]: removed += drop(old)
    return removed


def group_preview_path(store, group_id, name):
    """The real place of one group file, only when it really is straight inside that group's own folder (no folder link on the way)."""
    folder = group_files_dir(store, group_id); top = pathlib.Path(str(store.dir)) / 'group-files'; base = os.path.realpath(str(top))
    if pathlib.Path(str(store.dir)).is_symlink() or top.is_symlink() or folder.is_symlink() or os.path.realpath(str(folder)) != os.path.join(base, group_id): return None
    found = group_file_path(store, dict(id=group_id), name)
    real = os.path.realpath(str(found)) if found else ''
    return real if real and os.path.dirname(real) == os.path.join(base, group_id) else None


def preview_route(handler, store, path, rest, strict=False):
    """GET …/pages: how the preview stands; GET …/pages/<n>: the picture of page n."""
    try:
        if not rest: return handler.respond(200, office_preview(store, path, strict))
        data = preview_page(store, path, rest[0], strict)
    except OSError: return handler.error(404, '找不到這個檔案，可能已經被移走或刪除。')
    return handler.respond(200, data, 'image/png') if data else handler.error(404, '這一頁還沒有預覽圖。')
