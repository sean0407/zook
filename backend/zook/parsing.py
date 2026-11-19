# Reading what each CLI prints, usage totals. Loaded by backend/server.py into one shared namespace.
def _int(value):
    return value if isinstance(value, int) and value >= 0 else 0


_SECRET_VALUE = r"""(?:\\?"(?:[^"\\]|\\[^"])*\\?"|'[^']*'|[^\s"'&]+)"""
_SECRET_NAME = r'[a-z0-9_-]*(?:token|secret|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|credential)[a-z0-9_-]*'
_COMMAND_SECRETS = (
    (re.compile(r"""(?i)(authorization\\?["']?\s*[:=]\s*\\?["']?)[^"'\\\n]+"""), r'\1[redacted]'),
    (re.compile(r'(?i)(\bbearer\s+)[a-z0-9._~+/=-]{8,}'), r'\1[redacted]'),
    (re.compile(r'\b(?:sk|pk|rk|xai|ghp|gho|ghs|github_pat|glpat|hf|xox[abprs])[-_][-_A-Za-z0-9]{10,}|\bAIza[-_A-Za-z0-9]{12,}|\bAKIA[0-9A-Z]{12,}|\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}'), '[redacted]'),
    (re.compile(r'(?i)(://[^/\s:@]+:)[^/\s@]+@'), r'\1[redacted]@'),
    (re.compile(r"""(?i)((?:^|\s)(?:-u|--user)[= ]+["']?[^\s:"']+:)[^\s"']+"""), r'\1[redacted]'),
    (re.compile(r'(?i)(\bsshpass\s+-p\s*)\S+'), r'\1[redacted]'),
    (re.compile(r'(?i)(\b(?:mysql|mysqldump|mariadb)\b[^|;&\n]*?\s-p)(?=\S)\S+'), r'\1[redacted]'),
    (re.compile(r'(?i)([?&][a-z0-9_-]*(?:key|token|secret|sig|signature|auth|password)[a-z0-9_-]*=)[^&\s"\']+'), r'\1[redacted]'),
    (re.compile(r'(?i)(--?(?:password|passwd|pass|token|secret|api-?key)[= ]+)' + _SECRET_VALUE), r'\1[redacted]'),
    (re.compile(r"""(?i)(""" + _SECRET_NAME + r"""\\?["']?\s*[=:]\s*)""" + _SECRET_VALUE), r'\1[redacted]'),
)


def hide_command_secrets(text):
    for pattern, replacement in _COMMAND_SECRETS: text = pattern.sub(replacement, text)
    return text


def native_action(kind, value):
    """Activity entry for something a CLI's built-in tool did (a file it changed or a command it ran)."""
    value = str(value or '').strip()
    if kind == 'command':
        match = re.match(r"^/bin/(?:zsh|bash|sh) -lc (['\"]?)(.*)\1$", value, re.S)
        return dict(name='native_command', category='code', arguments={'command': hide_command_secrets(match.group(2) if match else value)[:300]})
    return dict(name='native_write', category='internal', arguments={'path': value[:300]})


