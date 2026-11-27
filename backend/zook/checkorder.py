# 群組「做完才查」(#245, 併 #145、#170、#226). Loaded by backend/server.py into one shared namespace, after groups.py.
#
# Who checks is the group's 驗收方式 (checkMode, #296): 自動 asks one member of another vendor, 同家複查 also lets a member of the
# same vendor check, 指定 names the checker, 不驗收 has none. A group from before the form had it (no checkMode, or 'name') keeps
# telling the checker by its name or persona (named_checker), as #245 did.
#
# A member whose role is checking (查核員、驗收、審核…) is asked only after the members who make the work have handed it in, and
# only when the files they said they handed in are there: a file said to be handed in but missing goes back to that member once
# first; nothing handed in means no check. The check only reads, so it never saves a second copy of the work (#170). In 主持人分工
# the check is a step between the work and the host's merge, and runs again after the host sends work back; in a discussion with
# a host it comes after the members' independent round. In 任務引擎 a task reported with files that are not there is tried again
# before another vendor checks it.
CHECKER_NAME = re.compile(r'查核|驗收|審核|審查|校對|稽核|覆核|複核|把關|品管|品檢|品保|品質檢查|檢查員|檢查專員|(?<![A-Za-z])(?:QA|reviewer|checker)(?![A-Za-z])', re.I)
CHECKER_DUTY = re.compile(r'(?:負責|專門|主要|擔任|你是|我是|身為|作為)(?:做|進行|的)?[^，。,.；;\n]{0,6}?(?:查核|驗收|審核|審查|校對|稽核|覆核|複核|把關|檢查)')
FILE_KINDS = CLAIM_KINDS + ('ai', 'psd', 'eps', 'svg', 'gif', 'webp', 'heic', 'tif', 'tiff', 'bmp', 'key', 'numbers', 'pages', 'rtf', 'odt', 'ods', 'odp', 'xml',
                            'yaml', 'yml', 'tsv', 'log', 'epub', 'indd', 'sketch', 'fig', 'mp4', 'mov', 'm4a', 'mp3', 'wav', 'py', 'js', 'sql', 'ics', 'vcf', 'xlsm')
FILE_WORD = re.compile(r'[^\s/\\「」『』【】\[\]，、。：；！？()（）*`\'"<>|]{1,120}\.(?=[A-Za-z0-9]{0,7}[A-Za-z])[A-Za-z0-9]{1,8}(?![A-Za-z0-9.])', re.I)  # a file name of any kind in a reply (a half-width colon may be part of it)
NOT_FILES = ('com', 'net', 'org', 'io', 'tw', 'edu', 'gov', 'co', 'app', 'dev', 'me', 'info', 'cn', 'jp', 'hk', 'us', 'uk')  # web addresses, not files
file_words = lambda text: [w for w in FILE_WORD.findall(str(text or '')) if w.rsplit('.', 1)[-1].lower() not in NOT_FILES and '://' not in w]


def _whole(full, part):
    """Whether part is full, or the end of full after a space or a mark (「Q3 報價單.xlsx」 read as 「報價單.xlsx」), never after a letter
    or character of a longer word (「新版報價單.xlsx」 is another file)."""
    full, part = _claim_key(full), _claim_key(part)
    return full == part or (full.endswith(part) and not full[len(full) - len(part) - 1].isalnum())
