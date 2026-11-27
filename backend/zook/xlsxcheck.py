# Excel 檢查 (#173, #125): after a reply, the .xlsx files it saved are read (never changed) and plain problems are said under the reply:
# formulas with no saved value (Quick Look and the phone show 0), a total whose range also holds subtotals, a saved value that does not match
# a simple SUM, references a shell ate. The Bot hears it with the next message of that conversation.
# Standard library only (zipfile + expat). Loaded by backend/server.py into one shared namespace.
import math as _xmath
import posixpath as _xposix
import zipfile as _xzip
import zlib as _xzlib

XLSX_MAX_BYTES = 20 * 1024 * 1024  # bigger files are skipped
XLSX_SECONDS = 2.0  # per file; slower ones are skipped
XLSX_FILES = 5  # files looked at per reply
XLSX_UNPACKED = 200 * 1024 * 1024  # all XML read from one file, unpacked
XLSX_SHEETS = 200
XLSX_WAIT = 20  # seconds the next reply waits for the check of the one before
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
# #347: a conditional total or count over a table (SUMIFS, COUNTIF …) whose ranges stop before the table does: 原始明細!$G$2:$G$55 with
# sales down to row 57. Only these functions: a plain SUM of the first rows may be meant (a quarter), a SUMIFS over part of a table hardly ever.
_XCOND = re.compile(r'(?<![A-Z0-9_.])(?:SUMIFS?|COUNTIFS?|AVERAGEIFS?|MAXIFS|MINIFS)\(')
_XQREF = re.compile(r"(?:(?:'((?:[^']|'')+)'|([^\s'!(),;=+\-*/^&<>{}\":\[\]$]+))!)?(?<![A-Z0-9_.$:])(\$?[A-Z]{1,3}\$?[0-9]{1,7}:\$?[A-Z]{1,3}\$?[0-9]{1,7})(?![A-Z0-9_(!])")
_XSHORT_ROWS = 10000  # rows looked at past a range's end
_XSHORT_COLS = 50
# #227: what a formula should take from a cell but has written in: a cell matched against a fixed item code with a number in the formula
# (IF(A8="X100",C8*0.1,0)), or only numbers and arithmetic (=1200*3). 0 and 1 are left alone (IF(...,1,0)).
_XCODE = re.compile(r'(?<![A-Za-z0-9_$.!])\$?[A-Za-z]{1,3}\$?[0-9]{1,7}\s*(?:=|<>)\s*"(?:[^"]|"")+"|"(?:[^"]|"")+"\s*(?:=|<>)\s*\$?[A-Za-z]{1,3}\$?[0-9]{1,7}(?![0-9])')
_XLITERAL = re.compile(r'(?<![A-Z0-9_$.:!])([0-9]+(?:\.[0-9]+)?)(?![0-9A-Z(.:!])')
_XARITH = re.compile(r'^=?[\s0-9.+\-*/^()%]+$')


class _XSlow(Exception): pass


def _xfixed(raw, bare):
    """Whether a formula has numbers or an item code written in where a cell should be referred to (#227)."""
    if not raw: return False
    if _XARITH.match(bare) and re.search(r'[0-9.]\s*\)*\s*[+\-*/^]\s*\(*\s*[0-9.]', bare): return True
    return bool(_XCODE.search(raw)) and any(float(m.group(1)) not in (0.0, 1.0) for m in _XLITERAL.finditer(bare))


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
    """A formula with its strings emptied and quoted sheet names replaced, in one pass, so words inside them are not read as references."""
    out, i = [], 0
    while i < len(text):
        q = text[i]
        if q in '"\'':
            j = i + 1
            while j < len(text):
                if text[j] == q and text[j + 1:j + 2] == q: j += 2; continue
                if text[j] == q: break
                j += 1
            out.append('""' if q == '"' else 'S'); i = j + 1
        else: out.append(q); i += 1
    return ''.join(out).upper()


def _xnamed(text):
    """Like _xbare, but quoted sheet names are kept ('原始 明細'!G2:G9 stays as it is, upper-cased like the rest)."""
    out, i = [], 0
    while i < len(text):
        q = text[i]
        if q in '"\'':
            j = i + 1
            while j < len(text):
                if text[j] == q and text[j + 1:j + 2] == q: j += 2; continue
                if text[j] == q: break
                j += 1
            out.append('""' if q == '"' else text[i:j + 1]); i = j + 1
        else: out.append(q); i += 1
    return ''.join(out).upper()


