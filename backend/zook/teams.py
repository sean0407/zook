# A whole team from one sentence: one model call drafts a coordinator and its members with clear, separate duties; the user looks the
# cards over, and Zook then makes the Bots and their group in one go. Loaded by backend/server.py into one shared namespace.
TEAM_MEMBERS = (3, 7)  # besides the coordinator
TEAM_FIELDS = dict(name=20, jobTitle=12, duty=200, deliverable=200, worksWith=200, notDoing=200, persona=300)
TEAM_LABELS = (('duty', '負責'), ('deliverable', '主要交付物'), ('worksWith', '協作對象'), ('notDoing', '不負責'))
TEAM_KICKOFF = '團隊剛成立。請每位成員依自己的職責，交一份自己領域的起步清單：最先要做的三到五件事、需要誰提供什麼。統籌最後整理成一份分工表。'
TEAM_ASK = '''請為下面這件事規劃一個工作團隊。只輸出一個 JSON 物件，不要有其他文字，也不要使用任何工具。

格式：
{"team": "團隊名稱（12 字以內）", "coordinator": {角色}, "members": [{角色}, …]}

每個角色的欄位（全部必填，繁體中文）：
- name：名字，8 字以內，彼此不同。用職能命名，不要用人名。
- jobTitle：職稱，12 字以內，彼此不同。
- duty：負責什麼，一句話。
- deliverable：主要交付物，具體可檢查。
- worksWith：和誰協作、交接什麼（用其他角色的 name）。
- notDoing：不負責什麼（寫出容易和別人重疊的地方歸誰）。
- persona：說話方式與做事風格，一句話。
- model：使用者在句子裡指定這個角色用的模型（例如 Claude、Codex、Grok、Gemini、Antigravity、Cursor），照原文寫；沒指定就寫空字串。
- effort：使用者指定這個角色的思考強度（快速、標準、深入）；沒指定就寫空字串。

規則：
- coordinator 是統籌：拆解目標、分派、整合成果、追進度；自己不做各領域的專業工作。
- members 要 %d 到 %d 位，依這件事真正需要的職能決定人數，不要為了湊數加人。
- 每位成員的分工都相對於統籌和其他成員來定義，彼此不重疊；每件重要的事只有一個負責人。
- 使用者指定的模型和思考強度只寫在 model、effort，不要寫進其他欄位。

要做的事：
'''


def _team_text(value, limit):
    text = ' '.join(str(value or '').split())
    return text[:limit]


def clean_team_role(raw, taken):
    """One role with every field present and within its length, and a name nobody else has. None when it cannot be used."""
    if not isinstance(raw, dict): return None
    role = {k: _team_text(raw.get(k), limit) for k, limit in TEAM_FIELDS.items()}
    if not role['name'] or not role['jobTitle'] or not role['duty']: return None
    base, n = role['name'], 2
    while role['name'].lower() in taken: role['name'] = '%s%d' % (base[:TEAM_FIELDS['name'] - 2], n); n += 1
    taken.add(role['name'].lower())
    return role


def parse_team(text, existing=()):
    """The draft a model wrote, checked field by field. Raises ValueError when it is not a usable team."""
    start, end = (text or '').find('{'), (text or '').rfind('}')
    try: data = json.loads(text[start:end + 1]) if 0 <= start < end else None
    except ValueError: data = None
    if not isinstance(data, dict): raise ValueError('模型沒有照格式回覆，請再試一次。')
    taken = {str(n).strip().lower() for n in existing}
    lead = clean_team_role(data.get('coordinator'), taken)
    members = []
    for raw in (data.get('members') if isinstance(data.get('members'), list) else [])[:TEAM_MEMBERS[1]]:
        role = clean_team_role(raw, taken)
        if role: members.append(role); _team_wish(role, raw)
    if lead: _team_wish(lead, data.get('coordinator'))
    if not lead or len(members) < TEAM_MEMBERS[0]: raise ValueError('模型規劃的團隊不完整，請再試一次，或把要做的事說得更具體。')
    titles = set()
    for role in [lead] + members:  # two people with one title would be told apart by nothing
        if role['jobTitle'] in titles: role['jobTitle'] = role['name'][:TEAM_FIELDS['jobTitle']]
        titles.add(role['jobTitle'])
    return dict(team=_team_text(data.get('team'), 30) or '新團隊', coordinator=lead, members=members)


