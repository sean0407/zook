# 成員卡住 (#307, 使用者 2026-11-26): a group reply that shows no sign of work for MEMBER_STALL is stopped and its backup model
# does that part again. Loaded by backend/server.py into one shared namespace.
#
# - A sign of work is anything its CLI prints (output, a tool it uses, a file it writes: they all come as output) or a Zook tool
#   it uses; time spent waiting for the user's approval does not count (app.py's wait loop). However long it runs, a reply that
#   keeps doing something is never stopped for it.
# - Stopping is the usual stop of that one reply's own CLI (terminate_tree / kill_group in app.py), nothing else.
# - The backup is the next model in the reply's own order (provider_chain / auto_backups / backups_with_room: accounts with less
#   than 20% left go last, the same CLI's other accounts are tried). The group is told in one plain sentence who stalled and
#   which model takes over.
# - A reply taken up after a restart (its CLI went on under its runner while Zook was closed, background.py) is never handed to a
#   backup: Zook did not watch what it did meanwhile, and its backups were not set up again. It is stopped and the user decides.
# - Under a runner, the stop goes through it (terminate_tree / kill_group end a HostedProc's group by way of its runner), the
#   runner's own silence limit comes a minute after Zook's (runner_quiet), and a backup is only said to take over once its runner
#   reported its CLI started (bg_ready, app.py).
# - A reply that may already have reached outside is never done again by itself (#60's careful rule, task_outward_kind): any
#   command counts, also one it started and never finished. Then, and when there is no backup, the group is told and the user
#   (or the host) decides.
try: MEMBER_STALL = max(1.0, float(os.environ.get('ZOOK_MEMBER_STALL') or 15 * 60))  # seconds without any sign of work before a group reply counts as stalled
except ValueError: MEMBER_STALL = 15 * 60.0
STALL_READABLE = ('claude', 'codex', 'grok', 'cursor', 'antigravity')  # CLIs whose steps progress.py reads as they happen


def reply_quiet(kind, job):
    """How long a reply may show no sign of work before it is stopped."""
    if job.get('long'): return LONG_JOB_TIMEOUT
    if job.get('groupId'): return MEMBER_STALL  # every CLI alike: the user's 15 minutes
    return agy_quiet(kind, JOB_TIMEOUT)


def runner_quiet(kind, job):
    """The runner's own stop for a silent CLI (background.py): a group reply's comes a minute after Zook's, so Zook's stop, which
    can hand the part to a backup, is the one that happens."""
    quiet = reply_quiet(kind, job)
    return quiet + 60 if job.get('groupId') and not job.get('long') else quiet


def stall_minutes(limit=None):
    return max(1, round((MEMBER_STALL if limit is None else limit) / 60))


def stall_mark(store, job, kind, native, limit):
    """Lock held. This try of a group reply stalled: remembered for the group's note, and whether it may have done something that
    must not be done twice. Returns that (it is the reply's mayHaveActed)."""
    rec = PROGRESS.get(job['id'])
    if job.get('stallTakenUp'):  # taken up after a restart: what it did while Zook was closed is not known
        job['stallNow'] = dict(minutes=stall_minutes(limit), acted=True, why='restart')
        return True
    if task_acted_outward(job): acted = True
    elif rec is not None and (rec['command'] > 0 or any(v[0] == 'command' for v in rec['asked'].values())): acted = True  # a command, also one still running
    else: acted = bool(native) and (kind not in STALL_READABLE or rec is None)  # its built-in tools' steps cannot be read: careful
    job['stallNow'] = dict(minutes=stall_minutes(limit), acted=bool(acted))
    return bool(acted)


def _stall_note(store, job, text):
    group = store.find('groups', job.get('groupId') or '')
    if group is None: return
    bot = store.find('bots', job.get('botId') or '') or {}
    group['messages'].append(dict(id=ID(), role='system', content=text % ('「%s」' % (bot.get('name') or '這位成員')), createdAt=NOW()))


def stall_switch(store, job, provider, account):
    """Lock held. The backup model's CLI has just started on a part whose try stalled: say so in the group. Stopped or Zook closing
    before that: nothing is said (stall_finish says nothing for a part that was stopped)."""
    if job.get('status') != 'running' or not job.get('stallSwitch'): return  # stopped meanwhile: stall_finish says nothing
    stall = job.pop('stallSwitch')
    _stall_note(store, job, '%%s 已經 %d 分鐘沒有任何動作，已停下這一份，改用 %s 重做。' % (stall['minutes'], auto_choice_name(provider, account or '')))


def stall_finish(store, job):
    """Lock held. The reply is over: a stalled part that was not handed to a backup is said in the group, with why."""
    now, waiting = job.pop('stallNow', None), job.pop('stallSwitch', None); job.pop('stallTakenUp', None)
    stall = now or waiting
    if not stall or job.get('status') != 'failed': return
    if stall.get('why') == 'restart':
        _stall_note(store, job, '%%s 已經 %d 分鐘沒有任何動作，已停下這一份。這一份是 Zook 重新開啟後接續的，Zook 不知道關閉期間它做了什麼，所以沒有自動換模型重做，請你決定要不要重做。' % stall['minutes'])
    elif stall.get('acted'):
        _stall_note(store, job, '%%s 已經 %d 分鐘沒有任何動作，已停下這一份。它這次用過指令或可能已經對外做了一部分，換模型重做可能重複，所以沒有自動重做，請你決定要不要重做。' % stall['minutes'])
    elif waiting:  # handed on, but no backup got to start (each was unavailable or could not start)
        _stall_note(store, job, '%%s 已經 %d 分鐘沒有任何動作，已停下這一份。備用模型都沒能接手，這一份沒有重做，請主持人或你接手。' % stall['minutes'])
    else:
        _stall_note(store, job, '%%s 已經 %d 分鐘沒有任何動作，已停下這一份。沒有可用的備用模型，這一份沒有重做，請主持人或你接手。' % stall['minutes'])


def quiet_why(kind, job, limit):
    """(why it was stopped, whether that is a stalled group reply) for a reply silent for its whole limit."""
    if job.get('groupId') and not job.get('long'): return '已經 %d 分鐘沒有任何動作。' % stall_minutes(limit), True
    return quiet_reason(kind, limit), False
