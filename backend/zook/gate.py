# The 「先問」 gate for a CLI's own tools, as Zook sets it up for each reply. Loaded by backend/server.py into one shared namespace.
# The checking itself is backend/zook_gate.py (run by Claude as a PreToolUse hook, and by cursor_guard.py for Cursor); what it asks
# arrives at the reply's worker as method 'gate' (handler.py) and becomes an approval card (RuntimeSession.gate in runtime.py).
# Every built-in tool that touches files or runs commands; reads too, because keys and passwords are a boundary.
CLAUDE_GATED_TOOLS = 'Bash|Read|Write|Edit|MultiEdit|NotebookEdit|Glob|Grep|Task|Agent'
GATE_NOTE = ('\n安全邊界：刪除檔案、對外送出（寄信、發文、付款、上傳、git push）、動到金鑰密碼帳號、安裝軟體或改系統設定、改動 Zook 或 CLI 的設定與掛鉤時，'
             'Zook 會先問使用者，其他動作直接做，不必先問。看不懂的指令（例如用變數當指令、內嵌程式碼刪檔或連網）也會先問。'
             '被拒絕就停下來告訴使用者，不要改用別的方法做同一件事，也不要把這類動作寫進腳本檔再執行來避開詢問。')
# Where an administrator's policy for Claude Code lives on a Mac. A policy that keeps only its own hooks, or turns hooks off, would
# silently drop Zook's gate, so Zook then gives Claude no built-in tool (checked at each reply; Zook's own tools still work).
CLAUDE_MANAGED = pathlib.Path('/Library/Application Support/ClaudeCode')


def gate_module():
    """backend/zook_gate.py, for the summaries the activity record keeps of a CLI's commands."""
    if 'module' not in _GATE_MODULE:
        spec = importlib.util.spec_from_file_location('zook_gate_for_records', str(pathlib.Path(__file__).with_name('zook_gate.py')))
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); _GATE_MODULE['module'] = module
    return _GATE_MODULE['module']


_GATE_MODULE = {}


def gate_python():
    return GROK_PYTHON if os.path.exists(GROK_PYTHON) else sys.executable


CLAUDE_MDM = ('/Library/Managed Preferences/%s/com.anthropic.claudecode.plist', '/Library/Managed Preferences/com.anthropic.claudecode.plist')


def _policy_blocks_hooks(policy):
    """A policy that keeps only its own hooks, or turns hooks off. A configuration profile may hold the settings as JSON text."""
    if isinstance(policy, dict) and isinstance(policy.get('Settings'), str):
        try: policy = dict(policy, **json.loads(policy['Settings']))
        except ValueError: return True
    elif isinstance(policy, dict) and isinstance(policy.get('Settings'), dict): policy = dict(policy, **policy['Settings'])
    return not isinstance(policy, dict) or policy.get('disableAllHooks') is True or policy.get('allowManagedHooksOnly') is True


def claude_hooks_allowed(folder=None, env=None):
    """Whether Claude will run the hook Zook passes with --settings, as far as this Mac can tell. Checked: the policy files in
    /Library/Application Support/ClaudeCode, a configuration profile (device or user) for com.anthropic.claudecode, and the copy of
    the organization's server policy Claude keeps in its settings folder. A policy that cannot be read counts as one that blocks.
    A server policy Claude has not saved yet (its very first start) cannot be seen beforehand."""
    folder = pathlib.Path(os.environ.get('ZOOK_CLAUDE_MANAGED_DIR') or folder or CLAUDE_MANAGED)
    files = ([folder / 'managed-settings.json'] if (folder / 'managed-settings.json').exists() else []) + (sorted((folder / 'managed-settings.d').glob('*.json')) if (folder / 'managed-settings.d').is_dir() else [])
    config = pathlib.Path((env or {}).get('CLAUDE_CONFIG_DIR') or os.environ.get('ZOOK_CLAUDE_CONFIG_DIR') or pathlib.Path.home() / '.claude')
    files += [f for f in (config / 'remote-settings.json', config / 'policy-limits.json') if f.exists()]
    for f in files:
        try: policy = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError): return False
        if _policy_blocks_hooks(policy): return False
    mdm = os.environ.get('ZOOK_CLAUDE_MDM')
    plists = [pathlib.Path(p) for p in (json.loads(mdm) if mdm else [CLAUDE_MDM[0] % getpass.getuser(), CLAUDE_MDM[1]])]
    for plist in plists:
        if not plist.exists(): continue
        try: policy = json.loads(subprocess.run(['/usr/bin/plutil', '-convert', 'json', '-o', '-', '--', str(plist)], capture_output=True, timeout=5, check=True).stdout)
        except (OSError, ValueError, subprocess.SubprocessError): return False
        if _policy_blocks_hooks(policy): return False
    return True


def claude_gate_settings(wait):
    """Claude's --settings: a PreToolUse hook on its own tools. onFailure "block" (Claude Code 2.1.330 and later) makes a hook that
    crashes, times out or is cut off a refusal; a crash of the check also exits 2. The hook waits longer than the check itself
    (which gives up after `wait` seconds and refuses), and the check answers allow or deny for every call."""
    script = str(pathlib.Path(__file__).with_name('zook_gate.py'))  # __file__ is backend/server.py in this namespace
    command = '%s %s || exit 2' % (shlex.quote(gate_python()), shlex.quote(script))
    hook = {'type': 'command', 'command': command, 'timeout': int(wait) + 60, 'onFailure': 'block'}
    start = {'type': 'command', 'command': command, 'timeout': 30}  # only leaves the sign that the hooks run (claude_gate_seen)
    return json.dumps({'hooks': {'PreToolUse': [{'matcher': CLAUDE_GATED_TOOLS, 'hooks': [hook]}], 'SessionStart': [{'hooks': [start]}]}}, ensure_ascii=False)


