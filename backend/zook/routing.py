# 自動選擇: picks a model for each message from the task type and saved quota, without asking any model. Loaded by backend/server.py into one shared namespace.
AUTO = 'auto'
AUTO_MODELS = ('codex', 'claude', 'grok', 'antigravity', 'cursor')
AUTO_DEFAULT_OFF = ('antigravity', 'cursor')  # Antigravity: the user accepted an account risk; Cursor: a CLI added later. Each is used only when turned on
AUTO_SUBSCRIPTIONS = ('Claude 訂閱帳號', 'ChatGPT 帳號', 'Grok 帳號', 'Google 帳號')
AUTO_MIN_LEFT = 10  # percent of quota that must remain
AUTO_TASKS = dict(image=('看圖', ('codex', 'claude', 'antigravity', 'grok')), code=('寫程式', ('codex', 'claude', 'grok', 'antigravity', 'cursor')),
                  analysis=('長篇分析', ('claude', 'codex', 'antigravity', 'grok', 'cursor')), quick=('簡短問答', ('claude', 'codex', 'antigravity', 'cursor', 'grok')))  # measured: Grok thinks for tens of seconds before a short answer
AUTO_MARKS = dict(image='image', code='code', analysis='analysis', quick='simple')  # the small mark at the end of a reply
AUTO_LONG = 1500
_AUTO_CODE = re.compile(r'```|`[^`\n]+`|程式|代碼|除錯|函式|腳本|報錯|重構|編譯|正則|(?<![a-z])(?:bug|debug|python|javascript|typescript|swift|sql|html|css|api|json|regex|script|git|commit|refactor|traceback|function)(?![a-z])', re.I)
_AUTO_ANALYSIS = re.compile(r'分析|比較|評估|研究|報告|策略|總結|摘要|規劃|企劃|優缺點|深入|(?<![a-z])(?:analy[sz]e|analysis|compare|research|report|summari[sz]e)(?![a-z])', re.I)


# What a Bot is for, read from its job title first, then its name, then its persona. It decides the model when the message itself does not say what
# kind of work it is. Work instructions are not read: a team often shares one text, which would make every member look alike.
_ROLE_CODE = re.compile(r'工程師|程式|軟體|前端|後端|開發者|資料庫|(?<![a-z])(?:engineer|developer|coder|devops|programmer)(?![a-z])', re.I)
_ROLE_ANALYSIS = re.compile(r'法規|法務|合規|品質|品管|財務|會計|稽核|營運|研發|研究|分析|策略|風險|審查|查核|數據|顧問|規劃|企劃|採購|供應鏈|(?<![a-z])(?:legal|compliance|quality|finance|accounting|audit|research|analyst|strategy|risk|planning)(?![a-z])', re.I)


def auto_role(bot):
    """'code', 'analysis' or None for a Bot whose role does not lean either way (design, marketing, sales, general help)."""
    for text in (bot.get('jobTitle'), bot.get('name'), (bot.get('persona') or '')[:300]):
        text = str(text or '')
        if _ROLE_CODE.search(text): return 'code'
        if _ROLE_ANALYSIS.search(text): return 'analysis'
    return None


_auto_checking = threading.Lock()


def auto_task(content, names=()):
    """The kind of work a message asks for, from its text and attached file names."""
    suffixes = [pathlib.Path(str(n)).suffix.lower() for n in names]
    text = content if isinstance(content, str) else ''
    if any(s in IMAGE_TYPES for s in suffixes): return 'image'
    if _AUTO_CODE.search(text): return 'code'
    if suffixes or len(text) >= AUTO_LONG or _AUTO_ANALYSIS.search(text): return 'analysis'
    return 'quick'


QUICK_NOTE = '；簡短問題用較快的思考強度'


def auto_quick_effort(store, bot, content, names=(), given=None):
    """'fast' when 自動選擇 sees a short question and neither the user, the Bot nor the settings asked for a thinking level."""
    if given or bot.get('effort') or (store.data['settings'].get('effort') or 'standard') != 'standard': return None
    if auto_task(content, names) != 'quick' or auto_role(bot): return None
    return 'fast'


