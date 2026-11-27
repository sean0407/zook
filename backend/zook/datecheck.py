# Checks a date the user wrote together with a day of the week ("1/23 禮拜五", "下週一 12/1", "2027/1/23 (Sat)") against this
# Mac's calendar before the message goes to a Bot. Nothing in the user's words is changed: a mismatch is shown under the message
# in plain words and added to what the Bots read, so they ask before copying it.
import bisect as _bisect
import datetime as _dt
import re as _re

DATE_WEEKDAYS = ('週一', '週二', '週三', '週四', '週五', '週六', '週日')
# #77④: a date in a notice says its weekday, 12/1（週二）; the Bots are told to write dates the same way.
WEEKDAY_NOTE = '寫到日期時（通知、提醒、時程、面試或會議時間）一律帶星期，寫成「月/日（週幾）」；寫星期之前先用這台 Mac 的日曆核對，不是今年的日期寫出年份。'


def day_label(date, today=None):
    """12/1（週二）; with the year when it is not this year (2027/1/5（週二）)."""
    today = today or _dt.date.today()
    shown = '%d/%d' % (date.month, date.day) if date.year == today.year else '%d/%d/%d' % (date.year, date.month, date.day)
    return '%s（%s）' % (shown, DATE_WEEKDAYS[date.weekday()])
_DAY_CHARS = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
_DAY_EN = (('mon', 0), ('tue', 1), ('wed', 2), ('thu', 3), ('fri', 4), ('sat', 5), ('sun', 6))
# 2027/1/23, 2027-1-23, 2027年1月23日, 1/23, 1月23日. A bare M-D with a dash is left alone (too often a range or a code).
_DATE = _re.compile(r'(?<![\d/.\-])(?:(?P<y>\d{4})\s{0,2}(?:年\s{0,2}|[/.\-]))?(?P<m>\d{1,2})\s{0,2}(?:月\s{0,2}|/)(?P<d>\d{1,2})(?:\s{0,2}[日號号])?(?![\d/])')
_DATE_DASH = _re.compile(r'(?<![\d/.\-])(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})(?![\d\-])')
_WEEKDAY = _re.compile(r'(?P<pre>[上下這这本前每]{0,2}|(?:last|next|this)\s{1,3})?(?:(?:週|周|星期|禮拜|礼拜)(?P<zh>[一二三四五六日天])|[（(]\s{0,2}(?P<bare>[一二三四五六日])\s{0,2}[)）]'
                       r'|(?P<en>\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]{0,6}\.?(?![a-z])))', _re.I)
_EN_FULL = {'mon', 'monday', 'tue', 'tues', 'tuesday', 'wed', 'wednesday', 'thu', 'thur', 'thurs', 'thursday', 'fri', 'friday', 'sat', 'saturday', 'sun', 'sunday'}
_RANGE_MARKS = '到至~～-–—'
_RANGE_AFTER = _re.compile(r'\s{0,3}[到至~～\-–—]\s{0,3}(?:週|周|星期|禮拜|礼拜)?[一二三四五六日天]')
_GAP_AFTER = _re.compile(r'[ \t　]{0,3}(?:[是為为][ \t　]{0,2})?[(（]?[ \t　]{0,2}')  # 1/23 週五, 1/23（週五）, 1/23 是週五
_GAP_AFTER_COMMA = _re.compile(r'[ \t　]{0,3}[,，][ \t　]{0,3}')  # 1/23，週五 (unless 週五 sits right before a date of its own)
_GAP_BEFORE = _re.compile(r'[ \t　]{0,3}[,，]?[ \t　]{0,3}')  # 週五 1/23, 星期五，1/23
_CLOSE = _re.compile(r'[ \t　]{0,2}[)）]')
_CLAUSE_END = _re.compile(r'[。！？!?\n；;]|\.(?=\s)')
_PAST_WORDS = _re.compile(r'上週|上周|上禮拜|上礼拜|上星期|上個月|上个月|上月|昨天|前天|上次|last\s{1,3}(?:week|month)', _re.I)
_YEAR_WORDS = (('前年', -2), ('去年', -1), ('今年', 0), ('明年', 1), ('後年', 2), ('后年', 2), ('last year', -1), ('this year', 0), ('next year', 1))
DATE_CHECK_MAX = 5  # notes per message
DATE_CHECK_SCAN = 200  # dates and weekdays looked at per message: a long list stays quick (this runs with the store locked)


