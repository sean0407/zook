# 知識庫第 2 版 (#295): what a Bot reads with a reply is the passages of the knowledge base that match what was asked, instead of the
# newest ten items. Everything is worked out on this Mac (no outside service, nothing downloaded). Loaded by backend/server.py after
# knowledge.py, into one shared namespace.
#
# How it works:
#   - Every usable item (typed text, or the text read out of a file) is cut into passages of about 1,200 characters (at most 1,500),
#     each remembering its item's title, file name and the heading it sits under (a Markdown heading, 【第 N 頁】, 【工作表 X】).
#   - The passages are kept in memory per item and made again only when that item changes (added, edited, deleted, synced, restored):
#     an item's signature is its text's hash (Python keeps a string's hash, so checking costs nothing after the first time), title and
#     file name. Older data is cut the first time it is needed.
#   - A question is scored against the passages with BM25. Words are matched as lower-case word starts; Chinese, Japanese and Korean
#     text as pairs of characters (a lone character on its own), so 「保固多久」 finds 「保固兩年」 without a dictionary.
#   - At most KNOWLEDGE_BUDGET characters and KNOWLEDGE_PIECES passages go into the prompt, best first, each labelled with where it is from.
#   - A knowledge base small enough to fit is given whole (nothing to choose). When nothing matches, the newest items are given in short
#     (as before, but smaller), so a note such as a style guide is still seen when the question does not name it.
import math as _kmath
import unicodedata as _kuni
import weakref as _kweak

KNOWLEDGE_PIECE = 1200              # characters a passage aims for
KNOWLEDGE_PIECE_MAX = 1500          # and never passes
KNOWLEDGE_BUDGET = 12000            # characters of passages a Bot reads with one reply
KNOWLEDGE_PIECES = 12               # passages a Bot reads with one reply
_KCJK = '぀-ヿ㐀-䶿一-鿿豈-﫿가-힯'
_KDROP = re.compile('[^0-9a-z%s]+' % _KCJK)
_KGAP = re.compile('(?<=[0-9a-z])(?=[%s])|(?<=[%s])(?=[0-9a-z])' % (_KCJK, _KCJK))
_KHEAD = re.compile(r'\s*(#{1,6}\s+\S.{0,80}|【[^】\n]{1,60}】)\s*')
_KSTOP = set('the a an is are was were be been to of and or in on for with what how why when where who which do does did can could '
             'should would will i you we they it its this that these those my your our me us please tell about from at by as not no yes '
             'any some there here have has had get'.split()) | {
             '什麼', '怎麼', '怎樣', '如何', '可以', '一下', '我們', '你們', '他們', '這個', '那個', '這些', '那些', '是不', '不是', '請問', '幫我',
             '為什', '麼是', '的是', '是什', '有沒', '沒有', '有什', '告訴', '一個', '現在', '需要', '要怎', '應該', '知道', '請你', '時候', '什么',
             '怎么', '是否', '的話', '一些', '多少', '哪些', '哪個', '還是', '或是', '以及', '我的', '你的', '要是', '能不', '不能', '麼辦', '怎樣',
             '的', '了', '是', '嗎', '呢', '吧', '我', '你', '他', '她', '在', '有', '和', '與', '及', '或', '也', '就', '都', '要', '會', '請', '嗎'}
_KINDEX = _kweak.WeakKeyDictionary()  # store → {item id: (signature, passages)}
_KINDEX_LOCK = threading.Lock()


def _knorm(text):
    """Lower case, full-width folded, everything but letters, digits and CJK turned into spaces, words and CJK runs kept apart.
    Padded with a space so a word start is ' ' + word."""
    text = _KDROP.sub(' ', _kuni.normalize('NFKC', text).lower())
    return ' ' + _KGAP.sub(' ', text) + ' '


def knowledge_terms(query):
    """What a question is matched on: word starts (' word') and CJK character pairs, without everyday words. In order, once each."""
    out = []
    for run in _knorm(str(query or '')[:4000]).split():
        if run.isascii():
            if len(run) > 1 and run not in _KSTOP: out.append(' ' + run)
        elif len(run) == 1:
            if run not in _KSTOP: out.append(run)
        else: out.extend(run[i:i + 2] for i in range(len(run) - 1) if run[i:i + 2] not in _KSTOP)
    return list(dict.fromkeys(out))[:60]


