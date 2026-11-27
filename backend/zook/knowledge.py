# 知識庫 (#84, #122, #123): reference material every Bot reads with each reply, or one Bot only. An item is text typed in the window, or a
# file whose text Zook reads out once. Loaded by backend/server.py into one shared namespace.
#
# Where things are:
#   store.data['knowledge']                  every item: title, content (the text a Bot reads), botId ('' = 所有 Bot), tags (older items; kept),
#                                            and for a file: source (its name), size, status (processing / ready / failed), error, note
#   <data folder>/knowledge/<id>/source.<ext>  the uploaded file itself (in the app: ~/Library/Application Support/swarmr/knowledge/)
# An item without status (everything from before) is plain text and ready: nothing to move.
#
# Reading a file's text uses only what macOS and Python already have:
#   .txt .md .csv …   read as text (UTF-8, UTF-16 or Big5)
#   .pdf              PDFKit, through osascript (JavaScript for Automation)
#   .docx .doc .rtf .odt  /usr/bin/textutil (after checking the file is what its name says)
#   .html .htm        Python's html.parser (textutil would open it in WebKit, which may fetch what the page links to)
#   .xlsx .xlsm .pptx  unzipped and read here (standard library)
import zipfile as _kzip
from html.parser import HTMLParser as _KHTMLParser
import xml.etree.ElementTree as _KET

KNOWLEDGE_FILES = 50                # files in the knowledge base at once
KNOWLEDGE_TEXT = 100000             # characters kept from one file (the same limit as typed text)
KNOWLEDGE_RECENT = 10               # items a Bot reads in short when nothing in the knowledge base matches its question (knowsearch.py)
KNOWLEDGE_SECONDS = 120             # reading one file's text
KNOWLEDGE_UNPACKED = 100 * 1024 * 1024  # all XML read from one .xlsx or .pptx
KNOWLEDGE_TEXT_TYPES = ('.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.log', '.yaml', '.yml', '.xml')
KNOWLEDGE_TEXTUTIL_TYPES = ('.docx', '.doc', '.rtf', '.odt')
KNOWLEDGE_HTML_TYPES = ('.html', '.htm')
KNOWLEDGE_ZIP_TYPES = ('.xlsx', '.xlsm', '.pptx')
KNOWLEDGE_TYPES = KNOWLEDGE_TEXT_TYPES + ('.pdf',) + KNOWLEDGE_TEXTUTIL_TYPES + KNOWLEDGE_HTML_TYPES + KNOWLEDGE_ZIP_TYPES
KNOWLEDGE_TYPE_WORDS = 'txt、md、csv、pdf、docx、doc、rtf、xlsx、pptx、html'
_KNOWLEDGE_PDF = '''ObjC.import('PDFKit');
function run(argv) {
  const doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  if (!doc || doc.isNil()) return 'open';
  if (doc.isLocked) return 'locked';
  const text = doc.string;
  return (text && !text.isNil() ? text : $('')).writeToFileAtomicallyEncodingError(argv[1], true, $.NSUTF8StringEncoding, null) ? 'ok' : 'write';
}'''
_knowledge_queue = queue.Queue()
_knowledge_worker = {'on': False}
_knowledge_worker_lock = threading.Lock()


class KnowledgeUnreadable(ValueError):
    """A file whose text could not be read; the message is said on its card."""


def knowledge_usable(item):
    return item.get('status', 'ready') == 'ready' and bool(item.get('content'))


def knowledge_view(store):
    """Lock held. The items as the window and the phone see them: a file's text only as a preview (it cannot be edited there)."""
    out = []
    for x in store.data['knowledge']:
        item = dict(x, status=x.get('status', 'ready'), chars=len(x.get('content') or ''))
        if x.get('source'): item['content'] = (x.get('content') or '')[:1000]
        out.append(item)
    return out


