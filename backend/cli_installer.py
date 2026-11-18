#!/usr/bin/env python3
"""Install an npm-based CLI into Zook's own tools folder, so the Mac does not need Node.js.

Downloads the official Node.js LTS from nodejs.org (checked against its published SHA-256), then uses that
copy's npm. Nothing is written outside the tools folder and the user's PATH is left alone.
"""
import argparse
import hashlib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

NODE_DIST = 'https://nodejs.org/dist/latest-v22.x/'


def say(text):
    print(text, flush=True)


def pick_node(sums, machine):
    """The archive for this Mac and its checksum, from SHASUMS256.txt."""
    arch = 'arm64' if machine == 'arm64' else 'x64'
    found = re.search(r'^([0-9a-f]{64})\s+(node-v\d+\.\d+\.\d+-darwin-%s\.tar\.gz)$' % arch, sums, re.M)
    if not found: raise RuntimeError('nodejs.org 沒有提供這台 Mac 可用的 Node.js。')
    return found.group(2), found.group(1)


def safe_extract(archive, target):
    """Unpack only regular files, folders and links that stay inside target."""
    bad = RuntimeError('下載的檔案內容不正確。')
    outside = lambda path: os.path.isabs(path) or path == '..' or path.startswith('../')
    through = lambda path, links: any('/'.join(path.split('/')[:i]) in links for i in range(1, path.count('/') + 1))  # passes through a link
    members, links = archive.getmembers(), set()
    for m in members:
        name = os.path.normpath(m.name)
        if outside(m.name) or outside(name) or through(name, links) or not (m.isfile() or m.isdir() or m.issym()): raise bad
        if m.issym():
            goal = os.path.normpath(os.path.join(os.path.dirname(name), m.linkname))
            if os.path.isabs(m.linkname) or outside(goal) or through(goal + '/', links): raise bad
            links.add(name)
    archive.extractall(str(target), members=members)


def fetch(url, target=None):
    request = urllib.request.Request(url, headers={'User-Agent': 'Zook'})
    with urllib.request.urlopen(request, timeout=60) as response:
        if target is None: return response.read(1024 * 1024).decode('utf-8', 'replace')
        digest = hashlib.sha256()
        with open(str(target), 'wb') as out:
            for chunk in iter(lambda: response.read(1 << 20), b''):
                digest.update(chunk); out.write(chunk)
        return digest.hexdigest()


def ensure_node(tools):
    node = tools / 'node'
    if (node / 'bin/node').is_file():
        return node
    say('正在下載 Node.js…')
    name, expected = pick_node(fetch(NODE_DIST + 'SHASUMS256.txt'), platform.machine())
    work = tools / '.node-download'
    shutil.rmtree(str(work), ignore_errors=True); work.mkdir(parents=True, mode=0o700)
    try:
        file = work / name
        if fetch(NODE_DIST + name, file) != expected: raise RuntimeError('下載的 Node.js 檢查碼不符，已停止安裝。')
        say('正在解壓縮 Node.js…')
        with tarfile.open(str(file), 'r:gz') as archive: safe_extract(archive, work)
        os.replace(str(work / name[:-len('.tar.gz')]), str(node))
    finally: shutil.rmtree(str(work), ignore_errors=True)
    return node


def write_wrapper(tools, node, binary):
    """A launcher that finds this private Node.js, however the CLI is started."""
    folder = tools / 'bin'; folder.mkdir(parents=True, exist_ok=True)
    target = folder / binary; temp = folder / ('.' + binary + '.new')
    temp.write_text('#!/bin/sh\nPATH=%s:"$PATH"\nexport PATH\nexec %s "$@"\n' % (shlex.quote(str(node / 'bin')), shlex.quote(str(tools / 'npm/bin' / binary))), encoding='utf-8')
    temp.chmod(0o755); os.replace(str(temp), str(target))
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tools', required=True); parser.add_argument('--package', required=True); parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    tools = Path(args.tools); tools.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        node = ensure_node(tools)
        say('正在安裝 %s…' % args.package)
        env = dict(os.environ, PATH=str(node / 'bin') + ':/usr/bin:/bin', npm_config_cache=str(tools / 'npm-cache'), npm_config_update_notifier='false')
        done = subprocess.run([str(node / 'bin/npm'), 'install', '--global', '--prefix', str(tools / 'npm'), '--no-fund', '--no-audit', '--loglevel=error', args.package + '@latest'], env=env)
        if done.returncode != 0: raise RuntimeError('npm 沒有安裝成功，請確認網路連線後再試。')
        wrapper = write_wrapper(tools, node, args.binary)
        check = subprocess.run([str(wrapper), '--version'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        if check.returncode != 0: raise RuntimeError('安裝完成，但無法啟動 %s。' % args.binary)
        say('已安裝 %s %s' % (args.binary, check.stdout.decode('utf-8', 'replace').strip()[-40:]))
    except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as exc:
        say(str(exc) if isinstance(exc, RuntimeError) else '安裝沒有完成，請確認網路連線後再試。')
        return 1
    return 0


if __name__ == '__main__': sys.exit(main())
