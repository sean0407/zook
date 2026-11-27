# PDF 檢查 (#65): a Chinese PDF that looks garbled elsewhere. Two things a plain reader can be sure of: a CID (CJK) font that is not embedded
# (fine on this Mac, garbled or blank on another computer or a phone), and reportlab's stand-in for characters its font lacks
# (ZapfDingbats 'n', black squares where the Chinese should be). Anything else is left to the delivery rule (turn the pages into pictures).
# Runs with the Excel check after a reply (xlsx_after_reply), read only, with size, unpacked-size and time caps. Loaded by backend/server.py.

PDF_SUFFIXES = ('.pdf',)
PDF_FILES = 3  # PDFs looked at per reply
PDF_UNPACKED = 64 * 1024 * 1024  # all streams inflated from one file
PDF_STREAMS = 5000
_PDF_OBJ = re.compile(rb'(\d{1,10})\s+\d{1,5}\s+obj\b')
_PDF_CID = re.compile(rb'/Subtype\s*/CIDFontType[02]\b')
_PDF_BOXES = re.compile(rb'/([^\s/<>\[\]()]+)\s+[\d.]+\s+Tf|\((n+)\)\s*Tj')  # font changes and runs of 'n'
PDF_OBJSTM = 100000  # objects read from one object stream
_PDF_ZAPF = re.compile(rb'/BaseFont\s*/ZapfDingbats\b')
_PDF_EMBEDDED = re.compile(rb'/FontFile[23]?\b')
_PDF_FONTS = {'boxes', 'cid', 'tiny'}
# #101⑧ #211: chart labels and table text drawn too small to read. The size is the font size times the text matrix's scale (Chrome writes
# 1 Tf with a 12-times Tm; only its vertical part); a few such runs are said, one footnote is not. A page-wide scale (cm) is not followed. Pictures of charts (PNG inside the PDF) cannot be read this way.
_PDF_TEXT = re.compile(rb'(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+-?[\d.]+\s+-?[\d.]+\s+Tm\b|/[^\s/<>\[\]()]+\s+(-?[\d.]+)\s+Tf\b|\b(BT)\b|[)\]>]\s*(?:Tj|TJ|\'|")')
PDF_TINY_PT = 6
PDF_TINY_RUNS = 3
# #211 #101①④⑧: a PDF said to be checked had a blank cover, small chart labels and a header column gone. Looked at as pictures, every time.
FILE_DELIVERY_NOTE += ('PDF 交件前和每次改版後都用上面的轉圖指令逐頁看過再交：封面或中間頁不要留大片空白（轉圖結果會列出空白過多的頁），'
                       '圖表的標籤和數字字級至少 8 pt，表格表頭和下面的欄位對齊、標籤欄沒有消失；說看過版面，就要真的轉過圖。')


def _pdf_tiny(streams, deadline):
    """How many text runs are drawn smaller than PDF_TINY_PT points."""
    tiny = 0
    for s in streams:
        if time.monotonic() > deadline: raise _XSlow()
        size, scale = None, 1.0
        for m in _PDF_TEXT.finditer(s):
            try:
                if m.group(1) is not None: c, d = float(m.group(3)), float(m.group(4)); scale = (c * c + d * d) ** 0.5  # the height of a letter: text narrowed sideways is not smaller
                elif m.group(5) is not None: size = float(m.group(5))
                elif m.group(6): scale = 1.0  # a new text object starts from the plain matrix; the font stays
                elif size is not None and 0 < size * scale < PDF_TINY_PT: tiny += 1
            except ValueError: continue
    return tiny


def _pdf_ref(body, key):
    m = re.search(rb'/' + key + rb'\s+(\d{1,10})\s+\d{1,5}\s+R', body)
    return int(m.group(1)) if m else None


def _pdf_inflate(raw, deadline, budget):
    out, z = [], _xzlib.decompressobj()
    data = raw
    while data:
        if time.monotonic() > deadline: raise _XSlow()
        chunk = z.decompress(data, 1024 * 1024); budget[0] -= len(chunk)
        if budget[0] < 0: raise _XSlow()
        out.append(chunk); data = z.unconsumed_tail
    return b''.join(out)


