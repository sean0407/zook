# Checks a date the user wrote together with a day of the week ("1/23 禮拜五", "下週一 12/1", "2027/1/23 (Sat)") against this
# Mac's calendar before the message goes to a Bot. Nothing in the user's words is changed: a mismatch is shown under the message
# in plain words and added to what the Bots read, so they ask before copying it.
import datetime as _dt
import re as _re

DATE_WEEKDAYS = ('週一', '週二', '週三', '週四', '週五', '週六', '週日')
_DAY_CHARS = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
_DAY_EN = (('mon', 0), ('tue', 1), ('wed', 2), ('thu', 3), ('fri', 4), ('sat', 5), ('sun', 6))
# 2027/1/23, 2027-1-23, 2027年1月23日, 1/23, 1月23日. A bare M-D with a dash is left alone (too often a range or a code).
_DATE = _re.compile(r'(?<![\d/.\-])(?:(?P<y>\d{4})\s*(?:年\s*|[/.\-]))?(?P<m>\d{1,2})\s*(?:月\s*|/)(?P<d>\d{1,2})(?:\s*[日號号])?(?![\d/])')
_DATE_DASH = _re.compile(r'(?<![\d/.\-])(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})(?![\d\-])')
_WEEKDAY = _re.compile(r'(?P<pre>[上下這这本前每]{0,2}|(?:last|next|this)\s+)?(?:(?:週|周|星期|禮拜|礼拜)(?P<zh>[一二三四五六日天])|[（(]\s*(?P<bare>[一二三四五六日])\s*[)）]'
                       r'|(?P<en>\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?(?![a-z])))', _re.I)
_EN_FULL = {'mon', 'monday', 'tue', 'tues', 'tuesday', 'wed', 'wednesday', 'thu', 'thur', 'thurs', 'thursday', 'fri', 'friday', 'sat', 'saturday', 'sun', 'sunday'}
_RANGE_AFTER = _re.compile(r'\s*(?:到|至|~|～|-|–|—)\s*(?:週|周|星期|禮拜|礼拜)?[一二三四五六日天]')
_PAST_WORDS = _re.compile(r'上週|上周|上禮拜|上礼拜|上星期|上個月|上个月|上月|去年|昨天|前天|上次|last\s+(?:week|month|year)', _re.I)
DATE_CHECK_MAX = 5  # notes per message


def _weekday_of(match):
    if match.group('zh'): return _DAY_CHARS[match.group('zh')]
    if match.group('bare'): return _DAY_CHARS[match.group('bare')]
    word = match.group('en').rstrip('.').lower()
    if word not in _EN_FULL: return None
    return next(n for key, n in _DAY_EN if word.startswith(key))


def _weekdays(text):
    found = []
    for w in _WEEKDAY.finditer(text):
        day = _weekday_of(w)
        if day is None: continue
        pre = (w.group('pre') or '').strip().lower()
        if '每' in pre: continue  # 每週五: a habit, not a date
        if _RANGE_AFTER.match(text, w.end()): continue  # 週一到週五: a span of days
        if w.start() > 0 and text[w.start() - 1] in '到至~～-–—': continue
        found.append(dict(day=day, start=w.start(), end=w.end(), past=pre.startswith('上') or pre.startswith('last'), future=pre.startswith('下') or pre.startswith('next')))
    return found


def _dates(text):
    spans = []
    for pattern in (_DATE, _DATE_DASH):
        for d in pattern.finditer(text):
            if any(s <= d.start() < e for s, e, _ in spans): continue
            spans.append((d.start(), d.end(), d))
    return sorted(spans, key=lambda x: x[0])


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


def _shown(date, with_year=True): return ('%d/%d/%d' % (date.year, date.month, date.day)) if with_year else '%d/%d' % (date.month, date.day)


def date_check(text, today=None):
    """Plain-words notes for every date written with a weekday that does not match, at most DATE_CHECK_MAX. [] when all is well."""
    if not isinstance(text, str) or not text: return []
    today = today or _dt.date.today()
    days, notes, used = _weekdays(text), [], set()
    for start, end, d in _dates(text):
        if len(notes) >= DATE_CHECK_MAX: break
        after = next((i for i, w in enumerate(days) if i not in used and w['start'] >= end and _re.fullmatch(r'[\s　,，、(（]{0,3}', text[end:w['start']])), None)
        before = None if after is not None else next((i for i, w in reversed(list(enumerate(days))) if i not in used and w['end'] <= start and _re.fullmatch(r'[\s　,，、]{0,3}', text[w['end']:start])), None)
        pick = after if after is not None else before
        if pick is None: continue
        used.add(pick); w = days[pick]
        month, day = int(d.group('m')), int(d.group('d'))
        written = text[min(start, w['start']):max(end, w['end'])].strip()
        if d.group('y'):
            try: actual = _dt.date(int(d.group('y')), month, day)
            except ValueError: notes.append('「%s」：沒有 %s/%d/%d 這一天，請確認日期。' % (written, d.group('y'), month, day)); continue
            if actual.weekday() != w['day']: notes.append('「%s」：%s 是%s，不是%s。請確認是哪一天。' % (written, _shown(actual), DATE_WEEKDAYS[actual.weekday()], DATE_WEEKDAYS[w['day']]))
            continue
        nearby = text[max(0, min(start, w['start']) - 12):max(end, w['end'])]
        past = w['past'] or (not w['future'] and bool(_PAST_WORDS.search(nearby)))
        main, other = _pick_year(month, day, today, past, w['future'])
        if w['future'] or past: other = None  # 下週、上週、去年…: the user said which way, so the other year is no excuse
        if main is None: notes.append('「%s」：沒有 %d/%d 這一天，請確認日期。' % (written, month, day)); continue
        if main.weekday() == w['day']: continue
        line = '「%s」：%s 是%s，不是%s。' % (written, _shown(main), DATE_WEEKDAYS[main.weekday()], DATE_WEEKDAYS[w['day']])
        if other and other.weekday() == w['day']: line += '%s 才是%s（%s）。' % (_shown(other), DATE_WEEKDAYS[w['day']], '已經過了' if other < today else '是更晚的那一年')
        notes.append(line + '請確認是哪一天。')
    return notes


def date_check_message(message, today=None):
    """Lock held. Marks a user's message whose dates and weekdays do not match; the words themselves stay as written."""
    notes = date_check(message.get('content'), today)
    if notes: message['dateCheck'] = notes
    else: message.pop('dateCheck', None)
    return notes


def date_check_note(message):
    """What the Bots read right after that message."""
    notes = [x for x in (message or {}).get('dateCheck') or [] if isinstance(x, str)][:DATE_CHECK_MAX]
    if not notes: return ''
    return '\n（Zook 檢查日期：%s 這是用這台 Mac 的日曆算的；回覆前請先向使用者確認是哪一天，不要照抄。）' % ' '.join(notes)
