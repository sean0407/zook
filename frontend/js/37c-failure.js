  // #238: a failed reply says what kind of failure it was, whether simply trying again helps, what to do next, and offers buttons that
  // only start what already exists (answer again, another model, the usage page, a new chat, the Bot's settings, macOS's privacy page).
  const FAILURE_BUTTONS = {
    retry: () => 'data-action="redo-again"', 'redo-model': () => 'data-action="redo-model"', usage: () => 'data-action="page" data-id="usage"',
    'new-chat': () => 'data-action="new-chat"', 'edit-bot': () => 'data-action="edit-bot"', settings: a => `data-action="open-privacy" data-pane="${esc(a.pane || '')}"`,
  };
  function failureJob(m) { return Object.values(state.jobDetails).find(j => j.messageId === m.id); }
  function failureWhen(iso) {
    const at = new Date(iso); if (isNaN(at)) return '';
    const time = at.toLocaleTimeString('zh-TW', {hour: '2-digit', minute: '2-digit', hour12: false});
    return at.toDateString() === new Date().toDateString() ? time : `${dayWeek(at)}${time}`;  // #77④: 12/1（週二）18:00
  }
  // The card for a failed reply, or '' when the reply has no kind yet (an older Zook, or a reply that did not fail). Buttons only on
  // the last reply of a Bot's conversation while nothing runs: that is the reply 重試 and 換模型 act on.
  function failureCard(m, withButtons) {
    if (m.status !== 'failed' || m.content) return '';
    const job = failureJob(m), f = job?.failure;
    if (!f) return '';
    const when = f.resetAt ? failureWhen(f.resetAt) : '';
    const buttons = withButtons ? (f.actions || []).filter(a => FAILURE_BUTTONS[a.action]).map((a, i) => `<button type="button" class="${i ? 'link' : 'primary small-btn'}" ${FAILURE_BUTTONS[a.action](a)}>${esc(a.label)}</button>`).join('') : '';
    return `<div class="bubble failure-card"><div class="failure-head"><span class="pill bad">${esc(f.label)}</span><span class="muted">${f.retry ? '可以直接重試' : '直接重試會一樣失敗'}</span></div>`
      + `<p class="failure-why">${esc(job.error || '回覆失敗。')}</p><p class="failure-next"><strong>下一步：</strong>${esc(f.next)}${when ? `（額度約 ${esc(when)} 恢復）` : ''}</p>`
      + (buttons ? `<div class="failure-actions">${buttons}</div>` : '') + '</div>';
  }
