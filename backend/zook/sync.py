# Keeping several Macs alike through a folder they all see (for example iCloud Drive).
# Each Mac writes one file of its own there and reads the others'. Newer wins, item by item.
# Synced: Bots (who they are), their conversations, knowledge, memories, the shared rules and the sidebar groups.
# Never synced: passwords and keys, sign-ins, connectors, permissions and access (主動性, 存取範圍), schedules, group chats, files.
# Loaded by backend/server.py into one shared namespace.
SYNC_EVERY = 30
SYNC_FILE = re.compile(r'zook-sync-([0-9a-f]{16})\.json')
MAX_SYNC_FILE = 100 * 1024 * 1024
SYNC_BOT_TEXT = {'name': 100, 'color': 30, 'shape': 30, 'instructions': 10000, 'persona': 20000, 'provider': 20, 'model': 100, 'section': 100}
SYNC_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
SYNC_PROVIDERS = ('', 'auto', 'codex', 'claude', 'grok', 'antigravity', 'gemini')  # the same on every Mac; custom ones are not
SYNC_MESSAGE_TEXT = {'createdAt': 40, 'status': 20, 'note': 300, 'auto': 100, 'autoWhy': 300, 'effort': 20, 'author': 100}
_sync_unwritten = set()
_sync_lock = threading.Lock()


def sync_state(store):
    state = store.data.setdefault('sync', {})
    if not SYNC_ID.fullmatch(str(state.get('deviceId') or '')) or len(state['deviceId']) != 16: state['deviceId'] = secrets.token_hex(8)
    state.setdefault('deviceName', (socket.gethostname() or 'Mac').split('.')[0][:40])
    return state


# What this Mac remembers about each item is kept beside the data, not in it: it is bookkeeping, and the window never needs it.
_marks = {}


def sync_marks(store, reset=False):
    path = store.dir / 'sync-marks.json'
    if reset or str(path) not in _marks:
        marks = {}
        if not reset:
            try: marks = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError): marks = {}
        ok = isinstance(marks, dict) and all(isinstance(marks.get(k), dict) for k in ('stamps', 'tombs')) and all(isinstance(v, list) and len(v) == 4 and isinstance(v[3], list) for v in marks['stamps'].values())
        _marks[str(path)] = marks if ok else dict(stamps={}, tombs={})
        if reset: sync_marks_save(store)
    return _marks[str(path)]


def sync_marks_save(store):
    path = store.dir / 'sync-marks.json'
    fd, temp = tempfile.mkstemp(prefix='.sync-marks-', dir=str(store.dir))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(_marks[str(path)], f)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def _digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def _busy_bots(store):
    return {j['botId'] for j in store.data['jobs'] if j['status'] == 'running'}


def sync_items(store):
    """Lock held. Everything this Mac shares, as {key: value}. A Bot that is answering right now is left out until it is done."""
    items, busy = {}, _busy_bots(store)
    for bot in store.data['bots']:
        if bot['id'] in busy: continue
        ensure_chats(bot)
        value = {k: bot.get(k) or '' for k in SYNC_BOT_TEXT}
        value.update(pinned=bool(bot.get('pinned')), createdAt=bot.get('createdAt') or '')
        if value['provider'] not in SYNC_PROVIDERS: value.update(provider='', model='')  # a model set up only on this Mac stays here
        items['bots:' + bot['id']] = value
        for chat in bot['chats']:
            messages = bot['messages'] if chat['id'] == bot['chatId'] else chat.get('messages') or []
            if not messages and chat.get('kind') != 'schedule': continue  # an empty new conversation is not worth sending around
            items['chats:%s:%s' % (bot['id'], chat['id'])] = dict(title=chat.get('title') or '', kind=chat.get('kind') or '', createdAt=chat.get('createdAt') or '', updatedAt=chat.get('updatedAt') or '',
                                                                 messages=[m for m in messages if m.get('status') != 'running'])
    for note in store.data['knowledge']:
        items['knowledge:' + note['id']] = {k: note.get(k) for k in ('title', 'content', 'botId', 'tags', 'createdAt', 'updatedAt') if note.get(k) is not None}
    for memory in store.data.get('memories') or []:
        items['memories:' + memory['id']] = {k: memory.get(k) for k in ('content', 'botId', 'createdBy', 'createdAt') if memory.get(k) is not None}
    settings = store.data['settings']
    items['settings:shared'] = dict(rules=settings.get('rules') or '', sections=list(settings.get('sections') or []))
    # What is sent is what would be accepted: both sides then agree on every item, byte for byte.
    return {key: clean for key, clean in ((key, sync_clean(key, value)) for key, value in items.items()) if clean is not None}


