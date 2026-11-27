# Files a group shares. Each Bot gets its own copy for a turn, so no Bot's access is widened. Loaded by backend/server.py into one shared namespace.
import io
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


def group_local_paths(store, group, bot_id, text, shared, author=''):
    """Lock held. Paths another member named for a file that is also among the group's files, rewritten to where this Bot reads
    that file: each member has its own workspace, so 「存在 workspaces/<別人>/簡報.pptx」 is a path the reader cannot open."""
    text = str(text or '')
    if not shared or not author or '/' not in text: return text
    pairs = [((info or {}).get('origName'), name) for name, info in (group.get('fileInfo') or {}).items() if (info or {}).get('origName') and name in shared]
    counts = {}
    for orig, _ in pairs: counts[orig] = counts.get(orig, 0) + 1
    originals = {orig: name for orig, name in pairs if counts[orig] == 1}  # two files uploaded under one name: which is meant is not known
    theirs = str(store.dir / 'workspaces' / author) + '/'  # only the author's own workspace: a same-named file elsewhere is another file
    mine = group_copy_folder(store, bot_id)
    for path in sorted(named_paths(text), key=len, reverse=True):  # a longer path first, so a shorter one inside it is not half-replaced
        if not path.startswith(theirs): continue
        base = path.rsplit('/', 1)[-1]
        name = base if base in shared else originals.get(base) or (upload_name(base) if upload_name(base) in shared else '')
        if name and path != str(mine / name): text = text.replace(path, str(mine / name))
    return text


NAMED_CHECK_MAX = 5  # PDFs named in a checked reply that are copied for the checker
NAMED_CHECK_KEEP = 50  # copies remembered per group, so the same file is not uploaded again at every check


def named_check_plan(store, group, message, given=()):
    """Lock held. What a check needs to copy, worked out from saved data only: the PDF paths the checked reply names that are
    neither attached nor among the group's files, and what its author could read in that turn (the path is the model's words, so
    only a file it could reach itself is ever copied). The copying is named_check_copy, outside the lock."""
    shared = {e.name for e in _plain_files(group_files_dir(store, group['id']))}
    known = shared | {a.get(k) for m in group['messages'] for a in m.get('attachments') or [] for k in ('name', 'origName')} | {a.get('name') for a in given}
    paths = [p for p in named_paths((message or {}).get('content')) if p.lower().endswith('.pdf') and p.rsplit('/', 1)[-1] not in known and upload_name(p.rsplit('/', 1)[-1]) not in known][:NAMED_CHECK_MAX]
    if not paths: return None
    author = next((j for j in store.data['jobs'] if j.get('messageId') == message['id'] and j.get('groupId') == group['id']), {})
    access = author.get('nativeAccess') if isinstance(author.get('nativeAccess'), list) and len(author['nativeAccess']) == 4 else None
    return dict(paths=paths, author=message.get('botId') or author.get('botId') or '', access=access, cache=copy.deepcopy((group.get('checkCopies') or {})))


def named_check_reach(store, plan, path):
    """'workspace' when the file is in the author's own workspace, 'path' when its access let it read there, '' when not."""
    workspace = str(store.dir / 'workspaces' / plan['author']) if plan.get('author') else ''
    if workspace and (path.startswith(workspace + '/') or os.path.realpath(path).startswith(os.path.realpath(workspace) + '/')): return 'workspace'
    scope, root, _, native = plan.get('access') or ('workspace', '', '', False)
    if not native: return ''  # 謹慎 and 先規劃 read only the workspace with Zook's tools
    if scope == 'full': return 'path'
    if scope == 'folder' and root and os.path.realpath(path).startswith(os.path.realpath(str(root)).rstrip('/') + '/'): return 'path'
    return ''