def auto_status(provider):
    """What the CLI reports about its sign-in. Runs the CLI, so it is never called while a reply is being sent."""
    account = account_status(provider)
    return auto_state(provider, account['status'], account['method'])


def auto_state(provider, status, method, account=None):
    """Only a sign-in known to be a subscription counts as free to use; anything else is treated as billed."""
    signed = True if status == 'logged_in' else False if status == 'not_logged_in' else None
    if account and account.get('type') == 'key': return dict(signedIn=signed, billed=True)
    return dict(signedIn=signed, billed=method not in AUTO_SUBSCRIPTIONS or any(provider_env(provider, account).get(k) for k in ACCOUNT_KEYS.get(provider, ())))


# Extra accounts are choices of their own, keyed 'provider@account' in autoStatus and quota. Each has its own switch in
# settings['autoAccounts']; until the user sets it, a signed-in subscription is on (like the default accounts) and API billing never is.
def auto_accounts(store, provider=None):
    return [a for a in store.data.get('accounts') or [] if isinstance(a, dict) and a.get('provider') in AUTO_MODELS and (provider is None or a['provider'] == provider)]


def auto_account_key(account): return account['provider'] + '@' + account['id']


def auto_account_status(account):
    """What the CLI reports about one extra account's sign-in. Runs the CLI."""
    view = account_view(account)
    return auto_state(account['provider'], view['status'], view['method'], account)


def auto_ready(store, key):
    """Lock held. Known to be signed in to a subscription: billing is known to be off, and it is not known to be signed out."""
    status = (store.data.get('autoStatus') or {}).get(key)
    return isinstance(status, dict) and status.get('billed') is False and status.get('signedIn') is not False


def auto_account_on(store, account):
    """Lock held. Whether 自動選擇 may use this extra account."""
    status = (store.data.get('autoStatus') or {}).get(auto_account_key(account)) or {}
    if account.get('type') == 'key' or auto_known_billed(status): return False  # API billing is never picked automatically
    switches = store.data['settings'].get('autoAccounts')
    chosen = switches.get(account['id']) if isinstance(switches, dict) else None  # a malformed value (an old backup) counts as not set
    if isinstance(chosen, bool): return chosen
    return account['provider'] not in AUTO_DEFAULT_OFF and status.get('signedIn') is True and status.get('billed') is False


def auto_account_name(account_id): return (find_account(account_id) or {}).get('name', '')


def auto_choice_problem(store, provider, account_id):
    """Lock held. Why a pick made earlier may no longer run now (the switch was turned off, the account was removed or is billed), or ''."""
    status = store.data.get('autoStatus') or {}
    if not account_id:
        if auto_known_billed(status.get(provider)): return 'API 計費不會被自動選用'
        if provider not in auto_allowed(store): return '已關閉自動選用'
        return '' if auto_ready(store, provider) else '還沒確認是訂閱帳號'
    account = find_account(account_id, provider)
    if not account: return '帳號已移除'
    if not auto_account_on(store, account): return '已關閉自動選用或使用 API 計費'
    return '' if auto_ready(store, auto_account_key(account)) else '還沒確認是訂閱帳號'


def auto_choice_name(provider, account_id=''):
    """'Codex', or 'Codex（Waifdance）' for an extra account."""
    short = provider_label(provider).split('（')[0]
    return '%s（%s）' % (short, auto_account_name(account_id)) if account_id else short


def merge_auto_status(old, new):
    """A check that could not finish keeps what was known before."""
    return {p: (old[p] if s.get('signedIn') is None and p in old else s) for p, s in new.items()}


def auto_known_billed(state):
    return bool(state) and state.get('signedIn') is True and bool(state.get('billed'))


AUTO_FRESH = 600  # seconds a sign-in check counts as current, for a Bot whose fixed model must not run on API billing


