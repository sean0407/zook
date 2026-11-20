# 自動選擇: picks a model for each message from the task type and saved quota, without asking any model. Loaded by backend/server.py into one shared namespace.
AUTO = 'auto'
AUTO_MODELS = ('codex', 'claude', 'grok', 'antigravity', 'opencode', 'cursor')
AUTO_DEFAULT_OFF = ('antigravity', 'opencode', 'cursor')  # Antigravity: the user accepted an account risk; OpenCode, Cursor: CLIs added later. Each is used only when turned on
AUTO_SUBSCRIPTIONS = ('Claude 訂閱帳號', 'ChatGPT 帳號', 'Grok 帳號', 'Google 帳號', '免費模型')
AUTO_MIN_LEFT = 10  # percent of quota that must remain
AUTO_TASKS = dict(image=('看圖', ('codex', 'claude', 'antigravity', 'grok', 'opencode')), code=('寫程式', ('codex', 'claude', 'grok', 'antigravity', 'opencode', 'cursor')),
                  analysis=('長篇分析', ('claude', 'codex', 'antigravity', 'grok', 'opencode', 'cursor')), quick=('簡短問答', ('claude', 'codex', 'antigravity', 'opencode', 'cursor', 'grok')))  # measured: Grok thinks for tens of seconds before a short answer
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


def auto_state(provider, status, method):
    """Only a sign-in known to be a subscription counts as free to use; anything else is treated as billed."""
    signed = True if status == 'logged_in' else False if status == 'not_logged_in' else None
    return dict(signedIn=signed, billed=method not in AUTO_SUBSCRIPTIONS or any(provider_env(provider).get(k) for k in ACCOUNT_KEYS.get(provider, ())))


def merge_auto_status(old, new):
    """A check that could not finish keeps what was known before."""
    return {p: (old[p] if s.get('signedIn') is None and p in old else s) for p, s in new.items()}


def auto_known_billed(state):
    return bool(state) and state.get('signedIn') is True and bool(state.get('billed'))


def refresh_auto_status(store):
    if not _auto_checking.acquire(blocking=False): return  # one check at a time
    try:
        found = {p: auto_status(p) for p in AUTO_MODELS if P.spec(store.data, p) and find_cli(p)}
        with store.lock:
            store.data['autoStatus'] = merge_auto_status(store.data.get('autoStatus') or {}, found)
            try: store.save()
            except OSError: pass  # kept in memory; the next save writes it
    finally: _auto_checking.release()


def refresh_auto(app):
    """Keep sign-ins and limits current for the next pick, at most every five minutes and without delaying this reply."""
    if time.time() - app.__dict__.get('auto_refreshed', 0) < 300: return
    app.auto_refreshed = time.time()
    def work():
        store = app.store
        refresh_auto_status(store)
        with store.lock: allowed = auto_allowed(store)
        live = {}
        try:
            if 'codex' in allowed and find_cli('codex'):
                live['codex'] = normalize_quota('codex', codex_rpc(find_cli('codex'), 'account/rateLimits/read', {}, provider_env('codex', None)))
                if live['codex']: live['codex'].update(updatedAt=NOW(), source='live')
        except (OSError, ValueError, TimeoutError, AttributeError, RuntimeError, TypeError): pass
        try:
            if 'antigravity' in allowed and find_cli('antigravity'): live['antigravity'] = antigravity_quota(find_cli('antigravity'))
        except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError): pass
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


def auto_quota_low(store, provider):
    """True when the saved quota shows less than 10% left in a limit that has not reset yet."""
    snap = (store.data.get('quota') or {}).get(provider) or {}
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
    status = store.data['autoStatus']
    allowed = [p for p in order if p in auto_allowed(store) and P.spec(store.data, p) and find_cli(p) and (status.get(p) or {}).get('billed') is False and (status.get(p) or {}).get('signedIn') is not False]
    if task == 'image': allowed = [p for p in allowed if ability_on(store, p, 'images')]
    if plan: allowed = [p for p in allowed if provider_kind(p) in PLAN_KINDS and ability_on(store, p, 'plan')]
    if not allowed: raise ValueError('自動選擇目前沒有可用的模型。請到「各模型使用量」開啟至少一個已登入的模型。')
    short = lambda p: provider_label(p).split('（')[0]
    usable = [p for p in allowed if not auto_quota_low(store, p)]
    if not usable: raise ValueError('可自動選用的模型額度都低於 10%%：%s。Zook 不會自動改用付費方式，請等額度重置，或指定其他模型。' % '、'.join(short(p) for p in allowed))
    settings = store.data['settings']
    best, spread = usable[0], False
    if keep in usable: usable = [keep] + [p for p in usable if p != keep]
    elif taken is not None:
        rank, used = {p: i for i, p in enumerate(usable)}, {p: list(taken).count(p) for p in usable}
        usable = sorted(usable, key=lambda p: (used[p], rank[p])); spread = usable[0] != best
    chain = [[p, settings.get('model', '') if p == settings.get('provider', 'codex') else ''] for p in usable]
    why = ('這個 Bot 的角色偏向%s，所以用 %s' if by_role else 'Zook 判斷這是%s，所以用 %s') % (label, short(best))
    if spread: why = '%s原本會用 %s；群組裡讓成員分散使用不同模型，這次用 %s' % ('依角色' if by_role else '', short(best), short(usable[0]))
    elif usable[0] != best: why = '這一輪討論沿用一開始的 %s' % short(usable[0])
    elif best != allowed[0]: why += '（%s 額度不足）' % short(allowed[0])
    return chain, dict(auto='%s %s' % (short(usable[0]), AUTO_MARKS[task]), autoWhy=why)
