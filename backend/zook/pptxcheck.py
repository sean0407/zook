# 簡報檢查 (#67, #42): text whose size, weight, colour or font is set only in the paragraph default (a:pPr/a:defRPr) and not on the text
# run itself. Quick Look shows it right; PowerPoint may not take the paragraph default and open it at its default size and colour.
# Runs with the Excel check after a reply (xlsx_after_reply), read only, with its guards (knowledge.py's safe XML reader, size and time caps). Loaded by backend/server.py.

_PA = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
_PP = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
_PATTRS = ('sz', 'b', 'i')  # set on the default, missing on the run
_PFILL = tuple(_PA + t for t in ('noFill', 'solidFill', 'gradFill', 'blipFill', 'pattFill', 'grpFill'))  # one property: any of them on the run overrides
_PCHILD = ((_PFILL,) + tuple((_PA + t,) for t in ('latin', 'ea')))
PPTX_SUFFIXES = ('.pptx',)
PPTX_SLIDES = 300
PPTX_FILES = 3  # decks looked at per reply
PPTX_SIZE_WRONG = (0, 1)  # in a scan: the deck's size is named for one shape and drawn in another (#164②); slide 0 = the whole deck
_PSIZES = {'screen4x3': (4 / 3, '4:3'), 'screen16x9': (16 / 9, '16:9'), 'screen16x10': (16 / 10, '16:10')}


def _pslides(z, deadline, budget):
    """Slide parts in presentation order."""
    targets = {}
    for _, el in _xparse(z, 'ppt/_rels/presentation.xml.rels', deadline, budget, {_XP + 'Relationship'}):
        if el.tag == _XP + 'Relationship' and el.get('Id'):
            target = el.get('Target') or ''
            targets[el.get('Id')] = target.lstrip('/') if target.startswith('/') else _xposix.normpath('ppt/' + target)
    return [targets[el.get(_XR)] for _, el in _xparse(z, 'ppt/presentation.xml', deadline, budget, {_PP + 'sldId'}) if el.tag == _PP + 'sldId' and targets.get(el.get(_XR))]


def _psize_wrong(z, deadline, budget):
    """True when presentation.xml names the size 4:3 (or 16:9, 16:10) but its width and height are another shape, as pptxgenjs writes a
    16:9 deck with type="screen4x3": PowerPoint's page setup then says 4:3 and changing anything there may stretch every slide."""
    for _, el in _xparse(z, 'ppt/presentation.xml', deadline, budget, {_PP + 'sldSz'}):
        if el.tag != _PP + 'sldSz': continue
        want = _PSIZES.get(el.get('type') or '')
        try: cx, cy = int(el.get('cx') or 0), int(el.get('cy') or 0)
        except ValueError: return False
        return bool(want and cx > 0 and cy > 0 and abs(cx / cy - want[0]) / want[0] > 0.02)
    return False


def _prun_bare(run, wanted_attrs, wanted_children):
    if not ''.join(t.text or '' for t in run.iter(_PA + 't')).strip(): return False  # nothing shown
    props = run.find(_PA + 'rPr')
    if props is None: return True
    return any(props.get(a) is None for a in wanted_attrs) or any(all(props.find(t) is None for t in group) for group in wanted_children)


def pptx_scan(path):
    """[(slide number, runs with their format only in the paragraph default)] for the slides that have any; [] when sound, too big,
    unreadable or slow. Only reads the file."""
    deadline = time.monotonic() + XLSX_SECONDS; budget = [XLSX_UNPACKED]; found = []
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > XLSX_MAX_BYTES: return []
            knowledge_zip_precheck(handle)  # #240: before zipfile reads its directory
            with _xzip.ZipFile(handle) as z:
                if _psize_wrong(z, deadline, budget): found.append(PPTX_SIZE_WRONG)
                for index, part in enumerate(_pslides(z, deadline, budget)[:PPTX_SLIDES]):
                    try: z.getinfo(part)
                    except KeyError: continue
                    bare = 0
                    for n, (_, el) in enumerate(_xparse(z, part, deadline, budget, {_PA + 'p'})):
                        if n % 2000 == 0 and time.monotonic() > deadline: raise _XSlow()
                        if el.tag != _PA + 'p': continue
                        default = el.find(_PA + 'pPr/' + _PA + 'defRPr')
                        if default is not None:
                            attrs = [a for a in _PATTRS if default.get(a) is not None]
                            children = [g for g in _PCHILD if any(default.find(t) is not None for t in g)]
                            if attrs or children:
                                bare += sum(1 for run in el if run.tag in (_PA + 'r', _PA + 'fld') and _prun_bare(run, attrs, children))
                        el.clear()
                    if bare: found.append((index + 1, bare))
    except (_XSlow, _xzip.BadZipFile, _xzlib.error, KeyError, OSError, ValueError, LookupError, RuntimeError, EOFError,
            NotImplementedError, OverflowError, RecursionError, UnicodeError):
        return []
    return found


def pptx_render(scan, for_bot=False):
    """A plain sentence from pptx_scan, rebuilt from slide numbers and counts only (a restored backup passes nothing else on)."""
    whole = [x for x in scan if isinstance(x, (list, tuple)) and len(x) == 2 and all(type(v) is int for v in x)] if isinstance(scan, list) else []
    slides = [x for x in whole if all(v > 0 for v in x)]
    out = ['投影片大小標示的比例（例如 4:3）和實際長寬不一致，用 PowerPoint 開啟時「投影片大小」會顯示錯的比例，改設定時可能把每頁拉變形'
           + ('。請把 ppt/presentation.xml 的 p:sldSz 改成和實際長寬一致（16:9 寬螢幕拿掉 type 或用 custom），再轉圖確認比例' if for_bot else '')] \
        if any(tuple(x) == PPTX_SIZE_WRONG for x in whole) else []
    if not slides: return out
    count = sum(n for _, n in slides); pages = '、'.join(str(s) for s, _ in slides[:8]) + ('…' if len(slides) > 8 else '')
    line = '有 %d 段文字的字級、顏色或字型只設在段落預設，文字本身沒有格式，用 PowerPoint 開啟可能變回預設字級和顏色而跑版（第 %s 頁）' % (count, pages)
    if for_bot: line += '。請把字級、粗細、顏色和字型直接設在每段文字上（python-pptx 用 run.font，中文字型另寫 a:ea）'
    return out + [line]


def pptx_issues(path, for_bot=False):
    return pptx_render(pptx_scan(path), for_bot)