def refresh_auto_status(store, wait=False):
    if not _auto_checking.acquire(blocking=wait): return  # one check at a time; wait=True waits for the one under way
    try:
        found = {p: auto_status(p) for p in AUTO_MODELS if P.spec(store.data, p) and find_cli(p)}
        with store.lock: extras = [dict(a) for a in auto_accounts(store) if P.spec(store.data, a['provider'])]
        for account in extras:
            if find_cli(account['provider']):
                try: found[auto_account_key(account)] = auto_account_status(account)
                except (OSError, ValueError, RuntimeError): pass
        for key, state in found.items():
            if state.get('signedIn') is not None: state.update(checkedAt=time.time(), signIn=auth_fingerprint(key))  # a check that finished
        with store.lock:
            store.data['autoStatus'] = merge_auto_status(store.data.get('autoStatus') or {}, found)
            try: store.save()
            except OSError: pass  # kept in memory; the next save writes it
            try: auto_retry(store)  # Bots that could not be matched before
            except OSError: pass
    finally: _auto_checking.release()


def refresh_auto(app):
    """Keep sign-ins and limits current for the next pick, at most every five minutes and without delaying this reply."""
    if time.time() - app.__dict__.get('auto_refreshed', 0) < 300: return
    app.auto_refreshed = time.time()
    def work():
        store = app.store
        refresh_auto_status(store)
        with store.lock: allowed = auto_allowed(store); extras = [dict(a) for a in auto_accounts(store, 'codex') if auto_account_on(store, a)]
        live = {}
        for key, account in ([('codex', None)] if 'codex' in allowed else []) + [(auto_account_key(a), a) for a in extras]:
            try:
                if find_cli('codex'):
                    live[key] = normalize_quota('codex', codex_rpc(find_cli('codex'), 'account/rateLimits/read', {}, provider_env('codex', account)))
                    if live[key]: live[key].update(updatedAt=NOW(), source='live')
            except (OSError, ValueError, TimeoutError, AttributeError, RuntimeError, TypeError): pass
        with store.lock: groks = [dict(a) for a in auto_accounts(store, 'grok') if auto_account_on(store, a)]
        for key, account in ([('grok', None)] if 'grok' in allowed else []) + [(auto_account_key(a), a) for a in groks]:
            try:
                if find_cli('grok'): live[key] = grok_live_quota(app, account)
            except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError): pass
        with store.lock: agys = [dict(a) for a in auto_accounts(store, 'antigravity') if auto_account_on(store, a)]
        for key, account in ([('antigravity', None)] if 'antigravity' in allowed else []) + [(auto_account_key(a), a) for a in agys]:
            try:
                if find_cli('antigravity'): live[key] = antigravity_quota(find_cli('antigravity'), provider_env('antigravity', account) if account else None)
            except (OSError, ValueError, TypeError, AttributeError, RuntimeError, subprocess.SubprocessError): pass
        with store.lock:
            store.data.setdefault('quota', {}).update({k: v for k, v in live.items() if v}); store.save()
    threading.Thread(target=work, daemon=True).start()


def watch_auto_status(store, bot):
    """A Bot just switched to 自動選擇: learn which models are signed in, without making the request wait for the CLIs."""
    if bot.get('provider') == AUTO and 'autoStatus' not in store.data: threading.Thread(target=refresh_auto_status, args=(store,), daemon=True).start()


def auto_allowed(store):
    """The models 自動選擇 may use. Until the user chooses: signed-in subscriptions only, never API billing."""
    chosen = store.data['settings'].get('autoModels')
    status = store.data.get('autoStatus') or {}
    if isinstance(chosen, list): return [p for p in AUTO_MODELS if p in chosen and not auto_known_billed(status.get(p))]  # API billing is never picked automatically
    return [p for p in AUTO_MODELS if p not in AUTO_DEFAULT_OFF and (status.get(p) or {}).get('signedIn') and not status[p].get('billed')]