CHECKER_NAME_WRITES = re.compile(r'撰寫|寫手|起草|整理|製作|設計|開發|企劃|規劃')  # 「驗收報告撰寫」 makes a document about checking; 「文件審核員」 checks
CHECKER_NOT = re.compile(r'[不沒没非無无別]')  # 「不負責查核」「我不是負責查核的」: said not to be its job
CHECKER_WRITES = re.compile(r'撰寫|寫|整理|製作|起草|報告|文件|紀錄|記錄|表單|清單')  # 「主要撰寫驗收報告」: it makes a document about checking
MODERATOR_RULES['split_check'] = ['現在輪到你查核。照主持人分派給你的查核工作（沒有分派時，查核其他成員這次交出的成果），實際打開要查的檔案（成員交的，或使用者給的）逐項核對，不要只看別人的說法。',
                                  '第一行只寫【判定】同意、【判定】有疑慮、【判定】有錯誤 或 【判定】無法查核 其中之一，接著用最多 4 點說明依據；有檔案沒打開，就寫明哪個沒看，不能判定通過。原檔和文字版都讀不到時寫【判定】無法查核，不要因為讀不到就判有疑慮或有錯誤。',
                                  '要給客戶或外部的內容，核對有沒有內部註記、計算過程、內部折扣或報價規則、【待確認】。',
                                  '只讀：不要修改、重做或另存任何檔案，也不要對外動作。', _NO_MENTION]
MODERATOR_RULES['split_resave'] = ['你剛才說交了檔案，但 Zook 檢查到群組檔案裡沒有。只把那些檔案存好，不要改內容或做別的事。',
                                   '存好後用一兩句話回報存了哪些檔名；存不了就直接說存不了和原因，不要說已經存好。', _NO_MENTION]
MODERATOR_RULES['split_plan'] = MODERATOR_RULES['split_plan'][:-1] + ['負責查核或驗收的成員，Zook 會等其他成員交件後才請他查核；他那一行寫要查什麼。', _NO_MENTION]


CHECK_MODES = ('auto', 'none', 'same', 'pick')  # the group form's 驗收方式 (#296); 'name' (or none) is a group from before it


def bot_vendor(store, bot):
    """Which vendor a member's replies come from; '' when 自動選擇 picks it per reply (not known ahead)."""
    provider = (bot or {}).get('provider') or (store.data.get('settings') or {}).get('provider') or ''
    return '' if provider == AUTO else provider_kind(provider)


def group_checkers(store, group, engine=False):
    """The members who check (#296), by the group's 驗收方式. 自動 and 同家複查 pick one member that is not the host, only when
    another member (the host too) is left to make the work. 自動 picks the one whose vendor differs from the most others, 同家複查
    the one of the same vendor as the most others (the later one on a tie, both); nobody when no member fits. In 任務引擎
    (engine) every task is already checked by another vendor, so 自動 and 同家複查 pick nobody there; a checker the user named, or a
    group from before 驗收方式 (by name, as #245 did), still counts."""
    present = [x for x in (group or {}).get('botIds') or [] if store.find('bots', x)]
    mode = (group or {}).get('checkMode')
    if mode not in CHECK_MODES: return [x for x in present if named_checker(store.find('bots', x))]  # a group from before 驗收方式
    if mode == 'none': return []
    host = group_host(store, group); seats = [x for x in present if x != host]
    if mode == 'pick' and group.get('checkerId') in seats: return [group['checkerId']]  # gone from the group, or now its host: picked as 自動
    if engine or not seats or len(present) < 2: return []
    family = {x: bot_vendor(store, store.find('bots', x)) for x in present}
    score = lambda c: sum(1 for x in present if x != c and family[x] and family[c] and (family[x] == family[c]) == (mode == 'same'))
    best = max(reversed(seats), key=score)  # the first best in this order: the later member on a tie
    return [best] if score(best) else []  # a vendor not known (自動選擇) is never counted as another one, or as the same


def group_is_checker(store, group, bot, engine=False):
    return bool(bot) and bot['id'] in group_checkers(store, group, engine)


GROUP_STANDING_MAX = 4000  # 長期指示 (#294): the group's own standing instructions


def group_standing(group):
    """The group's 長期指示 for a member's prompt, or ''."""
    text = str((group or {}).get('instructions') or '').strip()[:GROUP_STANDING_MAX]
    return '群組的長期指示（使用者設定，每次回覆都要遵守；和使用者這次的訊息衝突時，以這次的訊息為準）：\n' + text if text else ''


CHECKER_TAG = '（查核員：等其他成員交件後只讀查核，不接製作的工作）'


