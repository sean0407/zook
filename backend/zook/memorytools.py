# 「忘掉…」 (#298): the memory page is a plain list and says to tell a Bot 「記住…／忘掉…」, so a Bot can also forget.
# Loaded by backend/server.py into one shared namespace.
#
# It forgets only what it may read (shared memory and its own), only in a turn the user sent (a schedule, trigger, script or another
# Bot cannot wipe what the user taught), and only one memory or the ones written exactly so; more than one that fits is asked back.
FORGET_LIST = 5


def forget_tool(store, bot_id, runtime, origin):
    S = lambda d: {'type': 'string', 'description': d}
    def forget(args):
        text = ' '.join(str(args.get('content') or '').split())
        if not text: raise RuntimeError('請說要忘掉哪一則記憶。')
        if origin != 'user': raise RuntimeError('這個回合是由%s啟動的，不能刪除記憶。' % ORIGIN_NAMES.get(origin, '其他來源'))
        with store.lock:
            mems = store.data['memories']
            mine = [m for m in mems if not m.get('botId') or m.get('botId') == bot_id]
            same = [m for m in mine if ' '.join(m['content'].split()) == text]
            hits = same or [m for m in mine if text in ' '.join(m['content'].split())]
            if not hits: raise RuntimeError('找不到這則記憶。用記憶裡的原句或其中一段再試一次。')
            if len(hits) > 1 and not same:
                raise RuntimeError('有 %d 則記憶都符合，請用完整的一句：%s' % (len(hits), '；'.join('「%s」' % m['content'][:80] for m in hits[:FORGET_LIST])))
            gone = {id(m) for m in hits}
            mems[:] = [m for m in mems if id(m) not in gone]; store.save()
        return {'forgotten': [m['content'] for m in hits]}
    return (runtime._schema('zook_forget', 'Forget (delete) a long-term memory when the user asks you to. Give the memory\'s exact text, or a part that only one memory has.',
                            {'content': S('The memory to forget, as it is written')}, ['content'], False), forget, True)
