"""Selected-only MCP and Skills broker. Python 3.9+, no executable config evaluation.

Configuration snapshots contain credentials and MUST remain private. Only the
skills/mcp catalog arrays may be returned to the UI.
"""
import copy
import glob
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_MESSAGE = 2 * 1024 * 1024
MAX_TEXT = 128 * 1024
MAX_TOOLS = 512
TIMEOUT = 30
PROTOCOL = '2025-06-18'
SECRET_KEY = re.compile(r'(?i)(token|password|secret|authorization|api[_-]?key|cookie|credential)')


def _json_file(path):
    try:
        if path.stat().st_size > MAX_MESSAGE:
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _toml_file(path):
    if not path.exists():
        return {}
    try:
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                try:
                    from ._vendor import tomli as tomllib
                except ImportError:
                    from _vendor import tomli as tomllib
        if path.stat().st_size > MAX_MESSAGE:
            return {}
        return tomllib.loads(path.read_text())
    except (ImportError, OSError, ValueError):
        return {}


def _sid(source, name):
    return source + ':' + hashlib.sha256(name.encode()).hexdigest()[:20]


def _frontmatter(text):
    name, description = '', ''
    if text.startswith('---'):
        for line in text.split('---', 2)[1].splitlines()[:80]:
            if line.startswith('name:'):
                name = line[5:].strip().strip('\"\'')
            if line.startswith('description:'):
                description = line[12:].strip().strip('\"\'')
    return name, description


PLUGIN_SOURCES = {'claude-code': 'Claude Code'}


def _plugin_dirs(home):
    """Install folders of the plugins installed in Claude Code."""
    found = []
    installed = _json_file(home / '.claude/plugins/installed_plugins.json').get('plugins', {})
    if isinstance(installed, dict):
        for entries in list(installed.values())[:200]:
            entry = entries[0] if isinstance(entries, list) and entries and isinstance(entries[0], dict) else {}
            if isinstance(entry.get('installPath'), str): found.append(('claude-code', Path(entry['installPath'])))
    return found


def _plugin_expand(value, root):
    if isinstance(value, str): return value.replace('${CLAUDE_PLUGIN_ROOT}', str(root))
    if isinstance(value, list): return [_plugin_expand(v, root) for v in value]
    if isinstance(value, dict): return {k: _plugin_expand(v, root) for k, v in value.items()}
    return value


def _inside(root, relative):
    if not isinstance(relative, str) or not relative: return None
    try:
        path = (root / relative).resolve()
        path.relative_to(root)
        return path
    except (OSError, ValueError):
        return None


def _plugin_servers(root, spec):
    specs = spec if isinstance(spec, list) else [spec]
    servers = {}
    for item in specs[:20]:
        if isinstance(item, str):
            path = _inside(root, item)
            item = _json_file(path) if path else {}
        if isinstance(item, dict):
            item = item.get('mcpServers', item)
            for name, config in list(item.items())[:64]:
                if isinstance(name, str) and isinstance(config, dict): servers[name] = _plugin_expand(config, root)
    return servers


