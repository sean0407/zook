# 等待時的進度 (#236): what a reply has really done so far, for the line under 「正在思考…」. Loaded by backend/server.py into
# one shared namespace.
#
# - Only what the CLI itself reports counts: the tool events in its output as it arrives (a file read or changed, a command, a
#   web search), and Zook's own tools as they are used (job['toolCalls']). Nothing is made up from a timer; the window adds only
#   the time since the reply started.
# - lastAt is when the CLI last printed anything or used a Zook tool. The window says 「可能卡住了」 when that is long ago; it never
#   stops anything by itself.
# - After ■, a reply whose CLI has not ended yet is 「正在停止」 (stopping). 強制停止 ends it at once (SIGKILL through kill_group,
#   which goes through the runner for a CLI under one: never the CLI's own number, background.py) and lets go of its output.
# Nothing here is saved; after a restart a reply taken up again reads its CLI's output from the start, so it is counted again.
PROGRESS = {}   # job id -> dict(read, write, command, web, last, step, stepAt, seen)
STOPPING = {}   # job id -> when ■ was pressed (epoch seconds) while its CLI was still running
FORCED = set()  # job ids whose wait for their CLI is to end now (強制停止)
PROGRESS_STEP = 15  # seconds: lastAt moves in steps, so a busy reply does not redraw the window for every word


def progress_start(job_id):
    """A CLI starts for this reply (also a backup model, or the same reply taken up after a restart): counted from here."""
    PROGRESS[job_id] = dict(read=0, write=0, command=0, web=0, last=time.time(), step='', stepAt=0.0, seen=set(), asked={}, zookDone=0, zookAt=0.0, files=[])


def progress_end(job_id):
    """Its CLI is gone: nothing is left to count or to stop."""
    PROGRESS.pop(job_id, None); STOPPING.pop(job_id, None); FORCED.discard(job_id)


def progress_touch(job_id):
    rec = PROGRESS.get(job_id)
    if rec is not None and time.time() - rec['last'] >= PROGRESS_STEP: rec['last'] = time.time()


def _progress_base(path):
    return str(path or '').rstrip('/').split('/')[-1][:80]


def _progress_add(rec, what, ref, where=''):
    """One step the CLI reported. The same step reported twice (started, then done) is counted once."""
    if ref is not None:
        if ref in rec['seen']: return
        if len(rec['seen']) < 5000: rec['seen'].add(ref)
    if what == 'write' and isinstance(where, str) and where.startswith('/') and len(where) < 300 and len(rec.setdefault('paths', [])) < 50 and where not in rec['paths']:
        rec['paths'].append(where)  # before the count, so 產出 read for the new count finds it (#53, outputs.py)
    rec[what] += 1; rec['stepAt'] = time.time()
    rec['step'] = _progress_words(what, where)
    name = _progress_base(where)
    if what in ('read', 'write') and name:  # the last few files it read or changed, by name only (#307: a member's own page)
        rec['files'] = [f for f in rec['files'] if f['name'] != name][-5:] + [dict(w=what, name=name)]


def _progress_words(what, where=''):
    name = _progress_base(where)
    return {'read': '讀取檔案「%s」' % name if name else '讀取檔案', 'write': '修改檔案「%s」' % name if name else '修改檔案',
            'command': '執行指令', 'web': '查網路資料'}[what]  # a command is never shown, only that one ran


def _progress_tool(name, where=''):
    """read / write / command / web for a CLI's built-in tool by its name, or None."""
    n = str(name or '').lower()
    if n.startswith('mcp__zook') or n.startswith('zook_') or 'todo' in n: return None  # Zook's own tools are counted from toolCalls; a to-do list is not a file
    if any(w in n for w in ('web', 'fetch', 'browse', 'url')): return 'web'
    if any(w in n for w in ('bash', 'shell', 'command', 'terminal', 'execute', 'exec_')): return 'command'
    if any(w in n for w in ('write', 'edit', 'replace', 'create', 'delete', 'patch', 'notebook')): return 'write'
    if any(w in n for w in ('read', 'view', 'cat')) and not any(w in n for w in ('glob', 'list', 'grep', 'search', 'find')): return 'read'  # a file opened, not names listed
    return None


