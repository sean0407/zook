# Looking after the data: backups, the activity record, monthly usage budgets and the rules every Bot follows.
# Loaded by backend/server.py into one shared namespace.

# ---- Backups: one copy a day kept for two weeks, copies made by hand, and one before every restore.
BACKUP_KEEP = {'auto': 14, 'manual': 20, 'safety': 5, 'file': 5}
BACKUP_KINDS = {'auto': '每日自動', 'manual': '手動', 'safety': '還原前', 'file': '從檔案加入'}
BACKUP_NAME = re.compile(r'zook-(auto|manual|safety|file)-\d{8}-\d{6}\.json(?:\.gz)?')  # one file with everything in it; compressed since conversations moved to their own files
MAX_BACKUP_FILE = 50 * 1024 * 1024


def backup_dir(store):
    folder = store.dir / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def backup_list(store):
    out = []
    for path in backup_dir(store).glob('zook-*.json*'):
        match = BACKUP_NAME.fullmatch(path.name)
        if not match: continue
        try: stat = path.stat()
        except OSError: continue
        out.append(dict(name=path.name, kind=match.group(1), kindName=BACKUP_KINDS[match.group(1)], size=stat.st_size,
                        at=datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat()))
    return sorted(out, key=lambda x: re.search(r'\d{8}-\d{6}', x['name']).group(0), reverse=True)


def backup_write(store, kind, data):
    """Save one copy and drop the oldest ones of its kind. Passwords and keys are in the Keychain and are never part of a copy."""
    folder = backup_dir(store)
    name = 'zook-%s-%s.json.gz' % (kind, datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    fd, temp = tempfile.mkstemp(prefix='.backup-', dir=str(folder))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=6, mtime=0) as packed: packed.write(json.dumps(data, ensure_ascii=False).encode('utf-8', 'surrogatepass'))
            raw.flush(); os.fsync(raw.fileno())
        os.replace(temp, folder / name)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    same = sorted((p.name for p in folder.glob('zook-%s-*.json*' % kind) if BACKUP_NAME.fullmatch(p.name)), key=lambda n: re.search(r'\d{8}-\d{6}', n).group(0))
    for old in same[:-BACKUP_KEEP[kind]]:
        try: (folder / old).unlink()
        except OSError: pass
    return name


def backup_daily(store):
    """Lock held. Makes today's copy if there is none yet."""
    today = datetime.datetime.now().strftime('%Y%m%d')
    if any(p.name.startswith('zook-auto-' + today) for p in backup_dir(store).glob('zook-auto-*.json*')): return None
    return backup_write(store, 'auto', store.data)


