# 自動選擇: picks a model for each message from the task type and saved quota, without asking any model. Loaded by backend/server.py into one shared namespace.
AUTO = 'auto'
AUTO_MODELS = ('codex', 'claude', 'grok', 'antigravity')
AUTO_DEFAULT_OFF = ('antigravity',)  # the user accepted an account risk for this one, so it is only used when turned on
AUTO_MIN_LEFT = 10  # percent of quota that must remain
AUTO_TASKS = dict(image=('看圖', ('codex', 'claude', 'antigravity', 'grok')), code=('寫程式', ('codex', 'claude', 'grok', 'antigravity')),
                  analysis=('長篇分析', ('claude', 'codex', 'antigravity', 'grok')), quick=('簡短問答', ('grok', 'antigravity', 'codex', 'claude')))
AUTO_LONG = 1500
_AUTO_CODE = re.compile(r'```|`[^`\n]+`|程式|代碼|除錯|函式|腳本|報錯|重構|編譯|正則|(?<![a-z])(?:bug|debug|python|javascript|typescript|swift|sql|html|css|api|json|regex|script|git|commit|refactor|traceback|function)(?![a-z])', re.I)
_AUTO_ANALYSIS = re.compile(r'分析|比較|評估|研究|報告|策略|總結|摘要|規劃|企劃|優缺點|深入|(?<![a-z])(?:analy[sz]e|analysis|compare|research|report|summari[sz]e)(?![a-z])', re.I)


def auto_task(content, names=()):
    """The kind of work a message asks for, from its text and attached file names."""
    suffixes = [pathlib.Path(str(n)).suffix.lower() for n in names]
    text = content if isinstance(content, str) else ''
    if any(s in IMAGE_TYPES for s in suffixes): return 'image'
    if _AUTO_CODE.search(text): return 'code'
    if suffixes or len(text) >= AUTO_LONG or _AUTO_ANALYSIS.search(text): return 'analysis'
    return 'quick'


def auto_status(provider):
    """What the CLI reports about its sign-in. Runs the CLI, so it is never called while a reply is being sent."""
    account = account_status(provider)
    return auto_state(provider, account['status'], account['method'])


def auto_state(provider, status, method):
    signed = True if status == 'logged_in' else False if status == 'not_logged_in' else None
    return dict(signedIn=signed, billed=method in ('Anthropic Console', 'API 金鑰') or any(provider_env(provider).get(k) for k in ACCOUNT_KEYS.get(provider, ())))


def refresh_auto_status(store):
    found = {p: auto_status(p) for p in AUTO_MODELS if P.spec(store.data, p) and find_cli(p)}
    with store.lock: store.data['autoStatus'] = found; store.save()


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
            if 'codex' in allowed:
                live['codex'] = normalize_quota('codex', codex_rpc(find_cli('codex'), 'account/rateLimits/read', {}, provider_env('codex', None)))
                if live['codex']: live['codex'].update(updatedAt=NOW(), source='live')
        except (OSError, ValueError, TimeoutError, AttributeError, RuntimeError): pass
        try:
            if 'antigravity' in allowed: live['antigravity'] = antigravity_quota(find_cli('antigravity'))
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
    if isinstance(chosen, list): return [p for p in AUTO_MODELS if p in chosen and not (status.get(p) or {}).get('billed')]  # API billing is never picked automatically
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


def pick_auto(store, content, names=(), plan=False):
    """(models to try in order, the note shown under the reply). Raises ValueError when nothing can answer."""
    task = auto_task(content, names); label, order = AUTO_TASKS[task]
    if 'autoStatus' not in store.data:  # billing is not known yet, so nothing can be picked safely
        threading.Thread(target=refresh_auto_status, args=(store,), daemon=True).start()
        raise ValueError('正在確認各模型的登入狀態，請幾秒後再送一次。')
    status = store.data['autoStatus']
    allowed = [p for p in order if p in auto_allowed(store) and P.spec(store.data, p) and find_cli(p) and (status.get(p) or {}).get('signedIn') is not False]
    if task == 'image': allowed = [p for p in allowed if ability_on(store, p, 'images')]
    if plan: allowed = [p for p in allowed if provider_kind(p) in PLAN_KINDS and ability_on(store, p, 'plan')]
    if not allowed: raise ValueError('自動選擇目前沒有可用的模型。請到「各模型使用量」開啟至少一個已登入的模型。')
    short = lambda p: provider_label(p).split('（')[0]
    usable = [p for p in allowed if not auto_quota_low(store, p)]
    if not usable: raise ValueError('可自動選用的模型額度都低於 10%%：%s。Zook 不會自動改用付費方式，請等額度重置，或指定其他模型。' % '、'.join(short(p) for p in allowed))
    settings = store.data['settings']
    chain = [[p, settings.get('model', '') if p == settings.get('provider', 'codex') else ''] for p in usable]
    note = '自動選用 %s：%s' % (short(usable[0]), label)
    if usable[0] != allowed[0]: note += '（%s 額度不足）' % short(allowed[0])
    return chain, note