# The model and thinking level a sentence names for a role (「查核用 Grok、查核要深入」). The model writes them into its JSON; what it
# leaves out is read from the sentence, and a model named for nobody is said in the preview, never dropped without a word.
TEAM_ALIASES = (('claude', ('claude', 'anthropic', '克勞德')), ('codex', ('codex', 'chatgpt', 'openai', 'gpt')), ('grok', ('grok',)),
                ('antigravity', ('antigravity',)), ('gemini', ('gemini',)), ('cursor', ('cursor',)))
TEAM_EFFORT_WORDS = (('deep', ('深入', '仔細', '徹底')), ('fast', ('快速', '快一點')), ('standard', ('標準',)))


def _team_pattern(table, verb):
    words = sorted((w for _, ws in table for w in ws), key=len, reverse=True)
    return re.compile(verb + '(' + '|'.join(map(re.escape, words)) + ')', re.I)


# Only a word right after 用／交給／要 counts: 「做 ChatGPT 外掛」 or 「快速上市」 names no model and no level.
_TEAM_MODEL_RE = _team_pattern(TEAM_ALIASES, r'(?:要|請|就|都|需要|得|改|再)?(?:用|使用|交給|給|由|讓)\s*')
_TEAM_EFFORT_RE = _team_pattern(TEAM_EFFORT_WORDS, r'(?:要|請|需要|得|調成|改成|設為)\s*')


def _team_find(text, table):
    """(id, where it starts) for the word of the table that comes first in the text, or ('', -1)."""
    low, best = str(text or '').lower(), ('', -1)
    for key, words in table:
        for w in words:
            at = low.find(w)
            if at >= 0 and (best[1] < 0 or at < best[1]): best = (key, at)
    return best


def team_named_provider(text): return _team_find(text, TEAM_ALIASES)[0]


def team_effort(text):
    value = str(text or '').strip().lower()
    return TOOL_EFFORTS.get(value) or _team_find(value, TEAM_EFFORT_WORDS)[0] if value else ''


def _team_wish(role, raw):
    raw = raw if isinstance(raw, dict) else {}
    role['wanted'] = team_named_provider(raw.get('model')); role['effort'] = team_effort(raw.get('effort'))


def team_sentence_wishes(goal):
    """[(key, value, word, subject)] for each 「文案、設計用 Claude」「查核要深入」 in the sentence. The subject of a wish is what comes after
    the wish before it in the same clause, so 「文案用 Claude、設計用 Codex」 gives 文案 → Claude and 設計 → Codex."""
    out = []
    for clause in re.split(r'[，,。；;！!？?\n]+', goal):
        found = sorted([(m, 'wanted', TEAM_ALIASES) for m in _TEAM_MODEL_RE.finditer(clause)] + [(m, 'effort', TEAM_EFFORT_WORDS) for m in _TEAM_EFFORT_RE.finditer(clause)], key=lambda x: x[0].start())
        end = 0
        for m, key, table in found:
            if m.start() < end: continue
            word = m.group(1); value = next(k for k, ws in table if word.lower() in ws)
            for part in re.split(r'[、和與及跟/]+', clause[end:m.start()]):
                part = part.strip()
                if part: out.append((key, value, word, part))
            end = m.end()
    return out


def _team_role_for(subject, roles):
    """The one role whose name or title holds the end of the subject (「讓文案」 → 文案企劃), or None."""
    for n in (4, 3, 2):
        if len(subject) < n: continue
        hits = [r for r in roles if subject[-n:] in r['name'] + r['jobTitle']]
        if len(hits) == 1: return hits[0]
    return None


def team_effort_ok(store, provider):
    """Lock held. Whether the thinking level can be set for this CLI (自動選擇: each message's model uses it when it can)."""
    if provider == AUTO: return True
    return 'effort' in ABILITY_CHECKS.get(provider_kind(provider), {}) and 'effort' not in ((store.data.get('abilityChecks') or {}).get(provider) or {}).get('missing', {})


