# Checking what the window sends before it is saved: group settings, Bot settings, app settings, knowledge.
# Loaded by backend/server.py into one shared namespace.
def set_group_fields(store, group, body, creating=False):
    old_host = group_host(store, group) if group.get('botIds') else None
    if 'botIds' in body or creating:
        ids = body.get('botIds')
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids): raise ValueError('成員無效。')
        ids = list(dict.fromkeys(ids))
        if not GROUP_MIN_BOTS <= len(ids) <= GROUP_MAX_BOTS: raise ValueError('群組需要 %d 到 %d 個 Bot。' % (GROUP_MIN_BOTS, GROUP_MAX_BOTS))
        if any(not store.find('bots', x) for x in ids): raise ValueError('找不到所選的 Bot。')
        if group.get('status') == 'running' and ids != group['botIds']: raise ValueError('群組討論進行中，暫時無法修改成員。')
        group['botIds'] = ids
    if 'hostId' in body:
        if body['hostId'] != '' and body['hostId'] not in group['botIds']: raise ValueError('主持人要是這個群組的成員。')
        group['hostId'] = body['hostId']
    if old_host and old_host not in group['botIds'] and not (body.get('hostId') in group['botIds']): drop_group_host(store, group)
    if 'mode' in body:
        if body['mode'] not in GROUP_MODES or (body['mode'] == 'auto' and not task_on(store)): raise ValueError('討論方式無效。')
        group['mode'] = body['mode']
    if group.get('mode') == 'auto' and ('mode' in body or 'hostId' in body):  # chosen now: a host gone on its own already turned it back to 自由 (#218)
        if not (group_host(store, group) if 'hostId' in group or not creating else None): raise ValueError('「自動」討論方式要由主持人拆工作、派給成員，請在「主持人」選一位成員，或改用其他討論方式。')
        if len([x for x in group['botIds'] if store.find('bots', x)]) < 2: raise ValueError('「自動」討論方式至少要 2 位成員，請再加一位成員。')
    if 'turnLimit' in body:
        if body['turnLimit'] not in GROUP_LIMITS: raise ValueError('回合上限無效。')
        group['turnLimit'] = body['turnLimit']
    if 'name' in body:
        name = body['name']
        if not isinstance(name, str) or len(name) > 100: raise ValueError('名稱無效。')
        group['name'] = name.strip()
    if not group.get('name'):
        group['name'] = '、'.join(store.find('bots', x)['name'] for x in group['botIds'])[:100]


# What a field is called on screen, for a refusal in plain words (#156): 「名稱不能是空白。」「工作指示最多 10,000 字。」
FIELD_WORDS = {'name': '名稱', 'color': '顏色', 'shape': '形狀', 'instructions': '工作指示', 'persona': '人格檔案', 'provider': '模型與帳號', 'model': '模型',
               'section': '分類', 'jobTitle': '職稱', 'title': '標題', 'content': '內容', 'botId': 'Bot'}


def field_words(key, value, limit):
    word = FIELD_WORDS.get(key, key)
    if not isinstance(value, str): return '%s的內容不對，請重新填寫。' % word
    if key == 'name' and not value.strip(): return '名稱不能是空白。'
    return '%s最多 %s 字，目前是 %s 字。' % (word, format(limit, ','), format(len(value), ','))


