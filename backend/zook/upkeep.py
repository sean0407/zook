# Looking after the data: backups, the activity record, monthly usage budgets and the rules every Bot follows.
# Loaded by backend/server.py into one shared namespace.

# ---- Backups: one copy a day kept for two weeks, copies made by hand, and one before every restore.
BACKUP_KEEP = {'auto': 14, 'manual': 20, 'safety': 5, 'file': 5}
BACKUP_KINDS = {'auto': '每日自動', 'manual': '手動', 'safety': '還原前', 'file': '從檔案加入'}
BACKUP_NAME = re.compile(r'zook-(auto|manual|safety|file)-\d{8}-\d{6}\.json')
MAX_BACKUP_FILE = 50 * 1024 * 1024


def backup_dir(store):
    folder = store.dir / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def backup_list(store):
    out = []
    for path in backup_dir(store).glob('zook-*.json'):
        match = BACKUP_NAME.fullmatch(path.name)
        if not match: continue
        try: stat = path.stat()
        except OSError: continue
        out.append(dict(name=path.name, kind=match.group(1), kindName=BACKUP_KINDS[match.group(1)], size=stat.st_size,
                        at=datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat()))
    return sorted(out, key=lambda x: x['name'][-20:], reverse=True)


def backup_write(store, kind, data):
    """Save one copy and drop the oldest ones of its kind. Passwords and keys are in the Keychain and are never part of a copy."""
    folder = backup_dir(store)
    name = 'zook-%s-%s.json' % (kind, datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    fd, temp = tempfile.mkstemp(prefix='.backup-', dir=str(folder))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False)
        os.replace(temp, folder / name)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    same = sorted(p.name for p in folder.glob('zook-%s-*.json' % kind) if BACKUP_NAME.fullmatch(p.name))
    for old in same[:-BACKUP_KEEP[kind]]:
        try: (folder / old).unlink()
        except OSError: pass
    return name


def backup_daily(store):
    """Lock held. Makes today's copy if there is none yet."""
    today = datetime.datetime.now().strftime('%Y%m%d')
    if any(p.name.startswith('zook-auto-' + today) for p in backup_dir(store).glob('zook-auto-*.json')): return None
    return backup_write(store, 'auto', store.data)


def backup_check(data):
    """A file is only accepted when it has the shape of Zook's data."""
    if not isinstance(data, dict) or not isinstance(data.get('bots'), list) or not isinstance(data.get('settings'), dict): raise ValueError('這不是 Zook 的備份檔。')
    for key in ('bots', 'groups', 'knowledge', 'memories', 'schedules', 'jobs', 'skills', 'connectors', 'accounts'):
        if not isinstance(data.get(key, []), list) or any(not isinstance(x, dict) or not isinstance(x.get('id'), str) for x in data.get(key, [])): raise ValueError('備份檔的內容不完整。')
    if any(not isinstance(b.get('name'), str) for b in data['bots']): raise ValueError('備份檔的內容不完整。')
    return data


def backup_restore(app, name):
    """Lock held. Put a copy back. What is there now is saved first, so a restore can itself be undone."""
    store = app.store
    if not isinstance(name, str) or not BACKUP_NAME.fullmatch(name): raise ValueError('找不到這份備份。')
    path = backup_dir(store) / name
    if not path.is_file(): raise ValueError('找不到這份備份。')
    if any(j['status'] == 'running' for j in store.data['jobs']) or any(g.get('status') == 'running' for g in store.data['groups']):
        raise Busy('有 Bot 正在回覆，等它結束再還原。')
    if path.stat().st_size > MAX_BACKUP_FILE: raise ValueError('備份檔太大。')
    with path.open(encoding='utf-8') as f: data = backup_check(json.load(f))
    safety = backup_write(store, 'safety', store.data)
    # This Mac's own pairing, sign-ins and sync stay as they are: they belong to the machine, not to the copy.
    keep = {key: copy.deepcopy(store.data.get(key)) for key in ('remoteDevices', 'sync') if key in store.data}
    keep_remote = copy.deepcopy(store.data['settings'].get('remote'))
    previous = store.path.read_bytes()
    try:
        data.update(keep)
        if keep_remote is not None: data['settings']['remote'] = keep_remote
        with store.path.open('w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False)
        fresh = Store(store.dir)  # runs the same upgrades an old data file gets at startup
    except Exception:
        store.path.write_bytes(previous); _active['data'] = store.data
        raise ValueError('這份備份無法讀取，資料沒有變動。')
    store.data = fresh.data; _active['data'] = store.data
    return safety


# ---- Activity: who changed or approved what. Kept in its own file so restoring a backup does not rewrite history.
ACTIVITY_KEEP = 1000
ACTIVITY_KINDS = {'approval': '核准', 'tool': '對外動作', 'bot': 'Bot 與群組', 'setting': '設定', 'connector': 'Skills 與連接器', 'schedule': '排程', 'data': '知識與記憶', 'backup': '備份與同步', 'device': '裝置'}
_activity_lock = threading.Lock()


def activity_path(store): return store.dir / 'activity.jsonl'


def log_activity(store, kind, text, by=''):
    """Add one line. Never raises: a full disk must not break the action being recorded."""
    line = json.dumps(dict(id=ID(), at=NOW(), kind=kind, text=' '.join(str(text).split())[:300], by=str(by or '這台 Mac')[:60]), ensure_ascii=False)
    try:
        with _activity_lock:
            path = activity_path(store)
            fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, 'a', encoding='utf-8') as f: f.write(line + '\n')
            if path.stat().st_size > 1024 * 1024:
                lines = path.read_text(encoding='utf-8').splitlines()[-ACTIVITY_KEEP:]
                path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    except OSError: pass