# The whole Mac only after the hook was seen running in this Claude setup (its settings folder): the hook leaves a mark (ZOOK_GATE_MARK)
# when Claude starts and before each tool. Until then, and again whenever Claude used a tool without leaving it, a Claude Bot works in
# its workspace. A policy that turns hooks off for the first time in the very reply that starts cannot be seen in advance.
def claude_gate_key(env):
    return str((env or {}).get('CLAUDE_CONFIG_DIR') or pathlib.Path.home() / '.claude')


def claude_gate_mark(store, env):
    folder = store.dir / 'tools' / 'claude-gate'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / hashlib.sha256(claude_gate_key(env).encode()).hexdigest()[:24]
    try: before = path.stat().st_mtime
    except OSError: before = 0
    return str(path), before


def claude_gate_seen(store, env):
    """Lock held. Whether Zook has seen its hook run in this Claude setup, and not seen a tool run without it since."""
    return (store.data.get('claudeGate') or {}).get(claude_gate_key(env)) is True


def claude_scope(store, provider, bot, scope, root, workspace):
    """(scope, folder) for a Claude reply: the whole Mac only once its hook was seen running in this Claude setup."""
    with store.lock: seen = claude_gate_seen(store, provider_env(provider, find_account(bot.get('account'), provider)))
    return (scope, root) if scope != 'full' or seen else ('workspace', workspace)


def claude_gate_env(store, env, tools, scope, root, workspace):
    """The hook's environment for this reply; returns the mark's time before it. Without the whole Mac, the hook checks every path
    against the folders (ZOOK_GATE_ROOTS); a reply that only reads what was attached never gets an allow (ZOOK_GATE_DEFER)."""
    mark, before = claude_gate_mark(store, env); env['ZOOK_GATE_MARK'] = mark
    if not (tools and scope == 'full'): env['ZOOK_GATE_ROOTS'] = json.dumps([str(root), str(workspace)] if tools else [str(pathlib.Path(workspace) / 'attachments')])
    if not tools: env['ZOOK_GATE_DEFER'] = '1'
    return before


def claude_gate_after(store, env, mark, before, used_tools):
    """After a Claude reply: the mark proves the hook ran; a built-in tool that ran without it means it did not."""
    with store.lock: return _claude_gate_after(store, env, mark, before, used_tools)


def _claude_gate_after(store, env, mark, before, used_tools):
    try: ran = os.stat(mark).st_mtime > before
    except OSError: ran = False
    seen = store.data.setdefault('claudeGate', {}); key = claude_gate_key(env)
    if ran: seen[key] = True
    elif used_tools:
        seen[key] = False
        log_activity(store, 'tool', 'Claude 用了內建工具，但 Zook 的安全檢查沒有執行（可能被管理政策關掉）。之後 Claude 的 Bot 先只在工作資料夾裡做事。', by='Zook')
    return ran


def gate_access_note(note, kind):
    """For Claude and Cursor, which ask through the gate: the boundaries instead of 「ask before deleting」, so the card is the one question."""
    if kind not in GATED_KINDS: return note
    return note.replace('刪除或覆寫既有檔案前，先向使用者確認。', '') + GATE_NOTE.strip() + ' '


def local_migrate(store):
    """Once per data folder, at start:
    - Claude and Cursor Bots from before the gate get this Mac's permission to use the whole Mac behind it (gateFull, never synced);
    - local scripts are switched off for every Bot: the switch left the edit screen, so a Bot cannot stay open to scripts unseen.
      The zook-cli command itself stays; it reaches only a Bot whose scripts is turned on again on purpose."""
    with store.lock: _local_migrate(store)


def _local_migrate(store):
    settings = store.data['settings']; changed = False
    if not settings.get('gateFullSet'):
        for bot in store.data['bots']: set_gate_full(bot)
        settings['gateFullSet'] = True; changed = True
    if not settings.get('scriptsOff'):
        for bot in store.data['bots'] + (store.data.get('deletedBots') or []):
            if bot.get('scripts') is not False: bot['scripts'] = False
        settings['scriptsOff'] = True; changed = True
    if changed: store.save()


def worker_gate(server, conn, worker, job_id, params):
    """The worker's 'gate' request (handler.py): ask on the approval card while the CLI's hook waits. When the hook stops waiting
    (its CLI gave up or ended it), the card is taken down rather than left for an answer that can no longer reach anything."""
    call_id, done = uuid.uuid4().hex, threading.Event()
    def watch():
        while not done.wait(1):
            try:
                readable = select.select([conn], [], [], 0)[0]
                gone = bool(readable) and not conn.recv(1, socket.MSG_PEEK)
            except (OSError, ValueError): gone = True
            if gone: server.withdraw(job_id, call_id); return
    threading.Thread(target=watch, daemon=True).start()
    try: return worker['session'].gate(params, call_id)
    finally: done.set()
