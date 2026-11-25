# Phone notifications (queue #243). The phone is told only four things: a reply finished, a reply failed, an action waits for
# approval, a question waits for an answer. Everything else (a schedule started, Bots held in, backups, usage) stays on the Mac
# and in the activity record. Each of the four has a switch in 設定 (settings.phoneNotify), all on by default.
# What reaches the phone names the Bot or group and says what happened in fixed words: no reply text, error, command, key or path.
PHONE_EVENTS = ('done', 'failed', 'approval', 'question')
PHONE_TEXT = dict(bot=dict(done='回覆完成', failed='回覆失敗，打開看原因', approval='有動作等你核准', question='有問題等你回答'),
                  group=dict(done='群組討論結束', failed='群組討論沒有完成，打開看原因', approval='群組裡有動作等你核准', question='群組裡有問題等你回答'))


def phone_events_on(store, settings=None):
    saved = (store.data['settings'] if settings is None else settings).get('phoneNotify')
    saved = saved if isinstance(saved, dict) else {}
    return {e: saved.get(e) is not False for e in PHONE_EVENTS}


def phone_setting(value, settings):
    """The settings change for phoneNotify: some of the four switches, each true or false; the rest keep what they were."""
    if not isinstance(value, dict) or not value or any(k not in PHONE_EVENTS or not isinstance(v, bool) for k, v in value.items()): raise ValueError('手機通知設定無效。')
    return dict(phone_events_on(None, settings), **value)


def phone_notify(app, event, kind, target_id, message_id=''):
    """Lock held. Queue one phone notification. Whether it is shown is decided when the phone asks, so a switch turned off
    also holds back what was already waiting."""
    if event not in PHONE_EVENTS: return
    kind = 'group' if kind == 'group' else 'bot'
    app.notice_seq += 1
    app.notices.append(dict(seq=app.notice_seq, title=str(app.target_name(kind, target_id))[:80], body=PHONE_TEXT[kind][event], kind=kind,
                            targetId=target_id, messageId=message_id or '', createdAt=NOW(), phone=event))
    del app.notices[:-MAX_NOTICES]


def phone_notify_job(app, event, job):
    """Lock held. The same, for a reply: a group's reply speaks for its group."""
    if job.get('groupId'): phone_notify(app, event, 'group', job['groupId'], job.get('messageId'))
    else: phone_notify(app, event, 'bot', job['botId'], job.get('messageId'))


def phone_job_ended(app, job):
    """Lock held. A Bot's own reply is over: finished or failed is told; a stopped one, a group turn (the group tells it once,
    when the discussion ends) and Zook's own helpers are not."""
    if not job or job.get('groupId') or not job.get('messageId') or job.get('internal'): return
    if job.get('status') in ('completed', 'failed'): phone_notify(app, 'done' if job['status'] == 'completed' else 'failed', 'bot', job['botId'], job.get('messageId'))


def notices_for(app, after, device):
    """What /api/notifications gives: a paired phone gets the four kinds whose switch is on; the Mac window gets the rest."""
    with app.store.lock:
        items = [n for n in app.notices if n['seq'] > after]
        if device:
            on = phone_events_on(app.store)
            items = [{k: v for k, v in n.items() if k != 'phone'} for n in items if on.get(n.get('phone'))]
        else: items = [n for n in items if not n.get('phone')]
        return dict(seq=app.notice_seq, items=items)
