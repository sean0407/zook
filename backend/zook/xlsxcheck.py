# Excel 檢查 (#173, #125): after a reply, the .xlsx files it saved are read (never changed) and plain problems are said under the reply:
# formulas with no saved value (Quick Look and the phone show 0), a total whose range also holds subtotals, a saved value that does not match
# a simple SUM, references a shell ate. The Bot hears it with the next message of that conversation.
# Standard library only (zipfile + expat). Loaded by backend/server.py into one shared namespace.
import math as _xmath
import posixpath as _xposix
import xml.etree.ElementTree as _XET
import zipfile as _xzip
import zlib as _xzlib

XLSX_MAX_BYTES = 20 * 1024 * 1024  # bigger files are skipped
XLSX_SECONDS = 2.0  # per file; slower ones are skipped
XLSX_FILES = 5  # files looked at per reply
XLSX_UNPACKED = 200 * 1024 * 1024  # all XML read from one file, unpacked
XLSX_SHEETS = 200
XLSX_WAIT = 15  # seconds the next reply waits for the check of the one before
XLSX_SUFFIXES = ('.xlsx', '.xlsm')
_XM = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_XR = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
_XP = '{http://schemas.openxmlformats.org/package/2006/relationships}'
_XCELL = re.compile(r'^\$?([A-Z]{1,3})\$?([0-9]{1,7})$')
_XRANGE = r'\$?[A-Z]{1,3}\$?[0-9]{1,7}(?::\$?[A-Z]{1,3}\$?[0-9]{1,7})?'
_XSUM = re.compile(r'(?<![A-Z0-9_.])SUM\(')
_XSIMPLE = re.compile(r'^=?SUM\(\s*(%s(?:\s*,\s*%s)*)\s*\)$' % (_XRANGE, _XRANGE))
_XBROKEN = re.compile(r'!\s*[:),]|[(,]\s*:|:\s*[),]|!\s*$')
_XERROR = re.compile(r'^#[A-Z0-9/!?]{1,8}$')
_XAREA = 20000  # a range bigger than this is matched against the known cells instead of walked


class _XSlow(Exception): pass


class _XGuard:
    """A zip member read in chunks: no DOCTYPE or other encodings (no entity tricks), a cap on what is unpacked, and a deadline."""
    def __init__(self, raw, deadline, budget): self.raw, self.deadline, self.budget, self.tail, self.first = raw, deadline, budget, b'', True

    def read(self, n=65536):
        if time.monotonic() > self.deadline: raise _XSlow()
        chunk = self.raw.read(min(n, 65536) if n and n > 0 else 65536)
        self.budget[0] -= len(chunk)
        if self.budget[0] < 0: raise _XSlow()
        if self.first and chunk:
            self.first = False
            if chunk[:2] in (b'\xff\xfe', b'\xfe\xff') or b'\x00' in chunk[:64]: raise ValueError('encoding')  # UTF-16 would hide a DOCTYPE from the check below
        if b'<!DOCTYPE' in self.tail + chunk or b'<!ENTITY' in self.tail + chunk: raise ValueError('doctype')
        self.tail = chunk[-16:]; return chunk


def _xpos(ref):
    m = _XCELL.match(str(ref or '').upper())
    if not m: return None
    col = 0
    for ch in m.group(1): col = col * 26 + ord(ch) - 64
    return int(m.group(2)), col


def _xname(pos):
    row, col = pos; letters = ''
    while col: col, rest = divmod(col - 1, 26); letters = chr(65 + rest) + letters
    return '%s%d' % (letters, row)


def _xnum(x):
    if x == int(x) and abs(x) < 1e15: return '{:,}'.format(int(x))
    return '{:,.2f}'.format(x)


def _xbare(text):
    """A formula with its strings emptied and quoted sheet names replaced, so words inside them are not read as references."""
    return re.sub(r"'(?:[^']|'')*'", 'S', re.sub(r'"(?:[^"]|"")*"', '""', text)).upper()


def _xparse(z, part, deadline, budget):
    return _XET.iterparse(_XGuard(z.open(part), deadline, budget), events=('end',))


def _xsheets(z, deadline, budget):
    """[(sheet name, zip part)] in workbook order."""
    targets = {}
    for _, el in _xparse(z, 'xl/_rels/workbook.xml.rels', deadline, budget):
        if el.tag == _XP + 'Relationship' and el.get('Id'):
            target = el.get('Target') or ''
            targets[el.get('Id')] = target.lstrip('/') if target.startswith('/') else _xposix.normpath('xl/' + target)
    found = []
    for _, el in _xparse(z, 'xl/workbook.xml', deadline, budget):
        if el.tag == _XM + 'sheet' and targets.get(el.get(_XR)): found.append((str(el.get('name') or '')[:40], targets[el.get(_XR)]))
    return found


