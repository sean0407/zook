# A reply as it is being written: the words a CLI has produced so far, shown before the reply is finished.
# Loaded by backend/server.py into one shared namespace.
#
# Nothing here is saved. The finished reply still comes from the CLI's final result, exactly as before; this is only what is on
# screen meanwhile. Each CLI reports its progress in its own way:
#   Claude       stream_event / content_block_delta / text_delta   (word by word)
#   Antigravity  step_update / agent_response / text_delta         (word by word)
#   Grok         text / data                                        (word by word)
#   Codex        item.completed / agent_message                     (a whole message at a time)
MAX_PARTIAL = 400000
PARTIALS = {}  # job id -> dict(text, messageId)


def stream_on(store): return store.data['settings'].get('streamReplies') is not False


def partial_start(job):
    """A new attempt begins with nothing on screen: what an earlier model wrote before it failed is not carried over."""
    PARTIALS[job['id']] = dict(text='', messageId=job.get('messageId'), choices=(_active['data'].get('settings') or {}).get('choiceButtons') is not False and not job.get('groupId') and not job.get('origin') and not job.get('internal'))


def partial_end(job_id): PARTIALS.pop(job_id, None)


def partial_text(job_id):
    entry = PARTIALS.get(job_id) or {}
    return hide_choice_block(entry.get('text') or '') if entry.get('choices') else entry.get('text') or ''


def partial_of_message(message_id):
    return next((p['text'] for p in list(PARTIALS.values()) if p.get('messageId') == message_id and p.get('text')), '')


def job_view(job):
    """A job as the window and the phone get it: while it runs, with what has been written so far."""
    text = partial_text(job['id']) if job.get('status') == 'running' else ''
    view = {k: v for k, v in job.items() if k not in ('thinking', 'cliSession', 'cliPid', 'runner')}  # a CLI's thinking is fetched with a member's work only; its conversation id stays on the Mac
    view.update(progress_view(job))  # what it has done so far, and whether a stopped one is still ending (progress.py)
    return dict(view, partial=text) if text else view


def partial_feeder(kind, job_id):
    """feed(bytes) for a CLI's output as it arrives. Returns None for a CLI whose progress cannot be read."""
    if kind not in ('claude', 'antigravity', 'grok', 'codex', 'cursor'): return None
    pending, state = bytearray(), dict(text='', mark=None, fresh=False)

    def put(text):
        slot = PARTIALS.get(job_id)
        if slot is not None: slot['text'] = text[:MAX_PARTIAL]

    def add(piece, mark=None):
        if not isinstance(piece, str) or not piece: return
        if state['fresh'] or (mark is not None and mark != state['mark']): state.update(text='', fresh=False)  # the next message replaces the one before it
        state['mark'] = mark if mark is not None else state['mark']
        state['text'] += piece; put(state['text'])

    def line(raw):
        try: d = json.loads(raw)
        except ValueError: return
        if not isinstance(d, dict): return
        if kind == 'claude':
            if d.get('type') != 'stream_event' or d.get('parent_tool_use_id'): return  # a helper it started is not the reply
            event = d.get('event') if isinstance(d.get('event'), dict) else {}
            if event.get('type') == 'message_start': state['fresh'] = True  # kept on screen until the new message has its first words
            delta = event.get('delta') if isinstance(event.get('delta'), dict) else {}
            if event.get('type') == 'content_block_delta' and delta.get('type') == 'text_delta': add(delta.get('text'))
        elif kind == 'antigravity':
            step = d.get('step_update') if d.get('event') == 'step_update' and isinstance(d.get('step_update'), dict) else {}
            if step.get('step_type') == 'agent_response': add(step.get('text_delta'), mark=step.get('step_index'))
        elif kind == 'grok':
            if d.get('type') == 'text': add(d.get('data'))
        elif kind == 'cursor':  # small pieces carry timestamp_ms; the whole message follows without it; a tool call starts a new message
            if d.get('type') == 'tool_call': state['fresh'] = True
            message = d.get('message') if d.get('type') == 'assistant' and isinstance(d.get('message'), dict) else {}
            if message and 'timestamp_ms' in d:
                add(''.join(b.get('text', '') for b in message.get('content') or [] if isinstance(b, dict) and b.get('type') == 'text'))
        elif kind == 'codex':
            item = d.get('item') if d.get('type') == 'item.completed' and isinstance(d.get('item'), dict) else {}
            if item.get('type') == 'agent_message' and isinstance(item.get('text'), str): state['text'] = item['text']; put(state['text'])

    def feed(chunk):
        pending.extend(chunk)
        while True:
            end = pending.find(b'\n')
            if end < 0: break
            raw = bytes(pending[:end]); del pending[:end + 1]
            if raw.strip():
                try: line(raw.decode('utf-8', errors='replace'))
                except Exception: pass  # what is shown meanwhile must never stop the reply itself
        if len(pending) > 4 * 1024 * 1024: del pending[:]  # one endless line: not progress Zook can show
    return feed


def stream_route(handler, job_id):
    """GET /api/jobs/<id>/stream: server-sent events with what the reply has so far, until it is finished. Lock NOT held."""
    store = handler.server.store
    with store.lock: job = store.find('jobs', job_id)
    if not job: return handler.error(404, '找不到工作。')
    handler.send_response(200)
    for key, value in (('Content-Type', 'text/event-stream; charset=utf-8'), ('Cache-Control', 'no-store'), ('X-Accel-Buffering', 'no'), ('Connection', 'close')): handler.send_header(key, value)
    handler.end_headers()
    sent, quiet, until = '', 0.0, time.monotonic() + 1800
    def emit(obj): handler.wfile.write(('data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n').encode('utf-8')); handler.wfile.flush()
    try:
        while time.monotonic() < until:
            with store.lock:
                job = store.find('jobs', job_id); running = bool(job) and job['status'] == 'running'
            if not running: emit(dict(done=True)); return  # checked first: the words are cleared as the reply finishes, and that must not blank the screen
            text = partial_text(job_id)
            if text != sent:
                emit(dict(add=text[len(sent):]) if text.startswith(sent) and sent else dict(text=text)); sent, quiet = text, 0.0
            time.sleep(0.06); quiet += 0.06
            if quiet >= 15: handler.wfile.write(b': waiting\n\n'); handler.wfile.flush(); quiet = 0.0  # keeps the connection from being dropped as idle
    except (OSError, ValueError): pass  # the window went away
