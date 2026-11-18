# Settings packs, Skills and connector inventory, icons, schedule rules. Loaded by backend/server.py into one shared namespace.
def connector_keep_secrets(record, found):
    """Put a copied connector's keys in the Keychain. The first is the one the edit form shows; the rest are kept by name."""
    saved = []
    try:
        for index, (key, value) in enumerate(found.items()):
            ident = ID(); secret_set(ident, value); saved.append(ident)
            if index == 0: record['secretName'], record['secretId'] = key, ident
            else: record['moreSecrets'][key] = ident
    except (ValueError, RuntimeError):
        for ident in saved: secret_delete(ident)
        raise ValueError('這個連接器的金鑰含有鑰匙圈存不了的字元，無法複製。請改用「新增連接器」手動輸入。')


def connector_secret_ids(record):
    return [x for x in [record.get('secretId')] + list((record.get('moreSecrets') or {}).values()) if x]  # sign-in tokens are removed with oauth_logout


def pack_export(store):
    """Zook's own Skills and connectors as one zip file. Keys stay in the Keychain and are never included."""
    import io, zipfile
    with store.lock:
        skills = copy.deepcopy(store.data['skills']); connectors = copy.deepcopy(store.data['connectors'])
        off = set(store.data['settings']['disabledSkills']); on = set(store.data['settings'].get('sharedMcp') or [])
    manifest = dict(format='zook-pack', version=1, skills=[], connectors=[]); buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for record in skills:
            try: files = skill_files(store.dir / 'skills' / record['folder'])
            except (OSError, ValueError): continue
            if not files: continue
            manifest['skills'].append(dict(name=record['name'], folder=record['folder'], on=ZOOK_SKILL + record['id'] not in off))
            for relative, path in files: z.write(str(path), 'skills/%s/%s' % (record['folder'], relative))
        for c in connectors:
            manifest['connectors'].append(dict(name=c['name'], transport=c['transport'], command=c.get('command', ''), url=c.get('url', ''), env=c.get('env') or {},
                headers=c.get('headers') or {}, secretName=c.get('secretName', ''), moreSecrets=sorted(c.get('moreSecrets') or {}), on='zook:' + c['id'] in on))
        z.writestr('zook.json', json.dumps(manifest, ensure_ascii=False, indent=1))
    raw = buffer.getvalue()
    if len(raw) > PACK_BYTES: raise ValueError('設定包超過 150 MB，無法匯出。請先移除用不到的 Skill。')
    return raw, len(manifest['skills']), len(manifest['connectors'])


def pack_import(store, raw):
    """Add the Skills and connectors from a pack. Names Zook already has are left alone; connectors that need a key wait for it."""
    import io, zipfile
    bad = ValueError('這不是 Zook 的設定包，或檔案已損壞。')
    try: z = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, ValueError): raise bad
    result = dict(skills=[], connectors=[], skipped=[], needKeys=[])
    with z:
        infos = z.infolist()
        try: manifest = json.loads(z.read('zook.json').decode('utf-8'))
        except (KeyError, ValueError, zipfile.BadZipFile): raise bad
        if not isinstance(manifest, dict) or manifest.get('format') != 'zook-pack' or not isinstance(manifest.get('skills'), list) or not isinstance(manifest.get('connectors'), list): raise bad
        if manifest.get('version') != 1: raise ValueError('這個設定包是較新版的 Zook 匯出的，請先更新 Zook。')
        if len(infos) > 20000: raise bad
        home = skills_home(store)
        for item in manifest['skills'][:1024]:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(item.get('folder'))): continue
            prefix = 'skills/%s/' % item['folder']; temp = pathlib.Path(tempfile.mkdtemp(prefix='.incoming-', dir=str(home)))
            try:
                total = count = 0
                for info in infos:
                    if not info.filename.startswith(prefix) or info.is_dir(): continue
                    parts = info.filename[len(prefix):].split('/'); count += 1
                    if '\\' in info.filename or any(x in ('', '.', '..') or x in SKILL_SKIP for x in parts) or (info.external_attr >> 16) & 0o170000 == 0o120000 or count > SKILL_FILES: raise ValueError()
                    with z.open(info) as source: content = source.read(SKILL_BYTES - total + 1)
                    total += len(content)
                    if total > SKILL_BYTES: raise ValueError()
                    out = temp.joinpath(*parts); out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(content)
                    if (info.external_attr >> 16) & 0o111: out.chmod(0o755)
                if not (temp / 'SKILL.md').is_file(): raise ValueError()
                name, _ = skill_title(temp, item['name'][:200])
                with store.lock: have = {same_name(x['name']) for x in store.data['skills']}; taken = {x['folder'].lower() for x in store.data['skills']}
                if same_name(name) in have: raise KeyError(name)
                folder = skill_folder(name, taken); os.replace(str(temp), str(home / folder))
            except KeyError: shutil.rmtree(str(temp), ignore_errors=True); result['skipped'].append(item['name'][:200]); continue
            except (ValueError, OSError, zipfile.BadZipFile, RuntimeError): shutil.rmtree(str(temp), ignore_errors=True); result['skipped'].append(item['name'][:200]); continue
            record = dict(id=ID(), name=name, folder=folder, origin='pack', originPath='', stamp='')
            with store.lock:
                store.data['skills'].append(record)
                if item.get('on') is False: store.data['settings']['disabledSkills'].append(ZOOK_SKILL + record['id'])
                store.save()
            result['skills'].append(name)
        for item in manifest['connectors'][:200]:
            if not isinstance(item, dict): continue
            try:
                record, _ = connector_fields(dict(name=item.get('name'), transport=item.get('transport'), command=item.get('command'), url=item.get('url'), env=item.get('env') or {}))
                headers, more, secret_name = item.get('headers') or {}, item.get('moreSecrets') or [], item.get('secretName') or ''
                if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', k) or len(v) > 2000 or '\n' in v or '\r' in v
                                                       or k.lower() == 'authorization' or runtime_module().SECRET_KEY.search(k) for k, v in headers.items()): raise ValueError()
                if not isinstance(more, list) or len(more) > 20 or any(not isinstance(k, str) or not ENV_NAME.fullmatch(k) for k in more): raise ValueError()
                if not isinstance(secret_name, str) or (secret_name and not ENV_NAME.fullmatch(secret_name)): raise ValueError()
            except ValueError: result['skipped'].append(str(item.get('name'))[:80]); continue
            record['headers'] = headers; record['moreSecrets'] = {k: '' for k in more}
            record['secretName'] = ('Authorization' if secret_name else '') if record['transport'] == 'http' else secret_name
            waiting = bool(record['secretName'] or more)
            with store.lock:
                if any(same_name(c['name']) == same_name(record['name']) for c in store.data['connectors']): result['skipped'].append(record['name']); continue
                store.data['connectors'].append(record)
                if item.get('on') is True and not waiting:
                    st = store.data['settings']; st['sharedMcp'] = list(dict.fromkeys((st.get('sharedMcp') or []) + ['zook:' + record['id']]))
                store.save()
            result['connectors'].append(record['name'])
            if waiting: result['needKeys'].append(record['name'])
    return result


