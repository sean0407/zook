# What is left of each model's limits, in the form the sidebar rings and the bars on the usage page show it.
# Loaded by backend/server.py into one shared namespace.
RING_ORDER = ('codex', 'claude', 'grok', 'antigravity', 'cursor', 'gemini')


def _left(window, snap, now):
    """Percent left in one limit. A limit whose reset time has passed is full again."""
    used = window.get('usedPercent')
    if not isinstance(used, (int, float)) or isinstance(used, bool): return None
    return 100.0 if not _window_open(window, snap, now) else round(max(0.0, min(100.0, 100 - used)), 1)


def usage_rings(store):
    """Lock held. One entry per model Zook knows, in the order of the usage page: what is left of its five-hour and weekly limits.
    None means there is no figure: the model reports none (Grok, API keys), or it is not signed in yet (known is False)."""
    data = store.data; quota = data.get('quota') or {}; status = data.get('autoStatus') or {}; now = time.time()
    used = {(j.get('usage') or {}).get('provider') for j in data['jobs'] if isinstance(j.get('usage'), dict)}
    out = []
    for provider in P.active_ids(data):
        snap = quota.get(provider) if isinstance(quota.get(provider), dict) else {}
        windows = [w for w in snap.get('windows') or [] if isinstance(w, dict)]
        rows = [dict(label=str(w.get('label') or ''), left=_left(w, snap, now), resetsAt=w.get('resetsAt')) for w in windows]
        rows = [r for r in rows if r['left'] is not None]
        main = [r for r in rows if 'gemini' in r['label'].lower()] or rows if provider == 'antigravity' else rows  # the rings follow the model Zook runs by default
        short = [r['left'] for r in main if '小時' in r['label']]; long = [r['left'] for r in main if '週' in r['label']]
        out.append(dict(id=provider, name=provider_label(provider).split('（')[0], fiveHour=min(short) if short else None, week=min(long) if long else None,
                        left=min(r['left'] for r in main) if main else None, windows=rows, updatedAt=snap.get('updatedAt'),
                        known=bool(rows) or (status.get(provider) or {}).get('signedIn') is True or provider in used))
    return out



# ---- The order of the cards under 剩餘額度: dragged by the user (自訂), or most left first (自動). The phone lists its accounts in
# the same order. A card is known by its CLI ('codex') or its CLI and extra account ('codex::<id>'); cards that are not in the saved
# order (an account added since) come after the others, and saved keys whose account is gone are simply skipped.
USAGE_CARD_SORTS = ('custom', 'auto')


def usage_card_fields(body, changes):
    """Checks the two settings. Used by upkeep_fields."""
    if 'usageCardSort' in body:
        if body['usageCardSort'] not in USAGE_CARD_SORTS: raise ValueError('排序方式無效。')
        changes['usageCardSort'] = body['usageCardSort']
    if 'usageCardOrder' in body:
        order = body['usageCardOrder']
        if not isinstance(order, list) or len(order) > 200 or any(not isinstance(k, str) or not k or len(k) > 120 for k in order): raise ValueError('卡片順序無效。')
        changes['usageCardOrder'] = list(dict.fromkeys(order))


def api_billed_method(method):
    """A sign-in paid by use (an API key or an Anthropic Console sign-in): it has no plan limits to show, whatever figures are stored."""
    return str(method or '').strip().lower() in ('api 金鑰', 'anthropic console', 'api_key', 'api key')


def usage_card_focus(item, now=None):
    """(rank, percent left) for one card in 自動: rank 0 has figures, 1 has none, 2 is used up, 3 is not signed in. The percent is
    that of the limit worth watching now: the five-hour one when there is one, otherwise the weekly one."""
    if item.get('status') != 'logged_in': return 3, 0.0
    snap = item.get('quota') if isinstance(item.get('quota'), dict) else {}
    now = time.time() if now is None else now
    rows = [(str(w.get('label') or ''), _left(w, snap, now)) for w in snap.get('windows') or [] if isinstance(w, dict)]
    rows = [r for r in rows if r[1] is not None]
    if item.get('apiBilling'): return 1, 0.0  # paid by use: old figures of a subscription say nothing about it
    if limit_reached_now(snap) or any(left <= 0 for _, left in rows): return 2, 0.0
    if not rows: return 1, 0.0
    focus = next((r for r in rows if '小時' in r[0]), None) or next((r for r in rows if '週' in r[0]), None) or rows[0]
    return 0, focus[1]


