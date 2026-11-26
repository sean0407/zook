# 群組「做完才查」(#245, 併 #145、#170、#226). Loaded by backend/server.py into one shared namespace, after groups.py.
#
# Who checks is, for now, told by the member's name or persona (group_is_checker): a temporary fallback until the group form lets
# the user choose the checker, and Zook picks a member of another vendor when nobody is chosen (queue #296).
#
# A member whose role is checking (查核員、驗收、審核…) is asked only after the members who make the work have handed it in, and
# only when the files they said they handed in are there: a file said to be handed in but missing goes back to that member once
# first; nothing handed in means no check. The check only reads, so it never saves a second copy of the work (#170). In 主持人分工
# the check is a step between the work and the host's merge, and runs again after the host sends work back; in a discussion with
# a host it comes after the members' independent round. In 任務引擎 a task reported with files that are not there is tried again
# before another vendor checks it.
CHECKER_NAME = re.compile(r'查核|驗收|審核|審查|校對|稽核|覆核|複核|把關|品管|(?<![A-Za-z])(?:QA|reviewer|checker)(?![A-Za-z])', re.I)
CHECKER_DUTY = re.compile(r'(?:負責|專門|主要|擔任|你是|我是|身為|作為)(?:做|進行|的)?[^，。,.；;\n]{0,6}?(?:查核|驗收|審核|審查|校對|稽核|覆核|複核|把關)')
CHECKER_NOT = re.compile(r'[不沒没非無无別]')  # 「不負責查核」「我不是負責查核的」: said not to be its job
MODERATOR_RULES['split_check'] = ['現在輪到你查核。照主持人分派給你的查核工作，實際打開要查的檔案（成員交的，或使用者給的）逐項核對，不要只看別人的說法。',
                                  '第一行只寫【判定】同意、【判定】有疑慮 或 【判定】有錯誤 其中之一，接著用最多 4 點說明依據；有檔案沒打開，就寫明哪個沒看，不能判定通過。',
                                  '要給客戶或外部的內容，核對有沒有內部註記、計算過程、內部折扣或報價規則、【待確認】。',
                                  '只讀：不要修改、重做或另存任何檔案，也不要對外動作。', _NO_MENTION]
MODERATOR_RULES['split_resave'] = ['你剛才說交了檔案，但 Zook 檢查到群組檔案裡沒有。只把那些檔案存好，不要改內容或做別的事。',
                                   '存好後用一兩句話回報存了哪些檔名；存不了就直接說存不了和原因，不要說已經存好。', _NO_MENTION]
MODERATOR_RULES['split_plan'] = MODERATOR_RULES['split_plan'][:-1] + ['負責查核或驗收的成員，Zook 會等其他成員交件後才請他查核；他那一行寫要查什麼。', _NO_MENTION]


def group_is_checker(bot):
    """Whether a member's role is checking others' work: its name says so, or its persona starts by saying that is its job."""
    name = str((bot or {}).get('name') or '')
    if any(not CHECKER_NOT.search(name[max(0, hit.start() - 2):hit.start()]) for hit in CHECKER_NAME.finditer(name)): return True  # 「非查核員」 is not one
    persona = str((bot or {}).get('persona') or (bot or {}).get('instructions') or '')[:80]
    return any(not CHECKER_NOT.search(re.sub('不只|不僅|不但', '', persona[max(0, hit.start() - 4):hit.end()])) for hit in CHECKER_DUTY.finditer(persona))


def split_checkers(store, ids):
    """(members who make the work, members who check it) among these. A checker is always a checker: with nobody making
    anything it checks what is there, still only reading."""
    checkers = [x for x in ids if group_is_checker(store.find('bots', x))]
    return [x for x in ids if x not in checkers], checkers


def check_step(checkers, producers, fixes=None):
    """The 查核員's turn: after the work, only reading, waiting for a member busy elsewhere like the work does."""
    return dict(role='split_check', bots=list(checkers), blind=False, waitBusy=True, noSave=True, gate=list(producers), fixes=dict(fixes or {}))