def named_checker(bot):
    """Whether a member's role is checking others' work: its name says so, or the first sentence of its persona says that is its job now (not a past one)."""
    name = str((bot or {}).get('name') or '')
    if not CHECKER_NAME_WRITES.search(name) and any(not CHECKER_NOT.search(re.sub('不只|不僅|不但', '', name[:hit.start()])) for hit in CHECKER_NAME.finditer(name)): return True  # 「非查核員」「不負責查核員」 are not
    persona = re.split(r'[。.！!？?\n]', str((bot or {}).get('persona') or (bot or {}).get('instructions') or '').strip())[0][:80]  # its first sentence says what it is now
    clause = lambda hit: re.split(r'[，,；;、]', persona[:hit.start()])[-1]  # the words before it in the same clause
    return any(not re.search(r'曾|以前|過去|原本|之前|前任', clause(hit)) and not CHECKER_NOT.search(re.sub('不只|不僅|不但', '', persona[max(0, hit.start() - 4):hit.end()])) and not CHECKER_WRITES.search(hit.group(0) + re.split(r'[，。,.；;、\n]', persona[hit.end():hit.end() + 4])[0])
               for hit in CHECKER_DUTY.finditer(persona))


def split_checkers(store, group, ids):
    """(members who make the work, members who check it) among these. A checker is always a checker: with nobody making
    anything it checks what is there, still only reading."""
    checking = group_checkers(store, group); checkers = [x for x in ids if x in checking]
    return [x for x in ids if x not in checkers], checkers


def check_step(checkers, producers, fixes=None):
    """The 查核員's turn: after the work, only reading, waiting for a member busy elsewhere like the work does."""
    return dict(role='split_check', bots=list(checkers), blind=False, waitBusy=True, noSave=True, gate=list(producers), fixes=dict(fixes or {}))


def split_work_steps(store, group, ids, fixes=None, host=None):
    """分工's work: the members who make it at the same time, then those who check it (#245). With no member making anything,
    the check waits for the host's own share."""
    fixes = fixes or {}
    producers, checkers = split_checkers(store, group, ids)
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
        name = re.sub(r'(\.[A-Za-z0-9]{1,10})\s*[（(][^（）()]{0,30}[）)]$', r'\1', ' '.join(str(raw or '').split())).strip(' 「」『』`\'"')  # 「報價單.xlsx（群組檔案）」; 「報價單（新版）.xlsx」 stays as it is
        base = name.rsplit('/', 1)[-1]
        if (raw not in exact and not re.search(r'\.[A-Za-z0-9]{1,10}$', base)) or not base or base in gone: continue  # a report's own list is looked for name by name
        if _same_file(base, pool, owner): continue  # the very name (or Zook's rename of it): an older file whose name merely ends the same is not it
        gone.append(base)
    return gone[:10]


def _in_prose(word, names, joins=None):
    """Whether a word picked from prose (Chinese runs words together: 「已存好報價單.xlsx」) is one of these files: the full name, or the
    name right after a word that joins it to the sentence (存好、交了、：…, or the joins given). 「新版報價單.xlsx」 is not 「報價單.xlsx」."""
    word = _claim_key(word)
    for n in names:
        key = _claim_key(n)
        if not n or not word.endswith(key): continue
        lead = word[:len(word) - len(key)]
        if not lead or lead.endswith(PROSE_JOIN + tuple(joins or ())): return True
    return False


INPUT_JOIN = ('照', '據', '据', '考', '看', '讀', '读', '用', '依', '從', '从', '由', '附', '給', '给')  # 「依照需求.pdf」「參考規格.pdf」: a file it read
PROSE_JOIN = ('存', '好', '了', '到', '成', '進', '的', '是', '為', '为', '：', ':', '傳', '交', '出', '付', '上', '把', '將', '将', '即', '和', '與', '与', '及', '在')


SAVE_WORDS = ('已存', '存到', '存好', '存成', '存進', '另存', '已上傳', '上傳到')  # it says it saved a file
SAVE_SAID = SAVE_WORDS + ('交了', '交出', '已交', '交件', '交付', '附上')  # it says it saved or handed over something (a file only when it names one)