def inventory_for(store):
    """Discovered Skills/MCP minus anything from disabled plugins (also removed from the private config)."""
    data = runtime_module().discover()
    with store.lock: own = copy.deepcopy(store.data.get('connectors') or []); gmail = dict(store.data['settings'].get('gmail') or {})
    # Built-in Gmail: listed always, usable once an address and app password have been saved.
    item = {'id': GMAIL_ID, 'name': 'Gmail', 'source': 'builtin', 'transport': 'stdio', 'status': 'configured', 'gmail': True, 'address': gmail.get('address', ''),
            'needsSetup': not gmail.get('address')}
    password = secret_get(gmail['secretId']) if gmail.get('secretId') else ''
    if gmail.get('address') and password:
        data['_private']['mcp'][GMAIL_ID] = dict(transport='stdio', command=sys.executable, args=[str(pathlib.Path(__file__).with_name('gmail_mcp.py'))],
                                                 env={'ZOOK_GMAIL_ADDRESS': gmail['address'], 'ZOOK_GMAIL_PASSWORD': password})
    else: item['needsSetup'] = True
    data['mcp'].insert(1, item)
    with store.lock: google = dict(store.data['settings'].get('google') or {})
    access = google_access(store) if google else ''
    data['mcp'].insert(2, {'id': GOOGLE_ID, 'name': 'Google（Gmail、行事曆、雲端硬碟）', 'source': 'builtin', 'transport': 'stdio', 'status': 'configured', 'google': True,
                           'address': google.get('email', ''), 'write': bool(google.get('write')), 'needsSetup': not access, 'needsLogin': bool(google) and not access})
    if access:
        data['_private']['mcp'][GOOGLE_ID] = dict(transport='stdio', command=sys.executable, args=[str(pathlib.Path(__file__).with_name('google_mcp.py'))],
                                                  env=dict({'ZOOK_GOOGLE_TOKEN': access, 'ZOOK_GOOGLE_WRITE': '1' if google.get('write') else '0'},
                                                           **({'ZOOK_GOOGLE_API': os.environ['ZOOK_GOOGLE_API']} if os.environ.get('ZOOK_GOOGLE_API') else {})))
    for record in own:  # Connectors added in Zook itself; they do not depend on any other app's settings.
        ident = 'zook:' + record['id']; secret = secret_get(record['secretId']) if record.get('secretId') else ''
        if record['transport'] == 'stdio':
            parts = shlex.split(record['command'])
            config = dict(transport='stdio', command=parts[0], args=parts[1:], env=dict(record.get('env') or {}))
            if secret and record.get('secretName'): config['env'][record['secretName']] = secret
        else:
            config = dict(transport='http', url=record['url'], headers=dict(record.get('headers') or {}))
            if secret: config['headers']['Authorization'] = 'Bearer ' + secret
            elif record.get('oauth'):
                access = oauth_access(store, record)
                if access: config['headers']['Authorization'] = 'Bearer ' + access
        waiting = bool(record.get('secretName')) and not secret  # brought in from a pack: the key has not been pasted yet
        for key, sid in (record.get('moreSecrets') or {}).items():
            value = secret_get(sid) if sid else ''
            if value and record['transport'] == 'stdio': config['env'][key] = value
            elif not value: waiting = True
        data['_private']['mcp'][ident] = config
        data['mcp'].insert(3 + own.index(record), {'id': ident, 'name': record['name'], 'source': 'zook', 'transport': record['transport'], 'status': 'configured',
                            'editable': True, 'config': connector_view(record), 'needsKey': waiting,
                            'canLogin': record['transport'] == 'http' and not record.get('secretName') and not secret,
                            'signedIn': bool(record.get('oauth')) and 'Authorization' in config.get('headers', {}),
                            'needsLogin': bool(record.get('oauth')) and 'Authorization' not in config.get('headers', {})})
    copied = {record.get('origin') for record in own if record.get('origin')}
    for item in data['mcp']:
        if item['id'] in copied: item['copied'] = True  # Zook now has its own copy, so this one is no longer handed to Bots
        elif item.get('source') in ('codex', 'claude'): item['copyable'] = True
    with store.lock: mine = copy.deepcopy(store.data.get('skills') or [])
    names = set()
    for record in mine:  # Skills kept in Zook's own folder; they stay even when the tool they came from is removed
        root = store.dir / 'skills' / record['folder']
        if not (root / 'SKILL.md').is_file(): continue
        name, description = skill_title(root, record['name']); ident = ZOOK_SKILL + record['id']
        data['_private']['skills'][ident] = {'path': str(root / 'SKILL.md'), 'root': str(root), 'shared': record.get('origin') == 'shared'}
        data['skills'].append({'id': ident, 'name': name, 'description': description[:1500], 'path': str(root / 'SKILL.md'), 'source': 'zook', 'origin': record.get('origin', ''), 'removable': True})
        names.add(same_name(name))
    for item in data['skills']:
        if item['source'] != 'zook' and same_name(item['name']) in names: item['imported'] = True
    data['skills'].sort(key=lambda x: (x['name'].lower(), x['id']))
    with store.lock: off = set(store.data['settings'].get('disabledPlugins') or [])
    for plugin in data.get('plugins', []): plugin['enabled'] = plugin['id'] not in off
    for key in ('skills', 'mcp'):
        drop = {x['id'] for x in data[key] if x.get('plugin') in off}
        data[key] = [x for x in data[key] if x['id'] not in drop]
        for ident in drop: data['_private'][key].pop(ident, None)
    return data