def _text(value, limit): return isinstance(value, str) and len(value) <= limit


def sync_clean(key, value):
    """A value read from another Mac's file, reduced to what Zook accepts, or None. The folder is the user's, but the file is still only data."""
    parts = key.split(':')
    if not isinstance(value, dict) or any(not SYNC_ID.fullmatch(p) for p in parts[1:]): return None
    if parts[0] == 'bots' and len(parts) == 2:
        if any(not _text(value.get(k, ''), limit) for k, limit in SYNC_BOT_TEXT.items()) or not str(value.get('name') or '').strip(): return None
        out = {k: value.get(k, '') for k in SYNC_BOT_TEXT}
        out.update(pinned=value.get('pinned') is True, createdAt=value.get('createdAt') if _text(value.get('createdAt'), 40) else '')
        if out['provider'] not in SYNC_PROVIDERS: out.update(provider='', model='')
        return out
    if parts[0] == 'chats' and len(parts) == 3:
        messages = value.get('messages')
        if not isinstance(messages, list) or len(messages) > 5000 or not _text(value.get('title', ''), 200) or value.get('kind', '') not in ('', 'schedule'): return None
        kept = []
        for m in messages:
            if not isinstance(m, dict) or not SYNC_ID.fullmatch(str(m.get('id') or '')) or m.get('role') not in ('user', 'assistant') or not _text(m.get('content'), 400000): return None
            if m.get('status') == 'running': continue
            one = dict(id=m['id'], role=m['role'], content=m['content'])
            for k, limit in SYNC_MESSAGE_TEXT.items():
                if k in m and m[k] is not None:
                    if not _text(m[k], limit): return None
                    one[k] = m[k]
            for k in ('plan', 'long'):
                if m.get(k) is True: one[k] = True
            if m.get('attachments'):
                files = m['attachments']
                if not isinstance(files, list) or len(files) > 20: return None
                one['attachments'] = []
                for a in files:
                    if not isinstance(a, dict) or not SYNC_ID.fullmatch(str(a.get('id') or '')) or not _text(a.get('name'), 300) or not _text(a.get('kind', ''), 20): return None
                    size = a.get('size')
                    one['attachments'].append(dict(id=a['id'], name=a['name'], kind=a.get('kind', ''), size=size if type(size) is int and 0 <= size < 10 ** 12 else 0))
            kept.append(one)
        return dict(title=value.get('title', ''), kind=value.get('kind', ''), createdAt=str(value.get('createdAt') or '')[:40], updatedAt=str(value.get('updatedAt') or '')[:40], messages=kept)
    if parts[0] == 'knowledge' and len(parts) == 2:
        tags = value.get('tags', [])
        if not _text(value.get('title'), 300) or not _text(value.get('content'), 100000) or not _text(value.get('botId', ''), 100): return None
        if not isinstance(tags, list) or len(tags) > 30 or any(not _text(t, 100) for t in tags): return None
        return dict(title=value['title'], content=value['content'], botId=value.get('botId', ''), tags=tags, createdAt=str(value.get('createdAt') or '')[:40], updatedAt=str(value.get('updatedAt') or '')[:40])
    if parts[0] == 'memories' and len(parts) == 2:
        if not _text(value.get('content'), 5000) or not _text(value.get('botId', ''), 100) or not _text(value.get('createdBy', ''), 100): return None
        return dict(content=value['content'], botId=value.get('botId', ''), createdBy=value.get('createdBy', ''), createdAt=str(value.get('createdAt') or '')[:40])
    if key == 'settings:shared':
        sections = value.get('sections', [])
        if not _text(value.get('rules', ''), 10000) or not isinstance(sections, list) or len(sections) > 200 or any(not _text(s, 100) for s in sections): return None
        return dict(rules=value.get('rules', ''), sections=sections)
    return None


