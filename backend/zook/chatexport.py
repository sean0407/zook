# 「↑ 匯出對話」: one conversation as a Markdown file.
# Loaded by backend/server.py into one shared namespace.
#
# The file has one top title (the conversation). Each message starts with a bold line: who said it, when, and for a reply the
# model and whether it failed or was stopped. A reply's own headings move two levels down, so they never sit level with the title.
# Attached files, and the files a reply saved (#302), are named but not put in the file.
EXPORT_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
EXPORT_FENCE = re.compile(r'^\s{0,3}(`{3,}|~{3,})')
EXPORT_FENCE_END = re.compile(r'^\s{0,3}(`{3,}|~{3,})\s*$')
EXPORT_QUOTE = re.compile(r'^((?: {0,3}>\s?)*)(.*)$')
EXPORT_HEADING = re.compile(r'^( {0,3})(#{1,6})(?=\s|$)')
EXPORT_SETEXT = re.compile(r'^ {0,3}(=+|-+)\s*$')


def export_time(stamp):
    """2026-11-23 14:02 in this Mac's time, or '' when there is no usable time."""
    try: when = datetime.datetime.fromisoformat(str(stamp or '').replace('Z', '+00:00'))
    except ValueError: return ''
    return (when.astimezone() if when.tzinfo else when).strftime('%Y-%m-%d %H:%M')


def demote_headings(text):
    """Every Markdown heading two levels down (at most ######), also inside quotes and underlined (=== / ---) ones. Code blocks
    stay as they are, and one left open is closed, so it cannot swallow the messages after it."""
    out, fence = [], None
    for line in str(text or '').split('\n'):
        if fence:
            end = EXPORT_FENCE_END.match(line)
            if end and end.group(1)[0] == fence[0] and len(end.group(1)) >= len(fence): fence = None
            out.append(line); continue
        mark = EXPORT_FENCE.match(line)
        if mark: fence = mark.group(1); out.append(line); continue
        quote, rest = EXPORT_QUOTE.match(line).groups()
        under = EXPORT_SETEXT.match(rest)
        if under and out and not quote and out[-1].strip() and not EXPORT_HEADING.match(out[-1]) and not EXPORT_FENCE.match(out[-1]) and not re.match(r'^\s*([-*+]|\d+[.)])\s', out[-1]):
            out[-1] = ('### ' if under.group(1)[0] == '=' else '#### ') + out[-1].strip(); continue
        out.append(quote + EXPORT_HEADING.sub(lambda h: h.group(1) + '#' * min(6, len(h.group(2)) + 2), rest))
    if fence: out.append(fence)
    return '\n'.join(out)


def export_model(data, job):
    """「Claude claude-sonnet-4-5」: the model that answered, from the reply's job ('' when not known)."""
    if not job: return ''
    usage = job.get('usage') if isinstance(job.get('usage'), dict) else {}
    provider, model = (usage.get('provider'), usage.get('model')) if usage.get('provider') else ((job.get('ran') or ['', ''])[:2] if isinstance(job.get('ran'), list) else ('', ''))
    spec = P.spec(data, provider) if provider else None
    name = (spec['name'] if spec else str(provider or '')).split('（')[0]
    return name + '（預設模型）' if model == '預設模型' else ' '.join(x for x in (name, str(model or '')) if x)


def export_message(data, jobs, m, speaker, tag='', verdict=''):
    """One message: the bold line, then what it said."""
    head = ['**%s**%s' % (speaker, tag)]
    if export_time(m.get('createdAt')): head.append(export_time(m.get('createdAt')))
    job = jobs.get(m.get('id'))
    if m.get('role') == 'assistant':
        if export_model(data, job): head.append(export_model(data, job))
        status = m.get('status')
        if status == 'failed': head.append('⚠️ 回覆失敗')
        elif status == 'cancelled': head.append('⏹ 已停止')
        elif status == 'running': head.append('回覆中，還沒完成')
    lines = [' · '.join(head)]
    if m.get('note'): lines.append('*%s*' % ' '.join(str(m['note']).split()))
    body = str(m.get('content') or '').strip()
    if m.get('role') == 'assistant':
        body = demote_headings(body)
        why = (job or {}).get('error') or m.get('error')
        if not body and m.get('status') == 'failed': body = '（此回覆失敗%s）' % ('：' + ' '.join(str(why).split())[:300] if why else '')
        elif not body and m.get('status') == 'cancelled': body = '（停止時還沒有內容）'
    if body: lines.append(body)
    if verdict: lines.append(verdict)
    names = [str(a.get('name') or '') for a in m.get('attachments') or [] if isinstance(a, dict) and a.get('name')]
    if names: lines.append('📎 附件：%s（檔案沒有帶入這份匯出）' % '、'.join(names))
    made = export_saved(job) if m.get('role') == 'assistant' else []
    if made: lines.append('📄 這則回覆存的檔案：%s（檔案沒有帶入這份匯出）' % '、'.join(made))
    return '\n\n'.join(lines)