def _kcut(line):
    """A line longer than a passage, cut at the end of a sentence where there is one."""
    while len(line) > KNOWLEDGE_PIECE_MAX:
        window = line[KNOWLEDGE_PIECE // 2:KNOWLEDGE_PIECE_MAX]
        at = max(window.rfind(mark) for mark in '。！？；.!?;\t ')
        at = KNOWLEDGE_PIECE // 2 + at + 1 if at >= 0 else KNOWLEDGE_PIECE_MAX
        yield line[:at]; line = line[at:]
    if line: yield line


def knowledge_passages(content):
    """One item's text as passages: [(heading, text)], each at most KNOWLEDGE_PIECE_MAX characters."""
    out, buf, size, heading, heads = [], [], 0, '', []
    def flush():  # labelled with every heading it spans (short sections share a passage), at most three
        text = '\n'.join(buf).strip()
        if text: out.append(('、'.join([h for h in dict.fromkeys(heads) if h][:3]), text))
    for raw in str(content or '').split('\n'):
        head = _KHEAD.fullmatch(raw)
        if head:
            if size >= KNOWLEDGE_PIECE // 2: flush(); buf, size = [], 0  # a new section starts a new passage unless the last one is short
            heading = head.group(1).lstrip('#').strip()[:80]
            if buf: heads.append(heading)
        for line in _kcut(raw):
            if buf and size + len(line) + 1 > KNOWLEDGE_PIECE: flush(); buf, size = [], 0
            if not buf: heads = [heading]
            buf.append(line); size += len(line) + 1
    flush()
    return out


def _kitem(item):
    """The passages of one item: [(heading, text, normalised text)]."""
    return [(heading, text, _knorm(text)) for heading, text in knowledge_passages(item.get('content'))]


def _ksignature(item):
    return (hash(item.get('content') or ''), item.get('title'), item.get('source'))


def knowledge_index_touch(store, item_id):
    """An item was added, changed or deleted: its passages are made again now (or dropped), not at the next reply. Lock held."""
    item = store.find('knowledge', item_id)
    with _KINDEX_LOCK:
        index = _KINDEX.setdefault(store, {})
        if not item or not knowledge_usable(item): index.pop(item_id, None); return
        sig = _ksignature(item)
        if (index.get(item_id) or (None,))[0] != sig: index[item_id] = (sig, _kitem(item))


def knowledge_index_warm(store):
    """At start, in the background: older items are cut into passages before the first reply needs them, one item per hold of the lock."""
    def run():
        with store.lock: ids = [x['id'] for x in store.data['knowledge'] if knowledge_usable(x)]
        for item_id in ids:
            with store.lock: knowledge_index_touch(store, item_id)
    threading.Thread(target=run, daemon=True).start()


def _kindexed(store, items):
    """The passages of these items, made only for an item that is new or changed since last time; deleted items are forgotten."""
    with _KINDEX_LOCK:
        index = _KINDEX.setdefault(store, {})
        known = {x.get('id') for x in store.data['knowledge']}
        for gone in [k for k in index if k not in known]: index.pop(gone)
        out = []
        for item in items:
            sig, kept = _ksignature(item), index.get(item['id'])
            if not kept or kept[0] != sig: kept = index[item['id']] = (sig, _kitem(item))
            out.append((item, kept[1]))
        return out


def _kvisible(store, bot_id):
    """Usable items for every Bot, and for this one."""
    return [x for x in store.data['knowledge'] if (not x.get('botId') or x.get('botId') == bot_id) and knowledge_usable(x)]


def _kpassage(item, heading, text, score=None):
    return dict(id=item['id'], title=item.get('title') or '', source=item.get('source') or '', heading=heading, text=text, score=score)


def knowledge_pick(store, bot_id, query):
    """(how they were chosen, passages) for a Bot and a question. 'all': the whole knowledge base fits; 'match': passages that match
    the question; 'recent': nothing matched, the newest items in short; 'none': nothing to read. Lock held."""
    items = _kvisible(store, bot_id)
    if not items: return 'none', []
    indexed = _kindexed(store, items)
    if sum(len(x['content']) for x in items) <= KNOWLEDGE_BUDGET:
        whole = [_kpassage(item, heading, text) for item, passages in indexed for heading, text, _ in passages]
        if sum(_kcost(p) for p in whole) <= KNOWLEDGE_BUDGET: return 'all', whole
    found = knowledge_rank(indexed, knowledge_terms(query))
    if found: return 'match', found
    out, room = [], KNOWLEDGE_BUDGET
    for item, passages in reversed(indexed[-KNOWLEDGE_RECENT:]):
        if not passages: continue
        p = _kpassage(item, passages[0][0], passages[0][1])
        if _kcost(p) > room: break
        out.append(p); room -= _kcost(p)
    return 'recent', out


def _kcost(p):
    """Characters a passage takes in the prompt, its label included."""
    return len(p['text']) + len(knowledge_label(p)) + 8


def knowledge_rank(indexed, terms):
    """BM25 over every passage of the items given; the best ones that fit the budget. [] when no passage shares a word with the question."""
    if not terms: return []
    rows = [(item, heading, text, norm) for item, passages in indexed for heading, text, norm in passages]
    if not rows: return []
    counts = [[norm.count(t) for t in terms] for _, _, _, norm in rows]
    n, mean = len(rows), sum(len(r[3]) for r in rows) / len(rows)
    idf = [_kmath.log(1 + (n - df + 0.5) / (df + 0.5)) for df in (sum(1 for c in counts if c[i]) for i in range(len(terms)))]
    scored = []
    for row, c in zip(rows, counts):
        if not any(c): continue
        k = 1.2 * (0.25 + 0.75 * len(row[3]) / mean)
        scored.append((sum(idf[i] * tf * 2.2 / (tf + k) for i, tf in enumerate(c) if tf), row))
    if not scored: return []
    scored.sort(key=lambda s: -s[0])
    floor, out, room = scored[0][0] * 0.3, [], KNOWLEDGE_BUDGET
    for score, (item, heading, text, _) in scored:
        if score < floor or len(out) >= KNOWLEDGE_PIECES: break
        p = _kpassage(item, heading, text, round(score, 2))
        if _kcost(p) > room: continue
        out.append(p); room -= _kcost(p)
    return out


def knowledge_for(store, bot, query=''):
    """What one Bot reads with a reply to this question (passages; see knowledge_pick). Lock held."""
    return knowledge_pick(store, bot['id'], query)[1]


def knowledge_label(p):
    """Where a passage is from, as the Bot is asked to cite it: the item's title, its file, the heading."""
    label = p['title'] or p['source'] or '未命名'
    if p['source'] and p['source'] != p['title']: label += '（檔案：%s）' % p['source']
    return label + (' › ' + p['heading'] if p['heading'] else '')


def knowledge_lines(passages):
    if not passages: return ''
    return '（以下是知識庫的段落，每段標明出處；和問題有關才參考，用到時說明依據哪一份。）\n' + '\n\n'.join('【出處：%s】\n%s' % (knowledge_label(p), p['text']) for p in passages)


def knowledge_group_ask(group, target=None, fix='', hidden=()):
    """The question a group member's knowledge is looked up for: what it was asked to fix and the reply it checks first (so they always
    count within the terms kept), then the last few messages it may see, newest first (a hidden one never steers what it reads)."""
    said = [m['content'][:1000] for m in group.get('messages') or [] if m.get('content') and m.get('role') != 'system' and not m.get('waiting') and m.get('id') not in hidden][-3:]
    return '\n'.join([str(fix or '')[:1000], ((target or {}).get('content') or '')[:1000]] + said[::-1])


def knowledge_search_route(handler, store):
    """試搜尋 on the 知識庫 page: the passages a Bot would get for a question. Lock held."""
    body = handler.body()
    query, bot_id = body.get('query'), body.get('botId', '')
    if bot_id is None: bot_id = ''
    if not isinstance(query, str) or not query.strip() or len(query) > 2000: raise ValueError('請輸入要試搜尋的問題（2,000 字以內）。')
    if not isinstance(bot_id, str) or (bot_id and not store.find('bots', bot_id)): raise ValueError('找不到這個 Bot，請重新選擇。')
    mode, found = knowledge_pick(store, bot_id, query)
    return handler.respond(200, dict(mode=mode, passages=[dict(title=p['title'], source=p['source'], label=knowledge_label(p), text=p['text'][:400],
                                                               chars=len(p['text'])) for p in found]))
