# Continuing each CLI's own conversation. Loaded by backend/server.py into one shared namespace.
MAX_CONTEXT = 60000  # characters of saved conversation given to a CLI that starts a new conversation


def conversation_context(messages):
    """As much of the saved conversation as fits, newest kept first, in reading order."""
    lines, used = [], 0
    for m in reversed(messages):
        if not m.get('content'): continue
        line = m['role'] + ': ' + m['content'][:4000]
        if used + len(line) > MAX_CONTEXT: break
        lines.append(line); used += len(line)
    return '\n'.join(reversed(lines))


def cli_session(kind, text):
    """The id of the CLI's own conversation, from what it printed."""
    found = ''
    for line in str(text or '').splitlines():
        line = line.strip()
        if not line.startswith('{'): continue
        try: event = json.loads(line)
        except ValueError: continue
        if not isinstance(event, dict): continue
        if kind == 'codex' and event.get('type') == 'thread.started': found = event.get('thread_id') or found
        elif kind == 'claude' and event.get('session_id'): found = event['session_id']
        elif kind == 'grok' and event.get('type') == 'end': found = event.get('sessionId') or found
        elif kind == 'antigravity' and event.get('event') == 'result' and isinstance(event.get('result'), dict): found = event['result'].get('conversation_id') or found
    return str(found) if re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', str(found)) else ''


# Exactly what each CLI prints on stderr when asked to continue a conversation it no longer has (checked on the real CLIs).
_SESSION_LOST = re.compile(r'no rollout found for thread id|no conversation found with session id|no saved copy of session', re.I)


def session_lost(stderr):
    """True only when the CLI says the conversation no longer exists, so nothing was done and starting over is safe."""
    return bool(_SESSION_LOST.search(str(stderr or '')))


def cli_used_tools(kind, text):
    """Whether Grok or Antigravity started one of its built-in tools in this output."""
    if kind not in ('grok', 'antigravity'): return False
    for line in str(text or '').splitlines():
        if not line.lstrip().startswith('{'): continue
        try: event = json.loads(line)
        except ValueError: continue
        if not isinstance(event, dict): continue
        step = event.get('step_update') if isinstance(event.get('step_update'), dict) else {}
        if event.get('type') == 'tool_call' or step.get('step_type') == 'tool': return True
    return False


def latest_ask_note(content):
    """Ends the prompt with what the user just asked, so the model answers it and not the background above."""
    if not content: return ''
    return '\n\n以上都是背景說明。請回應使用者這次的訊息：\n' + (content if len(content) <= 4000 else '（內容較長，請看上方「使用者：」後面的完整訊息）')
