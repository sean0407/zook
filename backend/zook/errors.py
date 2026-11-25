# Why a CLI could not answer, in one place: what it reported is sorted into a few kinds, and each kind has one plain sentence.
# Loaded by backend/server.py into one shared namespace.
#
# Only whole phrases are matched. A bare "401" or "quota" also turns up in port numbers, ids and ordinary text, and would
# send the user to sign in again or to top up for no reason. What the Bot itself wrote is never searched.
ERROR_PHRASES = (
    ('denied', ('403 forbidden', 'permission_error', 'status 403', 'code 403', 'http 403')),
    ('auth', ('not logged in', 'please log in', 'please login', 'login required', 'please run /login', 'run codex login', 'authentication required', 'authentication_error',
              'failed to authenticate', 'invalid api key', 'invalid x-api-key', 'incorrect api key', '401 unauthorized', 'status 401', 'code 401', 'unauthenticated',
              'token has expired', 'token is expired', 'sign in again', 'session expired')),
    ('quota', ('out of credits', 'insufficient credit', 'insufficient_quota', 'insufficient quota', 'usage limit', 'quota exceeded', 'exceeded your current quota', 'resource_exhausted',
               'credit balance is too low', 'limit reached', 'hit your limit', 'usage cap')),
    ('rate', ('rate limit', 'rate_limit', 'too many requests', 'status 429', 'code 429', 'http 429', '429 too')),
    ('busy', ('overloaded', 'service unavailable', 'no capacity', 'server is busy', 'status 503', 'code 503', 'http 503', 'status 529', 'code 529', 'bad gateway', 'status 502')),
    ('context', ('context length', 'context window', 'maximum context', 'prompt is too long', 'too many tokens', 'context_length_exceeded', 'input is too long')),
    ('model', ('model not found', 'model_not_found', 'unknown model', 'unsupported model', 'invalid model', 'model is not supported', 'does not exist or you do not have access')),
    ('network', ('network error', 'connection refused', 'connection reset', 'connection error', 'econnreset', 'econnrefused', 'enotfound', 'etimedout', 'could not resolve host',
                 'getaddrinfo', 'fetch failed', 'socket hang up', 'stream disconnected', 'error sending request', 'network is unreachable', 'no internet')),
    # macOS's privacy protection (TCC) said no: a file in Desktop, Documents or Downloads, or control of another App. Last, so a reply that
    # also hit a limit or lost its connection is shown as that.
    ('automation', ('not authorized to send apple events', 'erraeeventnotpermitted', '(-1743)')),
    ('privacy', ('operation not permitted', 'eperm')),
)
ERROR_MESSAGES = dict(
    denied='%s 的登入驗證被服務拒絕（403）。請到「各模型使用量」重新登入，或確認帳號方案與權限。',
    auth='%s 尚未登入，或登入已經過期。請到「各模型使用量」重新登入。',
    quota='%s 的額度已用完，或已達使用上限。請等額度重置，或改用其他模型。',
    rate='%s 現在收到太多請求。請稍等一下再傳一次。',
    busy='%s 的服務目前太忙。請稍後再試，或換一個模型。',
    context='這個對話太長，%s 讀不完。請開一個新對話再試。',
    model='%s 不支援目前選的模型。請到 Bot 設定換一個模型。',
    network='連不上 %s 的服務。請確認網路連線後再試。',
    automation='%s 想控制其他 App，但 macOS 沒有允許。請到「系統設定 › 隱私權與安全性 › 自動化」允許 Zook，再試一次。',
    privacy='%s 要讀寫的檔案被 macOS 的隱私保護擋住了。請到「系統設定 › 隱私權與安全性 › 完整磁碟取用權限」打開 Zook，再試一次。',
    unknown='%s 沒有完成這次回覆。請再傳一次；一直發生的話，到「各模型使用量」確認登入狀態和模型設定。')
ERROR_REASONS = dict(denied='登入被拒絕', auth='尚未登入', quota='額度已用完', rate='請求太頻繁', busy='服務太忙', context='對話太長', model='模型不可用', network='連線有問題', automation='macOS 權限擋住', privacy='macOS 權限擋住', unknown='無法回覆')


def classify_error(reported):
    """The kind of failure in what a CLI reported (its error field and its error output), or 'unknown'."""
    text = ' '.join(str(reported or '').lower().split())
    for kind, phrases in ERROR_PHRASES:
        if any(p in text for p in phrases): return kind
    return 'unknown'


def cli_failure(provider, reported):
    """(kind, the sentence the user sees) for a reply a CLI could not finish. Raw output is never shown."""
    kind = classify_error(reported)
    return kind, ERROR_MESSAGES[kind] % provider_label(provider).split('（')[0]


# ---- #238: what the window shows for a failed reply. One kind, whether simply trying again can help, a plain next step, and buttons
# that only start what already exists: answer again, answer with another model, the usage page, a new chat, the Bot's settings,
# or macOS's own privacy page. Worked out from the sentence the user already sees (and the kind the CLI reported), never from raw output.
PRIVACY_PANES = dict(files='x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles',
                     automation='x-apple.systempreferences:com.apple.preference.security?Privacy_Automation')