# Official icons come from apps already installed on this Mac (or icon files shipped inside a plugin).
# Nothing is downloaded; items without a match keep their letter badge.
_APPS = [pathlib.Path('/Applications'), pathlib.Path.home() / 'Applications', pathlib.Path.home() / 'Applications/Chrome Apps.localized']
ICON_APPS = {'word': 'Microsoft Word', 'excel': 'Microsoft Excel', 'powerpoint': 'Microsoft PowerPoint', 'outlook': 'Microsoft Outlook',
             'onenote': 'Microsoft OneNote', 'gdocs': 'Google Docs', 'gsheets': 'Google Sheets', 'gslides': 'Google Slides', 'gdrive': 'Google Drive',
             'zoom': 'zoom.us', 'obsidian': 'Obsidian', 'telegram': 'Telegram', 'claude': 'Claude', 'chatgpt': 'ChatGPT', 'grok': 'Grok Bot'}
# Official icons bundled with Zook (frontend/icons), downloaded once from each vendor's own site.
BUNDLED_ICONS = {'gmail', 'gcalendar', 'gchat', 'gcontacts', 'notebooklm', 'gemini', 'perplexity', 'asana', 'nodejs'}
ICON_RULES = [('gmail', r'gmail'), ('gcalendar', r'google ?calendar|gcal'), ('gchat', r'google ?chat'), ('gcontacts', r'google ?(people|contacts)'),
              ('notebooklm', r'notebooklm'), ('gemini', r'gemini'), ('perplexity', r'perplexity'), ('asana', r'asana'), ('nodejs', r'\bnode(js|_repl|\b)'),
              ('figma', r'figma'), ('gdocs', r'google ?docs|gdocs'), ('gsheets', r'google ?sheets|gsheets'),
              ('gslides', r'google ?slides|logi-slide|gslides'), ('gdrive', r'gdrive|google ?drive'), ('word', r'\bdocx\b|\bword\b'),
              ('excel', r'\bxlsx\b|\bexcel\b'), ('powerpoint', r'pptx|powerpoint'), ('outlook', r'outlook'), ('onenote', r'onenote'),
              ('zoom', r'\bzoom\b'), ('obsidian', r'obsidian'), ('telegram', r'telegram')]


