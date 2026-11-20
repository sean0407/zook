# Cursor through its official CLI, `cursor-agent -p`. Loaded by backend/server.py into one shared namespace.
#
# Checked on the real CLI (cursor-agent 2026.11.19):
#   - `-p --output-format stream-json` prints one JSON event per line: system/init (session_id), assistant messages, tool_call
#     started/completed, and one result event with usage {inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens}.
#     Its `result` text joins everything the agent said, so the reply is what it said after its last tool call.
#     With --stream-partial-output the words also come as small assistant events that carry timestamp_ms.
#   - The message is read from stdin. `--resume <id>` continues a chat, and quietly starts a new one when the id is unknown;
#     chats are kept in <CURSOR_CONFIG_DIR>/chats/<hash>/<id>, so Zook checks there first.
#   - CURSOR_CONFIG_DIR points at a settings folder of Zook's own; the sign-in is not kept there and still works.
#   - Without --force, a run like this refuses web search, web fetch and deletes, because nobody is there to approve them.
#     So Zook runs it with --force and limits it itself: a preToolUse hook (cursor_guard.py, fail-closed) in the Bot's workspace
#     allows each file tool only inside the Bot's folders, and commands and subagents only when allowed. Cursor's permission
#     rules cannot do this: a deny always wins over an allow.
#   - Web search and web fetch do not pass through hooks. CURSOR_FORCED_SHELL_EGRESS=1 turns both off (and network use from
#     its shell), which is what Zook does when 上網搜尋 is off.
#   - An MCP server does not inherit the CLI's environment; `${env:NAME}` in mcp.json passes Zook's worker address and token on.
CURSOR_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._\[\]=,-]{0,120}')


def cursor_config_dir(base):
    folder = pathlib.Path(base) / 'tools' / 'cursor-config'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def cursor_has_session(base, session):
    """Whether Cursor still has this chat. It would otherwise start a new one under the same id without saying so."""
    if not re.fullmatch(r'[A-Za-z0-9-]{8,80}', str(session or '')): return False
    return any(p.is_dir() for p in (cursor_config_dir(base) / 'chats').glob('*/' + session))


def cursor_rule(native, planning, scope, root, workspace, features):
    """What the Bot may reach in this reply, for cursor_guard.py. None means anywhere."""
    attachments = str(pathlib.Path(workspace) / 'attachments')
    if planning: return dict(read=[str(root), str(workspace)], write=[], shell=False, task=False)
    if not native: return dict(read=[attachments], write=[], shell=False, task=False)  # 謹慎: only Zook's tools, and what was attached
    if scope == 'full': return dict(read=None, write=None, shell=True, task='multi' in (features or []))
    folders = [str(root), str(workspace)] if scope == 'folder' else [str(workspace)]
    return dict(read=folders, write=folders, shell=False, task='multi' in (features or []))


def prepare_cursor_folder(workspace, adapter, tools):
    """The Bot's workspace gets Cursor's project settings: Zook's MCP server and the guard hook. Nothing secret is written."""
    folder = pathlib.Path(workspace) / '.cursor'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    python = GROK_PYTHON if os.path.exists(GROK_PYTHON) else sys.executable
    guard = str(pathlib.Path(adapter).with_name('cursor_guard.py'))
    hooks = {'version': 1, 'hooks': {'preToolUse': [{'command': '%s %s' % (shlex.quote(python), shlex.quote(guard)), 'failClosed': True}]}}
    servers = {'zook': {'command': python, 'args': [adapter], 'env': {k: '${env:%s}' % k for k in ('ZOOK_WORKER_URL', 'ZOOK_WORKER_TOKEN', 'ZOOK_TOOL_WAIT')}}} if tools else {}
    if folder.is_symlink(): raise RuntimeError('Bot 工作資料夾裡的 .cursor 被換成了連結，為了安全，Cursor 這次不執行。')
    for name, value in (('hooks.json', hooks), ('mcp.json', {'mcpServers': servers})):
        target, temp = folder / name, folder / ('.%s.zook-new' % name)
        if os.path.lexists(str(temp)): os.unlink(str(temp))
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never follows a link someone left there
        with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(json.dumps(value, ensure_ascii=False, indent=2))
        os.replace(str(temp), str(target))  # replaces a link itself, never what it points to


def cursor_args(binary, model, planning, scope, root, web, streaming, resume):
    args = [binary, '-p', '--output-format', 'stream-json', '--trust', '--approve-mcps', '--force']
    if streaming: args.append('--stream-partial-output')
    if planning: args += ['--mode', 'plan']
    if scope == 'folder': args += ['--add-dir', str(root)]
    if scope == 'full' and not planning: args += ['--sandbox', 'disabled']
    if model and CURSOR_MODEL.fullmatch(model): args += ['--model', model]
    if resume: args += ['--resume', resume]
    return args


def cursor_env(base, env, rule, web):
    extra = dict(CURSOR_CONFIG_DIR=str(cursor_config_dir(base)), ZOOK_CURSOR_GUARD=json.dumps(rule, ensure_ascii=False), NO_OPEN_BROWSER='1')
    out = dict(env, **extra)
    if not web: out['CURSOR_FORCED_SHELL_EGRESS'] = '1'
    else: out.pop('CURSOR_FORCED_SHELL_EGRESS', None)
    return out


def cursor_error(text):
    low = str(text or '').lower()
    if 'not logged in' in low or 'not authenticated' in low or 'authentication required' in low or 'please log in' in low or 'run `agent login`' in low:
        return 'Cursor 還沒登入，請到「各模型使用量」按登入。'
    if 'usage limit' in low or 'rate limit' in low or 'quota' in low or 'out of requests' in low:
        return 'Cursor 這個帳號的額度用完了，請換一個模型或改用其他 CLI。'
    return ''


def cursor_models(binary, base):
    done = subprocess.run([binary, 'models'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env=dict(os.environ, CURSOR_CONFIG_DIR=str(cursor_config_dir(base)), NO_OPEN_BROWSER='1'), timeout=30)
    found = []
    for line in ANSI.sub('', done.stdout.decode('utf-8', 'replace')).splitlines():
        m = re.match(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]{0,80})\s+-\s+(.+?)\s*$', line)
        if m and CURSOR_MODEL.fullmatch(m.group(1)):
            name = re.sub(r'[​‌‍]+', '', m.group(2)).replace('(current, default)', '').strip()
            found.append(dict(id=m.group(1), name=name if m.group(1) != 'auto' else 'Auto（Cursor 自動選）', source='cli'))
    return found


def cursor_status(binary, env):
    done = subprocess.run([binary, 'status'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=dict(env, NO_OPEN_BROWSER='1'), timeout=20)
    text = ANSI.sub('', done.stdout.decode('utf-8', 'replace'))
    found = re.search(r'Logged in as\s+(\S+@\S+)', text)
    if found: return 'logged_in', found.group(1)
    if re.search(r'not logged in|not authenticated|log in', text, re.I): return 'not_logged_in', ''
    return 'unknown', ''