def sync_drop_bot(store, bot):
    """Lock held. Remove a Bot the same way the window does: its group seats and schedules go, its knowledge becomes shared."""
    for group in store.data['groups']:
        if bot['id'] in group['botIds']:
            was_host = group_host(store, group) == bot['id']
            group['botIds'].remove(bot['id'])
            if was_host: drop_group_host(store, group)
    store.data['schedules'][:] = [x for x in store.data['schedules'] if x.get('botId') != bot['id']]
    for note in store.data['knowledge']:
        if note.get('botId') == bot['id']: note['botId'] = ''
    store.data['bots'].remove(bot)


def sync_put(store, key, value, gone=()):
    """Lock held. Write one accepted value into this Mac's data. Returns False when it cannot be applied yet."""
    parts = key.split(':'); busy = _busy_bots(store)
    if parts[0] == 'bots':
        bot = store.find('bots', parts[1])
        if bot and bot['id'] in busy: return False
        if not bot:
            bot = dict(id=parts[1], messages=[], chats=[], chatId=None, enabledSkills=[], enabledMcp=[], allowCommands=True, webSearch=False)
            store.data['bots'].append(bot)
        if not value['provider'] and bot.get('provider') and bot['provider'] not in SYNC_PROVIDERS: value = dict(value, provider=bot['provider'], model=bot.get('model') or '')  # this Mac's own model for it stays
        bot.setdefault('isAdmin', False)  # who the 管理員 is, is decided on each Mac, never by a file
        bot.update(value)
        if bot.get('section') and not bot.get('pinned') and bot['section'] not in store.data['settings'].get('sections', []): store.data['settings'].setdefault('sections', []).append(bot['section'])
        return True
    if parts[0] == 'chats':
        bot = store.find('bots', parts[1])
        if not bot or bot['id'] in busy: return False
        chats = bot.setdefault('chats', [])
        chat = next((c for c in chats if c['id'] == parts[2]), None)
        if not chat:
            chat = dict(id=parts[2], messages=[]); chats.append(chat)
        chat.update(title=value['title'], createdAt=value['createdAt'] or NOW(), updatedAt=value['updatedAt'] or NOW())
        if value['kind']: chat['kind'] = value['kind']
        if bot.get('chatId') == chat['id']: bot['messages'] = value['messages']; chat.pop('messages', None)
        else: chat['messages'] = value['messages']
        if not any(c['id'] == bot.get('chatId') for c in chats):  # a Bot that just arrived opens on its newest conversation
            newest = max((c for c in chats if c.get('kind') != 'schedule'), key=lambda c: c.get('updatedAt') or '', default=None)
            if newest: bot['chatId'] = newest['id']; bot['messages'] = newest.pop('messages', None) or []
        return True
    if parts[0] in ('knowledge', 'memories'):
        if value.get('botId') and not store.find('bots', value['botId']):
            if 'bots:' + value['botId'] not in gone: return False  # its Bot has not arrived yet
            value = dict(value, botId='')
        items = store.data.setdefault(parts[0], [])
        found = next((x for x in items if x['id'] == parts[1]), None)
        if found: found.update(value)
        else: items.append(dict(value, id=parts[1]))
        return True
    if key == 'settings:shared':
        settings = store.data['settings']
        settings['rules'] = value['rules']
        settings['sections'] = list(dict.fromkeys(value['sections'] + [s for s in settings.get('sections') or [] if s not in value['sections']]))
        return True
    return False


