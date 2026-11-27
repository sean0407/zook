# 群組交件 (#319, #326, #273④, #266①, #291, #335, #140③). Loaded by backend/server.py into one shared namespace, after checkread.py.
#
# 說交了但沒有 is said only of a member that says, in its own words, that it handed a file over (已存好、已交付…), not of one that
# names a file while handing work out, asking for it or checking it. A deck checked after a reply is one the member saved, not the
# copy of the group's files Zook put in its folder. The place the user named for the results goes to every member and is looked at
# when work is handed in. A host that says it must ask the user first hands nothing out. A reply left 「正在查核」 after its run is
# over is marked failed.

# ---- 說交了但沒有 (#319, #326) ----
CLAIM_DONE = re.compile(r'已(?:經)?(?:另存|存|上傳|交付|交出|產出|輸出|匯出|放|寫入)|存(?:好|妥)|(?:存|放|寫)(?:到|進|入|成)了|交付了|交了|交出了|產出了')
CLAIM_UNDONE = re.compile(r'尚未|還沒|沒(?:有)?(?:存|放|上傳|交|產出|成功)|未(?:存|放|上傳|交|產出|成功)|其實沒|並沒|不成功|失敗|存不|放不|不了')  # 「已交付，但尚未存到群組檔案」
CLAIM_NOT = re.compile(r'請|麻煩|需要|要|會|將|預計|準備|打算|記得|負責|應該|必須|可以|待|還沒|尚未|沒有|沒|未|無法|不能|不要|是否|嗎|@')
CLAIM_ROLES_NOT = ('kickoff', 'moderate', 'verify', 'split_check', 'check_final', 'split_follow')  # handing work out or checking it
_CLAIM_CUT = re.compile(r'[。；;！!？?]')
_CLAIM_BULLET = re.compile(r'^\s*(?:[-*•・>]|\d{1,2}[.、)）])')


def delivery_claims(text, others=(), role=None):
    """The parts of a reply where the member says it handed a file over itself: a clause with 已存、存好、已交付… that is not a request,
    a plan, a doubt or another member's doing, and the list right under such a clause. '' when there is none."""
    if role in CLAIM_ROLES_NOT: return ''
    kept, listing = [], False
    for line in str(text or '')[:20000].splitlines()[:400]:
        if listing and _CLAIM_BULLET.match(line): kept.append(line); continue
        listing = False
        for clause in _CLAIM_CUT.split(line):
            hit = CLAIM_DONE.search(clause)
            if not hit: continue
            start = max(clause.rfind(x, 0, hit.start()) for x in '，,、') + 1
            end = min([i for i in (clause.find(x, hit.end()) for x in '，,、') if i >= 0] or [len(clause)])
            if CLAIM_NOT.search(clause[start:hit.start()]) or CLAIM_UNDONE.search(clause[hit.end():]) or any(n and n in clause[start:end] for n in others): continue  # a request, a doubt, not done after all, or what another member did
            kept.append(clause); listing = clause.rstrip(' *').endswith(('：', ':'))
    return '\n'.join(kept)


# ---- A deck's check belongs to the member that saved it (#326) ----
GROUP_COPIES_SEEN = {}  # job id → {name: content hash} of the group's files Zook copied in for that reply (in memory, for its checks)


def group_copies_seen(job_id, seen=None):
    """Kept while a reply runs (seen given), dropped after it (None)."""
    if seen is None: GROUP_COPIES_SEEN.pop(job_id, None)
    else: GROUP_COPIES_SEEN[job_id] = dict(seen)


def group_copy_unchanged(store, job_id, bot_id, path):
    """Whether this file is Zook's copy of a group file in the member's folder, as it was copied in for this reply: the member did
    not make it. Compared with what was copied, not with the group's file now (another member may have changed that meanwhile)."""
    try:
        if os.path.dirname(str(path)) != str(group_copy_folder(store, bot_id)): return False
        digest = (GROUP_COPIES_SEEN.get(job_id) or {}).get(os.path.basename(str(path)))
        return bool(digest) and _file_hash(pathlib.Path(str(path))) == digest
    except (OSError, ValueError): return False


# ---- 使用者指定的存檔位置 (#273④, #266①) ----
_PLACE_GAP = re.compile(r'(?<=[^\x00-\x7f])(?=~?/)')
_PLACE_TAIL = ('資料夾裡', '資料夾內', '資料夾', '目錄下', '底下', '裡面', '裡', '里', '內', '中', '下')


_PLACE_SAID = re.compile(r'(?:存到|存在|存進|存入|存放(?:到|在)?|存一份(?:到|在)?|放一份(?:到|在)|另存(?:一份)?(?:到|在)?|儲存(?:到|在)|放到|放在|放進|輸出到|匯出到|交到|save (?:it )?(?:to|in))'
                         r'\s*[:：]?\s*(?:「([^」\n]{1,300})」|『([^』\n]{1,300})』|"([^"\n]{1,300})"|(~?/[^\s，。、；;！？」』"\n]{1,300}))', re.I)


