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


def _is_local_host(host):
    """This Mac, or an address inside a private network, in any of the spellings a system accepts (127.1, 2130706433, localhost.)."""
    host = str(host or '').strip().rstrip('.').lower()
    if not host or host == 'localhost' or host.endswith('.localhost'): return True
    try: address = ipaddress.ip_address(host)
    except ValueError:
        try: address = ipaddress.ip_address(socket.inet_aton(host)) if re.fullmatch(r'[0-9a-fx.]+', host) else None
        except OSError: address = None
    if address is None: return False
    return address.is_loopback or address.is_private or address.is_link_local or address.is_unspecified or address.is_reserved or address in ipaddress.ip_network('100.64.0.0/10') if address.version == 4 else \
        address.is_loopback or address.is_private or address.is_link_local or address.is_unspecified or address.is_reserved or bool(address.ipv4_mapped and _is_local_host(str(address.ipv4_mapped)))


def _place(parsed):
    """Scheme, host and port, with the default port filled in, for comparing two addresses."""
    try: port = parsed.port
    except ValueError: port = -1
    return parsed.scheme, (parsed.hostname or '').rstrip('.').lower(), port or {'https': 443, 'http': 80}.get(parsed.scheme)


def _oauth_url(url, local=False):
    """Only HTTPS and never with a password inside. Addresses on this Mac or a private network are allowed only for a connector that is itself local."""
    parsed = urllib.parse.urlparse(str(url or ''))
    inside = _is_local_host(parsed.hostname or '')
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or (inside and not local) or (parsed.scheme == 'http' and not (inside and local)):
        raise RuntimeError('登入服務的網址無效。')
    return url


def _same_place(url, local):
    return _is_local_host(urllib.parse.urlparse(str(url or '')).hostname or '') if local is None else local


