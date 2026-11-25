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
    """Lock held. Mark a reply that was running when Zook stopped. `when` is when Zook stopped, as an ISO time; 'unknown' when the
    data comes from a Zook before this one (nothing then starts by itself)."""
    job['interrupted'] = when or 'unknown'


def finished_before_stop(store, job):
    """Lock held, at start. A reply whose answer reached its conversation file before Zook stopped, though its job record did not:
    it is finished, and is neither marked failed nor done again."""
    owner = store.find('groups', job['groupId']) if job.get('groupId') else store.find('bots', job.get('botId'))
    message = find_message(owner, job.get('messageId')) if owner else None
    if not message or message.get('status') != 'completed' or not message.get('content'): return False
    job.update(status='completed', content=message['content'], finishedAt=job.get('finishedAt') or NOW())
    return True


def process_started(pid):
    """(when the process started, its command line) as ps says, or ('', '') when there is no such process."""
    try: line = subprocess.run(['/bin/ps', '-o', 'lstart=,command=', '-p', str(int(pid))], capture_output=True, text=True, timeout=5, env=dict(os.environ, TZ='UTC0')).stdout.strip()  # the same text whatever the Mac's time zone
    except (OSError, ValueError, subprocess.SubprocessError): return '', ''
    return (line[:24].strip(), line[24:].strip()) if len(line) > 24 else ('', '')


def note_cli_pid(store, job_id, proc, binary):
    """Lock held. The CLI's process and when it started, so one left running by a crash is stopped before its reply is carried on."""
    if isinstance(getattr(getattr(proc, 'cli', None), 'proc', None) or proc, HostedProc): return  # its runner and placeholder end it (background.py)
    pid = getattr(proc, 'pid', None) or getattr(getattr(getattr(proc, 'cli', None), 'proc', None), 'pid', None)
    job = store.find('jobs', job_id)
    if job is None or not pid or (job.get('cliPid') or [0])[0] == int(pid): return
    started, command = process_started(pid)
    if started and binary and str(binary) in command: job['cliPid'] = [int(pid), str(binary), started]; store.save()  # on disk before a crash can come


def stop_left_behind(record):
    """At start: the CLI of a reply cut off by a crash may still be running, with what it started. Its whole process group is
    stopped, only when the process is still that same CLI (same start time and command line as when the reply began)."""
    pid, binary, seen = (list(record or []) + [0, '', ''])[:3]
    started, command = process_started(pid) if pid and binary and seen else ('', '')
    if not started or started != seen or str(binary) not in command: return  # gone, or the number now belongs to something else
    group = int(pid)  # the group it leads; a CLI under a runner is never recorded here (note_cli_pid)
    for sig, wait in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 2.0)):  # a group's number is not given out again while any member lives
        try: os.killpg(group, sig)
        except (ProcessLookupError, PermissionError): return
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try: os.killpg(group, 0)
            except (ProcessLookupError, PermissionError): return
            time.sleep(0.1)


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
    done = done_actions(old)  # what the user added while it answered goes with the new reply's own addedText (continue_job)
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
    wanted = body.get('messageId')
    if not isinstance(wanted, str) or not wanted: return handler.error(400, '請指定要接著做的回覆。')
    old = next((j for j in reversed(store.data['jobs']) if j.get('botId') == bot['id'] and j.get('messageId') == wanted and j.get('interrupted') and j.get('chatId') and not j.get('groupId') and not j.get('internal')), None)
    if not old: return handler.error(404, '找不到這則被中斷的回覆。')
    if any(j['botId'] == bot['id'] and j['status'] == 'running' for j in store.data['jobs']): return handler.error(409, '此機器人已有執行中的工作。')
    if handler.server.__dict__.get('resuming'): return handler.error(409, 'Zook 正在接續重啟前的工作，請過幾秒再按。')
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
    """The output feed of a reply, which also notes the CLI conversation it writes into as soon as that is known.
    A carried-on reply says under it whether it continued its CLI conversation or was sent Zook's saved one."""
    with store.lock:
        job = store.find('jobs', job_id) or {}
        message = find_message(store.find('bots', job.get('botId')), job.get('messageId')) if job.get('resumeOf') else None
        if message is not None: message['note'] = RESUME_MARK if resume else RESUME_MARK + '（' + RESUME_SAVED + '）'
    if not keep_session or kind not in RESUME_KINDS: return feed
    spot = lambda sid: note_cli_session(store, job_id, *where[:3], where[3], sid)
    if resume: spot(resume); return feed
    return session_sniffer(kind, feed, spot)


