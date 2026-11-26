# -*- coding: utf-8 -*-
"""Every page of a PDF or a PowerPoint deck as a PNG, without opening any app window.

Bots run this to look at what they made: `/usr/bin/python3 pagepics.py <file> <out folder>`.
PDF pages are drawn with macOS CoreGraphics (standard library only, through ctypes); each slide of a .pptx is cut into
a one-slide copy that Quick Look (qlmanage, no window) turns into a picture; a .docx is laid out on A4 pages by macOS's text
system and drawn like a PDF. Other formats get Quick Look's first page.
It prints each picture and the page size with its ratio (16:9 slides should say 16:9), and leaves no other files behind:
the one-slide copies sit in a hidden folder inside the output folder (the Bot's own scratch folder), removed on exit and on SIGTERM.
Pages that could not be pictured are listed and the exit code is 1, so no page goes unchecked.
"""
import ctypes, ctypes.util, os, re, shutil, signal, subprocess, sys, tempfile, threading, time, zipfile

# PresentationML, transitional and strict: the prefix bound to it is whatever the file chose (p:, ps:, or the default namespace).
PML = ('http://schemas.openxmlformats.org/presentationml/2006/main', 'http://purl.oclc.org/ooxml/presentationml/main')


MOST = [0]      # --pages N: picture only the first N pages (Zook's preview); 0 is every page
SKIPPED = [0]   # pages left out by --pages
_children = []  # Quick Look or osascript running now: ended with pagepics


def _run(command, timeout=120):
    """One helper program in its own group, ended (with whatever it started) on time-out or when pagepics is stopped."""
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    _children.append(proc)
    try: proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired: _end(proc)
    finally:
        if proc in _children: _children.remove(proc)


def _end(proc):
    try: os.killpg(proc.pid, signal.SIGKILL)
    except OSError: pass
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired: pass


def _first(count):
    """How many of count pages to picture."""
    if MOST[0] and count > MOST[0]: SKIPPED[0] = count - MOST[0]; return MOST[0]
    return count


class _Rect(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double), ('w', ctypes.c_double), ('h', ctypes.c_double)]


def ratio(w, h):
    """'16:9', '4:3', 'A4 直式' … or the plain numbers."""
    if not w or not h: return '?'
    r = w / h
    for name, value in (('16:9', 16 / 9), ('16:10', 1.6), ('4:3', 4 / 3), ('A4 直式', 210 / 297), ('A4 橫式', 297 / 210), ('Letter 直式', 8.5 / 11), ('1:1', 1.0)):
        if abs(r - value) < 0.01: return name
    return '%.3f:1' % r


