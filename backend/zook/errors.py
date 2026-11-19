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
    unknown='%s 沒有完成這次回覆。請再傳一次；一直發生的話，到「各模型使用量」確認登入狀態和模型設定。')
ERROR_REASONS = dict(denied='登入被拒絕', auth='尚未登入', quota='額度已用完', rate='請求太頻繁', busy='服務太忙', context='對話太長', model='模型不可用', network='連線有問題', unknown='無法回覆')


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
