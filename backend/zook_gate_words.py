# -*- coding: utf-8 -*-
"""The words zook_gate.py reads a command by: which programs, options and paths are at a safety boundary. Plain data, loaded by
zook_gate.py from the file next to it (so the gate itself stays readable); kept apart only for size."""
import os, re

HOME = os.path.expanduser('~')
# ---- what counts as a boundary
DELETE_COMMANDS = {'rm', 'rmdir', 'unlink', 'trash', 'srm', 'shred'}
MAIL_COMMANDS = {'mail', 'mailx', 'sendmail', 'msmtp', 'mutt'}
COPY_OUT = {'scp', 'sftp', 'rsync', 'ftp'}
CONNECT = {'ssh', 'nc', 'ncat', 'netcat', 'socat', 'telnet'}
SYSTEM_COMMANDS = {'sudo', 'su', 'doas', 'launchctl', 'systemsetup', 'networksetup', 'pmset', 'nvram', 'csrutil', 'spctl', 'softwareupdate',
                   'installer', 'kextload', 'kextunload', 'scutil', 'dscl', 'chsh', 'crontab', 'diskutil', 'tmutil', 'fdesetup', 'profiles'}
INSTALLERS = {'brew': {'install', 'uninstall', 'remove', 'rm', 'reinstall', 'upgrade', 'tap', 'untap', 'link', 'unlink', 'services', 'autoremove', 'cleanup', 'update', 'pin', 'unpin'},
              'port': {'install', 'uninstall', 'upgrade', 'selfupdate'}, 'mas': {'install', 'uninstall', 'upgrade'},
              'gem': {'install', 'uninstall', 'update'}, 'cargo': {'install', 'uninstall'}, 'pipx': {'install', 'uninstall', 'upgrade', 'reinstall', 'inject'},
              'pip': {'install', 'uninstall', 'download'}, 'pip3': {'install', 'uninstall', 'download'}, 'conda': {'install', 'remove', 'update', 'create'},
              'go': {'install'}}
NODE_INSTALLERS = {'npm', 'pnpm', 'yarn', 'bun'}
SECRET_DIRS = [os.path.join(HOME, p) for p in ('.ssh', '.aws', '.config/gh', '.gnupg', 'Library/Keychains', '.docker', '.kube', '.netrc', '.config/gcloud', '.git-credentials', '.npmrc', '.pypirc')] + ['/Library/Keychains']
# The sign-ins of the CLIs Zook runs (providers.py) and Zook's own extra accounts: reading them is reading a password.
CREDENTIALS = [os.path.join(HOME, p) for p in ('.codex/auth.json', '.gemini/oauth_creds.json', '.gemini/google_accounts.json', '.claude/.credentials.json',
                                               '.grok', '.config/cursor', '.cursor/cli-config.json', '.cursor/auth.json', '.config/anthropic', '.antigravity/auth')]
CREDENTIAL_NAMES = re.compile(r'(?i)^(?:\.env(?:\..*)?|\.netrc|\.npmrc|\.pypirc|\.git-credentials|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|.*\.(?:pem|p12|pfx|key|keychain|keychain-db)|'
                              r'credentials(?:\.json)?|\.credentials\.json|oauth_creds\.json|auth\.json|client_secret.*\.json|service[-_]account.*\.json)$')
SYSTEM_DIRS = ('/System', '/Library', '/usr', '/bin', '/sbin', '/etc', '/private', '/Applications', '/opt', '/var', os.path.join(HOME, 'Library/LaunchAgents'))
TEMP_DIRS = ['/tmp', '/private/tmp', '/var/folders', '/private/var/folders']
# The folders a CLI loads hooks, settings, Skills and plugins from, wherever they are (the home folder or a Bot's workspace).
CLI_FOLDERS = {'.claude', '.cursor', '.codex', '.grok', '.gemini', '.antigravity', 'cursor-config'}
WRAPPERS = {'env', 'nohup', 'time', 'command', 'builtin', 'exec', 'nice', 'caffeinate', 'timeout', 'xargs', 'stdbuf', 'arch', 'noglob', 'nocorrect', 'busybox', 'parallel'}
WRAPPER_VALUED = {'env': {'-u', '-P', '-C'}, 'nice': {'-n'}, 'timeout': {'-s', '-k', '--signal', '--kill-after'}, 'caffeinate': {'-t', '-w'},
                  'xargs': {'-I', '-J', '-L', '-n', '-P', '-R', '-S', '-s', '-E', '-d', '-a'}, 'stdbuf': {'-i', '-o', '-e'}, 'time': {'-o', '-f'}, 'exec': {'-a'},
                  'parallel': {'-j', '--jobs', '-S', '--sshlogin', '-a', '--arg-file', '--colsep', '-d', '--delimiter', '-n', '-N', '--timeout'}}
SHELL_WORDS = {'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until', '!', '{', '}', 'coproc'}  # what runs after them is a command too
SHELLS = {'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish'}
INTERPRETERS = {'python', 'python3', 'python2', 'node', 'nodejs', 'perl', 'ruby', 'php', 'deno', 'bun', 'osascript', 'lua', 'Rscript', 'swift'}
INLINE_FLAGS = {'-c', '-e', '-E', '--eval', '-p', '--print', '-r'}
CURL_SEND = {'-d', '--data', '--data-raw', '--data-binary', '--data-urlencode', '--data-ascii', '-F', '--form', '--form-string', '-T', '--upload-file', '--json',
             '-K', '--config', '--mail-rcpt', '--mail-from'}
