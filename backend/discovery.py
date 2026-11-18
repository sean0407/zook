"""What is set up on this Mac: Skills, connectors and plugins from Codex, Claude and the shared library. Read-only; nothing here is executed.

The private part of what it returns holds credentials and must never reach the UI."""
import copy
import glob
import hashlib
import json
import os
from pathlib import Path
import re

MAX_MESSAGE = 2 * 1024 * 1024
MAX_TEXT = 128 * 1024


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