def discover(home=None):
    home = Path(home) if home is not None else Path.home()
    private = {'skills': {}, 'mcp': {}}
    result = {'skills': [], 'mcp': [{'id': 'builtin:workspace', 'name': 'Bot workspace',
              'source': 'builtin', 'transport': 'builtin', 'status': 'ready'}], 'plugins': [], '_private': private}
    sources = [('codex', _toml_file(home / '.codex/config.toml').get('mcp_servers', {})),
               ('claude', _json_file(home / '.claude.json').get('mcpServers', {}))]
    for source, servers in sources:
        if not isinstance(servers, dict):
            continue
        for name, config in list(servers.items())[:256]:
            if not isinstance(config, dict) or not isinstance(name, str):
                continue
            ident = _sid(source, name)
            transport = config.get('type') or ('stdio' if config.get('command') else 'http')
            transport = {'streamable-http': 'http', 'streamable_http': 'http'}.get(transport, transport)
            private['mcp'][ident] = copy.deepcopy(config)
            private['mcp'][ident]['transport'] = transport
            result['mcp'].append({'id': ident, 'name': name[:160], 'source': source,
                                  'transport': transport, 'status': 'disabled' if config.get('enabled') is False else 'configured'})
    plugin_skill_roots = []
    for source, root in _plugin_dirs(home):
        try:
            root = root.resolve()
            manifest = _json_file(root / '.claude-plugin/plugin.json')
        except OSError:
            continue
        name = manifest.get('name') if isinstance(manifest.get('name'), str) else root.name
        plugin_id = 'plugin:' + re.sub('[^A-Za-z0-9_.-]', '_', name)[:80]
        if any(p['id'] == plugin_id for p in result['plugins']):
            continue  # Same plugin installed in several places: first source wins.
        ui = manifest.get('interface') if isinstance(manifest.get('interface'), dict) else {}
        skills_spec = manifest.get('skills', 'skills' if (root / 'skills').is_dir() else [])
        skill_dirs = [d for d in (_inside(root, x) for x in (skills_spec if isinstance(skills_spec, list) else [skills_spec])[:20]) if d and d.is_dir()]
        servers = _plugin_servers(root, manifest.get('mcpServers', '.mcp.json' if (root / '.mcp.json').is_file() else []))
        before = len(result['skills'])
        for d in skill_dirs: plugin_skill_roots.append((plugin_id, d))
        for server, config in servers.items():
            ident = _sid('plugin-' + name, server)
            transport = config.get('type') or ('stdio' if config.get('command') else 'http')
            transport = {'streamable-http': 'http', 'streamable_http': 'http'}.get(transport, transport)
            private['mcp'][ident] = copy.deepcopy(config); private['mcp'][ident]['transport'] = transport
            result['mcp'].append({'id': ident, 'name': server[:160], 'source': plugin_id, 'plugin': plugin_id, 'transport': transport, 'status': 'configured'})
        author = manifest.get('author', {})
        result['plugins'].append({'id': plugin_id, 'name': name[:120], 'displayName': str(ui.get('displayName') or name)[:120],
            'description': str(ui.get('shortDescription') or manifest.get('description') or '')[:500],
            'version': str(manifest.get('version') or '')[:40], 'author': str(author.get('name') if isinstance(author, dict) else author or '')[:120],
            'source': source, 'sourceName': PLUGIN_SOURCES.get(source, source), 'mcpCount': len(servers), 'skillCount': 0,
            'hasHooks': (root / 'hooks').is_dir() or 'hooks' in manifest, 'hasCommands': (root / 'commands').is_dir() or 'commands' in manifest})
    roots = [('agents', home / '.agents/skills'), ('codex', home / '.codex/skills'), ('claude', home / '.claude/skills')]
    repo = _json_file(home / '.config/sean-agents/config.json').get('repo')
    if isinstance(repo, str):
        private['shared_rules'] = [str(Path(repo) / name) for name in ('SHARED-AGENT-RULES.md', 'SERVICE-AUTH.md')]
        roots.append(('shared', Path(repo) / 'skills'))
    seen = set()
    plugins = {p['id']: p for p in result['plugins']}
    for source, root in roots + [(pid, d) for pid, d in plugin_skill_roots]:
        pending = [(root, 0)]
        visited = 0
        while pending and visited < 4000 and len(result['skills']) < 1024:
            directory, depth = pending.pop()
            visited += 1
            try:
                resolved = directory.resolve()
                if resolved in seen or not directory.is_dir():
                    continue
                seen.add(resolved)
                skill = directory / 'SKILL.md'
                if skill.is_file() and skill.stat().st_size <= MAX_TEXT:
                    name, description = _frontmatter(skill.read_text(errors='replace'))
                    plugin = plugins.get(source)
                    ident = _sid('skill-' + source + ('' if not plugin else ':' + str(root)), str(directory.relative_to(root)))
                    private['skills'][ident] = {'path': str(skill.resolve()), 'root': str(resolved)}
                    entry = {'id': ident, 'name': name or directory.name, 'description': description[:1500], 'path': str(skill), 'source': source}
                    if plugin: entry['plugin'] = source; plugin['skillCount'] += 1
                    result['skills'].append(entry)
                    continue
                if depth < 5:
                    children = sorted(directory.iterdir(), key=lambda p: p.name)[:512]
                    pending.extend((p, depth + 1) for p in reversed(children)
                                   if p.name not in ('.git', 'node_modules', '__pycache__', '.venv') and p.is_dir())
            except (OSError, ValueError):
                continue
    result['skills'].sort(key=lambda x: (x['name'].lower(), x['id']))
    return result


class Redactor:
    def __init__(self, inventory):
        self.secrets = set()
        def gather(value, key=''):
            if isinstance(value, dict):
                for k, v in value.items():
                    gather(v, k)
            elif isinstance(value, list):
                for v in value:
                    gather(v, key)
            elif isinstance(value, str) and (SECRET_KEY.search(key) or key in ('url', 'args')):
                if len(value) >= 5:
                    self.secrets.add(value)
        gather(inventory.get('_private', {}).get('mcp', {}))
        for key, value in os.environ.items():
            if SECRET_KEY.search(key) and len(value) >= 5:
                self.secrets.add(value)

    def text(self, value):
        text = str(value)
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, '[redacted]')
        # URL userinfo (user:pass@) and credential-like query parameters.
        text = re.sub(r'(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@', r'\1[redacted]@', text)
        text = re.sub(r'(?i)([?&][^=&#\s]*(?:token|password|secret|api[_-]?key|key|auth|sig|signature|credential)[^=&#\s]*=)[^&#\s]*', r'\1[redacted]', text)
        return text[:MAX_TEXT]

    def value(self, value, redact_keys=True):
        if isinstance(value, dict):
            return {str(k): ('[redacted]' if redact_keys and SECRET_KEY.search(str(k)) else self.value(v, redact_keys)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.value(v, redact_keys) for v in value]
        return self.text(value) if isinstance(value, str) else value


# An app opened from Finder does not get the shell's PATH, so connectors started with npx, uvx, node and
# the like would not be found. These are the usual places such tools are installed.
TOOL_DIRS = ('~/.local/bin', '/opt/homebrew/bin', '/usr/local/bin', '~/.npm-global/bin', '~/.bun/bin', '~/.volta/bin',
             '~/.cargo/bin', '~/.deno/bin', '~/.nvm/versions/node/*/bin')


def tool_path(current):
    parts = [p for p in (current or '').split(os.pathsep) if p]
    for pattern in TOOL_DIRS:
        for folder in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)[:1]:  # the newest Node version only
            if os.path.isdir(folder) and folder not in parts: parts.append(folder)
    return os.pathsep.join(parts)