def pdf_pages(path, out, width=1600):
    """Every page drawn on white at `width` pixels. Returns ([(png, w, h)] in PDF points, [pages not written])."""
    cg = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cf = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    io = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/ImageIO.framework/ImageIO')
    vp, sz, db = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_double
    for f, res, args in ((cf.CFURLCreateFromFileSystemRepresentation, vp, [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]),
                         (cf.CFStringCreateWithCString, vp, [vp, ctypes.c_char_p, ctypes.c_uint32]), (cf.CFRelease, None, [vp]),
                         (cg.CGPDFDocumentCreateWithURL, vp, [vp]), (cg.CGPDFDocumentGetNumberOfPages, sz, [vp]),
                         (cg.CGPDFDocumentGetPage, vp, [vp, sz]), (cg.CGPDFPageGetBoxRect, _Rect, [vp, ctypes.c_int]),
                         (cg.CGPDFPageGetRotationAngle, ctypes.c_int, [vp]), (cg.CGPDFDocumentRelease, None, [vp]),
                         (cg.CGColorSpaceCreateDeviceRGB, vp, []), (cg.CGColorSpaceRelease, None, [vp]),
                         (cg.CGBitmapContextCreate, vp, [vp, sz, sz, sz, sz, vp, ctypes.c_uint32]),
                         (cg.CGContextSetRGBFillColor, None, [vp, db, db, db, db]), (cg.CGContextFillRect, None, [vp, _Rect]),
                         (cg.CGContextScaleCTM, None, [vp, db, db]), (cg.CGContextTranslateCTM, None, [vp, db, db]),
                         (cg.CGContextRotateCTM, None, [vp, db]), (cg.CGContextDrawPDFPage, None, [vp, vp]),
                         (cg.CGBitmapContextCreateImage, vp, [vp]), (cg.CGContextRelease, None, [vp]), (cg.CGImageRelease, None, [vp]),
                         (io.CGImageDestinationCreateWithURL, vp, [vp, vp, sz, vp]), (io.CGImageDestinationAddImage, None, [vp, vp, vp]),
                         (io.CGImageDestinationFinalize, ctypes.c_bool, [vp])):
        f.restype, f.argtypes = res, args
    url = lambda p: cf.CFURLCreateFromFileSystemRepresentation(None, p.encode('utf-8'), len(p.encode('utf-8')), False)
    src = url(os.path.abspath(path))
    doc = cg.CGPDFDocumentCreateWithURL(src); cf.CFRelease(src)
    if not doc: raise SystemExit('讀不到這個 PDF：%s' % path)
    png_type, space, done, missing = cf.CFStringCreateWithCString(None, b'public.png', 0x08000100), cg.CGColorSpaceCreateDeviceRGB(), [], []
    stem = os.path.splitext(os.path.basename(path))[0]
    for n in range(1, _first(cg.CGPDFDocumentGetNumberOfPages(doc)) + 1):
        page = cg.CGPDFDocumentGetPage(doc, n)
        box, turn = cg.CGPDFPageGetBoxRect(page, 1), cg.CGPDFPageGetRotationAngle(page) % 360  # 1 = crop box
        w, h = (box.h, box.w) if turn in (90, 270) else (box.w, box.h)
        scale = width / w
        pw, ph = int(round(w * scale)), int(round(h * scale))
        ctx = cg.CGBitmapContextCreate(None, pw, ph, 8, 0, space, 1)  # premultiplied last
        cg.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1); cg.CGContextFillRect(ctx, _Rect(0, 0, pw, ph))
        cg.CGContextScaleCTM(ctx, scale, scale)
        if turn: cg.CGContextTranslateCTM(ctx, w / 2, h / 2); cg.CGContextRotateCTM(ctx, -turn * 3.141592653589793 / 180); cg.CGContextTranslateCTM(ctx, -box.w / 2, -box.h / 2)
        cg.CGContextTranslateCTM(ctx, -box.x, -box.y)
        cg.CGContextDrawPDFPage(ctx, page)
        image = cg.CGBitmapContextCreateImage(ctx)
        target = os.path.join(out, '%s-%02d.png' % (stem, n))
        dest_url = url(target); dest = io.CGImageDestinationCreateWithURL(dest_url, png_type, 1, None) if image else None
        written = False
        if dest: io.CGImageDestinationAddImage(dest, image, None); written = io.CGImageDestinationFinalize(dest); cf.CFRelease(dest)  # false: e.g. the disk is full
        cf.CFRelease(dest_url)
        if image: cg.CGImageRelease(image)
        if ctx: cg.CGContextRelease(ctx)
        if written: done.append((target, w, h))
        else:
            missing.append(n)
            try: os.remove(target)  # a half-written picture is not a page
            except OSError: pass
    cg.CGColorSpaceRelease(space); cf.CFRelease(png_type); cg.CGPDFDocumentRelease(doc)
    return done, missing


def quicklook(path, out, width=1600):
    """Quick Look's picture of the file's first page (no window). Returns the PNG or None."""
    _run(['/usr/bin/qlmanage', '-t', '-s', str(width), '-o', out, path])
    made = os.path.join(out, os.path.basename(path) + '.png')
    return made if os.path.exists(made) else None


def pptx_pages(path, out, width=1600):
    """One-slide copies of the deck, each pictured by Quick Look. Returns ([(png, w, h)] in EMU, [slides not pictured])."""
    with zipfile.ZipFile(path) as z:
        pres = z.read('ppt/presentation.xml').decode('utf-8')
        names = z.namelist()
        parts = {n: z.read(n) for n in names}
    p = re.escape(pml_prefix(pres))
    size = re.search(r'<%ssldSz\b[^>]*?\bcx="(\d+)"[^>]*?\bcy="(\d+)"' % p, pres)
    w, h = (int(size.group(1)), int(size.group(2))) if size else (0, 0)
    listed = re.search(r'(<%ssldIdLst\b[^>]*>)(.*?)(</%ssldIdLst\s*>)' % (p, p), pres, flags=re.S)
    ids = re.findall(r'<%ssldId\b[^>]*?(?:/>|>.*?</%ssldId\s*>)' % (p, p), listed.group(2), flags=re.S) if listed else []
    stem, done, missing = os.path.splitext(os.path.basename(path))[0], [], []
    work = tempfile.mkdtemp(prefix='.zook-pagepics-', dir=out)  # inside the scratch folder: cleaning that up removes it too
    try:
        for n, keep in enumerate(ids[:_first(len(ids))], 1):
            one = pres[:listed.start()] + listed.group(1) + keep + listed.group(3) + pres[listed.end():]
            copy = os.path.join(work, '%s-%02d.pptx' % (stem, n))
            with zipfile.ZipFile(copy, 'w', zipfile.ZIP_DEFLATED) as z:
                for name in names: z.writestr(name, one.encode('utf-8') if name == 'ppt/presentation.xml' else parts[name])
            made = quicklook(copy, work, width)
            os.remove(copy)  # each one-slide copy holds the whole deck: never keep them all at once
            if made:
                target = os.path.join(out, '%s-%02d.png' % (stem, n)); shutil.move(made, target); done.append((target, w, h))
            else: missing.append(n)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return done, missing


