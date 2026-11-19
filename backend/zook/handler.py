# The HTTP API and startup. Loaded by backend/server.py into one shared namespace.
class Handler(BaseHTTPRequestHandler):
    server_version = 'Zook'; sys_version = ''
    def log_message(self, *args): pass

    def codex_live_quota(self, account=None):
        """Codex limits straight from the CLI, at most once a minute per account."""
        store, app = self.server.store, self.server
        key = 'codex' + ('@' + account['id'] if account else '')
        caches = app.__dict__.setdefault('codex_quota_caches', {})
        hit = caches.get(key)
        if hit and time.time() - hit[0] < 60: return hit[1]
        try: live = normalize_quota('codex', codex_rpc(find_cli('codex'), 'account/rateLimits/read', {}, provider_env('codex', account)))
        except (OSError, ValueError, TimeoutError, AttributeError, RuntimeError): live = None
        if not live: return None
        live.update(updatedAt=NOW(), source='live'); caches[key] = (time.time(), live)
        with store.lock: store.data.setdefault('quota', {})[key] = live; store.save()
        return live

    def antigravity_live_quota(self):
        store, app = self.server.store, self.server
        caches = app.__dict__.setdefault('codex_quota_caches', {}); hit = caches.get('antigravity')
        if hit and time.time() - hit[0] < 60: return hit[1]
        try: live = antigravity_quota(find_cli('antigravity'))
        except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError): live = None
        caches['antigravity'] = (time.time(), live)  # a failed read is not retried on every page load either
        if not live: return None
        with store.lock: store.data.setdefault('quota', {})['antigravity'] = live; store.save()
        return live

    def quota(self):
        store = self.server.store
        result = []
        phone = bool(getattr(self, 'device', None))  # a paired phone only shows the main sign-ins of the three big CLIs
        for provider in [x for x in P.active_ids(store.data) if not phone or x in ('codex', 'claude', 'grok')]:
            account = account_status(provider)
            with store.lock: snap = copy.deepcopy(store.data.get('quota', {}).get(provider))
            if provider == 'codex' and account['status'] == 'logged_in': snap = self.codex_live_quota() or snap
            if provider == 'antigravity' and account['status'] == 'logged_in': snap = self.antigravity_live_quota() or snap
            if provider not in ('codex', 'claude', 'antigravity'): snap = None  # the other CLIs do not report plan limits to Zook
            profiles = []
            for extra in [] if phone else [a for a in store.data.get('accounts') or [] if a.get('provider') == provider]:
                try: view = account_view(extra)
                except (OSError, ValueError, RuntimeError): view = dict(id=extra['id'], name=extra['name'], type=extra['type'], status='unknown', method='', plan='', email='')
                billed = extra['type'] == 'key' or view.get('method') in ('Anthropic Console', 'API 金鑰')
                with store.lock:
                    used = provider_usage(store, provider, extra['id']); saved = copy.deepcopy(store.data.get('quota', {}).get(provider + '@' + extra['id']))
                if provider == 'codex' and view['status'] == 'logged_in' and not billed: saved = self.codex_live_quota(extra) or saved
                profiles.append(dict(view, zookUsage=used, quota=saved if provider in ('codex', 'claude') else None, apiBilling=billed, noQuotaApi=provider not in ('codex', 'claude')))
            with store.lock: zook = provider_usage(store, provider)
            result.append(dict(id=provider, name=account['name'], vendor=(P.spec(store.data, provider) or {}).get('vendor', ''), zookUsage=zook,
                               status=account['status'], method=account['method'], noQuotaApi=provider not in ('codex', 'claude', 'antigravity'),
                               plan=(snap or {}).get('plan') or account['plan'], email=account['email'], workspace=account.get('workspace', ''), quota=snap,
                               apiBilling=account['method'] in ('Anthropic Console', 'API 金鑰'), profiles=profiles))
        with store.lock:
            known = store.data.setdefault('autoStatus', {}); known.update(merge_auto_status(known, {x['id']: auto_state(x['id'], x['status'], x['method']) for x in result if x['id'] in AUTO_MODELS}))
            allowed = auto_allowed(store)
            for item in result:
                if item['id'] in AUTO_MODELS: item.update(autoOn=item['id'] in allowed, autoBilled=auto_known_billed(store.data['autoStatus'].get(item['id'])))
        return {'providers': result}

    def detect_usage(self):
        """偵測使用量: read fresh limits for every signed-in account. Claude only reports them with a reply, so each subscription gets one tiny request."""
        store, app = self.server.store, self.server
        app.__dict__.setdefault('codex_quota_caches', {}).clear()
        targets = []
        if 'claude' in P.active_ids(store.data):
            main = account_status('claude')
            if main['status'] == 'logged_in' and main['method'] != 'Anthropic Console': targets.append(None)
            for extra in [a for a in store.data.get('accounts') or [] if a.get('provider') == 'claude' and a.get('type') == 'login']:
                view = account_view(extra)
                if view['status'] == 'logged_in' and view['method'] != 'Anthropic Console': targets.append(extra)
        def probe(extra):
            try: app.record_quota('claude', claude_quota_probe(provider_env('claude', extra) if extra else None), extra['id'] if extra else '', 'probe')
            except (RuntimeError, OSError, subprocess.TimeoutExpired): pass
        threads = [threading.Thread(target=probe, args=(x,), daemon=True) for x in targets]
        for t in threads: t.start()
        for t in threads: t.join(100)
        app.claude_probe_at = time.time()
        return self.quota()

    def accounts(self, parts):
        logins = self.server.logins
        if len(parts) == 2 and self.command == 'GET':
            items = []
            data = self.server.store.data
            for provider, flow in list(logins.items()):  # remember the account a Zook-run sign-in reported (keys are provider or provider@account)
                if flow.state == 'succeeded' and not getattr(flow, 'recorded', False):
                    found = re.search(r'[Ss]igned in as\s+(\S+@\S+)', '\n'.join(flow.lines))
                    with self.server.store.lock:
                        if found: data.setdefault('accountInfo', {})[provider] = {'email': found.group(1).rstrip('.,')}
                        self.server.store.save()
                    flow.recorded = True
            for provider in P.active_ids(data):
                item = account_status(provider); flow = logins.get(provider); inst = self.server.installs.get(provider)
                s = P.spec(data, provider) or {}
                if inst and inst.state != 'running' and not getattr(inst, 'version_refreshed', False):
                    _version_cache.pop(provider, None); inst.version_refreshed = True
                ver = provider_version(provider)
                item.update(version={k: ver[k] for k in ('current', 'latest', 'updateAvailable', 'error')} if ver else None)
                item.update(login=flow.view() if flow else None, install=inst.view() if inst else None, loginMethods=[dict(id=m, label=l) for m, l in login_methods(provider)],
                            canInstall=bool(s.get('install') or s.get('update')), terminalLogin=bool(s.get('terminal_login')), installCommand=s.get('install', ''), canUpdate=bool(s.get('update')),
                            canLogout=bool(provider in ('codex', 'claude') or s.get('logout')), removable=provider not in P.DEFAULT_ADDED,
                            requires=s.get('requires', ''), requirementMet=not s.get('requires') or bool(P.find_binary(s['requires'])),
                            config={k: s.get(k, '') for k in ('command', 'args', 'model_args', 'install', 'login', 'status')} if s.get('custom') else None,
                            models=s.get('models', []) if s.get('custom') else None)
                profiles = []
                for account in [a for a in data.get('accounts') or [] if a.get('provider') == provider]:
                    try: view = account_view(account)
                    except (OSError, ValueError, RuntimeError): view = dict(id=account['id'], name=account['name'], type=account['type'], status='unknown', method='', plan='', email='')
                    sub = logins.get(provider + '@' + account['id'])
                    view['login'] = sub.view() if sub else None
                    profiles.append(view)
                record = (data.get('providerIssues') or {}).get(provider)
                item.update(issue=(record or {}).get('issue', '') if item['status'] == 'logged_in' else '', needsCheck=provider_needs_check(s, item['status'], record))
                item.update(ability_view(self.server.store, provider))
                item.update(profiles=profiles, canAddLogin=bool(provider in ACCOUNT_HOME and login_methods(provider)), canAddKey=provider in ACCOUNT_KEYS)
                items.append(item)
            return self.respond(200, {'providers': items, 'catalog': P.catalog_view(data)})
        if len(parts) == 3 and parts[2] == 'custom' and self.command == 'POST':
            store = self.server.store
            with store.lock:
                ids = set(P.CATALOG) | {c['id'] for c in P.custom_list(store.data)}
                item = P.validate_custom(self.body(), ids)
                store.data['customProviders'] = [c for c in P.custom_list(store.data) if c['id'] != item['id']] + [item]
                store.save()
            return self.respond(201, item)
        if len(parts) < 4 or self.command != 'POST' or not P.spec(self.server.store.data, parts[2]): return self.error(404, '找不到資源。')
        provider, action = parts[2], '/'.join(parts[3:])
        body = self.body(); store = self.server.store
        account = None
        if body.get('account'):
            account = find_account(body['account'], provider) if isinstance(body['account'], str) else None
            if not account: return self.error(404, '找不到這個帳號。')
        login_key = provider + ('@' + account['id'] if account else '')
        flow = logins.get(login_key)
        try:
            if action == 'profiles':
                name, kind, key = body.get('name'), body.get('type'), body.get('key')
                if not isinstance(name, str) or not name.strip() or len(name) > 60: raise ValueError('請輸入帳號名稱。')
                if kind == 'login' and not (provider in ACCOUNT_HOME and login_methods(provider)): raise ValueError('這個模型不支援再登入一個帳號，請改用 API 金鑰。')
                if kind == 'key' and provider not in ACCOUNT_KEYS: raise ValueError('這個模型不支援 API 金鑰。')
                if kind not in ('login', 'key'): raise ValueError('帳號類型無效。')
                with store.lock:
                    if any(a['provider'] == provider and a['name'] == name.strip() for a in store.data['accounts']): raise ValueError('已經有同名的帳號。')
                new = dict(id=ID(), provider=provider, name=name.strip(), type=kind, createdAt=NOW())
                if kind == 'key': secret_set(new['id'], key.strip() if isinstance(key, str) else '')
                if provider in ACCOUNT_HOME: account_dir(new['id'])
                with store.lock: store.data['accounts'].append(new); store.save()
                return self.respond(201, new)
            if action == 'profiles/delete':
                if not account: raise ValueError('帳號無效。')
                if flow and flow.state == 'running': flow.cancel()
                logins.pop(login_key, None)
                with store.lock:
                    store.data['accounts'] = [a for a in store.data['accounts'] if a['id'] != account['id']]
                    for b in store.data['bots']:
                        if b.get('account') == account['id']: b['account'] = ''  # back to the CLI's own sign-in
                    (store.data.get('accountInfo') or {}).pop(login_key, None); (store.data.get('quota') or {}).pop(login_key, None); store.save()
                secret_delete(account['id'])
                shutil.rmtree(str(_active['dir'] / 'accounts' / account['id']), ignore_errors=True)
                return self.respond(200, {'ok': True})
            if action == 'add':
                with self.server.store.lock:
                    st = self.server.store.data['settings']
                    st['addedProviders'] = list(dict.fromkeys(list(st.get('addedProviders') or P.DEFAULT_ADDED) + [provider]))
                    st['hiddenProviders'] = [x for x in st.get('hiddenProviders') or [] if x != provider]; self.server.store.save()
                return self.respond(200, {'ok': True})
            if action == 'remove':
                store = self.server.store
                with store.lock:
                    if provider in P.DEFAULT_ADDED: return self.error(409, '內建的 Codex 和 Claude 不能移除。')
                    users = [b['name'] for b in store.data['bots'] if b.get('provider') == provider]
                    if users or store.data['settings'].get('provider') == provider:
                        return self.error(409, '還有 Bot 或預設設定在使用這個提供者：' + ('、'.join(users) or '預設模型') + '。請先改用其他提供者。')
                    if provider.startswith(P.CUSTOM_PREFIX): store.data['customProviders'] = [c for c in P.custom_list(store.data) if c['id'] != provider]
                    else:
                        st = store.data['settings']; st['hiddenProviders'] = list(dict.fromkeys((st.get('hiddenProviders') or []) + [provider]))
                        st['addedProviders'] = [x for x in st.get('addedProviders') or P.DEFAULT_ADDED if x != provider]
                    store.save()
                return self.respond(200, {'ok': True})
            if action == 'install':
                inst = self.server.installs.get(provider)
                if inst and inst.state == 'running': return self.error(409, '安裝流程已在進行中。')
                self.server.installs[provider] = LoginFlow(provider, install_args(provider), failure='安裝沒有完成，請確認網路連線後再試。')
                return self.respond(202, self.server.installs[provider].view())
            if action == 'check':  # one tiny request, to learn whether this sign-in can really be used
                path = find_cli(provider); s = P.spec(self.server.store.data, provider) or {}
                if not path or not s.get('signed_in_file'): raise ValueError('這個模型不需要檢查。')
                try:
                    with tempfile.TemporaryDirectory() as empty:  # an empty folder: nothing there can change how Gemini behaves
                        done = subprocess.run([path, '-p', 'Reply with OK'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=provider_env(provider), timeout=90, cwd=empty)
                except subprocess.TimeoutExpired:
                    self.server.note_provider_issue(provider, '', unsure=True); return self.respond(200, {'issue': ''})
                issue = cli_issue(done.stderr.decode('utf-8', 'replace')) if done.returncode else ''
                self.server.note_provider_issue(provider, issue, unsure=bool(done.returncode and not issue))
                return self.respond(200, {'issue': issue})
            if action == 'terminal-login':
                path = find_cli(provider); s = P.spec(self.server.store.data, provider) or {}
                if not path or not s.get('terminal_login'): raise ValueError('這個模型不能用終端機登入。')
                folder = _active['dir'] / 'tools'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                script = folder / (provider + '-login.command')
                script.write_text('#!/bin/sh\nexec %s\n' % shlex.quote(path), encoding='utf-8'); script.chmod(0o700); _agy_status.clear()
                subprocess.run(['/usr/bin/open', str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=True)
                return self.respond(200, {'ok': True})
            if action == 'install/cancel':
                inst = self.server.installs.get(provider)
                if inst: inst.cancel()
                return self.respond(200, inst.view() if inst else {'state': 'idle'})
            if action == 'login':
                if flow and flow.state == 'running': return self.error(409, '登入流程已在進行中。')
                default = (login_methods(provider) or [('', '')])[0][0]
                if account and account['type'] != 'login': raise ValueError('API 金鑰帳號不需要登入。')
                logins[login_key] = LoginFlow(provider, login_args(provider, body.get('method') or default), account)
                return self.respond(202, logins[login_key].view())
            if action == 'login/cancel':
                if flow: flow.cancel()
                return self.respond(200, flow.view() if flow else {'state': 'idle'})
            if action == 'login/code':
                code = body.get('code')
                if not flow or not isinstance(code, str) or not code.strip() or len(code) > 2000: raise ValueError('授權碼無效。')
                flow.send(code); return self.respond(200, flow.view())
            if action == 'logout':
                if flow and flow.state == 'running': flow.cancel()
                p = subprocess.run(logout_args(provider), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=provider_env(provider, account), timeout=20)
                logins.pop(login_key, None)
                with self.server.store.lock:
                    (self.server.store.data.get('accountInfo') or {}).pop(login_key, None); (self.server.store.data.get('providerIssues') or {}).pop(login_key, None); self.server.store.save()
                return self.respond(200, {'ok': p.returncode == 0})
        except ValueError as exc: return self.error(400, str(exc))
        except (RuntimeError, OSError) as exc: return self.error(409, str(exc) if isinstance(exc, RuntimeError) else '無法執行 CLI。')
        except subprocess.TimeoutExpired: return self.error(504, 'CLI 沒有回應。')
        return self.error(404, '找不到資源。')
    def respond(self, code, data, content_type='application/json; charset=utf-8'):
        raw = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
        note_request(self, code, data)
        self.send_response(code); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(raw)))
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors %s" % ("'self'" if content_type == 'application/pdf' else "'none'")); self.send_header('Cache-Control', 'private, max-age=86400' if content_type == 'image/png' else 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers(); self.wfile.write(raw)
    def error(self, code, message): self.respond(code, {'error': message})
    def authorized(self):
        port = self.server.server_address[1]
        if self.headers.get('Host', '').lower() not in ('127.0.0.1:%d' % port, 'localhost:%d' % port, '[::1]:%d' % port): return False
        token = self.headers.get('Authorization', '')
        cookie = http.cookies.SimpleCookie()
        try: cookie.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError: pass
        value = cookie['swarmr_session'].value if 'swarmr_session' in cookie else ''
        self.via_bridge = False
        bridge = self.server.bridge_token
        if bridge and secrets.compare_digest(token, 'Bearer ' + bridge): self.via_bridge = True; return True
        return secrets.compare_digest(token, 'Bearer '+self.server.token) or secrets.compare_digest(value, self.server.token)
    def body(self, limit=MAX_BODY):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n <= 0 or n > limit: raise ValueError()
            obj = json.loads(self.rfile.read(n))
            if not isinstance(obj, dict): raise ValueError()
            self.last_body = obj
            return obj
        except (ValueError, UnicodeError): raise ValueError('無效或過大的 JSON。')
    def dispatch(self):
        path = urlsplit(self.path).path
        parts = [unquote(p) for p in path.strip('/').split('/')]
        if len(parts) == 3 and parts[:2] == ['api', 'worker']:
            port = self.server.server_address[1]
            if self.command != 'POST' or self.headers.get('Host', '').lower() not in ('127.0.0.1:%d' % port, 'localhost:%d' % port): return self.error(403, '禁止存取。')
            with self.server.store.lock:
                if parts[2].startswith('live-'):  # a CLI kept open between messages: the reply it is answering right now
                    worker, job = live_worker(self.server, parts[2], self.headers.get('Authorization', '')); authorized = bool(worker and job and job['status'] == 'running')
                else:
                    worker = self.server.workers.get(parts[2]); job = self.server.store.find('jobs', parts[2])
                    authorized = worker and job and job['status'] == 'running' and secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+worker['token'])
            if not authorized: return self.error(403, '禁止存取。')
            try:
                body = self.body(); method = body.get('method'); params = body.get('params', {})
                if method == 'tools/list': return self.respond(200, {'tools': worker['tools']})
                if method == 'tools/call' and isinstance(params, dict) and isinstance(params.get('name'), str) and isinstance(params.get('arguments', {}), dict):
                    return self.respond(200, worker['session'].call(params['name'], params.get('arguments', {})))
                return self.error(400, '無效的工具要求。')
            except (ValueError, RuntimeError): return self.error(400, '工具要求失敗。')
        if path == '/oauth/callback' and self.command == 'GET':
            # The browser returning from a connector's sign-in page. It has no Zook session, so the one-time state is what proves it.
            port = self.server.server_address[1]
            if self.headers.get('Host', '').lower() not in ('127.0.0.1:%d' % port, 'localhost:%d' % port): return self.error(403, '禁止存取。')
            query = parse_qs(urlsplit(self.path).query)
            if query.get('error'): self.server.__dict__.get('oauth_flows', {}).pop((query.get('state') or [''])[0], None); return self.respond(200, oauth_page('登入已取消，可以關閉這個分頁。'), 'text/html; charset=utf-8')
            try: oauth_finish(self.server, (query.get('state') or [''])[0], (query.get('code') or [''])[0])
            except (ValueError, RuntimeError) as exc: return self.respond(400, oauth_page(str(exc)), 'text/html; charset=utf-8')
            return self.respond(200, oauth_page('登入完成，可以關閉這個分頁，回到 Zook。'), 'text/html; charset=utf-8')
        if not self.authorized(): return self.error(403, '禁止存取。')
        if self.command in ('POST', 'PATCH', 'DELETE'):
            if not path.startswith(('/api/chat', '/api/groups/', '/api/jobs/', '/api/approvals/', '/api/mobile/')) or '/files' in path: forget_discovered()  # a change made in Zook shows at once; sending a message does not rescan
            origin = self.headers.get('Origin')
            if origin and origin not in ('http://127.0.0.1:%d' % self.server.server_address[1], 'http://localhost:%d' % self.server.server_address[1]):
                return self.error(403, '來源不符。')
        path = urlsplit(self.path).path
        parts = [unquote(p) for p in path.strip('/').split('/')]
        store = self.server.store
        if self.command != 'GET' and len(parts) >= 3 and parts[1] in ('bots', 'groups', 'mobile'): store.chat_touch(parts[3] if parts[1] == 'mobile' and len(parts) >= 4 else parts[2])  # its conversations are looked at when this request saves
        self.device = None
        self.hint = activity_hint(store, parts) if self.command in ('PATCH', 'DELETE', 'POST') else ''
        try:
            if self.via_bridge:
                device_id = self.headers.get('X-Zook-Device')
                if device_id is None:
                    if path.startswith('/api/remote/bridge/'): return self.server.bridge_request(self, self.command, path)
                    return self.error(403, '禁止存取。')
                # A paired device, reached through the relay. Checked on every request, so a revoked device stops at once.
                with store.lock:
                    self.device = next((d for d in store.data.get('remoteDevices', []) if d['id'] == device_id), None)
                    if self.device: self.device['lastSeenAt'] = NOW()
                if not self.device: return self.error(401, '這台裝置尚未配對或已被撤銷。')
                if not device_may(self.command, path): return self.error(403, '這個動作只能在 Mac 上進行。')
                if path == '/api/remote/me': return self.respond(200, {'id': self.device['id'], 'name': self.device['name']})
            elif path.startswith('/api/remote/bridge/'): return self.error(403, '禁止存取。')
            if self.command == 'POST' and path == '/api/choose-folder':
                # The Mac's own folder chooser. Never reachable from a paired device (not in DEVICE_ALLOWED).
                try:
                    done = subprocess.run(['/usr/bin/osascript', '-e', 'tell me to activate', '-e', 'POSIX path of (choose folder with prompt "選擇這個 Bot 可以使用的資料夾")'],
                                          capture_output=True, text=True, timeout=600)
                except subprocess.TimeoutExpired: return self.respond(200, {'path': ''})
                chosen = done.stdout.strip() if done.returncode == 0 else ''
                return self.respond(200, {'path': str(pathlib.Path(chosen).resolve()) if chosen and pathlib.Path(chosen).is_dir() else ''})
            if self.command == 'POST' and path == '/api/mobile/bots':
                body = self.body()
                with store.lock: bot = mobile_create_bot(store, body)
                return self.respond(201, dict(id=bot['id'], name=bot['name']))
            if path == '/api/mobile/schedules' and self.command == 'GET':
                with store.lock: return self.respond(200, mobile_schedules(store))
            if len(parts) == 4 and parts[:3] == ['api', 'mobile', 'schedules'] and self.command == 'POST':
                try:
                    with store.lock: mobile_schedule_action(store, parts[3], self.body().get('action'))
                except LookupError as exc: return self.error(404, str(exc))
                except ValueError as exc: return self.error(400, str(exc))
                return self.respond(200, {'ok': True})
            if path == '/api/mobile/photos' and self.command == 'POST':
                if not mobile_photo_allowed(self.server, (self.device or {}).get('id', '')): return self.error(429, '照片傳得太頻繁，請稍後再試。')
                try: return self.respond(201, mobile_photo(store, self.body()))
                except ValueError as exc: return self.error(400, str(exc))
            if len(parts) == 5 and parts[:3] == ['api', 'mobile', 'bots'] and parts[4] == 'chats' and self.command == 'POST':
                try:
                    with store.lock:
                        bot = store.find('bots', parts[3])
                        if not bot: return self.error(404, '找不到機器人。')
                        mobile_chat_switch(store, bot, self.body())
                except ValueError as exc: return self.error(400, str(exc))
                except RuntimeError as exc: return self.error(409, str(exc))
                return self.respond(200, {'ok': True})
            if self.command == 'GET' and path == '/api/mobile/settings':
                inventory = inventory_for(store)   # reads files; never under the store lock
                with store.lock: view = mobile_settings(store, inventory)
                view['thisDevice'] = (self.device or {}).get('id')
                return self.respond(200, view)
            if self.command == 'GET' and parts[:2] == ['api', 'mobile']:
                with store.lock:
                    if path == '/api/mobile/home': return self.respond(200, mobile_home(store))
                    if len(parts) == 4 and parts[2] in ('bots', 'groups'):
                        item = store.find(parts[2], parts[3])
                        if not item: return self.error(404, '找不到這個對話。')
                        return self.respond(200, mobile_bot(store, item) if parts[2] == 'bots' else mobile_group(store, item))
                return self.error(404, '找不到資源。')
            if path == '/api/remote' and self.command == 'GET': return self.respond(200, self.server.remote_view())
            if path == '/api/remote/pairing' and self.command == 'POST':
                try: return self.respond(200, self.server.start_pairing())
                except RuntimeError as exc: return self.error(409, str(exc))
            if path == '/api/remote/pairing' and self.command == 'DELETE':
                with store.lock: self.server.pairing = None
                return self.respond(200, {'ok': True})
            if len(parts) == 4 and parts[:3] == ['api', 'remote', 'devices'] and self.command == 'DELETE':
                with store.lock:
                    before = len(store.data.get('remoteDevices', []))
                    store.data['remoteDevices'] = [d for d in store.data.get('remoteDevices', []) if d['id'] != parts[3]]
                    if len(store.data['remoteDevices']) == before: return self.error(404, '找不到這台裝置。')
                    store.save()
                return self.respond(200, self.server.remote_view())
            if self.command == 'GET' and path == '/api/models':
                params = parse_qs(urlsplit(self.path).query)
                provider = params.get('provider', [''])[0]
                if not P.spec(store.data, provider): return self.error(400, '供應商無效。')
                return self.respond(200, model_list(provider))
            if self.command == 'GET' and path == '/api/integrations': return self.respond(200, integrations(self.server.store))
            if self.command == 'GET' and len(parts) == 3 and parts[:2] == ['api', 'icons']:
                png = icon_png(self.server.store, parts[2])
                return self.respond(200, png, 'image/png') if png else self.error(404, '沒有這個圖示。')
            if path == '/api/providers' and self.command == 'GET':
                data = self.server.store.data
                return self.respond(200, {'providers': [dict(id=pid, name=provider_label(pid), installed=bool(find_cli(pid)), tools=bool((P.spec(data, pid) or {}).get('tools')), features=feature_support(provider_kind(pid)),
                                                             accounts=[dict(id=a['id'], name=a['name'], type=a['type']) for a in data.get('accounts') or [] if a.get('provider') == pid])
                                                        for pid in P.active_ids(data)]})
            if parts[:2] == ['api', 'accounts']:
                return self.accounts(parts)
            if path == '/api/update' and self.command == 'GET':
                if self.server.store.data['settings'].get('autoUpdateCheck', True): threading.Thread(target=self.server.updater.check, daemon=True).start()
                return self.respond(200, self.server.updater.view())
            if path in ('/api/update/check', '/api/update/download', '/api/update/apply') and self.command == 'POST':
                try:
                    if path.endswith('check'): self.server.updater.check(force=True)
                    elif path.endswith('download'): self.server.updater.download()
                    else: self.server.updater.apply()
                except RuntimeError as exc: return self.error(409, str(exc))
                return self.respond(200, self.server.updater.view())
            if path == '/api/quota' and self.command == 'GET':
                if parse_qs(urlsplit(self.path).query).get('auto', [''])[0] == '1': self.server.auto_claude_quota()
                return self.respond(200, self.quota())
            if path == '/api/quota/detect' and self.command == 'POST' and not self.device:
                self.body(); return self.respond(200, self.detect_usage())
            if path == '/api/quota/claude/refresh' and self.command == 'POST':
                self.body()
                self.server.claude_probe_at = time.time()
                try: self.server.record_quota('claude', claude_quota_probe())
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc: return self.error(409, str(exc) if isinstance(exc, RuntimeError) else '無法查詢 Claude 額度。')
                with store.lock: store.data['quota']['claude']['source'] = 'probe'; store.save()
                return self.respond(200, self.quota())
            if path == '/api/usage/overview' and self.command == 'GET':
                try: span = int((parse_qs(urlsplit(self.path).query).get('days') or ['30'])[0])
                except ValueError: span = 0
                with store.lock: return self.respond(200, usage_overview(store, span))
            if path == '/api/usage/bots' and self.command == 'GET':
                with store.lock: return self.respond(200, bot_usage(store))
            if len(parts) in (4, 5, 6) and parts[:2] == ['api', 'bots'] and parts[3] == 'outputs' and not self.device:
                with store.lock: bot = copy.deepcopy(store.find('bots', parts[2]))
                if not bot: return self.error(404, '找不到機器人。')
                if len(parts) == 4 and self.command == 'GET': return self.respond(200, {'outputs': bot_outputs(store, bot)})
                item = bot_output(store, bot, parts[4])
                if not item: return self.error(404, '找不到這個檔案，可能已經被移走或刪除。')
                if len(parts) == 5 and self.command == 'GET':
                    try: data, kind = output_response(item)
                    except ValueError as exc: return self.error(413, str(exc))
                    except OSError: return self.error(404, '找不到這個檔案，可能已經被移走或刪除。')
                    return self.respond(200, data, kind)
                if len(parts) == 6 and parts[5] == 'reveal' and self.command == 'POST':
                    subprocess.run(['/usr/bin/open', '-R', item['path']], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    return self.respond(200, {'ok': True})
                return self.error(404, '找不到資源。')
            if path == '/api/google' and self.command in ('POST', 'DELETE') and not self.device:
                if self.command == 'DELETE': google_logout(store, (parse_qs(urlsplit(self.path).query).get('account') or [None])[0]); return self.respond(200, {'ok': True})
                body = self.body()
                try: url = google_begin(self.server, body.get('clientId'), body.get('clientSecret'), body.get('write') is True, add=body.get('add') is True)
                except ValueError as exc: return self.error(400, str(exc))
                if not os.environ.get('ZOOK_NO_BROWSER'): subprocess.run(['/usr/bin/open', _oauth_url(url, _same_place(url, None))], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                return self.respond(200, {'url': url})
            if path == '/api/gmail' and self.command in ('POST', 'DELETE'):
                with store.lock: saved = dict(store.data['settings'].get('gmail') or {})
                if self.command == 'DELETE':
                    with store.lock:
                        st = store.data['settings']; st.pop('gmail', None)
                        st['sharedMcp'] = [x for x in st.get('sharedMcp') or [] if x != GMAIL_ID]; store.save()
                    if saved.get('secretId'): secret_delete(saved['secretId'])
                    return self.respond(200, {'ok': True})
                body = self.body(); address, password = body.get('address'), body.get('password')
                if not isinstance(address, str) or not re.fullmatch(r'[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}', address.strip()): return self.error(400, '請輸入完整的 Gmail 信箱。')
                password = re.sub(r'\s+', '', password) if isinstance(password, str) else ''
                if not re.fullmatch(r'[A-Za-z0-9]{16}', password): return self.error(400, '應用程式密碼是 16 個英文字母。請貼上 Google 產生的那一組，不是你的 Google 登入密碼。')
                try:
                    gmail_check(address.strip(), password)
                    secret_id = saved.get('secretId') or ID(); secret_set(secret_id, password)
                except RuntimeError as exc: return self.error(409, str(exc))
                with store.lock:
                    st = store.data['settings']; st['gmail'] = dict(address=address.strip(), secretId=secret_id)
                    st['sharedMcp'] = list(dict.fromkeys((st.get('sharedMcp') or []) + [GMAIL_ID])); store.save()
                return self.respond(200, {'ok': True, 'address': address.strip()})
            if len(parts) == 4 and parts[:2] == ['api', 'jobs'] and parts[3] == 'stream' and self.command == 'GET' and not self.device: return stream_route(self, parts[2])
            if parts[:2] == ['api', 'sync']: return sync_route(self, store, parts, path)
            if len(parts) == 5 and parts[:2] == ['api', 'bots'] and parts[3] == 'queue' and self.command == 'DELETE':
                with store.lock:
                    bot = store.find('bots', parts[2])
                    if not bot: return self.error(404, '找不到機器人。')
                    return self.respond(200, {'ok': True}) if queue_cancel(store, bot, parts[4]) else self.error(409, '這則訊息已經送出了。')
            if len(parts) == 4 and parts[:2] == ['api', 'bots'] and parts[3] == 'restore' and self.command == 'POST' and not self.device:
                self.body()
                with store.lock: bot = restore_bot(store, parts[2]); store.save()
                return self.respond(200, bot)
            if path == '/api/skill-templates' and self.command == 'GET': return self.respond(200, dict(items=template_view(store)))
            if path == '/api/skills/template' and self.command == 'POST' and not self.device: return self.respond(201, template_add(store, self.body().get('id')))
            if path == '/api/skills/import' and self.command == 'POST':
                ids = self.body().get('ids')
                if not isinstance(ids, list) or len(ids) > 1024 or any(not isinstance(x, str) for x in ids): return self.error(400, '請選擇要匯入的 Skill。')
                return self.respond(200, skills_import(store, inventory_for(store), ids))
            if parts[:2] == ['api', 'skills'] and len(parts) in (3, 4) and parts[2] != 'import':
                with store.lock: record = next((dict(x) for x in store.data['skills'] if x['id'] == parts[2]), None)
                if not record: return self.error(404, '找不到這個 Skill。')
                if len(parts) == 3 and self.command == 'DELETE':
                    with store.lock:
                        store.data['skills'] = [x for x in store.data['skills'] if x['id'] != record['id']]
                        st = store.data['settings']; st['disabledSkills'] = [x for x in st['disabledSkills'] if x != ZOOK_SKILL + record['id']]
                        store.save()
                    shutil.rmtree(str(store.dir / 'skills' / record['folder']), ignore_errors=True)
                    return self.respond(200, {'ok': True})
                if len(parts) == 4 and parts[3] == 'update' and self.command == 'POST':
                    self.body()
                    if not record.get('originPath') or not os.path.isfile(os.path.join(record['originPath'], 'SKILL.md')): return self.error(409, '找不到原本的來源，無法更新。')
                    try: skill_copy(record['originPath'], store.dir / 'skills' / record['folder'])
                    except ValueError as exc: return self.error(400, str(exc))
                    except OSError: return self.error(409, '讀不到原本來源的檔案。')
                    with store.lock:
                        for x in store.data['skills']:
                            if x['id'] == record['id']: x['stamp'] = skill_stamp(record['originPath'])
                        store.save()
                    return self.respond(200, {'ok': True})
                return self.error(404, '找不到資源。')
            if path == '/api/connector-copy' and self.command == 'POST':
                ident = self.body().get('id'); found = inventory_for(store)
                entry = next((m for m in found['mcp'] if m['id'] == ident and m.get('copyable')), None); config = found['_private']['mcp'].get(ident)
                if not entry or not isinstance(config, dict): return self.error(404, '找不到這個連接器，或它已經複製過了。')
                with store.lock:
                    if any(same_name(c['name']) == same_name(entry['name']) for c in store.data['connectors']): return self.error(400, 'Zook 已經有同名的連接器。')
                try:
                    record, secrets_found = connector_from_config(entry['name'][:80], config)
                    connector_keep_secrets(record, secrets_found)
                except ValueError as exc: return self.error(400, str(exc))
                record['origin'] = ident
                with store.lock:
                    store.data['connectors'].append(record)
                    st = store.data['settings']; shared = st.get('sharedMcp') or []; was_on = ident in shared
                    st['sharedMcp'] = [x for x in shared if x != ident] + (['zook:' + record['id']] if was_on else [])
                    store.save()
                return self.respond(201, dict(id='zook:' + record['id'], name=record['name'], on=was_on))
            if path == '/api/pack' and self.command == 'GET':
                try: raw, skill_count, connector_count = pack_export(store)
                except ValueError as exc: return self.error(400, str(exc))
                return self.respond(200, dict(name='Zook-設定包-%s.zookpack' % datetime.date.today().strftime('%Y%m%d'), data=base64.b64encode(raw).decode(), skills=skill_count, connectors=connector_count))
            if path == '/api/pack' and self.command == 'POST':
                try:
                    raw = base64.b64decode(self.body(PACK_BYTES * 2).get('data') or '', validate=True)
                    if not raw or len(raw) > PACK_BYTES: raise ValueError('設定包超過 150 MB，無法匯入。')
                    return self.respond(200, pack_import(store, raw))
                except ValueError as exc: return self.error(400, str(exc) if '設定包' in str(exc) else '這不是 Zook 的設定包，或檔案已損壞。')
            if path == '/api/connector-catalog' and self.command == 'GET' and not self.device: return self.respond(200, catalog_view(store))
            if len(parts) == 3 and parts[:2] == ['api', 'connector-catalog'] and self.command == 'POST' and not self.device:
                try: record, url = catalog_add(self.server, parts[2], self.body().get('key'))
                except LookupError as exc: return self.error(404, str(exc))
                except ValueError as exc: return self.error(400, str(exc))
                except RuntimeError as exc: return self.error(409, str(exc))
                except OSError: return self.error(500, '沒有加入：無法儲存設定。')
                if url and not os.environ.get('ZOOK_NO_BROWSER'): subprocess.run(['/usr/bin/open', _oauth_url(url)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                return self.respond(200, dict(id='zook:' + record['id'], name=record['name'], login=bool(url)))
            if len(parts) == 4 and parts[:2] == ['api', 'connectors'] and parts[3] == 'account' and self.command == 'POST' and not self.device:
                body = self.body()
                try: oauth_switch(store, parts[2], body.get('account'), body.get('name'))
                except LookupError as exc: return self.error(404, str(exc))
                except ValueError as exc: return self.error(400, str(exc))
                return self.respond(200, {'ok': True})
            if path == '/api/google/account' and self.command == 'POST' and not self.device:
                try: google_switch(store, self.body().get('account'))
                except LookupError as exc: return self.error(404, str(exc))
                return self.respond(200, {'ok': True})
            if len(parts) == 4 and parts[:2] == ['api', 'connectors'] and parts[3] in ('login', 'logout') and self.command == 'POST' and not self.device:
                with store.lock: record = copy.deepcopy(next((c for c in store.data['connectors'] if c['id'] == parts[2]), None))
                if not record: return self.error(404, '找不到這個連接器。')
                body = self.body()
                if parts[3] == 'logout': oauth_logout(store, record['id'], body.get('account') if isinstance(body.get('account'), str) else None); return self.respond(200, {'ok': True})
                try: url = oauth_begin(self.server, record, add=body.get('add') is True)
                except ValueError as exc: return self.error(400, str(exc))
                except RuntimeError as exc: return self.error(409, str(exc))
                if not os.environ.get('ZOOK_NO_BROWSER'): subprocess.run(['/usr/bin/open', _oauth_url(url, _is_local_host(urllib.parse.urlparse(record['url']).hostname or ''))], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                return self.respond(200, {'url': url})
            if parts[:2] == ['api', 'connectors'] and len(parts) in (2, 3):
                body = self.body() if self.command in ('POST', 'PATCH') else {}
                try:
                    with store.lock: existing = next((c for c in store.data['connectors'] if len(parts) == 3 and c['id'] == parts[2]), None)
                    if len(parts) == 3 and not existing: return self.error(404, '找不到這個連接器。')
                    if (len(parts) == 2 and self.command == 'POST') or (existing and self.command == 'PATCH'):
                        record, secret = connector_fields(body, existing)
                        with store.lock:
                            if any(c['name'] == record['name'] and c['id'] != record['id'] for c in store.data['connectors']): raise ValueError('已經有同名的連接器。')
                        if secret:
                            record['secretId'] = record['secretId'] or ID(); secret_set(record['secretId'], secret)
                        elif not record['secretName'] and record['secretId']:
                            secret_delete(record['secretId']); record['secretId'] = ''
                        more = body.get('moreSecrets') if isinstance(body.get('moreSecrets'), dict) else {}
                        for key, value in more.items():  # keys a copied or imported connector carries besides the main one
                            if key in record['moreSecrets'] and isinstance(value, str) and value.strip():
                                record['moreSecrets'][key] = record['moreSecrets'][key] or ID(); secret_set(record['moreSecrets'][key], value.strip())
                        with store.lock:
                            current = next((c for c in store.data['connectors'] if c['id'] == record['id']), None) or {}
                            stale = current.get('oauth')  # read now, so a sign-in that just finished is not lost
                            drop = connector_blob_ids(current)
                            if stale and record['transport'] == 'http' and record['url'] == current.get('url') and not secret:  # still the same sign-ins
                                record['oauth'] = stale; drop = []
                                if current.get('otherAccounts'): record['otherAccounts'] = current['otherAccounts']
                            store.data['connectors'] = [c for c in store.data['connectors'] if c['id'] != record['id']] + [record]
                            for blob in drop: blob_delete(blob)  # the address or the way to sign in changed
                            if not existing:  # a connector you just added is switched on for every Bot
                                st = store.data['settings']; st['sharedMcp'] = list(dict.fromkeys((st.get('sharedMcp') or []) + ['zook:' + record['id']]))
                            store.save()
                        return self.respond(200 if existing else 201, dict(id='zook:' + record['id'], name=record['name']))
                    if existing and self.command == 'DELETE':
                        with store.lock:
                            store.data['connectors'] = [c for c in store.data['connectors'] if c['id'] != existing['id']]
                            st = store.data['settings']; st['sharedMcp'] = [x for x in st.get('sharedMcp') or [] if x != 'zook:' + existing['id']]
                            store.save()
                        for secret_id in connector_secret_ids(existing): secret_delete(secret_id)
                        for blob in connector_blob_ids(existing): blob_delete(blob)
                        return self.respond(200, {'ok': True})
                except ValueError as exc: return self.error(400, str(exc))
                except RuntimeError as exc: return self.error(409, str(exc))
                return self.error(404, '找不到資源。')
            if len(parts) == 4 and parts[:2] == ['api', 'mcp'] and parts[3] == 'test' and self.command == 'POST':
                self.body()
                return self.respond(200, runtime_module().test_connection(parts[2], inventory_for(self.server.store)))
            if path == '/api/uploads' and self.command == 'POST' and not self.device:
                # One attached file, sent as the raw request body; the name comes in X-File-Name.
                try: size = int(self.headers.get('Content-Length', '0'))
                except ValueError: size = 0
                if size <= 0: return self.error(400, '檔案是空的。')
                if size > MAX_UPLOAD: self.close_connection = True; return self.error(413, '單一檔案不能超過 20 MB。')
                name = upload_name(unquote(self.headers.get('X-File-Name', '')))
                upload_id = ID(); folder = store.dir / 'uploads' / upload_id
                folder.mkdir(parents=True, mode=0o700)
                remaining = size
                with open(folder / 'file', 'wb') as out:
                    while remaining:
                        chunk = self.rfile.read(min(remaining, 1 << 20))
                        if not chunk: break
                        out.write(chunk); remaining -= len(chunk)
                if remaining: shutil.rmtree(str(folder), ignore_errors=True); return self.error(400, '檔案沒有傳完整。')
                meta = dict(id=upload_id, name=name, size=size, kind='image' if pathlib.Path(name).suffix.lower() in IMAGE_TYPES else 'file', createdAt=NOW())
                (folder / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
                return self.respond(201, meta)
            if len(parts) == 4 and parts[:2] == ['api', 'groups'] and parts[3] == 'files' and self.command == 'POST' and not self.device:
                try: size = int(self.headers.get('Content-Length', '0'))
                except ValueError: size = 0
                if size <= 0: return self.error(400, '檔案是空的。')
                if size > MAX_UPLOAD: self.close_connection = True; return self.error(413, '單一檔案不能超過 20 MB。')
                with store.lock:
                    if not store.find('groups', parts[2]): self.close_connection = True; return self.error(404, '找不到群組。')
                incoming = store.dir / 'group-files'; incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
                temp = incoming / ('.incoming-' + ID()); remaining = size
                try:
                    with open(temp, 'wb') as out:
                        while remaining:
                            chunk = self.rfile.read(min(remaining, 1 << 20))
                            if not chunk: break
                            out.write(chunk); remaining -= len(chunk)
                    if remaining: return self.error(400, '檔案沒有傳完整。')
                    with store.lock:
                        group = store.find('groups', parts[2])
                        if not group: return self.error(404, '找不到群組。')
                        try: name = add_group_file(store, group, unquote(self.headers.get('X-File-Name', '')), temp, size, '你')
                        except ValueError as exc: return self.error(400, str(exc))
                        store.save()
                    return self.respond(201, {'name': name})
                finally:
                    if temp.exists(): temp.unlink()
            if len(parts) == 3 and parts[:2] == ['api', 'uploads'] and self.command == 'GET' and not self.device:
                meta = upload_meta(store, parts[2])
                if not meta: return self.error(404, '找不到這個檔案。')
                data = (store.dir / 'uploads' / meta['id'] / 'file').read_bytes()
                kind = IMAGE_TYPES.get(pathlib.Path(meta['name']).suffix.lower())
                return self.respond(200, data, kind or 'application/octet-stream')
            if path == '/api/team/draft' and self.command == 'POST' and not self.device:  # one model call; never under the store lock
                try: return self.respond(200, self.server.draft_team(self.body().get('goal'), inventory_for(store)))
                except RuntimeError as exc: return self.error(502, str(exc))
            if path == '/api/team' and self.command == 'POST' and not self.device:
                body = self.body()
                with store.lock: return self.respond(201, self.server.create_team(body))
            inventory = None
            if (path in ('/api/chat', '/api/chat/redo') and self.command == 'POST') or (parts[:2] == ['api', 'bots'] and self.command in ('POST', 'PATCH')) or (len(parts) == 4 and parts[:2] == ['api', 'schedules']):
                inventory = inventory_for(store)
            with store.lock:
                if self.command == 'GET' and path == '/api/state':
                    for b in store.data['bots']: ensure_chats(b)  # Bots added by an import, too
                    if (parse_qs(urlsplit(self.path).query).get('since') or [''])[0] == str(store.rev): return self.respond(200, {'unchanged': True, 'rev': store.rev})
                    return self.respond(200, state_view(store, whole=(parse_qs(urlsplit(self.path).query).get('full') or [''])[0] == '1'))  # full=1: every conversation whole, as before paging
                if self.command == 'GET' and path == '/api/notifications':
                    try: after = int((parse_qs(urlsplit(self.path).query).get('after') or ['0'])[0])
                    except ValueError: after = 0
                    return self.respond(200, dict(seq=self.server.notice_seq, items=[n for n in self.server.notices if n['seq'] > after]))
                if self.command == 'GET' and path == '/api/diagnostics': return self.respond(200, dict(providers=provider_info(), python=__import__('platform').python_version(), system=__import__('platform').system()))
                if self.command == 'GET' and path == '/api/usage': return self.respond(200, usage())
                if self.command == 'POST' and path == '/api/export': return self.respond(200, store.data)
                if parts[:2] == ['api', 'backups'] or path in ('/api/activity', '/api/budget'): return upkeep_route(self, store, parts, path)
                if self.command == 'GET' and (path == '/api/search' or (len(parts) == 4 and parts[:2] == ['api', 'bots'] and parts[3] == 'messages')): return paging_route(self, store, parts, path)
                if len(parts) == 3 and parts[:2] == ['api', 'jobs'] and self.command == 'GET':
                    job = store.find('jobs', parts[2]); return self.respond(200, job_view(job)) if job else self.error(404, '找不到工作。')
                if len(parts) == 3 and parts[:2] == ['api', 'approvals'] and self.command == 'POST':
                    body = self.body(); decision = body.get('decision')
                    if decision not in ('approve', 'deny'): raise ValueError('決定無效。')
                    for job in store.data['jobs']:
                        approval = next ( (x for x in job.get('approvals', []) if x['id'] == parts[2]), None)
                        if approval:
                            if job['status'] != 'running' or approval['status'] != 'pending': return self.error(409, '此審批已結束。')
                            approval['status'] = 'approved' if decision == 'approve' else 'denied'; store.save()
                            log_activity(store, 'approval', ('核准：' if decision == 'approve' else '拒絕：') + (approval.get('text') or describe_call(dict(approval, name=approval.get('name')))) + '（%s）' % self.server.target_name('bot', job['botId']),
                                         by=('手機：' + str(self.device.get('name') or '已配對裝置')) if self.device else '')
                            event = self.server.approval_events.get(approval['id'])
                            if event: event.set()
                            return self.respond(200, approval)
                    return self.error(404, '找不到審批。')
                if len(parts) == 3 and parts[:2] == ['api', 'questions'] and self.command == 'POST':
                    status, out = answer_question(self.server, parts[2], self.body(), by=('手機：' + str(self.device.get('name') or '已配對裝置')) if self.device else '')
                    return self.respond(200, out) if status == 200 else self.error(status, out)
                if len(parts) == 4 and parts[:2] == ['api', 'jobs'] and parts[3] == 'cancel'  and self.command == 'POST':
                    job = store.find('jobs', parts[2])
                    if not job: return self.error(404, '找不到工作。')
                    self.server.cancel_job(job)
                    return self.respond(200, job)
                if path == '/api/chat' and self.command == 'POST':
                    body = self.body(); bot = store.find('bots', body.get('botId'))
                    if not bot: return self.error(404, '找不到機器人。')
                    if self.device and isinstance(body.get('attachments'), list) and len(body['attachments']) > MOBILE_PHOTOS: return self.error(400, '手機每則訊息最多 %d 張照片。' % MOBILE_PHOTOS)
                    once = send_key('bot:' + bot['id'], body); sent = send_seen(self.server, once)
                    if sent: return self.respond(202, dict(sent, duplicate=True))  # the same message again: its answer was lost on the way
                    if queue_on(store) and bot.get('queue'):  # others are already waiting: this one goes behind them, even in the moment between two replies
                        waiting = {'queued': True, 'queueId': queue_add(store, bot, body)['id']}
                        send_remember(self.server, once, waiting)
                        threading.Thread(target=self.server.queue_drain, args=(bot['id'],), daemon=True).start()
                        return self.respond(202, waiting)
                    try: job = self.server.send_to_bot(bot, body.get('content'), inventory, attachments=attachments_for(store, body.get('attachments')), effort=body.get('effort'),
                                                         plan=body.get('plan', False), long=body.get('long', False))
                    except Busy as exc:
                        if not queue_on(store): return self.error(409, str(exc))
                        waiting = {'queued': True, 'queueId': queue_add(store, bot, body)['id']}  # it waits in line and is sent when the Bot is free
                        send_remember(self.server, once, waiting)
                        return self.respond(202, waiting)
                    send_remember(self.server, once, {'jobId': job['id']})
                    return self.respond(202, {'jobId': job['id']})
                if path == '/api/chat/redo' and self.command == 'POST':
                    # Answer the last question again, send an edited version of it, or answer it with another model.
                    body = self.body(); bot = store.find('bots', body.get('botId'))
                    if not bot: return self.error(404, '找不到機器人。')
                    if body.get('mode') not in ('again', 'edit'): return self.error(400, '動作無效。')
                    if any(j['botId'] == bot['id'] and j['status'] == 'running' for j in store.data['jobs']): return self.error(409, '此機器人已有執行中的工作。')
                    messages = bot['messages']
                    last = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]['role'] == 'user'), None)
                    if last is None: return self.error(400, '這個對話還沒有可以重來的訊息。')
                    content = body.get('content') if body['mode'] == 'edit' else messages[last]['content']
                    if not isinstance(content, str) or not content.strip(): return self.error(400, '訊息內容無效。')
                    use = None
                    if body.get('provider'):
                        if not isinstance(body['provider'], str) or not P.spec(store.data, body['provider']): return self.error(400, '找不到這個模型。')
                        model = body.get('model') or ''
                        if not isinstance(model, str) or len(model) > 100: return self.error(400, '找不到這個模型。')
                        use = (body['provider'], model)
                    author, kept = messages[last].get('author'), [a for a in messages[last].get('attachments') or [] if upload_meta(store, a['id'])]
                    reply = messages[last + 1] if len(messages) > last + 1 else {}
                    effort, plan = body.get('effort') or reply.get('effort') or 'standard', bool(messages[last].get('plan'))
                    removed = messages[last:]; del messages[last:]
                    # Answering again does not make it the user's own request: what a schedule or a trigger asked stays what it was.
                    began = next((j.get('origin') for j in reversed(store.data['jobs']) if j.get('messageId') == reply.get('id')), None) or ('schedule' if author else 'user')
                    try: job = self.server.send_to_bot(bot, content, inventory, author=author, use=use, attachments=kept, effort=effort, plan=plan, replaces=removed, origin=began)
                    except (ValueError, RuntimeError):
                        messages.extend(removed); raise
                    return self.respond(202, {'jobId': job['id']})
                if path == '/api/schedules' and self.command == 'POST':
                    if len(store.data['schedules']) >= MAX_SCHEDULES: return self.error(409, '排程已達上限 %d 個，請先刪除不用的排程。' % MAX_SCHEDULES)
                    item = schedule_fields(store, self.body(), dict(id=ID(), botId='', content='', time='', repeat='daily', on=True, catchUp=True, createdAt=NOW()))
                    if not self.device: trigger_fields(store, self.last_body, item)
                    store.data['schedules'].append(item); store.save(); return self.respond(201, item)
                if len(parts) == 3 and parts[:2] == ['api', 'schedules'] and self.command in ('PATCH', 'DELETE'):
                    item = store.find('schedules', parts[2])
                    if not item: return self.error(404, '找不到這個排程。')
                    if self.command == 'DELETE': store.data['schedules'].remove(item); store.save(); return self.respond(200, {'ok': True})
                    candidate = schedule_fields(store, self.body(), copy.deepcopy(item)); candidate.pop('held', None)
                    if not self.device: trigger_fields(store, self.last_body, candidate)
                    if 'runs' in item: candidate['runs'] = item['runs']  # keep the same history entries a running reply may still update
                    item.clear(); item.update(candidate); store.save(); return self.respond(200, item)
                if len(parts) == 4 and parts[:2] == ['api', 'schedules'] and parts[3] == 'run' and self.command == 'POST':
                    item = store.find('schedules', parts[2])
                    if not item: return self.error(404, '找不到這個排程。')
                    self.body()
                    try: problem = self.server.run_schedule(item, inventory)
                    except Busy as exc: return self.error(409, str(exc))
                    if problem: return self.error(400, problem)
                    item.update(lastAt=NOW(), lastStatus='sent', lastError=''); store.save(); return self.respond(202, item)
                if path == '/api/groups' and self.command == 'POST':
                    body = self.body(); group = dict(id=ID(), name='', botIds=[], messages=[], status='idle', runId=None, activeJobId=None, createdAt=NOW())
                    set_group_fields(store, group, body, creating=True)
                    store.data['groups'].append(group); store.save(); return self.respond(201, group)
                if len(parts) >= 3 and parts[:2] == ['api', 'groups']:
                    group = store.find('groups', parts[2])
                    if not group: return self.error(404, '找不到群組。')
                    if len(parts) == 3 and self.command == 'GET':
                        ids = group.get('activeJobIds') or ([group['activeJobId']] if group.get('activeJobId') else [])
                        return self.respond(200, {'group': group, 'jobs': [job_view(j) for j in (store.find('jobs', x) for x in ids) if j]})
                    if len(parts) == 3 and self.command == 'PATCH':
                        candidate = copy.deepcopy(group); set_group_fields(store, candidate, self.body())
                        added = candidate['messages'][len(group['messages']):]  # the discussion may still be running, so its messages stay as they are
                        group.update({k: candidate[k] for k in ('name', 'botIds', 'hostId', 'mode', 'turnLimit') if k in candidate}); group['messages'].extend(added)
                        store.save(); return self.respond(200, group)
                    if len(parts) == 3 and self.command == 'DELETE':
                        if group['status'] == 'running': return self.error(409, '群組討論進行中，請先停止。')
                        store.data['groups'].remove(group)
                        shutil.rmtree(str(group_files_dir(store, group['id'])), ignore_errors=True)
                        store.data['schedules'] = [x for x in store.data['schedules'] if x.get('groupId') != group['id']]
                        store.save(); return self.respond(200, {'ok': True})
                    if len(parts) == 4 and parts[3] == 'messages' and self.command == 'POST':
                        body = self.body()
                        if self.device and isinstance(body.get('attachments'), list) and len(body['attachments']) > MOBILE_PHOTOS: return self.error(400, '手機每則訊息最多 %d 張照片。' % MOBILE_PHOTOS)
                        once = send_key('group:' + group['id'], body); sent = send_seen(self.server, once)
                        if sent: return self.respond(202, dict(sent, duplicate=True))
                        try: run_id = self.server.post_group_message(group, body.get('content'), attachments=attachments_for(store, body.get('attachments')), effort=body.get('effort'), mode=body.get('mode'))
                        except RuntimeError as exc: return self.error(409, str(exc))
                        send_remember(self.server, once, {'runId': run_id})
                        store.save(); return self.respond(202, {'runId': run_id})
                    if len(parts) == 4 and parts[3] == 'continue' and self.command == 'POST':
                        body = self.body()
                        if body.get('discard') is True: group.pop('paused', None); store.save(); return self.respond(200, group)
                        try: run_id = self.server.continue_group(group)
                        except RuntimeError as exc: return self.error(409, str(exc))
                        store.save(); return self.respond(202, {'runId': run_id})
                    if len(parts) == 4 and parts[3] == 'summarize' and self.command == 'POST':
                        try: run_id = self.server.summarize_group(group)
                        except RuntimeError as exc: return self.error(409, str(exc))
                        store.save(); return self.respond(202, {'runId': run_id})
                    if len(parts) == 6 and parts[3] == 'messages' and parts[5] == 'verify' and self.command == 'POST':
                        body = self.body()
                        try: result = self.server.verify_group_message(group, parts[4], body.get('confirm') is True)
                        except RuntimeError as exc: return self.error(409, str(exc))
                        store.save(); return self.respond(200 if result.get('needsConfirm') else 202, result)
                    if len(parts) == 4 and parts[3] == 'files' and self.command == 'GET' and not self.device:
                        return self.respond(200, {'files': list_group_files(store, group), 'limit': GROUP_FILES_TOTAL})
                    if len(parts) == 5 and parts[3] == 'files' and self.command == 'GET' and not self.device:
                        found = group_file_path(store, group, parts[4])
                        if not found: return self.error(404, '找不到這個檔案。')
                        return self.respond(200, found.read_bytes(), 'application/octet-stream')
                    if len(parts) == 5 and parts[3] == 'files' and self.command == 'DELETE' and not self.device:
                        found = group_file_path(store, group, parts[4])
                        if not found: return self.error(404, '找不到這個檔案。')
                        found.unlink(); (group.get('fileInfo') or {}).pop(parts[4], None); store.save()
                        return self.respond(200, {'ok': True})
                    if len(parts) == 4 and parts[3] == 'estimate' and self.command == 'POST':
                        body = self.body(); mode = body.get('mode') or group.get('mode') or 'free'
                        if mode not in GROUP_MODES or not isinstance(body.get('content', ''), str): raise ValueError('討論方式無效。')
                        return self.respond(200, group_estimate(store, group, body.get('content', ''), mode))
                    if len(parts) == 4 and parts[3] == 'stop' and self.command == 'POST':
                        ids = group.get('activeJobIds') or ([group['activeJobId']] if group.get('activeJobId') else [])
                        group.update(status='idle', runId=None, activeJobId=None, activeJobIds=[])
                        for job in [j for j in (store.find('jobs', x) for x in ids) if j]: self.server.cancel_job(job)
                        store.save(); return self.respond(200, group)
                    return self.error(404, '找不到資源。')
                if len(parts) == 3 and parts[:2] == ['api', 'memories'] and self.command == 'DELETE':
                    item = store.find('memories', parts[2])
                    if not item: return self.error(404, '找不到記憶。')
                    store.data['memories'].remove(item); store.save(); return self.respond(200, {'ok': True})
                if path == '/api/bots' and self.command == 'POST':
                    body = self.body(); name = body.get('name', '')
                    if not isinstance(name, str) or not name.strip() or len(name)>100: raise ValueError('名稱無效。')
                    bot = dict(id=ID(), name=name, color='#8275f4', shape='circle', instructions='', persona='', provider='', model='', pinned=False, section='團隊', messages=[], enabledSkills=[], enabledMcp=[], allowCommands=True)
                    update(bot, body, 'bot'); validate_selection(bot, inventory); ensure_chats(bot); store.data['bots'].append(bot); store.save(); watch_auto_status(store, bot); return self.respond(201, bot)
                if path == '/api/bots/arrange' and self.command == 'POST':
                    body = self.body(); arrange_bots(store, body); store.save()
                    return self.respond(200, dict(bots=[dict(id=b['id'], section=b.get('section'), pinned=b.get('pinned')) for b in store.data['bots']], sections=store.data['settings']['sections']))
                if len(parts) >= 4 and parts[:2] == ['api', 'bots'] and parts[3] == 'chats':
                    bot = store.find('bots', parts[2])
                    if not bot: return self.error(404, '找不到機器人。')
                    ensure_chats(bot)
                    if len(parts) == 4 and self.command == 'POST':
                        self.body()
                        current = next(c for c in bot['chats'] if c['id'] == bot['chatId'])
                        if not bot['messages'] and current.get('kind') != 'schedule': return self.respond(201, current)  # already blank
                        chat = dict(id=ID(), title='', createdAt=NOW(), updatedAt=NOW(), messages=[])
                        bot['chats'].append(chat); open_chat(bot, chat['id']); store.save(); return self.respond(201, chat)
                    chat = next((c for c in bot['chats'] if c['id'] == parts[4]), None) if len(parts) >= 5 else None
                    if not chat: return self.error(404, '找不到這個對話。')
                    if len(parts) == 6 and parts[5] == 'open' and self.command == 'POST':
                        self.body(); open_chat(bot, chat['id']); store.save(); return self.respond(200, {k: v for k, v in chat.items() if k != 'messages'})
                    if len(parts) == 5 and self.command == 'PATCH':
                        title = self.body().get('title')
                        if not isinstance(title, str) or not title.strip() or len(title) > 80: return self.error(400, '請輸入 1–80 字的名稱。')
                        chat['title'] = title.strip(); store.save(); return self.respond(200, {k: v for k, v in chat.items() if k != 'messages'})
                    if len(parts) == 5 and self.command == 'DELETE':
                        if any(j['botId'] == bot['id'] and j['status'] == 'running' and j.get('chatId', bot['chatId']) == chat['id'] for j in store.data['jobs']):
                            return self.error(409, '這個對話還在回覆中，請等回覆完成或先停止。')
                        queue_forget_chat(bot, chat['id'])
                        if chat['id'] == bot['chatId']:
                            rest = sorted((c for c in bot['chats'] if c['id'] != chat['id']), key=lambda c: c.get('updatedAt') or '', reverse=True)
                            if rest: open_chat(bot, rest[0]['id'])
                            else:
                                fresh = dict(id=ID(), title='', createdAt=NOW(), updatedAt=NOW(), messages=[])
                                bot['chats'].append(fresh); open_chat(bot, fresh['id'])
                        bot['chats'].remove(chat); store.save(); return self.respond(200, {'ok': True, 'chatId': bot['chatId']})
                    return self.error(404, '找不到資源。')
                if len(parts) == 3 and parts[:2] == ['api', 'bots'] and self.command == 'PATCH':
                    bot = store.find('bots', parts[2])
                    if not bot: return self.error(404, '找不到機器人。')
                    body = self.body(); candidate = copy.deepcopy(bot); update(candidate, body, 'bot'); validate_selection(candidate, inventory); bot.update(candidate); store.save(); watch_auto_status(store, bot)
                    if 'permissionMode' in body: self.server.release_approvals()
                    return self.respond(200, bot)
                if len(parts) == 3 and parts[:2] == ['api', 'bots'] and self.command == 'DELETE':
                    bot = store.find('bots', parts[2])
                    if not bot: return self.error(404, '找不到機器人。')
                    if any(j['botId'] == bot['id'] and j['status'] == 'running' for j in store.data['jobs']): return self.error(409, '此機器人已有執行中的工作。')
                    if any(item.get('botId') == bot['id'] for item in store.data['knowledge']): return self.error(409, '請先將此 Bot 的知識移至其他 Bot 或共用知識。')
                    if any(g['status'] == 'running' and bot['id'] in g['botIds'] for g in store.data['groups']): return self.error(409, '此機器人正在群組討論中。')
                    for g in store.data['groups']:
                        if bot['id'] in g['botIds']:
                            was_host = group_host(store, g) == bot['id']
                            g['botIds'].remove(bot['id'])
                            if was_host: drop_group_host(store, g)
                    store.data['schedules'][:] = [x for x in store.data['schedules'] if x.get('botId') != bot['id']]
                    trash_bot(store, bot)  # kept aside, so it can be brought back
                    store.data['bots'].remove(bot); store.save(); return self.respond(200, {'ok': True})
                if path == '/api/settings' and self.command == 'PATCH':
                    body = self.body(); update(store.data['settings'], body, 'settings'); store.save()
                    if 'remote' in body: threading.Thread(target=self.server.sync_remote, daemon=True).start()
                    if 'permissionMode' in body: self.server.release_approvals()
                    return self.respond(200, store.data['settings'])
                if path == '/api/knowledge' and self.command == 'POST':
                    item = dict(id=ID(), title='', content='', tags=[], botId='', createdAt=NOW(), updatedAt=NOW())
                    update(item, self.body(), 'knowledge'); store.data['knowledge'].append(item); store.save(); return self.respond(201, item)
                if len(parts) == 3 and parts[:2] == ['api', 'knowledge']:
                    item = store.find('knowledge', parts[2])
                    if not item: return self.error(404, '找不到知識項目。')
                    if self.command == 'DELETE': store.data['knowledge'].remove(item); store.save(); return self.respond(200, {'ok': True})
                    if self.command == 'PATCH': update(item, self.body(), 'knowledge'); item['updatedAt'] = NOW(); store.save(); return self.respond(200, item)
            if self.command == 'GET' and not path.startswith('/api/'):
                relative = unquote(path).lstrip('/') or 'index.html'; target = (self.server.assets / relative).resolve()
                parts_dir = self.server.assets / 'js'
                if relative == 'app.js' and parts_dir.is_dir():  # the page's script is kept in several files, joined here in name order
                    return self.respond(200, b''.join(f.read_bytes() for f in sorted(parts_dir.glob('*.js'))), 'text/javascript; charset=utf-8')
                if not target.is_relative_to(self.server.assets) or not target.is_file(): return self.error(404, '找不到檔案。')
                return self.respond(200, target.read_bytes(), mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
            return self.error(404, '找不到資源。')
        except ValueError as exc: return self.error(400, str(exc))
        except (OSError, TypeError, KeyError): return self.error(500, '處理要求時發生錯誤。')
    do_GET = dispatch; do_POST = dispatch; do_PATCH = dispatch; do_DELETE = dispatch


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=0); parser.add_argument('--data-dir', required=True); parser.add_argument('--assets', required=True)
    args = parser.parse_args(); token = secrets.token_urlsafe(32)
    pathlib.Path(args.data_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
    instance_lock = open(pathlib.Path(args.data_dir) / '.instance.lock', 'a')
    try: fcntl.flock(instance_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit('Zook is already using this data directory.')
    app = App(('127.0.0.1', args.port), Store(args.data_dir), args.assets, token)
    print(json.dumps(dict(port=app.server_address[1], token=token)), flush=True)
    def stop_server(signum, frame):
        threading.Thread(target=app.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop_server)
    threading.Thread(target=app.sync_remote, daemon=True).start()
    threading.Thread(target=app.schedule_loop, daemon=True).start()
    for job in app.store.data['jobs']:  # activity saved by earlier versions
        for call in job.get('toolCalls') or []:
            if call.get('name') == 'native_command' and isinstance((call.get('arguments') or {}).get('command'), str): call['arguments']['command'] = hide_command_secrets(call['arguments']['command'])
    trim_jobs(app.store); recover_deleted_bots(app.store)
    app.store.save()
    try: app.script_api = ScriptApi(app)  # for scripts on this Mac; every Bot starts with it switched off
    except OSError: app.script_api = None
    later = threading.Timer(2.0, app.queue_drain_all); later.daemon = True; later.start()  # messages that were waiting when Zook was closed
    app.auto_refreshed = time.time()
    live_learn(app)
    if any(b.get('provider') == AUTO for b in app.store.data['bots']): threading.Thread(target=refresh_auto_status, args=(app.store,), daemon=True).start()
    try: app.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        app.closing = True  # replies end now because Zook is closing: what is waiting in line stays there for next time
        if app.__dict__.get('script_api'):
            try: app.script_api.close()
            except Exception: pass
        with app.store.lock:
            processes = list(app.processes.values())
            workers = [app.expire_job(job_id) for job_id in list(app.workers)]
            for job in app.store.data['jobs']:
                if job['status'] == 'running':
                    job.update(status='failed', error='服務關閉，工作已中斷。', finishedAt=NOW())
                    app.store.finish_message(job, '', 'failed')
            app.store.save(everything=True)
        live_tidy(app, everything=True)  # after the replies are marked as interrupted, so none of them is sent again on the way out
        app.stop_remote()
        for flow in list(app.logins.values()) + list(app.installs.values()): flow.cancel()
        for worker in workers:
            if worker: worker['session'].close()
        for proc in processes:
            try: os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        for proc in processes:
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired: pass
            # The leader may exit before its descendants.
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        app.server_close()

if __name__ == '__main__': main()
