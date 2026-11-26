# 換模型重答 (#143): the note under the new reply says who answered before and who answers now, with the model when it is known
# («原本：Codex gpt-5.5／這次：Claude claude-sonnet-4-5»). Loaded by backend/server.py into one shared namespace.
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


def redo_model_seen(store, job, provider, usage):
    """Lock held. When the CLI says which model it ran and the user did not name one, the 這次 part gets it."""
    who = job.get('redoWho')
    model = _named_model((usage or {}).get('model'))
    if not who or not model or provider != who[1]: return
    owner = store.find('bots', job['botId'])
    msg = find_message(owner, job['messageId']) if owner else None
    if not msg or msg.get('note') != job.get('redoNote'): return  # a backup answered instead: its own note stays
    now = _who(provider, model)
    msg['note'] = job['redoNote'] = ('原本：%s／這次：%s' % (who[0], now)) if who[0] else '這次用 %s 回答' % now
