# The activity record (#12 #27 #304 #247): what Zook did for you. Every finished reply of a Bot or a group is one line (when, which
# Bot or group, what it did in one plain sentence, how it ended, which CLI and model, and for a failure why and what to do next), next
# to the changes and approvals recorded before. Kept in its own file so restoring a backup does not rewrite history; at most
# ACTIVITY_KEEP lines and ACTIVITY_DAYS days. Never the message, a key or a whole path: only fixed words, names and a file's own name.
# Loaded by backend/server.py into one shared namespace, before chatfiles.py (Store finishes a reply through AuditTrail).
import datetime, json, os, re, threading

ACTIVITY_KEEP = 5000
ACTIVITY_DAYS = 90
ACTIVITY_ROOM = 100  # trimmed this many lines below ACTIVITY_KEEP, so the file is rewritten once every ACTIVITY_ROOM lines, not at every reply
ACTIVITY_PAGE = 50
ACTIVITY_KINDS = {'work': '工作', 'approval': '核准', 'tool': '對外動作', 'bot': 'Bot 與群組', 'setting': '設定', 'connector': 'Skills 與連接器', 'schedule': '排程',
                  'data': '知識與記憶', 'backup': '備份與同步', 'device': '裝置'}
ACTIVITY_CATEGORIES = {'work': 'Bot 與群組的工作', 'admin': '設定與核准'}  # 'admin': every line that is not a reply (the record before #304)
ACTIVITY_RANGES = {'today': '今天', '7d': '最近 7 天', '30d': '最近 30 天', '90d': '最近 90 天'}
ACTIVITY_FIELDS = ('botId', 'groupId', 'chatId', 'messageId', 'provider', 'providerName', 'model', 'result', 'why', 'next')
ACTIVITY_MERGE_SECONDS = 1800
_activity_lock = threading.Lock()
_activity_checked = {}  # file -> (the day it was last trimmed, its lines since)


def activity_path(store): return store.dir / 'activity.jsonl'


def _activity_at(line):
    found = re.search(r'"at": "([^"]*)"', line)
    return found.group(1) if found else ''


def _activity_cutoff(days):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()


def _activity_trim(path, keep=ACTIVITY_KEEP):
    """_activity_lock held. Only the newest `keep` lines of the last ACTIVITY_DAYS days stay. Returns how many lines are left."""
    lines = path.read_text(encoding='utf-8').splitlines()
    cutoff = _activity_cutoff(ACTIVITY_DAYS)
    kept = [x for x in lines if x.strip() and _activity_at(x) >= cutoff][-keep:]
    if len(kept) == len(lines): return len(kept)
    temp = path.with_name(path.name + '.tmp')
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(''.join(x + '\n' for x in kept))
    os.replace(str(temp), str(path))
    return len(kept)


def activity_prune(store):
    """Drop what is past the limits now. Never raises."""
    try:
        with _activity_lock:
            path = activity_path(store)
            if path.exists(): _activity_checked[str(path)] = (NOW()[:10], _activity_trim(path))
    except OSError: pass


def log_activity(store, kind, text, by='', **extra):
    """Add one line. Never raises: a full disk must not break the action being recorded."""
    item = dict(id=ID(), at=NOW(), kind=kind, text=' '.join(str(text).split())[:300], by=str(by or '這台 Mac')[:60])
    item.update({k: ' '.join(v.split())[:300] for k, v in extra.items() if k in ACTIVITY_FIELDS and isinstance(v, str) and v})
    line = json.dumps(item, ensure_ascii=False)
    try:
        with _activity_lock:
            path = activity_path(store)
            fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, 'a', encoding='utf-8') as f: f.write(line + '\n')
            day, count = _activity_checked.get(str(path)) or ('', 0)
            if day != item['at'][:10]: count = _activity_trim(path)  # the first line of a day (or since Zook started): read the whole file once
            elif count + 1 > ACTIVITY_KEEP: count = _activity_trim(path, ACTIVITY_KEEP - ACTIVITY_ROOM)  # never more than ACTIVITY_KEEP lines
            else: count += 1
            _activity_checked[str(path)] = (item['at'][:10], count)
    except OSError: pass


# ---- One line per finished reply.
WORK_RESULTS = {'completed': 'ok', 'failed': 'failed', 'cancelled': 'stopped'}
WORK_FILE = re.compile(r'(?:寫入|建立|修改|產生|存成)檔案「([^」]{1,80})」')