def _oauth_request(url, form=None, body=None, headers=None, local=False):
    """One request without following redirects. Returns (status, headers, parsed JSON or {})."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    data = urllib.parse.urlencode(form).encode() if form is not None else json.dumps(body).encode() if body is not None else None
    sent = dict({'Accept': 'application/json', 'User-Agent': 'Zook'}, **(headers or {}))
    if form is not None: sent['Content-Type'] = 'application/x-www-form-urlencoded'
    elif body is not None: sent['Content-Type'] = 'application/json'
    request = urllib.request.Request(_oauth_url(url, local), data=data, headers=sent, method='POST' if data is not None else 'GET')
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
    local = _is_local_host(urllib.parse.urlparse(str(mcp_url or '')).hostname or '')
    parsed = urllib.parse.urlparse(_oauth_url(mcp_url, local)); origin = '%s://%s' % (parsed.scheme, parsed.netloc); path = parsed.path.rstrip('/')
    status, headers, _ = _oauth_request(mcp_url, body={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'zook', 'version': '1'}}},
                                        headers={'Accept': 'application/json, text/event-stream'}, local=local)
    if status < 400: raise RuntimeError('這個連接器不需要登入。')
    hint = re.search(r'resource_metadata="([^"]+)"', headers.get('WWW-Authenticate', '') or '')
    resource = {}
    for candidate in ([hint.group(1)] if hint else []) + [origin + '/.well-known/oauth-protected-resource' + path, origin + '/.well-known/oauth-protected-resource']:
        try: code, _, found = _oauth_request(candidate, local=local)
        except RuntimeError: continue
        if code == 200 and found.get('authorization_servers'): resource = found; break
    # The token must be meant for this connector. A connector naming some other service as its resource would be handed that service's token.
    named = urllib.parse.urlparse(str(resource.get('resource') or mcp_url)); named_path = named.path.rstrip('/')
    if _place(named) != _place(parsed) or named.username or named.password or not (path == named_path or path.startswith(named_path + '/')):
        raise RuntimeError('這個連接器宣告的登入對象和它的網址不一致，為了安全不進行登入。')
    servers = resource.get('authorization_servers') if isinstance(resource.get('authorization_servers'), list) else []
    issuer = str(servers[0]).rstrip('/') if servers else origin
    at = urllib.parse.urlparse(_oauth_url(issuer, local)); base = '%s://%s' % (at.scheme, at.netloc); tail = at.path.rstrip('/')
    for candidate in (base + '/.well-known/oauth-authorization-server' + tail, base + '/.well-known/openid-configuration' + tail, issuer + '/.well-known/openid-configuration'):
        try: code, _, meta = _oauth_request(candidate, local=local)
        except RuntimeError: continue
        if code == 200 and meta.get('authorization_endpoint') and meta.get('token_endpoint'):
            if meta.get('issuer') and str(meta['issuer']).rstrip('/') != issuer: raise RuntimeError('登入服務回報的身分和連接器指定的不一致，為了安全不進行登入。')
            methods = meta.get('code_challenge_methods_supported')
            if isinstance(methods, list) and 'S256' not in methods: raise RuntimeError('這個連接器的登入方式不夠安全，Zook 不支援。')
            for key in ('authorization_endpoint', 'token_endpoint', 'registration_endpoint'):
                if meta.get(key): _oauth_url(meta[key], local)
            scopes = resource.get('scopes_supported') if isinstance(resource.get('scopes_supported'), list) else []
            return dict(authorize=meta['authorization_endpoint'], token=meta['token_endpoint'], register=meta.get('registration_endpoint') or '',
                        resource=str(resource.get('resource') or mcp_url), scope=' '.join(str(x) for x in scopes[:30]), local=local)
    raise RuntimeError('這個連接器不支援在瀏覽器登入。如果它使用金鑰，請用「編輯」貼上金鑰。')


def oauth_begin(app, record):
    """Start a sign-in. Returns the page to open in the browser."""
    if record.get('transport') != 'http': raise ValueError('只有遠端連接器可以登入。')
    meta = oauth_discover(record['url'])
    if not meta['register']: raise RuntimeError('這個連接器需要事先申請的應用程式編號，Zook 目前不支援。')
    redirect = 'http://127.0.0.1:%d/oauth/callback' % app.server_address[1]
    status, _, client = _oauth_request(meta['register'], local=meta['local'], body=dict(client_name='Zook', redirect_uris=[redirect], grant_types=['authorization_code', 'refresh_token'],
                                                                 response_types=['code'], token_endpoint_auth_method='none'))
    if status >= 300 or not isinstance(client.get('client_id'), str): raise RuntimeError('登入服務不接受 Zook 的登記，無法登入。')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    flows = app.__dict__.setdefault('oauth_flows', {})
    for old in [k for k, v in flows.items() if time.time() - v['at'] > OAUTH_FLOW_MINUTES * 60]: flows.pop(old, None)
    flows[state] = dict(connector=record['id'], url=record['url'], verifier=verifier, meta=meta, client=client['client_id'], secret=client.get('client_secret') or '', redirect=redirect, at=time.time())
    query = dict(response_type='code', client_id=client['client_id'], redirect_uri=redirect, state=state, code_challenge=challenge, code_challenge_method='S256', resource=meta['resource'])
    if meta['scope']: query['scope'] = meta['scope']
    return meta['authorize'] + ('&' if '?' in meta['authorize'] else '?') + urllib.parse.urlencode(query)


def _oauth_keep(token, previous=None):
    """What is stored: the tokens and when the access token runs out."""
    if not isinstance(token.get('access_token'), str) or not token['access_token']: raise RuntimeError('登入服務沒有回傳授權。')
    try: life = int(token.get('expires_in')) if token.get('expires_in') is not None else 3600
    except (TypeError, ValueError): life = 3600
    life = max(1, life)
    return dict(access=token['access_token'], refresh=token.get('refresh_token') or (previous or {}).get('refresh') or '', expiresAt=time.time() + life, life=life)


def oauth_finish(app, state, code):
    """The browser came back: trade the code for tokens and keep them in the Keychain."""
    flow = app.__dict__.get('oauth_flows', {}).pop(state, None) if isinstance(state, str) else None
    if not flow or time.time() - flow['at'] > OAUTH_FLOW_MINUTES * 60 or not isinstance(code, str) or not code: raise ValueError('這個登入連結已經失效，請回到 Zook 再按一次登入。')
    form = dict(grant_type='authorization_code', code=code, redirect_uri=flow['redirect'], client_id=flow['client'], code_verifier=flow['verifier'])
    if flow['meta']['resource']: form['resource'] = flow['meta']['resource']
    if flow['secret']: form['client_secret'] = flow['secret']
    status, _, token = _oauth_request(flow['meta']['token'], form=form, local=flow['meta'].get('local', False))
    if status >= 300: raise RuntimeError('登入沒有完成，請再試一次。')
    kept = dict(_oauth_keep(token), secret=flow['secret'])
    store = app.store
    if flow.get('kind') == 'google': return google_finish(store, flow, kept)
    changed = '這個連接器在登入期間被改過，請再登入一次。'
    with store.lock:
        record = next((c for c in store.data['connectors'] if c['id'] == flow['connector']), None)
        if not record or record.get('url') != flow['url']: raise ValueError(changed)
    blob_id = ID(); blob_set(blob_id, kept)  # always a new Keychain item, so another address's sign-in is never written over
    with store.lock:
        record = next((c for c in store.data['connectors'] if c['id'] == flow['connector']), None)
        fits = bool(record) and record.get('url') == flow['url']
        if fits:
            old = (record.get('oauth') or {}).get('secretId')
            record['oauth'] = dict(secretId=blob_id, clientId=flow['client'], tokenEndpoint=flow['meta']['token'], resource=flow['meta']['resource'], url=flow['url'], local=flow['meta'].get('local', False), signedInAt=NOW())
            store.save()
    if not fits: blob_delete(blob_id); raise ValueError(changed)
    if old: blob_delete(old)


def oauth_access(store, record):
    """A usable access token for this connector, refreshed when it is about to run out. '' when the user must sign in again."""
    info = record.get('oauth') or {}
    if info.get('url') != record.get('url'): return ''  # the token was issued for another address
    return oauth_token(info, info.get('resource') or record.get('url'), lambda: _oauth_lost(store, record['id']))


def oauth_token(info, resource, lost):
    """The access token kept for this sign-in, refreshed when needed. Calls lost() and returns '' when the user must sign in again."""
    if not info.get('secretId') or info.get('needsLogin'): return ''
    with _oauth_lock:
        kept = blob_get(info['secretId'])
        if not kept: return lost()
        if kept['expiresAt'] - time.time() > min(1200, kept.get('life', 3600) / 2): return kept['access']  # a reply can run for 15 minutes
        if not kept.get('refresh'): return kept['access'] if kept['expiresAt'] - time.time() > min(30, kept.get('life', 3600) / 4) else lost()
        form = dict(grant_type='refresh_token', refresh_token=kept['refresh'], client_id=info['clientId'])
        if resource: form['resource'] = resource
        if kept.get('secret'): form['client_secret'] = kept['secret']
        still = kept['access'] if kept['expiresAt'] - time.time() > min(30, kept.get('life', 3600) / 4) else ''
        try: status, _, token = _oauth_request(info['tokenEndpoint'], form=form, local=bool(info.get('local')))
        except RuntimeError: return still  # offline: try again next time
        if status >= 300:  # only a clear refusal means signing in again; a busy or broken service is tried again later
            return lost() if status in (400, 401) and token.get('error') in ('invalid_grant', 'invalid_client', 'unauthorized_client', 'invalid_token') else still
        try: fresh = dict(_oauth_keep(token, kept), secret=kept.get('secret') or ''); blob_set(info['secretId'], fresh)
        except RuntimeError: return still  # an answer without a token is a fault on their side, not a refusal
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


# ---- Google account (Gmail, Calendar, Drive) with the user's own Google Cloud client.
GOOGLE_ID = 'builtin:google'
GOOGLE_READ = ('https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/drive.readonly')
GOOGLE_WRITE = ('https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/drive.file')


def _google_endpoints():
    test = os.environ.get('ZOOK_GOOGLE_API', '')  # tests point this at a stand-in on this Mac
    at = urllib.parse.urlparse(test)
    if at.scheme == 'http' and at.hostname == '127.0.0.1' and not at.username and not at.password: return test + '/authorize', test + '/token', test + '/gmail/v1/users/me/profile'
    return 'https://accounts.google.com/o/oauth2/v2/auth', 'https://oauth2.googleapis.com/token', 'https://gmail.googleapis.com/gmail/v1/users/me/profile'


def google_begin(app, client_id, client_secret, write):
    """Start signing in to Google. Returns the page to open in the browser."""
    if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]{10,200}', client_id.strip()): raise ValueError('用戶端編號格式不對，請從 Google Cloud 複製完整的一串。')
    if not isinstance(client_secret, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{8,200}', client_secret.strip()): raise ValueError('用戶端密鑰格式不對，請從 Google Cloud 複製完整的一串。')
    authorize, token, _ = _google_endpoints()
    redirect = 'http://127.0.0.1:%d/oauth/callback' % app.server_address[1]
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    flows = app.__dict__.setdefault('oauth_flows', {})
    flows[state] = dict(kind='google', connector='', url='', verifier=verifier, meta=dict(token=token, resource='', local=_same_place(token, None)), client=client_id.strip(), secret=client_secret.strip(), redirect=redirect, write=bool(write), at=time.time())
    query = dict(response_type='code', client_id=client_id.strip(), redirect_uri=redirect, state=state, code_challenge=challenge, code_challenge_method='S256',
                 scope=' '.join(GOOGLE_READ + (GOOGLE_WRITE if write else ())), access_type='offline', prompt='consent')
    return authorize + '?' + urllib.parse.urlencode(query)


def google_finish(store, flow, kept):
    if not kept.get('refresh'): raise RuntimeError('Google 沒有給長期授權，請再登入一次並同意所有項目。')
    try: _, _, profile = _oauth_request(_google_endpoints()[2], headers={'Authorization': 'Bearer ' + kept['access']}, local=flow['meta']['local'])
    except RuntimeError: profile = {}
    with store.lock: old = dict(store.data['settings'].get('google') or {})
    blob_id = old.get('secretId') or ID(); blob_set(blob_id, kept)
    with store.lock:
        st = store.data['settings']
        st['google'] = dict(secretId=blob_id, clientId=flow['client'], tokenEndpoint=flow['meta']['token'], local=flow['meta']['local'], write=flow['write'], email=str(profile.get('emailAddress') or '')[:200], signedInAt=NOW())
        st['sharedMcp'] = list(dict.fromkeys((st.get('sharedMcp') or []) + [GOOGLE_ID])); store.save()


def google_access(store):
    with store.lock: info = dict(store.data['settings'].get('google') or {})
    def lost():
        with store.lock:
            now = store.data['settings'].get('google')
            if now and not now.get('needsLogin'): now['needsLogin'] = True; store.save()
        return ''
    return oauth_token(info, '', lost)


def google_logout(store):
    with store.lock:
        st = store.data['settings']; info = st.pop('google', None)
        st['sharedMcp'] = [x for x in st.get('sharedMcp') or [] if x != GOOGLE_ID]; store.save()
    if info and info.get('secretId'): blob_delete(info['secretId'])


def oauth_needs_login(store, connector_id):
    """True only after the sign-in was really refused, not while its service is merely unreachable."""
    with store.lock:
        record = next((c for c in store.data['connectors'] if c['id'] == connector_id), None) or {}
        info = record.get('oauth') or {}
        return bool(info.get('needsLogin')) or bool(info) and info.get('url') != record.get('url')


def google_needs_login(store):
    with store.lock: return bool((store.data['settings'].get('google') or {}).get('needsLogin'))
