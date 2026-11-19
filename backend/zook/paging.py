# Long conversations: the window loads the newest part and asks for older parts as the reader scrolls up.
# Loaded by backend/server.py into one shared namespace.
#
# Nothing about how conversations are stored changes. Only what is sent to the window does: the open conversation's newest
# messages, and for the other conversations a count instead of their messages. Search runs here, over everything.
PAGE = 100


def page_bot(bot):
    """A Bot as the window gets it. Lock held."""
    messages = bot.get('messages') or []
    out = dict(bot, messages=messages[-PAGE:], olderCount=max(0, len(messages) - PAGE))
    out['chats'] = [dict({k: v for k, v in c.items() if k != 'messages'},
                         count=sum(1 for m in (messages if c['id'] == bot.get('chatId') else c.get('messages') or []) if m.get('role') == 'user')) for c in bot.get('chats') or []]
    return out


def page_messages(bot, chat_id, query):
    """Older messages of one conversation. before=<message id>: the page before it. from=<message id>: from a little before
    it up to the newest (to jump to a search hit). all=1: everything (to export). Lock held."""
    one = lambda key: (query.get(key) or [''])[0]
    if one('find'):  # which conversation a message is in
        for chat in ensure_chats(bot):
            if any(m.get('id') == one('find') for m in (bot['messages'] if chat['id'] == bot['chatId'] else chat.get('messages') or [])): return dict(chatId=chat['id'])
        return dict(chatId='')
    messages = chat_messages(bot, chat_id or bot.get('chatId'))
    index = lambda mid: next((i for i, m in enumerate(messages) if m.get('id') == mid), None)
    if one('all'): return dict(messages=messages, more=False)
    if one('from'):
        at = index(one('from'))
        if at is None: raise ValueError('找不到這則訊息。')
        start = max(0, at - 20)
        return dict(messages=messages[start:], more=start > 0)
    end = index(one('before')) if one('before') else len(messages)
    if end is None: raise ValueError('找不到這則訊息。')
    start = max(0, end - PAGE)
    return dict(messages=messages[start:end], more=start > 0)


def search_messages(store, text, bot_id=''):
    """Messages that contain the text, newest conversations first: up to 30 hits and, for one Bot, every conversation that has one. Lock held."""
    needle = ' '.join(str(text or '').lower().split())
    if not needle: return dict(hits=[], chats=[])
    hits, chats = [], []
    for bot in store.data['bots']:
        if bot_id and bot['id'] != bot_id: continue
        for chat in sorted(ensure_chats(bot), key=lambda c: c.get('updatedAt') or '', reverse=True):
            found = False
            for m in bot['messages'] if chat['id'] == bot['chatId'] else chat.get('messages') or []:
                content = str(m.get('content') or '')
                at = ' '.join(content.lower().split()).find(needle)
                if at < 0: continue
                found = True
                if len(hits) < 30:
                    flat = ' '.join(content.split())
                    hits.append(dict(botId=bot['id'], chatId=chat['id'], chatTitle=chat.get('title') or '', kind=chat.get('kind') or '', messageId=m['id'],
                                     snippet=('…' if at > 30 else '') + flat[max(0, at - 30):at + 60]))
                elif not bot_id: break
            if found and bot_id: chats.append(chat['id'])
            if len(hits) >= 30 and not bot_id: return dict(hits=hits, chats=chats)
    return dict(hits=hits, chats=chats)


def paging_route(handler, store, parts, path):
    """Lock held."""
    query = parse_qs(urlsplit(handler.path).query)
    if path == '/api/search': return handler.respond(200, search_messages(store, (query.get('q') or [''])[0][:200], (query.get('bot') or [''])[0]))
    bot = store.find('bots', parts[2])
    if not bot: return handler.error(404, '找不到機器人。')
    return handler.respond(200, page_messages(bot, (query.get('chat') or [''])[0], query))