def parse_cli_output(provider, text, model=''):
    """Reply text, token usage and quota snapshot from Codex --json / Claude stream-json output."""
    objs = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('{'):
            try:
                value = json.loads(line)
                if isinstance(value, dict): objs.append(value)
            except ValueError: pass
    if not objs and text.strip().startswith('{'):
        try:  # Pretty-printed single JSON document (e.g. grok --output-format json).
            whole = json.loads(text)
            if isinstance(whole, dict): objs.append(whole)
        except ValueError: pass
    out = dict(content='', usage=None, quota=None, error='', isError=False, unparsable=False, web=[])
    if provider == 'plain':
        out['content'] = ANSI.sub('', text).strip(); return out
    if provider == 'antigravity':
        d = next((o['result'] for o in reversed(objs) if o.get('event') == 'result' and isinstance(o.get('result'), dict)), None)
        if d is None: out['unparsable'] = True; return out
        out['content'] = str(d.get('response') or '').strip()
        if d.get('status') != 'SUCCESS': out['isError'] = True; out['error'] = str(d.get('error') or out['content'])[:2000]
        u = d.get('usage') if isinstance(d.get('usage'), dict) else None
        if u: out['usage'] = dict(input=_int(u.get('input_tokens')), cachedInput=_int(u.get('cache_read_tokens')), output=_int(u.get('output_tokens')), model=model or '預設模型', costUsd=None)
        return out
    if provider == 'grok':
        # grok --output-format json: {text, usage{input_tokens, cache_read_input_tokens, ...}, total_cost_usd, modelUsage}
        end = next((o for o in reversed(objs) if o.get('type') == 'end'), None)
        if end is not None:
            # grok --output-format streaming-json: text deltas, tool_call events, then one 'end' event with usage.
            chunks, listed_web = [], False
            for o in objs:
                kind = o.get('type')
                if kind == 'text': chunks.append(str(o.get('data') or ''))
                elif kind == 'tool_call':
                    chunks = []  # Keep only what the Bot says after its last action.
                    tool = str(o.get('toolName') or o.get('kind') or '').lower(); raw = o.get('rawInput') if isinstance(o.get('rawInput'), dict) else {}
                    if tool in ('write', 'edit', 'search_replace', 'multi_edit') or o.get('kind') in ('write', 'edit'):
                        out['web'].append(native_action('write', raw.get('file_path') or raw.get('path') or ''))
                    elif tool in ('run_terminal_command', 'bash', 'execute'): out['web'].append(native_action('command', raw.get('command') or ''))
                    elif 'search' in tool and 'web' in tool:
                        listed_web = True; out['web'].append(dict(name='web_search', arguments={'query': str(raw.get('query') or '')[:200]}))
                    elif 'fetch' in tool or tool in ('open_url', 'browse_page'):
                        listed_web = True; out['web'].append(dict(name='web_fetch', arguments={'url': str(raw.get('url') or '')[:300]}))
            d = dict(end, text=''.join(chunks))
            if listed_web: d = dict(d, modelUsage={k: dict(v, webSearchRequests=0) if isinstance(v, dict) else v for k, v in (d.get('modelUsage') or {}).items()})
            if end.get('stopReason') == 'cancelled' and not d['text'].strip(): d['error'] = '回覆被中斷。'
        else:
            d = next((o for o in reversed(objs) if 'text' in o or 'usage' in o), None)
        if d is None:
            out['content'] = ANSI.sub('', text).strip(); return out
        out['content'] = str(d.get('text') or '').strip()
        if d.get('is_error') or d.get('error'): out['isError'] = True; out['error'] = str(d.get('error') or out['content'])[:2000]
        u = d.get('usage') if isinstance(d.get('usage'), dict) else None
        searches = _int(((u or {}).get('server_tool_use') or {}).get('web_search_requests')) if isinstance((u or {}).get('server_tool_use'), dict) else 0
        searches = searches or sum(_int(v.get('webSearchRequests')) for v in (d.get('modelUsage') or {}).values() if isinstance(v, dict))
        for _ in range(min(searches, 20)): out['web'].append(dict(name='web_search', arguments={}))
        if u:
            cached = _int(u.get('cache_read_input_tokens'))
            models = list(d['modelUsage'].keys()) if isinstance(d.get('modelUsage'), dict) else []
            cost = d.get('total_cost_usd')
            out['usage'] = dict(input=_int(u.get('input_tokens')) + cached + _int(u.get('cache_creation_input_tokens')), cachedInput=cached, cacheWrite=_int(u.get('cache_creation_input_tokens')),
                                output=_int(u.get('output_tokens')), model=models[0] if models else (model or '預設模型'),
                                costUsd=cost if isinstance(cost, (int, float)) else None)
        return out
    if provider == 'codex':
        if not objs:
            out['content'] = text.strip(); return out  # Plain-text output from older CLIs.
        messages, totals = [], {'input': 0, 'cachedInput': 0, 'output': 0}
        seen_usage = False
        for d in objs:
            kind = d.get('type')
            item = d.get('item') if isinstance(d.get('item'), dict) else {}
            if kind == 'item.completed' and item.get('type') == 'agent_message' and isinstance(item.get('text'), str): messages.append(item['text'])
            elif kind == 'item.completed' and item.get('type') == 'web_search':
                act = item.get('action') if isinstance(item.get('action'), dict) else {}
                query = str(item.get('query') or act.get('query') or '')[:300]
                url = str(act.get('url') or (query if re.match(r'https?://', query) else ''))[:300]
                if url: out['web'].append(dict(name='web_fetch', arguments={'url': url}))
                elif query: out['web'].append(dict(name='web_search', arguments={'query': query[:200]}))
            elif kind == 'item.completed' and item.get('type') == 'command_execution':
                out['web'].append(native_action('command', item.get('command')))
            elif kind == 'item.completed' and item.get('type') == 'file_change':
                for change in (item.get('changes') or [])[:20]:
                    if isinstance(change, dict) and change.get('path'): out['web'].append(native_action('write', change['path']))
            elif kind == 'turn.completed' and isinstance(d.get('usage'), dict):
                u = d['usage']; seen_usage = True
                totals['input'] += _int(u.get('input_tokens')); totals['cachedInput'] += _int(u.get('cached_input_tokens')); totals['output'] += _int(u.get('output_tokens'))
            elif kind in ('error', 'turn.failed'):
                err = d.get('error') if isinstance(d.get('error'), dict) else d
                out['error'] += str(err.get('message') or '')[:2000] + '\n'; out['isError'] = True
        out['content'] = messages[-1].strip() if messages else ''
        if out['content']: out['isError'] = False
        if seen_usage: out['usage'] = dict(totals, model=model or '預設模型', costUsd=None)
        return out
    result = None
    for d in objs:
        message = d.get('message') if d.get('type') == 'assistant' and isinstance(d.get('message'), dict) else {}
        for block in message.get('content') or []:
            if isinstance(block, dict) and block.get('type') in ('tool_use', 'server_tool_use') and block.get('name') in ('WebSearch', 'web_search', 'WebFetch', 'web_fetch'):
                inp = block.get('input') if isinstance(block.get('input'), dict) else {}
                if 'Fetch' in block['name'] or 'fetch' in block['name']: out['web'].append(dict(name='web_fetch', arguments={'url': str(inp.get('url') or '')[:300]}))
                else: out['web'].append(dict(name='web_search', arguments={'query': str(inp.get('query') or '')[:200]}))
            elif isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
                inp = block.get('input') if isinstance(block.get('input'), dict) else {}
                out['web'].append(native_action('write', inp.get('file_path') or inp.get('notebook_path') or ''))
            elif isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') == 'Bash':
                out['web'].append(native_action('command', (block.get('input') or {}).get('command') if isinstance(block.get('input'), dict) else ''))
        if d.get('type') == 'rate_limit_event' and isinstance(d.get('rate_limit_info'), dict): out['quota'] = d['rate_limit_info']
        if d.get('type') == 'result' or ('result' in d and 'type' not in d): result = d
    if result is None:
        out['unparsable'] = True; return out
    out['content'] = str(result.get('result') or '').strip()
    out['isError'] = bool(result.get('is_error'))
    if out['isError']: out['error'] = out['content']
    u = result.get('usage') if isinstance(result.get('usage'), dict) else None
    if u:
        cached = _int(u.get('cache_read_input_tokens'))
        models = list((result.get('modelUsage') or {}).keys()) if isinstance(result.get('modelUsage'), dict) else []
        cost = result.get('total_cost_usd')
        out['usage'] = dict(input=_int(u.get('input_tokens')) + _int(u.get('cache_creation_input_tokens')) + cached, cachedInput=cached, cacheWrite=_int(u.get('cache_creation_input_tokens')),
                            output=_int(u.get('output_tokens')), model=(models[0] if models else model or '預設模型'),
                            costUsd=cost if isinstance(cost, (int, float)) else None)
    return out