def asked_places(group):
    """Folders or files the user said to save the results to in this ask (「存到 /…」「放在「~/…」」): only a path right after such
    words, so a file the user only gave to be read is not one. A quoted path keeps its spaces."""
    found, home = [], os.path.expanduser('~')
    for hit in _PLACE_SAID.finditer(str(group_asked(group).get('content') or '')[:20000]):
        quoted = not hit.group(4); path = next(x for x in hit.groups() if x).strip()
        if not quoted:  # words of the sentence after a bare path; a quoted path is taken as it is
            path = path.rstrip('。，.,:：;；')
            for tail in _PLACE_TAIL:
                if path.endswith(tail) and len(path) > len(tail) + 2: path = path[:-len(tail)]; break
        if path.startswith('~/'): path = home + path[1:]
        if path.startswith('file:///'): path = path[7:]
        if not path.startswith('/') or path.startswith('//'): continue
        path = os.path.normpath(path)  # 「/tmp/../etc」 is /etc
        if path.count('/') < 2 or _folder_never(path) or _folder_never(os.path.realpath(path)) or path in found: continue  # the Mac's own folders, also through a link
        found.append(path)
    return found[:5]


def asked_place_rules(group, writable, moderator):
    """What every member is told of the place the user named."""
    places = asked_places(group)
    if not places: return []
    line = '使用者指定的存檔位置：%s。' % '、'.join(places)
    if moderator in ('verify', 'split_check'): return [line + '查核時一併確認成品也存到了這個位置，沒有就寫出來。']
    if moderator in ('kickoff', 'split_plan', 'split_follow'): line += '分工時把這個位置寫給負責製作的成員。'
    if writable: line += '成品除了存進群組檔案，也要另存一份到這個位置（資料夾不存在就建立），存好後寫出完整路徑；存不了就直接說存不了和原因，不要說下一則再存。'
    elif moderator not in ('kickoff', 'moderate'): line += '你這次不能存檔；成品要存到這個位置時，直接說明需要哪位成員存，不要說下一則再存。'
    return [line]


def asked_place_missed(store, group_id, turn, saved):
    """A member that handed files in to the group but did not put them in the place the user named during this reply: that place,
    else ''. Looked for by the names it handed in (saved, or kept as a group file with the same content)."""
    saved = list(dict.fromkeys(list(saved or []) + [n for pair in turn.get('kept') or [] for n in pair]))
    if not saved or turn.get('role') in CLAIM_ROLES_NOT + ('final', 'compare_diff', 'verdict'): return ''
    with store.lock:
        group = store.find('groups', group_id)
        places = asked_places(group) if group else []
        start = _xstamp((store.find('jobs', turn['job']['id']) or {}).get('createdAt'))
    if not places or start is None: return ''
    for place in places:
        try:
            if os.path.isdir(place):  # every file handed in, saved there during this reply
                if all(os.path.isfile(os.path.join(place, n)) and os.stat(os.path.join(place, n)).st_mtime >= start - 1 for n in saved): return ''
            elif os.path.isfile(place) and os.stat(place).st_mtime >= start - 1: return ''
        except OSError: continue
    return places[0]


# ---- 主持人說要先問使用者 (#335) ----
ASK_FIRST = re.compile(r'【先問你】|(?:確認|回覆|答覆|回答|決定|拍板)[^。\n]{0,8}?(?:後|完|好)[^。\n]{0,6}?再[^。\n]{0,8}?(?:交給|派|開工|分工|動工|開始|進行|製作|著手)'
                       r'|等(?:你|您|使用者)[^。\n]{0,8}?(?:確認|回覆|答覆|回答|決定)[^。\n]{0,6}?(?:後|再)[^。\n]{0,8}?(?:交給|派|開工|分工|動工|開始|進行|製作|著手)'
                       r'|先(?:問|請教)(?:你|您|使用者)|先(?:向|跟|和|與)(?:你|您|使用者)(?:確認|釐清|問)')


def host_asks_first(text):
    """Whether the host's planning reply says it must ask the user before anyone starts."""
    text = str(text or '')[:4000]
    return any(not ASK_NOT.search(text[max(0, hit.start() - 6):hit.start()]) for hit in ASK_FIRST.finditer(text))  # 「不用先問你，直接分工」 hands work out


ASK_NOT = re.compile(r'不用|不必|不需|無需|無須|免|沒必要|不再')


def ask_first_hold(store, group_id, run_id):
    """The host asks the user first: nobody else is started this time (#335)."""
    with store.lock:
        group = store.find('groups', group_id)
        if group and group.get('runId') == run_id:
            group['messages'].append(dict(id=ID(), role='system', content='主持人要先問你，成員這次先不開工；回答主持人的問題後才會分工。', createdAt=NOW())); store.save()
    return []


# ---- 殘留的「正在查核」(#291) ----
def group_settle_running(store, group):
    """Lock held. A reply still marked running whose job is not running any more (stopped before it began, gone after a restart) is
    marked failed; a check says so under the reply it was checking."""
    running = {j.get('messageId') for j in store.data.get('jobs') or [] if j.get('status') == 'running'}
    for m in (group or {}).get('messages') or []:
        if m.get('role') == 'assistant' and m.get('status') == 'running' and m.get('id') not in running:
            m['status'] = 'failed'
            if m.get('checkOf'): m['error'] = m.get('error') or '查核中斷了，沒有完成。可以再試一次。'
