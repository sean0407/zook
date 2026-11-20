#!/usr/bin/env python3
"""Cursor's preToolUse hook for a Zook reply: allows a built-in tool only inside what the Bot may reach.

Cursor runs this before each of its built-in tools (and before MCP tools) with the tool's name and input on stdin, and does what
the printed answer says. It is set up as fail-closed, so a crash or unreadable answer counts as a refusal. A subagent's tools come
here too (checked on the real CLI).
What the Bot may reach comes from ZOOK_CURSOR_GUARD (JSON, set by Zook for this one reply):
  read / write: folders, or null for anywhere; shell, task: whether commands and subagents may run.
Web search and web fetch never come here; Zook turns those off with Cursor's own switch.
Only tools known to be file tools, or known to touch nothing, are allowed; any other tool is refused.
"""
import json, os, sys

READING = {'read', 'grep', 'glob', 'ls', 'listdir', 'list_dir', 'semanticsearch', 'codebasesearch', 'filesearch', 'readlints'}
WRITING = {'write', 'edit', 'strreplace', 'str_replace', 'multiedit', 'delete', 'editnotebook', 'notebookedit', 'applypatch', 'apply_patch'}
NOTHING = {'todowrite', 'updatetodos', 'createplan', 'askquestion', 'switchmode'}  # keep a list, ask, plan: no files, no commands
SHELL = {'shell', 'bash', 'terminal', 'runterminalcommand', 'run_terminal_cmd'}
TASK = {'task', 'agent', 'subagent'}
PATH_KEYS = ('file_path', 'path', 'target_directory', 'directory', 'target_file', 'notebook_path', 'cwd', 'paths', 'target_directories', 'files')
CURSOR_OWN = os.path.realpath(os.path.expanduser('~/.cursor/projects'))
# Settings Cursor reads when it starts: MCP servers it launches and hooks it runs. A Bot that could write them could run any command
# later, so no Bot may write them, whatever its folder. macOS disks ignore case, so names are compared in lower case.
SETTINGS_DIRS = ('.cursor', '.claude')
SETTINGS_FILES = ('.mcp.json', 'mcp.json', 'hooks.json')


def inside(path, folders):
    real = os.path.realpath(path).lower()
    return any(real == f.lower() or real.startswith(f.lower().rstrip('/') + '/') for f in folders)


def settings_file(path):
    parts = os.path.realpath(path).lower().split(os.sep)
    return any(p in SETTINGS_DIRS for p in parts) or parts[-1] in SETTINGS_FILES


def own_results(path, home):
    """Cursor keeps a reply's long tool results in ~/.cursor/projects/<this workspace>/agent-tools; only this Bot's folder there."""
    if not inside(path, [CURSOR_OWN]): return False
    rest = os.path.realpath(path)[len(CURSOR_OWN) + 1:].split(os.sep)
    name = os.path.basename(os.path.realpath(home).rstrip('/'))
    return len(rest) >= 3 and rest[1] == 'agent-tools' and bool(name) and rest[0].lower().endswith(name.lower())


def paths_in(data):
    for key in PATH_KEYS:
        value = data.get(key)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and item: yield item


def decide(rule, tool, data, home):
    name = str(tool or '')
    if name.startswith('MCP:'):
        return name.startswith('MCP:zook_') or name.startswith('MCP:zook-'), 'Zook 只開放 zook 工具。'
    low = name.lower()
    if low in SHELL or 'command' in data:
        return bool(rule.get('shell')), '這個 Bot 目前不能執行指令。'
    if low in TASK:
        return bool(rule.get('task')), '這個 Bot 目前不能派出子代理。'
    if low in NOTHING: return True, ''
    if low not in READING and low not in WRITING:
        return False, 'Zook 還沒有開放 Cursor 的這個工具（%s）。' % name[:60]
    writing = low in WRITING
    folders = rule.get('write') if writing else rule.get('read')
    given = [os.path.expanduser(v) if v.startswith('~') else v if os.path.isabs(v) else os.path.join(home, v) for v in paths_in(data)]
    if not given:
        if writing: return False, '這個 Bot 目前不能修改這個檔案。'
        given = [home]  # a search with no folder given searches the workspace
    for path in given:
        if own_results(path, home): continue
        if writing and settings_file(path): return False, '不能修改 Cursor 或 Claude 的設定檔。'
        if folders is None: continue
        if not inside(path, [os.path.realpath(f) for f in folders]):
            return False, ('這個 Bot 目前不能修改這個位置的檔案：%s' if writing else '這個 Bot 目前讀不到這個位置的檔案：%s') % path
        if writing and low == 'delete' and any(os.path.realpath(path).lower() == os.path.realpath(f).lower() for f in folders):
            return False, '不能刪除整個資料夾。'
    return True, ''


def main():
    try: rule = json.loads(os.environ.get('ZOOK_CURSOR_GUARD') or '')
    except ValueError: rule = None
    try: event = json.load(sys.stdin)
    except ValueError: event = {}
    if not isinstance(rule, dict) or not isinstance(event, dict):
        print(json.dumps({'permission': 'deny', 'agent_message': 'Zook 沒有設定這次可用的範圍，所以擋下了。'})); return
    data = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
    roots = event.get('workspace_roots') if isinstance(event.get('workspace_roots'), list) else []
    home = str(roots[0]) if roots and isinstance(roots[0], str) else os.getcwd()
    allowed, why = decide(rule, event.get('tool_name'), data, home)
    print(json.dumps({'permission': 'allow'} if allowed else {'permission': 'deny', 'user_message': why, 'agent_message': why + ' 請不要改用其他方法繞過，直接告訴使用者。'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
