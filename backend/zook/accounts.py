# Finding CLIs, app updates, accounts, sign-in, connectors. Loaded by backend/server.py into one shared namespace.
def find_cli(provider):
    s = P.spec(_active['data'], provider) or {}  # a copy Zook installed in its own tools folder comes first: it is the one Zook updates
    private = _active['dir'] / 'tools/bin' / str(s.get('binary')) if s.get('npm_package') else None
    if private and os.access(str(private), os.X_OK): return str(private)
    return P.binary_for(_active['data'], provider)


def provider_kind(provider):
    s = P.spec(_active['data'], provider)
    return s['kind'] if s else None


def provider_label(provider):
    s = P.spec(_active['data'], provider)
    return s['name'] if s else provider


def claude_personal_env():
    env = os.environ.copy()
    for key in ('ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL',
                'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK',
                'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        env.pop(key, None)
    return env


def provider_info():
    result = []
    for provider in P.active_ids(_active['data']):
        name = provider_label(provider); path = find_cli(provider)
        item = dict(id=provider, name=name, installed=bool(path), path=path or '', status='installed' if path else 'not_installed')
        if provider == 'claude' and path:
            item['authStatus'] = 'unknown'
            try:
                p = subprocess.run([path, 'auth', 'status'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=claude_personal_env(), timeout=5)
                status = json.loads(p.stdout)
                if isinstance(status.get('loggedIn'), bool):
                    item['authStatus'] = 'logged_in' if status['loggedIn'] else 'not_logged_in'
            except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired): pass
        result.append(item)
    return result


# App updates come from this project's own GitHub releases.
UPDATE_REPO = 'sean0407/zook'
UPDATE_MAX_BYTES = 300 * 1024 * 1024
UPDATE_HELPER = """#!/bin/bash
# Waits for Zook to quit, swaps in the new app, and opens it. If anything goes wrong the old app is put back.
PID="$1"; APP="$2"; NEW="$3"; OPEN="$4"
if [ "$PID" != none ]; then
  for i in $(seq 1 300); do kill -0 "$PID" 2>/dev/null || break; sleep 0.2; done
  kill -0 "$PID" 2>/dev/null && exit 1
fi
OLD="$APP.old-$$"
mv "$APP" "$OLD" || exit 1
if mv "$NEW" "$APP"; then rm -rf "$OLD"; else mv "$OLD" "$APP"; fi
[ "$OPEN" = 1 ] && /usr/bin/open "$APP"
rm -f "$0"
"""


def version_tuple(text):
    m = re.fullmatch(r'v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})', str(text or '').strip())
    return tuple(int(x) for x in m.groups()) if m else None


def bundle_info(app):
    """(bundle id, version) of an app bundle, or ('', '')."""
    try:
        with open(pathlib.Path(app) / 'Contents/Info.plist', 'rb') as f: info = plistlib.load(f)
        return str(info.get('CFBundleIdentifier') or ''), str(info.get('CFBundleShortVersionString') or '')
    except (OSError, ValueError, plistlib.InvalidFileException): return '', ''


def app_bundle():
    """The app this server runs from; None when run from source."""
    for parent in pathlib.Path(__file__).resolve().parents:
        if parent.suffix == '.app' and (parent / 'Contents/Info.plist').is_file(): return parent
    return None


class Updater:
    """Checks this project's GitHub releases and installs a newer Zook. Nothing is replaced until the download
    has the published checksum, a valid signature, the same bundle identifier and a higher version."""
    def __init__(self, busy):
        self.lock = threading.Lock(); self.busy = busy  # busy(): True while a Bot is replying
        self.app = app_bundle(); self.bundle_id, self.current = bundle_info(self.app) if self.app else ('', '')
        self.url = os.environ.get('ZOOK_UPDATE_URL') or 'https://api.github.com/repos/%s/releases/latest' % UPDATE_REPO
        self.state, self.error, self.latest, self.notes, self.asset, self.checked, self.staged = 'idle', '', '', '', None, 0, None

    def can_install(self):
        return bool(self.app and version_tuple(self.current) and os.access(str(self.app), os.W_OK) and os.access(str(self.app.parent), os.W_OK))

    def view(self):
        with self.lock:
            newer = bool(version_tuple(self.latest) and version_tuple(self.current) and version_tuple(self.latest) > version_tuple(self.current))
            return dict(current=self.current, latest=self.latest, available=newer and bool(self.asset), notes=self.notes, state=self.state, error=self.error,
                        canInstall=self.can_install(), checkedAt=self.checked)

    def check(self, force=False):
        """Ask GitHub for the latest release (at most every 6 hours unless forced)."""
        with self.lock:
            if self.state in ('checking', 'downloading', 'ready') or (not force and time.time() - self.checked < 6 * 3600): return
            if os.environ.get('ZOOK_SKIP_UPDATE_CHECK') and not os.environ.get('ZOOK_UPDATE_URL'): return
            self.state, self.error = 'checking', ''
        try:
            request = urllib.request.Request(self.url, headers={'User-Agent': 'Zook-updater', 'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(request, timeout=15) as response: release = json.loads(response.read(2_000_000))
            asset = next((a for a in release.get('assets') or [] if str(a.get('name', '')).endswith('.dmg')), None)
            link = str((asset or {}).get('browser_download_url') or '')
            trusted = link.startswith('https://github.com/%s/releases/download/' % UPDATE_REPO) or (os.environ.get('ZOOK_UPDATE_URL') and link.startswith('http://127.0.0.1:'))
            with self.lock:
                self.latest = str(release.get('tag_name') or '').lstrip('v'); self.notes = str(release.get('body') or '')[:3000]
                self.asset = dict(url=link, digest=str(asset.get('digest') or ''), size=int(asset.get('size') or 0)) if asset and trusted else None
                self.state, self.checked = 'idle', time.time()
        except (OSError, ValueError, AttributeError, TypeError):
            with self.lock: self.state, self.error, self.checked = 'idle', '無法連上更新伺服器，稍後會再試。', time.time() - 5 * 3600

    def download(self):
        """Fetch and verify the new app, and place it next to the current one ready to swap in."""
        view = self.view()
        if not view['available']: raise RuntimeError('目前沒有可安裝的新版。')
        if not view['canInstall']: raise RuntimeError('這個 Zook 無法自行更新（可能是從磁碟映像直接開啟）。請把 Zook 拖到「應用程式」後再試。')
        with self.lock:
            if self.state in ('downloading', 'ready'): return
            self.state, self.error = 'downloading', ''; asset = dict(self.asset); latest = self.latest
        threading.Thread(target=self._download, args=(asset, latest), daemon=True).start()

    def _download(self, asset, latest):
        work = pathlib.Path(tempfile.mkdtemp(prefix='zook-update-')); mount = work / 'mount'; attached = False
        try:
            image = work / 'Zook.dmg'; digest = hashlib.sha256(); size = 0
            request = urllib.request.Request(asset['url'], headers={'User-Agent': 'Zook-updater'})
            with urllib.request.urlopen(request, timeout=60) as response, open(image, 'wb') as out:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk: break
                    size += len(chunk)
                    if size > UPDATE_MAX_BYTES: raise RuntimeError('下載的檔案過大，已取消。')
                    digest.update(chunk); out.write(chunk)
            if asset['digest'].startswith('sha256:') and asset['digest'][7:].lower() != digest.hexdigest(): raise RuntimeError('下載的檔案和發佈的檢查碼不符，已取消。')
            mount.mkdir()
            run = lambda *argv: subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180).returncode
            if run('/usr/bin/hdiutil', 'attach', '-nobrowse', '-readonly', '-noautoopen', '-mountpoint', str(mount), str(image)) != 0: raise RuntimeError('無法開啟下載的安裝檔。')
            attached = True
            source = next((a for a in mount.glob('*.app') if not a.is_symlink() and bundle_info(a)[0] == self.bundle_id), None)
            if not source: raise RuntimeError('安裝檔裡找不到 Zook。')
            new = version_tuple(bundle_info(source)[1])
            if not new or new != version_tuple(latest) or new <= version_tuple(self.current): raise RuntimeError('安裝檔的版本不正確，已取消。')
            staged = self.app.parent / ('.' + self.app.name + '.update')
            shutil.rmtree(str(staged), ignore_errors=True)
            if run('/usr/bin/ditto', str(source), str(staged)) != 0: raise RuntimeError('無法複製新版。')
            run('/usr/bin/xattr', '-dr', 'com.apple.quarantine', str(staged))
            if run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(staged)) != 0:
                shutil.rmtree(str(staged), ignore_errors=True); raise RuntimeError('新版的簽章驗證失敗，已取消。')
            with self.lock: self.staged, self.state = staged, 'ready'
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            with self.lock: self.state, self.error = 'idle', str(exc) if isinstance(exc, RuntimeError) else '下載更新失敗，請稍後再試。'
        finally:
            if attached: subprocess.run(['/usr/bin/hdiutil', 'detach', '-force', str(mount)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.rmtree(str(work), ignore_errors=True)

    def apply(self):
        """Hand over to a small script that swaps the app once Zook has quit. The caller then quits Zook."""
        with self.lock:
            if self.state != 'ready' or not self.staged or not self.staged.is_dir(): raise RuntimeError('新版還沒準備好。')
            if self.busy(): raise RuntimeError('有 Bot 正在回覆。等它完成後再更新，以免回覆中斷。')
            test = bool(os.environ.get('ZOOK_UPDATE_NO_RELAUNCH'))
            fd, script = tempfile.mkstemp(prefix='zook-update-', suffix='.sh')
            with os.fdopen(fd, 'w') as f: f.write(UPDATE_HELPER)
            os.chmod(script, 0o700)
            subprocess.Popen(['/bin/bash', script, 'none' if test else str(os.getppid()), str(self.app), str(self.staged), '0' if test else '1'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.state = 'applying'


ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07')
LOGIN_TIMEOUT = 600


# Extra accounts. Each CLI keeps a whole account in one folder, and reads an API key from its own environment variable.
ACCOUNT_HOME = {'codex': 'CODEX_HOME', 'claude': 'CLAUDE_CONFIG_DIR', 'grok': 'GROK_HOME', 'gemini': 'GEMINI_CLI_HOME', 'antigravity': 'HOME'}  # agy: only HOME moves it (agyhome.py)
ACCOUNT_KEYS = {'codex': ('CODEX_API_KEY', 'OPENAI_API_KEY'), 'claude': ('ANTHROPIC_API_KEY',), 'grok': ('XAI_API_KEY',), 'gemini': ('GEMINI_API_KEY',), 'cursor': ('CURSOR_API_KEY',)}
ACCOUNT_ID = re.compile(r'[0-9a-f]{32}')
KEYCHAIN_SERVICE = 'Zook account API key'


def find_account(account_id, provider=None):
    """An extra account by id; None for '' (the CLI's own sign-in) or when it belongs to another provider."""
    if not account_id: return None
    hit = next((a for a in _active['data'].get('accounts') or [] if a.get('id') == account_id), None)
    return hit if hit and (provider is None or hit.get('provider') == provider) else None


def account_dir(account_id):
    if not ACCOUNT_ID.fullmatch(account_id or ''): raise ValueError('帳號無效。')
    path = _active['dir'] / 'accounts' / account_id
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _secret_file(account_id):
    """Tests keep keys in a folder instead of the real Keychain."""
    folder = os.environ.get('ZOOK_SECRETS_DIR')
    return pathlib.Path(folder) / account_id if folder and ACCOUNT_ID.fullmatch(account_id or '') else None


def secret_set(account_id, value):
    """Store an API key in the macOS Keychain. The key travels on stdin, never on a command line."""
    _secret_cache.pop(account_id, None)
    if not ACCOUNT_ID.fullmatch(account_id or '') or not re.fullmatch(r'[A-Za-z0-9._~+/=:@-]{8,500}', value or ''): raise ValueError('API 金鑰無效：長度需為 8 到 500 個字元，且只能包含英數字與 . _ ~ + / = : @ -。')
    file = _secret_file(account_id)
    if file:
        fd = os.open(str(file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f: f.write(value)
        return
    command = 'add-generic-password -U -s %s -a %s -w %s\n' % (shlex.quote(KEYCHAIN_SERVICE), account_id, shlex.quote(value))
    p = subprocess.run(['/usr/bin/security', '-i'], input=command.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    if p.returncode != 0 or _secret_read(account_id) != value:
        secret_delete(account_id); raise RuntimeError('無法把 API 金鑰存進鑰匙圈。')


_secret_cache = {}  # Keychain lookups are slow; a value is read once per run and refreshed when it changes.


def secret_get(account_id):
    if account_id not in _secret_cache: _secret_cache[account_id] = _secret_read(account_id)
    return _secret_cache[account_id]


def _secret_read(account_id):
    if not ACCOUNT_ID.fullmatch(account_id or ''): return ''
    file = _secret_file(account_id)
    if file:
        try: return file.read_text().strip()
        except OSError: return ''
    try:
        p = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', account_id, '-w'],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired): return ''
    return p.stdout.decode('utf-8', 'replace').strip() if p.returncode == 0 else ''


def secret_delete(account_id):
    _secret_cache.pop(account_id, None)
    if not ACCOUNT_ID.fullmatch(account_id or ''): return
    file = _secret_file(account_id)
    if file:
        try: file.unlink()
        except OSError: pass
        return
    try: subprocess.run(['/usr/bin/security', 'delete-generic-password', '-s', KEYCHAIN_SERVICE, '-a', account_id],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired): pass


def provider_env(provider, account=None):
    """The CLI's environment. With an extra account, the CLI is pointed at that account's own folder, plus its API key if it is a key account."""
    env = claude_personal_env() if provider == 'claude' else os.environ.copy()
    env.update((P.spec(_active['data'], provider) or {}).get('run_env') or {})
    account = find_account(account, provider) if isinstance(account, str) else account
    if not account: return env
    if provider in ACCOUNT_HOME: env[ACCOUNT_HOME[provider]] = str(agy_account_home(account['id']) if provider == 'antigravity' else account_dir(account['id']))
    if provider == 'gemini' and account.get('type') == 'key':  # its own folder, or Gemini keeps using the saved Google sign-in
        settings = account_dir(account['id']) / '.gemini' / 'settings.json'
        if not settings.exists():
            settings.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            settings.write_text(json.dumps({'security': {'auth': {'selectedType': 'gemini-api-key'}}}), encoding='utf-8')
    if account.get('type') == 'key':
        key = secret_get(account['id'])
        if not key: raise RuntimeError('找不到帳號「%s」的 API 金鑰，請到「各模型使用量」頁重新新增。' % account.get('name', ''))
        for name in ACCOUNT_KEYS.get(provider, ()): env[name] = key
    return env


def account_view(account):
    """What the 各模型使用量 page shows for one extra account."""
    provider = account['provider']
    item = dict(id=account['id'], name=account['name'], type=account['type'], status='unknown', method='', plan='', email='', workspace='')
    if account['type'] == 'key':
        item.update(status='logged_in' if secret_get(account['id']) else 'not_logged_in', method='API 金鑰')
        return item
    full = account_status(provider, account)
    item.update({k: full.get(k, '') for k in ('status', 'method', 'plan', 'email', 'workspace')})
    return item


_agy_status = {}  # `agy models` can take seconds; the page asks often


def account_status(provider, account=None):
    """Login status from the CLI itself. Never reads credential files."""
    path = find_cli(provider); s = P.spec(_active['data'], provider) or {}
    env = provider_env(provider, account); info_key = provider + ('@' + account['id'] if account else '')
    item = dict(id=provider, name=s.get('name', provider), installed=bool(path), status='not_installed' if not path else 'unknown', method='', plan='', email='',
                kind=s.get('kind', ''), custom=bool(s.get('custom')), tools=bool(s.get('tools')), path=path or '', loginNote=s.get('login_note', ''))
    if not path: return item
    try:
        if s.get('kind') == 'grok':
            p = subprocess.run([path, 'models'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=15)
            text = ANSI.sub('', p.stdout.decode('utf-8', 'replace')).lower()
            item['status'] = 'not_logged_in' if 'not authenticated' in text or 'not logged in' in text else ('logged_in' if p.returncode == 0 else 'unknown')
            if item['status'] == 'logged_in':
                item['method'] = 'Grok 帳號'
                item['email'] = str((_active['data'].get('accountInfo') or {}).get(info_key, {}).get('email') or '')
        elif s.get('kind') == 'antigravity':
            cache = (path, account['id'] if account else ''); hit = _agy_status.get(cache)  # each account signs in on its own
            if not hit or time.time() - hit[0] > 30:
                try:
                    p = subprocess.run([path, 'models'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=15)
                    text = ANSI.sub('', p.stdout.decode('utf-8', 'replace')).lower()
                    state = 'not_logged_in' if 'authentication required' in text or 'not logged in' in text or 'please sign in' in text else ('logged_in' if p.returncode == 0 else 'unknown')
                except subprocess.TimeoutExpired: state = 'unknown'
                hit = _agy_status[cache] = (time.time(), state)
            item['status'] = hit[1]
            if item['status'] == 'logged_in': item['method'] = 'Google 帳號'
        elif s.get('kind') == 'cursor':
            if env.get('CURSOR_API_KEY'): item.update(status='logged_in', method='API 金鑰')
            else:
                state, email = cursor_status(path, env)
                item.update(status=state, method='Cursor 帳號' if state == 'logged_in' else '', email=email)
        elif s.get('kind') == 'generic':
            if s.get('signed_in_file'):  # only whether the CLI has signed in; the file is never opened
                signed_in = os.path.exists(os.path.expanduser(s['signed_in_file'])) or bool(env.get('GEMINI_API_KEY'))
                item.update(status='logged_in' if signed_in else 'not_logged_in', method='Google 帳號' if signed_in else '')
            elif s.get('status'):
                p = subprocess.run(shlex.split(s['status']), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                item['status'] = 'logged_in' if p.returncode == 0 else 'not_logged_in'
            else: item['status'] = 'installed'
        elif provider == 'claude':
            p = subprocess.run([path, 'auth', 'status'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, timeout=8)
            data = json.loads(p.stdout or b'{}')
            if isinstance(data.get('loggedIn'), bool): item['status'] = 'logged_in' if data['loggedIn'] else 'not_logged_in'
            if item['status'] == 'logged_in':
                item['method'] = {'claude.ai': 'Claude 訂閱帳號', 'console': 'Anthropic Console'}.get(data.get('authMethod'), str(data.get('authMethod') or ''))
                item['plan'] = str(data.get('subscriptionType') or '')
                item['email'] = str(data.get('email') or '')
        elif provider == 'codex':
            p = subprocess.run([path, 'login', 'status'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=8)
            text = ANSI.sub('', p.stdout.decode('utf-8', 'replace')).strip()
            if p.returncode == 0 and 'logged in' in text.lower() and 'not logged in' not in text.lower():
                item['status'] = 'logged_in'
                item['method'] = 'ChatGPT 帳號' if 'chatgpt' in text.lower() else ('API 金鑰' if 'api key' in text.lower() else text[:60])
                item.update(codex_account(path, account))
            elif 'not logged in' in text.lower() or p.returncode != 0:
                item['status'] = 'not_logged_in'
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return item


_codex_account_cache = {}


def codex_account(path, account=None):
    """Email, plan and workspace of one sign-in from the read-only app-server `account/read` (cached 5 minutes)."""
    key = (path, account['id'] if account else '')
    hit = _codex_account_cache.get(key)
    if hit and time.time() - hit[0] < 300: return dict(hit[1])
    info = {}
    try:
        result = codex_rpc(path, 'account/read', {}, provider_env('codex', account) if account else None)
        account = result.get('account') if isinstance(result, dict) and isinstance(result.get('account'), dict) else {}
        info = {k: v for k, v in (('email', str(account.get('email') or '')), ('plan', str(account.get('planType') or '')),
                                  ('workspace', str(account.get('workspaceName') or ''))) if v}
        if account.get('type') == 'apiKey': info['method'] = 'API 金鑰'
    except (OSError, ValueError, TimeoutError, AttributeError, RuntimeError):
        return {}
    _codex_account_cache[key] = (time.time(), info)
    return dict(info)


class LoginFlow:
    """Runs the provider CLI's own interactive login; Zook never sees credentials."""
    def __init__(self, provider, args, account=None, failure='登入沒有完成。請重試，或在終端機執行登入指令查看詳細訊息。'):
        self.provider, self.lines, self.state, self.error = provider, [], 'running', ''
        self.failure = failure
        self.started = time.time(); self.lock = threading.Lock()
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     env=provider_env(provider, account), start_new_session=True)
        self.reader = threading.Thread(target=self._read, daemon=True); self.reader.start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _read(self):
        for raw in iter(self.proc.stdout.readline, b''):
            line = ANSI.sub('', raw.decode('utf-8', 'replace')).strip()
            if line:
                with self.lock: self.lines = (self.lines + [line[:8000]])[-40:]

    def _watch(self):
        try: code = self.proc.wait(timeout=LOGIN_TIMEOUT)
        except subprocess.TimeoutExpired:
            terminate_tree(self.proc); code = None
        self.reader.join(timeout=5)  # the last lines (who signed in) must be read before the result is announced
        with self.lock:
            if self.state != 'running': return
            if code == 0: self.state = 'succeeded'
            else:
                self.state = 'failed'
                self.error = '登入逾時，請重試。' if code is None else self.failure

    def send(self, text):
        if self.state != 'running' or not self.proc.stdin: raise RuntimeError('登入流程已結束。')
        self.proc.stdin.write((text.strip() + '\n').encode()); self.proc.stdin.flush()

    def cancel(self):
        with self.lock:
            if self.state == 'running': self.state, self.error = 'cancelled', '已取消登入。'
        if self.proc.poll() is None: terminate_tree(self.proc)

    def view(self):
        with self.lock:
            text = '\n'.join(self.lines)
            urls = list(dict.fromkeys(re.findall(r'https?://[^\s<>"\'`]+', text)))
            code = re.findall(r'\b[A-Z0-9]{4}-[A-Z0-9]{4,5}\b', text)
            needs_code = bool(re.search(r'paste|code', text, re.I)) and self.provider == 'claude'
            return dict(state=self.state, error=self.error, url=urls[0] if urls else '', deviceCode=code[-1] if code else '',
                        needsCode=needs_code and self.state == 'running', log=self.lines[-8:])


def cli_issue(text):
    """A plain explanation for account problems a CLI reports in English."""
    text = str(text or '').lower()
    if 'ineligibletiererror' in text or 'no longer supported for gemini code assist' in text:
        return '這個 Google 登入不能用：Google 已不開放個人免費方案使用 Gemini CLI。要用 Gemini，請在用量頁 Gemini 卡片按「＋ 帳號」加入 Gemini API 金鑰（依用量計費），再到 Bot 的進階設定選用它。'
    if 'api_key_invalid' in text or 'api key not valid' in text:
        return 'Google 不接受這把 Gemini API 金鑰，請移除後重新新增。'
    return ''


def guard_gemini_folder(folder, workspace):
    """Gemini obeys a .gemini folder in the place it starts, and a Bot could have written one there to approve its own commands."""
    folder, found = pathlib.Path(folder), pathlib.Path(folder) / '.gemini'
    if folder == pathlib.Path.home() or not os.path.lexists(str(found)): return  # the home folder's .gemini is the user's own Gemini settings
    if folder != pathlib.Path(workspace):
        raise RuntimeError('這個資料夾裡有 .gemini 設定，為了安全，Gemini Bot 不會在這裡執行。請移除該設定，或改用其他資料夾。')
    if found.is_dir() and not found.is_symlink(): shutil.rmtree(str(found))  # Zook's own Bot workspace
    else: found.unlink()


def provider_needs_check(spec, status, record):
    """Whether to try a sign-in once more: never tried, signed in again since, or the last try could not tell."""
    if not spec.get('terminal_login') or not spec.get('signed_in_file') or status != 'logged_in': return False
    if record is None: return True
    if record.get('retryAt') and time.time() >= record['retryAt']: return True
    try: return os.path.getmtime(os.path.expanduser(spec.get('signed_in_file') or '')) > record.get('checkedTs', 0)
    except OSError: return False


def antigravity_settings(native, scope, web, reads=(), blocked=()):
    """This run's settings for agy, never saved. Paid AI credits stay off; 謹慎 and 先規劃 cannot change anything.
    reads: the copies Zook made for this reply (agy_read_paths). agy runs headless and cannot ask, so without an allow
    rule a read it wants approved is denied, and a read-only check could not open the PDF it was asked to check. Reading only."""
    allow, deny = ['mcp(zook/*)'] + ['read_file(%s)' % p for p in reads], []
    if web: allow.append('read_url(*)')
    else: deny += ['read_url(*)', 'execute_url(*)']
    settings = dict(useG1Credits=False)
    if not native:
        settings.update(agentMode='', toolPermission='request-review'); deny += ['write_file(*)', 'command(*)', 'execute_url(*)'] + list(blocked)
    elif scope == 'full': settings['allowNonWorkspaceAccess'] = True
    else: settings['toolPermission'] = 'proceed-in-sandbox'
    settings['permissions'] = dict(allow=allow, deny=list(dict.fromkeys(deny)))
    return settings


def antigravity_args(binary, model, effort, native, planning, scope, folder, web, reads=(), blocked=()):
    """The conversation goes in over stdin (stream-json), so it never shows on a command line."""
    args = [binary, '--input-format', 'stream-json', '--output-format', 'stream-json', '--disable-slash-commands', '--settings', json.dumps(antigravity_settings(native, scope, web, reads, blocked))]
    if planning: args += ['--mode', 'plan']
    elif native and scope == 'full': args += ['--dangerously-skip-permissions']
    elif native: args += ['--mode', 'accept-edits', '--sandbox'] + (['--add-dir', str(folder)] if scope == 'folder' else [])
    return args + (['--model', model] if model else []) + effort_args('antigravity', effort)


AGY_ROOTS = ('.agents', '.agent', '_agents', '_agent')  # agy loads hooks, tools, skills and plugins from any of these
AGY_READ_MAX = 200  # files named one by one in the read rules
try: AGY_QUIET = max(1.0, float(os.environ.get('ZOOK_AGY_QUIET') or 300))  # seconds an Antigravity reply may print nothing
except ValueError: AGY_QUIET = 300.0


AGY_TURNS = '.zook-turns'  # inside the Bot's attachments folder: one folder of copies per read-only turn, removed when it ends
AGY_UNSAFE = set('()[]*?{}')  # letters that would end a read rule early or make it match other files


def agy_read_paths(store, bot_id, job):
    """What a read-only agy turn may read, and a note for its prompt. Each file of this turn (the message's and conversation's
    attachments, the group's files for this turn) is copied from Zook's own copy (the upload, the group's files) into a folder of
    this turn alone, under a name a rule can hold; only those copies are named, one by one. So another conversation's attachments,
    a copy an earlier turn changed, links and hard links a Bot left in its workspace are never what is read, and nothing the Bot
    has is overwritten. Keys and sign-ins (by the name here and the name uploaded with) are left out, as Zook's tools would ask."""
    with store.lock:
        metas = [m for m in (upload_meta(store, x) for x in job.get('attachmentIds') or []) if m]
        group_id, shared = job.get('groupId') if job.get('groupFiles') else None, []
        if group_id:  # the group's own files, those this turn's copy holds (some may be hidden from it)
            here = {e.name for e in _plain_files(group_copy_folder(store, bot_id))}
            try: shared = [(group_original(store, group_id, e.name) or e.name, e.name, pathlib.Path(e.path)) for e in _plain_files(group_files_dir(store, group_id)) if e.name in here]
            except ValueError: shared = []
    sources = [(m.get('origName') or m['name'], m['name'], store.dir / 'uploads' / m['id'] / 'file') for m in metas] + shared
    secret = runtime_module().secret_name
    sources = [s for s in dict((x[2], x) for x in sources).values() if not secret(s[1], s[0])][:AGY_READ_MAX]  # this turn's attachments first
    blocked = agy_blocked(store, bot_id)
    if not sources: return [], '', blocked
    try: folder, fd = agy_turn_folder(store, bot_id, job['id'])
    except (OSError, ValueError): return [], '', blocked
    rules, lines = [], []
    try:
        for i, (_, name, source) in enumerate(sources, 1):
            safe = '%d-%s' % (i, ''.join('_' if c in AGY_UNSAFE or c == '/' or ord(c) < 32 else c for c in name)[:120])
            data = read_group_file(source)  # a plain file of its own, or None
            if data is None: continue
            out = os.open(safe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(out, 'wb') as f: f.write(data)
            path = str(folder / safe); lines.append('- %s：%s' % (name, path))
            rules += [p for p in dict.fromkeys((path, os.path.realpath(path))) if not set(p) & AGY_UNSAFE]
    finally: os.close(fd)
    return rules, ('\n這一輪只能讀下面這些副本（內容和附件或群組檔案相同，請讀這些路徑）：\n' + '\n'.join(lines)) if lines else '', blocked


def agy_turn_folder(store, bot_id, job_id):
    """A new, empty folder for one turn's copies, held open: outside Zook's data folder (a private folder of Zook's in the system's
    temporary folder), because everything of Zook's that is not this Bot's own is closed to the turn (agy_blocked)."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(job_id)): raise ValueError('job')
    base = agy_temp_turns(bot_id)
    parent = os.open(str(base), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: return base / job_id, agy_new_folder(parent, job_id)
    finally: os.close(parent)


def agy_blocked(store, bot_id):
    """What a read-only agy turn may not read. agy reads any file without asking (seen with agy 1.5.14: request-review leaves reads
    alone, and a deny rule wins over an allow rule), so instead of naming what it may read, everything of Zook's except this
    Bot's own workspace is closed: the attachments folder (other conversations' and groups' copies), the other Bots' workspaces
    and the rest of Zook's data. Checked with the real agy 1.5.14: those reads are refused, and this turn's copy is read in full."""
    roots = {str(store.dir), os.path.realpath(str(store.dir))}
    places = [os.path.join(r, n) for r in roots for n in os.listdir(str(store.dir)) if n != 'workspaces']
    try: others = [n for n in os.listdir(str(store.dir / 'workspaces')) if n != bot_id]
    except OSError: others = []
    places += [os.path.join(r, 'workspaces', n) for r in roots for n in others + ['%s/attachments' % bot_id]]
    rules = []
    for place in places:  # a bracket would end the rule: it becomes *, which can only close more, never less
        place = ''.join('*' if c in '()[]{}' else c for c in place)
        rules += ['read_file(%s)' % place, 'read_file(%s/*)' % place, 'read_file(%s/**)' % place]
    return list(dict.fromkeys(rules))


def agy_temp_turns(bot_id):
    """Zook's own folder for turn copies in the temporary folder: real folders, only this user's, no link."""
    base = pathlib.Path(tempfile.gettempdir()) / 'zook-agy-turns'
    for folder in (base, base / bot_id):
        try: os.mkdir(str(folder), 0o700)
        except FileExistsError: pass
        info = os.lstat(str(folder))
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077: raise OSError('turn folder')
    if set(str(base)) & AGY_UNSAFE: raise OSError('turn folder')
    return base / bot_id


def agy_new_folder(parent, name):
    os.mkdir(name, 0o700, dir_fd=parent)  # a turn's folder is new: one already there was not made for it
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def agy_cleanup(store, bot_id, job_id, busy):
    """After an Antigravity reply: its copies go, and, when no other reply of the Bot runs, the tool settings Zook wrote."""
    if not busy: shutil.rmtree(str(store.dir / 'workspaces' / bot_id / '.agents'), ignore_errors=True)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(job_id)): return
    for base in (store.dir / 'workspaces' / bot_id / 'attachments' / AGY_TURNS, pathlib.Path(tempfile.gettempdir()) / 'zook-agy-turns' / bot_id):
        try: parent = os.open(str(base), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError: continue
        try:
            child = os.open(job_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try: clear_folder(child)
            finally: os.close(child)
            os.rmdir(job_id, dir_fd=parent)
        except OSError: pass
        finally: os.close(parent)


def agy_quiet(kind, limit):
    """How long a reply may stay silent. Antigravity streams a line for every step, so a long silence means it is stuck (seen: a
    group member woken with nothing to do sat at 正在思考 for minutes using no CPU); it is stopped sooner than other CLIs."""
    return min(limit, AGY_QUIET) if kind == 'antigravity' else limit


def quiet_reason(kind, limit):
    minutes = max(1, round(limit / 60))
    if kind == 'antigravity': return 'Antigravity 已經 %d 分鐘沒有任何輸出，可能卡住了，已停止這次回覆。請再傳一次。' % minutes
    return '已經 %d 分鐘沒有任何進展。' % minutes


def prepare_antigravity_folder(workspace, scope, folder, wait):
    """Zook's tools reach agy through the workspace's .agents/mcp_config.json. The worker token stays in the environment, never in this file."""
    found = [name for name in AGY_ROOTS if scope == 'folder' and os.path.lexists(str(pathlib.Path(folder) / name))]
    if found: raise RuntimeError('這個資料夾裡有 %s 設定，為了安全，Antigravity Bot 不會在這裡執行。請移除該設定，或改用其他資料夾。' % found[0])
    for name in AGY_ROOTS:  # hooks or tools a Bot left here must not carry over to the next run
        old = pathlib.Path(workspace) / name
        if old.is_symlink() or old.is_file(): old.unlink()
        elif old.exists(): shutil.rmtree(str(old))
    agents = pathlib.Path(workspace) / '.agents'
    agents.mkdir(mode=0o700)
    python = GROK_PYTHON if os.path.exists(GROK_PYTHON) else sys.executable
    (agents / 'mcp_config.json').write_text(json.dumps({'mcpServers': {'zook': {'command': python, 'args': [str(pathlib.Path(__file__).with_name('tool_server.py'))], 'timeoutSeconds': wait}}}), encoding='utf-8')


def antigravity_error(error, stderr=''):
    """A plain explanation of the error agy reported for this run."""
    text = str(error or '').lower()
    if 'authentication required' in text or 'authentication required' in str(stderr or '').lower(): return 'Antigravity 尚未登入，請到「各模型使用量」登入。'
    if 'no capacity' in text or 'code 503' in text: return 'Antigravity 的這個模型目前太忙，請稍後再試或換一個模型。'
    if 'resource_exhausted' in text or 'code 429' in text or 'quota exceeded' in text: return 'Antigravity 的額度已用完，請等額度重置或換一個模型。'
    return ''


def antigravity_quota(path, env=None):
    """Remaining limits from `agy -p /usage`, which uses no model quota itself. env: an extra account's (provider_env). It starts in
    an empty folder of Zook's own, never a Bot's workspace: agy loads tool settings and hooks from the folder it starts in, and a
    Bot's .agents belongs to that Bot's reply. What agy keeps for the account itself (its sign-in) is agy's own; Zook writes none of it."""
    done = subprocess.run([path, '-p', '/usage', '--output-format', 'json'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, cwd=str(agy_empty_folder()), env=env)
    data = json.loads(done.stdout.decode('utf-8', 'replace'))
    windows = []
    for group in ((data.get('command') or {}).get('data') or {}).get('groups') or []:
        name = re.sub(r'\s+models$', ' 模型', str(group.get('name') or ''), flags=re.I).replace(' and ', ' 與 ')
        for bucket in group.get('buckets') or []:
            left = bucket.get('remaining_fraction')
            if isinstance(left, (int, float)):
                period = {'weekly': '每週', 'daily': '每天'}.get(bucket.get('window'), '5 小時' if 'hour' in str(bucket.get('window')) else '')
                windows.append(dict(label=(name + ' · ' + period).strip(' ·'), usedPercent=max(0.0, min(100.0, (1 - float(left)) * 100)), resetsAt=bucket.get('reset_time')))
    return dict(windows=windows, plan='', limitReached=None, credits={}, resetCredits=None, updatedAt=NOW(), source='live') if windows else None


def agy_empty_folder():
    """Zook's own empty folder for agy runs that are not a Bot's reply. Anything left in it (a planted .agents) is removed first."""
    folder = pathlib.Path(_active.get('dir') or tempfile.gettempdir()) / 'tools' / 'agy-empty'
    if folder.is_symlink() or (os.path.lexists(str(folder)) and not folder.is_dir()): folder.unlink()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in os.listdir(str(folder)):
        here = folder / name
        if here.is_symlink() or not here.is_dir(): here.unlink()
        else: shutil.rmtree(str(here))
    return folder


def login_methods(provider):
    s = P.spec(_active['data'], provider) or {}
    if provider == 'claude': return [('claudeai', 'Claude 訂閱帳號登入'), ('console', 'Console（API 計費）')]
    if provider == 'codex': return [('browser', '用 ChatGPT 帳號登入'), ('device', '裝置碼登入')]
    if s.get('login') and isinstance(s['login'], list): return [(m, label) for m, label, _ in s['login']]
    if s.get('login'): return [('custom', '登入')]
    return []


def login_args(provider, method):
    path = find_cli(provider)
    if not path: raise RuntimeError('找不到所選 CLI，請先安裝。')
    s = P.spec(_active['data'], provider) or {}
    if s.get('kind') in ('grok', 'generic'):
        if isinstance(s.get('login'), list):
            hit = next((argv for m, _, argv in s['login'] if m == method), None)
            if not hit: raise ValueError('登入方式無效。')
            return [path] + hit
        if s.get('login'): return shlex.split(s['login'])
        raise RuntimeError('這個 CLI 沒有設定登入指令。')
    if provider == 'claude':
        if method not in ('claudeai', 'console'): raise ValueError('登入方式無效。')
        return [path, 'auth', 'login', '--' + method]
    if method not in ('browser', 'device'): raise ValueError('登入方式無效。')
    return [path, 'login'] + (['--device-auth'] if method == 'device' else [])


_version_cache = {}  # provider -> (checked_at, info); the network part is cached for hours


def provider_version(provider, refresh=False):
    """Installed CLI version and whether the vendor has published a newer one."""
    s = P.spec(_active['data'], provider) or {}
    path = find_cli(provider)
    if not path: return None
    real = os.path.realpath(path)  # an in-place update swaps the target behind the same command name
    hit = _version_cache.get(provider)
    if hit and not refresh and time.time() - hit[0] < 6 * 3600 and hit[1].get('binary') == real: return hit[1]
    info = dict(binary=real, current='', latest='', updateAvailable=False, checkedAt=NOW(), error='')
    try:
        if s.get('version_check'):  # e.g. grok update --check --json
            out = subprocess.run([path] + s['version_check'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20).stdout
            data = json.loads(out.decode('utf-8', 'replace') or '{}')
            info.update(current=P.parse_version(str(data.get('currentVersion') or '')), latest=P.parse_version(str(data.get('latestVersion') or '')))
        else:
            out = subprocess.run([path, '--version'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10).stdout
            info['current'] = P.parse_version(ANSI.sub('', out.decode('utf-8', 'replace')))
            if s.get('latest_url') and not os.environ.get('ZOOK_SKIP_UPDATE_CHECK'):
                req = urllib.request.Request(s['latest_url'], headers={'User-Agent': 'Zook', 'Accept': 'application/json, text/plain'})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    info['latest'] = P.latest_from_response(s['latest_url'], resp.read(4 * 1024 * 1024).decode('utf-8', 'replace'))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        info['error'] = '無法查詢最新版本' if info['current'] else '無法讀取版本'
    if info['current'] and info['latest']:
        info['updateAvailable'] = P.version_key(info['latest']) > P.version_key(info['current'])
    _version_cache[provider] = (time.time(), info)
    return info


def install_args(provider):
    """Install (when missing) or update (when present) using the vendor's own installer or update command."""
    s = P.spec(_active['data'], provider)
    if not s: raise RuntimeError('找不到這個提供者。')
    if s.get('npm_package'):
        return [sys.executable, str(pathlib.Path(__file__).with_name('cli_installer.py')), '--tools', str(_active['dir'] / 'tools'), '--package', s['npm_package'], '--binary', s['binary']]
    path = find_cli(provider)
    if path and s.get('update'): return [path] + s['update']
    if not s.get('install'): raise RuntimeError('這個提供者沒有設定安裝指令。')
    if s.get('requires') and not P.find_binary(s['requires']):
        raise RuntimeError('需要先安裝 %s 才能安裝這個 CLI。' % {'npm': 'Node.js（npm）'}.get(s['requires'], s['requires']))
    return ['/bin/bash', '-lc', s['install']]


def logout_args(provider):
    path = find_cli(provider)
    if not path: raise RuntimeError('找不到所選 CLI。')
    s = P.spec(_active['data'], provider) or {}
    if s.get('kind') in ('grok', 'generic'):
        if s.get('logout'): return [path] + s['logout'] if isinstance(s['logout'], list) else shlex.split(s['logout'])
        raise RuntimeError('這個 CLI 沒有設定登出指令。')
    return [path, 'auth', 'logout'] if provider == 'claude' else [path, 'logout']


ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,80}')
GMAIL_ID = 'builtin:gmail'


def gmail_check(address, password):
    """Sign in to Gmail once, so a wrong address or password is caught when it is saved. Tests skip the network."""
    if os.environ.get('ZOOK_GMAIL_SKIP_CHECK'): return
    import imaplib, ssl
    try:
        box = imaplib.IMAP4_SSL('imap.gmail.com', 993, ssl_context=ssl.create_default_context(), timeout=20)
        try: box.login(address, password)
        finally:
            try: box.logout()
            except (imaplib.IMAP4.error, OSError): pass
    except imaplib.IMAP4.error:
        raise RuntimeError('Gmail 不接受這組信箱和應用程式密碼。請確認帳號已開啟兩步驟驗證、Gmail 設定裡已啟用 IMAP，並重新產生應用程式密碼。')
    except (OSError, ssl.SSLError):
        raise RuntimeError('連不上 Gmail，請確認網路連線後再試。')


def connector_fields(body, existing=None):
    """Validate a connector added in Zook. Returns (record, secret value or None). The secret is stored separately in the Keychain."""
    old = existing or {}
    name = body.get('name', old.get('name'))
    if not isinstance(name, str) or not name.strip() or len(name) > 80: raise ValueError('請輸入連接器名稱。')
    transport = body.get('transport', old.get('transport'))
    record = dict(id=old.get('id') or ID(), name=name.strip(), transport=transport, command='', url='', env={}, secretName='', secretId=old.get('secretId', ''),
                  headers=dict(old.get('headers') or {}), moreSecrets=dict(old.get('moreSecrets') or {}), origin=old.get('origin', ''))
    if transport == 'stdio':
        command = body.get('command', old.get('command'))
        if not isinstance(command, str) or not command.strip() or len(command) > 2000: raise ValueError('請輸入啟動連接器的指令。')
        try: parts = shlex.split(command)
        except ValueError: raise ValueError('指令的引號沒有成對。')
        if not parts: raise ValueError('請輸入啟動連接器的指令。')
        record['command'] = command.strip()
    elif transport == 'http':
        url = body.get('url', old.get('url'))
        parsed = urlsplit(url if isinstance(url, str) else '')
        local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if len(url or '') > 2000 or not parsed.hostname or parsed.username or parsed.password or not (parsed.scheme == 'https' or (parsed.scheme == 'http' and local)):
            raise ValueError('請輸入 https:// 開頭的連接器網址（本機網址可以用 http://）。')
        record['url'] = url.strip()
    else: raise ValueError('連接器類型無效。')
    env = body.get('env', old.get('env') or {})
    if not isinstance(env, dict) or len(env) > 40 or any(not isinstance(k, str) or not ENV_NAME.fullmatch(k) or not isinstance(v, str) or len(v) > 2000 for k, v in env.items()):
        raise ValueError('環境變數的格式不正確，每行寫成 名稱=值。')
    if transport == 'http' and env: raise ValueError('網址類型的連接器不使用環境變數。')
    record['env'] = dict(env)
    clear = body.get('clearSecret') is True  # the user removed the key
    secret = body.get('secret')
    if secret is not None and not isinstance(secret, str): raise ValueError('金鑰無效。')
    secret = secret.strip() if secret else None
    if transport == 'http': secret_name = 'Authorization' if not clear and (secret or old.get('secretId')) else ''
    else: secret_name = '' if clear else body.get('secretName', old.get('secretName') or '')
    if not isinstance(secret_name, str) or (secret_name and not ENV_NAME.fullmatch(secret_name)): raise ValueError('金鑰的環境變數名稱不正確。')
    record['secretName'] = secret_name
    if secret and not secret_name: raise ValueError('請填寫金鑰要放進哪個環境變數。')
    if secret_name and not secret and not old.get('secretId'): raise ValueError('請貼上金鑰。')
    if not secret_name: secret = None
    return record, secret


def connector_view(record):
    """What the interface may know about a Zook connector: everything except the secret itself."""
    return dict(command=record.get('command', ''), url=record.get('url', ''), env=record.get('env') or {},
                secretName=record.get('secretName', ''), hasSecret=bool(record.get('secretId')),
                moreSecrets=[dict(name=k, saved=bool(v)) for k, v in sorted((record.get('moreSecrets') or {}).items())])


# ---- Zook's own copies of Skills and connectors ----------------------------------------------------
SKILL_SKIP = {'.git', 'node_modules', '__pycache__', '.venv', '.DS_Store'}
SKILL_BYTES = 20 * 1024 * 1024
SKILL_FILES = 2000
PACK_BYTES = 150 * 1024 * 1024
ZOOK_SKILL = 'skill-zook:'


def same_name(value): return re.sub(r'\s+', ' ', str(value or '')).strip().lower()


def skills_home(store):
    path = store.dir / 'skills'; path.mkdir(exist_ok=True, mode=0o700)
    return path


def skill_files(root):
    """(relative path, file) for every regular file in a Skill folder. Links and build folders are left out."""
    root = pathlib.Path(root); found = []; total = 0
    for folder, dirs, files in os.walk(str(root)):
        dirs[:] = sorted(d for d in dirs if d not in SKILL_SKIP and not os.path.islink(os.path.join(folder, d)))
        for name in sorted(files):
            path = pathlib.Path(folder) / name
            if name in SKILL_SKIP or path.is_symlink() or not path.is_file(): continue
            total += path.stat().st_size; found.append((str(path.relative_to(root)), path))
            if len(found) > SKILL_FILES or total > SKILL_BYTES: raise ValueError('這個 Skill 的資料夾太大（超過 20 MB 或 2000 個檔案），無法匯入。')
    return found


def skill_stamp(root):
    """Changes whenever a file in the folder is added, removed or edited. Cheap: file contents are not read."""
    h = hashlib.sha256()
    try:
        for relative, path in skill_files(root):
            info = path.stat(); h.update(('%s\0%d\0%d\n' % (relative, info.st_size, info.st_mtime_ns)).encode())
    except (OSError, ValueError): return ''
    return h.hexdigest()


def skill_copy(source, target):
    files = skill_files(source)
    if not any(relative == 'SKILL.md' for relative, _ in files): raise ValueError('這個資料夾裡沒有 SKILL.md。')
    temp = pathlib.Path(tempfile.mkdtemp(prefix='.incoming-', dir=str(target.parent)))
    try:
        for relative, path in files:
            out = temp / relative; out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(path), str(out))
        if target.exists(): shutil.rmtree(str(target))
        os.replace(str(temp), str(target))
    except BaseException:
        shutil.rmtree(str(temp), ignore_errors=True); raise


def skill_folder(name, taken):
    base = re.sub(r'[^A-Za-z0-9_-]+', '-', name).strip('-')[:60] or 'skill'
    folder, n = base, 2
    while folder.lower() in taken: folder = '%s-%d' % (base, n); n += 1
    return folder


def skill_title(root, fallback):
    try: text = (root / 'SKILL.md').read_text(errors='replace')[:128 * 1024]
    except OSError: return fallback, ''
    name, description = runtime_module()._frontmatter(text)
    return name or fallback, description


def skills_import(store, inventory, ids):
    """Copy Skills from other tools into Zook's own folder. A name Zook already has is not copied twice."""
    home = skills_home(store); done, skipped, failed = [], [], []
    for ident in ids:
        entry = next((x for x in inventory['skills'] if x['id'] == ident), None); private = inventory['_private']['skills'].get(ident)
        if not entry or not private or entry.get('source') == 'zook': continue
        with store.lock: have = {same_name(x['name']) for x in store.data['skills']}; taken = {x['folder'].lower() for x in store.data['skills']}
        if same_name(entry['name']) in have: skipped.append(entry['name']); continue
        folder = skill_folder(entry['name'], taken)
        try: skill_copy(private['root'], home / folder)
        except ValueError as exc: failed.append(dict(name=entry['name'], error=str(exc))); continue
        except OSError: failed.append(dict(name=entry['name'], error='讀不到這個 Skill 的檔案。')); continue
        record = dict(id=ID(), name=entry['name'], folder=folder, origin=entry.get('plugin') or entry['source'], originPath=private['root'], stamp=skill_stamp(private['root']))
        with store.lock:
            store.data['skills'].append(record)
            off = store.data['settings']['disabledSkills']
            if ident in off: off.append(ZOOK_SKILL + record['id'])  # a Skill you had switched off stays off
            store.save()
        done.append(entry['name'])
    return dict(imported=done, skipped=skipped, failed=failed)


CLI_ONLY_TOOLS = (('Claude', ('AskUserQuestion', 'TodoWrite', 'NotebookEdit', 'ExitPlanMode', 'claude-in-chrome', 'computer-use')),
                  ('Codex', ('apply_patch',)))
_notes_cache = {}


def skill_needs(path):
    """Connector names and single-CLI tools a Skill's instructions mention. Read once per file version."""
    try: info = os.stat(path); key = (path, info.st_mtime_ns, info.st_size)
    except OSError: return [], []
    if key not in _notes_cache:
        try:
            with open(path, encoding='utf-8', errors='replace') as f: text = f.read(128 * 1024)
        except OSError: text = ''
        servers = []
        for server in dict.fromkeys(re.findall(r'mcp__([A-Za-z0-9_.-]+?)__[A-Za-z]', text)):
            label = re.sub(r'^(claude_ai_|plugin_[A-Za-z0-9-]+_)', '', server).replace('_', ' ').strip()
            if label and not re.fullmatch(r'[0-9a-f-]{20,}', server): servers.append(label)
        tools = [(cli, [t for t in names if re.search(r'(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])' % re.escape(t), text)]) for cli, names in CLI_ONLY_TOOLS]
        if len(_notes_cache) > 4000: _notes_cache.clear()
        _notes_cache[key] = (list(dict.fromkeys(servers))[:12], [(cli, found) for cli, found in tools if found])
    return _notes_cache[key]


def skill_notes(path, connectors):
    """What a Skill asks for that Zook may not have. `connectors` is [(name in lower-case letters and digits, switched on)]."""
    servers, tools = skill_needs(path); missing, off, notes = [], [], []
    for label in servers:
        key = re.sub(r'[^a-z0-9]', '', label.lower())
        hits = [on for name, on in connectors if len(key) >= 3 and len(name) >= 3 and (key in name or name in key)]
        if not hits: missing.append(label)
        elif not any(hits): off.append(label)
    if missing: notes.append('會用到連接器' + ''.join('「%s」' % x for x in missing[:6]) + '，Zook 裡沒有。')
    if off: notes.append('會用到的連接器' + ''.join('「%s」' % x for x in off[:6]) + '還沒開啟。')
    for cli, found in tools: notes.append('提到 %s 專屬的工具（%s），其他模型的 Bot 可能無法照做。' % (cli, '、'.join(found)))
    return notes


def connector_from_config(name, config):
    """A connector read from another tool's settings, as a Zook connector. Returns (record, {name: secret value})."""
    transport, found, fields = config.get('transport'), {}, dict(name=name, transport=config.get('transport'), env={})
    headers = {}
    if transport == 'stdio':
        command, args = config.get('command'), config.get('args') or []
        if not isinstance(command, str) or not command or not isinstance(args, list) or any(not isinstance(a, str) for a in args): raise ValueError('這個連接器的指令設定不完整，無法複製。')
        fields['command'] = ' '.join(shlex.quote(x) for x in [command] + args)
        env = config.get('env') if isinstance(config.get('env'), dict) else {}
        for key, value in env.items():
            if not isinstance(key, str) or not isinstance(value, str): raise ValueError('這個連接器的環境變數格式 Zook 讀不懂，無法複製。')
            if value and runtime_module().SECRET_KEY.search(key): found[key] = value
            else: fields['env'][key] = value
    elif transport == 'http':
        fields['url'] = config.get('url')
        for source in ('headers', 'http_headers'):
            if isinstance(config.get(source), dict): headers.update(config[source])
        for key, variable in (config.get('env_http_headers') or {}).items():
            if os.environ.get(variable): headers[key] = os.environ[variable]
        if config.get('bearer_token_env_var') and os.environ.get(config['bearer_token_env_var']): headers['Authorization'] = 'Bearer ' + os.environ[config['bearer_token_env_var']]
        for key, value in list(headers.items()):
            if not isinstance(key, str) or not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', key) or len(value) > 2000 or '\n' in value or '\r' in value:
                raise ValueError('這個連接器的標頭設定 Zook 讀不懂，無法複製。')
            if key.lower() == 'authorization' and value.startswith('Bearer '): found['Authorization'] = value[7:].strip(); del headers[key]
            elif key.lower() == 'authorization' or runtime_module().SECRET_KEY.search(key): raise ValueError('這個連接器用的驗證方式 Zook 還不支援，無法複製。請改用「新增連接器」。')
    else: raise ValueError('Zook 只支援本機指令和網址（Streamable HTTP）這兩種連接器。')
    record, _ = connector_fields(fields)
    record['headers'] = headers
    return record, found


