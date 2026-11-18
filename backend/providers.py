"""Model providers Zook can drive through their official CLIs.

Built-in entries come from each vendor's own install script and CLI help:
- Claude Code: https://claude.ai/install.sh, `claude update`
- Codex:       https://chatgpt.com/codex/install.sh, `codex update`
- Grok Build:  https://x.ai/cli/install.sh, `grok update`, `grok login`, `grok models`
- Gemini CLI:  npm package @google/gemini-cli (Zook installs its own Node.js for it; see cli_installer.py)

Custom providers are any other CLI the user configures: a command, its arguments with
{prompt}/{prompt_file}/{model} placeholders, and optional install/login/status commands.
"""
import glob
import os
import re
import shlex
import shutil
from pathlib import Path

CATALOG = {
    'codex': dict(name='Codex（ChatGPT / OpenAI）', vendor='OpenAI', binary='codex', kind='codex', tools=True,
                  install='curl -fsSL https://chatgpt.com/codex/install.sh | sh', update=['update'],
                  latest_url='https://api.github.com/repos/openai/codex/releases/latest',
                  docs='https://developers.openai.com/codex/cli'),
    'claude': dict(name='Claude（Anthropic）', vendor='Anthropic', binary='claude', kind='claude', tools=True,
                   install='curl -fsSL https://claude.ai/install.sh | bash', update=['update'],
                   latest_url='https://downloads.claude.ai/claude-code-releases/latest',
                   docs='https://code.claude.com/docs'),
    'grok': dict(name='Grok（xAI）', vendor='xAI', binary='grok', kind='grok', tools=True,
                 extra_paths=['~/.grok/bin/grok'], install='curl -fsSL https://x.ai/cli/install.sh | bash', update=['update'],
                 login=[('browser', '用 Grok 帳號登入', ['login', '--oauth']), ('device', '裝置碼登入', ['login', '--device-auth'])],
                 logout=['logout'], docs='https://docs.x.ai', version_check=['update', '--check', '--json']),
    'gemini': dict(name='Gemini（Google）', vendor='Google', binary='gemini', kind='generic', tools=False,
                   install='Zook 會從 https://nodejs.org 下載 Node.js，再安裝 @google/gemini-cli', npm_package='@google/gemini-cli', terminal_login=True,
                   signed_in_file='~/.gemini/oauth_creds.json', args='-p {prompt}', model_args='-m {model}', full_args='--yolo',
                   latest_url='https://registry.npmjs.org/@google/gemini-cli/latest',
                   docs='https://github.com/google-gemini/gemini-cli'),
}
DEFAULT_ADDED = ('codex', 'claude')
CUSTOM_PREFIX = 'custom-'
# An app opened from Finder does not get the shell's PATH, so the usual install folders are searched too.
# ZOOK_CLI_DIRS (colon-separated) replaces the list.
SEARCH_DIRS = tuple(filter(None, os.environ['ZOOK_CLI_DIRS'].split(':'))) if 'ZOOK_CLI_DIRS' in os.environ else ('~/.local/bin', '/opt/homebrew/bin', '/usr/local/bin', '~/.npm-global/bin', '~/.bun/bin', '~/.volta/bin', '~/.nvm/versions/node/*/bin')


def _expand(path):
    return str(Path(os.path.expanduser(path)))


def find_binary(command, extra=()):
    """Resolve a CLI by name or path; also looks in the usual per-user install folders."""
    if not command: return None
    if '/' in command:
        path = _expand(command)
        return path if os.path.isfile(path) and os.access(path, os.X_OK) else None
    found = shutil.which(command)
    if found: return found
    for candidate in [*extra, *(d + '/' + command for d in SEARCH_DIRS)]:
        for path in sorted(glob.glob(_expand(candidate)), reverse=True):
            if os.path.isfile(path) and os.access(path, os.X_OK): return path
    return None


def custom_list(data):
    items = data.get('customProviders')
    return items if isinstance(items, list) else []


def spec(data, provider_id):
    """Full description of a provider (built-in or custom), or None."""
    if provider_id in CATALOG:
        return dict(CATALOG[provider_id], id=provider_id, custom=False)
    for item in custom_list(data):
        if item.get('id') == provider_id:
            return dict(item, kind='generic', tools=False, custom=True)
    return None


def binary_for(data, provider_id):
    s = spec(data, provider_id)
    if not s: return None
    return find_binary(s.get('command') or s.get('binary'), s.get('extra_paths', ()))