def _audit_reason(text):
    """A failure sentence without a whole path (only the file's own name) or anything that looks like a key."""
    text = hide_command_secrets(' '.join(str(text or '').split()))
    text = re.sub(r'(?:~|\.{0,2})/(?:[^\s/「」（）()，。,]+/)+([^\s/「」（）()，。,]*)', lambda x: x.group(1) or '', text)
    text = re.sub(r'[A-Za-z0-9_\-+=]{24,}', '…', text)
    return text[:200]


def _audit_files(job):
    names = []
    for call in job.get('toolCalls') or []:
        if not isinstance(call, dict): continue
        try: line = describe_call(call)
        except Exception: continue
        for name in WORK_FILE.findall(line):
            if _file_word(name) and name not in names: names.append(name)
    return names


def _audit_what(store, job, redo):
    """What the reply did, in one plain sentence: who asked, how many tools it used, the files it wrote."""
    bot = store.find('bots', job.get('botId')) or {}
    origin = job.get('origin') or 'user'
    if job.get('taskRole') == 'verifier': head = '查核任務的結果'
    elif redo: head = '重新回答你的訊息'
    else: head = {'schedule': '執行排程', 'trigger': '依觸發條件執行', 'script': '回覆本機腳本傳來的訊息', 'bot': '回覆其他 Bot 的請求'}.get(origin, '在群組裡回覆' if job.get('groupId') else '回覆你的訊息')
    if job.get('groupId'): head = '%s %s' % (bot.get('name') or 'Bot', head)
    tools = len([c for c in job.get('toolCalls') or [] if isinstance(c, dict)])
    files = _audit_files(job)
    return head + ('，用了 %d 個工具' % tools if tools else '') + ('，寫了%s' % ''.join('「%s」' % f for f in files[:3]) + ('等 %d 個檔案' % len(files) if len(files) > 3 else '') if files else '')


def _audit_model(store, job):
    bot = store.find('bots', job.get('botId')) or {}
    ran = job.get('ran') if isinstance(job.get('ran'), list) and job.get('ran') else [bot.get('provider') or '', bot.get('model') or '']
    provider, model = str(ran[0] or ''), str((ran + [''])[1] or '')
    used = job.get('usage') if isinstance(job.get('usage'), dict) else {}
    if used.get('provider') == provider and isinstance(used.get('model'), str) and used['model'] not in ('', '預設模型'): model = used['model']  # what the CLI said it used
    if not provider or provider == AUTO: return provider, '自動選擇', ''
    try: name = provider_label(provider).split('（')[0]
    except Exception: name = provider
    return provider, name, model or '預設模型'


def audit_job(store, job, status, redo=False):
    """Lock held. The line for a reply that just ended. Zook's own helpers (a summary, a team plan) are not the user's work."""
    if not isinstance(job, dict) or job.get('audited') or job.get('internal') or not job.get('messageId') or not job.get('botId'): return
    result = WORK_RESULTS.get(status)
    if not result: return
    job['audited'] = True
    group = store.find('groups', job.get('groupId')) if job.get('groupId') else None
    bot = store.find('bots', job.get('botId')) or {}
    provider, provider_name, model = _audit_model(store, job)
    why = step = ''
    if result == 'failed':
        info = failure_info(dict(job, status='failed')) or {}
        why, step = _audit_reason(job.get('error')) or '這次回覆沒有完成。', info.get('next') or '打開對話再試一次。'
    elif result == 'stopped':
        why, step = '這次工作在做完之前被停止了。', '需要的話，打開%s再傳一次。' % ('群組' if group else '對話')
    log_activity(store, 'work', _audit_what(store, job, redo), by=(group or {}).get('name') or bot.get('name') or 'Bot',
                 botId=str(job.get('botId') or ''), groupId=str(job.get('groupId') or ''), chatId=str(job.get('chatId') or ''), messageId=str(job.get('messageId') or ''),
                 provider=provider, providerName=provider_name, model=model, result=result, why=why, next=step)


class AuditTrail:
    """Mixed into Store (chatfiles.py): every reply ends through finish_message, so each one is recorded there."""
    def finish_message(self, job, content, status):
        redo = bool(job.get('redoOf'))  # finish_message takes it off
        super().finish_message(job, content, status)
        try: audit_job(self, job, status, redo)
        except Exception: pass  # the record must never break a reply


# ---- Reading it: filtered, searched, a page at a time, the same change in a row as one line.
def _activity_since(span):
    if span == 'today':
        start = datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(datetime.timezone.utc).isoformat()
    days = {'7d': 7, '30d': 30, '90d': 90}.get(span)
    return _activity_cutoff(days) if days else ''


def _activity_names(store, kind, item_id):
    return str((store.find(kind, item_id) or {}).get('name') or '') if item_id else ''


