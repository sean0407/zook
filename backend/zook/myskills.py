# Skills written on the Skills page (#306), and a connector's first test right after it is added (#303).
# Loaded by backend/server.py into one shared namespace.
#
# A Skill written here is an ordinary Zook Skill: one SKILL.md in Zook's own Skill folder, so every Bot and every CLI gets it the
# same way as a template (inventory_for -> shared_skill_ids -> zook_read_skill). It holds text only, never a program: what a Bot
# does after reading it still goes through the same approval as anything else it does.
SKILL_NAME_MAX, SKILL_ABOUT_MAX, SKILL_BODY_MAX = 80, 500, 20000


def _skill_text(body):
    """(name, description, body) checked. Name and description are one line each, as SKILL.md's header needs them."""
    name, about, text = body.get('name'), body.get('description'), body.get('body')
    if not isinstance(name, str) or not name.strip(): raise ValueError('請輸入 Skill 名稱。')
    if not isinstance(about, str) or not about.strip(): raise ValueError('請用一句話寫出這個 Skill 能做什麼。')
    if not isinstance(text, str) or not text.strip(): raise ValueError('請寫下 Skill 的內容。')
    name, about = name.strip(), about.strip()
    if len(name) > SKILL_NAME_MAX: raise ValueError('名稱最多 %d 個字。' % SKILL_NAME_MAX)
    if len(about) > SKILL_ABOUT_MAX: raise ValueError('說明最多 %d 個字。' % SKILL_ABOUT_MAX)
    if len(text) > SKILL_BODY_MAX: raise ValueError('內容最多 %d 個字。' % SKILL_BODY_MAX)
    for value, what in ((name, '名稱'), (about, '說明')):
        if '\n' in value or '\r' in value or '---' in value: raise ValueError('%s只能寫一行，也不能有「---」。' % what)
    return name, about, text.strip('\n')


def _skill_body(path):
    """The text of a SKILL.md after its header."""
    try: text = path.read_text(encoding='utf-8', errors='replace')
    except OSError: return ''
    parts = text.split('---', 2) if text.startswith('---') else []
    return parts[2].lstrip('\n') if len(parts) == 3 else text


def _skill_write(path, name, about, body):
    """Only a name and a description in the header: a Skill saved here never carries other header fields (allowed tools and the like)."""
    path.write_text('---\nname: %s\ndescription: %s\n---\n\n%s\n' % (name, about, body), encoding='utf-8')


def _skill_clash(store, name, own=None):
    """Lock held. Another Skill already has this name, apart from upper and lower case (#288)."""
    if any(same_name(x['name']) == same_name(name) and x['id'] != own for x in store.data['skills']): raise ValueError('已經有同名的 Skill（大小寫不同也算同名）。')


def _editable_skill(store, record_id):
    with store.lock: record = copy.deepcopy(next((x for x in store.data['skills'] if x['id'] == record_id), None))
    if not record: raise LookupError('找不到這個 Skill。')
    if record.get('originPath'): raise ValueError('這個 Skill 是從其他工具匯入的，會跟著原來源更新，不能在這裡編輯。')
    return record


def custom_skill_add(store, body):
    name, about, text = _skill_text(body)
    home = skills_home(store)
    with store.lock:
        _skill_clash(store, name)
        folder = skill_folder(name if re.search(r'[A-Za-z0-9]', name) else 'my-skill', {x['folder'].lower() for x in store.data['skills']})
        target = home / folder; target.mkdir(mode=0o700)
        _skill_write(target / 'SKILL.md', name, about, text)
        record = dict(id=ID(), name=name, folder=folder, origin='custom')
        store.data['skills'].append(record); store.save()
    return record


def custom_skill_read(store, record_id):
    record = _editable_skill(store, record_id)
    path = store.dir / 'skills' / record['folder'] / 'SKILL.md'
    name, about = skill_title(path.parent, record['name'])
    body = _skill_body(path)
    return dict(id=record['id'], name=name, description=about, body=body)