def _xcond_ranges(raw):
    """[[(sheet name upper-cased or None for its own sheet, first, last)] for each SUMIFS-like call] with ranges of two rows or more;
    a call naming another workbook ([1]Sheet!) is left out."""
    text, calls = _xnamed(raw), []
    for m in _XCOND.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {'(': 1, ')': -1}.get(text[i], 0); i += 1
        args, ranges = text[m.end():i - 1], []
        for r in _XQREF.finditer(args):
            if r.start() and args[r.start() - 1] == ']': ranges = None; break
            a, _, b = r.group(3).partition(':'); first, last = _xpos(a), _xpos(b)
            if not first or not last: continue
            first, last = (min(first[0], last[0]), min(first[1], last[1])), (max(first[0], last[0]), max(first[1], last[1]))
            sheet = r.group(1).replace("''", "'") if r.group(1) is not None else r.group(2)
            if last[0] > first[0]: ranges.append((sheet, first, last))
        if ranges: calls.append(ranges)
    return calls


def _xpast(cells, first, last, deadline, totals=()):
    """How many rows right after a range hold a value in every one of its columns. A SUM in any of them or in the call's other columns
    of that sheet (totals) is a total row and ends the table; a blank cell ends it too: rows after a gap are not counted."""
    if last[1] - first[1] >= _XSHORT_COLS: return 0
    n = 0
    while n < _XSHORT_ROWS:
        row = last[0] + n + 1
        if n % 500 == 0 and time.monotonic() > deadline: raise _XSlow()
        if not all((x := cells.get((row, c))) and x[3] and not x[1] for c in range(first[1], last[1] + 1)): break
        if any((cells.get((row, c)) or (0, False))[1] for c in totals): break
        n += 1
    return n


class _XDeadline:
    def __init__(self, deadline): self.deadline = deadline
    def is_set(self): return time.monotonic() > self.deadline


def _xparse(z, part, deadline, budget, tags):
    """('end', record) for each element of part whose tag is in tags, with what is inside it: Zook's one safe XML reader
    (knowledge.py: the bytes really unpacked are counted, DOCTYPE and entities refused, elements and depth capped, nothing else kept)."""
    late = _XDeadline(deadline)
    for record in knowledge_xml_records(knowledge_zip_stream(z, part, budget, late), tags, late): yield 'end', record  # the deadline holds while it unpacks too


def _xsheets(z, deadline, budget):
    """[(sheet name, zip part)] in workbook order."""
    targets = {}
    for _, el in _xparse(z, 'xl/_rels/workbook.xml.rels', deadline, budget, {_XP + 'Relationship'}):
        if el.tag == _XP + 'Relationship' and el.get('Id'):
            target = el.get('Target') or ''
            targets[el.get('Id')] = target.lstrip('/') if target.startswith('/') else _xposix.normpath('xl/' + target)
    found = []
    for _, el in _xparse(z, 'xl/workbook.xml', deadline, budget, {_XM + 'sheet'}):
        if el.tag == _XM + 'sheet' and targets.get(el.get(_XR)): found.append((str(el.get('name') or '')[:40], targets[el.get(_XR)]))
    return found


def _xread_sheet(z, part, deadline, budget):
    """{(row, col): (number or None, is a SUM formula, is a formula, holds a value)}, {pos: [ranges of its SUM]},
    [(pos, bare formula, saved number, saved text, type)] and [(pos, SUMIFS-like calls)]."""
    cells, sums, formulas, shared, shared_fixed, conds = {}, {}, [], {}, {}, []
    for n, (_, el) in enumerate(_xparse(z, part, deadline, budget, {_XM + 'c'})):
        if n % 2000 == 0 and time.monotonic() > deadline: raise _XSlow()
        if el.tag == _XM + 'row': el.clear(); continue  # the cells read so far are let go
        if el.tag != _XM + 'c': continue
        f, v, kind = el.find(_XM + 'f'), el.find(_XM + 'v'), el.get('t')
        saved = (v.text or '') if v is not None else None
        try: number = float(saved) if saved not in (None, '') and kind in (None, 'n') else None
        except ValueError: number = None
        if number is not None and not _xmath.isfinite(number): number = None
        pos = _xpos(el.get('r'))
        held = saved not in (None, '') or el.find(_XM + 'is') is not None
        if f is not None:
            raw = (f.text or '').strip(); text = _xbare(raw); si = f.get('si')
            is_sum = bool(_XSUM.search(text)) if text else shared.get(si, False)
            fixed = _xfixed(raw, text) if text else shared_fixed.get(si, False)  # a shared formula's other cells carry only its index
            if f.get('t') == 'shared' and text and si is not None: shared[si] = is_sum; shared_fixed[si] = fixed
            formulas.append((pos, text, number, saved, kind, fixed))
            if pos:
                cells[pos] = (number, is_sum, True, held)
                if text and is_sum: sums[pos] = [r for args in _xsum_args(text) for r in _xrefs(args)]
                if text and _XCOND.search(text): conds.append((pos, _xcond_ranges(raw)))
        elif pos: cells[pos] = (number, False, False, held)
        el.clear()
    return cells, sums, formulas, conds


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


