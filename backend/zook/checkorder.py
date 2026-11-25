# 群組「做完才查」(#245, 併 #145、#170、#226). Loaded by backend/server.py into one shared namespace, after groups.py.
#
# A member whose role is checking (查核員、驗收、審核…) is asked only after the members who make the work have handed it in, and
# only when the files they said they handed in are there: a file said to be handed in but missing goes back to that member once
# first; nothing handed in means no check. The check only reads, so it never saves a second copy of the work (#170). In 主持人分工
# the check is a step between the work and the host's merge, and runs again after the host sends work back; in a discussion with
# a host it comes after the members' independent round. In 任務引擎 a task reported with files that are not there is tried again
# before another vendor checks it.
CHECKER_NAME = re.compile(r'查核|驗收|審核|審查|校對|稽核|覆核|複核|把關|品管|(?<![A-Za-z])(?:QA|reviewer|checker)(?![A-Za-z])', re.I)
CHECKER_DUTY = re.compile(r'(?:負責|專門|主要)(?:做|進行)?(?:查核|驗收|審核|審查|校對|稽核|覆核|複核|把關)')
MODERATOR_RULES['split_check'] = ['其他成員已經交出他們的部分，現在輪到你查核。照主持人分派給你的查核工作，實際打開他們交的檔案逐項核對，不要只看他們的說法。',
                                  '第一行只寫【判定】同意、【判定】有疑慮 或 【判定】有錯誤 其中之一，接著用最多 4 點說明依據；有檔案沒打開，就寫明哪個沒看，不能判定通過。',
                                  '要給客戶或外部的內容，核對有沒有內部註記、計算過程、內部折扣或報價規則、【待確認】。',
                                  '只讀：不要修改、重做或另存任何檔案，也不要對外動作。', _NO_MENTION]
MODERATOR_RULES['split_resave'] = ['你剛才說交了檔案，但 Zook 檢查到群組檔案裡沒有。只把那些檔案存好，不要改內容或做別的事。',
                                   '存好後用一兩句話回報存了哪些檔名；存不了就直接說存不了和原因，不要說已經存好。', _NO_MENTION]
MODERATOR_RULES['split_plan'] = MODERATOR_RULES['split_plan'][:-1] + ['負責查核或驗收的成員，Zook 會等其他成員交件後才請他查核；他那一行寫要查什麼。', _NO_MENTION]


def group_is_checker(bot):
    """Whether a member's role is checking others' work: its name says so, or its persona starts by saying that is its job."""
    if CHECKER_NAME.search(str((bot or {}).get('name') or '')): return True
    return bool(CHECKER_DUTY.search(str((bot or {}).get('persona') or (bot or {}).get('instructions') or '')[:80]))


def split_checkers(store, ids):
    """(members who make the work, members who check it) among these. Checkers wait only when someone else makes the work."""
    checkers = [x for x in ids if group_is_checker(store.find('bots', x))]
    producers = [x for x in ids if x not in checkers]
    return (list(ids), []) if not producers or not checkers else (producers, checkers)


def check_step(checkers, producers, fixes=None):
    """The 查核員's turn: after the work, only reading, waiting for a member busy elsewhere like the work does."""
    return dict(role='split_check', bots=list(checkers), blind=False, waitBusy=True, noSave=True, gate=list(producers), fixes=dict(fixes or {}))


def split_work_steps(store, ids, fixes=None):
    """分工's work: the members who make it at the same time, then those who check it (#245)."""
    fixes = fixes or {}
    producers, checkers = split_checkers(store, ids)
    work = dict(role='split_work', bots=producers, blind=True, waitBusy=True, **({'fixes': {k: v for k, v in fixes.items() if k in producers}} if fixes else {}))
    return [work] + ([check_step(checkers, producers, {k: v for k, v in fixes.items() if k in checkers})] if checkers else [])


def _same_file(name, pool):
    """The exact name, or it with the mark Zook adds to a second version (報表（專員）.xlsx, 報表 (2).xlsx)."""
    want = _claim_key(name)
    return any(_claim_key(have) == want or re.sub(r'\s*[（(][^（）()]{0,40}[）)](?=\.[^.]+$)', '', _claim_key(have)) == want for have in pool)


def checked_present(store, group_id, names, folders=(), exact=()):
    """Lock not needed. The names among these that are not there: not among the group's files (what a checker reads), not at the
    full path given, and not in a folder the work was sent to. Names in exact (a report's own list of files) must match a shared
    file exactly; others (words picked from a reply) may be the end of a longer name. A name that is not a file name is never counted."""
    pool = [e.name for e in _plain_files(group_files_dir(store, group_id))]
    gone = []
    for raw in names or []:
        name = re.sub(r'[（(][^（）()]{0,30}[）)]\s*$', '', ' '.join(str(raw or '').split())).strip(' 「」『』`\'"')
        base = name.rsplit('/', 1)[-1]
        if not re.search(r'\.[A-Za-z0-9]{1,10}$', base) or base in gone: continue
        if name.startswith(('/', '~')) and os.path.lexists(os.path.expanduser(name)): continue
        if (_same_file(base, pool) if raw in exact else _claim_present(base, pool)) or any(os.path.lexists(os.path.join(f, base)) for f in folders): continue
        gone.append(base)
    return gone[:10]


def _ask_start(group):
    return next((i for i in range(len(group['messages']) - 1, -1, -1) if group['messages'][i].get('role') == 'user' and not group['messages'][i].get('interjected')), 0)


