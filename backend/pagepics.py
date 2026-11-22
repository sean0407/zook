# -*- coding: utf-8 -*-
"""Every page of a PDF or a PowerPoint deck as a PNG, without opening any app window.

Bots run this to look at what they made: `/usr/bin/python3 pagepics.py <file> <out folder>`.
PDF pages are drawn with macOS CoreGraphics (standard library only, through ctypes); each slide of a .pptx is cut into
a one-slide copy that Quick Look (qlmanage, no window) turns into a picture. Other formats get Quick Look's first page.
It prints each picture and the page size with its ratio (16:9 slides should say 16:9), and leaves no other files behind.
"""
import ctypes, ctypes.util, os, re, shutil, subprocess, sys, tempfile, zipfile


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
    """Every page drawn on white at `width` pixels. Returns [(png, w, h)] in PDF points."""
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
    png_type, space, done = cf.CFStringCreateWithCString(None, b'public.png', 0x08000100), cg.CGColorSpaceCreateDeviceRGB(), []
    stem = os.path.splitext(os.path.basename(path))[0]
    for n in range(1, cg.CGPDFDocumentGetNumberOfPages(doc) + 1):
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
        dest_url = url(target); dest = io.CGImageDestinationCreateWithURL(dest_url, png_type, 1, None)
        io.CGImageDestinationAddImage(dest, image, None); io.CGImageDestinationFinalize(dest)
        cf.CFRelease(dest); cf.CFRelease(dest_url); cg.CGImageRelease(image); cg.CGContextRelease(ctx)
        done.append((target, w, h))
    cg.CGColorSpaceRelease(space); cf.CFRelease(png_type); cg.CGPDFDocumentRelease(doc)
    return done


def quicklook(path, out, width=1600):
    """Quick Look's picture of the file's first page (no window). Returns the PNG or None."""
    subprocess.run(['/usr/bin/qlmanage', '-t', '-s', str(width), '-o', out, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    made = os.path.join(out, os.path.basename(path) + '.png')
    return made if os.path.exists(made) else None


def pptx_pages(path, out, width=1600):
    """One-slide copies of the deck, each pictured by Quick Look. Returns [(png, w, h)] in EMU."""
    with zipfile.ZipFile(path) as z:
        pres = z.read('ppt/presentation.xml').decode('utf-8')
        names = z.namelist()
        parts = {n: z.read(n) for n in names}
    size = re.search(r'<p:sldSz\b[^>]*?\bcx="(\d+)"[^>]*?\bcy="(\d+)"', pres)
    w, h = (int(size.group(1)), int(size.group(2))) if size else (0, 0)
    ids = re.findall(r'<p:sldId\b[^>]*/>', pres)
    stem, done = os.path.splitext(os.path.basename(path))[0], []
    work = tempfile.mkdtemp(prefix='zook-pagepics-')
    try:
        for n, keep in enumerate(ids, 1):
            one = re.sub(r'<p:sldIdLst>.*?</p:sldIdLst>', '<p:sldIdLst>' + keep + '</p:sldIdLst>', pres, flags=re.S)
            copy = os.path.join(work, '%s-%02d.pptx' % (stem, n))
            with zipfile.ZipFile(copy, 'w', zipfile.ZIP_DEFLATED) as z:
                for name in names: z.writestr(name, one.encode('utf-8') if name == 'ppt/presentation.xml' else parts[name])
            made = quicklook(copy, work, width)
            if made:
                target = os.path.join(out, '%s-%02d.png' % (stem, n)); shutil.move(made, target); done.append((target, w, h))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return done


def main(argv):
    if len(argv) != 3: raise SystemExit('用法：python3 pagepics.py <檔案> <輸出資料夾>')
    path, out = argv[1], argv[2]
    os.makedirs(out, exist_ok=True)
    kind = os.path.splitext(path)[1].lower()
    if kind == '.pdf': pages = pdf_pages(path, out)
    elif kind in ('.pptx', '.potx', '.ppsx'): pages = pptx_pages(path, out)
    else:
        made = quicklook(path, out)
        pages = [(made, 0, 0)] if made else []
        if made: print('（這個格式只能轉第一頁；其餘內容請直接讀檔確認）')
    if not pages: raise SystemExit('沒有轉出圖片：%s' % path)
    for target, w, h in pages: print('%s\t比例 %s' % (target, ratio(w, h)))


if __name__ == '__main__': main(sys.argv)
