# 試算表預覽 (#320 #337⑤): an Excel file shown as real tables, one tab per sheet, read straight from the file in well under a
# second, instead of Quick Look's picture of the first sheet's first screen (often over 30 seconds, columns A–C only).
# Values are the ones Excel saved (formulas are not worked out again). Only the first SHEET_ROWS rows and SHEET_COLS columns
# of each sheet are shown. The file is read from a private copy, as data: an XML part that declares a DOCTYPE or entities is
# refused, so a crafted file cannot make Zook expand entities. Loaded by backend/server.py into one shared namespace.
import io, xml.parsers.expat
SHEET_ROWS = 300       # rows shown per sheet
SHEET_COLS = 60        # columns shown per sheet (A … BH)
SHEET_TABS = 30        # sheets shown
SHEET_TEXT = 300       # characters kept per cell
SHEET_STRINGS = 300000  # shared strings read
SHEET_XML = 60 * 1024 * 1024  # unpacked bytes read from one part at most


def keep_suffix(name, most):
    """A name cut to `most` characters, keeping its extension (.txt, .xlsx) when it has a short one (#336①)."""
    if len(name) <= most: return name
    found = re.search(r'\.[A-Za-z0-9]{1,10}$', name)
    tail = found.group() if found and len(found.group()) < most else ''
    return name[:most - len(tail)].rstrip(' .') + tail


class _SheetStop(Exception): pass


class SheetRefused(Exception): pass


def _sheet_xml(stream, start, end=None, text=None):
    """Walk one XML part with expat, calling start(name, attrs), end(name) and text(data) with names stripped of their namespace.
    A handler raises _SheetStop to finish early. A DOCTYPE or entity declaration is refused (SheetRefused)."""
    parser = xml.parsers.expat.ParserCreate(namespace_separator=' ')
    def refuse(*_): raise SheetRefused('doctype')
    parser.StartDoctypeDeclHandler = refuse; parser.EntityDeclHandler = refuse
    parser.StartElementHandler = lambda name, attrs: start(name.rsplit(' ', 1)[-1], {k.rsplit(' ', 1)[-1]: v for k, v in attrs.items()})
    if end: parser.EndElementHandler = lambda name: end(name.rsplit(' ', 1)[-1])
    if text: parser.CharacterDataHandler = text
    read = 0
    try:
        while read < SHEET_XML:
            chunk = stream.read(65536)
            if not chunk: break
            read += len(chunk); parser.Parse(chunk, False)
        if read < SHEET_XML: parser.Parse(b'', True)
    except _SheetStop: pass
    except xml.parsers.expat.ExpatError: raise SheetRefused('broken')


def _sheet_part(z, name):
    try: return z.open(name)
    except KeyError: return None


def _shared_strings(z):
    found, now, depth = [], [], {'si': 0, 'rPh': 0, 't': 0}
    def start(name, attrs):
        if name in depth: depth[name] += 1
        if name == 'si': now.clear()
    def end(name):
        if name in depth: depth[name] -= 1
        if name == 'si':
            found.append(''.join(now)[:SHEET_TEXT])
            if len(found) >= SHEET_STRINGS: raise _SheetStop()
    def text(data):
        if depth['si'] and depth['t'] and not depth['rPh']: now.append(data)  # rPh: the pronunciation guide above Japanese text
    part = _sheet_part(z, 'xl/sharedStrings.xml')
    if part:
        with part: _sheet_xml(part, start, end, text)
    return found


def _sheet_styles(z):
    """[(number format id, format code)] per cell style index."""
    codes, styles, inside = {}, [], [False]
    def start(name, attrs):
        if name == 'numFmt': codes[attrs.get('numFmtId', '')] = attrs.get('formatCode', '')
        elif name == 'cellXfs': inside[0] = True
        elif name == 'xf' and inside[0]:
            fid = attrs.get('numFmtId', '0'); styles.append((int(fid) if fid.isdigit() else 0, codes.get(fid, '')))
    def end(name):
        if name == 'cellXfs': inside[0] = False
    part = _sheet_part(z, 'xl/styles.xml')
    if part:
        with part: _sheet_xml(part, start, end)
    return styles


def _plain_code(code):
    """A number format without its quoted text, escapes and [colour] / [$-locale] parts."""
    return re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', '', code or '')


def _sheet_number(raw, style, date1904):
    try: value = float(raw)
    except ValueError: return raw
    fid, code = style
    plain = _plain_code(code).split(';')[0]; low = plain.lower()
    timed = fid in (18, 19, 20, 21, 22, 45, 46, 47) or bool(re.search(r'[hs]', low))
    dated = fid in (14, 15, 16, 17, 22) or bool(re.search(r'[yd]', low)) or ('m' in low and not timed and not re.search(r'[0#?]', low))
    if (dated or timed) and fid not in (0, 1, 2, 3, 4, 9, 10, 11, 12, 13, 37, 38, 39, 40, 48, 49) and -1 < value < 2958466:
        when = (datetime.datetime(1904, 1, 1) if date1904 else datetime.datetime(1899, 12, 30)) + datetime.timedelta(days=value)
        return ' '.join(x for x in (when.strftime('%Y-%m-%d') if dated else '', when.strftime('%H:%M') if timed else '') if x)
    places = len(re.search(r'\.(0*)', plain).group(1)) if re.search(r'\.0', plain) else 0
    if fid in (9, 10) or '%' in plain:
        return ('%.' + str(2 if fid == 10 else places) + 'f%%') % (value * 100)
    if fid in (3, 4) or ',' in plain:
        return format(value, ',.%df' % (2 if fid == 4 else places))
    if fid in (2,) or (plain and '0.' in plain): return '%.*f' % (2 if fid == 2 else places, value)
    return str(int(value)) if value == int(value) and abs(value) < 1e15 else '%.10g' % value