_RETRY, _MODEL, _USAGE = dict(action='retry', label='重試'), dict(action='redo-model', label='換模型'), '各模型使用量'
FAILURE_KINDS = dict(
    quota=('額度用完', False, '這個帳號的額度用完了。等額度恢復再重試，或先換一個模型回答。', [_MODEL, dict(action='usage', label='查看額度'), _RETRY]),
    auth=('沒登入', False, '到「各模型使用量」重新登入這個模型，再按重試；或先換一個模型回答。', [dict(action='usage', label='去登入'), _MODEL, _RETRY]),
    network=('網路', True, '確認這台 Mac 連得上網路，再按重試。', [_RETRY, _MODEL]),
    timeout=('逾時', True, '這次做太久或太久沒有動靜，已經停下。可以直接重試；常發生的話換一個模型，或把工作拆小一點。', [_RETRY, _MODEL]),
    approval=('被核准擋下', True, '這個動作要你核准才會做。要做的話按重試，跳出核准卡時按「允許」。', [_RETRY]),
    privacy=('macOS 權限擋住', False, '', [dict(action='settings', label='打開設定'), _RETRY]),
    install=('CLI 沒安裝', False, '到「各模型使用量」安裝並登入這個模型，或先換一個模型回答。', [dict(action='usage', label='去安裝'), _MODEL, _RETRY]),
    context=('對話太長', False, '開一個新對話再問一次，或換一個能讀更長對話的模型。', [dict(action='new-chat', label='開新對話'), _MODEL]),
    model=('模型不可用', False, '到 Bot 設定換一個模型版本，或這次先換一個模型回答。', [dict(action='edit-bot', label='Bot 設定'), _MODEL]),
    busy=('服務忙碌', True, '稍等一兩分鐘再按重試，或先換一個模型回答。', [_RETRY, _MODEL]),
    interrupted=('中斷', True, 'Zook 關閉或重新啟動時這則回覆還沒做完。按重試再做一次。', [_RETRY]),
    other=('其他', True, '再試一次；一直發生的話，到「各模型使用量」確認登入狀態，或換一個模型。', [_RETRY, _MODEL]))
PRIVACY_NEXT = dict(files='到「系統設定 › 隱私權與安全性 › 完整磁碟取用權限」打開 Zook，再按重試；或把檔案移出「桌面」「文件」「下載項目」。',
                    automation='到「系統設定 › 隱私權與安全性 › 自動化」允許 Zook 控制那個 App，再按重試。')
# The sentence's own words, in order: 「已超過時間上限」 is a timeout, not a limit; 「請先安裝並登入」 is a missing CLI, not a sign-in;
# the sentence for an unknown failure mentions 登入 only as something to check.
FAILURE_MARKS = (('privacy', ('macOS', '隱私')), ('approval', ('核准',)), ('install', ('找不到所選 CLI', '找不到這個提供者', '尚未安裝')),
                 ('timeout', ('逾時', '時間上限')), ('quota', ('額度', '用量預算')), ('other', ('沒有完成這次回覆',)), ('auth', ('登入',)), ('network', ('連不上',)),
                 ('busy', ('太忙', '太多請求')), ('context', ('對話太長',)), ('model', ('不支援目前選的模型',)), ('interrupted', ('工作已中斷',)))
FAILURE_OF_KIND = dict(quota='quota', auth='auth', denied='auth', network='network', rate='busy', busy='busy', context='context', model='model',
                       privacy='privacy', automation='privacy')


def failure_info(job):
    """For a failed job: dict(kind, label, retry, next, actions[, resetAt]). None for any other job."""
    if not isinstance(job, dict) or job.get('status') != 'failed': return None
    text = str(job.get('error') or '')
    kind = next((k for k, marks in FAILURE_MARKS if any(m in text for m in marks)), '') or FAILURE_OF_KIND.get(job.get('errorKind') or '', 'other')
    label, retry, step, actions = FAILURE_KINDS[kind]
    out = dict(kind=kind, label=label, retry=retry, next=step, actions=[dict(a) for a in actions])
    if kind == 'privacy':
        pane = 'automation' if job.get('errorKind') == 'automation' or '自動化' in text else 'files'
        out['next'] = PRIVACY_NEXT[pane]; out['actions'][0]['pane'] = pane
    if kind == 'quota' and isinstance(job.get('quotaResetAt'), str) and job['quotaResetAt']: out['resetAt'] = job['quotaResetAt']
    return out


def quota_reset_at(store, provider, account_id):
    """When the used-up window of this account comes back, as UTC ISO text, or '' when no full window is known to reset later."""
    snap = (store.data.get('quota') or {}).get(provider + '@' + account_id if account_id else provider) or {}
    now, times = time.time(), []
    for w in snap.get('windows') or []:
        if not isinstance(w, dict) or not isinstance(w.get('usedPercent'), (int, float)) or w['usedPercent'] < 100: continue
        reset = w.get('resetsAt')
        try: at = (reset / 1000 if reset > 1e12 else reset) if isinstance(reset, (int, float)) else datetime.datetime.fromisoformat(str(reset).replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError): continue
        if at > now: times.append(at)
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(max(times)))) if times else ''


def privacy_route(handler):
    """POST /api/privacy-settings {pane}: opens one of the two fixed macOS privacy pages on this Mac. Nothing else can be opened."""
    if handler.device: return handler.error(403, '請在 Mac 上打開系統設定。')
    pane = (handler.body() or {}).get('pane')
    url = PRIVACY_PANES.get(pane) if isinstance(pane, str) else None
    if not url: return handler.error(400, '沒有這個設定頁。')
    if not os.environ.get('ZOOK_NO_BROWSER'):
        try: subprocess.run(['/usr/bin/open', url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError): return handler.error(500, '打不開系統設定，請自己到「系統設定 › 隱私權與安全性」。')
    return handler.respond(200, dict(opened=True))
