#!/usr/bin/env python3
"""zook-cli: give a Zook Bot a task from a terminal or a script on this Mac.

    zook_cli.py list                               Bots that have 允許本機腳本 switched on
    zook_cli.py run "Bot 名稱" "要做的事" --wait     send it and print the answer
    zook_cli.py run "Bot 名稱" - --wait < task.md    the task from standard input
    zook_cli.py status "Bot 名稱" <id>              how an earlier message is doing

Options for run: --wait, --timeout 90s|5m|1h (default 5m, only how long this command waits), --id KEY (sending again with
the same key does not start a second reply), --json.
Exit codes: 0 done, 1 the reply failed, 2 could not reach Zook or bad arguments, 3 waiting for your approval in Zook,
4 still running when the wait ended.

Zook must be open. It cannot approve actions or change settings; that stays in the Zook window."""
import json, os, sys, urllib.error, urllib.parse, urllib.request

FOLDER = os.environ.get('ZOOK_AUTOMATION') or os.path.expanduser('~/Library/Application Support/swarmr/automation')


def call(method, path, body=None, timeout=30):
    try:
        base = open(os.path.join(FOLDER, 'url'), encoding='utf-8').read().strip()
        header = open(os.path.join(FOLDER, 'headers'), encoding='utf-8').read().strip().split(': ', 1)
    except OSError: sys.exit(fail('找不到 Zook。請先開啟 Zook。', 2))
    request = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={header[0]: header[1], 'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # this Mac only: never through a proxy
    try:
        with opener.open(request, timeout=timeout) as response: return json.load(response)
    except urllib.error.HTTPError as exc:
        try: message = json.load(exc).get('error') or str(exc)
        except ValueError: message = str(exc)
        sys.exit(fail(message, 2))
    except OSError: sys.exit(fail('連不上 Zook。請確認 Zook 開著。', 2))


def fail(message, code):
    sys.stderr.write(message + '\n'); return code


def seconds(text):
    try: return int(float(text[:-1]) * {'s': 1, 'm': 60, 'h': 3600}[text[-1]]) if text[-1:] in 'smh' else int(text)
    except (ValueError, KeyError): sys.exit(fail('--timeout 要像 90s、5m 或 1h。', 2))


def show(result, as_json):
    if as_json: print(json.dumps(result, ensure_ascii=False))
    elif result.get('status') == 'completed': print(result.get('answer') or '')
    elif result.get('status') == 'needs_approval': sys.stderr.write('等你在 Zook 核准：%s\n' % (result.get('waitingFor') or ''))
    elif result.get('status') in ('running', 'queued'): sys.stderr.write('還在進行中（%s）。之後查詢：status <Bot> %s\n' % (result['status'], result.get('id')))
    else: sys.stderr.write((result.get('error') or '回覆沒有完成。') + '\n')
    return {'completed': 0, 'needs_approval': 3, 'running': 4, 'queued': 4}.get(result.get('status'), 1)


def main(argv):
    if len(argv) < 1 or argv[0] in ('-h', '--help'): print(__doc__); return 0
    if argv[0] == 'list':
        for agent in call('GET', '/v1/agents')['agents']: print('%s\t%s' % (agent['id'], agent['name']))
        return 0
    if argv[0] == 'status' and len(argv) == 3:
        return show(call('GET', '/v1/agents/%s/deliveries/%s' % (urllib.parse.quote(argv[1], safe=''), urllib.parse.quote(argv[2], safe=''))), '--json' in argv)
    if argv[0] == 'run' and len(argv) >= 3:
        options, wait, key, i = argv[3:], 0, None, 0
        timeout = 300
        while i < len(options):
            if options[i] == '--wait': wait = 1
            elif options[i] == '--json': pass
            elif options[i] == '--timeout' and i + 1 < len(options): timeout = seconds(options[i + 1]); i += 1
            elif options[i] == '--id' and i + 1 < len(options): key = options[i + 1]; i += 1
            else: return fail('不認得的選項：' + options[i], 2)
            i += 1
        text = sys.stdin.read() if argv[2] == '-' else argv[2]
        body = dict(content=text, wait=min(timeout, 3600) if wait else 0)
        if key: body['id'] = key
        return show(call('POST', '/v1/agents/%s/messages' % urllib.parse.quote(argv[1], safe=''), body, timeout=body['wait'] + 30), '--json' in options)
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
