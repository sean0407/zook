#!/usr/bin/env python3
"""Local, authenticated Zook service. Python 3.9+, standard library only.

The code is in backend/zook/, one file per area. The files run in this order and share one namespace,
exactly as if they were a single file."""
import pathlib as _pathlib

for _part in ('core', 'datecheck', 'chatfiles', 'accounts', 'agyhome', 'agykeychain', 'library', 'oauth', 'catalog', 'outputs', 'xlsxcheck', 'pptxcheck', 'pdfcheck', 'mobile', 'phonenotice', 'groupfiles', 'groups', 'triggers', 'sync', 'errors', 'stream', 'progress', 'waiting', 'intake', 'paging', 'chatexport', 'compact', 'automation', 'choices', 'teams', 'intro', 'live', 'cursor', 'gate', 'scratch', 'browser', 'tasks', 'taskrun', 'taskcheck', 'taskplus', 'rounds', 'gitwork', 'resume', 'background', 'scheduling', 'app', 'parsing', 'actwords', 'abilities', 'grokquota', 'sessions', 'routing', 'fields', 'upkeep', 'backupplus', 'usageview', 'usagewatch', 'templates', 'handler'):
    _file = _pathlib.Path(__file__).with_name('zook') / (_part + '.py')
    exec(compile(_file.read_text(encoding='utf-8'), str(_file), 'exec'), globals())