WGET_SEND = ('--post-data', '--post-file', '--method', '--body-data', '--body-file')
GH_ACTIONS = {'create', 'merge', 'comment', 'review', 'close', 'reopen', 'delete', 'edit', 'upload', 'publish', 'fork', 'transfer', 'archive', 'lock', 'ready', 'set', 'sync', 'deploy', 'run', 'cancel', 'rerun'}
GH_VALUED = {'-R', '--repo', '--hostname', '-b', '--body', '-t', '--title', '-F', '--body-file', '-B', '--base', '-H', '--head', '-a', '--assignee', '-l', '--label',
             '-m', '--milestone', '-p', '--project', '-r', '--reviewer', '-X', '--method', '-f', '--raw-field', '--field', '--input', '-q', '--jq', '--template',
             '--json', '-L', '--limit', '-s', '--state', '-A', '--author', '-S', '--search', '-o', '--output', '-e', '--env', '-n', '--notes', '-c'}
GIT_VALUED = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env', '--exec-path', '--list-cmds', '--attr-source'}
GIT_FLAGS = {'-p', '--paginate', '-P', '--no-pager', '--bare', '--no-replace-objects', '--literal-pathspecs', '--glob-pathspecs', '--noglob-pathspecs',
             '--icase-pathspecs', '--no-optional-locks', '--html-path', '--man-path', '--info-path', '--version', '--help', '-v', '-h', '--no-lazy-fetch', '--no-advice'}
GREP_VALUED = {'-e', '-f', '-m', '-A', '-B', '-C', '--regexp', '--file', '--max-count', '--include', '--exclude', '--exclude-dir', '--context', '--after-context',
               '--before-context', '--label', '-g', '--glob', '-t', '--type', '-T', '--type-not', '-M', '--max-columns', '--max-depth', '-j', '--threads', '--iglob'}
# grep's own options that take a value (-d recurse searches the folder below): only for grep, where tree -d or tar -d mean something else.
GREP_ONLY_VALUED = GREP_VALUED | {'-d', '--directories', '-D', '--devices', '--exclude-from', '--binary-files'}
UGREP_VALUED = GREP_ONLY_VALUED | {'--include-from'}  # ugrep takes grep's options, and a file of globs to include
# ripgrep's own options that take a value: without them its value (rg --pre /bin/cat -e KEY) was read as the folder searched,
# so the current folder went unchecked. Not for grep, where -E, -r and -d mean something else.
RG_VALUED = GREP_VALUED | {'--pre', '--pre-glob', '--sort', '--sortr', '-d', '-E', '--encoding', '--ignore-file', '--type-add', '--type-clear',
                           '--path-separator', '-r', '--replace', '--max-filesize', '--dfa-size-limit', '--regex-size-limit', '--colors', '--color',
                           '--context-separator', '--field-context-separator', '--field-match-separator', '--engine', '--hostname-bin',
                           '--hyperlink-format', '--generate', '--maxdepth', '--max-depth', '-G', '--glob-not', '--max-bytes', '--in', '--in0'}
# Inline code (python -c, node -e, a here-document) that may delete, send, run commands or touch keys: it cannot be read reliably.
CODE_HINTS = re.compile(r'\b(?:os\.(?:remove|unlink|rmdir|removedirs|system|popen|exec\w*|spawn\w*|rename|replace)|shutil\.(?:rmtree|move)|subprocess|send2trash|'
                        r'unlink(?:Sync)?|rmSync|rename\w*\s*\(|File::Copy|fs\.promises|renameSync|moveItem|removeItem|File\.rename|FileUtils|rmdirSync|rm_rf|child_process|execSync|spawnSync|requests\.|httpx|urlopen|urllib|http\.client|smtplib|ftplib|'
                        r'paramiko|socket|fetch\s*\(|XMLHttpRequest|keyring|Keychain|system\s*\(|exec\s*\(|eval\s*\(|IO\.popen|File\.delete|Net::|LWP|'
                        r'do shell script|delete\b|trash\b)|\.ssh\b|\.aws\b|\.env\b|id_rsa|id_ed25519|password|passwd|`', re.I)
CURL_VALUED = CURL_SEND | {'-H', '--header', '-o', '--output', '-u', '--user', '-A', '--user-agent', '-e', '--referer', '-X', '--request', '-b', '--cookie',
                           '-c', '--cookie-jar', '-w', '--write-out', '-x', '--proxy', '-m', '--max-time', '--connect-timeout', '-r', '--range', '-E', '--cert',
                           '--key', '--cacert', '-U', '--proxy-user', '--retry', '--limit-rate', '-z', '--time-cond', '--resolve', '--connect-to', '-D',
                           '--dump-header', '-C', '--continue-at', '-Y', '-y', '--speed-limit', '--speed-time', '--max-redirs', '--interface', '--oauth2-bearer'}