def active_ids(data):
    """Providers shown in Zook: added or auto-detected built-ins (unless removed) plus custom ones."""
    settings = data.get('settings', {})
    added = set(settings.get('addedProviders') or DEFAULT_ADDED)
    hidden = set(settings.get('hiddenProviders') or [])
    ids = [pid for pid in CATALOG if pid not in hidden and (pid in added or binary_for(data, pid))]
    return ids + [item['id'] for item in custom_list(data) if isinstance(item.get('id'), str)]


def catalog_view(data):
    """Built-ins that can still be added, for the 新增 dialog."""
    active = set(active_ids(data))
    out = []
    for pid, s in CATALOG.items():
        if pid in active: continue
        req = s.get('requires')
        out.append(dict(id=pid, name=s['name'], vendor=s['vendor'], installed=bool(binary_for(data, pid)), install=s['install'],
                        requires=req or '', requirementMet=not req or bool(find_binary(req)), docs=s.get('docs', '')))
    return out


SLUG = re.compile(r'[^a-z0-9]+')


def validate_custom(body, existing_ids):
    """Clean user input for a custom provider. Raises ValueError with a readable message."""
    def text(key, limit, required=False):
        value = body.get(key, '')
        if not isinstance(value, str) or len(value) > limit: raise ValueError('欄位 %s 無效。' % key)
        value = value.strip()
        if required and not value: raise ValueError('請填寫 %s。' % {'name': '名稱', 'command': 'CLI 指令'}.get(key, key))
        return value
    name, command = text('name', 80, True), text('command', 500, True)
    args, model_args = text('args', 1000), text('model_args', 300)
    for label, value in (('args', args), ('model_args', model_args), ('command', command)):
        try: shlex.split(value)
        except ValueError: raise ValueError('「%s」的引號沒有成對。' % label)
    if len(shlex.split(command)) != 1: raise ValueError('CLI 指令只填執行檔名稱或路徑，參數請放在「參數」。')
    models = body.get('models', [])
    if isinstance(models, str): models = [m.strip() for m in models.split(',')]
    if not isinstance(models, list) or len(models) > 50 or any(not isinstance(m, str) or len(m) > 100 for m in models): raise ValueError('模型清單無效。')
    slug = SLUG.sub('-', name.lower()).strip('-') or 'cli'
    pid = body.get('id') if isinstance(body.get('id'), str) and body.get('id', '').startswith(CUSTOM_PREFIX) else CUSTOM_PREFIX + slug[:40]
    base, n = pid, 2
    while pid in existing_ids and pid != body.get('id'):
        pid = '%s-%d' % (base, n); n += 1
    return dict(id=pid, name=name, command=command, args=args, model_args=model_args, models=[m for m in dict.fromkeys(models) if m],
                install=text('install', 1000), login=text('login', 500), status=text('status', 500))


def command_args(s, prompt_file, prompt, model, full=False, binary=None):
    """argv for a generic/custom provider. Returns (argv, use_stdin).
    `full` adds the CLI's own switch for running every tool without asking, when the Bot may use the whole Mac."""
    binary = binary or find_binary(s.get('command') or s.get('binary'), s.get('extra_paths', ()))
    if not binary: raise RuntimeError('找不到這個 CLI，請先安裝。')
    template = s.get('args') or ''
    use_stdin = '{prompt}' not in template and '{prompt_file}' not in template
    argv = [binary] + [a.replace('{prompt_file}', prompt_file).replace('{prompt}', prompt) for a in shlex.split(template)]
    if model and s.get('model_args'):
        argv += [a.replace('{model}', model) for a in shlex.split(s['model_args'])]
    if full and s.get('full_args'): argv += shlex.split(s['full_args'])
    return argv, use_stdin


def parse_grok_models(text):
    models = []
    for line in text.splitlines():
        m = re.match(r'\s*[*-]\s+([A-Za-z0-9._:/-]+)', line)
        if m: models.append(m.group(1))
    return list(dict.fromkeys(models))


VERSION_RE = re.compile(r'(\d+\.\d+\.\d+(?:[-.][0-9A-Za-z]+)*)')


def parse_version(text):
    m = VERSION_RE.search(text or '')
    return m.group(1) if m else ''


def version_key(v):
    return tuple(int(x) for x in re.findall(r'\d+', v.split('-')[0])[:4]) if v else ()


def latest_from_response(url, body):
    """Latest version from a vendor's release endpoint (GitHub release JSON, npm JSON, or plain text)."""
    body = (body or '').strip()
    if body.startswith('{'):
        import json
        try: data = json.loads(body)
        except ValueError: return ''
        return parse_version(str(data.get('tag_name') or data.get('version') or ''))
    return parse_version(body.splitlines()[0] if body else '')
