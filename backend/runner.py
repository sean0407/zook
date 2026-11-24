#!/usr/bin/env python3
"""Runs one CLI for Zook, so a reply keeps going while Zook is closed or being updated (背景執行, #35). Standard library only.

Zook starts this program in a session of its own and gives it, on stdin, one line of settings: the CLI's command, folder and
environment, and two secrets made for this run alone (the CLI's tool token and this run's control key; Zook can make them again
after a restart from its own key in the Keychain, which never comes here). Whatever else arrives on stdin goes on to the CLI.
- No secret is ever sent over a connection. Each request carries a signature made with the secret, its own random nonce and the
  time, and each answer a proof made with the same secret over that nonce: a program that takes an old port over can neither
  read a secret nor answer in Zook's place, and a request cannot be used twice.

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

VERSION = 2
ANCHOR = '''import os, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN); signal.signal(signal.SIGHUP, signal.SIG_IGN)
while os.getppid() != 1: time.sleep(0.3)
os.killpg(0, signal.SIGTERM); time.sleep(2); os.killpg(0, signal.SIGKILL)
'''
MAX_BODY = 4 * 1024 * 1024
MAX_ERR = 1024 * 1024


def sign(key, *parts):
    """Proof that a message comes from someone who holds the runner key, without sending the key itself."""
    return hmac.new(key.encode(), b'\n'.join(p if isinstance(p, bytes) else str(p).encode() for p in parts), 'sha256').hexdigest()


class Fresh:
    """Requests already seen (by nonce) and their time: a request is taken once, and only while its time is close to now."""
    def __init__(self): self.seen, self.lock = {}, threading.Lock()

    def ok(self, nonce, when):
        try: when = int(when)
        except (TypeError, ValueError): return False
        now = time.time()
        if not re.fullmatch(r'[0-9a-f]{32}', nonce or '') or abs(now - when / 1000) > 300: return False  # milliseconds
        with self.lock:
            for old in [n for n, t in self.seen.items() if now - t > 900]: del self.seen[old]
            if nonce in self.seen: return False
            self.seen[nonce] = now
        return True


def signed(headers, secret, kind, *parts):
    """Whether a request carries a valid signature for this secret: (nonce) or None."""
    nonce, when = headers.get('X-Zook-Nonce') or '', headers.get('X-Zook-Time') or ''
    if not secret or not hmac.compare_digest(headers.get('X-Zook-Sig') or '', sign(secret, kind, nonce, when, *parts)): return None
    return nonce


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
        self.url = cfg.get('url') if worker_url(cfg.get('url')) else ''  # where Zook is now
        self.zook_pid = cfg.get('zook_pid')  # the Zook it belongs to now: once that process is gone, nothing is sent to its old address
        self.pending, self.last, self.stopped, self.proc, self.gone_at = 0, time.monotonic(), '', None, None
        self.out_size = 0; self.limit_at = time.monotonic() + float(cfg.get('limit') or 3600)
        self.fresh, self.reaped, self.group = Fresh(), False, None  # group: the CLI's process group, held by a placeholder (main)

    def write_json(self, name, value):
        tmp = self.folder / ('.' + name + '.tmp')
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f: json.dump(value, f)
        os.replace(str(tmp), str(self.folder / name))

    def stop(self, why):
        """End the CLI and everything it started."""
        with self.cond:
            if not self.stopped: self.stopped = why
        self.kill(signal.SIGTERM)
        def later():
            time.sleep(3); self.kill(signal.SIGKILL)
        threading.Thread(target=later, daemon=True).start()

    def alive(self): return bool(self.proc) and self.proc.poll() is None

    def kill(self, sig):
        """Signal the CLI and everything it started (its process group). The group's number belongs to a placeholder this program
        collects only at the very end, so it cannot be anyone else's while this can still be called."""
        with self.cond:
            if self.reaped or not self.group: return False
            try: os.killpg(self.group, sig); return True
            except OSError: return False

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
                    url = self.url
                if url:
                    where = urllib.parse.urlsplit(url)
                    conn = http.client.HTTPConnection(where.hostname, where.port, timeout=max(1, hold - time.monotonic())); box['conn'] = conn
                    try:
                        nonce, when = os.urandom(16).hex(), str(int(time.time() * 1000)); left = int(float(self.cfg.get('wait') or 660) - (time.monotonic() - arrived) - 5)
                        if left <= 0: return 504, b'{"error": "Zook is not open"}'
                        token = self.cfg.get('token') or ''  # signed with it, never sent: a program on Zook's old port learns nothing to use
                        conn.request('POST', where.path, body, {'Content-Type': 'application/json', 'X-Zook-Nonce': nonce, 'X-Zook-Time': when,
                                                                'X-Zook-Sig': sign(token, 'call', nonce, when, '%s%s' % (where.port, where.path), body), 'X-Zook-Left': str(left)})
                        response = conn.getresponse(); status, data = response.status, response.read(MAX_BODY)
                        # Only Zook can make the token again: an answer without its proof (another program on that port) is not passed on.
                        if not hmac.compare_digest(response.getheader('X-Zook-Proof') or '', sign(token, 'answer', nonce, status, data)): return 502, b'{"error": "Zook connection lost"}'
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
        if action == 'attach':  # where Zook is now (no secret in it: the token this run signs with stays the same)
            url, pid = value.get('url'), value.get('pid')
            if not worker_url(url) or not isinstance(pid, int) or isinstance(pid, bool): return 400, {}
            with self.cond: self.url, self.zook_pid = url, pid; self.cond.notify_all()  # a kept CLI stays timed: no Zook writes to it any more
            return 200, {'ok': True}
        if action == 'stop' or (action == 'signal' and value.get('sig') in (signal.SIGTERM, signal.SIGKILL)):
            running = self.alive()
            self.stop('stopped')  # the whole group, ended for sure (SIGKILL after a moment), and recorded as stopped
            return 200, {'ok': True, 'sent': running}
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
        while self.alive():
            time.sleep(1)
            with self.cond:
                now = time.monotonic()
                if self.pending: self.last = now; self.limit_at += 1  # waiting for Zook or for the user does not count
                timed = not self.cfg.get('live') or self.gone_at is not None
                # While its Zook is there, Zook times the reply and explains why it stopped; this is only a late backstop then.
                spare = 120 if self.zook_pid and pid_alive(self.zook_pid) else 0
                why = ('已超過時間上限。' if now >= self.limit_at + spare else (self.cfg.get('quiet_why') or '太久沒有動靜。') if now - self.last >= quiet + spare else '') if timed else ''
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

        def reply(self, status, data, proof=None):
            data = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
            if proof: self.send_header('X-Zook-Proof', sign(run.cfg[proof[0]], proof[1], proof[2], status, data))  # the asker checks it is talking to this run
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.headers.get('Host', '').lower() not in ('127.0.0.1:%d' % port_box[0], 'localhost:%d' % port_box[0]): return self.reply(403, {})
            try: size = int(self.headers.get('Content-Length') or 0)
            except ValueError: size = -1
            if not 0 <= size <= MAX_BODY: return self.reply(400, {})
            body = self.rfile.read(size); arrived = time.monotonic()
            ident = run.cfg.get('ident') or ''
            if self.path == '/control':  # signed with this run's own key, for this run: another run's command is refused
                nonce = signed(self.headers, run.cfg.get('key'), 'control', run.folder.name, body)
                if nonce is None or not run.fresh.ok(nonce, self.headers.get('X-Zook-Time')): return self.reply(403, {})
                try: value = json.loads(body)
                except ValueError: return self.reply(400, {})
                return self.reply(*run.control(value if isinstance(value, dict) else {}), proof=('key', 'runner', nonce))
            nonce = signed(self.headers, run.cfg.get('token'), 'call', '%d%s' % (port_box[0], self.path), body) if ident and self.path == '/api/worker/' + ident else None  # signed for this address
            if nonce is not None and run.fresh.ok(nonce, self.headers.get('X-Zook-Time')):
                box, out = {}, {}
                worker = threading.Thread(target=lambda: out.update(r=run.forward(body, box, arrived)), daemon=True); worker.start()
                while worker.is_alive():
                    worker.join(0.1)  # noticed within a moment: Zook takes the card down before anyone can answer it
                    if worker.is_alive() and client_gone(self.connection):  # the CLI stopped waiting: so does Zook
                        box['gone'] = True; conn = box.get('conn')
                        try: conn and conn.sock and conn.sock.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
                if box.get('gone'): return
                return self.reply(*out['r'], proof=('token', 'answer', nonce))  # the CLI's hook checks the answer is this run's
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
    # A placeholder leads the CLI's process group and stays until this program ends, so the group's number stays this run's even
    # after the CLI itself has ended and been collected (a number of an ended, collected process may be given to anything else).
    # If this program is ended by force, it ends the CLI and everything in the group, then itself: nothing runs on unwatched.
    anchor = subprocess.Popen([sys.executable, '-I', '-c', ANCHOR], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, preexec_fn=lambda: os.setpgid(0, 0))
    run.group = anchor.pid
    if run.stopped:  # told to stop before the CLI started: it never starts
        with run.cond: run.reaped = True
        anchor.kill(); anchor.wait(); run.write_json('exit', {'code': -15, 'stopped': run.stopped}); return
    try:
        run.proc = subprocess.Popen(cfg['args'], stdin=subprocess.PIPE if use_stdin else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    preexec_fn=lambda: os.setpgid(0, anchor.pid), cwd=cfg['cwd'], env=env)
    except OSError as exc:
        with run.cond: run.reaped = True  # nothing signals the group from here on
        anchor.kill(); anchor.wait()
        run.write_json('exit', {'code': 127, 'error': exc.__class__.__name__}); return
    if run.stopped: run.stop(run.stopped)  # told to stop while it was starting
    run.write_json('info', {'v': VERSION, 'cli': run.proc.pid, 'runner': os.getpid(), 'port': port})
    pumps = [threading.Thread(target=run.pump, args=(run.proc.stdout, 'out', int(cfg.get('max_out') or 64 * 1024 * 1024)), daemon=True),
             threading.Thread(target=run.pump, args=(run.proc.stderr, 'err', MAX_ERR), daemon=True)]
    for t in pumps: t.start()
    if use_stdin: threading.Thread(target=run.feed, args=(b'',), daemon=True).start()
    threading.Thread(target=run.watch, daemon=True).start()
    code = run.proc.wait()
    if run.stopped: run.kill(signal.SIGKILL)  # what it started goes with it, as Zook would have ended it
    with run.cond: run.reaped = True  # from here on nothing signals the group: the placeholder may be collected below
    try: anchor.kill()
    except OSError: pass
    anchor.wait()
    for t in pumps: t.join(timeout=5)  # a helper it left behind may hold the output open: not waited for
    run.write_json('exit', {'code': code, 'stopped': run.stopped})


if __name__ == '__main__':
    status = 0
    try: main()
    except BaseException:
        import traceback; traceback.print_exc(); status = 1  # into the run's log
    finally:
        # Out at once: its helper threads (output, the tool address) may still be busy, and a Python that waits for them on the
        # way out can end in a crash report (Python quit unexpectedly) instead of a quiet exit.
        try: sys.stdout.flush(); sys.stderr.flush()
        except (OSError, ValueError): pass
        os._exit(status)