_SHELL_ENV = None
_SHELL_LOCK = threading.Lock()
_OWN = ('ZOOK_', 'SWARMR_', 'CLAUDECODE', 'CLAUDE_CODE_')


def shell_environment():
    """The variables the user's login shell sets (from ~/.zshrc and the like). An app opened from the Dock gets none
    of them, so a connector that reads its sign-in from one works in a terminal tool and fails here. Read once."""
    global _SHELL_ENV
    with _SHELL_LOCK:
        if _SHELL_ENV is not None: return _SHELL_ENV
        found = {}
        shell = os.environ.get('SHELL') or '/bin/zsh'
        if os.environ.get('ZOOK_SHELL_ENV') != '0' and os.access(shell, os.X_OK):
            mark = '__zook_env_%s__' % uuid.uuid4().hex
            try:
                done = subprocess.run([shell, '-ilc', 'printf %s ' + mark + '; /usr/bin/env -0'], stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8, start_new_session=True)
                text = done.stdout.decode('utf-8', 'replace')
                if mark in text:
                    for item in text.split(mark, 1)[1].split('\0'):
                        key, eq, value = item.partition('=')
                        if eq and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) and not key.startswith(_OWN): found[key] = value
            except (OSError, subprocess.SubprocessError): pass
        _SHELL_ENV = found
        return found


def _lookup(name):
    return os.environ[name] if name in os.environ else shell_environment().get(name)


def _expand(value):
    """${VAR} and ${VAR:-default}, the way Claude Code reads them in a connector's settings."""
    if isinstance(value, str) and '${' in value:
        def swap(match):
            found = _lookup(match.group(1))
            if found is None: found = match.group(2)
            return match.group(0) if found is None else found
        return re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}', swap, value)
    if isinstance(value, list): return [_expand(v) for v in value]
    if isinstance(value, dict): return {k: _expand(v) for k, v in value.items()}
    return value


def _environment(config=None):
    env = {k: v for k, v in os.environ.items() if not SECRET_KEY.search(k) and not k.startswith(_OWN)}
    path = env.get('PATH') or '/usr/bin:/bin:/usr/sbin:/sbin'
    if config is not None:  # a connector: give it what a terminal would
        shell = shell_environment()
        for key, value in shell.items():
            if key != 'PATH': env.setdefault(key, value)
        have = path.split(os.pathsep)
        path = os.pathsep.join(have + [d for d in shell.get('PATH', '').split(os.pathsep) if d and d not in have])
    config = config or {}
    env['PATH'] = tool_path(path)
    for key in config.get('env_vars', []):
        if isinstance(key, str) and _lookup(key) is not None:
            env[key] = _lookup(key)
    for key, value in config.get('env', {}).items():
        if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
            env[key] = str(value)
    return env