def sync_remove(store, key):
    """Lock held. Apply a deletion made on another Mac. Returns False when it has to wait."""
    parts = key.split(':'); busy = _busy_bots(store)
    if parts[0] == 'bots':
        bot = store.find('bots', parts[1])
        if not bot: return True
        if bot['id'] in busy or any(g['status'] == 'running' and bot['id'] in g['botIds'] for g in store.data['groups']): return False
        sync_drop_bot(store, bot); return True
    if parts[0] == 'chats':
        bot = store.find('bots', parts[1])
        if not bot: return True
        if bot['id'] in busy: return False
        if bot.get('chatId') == parts[2]: bot['messages'] = []
        bot['chats'] = [c for c in bot.get('chats') or [] if c['id'] != parts[2]]
        if not any(c['id'] == bot.get('chatId') for c in bot['chats']):
            rest = [c for c in bot['chats'] if c.get('kind') != 'schedule']
            if rest: bot['chatId'] = rest[-1]['id']; bot['messages'] = rest[-1].pop('messages', None) or []
            else: bot['messages'] = []; ensure_chats(bot)
        return True
    if parts[0] in ('knowledge', 'memories'):
        store.data[parts[0]] = [x for x in store.data.get(parts[0]) or [] if x['id'] != parts[1]]
        return True
    return True


def sync_read_others(folder, own):
    """Other Macs' files: [(device, items, tombs)]. A file that is too big or broken is skipped, never trusted halfway."""
    out = []
    try: names = sorted(os.listdir(folder))
    except OSError: raise RuntimeError('找不到同步資料夾。')
    for name in names:
        match = SYNC_FILE.fullmatch(name)
        if not match or match.group(1) == own: continue
        path = os.path.join(folder, name)
        try:
            if os.path.islink(path) or os.path.getsize(path) > MAX_SYNC_FILE: continue
            with open(path, encoding='utf-8') as f: data = json.load(f)
        except (OSError, ValueError, RecursionError, MemoryError): continue
        if not isinstance(data, dict) or data.get('format') != 1 or not isinstance(data.get('items'), dict) or not isinstance(data.get('tombs', {}), dict): continue
        device = data.get('device') if isinstance(data.get('device'), dict) else {}
        out.append((dict(id=match.group(1), name=str(device.get('name') or 'Mac')[:40], at=str(data.get('at') or '')[:40]), data['items'], data.get('tombs') or {}))
    return out


def _stamp_ok(entry): return isinstance(entry, dict) and isinstance(entry.get('t'), (int, float)) and not isinstance(entry.get('t'), bool) and 0 < entry['t'] < time.time() + 86400


def _history(value): return [x for x in value if isinstance(x, str) and re.fullmatch(r'[0-9a-f]{24}', x)][-20:] if isinstance(value, list) else []