def _xread_sheet(z, part, deadline, budget):
    """{(row, col): (number or None, is a SUM formula, is a formula)}, {pos: [ranges of its SUM]} and [(pos, bare formula, saved number, saved text, type)]."""
    cells, sums, formulas, shared = {}, {}, [], {}
    for n, (_, el) in enumerate(_xparse(z, part, deadline, budget)):
        if n % 2000 == 0 and time.monotonic() > deadline: raise _XSlow()
        if el.tag == _XM + 'row': el.clear(); continue  # the cells read so far are let go
        if el.tag != _XM + 'c': continue
        f, v, kind = el.find(_XM + 'f'), el.find(_XM + 'v'), el.get('t')
        saved = (v.text or '') if v is not None else None
        try: number = float(saved) if saved not in (None, '') and kind in (None, 'n') else None
        except ValueError: number = None
        if number is not None and not _xmath.isfinite(number): number = None
        pos = _xpos(el.get('r'))
        if f is not None:
            text = _xbare((f.text or '').strip()); si = f.get('si')
            is_sum = bool(_XSUM.search(text)) if text else shared.get(si, False)
            if f.get('t') == 'shared' and text and si is not None: shared[si] = is_sum
            formulas.append((pos, text, number, saved, kind))
            if pos:
                cells[pos] = (number, is_sum, True)
                if text and is_sum: sums[pos] = [r for args in _xsum_args(text) for r in _xrefs(args)]
        elif pos: cells[pos] = (number, False, False)
        el.clear()
    return cells, sums, formulas


def _xrefs(args):
    """[(first, last)] positions for each reference or range in a formula's argument text; sheet-qualified ones are left out."""
    out = []
    for m in re.finditer(r"(?<![A-Z0-9_!$'.:])(%s)(?![A-Z0-9_(!])" % _XRANGE, args):
        a, _, b = m.group(1).partition(':'); first, last = _xpos(a), _xpos(b or a)
        if first and last: out.append(((min(first[0], last[0]), min(first[1], last[1])), (max(first[0], last[0]), max(first[1], last[1]))))
    return out


def _xinside(cells, first, last):
    area = (last[0] - first[0] + 1) * (last[1] - first[1] + 1)
    if area <= _XAREA:
        return [((r, c), cells[(r, c)]) for r in range(first[0], last[0] + 1) for c in range(first[1], last[1] + 1) if (r, c) in cells]
    return [(p, x) for p, x in cells.items() if first[0] <= p[0] <= last[0] and first[1] <= p[1] <= last[1]]


def _xoverlap(a, b):
    return a[0][0] <= b[1][0] and b[0][0] <= a[1][0] and a[0][1] <= b[1][1] and b[0][1] <= a[1][1]


def _xsum_args(text):
    """The argument text of each SUM( in a formula."""
    out = []
    for m in _XSUM.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {'(': 1, ')': -1}.get(text[i], 0); i += 1
        out.append(text[m.end():i - 1])
    return out


def xlsx_issues(path, for_bot=False):
    """Plain sentences about one workbook's formulas, or [] when it looks sound, is too big, unreadable or slow. Only reads the file.
    for_bot: sheets are named by their place (第 2 張工作表), never by the words in the file, and saved error texts are left out."""
    deadline = time.monotonic() + XLSX_SECONDS; budget = [XLSX_UNPACKED]
    missing, errors, double, wrong, broken = [], [], [], [], []
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)  # a pipe put in the file's place does not hold the check up
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > XLSX_MAX_BYTES: return []
            with _xzip.ZipFile(handle) as z:
                for index, (name, part) in enumerate(_xsheets(z, deadline, budget)[:XLSX_SHEETS]):
                    try: z.getinfo(part)
                    except KeyError: continue
                    cells, sums, formulas = _xread_sheet(z, part, deadline, budget)
                    label = '第 %d 張工作表' % (index + 1) if for_bot else name
                    where = lambda pos: '%s!%s' % (label, _xname(pos)) if pos else label
                    for pos, text, number, saved, kind in formulas:
                        if time.monotonic() > deadline: raise _XSlow()
                        if saved is None or (saved == '' and kind != 'str'): missing.append(where(pos))
                        elif kind == 'e': errors.append(where(pos) + ('' if for_bot or not _XERROR.match(saved) else '（%s）' % saved))
                        if text and _XBROKEN.search(text): broken.append(where(pos))
                        if not text or not pos or pos not in sums: continue
                        stacked = False  # a subtotal inside the range whose own detail rows are inside it too
                        for outer in sums[pos]:
                            for p, x in _xinside(cells, *outer):
                                if p != pos and x[1] and any(_xoverlap(outer, inner) for inner in sums.get(p, ())): stacked = True; break
                            if stacked: break
                        simple = _XSIMPLE.match(text.replace(' ', ''))
                        redo = None
                        if simple and number is not None:
                            redo = 0.0
                            for first, last in _xrefs(simple.group(1)):  # every argument counts, the same cell twice too
                                for p, x in _xinside(cells, first, last):
                                    if p == pos or (x[2] and x[0] is None): redo = None; break  # itself, or a formula with no saved value: cannot tell
                                    redo += x[0] or 0.0
                                if redo is None: break
                        off = redo is not None and abs(redo - number) > max(1e-6, 1e-12 * abs(redo))
                        detail = '：存的是 %s，Excel 重算會是 %s' % (_xnum(number), _xnum(redo)) if off else ''
                        if stacked: double.append(where(pos) + detail)
                        elif off: wrong.append(where(pos) + detail)
    except (_XSlow, _xzip.BadZipFile, _XET.ParseError, _xzlib.error, KeyError, OSError, ValueError, RuntimeError, EOFError, NotImplementedError, OverflowError, RecursionError):
        return []
    out = []
    if missing: out.append('有 %d 格公式沒有算好的值，預覽和手機會顯示 0（例如 %s）' % (len(missing), '、'.join(missing[:3])))
    if double: out.append('總計公式可能把小計重複加總（%s）' % '；'.join(double[:3]))
    if wrong: out.append('有 %d 格公式存的值和重算結果不符（%s）' % (len(wrong), '；'.join(wrong[:3])))
    if broken: out.append('公式看起來不完整，可能有參照被吃掉（例如 %s）' % '、'.join(broken[:3]))
    if errors: out.append('有 %d 格公式算出錯誤（例如 %s）' % (len(errors), '、'.join(errors[:3])))
    return out


