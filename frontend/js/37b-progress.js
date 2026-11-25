  // 等待時的進度 (#236): a line under 「正在思考…」 with how long the reply has run and what its CLI reported doing so far
  // (progress.py). Nothing here is made up from a timer: only the time is counted here, every step comes from the Mac.
  // Quiet for a long time: it says it may be stuck and that ■ stops it; it never stops anything itself. After ■, a reply whose
  // CLI has not ended is 「正在停止…」, and after a while it offers 強制停止.
  const STUCK_AFTER = 5 * 60000, FORCE_AFTER = 10000;
  if (!state.stopAsked) state.stopAsked = {};  // job id -> when ■ was pressed here, before the Mac has answered
  function spanWords(ms) { const s = Math.max(0, Math.floor(ms / 1000)), m = Math.floor(s / 60); return m ? `${m} 分 ${s % 60} 秒` : `${s} 秒`; }
  function progressWords(p) {
    if (!p) return '';
    return [p.read && `讀了 ${p.read} 個檔`, p.write && `寫了 ${p.write} 個檔`, p.command && `執行 ${p.command} 個指令`, p.web && `查了 ${p.web} 次網路`, p.tool && `用了 ${p.tool} 次工具`].filter(Boolean).join('、');
  }
  // Waiting on you (a card), or one of Zook's tools still at work: not stuck.
  const waitHeld = j => (j.approvals || []).some(a => a.status === 'pending') || (j.questions || []).some(q => q.status === 'pending') || (j.toolCalls || []).some(c => c.status === 'running' || c.status === 'pending' || c.status === 'waiting_approval');
  // d: the line's data (strings or numbers, as in the element's dataset). {text, stuck, late}
  function waitState(d, now) {
    if (d.stop) {
      const late = now - Number(d.stop) >= FORCE_AFTER;
      return {text: late ? '還沒停下來。' : '正在停止…', late};
    }
    const since = now - Number(d.since), quiet = d.last ? now - Number(d.last) : 0;
    if (!d.hold && d.last && quiet >= STUCK_AFTER) return {text: `已經 ${Math.floor(quiet / 60000)} 分鐘沒有新動作，可能卡住了，可以按 ■ 停止（已 ${spanWords(since)}）`, stuck: true};
    return {text: (Number.isFinite(since) ? '已 ' + spanWords(since) : '') + (d.words ? '・' + d.words : '') + (d.step ? '・最近：' + d.step : '')};
  }
  function waitLine(m) {
    if (!m || m.role === 'user') return '';
    const j = Object.values(state.jobDetails).find(x => x.messageId === m.id);
    if (!j) return '';
    const asked = state.stopAsked[j.id], stopping = j.stopping || (asked && j.status === 'running');
    if (!stopping) {
      if (asked) delete state.stopAsked[j.id];
      if (j.status !== 'running' || m.status !== 'running') return '';
    }
    const p = j.progress;
    const d = stopping ? {stop: asked || j.stoppingAt || Date.now()} : {since: new Date(j.createdAt).getTime(), last: p?.lastAt || '', words: progressWords(p), step: p?.step || '', hold: waitHeld(j) ? '1' : ''};
    const now = Date.now(), s = waitState(d, now);
    const attrs = Object.entries(d).filter(([, v]) => v !== '' && v != null).map(([k, v]) => `data-${k}="${esc(String(v))}"`).join(' ');
    return `<div class="wait-line${s.stuck ? ' stuck' : ''}" role="status" ${attrs}><span class="wait-text">${esc(s.text)}</span>${stopping ? `<button type="button" class="link" data-action="force-stop" data-id="${esc(j.id)}"${s.late ? '' : ' hidden'}>強制停止</button>` : ''}</div>`;
  }
  // The time goes on between polls: only the lines' words change, the page is not redrawn.
  setInterval(() => {
    const now = Date.now();
    document.querySelectorAll('.wait-line').forEach(el => {
      const s = waitState(el.dataset, now), text = el.querySelector('.wait-text'), button = el.querySelector('button');
      if (text && text.textContent !== s.text) text.textContent = s.text;
      el.classList.toggle('stuck', !!s.stuck);
      if (button) button.hidden = !s.late;
    });
  }, 1000);
  // ■ pressed: 「正在停止…」 at once, while the Mac is asked.
  function stopAsked(jobId) { state.stopAsked[jobId] = Date.now(); render(true); }
  async function forceStop(jobId) {
    await post('jobs/' + encodeURIComponent(jobId) + '/cancel', {force: true});
    toast('已強制停止');
  }
