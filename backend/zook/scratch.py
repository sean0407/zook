# Each Bot's own scratch folder (queue #261, decisions #28). Loaded by backend/server.py into one shared namespace.
# Zook makes <data>/workspaces/<Bot>/.zook-scratch once, keeps its device:inode in Zook's data (outside the workspace), and gives
# the Bot the tool zook_clean_scratch: it deletes plain files right in that very folder by name, through the folder opened once and
# checked to be the one Zook made, without asking; only files made during this reply (their birth time), so an existing file of the
# user's moved in there is not deleted (a second line behind zook_gate.py asking before a move into the folder). Birth time is not a
# proof the Bot made the file: one rewritten as a new file (sed -i, an editor's save) is new too, and setattrlist can set it. A Bot
# of a CLI without Zook's gate can delete anything with its own rm anyway. A shell rm is never let through without asking (zook_gate.py), because what it
# really deletes cannot be known for sure from the command line; /tmp and the Mac's temporary folder are asked as before.
SCRATCH_NOTE = ('\n暫存檔：中間產物、一次性腳本、預覽圖（轉圖看版面的圖片）和轉檔過程的檔案，一律直接放在「%s」裡（不要另建子資料夾），不要放 /tmp、系統暫存資料夾或家目錄。'
                '回覆結束時 Zook 會自動清掉這次回覆放進去的檔案，不用自己刪、也不用等使用者核准；想提早清可以呼叫 zook_clean_scratch，'
                '把要刪的檔名（只有檔名，不含路徑）列給它。不要用 rm 刪暫存檔：用 rm 一律會先問使用者。')
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
    Returns (path, identity, since), or None when it could not be set up (then the tool is not offered and the record is left as it is)."""
    for key in ('ZOOK_SCRATCH', 'ZOOK_SCRATCH_ID'): env.pop(key, None)  # never one inherited from elsewhere
    workspace = os.path.normpath(os.path.abspath(str(store.dir / 'workspaces' / bot_id)))
    folder = os.path.join(workspace, '.zook-scratch')
    record = store.dir / 'tools' / 'scratch' / re.sub(r'[^A-Za-z0-9_-]', '_', str(bot_id))
    with _SCRATCH_LOCK:  # two replies of one Bot starting together make one folder
        try:
            record.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try: known = record.read_text(encoding='utf-8').strip()
            except FileNotFoundError: known = ''
            if known and not re.fullmatch(r'\d+:\d+', known): raise ValueError('damaged')
            try: info = os.lstat(folder)
            except FileNotFoundError: info = None
            if info is not None and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and _scratch_id(info) == known: ident = known
            else:
                if info is not None: os.rename(folder, '%s-old-%d' % (folder, int(time.time() * 1000)))
                ident = _make_scratch(workspace, folder)
                new = record.with_name(record.name + '.new'); new.write_text(ident, encoding='utf-8'); os.replace(str(new), str(record))
        except (OSError, UnicodeDecodeError, ValueError) as error:  # damaged or unreadable: touch nothing, no tool this time
            if not isinstance(error, OSError):
                log_activity(store, 'tool', 'Bot 暫存資料夾的紀錄損壞（%s），這次不提供清理工具；刪掉這個紀錄檔就會重建。' % record, by='Zook')
            return None
    env['ZOOK_SCRATCH'], env['ZOOK_SCRATCH_ID'] = folder, ident
    return folder, ident, time.time()  # since when files there are this reply's: Zook's sweep at its end takes nothing made before


def scratch_note(scratch):
    return SCRATCH_NOTE % scratch[0] if scratch else ''


def scratch_file_name(name):
    """One plain name right in the folder: no path, no .., not hidden."""
    return (isinstance(name, str) and 0 < len(name) <= 255 and '/' not in name and not name.startswith('.')
            and all(c.isprintable() for c in name) and name == name.strip())


def clean_scratch(folder, ident, names, since):
    """Delete these plain files of the scratch folder. The folder is opened once (never through a link) and must still be the one Zook
    made; each name is looked at in that open folder and deleted there only when it is a plain file with one name, of this user, made
    at or after `since` (a move keeps a file's birth time; setting a file's times only moves it earlier, a later one takes setattrlist / SetFile)."""
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
            try: still = _scratch_id(os.lstat(folder)) == ident
            except OSError: still = False
            if not still: kept.append('%s（暫存資料夾被換掉了，沒有刪）' % name); continue  # moved away meanwhile: what is in it is no longer only the Bot's
            try: own = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError: kept.append('%s（不存在）' % name); continue
            except OSError: kept.append('%s（讀不到）' % name); continue
            if not stat.S_ISREG(own.st_mode) or own.st_nlink != 1 or own.st_uid != os.getuid():
                kept.append('%s（不是一般檔案，沒有刪）' % name); continue  # a link, a folder, a hard link to a file elsewhere
            if getattr(own, 'st_birthtime', 0) < since:
                kept.append('%s（不是這次回覆建立的，沒有刪）' % name); continue
            if not _unlink_checked(fd, name, own): kept.append('%s（刪不掉）' % name); continue
            deleted.append(name)
    finally: os.close(fd)
    return deleted, kept


def scratch_busy(store, bot_id, job_id):
    """Another reply of this Bot is running (it may be using the scratch folder)."""
    with store.lock: return any(j.get('botId') == bot_id and j.get('id') != job_id and j.get('status') == 'running' for j in store.data['jobs'])


def scratch_sweep(store, bot, scratch, busy=lambda: False):
    """When a reply ends (#331 #249): Zook clears what the Bot left right in its scratch folder during this reply (preview pictures,
    one-off scripts), with the same checks as zook_clean_scratch, so no rm and no approval card is needed. Only when no other reply of
    the Bot is running (its files would be this reply's too by their time): busy() is asked under the same lock that a new reply's
    scratch_env waits for, so none starts using the folder while it is swept. Returns the names deleted."""
    if not scratch or len(scratch) < 3: return []
    folder, ident, since = scratch[:3]
    deleted = []
    with _SCRATCH_LOCK:
        if busy(): return []
        try: names = sorted(n for n in os.listdir(folder) if scratch_file_name(n))
        except OSError: return []
        for i in range(0, len(names), SCRATCH_MOST):
            try: deleted += clean_scratch(folder, ident, names[i:i + SCRATCH_MOST], since)[0]
            except RuntimeError: break  # not the folder Zook made any more: nothing more is touched
    if deleted: log_activity(store, 'tool', 'Zook 在回覆結束後清掉「%s」暫存資料夾裡這次回覆留下的 %d 個檔案' % (bot.get('name', 'Bot'), len(deleted)), by='Zook')
    return deleted


def _unlink_checked(fd, name, seen):
    """Delete the very file looked at: first renamed to a name nobody can guess (so nothing can be put under it meanwhile), and deleted
    only when it is still that file; otherwise given its name back (unless something else took it)."""
    hidden = '.zook-deleting-' + secrets.token_hex(8)
    try: os.rename(name, hidden, src_dir_fd=fd, dst_dir_fd=fd)
    except OSError: return False
    try: now = os.stat(hidden, dir_fd=fd, follow_symlinks=False)
    except OSError: return False
    if stat.S_ISREG(now.st_mode) and now.st_nlink == 1 and (now.st_dev, now.st_ino) == (seen.st_dev, seen.st_ino):
        try: os.unlink(hidden, dir_fd=fd); return True
        except OSError: pass
    try: os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        try: os.rename(hidden, name, src_dir_fd=fd, dst_dir_fd=fd)
        except OSError: pass
    except OSError: pass
    return False


def scratch_tools(store, bot, runtime, scratch):
    """zook_clean_scratch, for a Bot whose scratch folder Zook set up for this reply. Never asked (False: Zook's runtime treats it like
    a read, so no mode asks; a reply that may only read never has it, see plan_safe); each use is in the activity record."""
    if not scratch: return []
    folder, ident = scratch[:2]
    since = scratch[2] if len(scratch) > 2 else time.time()  # from when this reply set the folder up: nothing made before it
    def clean(args):
        deleted, kept = clean_scratch(folder, ident, args.get('names'), since)
        if deleted: log_activity(store, 'tool', '「%s」清理暫存資料夾，刪除 %d 個檔案：%s' % (bot.get('name', 'Bot'), len(deleted), '、'.join(deleted)), by='Zook')
        return dict({'deleted': deleted}, **({'notDeleted': kept} if kept else {}))
    return [(runtime._schema('zook_clean_scratch', 'Delete your own scratch files: plain files right in your scratch folder (%s), by file name only (no path, '
                             'no /, no .., no hidden files), made during this reply. Runs without asking the user. Use this instead of rm for scratch files.' % folder,
                             {'names': {'type': 'array', 'items': {'type': 'string'}, 'description': 'File names in the scratch folder, 1–%d' % SCRATCH_MOST}},
                             ['names'], False), clean, False)]
