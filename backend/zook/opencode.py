# OpenCode through its official CLI, `opencode run`. Loaded by backend/server.py into one shared namespace.
#
# Checked on the real CLI (opencode 2.3.2):
#   - `opencode run --format json` prints one JSON event per line: step_start, text (part.text), tool events, step_finish
#     (part.tokens, part.cost) and error (error.type, error.message). The message is read from stdin.
#   - `--standalone` runs a private server for this run only; without it OpenCode starts a shared background service.
#   - `-s <session>` continues a conversation, and quietly starts a new one when that id does not exist; so Zook checks first
#     with `opencode session export <id>`, which fails with "Session not found".
#   - Settings come only from Zook: OPENCODE_CONFIG_DIR points at an empty folder of Zook's (the user's own
#     ~/.config/opencode is not read), project settings and Claude Code's files are turned off, and the run's settings
#     (Zook's tools, permissions) are given in OPENCODE_CONFIG_CONTENT.
#   - Free models need no sign-in. Their allowance is shared and small; when it runs out the error type is provider.free-limit.
# Permissions: OpenCode asks about anything no rule covers, and a run like this has nobody to answer, so every run starts
# with "deny everything" and then allows exactly what this Bot may do.
OPENCODE_FREE_FALLBACK = 'opencode/big-pickle'
_opencode_free = []  # the free models `opencode models` listed last


OPENCODE_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._:/#-]{1,120}')


def opencode_config_dir(base):
    """An empty settings folder of Zook's own (base: Zook's data folder)."""
    folder = pathlib.Path(base) / 'tools' / 'opencode-config'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def opencode_env(base, env):
    """The run's environment: nothing of the user's own OpenCode settings, no updates, no project files."""
    return dict(env, OPENCODE_CONFIG_DIR=str(opencode_config_dir(base)), OPENCODE_DISABLE_PROJECT_CONFIG='1', OPENCODE_DISABLE_CLAUDE_CODE='1',
                OPENCODE_DISABLE_CLAUDE_CODE_SKILLS='1', OPENCODE_DISABLE_CLAUDE_CODE_PROMPT='1', OPENCODE_DISABLE_AUTOUPDATE='1')


def opencode_permissions(native, planning, scope, root, web, tools, features, attachments=None):
    rules = [dict(action='*', resource='*', effect='deny')]
    allow = lambda action, resource='*': rules.append(dict(action=action, resource=resource, effect='allow'))
    if tools: allow('zook_*')  # Zook's own tools; Zook decides about each call
    if planning:
        for action in ('read', 'glob', 'grep'): allow(action)
    elif native:
        for action in ('read', 'glob', 'grep', 'edit'): allow(action)
        if scope == 'full': allow('shell'); allow('external_directory')
        elif scope == 'folder': allow('external_directory', str(root).rstrip('/') + '/*')
        if 'multi' in (features or {}): allow('subagent')
    if attachments: allow('read', str(attachments).rstrip('/') + '/*'); allow('external_directory', str(attachments).rstrip('/') + '/*')
    if web: allow('webfetch'); allow('websearch')
    return rules


def opencode_args(binary, model, native, planning, scope, root, web, tools, features, adapter, wait, resume, attachments=None):
    """(arguments, extra environment). The message itself goes in on stdin, so it never shows on a command line."""
    config = {'permissions': opencode_permissions(native, planning, scope, root, web, tools, features, attachments)}
    if tools:
        python = GROK_PYTHON if os.path.exists(GROK_PYTHON) else sys.executable
        config['mcp'] = {'servers': {'zook': {'type': 'local', 'command': [python, adapter], 'timeout': {'execution': int(wait) * 1000}}}}
    args = [binary, 'run', '--standalone', '--format', 'json', '--archived', '-m', model if model and OPENCODE_MODEL.fullmatch(model) else opencode_default_model()]
    if resume: args += ['-s', resume]
    return args, {'OPENCODE_CONFIG_CONTENT': json.dumps(config, ensure_ascii=False)}


def opencode_default_model():
    """A Bot with no model chosen gets a free one, never a paid one."""
    return _opencode_free[0] if _opencode_free else OPENCODE_FREE_FALLBACK