# A Word file's text laid out on A4 pages by macOS's own text system (no app window), saved as PDFs. Quick Look only pictures
# the first page of a .docx; this gives every page. macOS's reader drops Word's page breaks (#338), so a copy marks each one
# with PAGE_MARK first and the text is laid out in pieces cut there, each piece starting a new page. Pictures inside the
# document may be left out: it is a preview, not the file.
PAGE_MARK = 'ZOOKPAGEBREAK7F3A'
DOCX_TO_PDF = '''ObjC.import('AppKit');
function layout(text, path) {
  var info = $.NSPrintInfo.sharedPrintInfo.copy;
  info.paperSize = $.NSMakeSize(595, 842); info.topMargin = 56; info.bottomMargin = 56; info.leftMargin = 56; info.rightMargin = 56;
  info.horizontalPagination = $.NSFitPagination; info.verticalPagination = $.NSAutoPagination; info.jobDisposition = $.NSPrintSaveJob;
  info.dictionary.setObjectForKey($.NSURL.fileURLWithPath(path), $.NSPrintJobSavingURL);
  var view = $.NSTextView.alloc.initWithFrame($.NSMakeRect(0, 0, 483, 730));
  view.textStorage.setAttributedString(text);
  var job = $.NSPrintOperation.printOperationWithViewPrintInfo(view, info);
  job.showsPrintPanel = false; job.showsProgressPanel = false;
  return job.runOperation;
}
function run(argv) {
  var text = $.NSAttributedString.alloc.initWithURLOptionsDocumentAttributesError($.NSURL.fileURLWithPath(argv[0]), $({}), null, null);
  if (!text || text.isNil()) return 'unreadable';
  var plain = text.string.js, mark = argv[2], cuts = [], at = 0, from = 0, n = 0;
  while ((at = plain.indexOf(mark, at)) >= 0) { cuts.push(at); at += mark.length; }
  cuts.push(plain.length);
  for (var i = 0; i < cuts.length && i < 2000; i++) {
    var start = from, end = cuts[i]; from = end + mark.length;
    while (start < end && plain[start] === '\\n') start++;
    if (start >= end && i > 0 && i === cuts.length - 1) break;  // nothing after the last break
    if (!layout(text.attributedSubstringFromRange($.NSMakeRange(start, Math.max(0, end - start))), argv[1] + '-' + (++n) + '.pdf')) return 'failed';
  }
  return 'ok';
}'''


def mark_page_breaks(xml):
    """word/document.xml with each page break (a break run, a paragraph set to start a new page, a section that starts on a new
    page) written as PAGE_MARK text, which macOS's reader keeps. One pass over the paragraphs with plain searches: a malformed
    file cannot make it slow."""
    run = '<w:r><w:t>%s</w:t></w:r>' % PAGE_MARK
    xml = re.sub(r'<w:br\b[^>]*?\bw:type="page"[^>]*/>', '<w:t>%s</w:t>' % PAGE_MARK, xml)
    out = []
    for part in xml.split('</w:p>'):
        start = part.find('<w:pPr>'); end = part.find('</w:pPr>', start) if start >= 0 else -1
        props = part[start:end] if 0 <= start < end else ''
        if props and re.search(r'<w:pageBreakBefore\b(?![^>]*w:val="(?:0|false|off)")', props):
            part = part[:end + 8] + run + part[end + 8:]
        if props and '<w:sectPr' in props and 'w:val="continuous"' not in props: part += run
        out.append(part)
    return '</w:p>'.join(out)


