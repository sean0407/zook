# Backup settings (queue #232): on/off, how often, how many automatic copies to keep, where they go, a name for a copy made by
# hand, and copies that include files (attachments, group files, what Bots made in their workspaces). Also what a restore
# will lose (#50) and who is busy when it has to wait. Loaded by backend/server.py into one shared namespace, after upkeep.py.
import stat as _stat, zipfile as _zipfile

BACKUP_EVERY = {'daily': 1, 'weekly': 7}
BACKUP_KEEP_CHOICES = (3, 7, 14, 30, 60)
BACKUP_FILE_TOPS = ('uploads', 'group-files', 'workspaces', 'knowledge')  # knowledge: files added to 知識庫 (knowledge.py)
BACKUP_SUBFOLDER = 'Zook 備份'  # made inside the folder the user picked, so Zook never trims files of its own among theirs
BACKUP_SKIP_DIRS = {'node_modules', '__pycache__', 'venv'}  # and every hidden folder (.git, .claude, .ssh …): CLI sign-ins live there
# Names that look like keys or passwords are never copied. Passwords and API keys themselves are in the Keychain, which no backup reads.
BACKUP_SECRET = re.compile(r'(?i)^(\..*|.*\.(pem|key|p8|p12|pkcs12|pfx|crt|cer|der|ovpn|env|keychain|keychain-db|kdbx|ppk|gpg|asc|jks|keystore)|env\..*|id_(rsa|dsa|ecdsa|ed25519).*|service[-_]?account.*|credentials?(\..*)?|.*(secret|token|password|passwd|apikey|api_key|private[-_]?key).*)$')
BACKUP_POINTER = 'backup-folder.json'  # the chosen place, also beside the data: read before the data file is (startup recovery)
BACKUP_ENTRIES_MAX = 200000
LABEL_MAX = 40


def backup_files_limit():
    try: return max(1, int(os.environ.get('ZOOK_BACKUP_FILES_LIMIT') or 0)) if os.environ.get('ZOOK_BACKUP_FILES_LIMIT') else 1024 ** 3
    except ValueError: return 1024 ** 3


def backup_settings(store):
    data = getattr(store, 'data', None)  # not loaded yet while a damaged data file is being replaced
    settings = data.get('settings') if isinstance(data, dict) and isinstance(data.get('settings'), dict) else {}
    raw = dict(settings.get('backup')) if isinstance(settings.get('backup'), dict) else {}
    # The place is only in a file beside the data, which only the folder chooser writes: never in the data, so no copy, import
    # or sync carries it, and startup recovery finds it before the data is read.
    try: pointer = json.loads((store.dir / BACKUP_POINTER).read_text(encoding='utf-8'))
    except (OSError, ValueError): pointer = {}
    raw['folder'] = pointer.get('folder') if isinstance(pointer, dict) else ''
    return dict(auto=raw.get('auto') is not False, every=raw.get('every') if raw.get('every') in BACKUP_EVERY else 'daily',
                keep=raw.get('keep') if raw.get('keep') in BACKUP_KEEP_CHOICES and not isinstance(raw.get('keep'), bool) else 14,
                withFiles=raw.get('withFiles') is True, folder=raw.get('folder') if isinstance(raw.get('folder'), str) else '')


def backup_fields(data, body, changes):
    """PATCH /api/settings {backup: {...}}: only the choices the page offers. The place is never set here (see backup_folder_route)."""
    if 'backup' not in body: return
    value = body['backup']
    if not isinstance(value, dict) or not value or set(value) - {'auto', 'every', 'keep', 'withFiles'}: raise ValueError('備份設定無效。')
    for key in ('auto', 'withFiles'):
        if key in value and not isinstance(value[key], bool): raise ValueError('備份設定無效。')
    if 'every' in value and value['every'] not in BACKUP_EVERY: raise ValueError('備份頻率無效。')
    if 'keep' in value and (isinstance(value['keep'], bool) or value['keep'] not in BACKUP_KEEP_CHOICES): raise ValueError('保留份數無效。')
    now = data['settings'].get('backup') if isinstance(data['settings'].get('backup'), dict) else {}
    changes['backup'] = dict(now, **value)


