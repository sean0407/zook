# Chat attachments that never went out (#153②): taken out of the message box with ×, or left behind when the page was closed
# before sending. Zook keeps every upload in data/uploads/<id>/ until no message names it. Loaded by backend/server.py into one
# shared namespace.
UPLOAD_STALE_SECONDS = 24 * 3600   # an upload no message names is removed after a day (a draft kept in another window keeps it that long)
UPLOAD_SWEEP_EVERY = 3600
_upload_swept = [0.0]


def _upload_names(store):
    """Every upload id that Zook's data still names: messages of Bots, deleted Bots and groups, messages waiting in line, jobs."""
    return json.dumps(store.data, ensure_ascii=False)


def _uploads_root(store):
    """data/uploads, or None when it (or the data folder) is a link: nothing is ever deleted through one."""
    root = store.dir / 'uploads'
    return None if root.is_symlink() or pathlib.Path(store.dir).is_symlink() else root


def upload_drop(store, upload_id):
    """Lock held. The user took a file out of the message box before sending it: its upload is deleted, unless a message uses it."""
    root = _uploads_root(store)
    if root is None or not upload_meta(store, upload_id) or upload_id in _upload_names(store): return False
    folder = root / upload_id
    if folder.is_symlink() or not folder.is_dir(): return False
    shutil.rmtree(str(folder), ignore_errors=True)
    return True


def upload_bytes(store, meta):
    """The file of an upload, or None when it is gone from the disk (a 404, not an error page)."""
    try: return (store.dir / 'uploads' / meta['id'] / 'file').read_bytes()
    except OSError: return None


def sweep_uploads(store, force=False):
    """Lock held. Uploads older than a day that no message names are removed. Returns how many."""
    now = time.time()
    if not force and now - _upload_swept[0] < UPLOAD_SWEEP_EVERY: return 0
    _upload_swept[0] = now
    root = _uploads_root(store)
    if root is None: return 0
    try: folders = [p for p in root.iterdir() if re.fullmatch(r'[0-9a-f]{32}', p.name) and not p.is_symlink() and p.is_dir()]
    except OSError: return 0
    named, removed = None, 0
    for folder in folders:
        try: age = now - folder.stat().st_mtime
        except OSError: continue
        if age < UPLOAD_STALE_SECONDS: continue
        if named is None: named = _upload_names(store)
        if folder.name in named: continue
        shutil.rmtree(str(folder), ignore_errors=True); removed += 1
    return removed
