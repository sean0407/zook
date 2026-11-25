# Taking a message in (#289). Loaded by backend/server.py into one shared namespace.
#
# Pressing send must be answered at once. Taking a message in needs Zook's data, and that can be held for seconds by other work
# (another reply starting its CLI waits for it under the lock, up to 15 seconds), and a message may have to wait for the one sent
# just before it (#142). So the request starts the work in its own thread and waits for it only SEND_ANSWER_WAIT: a quick answer is
# the same as always (the reply's id, 排在後面, 已插話, or why it was refused); otherwise the window hears 'accepted' and the work goes
# on. A message refused after that answer is said in the conversation, as a message in line that could not be sent is.
import traceback

SEND_ANSWER_WAIT = 1.0


def chat_intake(handler, body):
    """POST /api/chat. Not under the store lock."""
    app, device = handler.server, handler.device
    key = send_key('bot:' + str(body.get('botId')), body)
    seen = app.__dict__.get('recent_sends', {}).get(key) if key else None  # read without the lock: one lookup, never changed in place
    if seen and seen[0] > time.monotonic(): return handler.respond(202, dict(seen[1], duplicate=True))  # sent again after its answer was lost
    guard = app.__dict__.setdefault('intake_lock', threading.Lock()); taking = app.__dict__.setdefault('intake_taking', {})
    with guard:
        box = taking.get(key) if key else None  # the same message sent again while it is still being taken in: one of them
        fresh = box is None
        if fresh:
            box = dict(done=threading.Event(), answer=None, told=False, body=body)
            if key: taking[key] = box
    if fresh: threading.Thread(target=chat_take, args=(app, body, device, key, box), daemon=True).start()
    box['done'].wait(SEND_ANSWER_WAIT)
    with guard:
        answer = box['answer']
        if answer is None: box['told'] = True
    if answer is None: return handler.respond(202, {'accepted': True})
    status, out = answer
    return handler.respond(status, out if fresh or status >= 300 or out.get('duplicate') else dict(out, duplicate=True))


def chat_take(app, body, device, key, box):
    """In its own thread: everything that taking the message in needs, as the request itself did before."""
    store = app.store; status, out, done = 500, {'error': '處理要求時發生錯誤。'}, False
    try:
        send_order_wait(app, body)  # #142: after the message the app sent just before it
        inventory = inventory_for(store, tokens=False)  # a message only checks its Bot's choices; the reply signs in to connectors itself
        with store.lock:
            try: status, out = chat_take_locked(app, body, device, inventory, key)
            except ValueError as exc: status, out = 400, {'error': str(exc)}
            except Exception: traceback.print_exc()
            done = chat_take_answer(app, key, box, status, out)  # a refusal is written before the next message can be taken in
    except ValueError as exc: status, out = 400, {'error': str(exc)}
    except Exception: traceback.print_exc()  # nobody else would hear about it
    finally:
        send_order_taken(app, body)  # also when it failed before it got that far: the one after it need not wait
        if not done: chat_take_answer(app, key, box, status, out)


def chat_take_answer(app, key, box, status, out):
    """Hand the answer to the request, or, when it has already said 'accepted', write a refusal into the conversation. True."""
    with app.__dict__['intake_lock']:
        box['answer'] = (status, out); told = box['told']
        app.__dict__['intake_taking'].pop(key, None); box['done'].set()
    if told and status >= 300:
        try: chat_take_refused(app.store, box.get('body') or {}, out.get('error'))
        except Exception: traceback.print_exc()
    return True


def chat_take_locked(app, body, device, inventory, once):
    """Store lock held. (status, answer) for the message: sent, put in line, joined the running reply, or refused."""
    store = app.store
    send_order_taken(app, body); bot = store.find('bots', body.get('botId'))
    if not bot: return 404, {'error': '找不到機器人。'}
    if device and isinstance(body.get('attachments'), list) and len(body['attachments']) > MOBILE_PHOTOS: return 400, {'error': '手機每則訊息最多 %d 張照片。' % MOBILE_PHOTOS}
    sent = send_seen(app, once)
    if sent: return 202, dict(sent, duplicate=True)  # the same message again: its answer was lost on the way
    notice = ''
    busy = any(j['botId'] == bot['id'] and j['status'] == 'running' for j in store.data['jobs'])
    if busy and interject_wanted(body.get('content')):  # a correction or addition: into the reply that is running, when its CLI can take it
        joined, why = interject_send(app, bot, body, by=('手機：' + str(device.get('name') or '已配對裝置')) if device else '')
        if joined:
            sent = {'jobId': joined['id'], 'interjected': True}; send_remember(app, once, sent)
            return 202, sent
        if why:
            if not queue_on(store): return 409, {'error': why + '，請等它回覆完再傳。'}
            notice = why + '，已改成排在後面。'
    if queue_on(store) and (bot.get('queue') or notice):  # others are already waiting: this one goes behind them, even in the moment between two replies
        waiting = {'queued': True, 'queueId': queue_add(store, bot, body)['id']}
        if notice: waiting['notice'] = notice
        send_remember(app, once, waiting)
        threading.Thread(target=app.queue_drain, args=(bot['id'],), daemon=True).start()
        return 202, waiting
    try: job = app.send_to_bot(bot, body.get('content'), inventory, attachments=attachments_for(store, body.get('attachments')), effort=body.get('effort'),
                               plan=body.get('plan', False), long=body.get('long', False))
    except Busy as exc:
        if not queue_on(store): return 409, {'error': str(exc)}
        waiting = {'queued': True, 'queueId': queue_add(store, bot, body)['id']}  # it waits in line and is sent when the Bot is free
        send_remember(app, once, waiting)
        return 202, waiting
    send_remember(app, once, {'jobId': job['id']})
    return 202, {'jobId': job['id']}


def chat_take_refused(store, body, why):
    """A message refused after the window was told it had been taken in: shown in the open conversation as not sent, with why."""
    content = body.get('content')
    text = content[:30000] if isinstance(content, str) and content.strip() else '（請看附件）'
    with store.lock:
        bot = store.find('bots', body.get('botId'))
        if not bot: return
        ensure_chats(bot)
        chat_messages(bot, bot['chatId']).extend([dict(id=ID(), role='user', content=text, createdAt=NOW()),
                                                  dict(id=ID(), role='assistant', content='', createdAt=NOW(), status='failed', note='這則訊息沒有送出：' + str(why or '送出時發生錯誤。')[:200])])
        store.save()