def _window_open(window, snap, now):
    reset = window.get('resetsAt')
    try:
        if isinstance(reset, (int, float)): at = reset / 1000 if reset > 1e12 else reset
        else: at = datetime.datetime.fromisoformat(str(reset).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        try: at = datetime.datetime.fromisoformat(snap['updatedAt']).timestamp() + 5 * 3600
        except (KeyError, ValueError, TypeError): return False
    return at > now


BACKUP_MIN_LEFT = 20  # a backup with less left than this is used only when every backup is that low


def backup_low(store, provider, account_id=''):
    """True when the saved quota shows less than BACKUP_MIN_LEFT% left in a limit that has not reset yet."""
    snap = (store.data.get('quota') or {}).get(provider + '@' + account_id if account_id else provider) or {}
    if limit_reached_now(snap): return True
    windows = [w for w in snap.get('windows') or [] if isinstance(w, dict)]
    if provider == 'antigravity': windows = [w for w in windows if 'gemini' in str(w.get('label')).lower()] or windows  # Zook runs its default Gemini model
    now = time.time()
    return any(isinstance(w.get('usedPercent'), (int, float)) and w['usedPercent'] > 100 - BACKUP_MIN_LEFT and _window_open(w, snap, now) for w in windows)


def backups_with_room(store, bot, backups):
    """The backups in order, those with less than 20% left moved after the rest: a nearly used-up account answers only when nothing else can."""
    def low(x):
        own = None if x[2] is not None else find_account(bot.get('account'), x[0])
        account = x[2] or (own or {}).get('id') or ''
        return backup_low(store, x[0], account)
    marks = [low(x) for x in backups]
    return [x for x, m in zip(backups, marks) if not m] + [x for x, m in zip(backups, marks) if m]


def auto_quota_low(store, provider, account_id=''):
    """True when the saved quota shows less than 10% left in a limit that has not reset yet."""
    snap = (store.data.get('quota') or {}).get(provider + '@' + account_id if account_id else provider) or {}
    if limit_reached_now(snap): return True  # e.g. the workspace ran out of credits (a recent reading only)
    windows = [w for w in snap.get('windows') or [] if isinstance(w, dict)]
    if provider == 'antigravity': windows = [w for w in windows if 'gemini' in str(w.get('label')).lower()] or windows  # Zook runs its default Gemini model
    now = time.time()
    return any(isinstance(w.get('usedPercent'), (int, float)) and w['usedPercent'] > 100 - AUTO_MIN_LEFT and _window_open(w, snap, now) for w in windows)


def pick_auto(store, content, names=(), plan=False, bot=None, taken=None, keep=None):
    """(models to try in order, the fields that mark the reply). Raises ValueError when nothing can answer.

    The message decides when it is plainly an image, code or analysis task. Otherwise the Bot's own role does.
    In a group, taken lists the models the other members are already using this round, so the members are spread over
    different models; keep is the model this Bot already answered with in this round, which it stays on."""
    task = auto_task(content, names); by_role = False
    if task == 'quick' and bot and auto_role(bot): task, by_role = auto_role(bot), True
    label, order = AUTO_TASKS[task]
    if 'autoStatus' not in store.data:  # billing is not known yet, so nothing can be picked safely
        threading.Thread(target=refresh_auto_status, args=(store,), daemon=True).start()
        raise ValueError('正在確認各模型的登入狀態，請幾秒後再送一次。')
    allowed, usable = auto_candidates(store, task, order, plan)
    name = lambda c: auto_choice_name(*c)
    settings = store.data['settings']
    best, spread = usable[0], False
    kept = next((c for c in usable if c[0] == keep), None)
    if kept: usable = [kept] + [c for c in usable if c != kept]
    elif taken is not None:
        rank, used = {c: i for i, c in enumerate(usable)}, {p: list(taken).count(p) for p in {c[0] for c in usable}}
        usable = sorted(usable, key=lambda c: (used[c[0]], rank[c])); spread = usable[0][0] != best[0]
    chain = [[p, settings.get('model', '') if p == settings.get('provider', 'codex') else '', a] for p, a in usable]  # always the account: '' is the CLI's own sign-in
    why = ('這個 Bot 的角色偏向%s，所以用 %s' if by_role else 'Zook 判斷這是%s，所以用 %s') % (label, name(best))
    if spread: why = '%s原本會用 %s；群組裡讓成員分散使用不同模型，這次用 %s' % ('依角色' if by_role else '', name(best), name(usable[0]))
    elif usable[0] != best: why = '這一輪討論沿用一開始的 %s' % name(usable[0])
    elif best != allowed[0]: why += '（%s 額度不足）' % name(allowed[0])
    return chain, dict(auto='%s %s' % (name(usable[0]), AUTO_MARKS[task]), autoWhy=why)


def auto_candidates(store, task, order, plan=False):
    """Lock held. (signed-in subscriptions that may be picked, in order; those of them with quota left). Raises ValueError when none."""
    allowed = auto_choices(store, task, order, plan)
    usable = [c for c in allowed if not auto_quota_low(store, *c)]
    if not usable: raise ValueError('可自動選用的模型額度都低於 10%%：%s。Zook 不會自動改用付費方式，請等額度重置，或指定其他模型。' % '、'.join(auto_choice_name(*c) for c in allowed))
    return allowed, usable


def auto_choices(store, task, order, plan=False):
    """Lock held. The signed-in subscriptions that may be picked, best fit first, whatever quota they have left. Raises ValueError when none."""
    main = auto_allowed(store)
    ready = lambda key: auto_ready(store, key)
    allowed = []  # (provider, account id); '' is the CLI's own sign-in, which comes before that CLI's extra accounts
    for p in order:
        if not (P.spec(store.data, p) and find_cli(p)): continue
        if task == 'image' and not ability_on(store, p, 'images'): continue
        if plan and not (provider_kind(p) in PLAN_KINDS and ability_on(store, p, 'plan')): continue
        if p in main and ready(p): allowed.append((p, ''))
        allowed += [(p, a['id']) for a in auto_accounts(store, p) if auto_account_on(store, a) and ready(auto_account_key(a))]
    if not allowed: raise ValueError('自動選擇目前沒有可用的模型。請到「各模型使用量」開啟至少一個已登入的模型。')
    return allowed


# 自動選擇 decides when a Bot is made (2026-11-22): its model is fixed from what it is for, and it answers with that model from then
# on. A Bot whose work changes (persona or work instructions) is matched again when it is saved. A Bot stays on 自動選擇 (each
# message picks) only when no model could be picked: sign-ins not known yet or none turned on. The match looks at the work only, never
# at the quota left right now (2026-11-22): when the matched model runs out, each message's backup models take over.
AUTO_WORK = dict(code='寫程式多', analysis='分析和寫報告多', image='常要看圖', quick='一般問答和文書為主')


def bot_work(bot, instructions=True):
    """'code', 'analysis' or 'quick': what a Bot is for, from its job title, name and persona, then its work instructions."""
    role = auto_role(bot)
    if role: return role
    text = str(bot.get('instructions') or '')[:3000] if instructions else ''
    if _ROLE_CODE.search(text): return 'code'
    if _ROLE_ANALYSIS.search(text): return 'analysis'
    found = auto_task(' '.join([str(bot.get('persona') or '')[:3000], text]))
    return found if found in ('code', 'analysis') else 'quick'


def auto_assign(store, bot, instructions=True, grant=False):
    """Lock held. Fix a model for the Bot from what it is for. Returns the reason (「寫程式多，配 Codex」), or '' when none could be picked.
    grant: the user is making or setting this Bot on this Mac right now. Anything else (a match in the background, a re-match after an
    edit, a Bot made by another Bot) never widens what it may reach (set_access_after_match in core.py)."""
    if 'autoStatus' not in store.data: return ''
    task = bot_work(bot, instructions)
    try: provider, account = auto_choices(store, task, AUTO_TASKS[task][1])[0]
    except ValueError: return ''
    reason = '%s，配 %s' % (AUTO_WORK[task], auto_choice_name(provider, account))
    model = auto_known_model(store, provider, account)
    bot.update(provider=provider, account=account, model=model, autoAssigned=True, autoReason=reason)
    for key in ('autoPending', 'syncedModel', 'autoRematch'): bot.pop(key, None)
    if model: bot.pop('autoModelPending', None)
    else: bot['autoModelPending'] = True  # the CLI's own default is not known yet: the model of its first reply is kept (app.py)
    set_access_after_match(bot, grant)
    return reason


def auto_known_model(store, provider, account=''):
    """Lock held. The CLI's default model, as this Mac sets it: the default model in 設定 for the default CLI, or Codex's own setting.
    '' when it is not written anywhere (Claude, Cursor, Grok, Antigravity): then the model of the Bot's own first reply is kept. Never
    a model another Bot or an earlier reply used."""
    settings = store.data['settings']
    if provider == settings.get('provider', 'codex') and clean_model(settings.get('model')): return settings['model']
    if provider_kind(provider) == 'codex':
        return clean_model(codex_default_model(provider_env(provider, find_account(account, provider) if account else None))) or ''
    return ''


def auto_pin_model(store, bot_id, provider, usage):
    """Lock held. A Bot matched automatically whose model was not known keeps the model its first reply reported."""
    bot = store.find('bots', bot_id)
    if not bot or not bot.get('autoModelPending') or bot.get('provider') != provider or not clean_model((usage or {}).get('model')): return
    bot['model'] = usage['model']; bot.pop('autoModelPending', None)


def auto_billing_problem(store, provider, account_id):
    """Lock held. For a Bot matched automatically: why the account it really runs on may cost money now, or ''. Checked before
    its model and each backup run, since an account can be removed, signed out or switched to API billing after the match."""
    if account_id:
        account = find_account(account_id, provider)
        if not account: return '帳號已移除'
        if account.get('type') == 'key': return 'API 計費不會被自動選用'
        key = auto_account_key(account)
    else: key = provider
    state = (store.data.get('autoStatus') or {}).get(key) or {}
    if auto_known_billed(state): return 'API 計費不會被自動選用'
    if _auto_stale(state, key): return '最近沒能確認是訂閱帳號'
    return '' if state.get('signedIn') is True and state.get('billed') is False else '還沒確認是訂閱帳號'


def auto_status_forget(store, provider):
    """A sign-in of this CLI (its own or an extra account) is being changed in Zook: its billing is checked again before the next use."""
    with store.lock:
        for key, state in (store.data.get('autoStatus') or {}).items():
            if (key == provider or key.startswith(provider + '@')) and isinstance(state, dict): state.pop('checkedAt', None)


def auto_recheck(store, keys):
    """Ask each CLI now which sign-in (and so which billing) these keys use. Runs the CLIs: never with the lock held. A key whose CLI
    cannot say is left unchecked, so it is not used."""
    for key in dict.fromkeys(keys):
        provider, _, account_id = key.partition('@')
        with store.lock: account = dict(find_account(account_id, provider) or {}) if account_id else None
        try: state = auto_account_status(account) if account else auto_status(provider) if not account_id else dict(signedIn=None, billed=True)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError): state = dict(signedIn=None, billed=True)
        if state.get('signedIn') is not None: state.update(checkedAt=time.time(), signIn=auth_fingerprint(key))
        with store.lock:
            status = store.data.setdefault('autoStatus', {})
            if state.get('signedIn') is None: (status.get(key) or {}).pop('checkedAt', None)  # could not say: not used until it can
            else: status[key] = state