def _activity_of(item, field, item_id, name):
    """Lines written before #304 name a Bot or group only in their words: 「名稱」 or （名稱）."""
    if item.get(field): return item[field] == item_id
    return bool(name) and (item.get('by') == name or '「%s」' % name in item.get('text', '') or '（%s）' % name in item.get('text', ''))


def _activity_shape(item):
    """Lines that read as one when they come in a row: the same words, or the same automatic change by Zook to several Bots (#247⑦)."""
    text = item.get('text') or ''
    return (item.get('kind'), item.get('by'), item.get('result'), re.sub(r'「[^」]*」|（[^）]*）', '「」', text) if item.get('by') == 'Zook' else text)


def _activity_seconds(at):
    try: return datetime.datetime.fromisoformat(str(at)).timestamp()
    except ValueError: return 0


def _activity_merge(items):
    out = []
    for item in items:
        last = out[-1] if out else None
        if (last and item.get('kind') != 'work' and item.get('result') != 'waiting' and _activity_shape(item) == _activity_shape(last)
                and abs(_activity_seconds(last['at']) - _activity_seconds(item['at'])) <= ACTIVITY_MERGE_SECONDS):
            last['count'] += 1; last['more'].append(item['text']); continue
        out.append(dict(item, count=1, more=[item['text']]))
    for item in out:
        if item['count'] == 1: item.pop('more')
    return out


def activity_list(store, kind='', result='', bot='', group='', range='', q='', offset=0, limit=None, merge=False):
    """Newest first: approvals a Bot waits for now, then the saved lines; each says how it ended (actlog.py). Lock held."""
    try:
        with _activity_lock: lines = activity_path(store).read_text(encoding='utf-8').splitlines()[-ACTIVITY_KEEP:]
    except OSError: lines = []
    result = result if result in ACTIVITY_RESULTS else ''
    bot_name, group_name = _activity_names(store, 'bots', bot), _activity_names(store, 'groups', group)
    since, oldest, words = _activity_since(range), _activity_cutoff(ACTIVITY_DAYS), str(q or '').strip().casefold()

    def wanted(item):
        if kind == 'admin' and item.get('kind') == 'work' or kind not in ('', 'admin') and item.get('kind') != kind: return False
        if result and item['result'] != result: return False
        if bot and not _activity_of(item, 'botId', bot, bot_name): return False
        if group and not _activity_of(item, 'groupId', group, group_name): return False
        if since and str(item.get('at') or '') < since: return False
        return not words or words in ' '.join(str(item.get(k) or '') for k in ('text', 'by', 'providerName', 'model', 'why', 'resultName')).casefold()
    out = [x for x in activity_waiting(store) if wanted(x)]
    for line in reversed(lines):
        try: item = json.loads(line)
        except ValueError: continue
        if not isinstance(item, dict) or str(item.get('at') or '') < oldest: continue
        item.update(activity_outcome(item))
        if wanted(item): out.append(item)
    if merge: out = _activity_merge(out)
    offset = max(0, int(offset or 0)); page = out[offset:offset + limit] if limit else out[offset:]
    return dict(items=page, total=len(out), offset=offset, more=offset + len(page) < len(out),
                kinds=[dict(id=k, name=v) for k, v in ACTIVITY_KINDS.items()], categories=[dict(id=k, name=v) for k, v in ACTIVITY_CATEGORIES.items()],
                results=[dict(id=k, name=v) for k, v in ACTIVITY_RESULTS.items()], ranges=[dict(id=k, name=v) for k, v in ACTIVITY_RANGES.items()],
                bots=[dict(id=b['id'], name=b.get('name') or '') for b in store.data.get('bots') or [] if isinstance(b, dict) and b.get('id')],
                groups=[dict(id=g['id'], name=g.get('name') or '') for g in store.data.get('groups') or [] if isinstance(g, dict) and g.get('id')])


def activity_route(handler, store):
    """GET /api/activity. Lock held."""
    query = parse_qs(urlsplit(handler.path).query)
    one = lambda key: str((query.get(key) or [''])[0])[:100]
    number = lambda key, default, top: max(0, min(top, int(one(key)))) if one(key).isdigit() else default
    kind = one('kind') if one('kind') in ACTIVITY_KINDS or one('kind') in ACTIVITY_CATEGORIES else ''
    return handler.respond(200, activity_list(store, kind, one('result'), one('bot'), one('group'), one('range') if one('range') in ACTIVITY_RANGES else '', one('q'),
                                              number('offset', 0, ACTIVITY_KEEP), number('limit', ACTIVITY_PAGE, 200) or ACTIVITY_PAGE, merge=True))