def update(target, body, kind):
    fields = {'bot': {'name': 100, 'color': 30, 'shape': 30, 'instructions': 10000, 'persona': 20000, 'provider': 20, 'model': 100, 'section': 100, 'jobTitle': 12},
              'settings': {'provider': 20, 'model': 100}, 'knowledge': {'title': 300, 'content': 100000, 'botId': 100}}[kind]
    changes = {}
    for key, limit in fields.items():
        if key in body:
            value = body[key]
            if not isinstance(value, str) or len(value) > limit or (key == 'name' and not value.strip()): raise ValueError(field_words(key, value, limit))
            if key == 'provider' and not ((kind == 'bot' and value in ('', AUTO)) or P.spec(_active['data'], value)): raise ValueError('供應商無效。')
            changes[key] = value.strip() if key == 'jobTitle' else value
    if kind == 'settings' and 'autoModels' in body:
        value = body['autoModels']
        if not isinstance(value, list) or any(x not in AUTO_MODELS for x in value): raise ValueError('自動選擇的模型無效。')
        changes['autoModels'] = list(dict.fromkeys(value))
    if kind == 'settings' and 'autoAccounts' in body:
        value = body['autoAccounts']; extras = {a['id']: a for a in _active['data'].get('accounts') or [] if a.get('provider') in AUTO_MODELS}
        if not isinstance(value, dict) or any(k not in extras or not isinstance(v, bool) for k, v in value.items()): raise ValueError('自動選擇的帳號無效。')
        known = _active['data'].get('autoStatus') or {}
        if any(v and (extras[k].get('type') == 'key' or auto_known_billed(known.get(auto_account_key(extras[k])))) for k, v in value.items()): raise ValueError('API 計費的帳號不會被自動選用。')
        changes['autoAccounts'] = dict(target.get('autoAccounts') or {}, **value)
    if kind == 'bot':
        for key in ('enabledSkills', 'enabledMcp'):
            if key in body:
                value = body[key]
                if not isinstance(value, list) or any(not isinstance(x, str) for x in value): raise ValueError('欄位 %s 無效。' % key)
                changes[key] = value[:]
        if 'allowCommands' in body:
            if not isinstance(body['allowCommands'], bool): raise ValueError('allowCommands 無效。')
            changes['allowCommands'] = body['allowCommands']
    if kind == 'settings' and 'disabledPlugins' in body:
        value = body['disabledPlugins']
        if not isinstance(value, list) or len(value) > 500 or any(not isinstance(x, str) or len(x) > 200 for x in value): raise ValueError('disabledPlugins 無效。')
        changes['disabledPlugins'] = list(dict.fromkeys(value))
    if kind == 'settings' and 'remote' in body:
        value = body['remote']
        if not isinstance(value, dict) or not isinstance(value.get('enabled', False), bool) or not isinstance(value.get('relayUrl', ''), str): raise ValueError('遠端連線設定無效。')
        relay = value.get('relayUrl', '').strip().rstrip('/')
        if relay and not re.fullmatch(r'wss?://[A-Za-z0-9.\-]+(:\d+)?(/[A-Za-z0-9._~/\-]*)?', relay): raise ValueError('中繼伺服器網址要以 wss:// 開頭。')
        if relay.startswith('ws://') and not re.match(r'ws://(127\.0\.0\.1|localhost)(:|/|$)', relay): raise ValueError('中繼伺服器網址要以 wss:// 開頭。')
        if value.get('enabled') and not relay: raise ValueError('請先填入中繼伺服器網址。')
        changes['remote'] = dict(enabled=bool(value.get('enabled')), relayUrl=relay)
    if kind == 'settings' and 'remoteExpiryDays' in body: changes['remoteExpiry'] = remote_expiry_set(target, body['remoteExpiryDays'])
    if kind in ('settings', 'bot') and 'fallbacks' in body:
        value = body['fallbacks']
        if value is None and kind == 'bot': changes['fallbacks'] = None  # follow the default order
        else:
            if not isinstance(value, list) or len(value) > 10 or any(not isinstance(x, str) or not P.spec(_active['data'], x) for x in value): raise ValueError('備用模型無效。')
            changes['fallbacks'] = list(dict.fromkeys(value))
    if kind == 'settings' and 'dirCollapsed' in body:
        value = body['dirCollapsed']
        if not isinstance(value, list) or len(value) > 200 or any(not isinstance(x, str) or len(x) > 200 for x in value): raise ValueError('dirCollapsed 無效。')
        changes['dirCollapsed'] = list(dict.fromkeys(value))
    if kind == 'settings' and 'sharedMcp' in body:
        value = body['sharedMcp']
        if not isinstance(value, list) or len(value) > 200 or any(not isinstance(x, str) or len(x) > 200 for x in value): raise ValueError('sharedMcp 無效。')
        changes['sharedMcp'] = list(dict.fromkeys(value))
    if kind == 'settings' and 'disabledSkills' in body:
        value = body['disabledSkills']
        if not isinstance(value, list) or len(value) > 1000 or any(not isinstance(x, str) or len(x) > 200 for x in value): raise ValueError('disabledSkills 無效。')
        changes['disabledSkills'] = list(dict.fromkeys(value))
    if kind == 'bot' and 'account' in body:
        if body['account'] != '' and not find_account(body['account'] if isinstance(body['account'], str) else None): raise ValueError('帳號無效。')
        changes['account'] = body['account']
    if kind in ('bot', 'settings') and ('access' in body or 'accessFolder' in body):
        access = body.get('access', target.get('access') or ('' if kind == 'bot' and 'access' in target else 'full')); folder = body.get('accessFolder', target.get('accessFolder') or '')
        if access not in ACCESS_SCOPES + (('',) if kind == 'bot' else ()) or not isinstance(folder, str) or len(folder) > 1000: raise ValueError('存取範圍無效。')
        if access == 'folder':
            chosen = pathlib.Path(folder.strip()).expanduser()
            if not folder.strip() or not chosen.is_absolute() or not chosen.is_dir(): raise ValueError('請選擇一個存在的資料夾。')
            folder = str(chosen.resolve())
        changes['access'] = access; changes['accessFolder'] = folder if access == 'folder' else ''
    if 'permissionMode' in body and kind in ('bot', 'settings'):
        allowed = ('manual', 'auto', 'bypass') + (('',) if kind == 'bot' else ())
        if body['permissionMode'] not in allowed: raise ValueError('主動性設定無效。')
        changes['permissionMode'] = body['permissionMode']
    if kind == 'settings' and 'autoUpdateCheck' in body:
        if not isinstance(body['autoUpdateCheck'], bool): raise ValueError('autoUpdateCheck 無效。')
        changes['autoUpdateCheck'] = body['autoUpdateCheck']
    if kind == 'settings' and 'usageDetectEvery' in body:
        value = body['usageDetectEvery']
        if isinstance(value, bool) or value not in USAGE_DETECT_CHOICES: raise ValueError('自動偵測的間隔無效。')
        changes['usageDetectEvery'] = int(value)
    if kind == 'settings' and 'scheduleNotify' in body:
        if not isinstance(body['scheduleNotify'], bool): raise ValueError('scheduleNotify 無效。')
        changes['scheduleNotify'] = body['scheduleNotify']
    if kind == 'settings' and 'webSearch' in body:
        if not isinstance(body['webSearch'], bool): raise ValueError('webSearch 無效。')
        changes['webSearch'] = body['webSearch']
    if kind == 'bot' and 'isAdmin' in body:
        if not isinstance(body['isAdmin'], bool): raise ValueError('isAdmin 無效。')
        changes['isAdmin'] = body['isAdmin']
    if kind in ('bot', 'settings') and 'features' in body:
        value = body['features']
        if not isinstance(value, dict) or any(k not in FEATURES or not isinstance(v, bool) for k, v in value.items()): raise ValueError('特色功能設定無效。')
        changes['features'] = value
    if kind in ('bot', 'settings') and 'effort' in body:
        if body['effort'] not in tuple(EFFORTS) + (('',) if kind == 'bot' else ()): raise ValueError('思考強度無效。')
        changes['effort'] = body['effort']
    if kind == 'bot' and 'scripts' in body:
        if not isinstance(body['scripts'], bool): raise ValueError('scripts 無效。')
        changes['scripts'] = body['scripts']
    if kind == 'bot' and 'pinned' in body:
        if not isinstance(body['pinned'], bool): raise ValueError('pinned 無效。')
        changes['pinned'] = body['pinned']
    if kind == 'knowledge' and 'tags' in body:
        tags = body['tags']
        if not isinstance(tags, list) or len(tags)>30 or any(not isinstance(t, str) or len(t)>100 for t in tags): raise ValueError('標籤無效。')
        changes['tags'] = tags
    if kind == 'settings': upkeep_fields(_active['data'], body, changes)
    if kind == 'bot' and changes.get('provider') == AUTO: changes.update(model='', account='')  # each reply picks its own model
    target.update(changes)