def backup_home(store):
    folder = store.dir / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def backup_chosen(store):
    """The 「Zook 備份」 folder inside the folder the user picked, when it is there now (a drive may be unplugged)."""
    folder = backup_settings(store)['folder']
    if not folder or not os.path.isabs(folder) or not os.path.isdir(folder): return None
    sub = pathlib.Path(folder) / BACKUP_SUBFOLDER
    try:
        if sub.is_symlink(): return None
        sub.mkdir(mode=0o700, exist_ok=True)
        return sub if sub.is_dir() else None
    except OSError: return None


def backup_folders(store):
    """Every folder backups are listed from: the chosen one first, and Zook's own, which keeps the copies made before."""
    home = backup_home(store); chosen = backup_chosen(store)
    return [chosen, home] if chosen and chosen.resolve() != home.resolve() else [home]


def backup_path(store, name):
    """The backup file by its name, in whichever folder it is, or None."""
    if not isinstance(name, str) or not BACKUP_NAME.fullmatch(name): return None
    for folder in backup_folders(store):
        path = folder / name
        if path.is_file() and not path.is_symlink(): return path
    return None


def backup_stamp(name): return re.search(r'\d{8}-\d{6}', name).group(0)


def backup_labels(store):
    try: labels = json.loads((backup_home(store) / 'labels.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}
    return {k: v for k, v in labels.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(labels, dict) else {}


def backup_label_save(store, name='', label=''):
    """Lock held. Names given to backups, kept beside them in Zook's own folder; names of copies no longer there are dropped."""
    labels = backup_labels(store)
    if name and label: labels[name] = label
    alive = {x['name'] for x in backup_list(store)}
    if not backup_settings(store)['folder'] or backup_chosen(store):  # a chosen drive unplugged now: its names are kept
        labels = {k: v for k, v in labels.items() if k in alive}
    path = backup_home(store) / 'labels.json'; temp = path.with_name('.labels.tmp')
    try:
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(labels, f, ensure_ascii=False)
        os.replace(temp, path)
    except OSError: pass


def backup_label_clean(label):
    if label is None: return ''
    if not isinstance(label, str): raise ValueError('備份名稱無效。')
    label = ' '.join(label.split())
    if len(label) > LABEL_MAX: raise ValueError('備份名稱最多 %d 個字。' % LABEL_MAX)
    return label


def backup_keep(store, kind): return backup_settings(store)['keep'] if kind == 'auto' else BACKUP_KEEP[kind]


def backup_trim(store, kind):
    """Lock held. Drop the oldest copies of one kind, in every folder, beyond what is kept."""
    found = {}
    for folder in reversed(backup_folders(store)):
        for p in folder.glob('zook-%s-*' % kind):
            if BACKUP_NAME.fullmatch(p.name) and not p.is_symlink(): found[p.name] = p
    for old in sorted(found, key=backup_stamp)[:-backup_keep(store, kind)]:
        try: found[old].unlink()
        except OSError: pass


def backup_save(folder, name, fill):
    """Write one backup file: only this user can read it, and it appears whole or not at all."""
    for old in folder.glob('.backup-*'):  # left by a Zook that quit while writing
        try:
            if time.time() - old.stat().st_mtime > 86400: old.unlink()
        except OSError: pass
    fd, temp = tempfile.mkstemp(prefix='.backup-', dir=str(folder))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as raw:
            fill(raw); raw.flush(); os.fsync(raw.fileno())
        os.replace(temp, folder / name)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def backup_due(store):
    """Lock held. Whether an automatic copy is due now, as the settings say."""
    cfg = backup_settings(store)
    if not cfg['auto']: return False
    newest = max((backup_stamp(x['name']) for x in backup_list(store) if x['kind'] == 'auto'), default='')
    if not newest: return True
    try: then = datetime.datetime.strptime(newest, '%Y%m%d-%H%M%S')
    except ValueError: return True
    if cfg['every'] == 'daily': return then.date() < datetime.date.today()
    return datetime.datetime.now() - then >= datetime.timedelta(days=7)


def backup_make(store, kind, label=''):
    """Lock held. One backup as the settings say. With files it is written in the background; the result says so."""
    if not backup_settings(store)['withFiles']: return dict(name=backup_write(store, kind, store.data, label=label), pending=False)
    if store.__dict__.get('backup_running'): raise Busy('正在建立一份含檔案的備份，完成後再試。')
    raw = json.dumps(store.data, ensure_ascii=False).encode('utf-8', 'surrogatepass')
    name = 'zook-%s-%s.zip' % (kind, datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    store.__dict__['backup_running'] = dict(name=name, at=NOW())
    threading.Thread(target=backup_files_job, args=(store, kind, name, raw, label), daemon=True).start()
    return dict(name=name, pending=True)


def backup_file_list(store):
    """(name in the backup, full path) of every file a backup with files holds, and their total size. Symbolic links, hidden
    folders and files, and names that look like keys or passwords are left out."""
    out, total = [], 0
    for top in BACKUP_FILE_TOPS:
        base = store.dir / top
        if base.is_symlink() or not base.is_dir(): continue
        for here, dirs, files in os.walk(str(base)):
            dirs[:] = [d for d in dirs if d not in BACKUP_SKIP_DIRS and d != BACKUP_SUBFOLDER and not BACKUP_SECRET.match(d) and not os.path.islink(os.path.join(here, d))]
            for f in files:
                if BACKUP_SECRET.match(f): continue
                full = os.path.join(here, f)
                try: st = os.lstat(full)
                except OSError: continue
                if not _stat.S_ISREG(st.st_mode): continue
                out.append(('files/' + os.path.relpath(full, str(store.dir)).replace(os.sep, '/'), full)); total += st.st_size
    return out, total


def backup_files_size(store):
    """Lock held. About how big the files part is, for the page: counted in the background at most once a minute, never under the lock.
    0 until the first count is done."""
    seen = store.__dict__.get('backup_size_seen') or (-1e9, 0)
    if time.monotonic() - seen[0] >= 60 and not store.__dict__.get('backup_size_counting'):
        store.__dict__['backup_size_counting'] = True
        def count():
            try: size = backup_file_list(store)[1]
            except Exception: size = seen[1]
            store.__dict__['backup_size_seen'] = (time.monotonic(), size); store.__dict__['backup_size_counting'] = False
        threading.Thread(target=count, daemon=True).start()
        if seen[0] < 0:  # the very first look: wait briefly so the page has a number
            for _ in range(20):
                if not store.__dict__.get('backup_size_counting'): break
                time.sleep(0.05)
    now = store.__dict__.get('backup_size_seen') or seen
    return None if now[0] < 0 else now[1]  # None: still being counted


def backup_files_job(store, kind, name, raw, label):
    """Not under the lock. Writes the data and the files into one zip; when the files are over the limit, writes the data alone."""
    note = ''
    try:
        files, total = backup_file_list(store); limit = backup_files_limit()
        with store.lock: folder = backup_dir(store)
        if total > limit:
            name = name.replace('.zip', '.json.gz')
            backup_save(folder, name, lambda out: backup_gzip(out, raw))
            note = '檔案共 %s，超過 %s 的上限，這次只備份資料（Bot、對話、記憶、知識、排程與設定）。' % (backup_size_text(total), backup_size_text(limit))
        else:
            def fill(out):
                written = 0
                with _zipfile.ZipFile(out, 'w', _zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                    z.writestr('data.json', raw)
                    for arc, full in files:
                        try: fd = os.open(full, os.O_RDONLY | os.O_NOFOLLOW)
                        except OSError: continue
                        info = _zipfile.ZipInfo(arc, time.localtime(max(os.fstat(fd).st_mtime, 315532800 + 86400))[:6])  # a zip cannot hold a date before 1980
                        info.compress_type = _zipfile.ZIP_DEFLATED
                        with os.fdopen(fd, 'rb') as src, z.open(info, 'w', force_zip64=True) as dst:
                            while True:
                                chunk = src.read(1 << 20)
                                if not chunk: break
                                written += len(chunk)
                                if written > limit: raise OSError('檔案在備份時變大，超過上限。')
                                dst.write(chunk)
            backup_save(folder, name, fill)
        with store.lock:
            backup_trim(store, kind); backup_label_save(store, name, label)
            log_activity(store, 'backup', ('建立備份' if kind == 'manual' else '自動備份') + ('（含檔案）' if name.endswith('.zip') else '') + ('「%s」' % label if label else ''), by='' if kind == 'manual' else 'Zook')
    except Exception as exc:
        note = '含檔案的備份沒有完成（%s），資料沒有變動。' % str(exc)[:120]
    finally:
        with store.lock:
            store.__dict__['backup_running'] = None
            if note: backup_tell(store, note)


def backup_gzip(out, raw):
    with gzip.GzipFile(fileobj=out, mode='wb', compresslevel=6, mtime=0) as packed: packed.write(raw)


def backup_size_text(n): return '%.1f GB' % (n / 1024 ** 3) if n >= 1024 ** 3 else '%.1f MB' % (n / 1024 ** 2) if n >= 1024 ** 2 else '%d KB' % max(1, n // 1024)


def backup_tell(store, note):
    """Lock held. Something about a backup the user should know: in the activity record, as a notification, and on the page."""
    store.__dict__['backup_note'] = note
    log_activity(store, 'backup', note, by='Zook')
    app = getattr(store, 'notice_app', None)
    if app is not None: app.notify('備份', note, 'page', 'settings', '', always=True)


def backup_is_files(path): return path.name.endswith('.zip')


def backup_files_restore(store, path):
    """Not under the lock. Put back the files of a backup with files that are missing now. A file that is there is left as it is,
    and nothing is written outside the attachment, group file and workspace folders (no '..', no hidden names, no symbolic links)."""
    added = skipped = 0; budget = backup_files_limit() + (64 << 20)
    try:
        with _zipfile.ZipFile(str(path)) as z:
            for info in z.infolist()[:BACKUP_ENTRIES_MAX]:
                name = info.filename
                if not name.startswith('files/') or info.is_dir(): continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000: skipped += 1; continue
                parts = name[6:].split('/')
                if len(parts) < 2 or parts[0] not in BACKUP_FILE_TOPS or any(p in ('', '.', '..') or p.startswith('.') or '\\' in p or '\x00' in p for p in parts) or any(BACKUP_SECRET.match(p) for p in parts[1:]): skipped += 1; continue
                folder = backup_safe_dirs(store.dir, parts[:-1])
                if folder is None: skipped += 1; continue
                target = os.path.join(str(folder), parts[-1])
                try: fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                except FileExistsError: continue
                except OSError: skipped += 1; continue
                ok = False
                try:
                    with os.fdopen(fd, 'wb') as dst, z.open(info) as src:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk: break
                            budget -= len(chunk)
                            if budget < 0: raise OSError('too big')
                            dst.write(chunk)
                    ok = True; added += 1
                finally:
                    if not ok:
                        try: os.unlink(target)
                        except OSError: pass
        note = '還原時補回 %d 個檔案（現有的檔案沒有覆蓋）。' % added + ('有 %d 個檔案因為位置不安全而略過。' % skipped if skipped else '')
    except Exception:
        note = '還原時補回了 %d 個檔案，其餘的檔案無法讀取。資料已經還原。' % added
    with store.lock:
        store.__dict__['backup_restoring'] = None
        backup_tell(store, note)
    knowledge_requeue(store)  # files that were being read when the copy was made, now that they are back


def backup_safe_dirs(root, parts):
    """The folder root/parts, made one level at a time; None when any level is a symbolic link or not a folder."""
    here = root
    for part in parts:
        here = here / part
        if here.is_symlink(): return None
        if not here.exists():
            try: here.mkdir(mode=0o700)
            except FileExistsError: pass
            except OSError: return None
        if here.is_symlink() or not here.is_dir(): return None
    real, base = os.path.realpath(str(here)), os.path.realpath(str(root / parts[0]))
    return here if real == base or real.startswith(base + os.sep) else None


def backup_busy(store):
    """Lock held. What is answering now, by name: a group as a whole, and each Bot replying outside a running group."""
    groups = [g for g in store.data['groups'] if g.get('status') == 'running']
    in_group = {g['id'] for g in groups}
    out = [dict(type='group', id=g['id'], name=str(g.get('name') or '未命名群組')) for g in groups]
    for job in store.data['jobs']:
        if job.get('status') != 'running' or job.get('groupId') in in_group: continue
        bot = store.find('bots', job.get('botId'))
        out.append(dict(type='bot', id=job['id'], name=str((bot or {}).get('name') or '已刪除的 Bot'), group=str((store.find('groups', job.get('groupId')) or {}).get('name') or '')))
    return out


def backup_stop_busy(app, store):
    """Lock held. 停止後還原 (#50): stop every group and reply that is answering, in the same hold of the lock as the restore itself,
    so a message waiting behind a stopped reply cannot start in between. Returns who was stopped."""
    busy = backup_busy(store)
    for x in busy:
        if x['type'] == 'group': group_stop_now(app, store, store.find('groups', x['id']))
        else: app.cancel_job(store.find('jobs', x['id']))
    return busy


def backup_busy_text(busy):
    names = '、'.join(('群組「%s」' if x['type'] == 'group' else 'Bot「%s」') % x['name'] for x in busy[:5]) + ('等 %d 個' % len(busy) if len(busy) > 5 else '')
    return '%s正在回覆，等它結束再還原，或按「停止後還原」。' % names


def backup_counts(data):
    bots = [b for b in data.get('bots') or [] if isinstance(b, dict)]
    return dict(bots=len(bots), groups=len(data.get('groups') or []), chats=sum(len(b.get('chats') or []) or 1 for b in bots),
                memories=len(data.get('memories') or []), knowledge=len(data.get('knowledge') or []), schedules=len(data.get('schedules') or []))


def backup_preview(store, name):
    """Lock held. What restoring this copy changes: what is there now and would be gone, what comes back, and who is busy."""
    path = backup_path(store, name)
    if not path: raise LookupError('找不到這份備份。')
    if backup_too_big(path): raise ValueError('備份檔太大。')
    try: old = backup_check(backup_read(path))
    except (OSError, EOFError, UnicodeError, RecursionError, KeyError, _zipfile.BadZipFile): raise ValueError('這份備份無法讀取。')
    now = store.data
    old_bots, old_groups = {b['id'] for b in old['bots']}, {g['id'] for g in old.get('groups') or []}
    old_chats = {key: {m.get('id') for m in messages} for key, _, messages, _ in chat_conversations(old)}
    live = {b['id'] for b in now['bots']} | {g['id'] for g in now['groups']}
    lost_chats = lost_messages = 0
    for key, _, messages, _ in chat_conversations(now):
        if key[0] not in live: continue  # a deleted Bot's conversations are not shown anyway
        if key not in old_chats: lost_chats += 1 if messages or key[1] else 0; lost_messages += len(messages)
        else: lost_messages += sum(1 for m in messages if m.get('id') not in old_chats[key])
    here_bots = {b['id'] for b in now['bots']}
    return dict(name=name, label=backup_labels(store).get(name, ''), hasFiles=backup_is_files(path), backup=backup_counts(old), now=backup_counts(now),
                lost=dict(bots=[b['name'] for b in now['bots'] if b['id'] not in old_bots], groups=[str(g.get('name') or '') for g in now['groups'] if g['id'] not in old_groups],
                          chats=lost_chats, messages=lost_messages, memories=len({m.get('id') for m in now.get('memories') or []} - {m.get('id') for m in old.get('memories') or []})),
                back=[b['name'] for b in old['bots'] if b['id'] not in here_bots], busy=backup_busy(store), syncOn=bool((now.get('sync') or {}).get('folder')))


def backup_too_big(path):
    """A plain backup over the size limit, or a backup with files whose data part is."""
    try:
        if not backup_is_files(path): return path.stat().st_size > MAX_BACKUP_FILE
        with _zipfile.ZipFile(str(path)) as z: return z.getinfo('data.json').file_size > 8 * MAX_BACKUP_FILE
    except (OSError, KeyError, _zipfile.BadZipFile): return True


def backup_view(store):
    """Lock held. GET /api/backups."""
    cfg = backup_settings(store); home = backup_home(store); chosen = backup_chosen(store)
    labels = backup_labels(store)
    items = [dict(x, label=labels.get(x['name'], ''), hasFiles=x['name'].endswith('.zip')) for x in backup_list(store)]
    running = store.__dict__.get('backup_running')
    return dict(items=items, running=running, restoring=bool(store.__dict__.get('backup_restoring')), lastNote=store.__dict__.get('backup_note') or '',
                filesSize=backup_files_size(store), filesLimit=backup_files_limit(), choices=dict(keep=list(BACKUP_KEEP_CHOICES), every=list(BACKUP_EVERY)),
                settings=dict(auto=cfg['auto'], every=cfg['every'], keep=cfg['keep'], withFiles=cfg['withFiles'], folder=str((chosen or home).resolve()),
                              isDefault=not cfg['folder'], missing=bool(cfg['folder'] and not chosen)))


def backup_unlocked(handler, store, parts):
    """Requests that must not hold the lock while they wait: the Mac's folder chooser. Returns True when it answered."""
    if parts[:3] != ['api', 'backups', 'folder'] or len(parts) != 3 or handler.command != 'POST': return False
    if handler.device: handler.error(403, '這項功能只能在 Mac 上使用。'); return True
    body = handler.body()
    if body.get('reset') is True: chosen = ''
    elif body.get('choose') is True and set(body) == {'choose'}:
        try:
            done = subprocess.run(['/usr/bin/osascript', '-e', 'tell me to activate', '-e', 'POSIX path of (choose folder with prompt "選擇備份要存放的資料夾")'], capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired: handler.respond(200, dict(changed=False)); return True
        picked = done.stdout.strip() if done.returncode == 0 else ''
        if not picked or not os.path.isdir(picked): handler.respond(200, dict(changed=False)); return True
        chosen = os.path.realpath(picked)
        inside = [os.path.realpath(str(store.dir / t)) for t in BACKUP_FILE_TOPS]
        if any(chosen == t or chosen.startswith(t + os.sep) for t in inside): handler.error(400, '這個資料夾在 Zook 的檔案裡，備份會越包越大，請換一個。'); return True
    else: handler.error(400, '請用「選擇資料夾」挑選備份位置。'); return True
    with store.lock:
        before = backup_settings(store)['folder']
        backup_pointer_save(store, chosen)
        if chosen and not backup_chosen(store):
            backup_pointer_save(store, before); handler.error(400, '這個資料夾無法寫入，請換一個。'); return True
        log_activity(store, 'setting', '變更設定：備份位置（%s）' % (chosen or '預設位置'))
        handler.respond(200, dict(backup_view(store), changed=True))
    return True


def backup_route(handler, store, parts, path):
    """Lock held. The backup requests beyond list and delete. Returns True when it answered."""
    method, n = handler.command, len(parts)
    if path == '/api/backups' and method == 'GET': handler.respond(200, backup_view(store)); return True
    if path == '/api/backups' and method == 'POST':
        label = backup_label_clean(handler.body().get('label'))
        try: made = backup_make(store, 'manual', label)
        except Busy as exc: handler.error(409, str(exc)); return True
        if not made['pending']:
            backup_label_save(store, made['name'], label); log_activity(store, 'backup', '建立備份' + ('「%s」' % label if label else ''))
        handler.respond(202 if made['pending'] else 201, dict(backup_view(store), name=made['name'], pending=made['pending'])); return True
    if path == '/api/backups/reveal' and method == 'POST':
        folder = backup_chosen(store) or backup_home(store)
        subprocess.run(['/usr/bin/open', str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        handler.respond(200, dict(ok=True)); return True
    if n == 4 and parts[3] == 'preview' and method == 'GET':
        try: handler.respond(200, backup_preview(store, parts[2])); return True
        except LookupError as exc: handler.error(404, str(exc)); return True
    return False


def backup_pointer_save(store, folder):
    """The chosen place beside the data file, for startup recovery before the data is read. Only the folder chooser writes it."""
    path = store.dir / BACKUP_POINTER
    try:
        if not folder: path.unlink(); return
        temp = path.with_name('.' + BACKUP_POINTER + '.tmp')
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(dict(folder=folder), f, ensure_ascii=False)
        os.replace(temp, path)
    except OSError: pass
