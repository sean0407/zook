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
# with a random word only this CLI was given (word:start when Claude starts, word:tool before each tool; only the latter counts). Until then, and again whenever Claude used a tool without leaving it, a Claude Bot works in
# its workspace. A policy that turns hooks off for the first time in the very reply that starts cannot be seen in advance.
def claude_gate_key(env):
    return str((env or {}).get('CLAUDE_CONFIG_DIR') or pathlib.Path.home() / '.claude')


def claude_gate_seen(store, env):
    """Lock held. Whether Zook has seen its hook run in this Claude setup, and not seen a tool run without it since."""
    return (store.data.get('claudeGate') or {}).get(claude_gate_key(env)) is True


def claude_scope(store, provider, bot, scope, root, workspace, job=None):
    """(scope, folder) for a Claude reply: the whole Mac only once its hook was seen checking a tool in this Claude setup. Until then
    the reply keeps every built-in tool, Bash too (job['gateProbe']), held to its workspace by the gate: the first tool it uses
    leaves the mark, and the next reply has the whole Mac."""
    with store.lock: seen = claude_gate_seen(store, provider_env(provider, find_account(bot.get('account'), provider)))
    if scope != 'full' or seen: return scope, root
    if job is not None: job['gateProbe'] = True
    return 'workspace', workspace


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
    if 'Bash' in tools and scope != 'full': env['ZOOK_GATE_SHELL'] = '1'  # commands too, with every path in them inside those folders
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
    ran = (gate[1] + ':tool').encode() in new.split(b'\n')  # a tool was checked; the start of Claude alone proves nothing
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
    if held_in_migrate(store): changed = True
    if not settings.get('scriptsOff'):
        for bot in store.data['bots'] + (store.data.get('deletedBots') or []):
            if bot.get('scripts') is not False: bot['scripts'] = False
        settings['scriptsOff'] = True; changed = True
    if changed: store.save()


# What this Mac allows a Bot. Never taken from a copy put back: a backup holds what was allowed then, maybe on another Mac.
LOCAL_GRANTS = ('access', 'accessFolder', 'permissionMode', 'isAdmin', 'scripts', 'gateFull', 'localLimit')
NOTHING_HERE = lambda: dict(settings={}, bots=[], deletedBots=[], customProviders=[], connectors=[])  # recover_data: nothing on this Mac to go by


def restore_keep_access(old, new):
    """A copy put back (backup_restore, recover_data). Nothing in it widens what this Mac allows or starts a program this Mac has not
    set up: the defaults in 設定, each Bot's 存取範圍, 主動性, 管理員 and local scripts, the custom CLIs, the connectors that are on and
    Claude's checked hook are what this Mac has now. A Bot this Mac has never had keeps to its workspace and 謹慎 (hold_in) until the
    user changes it here; a Bot whose model in the copy is another CLI than here loses the whole-Mac permission (limit_locally), and
    every schedule in the copy is off until the user turns it on here. Runs again on the loaded data, after the upgrades a file gets."""
    settings, here_settings = new['settings'], old.get('settings') or {}
    for key in ('access', 'accessFolder', 'permissionMode', 'sharedMcp'):
        if key in here_settings: settings[key] = copy.deepcopy(here_settings[key])
        else: settings.pop(key, None)
    settings.setdefault('sharedMcp', []); settings['abilitiesV2'] = True  # nor does an upgrade pick a 管理員 by name (core.py)
    new['customProviders'] = copy.deepcopy(P.custom_list(old))
    custom = lambda p: isinstance(p, str) and p.startswith(P.CUSTOM_PREFIX)
    # A custom CLI runs with no sandbox of Zook's: only where this Mac itself set it, never because the copy names one.
    if custom(settings.get('provider')) and settings.get('provider') != here_settings.get('provider'):
        if here_settings.get('provider'): settings['provider'] = here_settings['provider']
        else: settings.pop('provider', None); settings.pop('model', None)  # the built-in default
    own_order = lambda d: d.get('fallbacks') if isinstance(d.get('fallbacks'), list) else []
    if isinstance(settings.get('fallbacks'), list): settings['fallbacks'] = [x for x in settings['fallbacks'] if not custom(x) or x in own_order(here_settings)]
    for key in ('google', 'googleOthers', 'gmail'):  # sign-ins in this Mac's Keychain are used only as this Mac set them up
        if key in here_settings: settings[key] = copy.deepcopy(here_settings[key])
        else: settings.pop(key, None)
    local_connectors = [c for c in old.get('connectors') or [] if isinstance(c, dict)]
    known = {c.get('id') for c in local_connectors}
    brought = [copy.deepcopy(c) for c in new.get('connectors') or [] if isinstance(c, dict) and c.get('id') not in known]  # off: not in sharedMcp
    for c in brought:  # and with no sign-in or key of this Mac's: it is signed in again once the user turns it on here
        for key in ('oauth', 'otherAccounts', 'secretId'): c.pop(key, None)
        if isinstance(c.get('moreSecrets'), dict): c['moreSecrets'] = {k: '' for k in c['moreSecrets']}
    new['connectors'] = copy.deepcopy(local_connectors) + brought
    if isinstance(old.get('claudeGate'), dict): new['claudeGate'] = copy.deepcopy(old['claudeGate'])
    else: new.pop('claudeGate', None)
    for item in new.get('schedules') or []:
        if isinstance(item, dict): item['on'] = False
    listed = lambda data: [b for b in (data.get('bots') or []) + (data.get('deletedBots') or []) if isinstance(b, dict)]
    here = {b.get('id'): b for b in listed(old)}
    kind = lambda bot, data: provider_kind(bot.get('provider') or (data.get('settings') or {}).get('provider', 'codex'))
    for bot in listed(new):
        was = here.get(bot.get('id')) or {}
        if custom(bot.get('provider')) and bot['provider'] != was.get('provider'): bot.update(provider='', model='')
        if isinstance(bot.get('fallbacks'), list): bot['fallbacks'] = [x for x in bot['fallbacks'] if not custom(x) or x in own_order(was)]
        was = here.get(bot.get('id'))
        if was is None or was.get('recovered'): hold_in(bot); continue  # found in an old copy by an earlier version: never allowed here
        for key in LOCAL_GRANTS:
            if key in was: bot[key] = copy.deepcopy(was[key])
            else: bot.pop(key, None)
        if kind(bot, new) != kind(was, old):
            had = bot.pop('gateFull', None)
            if had or kind(bot, new) in GATED_KINDS: hold_scope(bot)
    # One 管理員, the one this Mac has: a Bot back from the copy that was 管理員 when it was set aside here steps down.
    admins = [b for b in new.get('bots') or [] if isinstance(b, dict) and b.get('isAdmin')]
    if len(admins) > 1:
        now = {b.get('id') for b in old.get('bots') or [] if isinstance(b, dict) and b.get('isAdmin')}
        chosen = next((b for b in admins if b['id'] in now), admins[0])
        for b in admins:
            if b is not chosen: b['isAdmin'] = False


