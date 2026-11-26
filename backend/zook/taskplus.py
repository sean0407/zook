# 任務引擎, learning and helpers: how often each vendor's work passes its check, per kind of work, and what that means when the
# host picks a member; and a member handing part of its task to a helper (two layers at most). Loaded by backend/server.py into
# one shared namespace.
TASK_KINDS = dict(code='寫程式', analysis='分析', quick='簡短工作', image='圖片')
TASK_RATE_MIN = 3        # checks before a vendor's record counts
TASK_DEPTH = 2           # the host's tasks are layer 1, a member's helpers layer 2; nothing deeper
TASK_HELPERS = 3         # helpers one task may have


def task_learn_on(store): return (store.data.get('settings') or {}).get('taskLearn') is not False


def task_kind_of(spec, given=None):
    """What kind of work a task is: what the host said (code, analysis, quick or image), else guessed from its words."""
    if isinstance(given, str) and given.strip().lower() in TASK_KINDS: return given.strip().lower()
    try: kind = auto_task(spec)
    except Exception: kind = 'quick'
    return kind if kind in TASK_KINDS else 'quick'


def task_rate(store, vendor, kind):
    """(passed, checked) for one vendor's work of one kind. Anything damaged counts as nothing."""
    stats = store.data.get('taskStats')
    bucket = stats.get(vendor) if isinstance(stats, dict) else None
    entry = bucket.get(kind) if isinstance(bucket, dict) else None
    ok = isinstance(entry, list) and len(entry) == 2 and all(type(x) is int for x in entry) and 0 <= entry[0] <= entry[1]
    return (entry[0], entry[1]) if ok else (0, 0)


def task_rate_record(store, task, verdict):
    """Lock held. Count one check of the work's vendor, for this kind of work."""
    vendor = task_worker_kind(store, task)
    if not vendor or verdict not in ('pass', 'fail'): return
    kind = task.get('kind') if task.get('kind') in TASK_KINDS else 'quick'
    passed, checked = task_rate(store, vendor, kind)
    if not isinstance(store.data.get('taskStats'), dict): store.data['taskStats'] = {}
    stats = store.data['taskStats']
    if not isinstance(stats.get(vendor), dict): stats[vendor] = {}
    stats[vendor][kind] = [passed + (verdict == 'pass'), checked + 1]


def task_rate_text(store, vendor, kind):
    passed, checked = task_rate(store, vendor, kind)
    return '%s 在「%s」類工作的驗收通過 %d／%d' % (provider_label(vendor), TASK_KINDS.get(kind, kind), passed, checked) if checked else ''


def task_pick_by_record(store, group, run, bot, kind, label='主持人指定', changes='files'):
    """(the member to give the task to, why). The host's pick stands unless its vendor's record on this kind of work is poor
    (under half passed, at least three checks) and another member's vendor does clearly better (30 points or more)."""
    vendor = provider_kind(bot_model(store, bot)[0] or '') if task_lane(store, bot)[0] != AUTO else None
    if not vendor: return bot, label
    passed, checked = task_rate(store, vendor, kind)
    basis = label + ('；' + task_rate_text(store, vendor, kind) if checked else '')
    if checked < TASK_RATE_MIN or passed / checked >= 0.5: return bot, basis
    best = None
    for other in [store.find('bots', x) for x in group['botIds']]:
        if not other or other['id'] in (run['hostId'], bot['id']) or task_lane(store, other)[0] == AUTO or task_can_deliver(store, other, changes): continue
        theirs = provider_kind(bot_model(store, other)[0] or '')
        p2, c2 = task_rate(store, theirs, kind)
        if c2 >= TASK_RATE_MIN and p2 / c2 >= passed / checked + 0.3 and (best is None or p2 / c2 > best[1]): best = (other, p2 / c2, theirs)
    if not best: return bot, basis
    return best[0], '依過去的驗收紀錄改派：%s；%s' % (task_rate_text(store, vendor, kind), task_rate_text(store, best[2], kind))


def task_handoff_abort(run, parent_n, why='派助手的那一輪沒有完成，助手沒有開始。'):
    """Lock held. The helpers a turn asked for and never released: they never start, cannot be retried, and nothing waits for them."""
    gone = set()
    for t in run.get('tasks') or []:
        if t.get('parent') == parent_n and t.get('staged'):
            t.pop('staged', None); t.update(status='cancelled', aborted=True, note=why); gone.add(t['n'])
    for t in run.get('tasks') or []:
        if t.get('n') == parent_n: t['deps'] = [n for n in t.get('deps') or [] if n not in gone]
    return gone


def task_handoff_orphans(run):
    """Lock held. Staged helpers whose member's turn is no longer running (an internal error, a stop): dropped."""
    running = {t['n'] for t in run['tasks'] if t['status'] == 'running'}
    for parent in {t['parent'] for t in run['tasks'] if t.get('parent') and t.get('staged') and t['parent'] not in running}: task_handoff_abort(run, parent)


