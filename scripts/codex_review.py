#!/usr/bin/env python3
"""Run a read-only Codex review, taking turns between this Mac's Codex accounts.

    python3 scripts/codex_review.py --family sol --brief <審查說明.md> --out <結果.md>
    python3 scripts/codex_review.py --family astra --brief <審查說明.md> --out <結果.md>

- Accounts: Codex's own sign-in (~/.codex) and every Codex sign-in added in Zook (its accounts folder). Reviews take turns; the
  turn is kept in ~/.config/zook-dev/codex-review.json. When one account is out of quota, the same review runs on the next one.
  When all are out, it stops and says so (exit code 3); it never switches to paid credits.
- An account with under 20% left in any window on Zook's usage page is skipped, so reviews never use up the last of it.
- Model: the newest of the family listed by Codex (gpt-*-sol or gpt-*-astra). sol runs at medium reasoning, astra at high,
  unless --effort says otherwise.
- Always read-only, not saved, and without the user's own Codex settings (connectors, instructions). Nothing from the sign-in
  files is read or printed; Codex is only pointed at the folder.
- Run it from the repository root. Prints which account and model were used, for the progress notes.
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, time

HOME = pathlib.Path.home()
ZOOK = HOME / 'Library/Application Support/swarmr'
STATE = HOME / '.config/zook-dev/codex-review.json'
OUT_OF_QUOTA = re.compile(r"usage limit|rate limit|quota|too many requests|\b429\b|purchase more credits|limit reached", re.I)


def accounts():
    """[(name, CODEX_HOME or None)]: Codex's own sign-in first, then Zook's Codex sign-ins, by id."""
    found = [('Codex 預設帳號', None)] if (HOME / '.codex/auth.json').exists() else []
    try: data = json.loads((ZOOK / 'swarmr.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): data = {}
    for a in data.get('accounts') or []:
        folder = ZOOK / 'accounts' / str(a.get('id') or '')
        if a.get('provider') == 'codex' and a.get('type') == 'login' and re.fullmatch(r'[0-9a-f]{32}', str(a.get('id') or '')) and (folder / 'auth.json').exists():
            found.append(('Zook 帳號「%s」' % (a.get('name') or a['id'][:6]), str(folder)))
    return found


def low_quota(home):
    """The reason to leave this account alone, when Zook's usage page shows under 20% left in any of its windows; '' otherwise."""
    try: quota = json.loads((ZOOK / 'swarmr.json').read_text(encoding='utf-8')).get('quota') or {}
    except (OSError, ValueError): return ''
    entry = quota.get('codex' if not home else 'codex@' + pathlib.Path(home).name) or {}
    now = time.time()
    for w in entry.get('windows') or []:
        try: used = float(w.get('usedPercent') or 0)
        except (TypeError, ValueError): continue
        if used > 80 and window_open(w, entry, now): return '%s只剩 %d%%' % (w.get('label') or '', round(100 - used))
    return ''


def window_open(window, snap, now):
    """Read like Zook's usage page (routing.py _window_open): seconds, milliseconds or a date; no date means five hours from the snapshot."""
    import datetime
    reset = window.get('resetsAt')
    try:
        if isinstance(reset, (int, float)): at = reset / 1000 if reset > 1e12 else reset
        else: at = datetime.datetime.fromisoformat(str(reset).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        try: at = datetime.datetime.fromisoformat(snap['updatedAt']).timestamp() + 5 * 3600
        except (KeyError, ValueError, TypeError): return False
    return at > now


def newest(family, home):
    cache = pathlib.Path(home or HOME / '.codex') / 'models_cache.json'
    try: models = [m.get('slug') for m in json.loads(cache.read_text(encoding='utf-8')).get('models') or []]
    except (OSError, ValueError, AttributeError): models = []
    named = [m for m in models if re.fullmatch(r'gpt-[0-9]+(\.[0-9]+)*-' + family, m or '')]
    if not named: return 'gpt-6.2-' + family  # newest known on 2026-11-20
    return max(named, key=lambda m: tuple(int(x) for x in m.split('-')[1].split('.')))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--family', choices=('sol', 'astra'), required=True)
    ap.add_argument('--brief', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--effort', choices=('low', 'medium', 'high'))
    args = ap.parse_args()
    effort = args.effort or ('high' if args.family == 'astra' else 'medium')
    brief = pathlib.Path(args.brief).read_bytes()
    found = accounts()
    if not found: print('找不到已登入的 Codex 帳號。', file=sys.stderr); return 2
    try: state = json.loads(STATE.read_text())
    except (OSError, ValueError): state = {}
    start = int(state.get('next', 0)) % len(found)
    order = found[start:] + found[:start]
    env_path = os.environ.get('PATH', '') if shutil.which('codex') else os.pathsep.join([str(HOME / '.local/bin'), '/opt/homebrew/bin', '/usr/local/bin', os.environ.get('PATH', '')])
    for i, (name, home) in enumerate(order):
        low = low_quota(home)
        if low:  # under 20% left: keep it for the user's own work
            print('%s 的額度%s，不用它審查。' % (name, low), flush=True)
            continue
        model = newest(args.family, home)
        env = dict(os.environ, PATH=env_path)
        env.pop('CODEX_HOME', None)
        if home: env['CODEX_HOME'] = home
        print('審查：%s，模型 %s，思考強度 %s' % (name, model, effort), flush=True)
        began = time.time()
        done = subprocess.run(['codex', 'exec', '--ignore-user-config', '--ephemeral', '-s', 'read-only', '-m', model,
                               '-c', 'model_reasoning_effort="%s"' % effort, '-o', args.out, '-'],
                              input=brief, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        log = done.stdout.decode('utf-8', 'replace')
        tokens = re.search(r'tokens used\s*\n\s*([\d,]+)', log)
        ok = done.returncode == 0 and pathlib.Path(args.out).exists() and pathlib.Path(args.out).stat().st_mtime >= began
        if ok:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({'next': (found.index((name, home)) + 1) % len(found)}))  # the next review starts on the other account
            print('完成：%s，模型 %s，用了約 %s token。結果：%s' % (name, model, tokens.group(1) if tokens else '?', args.out))
            return 0
        if OUT_OF_QUOTA.search(log[-4000:]):
            print('%s 的額度用完了，改用下一個帳號。' % name, flush=True)
            continue
        print('審查失敗（不是額度問題），沒有換帳號重跑。最後的輸出：\n' + log[-1500:], file=sys.stderr)
        return 1
    print('所有 Codex 帳號的額度都用完或剩不到 20%，這次審查沒有執行。等額度恢復再跑。', file=sys.stderr)
    return 3


if __name__ == '__main__':
    sys.exit(main())
