# One source for what is left of an account's limits (#323). The usage page cards, the sidebar and Bot detail rings, the Bot form's
# 已用完／快用完 line and the models a reply tries all read it here, so they never say different things. A figure Zook cannot trust
# is 無法確定 ('unknown'), never a number: one without a reset time read long ago, or one that says used up while the account went on
# answering. Also the backups of a Bot whose model the user picked (#33) and the report of 偵測使用量 (#321 #207).
# Loaded by backend/server.py into one shared namespace.
QUOTA_NO_RESET_FRESH = 5 * 3600  # a figure without a reset time (Grok) counts this long after it was read, as _window_open has it
QUOTA_DOUBT_AFTER_REPLY = 3600  # such a figure saying used up while the account answered within this long is not trusted
QUOTA_SAME_REPLY = 120  # a reply ending this soon after a reading is the one that brought it (a CLI reports its limits with the reply)


def _quota_time(value):
    """Seconds since the epoch from an ISO time or a number (seconds or milliseconds), or None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool): return value / 1000 if value > 1e12 else float(value)
    try: return datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError): return None


def quota_last_answer(store, provider, account_id=''):
    """Lock held. When this account ('' is the CLI's own sign-in) last finished a reply in Zook, or None."""
    last = None
    for job in store.data['jobs']:
        if job.get('status') != 'completed': continue
        ran, u = job.get('ran'), job.get('usage') if isinstance(job.get('usage'), dict) else {}
        p, a = (ran[0], ran[2] or '') if isinstance(ran, list) and len(ran) > 2 else (u.get('provider'), u.get('account') or '')
        if a:
            known = find_account(a)
            if not known: continue  # an account removed since: its replies say nothing about any other sign-in
            if known.get('provider') != p: a = ''  # a backup of another CLI ran on that CLI's own sign-in, not on the Bot's account
        if p != provider or a != account_id: continue
        at = _quota_time(job.get('finishedAt'))
        if at and (last is None or at > last): last = at
    return last


def _quota_clock(at): return datetime.datetime.fromtimestamp(at).strftime('%H:%M')


def quota_view(store, provider, account_id='', now=None):
    """Lock held. What is left of one account's limits, the one reading every screen and every reply goes by.
    level: 'ok', 'low' (under 20%), 'out' (cannot be used now), 'unknown' (無法確定: note says why) or '' (no figures).
    windows: each limit with left in percent (None when not known), as the cards draw them."""
    snap = (store.data.get('quota') or {}).get(provider + '@' + account_id if account_id else provider)
    snap = snap if isinstance(snap, dict) else {}
    now = time.time() if now is None else now
    read, limit_now, stale, rows = _quota_time(snap.get('updatedAt')), limit_reached_now(snap), False, []
    for w in snap.get('windows') or []:
        used = w.get('usedPercent') if isinstance(w, dict) else None
        if not isinstance(used, (int, float)) or isinstance(used, bool): continue
        left = round(max(0.0, min(100.0, 100 - used)), 1)
        if w.get('resetsAt') not in (None, ''):
            if not _window_open(w, snap, now): left = 100.0  # reset since it was read
        elif read is None or now - read > QUOTA_NO_RESET_FRESH: left = None; stale = True  # no reset time, read long ago
        rows.append(dict(label=str(w.get('label') or ''), left=left, resetsAt=w.get('resetsAt')))
    empty = [r for r in rows if r['left'] is not None and r['left'] <= 0]
    if limit_now: rows = [dict(r, left=0.0 if r['left'] is not None else None) for r in rows]  # the CLI just said it is reached: no bar says otherwise (#184②)
    known = [r for r in rows if r['left'] is not None]
    view = dict(level='', note='', windows=rows, left=min(r['left'] for r in known) if known else None, limitNow=limit_now, limitCode=str(snap.get('limitReached') or '') if limit_now else '',
                outGroup='', outReset=None, readAt=snap.get('updatedAt'))
    if limit_now or empty:
        view.update(level='out', outGroup=empty[0]['label'].split(' · ')[0] if empty and ' · ' in empty[0]['label'] else '')
        times = [r['resetsAt'] for r in empty]
        view['outReset'] = max(times, key=_quota_time) if times and all(_quota_time(t) for t in times) else None
        last = quota_last_answer(store, provider, account_id)
        unsure = bool(empty) and snap.get('source') != 'reply' and any(r['resetsAt'] in (None, '') for r in empty) and now - last < QUOTA_DOUBT_AFTER_REPLY if last else False
        if last and provider != 'antigravity' and (read is None or last > read + QUOTA_SAME_REPLY or unsure):  # Antigravity: a reply proves only the group it ran on
            view.update(level='unknown', left=None, note='顯示已用完，但 %s 仍正常回覆，額度無法確定' % _quota_clock(last))
    elif known: view['level'] = 'low' if view['left'] < 20 else 'ok'
    elif stale: view.update(level='unknown', note='上次讀到額度已超過 5 小時，這家沒有說何時重置，額度無法確定')
    return view


def quota_exhausted(store, key):
    """True when the account ('codex' or 'codex@<id>') cannot be used now: the CLI said so lately, or a limit is used up and has not reset."""
    provider, _, account = str(key).partition('@')
    if provider == 'antigravity': return False  # its limits are per model group; a used-up group simply fails over
    return quota_view(store, provider, account)['level'] == 'out'


def quota_left(store, provider, account_id=''):
    """Percent left in the tightest limit; 0 when used up, 50 when nothing is known (or 無法確定)."""
    view = quota_view(store, provider, account_id)
    return 0 if view['level'] == 'out' else 50 if view['left'] is None or view['level'] == 'unknown' else view['left']


def same_cli_backups(store, bot, provider, model):
    """Lock held. #33 (decisions #7): a Bot whose model the user picked tries the same CLI's other accounts, model kept, before
    another CLI: those 自動選擇 may use (signed in, a subscription, 自動選用 on), most left first. Nearly used-up ones go last later
    (backups_with_room). Also with no backups at all: 不自動換 only means no other CLI (使用者 2026-11-27). 自動選擇 has auto_backups."""
    if bot.get('autoAssigned') or bot.get('provider') == AUTO: return []
    own = (find_account(bot.get('account'), provider) or {}).get('id', '')
    try: same = [c for c in auto_choices(store, 'quick', (provider,)) if c[1] != own]
    except ValueError: return []
    return [(p, model, a) for p, a in sorted(same, key=lambda c: -quota_left(store, *c))]


def provider_chain(store, bot, provider, model):
    """Models to try for one reply: the Bot's own model, the same CLI's other accounts (same_cli_backups), then its backup order: its
    own list as set, or the default order from 設定 with the CLI that has most left first (#33)."""
    settings = store.data['settings']
    mine = isinstance(bot.get('fallbacks'), list)
    order = bot['fallbacks'] if mine else list(settings.get('fallbacks') or [])
    if not mine: order.sort(key=lambda p: -quota_left(store, p))
    chain = [(provider, model)] + same_cli_backups(store, bot, provider, model)
    for p in order:
        if p != provider and p not in [x[0] for x in chain] and P.spec(store.data, p):
            chain.append((p, settings.get('model', '') if p == settings.get('provider', 'codex') else ''))
    return chain


def quota_attach_views(store, out):
    """Lock held. The quota answer gets each account's view and the last 偵測使用量 report."""
    for item in out['providers']:
        item['view'] = quota_view(store, item['id'])
        for a in item.get('profiles') or []: a['view'] = quota_view(store, item['id'], a['id'])
    out['lastDetect'] = store.data.get('usageDetectReport')
    return out


DETECT_MISSED = dict(claude='Claude 這次沒有帶回額度', grok='讀不到 Grok 畫面上的每週額度', codex='Codex 這次沒有回傳額度', antigravity='Antigravity 這次沒有回傳額度')


def detect_report(store, started, out):
    """Lock held. After 偵測使用量: how many accounts got a new reading, and each one that did not with why, kept for the page."""
    updated, failed = 0, []
    for item in out['providers']:
        for a in [None] + list(item.get('profiles') or []):
            who = a or item
            if who.get('status') != 'logged_in' or who.get('apiBilling') or who.get('noQuotaApi') or item['id'] not in DETECT_MISSED: continue
            if item['id'] == 'claude' and who.get('autoBilled'): continue  # not known to be a subscription: never asked (claude_probe_targets)
            name = provider_label(item['id']).split('（')[0] + '（' + (a['name'] if a else '預設') + '）'
            at = _quota_time((who.get('quota') or {}).get('updatedAt'))
            if at and at >= started - 1: updated += 1
            else: failed.append(dict(name=name, why=str(item.get('issue') or '').split('。')[0] if not a and item.get('issue') else DETECT_MISSED[item['id']]))
    report = dict(at=time.time(), updated=updated, failed=failed[:20])
    store.data['usageDetectReport'] = report; out['lastDetect'] = report
    return out


def quota_low(store, provider, account_id, under):
    """Lock held. Less than under% left in a limit by the shared reading, or the CLI said the limit is reached; 無法確定 is not low.
    Antigravity goes by its Gemini limits, the model Zook runs by default."""
    view = quota_view(store, provider, account_id)
    if view['level'] == 'unknown': return False
    if view['limitNow']: return True
    rows = [r for r in view['windows'] if r['left'] is not None]
    if provider == 'antigravity': rows = [r for r in rows if 'gemini' in r['label'].lower()] or rows
    return any(r['left'] < under for r in rows)


def manual_backup_problem(store, bot, provider, account):
    """Lock held. #132: why a backup of a Bot whose model the user picked must not run now, or ''. Every backup, of its own CLI or
    another, runs only on a sign-in known lately to be a subscription; API billing or one not confirmed is skipped (only the Bot's own
    model, as the user chose it, is not held to this). account None: that CLI's own sign-in, unless the Bot's account is one of it."""
    if account is not None: return auto_choice_problem(store, provider, account) or auto_billing_problem(store, provider, account)
    return auto_billing_problem(store, provider, (find_account(bot.get('account'), provider) or {}).get('id', ''))


def backup_skip_error(store, bot, first, why, provider, account, problem):
    """Lock held. The reply's error when the last backup could not be used: what failed first, and why the backup was not used."""
    mine = first[2] if first[2] is not None else (find_account(bot.get('account'), first[0]) or {}).get('id', '')
    named = lambda p, a: auto_choice_name(p, a if a is not None else (find_account(bot.get('account'), p) or {}).get('id', ''))
    return '%s 沒有回覆（%s）；備用的 %s 沒有改用：%s。Zook 只用訂閱額度，不用 API 計費。' % (auto_choice_name(first[0], mine), why or '無法回覆', named(provider, account), problem)