class ProtocolClient:
    def __init__(self, config):
        config = dict(config)
        for field in ('command', 'args', 'env', 'url', 'headers', 'http_headers'):
            if field in config: config[field] = _expand(config[field])
        self.config = config
        self.closed = False
        self.lock = threading.Lock()
        self.counter = 0
        self.session_id = None
        self.protocol = PROTOCOL
        self.process = None
        self.responses = queue.Queue(maxsize=128)
        transport = config.get('transport', config.get('type', 'stdio'))
        if config.get('enabled') is False:
            raise RuntimeError('This configured server is disabled. Enable it in its owning app first.')
        if transport == 'sse':
            raise RuntimeError('Legacy SSE is unsupported. Configure this server with its Streamable HTTP MCP endpoint.')
        if transport == 'stdio':
            command, args = config.get('command'), config.get('args', [])
            if not isinstance(command, str) or not isinstance(args, list) or not all(isinstance(x, str) for x in args):
                raise RuntimeError('Invalid configured MCP command or arguments.')
            env = _environment(config)
            program = os.path.expanduser(command)
            if '/' not in program:  # look the command up in the widened PATH, not only the app's own
                program = next((os.path.join(d, program) for d in env['PATH'].split(os.pathsep) if os.access(os.path.join(d, program), os.X_OK)), None)
                if not program: raise RuntimeError('找不到連接器的指令「%s」。請先安裝它，或在來源 App 的設定裡改成完整路徑。' % command)
            self.errors = tempfile.TemporaryFile()  # what the connector prints when it fails, shown to the user as the reason
            try:
                self.process = subprocess.Popen([program] + args, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=self.errors, env=env, start_new_session=True)
            except (OSError, ValueError):
                raise RuntimeError('Configured MCP executable could not start. Install or authorize it in its owning app, then retry.')
            threading.Thread(target=self._reader, daemon=True).start()
        elif transport in ('http', 'streamable-http', 'streamable_http'):
            url = config.get('url', '')
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                raise RuntimeError('Configure a valid HTTP MCP endpoint without embedded credentials.')
            if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
                raise RuntimeError('Remote MCP endpoints require HTTPS; HTTP is allowed only on loopback.')
        else:
            raise RuntimeError('Unsupported MCP transport. Configure stdio or Streamable HTTP.')
        try:
            initialized = self.request('initialize', {'protocolVersion': PROTOCOL, 'capabilities': {},
                                                    'clientInfo': {'name': 'zook', 'version': '0.2.0'}})
            self.protocol = initialized.get('protocolVersion', PROTOCOL)
            if self.protocol not in ('2024-11-05', '2025-03-26', PROTOCOL, '2025-11-25'):
                raise RuntimeError('Server negotiated an unsupported MCP protocol version.')
            self.notify('notifications/initialized')
        except Exception:
            self.close()
            raise

    def _reader(self):
        skipped = 0
        try:
            while not self.closed:
                line = self.process.stdout.readline(MAX_MESSAGE + 1)
                if not line or len(line) > MAX_MESSAGE:
                    break
                try:
                    msg = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    msg = None
                if not isinstance(msg, dict):  # a banner or log line on standard output; some connectors print one before they are ready
                    skipped += 1
                    if skipped > 500: break
                    continue
                self.responses.put_nowait(msg)
        except (OSError, ValueError, queue.Full):
            pass
        try:
            self.responses.put_nowait({'_closed': True})
        except queue.Full:
            pass

    def _last_error(self):
        """The last lines the connector wrote to its error output, with anything secret-looking removed."""
        try:
            time.sleep(0.2); self.errors.seek(0)
            lines = [l.strip() for l in self.errors.read(200000).decode('utf-8', 'replace').splitlines() if l.strip()]
        except (OSError, ValueError, AttributeError):
            return ''
        text = re.sub(r'(?i)((?:token|password|secret|authorization|api[_-]?key|cookie|bearer)[\w-]*)(\s*[=:]\s*|\s+)\S+', r'\1\2***', ' / '.join(lines[-3:]))
        return ('它回報：' + text[:400]) if text else ''

    def _send_stdio(self, msg):
        try:
            self.process.stdin.write(json.dumps(msg, separators=(',', ':')).encode() + b'\n')
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise RuntimeError('MCP process disconnected. Check authorization in its owning app and reconnect.')

    def _http(self, msg):
        headers = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json',
                   'MCP-Protocol-Version': self.protocol}
        headers.update(self.config.get('headers', {}))
        headers.update(self.config.get('http_headers', {}))
        for key, envname in self.config.get('env_http_headers', {}).items():
            if _lookup(envname) is None:
                raise RuntimeError('A configured MCP credential environment variable is unavailable. Authorize it in its owning app.')
            headers[key] = _lookup(envname)
        token = self.config.get('bearer_token_env_var')
        if token:
            if _lookup(token) is None:
                raise RuntimeError('MCP bearer credential is unavailable. Authorize it in its owning app.')
            headers['Authorization'] = 'Bearer ' + _lookup(token)
        if self.session_id:
            headers['Mcp-Session-Id'] = self.session_id
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect())
        request = urllib.request.Request(self.config['url'], data=json.dumps(msg).encode(), headers=headers, method='POST')
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                sid = response.headers.get('Mcp-Session-Id')
                if sid:
                    self.session_id = sid
                if 'id' not in msg:
                    return None
                if response.headers.get_content_type() == 'text/event-stream':
                    deadline, size, data = time.monotonic() + TIMEOUT, 0, []
                    while time.monotonic() < deadline:
                        line = response.readline(MAX_MESSAGE + 1)
                        size += len(line)
                        if size > MAX_MESSAGE:
                            raise RuntimeError('MCP response exceeds the size limit.')
                        if not line:
                            break
                        decoded = line.decode('utf-8').rstrip('\r\n')
                        if decoded.startswith('data:'):
                            data.append(decoded[5:].lstrip(' '))
                        elif not decoded and data:
                            item = json.loads('\n'.join(data)); data = []
                            if item.get('id') == msg['id'] and ('result' in item or 'error' in item):
                                return item
                    raise RuntimeError('MCP SSE response ended without a matching result; reconnect and retry.')
                body = response.read(MAX_MESSAGE + 1)
                if len(body) > MAX_MESSAGE:
                    raise RuntimeError('MCP response exceeds the size limit.')
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError('MCP authorization was rejected. Sign in or refresh access in the owning app, then reconnect.')
            raise RuntimeError('MCP HTTP request failed (status %s). Verify the configured MCP endpoint.' % exc.code)
        except (urllib.error.URLError, OSError, ValueError):
            raise RuntimeError('MCP endpoint did not return a valid response. Check connectivity and its configured transport.')

    def notify(self, method):
        msg = {'jsonrpc': '2.0', 'method': method}
        if self.process:
            self._send_stdio(msg)
        else:
            self._http(msg)

    def request(self, method, params):
        with self.lock:
            if self.closed:
                raise RuntimeError('MCP session is closed.')
            self.counter += 1
            msg = {'jsonrpc': '2.0', 'id': self.counter, 'method': method, 'params': params}
            if self.process:
                self._send_stdio(msg)
                deadline = time.monotonic() + TIMEOUT
                while True:
                    try:
                        response = self.responses.get(timeout=max(0.01, deadline - time.monotonic()))
                    except queue.Empty:
                        self.close()
                        raise RuntimeError('MCP request timed out. Check server readiness and reconnect.')
                    if response.get('_closed'):
                        raise RuntimeError('連接器啟動後就結束了。' + (self._last_error() or '請確認它的設定，以及是否已在來源 App 登入授權。'))
                    if response.get('method') and 'id' in response:
                        if response['method'] == 'ping':
                            self._send_stdio({'jsonrpc': '2.0', 'id': response['id'], 'result': {}})
                        else:
                            self._send_stdio({'jsonrpc': '2.0', 'id': response['id'], 'error': {'code': -32601, 'message': 'Client capabilities are not enabled'}})
                    if response.get('id') == msg['id'] and ('result' in response or 'error' in response):
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError('MCP request timed out.')
            else:
                response = self._http(msg)
            if not isinstance(response, dict) or response.get('id') != msg['id']:
                raise RuntimeError('MCP response ID did not match the request.')
            if 'error' in response:
                # Server error text may contain credentials/endpoint internals.
                raise RuntimeError('MCP server rejected %s (code %s). Check required arguments and server authorization.' %
                                   (method, response.get('error', {}).get('code', 'unknown')))
            result = response.get('result')
            if not isinstance(result, dict):
                raise RuntimeError('MCP returned an invalid result object.')
            return result

    def tools(self):
        tools, cursor, seen = [], None, set()
        for _ in range(16):
            page = self.request('tools/list', {'cursor': cursor} if cursor else {})
            entries = page.get('tools', [])
            if not isinstance(entries, list):
                raise RuntimeError('MCP tools/list returned an invalid catalog.')
            tools.extend(entries)
            if len(tools) > MAX_TOOLS:
                raise RuntimeError('MCP catalog exceeds 512 tools. Limit the server tool profile before reconnecting.')
            cursor = page.get('nextCursor')
            if not cursor:
                return tools
            if not isinstance(cursor, str) or cursor in seen:
                raise RuntimeError('MCP tools/list returned an invalid pagination cursor.')
            seen.add(cursor)
        raise RuntimeError('MCP catalog exceeds the pagination limit. Limit its tool profile.')

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process:
            try:
                self.process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            try:
                self.process.stdout.close()
            except (OSError, ValueError):
                pass
        try:
            self.responses.put_nowait({'_closed': True})
        except queue.Full:
            pass


