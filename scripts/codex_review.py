#!/usr/bin/env python3
"""Codex review for Zook: runs the shared codex-review skill (~/.claude/skills/codex-review), which every project on this Mac uses.

    python3 scripts/codex_review.py --family sol --brief <審查說明.md> --out <結果.md>

The skill takes turns between this Mac's Codex accounts (Codex's own sign-in and the Codex sign-ins added in Zook), skips
accounts with under 20% left, never uses paid credits, picks the newest sol or astra model and runs Codex read-only.
Every option is passed on unchanged; see the skill's SKILL.md. This file only finds it, so Zook's instructions keep one command.
"""
import os, pathlib, sys

SHARED = pathlib.Path.home() / '.claude/skills/codex-review/scripts/codex_review.py'

if __name__ == '__main__':
    if not SHARED.is_file():
        print('找不到共用的 codex-review Skill（%s）。請先安裝共用設定庫。' % SHARED, file=sys.stderr); sys.exit(2)
    os.execv(sys.executable, [sys.executable, str(SHARED)] + sys.argv[1:])