def _weekday_of(match):
    if match.group('zh'): return _DAY_CHARS[match.group('zh')]
    if match.group('bare'): return _DAY_CHARS[match.group('bare')]
    word = match.group('en').rstrip('.').lower()
    if word not in _EN_FULL: return None
    return next(n for key, n in _DAY_EN if word.startswith(key))


def _weekdays(text):
    found = []
    for w in _WEEKDAY.finditer(text):
        if len(found) >= DATE_CHECK_SCAN: break
        day = _weekday_of(w)
        if day is None: continue
        pre = (w.group('pre') or '').strip().lower()
        if '每' in pre: continue  # 每週五: a habit, not a date
        if _RANGE_AFTER.match(text, w.end()): continue  # 週一到週五: a span of days
        if text[max(0, w.start() - 4):w.start()].rstrip()[-1:] in tuple(_RANGE_MARKS): continue  # the end of such a span
        close = _CLOSE.match(text, w.end()) if not w.group('bare') else None
        found.append(dict(day=day, start=w.start(), end=w.end(), shown_end=close.end() if close else w.end(),
                          past=pre.startswith('上') or pre.startswith('last'), future=pre.startswith('下') or pre.startswith('next')))
    return found


def _dates(text):
    spans, starts = [], []
    for pattern in (_DATE, _DATE_DASH):  # the first ones of each kind, then the first ones in the order they were written
        for n, d in enumerate(pattern.finditer(text)):
            if n >= DATE_CHECK_SCAN: break
            at = _bisect.bisect_right(starts, d.start()) - 1
            if at >= 0 and spans[at][0] <= d.start() < spans[at][1]: continue
            spans.insert(at + 1, (d.start(), d.end(), d)); starts.insert(at + 1, d.start())
    return spans[:DATE_CHECK_SCAN]


def _pick_year(month, day, today, past, future=False):
    """Without a year: the next time this day comes, or the last time it came when the user is talking about the past
    (上週…) or it was within the last month. None when the day does not exist."""
    near = []
    for year in (today.year - 1, today.year, today.year + 1, today.year + 2, today.year - 2, today.year - 3, today.year + 3, today.year + 4):
        try: near.append(_dt.date(year, month, day))
        except ValueError: continue
    if not near: return None, None
    ahead = min((x for x in near if x >= today), default=None)
    behind = max((x for x in near if x < today), default=None)
    if ahead is None or (not future and (past or (behind and (today - behind).days <= 31))): return behind or ahead, ahead if behind else None
    return ahead, behind


def _shown(date): return '%d/%d/%d' % (date.year, date.month, date.day)


def _clause(text, start, end):
    """The words around a date in the same sentence, for 去年、上週… said about it."""
    lead = text[max(0, start - 16):start]
    cut = list(_CLAUSE_END.finditer(lead))
    return (lead[cut[-1].end():] if cut else lead) + text[start:end]