def _xstamp(text):
    try: return datetime.datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError): return None


def _xsafe_name(name):
    """A file name as the Bot will read it: one line, no brackets that could close the note, short."""
    return re.sub(r'[\r\n\t（）()「」\[\]{}<>]', ' ', str(name))[:80]


def xlsx_after_reply(store, job_id):
    """After a finished reply: check the Excel files it saved and write what is wrong under it and on the job. Never holds the lock while reading files."""
    with store.lock:
        job = store.find('jobs', job_id)
        if not job: return
        if job.get('status') != 'completed' or job.get('plan'): job['xlsxChecked'] = True; return
        bot = store.find('bots', job['botId'])
        start, end = _xstamp(job.get('createdAt')), _xstamp(job.get('finishedAt'))
        if not bot or start is None or end is None: job['xlsxChecked'] = True; return
    shown, told, looked = [], [], 0
    try:
        for item in bot_outputs(store, bot):
            if looked >= XLSX_FILES: break
            if not item['name'].lower().endswith(XLSX_SUFFIXES): continue
            try: when = os.stat(item['path'], follow_symlinks=False).st_mtime
            except OSError: continue
            if not start <= when <= end + 1: continue  # only what this reply saved (its CLI had ended by finishedAt)
            looked += 1
            found = xlsx_issues(item['path'])
            if found:
                shown.append('%s：%s' % (item['name'][:80].replace('\n', ' '), '；'.join(found)))
                told.append('「%s」：%s' % (_xsafe_name(item['name']), '；'.join(xlsx_issues(item['path'], for_bot=True)) or '公式有問題'))
    finally:
        with store.lock:
            job = store.find('jobs', job_id)
            if job:
                job['xlsxChecked'] = True
                if shown:
                    job['xlsxIssues'] = told
                    owner = store.find('groups', job['groupId']) if job.get('groupId') else store.find('bots', job['botId'])
                    message = find_message(owner, job.get('messageId')) if owner else None
                    if message: message['note'] = '；'.join(x for x in (message.get('note'), *shown) if x)
                store.save()


def _xlast(store, bot_id, chat_id, before):
    return next((j for j in reversed(store.data['jobs']) if j.get('id') != before and j.get('botId') == bot_id and j.get('chatId') == chat_id
                 and not j.get('groupId') and j.get('status') == 'completed'), None)


def xlsx_carry(store, job):
    """For a reply about to start (lock not held): what the last finished reply of its conversation saved wrong in Excel files, or ''.
    Waits a little when that reply's check is still running, so a message sent right after it still hears about it."""
    if job.get('groupId') or not job.get('chatId'): return ''
    end = time.monotonic() + XLSX_WAIT
    while True:
        with store.lock:
            last = _xlast(store, job.get('botId'), job['chatId'], job.get('id'))
            if not last: return ''
            finished = _xstamp(last.get('finishedAt'))
            ready = last.get('xlsxChecked') or finished is None or time.time() - finished > XLSX_WAIT + 30  # an older reply, or one from before this check
            issues = last.get('xlsxIssues')
        if ready or time.monotonic() > end: break
        time.sleep(0.1)
    lines = [str(x)[:600].replace('\n', ' ') for x in issues if isinstance(x, str)][:XLSX_FILES] if isinstance(issues, list) else []
    if not lines: return ''
    return ('\n（Zook 的檢查結果，不是使用者的話：你上一則回覆存的 Excel 有問題——%s。請在這次回覆一併修好：公式和算好的值都要存，合計範圍不要包含小計；'
            '做不到就照實告訴使用者。）' % '；'.join(lines))