def _knowledge_folder(store, item_id):
    """<data folder>/knowledge/<id>, or None for an id Zook did not make or a knowledge folder that is a link (never followed out)."""
    root = store.dir / 'knowledge'
    if not re.fullmatch(r'[0-9a-f]{32}', str(item_id)) or root.is_symlink(): return None
    folder = root / item_id
    return None if folder.is_symlink() else folder


def knowledge_drop_file(store, item_id):
    """The uploaded file of an item that is gone (deleted here or on another Mac). Never follows a link out of the data folder."""
    folder, root = _knowledge_folder(store, item_id), store.dir / 'knowledge'
    if not folder or not folder.is_dir(): return
    shutil.rmtree(str(folder), ignore_errors=True)


def _knowledge_bot(store, body):
    if 'botId' in body and body['botId'] not in ('', None) and not store.find('bots', body['botId']): raise ValueError('找不到這個 Bot，請重新選擇「給誰用」。')


def knowledge_route(handler, store, parts, path):
    """Typed items: add, change, delete. Lock held."""
    method = handler.command
    if path == '/api/knowledge/search' and method == 'POST': return knowledge_search_route(handler, store)  # 試搜尋 (knowsearch.py)
    if path == '/api/knowledge' and method == 'POST':
        item = dict(id=ID(), title='', content='', tags=[], botId='', createdAt=NOW(), updatedAt=NOW()); body = handler.body()
        if (again := create_seen(handler, 'knowledge', body)): return handler.respond(200, dict(again, duplicate=True))
        _knowledge_bot(store, body); update(item, body, 'knowledge'); store.data['knowledge'].append(item); store.save(); knowledge_index_touch(store, item['id']); return handler.respond(201, item)
    if len(parts) == 3:
        item = store.find('knowledge', parts[2])
        if not item: return handler.error(404, '找不到知識項目。')
        if method == 'DELETE':
            store.data['knowledge'].remove(item); store.save(); knowledge_drop_file(store, item['id']); knowledge_index_touch(store, item['id'])
            return handler.respond(200, {'ok': True})
        if method == 'PATCH':
            body = handler.body()
            if item.get('source') and 'content' in body and body['content'] != item.get('content'): raise ValueError('檔案的內容不能在這裡修改；要換內容，請刪除後重新上傳。')
            _knowledge_bot(store, body); update(item, body, 'knowledge'); item['updatedAt'] = NOW(); store.save(); knowledge_index_touch(store, item['id']); return handler.respond(200, item)
    return handler.error(404, '找不到資源。')