def export_saved(job):
    """The names of the files a reply saved (#302), from what its tools wrote; only the names, never where on this Mac."""
    paths = [(c.get('arguments') or {}).get('path') for c in (job or {}).get('toolCalls') or [] if isinstance(c, dict) and c.get('name') in ('native_write', 'zook_workspace_write')]
    names = [str(p).rstrip('/').rsplit('/', 1)[-1] for p in paths + list((job or {}).get('wrote') or []) if isinstance(p, str) and p.strip()]
    return list(dict.fromkeys(n for n in names if n))[:20]


def export_file(title, facts, blocks):
    """The whole file, and the empty case."""
    head = ['# ' + title, '\n'.join('- %s：%s' % pair for pair in facts if pair[1])]
    if not blocks: head.append('（這段對話還沒有內容）')
    return '\n\n'.join(head + ['---\n\n' + b for b in blocks]) + '\n'


def export_name(*parts, now=None):
    base = '-'.join(EXPORT_UNSAFE.sub('_', ' '.join(str(p).split()))[:60] for p in parts if p)
    return '%s-%s.md' % (base, export_time(now or NOW())[:10])


def export_span(messages):
    times = sorted(export_time(m.get('createdAt')) for m in messages if export_time(m.get('createdAt')))  # a note added while a reply ran sits before it
    return '%s ～ %s' % (times[0], times[-1]) if len(times) > 1 and times[0] != times[-1] else (times[0] if times else '')


def export_chat(data, bot, chat_id, now=None):
    """One of a Bot's conversations as {name, markdown, empty}. Lock held."""
    messages = [m for m in chat_messages(bot, chat_id) if isinstance(m, dict)]
    chat = next((c for c in bot.get('chats') or [] if c.get('id') == (chat_id or bot.get('chatId'))), {})
    title = chat.get('title') or ('排程' if chat.get('kind') == 'schedule' else '本機腳本' if chat.get('kind') == 'script' else '新對話')
    jobs = {j.get('messageId'): j for j in data.get('jobs') or [] if j.get('botId') == bot.get('id') and not j.get('groupId')}
    shown = [m for m in messages if m.get('role') in ('user', 'assistant') and (m.get('content') or m.get('attachments') or m.get('role') == 'assistant')]
    blocks = [export_message(data, jobs, m, (m.get('author') or '我') if m.get('role') == 'user' else bot.get('name') or 'Bot') for m in shown]
    facts = [('Bot', bot.get('name')), ('對話', title), ('期間', export_span(shown)), ('匯出時間', export_time(now or NOW()))]
    return dict(name=export_name(bot.get('name') or 'Bot', title, now=now), markdown=export_file('%s · %s' % (bot.get('name') or 'Bot', title), facts, blocks), empty=not blocks)


def export_verdict(group, m, job):
    """A task check's verdict, which the checker gives with a tool and may not repeat in its reply (only the latest check of a task keeps one)."""
    if not m.get('taskCheck') or not m.get('taskId') or not job: return ''
    task = next((t for t in (group.get('taskRun') or {}).get('tasks') or [] if t.get('id') == m['taskId']), {})
    check = task.get('verify') or {}
    if check.get('jobId') != job.get('id'): return ''
    if check.get('verdict') not in ('pass', 'fail'): return ''
    return '驗收判定：%s%s' % ('通過' if check['verdict'] == 'pass' else '不通過', '。' + ' '.join(str(check.get('reasons') or '').split()) if check.get('reasons') else '')


def export_group(data, group, now=None):
    """A group's whole discussion as {name, markdown, empty}. Lock held."""
    messages = [m for m in group.get('messages') or [] if isinstance(m, dict)]
    everyone = {b.get('id'): b.get('name') for b in (data.get('bots') or []) + [b for b in data.get('deletedBots') or [] if isinstance(b, dict)]}
    jobs = {j.get('messageId'): j for j in data.get('jobs') or [] if j.get('groupId') == group.get('id')}
    blocks = []
    for m in messages:
        if m.get('role') == 'system':
            if m.get('content'): blocks.append('\n'.join(['> *Zook%s*' % (' · ' + export_time(m.get('createdAt')) if export_time(m.get('createdAt')) else '')] + ['> ' + line for line in str(m['content']).strip().split('\n')]))
        elif m.get('role') == 'user' and (m.get('content') or m.get('attachments')): blocks.append(export_message(data, jobs, m, m.get('author') or '我'))
        elif m.get('role') == 'assistant':
            blocks.append(export_message(data, jobs, m, everyone.get(m.get('botId')) or 'Bot', '（驗收）' if m.get('checkOf') or m.get('taskCheck') else '', export_verdict(group, m, jobs.get(m.get('id')))))
    members = '、'.join(everyone.get(x) or 'Bot' for x in group.get('botIds') or [])
    facts = [('群組成員', members), ('期間', export_span(messages)), ('匯出時間', export_time(now or NOW()))]
    return dict(name=export_name(group.get('name') or '群組', '群組對話', now=now), markdown=export_file(group.get('name') or '群組', facts, blocks), empty=not blocks)