def xlsx_scan(path):
    """What is wrong in one workbook, as [(kind, count, [(sheet number, sheet name, cell, saved, recalculated)])], or [] when it looks sound,
    is too big, unreadable or slow. Only reads the file."""
    deadline = time.monotonic() + XLSX_SECONDS; budget = [XLSX_UNPACKED]
    found = {k: [] for k in _XKINDS}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)  # a pipe put in the file's place does not hold the check up
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > XLSX_MAX_BYTES: return []
            knowledge_zip_precheck(handle)  # #240: before zipfile reads its directory
            with _xzip.ZipFile(handle) as z:
                books, pending = {}, []  # every sheet's cells by its name, for ranges on another sheet (#347)
                for index, (name, part) in enumerate(_xsheets(z, deadline, budget)[:XLSX_SHEETS]):
                    try: z.getinfo(part)
                    except KeyError: continue
                    cells, sums, formulas, conds = _xread_sheet(z, part, deadline, budget)
                    books.setdefault(name.upper(), cells); pending += [(index, name, pos, calls) for pos, calls in conds if pos]
                    at = lambda pos, saved=None, redo=None: (index + 1, name, _xname(pos) if pos else '', saved, redo)
                    for pos, text, number, saved, kind, fixed in formulas:
                        if time.monotonic() > deadline: raise _XSlow()
                        if fixed and pos: found['fixed'].append(at(pos))
                        if saved is None or (saved == '' and kind != 'str'): found['missing'].append(at(pos))
                        elif kind == 'e': found['error'].append(at(pos, saved if _XERROR.match(saved) else None))
                        if text and _XBROKEN.search(text): found['broken'].append(at(pos))
                        if not text or not pos or pos not in sums: continue
                        stacked = _xstacked(cells, sums, pos)
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
                        if stacked: found['double'].append(at(pos, number if off else None, redo if off else None))
                        elif off: found['wrong'].append(at(pos, number, redo))
                seen = {}  # the same range in many formulas is walked once
                for index, name, pos, calls in pending:
                    for ranges in calls:
                        keys = [((sheet if sheet is not None else name).upper(), first, last) for sheet, first, last in ranges]
                        if any(k[0] not in books for k in keys): continue  # a sheet this workbook does not have (or one not read): cannot tell
                        walked = []
                        for k in keys:
                            cols = tuple(sorted({c for s, f, l in keys if s == k[0] for c in range(f[1], min(l[1], f[1] + _XSHORT_COLS) + 1)}))
                            if (k, cols) not in seen: seen[k, cols] = _xpast(books[k[0]], k[1], k[2], deadline, cols)
                            walked.append((seen[k, cols], k[2][0]))
                        past, end = max(walked)  # any range short (the sum or a condition): rows are missed
                        if past: found['short'].append((index + 1, name, _xname(pos), end, end + past)); break
    except (_XSlow, _xzip.BadZipFile, _xzlib.error, KeyError, OSError, ValueError, LookupError, RuntimeError, EOFError,
            NotImplementedError, OverflowError, RecursionError, UnicodeError):
        return []
    return [(k, len(found[k]), found[k][:3]) for k in _XKINDS if found[k]]


def _xstacked(cells, sums, pos):
    """A SUM whose references take in a subtotal and also cells with values that subtotal already added."""
    outer = sums[pos]
    for o in outer:
        for p, x in _xinside(cells, *o):
            if p == pos or not x[1]: continue
            for inner in sums.get(p, ()):
                for o2 in outer:
                    if not _xoverlap(inner, o2): continue
                    both = ((max(inner[0][0], o2[0][0]), max(inner[0][1], o2[0][1])), (min(inner[1][0], o2[1][0]), min(inner[1][1], o2[1][1])))
                    if any(q not in (pos, p) and y[0] is not None for q, y in _xinside(cells, *both)): return True
    return False


_XKINDS = ('missing', 'double', 'wrong', 'broken', 'error', 'fixed', 'short')