def split_work_steps(store, ids, fixes=None, host=None):
    """分工's work: the members who make it at the same time, then those who check it (#245). With no member making anything,
    the check waits for the host's own share."""
    fixes = fixes or {}
    producers, checkers = split_checkers(store, ids)
    work = dict(role='split_work', bots=producers, blind=True, waitBusy=True, **({'fixes': {k: v for k, v in fixes.items() if k in producers}} if fixes else {}))
    return ([work] if producers else []) + ([check_step(checkers, producers or ([host] if host else []), {k: v for k, v in fixes.items() if k in checkers})] if checkers else [])


def _same_file(name, pool, owner=''):
    """A report's own file name: exactly that shared file, or the name Zook gave it when another member's file had that name
    (報表（專員）.xlsx, with this member's name)."""
    wants = set()
    for given in {name, _short_name(name)}:  # the name as reported, and as Zook saves it (unsafe characters dropped, shortened)
        want = _claim_key(given); stem, dot, ext = want.rpartition('.'); wants.add(want)
        if owner and dot: wants.update({_claim_key('%s（%s）.%s' % (stem, owner[:20], ext)), _claim_key(_short_name('%s（%s）.%s' % (stem, owner[:20], ext)))})
    return any(_claim_key(have) in wants for have in pool)


def checked_present(store, group_id, names, exact=(), owner=''):
    """The names among these that are not among the group's shared files, the only place a checker reads them: the very name, or
    Zook's rename of it for this member. Names picked from a reply must look like file names; a report's own list (exact) is looked
    for name by name."""
    pool = [e.name for e in _plain_files(group_files_dir(store, group_id))]
    gone = []
    for raw in names or []:
        name = re.sub(r'[（(][^（）()]{0,30}[）)]\s*$', '', ' '.join(str(raw or '').split())).strip(' 「」『』`\'"')
        base = name.rsplit('/', 1)[-1]
        if (raw not in exact and not re.search(r'\.[A-Za-z0-9]{1,10}$', base)) or not base or base in gone: continue  # a report's own list is looked for name by name
        if _same_file(base, pool, owner): continue  # the very name (or Zook's rename of it): an older file whose name merely ends the same is not it
        gone.append(base)
    return gone[:10]


SAVE_SAID = ('已存', '存到', '存好', '存成', '存進', '另存', '已上傳', '上傳到', '交了', '交出', '已交', '交件', '交付', '附上')  # a reply that says it saved or handed over something


def _nothing_saved(replies, pool):
    """Whether a member said it saved files while none of its replies in this ask brought one into the group's files, and none
    names a file that is already there (saved earlier, unchanged). Only replies whose files Zook brought back count; one that could
    not save, such as in 謹慎, is not asked to."""
    looked = [m for m in replies if 'savedFiles' in m]
    if not looked or any(m.get('savedFiles') for m in looked) or not any(w in (m.get('content') or '') for m in looked for w in SAVE_SAID): return False
    return not any(_same_file(n, pool) for m in looked for n in CLAIM_WORD.findall(m.get('content') or ''))


NOTHING_SAVED = '（說存了的檔案）'


def _ask_start(group):
    return next((i for i in range(len(group['messages']) - 1, -1, -1) if group['messages'][i].get('role') == 'user' and not group['messages'][i].get('interjected')), 0)


def _names(store, ids):
    return '、'.join(b['name'] for b in (store.find('bots', x) for x in ids) if b)