def usage_card_sort(settings, items, key=lambda x: x['id']):
    """items in the order the usage page shows them."""
    saved = settings.get('usageCardOrder') if isinstance(settings.get('usageCardOrder'), list) else []
    place = {k: i for i, k in enumerate(saved)}
    custom = sorted(range(len(items)), key=lambda i: (place.get(key(items[i]), len(saved)), i))
    if settings.get('usageCardSort') != 'auto': return [items[i] for i in custom]
    rank = {i: n for n, i in enumerate(custom)}
    def auto(i):
        level, left = usage_card_focus(items[i])
        return level, -left, rank[i]
    return [items[i] for i in sorted(custom, key=auto)]

# ---- The overview on the usage page: what the replies would have cost at API prices, per day and per model, and where the tokens went.
# A subscription is not charged these amounts; the page says so. A CLI's own figure is used when it reports one (Claude, Grok);
# otherwise the price list in backend/prices.json is applied, and a model that is not on the list has no price at all.
USAGE_DAYS = (7, 30, 90)
USAGE_DAILY_KEEP = 120  # days of per-day totals kept after the replies themselves are folded away
USAGE_FIELDS = ('input', 'cachedInput', 'cacheWrite', 'output')
_prices = {}


def price_list():
    if not _prices:
        here = pathlib.Path(__file__).resolve().parent  # this file is run inside server.py's namespace
        try: _prices.update(json.loads(next(x for x in (here / 'prices.json', here.parent / 'prices.json') if x.is_file()).read_text(encoding='utf-8')))
        except (OSError, ValueError, StopIteration): _prices.update(date='', models={})
    return _prices


def price_for(model):
    """[input, cache read, cache write, output] in dollars per million tokens, or None when the model is not on the list."""
    name = re.sub(r'-\d{8}$', '', str(model or '').lower().split('/')[-1].split('[')[0].replace('.', '-').strip())
    row = (price_list().get('models') or {}).get(name)
    return row if isinstance(row, list) and len(row) == 4 else None


def usage_cost(u):
    """(dollars, 'reported' | 'estimated') for one reply's usage, or (None, None) when there is no price for its model."""
    cost = u.get('costUsd')
    if isinstance(cost, (int, float)) and not isinstance(cost, bool): return float(cost), 'reported'
    row = price_for(u.get('model'))
    if not row: return None, None
    cached, wrote = _int(u.get('cachedInput')), _int(u.get('cacheWrite'))
    fresh = max(0, _int(u.get('input')) - cached - wrote)  # input counts everything that was read, cached or not
    read = row[1] if row[1] is not None else row[0]; write = row[2] if row[2] is not None else row[0]
    return (fresh * row[0] + cached * read + wrote * write + _int(u.get('output')) * row[3]) / 1e6, 'estimated'


def codex_default_model(env):
    """The model Codex uses when Zook names none, read from its own settings file."""
    try: text = (pathlib.Path((env or {}).get('CODEX_HOME') or pathlib.Path.home() / '.codex') / 'config.toml').read_text(encoding='utf-8', errors='replace')
    except OSError: return ''
    match = re.search(r'^model\s*=\s*"([A-Za-z0-9._:/-]{1,80})"', text.split('\n[', 1)[0], re.M)
    return match.group(1) if match else ''


def _usage_day(job):
    try: return datetime.datetime.fromisoformat(str(job.get('finishedAt') or job.get('createdAt'))).astimezone().date().isoformat()
    except ValueError: return ''


def _usage_row(): return dict(replies=0, input=0, cachedInput=0, cacheWrite=0, output=0, cost=0.0, reported=0, estimated=0, unpriced=0, noWrite=0)


def _usage_add(row, u):
    row['replies'] += 1
    for k in USAGE_FIELDS: row[k] += _int(u.get(k))
    if 'cacheWrite' not in u: row['noWrite'] += 1  # this CLI, or this older reply, did not say
    cost, kind = usage_cost(u)
    if kind: row['cost'] += cost; row[kind] += 1
    else: row['unpriced'] += 1


