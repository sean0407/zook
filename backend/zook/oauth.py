# Signing in to remote connectors in the browser (OAuth 2.1 with PKCE, as MCP servers ask for it).
# Tokens live only in the Keychain. Loaded by backend/server.py into one shared namespace.
OAUTH_TIMEOUT = 15
OAUTH_FLOW_MINUTES = 10
_oauth_lock = threading.Lock()   # one token refresh at a time
_BLOB_PART = 480                 # a Keychain entry holds one short line, so long tokens are kept in pieces


def blob_set(blob_id, value):
    """Keep a small dictionary in the Keychain."""
    text = base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode()
    pieces = [text[i:i + _BLOB_PART] for i in range(0, len(text), _BLOB_PART)]
    if not ACCOUNT_ID.fullmatch(blob_id or '') or len(pieces) > 40: raise RuntimeError('授權資料太大，無法保存。')
    blob_delete(blob_id)
    for index, piece in enumerate(pieces): secret_set(_blob_part_id(blob_id, index), 'part:' + piece)


def _blob_part_id(blob_id, index):
    return hashlib.sha256(('%s/%d' % (blob_id, index)).encode()).hexdigest()[:32]


def blob_get(blob_id):
    if not ACCOUNT_ID.fullmatch(blob_id or ''): return None
    pieces = []
    for index in range(40):
        piece = secret_get(_blob_part_id(blob_id, index))
        if not piece.startswith('part:'): break
        pieces.append(piece[5:])
    try: return json.loads(base64.urlsafe_b64decode(''.join(pieces))) if pieces else None
    except ValueError: return None


def blob_delete(blob_id):
    if not ACCOUNT_ID.fullmatch(blob_id or ''): return
    for index in range(40):
        part = _blob_part_id(blob_id, index)
        if not secret_get(part): break
        secret_delete(part)


def _oauth_url(url):
    """Only HTTPS, or plain HTTP on this Mac, and never with a password inside."""
    parsed = urllib.parse.urlparse(str(url or ''))
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or (parsed.scheme == 'http' and not local):
        raise RuntimeError('登入服務的網址無效。')
    return url


def _oauth_request(url, form=None, body=None, headers=None):
    """One request without following redirects. Returns (status, headers, parsed JSON or {})."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    data = urllib.parse.urlencode(form).encode() if form is not None else json.dumps(body).encode() if body is not None else None
    sent = dict({'Accept': 'application/json', 'User-Agent': 'Zook'}, **(headers or {}))
    if form is not None: sent['Content-Type'] = 'application/x-www-form-urlencoded'
    elif body is not None: sent['Content-Type'] = 'application/json'
    request = urllib.request.Request(_oauth_url(url), data=data, headers=sent, method='POST' if data is not None else 'GET')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=OAUTH_TIMEOUT) as response:
            status, got, raw = response.status, response.headers, response.read(1 << 20)
    except urllib.error.HTTPError as exc: status, got, raw = exc.code, exc.headers, exc.read(1 << 20)
    except (urllib.error.URLError, OSError, ValueError): raise RuntimeError('連不上登入服務，請確認網路後再試。')
    try: parsed = json.loads(raw) if raw else {}
    except ValueError: parsed = {}
    return status, got, parsed if isinstance(parsed, dict) else {}


def oauth_discover(mcp_url):
    """Where to sign in for this connector: its authorization server's endpoints."""
    parsed = urllib.parse.urlparse(_oauth_url(mcp_url)); origin = '%s://%s' % (parsed.scheme, parsed.netloc); path = parsed.path.rstrip('/')
    status, headers, _ = _oauth_request(mcp_url, body={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'zook', 'version': '1'}}},
                                        headers={'Accept': 'application/json, text/event-stream'})
    if status < 400: raise RuntimeError('這個連接器不需要登入。')
    hint = re.search(r'resource_metadata="([^"]+)"', headers.get('WWW-Authenticate', '') or '')
    resource = {}
    for candidate in ([hint.group(1)] if hint else []) + [origin + '/.well-known/oauth-protected-resource' + path, origin + '/.well-known/oauth-protected-resource']:
        try: code, _, found = _oauth_request(candidate)
        except RuntimeError: continue
        if code == 200 and found.get('authorization_servers'): resource = found; break
    servers = resource.get('authorization_servers') if isinstance(resource.get('authorization_servers'), list) else []
    issuer = str(servers[0]).rstrip('/') if servers else origin
    at = urllib.parse.urlparse(_oauth_url(issuer)); base = '%s://%s' % (at.scheme, at.netloc); tail = at.path.rstrip('/')
    for candidate in (base + '/.well-known/oauth-authorization-server' + tail, base + '/.well-known/openid-configuration' + tail, issuer + '/.well-known/openid-configuration'):
        try: code, _, meta = _oauth_request(candidate)
        except RuntimeError: continue
        if code == 200 and meta.get('authorization_endpoint') and meta.get('token_endpoint'):
            methods = meta.get('code_challenge_methods_supported')
            if isinstance(methods, list) and 'S256' not in methods: raise RuntimeError('這個連接器的登入方式不夠安全，Zook 不支援。')
            for key in ('authorization_endpoint', 'token_endpoint', 'registration_endpoint'):
                if meta.get(key): _oauth_url(meta[key])
            scopes = resource.get('scopes_supported') if isinstance(resource.get('scopes_supported'), list) else []
            return dict(authorize=meta['authorization_endpoint'], token=meta['token_endpoint'], register=meta.get('registration_endpoint') or '',
                        resource=str(resource.get('resource') or mcp_url), scope=' '.join(str(x) for x in scopes[:30]))
    raise RuntimeError('這個連接器不支援在瀏覽器登入。如果它使用金鑰，請用「編輯」貼上金鑰。')