def named_check_copy(store, group_id, bot_id, job, plan):
    """Outside the lock: copy each named PDF the author could reach into the checker's workspace, through the same checks as a path
    the user attaches (upload_from_path) or, inside the author's own workspace, refusing links, hard links and hidden names on the
    way. A file already copied and not changed since is not uploaded again. Returns the note for the checker's prompt."""
    metas, missing, cache = [], [], {}
    for path in plan['paths']:
        reach = named_check_reach(store, plan, path)
        if not reach: missing.append('%s（路徑在範圍外）' % path); continue
        try: info = os.lstat(path); mark = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
        except OSError: missing.append('%s（找不到檔案）' % path); continue
        kept = plan['cache'].get(path) or {}
        meta = upload_meta(store, kept.get('id')) if kept.get('mark') == mark else None
        if not meta:
            try: meta = upload_from_path(store, path) if reach == 'path' else upload_from_workspace(store, plan['author'], path)
            except (OSError, ValueError) as exc: missing.append('%s（%s）' % (path, str(exc).rstrip('。') if isinstance(exc, ValueError) else '無法讀取')); continue
        metas.append(meta); cache[path] = dict(id=meta['id'], mark=mark)
    copies = place_attachments(store, bot_id, metas) if metas else []
    with store.lock:
        group = store.find('groups', group_id)
        if group and cache: group['checkCopies'] = dict(list(dict(group.get('checkCopies') or {}, **cache).items())[-NAMED_CHECK_KEEP:])
        if copies:
            job['attachments'] = (job.get('attachments') or []) + [str(x) for x in copies]
            job['attachmentIds'] = (job.get('attachmentIds') or []) + [m['id'] for m in metas]
        store.save()
    note = attachment_note(copies, '受查核的回覆提到的檔案（已複製一份給你，請讀這份）') if copies else ''
    return note + ('\n受查核的回覆提到、但沒附上的檔案：\n' + '\n'.join('- ' + x for x in missing) if missing else '')