def _pdf_objects(data, deadline, budget):
    """({object number: dictionary bytes}, [inflated page and form streams]). Object streams are opened; images and font files are not."""
    objs, streams, pos, count = {}, [], 0, 0
    while True:
        m = _PDF_OBJ.search(data, pos)
        if not m: break
        count += 1
        if count % 500 == 0 and time.monotonic() > deadline: raise _XSlow()
        start = m.end(); end = data.find(b'endobj', start); end = end if end >= 0 else len(data)
        body = data[start:end]; pos = end + 6  # never look for objects inside this one's stream
        at = body.find(b'stream')
        if at < 0: objs[int(m.group(1))] = body; continue
        head, raw = body[:at], body[at + 6:]
        raw = raw[2:] if raw[:2] == b'\r\n' else raw[1:] if raw[:1] in (b'\r', b'\n') else raw
        tail = raw.rfind(b'endstream'); raw = raw[:tail] if tail >= 0 else raw
        objs[int(m.group(1))] = head
        sub = re.search(rb'/Subtype\s*/(\w+)', head)
        if (sub and sub.group(1) != b'Form') or b'/Length1' in head or b'/Length2' in head: continue  # images, font files
        if len(streams) >= PDF_STREAMS: continue
        filters = re.findall(rb'/(\w+Decode)\b', head); content = raw
        if any(f not in (b'ASCII85Decode', b'FlateDecode') for f in filters): continue
        try:
            for f in filters:  # reportlab writes [/ASCII85Decode /FlateDecode] by default
                if f == b'FlateDecode': content = _pdf_inflate(content, deadline, budget)
                else:
                    text = re.sub(rb'\s+', b'', content); text = text[2:] if text.startswith(b'<~') else text
                    content = base64.a85decode(text[:-2] if text.endswith(b'~>') else text)
        except (_xzlib.error, ValueError): continue
        if re.search(rb'/Type\s*/ObjStm\b', head):
            first = re.search(rb'/First\s+(\d{1,10})', head)
            if not first: continue
            first = int(first.group(1)); count_n = re.search(rb'/N\s+(\d{1,10})', head)
            if first > len(content) or not count_n: continue
            numbers = content[:first].split(None, 2 * min(int(count_n.group(1)), PDF_OBJSTM))[:2 * PDF_OBJSTM]
            if time.monotonic() > deadline: raise _XSlow()
            pairs = [(int(numbers[i]), int(numbers[i + 1])) for i in range(0, len(numbers) - 1, 2) if numbers[i].isdigit() and numbers[i + 1].isdigit()]
            for i, (n, off) in enumerate(pairs):
                stop = pairs[i + 1][1] if i + 1 < len(pairs) else len(content) - first
                objs.setdefault(n, content[first + off:first + stop])
        else: streams.append(content)
    return objs, streams


def pdf_scan(path):
    """[[kind, count]] for what makes the PDF look garbled: 'cid' (CJK fonts not embedded), 'boxes' (characters drawn as black squares);
    [] when sound, too big, unreadable or slow. Only reads the file."""
    deadline = time.monotonic() + XLSX_SECONDS; budget = [PDF_UNPACKED]; found = []
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > XLSX_MAX_BYTES: return []
            data = handle.read(XLSX_MAX_BYTES + 1)
        if not data.startswith(b'%PDF-'): return []
        objs, streams = _pdf_objects(data, deadline, budget)
        bare = set()
        for n, body in objs.items():
            if not _PDF_CID.search(body): continue
            if re.search(rb'/FontDescriptor\s*<<', body): embedded = bool(_PDF_EMBEDDED.search(body))
            else:
                ref = _pdf_ref(body, b'FontDescriptor')
                if ref is None or ref not in objs: continue  # cannot tell: say nothing
                embedded = bool(_PDF_EMBEDDED.search(objs[ref]))
            if not embedded:
                name = re.search(rb'/BaseFont\s*/([^\s/<>\[\]()]+)', body); bare.add(name.group(1) if name else n)
        if bare: found.append(['cid', len(bare)])
        zapf = {n for n, b in objs.items() if _PDF_ZAPF.search(b)}
        if b'ReportLab' in data and zapf:
            names = {m.group(1) for n in zapf for m in re.finditer(rb'/Name\s*/([^\s/<>\[\]()]+)', objs[n])}  # the resource names pointing at it
            refs = re.compile(rb'/([^\s/<>\[\]()]+)\s+(\d{1,10})\s+\d{1,5}\s+R')
            names |= {m.group(1) for b in objs.values() if b'/Font' in b for m in refs.finditer(b) if int(m.group(2)) in zapf}
            boxes = 0
            for s in streams:  # only 'n' drawn while ZapfDingbats is the font: a plain "n" in a table is not a box
                font = None
                for m in _PDF_BOXES.finditer(s):
                    if m.group(1) is not None: font = m.group(1)
                    elif font in names: boxes += len(m.group(2))
            if boxes: found.append(['boxes', boxes])
        tiny = _pdf_tiny(streams, deadline)
        if tiny >= PDF_TINY_RUNS: found.append(['tiny', tiny])
    except (_XSlow, _xzlib.error, OSError, ValueError, LookupError, RuntimeError, MemoryError, OverflowError, RecursionError):
        return []
    return found


def pdf_render(scan, for_bot=False):
    """Plain sentences from pdf_scan, rebuilt from known kinds and counts only (a restored backup passes nothing else on)."""
    kinds = {x[0]: x[1] for x in scan if isinstance(x, (list, tuple)) and len(x) == 2 and x[0] in _PDF_FONTS
             and isinstance(x[1], int) and not isinstance(x[1], bool) and x[1] > 0} if isinstance(scan, list) else {}
    lines = []
    if 'boxes' in kinds: lines.append('有 %d 個字顯示成黑色方塊（中文用了沒有中文字的字型），打開就是亂碼' % kinds['boxes'])
    if 'cid' in kinds: lines.append('中文字型沒有內嵌在檔案裡，換一台電腦或在手機上打開可能變成亂碼或空白')
    if lines and for_bot: lines[-1] += '。請改用內嵌的中文字型重新產生（例如 reportlab 用 TTFont 註冊 .ttf 中文字型檔，不用 Helvetica 或 UnicodeCIDFont），存好後轉圖看過沒有亂碼'
    if 'tiny' in kinds: lines.append('有 %d 段文字小於 %d pt（例如圖表標籤），印出來或在手機上看不清楚%s' % (kinds['tiny'], PDF_TINY_PT,
                                     '。請把圖表標籤和表格文字放大到至少 8 pt，存好後轉圖確認看得清楚' if for_bot else ''))
    return lines


def pdf_issues(path, for_bot=False):
    return pdf_render(pdf_scan(path), for_bot)
