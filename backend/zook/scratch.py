# Each Bot's own scratch folder (queue #261, decisions #28). Loaded by backend/server.py into one shared namespace.
# Zook makes <data>/workspaces/<Bot>/.zook-scratch once, keeps its device:inode in Zook's data (outside the workspace), and gives
# the Bot the tool zook_clean_scratch: it deletes plain files right in that very folder by name, through the folder opened once and
# checked to be the one Zook made, without asking. A shell rm is never let through without asking (zook_gate.py), because what it
# really deletes cannot be known for sure from the command line; /tmp and the Mac's temporary folder are asked as before.
SCRATCH_NOTE = ('\n暫存檔：中間產物、一次性腳本、轉檔過程的檔案一律放在「%s」，不要放 /tmp 或系統暫存資料夾。用完呼叫 zook_clean_scratch，'
                '把要刪的檔名（只有檔名，不含路徑）列給它，Zook 會直接清掉，不用等使用者核准。不要用 rm 刪暫存檔：用 rm 一律會先問使用者。')
SCRATCH_MOST = 50
_SCRATCH_LOCK = threading.Lock()


def _scratch_id(info):
    return '%d:%d' % (info.st_dev, info.st_ino)


def _make_scratch(workspace, folder):
    """Make the folder under a name nobody can guess, take its identity from the open folder itself, then put it in place. Something
    put at that path meanwhile makes the rename fail (or, an empty folder, is replaced); a folder that is not the one opened is never
    recorded."""
    temp = os.path.join(workspace, '.zook-scratch-new-' + secrets.token_hex(8))
    os.mkdir(temp, 0o700)
    fd = os.open(temp, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid(): raise OSError('not the folder Zook made')
        try: os.rename(temp, folder)
        except OSError:
            try: os.rmdir(temp)
            except OSError: pass
            raise
        now = os.lstat(folder)
        if _scratch_id(now) != _scratch_id(info): raise OSError('the folder was replaced')
        return _scratch_id(info)
    finally: os.close(fd)


def scratch_env(store, bot_id, env):
    """Make (or keep) this Bot's scratch folder and give zook_gate.py its path and identity (ZOOK_SCRATCH, ZOOK_SCRATCH_ID). A folder
    there that Zook did not make (a link, a file, another folder put in its place) is renamed aside, never deleted, and a new one made.
    Returns (path, identity), or None when it could not be set up (then the tool is not offered and the record is left as it is)."""
    for key in ('ZOOK_SCRATCH', 'ZOOK_SCRATCH_ID'): env.pop(key, None)  # never one inherited from elsewhere
    workspace = os.path.normpath(os.path.abspath(str(store.dir / 'workspaces' / bot_id)))
    folder = os.path.join(workspace, '.zook-scratch')
    record = store.dir / 'tools' / 'scratch' / re.sub(r'[^A-Za-z0-9_-]', '_', str(bot_id))
    with _SCRATCH_LOCK:  # two replies of one Bot starting together make one folder
        try:
            record.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try: known = record.read_text(encoding='utf-8').strip()
            except FileNotFoundError: known = ''
            if known and not re.fullmatch(r'\d+:\d+', known): return None  # damaged: touch nothing, no tool this time
            try: info = os.lstat(folder)
            except FileNotFoundError: info = None
            if info is not None and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and _scratch_id(info) == known: ident = known
            else:
                if info is not None: os.rename(folder, '%s-old-%d' % (folder, int(time.time() * 1000)))
                ident = _make_scratch(workspace, folder)
                new = record.with_name(record.name + '.new'); new.write_text(ident, encoding='utf-8'); os.replace(str(new), str(record))
        except (OSError, UnicodeDecodeError): return None
    env['ZOOK_SCRATCH'], env['ZOOK_SCRATCH_ID'] = folder, ident
    return folder, ident


def scratch_note(scratch):
    return SCRATCH_NOTE % scratch[0] if scratch else ''


def scratch_file_name(name):
    """One plain name right in the folder: no path, no .., not hidden."""
    return (isinstance(name, str) and 0 < len(name) <= 255 and '/' not in name and not name.startswith('.')
            and all(c.isprintable() for c in name) and name == name.strip())


def clean_scratch(folder, ident, names):
    """Delete these plain files of the scratch folder. The folder is opened once (never through a link) and must still be the one Zook
    made; each name is looked at in that open folder and deleted there only when it is a plain file with one name, of this user."""
    if not isinstance(names, list) or not 0 < len(names) <= SCRATCH_MOST: raise RuntimeError('names 要是 1–%d 個檔名。' % SCRATCH_MOST)
    bad = [n for n in names if not scratch_file_name(n)]
    if bad: raise RuntimeError('只能給暫存資料夾裡的檔名，不能有路徑、/、..，也不能是隱藏檔：%s。沒有刪除任何檔案。' % '、'.join(str(n)[:40] for n in bad[:5]))
    try: fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError: raise RuntimeError('暫存資料夾不在了或被換成別的東西，沒有刪除任何檔案。')
    deleted, kept = [], []
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or _scratch_id(info) != ident:
            raise RuntimeError('暫存資料夾已經不是 Zook 建立的那一個，沒有刪除任何檔案。')
        for name in dict.fromkeys(names):
            try: own = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError: kept.append('%s（不存在）' % name); continue
            except OSError: kept.append('%s（讀不到）' % name); continue
            if not stat.S_ISREG(own.st_mode) or own.st_nlink != 1 or own.st_uid != os.getuid():
                kept.append('%s（不是一般檔案，沒有刪）' % name); continue  # a link, a folder, a hard link to a file elsewhere
            try: os.unlink(name, dir_fd=fd)
            except OSError: kept.append('%s（刪不掉）' % name); continue
            deleted.append(name)
    finally: os.close(fd)
    return deleted, kept


def scratch_tools(store, bot, runtime, scratch):
    """zook_clean_scratch, for a Bot whose scratch folder Zook set up for this reply. Never asked; each use is in the activity record."""
    if not scratch: return []
    folder, ident = scratch
    def clean(args):
        deleted, kept = clean_scratch(folder, ident, args.get('names'))
        if deleted: log_activity(store, 'tool', '「%s」清理暫存資料夾，刪除 %d 個檔案：%s' % (bot.get('name', 'Bot'), len(deleted), '、'.join(deleted)), by='Zook')
        return dict({'deleted': deleted}, **({'notDeleted': kept} if kept else {}))
    return [(runtime._schema('zook_clean_scratch', 'Delete your own scratch files: plain files right in your scratch folder (%s), by file name only (no path, '
                             'no /, no .., no hidden files). Runs without asking the user. Use this instead of rm for scratch files.' % folder,
                             {'names': {'type': 'array', 'items': {'type': 'string'}, 'description': 'File names in the scratch folder, 1–%d' % SCRATCH_MOST}},
                             ['names'], False), clean, False)]