def knowledge_upload(handler, store):
    """One file for the knowledge base, sent as the raw request body: the name in X-File-Name, the title in X-Title and who it is for in
    X-Bot-Id (both optional, URL-encoded). Answered at once with the item marked 處理中; its text is read in the background. Not under the lock."""
    try: size = int(handler.headers.get('Content-Length', '0'))
    except ValueError: size = 0
    if size <= 0: return handler.error(400, '檔案是空的。')
    if size > MAX_UPLOAD: handler.close_connection = True; return handler.error(413, '單一檔案不能超過 20 MB。')
    sent = unquote(handler.headers.get('X-File-Name', ''))
    suffix = pathlib.Path(upload_name(sent.replace('\\', '/').split('/')[-1][-20:])).suffix.lower()  # from the end of the name, before it is shortened
    name = re.sub(r'[\x7f-\x9f]+', '', upload_name(sent)) or 'file'  # the same plain name other Macs accept (sync.py)
    if suffix and not name.lower().endswith(suffix): name = name[:120 - len(suffix)] + suffix  # a long name keeps its type
    title = unquote(handler.headers.get('X-Title', '')).strip() or pathlib.Path(name).stem or name
    bot_id = unquote(handler.headers.get('X-Bot-Id', ''))
    def refuse(code, why): handler.close_connection = True; return handler.error(code, why)
    if suffix not in KNOWLEDGE_TYPES: return refuse(400, '不支援這種檔案。可以上傳：%s。' % KNOWLEDGE_TYPE_WORDS)
    if len(title) > 300: return refuse(400, '標題最多 300 字。')
    with store.lock:
        if bot_id and not store.find('bots', bot_id): return refuse(400, '找不到這個 Bot，請重新選擇「給誰用」。')
        if sum(1 for x in store.data['knowledge'] if x.get('source')) >= KNOWLEDGE_FILES: return refuse(400, '知識庫最多放 %d 個檔案，請先刪掉不用的再上傳。' % KNOWLEDGE_FILES)
    item_id = ID(); folder = _knowledge_folder(store, item_id)
    if not folder: return refuse(500, '知識庫的資料夾位置不安全，沒有上傳。')
    folder.mkdir(parents=True, mode=0o700)
    remaining = size
    with open(folder / ('source' + suffix), 'wb') as out:
        while remaining:
            chunk = handler.rfile.read(min(remaining, 1 << 20))
            if not chunk: break
            out.write(chunk); remaining -= len(chunk)
    if remaining: shutil.rmtree(str(folder), ignore_errors=True); return handler.error(400, '檔案沒有傳完整。')
    with store.lock:
        why = '這個 Bot 剛剛被刪除了，沒有上傳。請重新選擇「給誰用」。' if bot_id and not store.find('bots', bot_id) else \
              '知識庫最多放 %d 個檔案，請先刪掉不用的再上傳。' % KNOWLEDGE_FILES if sum(1 for x in store.data['knowledge'] if x.get('source')) >= KNOWLEDGE_FILES else ''
        if why: shutil.rmtree(str(folder), ignore_errors=True); return handler.error(400, why)  # never widened to every Bot; two uploads at once do not pass the limit
        item = dict(id=item_id, title=title, content='', tags=[], botId=bot_id, source=name, size=size, status='processing', createdAt=NOW(), updatedAt=NOW())
        store.data['knowledge'].append(item); store.save()
        answer = dict(item)  # #352: a copy taken now; the reader changes the stored item from another thread, maybe before this is sent
    knowledge_queue(store, item_id)
    return handler.respond(201, answer)


def knowledge_queue(store, item_id):
    _knowledge_queue.put((store, item_id))
    with _knowledge_worker_lock:
        if _knowledge_worker['on']: return
        _knowledge_worker['on'] = True
    threading.Thread(target=_knowledge_work, daemon=True).start()


def _knowledge_work():
    while True:
        try: store, item_id = _knowledge_queue.get(timeout=30)
        except queue.Empty:
            with _knowledge_worker_lock:
                if _knowledge_queue.empty(): _knowledge_worker['on'] = False; return
            continue
        try: knowledge_process(store, item_id)
        except Exception: pass  # one bad file must not stop the others


def knowledge_process(store, item_id):
    """Read one file's text and mark the item ready or failed. Runs outside the lock while reading."""
    folder = _knowledge_folder(store, item_id)
    with store.lock:
        item = store.find('knowledge', item_id)
        if not item or item.get('status') != 'processing': return
        suffix = pathlib.Path(item['source']).suffix.lower() if isinstance(item.get('source'), str) else ''
    source = folder / ('source' + suffix) if folder and suffix in KNOWLEDGE_TYPES else None
    done = {}
    try:
        if not source or not source.is_file(): raise KnowledgeUnreadable('原始檔案已經不在，請刪除後重新上傳。')
        text = knowledge_extract(source)
        long = len(text) > KNOWLEDGE_TEXT * 2
        text = '\n'.join(line.rstrip(' \t') for line in text[:KNOWLEDGE_TEXT * 2].replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '').split('\n'))
        text = re.sub(r'\n{3,}', '\n\n', text).strip()  # (a run of newlines only: linear)
        if not text: raise KnowledgeUnreadable('檔案裡讀不到文字（PDF 可能是掃描的圖片），目前只支援有文字的檔案。')
        done = dict(status='ready', content=text[:KNOWLEDGE_TEXT], error='')
        if long or len(text) > KNOWLEDGE_TEXT: done['note'] = '檔案很長，只保留前 %s 字。' % format(KNOWLEDGE_TEXT, ',')
    except KnowledgeUnreadable as exc: done = dict(status='failed', error=str(exc))
    except subprocess.TimeoutExpired: done = dict(status='failed', error='讀取超過 %d 秒，檔案可能太大或太複雜。' % KNOWLEDGE_SECONDS)
    except Exception: done = dict(status='failed', error='讀取檔案時發生錯誤，檔案可能已損壞。')
    with store.lock:
        item = store.find('knowledge', item_id)
        if not item or item.get('status') != 'processing': return  # deleted meanwhile
        item.update(done, updatedAt=NOW())
        if not item.get('error'): item.pop('error', None)
        store.save(); knowledge_index_touch(store, item_id)  # its passages are ready before the next reply (knowsearch.py)