def usage_daily_fold(store, job):
    """Lock held. A reply is about to be dropped from the job list: keep its figures in that day's totals."""
    u = job.get('usage'); day = _usage_day(job)
    if not isinstance(u, dict) or not day: return
    days = store.data.setdefault('usageDaily', {})
    row = days.setdefault(day, {}).setdefault('%s\t%s' % (u.get('provider', ''), u.get('model') or ''), _usage_row())
    _usage_add(row, u)
    oldest = (datetime.datetime.now().astimezone().date() - datetime.timedelta(days=USAGE_DAILY_KEEP)).isoformat()
    for old in [d for d in days if d < oldest]: del days[old]


def usage_overview(store, span=30):
    """Lock held."""
    if span not in USAGE_DAYS: raise ValueError('期間無效。')
    today = datetime.datetime.now().astimezone().date()
    days = [(today - datetime.timedelta(days=i)).isoformat() for i in range(span - 1, -1, -1)]; wanted = set(days)
    cells = {}  # (day, provider, model) -> totals
    for job in store.data['jobs']:
        u = job.get('usage'); day = _usage_day(job)
        if isinstance(u, dict) and day in wanted and not job.get('internal'): _usage_add(cells.setdefault((day, u.get('provider', ''), u.get('model') or ''), _usage_row()), u)
    for day, rows in (store.data.get('usageDaily') or {}).items():
        if day not in wanted or not isinstance(rows, dict): continue
        for key, old in rows.items():
            provider, _, model = key.partition('\t'); row = cells.setdefault((day, provider, model), _usage_row())
            for k in row: row[k] += old.get(k) or 0
    providers, total = {}, _usage_row()
    for (day, provider, model), row in cells.items():
        p = providers.setdefault(provider, dict(_usage_row(), id=provider, name=provider_label(provider).split('（')[0] if P.spec(store.data, provider) else (provider or '其他'), daily={}, tokensByDay={}, models={}))
        for k in total: total[k] += row[k]; p[k] += row[k]
        p['daily'][day] = p['daily'].get(day, 0.0) + row['cost']; p['tokensByDay'][day] = p['tokensByDay'].get(day, 0) + row['input'] + row['output']
        if row['unpriced']: p['models'][model or '預設模型'] = True
    listing = []
    for p in sorted(providers.values(), key=lambda p: (p['cost'], p['input'] + p['output']), reverse=True):
        listing.append(dict(id=p['id'], name=p['name'], cost=round(p['cost'], 4), share=round(100 * p['cost'] / total['cost'], 1) if total['cost'] else None, tokens=p['input'] + p['output'], replies=p['replies'],
                            kind='reported' if p['reported'] and not p['estimated'] else 'estimated' if p['estimated'] else None, unpriced=p['unpriced'], unpricedModels=sorted(p['models'])[:5],
                            daily=[round(p['daily'].get(d, 0.0), 4) for d in days], dailyTokens=[p['tokensByDay'].get(d, 0) for d in days]))
    sent = 0
    for owner in store.data['bots'] + store.data.get('groups', []):
        for messages in [owner.get('messages') or []] + [c.get('messages') or [] for c in owner.get('chats') or [] if c.get('messages') is not owner.get('messages')]:
            sent += sum(1 for m in messages if m.get('role') == 'user' and not m.get('author') and str(m.get('createdAt') or '')[:10] >= days[0])
    known_write = total['replies'] > total['noWrite']
    return dict(span=span, days=days, cost=round(total['cost'], 4), replies=total['replies'], unpriced=total['unpriced'], providers=listing, priceDate=price_list().get('date') or '', priceSource=price_list().get('source') or '',
                totals=dict(withoutCacheRead=total['input'] - total['cachedInput'] + total['output'], withCacheRead=total['input'] + total['output'], cachedInput=total['cachedInput'],
                            freshInput=max(0, total['input'] - total['cachedInput'] - total['cacheWrite']), cacheWrite=total['cacheWrite'] if known_write else None, output=total['output'], sent=sent, replies=total['replies']))