def task_handoff_end(task, run, job, published=True):
    """Lock held. The turn that handed part of a task to helpers has ended. Ended well: the helpers may start and the task waits for
    them. Failed or stopped: the helpers never start and the task is handled like any try that did not finish."""
    if job['status'] == 'completed' and published:
        released = [t for t in run['tasks'] if t.get('parent') == task['n'] and t.get('staged')]
        for t in released: t.pop('staged', None)
        run['bonusAttempts'] = run.get('bonusAttempts', 0) + len(released) + 1  # each helper's start, and the task going on afterwards (bounded: helpers per task and TASK_MAX)
        task['status'] = 'pending'; return
    task_handoff_abort(run, task['n'], '派助手的那一輪沒有完成%s，助手沒有開始。' % ('' if job['status'] != 'completed' else '（檔案沒有交回群組）'))
    if job['status'] == 'cancelled': task['status'] = 'cancelled'
    else: task_failed_attempt(task, '派了助手，但這一輪沒有完成：%s' % ((job.get('error') or '') if job['status'] != 'completed' else '檔案沒有交回群組')[:200], job)


def task_can_deliver(store, bot, changes):
    """Why a member cannot do a task that changes this much, or ''."""
    if task_lane(store, bot)[0] == AUTO: return '它用「自動選擇」，還不知道會用哪家模型'
    why = task_member_ok(store, bot) or task_quota_why(store, bot)
    if why: return why
    if changes != 'none' and permission_mode(store, bot) not in ('auto', 'bypass'): return '它的權限是「謹慎」，交不出檔案'
    return ''


def task_delegate_tool(app, store, job_id, group_id, run_id, task_id, mine, acted, schema, S, text):
    """A member hands part of its own task to a helper and ends its turn; it is sent back to its task with the helper's report."""
    def delegate(args):
        title, spec, done_when = text(args.get('title'), 'title', 1, 40), text(args.get('spec'), 'spec', 10, 8000), text(args.get('done_when'), 'done_when', 4, 1000)
        with store.lock:
            group, run, task, attempt = mine()
            if (task.get('depth') or 1) >= TASK_DEPTH: raise RuntimeError('最多兩層：你自己就是助手，不能再派助手。自己完成，或用 zook_task_done 回報做不到。')
            if len([t for t in run['tasks'] if t.get('parent') == task['n']]) >= TASK_HELPERS: raise RuntimeError('一項工作最多派 %d 位助手。' % TASK_HELPERS)
            if len(run['tasks']) >= task_max(run): raise RuntimeError('這個目標的工作已經到上限 %d 項。' % task_max(run))
            if any(t['title'] == title for t in run['tasks']): raise RuntimeError('已經有同名的工作，換一個標題。')
            name = ' '.join(str(args.get('assignee') or '').split()).lstrip('@').lower()
            bot = next((b for b in (store.find('bots', x) for x in group['botIds']) if b and b['name'].strip().lower() == name), None)
            if not bot or bot['id'] in (run['hostId'], task['assignee']): raise RuntimeError('助手要是群組裡的其他成員（不是主持人，也不是你自己）。')
            if group_is_checker(bot) and not task.get('check'): raise RuntimeError('%s 負責查核，不接製作的工作；派給其他成員。' % bot['name'])  # #245
            changes = str(args.get('changes') or 'files').strip().lower()
            if changes not in TASK_CHANGES: raise RuntimeError('changes 只能是 none、files 或 external。')
            why = task_can_deliver(store, bot, changes)
            if why: raise RuntimeError('%s 不能接這項工作：%s' % (bot['name'], why))
            rank = dict(none=0, files=1, external=2)
            if rank[changes] > rank.get(task.get('changes') or 'files', 1): raise RuntimeError('助手能做的不能比你這項工作多：你的工作是 %s。' % (task.get('changes') or 'files'))
            child = dict(id=ID(), staged=True, n=len(run['tasks']) + 1, title=title, spec=spec, doneWhen=done_when, assignee=bot['id'], suggested=bot['name'], deps=[], why='', basis='%s 派的助手' % task_member_name(store, task['assignee']),
                         status='ready', attempts=[], failures=0, question='', answer='', changes=changes, kind=task_kind_of(spec, args.get('kind')), depth=(task.get('depth') or 1) + 1, parent=task['n'],
                         confirmed=task_execution(store) == 'lowrisk' and changes == 'none' and not any(t['status'] == 'stuck' for t in run['tasks']), createdAt=NOW())
            run['tasks'].append(child); task['deps'] = list(task.get('deps') or []) + [child['n']]
            attempt.update(state='delegated', endedAt=NOW()); acted(True)
            run['log'].append(dict(at=NOW(), what='delegate', task=task['n'], helper=child['n']))
            task_board_update(store, group); store.save()
        app.task_poke(group_id)
        return dict(helper=child['n'], assignee=bot['name'], next='已派出。現在就結束這一輪；助手完成後，Zook 會帶著它的回報再派你接著做。')
    return [(schema('zook_task_delegate', 'Hand one part of your task to another group member (a helper), then end your turn. You are sent back to your task with the helper\'s report. Helpers cannot have helpers of their own.',
                    {'title': S('Short title'), 'assignee': S('Member name'), 'spec': S('Self-contained instructions for the helper'), 'done_when': S('A checkable condition'),
                     'changes': S('none, files or external; default files; never more than your own task'), 'kind': S('code, analysis, quick or image; optional')}, ['title', 'assignee', 'spec', 'done_when']), delegate, False)]