def progress_line(kind, d, rec):
    """One line of a CLI's output (already read as JSON)."""
    if kind == 'claude':
        message = d.get('message') if d.get('type') == 'assistant' and isinstance(d.get('message'), dict) else {}
        for block in message.get('content') or []:
            if not isinstance(block, dict) or block.get('type') not in ('tool_use', 'server_tool_use'): continue
            inp = block.get('input') if isinstance(block.get('input'), dict) else {}
            what = _progress_tool(block.get('name')); where = inp.get('file_path') or inp.get('notebook_path') or inp.get('path') or ''
            if what and block['type'] == 'server_tool_use': _progress_add(rec, what, 'c:' + str(block.get('id')), where)  # done on the server
            elif what and block.get('id') and len(rec['asked']) < 500: rec['asked']['c:' + str(block['id'])] = (what, where)  # counted once its result comes back
        user = d.get('message') if d.get('type') == 'user' and isinstance(d.get('message'), dict) else {}
        for block in user.get('content') or [] if isinstance(user.get('content'), list) else []:
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                asked = rec['asked'].pop('c:' + str(block.get('tool_use_id')), None)
                if asked and block.get('is_error') is not True: _progress_add(rec, asked[0], 'c:' + str(block.get('tool_use_id')), asked[1])  # refused or failed: not done
    elif kind == 'codex':
        if d.get('type') == 'item.started' and isinstance(d.get('item'), dict) and d['item'].get('id') and len(rec['asked']) < 500:
            what = {'command_execution': 'command', 'web_search': 'web', 'file_change': 'write'}.get(d['item'].get('type'))
            if what: rec['asked']['x:' + str(d['item']['id'])] = (what, '')  # what it is doing now, counted once it finishes
        item = d.get('item') if d.get('type') == 'item.completed' and isinstance(d.get('item'), dict) else {}  # only what it finished
        ref = 'x:' + str(item.get('id')) if item.get('id') else None
        if ref: rec['asked'].pop(ref, None)
        if item.get('type') == 'command_execution': _progress_add(rec, 'command', ref)
        elif item.get('type') == 'web_search': _progress_add(rec, 'web', ref)
        elif item.get('type') == 'file_change':
            for i, change in enumerate((item.get('changes') or [])[:50]):
                if isinstance(change, dict): _progress_add(rec, 'write', None if ref is None else '%s:%d' % (ref, i), change.get('path') or '')
    elif kind == 'grok':
        if d.get('type') == 'tool_call':
            raw = d.get('rawInput') if isinstance(d.get('rawInput'), dict) else {}
            what = _progress_tool(d.get('toolName') or d.get('kind'))
            ref = d.get('toolCallId') or d.get('id')
            if what: _progress_add(rec, what, 'g:' + str(ref) if ref else None, raw.get('file_path') or raw.get('path') or '')
    elif kind == 'cursor':
        if d.get('type') == 'tool_call':
            call = d.get('tool_call') if isinstance(d.get('tool_call'), dict) else {}
            name = next(iter(call), ''); raw = (call.get(name) or {}).get('args') if isinstance(call.get(name), dict) else {}
            raw = raw if isinstance(raw, dict) else {}
            what = _progress_tool(name.replace('ToolCall', ''))
            ref = 'u:' + str(d.get('call_id')) if d.get('call_id') else None
            if what and ref and d.get('subtype') == 'started' and len(rec['asked']) < 500: rec['asked'][ref] = (what, raw.get('path') or raw.get('file_path') or '')
            elif ref: rec['asked'].pop(ref, None)
            refused = re.search(r'(?i)"(?:error|rejected|denied|failure)"|permission denied|被拒|沒有允許', json.dumps(call, ensure_ascii=False)[:20000])
            if what and d.get('subtype') == 'completed' and not refused: _progress_add(rec, what, 'u:' + str(d.get('call_id')) if d.get('call_id') else None, raw.get('path') or raw.get('file_path') or '')
    elif kind == 'antigravity':
        step = d.get('step_update') if d.get('event') == 'step_update' and isinstance(d.get('step_update'), dict) else {}
        if step.get('step_type') == 'tool' and step.get('state') == 'DONE':
            info = step.get('tool_info') if isinstance(step.get('tool_info'), dict) else {}
            given = info.get('parameters') if isinstance(info.get('parameters'), dict) else {}
            what = _progress_tool(step.get('tool_name'))
            where = given.get('Path') or given.get('path') or given.get('TargetFile') or given.get('AbsolutePath') or given.get('file_path') or ''
            if what: _progress_add(rec, what, 'a:' + str(step['step_index']) if 'step_index' in step else None, where)