def backup_check(data):
    """A file is only accepted when it has the shape of Zook's data."""
    if not isinstance(data, dict) or not isinstance(data.get('bots'), list) or not isinstance(data.get('settings'), dict): raise ValueError('這不是 Zook 的備份檔。')
    for key in ('bots', 'groups', 'knowledge', 'memories', 'schedules', 'jobs', 'skills', 'connectors', 'accounts'):
        if not isinstance(data.get(key, []), list) or any(not isinstance(x, dict) or not isinstance(x.get('id'), str) for x in data.get(key, [])): raise ValueError('備份檔的內容不完整。')
    if any(not isinstance(b.get('name'), str) for b in data['bots']): raise ValueError('備份檔的內容不完整。')
    for g in data.get('groups') or []:
        if 'taskRun' in g and not task_run_ok(g['taskRun']): g.pop('taskRun')  # 任務引擎's books, only in the shape Zook writes
    task_settings_clean(data['settings'])
    for bot in data['bots'] + [b for b in data.get('deletedBots') or [] if isinstance(b, dict)]:  # what this Mac allows is never in a copy
        bot['scripts'] = False; limit_locally(bot)
    data['settings'].update(gateFullSet=True, scriptsOff=True)  # and the one-time upgrades do not grant it afterwards
    # The main file of a Zook that keeps conversations in their own files has no conversation in it. Putting it back as if it were whole would empty them all.
    if data.get('layout') is not None: raise ValueError('這個檔案是 Zook 的主檔，裡面沒有對話內容，不能當成備份。請改用「備份與還原」建立的備份檔。')
    for key, rel, messages, _ in chat_conversations(data):
        if any(not isinstance(m, dict) or any(not isinstance(m.get(k), (str, type(None))) for k in ('id', 'role', 'status', 'content', 'note')) for m in messages): raise ValueError('備份檔的內容不完整。')
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
    try: data = backup_check(backup_read(path))
    except (OSError, EOFError, UnicodeError, RecursionError): raise ValueError('這份備份無法讀取，資料沒有變動。')
    for bot in data['bots']: bot.pop('queue', None)  # messages that were waiting when the copy was made have been sent since
    safety = backup_write(store, 'safety', store.data)
    # This Mac's own pairing, sign-ins and sync stay as they are: they belong to the machine, not to the copy.
    keep = {key: copy.deepcopy(store.data.get(key)) for key in ('remoteDevices', 'sync') if key in store.data}
    keep_remote = copy.deepcopy(store.data['settings'].get('remote'))
    # A triggered schedule goes on from where it is now, so files and mails it has already handled do not start it again.
    progress = {x['id']: {k: copy.deepcopy(x[k]) for k in ('watchSeen', 'mailState', 'mailWaiting') if k in x} for x in store.data['schedules']}
    for item in data.get('schedules') or []:
        now_at = store.find('schedules', item['id'])
        if now_at and (now_at.get('trigger'), now_at.get('watchFolder'), now_at.get('mailFrom'), now_at.get('mailSubject')) == (item.get('trigger'), item.get('watchFolder'), item.get('mailFrom'), item.get('mailSubject')): item.update(progress[item['id']])
    previous = store.path.read_bytes(); root, aside = store.chat_root(), store.dir / (CHAT_FOLDER + '.old')
    try:
        data.update(keep)
        if keep_remote is not None: data['settings']['remote'] = keep_remote
        browser_keep_local(store.data, data)  # a copy never turns the browser on
        task_keep_local(store.data, data)  # nor 任務引擎, nor work that starts by itself
        usage_detect_keep_local(store.data, data)  # nor 自動偵測使用量
        with store.path.open('w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False)
        Store.keep_aside = True  # the conversations that are there now stay in chats.old until the copy is known to be in place
        try: fresh = Store(store.dir, recover=False)  # runs the same upgrades an old data file gets at startup
        finally: Store.keep_aside = False
    except Exception:
        # Back to exactly what was there: the main file, and the conversation files if they had already been swapped.
        store.path.write_bytes(previous); _active['data'] = store.data
        if aside.is_dir():
            shutil.rmtree(str(root), ignore_errors=True); os.replace(str(aside), str(root))
        store.chat_forget()
        try: store.save(everything=True)
        except OSError: pass
        raise ValueError('這份備份無法讀取，資料沒有變動。')
    shutil.rmtree(str(aside), ignore_errors=True)
    store.data = fresh.data; _active['data'] = store.data
    store.chat_forget()  # the files on disk are the copy's now
    store.save(everything=True)
    # Older data must not be sent to the other Macs as if it were new, nor its gaps as deletions: syncing stops until it is switched on again.
    return safety, sync_halt(store)


def sync_halt(store):
    """Lock held. Stop syncing after the data went back in time. True when it was on."""
    sync = store.data.get('sync') or {}
    if not sync.get('folder'): return False
    try: os.unlink(os.path.join(sync['folder'], 'zook-sync-%s.json' % sync.get('deviceId')))
    except OSError: pass
    sync.update(folder='', others=[], lastError=''); sync_marks(store, reset=True); store.save()
    return True


def recover_data(store):
    """The data file cannot be read. Keep it under another name, load the newest backup that is whole, and say what happened.
    Sets store.data and returns the note the window shows once."""
    kept = 'swarmr.corrupt-%s.json' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    try: os.replace(store.path, store.dir / kept)
    except OSError: kept = ''
    for backup in backup_list(store):
        if backup['kind'] == 'file' or backup['size'] > MAX_BACKUP_FILE: continue  # a file brought in from elsewhere was never this Mac's data
        try:
            store.data = backup_check(backup_read(backup_dir(store) / backup['name']))
        except (OSError, ValueError, UnicodeError, RecursionError, EOFError): continue
        for bot in store.data['bots']: bot.pop('queue', None)
        log_activity(store, 'backup', '資料檔無法讀取，改用備份 %s（損壞的檔案留存為 %s）' % (backup['name'], kept or '無法留存'), by='Zook')
        return dict(at=NOW(), backup=backup['name'], backupAt=backup['at'], kept=kept)
    log_activity(store, 'backup', '資料檔無法讀取，也沒有可用的備份，從全新狀態開始（損壞的檔案留存為 %s）' % (kept or '無法留存'), by='Zook')
    store.data = seeds()
    return dict(at=NOW(), backup='', backupAt='', kept=kept)


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


# ---- CLIs Zook no longer supports. Data from before (or a restored backup) may still name them.
REMOVED_PROVIDERS = {'opencode': 'OpenCode', 'copilot': 'GitHub Copilot', 'kimi': 'Kimi'}


def drop_removed_providers(store):
    """Runs on every load, after a sync and when a deleted Bot comes back. A Bot set to a removed CLI switches to 自動選擇, and the settings
    forget it; the activity record says what changed. Does nothing once no data names them. API keys already in the Keychain are left as they are."""
    data, gone = store.data, set(REMOVED_PROVIDERS)
    settings = data.get('settings') if isinstance(data.get('settings'), dict) else {}
    named = lambda x: isinstance(x, str) and x in gone
    dropped = {a.get('id') for a in data.get('accounts') or [] if isinstance(a, dict) and named(a.get('provider'))}
    if dropped: data['accounts'] = [a for a in data.get('accounts') or [] if not (isinstance(a, dict) and named(a.get('provider')))]
    default = named(settings.get('provider'))
    moved, changed = [], bool(dropped)
    for bot in list(data.get('bots') or []) + list(data.get('deletedBots') or []):
        if not isinstance(bot, dict): continue
        if named(bot.get('provider')) or (default and not bot.get('provider') and bot.get('model')):  # its own CLI, or 使用預設 with that CLI's model
            bot.update(provider=AUTO, model='', account=''); changed = True
            if any(b is bot for b in data.get('bots') or []): moved.append(str(bot.get('name') or '未命名'))
        elif bot.get('account') in dropped: bot['account'] = ''; changed = True
        if isinstance(bot.get('fallbacks'), list) and any(named(x) for x in bot['fallbacks']): bot['fallbacks'] = [x for x in bot['fallbacks'] if not named(x)]; changed = True
    if default: settings.pop('provider'); settings.pop('model', None)
    for key in ('fallbacks', 'autoModels', 'addedProviders', 'hiddenProviders'):
        value = settings.get(key)
        if isinstance(value, list) and any(named(x) for x in value):
            settings[key] = [x for x in value if not named(x)]; changed = True
            if key == 'autoModels' and not settings[key]: settings.pop(key)  # only removed CLIs were chosen: back to the usual choice, not to none at all
    if isinstance(settings.get('autoAccounts'), dict) and dropped & set(settings['autoAccounts']): settings['autoAccounts'] = {k: v for k, v in settings['autoAccounts'].items() if k not in dropped}
    names = '、'.join(REMOVED_PROVIDERS.values())
    if moved: log_activity(store, 'bot', 'Zook 已不再支援 %s。這些 Bot 原本使用它們，已改成「自動選擇」：%s' % (names, '、'.join(moved)), by='Zook')
    elif changed or default: log_activity(store, 'setting', 'Zook 已不再支援 %s，相關的帳號與設定已移除%s。' % (names, '，預設提供者改回 Codex' if default else ''), by='Zook')
    if default and moved: log_activity(store, 'setting', 'Zook 已不再支援 %s。預設提供者原本是其中之一，已改回 Codex。' % names, by='Zook')
    return moved


SETTING_NAMES = {'permissionMode': '主動性', 'webSearch': '上網搜尋', 'browserAutomation': '排程與觸發可用內建瀏覽器', 'provider': '預設提供者', 'model': '預設模型', 'fallbacks': '備用模型', 'access': '存取範圍', 'accessFolder': '存取範圍',
                 'features': '功能開關', 'effort': '思考強度', 'remote': '手機連線', 'autoUpdateCheck': '自動檢查更新', 'usageDetectEvery': '自動偵測使用量', 'scheduleNotify': '通知', 'sharedMcp': '共用連接器', 'disabledSkills': 'Skills 開關',
                 'disabledPlugins': '插件開關', 'autoModels': '自動選擇的模型', 'autoAccounts': '自動選擇的帳號', 'rules': '固定規則', 'budgets': '用量預算', 'budgetOver': '用量預算', 'sync': '多台 Mac 同步', 'voiceLang': '語音輸入語言', 'streamReplies': '回覆逐字顯示', 'queueWhenBusy': 'Bot 忙碌時排隊', 'busySend': '回覆中送出的訊息', 'keepCli': '保持 CLI 開啟', 'autoCompact': '對話過長時自動整理'}
BOT_FIELD_NAMES = {'name': '名稱', 'persona': '人格檔案', 'instructions': '工作指示', 'provider': '模型', 'model': '模型', 'account': '帳號', 'permissionMode': '主動性', 'access': '存取範圍', 'accessFolder': '存取範圍',
                   'fallbacks': '備用模型', 'features': '功能開關', 'effort': '思考強度', 'isAdmin': '管理員身分', 'enabledMcp': '連接器', 'scripts': '允許本機腳本'}


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
        if n == 4 and parts[3] == 'restore': return 'bot', '喚回 Bot「%s」' % (result.get('name') or '')
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
    if area == 'quota' and parts[2:] == ['auto'] and method == 'POST':
        every = result.get('usageDetectEvery', body.get('every'))
        return 'setting', '變更設定：自動偵測使用量（%s）' % USAGE_DETECT_NAMES.get(every, every)
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
    browser_fields(body, changes); task_fields(body, changes)
    if 'rules' in body:
        if not isinstance(body['rules'], str) or len(body['rules']) > 10000: raise ValueError('固定規則太長，最多 10000 字。')
        changes['rules'] = body['rules'].strip()
    if 'voiceLang' in body:
        if body['voiceLang'] not in ('', 'zh-TW', 'en-US', 'ja-JP'): raise ValueError('語音語言無效。')
        changes['voiceLang'] = body['voiceLang']
    if 'recoveredSeen' in body:
        if body['recoveredSeen'] is not True: raise ValueError('recoveredSeen 無效。')
        changes['recovered'] = None
    if 'busySend' in body:
        if body['busySend'] not in ('queue', 'now'): raise ValueError('busySend 無效。')
        changes['busySend'] = body['busySend']
    if 'queueWhenBusy' in body:
        if not isinstance(body['queueWhenBusy'], bool): raise ValueError('queueWhenBusy 無效。')
        changes['queueWhenBusy'] = body['queueWhenBusy']
    if 'autoCompact' in body:
        if not isinstance(body['autoCompact'], bool): raise ValueError('autoCompact 無效。')
        changes['autoCompact'] = body['autoCompact']
    if 'appearance' in body:
        if body['appearance'] not in ('system', 'light', 'dark'): raise ValueError('深淺色設定無效。')
        changes['appearance'] = body['appearance']
    if 'textSize' in body:
        if body['textSize'] not in ('small', 'normal', 'large', 'xlarge'): raise ValueError('字體大小設定無效。')
        changes['textSize'] = body['textSize']
    if 'keepCli' in body:
        if not isinstance(body['keepCli'], bool): raise ValueError('keepCli 無效。')
        changes['keepCli'] = body['keepCli']
    if 'choiceButtons' in body:
        if not isinstance(body['choiceButtons'], bool): raise ValueError('choiceButtons 無效。')
        changes['choiceButtons'] = body['choiceButtons']
    if 'streamReplies' in body:
        if not isinstance(body['streamReplies'], bool): raise ValueError('streamReplies 無效。')
        changes['streamReplies'] = body['streamReplies']
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
        try: safety, stopped = backup_restore(handler.server, parts[2])
        except Busy as exc: return handler.error(409, str(exc))
        log_activity(store, 'backup', '還原備份 %s（還原前的資料另存為 %s）%s' % (parts[2], safety, '，並停止同步' if stopped else ''))
        return handler.respond(200, dict(ok=True, safety=safety, syncStopped=stopped))
    if n == 3 and method == 'DELETE':
        if not BACKUP_NAME.fullmatch(parts[2]) or not (backup_dir(store) / parts[2]).is_file(): return handler.error(404, '找不到這份備份。')
        (backup_dir(store) / parts[2]).unlink(); log_activity(store, 'backup', '刪除備份 ' + parts[2])
        return handler.respond(200, dict(items=backup_list(store)))
    return handler.error(404, '找不到資源。')


# ---- Old jobs: a finished reply keeps its details only while it is recent, so the data file and the window stay small.
JOBS_FULL_PER_BOT = 10   # the newest finished replies of each Bot keep what it did and its approvals
JOBS_WITH_ANSWER = 3     # only the very newest also keep a second copy of the answer; the conversation always has it
JOBS_SLIM_DAYS = 30      # after that only what usage figures and the files list need; older than this is added to the totals
JOB_SLIM_KEEP = ('id', 'botId', 'groupId', 'chatId', 'messageId', 'status', 'createdAt', 'finishedAt', 'usage', 'fallback', 'effort', 'plan', 'long', 'origin', 'queueId')


def _job_time(job):
    try: return datetime.datetime.fromisoformat(str(job.get('finishedAt') or job.get('createdAt'))).timestamp()
    except ValueError: return 0


def trim_jobs(store):
    """Lock held. Returns True when something was made smaller. A running reply, and one a schedule is still waiting on, are left alone."""
    jobs, changed, seen = store.data['jobs'], False, {}
    waiting = {run.get('jobId') for item in store.data.get('schedules') or [] for run in item.get('runs') or [] if run.get('status') == 'running'}
    talking = {g['id'] for g in store.data.get('groups') or [] if g.get('status') == 'running'}  # a discussion still reads its own earlier replies
    alive = {b['id'] for b in store.data['bots']}
    for job in reversed(jobs):
        if job.get('status') == 'running' or job.get('slim') or job['id'] in waiting or job.get('groupId') in talking: continue
        seen[job['botId']] = seen.get(job['botId'], 0) + 1
        if seen[job['botId']] > JOBS_WITH_ANSWER and job.get('content'):
            said = job.pop('content'); named = [] if job.get('plan') else named_paths(said)  # the files its answer named still count for 產出
            if named: job['wrote'] = list(dict.fromkeys((job.get('wrote') or []) + named))[:50]
            changed = True
        if seen[job['botId']] <= JOBS_FULL_PER_BOT and job['botId'] in alive: continue  # a deleted Bot's replies keep only their usage figures
        wrote = [str((c.get('arguments') or {}).get('path') or '')[:300] for c in job.get('toolCalls') or [] if c.get('name') == 'native_write'] + (job.get('wrote') or [])
        small = {k: job[k] for k in JOB_SLIM_KEEP if k in job}
        if job.get('error'): small['error'] = str(job['error'])[:300]
        if wrote: small['wrote'] = [p for p in dict.fromkeys(wrote) if p][:50]
        job.clear(); job.update(small, slim=True, toolCalls=[], approvals=[]); changed = True
    cutoff = time.time() - JOBS_SLIM_DAYS * 86400
    old = [j for j in jobs if j.get('slim') and _job_time(j) < cutoff]
    if old:
        archive = store.data.setdefault('usageArchive', {})
        for job in old:
            u = job.get('usage')
            if not isinstance(u, dict): continue
            usage_daily_fold(store, job)
            row = archive.setdefault(job['botId'], dict(replies=0, groupReplies=0, input=0, cachedInput=0, output=0, costUsd=0.0, hasCost=False, models={}))
            row['replies'] += 1; row['groupReplies'] += 1 if job.get('groupId') else 0
            for k in ('input', 'cachedInput', 'output'): row[k] += _int(u.get(k))
            if isinstance(u.get('costUsd'), (int, float)) and not isinstance(u.get('costUsd'), bool): row['costUsd'] += u['costUsd']; row['hasCost'] = True
            label = '%s · %s' % (u.get('provider', ''), u.get('model') or '預設模型')
            row['models'][label] = row['models'].get(label, 0) + _int(u.get('input')) + _int(u.get('output'))
        gone = {id(j) for j in old}
        jobs[:] = [j for j in jobs if id(j) not in gone]; changed = True
    return changed


def state_view(store, whole=False):
    """Lock held. What the window and the phone load: everything except the trimmed jobs and the usage totals, which only the usage page needs."""
    view = dict(store.data, rev=store.rev)
    view['jobs'] = [{k: v for k, v in j.items() if k != 'thinking'} for j in store.data['jobs'] if not j.get('slim') and not j.get('internal')]
    if not whole: view['bots'] = [page_bot(b) for b in store.data['bots']]  # the newest part of each open conversation; older parts are asked for
    if not whole: view['groups'] = [page_group(g) for g in store.data['groups']]
    view.pop('usageArchive', None); view.pop('usageDaily', None); view['rings'] = usage_rings(store)
    view['deletedBots'] = [{k: b.get(k) for k in ('id', 'name', 'color', 'shape', 'deletedAt')} for b in store.data.get('deletedBots') or []]  # their conversations stay on disk
    return view


# ---- Sending once: a message carries an id made by the window or the phone. If the answer to a send is lost on the way and the
# same message is sent again, the first send's result comes back instead of a second reply being started.
SEND_ONCE_SECONDS = 600
SEND_ID = re.compile(r'[A-Za-z0-9_-]{8,64}')


def send_key(target, body):
    """The key for one message to one Bot or group, or None when the sender gave no usable id (older apps)."""
    client = body.get('clientId')
    if not isinstance(client, str) or not SEND_ID.fullmatch(client): return None
    return (target, client, hashlib.sha256(str(body.get('content')).encode('utf-8', 'replace')).hexdigest())


def send_seen(app, key):
    """Lock held. What the first send of this message returned, if it was accepted within the last ten minutes."""
    sends, now = app.__dict__.setdefault('recent_sends', {}), time.monotonic()
    for old in [k for k, (until, _) in sends.items() if until < now]: sends.pop(old)
    return sends[key][1] if key and key in sends else None


def send_remember(app, key, result):
    """Lock held. Only an accepted send is remembered: one that was refused can simply be tried again."""
    if key: app.__dict__.setdefault('recent_sends', {})[key] = (time.monotonic() + SEND_ONCE_SECONDS, result)


# ---- Deleted Bots: a Bot that is deleted is kept aside with its conversations, so it can be brought back with one click.
TRASH_KEEP = 30


def trash_bot(store, bot):
    """Lock held. Called just before a Bot is removed from the list."""
    kept = copy.deepcopy(bot); kept['deletedAt'] = NOW(); kept.pop('queue', None)  # what was waiting for it is not sent later by surprise
    trash = store.data.setdefault('deletedBots', [])
    trash[:] = [b for b in trash if b.get('id') != bot['id']] + [kept]
    del trash[:-TRASH_KEEP]


def restore_bot(store, bot_id):
    """Lock held. Put a deleted Bot back, with its conversations. Its group seats and schedules were removed when it was deleted and do not return."""
    trash = store.data.get('deletedBots') or []
    kept = next((b for b in trash if b.get('id') == bot_id), None)
    if not kept or store.find('bots', bot_id): raise ValueError('找不到可以喚回的 Bot。')
    bot = copy.deepcopy(kept); bot.pop('deletedAt', None); bot.pop('recovered', None)
    if bot.get('provider') in REMOVED_PROVIDERS: bot.update(provider=AUTO, model='', account='')  # set to a CLI Zook no longer has
    if bot.get('isAdmin') and any(b.get('isAdmin') for b in store.data['bots']): bot['isAdmin'] = False  # there is one 管理員
    bot.setdefault('isAdmin', False); bot['pinned'] = False; bot['scripts'] = False  # local scripts are switched on again on purpose, if at all
    for key, value in (('enabledSkills', []), ('enabledMcp', []), ('allowCommands', True), ('persona', ''), ('webSearch', False), ('messages', [])): bot.setdefault(key, value)
    if bot.get('provider') and bot['provider'] != AUTO and not P.spec(store.data, bot['provider']): bot.update(provider='', model='')
    if bot.get('account') and not find_account(bot['account']): bot['account'] = ''
    ensure_chats(bot)
    section = bot.get('section') or '我的 Bots'
    if section not in store.data['settings'].setdefault('sections', []): store.data['settings']['sections'].append(section)
    store.data['bots'].append(bot); trash.remove(kept)
    return bot


def recover_deleted_bots(store):
    """Lock held, once. Bots deleted before Zook kept them aside are looked up in the older copies of the data that are still on
    this Mac, so their usage rows can show a name and they can be brought back."""
    if store.data['settings'].get('trashSeeded'): return False
    store.data['settings']['trashSeeded'] = True
    alive = {b['id'] for b in store.data['bots']} | {b.get('id') for b in store.data.get('deletedBots') or []}
    wanted = ({j['botId'] for j in store.data['jobs']} | set(store.data.get('usageArchive') or {})) - alive
    if not wanted: return True
    files = [p for p in list(store.dir.glob('swarmr*.json')) + list(backup_dir(store).glob('zook-*.json*')) if p != store.path]
    def age(path):
        try: return path.stat().st_mtime
        except OSError: return 0
    for path in sorted(files, key=age, reverse=True)[:60]:  # the newest copy that still has the Bot is the closest to how it was
        if not wanted: break
        try:
            if path.is_symlink() or path.stat().st_size > MAX_BACKUP_FILE: continue
            old = backup_read(path)
        except (OSError, ValueError, UnicodeError, RecursionError, EOFError): continue
        for bot in (old.get('bots') if isinstance(old, dict) and isinstance(old.get('bots'), list) else []):
            if isinstance(bot, dict) and bot.get('id') in wanted and isinstance(bot.get('name'), str) and bot['name'].strip():
                wanted.discard(bot['id'])
                store.data.setdefault('deletedBots', []).append(dict(copy.deepcopy(bot), deletedAt='', recovered=path.name))
    del store.data.get('deletedBots', [])[:-TRASH_KEEP]
    return True
