# Local scripts: a script or a terminal on this Mac can give a Bot a task and wait for its answer.
# Loaded by backend/server.py into one shared namespace.
#
# It is a second, separate listener with its own token, written to a folder only the user can read. It is off for every Bot
# until switched on for that Bot. It can list those Bots, send them a message and ask how a message is doing. It cannot change
# settings, permissions or keys, and cannot approve anything: a reply that needs approval waits for the user in Zook as always.
# A turn started this way has origin 'script', so it cannot set up schedules or write shared memories.
SCRIPT_RATE = 60          # messages per Bot per hour
SCRIPT_WAIT_MAX = 3600
SCRIPT_BODY_MAX = 128 * 1024
SCRIPT_CONNECTIONS = 32  # at once; more are turned away
SCRIPT_WAITING = 10       # of the 20 places in a Bot's line: the rest stay free for the user


def script_bots(store): return [b for b in store.data['bots'] if b.get('scripts') is True]


def script_find(store, name):
    """A Bot with local scripts on, by id or by name (case does not matter). None when there is none, or when the name fits several."""
    wanted = str(name or '').strip().lower()
    found = [b for b in script_bots(store) if b['id'] == name or b['name'].strip().lower() == wanted]
    return found[0] if len(found) == 1 else None


def script_delivery(store, bot, ident):
    """What became of a message. Lock held."""
    waiting = next((e for e in bot.get('queue') or [] if e['id'] == ident and e.get('origin') == 'script'), None)
    if waiting: return dict(id=ident, status='queued')
    # The id a script was given is the reply's id, or the id of its place in line, which the reply remembers.
    job = next((j for j in reversed(store.data['jobs']) if (j['id'] == ident or j.get('queueId') == ident) and j['botId'] == bot['id'] and j.get('origin') == 'script'), None)
    if not job: return None
    if job['status'] == 'running':
        asking = [a for a in job.get('approvals') or [] if a.get('status') == 'pending']
        return dict(id=ident, status='needs_approval' if asking else 'running', **({'waitingFor': str(asking[0].get('text') or asking[0].get('label') or '')[:200]} if asking else {}))
    out = dict(id=ident, status=job['status'])
    if job['status'] == 'completed': out['answer'] = job.get('content') or (find_message(bot, job.get('messageId')) or {}).get('content') or ''
    if job.get('error'): out['error'] = job['error']
    return out


class ScriptHandler(BaseHTTPRequestHandler):
    server_version = 'ZookScripts'; protocol_version = 'HTTP/1.0'
    timeout = 15  # a connection that sends nothing is dropped
    def log_message(self, *args): pass

    def handle(self):
        gate = self.server.api.gate
        if not gate.acquire(blocking=False): return  # too many at once: this one is closed unanswered
        try: super().handle()
        except (OSError, ValueError): pass
        finally: gate.release()

    def reply(self, code, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(raw)

    def allowed(self):
        """A web page must never reach this, even one that guessed the port: no browser origin, and the exact local host name."""
        api = self.server.api
        if self.headers.get('Origin') is not None or self.headers.get('Sec-Fetch-Site') is not None or self.headers.get('Referer') is not None: return False
        if self.headers.get('Host', '').lower() != '127.0.0.1:%d' % self.server.server_address[1]: return False
        given = self.headers.get('Authorization', '')
        return given.startswith('Bearer ') and secrets.compare_digest(given[7:].encode(), api.token.encode())

    def handle_request_safely(self, method):
        try:
            if not self.allowed(): return self.reply(403, {'error': 'forbidden'})
            parts = [unquote(p) for p in urlsplit(self.path).path.strip('/').split('/')]
            body = {}
            if method == 'POST':
                size = int(self.headers.get('Content-Length') or 0)
                if size <= 0 or size > SCRIPT_BODY_MAX: return self.reply(400, {'error': '內容無效或太大。'})
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict): return self.reply(400, {'error': '內容無效。'})
            return self.server.api.route(self, method, parts, body)
        except (ValueError, UnicodeError): return self.reply(400, {'error': '內容無效。'})
        except Exception: return self.reply(500, {'error': '處理要求時發生錯誤。'})

    def do_GET(self): self.handle_request_safely('GET')
    def do_POST(self): self.handle_request_safely('POST')