def knowledge_start(store):
    """At start: files whose reading was cut short are read again; folders of deleted items are removed."""
    with store.lock:
        waiting = [x['id'] for x in store.data['knowledge'] if x.get('status') == 'processing']
        known = {x['id'] for x in store.data['knowledge']}
    root = store.dir / 'knowledge'
    try: folders = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and re.fullmatch(r'[0-9a-f]{32}', p.name)] if root.is_dir() and not root.is_symlink() else []
    except OSError: folders = []
    for folder in folders:
        if folder.name not in known: shutil.rmtree(str(folder), ignore_errors=True)
    for item_id in waiting: knowledge_queue(store, item_id)
    knowledge_index_warm(store)  # older items are cut into passages now, not at the first reply (knowsearch.py)


def knowledge_requeue(store):
    """After a restore: items the copy has as 處理中 are read again (or marked failed when their file is not there)."""
    for item_id in [x.get('id') for x in store.data['knowledge'] if x.get('status') == 'processing']: knowledge_queue(store, item_id)


def knowledge_extract(path):
    """The plain text of one file, or KnowledgeUnreadable with the reason in words."""
    suffix = path.suffix.lower()
    if suffix in KNOWLEDGE_TEXT_TYPES: return _knowledge_decode(path.read_bytes())
    if suffix == '.pdf': return _knowledge_pdf(path)
    if suffix in KNOWLEDGE_HTML_TYPES: return _knowledge_html(_knowledge_decode(path.read_bytes()))
    if suffix in KNOWLEDGE_TEXTUTIL_TYPES:
        with open(path, 'rb') as f: head = f.read(8)
        looks = {'.docx': head.startswith(b'PK'), '.odt': head.startswith(b'PK'), '.doc': head.startswith(b'\xd0\xcf\x11\xe0'), '.rtf': head.startswith(b'{\\rtf')}[suffix]
        if not looks: raise KnowledgeUnreadable('打不開這個檔案，可能已損壞或不是 %s 檔。' % suffix[1:].upper())  # textutil would read anything (HTML too, through WebKit)
        done = subprocess.run(['/usr/bin/textutil', '-convert', 'txt', '-stdout', '--', str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=KNOWLEDGE_SECONDS)
        if done.returncode != 0: raise KnowledgeUnreadable('打不開這個檔案，可能已損壞或不是 %s 檔。' % suffix[1:].upper())
        return done.stdout.decode('utf-8', 'replace')
    if suffix in KNOWLEDGE_ZIP_TYPES: return _knowledge_office(path, suffix)
    raise KnowledgeUnreadable('不支援這種檔案。')


def _knowledge_decode(raw):
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')): return raw.decode('utf-16', 'replace')
    for codec in ('utf-8-sig', 'cp950'):
        try: return raw.decode(codec)
        except UnicodeDecodeError: pass
    raise KnowledgeUnreadable('看不懂這個檔案的文字編碼，請另存成 UTF-8 再上傳。')


class _KnowledgeHTML(_KHTMLParser):
    SKIP = {'script', 'style', 'head', 'template', 'noscript'}
    BREAK = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'table', 'ul', 'ol'}

    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        elif tag in self.BREAK: self.parts.append('\n')
        elif tag in ('td', 'th'): self.parts.append('\t')

    def handle_endtag(self, tag):
        if tag in self.SKIP: self.skip = max(0, self.skip - 1)
        elif tag in self.BREAK: self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def _knowledge_html(text):
    page = _KnowledgeHTML(); page.feed(text); page.close()
    return '\n'.join(line.strip(' \t') for line in ''.join(page.parts).split('\n'))


