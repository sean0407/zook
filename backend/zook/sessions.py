# Continuing each CLI's own conversation. Loaded by backend/server.py into one shared namespace.
MAX_CONTEXT = 60000  # characters of saved conversation given to a CLI that starts a new conversation


def conversation_context(messages):
    """As much of the saved conversation as fits, newest kept first, in reading order."""
    lines, used = [], 0
    for m in reversed(messages):
        if not m.get('content'): continue
        line = (m['role'] + '（由%s送出，不是使用者本人）: ' % m['author'] if m.get('author') and m['role'] == 'user' else m['role'] + ': ') + m['content'][:4000]
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
        elif kind == 'opencode' and event.get('sessionID'): found = event['sessionID']
        elif kind == 'antigravity' and event.get('event') == 'result' and isinstance(event.get('result'), dict): found = event['result'].get('conversation_id') or found
    return str(found) if re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', str(found)) else ''


# Exactly what each CLI prints on stderr when asked to continue a conversation it no longer has (checked on the real CLIs).
_SESSION_LOST = re.compile(r'no rollout found for thread id|no conversation found with session id|no saved copy of session', re.I)


def session_lost(stderr):
    """True only when the CLI says the conversation no longer exists, so nothing was done and starting over is safe."""
    return bool(_SESSION_LOST.search(str(stderr or '')))


def cli_used_tools(kind, text):
    """Whether Grok or Antigravity started one of its built-in tools in this output."""
    if kind not in ('grok', 'antigravity', 'opencode'): return False
    for line in str(text or '').splitlines():
        if not line.lstrip().startswith('{'): continue
        try: event = json.loads(line)
        except ValueError: continue
        if not isinstance(event, dict): continue
        step = event.get('step_update') if isinstance(event.get('step_update'), dict) else {}
        if event.get('type') == 'tool_call' or step.get('step_type') == 'tool': return True
        part = event.get('part') if isinstance(event.get('part'), dict) else {}
        if kind == 'opencode' and (event.get('type') in ('tool_use', 'tool') or part.get('type') == 'tool') and not str(part.get('tool') or '').startswith('zook_'): return True
    return False


def latest_ask_note(content):
    """Ends the prompt with what the user just asked, so the model answers it and not the background above."""
    if not content: return ''
    return '\n\n以上都是背景說明。請回應使用者這次的訊息：\n' + (content if len(content) <= 4000 else '（內容較長，請看上方「使用者：」後面的完整訊息）')


def skipped_connectors(session):
    return ['%s（%s）' % (name, session.unavailable_why.get(name, '連不上')) for name in session.unavailable]


class Pipes:
    """Reads what a CLI writes as it comes, so a CLI that is busy can be told from one that is stuck. Nothing beyond the size limit is kept."""
    def __init__(self, proc, data, limit, on_output=None):
        self.proc, self.limit, self.last, self.out, self.on_output = proc, limit, time.monotonic(), [bytearray(), bytearray()], on_output
        self.threads = [threading.Thread(target=self._read, args=(proc.stdout, 0), daemon=True), threading.Thread(target=self._read, args=(proc.stderr, 1), daemon=True)]
        if data is not None: self.threads.append(threading.Thread(target=self._write, args=(data,), daemon=True))
        for t in self.threads: t.start()

    def _read(self, pipe, index):
        try:
            while True:
                chunk = pipe.read1(65536)
                if not chunk: return
                self.last = time.monotonic()
                if len(self.out[index]) <= self.limit: self.out[index] += chunk
                if index == 0 and self.on_output: self.on_output(chunk)
        except (OSError, ValueError): pass

    def _write(self, data):
        try: self.proc.stdin.write(data); self.proc.stdin.close()
        except (OSError, ValueError): pass  # the CLI left without reading its prompt

    def wait(self, seconds):
        """True once the CLI has ended and its last output has been read."""
        try: self.proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired: return False
        for t in self.threads: t.join(timeout=5)  # a child it left behind may hold the pipe open: do not wait for that one
        for thread, pipe in zip(self.threads, (self.proc.stdout, self.proc.stderr)):
            if not thread.is_alive():  # a pipe still being read is left to its reader
                try: pipe.close()
                except (OSError, ValueError): pass
        return True

    def result(self): return bytes(self.out[0]), bytes(self.out[1])
