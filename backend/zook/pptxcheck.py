# 簡報檢查 (#67, #42): text whose size, weight, colour or font is set only in the paragraph default (a:pPr/a:defRPr) and not on the text
# run itself. Quick Look shows it right; PowerPoint may not take the paragraph default and open it at its default size and colour.
# Runs with the Excel check after a reply (xlsx_after_reply), read only, with its guards (_XGuard, size and time caps). Loaded by backend/server.py.

_PA = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
_PP = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
_PATTRS = ('sz', 'b', 'i')  # set on the default, missing on the run
_PFILL = tuple(_PA + t for t in ('noFill', 'solidFill', 'gradFill', 'blipFill', 'pattFill', 'grpFill'))  # one property: any of them on the run overrides
_PCHILD = ((_PFILL,) + tuple((_PA + t,) for t in ('latin', 'ea')))
PPTX_SUFFIXES = ('.pptx',)
PPTX_SLIDES = 300
PPTX_FILES = 3  # decks looked at per reply


def _pslides(z, deadline, budget):
    """Slide parts in presentation order."""
    targets = {}
    for _, el in _xparse(z, 'ppt/_rels/presentation.xml.rels', deadline, budget):
        if el.tag == _XP + 'Relationship' and el.get('Id'):
            target = el.get('Target') or ''
            targets[el.get('Id')] = target.lstrip('/') if target.startswith('/') else _xposix.normpath('ppt/' + target)
    return [targets[el.get(_XR)] for _, el in _xparse(z, 'ppt/presentation.xml', deadline, budget) if el.tag == _PP + 'sldId' and targets.get(el.get(_XR))]


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
            with _xzip.ZipFile(handle) as z:
                for index, part in enumerate(_pslides(z, deadline, budget)[:PPTX_SLIDES]):
                    try: z.getinfo(part)
                    except KeyError: continue
                    bare = 0
                    for n, (_, el) in enumerate(_xparse(z, part, deadline, budget)):
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
    except (_XSlow, _xzip.BadZipFile, _XET.ParseError, _xzlib.error, KeyError, OSError, ValueError, LookupError, RuntimeError, EOFError,
            NotImplementedError, OverflowError, RecursionError, UnicodeError):
        return []
    return found


def pptx_render(scan, for_bot=False):
    """A plain sentence from pptx_scan, rebuilt from slide numbers and counts only (a restored backup passes nothing else on)."""
    slides = [x for x in scan if isinstance(x, (list, tuple)) and len(x) == 2 and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in x)] if isinstance(scan, list) else []
    if not slides: return []
    count = sum(n for _, n in slides); pages = '、'.join(str(s) for s, _ in slides[:8]) + ('…' if len(slides) > 8 else '')
    line = '有 %d 段文字的字級、顏色或字型只設在段落預設，文字本身沒有格式，用 PowerPoint 開啟可能變回預設字級和顏色而跑版（第 %s 頁）' % (count, pages)
    if for_bot: line += '。請把字級、粗細、顏色和字型直接設在每段文字上（python-pptx 用 run.font，中文字型另寫 a:ea）'
    return [line]


def pptx_issues(path, for_bot=False):
    return pptx_render(pptx_scan(path), for_bot)