def auto_billing_keys(store, bot, chain):
    """Lock held. The sign-ins a fixed Bot's tries really use, as autoStatus keys."""
    keys = []
    for p, _, a, _ in chain:
        acct = a if a is not None else (find_account(bot.get('account'), p) or {}).get('id', '')
        account = find_account(acct, p) if acct else None
        keys.append(auto_account_key(account) if account else p)
    return keys


def auto_billing_stale(store, keys):
    """Lock held. Whether any of these sign-ins was not checked recently."""
    status = store.data.get('autoStatus') or {}
    return any(_auto_stale(status.get(k) or {}, k) for k in keys)


# CLIs whose sign-in Zook cannot watch on disk (Claude keeps it in the Keychain; Cursor and Antigravity in their own stores): their
# billing is asked of the CLI itself right before each request (auto_recheck_live), so only a check from these last seconds counts:
# no cached answer is used. Asking takes about 0.1 s for Claude and 1 s for Cursor (measured 2026-11-22).
UNWATCHED = ('claude', 'cursor', 'antigravity')
AUTO_LIVE = 10


def auto_unwatched(key): return provider_kind(str(key).partition('@')[0]) in UNWATCHED


def auto_recheck_live(store, bot, provider, account):
    """Right before a request of a Bot whose model must not run on API billing: ask a CLI Zook cannot watch which sign-in it uses now."""
    with store.lock: key = auto_billing_keys(store, bot, [(provider, '', account, False)])[0]
    if auto_unwatched(key): auto_recheck(store, [key])