class CheckOrder:
    def _check_gate(self, group_id, run_id, step, steps):
        """Before a 查核員's turn (steps[0] is it): returns steps to run it, steps[1:] when there is nothing to check, a 補存 turn
        for the members whose files are missing followed by this check again, or False when the run ended."""
        store = self.store
        if not step.get('gate'): return steps  # nobody makes anything for it: it checks what is already there
        with store.lock:  # the files are looked at with the lock held, so what is decided is what was seen
            group = store.find('groups', group_id)
            if not group or group.get('runId') != run_id: return False
            start = _ask_start(group); last = {}
            since = max(start, step['since']) if isinstance(step.get('since'), int) else start  # after a send-back: only what came after it
            for m in group['messages'][since:]:  # each member's newest reply: a redo or 補存 that failed means the work was not handed in again
                if m.get('role') == 'assistant' and m.get('botId') in step.get('gate', []) and not m.get('checkOf') and m.get('status') != 'running': last[m['botId']] = m
            latest = {b: m for b, m in last.items() if m.get('status') == 'completed' and m.get('content')}
            unfinished = [b for b in step.get('gate', []) if b not in latest and store.find('bots', b) and b in group['botIds']]  # no reply, or one that did not finish: not handed in
            earlier = step.get('missing') if isinstance(step.get('missing'), dict) else {}  # what was missing before 補存 is looked for again, whatever the new reply says
            said = {b: [n for n in dict.fromkeys(list(m.get('missingFiles') or []) + list(earlier.get(b) or [])) if n != NOTHING_SAVED] for b, m in latest.items()}  # looked for again by the full name, among the files there now
            checkers = _names(store, step['bots'])
            with _group_files_lock:  # nothing is being saved into the group's files while they are looked at
                gone = {b: checked_present(store, group_id, names) for b, names in said.items() if names}
                pool = [e.name for e in _plain_files(group_files_dir(store, group_id))]
            given = {a.get(k) for x in group['messages'][start:] if x.get('role') == 'user' for a in x.get('attachments') or [] for k in ('name', 'origName')}
            asked = '\n'.join(x.get('content') or '' for x in group['messages'][start:] if x.get('role') == 'user')
            for b, m in latest.items():  # a file the reply says it handed over, by its full name, that is not among the shared files (the user's own files aside)
                text = m.get('content') or ''
                if any(w in text for w in SAVE_SAID):
                    named = [n for n in CLAIM_WORD.findall(text) if n not in given and n not in asked and not _same_file(n, pool)]
                    if named: gone[b] = list(dict.fromkeys((gone.get(b) or []) + named))[:10]
            for b, m in latest.items():
                if m.get('skippedFiles'): gone[b] = list(dict.fromkeys((gone.get(b) or []) + list(m['skippedFiles'])))  # too big to keep: an older file of that name is not this work
                replies = [x for x in group['messages'][start:] if x.get('role') == 'assistant' and x.get('botId') == b and not x.get('checkOf')]
                if step.get('fresh') and 'savedFiles' in m and not m.get('savedFiles') and any(x.get('savedFiles') for x in replies): gone.setdefault(b, []).append(NOTHING_SAVED)  # redone work with files: the new version must be saved, not the old one checked
                elif not gone.get(b) and _nothing_saved(replies, pool): gone[b] = [NOTHING_SAVED]
            gone = {b: names for b, names in gone.items() if names}
            note = lambda text: group['messages'].append(dict(id=ID(), role='system', content=text, createdAt=NOW()))
            if gone and not step.get('resaved'):  # 補存 first, also while another member's part is still missing
                fixes = {b: ('你說存了檔案，但這次沒有任何檔案存進群組檔案。' if names == [NOTHING_SAVED] else '你說交了 %s，但群組檔案裡找不到，可能沒有存成功（或太大存不進去）。' % '、'.join(names)) + '把這些檔案存到群組檔案。' for b, names in gone.items()}
                who = _names(store, list(gone))
                note('%s 說交了 %s，但群組檔案裡找不到；先退回給 %s 補存，補好再請 %s 查核。' % (who, '、'.join(n for v in gone.values() for n in v), who, checkers))
                store.save()
                return [dict(role='split_resave', bots=list(gone), blind=False, fixes=fixes), dict(step, resaved=True, missing=gone)] + steps[1:]
            if not latest or unfinished:  # the check waits for everyone's part: nothing is checked half-handed-in
                note('%s 還沒交出成果，%s 這次不用查核。' % (_names(store, unfinished or step.get('gate', [])) or '成員', checkers)); store.save(); return steps[1:]
            if gone:
                note('%s 補存後還是找不到 %s，%s 這次不查核；請 %s 重新存檔後再請查核。' % (_names(store, list(gone)), '、'.join(n for v in gone.values() for n in v), checkers, _names(store, list(gone))))
                store.save(); return steps[1:]
        return steps

    def _free_check(self, group_id, run_id, gate):
        """A discussion with a host: the 查核員 the kickoff named, once the members' independent round is over. Returns
        (turns to add, the gate still to pass, the step those turns run with); False when the run ended."""
        if not gate.get('bots'): return [], None, None  # no 查核員 was named for this work
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
        redo = [x for x in producers if x in fixes]
        checked = checkers if redo else [x for x in checkers if x in fixes]  # redone work is checked, also when the first check did not run
        step = dict(role='split_redo', bots=redo, blind=False, waitBusy=True, fixes={k: fixes[k] for k in redo}) if redo else None  # a busy member redoes it once free
        again = check_step(checked, redo or producers, {k: v for k, v in fixes.items() if k in checkers}) if checked and (redo or any(x in fixes for x in checkers)) else None
        if again and redo: again.update(fresh=True, since=len(group['messages']))
        return step, again