def team_provider_problem(store, provider):
    """Lock held. Why this CLI cannot be used for a new Bot on this Mac, or ''."""
    name = provider_label(provider).split('（')[0]
    if provider not in P.active_ids(store.data): return '這台 Mac 沒有加入 %s。' % name
    if not find_cli(provider): return '這台 Mac 沒有安裝 %s。' % name
    if ((store.data.get('autoStatus') or {}).get(provider) or {}).get('signedIn') is False: return '%s 還沒登入。' % name
    return ''


def team_models(store, goal, roles):
    """Lock held. Each role's model for the preview: the one named, 自動選擇 (with what it would pick now), or '' with the reason when
    the named one cannot be used here and the user has to choose. Returns (choices for the dropdown, warnings for the whole team)."""
    low, warnings = goal.lower(), []
    for role in roles:  # what the model wrote is kept only when the sentence names it at all
        if role.get('wanted') and not any(w in low for w in dict(TEAM_ALIASES)[role['wanted']]): role['wanted'] = ''
        if role.get('effort') and not _TEAM_EFFORT_RE.search(goal): role['effort'] = ''
    for key, value, word, subject in team_sentence_wishes(goal):  # the sentence itself comes first
        role = _team_role_for(subject, roles)
        if role: role[key] = value
        else: warnings.append('句子裡「%s%s%s」沒有對應到唯一的成員，請在下面替%s選擇%s。' % (subject, '用 ' if key == 'wanted' else '要', word, '要用它的成員' if key == 'wanted' else '成員', '模型' if key == 'wanted' else '思考強度'))
    choices = [dict(id=AUTO, name='自動選擇', problem='', effort=True)]
    choices += [dict(id=pid, name=provider_label(pid).split('（')[0], problem=team_provider_problem(store, pid), effort=team_effort_ok(store, pid)) for pid in P.active_ids(store.data)]
    for role in roles:
        wanted = role.pop('wanted', '') or ''
        problem = team_provider_problem(store, wanted) if wanted else ''
        role.update(provider=AUTO if not wanted else '' if problem else wanted, problem='', wanted=wanted)
        if problem: role['problem'] = '句子指定 %s，但%s請選一個要用的模型。' % (provider_label(wanted).split('（')[0], problem)
        if role['provider'] and role.get('effort') and not team_effort_ok(store, role['provider']):
            warnings.append('「%s」用的 %s 不能調整思考強度，指定的強度沒有套用。' % (role['name'], provider_label(role['provider']).split('（')[0])); role['effort'] = ''
        if role['provider'] == AUTO and 'autoStatus' in store.data:
            task = bot_work(dict(name=role['name'], jobTitle=role['jobTitle'], persona=role.get('persona', '')), False)
            try: role['autoPick'] = auto_choice_name(*auto_choices(store, task, AUTO_TASKS[task][1])[0])
            except ValueError: pass
    return choices, warnings


def team_instructions(role, team, goal, lead, everyone):
    lines = ['你是「%s」團隊的%s，職稱是%s。' % (team, '統籌' if role is lead else '成員', role['jobTitle']), '團隊目標：' + goal, '']
    lines += ['%s：%s' % (label, role[key]) for key, label in TEAM_LABELS if role.get(key)]
    lines += ['', '團隊成員：'] + ['- %s（%s）%s：%s' % (r['name'], r['jobTitle'], '，統籌' if r is lead else '', r['duty']) for r in everyone if r is not role]
    lines += ['', '不屬於你負責的事，交給負責的成員，不要自己做。' if role is not lead else '你負責拆解目標、分派工作、整合成果與追蹤進度；各領域的專業工作交給負責的成員。']
    return '\n'.join(lines)[:10000]


TOOL_EFFORTS = {'fast': 'fast', 'low': 'fast', '快速': 'fast', '低': 'fast', 'standard': 'standard', 'medium': 'standard', '標準': 'standard', '中': 'standard', '中度': 'standard',
                'deep': 'deep', 'high': 'deep', '深入': 'deep', '高': 'deep'}


