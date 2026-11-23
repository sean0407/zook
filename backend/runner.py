#!/usr/bin/env python3
"""Runs one CLI for Zook, so a reply keeps going while Zook is closed or being updated (背景執行, #35). Standard library only.

Zook starts this program in a session of its own and gives it, on stdin, one line of settings: the CLI's command, folder and
environment, and two secrets that exist only in memory (the CLI's tool token and the key Zook uses to reach this program again
after a restart). Whatever else arrives on stdin goes on to the CLI.

- What the CLI prints goes into files in this run's folder (out, err), which only this user can read. Zook reads them as they grow,
  also after it was closed and opened again; it deletes the folder once the reply is in.
- The CLI's Zook tools and Claude's check (tool_server.py, zook_gate.py) reach Zook through this program: the CLI's address points
  here, and each call is passed on to wherever Zook is now. While Zook is closed a call waits here (it is not counted as idle).
  Zook answers 503 {"retry": true} for a call it let go of unanswered while closing: nothing was done, so it is asked again
  once Zook is back. Any other broken connection is reported to the CLI as a failed call, never sent twice.
- It ends the CLI when nothing has happened for too long or at the overall limit, as Zook itself would. A kept CLI (live) is only
  timed once Zook is gone: until then Zook decides.
- When the CLI has ended and its last output is written, the file exit says how it ended, and this program leaves.
"""
import hmac
import http.client
import http.server
import select
import socket
import json
import re
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
import urllib.parse

VERSION = 1
MAX_BODY = 4 * 1024 * 1024
MAX_ERR = 1024 * 1024


def sign(key, *parts):
    """Proof that a message comes from someone who holds the runner key, without sending the key itself."""
    return hmac.new(key.encode(), b'\n'.join(p if isinstance(p, bytes) else str(p).encode() for p in parts), 'sha256').hexdigest()


def pid_alive(pid):
    try: os.kill(int(pid), 0); return True
    except ProcessLookupError: return False
    except (OSError, ValueError, TypeError): return True


def worker_url(url):
    """Only Zook's own worker address on this Mac: http://127.0.0.1:<port>/api/worker/<id>, nothing else in it."""
    if not isinstance(url, str): return False
    try: where = urllib.parse.urlsplit(url); port = where.port
    except ValueError: return False
    return (where.scheme == 'http' and where.hostname == '127.0.0.1' and where.netloc == '127.0.0.1:%d' % (port or 0) and bool(port)
            and not where.query and not where.fragment and bool(re.fullmatch(r'/api/worker/[A-Za-z0-9_-]{1,80}', where.path)))