def _auto_stale(state, key):
    """Not checked recently enough, or its sign-in files changed since (a sign-in switched outside Zook)."""
    limit = AUTO_LIVE if provider_kind(str(key).partition('@')[0]) in UNWATCHED else AUTO_FRESH
    if not isinstance(state.get('checkedAt'), (int, float)) or time.time() - state['checkedAt'] > limit: return True
    return 'signIn' in state and state['signIn'] != auth_fingerprint(key)


def auth_fingerprint(key):
    """When the files a CLI keeps its sign-in in last changed, for a sign-in Zook can see on disk (Claude keeps its own in the Keychain)."""
    provider, _, account_id = str(key).partition('@')
    account = find_account(account_id, provider) if account_id else None
    if account_id:  # an extra account signs in inside its own folder; a key account has nothing on disk to watch
        try: files = [account_dir(account['id'])] if account and account.get('type') == 'login' and provider in ACCOUNT_HOME else []
        except ValueError: files = []
    else: files = [pathlib.Path(os.path.expanduser(p)) for p in AUTH_FILES.get(provider_kind(provider) or '', ())]
    out = []
    for f in files:
        try: out.append([str(f), max([f.stat().st_mtime] + [c.lstat().st_mtime for c in f.iterdir()] if f.is_dir() else [f.stat().st_mtime])])
        except OSError: out.append([str(f), 0])
    return out