def sync_pass(app):
    """One round: note what changed here, take what is newer elsewhere, then write this Mac's file. Returns what happened.

    For every item this Mac remembers [digest, when it changed, whether this Mac made that version, the versions it grew from].
    A conversation both Macs wrote in is found by that last list: the newer one wins and the older one is kept as a copy."""
    store = app.store
    with _sync_lock:
        with store.lock:
            state = sync_state(store); folder = state.get('folder')
            if not folder: return dict(on=False)
            own = state['deviceId']
        try:
            if not os.path.isdir(folder): raise RuntimeError('找不到同步資料夾。')
            others = sync_read_others(folder, own)
        except RuntimeError as exc:
            with store.lock:
                if state.get('lastError') != str(exc): state['lastError'] = str(exc); store.save()
            return dict(on=True, error=str(exc))
        now, took, conflicts = time.time(), 0, 0
        with store.lock:
            if state.get('folder') != folder: return dict(on=bool(state.get('folder')))  # switched off or moved meanwhile
            marks = sync_marks(store); stamps, tombs = marks['stamps'], marks['tombs']
            before = _digest([stamps, tombs])
            joining = not stamps  # first round on this Mac: where both sides have the same item, the folder's version is taken
            local = sync_items(store); busy = _busy_bots(store)
            waiting = lambda key: key.split(':')[0] in ('bots', 'chats') and key.split(':')[1] in busy
            # 1. What changed on this Mac since the last round.
            for key, value in local.items():
                digest, old = _digest(value), stamps.get(key)
                if not old or old[0] != digest:
                    # Never earlier than the version it replaces, even if that one came from a Mac whose clock runs ahead.
                    stamps[key] = [digest, 0 if joining else max(now, old[1] + 0.001 if old else 0), not joining, ((old[3] + [old[0]]) if old else [])[-20:]]; tombs.pop(key, None)
            for key in [k for k in stamps if k not in local and not waiting(k)]:
                tombs[key] = max(now, stamps.pop(key)[1] + 0.001)
            # 2. What is newer on the other Macs.
            for device, items, gone in others:
                for key, when in ({} if joining else gone).items():  # a Mac that is joining keeps what it has
                    if not isinstance(key, str) or len(key) > 200 or not isinstance(when, (int, float)) or isinstance(when, bool) or not 0 < when < now + 86400: continue
                    if key in stamps:
                        if when <= stamps[key][1] or not sync_remove(store, key): continue
                        stamps.pop(key); took += 1
                    tombs[key] = max(tombs.get(key, 0), when)
                for key in sorted((k for k in items if isinstance(k, str) and len(k) <= 200), key=lambda k: (not k.startswith('bots:'), k)):  # Bots before their conversations
                    entry = items[key]
                    if not _stamp_ok(entry): continue
                    mine = stamps.get(key)
                    if entry['t'] <= max(mine[1] if mine else -1, tombs.get(key, -1)): continue
                    value = sync_clean(key, entry.get('v'))
                    if value is None: continue
                    if joining and key == 'settings:shared' and not value['rules'] and key in local: value = dict(value, rules=local[key]['rules'])
                    digest, history = _digest(value), _history(entry.get('p'))
                    if mine and mine[0] == digest: stamps[key] = [digest, entry['t'], False, history]; continue
                    theirs = {m['id'] for m in value['messages']} if key.startswith('chats:') else set()
                    if key.startswith('chats:') and mine and (joining or (mine[2] and mine[0] not in history)) and key in local and any(m['id'] not in theirs for m in local[key]['messages']):
                        # Both Macs wrote in this conversation. The other one is newer and wins; this Mac's version is kept as a copy.
                        bot = store.find('bots', key.split(':')[1])
                        if not bot or bot['id'] in busy: continue
                        bot['chats'].append(dict(id=ID(), title=((local[key]['title'] or '對話') + '（這台 Mac 的版本）')[:200], createdAt=NOW(), updatedAt=NOW(), messages=copy.deepcopy(local[key]['messages'])))
                        conflicts += 1
                    if sync_put(store, key, value, tombs):
                        stamps[key] = [digest, entry['t'], False, history]; tombs.pop(key, None); took += 1
            if joining and not any(b.get('isAdmin') for b in store.data['bots']):  # every Mac keeps one 管理員, chosen the way a new workspace chooses it
                for b in store.data['bots']:
                    if b.get('name') == '管理員': b['isAdmin'] = True; break
            # 3. This Mac's file: everything it has, with when each item last changed.
            final = sync_items(store)
            for key, value in final.items():
                digest, old = _digest(value), stamps.get(key)
                if not old or old[0] != digest: stamps[key] = [digest, max(now, old[1] + 0.001 if old else 0), True, ((old[3] + [old[0]]) if old else [])[-20:]]  # what taking the others' changes made here
                elif old[1] == 0: old[1] = now
            for key in list(tombs):
                if now - tombs[key] > 180 * 86400: tombs.pop(key)  # a Mac that has been away for half a year starts over
            payload = dict(format=1, device=dict(id=own, name=state['deviceName']), at=NOW(),
                           items={k: dict(t=stamps[k][1], h=stamps[k][0], p=stamps[k][3], v=v) for k, v in final.items()}, tombs=dict(tombs))
            changed = _digest([stamps, tombs]) != before
            if changed: sync_marks_save(store)
            names = [d for d, _, _ in others]
            if took or conflicts or state.get('lastError') or names != state.get('others'):
                state.update(lastAt=NOW(), lastError='', others=names); store.save()
            else: state['lastAt'] = NOW()  # nothing to write down: the time is only shown
        target = os.path.join(folder, 'zook-sync-%s.json' % own)
        if changed or took or folder in _sync_unwritten or not os.path.exists(target):
            try:
                fd, temp = tempfile.mkstemp(prefix='.zook-sync-', dir=folder)
                try:
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(payload, f, ensure_ascii=False)
                    os.replace(temp, target); _sync_unwritten.discard(folder)
                finally:
                    if os.path.exists(temp): os.unlink(temp)
            except OSError:
                _sync_unwritten.add(folder)  # written on the next round, whether or not anything else changes
                with store.lock: state['lastError'] = '寫不進同步資料夾。'; store.save()
                return dict(on=True, error='寫不進同步資料夾。')
        if conflicts: log_activity(store, 'backup', '同步時有 %d 個對話兩台都改過，這台的版本另存成副本' % conflicts, by='Zook')
        return dict(on=True, took=took, conflicts=conflicts)