def oauth_begin(app, record):
    """Start a sign-in. Returns the page to open in the browser."""
    if record.get('transport') != 'http': raise ValueError('只有遠端連接器可以登入。')
    meta = oauth_discover(record['url'])
    if not meta['register']: raise RuntimeError('這個連接器需要事先申請的應用程式編號，Zook 目前不支援。')
    redirect = 'http://127.0.0.1:%d/oauth/callback' % app.server_address[1]
    status, _, client = _oauth_request(meta['register'], body=dict(client_name='Zook', redirect_uris=[redirect], grant_types=['authorization_code', 'refresh_token'],
                                                                 response_types=['code'], token_endpoint_auth_method='none'))
    if status >= 300 or not isinstance(client.get('client_id'), str): raise RuntimeError('登入服務不接受 Zook 的登記，無法登入。')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    flows = app.__dict__.setdefault('oauth_flows', {})
    for old in [k for k, v in flows.items() if time.time() - v['at'] > OAUTH_FLOW_MINUTES * 60]: flows.pop(old, None)
    flows[state] = dict(connector=record['id'], verifier=verifier, meta=meta, client=client['client_id'], secret=client.get('client_secret') or '', redirect=redirect, at=time.time())
    query = dict(response_type='code', client_id=client['client_id'], redirect_uri=redirect, state=state, code_challenge=challenge, code_challenge_method='S256', resource=meta['resource'])
    if meta['scope']: query['scope'] = meta['scope']
    return meta['authorize'] + ('&' if '?' in meta['authorize'] else '?') + urllib.parse.urlencode(query)


def _oauth_keep(token, previous=None):
    """What is stored: the tokens and when the access token runs out."""
    if not isinstance(token.get('access_token'), str) or not token['access_token']: raise RuntimeError('登入服務沒有回傳授權。')
    try: life = max(60, int(token.get('expires_in') or 3600))
    except (TypeError, ValueError): life = 3600
    return dict(access=token['access_token'], refresh=token.get('refresh_token') or (previous or {}).get('refresh') or '', expiresAt=time.time() + life)


def oauth_finish(app, state, code):
    """The browser came back: trade the code for tokens and keep them in the Keychain."""
    flow = app.__dict__.get('oauth_flows', {}).pop(state, None) if isinstance(state, str) else None
    if not flow or time.time() - flow['at'] > OAUTH_FLOW_MINUTES * 60 or not isinstance(code, str) or not code: raise ValueError('這個登入連結已經失效，請回到 Zook 再按一次登入。')
    form = dict(grant_type='authorization_code', code=code, redirect_uri=flow['redirect'], client_id=flow['client'], code_verifier=flow['verifier'], resource=flow['meta']['resource'])
    if flow['secret']: form['client_secret'] = flow['secret']
    status, _, token = _oauth_request(flow['meta']['token'], form=form)
    if status >= 300: raise RuntimeError('登入沒有完成，請再試一次。')
    kept = dict(_oauth_keep(token), secret=flow['secret'])
    store = app.store
    with store.lock:
        record = next((c for c in store.data['connectors'] if c['id'] == flow['connector']), None)
        if not record: raise ValueError('找不到這個連接器。')
        blob_id = (record.get('oauth') or {}).get('secretId') or ID()
    blob_set(blob_id, kept)
    with store.lock:
        record = next((c for c in store.data['connectors'] if c['id'] == flow['connector']), None)
        if not record: blob_delete(blob_id); raise ValueError('找不到這個連接器。')
        record['oauth'] = dict(secretId=blob_id, clientId=flow['client'], tokenEndpoint=flow['meta']['token'], resource=flow['meta']['resource'], signedInAt=NOW())
        store.save()


def oauth_access(store, record):
    """A usable access token for this connector, refreshed when it is about to run out. '' when the user must sign in again."""
    info = record.get('oauth') or {}
    if not info.get('secretId') or info.get('needsLogin'): return ''
    with _oauth_lock:
        kept = blob_get(info['secretId'])
        if not kept: return _oauth_lost(store, record['id'])
        if kept['expiresAt'] - time.time() > 60: return kept['access']
        if not kept.get('refresh'): return _oauth_lost(store, record['id'])
        form = dict(grant_type='refresh_token', refresh_token=kept['refresh'], client_id=info['clientId'], resource=info.get('resource') or record['url'])
        if kept.get('secret'): form['client_secret'] = kept['secret']
        try: status, _, token = _oauth_request(info['tokenEndpoint'], form=form)
        except RuntimeError: return kept['access'] if kept['expiresAt'] > time.time() else ''  # offline: try again next time
        if status >= 300: return _oauth_lost(store, record['id'])
        try: fresh = dict(_oauth_keep(token, kept), secret=kept.get('secret') or ''); blob_set(info['secretId'], fresh)
        except RuntimeError: return _oauth_lost(store, record['id'])
        return fresh['access']


def _oauth_lost(store, connector_id):
    with store.lock:
        record = next((c for c in store.data['connectors'] if c['id'] == connector_id), None)
        if record and record.get('oauth') and not record['oauth'].get('needsLogin'): record['oauth']['needsLogin'] = True; store.save()
    return ''


def oauth_logout(store, connector_id):
    with store.lock:
        record = next((c for c in store.data['connectors'] if c['id'] == connector_id), None)
        info = record.pop('oauth', None) if record else None
        store.save()
    if info and info.get('secretId'): blob_delete(info['secretId'])


def oauth_page(message):
    return ('<!doctype html><meta charset="utf-8"><title>Zook</title><body style="font:16px -apple-system,sans-serif;display:grid;place-items:center;height:90vh;color:#333">'
            '<p>%s</p></body>' % html.escape(message)).encode()