def tool_bot_fields(store, args):
    """(fields for the new Bot, notes on what could not be set). Lock held. The account is found by its name, for that CLI only."""
    fields, notes = {}, []
    provider = str(args.get('provider') or '').strip()
    if provider:
        if provider.startswith(P.CUSTOM_PREFIX): notes.append('Bot 新增的 Bot 不能用自訂 CLI「%s」，改用自動選擇；要用請在 Mac 上設定。' % provider)
        elif provider != AUTO and not P.spec(store.data, provider): notes.append('找不到模型「%s」，改用自動選擇。' % provider)
        else: fields['provider'] = provider
    if args.get('model'):
        if fields.get('provider', AUTO) == AUTO: notes.append('自動選擇的 Bot 每則訊息自己挑模型，沒有套用「%s」。' % args['model'])
        else: fields['model'] = str(args['model'])[:100]
    wanted = str(args.get('account') or '').strip()
    if wanted:
        cli = fields.get('provider', '')
        mine = [a for a in store.data.get('accounts') or [] if a.get('provider') == cli] if cli and cli != AUTO else []
        exact = [a for a in mine if a.get('name') == wanted]; loose = [a for a in mine if same_name(a.get('name')) == same_name(wanted)]
        match = exact[0] if len(exact) == 1 else loose[0] if not exact and len(loose) == 1 else None
        if not cli or cli == AUTO: notes.append('帳號「%s」要搭配指定的模型（例如 Codex）才能套用，這次沒有套用。' % wanted)
        elif len(exact) > 1 or (not exact and len(loose) > 1): notes.append('%s 有不只一個叫「%s」的帳號，這次用預設帳號，請你在 Bot 設定裡選。' % (provider_label(cli).split('（')[0], wanted))
        elif not match: notes.append('%s 沒有名為「%s」的帳號，這次用預設帳號。' % (provider_label(cli).split('（')[0], wanted))
        elif match.get('type') == 'key' or auto_known_billed((store.data.get('autoStatus') or {}).get(auto_account_key(match))): notes.append('「%s」是 API 計費的帳號，要由你在 Bot 設定裡指定，這次用預設帳號。' % match['name'])
        else: fields['account'] = match['id']
    if args.get('effort'):
        level = TOOL_EFFORTS.get(str(args['effort']).strip().lower()); cli = fields.get('provider', '')
        if not level: notes.append('思考強度「%s」看不懂，用預設。' % args['effort'])
        elif cli and not team_effort_ok(store, cli):
            notes.append('%s 不能調整思考強度，沒有套用。' % provider_label(cli).split('（')[0])
        else: fields['effort'] = level
    return fields, notes


def team_role_model(store, raw, name):
    """Lock held. {provider, effort} the user confirmed for one role. A role sent without a model (an older window) is 自動選擇; one
    left on 「請選擇」, or with a model this Mac cannot use, stops the whole team before anything is made."""
    provider = raw.get('provider')
    provider = AUTO if provider is None else str(provider).strip()
    if not provider: raise ValueError('請替「%s」選擇要用的模型。' % name)
    if provider != AUTO:
        problem = team_provider_problem(store, provider)
        if problem: raise ValueError('「%s」：%s請改選其他模型。' % (name, problem))
    effort = str(raw.get('effort') or '').strip()
    if effort and effort not in EFFORTS: raise ValueError('「%s」的思考強度無效。' % name)
    if effort and not team_effort_ok(store, provider): raise ValueError('「%s」：%s 不能調整思考強度。' % (name, provider_label(provider).split('（')[0]))
    return dict(provider=provider, effort=effort)