def icon_source(key):
    if key == 'figma':
        found = sorted(pathlib.Path.home().glob('.claude/plugins/cache/*/figma/*/Figma Icon (Full-color).svg'))
        return found[-1] if found else None
    name = ICON_APPS.get(key)
    if not name: return None
    return next((d / (name + '.app') for d in _APPS if (d / (name + '.app')).is_dir()), None)


def icon_tool():
    env = os.environ.get('ZOOK_ICON_TOOL')
    if env: return pathlib.Path(env)
    return pathlib.Path(__file__).resolve().parents[2] / 'MacOS' / 'zook-icon'


_icon_keys = {}


def icon_for(name):
    text = str(name or '').lower()
    key = next((k for k, pattern in ICON_RULES if re.search(pattern, text)), None)
    if not key: return None
    if key in BUNDLED_ICONS: return '/icons/%s.png' % key
    if key not in _icon_keys: _icon_keys[key] = bool(icon_source(key)) and icon_tool().is_file()
    return '/api/icons/' + key if _icon_keys[key] else None


def icon_png(store, key):
    """PNG bytes for a known icon key, rendered once and cached in the data folder."""
    if key not in ICON_APPS and key != 'figma': return None
    cache = store.dir / 'icons'; cache.mkdir(exist_ok=True, mode=0o700)
    out = cache / (key + '.png')
    if not out.is_file():
        source, tool = icon_source(key), icon_tool()
        if not source or not tool.is_file(): return None
        try: subprocess.run([str(tool), str(source), str(out), '128'], timeout=20, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError, OSError): return None
    try: return out.read_bytes()
    except OSError: return None


def integrations(store):
    data = inventory_for(store)
    with store.lock: on = set(store.data['settings'].get('sharedMcp') or []); records = {ZOOK_SKILL + x['id']: dict(x) for x in store.data.get('skills') or []}
    connectors = [(re.sub(r'[^a-z0-9]', '', m['name'].lower()), m['id'] in on and not (m.get('needsSetup') or m.get('needsKey') or m.get('copied'))) for m in data['mcp']]
    for item in data['skills']:
        if item.get('imported'): continue
        notes = skill_notes(data['_private']['skills'].get(item['id'], {}).get('path', ''), connectors)
        if notes: item['notes'] = notes
        record = records.get(item['id'])
        if record and record.get('originPath') and record.get('stamp') and os.path.isfile(os.path.join(record['originPath'], 'SKILL.md')):
            item['canUpdate'] = skill_stamp(record['originPath']) != record['stamp']
    with_icons = lambda items, field: [dict(x, icon=icon_for(x.get(field)) or icon_for(x.get('plugin', '')) ) for x in items]
    return dict(skills=with_icons(data['skills'], 'name'), mcp=with_icons(data['mcp'], 'name'), plugins=with_icons(data.get('plugins', []), 'displayName'), providers=provider_info())


def validate_selection(bot, inventory):
    for field, key in [('enabledMcp', 'mcp')]:
        values = bot.get(field, [])
        ids = {x['id'] for x in inventory[key]}
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(x, str) or x not in ids for x in values) or len(set(values)) != len(values):
            raise ValueError('所選整合項目不存在或重複：' + field)
    if not isinstance(bot.get('allowCommands', False), bool): raise ValueError('allowCommands 無效。')