def xlsx_render(scan, for_bot=False):
    """Plain sentences from xlsx_scan. for_bot: sheets by their place (第 2 張工作表), never words from the file; anything not made here is dropped."""
    out = []
    for item in scan if isinstance(scan, list) else []:
        if not isinstance(item, (list, tuple)) or len(item) != 3 or item[0] not in _XKINDS or not isinstance(item[1], int) or not isinstance(item[2], list): continue
        kind, count, places = item; shown = []
        for p in places[:3]:
            if not isinstance(p, (list, tuple)) or len(p) != 5 or not isinstance(p[0], int) or not _XCELL.match(str(p[2])): continue
            sheet = '第 %d 張工作表' % p[0] if for_bot else str(p[1])
            line = '%s!%s' % (sheet, p[2])
            nums = [x for x in p[3:5] if isinstance(x, (int, float)) and not isinstance(x, bool) and _xmath.isfinite(x)]
            if kind in ('double', 'wrong') and len(nums) == 2: line += '：存的是 %s，Excel 重算會是 %s' % (_xnum(nums[0]), _xnum(nums[1]))
            if kind == 'error' and not for_bot and isinstance(p[3], str) and _XERROR.match(p[3]): line += '（%s）' % p[3]
            if kind == 'short':
                if not all(isinstance(x, int) and not isinstance(x, bool) and 0 < x < 10 ** 8 for x in p[3:5]) or p[4] <= p[3]: continue
                line += '：範圍只到第 %d 列，資料到第 %d 列' % (p[3], p[4])
            shown.append(line)
        if not shown: continue
        if kind == 'missing': out.append('有 %d 格公式沒有算好的值，預覽和手機會顯示 0（例如 %s）' % (count, '、'.join(shown)))
        if kind == 'double': out.append('總計公式可能把小計重複加總（%s）' % '；'.join(shown))
        if kind == 'wrong': out.append('有 %d 格公式存的值和重算結果不符（%s）' % (count, '；'.join(shown)))
        if kind == 'broken': out.append('公式看起來不完整，可能有參照被吃掉（例如 %s）' % '、'.join(shown))
        if kind == 'error': out.append('有 %d 格公式算出錯誤（例如 %s）' % (count, '、'.join(shown)))
        if kind == 'short': out.append('有 %d 格條件加總或計數的範圍沒涵蓋到最後的資料，Excel 重算會少算（%s）%s' % (count, '；'.join(shown),
                                       '，請把範圍延伸到最後一筆資料（或用整欄，例如 $G:$G），存好後回讀公式確認' if for_bot else ''))
        if kind == 'fixed': out.append('有 %d 格公式把數字或品號直接寫在公式裡，改數量或品項不會跟著變（例如 %s）%s' % (count, '、'.join(shown),
                                       '，請把單價、折扣率等放進儲存格，公式改成引用那一格' if for_bot else ''))
    return out


def xlsx_issues(path, for_bot=False):
    return xlsx_render(xlsx_scan(path), for_bot)


def _xstamp(text):
    try: return datetime.datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError): return None


_XFILE = re.compile(r'^[\w.\- ]{1,60}\.(?:xls[xm]|pptx|pdf)$', re.IGNORECASE)


def xlsx_before_reply(store, job_id):
    """When a reply starts: the next message waits for this reply's check (xlsx_carry), and only for replies marked here."""
    with store.lock:
        job = store.find('jobs', job_id)
        if job: job['xlsxPending'] = True


