# What a paired phone can do beyond chatting: look after schedules, send photos, switch conversations.
# Loaded by backend/server.py into one shared namespace.
MOBILE_PHOTOS = 4                 # per message
MOBILE_PHOTO_BYTES = 700 * 1024   # the phone shrinks a photo before sending


def mobile_schedules(store):
    return dict(schedules=[dict(id=x['id'], name=schedule_title(x), content=(x.get('content') or '')[:120], when=schedule_when(x), target=schedule_target_name(store, x), on=bool(x.get('on', True)),
                                group=bool(x.get('groupId'))) for x in store.data['schedules']])


def mobile_schedule_action(store, schedule_id, action):
    """Pause, resume or delete. Making and changing schedules stays on the Mac."""
    item = store.find('schedules', schedule_id)
    if not item: raise LookupError('找不到這個排程。')
    if action == 'delete': store.data['schedules'].remove(item)
    elif action == 'pause': item['on'] = False; item.pop('held', None)
    elif action == 'resume': raise ValueError('排程要在 Mac 上恢復。')  # it starts work by itself later: only the user in the Mac's window turns it on
    else: raise ValueError('動作無效。')
    store.save()


def mobile_photo(store, body):
    """Keep one photo sent from the phone as an upload, ready to attach to a message."""
    try: raw = base64.b64decode(body.get('data') or '', validate=True)
    except (ValueError, TypeError): raise ValueError('照片資料無效。')
    kind = '.jpg' if raw[:3] == b'\xff\xd8\xff' else '.png' if raw[:8] == b'\x89PNG\r\n\x1a\n' else ''
    if not kind or len(raw) > MOBILE_PHOTO_BYTES: raise ValueError('照片太大或格式不支援。')
    upload_id = ID(); folder = store.dir / 'uploads' / upload_id; folder.mkdir(parents=True, mode=0o700)
    (folder / 'file').write_bytes(raw)
    meta = dict(id=upload_id, name='照片-%s%s' % (datetime.datetime.now().strftime('%m%d-%H%M%S'), kind), size=len(raw), kind='image', createdAt=NOW())
    (folder / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
    return meta


def mobile_chat_switch(store, bot, body):
    """Open another of the Bot's conversations, or start a new one."""
    ensure_chats(bot)
    if any(j['botId'] == bot['id'] and j['status'] == 'running' and not j.get('groupId') for j in store.data['jobs']): raise RuntimeError('這個 Bot 還在回覆，等它回完再切換對話。')
    if body.get('new') is True:
        if bot['messages']:
            chat = dict(id=ID(), title='', createdAt=NOW(), updatedAt=NOW(), messages=[]); bot['chats'].append(chat); open_chat(bot, chat['id'])
    elif isinstance(body.get('chatId'), str) and any(c['id'] == body['chatId'] for c in bot['chats']): open_chat(bot, body['chatId'])
    else: raise ValueError('找不到這個對話。')
    store.save()


MOBILE_PHOTOS_PER_HOUR = 60


def mobile_photo_allowed(app, device_id):
    """A phone may send a limited number of photos an hour, so it cannot fill the Mac's disk."""
    now = time.time(); sent = app.__dict__.setdefault('mobile_photo_times', {})
    recent = [t for t in sent.get(device_id, []) if now - t < 3600]
    if len(recent) >= MOBILE_PHOTOS_PER_HOUR: sent[device_id] = recent; return False
    sent[device_id] = recent + [now]; return True


# ---- How long a paired phone stays valid without being used (設定 > 遠端連線 > 自動失效)
REMOTE_EXPIRY_CHOICES = (7, 30, 90, 365, 0)  # days; 0 = never (the phone must then be revoked by hand if lost)
REMOTE_EXPIRY_DEFAULT = 30


def remote_expiry(settings):
    """The chosen period and when it was chosen. A new period counts from then, so choosing a shorter one never cuts a phone off at once."""
    value = settings.get('remoteExpiry') if isinstance(settings.get('remoteExpiry'), dict) else {}
    days = value.get('days')
    return (days if type(days) is int and days in REMOTE_EXPIRY_CHOICES else REMOTE_EXPIRY_DEFAULT), value.get('since')


def remote_expiry_set(settings, days):
    """For PATCH /api/settings {remoteExpiryDays}: the new value of settings['remoteExpiry']."""
    if type(days) is not int or days not in REMOTE_EXPIRY_CHOICES: raise ValueError('自動失效期限無效。')
    current, since = remote_expiry(settings)
    return dict(days=days, since=since if days == current and since else NOW())


def remote_expiry_repair(settings):
    """At load: a missing or damaged setting starts counting now, so no phone paired before it existed is cut off at once."""
    days, since = remote_expiry(settings)
    if not isinstance(settings.get('remoteExpiry'), dict) or settings['remoteExpiry'].get('days') != days or _remote_stamp(since) is None:
        settings['remoteExpiry'] = dict(days=days, since=NOW())


def _remote_stamp(text):
    try: at = datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError: return None
    return (at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)).timestamp()


def remote_expired(settings, device, now=None):
    days, since = remote_expiry(settings)
    if not days: return False
    marks = [x for x in (_remote_stamp(device.get('lastSeenAt')), _remote_stamp(device.get('createdAt')), _remote_stamp(since)) if x is not None]
    return not marks or (now or time.time()) - max(marks) > days * 86400  # no readable time at all: fail closed


def remote_prune(store):
    """Drop paired devices left unused longer than 設定 allows; the relay connection then closes theirs. Lock held."""
    devices = store.data.get('remoteDevices') or []
    gone = [d for d in devices if remote_expired(store.data['settings'], d)]
    if not gone: return
    store.data['remoteDevices'] = [d for d in devices if d not in gone]
    store.save()
    days = remote_expiry(store.data['settings'])[0]
    for d in gone: log_activity(store, 'device', '「%s」超過 %d 天沒有使用，已自動失效' % (d.get('name') or '裝置', days), by='Zook')


def remote_device(store, device_id):
    """The paired device making a request through the relay, or None when unknown, revoked or expired. Lock held.
    Checked on every request, so a revoked device stops at once."""
    remote_prune(store)
    device = next((d for d in store.data.get('remoteDevices', []) if d['id'] == device_id), None)
    if device: device['lastSeenAt'] = NOW()
    return device