def _check_tasks(run, deps):
    """(checks not started that can wait for new work, checks already under way or done that cannot) — a check the new work itself
    waits for is neither."""
    checks = [t for t in run['tasks'] if t.get('check') and t['n'] not in deps and t['status'] not in ('cancelled', 'failed')]
    waiting = [t for t in checks if not t['attempts'] and t['status'] in ('pending', 'ready', 'waiting')]
    return waiting, [t for t in checks if t not in waiting]


def task_check_room(run, deps):
    """Lock held. How many follow-up checks new work would need: one when a check is under way or done and none waits for it."""
    waiting, begun = _check_tasks(run, deps)
    return 1 if begun and not waiting else 0


def task_check_new_work(run, task):
    """Lock held. Work added after the host planned its checks: a check that has not started waits for it too; when every check
    has already started (or finished), a follow-up check of it is added, by the same member and only reading."""
    waiting, begun = _check_tasks(run, task.get('deps') or [])
    for t in waiting: t['deps'] = list(t.get('deps') or []) + [task['n']]; t['status'] = 'pending'
    if waiting or not begun: return
    model = begun[-1]
    run['tasks'].append(dict(model, id=ID(), n=len(run['tasks']) + 1, title=('複查：' + model['title'])[:40], deps=[task['n']], status='pending', attempts=[], failures=0,
                             question='', answer='', staged=True, createdAt=NOW(), confirmed=task.get('confirmed', True), why='Zook 加的：查核開始後才新增了工作 %d' % task['n']))
    for key in ('verify', 'note', 'feedback', 'redo', 'missingFiles', 'decisions', 'reviewSince', 'resumed', 'acceptedCut', 'gate'): run['tasks'][-1].pop(key, None)
    run['log'].append(dict(at=NOW(), what='create', task=run['tasks'][-1]['n']))


def task_files_missing(store, group, owner, attempt, msg):
    """Lock held. The files a task's report lists, or its reply says it saved, that are not there as this member's: saved in this
    reply, or last saved by this member (another member's file of the same name is not its work)."""
    listed = list(attempt.get('files') or [])
    with _group_files_lock:
        gone = checked_present(store, group['id'], listed + list(msg.get('missingFiles') or []), exact=listed, owner=owner)
        mine = set(msg.get('savedFiles') or []) | {n for n, info in (group.get('fileInfo') or {}).items() if (info or {}).get('by') == owner}
        pool = [e.name for e in _plain_files(group_files_dir(store, group['id']))]
    for raw in listed:
        base = re.sub(r'[（(][^（）()]{0,30}[）)]\s*$', '', ' '.join(str(raw or '').split())).strip(' 「」『』`\'"').rsplit('/', 1)[-1]
        if base and base not in gone and _same_file(base, pool, owner) and not _same_file(base, [n for n in pool if n in mine], owner): gone.append(base)
    return list(dict.fromkeys(gone + list(msg.get('skippedFiles') or [])))[:10]
