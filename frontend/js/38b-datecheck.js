
  // Under the user's own message: a date and weekday that do not match on this Mac's calendar (backend datecheck.py). The
  // message itself is shown as written; the Bots read the same note.
  window.dateNote = m => {
    const notes = (m && m.role === 'user' && Array.isArray(m.dateCheck) ? m.dateCheck : []).filter(x => typeof x === 'string').slice(0, 5);
    if (!notes.length) return '';
    return `<div class="date-note" role="note"><strong>日期提醒</strong>${notes.map(x => `<span>${esc(x)}</span>`).join('')}<small>已一併提醒 Bot 先跟你確認。</small></div>`;
  };
