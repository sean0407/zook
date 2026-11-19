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

規則：
- coordinator 是統籌：拆解目標、分派、整合成果、追進度；自己不做各領域的專業工作。
- members 要 %d 到 %d 位，依這件事真正需要的職能決定人數，不要為了湊數加人。
- 每位成員的分工都相對於統籌和其他成員來定義，彼此不重疊；每件重要的事只有一個負責人。

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
    members = [r for r in (clean_team_role(x, taken) for x in (data.get('members') if isinstance(data.get('members'), list) else [])[:TEAM_MEMBERS[1]]) if r]
    if not lead or len(members) < TEAM_MEMBERS[0]: raise ValueError('模型規劃的團隊不完整，請再試一次，或把要做的事說得更具體。')
    titles = set()
    for role in [lead] + members:  # two people with one title would be told apart by nothing
        if role['jobTitle'] in titles: role['jobTitle'] = role['name'][:TEAM_FIELDS['jobTitle']]
        titles.add(role['jobTitle'])
    return dict(team=_team_text(data.get('team'), 30) or '新團隊', coordinator=lead, members=members)


def team_instructions(role, team, goal, lead, everyone):
    lines = ['你是「%s」團隊的%s，職稱是%s。' % (team, '統籌' if role is lead else '成員', role['jobTitle']), '團隊目標：' + goal, '']
    lines += ['%s：%s' % (label, role[key]) for key, label in TEAM_LABELS if role.get(key)]
    lines += ['', '團隊成員：'] + ['- %s（%s）%s：%s' % (r['name'], r['jobTitle'], '，統籌' if r is lead else '', r['duty']) for r in everyone if r is not role]
    lines += ['', '不屬於你負責的事，交給負責的成員，不要自己做。' if role is not lead else '你負責拆解目標、分派工作、整合成果與追蹤進度；各領域的專業工作交給負責的成員。']
    return '\n'.join(lines)[:10000]


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
            try: provider, model = pick_auto(store, '請分析並規劃', plan=True)[0][0] if store.data.get('autoStatus') and auto_allowed(store) else bot_model(store, {})
            except ValueError: provider, model = bot_model(store, {})
            helper = dict(id=ID(), botId=carrier['id'], messageId='', status='running', content='', createdAt=NOW(), toolCalls=[], approvals=[], plan=True, noResume=True, internal='team')
            store.data['jobs'].append(helper); bot = copy.deepcopy(carrier)
        try: self._run_attempt(helper['id'], TEAM_ASK % TEAM_MEMBERS + goal.strip(), provider, model, bot, inventory, True)
        finally:
            with store.lock: store.data['jobs'][:] = [j for j in store.data['jobs'] if j['id'] != helper['id']]
        if helper.get('status') != 'completed' or not (helper.get('content') or '').strip(): raise RuntimeError(str(helper.get('error') or '模型沒有回覆，請再試一次。')[:300])
        return dict(parse_team(helper['content'], existing), goal=goal.strip())

    def create_team(self, body):
        """Lock held. Makes every Bot and the group, or nothing at all. Started by the user in the window, so it is not an approval."""
        store = self.store; goal = _team_text(body.get('goal'), 2000); team = _team_text(body.get('team'), 30)
        roles = body.get('roles')
        if not team or not goal or not isinstance(roles, list): raise ValueError('團隊資料不完整。')
        taken = {b['name'].strip().lower() for b in store.data['bots']}; cleaned = []
        for raw in roles:
            role = clean_team_role(raw, set())
            if not role: raise ValueError('每個角色都要有名稱、職稱和負責的事。')
            if role['name'].lower() in taken: raise ValueError('已經有名為「%s」的 Bot，請改一個名稱。' % role['name'])
            taken.add(role['name'].lower()); cleaned.append(role)
        if not 1 + TEAM_MEMBERS[0] <= len(cleaned) <= 1 + TEAM_MEMBERS[1]: raise ValueError('團隊要有一位統籌和 %d 到 %d 位成員。' % TEAM_MEMBERS)
        if any(g['name'].strip().lower() == team.lower() for g in store.data['groups']): raise ValueError('已經有同名的群組，請改一個團隊名稱。')
        lead, bots, at = cleaned[0], [], len(store.data['bots'])
        for i, role in enumerate(cleaned):
            bot = dict(id=ID(), name=role['name'], color=colors_for(at + i), shape=str((at + i) % 13), instructions='', persona='', provider=AUTO, model='', pinned=False, section=team, messages=[], enabledSkills=[], enabledMcp=[], allowCommands=True, isAdmin=False)
            update(bot, dict(name=role['name'], jobTitle=role['jobTitle'], persona=role['persona'], instructions=team_instructions(role, team, goal, lead, cleaned)), 'bot')
            ensure_chats(bot); bots.append(bot)
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
        return dict(group=group, bots=[dict(id=b['id'], name=b['name']) for b in bots])