class Teams:
    """Mixed into App."""
    def draft_team(self, goal, inventory):
        """One model call, read-only and without tools. Nothing is created yet."""
        store = self.store
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 2000: raise ValueError('請用一句話描述要做的事（最多 2000 字）。')
        with store.lock:
            carrier = next((b for b in store.data['bots'] if b.get('isAdmin')), None) or next(iter(store.data['bots']), None)
            if not carrier: raise ValueError('請先新增一個 Bot，再建立團隊。')
            existing = [b['name'] for b in store.data['bots']]
            try: provider, model, account = pick_auto(store, '請分析並規劃', plan=True)[0][0] if store.data.get('autoStatus') else bot_model(store, {}) + ('',)
            except ValueError: provider, model, account = bot_model(store, {}) + ('',)
            helper = dict(id=ID(), botId=carrier['id'], messageId='', status='running', content='', createdAt=NOW(), toolCalls=[], approvals=[], plan=True, noResume=True, internal='team')
            store.data['jobs'].append(helper); bot = dict(copy.deepcopy(carrier), account=account)  # the chosen sign-in, never an account the carrier Bot happens to have
        try: self._run_attempt(helper['id'], TEAM_ASK % TEAM_MEMBERS + goal.strip(), provider, model, bot, inventory, True)
        finally:
            with store.lock: store.data['jobs'][:] = [j for j in store.data['jobs'] if j['id'] != helper['id']]
        if helper.get('status') != 'completed' or not (helper.get('content') or '').strip(): raise RuntimeError(str(helper.get('error') or '模型沒有回覆，請再試一次。')[:300])
        draft = dict(parse_team(helper['content'], existing), goal=goal.strip())
        with store.lock: choices, warnings = team_models(store, draft['goal'], [draft['coordinator']] + draft['members'])
        return dict(draft, choices=choices, warnings=warnings)

    def create_team(self, body):
        """Lock held. Makes every Bot and the group, or nothing at all. Started by the user in the window, so it is not an approval."""
        store = self.store; goal = _team_text(body.get('goal'), 2000); team = _team_text(body.get('team'), 30)
        roles = body.get('roles')
        if not team or not goal or not isinstance(roles, list): raise ValueError('團隊資料不完整。')
        taken = {b['name'].strip().lower() for b in store.data['bots']}; cleaned, models = [], []
        for raw in roles:
            role = clean_team_role(raw, set())
            if not role: raise ValueError('每個角色都要有名稱、職稱和負責的事。')
            if role['name'].lower() in taken: raise ValueError('已經有名為「%s」的 Bot，請改一個名稱。' % role['name'])
            taken.add(role['name'].lower()); cleaned.append(role); models.append(team_role_model(store, raw, role['name']))
        if not 1 + TEAM_MEMBERS[0] <= len(cleaned) <= 1 + TEAM_MEMBERS[1]: raise ValueError('團隊要有一位統籌和 %d 到 %d 位成員。' % TEAM_MEMBERS)
        if any(g['name'].strip().lower() == team.lower() for g in store.data['groups']): raise ValueError('已經有同名的群組，請改一個團隊名稱。')
        lead, bots, at = cleaned[0], [], len(store.data['bots'])
        for i, role in enumerate(cleaned):
            bot = dict(id=ID(), name=role['name'], color=colors_for(at + i), shape=str((at + i) % 13), instructions='', persona='', provider=AUTO, model='', pinned=False, section=team, messages=[], enabledSkills=[], enabledMcp=[], allowCommands=True, isAdmin=False)
            update(bot, dict(models[i], name=role['name'], jobTitle=role['jobTitle'], persona=role['persona'], instructions=team_instructions(role, team, goal, lead, cleaned)), 'bot')
            set_gate_full(bot); auto_on_create(store, bot, instructions=False, grant=True); ensure_chats(bot); bots.append(bot)  # the team's shared instructions would make every member look alike
        group = dict(id=ID(), name='', botIds=[], messages=[], status='idle', runId=None, activeJobId=None, createdAt=NOW())
        store.data['bots'].extend(bots)
        try: set_group_fields(store, group, dict(botIds=[b['id'] for b in bots], name=team, hostId=bots[0]['id']), creating=True)
        except Exception:
            del store.data['bots'][at:]; raise
        store.data['groups'].append(group)
        sections = store.data['settings'].setdefault('sections', [])
        if team not in sections: sections.append(team)
        if body.get('kickoff') is True: self.post_group_message(group, TEAM_KICKOFF)
        store.save(); watch_auto_status(store, bots[0])
        log_activity(store, 'bot', '建立團隊「%s」：%s' % (team, '、'.join(b['name'] for b in bots)))
        for b in bots: self.want_intro(b['id'])  # each new member's greeting, one at a time in the background
        return dict(group=group, bots=[dict(id=b['id'], name=b['name']) for b in bots])