def activity_list(store, kind=''):
    try:
        with _activity_lock: lines = activity_path(store).read_text(encoding='utf-8').splitlines()[-ACTIVITY_KEEP:]
    except OSError: lines = []
    out = []
    for line in reversed(lines):
        try: item = json.loads(line)
        except ValueError: continue
        if isinstance(item, dict) and (not kind or item.get('kind') == kind): out.append(item)
    return dict(items=out, kinds=[dict(id=k, name=v) for k, v in ACTIVITY_KINDS.items()])


SETTING_NAMES = {'permissionMode': '主動性', 'webSearch': '上網搜尋', 'provider': '預設提供者', 'model': '預設模型', 'fallbacks': '備用模型', 'access': '存取範圍', 'accessFolder': '存取範圍',
                 'features': '功能開關', 'effort': '思考強度', 'remote': '手機連線', 'autoUpdateCheck': '自動檢查更新', 'scheduleNotify': '通知', 'sharedMcp': '共用連接器', 'disabledSkills': 'Skills 開關',
                 'disabledPlugins': '插件開關', 'autoModels': '自動選擇的模型', 'rules': '固定規則', 'budgets': '用量預算', 'budgetOver': '用量預算', 'sync': '多台 Mac 同步'}
BOT_FIELD_NAMES = {'name': '名稱', 'persona': '人格檔案', 'instructions': '工作指示', 'provider': '模型', 'model': '模型', 'account': '帳號', 'permissionMode': '主動性', 'access': '存取範圍', 'accessFolder': '存取範圍',
                   'fallbacks': '備用模型', 'features': '功能開關', 'effort': '思考強度', 'isAdmin': '管理員身分', 'enabledMcp': '連接器'}


def activity_hint(store, parts):
    """The name of what a request is about, read before the request runs (a deleted item has no name afterwards)."""
    if len(parts) < 3 or parts[0] != 'api': return ''
    collection = {'bots': 'bots', 'groups': 'groups', 'schedules': 'schedules', 'connectors': 'connectors', 'knowledge': 'knowledge', 'skills': 'skills'}.get(parts[1])
    if not collection: return ''
    with store.lock: item = next((x for x in store.data.get(collection) or [] if x.get('id') == parts[2]), None)
    if not item: return ''
    return str(item.get('name') or item.get('title') or (item.get('content') or '')[:30] or '')[:60]