def _knowledge_pdf(path):
    out = path.with_name('text.txt')
    try:
        done = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-', str(path), str(out)], input=_KNOWLEDGE_PDF.encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=KNOWLEDGE_SECONDS)
        said = done.stdout.decode('utf-8', 'replace').strip()
        if said == 'locked': raise KnowledgeUnreadable('這個 PDF 有密碼保護，請先解除密碼再上傳。')
        if said != 'ok' or not out.is_file(): raise KnowledgeUnreadable('打不開這個 PDF，可能已損壞。')
        return out.read_text(encoding='utf-8', errors='replace')
    finally:
        try: out.unlink()
        except OSError: pass


def knowledge_zip_read(book, name, budget, keep=True):
    """One part of a ZIP, unpacked here from its own stored bytes (zipfile's reader stops at the size a part claims, so a part that lies
    about its size and check would pass it), counted by what really comes out: stopped as soon as budget[0] (what is left for the whole
    file) runs out, and refused when what came out is not the size and check it claims. Only stored and deflated parts are read.
    keep=False only counts (nothing is held)."""
    import zlib as _kzlib
    too_big = lambda: KnowledgeUnreadable('檔案解開後太大，請拆成幾個檔案再上傳。')
    broken = KnowledgeUnreadable('打不開這個檔案，可能已損壞。')
    info = book.getinfo(name)
    if info.flag_bits & 0x1 or info.compress_type not in (_kzip.ZIP_STORED, _kzip.ZIP_DEFLATED): raise broken  # locked, or packed some other way
    if info.file_size > budget[0]: raise too_big()
    with open(book.filename, 'rb') as f:
        f.seek(info.header_offset); head = f.read(30)
        if len(head) != 30 or head[:4] != b'PK\x03\x04': raise broken
        f.seek(info.header_offset + 30 + int.from_bytes(head[26:28], 'little') + int.from_bytes(head[28:30], 'little'))
        raw = f.read(info.compress_size)
    if len(raw) != info.compress_size: raise broken
    unpack = _kzlib.decompressobj(-15) if info.compress_type == _kzip.ZIP_DEFLATED else None
    chunks, size, crc = [], 0, 0
    def take(chunk):
        nonlocal size, crc
        size += len(chunk); budget[0] -= len(chunk)
        if budget[0] < 0 or size > info.file_size: raise too_big() if budget[0] < 0 else broken
        crc = _kzlib.crc32(chunk, crc)
        if keep: chunks.append(chunk)
    try:
        for at in range(0, len(raw), 1 << 16):
            data = raw[at:at + (1 << 16)]
            if unpack is None: take(data); continue
            while data:
                take(unpack.decompress(data, 1 << 20)); data = unpack.unconsumed_tail
        if unpack is not None: take(unpack.flush())
    except _kzlib.error: raise broken
    if size != info.file_size or crc != info.CRC: raise broken
    return b''.join(chunks)


class _KnowledgeUnsafeXML(Exception): pass


def knowledge_safe_xml(data):
    """Parsed XML, refused when it declares a DOCTYPE or an entity (#240: entity expansion, billion laughs, could fill the memory).
    expat itself looks first, so the encoding (UTF-16 too) cannot hide it."""
    import xml.parsers.expat as _kexpat
    check = _kexpat.ParserCreate()
    def refuse(*_): raise _KnowledgeUnsafeXML()
    check.StartDoctypeDeclHandler = refuse; check.EntityDeclHandler = refuse
    try: check.Parse(data, True)
    except _KnowledgeUnsafeXML: raise KnowledgeUnreadable('這個檔案裡有不安全的 XML 設定（DOCTYPE 或實體定義），Zook 不讀。')
    except _kexpat.ExpatError: raise KnowledgeUnreadable('打不開這個檔案，可能已損壞。')
    return _KET.fromstring(data)