WINDOW_LABELS = {300: '5 小時', 10080: '每週', 1440: '每日'}


def normalize_quota(provider, info):
    if not isinstance(info, dict): return None
    if provider == 'codex':
        rl = info.get('rateLimits') if isinstance(info.get('rateLimits'), dict) else info
        windows = []
        for key in ('primary', 'secondary'):
            w = rl.get(key)
            if isinstance(w, dict) and isinstance(w.get('usedPercent'), (int, float)):
                mins = w.get('windowDurationMins')
                windows.append(dict(label=WINDOW_LABELS.get(mins, '%s 分鐘' % mins if mins else key), usedPercent=float(w['usedPercent']), resetsAt=w.get('resetsAt')))
        credits = rl.get('credits') if isinstance(rl.get('credits'), dict) else {}
        resets = info.get('rateLimitResetCredits') if isinstance(info.get('rateLimitResetCredits'), dict) else {}
        return dict(windows=windows, plan=str(rl.get('planType') or ''), limitReached=rl.get('rateLimitReachedType'),
                    credits=dict(balance=credits.get('balance'), unlimited=bool(credits.get('unlimited')), hasCredits=bool(credits.get('hasCredits'))),
                    resetCredits=resets.get('availableCount') if isinstance(resets.get('availableCount'), int) else None)
    unified = info.get('unifiedWindows') if isinstance(info.get('unifiedWindows'), dict) else {}
    windows = []
    for key, label in (('five_hour', '5 小時'), ('seven_day', '每週'), ('seven_day_opus', '每週（Opus）'), ('seven_day_sonnet', '每週（Sonnet）')):
        w = unified.get(key)
        if isinstance(w, dict) and isinstance(w.get('utilization'), (int, float)):
            windows.append(dict(label=label, usedPercent=round(float(w['utilization']) * 100, 1), resetsAt=w.get('resetsAt'), status=w.get('status')))
    if not windows and isinstance(info.get('utilization'), (int, float)):
        windows.append(dict(label=WINDOW_LABELS.get(300) if info.get('rateLimitType') == 'five_hour' else str(info.get('rateLimitType') or ''), usedPercent=round(info['utilization'] * 100, 1), resetsAt=info.get('resetsAt')))
    return dict(windows=windows, status=info.get('status'), overage=info.get('overageStatus')) if windows or info.get('status') else None