def _nothing_saved(replies, pool):
    """Whether a member said it saved files while none of its replies in this ask brought one into the group's files, and none
    names a file that is already there (saved earlier, unchanged). Only replies whose files Zook brought back count; one that could
    not save, such as in 謹慎, is not asked to."""
    looked = [m for m in replies if 'savedFiles' in m]
    if not looked or any(n in pool for m in looked for n in m.get('savedFiles') or []): return False
    if not any(any(w in (m.get('content') or '') for w in SAVE_WORDS) or (any(w in (m.get('content') or '') for w in SAVE_SAID) and FILE_WORD.search(m.get('content') or '')) for m in looked): return False  # 「已交付三個建議」 hands over text, not a file
    return not any(_in_prose(n, pool) for m in looked for n in file_words(m.get('content')))


NOTHING_SAVED = '（說存了的檔案）'


def _ask_start(group):
    return next((i for i in range(len(group['messages']) - 1, -1, -1) if group['messages'][i].get('role') == 'user' and not group['messages'][i].get('interjected')), 0)


def _names(store, ids):
    return '、'.join(b['name'] for b in (store.find('bots', x) for x in ids) if b)


def _work_files(store, group, bot_id):
    """Lock held. {name: content hash} of the shared files this ask's work is in (saved in it, or named by its replies), as they are
    when the host sends the work back. Older files of the member's are not this work."""
    start = _ask_start(group); names = set()
    replies = [m for m in group['messages'][start:] if m.get('botId') == bot_id and m.get('role') == 'assistant' and not m.get('checkOf')]
    names |= {n for m in replies for n in m.get('savedFiles') or []}
    out = {}
    with _group_files_lock:
        pool = [e.name for e in _plain_files(group_files_dir(store, group['id']))]
        names |= {p for p in pool for m in replies for w in file_words(m.get('content')) if _in_prose(w, [p])}  # a file its reply says it handed over
        names |= {v for m in replies for v in (m.get('sameAs') or {}).values() if v in pool}  # saved, kept as the shared file with the same content
        for n in sorted(names)[:40]:
            path = group_files_dir(store, group['id']) / n
            if path.is_file() and not path.is_symlink(): out[n] = _file_hash(path)
    return out


def _redone(store, group_id, before, replies, bot_id):
    """store.lock and _group_files_lock held. Whether redone work with files was really handed in again: one of its files changed,
    or the redo saved a new file its reply names (a new version under a new name). Work without files is judged by its reply."""
    if not before: return True
    for n, digest in before.items():
        path = group_files_dir(store, group_id) / n
        if path.is_file() and not path.is_symlink() and _file_hash(path) != digest: return True
    pool = [e.name for e in _plain_files(group_files_dir(store, group_id))]
    for m in replies:
        if m.get('botId') != bot_id or m.get('role') != 'assistant': continue
        new = [n for n in m.get('savedFiles') or [] if n in pool and n not in before]
        if any(_in_prose(w, [n]) or _whole(n, w) or _claim_key(_short_name(w)) == _claim_key(n) for w in file_words(m.get('content')) for n in new): return True
    return False