def date_check(text, today=None):
    """Plain-words notes for every date written with a weekday that does not match, at most DATE_CHECK_MAX. [] when all is well."""
    if not isinstance(text, str) or not text: return []
    today = today or _dt.date.today()
    days, notes, used = _weekdays(text), [], set()
    starts = [w['start'] for w in days]
    dates = _dates(text); dates_at = [x[0] for x in dates]
    for start, end, d in dates:
        if len(notes) >= DATE_CHECK_MAX: break
        pick = None
        i = _bisect.bisect_left(starts, end)  # the first weekday after the date, if it follows right on
        if i < len(days) and i not in used:
            if days[i]['start'] - end <= 10 and _GAP_AFTER.fullmatch(text, end, days[i]['start']): pick = i
            elif days[i]['start'] - end <= 10 and _GAP_AFTER_COMMA.fullmatch(text, end, days[i]['start']):
                follows = _bisect.bisect_left(dates_at, days[i]['end'])  # 1/22，週五 1/23: 週五 is 1/23's
                if not (follows < len(dates_at) and dates_at[follows] - days[i]['end'] <= 3 and not text[days[i]['end']:dates_at[follows]].strip()): pick = i
        if pick is None:
            i = _bisect.bisect_left(starts, start) - 1  # else the one right before it
            if i >= 0 and i not in used and days[i]['end'] <= start:
                if start - days[i]['end'] <= 10 and _GAP_BEFORE.fullmatch(text, days[i]['end'], start): pick = i
        if pick is None: continue
        used.add(pick); w = days[pick]
        month, day = int(d.group('m')), int(d.group('d'))
        written = text[min(start, w['start']):max(end, w['shown_end'])].strip()
        if d.group('y'):
            try: actual = _dt.date(int(d.group('y')), month, day)
            except ValueError: notes.append('「%s」：沒有 %s/%d/%d 這一天，請確認日期。' % (written, d.group('y'), month, day)); continue
            if actual.weekday() != w['day']: notes.append('「%s」：%s 是%s，不是%s。請確認是哪一天。' % (written, _shown(actual), DATE_WEEKDAYS[actual.weekday()], DATE_WEEKDAYS[w['day']]))
            continue
        nearby = _clause(text, min(start, w['start']), max(end, w['end'])).lower()
        said_year = max(((nearby.rfind(word), n) for word, n in _YEAR_WORDS if word in nearby), default=None)  # the nearest one: 去年 1/23、明年 1/23
        shift = said_year[1] if said_year else None
        if shift is not None:  # 去年 1/23: that year, no guessing
            try: main, other = _dt.date(today.year + shift, month, day), None
            except ValueError: main = other = None
        else:
            past = w['past'] or (not w['future'] and bool(_PAST_WORDS.search(nearby)))
            main, other = _pick_year(month, day, today, past, w['future'])
            if w['future'] or past: other = None  # 下週、上週…: the user said which way, so the other year is no excuse
        if main is None: notes.append('「%s」：沒有 %d/%d 這一天，請確認日期。' % (written, month, day)); continue
        if main.weekday() == w['day']: continue
        line = '「%s」：%s 是%s，不是%s。' % (written, _shown(main), DATE_WEEKDAYS[main.weekday()], DATE_WEEKDAYS[w['day']])
        if other and other.weekday() == w['day']: line += '%s 才是%s（%s）。' % (_shown(other), DATE_WEEKDAYS[w['day']], '已經過了' if other < today else '是更晚的那一年')
        notes.append(line + '請確認是哪一天。')
    return notes


def _check_day(message):
    day = (message or {}).get('dateCheckDay')
    try: return _dt.date.fromisoformat(day) if isinstance(day, str) and len(day) == 10 else None
    except ValueError: return None


def date_check_message(message, today=None):
    """Lock held. Marks a user's message whose dates and weekdays do not match; the words themselves stay as written. The day
    it was checked on is kept, so what the Bots read later is worked out again the same way, never taken from a stored text."""
    today = today or _dt.date.today()
    notes = date_check(message.get('content'), today)
    if notes: message.update(dateCheck=notes, dateCheckDay=today.isoformat())
    else: message.pop('dateCheck', None); message.pop('dateCheckDay', None)
    return notes


def date_check_note(message):
    """What the Bots read right after that message: worked out from its words and the day it was sent (a copy restored or synced
    from elsewhere cannot put its own text here)."""
    day = _check_day(message)
    if not day or not message.get('dateCheck'): return ''
    notes = date_check(message.get('content'), day)
    if not notes: return ''
    return '\n（Zook 檢查日期：%s 這是用這台 Mac 的日曆算的；回覆前請先向使用者確認是哪一天，不要照抄。）' % ' '.join(notes)


def date_check_copy(source, into):
    """Sync: a message from another Mac keeps its reminder, worked out here again from its words and the day it was sent."""
    day = _check_day(source)
    if day and source.get('dateCheck') and into.get('role') == 'user': date_check_message(into, day)
    else: into.pop('dateCheck', None); into.pop('dateCheckDay', None)


def date_check_restored(messages):
    """A backup being put back: its reminders are never taken as written, only worked out again from each message's words."""
    for m in messages:
        if isinstance(m, dict) and ('dateCheck' in m or 'dateCheckDay' in m): date_check_copy(dict(m), m)
