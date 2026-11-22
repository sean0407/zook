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
# with a random word only this CLI was given, when Claude starts and before each tool. Until then, and again whenever Claude used a tool without leaving it, a Claude Bot works in
# its workspace. A policy that turns hooks off for the first time in the very reply that starts cannot be seen in advance.
def claude_gate_key(env):
    return str((env or {}).get('CLAUDE_CONFIG_DIR') or pathlib.Path.home() / '.claude')


def claude_gate_seen(store, env):
    """Lock held. Whether Zook has seen its hook run in this Claude setup, and not seen a tool run without it since."""
    return (store.data.get('claudeGate') or {}).get(claude_gate_key(env)) is True


def claude_scope(store, provider, bot, scope, root, workspace):
    """(scope, folder) for a Claude reply: the whole Mac only once its hook was seen running in this Claude setup."""
    with store.lock: seen = claude_gate_seen(store, provider_env(provider, find_account(bot.get('account'), provider)))
    return (scope, root) if scope != 'full' or seen else ('workspace', workspace)


def claude_gate_env(store, env, tools, scope, root, workspace, files=(), group_bot=None):
    """The hook's environment for this reply: a new random word and a new file for its mark (claude_gate_after), and, without the whole
    Mac, what it may reach (ZOOK_GATE_ROOTS). A reply that only reads what was attached gets this reply's own files, one by one (and
    its group's shared files), never the whole attachments folder, and never an allow (ZOOK_GATE_DEFER). Returns the mark to check."""
    folder = store.dir / 'tools' / 'claude-gate'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for old in folder.iterdir():  # marks of replies long done
        try:
            if time.time() - old.stat().st_mtime > 86400: old.unlink()
        except OSError: pass
    gate = [str(folder / secrets.token_hex(12)), secrets.token_hex(16), 0]
    env['ZOOK_GATE_MARK'], env['ZOOK_GATE_NONCE'] = gate[0], gate[1]
    if tools and scope != 'full': env['ZOOK_GATE_ROOTS'] = json.dumps([str(root), str(workspace)])
    if not tools:
        env['ZOOK_GATE_ROOTS'] = json.dumps([str(f) for f in files] + ([str(group_copy_folder(store, group_bot))] if group_bot else []))
        env['ZOOK_GATE_DEFER'] = '1'
    return gate


def claude_gate_after(store, env, gate, used_tools):
    """After a Claude reply. gate is [mark file, this CLI's word, how much of the file was read before]: only new lines with this CLI's
    own word prove its hook ran in this reply. A built-in tool that ran without them means it did not: the whole Mac is taken back."""
    try:
        with open(gate[0], 'rb') as f: f.seek(gate[2]); new = f.read(1 << 20)
    except OSError: new = b''
    gate[2] += len(new)
    ran = gate[1].encode() in new.split(b'\n')
    with store.lock:
        seen = store.data.setdefault('claudeGate', {}); key = claude_gate_key(env)
        if ran: seen[key] = True
        elif used_tools:
            seen[key] = False
            log_activity(store, 'tool', 'Claude 用了內建工具，但這一次 Zook 的安全檢查沒有執行（可能被管理政策關掉）。之後 Claude 的 Bot 先只在工作資料夾裡做事，直到再看到安全檢查生效。', by='Zook')
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


def native_record(job, w):
    """Lock held. The activity record of one built-in tool call the CLI reported: who allowed it (the user on an approval card, or
    nobody had to) and whether it worked, as two separate things."""
    ref = w.get('_ref'); status = w.get('status', 'completed')
    by_user = bool(ref) and any(a.get('name') == 'zook_native_gate' and a.get('status') == 'approved' and (a.get('arguments') or {}).get('toolUseId') == ref for a in job.get('approvals') or [])
    out = dict(dict(category='external_read'), id=ID(), createdAt=NOW(), **{k: v for k, v in w.items() if k != '_ref'})
    out.update(status=status, approvedBy='user' if by_user else 'auto', autoApproved=not by_user and status == 'completed')
    return out