AUTH_FILES = {'codex': ('~/.codex/auth.json',), 'grok': ('~/.grok',), 'generic': ('~/.gemini/oauth_creds.json',), 'claude': ('~/.claude/.credentials.json',)}


def auto_on_create(store, bot, instructions=True, grant=False):
    """Lock held. A new Bot on 自動選擇 gets its model now; when none can be picked, it stays on 自動選擇 (each message picks)."""
    for key in ('autoAssigned', 'autoReason', 'autoPending', 'autoModelPending'): bot.pop(key, None)
    return auto_assign(store, bot, instructions, grant) if bot.get('provider') == AUTO else ''


def auto_on_edit(store, before, after, body):
    """Lock held. Saving a Bot: choosing 自動選擇 matches it again; a model chosen by hand ends the automatic match; a Bot that was
    matched automatically and whose work changed is matched again. Returns what to tell the user, or ''."""
    if after.get('provider') == AUTO:
        if body.get('provider') != AUTO: return ''
        reason = auto_on_create(store, after, grant=True)  # the user chose 自動選擇 here, now
        return '已自動配好：' + reason if reason else ''
    if not before.get('autoAssigned'): return ''
    if not after.get('model') and after.get('provider') == before.get('provider'): after['model'] = before.get('model') or ''  # 「預設」 in the form: the model it was matched with
    if any((after.get(k) or '') != (before.get(k) or '') for k in ('provider', 'account', 'model')):
        for key in ('autoAssigned', 'autoReason', 'autoModelPending', 'autoRematch'): after.pop(key, None)
        return ''  # the user picked a model: it stays
    if all(after.get(k) == before.get(k) for k in ('persona', 'instructions', 'jobTitle', 'name')): return ''
    trial = auto_rematch(store, after)
    if not trial: return ''  # nothing can be picked right now, or it stays where it is
    log_activity(store, 'bot', 'Bot「%s」的工作內容改了，改配 %s' % (after.get('name', ''), trial['autoReason']), by='Zook')
    return '工作內容改了，改配 ' + auto_choice_name(trial['provider'], trial['account']) + '（' + trial['autoReason'] + '）'


