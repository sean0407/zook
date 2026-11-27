# 換模型重答 (#143): the note under the new reply says who answered before and who answers now, with the model when it is known
# («原本：Codex gpt-5.5／這次：Claude claude-sonnet-4-5»). Loaded by backend/server.py into one shared namespace.
# #305: answering the same question with another model (換模型重答) keeps the answers before it; 重新回答 replaces them. The new reply carries them in 'versions' (oldest first,
# each a copy of that reply with 'who' wrote it) and its own 'who'; the page switches 第 1／2 版, the export lists every one.
# Only the newest is what the conversation goes on from. A reply without 'versions' (older Zook) is shown as before.
MAX_REPLY_VERSIONS = 10
_UNNAMED_MODELS = ('', '預設模型', 'cursor/auto')


def _named_model(model):
    model = str(model or '').strip()
    return '' if model in _UNNAMED_MODELS else model[:60]


def _who(provider, model=''):
    model = _named_model(model)
    return provider_label(provider).split('（')[0] + (' ' + model if model else '')


def redo_before(store, bot, replaces):
    """Lock held. Who wrote the reply that is being answered again: the model its CLI reported, else what it was asked to run."""
    old = next((m for m in replaces or [] if isinstance(m, dict) and m.get('role') == 'assistant'), None)
    job = next((j for j in reversed(store.data['jobs']) if old and j.get('messageId') == old.get('id')), None) if old else None
    if job and job.get('ran'):
        used = job.get('usage') if isinstance(job.get('usage'), dict) and job['usage'].get('provider') == job['ran'][0] else {}
        return _who(job['ran'][0], used.get('model') or job['ran'][1])
    return '' if bot.get('provider') == AUTO else _who(*bot_model(store, bot))


def redo_note(store, bot, replaces, provider, model):
    """The note under a reply answered with another model, and the [before, provider] kept on the job to add the model later."""
    before = redo_before(store, bot, replaces)
    now = _who(provider, model)
    return ('原本：%s／這次：%s' % (before, now)) if before else '這次用 %s 回答' % now, [before, provider]


def redo_versions(store, bot, replaces, content, msg, provider, model):
    """Lock held. The answers to the same question before this one, kept on the new reply (#305). Another question (編輯) has none."""
    asked = next((m for m in replaces or [] if isinstance(m, dict) and m.get('role') == 'user'), None)
    old = next((m for m in replaces or [] if isinstance(m, dict) and m.get('role') == 'assistant'), None)
    if not asked or not old or asked.get('content') != content: return
    kept = [v for v in old.get('versions') or [] if isinstance(v, dict)]
    if str(old.get('content') or '').strip():  # a reply that failed or stopped before saying anything is not an answer to keep
        kept.append(dict({k: v for k, v in old.items() if k != 'versions'}, who=redo_before(store, bot, replaces) or str(old.get('who') or '')))
    if kept: msg['versions'] = kept[-(MAX_REPLY_VERSIONS - 1):]; msg['who'] = _who(provider, model)  # with the new one, at most 10


def redo_model_seen(store, job, provider, usage):
    """Lock held. When the CLI says which model it ran and the user did not name one, the 這次 part gets it."""
    who = job.get('redoWho')
    model = _named_model((usage or {}).get('model'))
    owner = store.find('bots', job['botId']) if not job.get('groupId') else None
    msg = find_message(owner, job['messageId']) if owner else None
    if msg and msg.get('versions') and (model or provider != (job.get('ran') or [provider])[0]): msg['who'] = _who(provider, model or (job.get('ran') or ['', ''])[1])
    if not who or not model or provider != who[1]: return
    if not msg or msg.get('note') != job.get('redoNote'): return  # a backup answered instead: its own note stays
    now = _who(provider, model)
    msg['note'] = job['redoNote'] = ('原本：%s／這次：%s' % (who[0], now)) if who[0] else '這次用 %s 回答' % now