def describe_request(method, parts, body, hint, result):
    """(kind, text) for a change worth recording, or None. Messages, uploads and window layout are not recorded."""
    if len(parts) < 2 or parts[0] != 'api': return None
    area, n, named = parts[1], len(parts), ('「%s」' % hint if hint else '')
    result = result if isinstance(result, dict) else {}
    if area == 'bots':
        if n == 2 and method == 'POST': return 'bot', '新增 Bot「%s」' % (result.get('name') or body.get('name') or '')
        if n == 3 and method == 'DELETE': return 'bot', '刪除 Bot' + named
        if n == 3 and method == 'PATCH':
            changed = list(dict.fromkeys(BOT_FIELD_NAMES[k] for k in body if k in BOT_FIELD_NAMES))
            return ('bot', '修改 Bot%s：%s' % (named, '、'.join(changed))) if changed else None
        return None
    if area == 'groups':
        if n == 2 and method == 'POST': return 'bot', '新增群組「%s」' % (result.get('name') or '')
        if n == 3 and method == 'PATCH': return 'bot', '修改群組' + named
        if n == 3 and method == 'DELETE': return 'bot', '刪除群組' + named
        return None
    if area == 'settings' and method == 'PATCH':
        changed = list(dict.fromkeys(SETTING_NAMES[k] for k in body if k in SETTING_NAMES))
        return ('setting', '變更設定：' + '、'.join(changed)) if changed else None
    if area == 'schedules':
        if n == 2 and method == 'POST': return 'schedule', '新增排程：' + str(body.get('content') or '')[:60]
        if n == 3 and method == 'PATCH': return 'schedule', '修改排程' + named
        if n == 3 and method == 'DELETE': return 'schedule', '刪除排程' + named
        if n == 4 and parts[3] == 'run': return 'schedule', '手動執行排程' + named
        return None
    if area == 'knowledge':
        if method == 'POST': return 'data', '新增知識「%s」' % str(body.get('title') or '')[:60]
        return 'data', ('刪除知識' if method == 'DELETE' else '修改知識') + named
    if area == 'memories' and method == 'DELETE': return 'data', '刪除一則記憶'
    if area == 'connector-catalog' and method == 'POST': return 'connector', '加入連接器「%s」' % (result.get('name') or parts[-1])
    if area == 'connectors':
        if n == 2 and method == 'POST': return 'connector', '新增連接器「%s」' % (result.get('name') or body.get('name') or '')
        if n == 3 and method == 'PATCH': return 'connector', '修改連接器' + named
        if n == 3 and method == 'DELETE': return 'connector', '移除連接器' + named
        if n == 4 and parts[3] in ('login', 'logout', 'account'): return 'connector', {'login': '登入連接器', 'logout': '登出連接器', 'account': '切換連接器帳號'}[parts[3]] + named
        return None
    if area in ('google', 'gmail') and n <= 3: return 'connector', ('中斷 %s 連線' if method == 'DELETE' else '連接或切換 %s 帳號') % ('Gmail' if area == 'gmail' else 'Google')
    if area == 'skills':
        if n == 3 and parts[2] == 'import': return 'connector', '匯入 Skill'
        if n == 3 and parts[2] == 'template': return 'connector', '從範本加入 Skill「%s」' % (result.get('name') or '')
        if n == 3 and method == 'DELETE': return 'connector', '移除 Skill' + named
        return None
    if area in ('pack', 'connector-copy') and method == 'POST': return 'connector', '加入 Skill 或連接器'
    if area == 'remote':
        if parts[2:] == ['pairing'] and method == 'POST': return 'device', '開始配對新裝置'
        if n == 4 and parts[2] == 'devices' and method == 'DELETE': return 'device', '移除已配對的裝置'
        return None
    if area == 'providers' and method in ('POST', 'DELETE', 'PATCH'): return 'setting', '變更模型或帳號設定'
    if area == 'update' and parts[2:] == ['apply']: return 'setting', '安裝更新'
    return None


def note_request(handler, code, result):
    """Called for every answered request; records the ones that changed something."""
    if code >= 300 or handler.command not in ('POST', 'PATCH', 'DELETE') or getattr(handler, 'noted', False): return
    handler.noted = True
    try:
        parts = [unquote(p) for p in urlsplit(handler.path).path.strip('/').split('/')]
        found = describe_request(handler.command, parts, getattr(handler, 'last_body', None) or {}, getattr(handler, 'hint', ''), result)
        if found:
            device = getattr(handler, 'device', None)
            log_activity(handler.server.store, found[0], found[1], by=('手機：' + str(device.get('name') or '已配對裝置')) if device else '')
    except Exception: pass


# ---- Budgets: a monthly Token ceiling per model, counted from Zook's own replies.
BUDGET_LIMITS = (0, 1_000_000, 5_000_000, 10_000_000, 50_000_000, 100_000_000, 500_000_000)
BUDGET_OVER = ('warn', 'switch', 'stop')
BUDGET_NEAR = 0.8


def budget_month(): return datetime.datetime.now().strftime('%Y-%m')


def budget_limit(store, provider):
    value = (store.data['settings'].get('budgets') or {}).get(provider)
    return value if isinstance(value, int) and value > 0 else 0


def budget_used(store, provider):
    return int(((store.data.get('spend') or {}).get(budget_month()) or {}).get(provider) or 0)


def budget_state(store, provider):
    """'' when there is no ceiling or plenty left, 'near' from 80 percent, 'over' when used up."""
    limit = budget_limit(store, provider)
    if not limit: return ''
    used = budget_used(store, provider)
    return 'over' if used >= limit else 'near' if used >= limit * BUDGET_NEAR else ''


def budget_blocks(store, provider):
    """What a used-up budget does to a reply: 'switch' to a backup model, 'stop', or nothing."""
    over = store.data['settings'].get('budgetOver') or 'warn'
    return over if over in ('switch', 'stop') and budget_state(store, provider) == 'over' else ''