def held_in_migrate(store):
    """Once per data folder: Bots from before the hold that the user did not set up here, made by another Bot (its 新增 Bot call is
    still in a reply's record) or arrived from another Mac (this Mac's sync record says its version here was written elsewhere, not
    changed here since), keep to their workspace and 謹慎. A Bot of this Mac's own that has not changed since joining is held in too."""
    settings = store.data['settings']
    if settings.get('heldInSet'): return False
    stamps = sync_marks(store)['stamps'] if (store.dir / 'sync-marks.json').exists() else {}
    synced = {k for k, v in stamps.items() if isinstance(v, list) and len(v) > 2 and v[2] is False}
    made = {str((c.get('arguments') or {}).get('name') or '').strip().lower() for j in store.data.get('jobs') or [] for c in j.get('toolCalls') or []
            if str(c.get('name') or '').endswith('zook_create_bot')} - {''}
    for bot in store.data['bots']:
        if bot.get('localLimit'): continue
        if 'bots:' + str(bot.get('id')) in synced or str(bot.get('name') or '').strip().lower() in made: hold_in(bot)
    for bot in store.data.get('deletedBots') or []:  # found in an old copy by an earlier version, before it was held in there
        if isinstance(bot, dict) and bot.get('recovered') and not bot.get('localLimit'): hold_in(bot)
    settings['heldInSet'] = True
    return True


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


def billing_still_ok(store, job_id, bot, provider, account, fixed):
    """Before a reply is sent again (its conversation could not be continued, or it was too long): a Bot whose model must not run on API
    billing has its sign-in asked again, as before the first try. False, and the reply stops, when it is no longer a subscription."""
    if not fixed: return True
    auto_recheck_live(store, bot, provider, account)
    with store.lock:
        key_account = account if account is not None else (find_account(bot.get('account'), provider) or {}).get('id', '')
        problem = auto_billing_problem(store, provider, key_account)
        if problem:
            stale = auto_billing_stale(store, auto_billing_keys(store, bot, [(provider, '', account, False)]))
        else: return True
    if stale:  # a watched sign-in not checked recently: checked now
        auto_recheck(store, auto_billing_keys(store, bot, [(provider, '', account, False)]))
        with store.lock: problem = auto_billing_problem(store, provider, key_account)
        if not problem: return True
    with store.lock:
        job = store.find('jobs', job_id) or {}
        if job.get('status') == 'running':
            job.update(status='failed', error='%s 現在不能用（%s），所以沒有重送。請到「各模型使用量」確認。' % (auto_choice_name(provider, key_account), problem), finishedAt=NOW())
            store.finish_message(job, '', 'failed'); store.save()
    return False