class CheckOrder:
    def _check_gate(self, group_id, run_id, step, steps):
        """Before a 查核員's turn (steps[0] is it): returns steps to run it, steps[1:] when there is nothing to check, a 補存 turn
        for the members whose files are missing followed by this check again, or False when the run ended."""
        store = self.store
        if not step.get('gate'): return steps  # nobody makes anything for it: it checks what is already there
        with store.lock, _group_files_lock:  # the files are looked at with both locks held, so what is decided is what is there
            group = store.find('groups', group_id)
            if not group or group.get('runId') != run_id: return False
            start = _ask_start(group); last = {}
            since = max(start, step['since']) if isinstance(step.get('since'), int) else start  # after a send-back: only what came after it
            for m in group['messages'][since:]:  # each member's newest reply: a redo or 補存 that failed means the work was not handed in again
                if m.get('role') == 'assistant' and m.get('botId') in step.get('gate', []) and not m.get('checkOf') and m.get('status') != 'running': last[m['botId']] = m
            latest = {b: m for b, m in last.items() if m.get('status') == 'completed' and m.get('content')}
            unfinished = [b for b in step.get('gate', []) if b not in latest and store.find('bots', b) and b in group['botIds']]  # no reply, or one that did not finish: not handed in
            shared = [e.name for e in _plain_files(group_files_dir(store, group_id))]
            earlier = step.get('missing') if isinstance(step.get('missing'), dict) else {}  # what was missing before 補存 is looked for again, whatever the new reply says
            alias = {b: [k for x in group['messages'][start:] if x.get('botId') == b and x.get('role') == 'assistant' for k, v in (x.get('sameAs') or {}).items() if v in shared] for b in latest}  # saved, kept as a shared file with the same content that is still there
            said = {b: [n for n in dict.fromkeys(list(m.get('missingFiles') or []) + list(earlier.get(b) or [])) if n != NOTHING_SAVED and not _same_file(n, alias[b])] for b, m in latest.items()}  # looked for again by the full name, among the files there now
            checkers = _names(store, step['bots'])
            gone = {b: checked_present(store, group_id, names) for b, names in said.items() if names}
            pool = [e.name for e in _plain_files(group_files_dir(store, group_id))]
            given = {a.get(k) for x in group['messages'][start:] if x.get('role') == 'user' for a in x.get('attachments') or [] for k in ('name', 'origName')}
            given |= {p.rsplit('/', 1)[-1] for x in group['messages'][start:] if x.get('role') == 'user' for p in named_paths(x.get('content') or '')}  # the user's own files, given or named by path
            for b, m in latest.items():  # a file the reply says it handed over, by its full name, that is not among the shared files (the user's own files aside)
                text = m.get('content') or ''
                if any(w in text for w in SAVE_SAID):
                    mine = [n for x in group['messages'][start:] if x.get('botId') == b and x.get('role') == 'assistant' for n in x.get('savedFiles') or [] if n in pool]  # what it really saved and is still there (Zook may have cleaned the name)
                    named = [n for n in file_words(text) if not _in_prose(n, given, INPUT_JOIN) and not _in_prose(n, pool) and not _in_prose(n, alias[b]) and not any(_whole(s, n) or _claim_key(_short_name(n)) == _claim_key(s) for s in mine)]
                    if named: gone[b] = list(dict.fromkeys((gone.get(b) or []) + named))[:10]
            for b, m in latest.items():
                if m.get('skippedFiles'): gone[b] = list(dict.fromkeys((gone.get(b) or []) + list(m['skippedFiles'])))  # too big to keep: an older file of that name is not this work
                replies = [x for x in group['messages'][start:] if x.get('role') == 'assistant' and x.get('botId') == b and not x.get('checkOf')]
                before = (step.get('before') or {}).get(b) if isinstance(step.get('before'), dict) else None
                if step.get('fresh') and before is not None and not _redone(store, group_id, before, group['messages'][since:], b): gone.setdefault(b, []).append(NOTHING_SAVED)  # the new version must be saved, not the old one checked
                elif not gone.get(b) and _nothing_saved(replies, pool): gone[b] = [NOTHING_SAVED]
            gone = {b: names for b, names in gone.items() if names}
            note = lambda text: group['messages'].append(dict(id=ID(), role='system', content=text, createdAt=NOW()))
            if gone and not step.get('resaved'):  # 補存 first, also while another member's part is still missing
                fixes = {b: ('你說存了檔案，但這次沒有任何檔案存進群組檔案。' if names == [NOTHING_SAVED] else '你說交了 %s，但群組檔案裡找不到，可能沒有存成功（或太大存不進去）。' % '、'.join(names)) + '把這些檔案存到群組檔案。' for b, names in gone.items()}
                who = _names(store, list(gone))
                note('%s 說交了 %s，但群組檔案裡找不到；先退回給 %s 補存，補好再請 %s 查核。' % (who, '、'.join(n for v in gone.values() for n in v), who, checkers))
                store.save()
                return [dict(role='split_resave', bots=list(gone), blind=False, waitBusy=True, fixes=fixes), dict(step, resaved=True, missing=gone, resaveAt=len(group['messages']))] + steps[1:]  # a busy member saves once free
            if not latest or unfinished:  # the check waits for everyone's part: nothing is checked half-handed-in
                note('%s 還沒交出成果，%s 這次不用查核。' % (_names(store, unfinished or step.get('gate', [])) or '成員', checkers)); store.save(); return steps[1:]
            if gone:
                at = step.get('resaveAt') if isinstance(step.get('resaveAt'), int) else len(group['messages'])
                idle = [b for b in gone if not any(x.get('role') == 'assistant' and x.get('botId') == b for x in group['messages'][at:])]  # never got to 補存 (busy, or skipped)
                files = '、'.join(n for v in gone.values() for n in v)
                note(('%s 沒有補存到（正在忙或沒有回覆），%s 還是找不到；%s 這次不查核。' % (_names(store, idle), files, checkers)) if idle else
                     '%s 補存後還是找不到 %s，%s 這次不查核；請 %s 重新存檔後再請查核。' % (_names(store, list(gone)), files, checkers, _names(store, list(gone))))
                store.save(); return steps[1:]
            need = sorted({n for b in latest for x in group['messages'][start:] if x.get('botId') == b and x.get('role') == 'assistant' and not x.get('checkOf')
                           for n in list(x.get('savedFiles') or []) + list((x.get('sameAs') or {}).values()) + [p for w in file_words(x.get('content')) for p in pool if _in_prose(w, [p])] if n in pool})[:40]  # saved, or named and already there
            step['need'] = {n: _file_hash(group_files_dir(store, group_id) / n) for n in need}  # what the check is for, as it is now: gone or changed by the time it starts, it does not run
        return steps

    def _free_check(self, group_id, run_id, gate):
        """A discussion with a host: the 查核員 the kickoff named, once the members' independent round is over. Returns
        (turns to add, the gate still to pass, the step those turns run with); False when the run ended."""
        if not gate.get('bots'): return [], None, None  # no 查核員 was named for this work
        step = check_step(gate['bots'], gate['gate']); step.update(resaved=gate.get('resaved', False), missing=gate.get('missing') or {}, resaveAt=gate.get('resaveAt'))
        after = self._check_gate(group_id, run_id, step, [step])
        if after is False: return False
        if not after: return [], None, None
        now = {k: v for k, v in after[0].items() if k != 'waitBusy'}  # a member busy elsewhere is skipped with a line, as in any discussion
        later = dict(gate, resaved=True, missing=after[1].get('missing'), resaveAt=after[1].get('resaveAt')) if now['role'] == 'split_resave' else None
        return [(x, False, now['role']) for x in now['bots']], later, now

    def _recheck(self, group_id, run_id, closer, fixes):
        """Lock held. After the host sends work back in 分工: (the redo step, the check that follows it). A member that checks is
        asked again after the work it checked is redone (the new version is checked, not the old one)."""
        group = self.store.find('groups', group_id)
        bots = [b for b in (self.store.find('bots', x) for x in group['botIds']) if b and b['id'] != closer]
        producers, checkers = split_checkers(self.store, group, [b['id'] for b in bots])
        if not checkers: return dict(role='split_redo', bots=[b['id'] for b in bots if b['id'] in fixes], blind=False, fixes=fixes), None
        redo = [x for x in producers if x in fixes]
        checked = checkers if redo else [x for x in checkers if x in fixes]  # redone work is checked, also when the first check did not run
        step = dict(role='split_redo', bots=redo, blind=False, waitBusy=True, fixes={k: fixes[k] for k in redo}) if redo else None  # a busy member redoes it once free
        again = check_step(checked, redo or producers, {k: v for k, v in fixes.items() if k in checkers}) if checked and (redo or any(x in fixes for x in checkers)) else None
        if again and redo: again.update(fresh=True, since=len(group['messages']), before={b: _work_files(self.store, group, b) for b in redo})
        return step, again