def auto_rematch(store, bot):
    """Lock held. Match a Bot that was matched automatically again, in place, never widening what it may reach. Returns the new match
    when it moved to another model, else None (it keeps its model, with the reason brought up to date)."""
    trial = dict(bot)
    if not auto_assign(store, trial): return None  # nothing can be picked right now: it keeps the model it has
    bot.pop('autoRematch', None); bot['autoReason'] = trial['autoReason']
    for key in ('gateFull', 'localLimit'):  # a re-match never widens it: held in when it moves off the gate (set_access_after_match)
        if key in trial: bot[key] = trial[key]
        else: bot.pop(key, None)
    if (trial['provider'], trial['account']) == (bot.get('provider'), bot.get('account') or ''): return None  # same model: it keeps it
    bot.update({k: trial[k] for k in ('provider', 'account', 'model', 'autoAssigned')})
    if 'autoModelPending' in trial: bot['autoModelPending'] = True
    else: bot.pop('autoModelPending', None)
    return trial


def auto_migrate(store):
    """At start: every Bot on 自動選擇 from before 2026-11-22 is marked to be matched, once per data folder; then every Bot waiting
    to be matched gets its model now if one can be picked (auto_retry). Sign-ins are checked first."""
    with store.lock:
        if not store.data['settings'].get('autoFixed'):
            for bot in store.data['bots']:
                if bot.get('provider') == AUTO: bot['autoPending'] = True
            store.data['settings']['autoFixed'] = True; store.save()
        if not store.data['settings'].get('autoByWork'):  # 0.20.0 matched by the quota left at that moment: matched again by the work, once
            for bot in store.data['bots']:
                if bot.get('autoAssigned') and bot.get('provider') != AUTO and '額度不足' in str(bot.get('autoReason') or ''): bot['autoRematch'] = True
            store.data['settings']['autoByWork'] = True; store.save()
        waiting = any(b.get('provider') == AUTO or b.get('autoRematch') for b in store.data['bots'])
    if waiting: refresh_auto_status(store)  # runs each CLI; never with the lock held; ends with auto_retry


def auto_retry(store):
    """Lock held. Bots still waiting to be matched (no model could be picked before) get one now if one can; each is recorded by
    itself, so a Bot left waiting is tried again after the next sign-in check, and one that is matched is told once."""
    changed = False
    for bot in store.data['bots']:
        if bot.get('autoRematch'): changed = _auto_rematch_old(store, bot) or changed
        if bot.get('provider') != AUTO or not bot.get('autoPending'): continue
        reason = auto_assign(store, bot)
        if reason: changed = True; log_activity(store, 'bot', 'Bot「%s」原本用自動選擇，現在固定配好：%s。可以在編輯 Bot 改。' % (bot['name'], reason), by='Zook')
        elif not bot.get('autoPendingTold'):
            bot['autoPendingTold'] = True; changed = True
            log_activity(store, 'bot', 'Bot「%s」用自動選擇，目前沒有能配的模型，先維持每則訊息自動挑；帳號可用時會再配。' % bot['name'], by='Zook')
        if reason: bot.pop('autoPendingTold', None)
    if changed: store.save()


def _auto_rematch_old(store, bot):
    """Lock held. A Bot 0.20.0 matched by the quota left at that moment: matched again by its work. Only a move is told. True when changed."""
    if not bot.get('autoAssigned') or bot.get('provider') == AUTO:  # chosen by hand since, or by another Mac: not this Mac's match any more
        bot.pop('autoRematch', None); return True
    before = bot.get('autoReason')
    trial = auto_rematch(store, bot)
    if trial: log_activity(store, 'bot', 'Bot「%s」改依工作內容配模型，改配 %s（%s）。可以在編輯 Bot 改。' % (bot.get('name', ''), auto_choice_name(trial['provider'], trial['account']), trial['autoReason']), by='Zook')
    return bool(trial) or 'autoRematch' not in bot or bot.get('autoReason') != before