def _knowledge_xml(book, name, budget):
    return knowledge_safe_xml(knowledge_zip_read(book, name, budget))


def _knowledge_column(ref):
    letters = re.match(r'[A-Z]{1,3}', ref or '')
    if not letters: return None
    n = 0
    for ch in letters.group(0): n = n * 26 + ord(ch) - 64
    return n - 1


def _knowledge_office(path, suffix):
    """Slides' and sheets' text. Every piece counts against KNOWLEDGE_TEXT as it is added, so a small file cannot grow into a huge text;
    page and sheet headings alone do not count as content."""
    try: book = _kzip.ZipFile(str(path))
    except (_kzip.BadZipFile, OSError): raise KnowledgeUnreadable('打不開這個檔案，可能已損壞或不是 %s 檔。' % suffix[1:].upper())
    budget, lines, names, total, found = [KNOWLEDGE_UNPACKED], [], set(book.namelist()), [0], [False]
    def add(line, content=True):  # True: enough text
        lines.append(line); total[0] += len(line) + 1; found[0] = found[0] or content; return total[0] > KNOWLEDGE_TEXT
    result = lambda: '\n'.join(lines) if found[0] else ''
    number = lambda n: int(re.sub(r'\D', '', n.rsplit('/', 1)[-1]) or 0)
    with book:
        if suffix == '.pptx':
            ns = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
            for i, name in enumerate(sorted((n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)), key=number), 1):
                paras = [''.join(t.text or '' for t in p.iter(ns + 't')) for p in _knowledge_xml(book, name, budget).iter(ns + 'p')]
                if add('【第 %d 頁】' % i, False) or any(add(p) for p in paras if p.strip()): break
            return result()
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        shared = []
        if 'xl/sharedStrings.xml' in names:
            shared = [''.join(t.text or '' for t in si.iter(ns + 't')) for si in _knowledge_xml(book, 'xl/sharedStrings.xml', budget).iter(ns + 'si')]
        titles = {}
        try:
            rels = {r.get('Id'): r.get('Target') for r in _knowledge_xml(book, 'xl/_rels/workbook.xml.rels', budget)}
            for sheet in _knowledge_xml(book, 'xl/workbook.xml', budget).iter(ns + 'sheet'):
                target = rels.get(sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')) or ''
                titles['xl/' + target.lstrip('/').replace('xl/', '', 1)] = sheet.get('name') or ''
        except (KeyError, _KET.ParseError): pass
        sheets = [n for n in titles if n in names] or sorted((n for n in names if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', n)), key=number)
        for name in sheets:
            if add('【工作表 %s】' % (titles.get(name) or number(name)), False): break
            for row in _knowledge_xml(book, name, budget).iter(ns + 'row'):
                cells, size = [], 0
                for c in row.iter(ns + 'c'):
                    kind, value = c.get('t'), c.find(ns + 'v')
                    if kind == 'inlineStr': text = ''.join(t.text or '' for t in c.iter(ns + 't'))
                    elif value is None or value.text is None: text = ''
                    elif kind == 's':
                        try: text = shared[int(value.text)]
                        except (ValueError, IndexError): text = ''
                    else: text = value.text
                    at = _knowledge_column(c.get('r'))
                    gap = max(0, at - len(cells)) if at is not None else 0  # a skipped column stays empty, so values keep their columns
                    size += gap + len(text) + 1
                    if total[0] + size > KNOWLEDGE_TEXT: break  # counted cell by cell: one shared string used a million times stops here
                    cells.extend([''] * gap); cells.append(text)
                while cells and not cells[-1]: cells.pop()
                if cells and add('\t'.join(cells)): return result()
                if total[0] + size > KNOWLEDGE_TEXT: return result()
        return result()
