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
