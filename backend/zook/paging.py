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


def group_counts(group):
    """What the window shows about a whole discussion without loading it: how many times each member has spoken, and the replies
    since the user last wrote (to offer 整理結論). Lock held."""
    messages = group.get('messages') or []; counts = {}
    for m in messages:
        if m.get('role') == 'assistant' and m.get('content') and not m.get('checkOf') and m.get('status') == 'completed': counts[m.get('botId')] = counts.get(m.get('botId'), 0) + 1
    ask = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user'), -1)
    since = [m for m in messages[ask + 1:] if m.get('role') == 'assistant' and m.get('content') and not m.get('checkOf')]
    return counts, dict(replies=len(since), card=any(m.get('card') for m in since))


def page_group(group):
    """A group as the window gets it: the newest part of its discussion. Lock held."""
    messages = group.get('messages') or []
    counts, after = group_counts(group)
    return dict(group, messages=messages[-PAGE:], olderCount=max(0, len(messages) - PAGE), memberCounts=counts, afterAsk=after)


OUTLINE_MARKS = re.compile(r'```[a-zA-Z0-9_-]*|[*_`#>|]+|^\s*[-+]\s+|\[([^\]]*)\]\([^)]*\)', re.M)


def outline_text(text, size):
    """One line of plain text, at most size characters (plus 「…」 when cut)."""
    flat = ' '.join(OUTLINE_MARKS.sub(lambda m: m.group(1) or '', str(text or '')).split())
    return flat if len(flat) <= size else flat[:size] + '…'


def page_outline(messages):
    """The conversation beside the messages: every question in order, with the start of the first finished reply to it."""
    out, last = [], None
    for m in messages:
        if m.get('role') == 'user' and m.get('interjected') and last is not None: continue  # added while the reply ran: part of that question
        if m.get('role') == 'user':
            last = dict(id=m.get('id'), createdAt=m.get('createdAt') or '', author=m.get('author') or '',
                        title=outline_text(m.get('content'), 60) or ('（附件）' if m.get('attachments') else '（空白訊息）'), reply='', replyBy='')
            out.append(last)
        elif last is not None and not last['reply'] and m.get('role') == 'assistant' and m.get('content') and m.get('status') != 'running' and not m.get('checkOf'):
            last.update(reply=outline_text(m.get('content'), 90), replyBy=m.get('botId') or '')
    return out


def page_list(messages, query):
    """before=<id>: the page before it. from=<id>: from a little before it to the newest. all=1: everything. outline=1: the outline."""
    one = lambda key: (query.get(key) or [''])[0]
    index = lambda mid: next((i for i, m in enumerate(messages) if m.get('id') == mid), None)
    if one('outline'): return dict(outline=page_outline(messages))
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


def page_group_messages(group, query, store=None):
    """Older parts of a discussion, or (member=<Bot id>) every time one member spoke, newest last, each with what it was answering. Lock held."""
    messages = group.get('messages') or []
    member = (query.get('member') or [''])[0]
    if not member: return page_list(messages, query)
    turns, asked = [], None
    for m in messages:
        if m.get('role') == 'user': asked = dict(author=m.get('author') or '', content=str(m.get('content') or '')[:300])
        elif m.get('role') == 'assistant' and m.get('botId') == member and not m.get('checkOf'): turns.append(dict(m, asked=asked))
    if store is not None:  # what the member did for each turn: the tools it used and what it says it thought
        jobs = {j.get('messageId'): j for j in store.data['jobs'] if j.get('groupId') == group.get('id') and j.get('botId') == member}
        turns = [dict(t, work=dict(thinking=jobs[t['id']].get('thinking') or [], calls=jobs[t['id']].get('toolCalls') or [])) if t['id'] in jobs else t for t in turns]
    before = (query.get('before') or [''])[0]
    end = next((i for i, t in enumerate(turns) if t['id'] == before), None) if before else len(turns)
    if end is None: raise ValueError('找不到這則訊息。')
    start = max(0, end - PAGE)
    return dict(turns=turns[start:end], more=start > 0, total=len(turns))


def page_messages(bot, chat_id, query):
    """Older messages of one conversation. before=<message id>: the page before it. from=<message id>: from a little before
    it up to the newest (to jump to a search hit). all=1: everything (to export). Lock held."""
    one = lambda key: (query.get(key) or [''])[0]
    if one('find'):  # which conversation a message is in
        for chat in ensure_chats(bot):
            if any(m.get('id') == one('find') for m in (bot['messages'] if chat['id'] == bot['chatId'] else chat.get('messages') or [])): return dict(chatId=chat['id'])
        return dict(chatId='')
    return page_list(chat_messages(bot, chat_id or bot.get('chatId')), query)


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