def _column_number(ref):
    letters = re.match(r'[A-Z]+', ref or '')
    n = 0
    for ch in (letters.group() if letters else ''): n = n * 26 + ord(ch) - 64
    return n


def _read_sheet(z, name, shared, styles, date1904):
    rows, cell, state = [], {}, {'row': 0, 'col': 0, 'more': False, 'wide': 0, 'in': None}
    def start(tag, attrs):
        if tag == 'row':
            r = attrs.get('r', '')
            state['row'] = int(r) if r.isdigit() else state['row'] + 1; state['col'] = 0
            if state['row'] > SHEET_ROWS: state['more'] = True; raise _SheetStop()
            rows.append([state['row'], []])
        elif tag == 'c' and rows:
            col = _column_number(attrs.get('r', '')) or state['col'] + 1; state['col'] = col
            s = attrs.get('s', '0')
            cell.clear(); cell.update(col=col, t=attrs.get('t', 'n'), s=int(s) if s.isdigit() else 0, v=[], text=[])
        elif tag in ('v', 'is') and cell: state['in'] = tag
    def end(tag):
        if tag in ('v', 'is'): state['in'] = None
        elif tag == 'c' and cell and rows:
            col, kind, raw = cell['col'], cell['t'], ''.join(cell['v']).strip()
            if kind == 's': value = shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ''
            elif kind == 'inlineStr': value = ''.join(cell['text'])
            elif kind == 'b': value = 'TRUE' if raw == '1' else 'FALSE'
            elif kind in ('str', 'e'): value = ''.join(cell['v'])
            else: value = _sheet_number(raw, styles[cell['s']] if cell['s'] < len(styles) else (0, ''), date1904) if raw else ''
            if col > SHEET_COLS: state['wide'] = max(state['wide'], col)
            elif value != '':
                line = rows[-1][1]
                line.extend([''] * (col - len(line))); line[col - 1] = str(value)[:SHEET_TEXT]
            cell.clear()
    def text(data):
        if state['in'] == 'v': cell['v'].append(data)
        elif state['in'] == 'is': cell['text'].append(data)
    part = _sheet_part(z, name)
    if part:
        with part: _sheet_xml(part, start, end, text)
    rows = [r for r in rows if r[1]]
    return dict(rows=rows, cols=max([len(r[1]) for r in rows] or [0]), more=state['more'], wide=state['wide'] > SHEET_COLS)


def sheet_tables(data):
    """{'sheets': [{'name', 'rows': [[row number, [cell text, …]]], 'cols', 'more', 'wide'}], 'charts': bool} for an .xlsx file's bytes."""
    try: z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError): raise SheetRefused('not a zip')
    with z:
        parts = z.infolist()
        if len(parts) > 5000 or sum(p.file_size for p in parts) > PREVIEW_UNPACKED: raise SheetRefused('too big')
        names = set(z.namelist())
        targets, listed, flags = {}, [], {'date1904': False}
        def rel(tag, attrs):
            if tag == 'Relationship': targets[attrs.get('Id', '')] = attrs.get('Target', '')
        def book(tag, attrs):
            if tag == 'sheet' and attrs.get('state', 'visible') == 'visible': listed.append((attrs.get('name', ''), attrs.get('id', '')))
            elif tag == 'workbookPr' and attrs.get('date1904') in ('1', 'true'): flags['date1904'] = True
        for part_name, walk in (('xl/_rels/workbook.xml.rels', rel), ('xl/workbook.xml', book)):
            part = _sheet_part(z, part_name)
            if part is None: raise SheetRefused('no workbook')
            with part: _sheet_xml(part, walk)
        shared, styles, sheets = _shared_strings(z), _sheet_styles(z), []
        for title, rid in listed[:SHEET_TABS]:
            target = targets.get(rid, '')
            target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            target = os.path.normpath(target)
            if target not in names: continue
            sheets.append(dict(name=title[:100] or '工作表', **_read_sheet(z, target, shared, styles, flags['date1904'])))
        return dict(sheets=sheets, more=len(listed) > SHEET_TABS, charts=any(n.startswith('xl/charts/chart') for n in names))


def sheet_preview(path, strict=False):
    """The tables of one .xlsx the caller already found shareable, or {'status': 'failed', 'reason': …}."""
    if pathlib.Path(path).suffix.lower() != '.xlsx': raise OSError('not a sheet')
    fd, _, info = _preview_open(path, strict)
    try:
        if info.st_size > MAX_UPLOAD: return dict(status='failed', reason='這個檔案超過 20 MB，無法在 Zook 裡預覽，請在 Finder 開啟。')
        with os.fdopen(os.dup(fd), 'rb') as f: data = f.read(MAX_UPLOAD + 1)
    finally: os.close(fd)
    try: return dict(status='ready', **sheet_tables(data))
    except (SheetRefused, KeyError, ValueError, zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
        return dict(status='failed', reason='這份試算表打不開，可能已損壞或用了特殊格式。可以下載後用 Excel 或 Numbers 開啟。')
