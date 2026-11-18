# What a paired phone can do beyond chatting: look after schedules, send photos, switch conversations.
# Loaded by backend/server.py into one shared namespace.
MOBILE_PHOTOS = 4                 # per message
MOBILE_PHOTO_BYTES = 700 * 1024   # the phone shrinks a photo before sending


def mobile_schedules(store):
    return dict(schedules=[dict(id=x['id'], content=(x.get('content') or '')[:120], when=schedule_when(x), target=schedule_target_name(store, x), on=bool(x.get('on', True)),
                                group=bool(x.get('groupId'))) for x in store.data['schedules']])


def mobile_schedule_action(store, schedule_id, action):
    """Pause, resume or delete. Making and changing schedules stays on the Mac."""
    item = store.find('schedules', schedule_id)
    if not item: raise LookupError('找不到這個排程。')
    if action == 'delete': store.data['schedules'].remove(item)
    elif action in ('pause', 'resume'): item['on'] = action == 'resume'; item.pop('held', None)
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