def progress_feeder(kind, job_id, inner=None):
    """feed(bytes) for a CLI's output as it arrives: notes that something came, counts the steps it reports, then hands the same
    bytes to inner (the words shown meanwhile, stream.py). Never stops the reply, whatever it is given."""
    pending = bytearray()

    def feed(chunk):
        try:
            rec = PROGRESS.get(job_id)
            if rec is not None:
                progress_touch(job_id)
                pending.extend(chunk)
                while True:
                    end = pending.find(b'\n')
                    if end < 0: break
                    raw = bytes(pending[:end]).strip(); del pending[:end + 1]
                    if raw.startswith(b'{'):
                        try:
                            d = json.loads(raw.decode('utf-8', errors='replace'))
                            if isinstance(d, dict): progress_line(kind, d, rec)
                        except ValueError: pass
                if len(pending) > 4 * 1024 * 1024: del pending[:]
        except Exception: pass
        if inner: inner(chunk)
    return feed


def _progress_zook(job):
    """Zook's own tools this reply used so far (done ones only), as (read, write, web, other, last step, when it started)."""
    read = write = web = other = 0; step = ''; at = 0.0
    for c in job.get('toolCalls') or []:
        name = str(c.get('name') or '')
        if name == 'zook_native_gate' or name.startswith('native_') or name.startswith('web_'): continue  # the CLI's own step, counted from its output
        if c.get('status') != 'completed': continue  # asked for, waiting or refused: not done
        if name in ('zook_workspace_read', 'zook_group_file_read', 'zook_read_skill_resource'): read += 1
        elif name == 'zook_workspace_write': write += 1
        elif name.startswith('zook_browser_'): web += 1
        else: other += 1
        try: step, at = describe_call(c), datetime.datetime.fromisoformat(str(c.get('createdAt'))).timestamp()
        except Exception: step, at = '', 0.0
    return read, write, web, other, step, at


def progress_view(job):
    """What the window and the phone get about a running reply's progress, or None."""
    out = {}
    if job.get('id') in STOPPING: out['stopping'] = True; out['stoppingAt'] = int(STOPPING[job['id']] * 1000)
    rec = PROGRESS.get(job.get('id'))
    if job.get('status') != 'running' or rec is None: return out
    read, write, web, other, zook_step, zook_at = _progress_zook(job)
    if read + write + web + other > rec['zookDone']: rec['zookDone'], rec['zookAt'] = read + write + web + other, time.time()  # when it was seen done, not asked for
    step = zook_step if zook_step and rec['zookAt'] >= rec['stepAt'] else rec['step'] or zook_step  # whichever was done last
    out['progress'] = dict(read=rec['read'] + read, write=rec['write'] + write, command=rec['command'], web=rec['web'] + web, tool=other, lastAt=int(rec['last'] * 1000), step=step)
    started = list(rec['asked'].values())  # a step the CLI began and has not finished: what it is doing right now
    if started: out['progress']['now'] = _progress_words(*started[-1])
    if rec['files']: out['progress']['files'] = list(rec['files'])
    return out


def progress_stop(job_id, proc):
    """■ was pressed while this reply's CLI runs: it shows as 正在停止 until the CLI is gone."""
    if proc is not None: STOPPING.setdefault(job_id, time.time())


def progress_force(app, job_id):
    """Lock held. 強制停止: the CLI's whole group is killed now (kill_group; through its runner for one under a runner) and Zook stops
    waiting for its output. False when there is nothing left to stop."""
    proc = app.processes.get(job_id)
    if proc is None or job_id not in STOPPING: return False
    FORCED.add(job_id)
    inner = getattr(getattr(proc, 'cli', None), 'proc', None) or proc  # a kept CLI's reply stands for its process (live.py)
    # Under a runner: its runner ends the whole group (it checks the group is still its own). A CLI Zook started itself is not
    # signalled again here: its number could already belong to another program, and ■ already sent SIGTERM and then SIGKILL.
    if isinstance(inner, HostedProc): threading.Thread(target=kill_group, args=(proc,), daemon=True).start()
    return True


def progress_asks_force(handler):
    """POST /api/jobs/<id>/cancel with {"force": true}. An empty body is a plain stop, as before."""
    try: size = int(handler.headers.get('Content-Length') or 0)
    except ValueError: size = 0
    if size <= 0: return False
    return handler.body().get('force') is True


def progress_stopping_in(store, group):
    """The ids of a group's replies that were stopped but whose CLI has not ended yet."""
    return [j['id'] for j in store.data['jobs'] if j.get('groupId') == group['id'] and j['id'] in STOPPING]