def opencode_has_session(base, binary, session, env):
    """Whether OpenCode still has this conversation. It would otherwise start a new one under the same id without saying so."""
    try: done = subprocess.run([binary, 'session', 'export', session, '--standalone'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=opencode_env(base, env), timeout=30)
    except (OSError, subprocess.SubprocessError): return False
    return done.returncode == 0


def opencode_error(error):
    """A plain explanation of the error OpenCode reported."""
    text = str(error or '')
    if 'free-limit' in text or 'FreeUsageLimit' in text: return 'OpenCode 免費模型的額度用完了（約一天後恢復），請換一個模型或改用其他 CLI。'
    if 'auth' in text.lower() and ('missing' in text.lower() or 'not' in text.lower()): return 'OpenCode 這個模型需要先登入或設定金鑰。'
    return ''


def opencode_free(model):
    """Free models: OpenCode's own (listed without any sign-in) and OpenRouter's :free ones."""
    return model.endswith(('-free', ':free')) or model == OPENCODE_FREE_FALLBACK


def opencode_models(binary, base):
    """Models from `opencode models`. Free ones first; the others are marked 付費."""
    done = subprocess.run([binary, 'models', '--standalone'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=opencode_env(base, os.environ.copy()), timeout=40)
    ids = [line.strip() for line in ANSI.sub('', done.stdout.decode('utf-8', 'replace')).splitlines() if OPENCODE_MODEL.fullmatch(line.strip())]
    free = [m for m in ids if opencode_free(m)]
    _opencode_free[:] = free
    return [dict(id=m, name=m.split('/', 1)[1] + '（免費）', source='cli', free=True) for m in free] + [dict(id=m, name=m.split('/', 1)[1] + '（付費）', source='cli', free=False) for m in ids if m not in free]


# OpenRouter, through OpenCode: the user's own key (kept in the Keychain) reaches OpenCode as OPENROUTER_API_KEY, and its models
# are named openrouter/<model>. The list comes from OpenRouter's public catalog, which needs no key and is sent nothing.
OPENROUTER_LIST = 'https://openrouter.ai/api/v1/models'
_openrouter_cache = {}


def openrouter_price(value):
    try: return float(value) * 1e6
    except (TypeError, ValueError): return None


def openrouter_models():
    """[{id, name, free, price}] with the free models first. Cached for an hour."""
    hit = _openrouter_cache.get('list')
    if hit and time.time() - hit[0] < 3600: return copy.deepcopy(hit[1])
    request = urllib.request.Request(OPENROUTER_LIST, headers={'User-Agent': 'Zook'})
    with urllib.request.urlopen(request, timeout=20) as response: data = json.loads(response.read(8 * 1024 * 1024).decode('utf-8', 'replace'))
    found = []
    for item in data.get('data') or []:
        mid = str(item.get('id') or '')
        if not OPENCODE_MODEL.fullmatch('openrouter/' + mid): continue
        pricing = item.get('pricing') if isinstance(item.get('pricing'), dict) else {}
        cost_in, cost_out = openrouter_price(pricing.get('prompt')), openrouter_price(pricing.get('completion'))
        free = mid.endswith(':free') or (cost_in == 0 and cost_out == 0)
        label = str(item.get('name') or mid)[:80]
        price = '' if free or cost_in is None or cost_out is None else '輸入 $%s／輸出 $%s 每百萬 token' % (('%.2f' % cost_in).rstrip('0').rstrip('.'), ('%.2f' % cost_out).rstrip('0').rstrip('.'))
        found.append(dict(id='openrouter/' + mid, name='OpenRouter · %s（%s）' % (label, '免費' if free else '付費 · ' + price), free=free, paid=not free, source='openrouter'))
    found.sort(key=lambda m: (not m['free'], m['name'].lower()))
    _openrouter_cache['list'] = (time.time(), found)
    return copy.deepcopy(found)


def opencode_has_openrouter(data):
    return any(a.get('provider') == 'opencode' and a.get('type') == 'key' for a in data.get('accounts') or [])
