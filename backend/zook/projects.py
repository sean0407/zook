# 專案: a named set of Bots, groups and knowledge with a shared folder and note. Nothing here changes what a Bot may reach.
# Loaded by backend/server.py into one shared namespace.
MAX_PROJECTS = 50


def project_fields(store, body, project):
    """Checked changes for one project. A Bot or group belongs to at most one project."""
    if 'name' in body:
        name = body['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 60: raise ValueError('請輸入 1–60 字的專案名稱。')
        if any(p['name'] == name.strip() and p['id'] != project['id'] for p in store.data['projects']): raise ValueError('已經有同名的專案。')
        project['name'] = name.strip()
    if not project.get('name'): raise ValueError('請輸入 1–60 字的專案名稱。')
    if 'note' in body:
        if not isinstance(body['note'], str) or len(body['note']) > 4000: raise ValueError('說明不能超過 4000 字。')
        project['note'] = body['note'].strip()
    if 'folder' in body:
        folder = body['folder']
        if not isinstance(folder, str) or len(folder) > 1000: raise ValueError('資料夾無效。')
        if folder.strip():
            chosen = pathlib.Path(folder.strip()).expanduser()
            if not chosen.is_absolute() or not chosen.is_dir(): raise ValueError('請選擇一個存在的資料夾。')
            folder = str(chosen.resolve())
        project['folder'] = folder.strip()
    for key, kind in (('botIds', 'bots'), ('groupIds', 'groups'), ('knowledgeIds', 'knowledge')):
        if key in body:
            ids = body[key]
            if not isinstance(ids, list) or len(ids) > 500 or any(not isinstance(x, str) or not store.find(kind, x) for x in ids): raise ValueError('所選的項目不存在。')
            project[key] = list(dict.fromkeys(ids))
    return project


def save_project(store, project):
    """Put the project in place and take its Bots and groups out of any other project."""
    others = [p for p in store.data['projects'] if p['id'] != project['id']]
    for other in others:
        for key in ('botIds', 'groupIds'): other[key] = [x for x in other.get(key) or [] if x not in project.get(key, [])]
    store.data['projects'] = others + [project] if not any(p['id'] == project['id'] for p in store.data['projects']) else [project if p['id'] == project['id'] else p for p in store.data['projects']]


def forget_in_projects(store, key, item_id):
    for project in store.data.get('projects') or []:
        if item_id in (project.get(key) or []): project[key].remove(item_id)


def project_of(store, bot_id=None, group_id=None):
    return next((p for p in store.data.get('projects') or [] if (bot_id and bot_id in (p.get('botIds') or [])) or (group_id and group_id in (p.get('groupIds') or []))), None)


def project_block(store, bot_id=None, group_id=None):
    """What a reply is told about its project. In a group, the group's project comes first."""
    project = (project_of(store, group_id=group_id) if group_id else None) or (project_of(store, bot_id=bot_id) if bot_id else None)
    if not project: return ''
    text = '\n你正在專案「%s」裡工作。' % project['name']
    if project.get('note'): text += '\n專案說明：' + project['note']
    if project.get('folder'): text += '\n專案資料夾：%s（能不能讀寫仍依你的存取範圍）。' % project['folder']
    return text


def bot_knowledge(store, bot, group_id=None):
    """Knowledge for a reply: shared and the Bot's own, plus what its project holds."""
    base = [x for x in store.data['knowledge'] if not x.get('botId') or x.get('botId') == bot['id']]
    project = (project_of(store, group_id=group_id) if group_id else None) or project_of(store, bot_id=bot['id'])
    extra = [x for x in store.data['knowledge'] if project and x['id'] in (project.get('knowledgeIds') or []) and x not in base]
    return (base + extra)[-10:]
