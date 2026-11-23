# Zook 重啟後接著做 (queue #34): a reply or a 任務引擎 run that Zook's restart cut short carries on by itself.
# Loaded by backend/server.py into one shared namespace; mixed into App.
#
# While a reply runs, the id of the CLI's own conversation is kept on the job as soon as the CLI prints it (Codex and Claude save
# their conversation as they go). After a restart that conversation is continued with a note that the Bot was cut off, so it checks
# what it already did instead of doing it again. A CLI that cannot continue mid-reply is sent Zook's saved conversation with the
# same note. Anything that needs the user's approval is asked again, because approvals that were open when Zook stopped are void.
# Cut off more than RESUME_HOURS ago: nothing starts by itself; the reply shows 「接著做」 and the task board its 重試 buttons.
RESUME_HOURS = 24
RESUME_KINDS = ('codex', 'claude')  # CLIs whose conversation id is known while the reply is still running
RESUME_MARK = '接續 Zook 重啟前中斷的回覆'
RESUME_SAVED = '這個模型接不回原本的對話，改用 Zook 保存的對話內容'
INTERRUPT_NOTE = ('\n\n（Zook 系統提示）Zook 剛才重新啟動，你上一次回覆在中途被中斷了。請先確認做到哪裡（例如檢查已經寫好或改過的檔案），'
                  '不要重複已經完成的動作，再從中斷的地方接著完成。之前等使用者核准的動作已經失效，需要的話會重新詢問。')


def interrupted_at(job, when):
    """Lock held. Mark a reply that was running when Zook stopped. `when` is when Zook stopped, as an ISO time."""
    job['interrupted'] = when or job.get('createdAt') or NOW()


def resume_age_ok(when, now=None):
    try: then = datetime.datetime.fromisoformat(str(when).replace('Z', '+00:00'))
    except ValueError: return False
    if then.tzinfo is None: then = then.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now - then <= datetime.timedelta(hours=RESUME_HOURS)  # a clock set back counts as recent


def done_actions(job, limit=15):
    """What the cut-off reply already did that changed something, in a few words each (never its arguments in full)."""
    out = []
    for c in job.get('toolCalls') or []:
        if c.get('category') in (None, 'read', 'external_read') or c.get('status') not in ('completed', 'approved', 'ok', 'done'): continue
        try: text = describe_call(c)
        except Exception: text = str(c.get('label') or c.get('name') or '')
        if text: out.append(str(text)[:160])
    return out[-limit:]


def interrupt_note(old):
    done = done_actions(old)
    return INTERRUPT_NOTE + ('\n中斷前已經完成、不要再做一次的動作：\n' + '\n'.join('- ' + x for x in done) if done else '')


def note_cli_session(store, job_id, provider, model, account, folder, session):
    """While a reply runs: the CLI conversation it is writing into, in the same form a chat keeps after a good reply."""
    if not session: return
    with store.lock:
        job = store.find('jobs', job_id)
        if not job or job.get('status') != 'running': return
        found = dict(provider=provider, account=account['id'] if account else '', model=model, folder=str(folder), session=str(session),
                     features=job.get('features', []), access=job.get('nativeAccess'), planned=bool(job.get('plan')))
        if job.get('cliSession') != found: job['cliSession'] = found; store.save()


def session_sniffer(kind, inner, found, limit=262144):
    """feed(bytes) that passes the CLI's output on to `inner` and calls found(id) once, when the conversation id first shows up."""
    state = dict(pending=bytearray(), seen=0, done=False)
    def feed(chunk):
        if not state['done'] and chunk:
            state['pending'] += chunk; state['seen'] += len(chunk)
            *lines, rest = bytes(state['pending']).split(b'\n')
            state['pending'] = bytearray(rest[-limit:])
            for line in lines:
                sid = cli_session(kind, line.decode('utf-8', 'replace')) if (b'session_id' in line or b'thread_id' in line) else ''
                if sid:
                    state['done'] = True
                    try: found(sid)
                    except Exception: pass
                    break
            if state['seen'] > limit: state['done'] = True  # it never said: this reply cannot be continued from the CLI's side
        if inner: inner(chunk)
    return feed


def resume_request(handler, store, inventory):
    """POST /api/chat/resume {botId, messageId}: 接著做, a reply that Zook's restart cut off. Lock held."""
    body = handler.body(); bot = store.find('bots', body.get('botId'))
    if not bot: return handler.error(404, '找不到機器人。')
    old = next((j for j in reversed(store.data['jobs']) if j.get('botId') == bot['id'] and j.get('messageId') == body.get('messageId') and j.get('interrupted') and not j.get('groupId')), None)
    if not old: return handler.error(404, '找不到這則被中斷的回覆。')
    if any(j['botId'] == bot['id'] and j['status'] == 'running' for j in store.data['jobs']): return handler.error(409, '此機器人已有執行中的工作。')
    return handler.respond(202, {'jobId': handler.server.continue_job(bot, old, inventory)['id']})


def resume_spot(app, bot, old):
    """send_to_bot's look at the cut-off reply: None when this is an ordinary message. Lock held."""
    if not old: return None
    place = app.resume_place(bot, old)
    if not place: raise ValueError('這則回覆後面已經有新的訊息，不能接著做。')
    return place


def resume_reply(place):
    """The cut-off reply's own message, running again."""
    msg = place[2]; msg.update(content='', status='running')
    for key in ('resumable', 'options', 'note', 'auto', 'autoWhy'): msg.pop(key, None)
    return msg


