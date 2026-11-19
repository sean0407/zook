# Messages sent while a Bot is still answering: they wait in line and are sent one by one as it becomes free.
# Loaded by backend/server.py into one shared namespace.
#
# The line belongs to the Bot (it answers one thing at a time) and each entry remembers its conversation. It is saved with the
# data, so it is still there after Zook restarts. Schedules, triggers and group turns do not use it: they keep trying later.
MAX_WAITING = 20


def queue_on(store): return store.data['settings'].get('queueWhenBusy') is not False


def queue_add(store, bot, body):
    """Lock held. Put a message in line. Raises ValueError when it could not be sent anyway, so the user hears about it now."""
    content, attachments = body.get('content'), body.get('attachments')
    if attachments is not None and (not isinstance(attachments, list) or any(not isinstance(x, str) for x in attachments)): raise ValueError('附件無效。')
    kept = attachments_for(store, attachments)  # checks the files are there; only their ids are kept
    if kept and isinstance(content, str) and not content.strip(): content = '（請看附件）'
    if not isinstance(content, str) or not content.strip() or len(content) > 30000: raise ValueError('訊息內容無效。')
    if not isinstance(body.get('plan', False), bool) or not isinstance(body.get('long', False), bool): raise ValueError('設定無效。')
    line = bot.setdefault('queue', [])
    if len(line) >= MAX_WAITING: raise ValueError('排隊的訊息已有 %d 則，請等 Bot 回覆一些再傳。' % MAX_WAITING)
    entry = dict(id=ID(), chatId=bot.get('chatId'), content=content, createdAt=NOW())
    if kept: entry['attachments'] = [a['id'] for a in kept]
    if body.get('effort'): entry['effort'] = pick_effort(body.get('effort'), bot_effort(bot))
    for key in ('plan', 'long'):
        if body.get(key): entry[key] = True
    line.append(entry); store.save()
    return entry


def queue_cancel(store, bot, entry_id):
    """Lock held. True when the message was still waiting and has been taken out."""
    line = bot.get('queue') or []
    kept = [e for e in line if e['id'] != entry_id]
    if len(kept) == len(line): return False
    bot['queue'] = kept; store.save()
    return True


def queue_forget_chat(bot, chat_id):
    """Lock held. A deleted conversation takes its waiting messages with it."""
    if bot.get('queue'): bot['queue'] = [e for e in bot['queue'] if e.get('chatId') != chat_id]


class Waiting:
    """Mixed into App."""
    def queue_drain(self, bot_id):
        """Send the Bot's next waiting message, if it is free. Called when one of its replies ends, and at startup."""
        store = self.store
        if self.__dict__.get('closing'): return
        with store.lock:
            bot = store.find('bots', bot_id)
            if not bot or not bot.get('queue'): return
        inventory = inventory_for(store)  # reads the CLIs' settings: not under the lock
        with store.lock:
            bot = store.find('bots', bot_id)
            if not bot or not bot.get('queue'): return
            if self.__dict__.get('closing'): return
            if any(j['botId'] == bot_id and j['status'] == 'running' for j in store.data['jobs']): return  # still busy: the end of that reply comes back here
            entry = bot['queue'].pop(0)  # taken out before it is sent, so the save that records the reply also records that it left the line
            if not any(c['id'] == entry.get('chatId') for c in ensure_chats(bot)):
                store.save(); again = True  # its conversation is gone, and it is not put into another one
            else:
                again = False
                try:
                    self.send_to_bot(bot, entry['content'], inventory, chat_id=entry['chatId'], attachments=attachments_for(store, entry.get('attachments')) or None,
                                     effort=entry.get('effort'), plan=bool(entry.get('plan')), long=bool(entry.get('long')))
                except Busy:
                    bot['queue'].insert(0, entry); return
                except Exception as exc:
                    # It cannot be sent after all (the model was removed meanwhile, a file is gone). Shown as a failed message, never dropped
                    # silently, and never left to block the ones behind it.
                    reason = str(exc)[:200] if isinstance(exc, (ValueError, RuntimeError)) else '送出時發生錯誤。'
                    messages = chat_messages(bot, entry['chatId'])
                    messages.extend([dict(id=ID(), role='user', content=entry['content'], createdAt=NOW()),
                                     dict(id=ID(), role='assistant', content='', createdAt=NOW(), status='failed', note='這則排隊的訊息沒有送出：' + reason)])
                    store.save(); again = True
        if again: self.queue_drain(bot_id)  # the next one in line

    def queue_drain_all(self):
        with self.store.lock: waiting = [b['id'] for b in self.store.data['bots'] if b.get('queue')]
        for bot_id in waiting: self.queue_drain(bot_id)