def _schema(name, description, properties, required=(), read_only=True):
    return {'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': properties,
            'required': list(required), 'additionalProperties': False},
            'annotations': {'readOnlyHint': read_only, 'destructiveHint': not read_only, 'openWorldHint': False}}


def _str(description):
    return {'type': 'string', 'description': description}


def _content(value):
    return {'content': [{'type': 'text', 'text': value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}]}


PERMISSION_MODES = ('manual', 'auto', 'bypass')
# Which tool categories still need a person's approval in each mode.
ASK_IN_MODE = {'manual': {'internal', 'external_read', 'code', 'external_write', 'danger'},
               'auto': {'code', 'external_write', 'danger'},
               'bypass': {'danger'}}
# Delete, security and irreversible outbound actions always need approval.
DANGER_WORDS = {'delete', 'remove', 'trash', 'destroy', 'drop', 'purge', 'wipe', 'erase', 'revoke', 'unshare', 'share', 'permission',
                'permissions', 'acl', 'auth', 'oauth', 'token', 'secret', 'password', 'credential', 'credentials', 'key', 'keys', 'logout',
                'send', 'publish', 'forward', 'reply', 'transfer', 'pay', 'payment', 'invite', 'grant'}
DANGER_COMMANDS = {'rm', 'rmdir', 'sudo', 'su', 'chmod', 'chown', 'dd', 'mkfs', 'diskutil', 'kill', 'killall', 'pkill', 'launchctl',
                   'security', 'defaults', 'shutdown', 'reboot', 'csrutil', 'spctl', 'git', 'curl', 'wget', 'ssh', 'scp'}


def _words(name):
    return set(re.findall('[a-z]+', re.sub('([a-z])([A-Z])', r'\1_\2', str(name)).lower()))


def is_dangerous_name(name):
    return bool(_words(name) & DANGER_WORDS)