def resume_job(job, chat, old, use, note, content):
    """Lock held. The new reply continues the CLI conversation the cut-off one was writing into. Returns its short prompt."""
    job['resumeOf'] = old['id']
    if old.get('cliSession') and use: chat['native'] = dict(old['cliSession'])
    return note.strip() + '\n\n使用者原本的要求：' + content


def resume_feed(store, job_id, kind, keep_session, resume, feed, where):
    """The output feed of a reply, which also notes the CLI conversation it writes into as soon as that is known."""
    if not keep_session or kind not in RESUME_KINDS: return feed
    spot = lambda sid: note_cli_session(store, job_id, *where[:3], where[3], sid)
    if resume: spot(resume); return feed
    return session_sniffer(kind, feed, spot)


class Resuming:
    def resume_interrupted(self):
        """Shortly after Zook starts: carry on what the last stop cut short."""
        store = self.store
        try: inventory = inventory_for(store)
        except Exception: inventory = None
        with store.lock:
            for old in [j for j in store.data['jobs'] if j.get('interrupted') and not j.get('resumedBy') and not j.get('resumeSeen')]:
                old['resumeSeen'] = True
                if old.get('groupId') or not old.get('chatId') or old.get('internal'): continue
                bot = store.find('bots', old['botId'])
                if not bot or not self.resume_place(bot, old): continue
                message = self.resume_place(bot, old)[2]
                if not resume_age_ok(old['interrupted']): message['resumable'] = True; continue
                try: self.continue_job(bot, old, inventory)
                except Exception: message['resumable'] = True  # busy, removed model, …: the user can press 「接著做」
            for group in store.data['groups']:
                run = group.get('taskRun')
                if isinstance(run, dict) and run.get('interrupted') and not run.get('resumeSeen'):
                    run['resumeSeen'] = True
                    try: self.task_pickup(group)
                    except Exception: pass
            store.save()

    def resume_place(self, bot, old):
        """(messages, asked, reply) when the cut-off reply is still the last thing in its conversation, else None. Lock held."""
        try: messages = chat_messages(bot, old['chatId'])
        except ValueError: return None
        at = next((i for i, m in enumerate(messages) if m['id'] == old.get('messageId')), None)
        if at is None or at == 0 or at != len(messages) - 1 or messages[at - 1].get('role') != 'user': return None  # the user has moved on
        return messages, messages[at - 1], messages[at]

    def continue_job(self, bot, old, inventory):
        """Lock held. Start the reply again where it was cut off, in the same message. Raises like send_to_bot."""
        place = self.resume_place(bot, old)
        if not place: raise ValueError('這則回覆後面已經有新的訊息，不能接著做。')
        if old.get('resumedBy'): raise ValueError('這則回覆已經接著做了。')
        messages, asked, reply = place
        kept = [a for a in asked.get('attachments') or [] if upload_meta(self.store, a['id'])]
        ran, native = old.get('ran') or [], old.get('cliSession')
        use = (ran[0], ran[1]) if native and len(ran) >= 2 and native.get('provider') == ran[0] else None
        job = self.send_to_bot(bot, asked['content'], inventory, author=asked.get('author'), chat_id=old['chatId'], use=use, attachments=kept,
                               effort=old.get('effort') or reply.get('effort') or 'standard', plan=bool(asked.get('plan')), long=bool(old.get('long')),
                               origin=old.get('origin') or 'user', resume_of=old)
        old['resumedBy'] = job['id']
        return job

    def task_pickup(self, group):
        """Lock held. A 任務引擎 run cut off by a restart goes on from where it was: finished tasks stay finished, the one that was
        running is done again with a note, one that had already reported is only checked again. Too old: the user decides."""
        run = group['taskRun']
        if run.get('status') != 'stopped': return
        if not resume_age_ok(run['interrupted']):
            group['messages'].append(dict(id=ID(), role='system', content='Zook 關閉超過 %d 小時，這個任務沒有自動接著做。要繼續的話，在任務看板上按「重試」。' % RESUME_HOURS, createdAt=NOW()))
            return
        if group.get('status') == 'running' or not any(t.get('before') for t in run.get('tasks') or []): return  # nothing was planned yet: nothing to carry on
        for t in run['tasks']:
            before = t.pop('before', None)
            if not before or t.get('aborted') or t.get('status') not in ('unknown', 'cancelled', 'stuck'): continue
            last = (t.get('attempts') or [{}])[-1]
            if before == 'verifying' or (before == 'running' and last.get('state') == 'reported' and last.get('outcome') == 'succeeded'):
                t.update(status='verifying', verify=dict(state='waiting')); t.pop('note', None)
            elif before == 'running':
                t.update(status='pending' if t.get('deps') else 'ready', resumed=True); t.pop('note', None)
                run['bonusAttempts'] = run.get('bonusAttempts', 0) + 1  # the cut-off try does not use up the task's own tries
            elif before == 'review': t['status'] = 'review'
            else: t['status'] = before; t.pop('note', None)
        for g in run.get('gates') or []:
            if g.pop('before', None) == 'pending' and g.get('status') == 'cancelled': g.update(status='pending', since=time.time())
        group['messages'].append(dict(id=ID(), role='system', content='Zook 重新啟動，任務從中斷的地方接著做：已完成的工作不重做，中斷的那一項會先確認做到哪。', createdAt=NOW()))
        task_board_update(self.store, group)
        self.task_resume(group)