def claude_quota_probe(env=None):
    """Smallest possible Claude request (haiku, one word) to read the current limits. User-triggered only."""
    path = find_cli('claude')
    if not path: raise RuntimeError('找不到 Claude CLI。')
    p = subprocess.run([path, '--print', '--model', 'haiku', '--safe-mode', '--strict-mcp-config', '--no-session-persistence', '--tools', '',
                        '--output-format', 'stream-json', '--verbose'], input=b'Reply with OK', stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                       env=env or claude_personal_env(), timeout=90, cwd=tempfile.gettempdir())
    parsed = parse_cli_output('claude', p.stdout.decode('utf-8', 'replace'))
    if not parsed['quota']: raise RuntimeError('Claude 沒有回報額度資訊。' + ('請確認已登入。' if p.returncode else ''))
    return parsed['quota']


def provider_usage(store, provider, account_id=''):
    """What Zook itself spent through one account of a provider ('' is the CLI's own sign-in) in the last 5 hours and 7 days."""
    now = time.time(); windows = {'fiveHour': 5 * 3600, 'week': 7 * 86400}
    out = {k: dict(replies=0, tokens=0, costUsd=0.0, hasCost=False) for k in windows}
    bots = {b['id']: b for b in store.data['bots']}
    for job in store.data['jobs']:
        u = job.get('usage')
        if not isinstance(u, dict) or u.get('provider') != provider: continue
        used = u['account'] if 'account' in u else (find_account((bots.get(job.get('botId')) or {}).get('account'), provider) or {}).get('id', '')  # older replies: the Bot's account
        if used != account_id: continue
        try: age = now - datetime.datetime.fromisoformat(str(job.get('finishedAt') or job.get('createdAt'))).timestamp()
        except ValueError: continue
        for key, span in windows.items():
            if age <= span:
                w = out[key]; w['replies'] += 1; w['tokens'] += _int(u.get('input')) + _int(u.get('output'))
                if isinstance(u.get('costUsd'), (int, float)): w['costUsd'] += u['costUsd']; w['hasCost'] = True
    for w in out.values(): w['costUsd'] = round(w['costUsd'], 4) if w.pop('hasCost') else None
    return out


