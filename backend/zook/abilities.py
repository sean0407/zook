# What each CLI can do in Zook, and whether the installed version still has what Zook relies on. Loaded by backend/server.py into one shared namespace.
ABILITIES = (('chat', '對話'), ('tools', 'Zook 工具'), ('images', '看圖'), ('plan', '先規劃'), ('effort', '思考強度'), ('resume', '原生對話'), ('quota', '額度讀取'))

# For each kind of CLI: ability -> the help screens and the option each must still list. An ability that is not listed is not offered.
_HELP = ('--help',)
_EXEC = ('exec', '--help')
ABILITY_CHECKS = {
    'codex': dict(chat=[(_EXEC, '--json'), (_EXEC, '--skip-git-repo-check')], tools=[(_EXEC, '--config')], images=[(_EXEC, '--image')], plan=[(_EXEC, '--sandbox')],
                  effort=[(_EXEC, '--config')], resume=[(('exec', 'resume', '--help'), 'SESSION_ID')], quota=[(('app-server', '--help'), '--listen')]),
    'claude': dict(chat=[(_HELP, '--print'), (_HELP, '--output-format')], tools=[(_HELP, '--mcp-config'), (_HELP, '--allowedTools')], images=[(_HELP, '--tools')], plan=[(_HELP, '--tools')],
                   effort=[(_HELP, '--effort')], resume=[(_HELP, '--resume'), (_HELP, '--session-id')], quota=[(_HELP, '--output-format')]),
    'grok': dict(chat=[(_HELP, '--prompt-file'), (_HELP, '--output-format')], tools=[(_HELP, '--allow')], images=[(_HELP, '--prompt-file')], plan=[(_HELP, '--deny')],
                 effort=[(_HELP, '--reasoning-effort')], resume=[(_HELP, '--resume')]),
    'antigravity': dict(chat=[(_HELP, '--input-format'), (_HELP, '--output-format')], tools=[(_HELP, '--settings')], images=[(_HELP, '--settings')], plan=[(_HELP, '--mode')],
                        effort=[(_HELP, '--effort')], resume=[(_HELP, '--conversation')], quota=[(_HELP, '--print')]),
}
_ability_lock = threading.Lock()


def check_abilities(path, kind):
    """Which abilities this CLI's help screens still support. Costs no model quota. None when the help cannot be read."""
    screens = {}
    def screen(args):
        if args not in screens:
            done = subprocess.run([path] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
            screens[args] = ANSI.sub('', done.stdout.decode('utf-8', 'replace')) if done.returncode == 0 else ''
        return screens[args]
    missing = {}
    try:
        for ability, needs in ABILITY_CHECKS[kind].items():
            gone = []
            for args, option in needs:
                text = screen(args)
                if not text.strip(): return None
                if option not in text: gone.append(option)
            if gone: missing[ability] = gone
    except (OSError, subprocess.SubprocessError): return None
    return missing


def ability_report(store, provider):
    """The saved check for the installed version, running it once whenever the version changes."""
    kind, path = provider_kind(provider), find_cli(provider)
    if kind not in ABILITY_CHECKS or not path: return None
    version = (provider_version(provider) or {}).get('current') or ''
    with store.lock: saved = (store.data.get('abilityChecks') or {}).get(provider)
    if saved and saved.get('version') == version: return saved
    with _ability_lock:
        missing = check_abilities(path, kind)
        if missing is None: return saved
        report = dict(version=version, missing=missing, checkedAt=NOW())
        with store.lock: store.data.setdefault('abilityChecks', {})[provider] = report; store.save()
    return report


def ability_on(store, provider, ability):
    """False only when this version was checked and no longer has what the ability needs."""
    with store.lock: saved = (store.data.get('abilityChecks') or {}).get(provider) or {}
    return ability not in (saved.get('missing') or {})


def ability_view(store, provider):
    """For the model's card: every ability, and what changed in this version."""
    kind = provider_kind(provider); offered = ABILITY_CHECKS.get(kind)
    report = ability_report(store, provider) if offered else None
    missing = (report or {}).get('missing') or {}
    if not offered: return dict(abilities=[dict(id='chat', name='對話', state='on')], changed=[])
    items = [dict(id=key, name=name, state='broken' if key in missing else 'on') for key, name in ABILITIES if key in offered]
    return dict(abilities=items, changed=[name for key, name in ABILITIES if key in missing])


# Special features a Bot can turn on. Each was tried on the real CLI: browser control is not offered because none could complete it,
# and Antigravity's image generation often ended in a capacity error before it could reply.
FEATURES = dict(multi=('codex', 'claude', 'grok'), image=('codex', 'grok'))
FEATURE_NAMES = dict(multi='多代理協作', image='圖片生成')
FEATURE_NEEDS_WHOLE_MAC = dict(image=('grok',))  # these only finish the job with full access


def feature_support(kind):
    return [name for name, kinds in FEATURES.items() if kind in kinds]


def active_features(bot, kind, native, planning, scope):
    """The features this reply may use. Never in 謹慎 or 先規劃."""
    defaults = (_active['data'].get('settings') or {}).get('features') or {}
    chosen = dict(defaults, **(bot.get('features') if isinstance(bot.get('features'), dict) else {}))  # the Bot's own choice wins over the default in 設定
    if not native or planning: return []
    return [name for name in feature_support(kind) if chosen.get(name) is True and (kind not in FEATURE_NEEDS_WHOLE_MAC.get(name, ()) or scope == 'full')]


def feature_note(features, kind):
    note = '\n你可以派出子代理分工處理適合平行的工作。' if 'multi' in features else SUBAGENT_NOTE
    if 'image' in features: note += '\n使用者要圖片時，用你的 AI 圖片生成工具產生，存到目前資料夾並告訴使用者檔名。'
    elif kind == 'grok': note += '\n不要使用 AI 圖片生成工具。'
    return note


def feature_events(kind, text, features, folder, started):
    """Activity entries for the special features a reply really used."""
    used = []
    if 'multi' in features:
        for line in str(text or '').splitlines():
            try: event = json.loads(line) if line.strip().startswith('{') else {}
            except ValueError: continue
            item = event.get('item') if isinstance(event.get('item'), dict) else {}
            blocks = (event.get('message') or {}).get('content') if isinstance(event.get('message'), dict) else None
            if item.get('type') == 'collab_tool_call' or event.get('toolName') == 'spawn_subagent' or any(isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') in ('Agent', 'Task') for b in blocks or []):
                used.append('multi'); break
    if 'image' in features:
        try:
            with os.scandir(str(folder)) as found:
                if any(e.is_file() and pathlib.Path(e.name).suffix.lower() in IMAGE_TYPES and e.stat().st_mtime >= started for e in found): used.append('image')
        except OSError: pass
    return [dict(name='zook_feature', category='read', arguments=dict(feature=FEATURE_NAMES[x])) for x in used]