def _check_tasks(run, deps):
    """(checks not started that can wait for new work, checks that cannot: under way, done, or one the new work itself waits for)."""
    checks = [t for t in run['tasks'] if t.get('check') and t['status'] not in ('cancelled', 'failed')]
    waiting = [t for t in checks if not t['attempts'] and t['status'] in ('pending', 'ready', 'waiting') and t['n'] not in deps]  # one the new work waits for cannot wait for it
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


def verify_again(task):
    """A check that runs again (stopped, restarted, retried) keeps the files it is for."""
    need = (task.get('verify') or {}).get('need')
    return dict(state='waiting', **({'need': need} if isinstance(need, dict) else {}))


def task_files_kept(store, group, msg, attempt=None, owner=''):
    """store.lock and _group_files_lock held. {name: content hash} of the shared files the task handed in (brought in by its reply,
    or listed in its report and already there), for its check to find still there, unchanged."""
    pool = {e.name for e in _plain_files(group_files_dir(store, group['id']))}
    names = set(list(msg.get('savedFiles') or []) + list((msg.get('sameAs') or {}).values()))
    names |= {p for p in pool for f in (attempt or {}).get('files') or [] if _same_file(str(f).rsplit('/', 1)[-1], [p], owner)}
    return {n: _file_hash(group_files_dir(store, group['id']) / n) for n in sorted(names & pool)[:40]}