def bot_usage(store):
    """Token totals per Bot from Zook's own jobs (only replies made after usage tracking began)."""
    alive = {b['id'] for b in store.data['bots']}; gone = {b['id']: b for b in store.data.get('deletedBots') or [] if b.get('id') not in alive}
    names = dict(gone, **{b['id']: b for b in store.data['bots']})  # a deleted Bot that is kept aside still has its name and looks
    today = datetime.datetime.now().astimezone().date()
    days = [(today - datetime.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    rows = {}
    for job in store.data['jobs']:
        u = job.get('usage')
        if not isinstance(u, dict): continue
        row = rows.setdefault(job['botId'], dict(botId=job['botId'], name=names.get(job['botId'], {}).get('name', '已刪除的 Bot'),
                              color=names.get(job['botId'], {}).get('color', '#959595'), shape=names.get(job['botId'], {}).get('shape', 0),
                              replies=0, groupReplies=0, input=0, cachedInput=0, output=0, costUsd=0.0, hasCost=False, models={}, daily={d: 0 for d in days}))
        row['replies'] += 1; row['groupReplies'] += 1 if job.get('groupId') else 0
        for k in ('input', 'cachedInput', 'output'): row[k] += _int(u.get(k))
        if isinstance(u.get('costUsd'), (int, float)): row['costUsd'] += u['costUsd']; row['hasCost'] = True
        label = '%s · %s' % (u.get('provider', ''), u.get('model') or '預設模型')
        row['models'][label] = row['models'].get(label, 0) + _int(u.get('input')) + _int(u.get('output'))
        try: day = datetime.datetime.fromisoformat(str(job.get('finishedAt') or job.get('createdAt'))).astimezone().date().isoformat()
        except ValueError: day = ''
        if day in row['daily']: row['daily'][day] += _int(u.get('input')) + _int(u.get('output'))
    for bot_id, old in (store.data.get('usageArchive') or {}).items():  # replies older than the job list keeps
        row = rows.setdefault(bot_id, dict(botId=bot_id, name=names.get(bot_id, {}).get('name', '已刪除的 Bot'), color=names.get(bot_id, {}).get('color', '#959595'), shape=names.get(bot_id, {}).get('shape', 0),
                              replies=0, groupReplies=0, input=0, cachedInput=0, output=0, costUsd=0.0, hasCost=False, models={}, daily={d: 0 for d in days}))
        for k in ('replies', 'groupReplies', 'input', 'cachedInput', 'output'): row[k] += _int(old.get(k))
        if old.get('hasCost'): row['costUsd'] += old.get('costUsd') or 0; row['hasCost'] = True
        for label, tokens in (old.get('models') or {}).items(): row['models'][label] = row['models'].get(label, 0) + _int(tokens)
    result = sorted(rows.values(), key=lambda r: r['input'] + r['output'], reverse=True)
    for r in result:
        r['costUsd'] = round(r['costUsd'], 4) if r['hasCost'] else None
        r['deleted'] = r['botId'] not in alive; r['restorable'] = r['botId'] in gone
    return dict(bots=result, days=days, untracked=sum(1 for j in store.data['jobs'] if j.get('status') == 'completed' and not j.get('usage')))


def terminate_tree(proc):
    try: os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError: return
    def force():
        # Kill the process group even if its leader exited; descendants may still run.
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    timer = threading.Timer(2.0, force); timer.daemon = True; timer.start()