class Run:
    def __init__(self, cfg):
        self.cfg = cfg; self.folder = pathlib.Path(cfg['dir'])
        self.cond = threading.Condition()
        self.url, self.auth = (cfg.get('url') if worker_url(cfg.get('url')) else ''), 'Bearer ' + (cfg.get('token') or '')  # where Zook is now, and how it knows the calls
        self.zook_pid = cfg.get('zook_pid')  # the Zook it belongs to now: once that process is gone, nothing is sent to its old address
        self.pending, self.last, self.stopped, self.proc, self.gone_at = 0, time.monotonic(), '', None, None
        self.out_size = 0; self.limit_at = time.monotonic() + float(cfg.get('limit') or 3600)

    def write_json(self, name, value):
        tmp = self.folder / ('.' + name + '.tmp')
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f: json.dump(value, f)
        os.replace(str(tmp), str(self.folder / name))

    def stop(self, why):
        """End the CLI and everything it started."""
        with self.cond:
            if not self.stopped: self.stopped = why
        proc = self.proc
        if not proc or proc.poll() is not None: return
        try: os.killpg(proc.pid, signal.SIGTERM)
        except OSError: pass
        def later():
            time.sleep(3)
            try: os.killpg(proc.pid, signal.SIGKILL)
            except OSError: pass
        threading.Thread(target=later, daemon=True).start()

    # Calls from the CLI ------------------------------------------------------------------------------------------------
    def forward(self, body, box, arrived):
        """(status, data) for one tool call, waiting while Zook is away. box['conn'] is the call's connection to Zook, so it can be
        cut when the CLI stops waiting (Zook then takes its approval card down); box['gone'] says the CLI stopped waiting."""
        hold = time.monotonic() + float(self.cfg.get('hold') or 720)
        with self.cond: self.pending += 1
        try:
            while not box.get('gone'):
                with self.cond:
                    if self.url and self.zook_pid and not pid_alive(self.zook_pid): self.url = ''
                    url, auth = self.url, self.auth
                if url:
                    where = urllib.parse.urlsplit(url)
                    conn = http.client.HTTPConnection(where.hostname, where.port, timeout=max(1, hold - time.monotonic())); box['conn'] = conn
                    try:
                        nonce = os.urandom(16).hex(); left = int(float(self.cfg.get('wait') or 660) - (time.monotonic() - arrived) - 5)
                        if left <= 0: return 504, b'{"error": "Zook is not open"}'
                        conn.request('POST', where.path, body, {'Authorization': auth, 'Content-Type': 'application/json', 'X-Zook-Nonce': nonce, 'X-Zook-Left': str(left)})
                        response = conn.getresponse(); status, data = response.status, response.read(MAX_BODY)
                        # Only Zook holds the runner key: an answer without its proof (another program on that port) is not passed on.
                        if not hmac.compare_digest(response.getheader('X-Zook-Proof') or '', sign(self.cfg['key'], 'zook', nonce, status, data)): return 502, b'{"error": "Zook connection lost"}'
                        retry = False
                        if status == 503:
                            try: retry = json.loads(data or b'{}').get('retry') is True
                            except ValueError: pass
                        if not retry: return status, data
                    except ConnectionRefusedError: pass  # Zook is not there
                    except (OSError, http.client.HTTPException): return 502, b'{"error": "Zook connection lost"}'
                    finally: box.pop('conn', None); conn.close()
                    with self.cond:  # Zook is not there (or let the call go while closing): wait for it to come back
                        if self.url == url: self.url = ''
                with self.cond:
                    if time.monotonic() >= hold: return 504, b'{"error": "Zook is not open"}'
                    self.cond.wait(1)
            return 499, b'{}'
        finally:
            with self.cond: self.pending -= 1; self.last = time.monotonic()

    def control(self, value):
        action = value.get('action')
        if action == 'hello': return 200, {'ok': True, 'version': VERSION}
        if action == 'attach':
            url, token, pid = value.get('url'), value.get('token'), value.get('pid')
            if not worker_url(url) or not isinstance(token, str) or not token or not isinstance(pid, int): return 400, {}
            with self.cond: self.url, self.auth, self.zook_pid = url, 'Bearer ' + token, pid; self.cond.notify_all()  # a kept CLI stays timed: no Zook writes to it any more
            return 200, {'ok': True}
        if action == 'stop': self.stop('stopped'); return 200, {'ok': True}
        if action == 'signal' and value.get('sig') in (signal.SIGTERM, signal.SIGKILL):
            proc = self.proc  # not collected yet, so its number is still its own
            if proc and proc.poll() is None:
                try: os.killpg(proc.pid, value['sig'])
                except OSError: pass
                return 200, {'ok': True, 'sent': True}
            return 200, {'ok': True, 'sent': False}
        if action == 'status': return 200, {'pending': self.pending, 'version': VERSION}
        return 400, {}

    # The CLI's output and input -----------------------------------------------------------------------------------------
    def pump(self, pipe, name, cap):
        fd = os.open(str(self.folder / name), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        written = 0
        try:
            while True:
                chunk = pipe.read1(65536)
                if not chunk: return
                if name == 'out': self.last = time.monotonic()
                if written + len(chunk) > cap: self.stop('輸出超過大小限制。'); continue  # ended, not cut short without a word
                os.write(fd, chunk); written += len(chunk)
        except (OSError, ValueError): pass
        finally: os.close(fd)

    def feed(self, data):
        """What Zook sends after the settings line goes to the CLI. When Zook goes away: a reply's input ends with it; a kept CLI
        keeps its input open (it finishes the message it has) and from then on this program times it."""
        proc = self.proc
        try:
            if data: proc.stdin.write(data); proc.stdin.flush()
            while True:
                chunk = sys.stdin.buffer.read1(65536)
                if not chunk: break
                proc.stdin.write(chunk); proc.stdin.flush()
        except (OSError, ValueError): pass
        with self.cond:
            self.gone_at = time.monotonic(); self.limit_at = time.monotonic() + float(self.cfg.get('limit') or 3600) if self.cfg.get('live') else self.limit_at
        if not self.cfg.get('live'):
            try: proc.stdin.close()
            except (OSError, ValueError): pass

    def watch(self):
        quiet = float(self.cfg.get('quiet') or 600)
        while self.proc.poll() is None:
            time.sleep(1)
            with self.cond:
                now = time.monotonic()
                if self.pending: self.last = now; self.limit_at += 1  # waiting for Zook or for the user does not count
                timed = not self.cfg.get('live') or self.gone_at is not None
                why = ('已超過時間上限。' if now >= self.limit_at else '太久沒有動靜。' if now - self.last >= quiet else '') if timed else ''
            if why: self.stop(why); return


def client_gone(sock):
    try:
        readable = select.select([sock], [], [], 0)[0]
        return bool(readable) and not sock.recv(1, socket.MSG_PEEK)
    except (OSError, ValueError): return True


def serve(run):
    port_box = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def reply(self, status, data, nonce=None):
            data = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
            if nonce: self.send_header('X-Zook-Proof', sign(run.cfg['key'], 'runner', nonce, status, data))  # Zook checks it is talking to this runner
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.headers.get('Host', '').lower() not in ('127.0.0.1:%d' % port_box[0], 'localhost:%d' % port_box[0]): return self.reply(403, {})
            try: size = int(self.headers.get('Content-Length') or 0)
            except ValueError: size = -1
            if not 0 <= size <= MAX_BODY: return self.reply(400, {})
            body = self.rfile.read(size); auth = self.headers.get('Authorization', ''); arrived = time.monotonic()
            ident = run.cfg.get('ident') or ''
            if self.path == '/control':
                nonce = self.headers.get('X-Zook-Nonce') or ''
                if not re.fullmatch(r'[0-9a-f]{32}', nonce) or not hmac.compare_digest(self.headers.get('X-Zook-Sig') or '', sign(run.cfg['key'], 'control', nonce, body)): return self.reply(403, {})
                try: value = json.loads(body)
                except ValueError: return self.reply(400, {})
                return self.reply(*run.control(value if isinstance(value, dict) else {}), nonce=nonce)
            if ident and self.path == '/api/worker/' + ident and hmac.compare_digest(auth, 'Bearer ' + (run.cfg.get('token') or '')):
                box, out = {}, {}
                worker = threading.Thread(target=lambda: out.update(r=run.forward(body, box, arrived)), daemon=True); worker.start()
                while worker.is_alive():
                    worker.join(1)
                    if worker.is_alive() and client_gone(self.connection):  # the CLI stopped waiting: so does Zook
                        box['gone'] = True; conn = box.get('conn')
                        try: conn and conn.sock and conn.sock.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
                if box.get('gone'): return
                return self.reply(*out['r'])
            return self.reply(403, {})

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
    port_box.append(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def main():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    line = sys.stdin.buffer.readline(MAX_BODY * 4)
    cfg = json.loads(line); run = Run(cfg)
    signal.signal(signal.SIGTERM, lambda *a: run.stop('stopped'))
    port = serve(run)
    env = dict(cfg['env'])
    if cfg.get('ident') and env.get('ZOOK_WORKER_URL'): env['ZOOK_WORKER_URL'] = 'http://127.0.0.1:%d/api/worker/%s' % (port, cfg['ident'])
    use_stdin = bool(cfg.get('stdin'))
    try:
        run.proc = subprocess.Popen(cfg['args'], stdin=subprocess.PIPE if use_stdin else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True, cwd=cfg['cwd'], env=env)
    except OSError as exc:
        run.write_json('exit', {'code': 127, 'error': exc.__class__.__name__}); return
    run.write_json('info', {'v': VERSION, 'cli': run.proc.pid, 'runner': os.getpid(), 'port': port})
    pumps = [threading.Thread(target=run.pump, args=(run.proc.stdout, 'out', int(cfg.get('max_out') or 64 * 1024 * 1024)), daemon=True),
             threading.Thread(target=run.pump, args=(run.proc.stderr, 'err', MAX_ERR), daemon=True)]
    for t in pumps: t.start()
    if use_stdin: threading.Thread(target=run.feed, args=(b'',), daemon=True).start()
    threading.Thread(target=run.watch, daemon=True).start()
    code = run.proc.wait()
    if run.stopped:  # what it started goes with it, as Zook would have ended it (only just collected: the number is still its group's)
        try: os.killpg(run.proc.pid, signal.SIGKILL)
        except OSError: pass
    for t in pumps: t.join(timeout=5)  # a helper it left behind may hold the output open: not waited for
    run.write_json('exit', {'code': code, 'stopped': run.stopped})


if __name__ == '__main__': main()
