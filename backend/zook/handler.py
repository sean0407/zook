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

    def antigravity_live_quota(self, account=None):
        store, app = self.server.store, self.server; key = 'antigravity' + ('@' + account['id'] if account else '')
        caches = app.__dict__.setdefault('codex_quota_caches', {}); hit = caches.get(key)
        if hit and time.time() - hit[0] < 60: return hit[1]
        try: live = antigravity_quota(find_cli('antigravity'), provider_env('antigravity', account) if account else None)
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError, subprocess.SubprocessError): live = None
        caches[key] = (time.time(), live)  # a failed read is not retried on every page load either
        if not live: return None
        with store.lock: store.data.setdefault('quota', {})[key] = live; store.save()
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
            if provider == 'grok' and account['status'] == 'logged_in': snap = grok_live_quota(self.server) or snap
            if provider not in ('codex', 'claude', 'antigravity', 'grok'): snap = None  # the other CLIs do not report plan limits to Zook
            profiles = []
            for extra in [] if phone else [a for a in store.data.get('accounts') or [] if a.get('provider') == provider]:
                try: view = account_view(extra)
                except (OSError, ValueError, RuntimeError): view = dict(id=extra['id'], name=extra['name'], type=extra['type'], status='unknown', method='', plan='', email='')
                billed = extra['type'] == 'key' or api_billed_method(view.get('method'))
                with store.lock:
                    used = provider_usage(store, provider, extra['id']); saved = copy.deepcopy(store.data.get('quota', {}).get(provider + '@' + extra['id']))
                if provider in ('codex', 'grok', 'antigravity') and view['status'] == 'logged_in' and not billed: saved = (self.codex_live_quota(extra) if provider == 'codex' else grok_live_quota(self.server, extra) if provider == 'grok' else self.antigravity_live_quota(extra)) or saved
                profiles.append(dict(view, zookUsage=used, quota=saved if provider in ('codex', 'claude', 'grok', 'antigravity') else None, apiBilling=billed, noQuotaApi=provider not in ('codex', 'claude', 'grok', 'antigravity'), quotaUnread=provider == 'grok' and not saved, _account=extra))
            with store.lock: zook = provider_usage(store, provider)
            result.append(dict(id=provider, name=account['name'], vendor=(P.spec(store.data, provider) or {}).get('vendor', ''), zookUsage=zook,
                               status=account['status'], method=account['method'], noQuotaApi=provider not in ('codex', 'claude', 'antigravity', 'grok'), quotaUnread=provider == 'grok' and not snap,
                               plan=(snap or {}).get('plan') or account['plan'], email=account['email'], workspace=account.get('workspace', ''), quota=snap,
                               apiBilling=api_billed_method(account['method']), profiles=profiles, issue=((store.data.get('providerIssues') or {}).get(provider) or {}).get('issue', '') if account['status'] == 'logged_in' else ''))  # #158②
        with store.lock:
            known = store.data.setdefault('autoStatus', {}); known.update(merge_auto_status(known, {x['id']: auto_state(x['id'], x['status'], x['method']) for x in result if x['id'] in AUTO_MODELS}))
            known.update(merge_auto_status(known, {auto_account_key(a['_account']): auto_state(x['id'], a['status'], a['method'], a['_account']) for x in result if x['id'] in AUTO_MODELS for a in x['profiles']}))
            allowed = auto_allowed(store)
            for item in result:
                if item['id'] in AUTO_MODELS: item.update(autoOn=item['id'] in allowed, autoBilled=auto_known_billed(store.data['autoStatus'].get(item['id'])))
                for a in item['profiles']:
                    account = a.pop('_account')
                    if item['id'] in AUTO_MODELS: a.update(autoOn=auto_account_on(store, account), autoBilled=account.get('type') == 'key' or auto_known_billed(known.get(auto_account_key(account))))
        if phone:
            with store.lock: result = usage_card_sort(store.data['settings'], result)  # the same order as the cards on the Mac
        return {'providers': result, 'usageDetectEvery': usage_detect_every(store)}

    def detect_usage(self):
        """偵測使用量 (usagewatch.py, shared with 自動偵測), then the fresh figures."""
        detect_usage_now(self.server); return self.quota()

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
                item.update(profiles=profiles, canAddLogin=can_add_login(provider), canAddKey=provider in ACCOUNT_KEYS)
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
        login_key = provider + ('@' + account['id'] if account else ''); flow = logins.get(login_key)
        if action not in ('install/cancel', 'login/cancel'): auto_status_forget(store, provider)  # a sign-in may change: billing is checked again first
        try:
            if action == 'profiles':
                name, kind, key = body.get('name'), body.get('type'), body.get('key')
                if not isinstance(name, str) or not name.strip() or len(name) > 60: raise ValueError('請輸入帳號名稱。')
                if kind == 'login' and not can_add_login(provider): raise ValueError('這個模型不支援再登入一個帳號，請改用 API 金鑰。')
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
                with store.lock:
                    if any(j['status'] == 'running' and (store.find('bots', j['botId']) or {}).get('account') == account['id'] for j in store.data['jobs']): raise RuntimeError('有 Bot 正在用這個帳號回覆，等它完成後再移除。')
                logins.pop(login_key, None)
                with store.lock:
                    store.data['accounts'] = [a for a in store.data['accounts'] if a['id'] != account['id']]
                    users = [b for b in store.data['bots'] if b.get('account') == account['id']]
                    for b in users: b['account'] = ''  # back to the CLI's own sign-in
                    (store.data.get('accountInfo') or {}).pop(login_key, None); (store.data.get('quota') or {}).pop(login_key, None); store.save()
                secret_delete(account['id'])
                problem = agy_account_remove(self.server, account['id']) if provider == 'antigravity' else shutil.rmtree(str(_active['dir'] / 'accounts' / account['id']), ignore_errors=True)
                if problem:  # its agy keychain could not be cleared: the account stays, so removing it can be tried again
                    with store.lock:
                        store.data['accounts'].append(account)
                        for b in users: b['account'] = account['id']
                        store.save()
                    return self.error(500, problem)
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
                script = terminal_login_script(provider, account)  # agyhome.py; an extra Antigravity account signs in in its own home
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
        note_request(self, code, data); create_done(self, code, data)
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
            try:
                found = bg_worker(self, parts[2])  # signed with the reply's token (background.py)
                if not found: return self.error(403, '禁止存取。')
                worker, job, body = found; method = body.get('method'); params = body.get('params', {})
                if method == 'tools/list': return bg_answer(self, {'tools': worker['tools']})
                if method == 'tools/call' and isinstance(params, dict) and isinstance(params.get('name'), str) and isinstance(params.get('arguments', {}), dict):
                    return bg_answer(self, worker['session'].call(params['name'], params.get('arguments', {})))  # background.py
                return bg_answer(self, {'approved': worker_gate(self.server, self.connection, worker, job['id'], params)}) if method == 'gate' else self.error(400, '無效的工具要求。')  # gate: zook_gate.py
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
                # A paired device, reached through the relay. Checked on every request, so a revoked or expired device stops at once.
                with store.lock: self.device = remote_device(store, device_id)
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
                return self.respond(200, model_view(provider))  # clitable.py: the list with each model's family
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
            if path == '/api/quota/auto' and self.command == 'POST': return self.respond(200, set_usage_detect(store, self.body().get('every')))  # 自動偵測, also from a paired phone
            if path == '/api/quota/auto' and self.command == 'GET': return self.respond(200, usage_detect_status(self.server))  # an open usage page asks whether to read again
            if path == '/api/quota/claude/refresh' and self.command == 'POST':
                self.body()
                try: claude_probe_default(self.server, 'probe')  # shares 偵測使用量's lock (usagewatch.py)
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc: return self.error(409, str(exc) if isinstance(exc, RuntimeError) else '無法查詢 Claude 額度。')
                return self.respond(200, self.quota())
            if path == '/api/usage/overview' and self.command == 'GET':
                try: span = int((parse_qs(urlsplit(self.path).query).get('days') or ['30'])[0])
                except ValueError: span = 0
                with store.lock: return self.respond(200, usage_overview(store, span))
            if path == '/api/usage/bots' and self.command == 'GET':
                with store.lock: return self.respond(200, bot_usage(store))
            if len(parts) in (4, 5, 6, 7) and parts[:2] == ['api', 'bots'] and parts[3] == 'outputs' and not self.device:
                with store.lock: bot = copy.deepcopy(store.find('bots', parts[2]))
                if not bot: return self.error(404, '找不到機器人。')
                if len(parts) == 4 and self.command == 'GET': return self.respond(200, {'outputs': bot_outputs_all(store, bot)})
                item = bot_output(store, bot, parts[4])
                if not item: return self.error(404, '找不到這個檔案，可能已經被移走或刪除。')
                if len(parts) == 5 and self.command == 'GET':
                    try: data, kind = output_response(item)
                    except ValueError as exc: return self.error(413, str(exc))
                    except OSError: return self.error(404, '找不到這個檔案，可能已經被移走或刪除。')
                    return self.respond(200, data, kind)
                if len(parts) in (6, 7) and parts[5] == 'pages' and self.command == 'GET': return preview_route(self, store, item['path'], parts[6:], strict=True)  # Office 預覽 (officeview.py)
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
            if len(parts) == 4 and parts[:2] == ['api', 'bots'] and parts[3] == 'intro' and self.command == 'POST':  # an older Bot's empty conversation opened
                self.body(); known = bool(store.find('bots', parts[2]))  # one look, no lock needed for it
                return self.error(404, '找不到機器人。') if not known else (self.server.want_intro(parts[2]), self.respond(202, {'ok': True}))[1]
            if len(parts) == 4 and parts[:2] == ['api', 'bots'] and parts[3] == 'restore' and self.command == 'POST' and not self.device:
                self.body()
                with store.lock: bot = restore_bot(store, parts[2]); store.save()
                return self.respond(200, bot)
            if path == '/api/skill-templates' and self.command == 'GET': return self.respond(200, dict(items=template_view(store)))
            if path == '/api/skills/template' and self.command == 'POST' and not self.device: return self.respond(201, template_add(store, self.body().get('id')))
            if parts[:2] == ['api', 'skills'] and ((len(parts) == 2 and self.command == 'POST') or (len(parts) == 3 and self.command in ('GET', 'PATCH'))) and not self.device: return self.respond(*custom_skill_route(store, self.command, parts[2:], self.body() if self.command != 'GET' else {}))
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
                    st['sharedMcp'] = [x for x in shared if x != ident]
                    store.save()
                on, test = connector_first_test(store, 'zook:' + record['id'], was_on)
                return self.respond(201, dict(id='zook:' + record['id'], name=record['name'], on=on, test=test))
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
            if len(parts) == 4 and parts[:2] == ['api', 'connectors'] and parts[3] == 'turn-on' and self.command == 'POST' and not self.device:  # after its sign-in: tested again here, on only if what was tested is what is saved (#303)
                self.body(); on, test = connector_first_test(store, 'zook:' + parts[2], 'if-waiting', waiting=True); return self.respond(200, dict(on=on, test=test))
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
                            if any(same_name(c['name']) == same_name(record['name']) and c['id'] != record['id'] for c in store.data['connectors']): raise ValueError('已經有同名的連接器（大小寫不同也算同名）。')
                        more = body.get('moreSecrets') if isinstance(body.get('moreSecrets'), dict) else {}
                        written = connector_keys_write(record, secret, {k: v.strip() for k, v in more.items() if k in record['moreSecrets'] and isinstance(v, str) and v.strip()})  # new Keychain items; nothing changed if one fails
                        old_keys, drop = connector_publish(store, record, written)  # saved with its keys as one change (myskills.py)
                        for blob in drop: blob_delete(blob)  # the address or the way to sign in changed
                        for old in old_keys: secret_drop(old)  # the keys these replaced
                        if existing: return self.respond(200, dict(id='zook:' + record['id'], name=record['name']))
                        on, test = connector_first_test(store, 'zook:' + record['id'], waiting=True)  # on for every Bot only once it worked (#303)
                        return self.respond(201, dict(id='zook:' + record['id'], name=record['name'], on=on, test=test))
                    if existing and self.command == 'DELETE':
                        with store.lock:
                            store.data['connectors'] = [c for c in store.data['connectors'] if c['id'] != existing['id']]; connector_touch(existing['id'])
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
                return self.respond(200, runtime_module().test_connection(parts[2], inventory_for(self.server.store, testing=parts[2])))
            if path == '/api/uploads/path' and self.command == 'POST' and not self.device: return self.respond(201, upload_from_path(store, self.body().get('path')))  # 附上 a file the user named, after they clicked
            if path == '/api/uploads' and self.command == 'POST' and not self.device:
                # One attached file, sent as the raw request body; the name comes in X-File-Name.
                try: size = int(self.headers.get('Content-Length', '0'))
                except ValueError: size = 0
                if size <= 0 or size > MAX_UPLOAD: self.close_connection = size > 0; return self.error(400 if size <= 0 else 413, '檔案是空的。' if size <= 0 else '單一檔案不能超過 20 MB。')
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
                meta = dict(id=upload_id, name=name, origName=upload_original(unquote(self.headers.get('X-File-Name', ''))), size=size, kind='image' if pathlib.Path(name).suffix.lower() in IMAGE_TYPES else 'file', createdAt=NOW())
                (folder / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
                return self.respond(201, meta)
            if path == '/api/knowledge/file' and self.command == 'POST' and not self.device: return knowledge_upload(self, store)  # read in the background (knowledge.py)
            if len(parts) in (6, 7) and parts[:2] == ['api', 'groups'] and parts[3] == 'files' and parts[5] == 'pages' and self.command == 'GET' and not self.device:  # Office 預覽, outside the store lock
                with store.lock: found = bool(store.find('groups', parts[2]))
                found = found and group_preview_path(store, parts[2], parts[4])
                return preview_route(self, store, found, parts[6:], strict=True) if found else self.error(404, '找不到這個檔案。')
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
            if len(parts) == 3 and parts[:2] == ['api', 'uploads'] and self.command == 'DELETE' and not self.device:
                with store.lock: return self.respond(200, {'removed': upload_drop(store, parts[2])})  # × in the message box (#153②)
            if len(parts) == 3 and parts[:2] == ['api', 'uploads'] and self.command == 'GET' and not self.device:
                meta = upload_meta(store, parts[2])
                if not meta or (data := upload_bytes(store, meta)) is None: return self.error(404, '找不到這個檔案。')  # #153⑤: a file gone from the disk too
                kind = IMAGE_TYPES.get(pathlib.Path(meta['name']).suffix.lower())
                return self.respond(200, data, kind or 'application/octet-stream')
            if path == '/api/team/draft' and self.command == 'POST' and not self.device:  # one model call; never under the store lock
                try: return self.respond(200, self.server.draft_team(self.body().get('goal'), inventory_for(store)))
                except RuntimeError as exc: return self.error(502, str(exc))
            if path == '/api/team' and self.command == 'POST' and not self.device:
                body = self.body()
                with store.lock: return self.respond(201, self.server.create_team(body))
            if parts[:2] == ['api', 'backups'] and backup_unlocked(self, store, parts): return  # the folder chooser waits on the user: never under the lock
            if path == '/api/privacy-settings' and self.command == 'POST': return privacy_route(self)  # macOS's own privacy page, for a failed reply (errors.py)
            if path == '/api/chat' and self.command == 'POST': return chat_intake(self, self.body())  # answered at once, taken in beside it (intake.py, #289)
            inventory = None
            if (path in ('/api/chat/redo', '/api/chat/resume') and self.command == 'POST') or (parts[:2] == ['api', 'bots'] and self.command in ('POST', 'PATCH')) or (len(parts) == 4 and parts[:2] == ['api', 'schedules']):
                inventory = inventory_for(store, tokens=path not in ('/api/chat/redo', '/api/chat/resume'))  # a message only checks its Bot's choices; the reply signs in to connectors itself
            with store.lock:
                if self.command == 'GET' and path == '/api/state':
                    for b in store.data['bots']: ensure_chats(b)  # Bots added by an import, too
                    if (parse_qs(urlsplit(self.path).query).get('since') or [''])[0] == str(store.rev): return self.respond(200, {'unchanged': True, 'rev': store.rev})
                    return self.respond(200, state_view(store, whole=(parse_qs(urlsplit(self.path).query).get('full') or [''])[0] == '1'))  # full=1: every conversation whole, as before paging
                if self.command == 'GET' and path == '/api/notifications':
                    try: after = int((parse_qs(urlsplit(self.path).query).get('after') or ['0'])[0])
                    except ValueError: after = 0
                    return self.respond(200, notices_for(self.server, after, device=bool(self.device)))  # a phone gets only its four kinds (phonenotice.py)
                if self.command == 'GET' and path == '/api/diagnostics': return self.respond(200, dict(providers=provider_info(), python=__import__('platform').python_version(), system=__import__('platform').system()))
                if self.command == 'GET' and path == '/api/usage': return self.respond(200, usage())
                if self.command == 'POST' and path == '/api/export': return self.respond(200, store.data)
                if parts[:2] == ['api', 'backups'] or path in ('/api/activity', '/api/budget'): return upkeep_route(self, store, parts, path)
                if self.command == 'GET' and (path == '/api/search' or (len(parts) == 4 and parts[:2] == ['api', 'bots'] and parts[3] in ('messages', 'export'))): return paging_route(self, store, parts, path)
                if len(parts) == 3 and parts[:2] == ['api', 'jobs'] and self.command == 'GET':
                    job = store.find('jobs', parts[2]); return self.respond(200, job_view(job)) if job else self.error(404, '找不到工作。')
                if len(parts) == 3 and parts[:2] == ['api', 'approvals'] and self.command == 'POST':
                    body = self.body(); decision = body.get('decision')
                    if decision not in ('approve', 'deny'): raise ValueError('決定無效。')
                    for job in store.data['jobs']:
                        approval = next ( (x for x in job.get('approvals', []) if x['id'] == parts[2]), None)
                        if approval:
                            if job['status'] != 'running' or approval['status'] != 'pending': return self.error(409, '此審批已結束。')
                            if self.device and decision == 'approve' and str(approval.get('name') or '').endswith(('zook_create_schedule', 'zook_update_schedule')):
                                return self.error(403, '建立或修改排程要在 Mac 上核准。')  # work that starts by itself later
                            approval['status'] = 'approved' if decision == 'approve' else 'denied'; approval.update(decidedAt=NOW(), callsAt=len(job.get('toolCalls') or [])); store.save()  # #235: the wait line goes once the Bot does something new
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
                    self.server.cancel_job(job, progress_asks_force(self))
                    return self.respond(200, job_view(job))
                if path == '/api/chat/resume' and self.command == 'POST': return resume_request(self, store, inventory)  # 接著做 (resume.py)
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
                    body = self.body()
                    if (again := create_seen(self, 'schedules', body)): return self.respond(200, dict(again, duplicate=True))
                    if len(store.data['schedules']) >= MAX_SCHEDULES: return self.error(409, '排程已達上限 %d 個，請先刪除不用的排程。' % MAX_SCHEDULES)
                    item = schedule_fields(store, body, dict(id=ID(), botId='', content='', time='', repeat='daily', on=True, catchUp=True, createdAt=NOW()))
                    if not self.device: trigger_fields(store, self.last_body, item)
                    number_same_schedule(store, item)  # 「…（2）」 (scheduling.py, #299)
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
                    if (again := create_seen(self, 'groups', body)): return self.respond(200, dict(again, duplicate=True))
                    set_group_fields(store, group, body, creating=True)
                    store.data['groups'].append(group); store.save(); return self.respond(201, group)
                if len(parts) >= 3 and parts[:2] == ['api', 'groups']:
                    group = store.find('groups', parts[2])
                    if not group: return self.error(404, '找不到群組。')
                    if len(parts) == 3 and self.command == 'GET':
                        ids = (group.get('activeJobIds') or ([group['activeJobId']] if group.get('activeJobId') else [])) + progress_stopping_in(store, group)  # stopped, still ending
                        return self.respond(200, {'group': page_group(group), 'jobs': [job_view(j) for j in (store.find('jobs', x) for x in ids) if j]})
                    if len(parts) == 4 and parts[3] == 'messages' and self.command == 'GET':
                        return self.respond(200, page_group_messages(group, parse_qs(urlsplit(self.path).query), store))
                    if len(parts) == 4 and parts[3] == 'export' and self.command == 'GET': return self.respond(200, export_group(store.data, group))
                    if len(parts) == 3 and self.command == 'PATCH':
                        candidate = copy.deepcopy(group); set_group_fields(store, candidate, self.body())
                        added = candidate['messages'][len(group['messages']):]  # the discussion may still be running, so its messages stay as they are
                        group.update({k: candidate[k] for k in ('name', 'botIds', 'hostId', 'mode', 'turnLimit', 'checkMode', 'checkerId', 'instructions') if k in candidate}); group['messages'].extend(added)
                        store.save(); return self.respond(200, page_group(group))
                    if len(parts) == 3 and self.command == 'DELETE':
                        if group['status'] == 'running': return self.error(409, '群組討論進行中，請先停止。')
                        store.data['groups'].remove(group)
                        drop_group_files(store, self.server, group)  # with Zook's copies in the members' workspaces (#213)
                        store.data['schedules'] = [x for x in store.data['schedules'] if x.get('groupId') != group['id']]
                        store.save(); return self.respond(200, {'ok': True})
                    if len(parts) == 4 and parts[3] == 'messages' and self.command == 'POST':
                        body = self.body()
                        if self.device and isinstance(body.get('attachments'), list) and len(body['attachments']) > MOBILE_PHOTOS: return self.error(400, '手機每則訊息最多 %d 張照片。' % MOBILE_PHOTOS)
                        once = send_key('group:' + group['id'], body); sent = send_seen(self.server, once)
                        if sent: return self.respond(202, dict(sent, duplicate=True))
                        try: sent = self.server.user_group_message(group, body)  # 插話 while it runs
                        except RuntimeError as exc: return self.error(409, str(exc))
                        send_remember(self.server, once, sent)
                        store.save(); return self.respond(202, sent)
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
                        if result.get('needsConfirm'): return self.respond(409, dict(result, error=result['message']))  # nothing started: the window says why and asks
                        store.save(); return self.respond(202, result)
                    if len(parts) == 4 and parts[3] == 'files' and self.command == 'GET' and not self.device:
                        return self.respond(200, {'files': list_group_files(store, group), 'limit': GROUP_FILES_TOTAL})
                    if len(parts) == 5 and parts[3] == 'files' and self.command == 'GET' and not self.device:
                        found = group_file_path(store, group, parts[4])
                        if not found: return self.error(404, '找不到這個檔案。')
                        kind, data = _output_kind(found.name), read_group_file(found)  # shown in the conversation: a picture as a picture, a page or SVG only as text
                        if data is None: return self.error(404, '找不到這個檔案。')
                        return self.respond(200, data, IMAGE_TYPES[found.suffix.lower()] if kind == 'image' else 'application/pdf' if kind == 'pdf' else 'text/plain; charset=utf-8' if kind in ('text', 'markdown', 'html') else OFFICE_TYPES.get(found.suffix.lower(), 'application/octet-stream'))
                    if len(parts) == 5 and parts[3] == 'files' and self.command == 'DELETE' and not self.device:
                        found = group_file_path(store, group, parts[4])
                        if not found: return self.error(404, '找不到這個檔案。')
                        with _group_files_lock: found.unlink()  # not while a check is letting files through (#245)
                        (group.get('fileInfo') or {}).pop(parts[4], None); store.save(); sweep_previews_later(store, force=True)  # its preview pictures go with it
                        return self.respond(200, {'ok': True})
                    if len(parts) == 4 and parts[3] == 'estimate' and self.command == 'POST':
                        body = self.body(); mode = body.get('mode') or group.get('mode') or 'free'
                        if mode not in GROUP_MODES or not isinstance(body.get('content', ''), str): raise ValueError('討論方式無效。')
                        return self.respond(200, group_estimate(store, group, body.get('content', ''), mode))
                    if len(parts) >= 5 and parts[3] in ('tasks', 'gates'): return task_route(self, store, group, parts)  # 任務引擎 (taskcheck.py)
                    if len(parts) == 4 and parts[3] == 'stop' and self.command == 'POST':
                        group_stop_now(self.server, store, group); store.save(); return self.respond(200, group)
                    return self.error(404, '找不到資源。')
                if len(parts) == 3 and parts[:2] == ['api', 'memories'] and self.command == 'DELETE':
                    item = store.find('memories', parts[2])
                    if not item: return self.error(404, '找不到記憶。')
                    store.data['memories'].remove(item); store.save(); return self.respond(200, {'ok': True})
                if path == '/api/bots' and self.command == 'POST':
                    body = self.body(); name = body.get('name', '')
                    if (again := create_seen(self, 'bots', body)): return self.respond(200, dict(again, duplicate=True))
                    if not isinstance(name, str) or not name.strip() or len(name)>100: raise ValueError('名稱無效。')
                    bot = dict(id=ID(), name=name, color='#8275f4', shape='circle', instructions='', persona='', provider='', model='', pinned=False, section='團隊', messages=[], enabledSkills=[], enabledMcp=[], allowCommands=True)
                    update(bot, body, 'bot'); validate_selection(bot, inventory); set_gate_full(bot); auto_on_create(store, bot, grant=True); ensure_chats(bot); store.data['bots'].append(bot); store.save(); watch_auto_status(store, bot); self.server.want_intro(bot['id']); return self.respond(201, bot)
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
                    if len(parts) == 6 and parts[5] == 'folder' and self.command == 'POST':  # 打開資料夾: this conversation's files in Finder
                        self.body(); folder = chat_folder(store, bot['id'], chat['id'])
                        if not os.environ.get('ZOOK_NO_BROWSER'): subprocess.run(['/usr/bin/open', str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                        return self.respond(200, {'path': str(folder)})
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
                    body = self.body()
                    if edit_conflict(bot, body): return self.error(409, EDIT_CONFLICT)  # #162: changed elsewhere since the form opened
                    candidate = copy.deepcopy(bot); update(candidate, body, 'bot'); validate_selection(candidate, inventory); local_choice(bot, candidate, body, local=not self.via_bridge and self.device is None); notice = auto_on_edit(store, bot, candidate, body); bot.clear(); bot.update(candidate); store.save(); watch_auto_status(store, bot)
                    if 'permissionMode' in body: self.server.release_approvals()
                    if (bot.get('intro') or {}).get('source') != intro_source(bot): bot.pop('intro', None); store.save(); self.server.want_intro(bot['id'])  # what it is changed: a new greeting
                    return self.respond(200, dict(bot, **({'autoNotice': notice} if notice else {})))
                if len(parts) == 3 and parts[:2] == ['api', 'bots'] and self.command == 'DELETE':
                    bot = store.find('bots', parts[2])
                    if not bot: return self.error(404, '找不到機器人。')
                    if any(j['botId'] == bot['id'] and j['status'] == 'running' for j in store.data['jobs']): return self.error(409, '此機器人已有執行中的工作。')
                    if any(item.get('botId') == bot['id'] for item in store.data['knowledge']): return self.error(409, '這個 Bot 還有只給它用的知識庫項目，請先把「給誰用」改成所有 Bot 或其他 Bot。')
                    if any(g['status'] == 'running' and bot['id'] in g['botIds'] for g in store.data['groups']): return self.error(409, '此機器人正在群組討論中。')
                    bot_leaves_groups(store, bot)
                    store.data['schedules'][:] = [x for x in store.data['schedules'] if x.get('botId') != bot['id']]
                    trash_bot(store, bot)  # kept aside, so it can be brought back
                    store.data['bots'].remove(bot); store.save(); return self.respond(200, {'ok': True})
                if path == '/api/settings' and self.command == 'PATCH':
                    body = self.body(); settings_patch(store, body)  # with the change count of a connector switched on or off (myskills.py)
                    if 'remote' in body: threading.Thread(target=self.server.sync_remote, daemon=True).start()
                    if 'permissionMode' in body: self.server.release_approvals()
                    return self.respond(200, store.data['settings'])
                if path == '/api/knowledge' or (len(parts) == 3 and parts[:2] == ['api', 'knowledge']): return knowledge_route(self, store, parts, path)  # 知識庫 (knowledge.py)
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
    trim_jobs(app.store); recover_deleted_bots(app.store); sweep_uploads(app.store, force=True); sweep_previews(app.store, force=True)
    app.store.save()
    try: app.script_api = ScriptApi(app)  # for scripts on this Mac; every Bot starts with it switched off
    except OSError: app.script_api = None
    later = threading.Timer(float(os.environ.get('ZOOK_RESUME_DELAY') or 1), app.resume_then_drain); later.daemon = True; later.start()  # what the last stop cut short (resume.py), then the messages that were waiting
    app.auto_refreshed = time.time()
    live_learn(app); local_migrate(app.store)  # this Mac's own settings for Bots from before (gate.py)
    threading.Thread(target=auto_migrate, args=(app.store,), daemon=True).start()  # Bots on 自動選擇 from before get their model once (routing.py)
    knowledge_start(app.store)  # files whose reading was cut short (knowledge.py)
    try: app.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        app.closing = True  # replies end now because Zook is closing: what is waiting in line stays there for next time
        bg_starting(app)  # a CLI still starting is waited for, as the lock once made it (background.py, #290)
        if app.__dict__.get('script_api'):
            try: app.script_api.close()
            except Exception: pass
        with app.store.lock:
            spare = bg_closing(app); processes = [p for j, p in app.processes.items() if j not in spare]  # replies that go on under their runner (background.py)
            workers = [app.expire_job(job_id) for job_id in list(app.workers) if job_id not in spare]
            for job in app.store.data['jobs']:
                if job['status'] == 'running' and job['id'] not in spare:
                    job.update(status='failed', error='服務關閉，工作已中斷。', finishedAt=NOW()); interrupted_at(job, NOW())  # carried on at the next start (resume.py)
                    app.store.finish_message(job, '', 'failed')
            app.store.save(everything=True)
        live_tidy(app, everything=True, spare=bg_settle(app, spare))  # after the replies are marked as interrupted, so none of them is sent again on the way out
        app.stop_remote()
        for flow in list(app.logins.values()) + list(app.installs.values()): flow.cancel()
        for worker in workers:
            if worker: worker['session'].close()
        bg_end(processes)  # background.py
        app.server_close()

if __name__ == '__main__': main()