class RuntimeSession:
    def __init__(self, skill_ids, mcp_ids, allow_commands, workspace, approval_callback, event_callback, inventory=None, extra_tools=None, permission_mode='manual'):
        self.inventory = inventory if inventory is not None else discover()
        self.redactor = Redactor(self.inventory)
        private = self.inventory.get('_private', {})
        self.skills = {key: private.get('skills', {}).get(key) for key in set(skill_ids)}
        self.mcp_ids = set(mcp_ids)
        known = set(private.get('mcp', {})) | {'builtin:workspace'}
        if any(v is None for v in self.skills.values()) or self.mcp_ids - known:
            raise RuntimeError('A selected integration is unavailable. Refresh integrations and update this Bot selection.')
        self.allow_commands = bool(allow_commands)
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.approval_callback = approval_callback
        self.event_callback = event_callback
        self.clients, self.routes, self.catalog = {}, {}, None
        self.closed = False
        self.init_lock = threading.Lock()
        # App-provided tools: {name: (schema, handler(args) -> value, needs_approval)}; needs_approval 'always' asks in every mode.
        self.extras = {t[0]['name']: t for t in (extra_tools or [])}
        # A callable is read on every tool call, so a change in Settings applies mid-reply.
        self.permission_mode = permission_mode if callable(permission_mode) or permission_mode in PERMISSION_MODES else 'manual'
        self.annotations = {}

    def tools(self):
        with self.init_lock:
            if self.closed:
                raise RuntimeError('Runtime session is closed.')
            if self.catalog is not None:
                return copy.deepcopy(self.catalog)
            catalog = []
            if self.skills:
                selected = [{'id': k, 'name': next((s['name'] for s in self.inventory['skills'] if s['id'] == k), k)} for k in sorted(self.skills)]
                catalog += [_schema('zook_read_skill', 'Read selected Skill instructions. Selected Skills: ' + json.dumps(selected, ensure_ascii=False),
                                    {'skill_id': _str('Selected Skill ID')}, ['skill_id']),
                            _schema('zook_read_skill_resource', 'Read a selected Skill reference file relative to its directory.',
                                    {'skill_id': _str('Selected Skill ID'), 'path': _str('Relative resource path')}, ['skill_id', 'path'])]
            catalog += [copy.deepcopy(t[0]) for t in self.extras.values()]
            if 'builtin:workspace' in self.mcp_ids:
                catalog += [_schema('zook_workspace_list', 'List files in the Bot workspace.', {'path': _str('Relative directory, default .')}),
                            _schema('zook_workspace_read', 'Read a UTF-8 file from the Bot workspace.', {'path': _str('Relative file path')}, ['path']),
                            _schema('zook_workspace_write', 'Write a UTF-8 file inside the Bot workspace after user approval.',
                                    {'path': _str('Relative file path'), 'content': _str('Exact file contents')}, ['path', 'content'], False)]
            if self.allow_commands and self.skills:
                catalog.append(_schema('zook_run_skill_helper', 'Run an exact helper script argv from a selected Skill after explicit user approval. No shell expressions.',
                    {'skill_id': _str('Selected Skill ID'), 'argv': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 32},
                     'cwd': _str('Relative Bot workspace directory, default .')}, ['skill_id', 'argv'], False))
            try:
                for ident in sorted(self.mcp_ids - {'builtin:workspace'}):
                    client = ProtocolClient(self.inventory['_private']['mcp'][ident])
                    self.clients[ident] = client
                    for tool in client.tools():
                        original = tool.get('name')
                        if not isinstance(original, str) or not isinstance(tool.get('inputSchema'), dict):
                            raise RuntimeError('MCP returned an invalid tool schema.')
                        prefix = hashlib.sha256(ident.encode()).hexdigest()[:10]
                        suffix = hashlib.sha256(original.encode()).hexdigest()[:8]
                        name = 'zook_' + prefix + '_' + re.sub('[^A-Za-z0-9_]', '_', original)[:36] + '_' + suffix
                        if name in self.routes:
                            raise RuntimeError('MCP returned duplicate tools.')
                        schema = copy.deepcopy(tool)
                        schema['name'] = name
                        schema['description'] = self.redactor.text(tool.get('description', original))[:4000]
                        self.routes[name] = (ident, original)
                        self.annotations[name] = tool.get('annotations') if isinstance(tool.get('annotations'), dict) else {}
                        catalog.append(self.redactor.value(schema, redact_keys=False))
                self.catalog = catalog
                return copy.deepcopy(catalog)
            except Exception as exc:
                self.close()
                raise RuntimeError(self.redactor.text(exc))

    def current_mode(self):
        mode = self.permission_mode() if callable(self.permission_mode) else self.permission_mode
        return mode if mode in PERMISSION_MODES else 'manual'

    def classify(self, name, args):
        """read | internal | external_read | code | external_write | danger"""
        if name in self.routes:
            original = self.routes[name][1]
            if is_dangerous_name(original): return 'danger'
            return 'external_read' if self.annotations.get(name, {}).get('readOnlyHint') is True else 'external_write'
        if name == 'zook_run_skill_helper':
            argv = args.get('argv') or []
            if any(Path(str(a)).name in DANGER_COMMANDS for a in argv) or any(re.search(r'\brm\s+-|sudo\b', str(a)) for a in argv): return 'danger'
            return 'code'
        if name == 'zook_workspace_write': return 'internal'
        if name in self.extras:
            need = self.extras[name][2]
            return 'danger' if need == 'always' else 'internal' if need else 'read'
        return 'read'

    def _path(self, root, relative, write=False):
        if not isinstance(relative, str) or not relative or '\x00' in relative:
            raise RuntimeError('Provide a nonempty relative path.')
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise RuntimeError('Paths must remain inside the selected workspace or Skill directory.')
        root = Path(root).resolve()
        candidate = root / path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise RuntimeError('Symlinks may not escape the selected workspace or Skill directory.')
        # Refuse symlinks entirely for writes: do not follow or overwrite their targets.
        if write:
            current = root
            for part in path.parts:
                current = current / part
                if current.is_symlink():
                    raise RuntimeError('Workspace writes cannot traverse symlinks.')
        return resolved

    def _read(self, path):
        if not path.is_file() or path.stat().st_size > MAX_TEXT:
            raise RuntimeError('File is unavailable or exceeds the 128 KiB read limit.')
        return path.read_text(encoding='utf-8')

    def _event(self, call_id, name, source, status, args, **kwargs):
        event = {'id': call_id, 'name': name, 'source': source, 'status': status, 'arguments': self.redactor.value(args),
                 'label': self.routes[name][1] if name in self.routes else name,
                 'sourceLabel': next((x['name'] for k in ('mcp', 'skills') for x in self.inventory.get(k, []) if x['id'] == source), source)}
        event.update(self.redactor.value(kwargs))
        if self.event_callback:
            self.event_callback(event)

    def call(self, name, args):
        call_id = uuid.uuid4().hex
        source = 'builtin:workspace'
        try:
            if self.closed:
                raise RuntimeError('Runtime session is closed.')
            self.tools()
            # Serialize before approval; callbacks cannot mutate the executed arguments.
            encoded = json.dumps(args, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > MAX_MESSAGE or not isinstance(args, dict):
                raise RuntimeError('Tool arguments must be a bounded JSON object.')
            frozen = json.loads(encoded)
            known = {tool['name']: tool for tool in self.catalog}
            if name not in known:
                raise RuntimeError('Tool is not selected or is unavailable for this Bot.')
            schema = known[name]['inputSchema']
            if name not in self.routes:
                if any(k not in schema['properties'] for k in frozen) or any(k not in frozen for k in schema['required']):
                    raise RuntimeError('Tool arguments do not match the selected tool schema.')
                for key, value in frozen.items():
                    expected = schema['properties'][key]['type']
                    if (expected == 'string' and not isinstance(value, str)) or (expected == 'array' and (not isinstance(value, list) or not all(isinstance(x, str) for x in value))):
                        raise RuntimeError('Tool argument has an invalid type.')
            if name in self.routes:
                source = self.routes[name][0]
            elif name.startswith('zook_read_skill') or name == 'zook_run_skill_helper':
                source = frozen.get('skill_id', '')
                if source not in self.skills:
                    raise RuntimeError('Skill is not selected for this Bot.')
            if name in self.extras:
                source = 'builtin:zook'
            category = self.classify(name, frozen)
            approval = category in ASK_IN_MODE[self.current_mode()]
            self._event(call_id, name, source, 'waiting_approval' if approval else 'running', frozen, category=category,
                        **({'autoApproved': True} if not approval and category != 'read' else {}))
            if approval:
                approved = self.approval_callback and self.approval_callback(call_id, name, copy.deepcopy(frozen), source)
                if not approved or self.closed:
                    self._event(call_id, name, source, 'denied', frozen, error='Tool execution was denied or cancelled.')
                    return dict(_content('Tool execution was denied or cancelled.'), isError=True)
                self._event(call_id, name, source, 'running', frozen)
            if name in self.routes:
                ident, original = self.routes[name]
                result = self.clients[ident].request('tools/call', {'name': original, 'arguments': frozen})
            elif name in self.extras:
                result = _content(self.extras[name][1](copy.deepcopy(frozen)))
            elif name == 'zook_read_skill':
                instructions = self._read(Path(self.skills[source]['path']))
                if source.startswith('skill-shared:') or self.skills[source].get('shared'):  # the shared library's rules travel with its Skills
                    preface = []
                    for rule in self.inventory.get('_private', {}).get('shared_rules', []):
                        try:
                            preface.append('\n\n# Shared policy: ' + Path(rule).name + '\n' + self._read(Path(rule)))
                        except (OSError, RuntimeError):
                            preface.append('\n\nShared policy ' + Path(rule).name + ' unavailable. Verify service authorization before business operations.')
                    instructions += ''.join(preface)
                result = _content(instructions)
            elif name == 'zook_read_skill_resource':
                result = _content(self._read(self._path(self.skills[source]['root'], frozen['path'])))
            elif name == 'zook_workspace_list':
                directory = self._path(self.workspace, frozen.get('path', '.'))
                if not directory.is_dir():
                    raise RuntimeError('Workspace directory is unavailable.')
                items = []
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        if len(items) == 200:
                            break
                        if entry.name == '.grok' or entry.name.startswith('.zook'):
                            continue  # Zook's per-reply CLI scaffolding, not the Bot's files.
                        items.append({'name': entry.name, 'type': 'symlink' if entry.is_symlink() else ('directory' if entry.is_dir(follow_symlinks=False) else 'file')})
                result = _content({'entries': sorted(items, key=lambda x: x['name']), 'limit': 200})
            elif name == 'zook_workspace_read':
                result = _content(self._read(self._path(self.workspace, frozen['path'])))
            elif name == 'zook_workspace_write':
                if len(frozen['content'].encode()) > MAX_TEXT:
                    raise RuntimeError('Workspace write exceeds 128 KiB.')
                path = self._path(self.workspace, frozen['path'], True)
                path.parent.mkdir(parents=True, exist_ok=True)
                # Recheck containment after mkdir; O_NOFOLLOW rejects final symlinks.
                path = self._path(self.workspace, frozen['path'], True)
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    output.write(frozen['content'])
                result = _content({'written': frozen['path'], 'bytes': len(frozen['content'].encode())})
            elif name == 'zook_run_skill_helper':
                result = self._run_helper(source, frozen)
            else:
                raise RuntimeError('Tool is unavailable.')
            if len(json.dumps(result).encode()) > MAX_MESSAGE:
                raise RuntimeError('Tool result exceeds 2 MiB. Ask the tool for fewer results.')
            result = self.redactor.value(result)
            summary = ' '.join(c.get('text', '') for c in result.get('content', []) if isinstance(c, dict) and c.get('type') == 'text')[:1000]
            self._event(call_id, name, source, 'error' if result.get('isError') else 'completed', frozen,
                        resultSummary=summary, **({'error': summary} if result.get('isError') else {}))
            return result
        except Exception as exc:
            error = self.redactor.text(exc)
            self._event(call_id, name, source, 'error', locals().get('frozen', {}), error=error)
            return dict(_content(error), isError=True)

    def _run_helper(self, skill_id, args):
        argv = args['argv']
        if not argv or len(argv) > 32 or sum(len(x) for x in argv) > 16384:
            raise RuntimeError('Provide a helper argv containing 1–32 bounded strings.')
        root = Path(self.skills[skill_id]['root'])
        first = Path(argv[0]).name
        if first in ('python', 'python3', 'node', 'bash', 'sh', 'zsh'):
            if len(argv) < 2 or argv[1].startswith('-'):
                raise RuntimeError('Helpers must name a script file; inline command execution is unavailable.')
            script_index = 1
        else:
            script_index = 0
        script = Path(argv[script_index])
        if script.is_absolute():
            try:
                relative = str(script.relative_to(root))
            except ValueError:
                raise RuntimeError('Helper scripts must belong to the selected Skill.')
        else:
            relative = str(script)
        script = self._path(root, relative)
        if not script.is_file():
            raise RuntimeError('Selected Skill helper script is unavailable.')
        argv = list(argv); argv[script_index] = str(script)
        cwd = self._path(self.workspace, args.get('cwd', '.'))
        process = subprocess.Popen(argv, cwd=str(cwd), env=_environment(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        # Drain continuously into a bounded buffer, kill overflowing/expired helpers.
        chunks, total, overflow = [], [0], threading.Event()
        def drain():
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    return
                total[0] += len(chunk)
                if total[0] > MAX_TEXT:
                    overflow.set(); return
                chunks.append(chunk)
        thread = threading.Thread(target=drain, daemon=True); thread.start()
        deadline = time.monotonic() + TIMEOUT
        try:
            while process.poll() is None:
                if self.closed or overflow.is_set() or time.monotonic() > deadline:
                    raise RuntimeError('Skill helper cancelled, exceeded its output limit, or timed out.')
                time.sleep(.05)
            thread.join(timeout=1)
            if overflow.is_set():
                raise RuntimeError('Skill helper exceeded its output limit.')
            return dict(_content({'exitCode': process.returncode, 'output': b''.join(chunks).decode('utf-8', errors='replace')}),
                        isError=process.returncode != 0)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.wait(timeout=2)
            process.stdout.close()

    def close(self):
        self.closed = True
        for client in list(self.clients.values()):
            client.close()


def test_connection(ident, inventory=None):
    inventory = inventory if inventory is not None else discover()
    if ident == 'builtin:workspace':
        return {'status': 'ready', 'toolCount': 3, 'tools': [{'name': n, 'description': d} for n, d in
                [('zook_workspace_list', 'List Bot workspace files'), ('zook_workspace_read', 'Read Bot workspace files'), ('zook_workspace_write', 'Write approved Bot workspace files')]]}
    redactor, client = Redactor(inventory), None
    try:
        config = inventory.get('_private', {}).get('mcp', {}).get(ident)
        if config is None:
            raise RuntimeError('Integration is unavailable. Refresh integrations and select a configured server.')
        client = ProtocolClient(config)
        tools = client.tools()
        return {'status': 'ready', 'toolCount': len(tools), 'tools': redactor.value([
            {'name': t.get('name', ''), 'description': t.get('description', '')[:1500]} for t in tools])}
    except Exception as exc:
        return {'status': 'error', 'toolCount': 0, 'error': redactor.text(exc)}
    finally:
        if client:
            client.close()
