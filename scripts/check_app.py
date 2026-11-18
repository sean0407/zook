#!/usr/bin/python3
"""Check a built Zook.app: signature, version, and the backend bundled inside it.

    python3 scripts/check_app.py [path/to/Zook.app] [--live] [--providers codex,claude]

Runs the app's own backend with a throwaway data folder, so it never touches the
user's Zook data or Keychain. --live also sends one short message through each
installed CLI (uses a little of the provider's quota).
"""
import argparse
import http.client
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_PROMPT = '只回覆 ZOOK-OK 這幾個字，不要做其他事。'
results = []


def record(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('通過  ' if ok else '失敗  ') + name + (('：' + detail) if detail else ''), flush=True)


class Backend:
    def __init__(self, app, folder):
        resources = app / 'Contents/Resources'
        env = dict(os.environ, ZOOK_SKIP_UPDATE_CHECK='1', ZOOK_SECRETS_DIR=str(folder), ZOOK_SCHEDULE_TICK='3600')
        self.proc = subprocess.Popen(['/usr/bin/python3', str(resources / 'backend/server.py'), '--port', '0',
                                      '--data-dir', str(folder / 'data'), '--assets', str(resources / 'frontend')],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError('後端沒有啟動：' + self.proc.stderr.read()[-500:])
        ready = json.loads(line)
        self.port, self.token = ready['port'], ready['token']

    def req(self, method, path, body=None, cookie=False, timeout=30):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        headers = {'Cookie': 'swarmr_session=' + self.token} if cookie else {'Authorization': 'Bearer ' + self.token}
        if body is not None: headers['Content-Type'] = 'application/json'
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
        resp = conn.getresponse(); raw = resp.read(); conn.close()
        try: data = json.loads(raw)
        except ValueError: data = raw
        return resp.status, data

    def close(self):
        self.proc.terminate()
        try: self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired: self.proc.kill()
        self.proc.stdout.close(); self.proc.stderr.close()


def check_bundle(app):
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    app_version = info.get('CFBundleShortVersionString', '')
    swift = (ROOT / 'native/Zook.swift').read_text(encoding='utf-8')
    record('版本號 ' + app_version, bool(app_version) and app_version in swift, '' if app_version in swift else 'native/Zook.swift 的版本號不同')
    sign = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], capture_output=True, text=True)
    record('簽章', sign.returncode == 0, sign.stderr.strip()[:200])
    for name in ('Zook', 'zook-remote', 'zook-icon'):
        record('執行檔 ' + name, os.access(app / 'Contents/MacOS' / name, os.X_OK))
    # The app holds exactly the source files: nothing missing, and nothing left over from an earlier build.
    for folder, pattern in (('backend', '*.py'), ('backend/zook', '*.py'), ('frontend', '*.*'), ('frontend/js', '*.js')):
        mine = sorted(p.name for p in (ROOT / folder).glob(pattern) if p.is_file()); built = sorted(p.name for p in (app / 'Contents/Resources' / folder).glob(pattern) if p.is_file())
        extra, missing = sorted(set(built) - set(mine)), sorted(set(mine) - set(built))
        record('檔案一致 ' + folder, not extra and not missing, ('多出 ' + '、'.join(extra) if extra else '') + (' 缺少 ' + '、'.join(missing) if missing else ''))


def check_backend(b):
    for path in ('/', '/app.js', '/style.css'):
        status, _ = b.req('GET', path, cookie=True)
        record('介面檔案 ' + path, status == 200, 'HTTP %d' % status)
    for path in ('/api/state', '/api/integrations', '/api/providers', '/api/models?provider=codex', '/api/notifications?after=0'):
        status, _ = b.req('GET', path)
        record('API ' + path, status == 200, 'HTTP %d' % status)
    status, bot = b.req('POST', '/api/bots', {'name': '檢查用 Bot'})
    record('建立 Bot', status == 201, 'HTTP %d' % status)
    if status != 201: return
    status, item = b.req('POST', '/api/schedules', {'botId': bot['id'], 'content': '檢查', 'time': '10:00', 'repeat': 'daily'})
    record('建立排程', status == 201, 'HTTP %d' % status)
    if status == 201:
        record('刪除排程', b.req('DELETE', '/api/schedules/' + item['id'])[0] == 200)
    status, group = b.req('POST', '/api/groups', {'name': '檢查用群組', 'botIds': [bot['id'], b.req('GET', '/api/state')[1]['bots'][0]['id']]})
    record('建立群組', status == 201, 'HTTP %d' % status)
    if status == 201:
        status, item = b.req('POST', '/api/schedules', {'groupId': group['id'], 'content': '檢查', 'time': '09:15', 'repeat': 'monthly', 'day': 31})
        record('建立群組的每月排程', status == 201, 'HTTP %d' % status)
        record('刪除群組（連同排程）', b.req('DELETE', '/api/groups/' + group['id'])[0] == 200 and not b.req('GET', '/api/state')[1]['schedules'])
    record('刪除 Bot', b.req('DELETE', '/api/bots/' + bot['id'])[0] == 200)


def check_live(b, wanted):
    providers = b.req('GET', '/api/providers')[1].get('providers', [])
    for p in providers:
        if wanted and p['id'] not in wanted: continue
        if not p.get('installed'):
            if wanted: record('真實 CLI ' + p['name'], False, '沒有安裝')
            continue
        status, bot = b.req('POST', '/api/bots', {'name': '檢查 ' + p['name'], 'provider': p['id']})
        if status != 201:
            record('真實 CLI ' + p['name'], False, '無法建立 Bot：%s' % bot); continue
        started = time.time()
        status, sent = b.req('POST', '/api/chat', {'botId': bot['id'], 'content': LIVE_PROMPT})
        job = None
        if status == 202:
            end = started + 240
            while time.time() < end:
                job = b.req('GET', '/api/jobs/' + sent['jobId'])[1]
                if job.get('status') != 'running': break
                time.sleep(1)
        took = '%.0f 秒' % (time.time() - started)
        if status != 202: record('真實 CLI ' + p['name'], False, '送出失敗：%s' % sent)
        elif not job or job.get('status') == 'running': record('真實 CLI ' + p['name'], False, '超過 4 分鐘沒有回覆')
        else:
            reply = (job.get('content') or '').strip()
            ok = job.get('status') == 'completed' and 'ZOOK-OK' in reply
            record('真實 CLI ' + p['name'], ok, took + ('' if ok else '，' + (job.get('error') or reply or job.get('status', ''))[:200]))
        b.req('DELETE', '/api/bots/' + bot['id'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('app', nargs='?', default=str(ROOT / 'build/Zook.app'))
    parser.add_argument('--live', action='store_true', help='也用真實 CLI 送一則短訊息')
    parser.add_argument('--providers', default='', help='只檢查這些 CLI，以逗號分隔（例如 codex,claude）')
    args = parser.parse_args()
    app = Path(args.app).resolve()
    if not (app / 'Contents/Info.plist').exists():
        print('找不到 App：%s（先執行 bash scripts/build.sh）' % app); return 2
    check_bundle(app)
    folder = Path(tempfile.mkdtemp(prefix='zook-check-'))
    backend = None
    try:
        backend = Backend(app, folder)
        record('後端啟動', True)
        check_backend(backend)
        if args.live: check_live(backend, {x.strip() for x in args.providers.split(',') if x.strip()})
    except Exception as exc:
        record('後端啟動', False, str(exc)[:300])
    finally:
        if backend: backend.close()
        shutil.rmtree(folder, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print('\n%d 項通過，%d 項失敗' % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