def custom_skill_edit(store, record_id, body):
    record = _editable_skill(store, record_id)
    name, about, text = _skill_text(body)
    path = store.dir / 'skills' / record['folder'] / 'SKILL.md'
    with store.lock:
        _skill_clash(store, name, record['id'])
        _skill_write(path, name, about, text)
        for x in store.data['skills']:
            if x['id'] == record['id']: x['name'] = name
        store.save()
    return dict(id=record['id'], name=name)


def custom_skill_route(store, method, rest, body):
    """(status, reply) for POST /api/skills, GET and PATCH /api/skills/<id>."""
    try:
        if not rest and method == 'POST': return 201, custom_skill_add(store, body)
        if len(rest) == 1 and method == 'GET': return 200, custom_skill_read(store, rest[0])
        if len(rest) == 1 and method == 'PATCH': return 200, custom_skill_edit(store, rest[0], body)
    except LookupError as exc: return 404, {'error': str(exc)}
    return 404, {'error': '找不到資源。'}


_connector_revs, _revs_lock = {}, threading.Lock()


def connector_touch(connector_id):
    """Count a change to what a connector connects with: its settings, a key replaced in the Keychain (same id), an account signed
    in, switched or signed out, removal. A sign-in renewed while the connector is being used or tested is not counted."""
    with _revs_lock: _connector_revs[connector_id] = _connector_revs.get(connector_id, 0) + 1


def shared_touch(before, after):
    """A connector switched on or off for every Bot is a change too: a test running meanwhile does not switch it back (#303)."""
    for ident in set(before or []) ^ set(after or []):
        if isinstance(ident, str) and ident.startswith('zook:'): connector_touch(ident[5:])


def connector_keys_write(record, secret, more):
    """Write a connector's new keys under new Keychain ids and point the record at them; returns the ids they replace, to delete
    once the record is saved. A key is never overwritten in place, so a test reading the old one cannot be mistaken for the new.
    If one cannot be written, the ones already written are deleted and the record is left as it was."""
    made, old, plan = [], [], ([('', secret)] if secret else []) + sorted(more.items())
    try:
        for key, value in plan:
            ident = ID(); secret_set(ident, value); made.append((key, ident))
    except Exception:
        for _, ident in made: secret_delete(ident)
        raise
    for key, ident in made:
        if key: old.append(record['moreSecrets'].get(key)); record['moreSecrets'][key] = ident
        else: old.append(record.get('secretId')); record['secretId'] = ident
    if not secret and not record['secretName'] and record.get('secretId'): old.append(record['secretId']); record['secretId'] = ''  # the key was removed
    return [x for x in old if x]


def connector_rev(connector_id):
    with _revs_lock: return _connector_revs.get(connector_id, 0)


def connector_first_test(store, ident, turn_on=True):
    """Test a connector just added, or just signed in to. It is switched on for every Bot only when it worked and nothing about it
    changed while it was tested (#303); otherwise it stays off and the reason goes back with the answer.
    Never called with store.lock held: starting a program or reaching a service takes time."""
    cid = ident.split(':', 1)[1] if ident.startswith('zook:') else ''
    exists = lambda: any(c['id'] == cid for c in store.data['connectors'])
    with store.lock: rev = connector_rev(cid); there = exists()  # read before the test reads its settings and keys
    try: test = runtime_module().test_connection(ident, inventory_for(store, testing=ident))
    except Exception as exc: test = {'status': 'error', 'toolCount': 0, 'error': str(exc)[:300] or '連線失敗。'}
    on = bool(turn_on) and test.get('status') == 'ready'
    if on:
        with store.lock:
            on = there and exists() and connector_rev(cid) == rev  # any change in between, even one changed back, means it was not what was tested
            if on: st = store.data['settings']; st['sharedMcp'] = list(dict.fromkeys((st.get('sharedMcp') or []) + [ident])); store.save()
        if not on: test = dict(test, changed=True, error='測試時的設定已經被修改或移除，先維持關閉。請再測試一次。')
    return on, test