def _names(store, ids):
    return '、'.join(b['name'] for b in (store.find('bots', x) for x in ids) if b)


class CheckOrder:
    def _check_gate(self, group_id, run_id, step, steps):
        """Before a 查核員's turn (steps[0] is it): returns steps to run it, steps[1:] when there is nothing to check, a 補存 turn
        for the members whose files are missing followed by this check again, or False when the run ended."""
        store = self.store
        with store.lock:
            group = store.find('groups', group_id)
            if not group or group.get('runId') != run_id: return False
            start = _ask_start(group); last = {}
            for m in group['messages'][start:]:  # each member's newest reply: a redo or 補存 that failed means the work was not handed in again
                if m.get('role') == 'assistant' and m.get('botId') in step.get('gate', []) and not m.get('checkOf') and m.get('status') != 'running': last[m['botId']] = m
            latest = {b: m for b, m in last.items() if m.get('status') == 'completed' and m.get('content')}
            earlier = step.get('missing') if isinstance(step.get('missing'), dict) else {}  # what was missing before 補存 is looked for again, whatever the new reply says
            said = {b: list(dict.fromkeys(list(m.get('missingFiles') or []) + list(earlier.get(b) or []))) for b, m in latest.items()}
            asked = '\n'.join(m.get('content') or '' for m in group['messages'][start:] if m.get('role') == 'user')
            checkers = _names(store, step['bots'])
        folders = named_folders(asked)
        gone = {b: checked_present(store, group_id, names, folders) for b, names in said.items() if names}
        gone = {b: names for b, names in gone.items() if names}
        with store.lock:
            group = store.find('groups', group_id)
            if not group or group.get('runId') != run_id: return False
            note = lambda text: group['messages'].append(dict(id=ID(), role='system', content=text, createdAt=NOW()))
            if not latest:
                note('%s 還沒交出成果，%s 這次不用查核。' % (_names(store, step.get('gate', [])) or '成員', checkers)); store.save(); return steps[1:]
            if gone and not step.get('resaved'):
                fixes = {b: '你說交了 %s，但群組檔案裡找不到，可能沒有存成功。把這些檔案存到群組檔案。' % '、'.join(names) for b, names in gone.items()}
                who = _names(store, list(gone))
                note('%s 說交了 %s，但群組檔案裡找不到；先退回給 %s 補存，補好再請 %s 查核。' % (who, '、'.join(n for v in gone.values() for n in v), who, checkers))
                store.save()
                return [dict(role='split_resave', bots=list(gone), blind=False, fixes=fixes), dict(step, resaved=True, missing=gone)] + steps[1:]
            if gone and len(gone) == len(latest):
                note('%s 補存後還是找不到 %s，%s 這次不查核；請 %s 重新存檔後再請查核。' % (_names(store, list(gone)), '、'.join(n for v in gone.values() for n in v), checkers, _names(store, list(gone))))
                store.save(); return steps[1:]
            if gone:
                note('%s 的 %s 還是找不到，%s 先查核其他已交的部分。' % (_names(store, list(gone)), '、'.join(n for v in gone.values() for n in v), checkers)); store.save()
        return steps

    def _free_check(self, group_id, run_id, gate):
        """A discussion with a host: the 查核員 the kickoff named, once the members' independent round is over. Returns
        (turns to add, the gate still to pass, the step those turns run with); False when the run ended."""
        step = check_step(gate['bots'], gate['gate']); step.update(resaved=gate.get('resaved', False), missing=gate.get('missing') or {})
        after = self._check_gate(group_id, run_id, step, [step])
        if after is False: return False
        if not after: return [], None, None
        now = {k: v for k, v in after[0].items() if k != 'waitBusy'}  # a member busy elsewhere is skipped with a line, as in any discussion
        later = dict(gate, resaved=True, missing=after[1].get('missing')) if now['role'] == 'split_resave' else None
        return [(x, False, now['role']) for x in now['bots']], later, now

    def _recheck(self, group_id, run_id, closer, fixes):
        """Lock held. After the host sends work back in 分工: (the redo step, the check that follows it). A member that checks is
        asked again after the work it checked is redone (the new version is checked, not the old one)."""
        group = self.store.find('groups', group_id)
        bots = [b for b in (self.store.find('bots', x) for x in group['botIds']) if b and b['id'] != closer]
        producers, checkers = split_checkers(self.store, [b['id'] for b in bots])
        if not checkers: return dict(role='split_redo', bots=[b['id'] for b in bots if b['id'] in fixes], blind=False, fixes=fixes), None
        start = _ask_start(group)
        checked = [x for x in checkers if x in fixes or any(m.get('botId') == x and m.get('role') == 'assistant' and m.get('content') for m in group['messages'][start:])]
        redo = [x for x in producers if x in fixes]
        step = dict(role='split_redo', bots=redo, blind=False, fixes={k: fixes[k] for k in redo}) if redo else None
        again = check_step(checked, redo or producers, {k: v for k, v in fixes.items() if k in checkers}) if checked and (redo or any(x in fixes for x in checkers)) else None
        return step, again


def task_files_missing(store, group_id, run, task, attempt, msg):
    """Outside the lock, with copies of what is read. The files a task's report lists, or its reply says it saved, that are not there."""
    listed = list(attempt.get('files') or [])
    folders = named_folders('\n'.join([task.get('spec') or '', run.get('goal') or '']))
    return checked_present(store, group_id, listed + list(msg.get('missingFiles') or []), folders, exact=listed)