def usage():
    # Session archives are bounded; only aggregate numeric metadata is returned.
    groups, examined, truncated, session_count = {}, 0, False, 0
    patterns = [(str(pathlib.Path.home()/'.codex/sessions/*/*/*/*.jsonl'), 'codex'),
                (str(pathlib.Path.home()/'.claude/projects/*/*.jsonl'), 'claude')]
    files = []
    for pattern, provider in patterns:
        for file in glob.iglob(pattern):
            try: files.append((os.path.getmtime(file), file, provider))
            except OSError: pass
    files.sort(reverse=True)
    if len(files) > 500: truncated = True
    def valid_number(value):
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**15
    def add(key, inp, out):
        date, provider, model = key
        group = groups.setdefault(key, dict(date=date, provider=provider, model=model, sessions=0, inputTokens=0, outputTokens=0, cost=None))
        group['inputTokens'] += inp; group['outputTokens'] += out
    for _, file, provider in files[:500]:
        try:
            if os.path.getsize(file) > 10 * 1024 * 1024: truncated = True; continue
            seen, previous, model, messages = set(), None, 'unknown', {}
            with open(file, encoding='utf-8') as f:
                for line in f:
                    examined += len(line.encode('utf-8'))
                    if examined > 40 * 1024 * 1024: truncated = True; break
                    try: event = json.loads(line)
                    except ValueError: continue
                    if not isinstance(event, dict): continue
                    date = str(event.get('timestamp', ''))[:10]
                    try: datetime.date.fromisoformat(date)
                    except ValueError: continue
                    if provider == 'codex':
                        payload = event.get('payload'); payload = payload if isinstance(payload, dict) else {}
                        if event.get('type') == 'turn_context':
                            candidate = payload.get('model')
                            if isinstance(candidate, str) and candidate: model = candidate[:100]
                        info = payload.get('info'); info = info if isinstance(info, dict) else {}
                        u = info.get('total_token_usage'); u = u if isinstance(u, dict) else {}
                        if payload.get('type') != 'token_count': continue
                        inp, out = u.get('input_tokens'), u.get('output_tokens')
                        if not valid_number(inp) or not valid_number(out): continue
                        # Repeated snapshots add zero. A reset starts a new cumulative sequence.
                        if previous is None or inp < previous[0] or out < previous[1]: delta = (inp, out)
                        else: delta = (inp - previous[0], out - previous[1])
                        previous = (inp, out)
                        if delta == (0, 0): continue
                        key = (date, provider, model); add(key, *delta); seen.add(key)
                    else:
                        msg = event.get('message'); msg = msg if isinstance(msg, dict) else {}
                        u = msg.get('usage'); u = u if isinstance(u, dict) else {}
                        if event.get('type') != 'assistant' or not u: continue
                        numbers = [u.get(k, 0) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')]
                        if not all(valid_number(x) for x in numbers): continue
                        inp, out = sum(numbers[:3]), numbers[3]
                        if inp == 0 and out == 0: continue
                        candidate = msg.get('model'); model = candidate[:100] if isinstance(candidate, str) and candidate else 'unknown'
                        # Stream records repeat a cumulative usage snapshot for each message ID.
                        mid = msg.get('id'); req = event.get('requestId') or event.get('request_id')
                        if isinstance(mid, str) and mid: ident = ('message', mid)
                        elif isinstance(req, str) and req: ident = ('request', req)
                        else: ident = ('line', examined)
                        old = messages.get(ident)
                        if old: messages[ident] = (old[0], max(old[1], inp), max(old[2], out))
                        else: messages[ident] = ((date, provider, model), inp, out)
            for key, inp, out in messages.values(): add(key, inp, out); seen.add(key)
            for key in seen: groups[key]['sessions'] += 1
            if seen: session_count += 1
            if examined > 40 * 1024 * 1024: break
        except (OSError, UnicodeError): continue
    return dict(groups=sorted(groups.values(), key=lambda x: x['date'], reverse=True), sessionCount=session_count, truncated=truncated, cost=None,
                note='依有限範圍內可讀的本機 session 紀錄統計；模型可能未知。金額未估算。')


def clean_model(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value) else None


def normalize_models(items, source):
    result, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get('hidden') is True or item.get('visibility') in ('hide', 'hidden'): continue
        mid = clean_model(item.get('id') or item.get('slug') or item.get('model'))
        if not mid or mid in seen: continue
        name = item.get('displayName') or item.get('display_name') or mid
        if not isinstance(name, str) or len(name) > 128 or not re.fullmatch(r'[\w .:/()+-]+', name): name = mid
        result.append(dict(id=mid, name=name, source=source)); seen.add(mid)
    return result


def codex_models_cli(binary):
    # model/list reads metadata only; no model generation or conversation is started.
    result = codex_rpc(binary, 'model/list', {'limit': 100, 'includeHidden': False})
    return normalize_models(result.get('data', []) if isinstance(result, dict) else [], 'cli')


def codex_rpc(binary, method, params, env=None):
    """One read-only JSON-RPC call to a short-lived `codex app-server`."""
    proc = subprocess.Popen([binary, 'app-server', '--listen', 'stdio://'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True, env=env)
    messages = queue.Queue(maxsize=128)
    def read_output():
        try:
            for line in proc.stdout:
                if len(line) > MAX_BODY: break
                try: messages.put_nowait(json.loads(line))
                except (ValueError, queue.Full): break
        except (OSError, ValueError): pass
    threading.Thread(target=read_output, daemon=True).start()
    def send(message):
        proc.stdin.write((json.dumps(message)+'\n').encode()); proc.stdin.flush()
    def response(request_id, timeout=7):
        deadline = __import__('time').monotonic() + timeout
        while True:
            remaining = deadline - __import__('time').monotonic()
            if remaining <= 0: raise TimeoutError()
            try: item = messages.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                if proc.poll() is not None and messages.empty(): raise TimeoutError()
                continue
            if isinstance(item, dict) and item.get('id') == request_id:
                if 'error' in item: raise ValueError('model request failed')
                return item.get('result')
    try:
        send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'clientInfo':{'name':'swarmr','version':'1.0.0'}}})
        response(1)
        send({'jsonrpc':'2.0','method':'initialized','params':{}})
        send({'jsonrpc':'2.0','id':2,'method':method,'params':params})
        return response(2)
    finally:
        try: os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: proc.wait(timeout=1)
            except subprocess.TimeoutExpired: pass
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        if proc.stdin: proc.stdin.close()
        if proc.stdout: proc.stdout.close()