class ScriptApi:
    def __init__(self, app):
        self.app, self.token, self.sent, self.gate = app, secrets.token_urlsafe(32), {}, threading.BoundedSemaphore(SCRIPT_CONNECTIONS)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ScriptHandler); self.server.daemon_threads = True; self.server.api = self
        folder = app.store.dir / 'automation'
        folder.mkdir(mode=0o700, exist_ok=True); os.chmod(str(folder), 0o700)
        for name, text in (('url', 'http://127.0.0.1:%d\n' % self.server.server_address[1]), ('headers', 'Authorization: Bearer %s\n' % self.token)):
            fd = os.open(str(folder / name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(text)
            os.chmod(str(folder / name), 0o600)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown(); self.server.server_close()
        for name in ('url', 'headers'):
            try: os.unlink(str(self.app.store.dir / 'automation' / name))
            except OSError: pass

    def route(self, handler, method, parts, body):
        store = self.app.store
        if parts[:2] != ['v1', 'agents']: return handler.reply(404, {'error': '找不到資源。'})
        if method == 'GET' and len(parts) == 2:
            with store.lock: return handler.reply(200, {'agents': [dict(id=b['id'], name=b['name']) for b in script_bots(store)]})
        with store.lock: bot = script_find(store, parts[2]) if len(parts) >= 3 else None
        if not bot: return handler.reply(404, {'error': '找不到這個 Bot，或它沒有開啟「允許本機腳本」。'})
        if method == 'GET' and len(parts) == 5 and parts[3] == 'deliveries':
            with store.lock: found = script_delivery(store, bot, parts[4])
            return handler.reply(200, found) if found else handler.reply(404, {'error': '找不到這次送出的紀錄。'})
        if method == 'POST' and len(parts) == 4 and parts[3] == 'messages':
            content = body.get('content')
            if not isinstance(content, str) or not content.strip() or len(content) > 30000: return handler.reply(400, {'error': '訊息內容無效。'})
            wait = body.get('wait', 0)
            if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 0 <= wait <= SCRIPT_WAIT_MAX: return handler.reply(400, {'error': 'wait 要在 0 到 %d 秒之間。' % SCRIPT_WAIT_MAX})
            if body.get('id') is not None and (not isinstance(body['id'], str) or not SEND_ID.fullmatch(body['id'])):
                return handler.reply(400, {'error': 'id 要是 8 到 64 個英數字、底線或連字號。'})  # refused out loud: a key that is silently ignored would start a second reply
            once = send_key('script:' + bot['id'], dict(clientId=body.get('id'), content=content))
            inventory = inventory_for(store)
            with store.lock:
                bot = script_find(store, bot['id'])
                if not bot: return handler.reply(404, {'error': '找不到這個 Bot，或它沒有開啟「允許本機腳本」。'})
                seen = send_seen(self.app, once)
                if seen: ident = seen['id']
                else:
                    now = time.time(); recent = self.sent[bot['id']] = [t for t in self.sent.get(bot['id'], []) if now - t < 3600]
                    if len(recent) >= SCRIPT_RATE: return handler.reply(429, {'error': '這個 Bot 一小時內已收到 %d 則腳本訊息，請稍後再送。' % SCRIPT_RATE})
                    chat_id = script_chat(bot)  # its own conversation, apart from the ones the user types in
                    try: ident = self.app.send_to_bot(bot, content, inventory, author='本機腳本', origin='script', chat_id=chat_id)['id']
                    except Busy as exc:
                        if not queue_on(store): return handler.reply(409, {'error': str(exc)})
                        if sum(1 for e in bot.get('queue') or [] if e.get('origin') == 'script') >= SCRIPT_WAITING: return handler.reply(429, {'error': '這個 Bot 已有 %d 則腳本訊息在排隊，請等它處理完再送。' % SCRIPT_WAITING})
                        try: ident = queue_add(store, bot, dict(content=content), origin='script', chat_id=chat_id)['id']
                        except ValueError as exc2: return handler.reply(400, {'error': str(exc2)})
                    except (ValueError, RuntimeError) as exc: return handler.reply(400, {'error': str(exc)})
                    recent.append(now); send_remember(self.app, once, {'id': ident})
            end = time.time() + wait
            while True:
                with store.lock:
                    bot = store.find('bots', bot['id'])
                    found = script_delivery(store, bot, ident) if bot and bot.get('scripts') is True else None
                if not found: return handler.reply(404, {'error': '這則訊息已被取消。'})
                if found['status'] in ('completed', 'failed', 'cancelled', 'needs_approval') or time.time() >= end: return handler.reply(202 if found['status'] in ('running', 'queued') else 200, found)
                time.sleep(0.3)
        return handler.reply(404, {'error': '找不到資源。'})