def upload_from_workspace(store, bot_id, path):
    """A file in a Bot's own workspace, as a new upload: every step a real folder (no link, no hidden name), the file a plain one
    with one name, at most 20 MB, counted while copying."""
    workspace = str(store.dir / 'workspaces' / bot_id)
    if not path.startswith(workspace + '/'): path = os.path.join(workspace, os.path.relpath(os.path.realpath(path), os.path.realpath(workspace)))
    parts = os.path.relpath(path, workspace).split('/')
    if '..' in parts or any(x.startswith('.') for x in parts): raise ValueError('這個位置的檔案不能複製')
    fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for i, name in enumerate(parts):
            last = i == len(parts) - 1
            nxt = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | (os.O_NONBLOCK if last else os.O_DIRECTORY), dir_fd=fd)
            os.close(fd); fd = nxt
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_UPLOAD: raise ValueError('這不是一般檔案或超過 20 MB')
        upload_id = ID(); folder = store.dir / 'uploads' / upload_id; folder.mkdir(parents=True, mode=0o700); copied = 0
        try:
            with os.fdopen(os.dup(fd), 'rb') as source, open(str(folder / 'file'), 'wb') as out:
                for chunk in iter(lambda: source.read(1 << 20), b''):
                    copied += len(chunk)
                    if copied > MAX_UPLOAD: raise ValueError('檔案超過 20 MB')
                    out.write(chunk)
            name = upload_name(parts[-1])
            meta = dict(id=upload_id, name=name, origName=upload_original(parts[-1]), size=copied, kind='file', createdAt=NOW())
            (folder / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
            return meta
        except BaseException:
            shutil.rmtree(str(folder), ignore_errors=True); raise
    finally: os.close(fd)


def group_copy_folder(store, bot_id):
    return store.dir / 'workspaces' / bot_id / 'attachments' / GROUP_FILES_FOLDER


def sync_group_files_in(store, group_id, bot_id, skip=()):
    """Give this Bot a fresh copy for its turn. Returns what the copy looked like."""
    seen = {}
    with bot_folder(store, bot_id, 'attachments', GROUP_FILES_FOLDER) as fd:
        clear_folder(fd)
        for entry in _plain_files(group_files_dir(store, group_id)):
            if entry.name in skip: continue
            with open(entry.path, 'rb') as source: data = source.read()  # one read: the copy and its hash are the same content (#240)
            write_into_folder(fd, entry.name, io.BytesIO(data)); seen[entry.name] = hashlib.sha256(data).hexdigest()
    remember_uploaded_names(store, bot_id, {n: group_original(store, group_id, n) for n in seen if group_original(store, group_id, n)})  # for the key-file check
    return seen


def _open_copy_folder(store, bot_id):
    """The Bot's group-files copy folder, held open without following a link anywhere on the way and without making anything. None when there is none."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(bot_id)): return None
    try: fd = os.open(str(store.dir / 'workspaces' / bot_id), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError: return None
    try:
        for name in ('attachments', GROUP_FILES_FOLDER):
            nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd); os.close(fd); fd = nxt
        return fd
    except OSError: os.close(fd); return None


def _same_copy(folder_fd, name, size, digest):
    """This entry's identity when it is a plain file of its own with exactly this content (Zook's copy, not something the Bot made), else None."""
    try: fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
    except OSError: return None
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != size: return None
        found = hashlib.sha256()
        for chunk in iter(lambda: f.read(1 << 20), b''): found.update(chunk)
        return (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size) if found.hexdigest() == digest else None


def drop_group_files(store, server, group):
    """Lock held. A deleted group's files go, and so do the copies of them Zook put in its members' workspaces (#213). Under the lock
    the group's folder is only moved aside; the comparing and removing run in a thread of their own (the files can add up to 200 MB),
    which is returned. Only a copy still exactly as Zook placed it (same name, same content, the same file when it is removed) goes;
    anything else there stays. A Bot kept aside in 已刪除的 Bot is not a member any more and its workspace is left alone until it is
    gone for good (forget_trashed_copies). A member in another group's turn right now is skipped: that turn has already replaced its
    copy folder with the other group's files. Never raises: the group's deletion goes on whatever happens here."""
    try:
        folder = group_files_dir(store, group['id']); aside = folder.parent / ('.deleting-' + ID())
        os.replace(str(folder), str(aside))
    except (OSError, ValueError, KeyError): return None  # no files, so no copies of them either
    members = [b for b in dict.fromkeys(group.get('botIds') or []) if isinstance(b, str)]
    locks = server.__dict__.setdefault('group_copy_locks', {}) if server is not None and hasattr(server, '__dict__') else {}
    def work():
        try:
            wanted = {}
            for entry in _plain_files(aside):
                try: wanted[entry.name] = (entry.stat(follow_symlinks=False).st_size, _file_hash(entry.path))
                except OSError: pass
            for bot_id in members:
                with store.lock: alive = bool(store.find('bots', bot_id))
                if not alive or not wanted: continue
                lock = locks.setdefault(bot_id, threading.Lock())
                if not lock.acquire(blocking=False): continue
                try:
                    fd = _open_copy_folder(store, bot_id)
                    if fd is None: continue
                    try:
                        for name, (size, digest) in wanted.items():
                            try:
                                mark = _same_copy(fd, name, size, digest)
                                now = os.stat(name, dir_fd=fd, follow_symlinks=False) if mark else None
                                if now and (now.st_dev, now.st_ino, now.st_mtime_ns, now.st_size) == mark: os.unlink(name, dir_fd=fd)  # not swapped meanwhile
                            except OSError: pass
                    finally: os.close(fd)
                except Exception: pass
                finally: lock.release()
        finally:
            shutil.rmtree(str(aside), ignore_errors=True)
            shutil.rmtree(str(group_text_root(store, group['id'])), ignore_errors=True)  # its text versions (checkread.py)
            for old in aside.parent.glob('.deleting-*'):  # left by an earlier deletion that Zook quit in the middle of
                try:
                    if old.is_dir() and not old.is_symlink() and time.time() - old.stat().st_mtime > 3600: shutil.rmtree(str(old), ignore_errors=True)
                except OSError: pass
    thread = threading.Thread(target=work, daemon=True, name='zook-group-drop'); thread.start()
    return thread


def forget_trashed_copies(store, gone):
    """Lock held. Bots that have left 已刪除的 Bot for good (#213): the group-files copy folder in each one's workspace is emptied.
    Zook empties and refills that folder at every group turn, so all of it is Zook's copy; the rest of the workspace stays."""
    alive = {b.get('id') for b in (store.data.get('bots') or []) + (store.data.get('deletedBots') or []) if isinstance(b, dict)}
    for bot in gone:
        bot_id = bot.get('id') if isinstance(bot, dict) else None
        if not bot_id or bot_id in alive: continue
        fd = _open_copy_folder(store, bot_id)
        if fd is None: continue
        try: clear_folder(fd)
        except OSError: pass
        finally: os.close(fd)


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


def sync_group_files_out(store, group_id, bot_name, bot_id, seen, kept=None):
    """Bring back what the Bot added or changed. A file someone else changed meanwhile is kept, and this version gets its own name.
    kept, when given, gets (the name the Bot saved, the shared file that already held the same content) for what was not saved twice,
    so the work still counts as handed in."""
    shared = group_files_dir(store, group_id); shared.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with bot_folder(store, bot_id) as workspace:
            attachments = os.open('attachments', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=workspace)
            try: folder_fd = os.open(GROUP_FILES_FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=attachments)
            finally: os.close(attachments)
    except OSError: return [], []
    saved, skipped, same = [], [], None
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
                    now = _file_hash(current) if os.path.lexists(str(current)) else None
                    if now is not None and now != seen.get(entry_name):
                        if now == digest:  # someone saved the very same file meanwhile: no second copy named after this Bot (#176)
                            if kept is not None: kept.append((_short_name(entry_name), name))
                            continue
                        name = free_group_file_name(shared, name, bot_name)
                    if now is None or name != _short_name(entry_name):  # a new file: one with the very same content already shared is not kept twice (#170)
                        same = {_file_hash(e.path): e.name for e in _plain_files(shared)}  # as the files are now: another member may have saved one meanwhile
                        if digest in same:
                            if kept is not None: kept.append((_short_name(entry_name), same[digest]))
                            continue
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
        if found.suffix.lower() in GROUP_TEXT_KINDS: return group_text_read(store, group_id, found.name)  # #240: Excel, Word, PowerPoint, PDF as their text version
        if found.stat().st_size > runtime.MAX_TEXT: raise RuntimeError('這個檔案超過 128 KB。謹慎模式讀不到，請把這個 Bot 的主動性改成自動後再試。')
        try: return {'name': args['name'], 'content': found.read_text(encoding='utf-8')}
        except UnicodeDecodeError: raise RuntimeError('這個檔案不是文字檔。謹慎模式讀不到，請把這個 Bot 的主動性改成自動後再試。')
    return (runtime._schema('zook_group_file_read', "Read a text file from this group's shared files by its exact name.", {'name': {'type': 'string', 'description': 'Exact file name'}}, ['name']), read, lambda args: 'always' if runtime.secret_name(args.get('name'), group_original(store, group_id, args.get('name'))) else False)  # keys and sign-ins, by the uploaded name too


# 謊報存檔 (#109): a member says it handed over a file that is neither among the group's files nor anywhere it named. Only what it
# named is checked; nothing is searched for.
import unicodedata

CLAIM_KINDS = ('xlsx', 'xls', 'csv', 'docx', 'doc', 'pptx', 'ppt', 'pdf', 'png', 'jpg', 'jpeg', 'md', 'txt', 'zip', 'json', 'html')
CLAIM_WORD = re.compile(r'[^\s/\\「」『』【】\[\]，、。：:；！？()（）*`\'"<>|]{1,120}\.(?:%s)(?![A-Za-z0-9])' % '|'.join(CLAIM_KINDS), re.I)
CLAIM_SAID = ('群組檔案', '共用檔案', '已存', '存到', '存在', '存好', '存成', '已完成', '交付', '產出')  # it says it made or saved something


def _claim_key(name):
    return unicodedata.normalize('NFC', str(name or '')).casefold()


def _claim_present(name, pool):
    """Whether a name a reply used is one of these files: the same, a longer name ending with it (「Q3 報表.xlsx」 read as 「報表.xlsx」),
    or the same with the mark Zook adds to a second version (報表（專員）.xlsx, 報表 (2).xlsx)."""
    want = _claim_key(name)
    for have in pool:
        key = _claim_key(have)
        if key.endswith(want) or re.sub(r'\s*[（(][^（）()]{0,40}[）)](?=\.[^.]+$)', '', key).endswith(want): return True
    return False


def claimed_missing(store, group_id, bot_id, text, given=()):
    """Lock not needed. Files the reply says it made that are not there: a full path that does not exist (and is not among the group's
    files by its name), or a bare name it said is in the group's files that is not there. Only when the reply says it saved or
    handed something over; a name is never searched for elsewhere."""
    text = str(text or '')[:20000]
    if not any(w in text for w in CLAIM_SAID): return []
    shared = [e.name for e in _plain_files(group_files_dir(store, group_id))]
    copies = group_copy_folder(store, bot_id)
    pool = shared + ([e.name for e in _plain_files(copies)] if copies.is_dir() else [])
    known = pool + [g for g in given if g]
    missing = []
    for path in named_paths(text):
        base = path.rsplit('/', 1)[-1]
        if not os.path.lexists(path) and not _claim_present(base, known) and base not in missing: missing.append(base)
    if '群組檔案' in text or '共用檔案' in text:
        for name in CLAIM_WORD.findall(re.sub(r'(?:file://)?/[^\s「」『』，、。；）)]+', ' ', text)):
            if not _claim_present(name, known) and name not in missing: missing.append(name)
    return missing[:10]


# #68①: a reply that says it looked at the pages as pictures (渲染、轉成圖片、逐頁預覽). Not 「逐頁檢查」 alone: reading the text page by
# page is a check too. Only a clause that does not say it was not done, and is not asking or suggesting it.
RENDER_CLAIM = re.compile(r'(?:逐頁|每一?頁|各頁|全部頁面|所有頁面|整份)[^。；;\n]{0,8}?(?:渲染|轉成?圖片?|轉圖|預覽|截圖)|(?:轉成?圖片|轉圖)[^。；;，,、\n]{0,6}?(?:檢查|確認|核對|看過|檢視)|已(?:轉成?圖|逐頁預覽|逐頁渲染)')
RENDER_NOT = re.compile(r'沒有|沒|未|無法|不能|不到|不曾|並非|尚未|還沒|請|建議|需要|要再|之後|下次|可以')  # before the claim, in its clause
RENDER_NOT_AFTER = re.compile(r'^[^。；;，,\n]{0,12}?(?:尚未|還沒|未完成|沒做|沒有做|沒辦法|無法|失敗)')  # 「逐頁渲染檢查尚未完成」
RENDER_REPORTS = ('codex', 'claude', 'cursor', 'grok', 'antigravity')  # the CLIs whose commands Zook reads from their output


def claimed_unrendered(text, calls, kind, others=()):
    """Whether a reply says it looked at its pages as pictures while none of its commands made a picture. False when the CLI does
    not report its commands to Zook (it cannot be told), the reply says nothing of the kind, or the clause names another member."""
    if kind not in RENDER_REPORTS: return False
    if any(c.get('rendered') and c.get('status') in ('completed', 'running') for c in calls or []): return False
    text = str(text or '')[:20000]
    for n, hit in enumerate(RENDER_CLAIM.finditer(text)):
        if n >= 20: break
        start = max(text.rfind(x, max(0, hit.start() - 200), hit.start()) for x in '。；;\n，,、！!？?') + 1
        clause = text[start:hit.end()]
        if RENDER_NOT.search(clause) or RENDER_NOT_AFTER.match(text[hit.end():hit.end() + 40]): continue
        if any(name and name in clause for name in others): continue  # what another member said it did (a host's merge), not this reply's own claim
        return True
    return False