def docx_pages(path, out, width=1600):
    """Every page of a Word file: laid out as PDFs by macOS, then drawn like any PDF. Returns ([(png, w, h)], [pages not written])."""
    work = tempfile.mkdtemp(prefix='.zook-pagepics-', dir=out)
    try:
        stem = os.path.splitext(os.path.basename(path))[0]
        script, marked = os.path.join(work, 'layout.js'), os.path.join(work, 'marked.docx')
        with open(script, 'w', encoding='utf-8') as f: f.write(DOCX_TO_PDF)
        try:
            with zipfile.ZipFile(path) as z, zipfile.ZipFile(marked, 'w', zipfile.ZIP_DEFLATED) as copy:
                for item in z.infolist():
                    data = z.read(item)
                    if item.filename == 'word/document.xml': data = mark_page_breaks(data.decode('utf-8')).encode('utf-8')
                    copy.writestr(item.filename, data)
        except (OSError, ValueError, zipfile.BadZipFile, UnicodeDecodeError): marked = os.path.abspath(path)
        _run(['/usr/bin/osascript', '-l', 'JavaScript', script, marked, os.path.join(work, 'part'), PAGE_MARK])
        parts = sorted((n for n in os.listdir(work) if re.fullmatch(r'part-\d+\.pdf', n)), key=lambda n: int(n[5:-4]))
        done, missing, most = [], [], MOST[0]
        for i, name in enumerate(parts):
            if most and len(done) >= most: SKIPPED[0] = max(SKIPPED[0], len(parts) - i); break
            MOST[0] = most - len(done) if most else 0
            try: made, lost = pdf_pages(os.path.join(work, name), work, width)
            except SystemExit: continue  # an unreadable piece
            for target, w, h in made:
                final = os.path.join(out, '%s-%02d.png' % (stem, len(done) + len(missing) + 1)); shutil.move(target, final); done.append((final, w, h))
            for _ in lost: missing.append(len(done) + len(missing) + 1)
        MOST[0] = most
        if most and len(done) >= most and SKIPPED[0]: SKIPPED[0] = max(SKIPPED[0], 1)
        return done, missing
    finally:
        shutil.rmtree(work, ignore_errors=True)


def pml_prefix(xml):
    """'p:' or whatever prefix (or '' for the default namespace) the file bound to PresentationML."""
    for found in re.finditer(r'\bxmlns(?::([A-Za-z_][\w.-]*))?\s*=\s*["\']([^"\']*)["\']', xml):
        if found.group(2) in PML: return found.group(1) + ':' if found.group(1) else ''
    return 'p:'


def _orphaned(parent):
    """Whoever started this (Zook, a Bot's shell) quit without stopping it: stop too, removing the one-slide copies."""
    while os.getppid() == parent: time.sleep(2)
    os.kill(os.getpid(), signal.SIGTERM)


def _stop(signum, frame):
    for proc in list(_children): _end(proc)  # Quick Look or the Word layout it was waiting on goes too
    raise SystemExit(128 + signum)  # Zook stopping the job: unwind so the one-slide copies are removed


def main(argv):
    if len(argv) == 5 and argv[3] == '--pages' and argv[4].isdigit(): MOST[0] = int(argv[4]); argv = argv[:3]
    if len(argv) != 3: raise SystemExit('用法：python3 pagepics.py <檔案> <輸出資料夾> [--pages 頁數]')
    path, out = argv[1], argv[2]
    for sig in (signal.SIGTERM, signal.SIGHUP): signal.signal(sig, _stop)
    threading.Thread(target=_orphaned, args=(os.getppid(),), daemon=True).start()
    os.makedirs(out, exist_ok=True)
    kind = os.path.splitext(path)[1].lower()
    if kind == '.pdf': pages, missing = pdf_pages(path, out)
    elif kind in ('.pptx', '.potx', '.ppsx'): pages, missing = pptx_pages(path, out)
    else: pages, missing = docx_pages(path, out) if kind == '.docx' else ([], [])
    if not pages and kind not in ('.pdf', '.pptx', '.potx', '.ppsx'):  # a Word file macOS could not lay out still gets its first page
        made = quicklook(path, out)
        pages, missing = [(made, 0, 0)] if made else [], []
        if made: print('（這個格式只能轉第一頁；其餘內容請直接讀檔確認）')
    for target, w, h in pages: print('%s\t比例 %s' % (target, ratio(w, h)))
    if SKIPPED[0]: print('（共 %d 頁，只轉了前 %d 頁）' % (SKIPPED[0] + MOST[0], MOST[0]))
    if missing: raise SystemExit('這幾頁沒有轉出圖片：第 %s 頁（%s）。請改讀這幾頁的內容確認，並告訴使用者哪些版面沒有看到。'
                                 % ('、'.join(map(str, missing)), path))
    if not pages: raise SystemExit('沒有轉出圖片：%s' % path)


if __name__ == '__main__': main(sys.argv)