def group_files_given(group):
    """The attachments of the user's messages in a group: the user's own files, never a member's work."""
    return [m.get('attachments') or [] for m in (group or {}).get('messages') or [] if m.get('role') == 'user']


def task_files_missing(store, group, owner, attempt, msg, spec='', given=(), owner_id=''):
    """store.lock and _group_files_lock held. The files a task's report lists, or its reply or summary says it saved, that are not
    there as this member's: saved in this reply, or last saved by this member (another member's file of the same name is not its work)."""
    listed = list(attempt.get('files') or [])
    said = str(attempt.get('summary') or '') + '\n' + str(msg.get('content') or '')
    inputs = {p.rsplit('/', 1)[-1] for p in named_paths(str(spec or ''))} | set(given)  # files the work was told to read, or the user gave
    named = [n for n in file_words(said) if not _in_prose(n, inputs, INPUT_JOIN)] if any(w in said for w in SAVE_SAID) else []  # 「已存好報價單.xlsx」 without listing it in files
    pool = [e.name for e in _plain_files(group_files_dir(store, group['id']))]
    mine = set(msg.get('savedFiles') or []) | {n for n, info in (group.get('fileInfo') or {}).items() if (((info or {}).get('byId') == owner_id) if (info or {}).get('byId') else (info or {}).get('by') == owner)}  # by the Bot itself; names can repeat
    gone = checked_present(store, group['id'], listed + list(msg.get('missingFiles') or []), exact=listed, owner=owner) + [n for n in named if not _in_prose(n, [p for p in pool if p in mine])]  # named: there, and its own
    for raw in listed:
        base = re.sub(r'(\.[A-Za-z0-9]{1,10})\s*[（(][^（）()]{0,30}[）)]$', r'\1', ' '.join(str(raw or '').split())).strip(' 「」『』`\'"').rsplit('/', 1)[-1]
        if base and base not in gone and _same_file(base, pool, owner) and not _same_file(base, [n for n in pool if n in mine], owner): gone.append(base)
    alias = [k for k in (msg.get('sameAs') or {}) if k]  # saved under its name, kept as the shared file with the same content
    full = [x for x in listed + list(msg.get('savedFiles') or []) + alias if x and x not in gone]  # whole names it handed over: a piece of one picked from the prose is that file
    piece = lambda n: n in named and any(_whole(f, n) or _claim_key(_short_name(n)) == _claim_key(_short_name(f)) for f in full)
    return [n for n in dict.fromkeys(gone + list(msg.get('skippedFiles') or [])) if not _in_prose(n, alias) and not _same_file(n, alias) and not piece(n)][:10]