def budget_add(app, provider, usage):
    """Lock held. Count one reply and say so once when a ceiling is near or reached."""
    store = app.store
    tokens = sum(v for v in ((usage or {}).get('input'), (usage or {}).get('output')) if isinstance(v, int) and v > 0)
    if not tokens: return
    spend = store.data.setdefault('spend', {}); month = budget_month()
    for old in sorted(spend)[:-6]: spend.pop(old, None)
    before = budget_state(store, provider)
    spend.setdefault(month, {})[provider] = budget_used(store, provider) + tokens
    after = budget_state(store, provider)
    if after and after != before:
        name = provider_label(provider).split('（')[0]
        over = store.data['settings'].get('budgetOver') or 'warn'
        text = '這個月的用量預算已用完' + {'switch': '，之後改用備用模型。', 'stop': '，之後不再用它回覆。'}.get(over, '。') if after == 'over' else '這個月的用量已達預算的 80%。'
        app.notify(name, text, 'page', 'usage', '', always=True)
        log_activity(store, 'setting', '%s：%s' % (name, text), by='Zook')


def budget_view(store):
    providers = [p['id'] for p in provider_info()] if callable(globals().get('provider_info')) else []
    month = (store.data.get('spend') or {}).get(budget_month()) or {}
    ids = list(dict.fromkeys(providers + list(month) + list(store.data['settings'].get('budgets') or {})))
    return dict(month=budget_month(), over=store.data['settings'].get('budgetOver') or 'warn', limits=list(BUDGET_LIMITS),
                items=[dict(id=p, name=provider_label(p).split('（')[0], used=int(month.get(p) or 0), limit=budget_limit(store, p), state=budget_state(store, p)) for p in ids if P.spec(store.data, p)])


def upkeep_fields(data, body, changes):
    """Checks the settings this file owns. Used by update() for kind 'settings'."""
    if 'rules' in body:
        if not isinstance(body['rules'], str) or len(body['rules']) > 10000: raise ValueError('固定規則太長，最多 10000 字。')
        changes['rules'] = body['rules'].strip()
    if 'onboarded' in body:
        if body['onboarded'] is not True: raise ValueError('onboarded 無效。')
        changes['onboarded'] = True
    if 'budgetOver' in body:
        if body['budgetOver'] not in BUDGET_OVER: raise ValueError('預算用完後的做法無效。')
        changes['budgetOver'] = body['budgetOver']
    if 'budgets' in body:
        value = body['budgets']
        if not isinstance(value, dict) or len(value) > 50 or any(not isinstance(k, str) or not P.spec(data, k) or v not in BUDGET_LIMITS or isinstance(v, bool) for k, v in value.items()): raise ValueError('用量預算無效。')
        changes['budgets'] = {k: v for k, v in dict(data['settings'].get('budgets') or {}, **value).items() if v}


def rules_block():
    rules = str(((_active.get('data') or {}).get('settings') or {}).get('rules') or '').strip()
    return '【固定規則】（所有 Bot 都要遵守；與其他指示衝突時以這裡為準）\n' + rules[:10000] if rules else ''


def upkeep_route(handler, store, parts, path):
    """Backups, the activity record and budgets. Only this Mac may use them. Lock held."""
    if handler.device: return handler.error(403, '這項功能只能在 Mac 上使用。')
    method, n = handler.command, len(parts)
    if path == '/api/activity' and method == 'GET':
        kind = (parse_qs(urlsplit(handler.path).query).get('kind') or [''])[0]
        return handler.respond(200, activity_list(store, kind if kind in ACTIVITY_KINDS else ''))
    if path == '/api/budget' and method == 'GET': return handler.respond(200, budget_view(store))
    if path == '/api/backups' and method == 'GET': return handler.respond(200, dict(items=backup_list(store)))
    if path == '/api/backups' and method == 'POST':
        name = backup_write(store, 'manual', store.data); log_activity(store, 'backup', '建立備份')
        return handler.respond(201, dict(name=name, items=backup_list(store)))
    if path == '/api/backups/file' and method == 'POST':
        name = backup_write(store, 'file', backup_check(handler.body(MAX_BACKUP_FILE).get('data'))); log_activity(store, 'backup', '從檔案加入一份備份')
        return handler.respond(201, dict(name=name, items=backup_list(store)))
    if n == 4 and parts[3] == 'restore' and method == 'POST':
        try: safety = backup_restore(handler.server, parts[2])
        except Busy as exc: return handler.error(409, str(exc))
        log_activity(store, 'backup', '還原備份 %s（還原前的資料另存為 %s）' % (parts[2], safety))
        return handler.respond(200, dict(ok=True, safety=safety))
    if n == 3 and method == 'DELETE':
        if not BACKUP_NAME.fullmatch(parts[2]) or not (backup_dir(store) / parts[2]).is_file(): return handler.error(404, '找不到這份備份。')
        (backup_dir(store) / parts[2]).unlink(); log_activity(store, 'backup', '刪除備份 ' + parts[2])
        return handler.respond(200, dict(items=backup_list(store)))
    return handler.error(404, '找不到資源。')