class Resuming:
    def resume_then_drain(self):
        """At start: first what the last stop cut short, then the messages that were waiting (they would otherwise come after it)."""
        try: bg_reattach(self); self.resume_interrupted()  # what went on under its runner first (background.py)
        finally: self.queue_drain_all()

    def resume_interrupted(self):
        """Shortly after Zook starts: carry on what the last stop cut short."""
        store = self.store; self.resuming = True  # 接著做 waits for this
        try:
            with store.lock: left = [j.pop('cliPid') for j in store.data['jobs'] if j.get('interrupted') and j.get('cliPid')]
            for record in left: stop_left_behind(record)  # before anything starts again; it may wait a few seconds
            try: inventory = inventory_for(store)
            except Exception: inventory = None
            with store.lock: self._resume_all(inventory)
        finally: self.resuming = False

    def _resume_all(self, inventory):
        store = self.store
        for old in [j for j in store.data['jobs'] if j.get('interrupted') and j.get('resumedBy') and not store.find('jobs', j['resumedBy'])]:
            old.pop('resumedBy'); old.pop('resumeSeen', None)  # its new reply never reached the main file: the claim is void
            bot = store.find('bots', old.get('botId'))
            message = find_message(bot, old.get('messageId')) if bot else None
            if message and message.get('status') == 'running': message['status'] = 'failed'
        for old in [j for j in store.data['jobs'] if j.get('interrupted') and not j.get('resumedBy') and not j.get('resumeSeen')]:
            old['resumeSeen'] = True
            if old.get('groupId') or not old.get('chatId') or old.get('internal'): continue
            bot = store.find('bots', old['botId'])
            place = self.resume_place(bot, old) if bot else None
            if not place: continue
            message = place[2]
            if task_acted_outward(old):  # it may have sent or changed something outside: doing it again could do it twice
                message.update(resumable=True, note='中斷前可能已經對外做了一部分（例如寄出或改了連接的服務），所以沒有自動接著做。確認後可以按「接著做」。'); continue
            if not resume_age_ok(old['interrupted']):
                message.update(resumable=True, note='Zook 關閉超過 %d 小時（或不知道關了多久），所以沒有自動接著做。' % RESUME_HOURS); continue
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
        if at is None or at != len(messages) - 1 or messages[at].get('status') != 'failed': return None  # the user has moved on, or it finished
        asked = at - 1
        while asked >= 0 and messages[asked].get('role') == 'user' and messages[asked].get('interjected'): asked -= 1  # added while it answered
        if asked < 0 or messages[asked].get('role') != 'user': return None
        return messages, messages[asked], messages[at], asked

    def continue_job(self, bot, old, inventory):
        """Lock held. Start the reply again where it was cut off, in the same message. Raises like send_to_bot."""
        place = self.resume_place(bot, old)
        if not place: raise ValueError('這則回覆後面已經有新的訊息，不能接著做。')
        if old.get('resumedBy'): raise ValueError('這則回覆已經接著做了。')
        messages, asked, reply, _ = place
        kept = [a for a in asked.get('attachments') or [] if upload_meta(self.store, a['id'])]
        ran, native = old.get('ran') or [], old.get('cliSession')
        use = (ran[0], ran[1]) if native and len(ran) >= 2 and native.get('provider') == ran[0] else None
        old['resumedBy'] = 'starting'  # claimed before the new reply is first saved, so a crash in between never starts it twice
        try:
            job = self.send_to_bot(bot, asked['content'], inventory, author=asked.get('author'), chat_id=old['chatId'], use=use, attachments=kept,
                                   effort=old.get('effort') or reply.get('effort') or 'standard', plan=bool(asked.get('plan') or old.get('plan')), long=bool(old.get('long')),
                                   origin=old.get('origin') or 'user', resume_of=old)
        except BaseException: old.pop('resumedBy', None); raise
        old['resumedBy'] = job['id']
        added = [m['content'] + date_check_note(m) for m in messages[place[3] + 1:-1] if m.get('interjected')][-10:]  # what the user added while it answered, kept for a later restart too
        if added: job['addedText'] = added
        return job

    def task_pickup(self, group):
        """Lock held. A 任務引擎 run cut off by a restart goes on from where it was: finished tasks stay finished, the one that was
        running is done again with a note, one that had already reported is only checked again. Too old: the user decides."""
        run = group['taskRun']
        if run.get('status') != 'stopped': return
        if not resume_age_ok(run['interrupted']):
            group['messages'].append(dict(id=ID(), role='system', content='Zook 關閉超過 %d 小時（或不知道關了多久），這個任務沒有自動接著做。要繼續的話，在任務看板上按「重試」。' % RESUME_HOURS, createdAt=NOW()))
            return
        if group.get('status') == 'running' or not any(t.get('before') for t in run.get('tasks') or []): return  # nothing was planned yet: nothing to carry on
        for t in run['tasks']:
            before = t.pop('before', None)
            if not before or t.get('aborted') or t.get('status') not in ('unknown', 'cancelled', 'stuck'): continue
            last = (t.get('attempts') or [{}])[-1]
            cut = self.store.find('jobs', last.get('jobId')) if last.get('jobId') else None
            if before == 'running' and cut and task_acted_outward(cut):
                t.update(status='stuck', note='這次嘗試可能已經對外做了一部分（例如寄出或改了連接的服務），自動接著做可能重複，停下來等你決定。'); continue
            if before == 'verifying' or (before == 'running' and last.get('state') == 'reported' and last.get('outcome') == 'succeeded'):
                t.update(status='verifying', verify=dict(state='waiting')); t.pop('note', None)
            elif before == 'running':
                t.update(status='pending' if t.get('deps') else 'ready', resumed=True); t.pop('note', None)
                if not t.get('resumeBonus'):  # the try that was cut off (or only reserved), once per task: restarts never lift the cap for good
                    run['bonusAttempts'] = run.get('bonusAttempts', 0) + 1; t['resumeBonus'] = True
            elif before == 'review': t['status'] = 'review'
            else: t['status'] = before; t.pop('note', None)
        for g in run.get('gates') or []:
            if g.pop('before', None) == 'pending' and g.get('status') == 'cancelled': g.update(status='pending', since=time.time())
        group['messages'].append(dict(id=ID(), role='system', content='Zook 重新啟動，任務從中斷的地方接著做：已完成的工作不重做，中斷的那一項會先確認做到哪。', createdAt=NOW()))
        task_board_update(self.store, group)
        self.task_resume(group)