def model_list(provider):
    binary = find_cli(provider); models = []; source = 'none'
    s = P.spec(_active['data'], provider) or {}
    if s.get('kind') == 'grok':
        if binary:
            try:
                out = subprocess.run([binary, 'models'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20).stdout
                models = [dict(id=m, name=m, source='cli') for m in P.parse_grok_models(ANSI.sub('', out.decode('utf-8', 'replace'))) if clean_model(m)]
            except (OSError, subprocess.SubprocessError): pass
        source = 'cli' if models else 'none'
        note = '由 grok models 取得。' if models else '無法取得 Grok 模型清單，請確認已安裝 Grok CLI。'
        return dict(provider=provider, models=models, source=source, status='available' if models else 'unavailable', note=note, detectedAt=NOW())
    if s.get('kind') == 'antigravity':
        if binary:
            try:
                out = subprocess.run([binary, 'models'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=25).stdout.decode('utf-8', 'replace')
                for line in ANSI.sub('', out).splitlines():
                    parts = line.strip().split('\t')
                    if len(parts) == 2 and clean_model(parts[0]): models.append(dict(id=parts[0], name=parts[1], source='cli'))
            except (OSError, subprocess.SubprocessError): pass
        return dict(provider=provider, models=models, source='cli' if models else 'none', status='available' if models else 'unavailable',
                    note='由 agy models 取得。' if models else '無法取得 Antigravity 模型清單，請確認已登入。', detectedAt=NOW())
    if s.get('kind') == 'generic':
        models = [dict(id=m, name=m, source='config') for m in s.get('models', []) if clean_model(m)]
        note = '來自這個提供者的設定；也可以輸入自訂模型 ID。' if models else '沒有設定模型清單，請輸入模型 ID，或留空使用 CLI 預設。'
        return dict(provider=provider, models=models, source='config' if models else 'none', status='available' if models else 'unavailable', note=note, detectedAt=NOW())
    if provider == 'codex':
        if binary:
            try: models = codex_models_cli(binary)
            except (OSError, ValueError, TimeoutError, BrokenPipeError): pass
        if models: source = 'cli'; note = '由本機 Codex 服務取得模型清單；個別模型的使用權限尚未測試。'
        else:
            try:
                cache = pathlib.Path.home()/'.codex/models_cache.json'
                if cache.stat().st_size > 8 * 1024 * 1024: raise ValueError()
                data = json.loads(cache.read_text(encoding='utf-8'))
                models = normalize_models(data.get('models', []) if isinstance(data, dict) else [], 'cache')
            except (OSError, UnicodeError, ValueError): pass
            if models: source = 'cache'; note = '使用本機快取；目前帳號可用性未確認。'
            else: note = '無法取得模型清單，請檢查 Codex 安裝與登入。'
    else:
        aliases = []
        if binary:
            try:
                help_result = subprocess.run([binary, '--help'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=4, check=True)
                help_text = help_result.stdout[:131072].decode('utf-8', errors='replace')
                example = re.search(r"an alias for the latest model.*?model's full name", help_text, re.S)
                if example: aliases = re.findall(r"'([A-Za-z0-9_-]+)'", example.group(0))
            except (OSError, subprocess.SubprocessError): pass
        models = [dict(id=x, name=x, source='alias') for x in dict.fromkeys(aliases) if clean_model(x)]
        seen = {x['id'] for x in models}
        files = []
        for f in glob.iglob(str(pathlib.Path.home()/'.claude/projects/*/*.jsonl')):
            try: files.append((os.path.getmtime(f), f))
            except OSError: pass
        files.sort(reverse=True); consumed = 0
        for _, filename in files[:50]:
            try:
                if os.path.getsize(filename) > 2*1024*1024: continue
                with open(filename, encoding='utf-8') as f:
                    for line in f:
                        consumed += len(line)
                        if consumed > 5*1024*1024: break
                        try: event = json.loads(line)
                        except ValueError: continue
                        if not isinstance(event, dict) or event.get('type') != 'assistant': continue
                        message = event.get('message'); message = message if isinstance(message, dict) else {}
                        mid = clean_model(message.get('model'))
                        if mid and mid not in seen and mid != '<synthetic>':
                            models.append(dict(id=mid, name=mid, source='cache')); seen.add(mid)
                if consumed > 5*1024*1024: break
            except (OSError, UnicodeError): continue
        source = 'alias' if aliases else ('cache' if models else 'none')
        note = '別名來自 CLI 說明，其他名稱來自本機紀錄；目前帳號可用性未確認。' if models else '無法取得 Claude 模型名稱，請檢查 CLI 安裝。'
    return dict(provider=provider, models=models, source=source, status='available' if models else 'unavailable', note=note, detectedAt=NOW())


class Busy(Exception): pass


SCHEDULE_WEEKLY = dict(daily=range(7), weekdays=range(5), mon=[0], tue=[1], wed=[2], thu=[3], fri=[4], sat=[5], sun=[6])
SCHEDULE_REPEATS = set(SCHEDULE_WEEKLY) | {'once', 'hourly', 'monthly'}


def schedule_fields(store, body, record):
    """Check and apply what the schedule form sends. Times are the Mac's local time."""
    # A schedule talks to one Bot or one group, never both.
    if body.get('groupId'):
        if not store.find('groups', body['groupId']): raise ValueError('找不到這個群組。')
        record.update(groupId=body['groupId'], botId='')
    elif body.get('botId') or 'botId' in body:
        if not store.find('bots', body['botId']): raise ValueError('找不到這個 Bot。')
        record.update(botId=body['botId'], groupId='')
    if 'content' in body:
        if not isinstance(body['content'], str) or not body['content'].strip() or len(body['content']) > 30000: raise ValueError('請填寫要 Bot 做的事。')
        record['content'] = body['content'].strip()
    if 'time' in body:
        if not isinstance(body['time'], str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', body['time']): raise ValueError('時間格式無效。')
        record['time'] = body['time']
    if 'repeat' in body:
        if body['repeat'] not in SCHEDULE_REPEATS: raise ValueError('重複方式無效。')
        record['repeat'] = body['repeat']
    if 'date' in body:
        try: record['date'] = datetime.datetime.strptime(str(body['date']), '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError: raise ValueError('日期無效。')
    if 'day' in body:
        if type(body['day']) is not int or not 1 <= body['day'] <= 31: raise ValueError('每月的日期無效。')
        record['day'] = body['day']
    for key in ('on', 'catchUp'):
        if key in body:
            if not isinstance(body[key], bool): raise ValueError('設定無效。')
            record[key] = body[key]
    if not (record.get('botId') or record.get('groupId')) or not record.get('content') or not record.get('time'): raise ValueError('請選擇 Bot 或群組、填寫內容和時間。')
    now = datetime.datetime.now()
    if record.get('repeat') == 'monthly' and not record.get('day'): raise ValueError('請選擇每月幾號。')
    if record.get('repeat') == 'once':
        if not record.get('date'): raise ValueError('請選擇日期。')
        if record.get('on') and datetime.datetime.strptime(record['date'] + ' ' + record['time'], '%Y-%m-%d %H:%M') <= now:
            raise ValueError('這個時間已經過了，請改日期或時間。')
    if record.get('on'): record.pop('done', None)
    record['since'] = now.isoformat()  # only times after this moment count
    return record


SCHEDULE_HISTORY = 20
MAX_SCHEDULES = 50
SCHEDULE_TOOLS = ('zook_create_schedule', 'zook_update_schedule', 'zook_delete_schedule')
REPEAT_NAMES = dict(daily='每天', weekdays='週一到週五', mon='每週一', tue='每週二', wed='每週三', thu='每週四', fri='每週五', sat='每週六', sun='每週日',
                    hourly='每小時', monthly='每月', once='只一次')


def schedule_when(item):
    """When a schedule runs, in words."""
    repeat, at = item.get('repeat'), item.get('time') or ''
    if repeat == 'hourly': return '每小時的 %s 分' % at[3:]
    if repeat == 'monthly': return '每月 %s 號 %s' % (item.get('day'), at)
    if repeat == 'once': return '%s %s（只一次）' % (item.get('date'), at)
    return '%s %s' % (REPEAT_NAMES.get(repeat, '每天'), at)


def schedule_target_name(store, item):
    found = store.find('groups', item['groupId']) if item.get('groupId') else store.find('bots', item.get('botId'))
    return found['name'] if found else '已刪除的對象'


def schedule_tool_body(store, bot, group_id, args, creating):
    """What a Bot's schedule tool asks for, in the shape the schedule form sends. Lock held."""
    body = {}
    target = str(args.get('target') or '').strip()
    if target:
        bots = [b for b in store.data['bots'] if b['name'].strip().lower() == target.lower()]
        groups = [g for g in store.data['groups'] if g['name'].strip().lower() == target.lower()]
        if bots and groups: raise RuntimeError('「%s」同時是 Bot 和群組的名稱，請說清楚是哪一個。' % target)
        if not bots and not groups: raise RuntimeError('找不到名為「%s」的 Bot 或群組。' % target)
        body['groupId' if groups else 'botId'] = (groups or bots)[0]['id']
    elif creating:  # by default: the conversation the request came from
        body['groupId' if group_id else 'botId'] = group_id or bot['id']
    for key in ('content', 'repeat', 'time', 'date'):
        if key in args: body[key] = args[key]
    if 'day' in args:
        try: body['day'] = int(str(args['day']).strip())
        except ValueError: raise RuntimeError('day 要是 1 到 31 的數字。')
    if 'enabled' in args:
        if args['enabled'] not in ('on', 'off'): raise RuntimeError('enabled 只能是 on 或 off。')
        body['on'] = args['enabled'] == 'on'
    return body


def describe_schedule_call(store, bot, group_id, name, args):
    """The approval card's sentence for a schedule tool: what will be created, changed or deleted."""
    try:
        if name == 'zook_create_schedule':
            body = schedule_tool_body(store, bot, group_id, args, True)
            item = dict(body, groupId=body.get('groupId', ''), botId=body.get('botId', ''))
            return '建立排程：%s，在「%s」執行「%s」' % (schedule_when(item), schedule_target_name(store, item), str(args.get('content') or '')[:80])
        item = store.find('schedules', args.get('schedule_id'))
        if not item: return '修改排程' if name == 'zook_update_schedule' else '刪除排程'
        what = '「%s」（%s）' % (item.get('content', '')[:40], schedule_when(item))
        if name == 'zook_delete_schedule': return '刪除排程' + what
        body = schedule_tool_body(store, bot, group_id, args, False)
        after = dict(item, **{k: v for k, v in body.items() if k in ('repeat', 'time', 'date', 'day')})
        changes = []
        if schedule_when(after) != schedule_when(item): changes.append('改成' + schedule_when(after))
        if 'content' in body: changes.append('內容改成「%s」' % str(body['content'])[:60])
        if 'botId' in body or 'groupId' in body: changes.append('對象改成「%s」' % schedule_target_name(store, dict(groupId=body.get('groupId', ''), botId=body.get('botId', ''))))
        if 'on' in body: changes.append('啟用' if body['on'] else '停用')
        return '修改排程' + what + ('，' + '、'.join(changes) if changes else '')
    except (RuntimeError, ValueError, TypeError, KeyError):
        return {'zook_create_schedule': '建立排程', 'zook_update_schedule': '修改排程'}.get(name, '刪除排程')


def schedule_instructions():
    now = datetime.datetime.now()
    return ('\n排程：使用者要你在固定時間、定期或之後某個時間做事時，用 zook_create_schedule 建立排程，不要說你做不到；Zook 會先請使用者核准。'
            '在群組裡沒有指定對象時，排程建給這個群組。用 zook_list_schedules 查看現有排程，zook_update_schedule、zook_delete_schedule 修改或刪除。'
            '現在是這台 Mac 的 %s（週%s），時間一律用這台 Mac 的時間。' % (now.strftime('%Y-%m-%d %H:%M'), '一二三四五六日'[now.weekday()]))
MAX_NOTICES = 100


def schedule_approval_wait():
    try: return float(os.environ.get('ZOOK_SCHEDULE_APPROVAL_WAIT') or SCHEDULE_APPROVAL_WAIT)
    except ValueError: return SCHEDULE_APPROVAL_WAIT


def tool_wait(scheduled):
    """How long a CLI waits on one Zook tool call: the approval wait plus room for the tool itself."""
    return int(schedule_approval_wait() + 600) if scheduled else APPROVAL_TIMEOUT + 60


def describe_send(label, args):
    """The approval card's sentence for sending mail: who gets it and the subject."""
    if str(label or '').lower().replace('-', '_') not in SEND_TOOLS or not isinstance(args, dict) or not args.get('to'): return None
    to = args['to'] if isinstance(args['to'], list) else [args['to']]
    return '寄信給 %s，主旨「%s」' % ('、'.join(str(x) for x in to[:5]), str(args.get('subject') or '')[:80])


def first_sentence(text, limit=120):
    """The first sentence of a reply, without Markdown marks, for a notification."""
    for line in re.sub(r'[*_`>#|]+', '', text or '').splitlines():
        line = line.strip(' -•\t')
        if not line: continue
        found = re.match(r'(.+?(?:[。！？!?]|\.(?=\s|$)))', line)
        line = found.group(1) if found else line
        return line if len(line) <= limit else line[:limit - 1] + '…'
    return ''


def schedule_add_run(item, run):
    """Keep the schedule's most recent runs: when, how it went and where the conversation is."""
    run = dict(run, id=ID(), at=NOW())
    item['runs'] = ((item.get('runs') or []) + [run])[-SCHEDULE_HISTORY:]
    return run


def schedule_last_due(item, now):
    """The most recent moment this schedule was meant to run, at or before now (local time)."""
    hour, minute = int(item['time'][:2]), int(item['time'][3:])
    repeat = item.get('repeat')
    if repeat == 'hourly':
        moment = now.replace(minute=minute, second=0, microsecond=0)
        return moment if moment <= now else moment - datetime.timedelta(hours=1)
    if repeat == 'once':
        try: moment = datetime.datetime.strptime('%s %s' % (item.get('date'), item['time']), '%Y-%m-%d %H:%M')
        except ValueError: return None
        return moment if moment <= now else None
    if repeat == 'monthly':
        year, month = now.year, now.month
        for _ in range(2):
            moment = datetime.datetime(year, month, min(int(item.get('day') or 1), calendar.monthrange(year, month)[1]), hour, minute)
            if moment <= now: return moment
            year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        return None
    days = SCHEDULE_WEEKLY.get(repeat, range(7))
    for back in range(8):
        moment = (now - datetime.timedelta(days=back)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment <= now and moment.weekday() in days: return moment
    return None