def sync_view(store):
    with store.lock:
        state = sync_state(store)
        return dict(on=bool(state.get('folder')), folder=state.get('folder') or '', deviceName=state['deviceName'], lastAt=state.get('lastAt') or '', lastError=state.get('lastError') or '', others=list(state.get('others') or []))


def sync_route(handler, store, parts, path):
    """Only this Mac may set up or stop syncing. Lock NOT held: a round reads and writes files."""
    if handler.device: return handler.error(403, '這項功能只能在 Mac 上使用。')
    method = handler.command
    if path == '/api/sync' and method == 'GET': return handler.respond(200, sync_view(store))
    if path == '/api/sync/now' and method == 'POST':
        handler.body(); sync_pass(handler.server)
        return handler.respond(200, sync_view(store))
    if path == '/api/sync/check' and method == 'POST':
        folder = sync_folder(handler.body().get('folder'))
        with store.lock: own = sync_state(store)['deviceId']
        return handler.respond(200, dict(folder=folder, others=[d for d, _, _ in sync_read_others(folder, own)]))
    if path == '/api/sync' and method == 'POST':
        body = handler.body(); folder = sync_folder(body.get('folder'))
        if body.get('join', 'merge') not in ('merge', 'replace'): raise ValueError('合併方式無效。')
        replace = body.get('join') == 'replace'
        with store.lock:
            if replace:
                if any(j['status'] == 'running' for j in store.data['jobs']) or any(g.get('status') == 'running' for g in store.data['groups']): return handler.error(409, '有 Bot 正在回覆，等它結束再開始同步。')
                own = sync_state(store)['deviceId']
                if not sync_read_others(folder, own): raise ValueError('這個資料夾裡還沒有其他 Mac 的資料，無法取代。')
            backup_write(store, 'safety', store.data)  # what was here can be put back from 備份與還原
            state = sync_state(store)
            state.update(folder=folder, lastError='', lastAt=''); sync_marks(store, reset=True)
            if replace:
                # This Mac's own Bots, knowledge and memories make way; nothing is reported as deleted to the others.
                for bot in list(store.data['bots']): sync_drop_bot(store, bot)
                store.data['knowledge'] = []; store.data['memories'] = []
            store.save()
        log_activity(store, 'backup', '開始同步（%s）' % ('換成同步資料夾的內容' if replace else '合併'))
        sync_pass(handler.server)
        return handler.respond(200, sync_view(store))
    if path == '/api/sync' and method == 'DELETE':
        with store.lock:
            state = sync_state(store); folder, own = state.get('folder'), state['deviceId']
            state.update(folder='', others=[], lastError=''); sync_marks(store, reset=True); store.save()
        if folder:
            try: os.unlink(os.path.join(folder, 'zook-sync-%s.json' % own))
            except OSError: pass
        log_activity(store, 'backup', '停止同步')
        return handler.respond(200, sync_view(store))
    return handler.error(404, '找不到資源。')


def sync_folder(folder):
    if not isinstance(folder, str) or len(folder) > 1000: raise ValueError('資料夾無效。')
    chosen = pathlib.Path(folder.strip()).expanduser()
    if not folder.strip() or not chosen.is_absolute() or not chosen.is_dir(): raise ValueError('請選擇一個存在的資料夾。')
    return str(chosen.resolve())


class Syncing:
    """Mixed into App: a round every half minute while a folder is set."""
    def sync_tick(self):
        last = self.__dict__.get('sync_last', 0)
        if time.time() - last < float(os.environ.get('ZOOK_SYNC_EVERY') or SYNC_EVERY): return
        self.sync_last = time.time()
        with self.store.lock: on = bool((self.store.data.get('sync') or {}).get('folder'))
        if on: sync_pass(self)