def xlsx_after_reply(store, job_id):
    """After a reply: check the Excel files it saved, say what is wrong under it and keep it on the job. Never holds the lock while reading files."""
    found, decks, pdfs = [], [], []
    try:
        with store.lock:
            job = store.find('jobs', job_id)
            if not job or job.get('status') != 'completed' or job.get('plan'): return
            bot = store.find('bots', job['botId'])
            start, end = _xstamp(job.get('createdAt')), _xstamp(job.get('finishedAt'))
            if not bot or start is None or end is None: return
        books, slides, papers = [], [], []
        for item in bot_outputs(store, bot):
            lower = item['name'].lower(); deck = lower.endswith(PPTX_SUFFIXES)  # decks and PDFs are checked here too (pptxcheck.py, pdfcheck.py)
            paper = lower.endswith(PDF_SUFFIXES)
            if not deck and not paper and not lower.endswith(XLSX_SUFFIXES): continue
            chosen = slides if deck else papers if paper else books
            if len(chosen) >= (PPTX_FILES if deck else PDF_FILES if paper else XLSX_FILES): continue
            try: when = os.stat(item['path'], follow_symlinks=False).st_mtime
            except OSError: continue
            if start <= when <= end + 0.2: chosen.append(item)  # only what this reply saved: its CLI had ended by finishedAt
        stop = time.monotonic() + XLSX_WAIT / 2  # Excel first; decks only while the next reply would still hear about them
        for item in books + slides + papers:
            deck, paper = item in slides, item in papers
            if (deck or paper) and time.monotonic() > stop: break
            try: scan = pptx_scan(item['path']) if deck else pdf_scan(item['path']) if paper else xlsx_scan(item['path'])
            except Exception: continue  # one odd file never costs the others their check
            if scan: (decks if deck else pdfs if paper else found).append((item['name'], scan))
    finally:
        with store.lock:
            job = store.find('jobs', job_id)
            if job:
                job.pop('xlsxPending', None)
                if found: job['xlsxIssues'] = [dict(file=name if _XFILE.match(name) else '', scan=[[k, n, [list(p) for p in places]] for k, n, places in scan]) for name, scan in found]
                if decks: job['pptxIssues'] = [dict(file=name if _XFILE.match(name) else '', scan=[list(x) for x in scan]) for name, scan in decks]
                if pdfs: job['pdfIssues'] = [dict(file=name if _XFILE.match(name) else '', scan=[list(x) for x in scan]) for name, scan in pdfs]
                if found or decks or pdfs:
                    owner = store.find('groups', job['groupId']) if job.get('groupId') else store.find('bots', job['botId'])
                    message = find_message(owner, job.get('messageId')) if owner else None
                    shown = ['%s：%s' % (name[:80].replace('\n', ' '), '；'.join(xlsx_render([list(x) for x in scan]))) for name, scan in found]
                    shown += ['%s：%s' % (name[:80].replace('\n', ' '), '；'.join(pptx_render([list(x) for x in scan]))) for name, scan in decks]
                    shown += ['%s：%s' % (name[:80].replace('\n', ' '), '；'.join(pdf_render([list(x) for x in scan]))) for name, scan in pdfs]
                    if message: message['note'] = '；'.join(x for x in (message.get('note'), *shown) if x)
                store.save()


def _xlast(store, bot_id, chat_id, before):
    return next((j for j in reversed(store.data['jobs']) if j.get('id') != before and j.get('botId') == bot_id and j.get('chatId') == chat_id
                 and not j.get('groupId') and j.get('status') == 'completed'), None)


def xlsx_carry(store, job):
    """For a reply about to start (lock not held): what the last reply of its conversation saved wrong in Excel files, or ''.
    Waits while that reply's check is still running, so a message sent the moment it finished still hears about it."""
    if job.get('groupId') or not job.get('chatId'): return ''
    end = time.monotonic() + XLSX_WAIT
    while True:
        with store.lock:
            last = _xlast(store, job.get('botId'), job['chatId'], job.get('id'))
            if not last: return ''
            finished = _xstamp(last.get('finishedAt'))
            pending = last.get('xlsxPending') and finished is not None and time.time() - finished < XLSX_WAIT + 30  # not one left over from a restart
            issues, decks, pdfs = last.get('xlsxIssues'), last.get('pptxIssues'), last.get('pdfIssues')
        if not pending or time.monotonic() > end: break
        time.sleep(0.1)
    lines = []
    for f in issues if isinstance(issues, list) else []:
        if not isinstance(f, dict): continue
        said = xlsx_render(f.get('scan'), for_bot=True)  # rebuilt from numbers and cell names only: nothing restored from a backup is passed on as words
        name = f.get('file') if isinstance(f.get('file'), str) and _XFILE.match(f.get('file')) else '其中一個 Excel 檔'
        if said: lines.append('%s：%s' % (name, '；'.join(said)))
    lines = lines[:XLSX_FILES]
    for f in decks if isinstance(decks, list) else []:
        if not isinstance(f, dict): continue
        said = pptx_render(f.get('scan'), for_bot=True)
        if said and len(lines) < XLSX_FILES + PPTX_FILES: lines.append('你存的簡報檔：' + '；'.join(said))  # slide numbers and counts only, no file name
    for f in pdfs if isinstance(pdfs, list) else []:
        if not isinstance(f, dict): continue
        said = pdf_render(f.get('scan'), for_bot=True)
        if said and len(lines) < XLSX_FILES + PPTX_FILES + PDF_FILES: lines.append('你存的 PDF：' + '；'.join(said))  # known kinds and counts only, no file name
    if not lines: return ''
    return ('\n（Zook 的檢查結果，不是使用者的話：你上一則回覆存的檔案有問題——%s。請在這次回覆一併修好：Excel 的公式和算好的值都要存，合計範圍不要包含小計；'
            '做不到就照實告訴使用者。）' % '；'.join(lines))
