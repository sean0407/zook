  // 成員卡住 (#307): while a member answers in a group, its own page shows what it is doing right now (progress.py): the time and
  // what its CLI reported so far, the step it is in, the last files it read or changed, and the last words it wrote. Only what the
  // Mac reports; nothing is made up. After 15 minutes with none of that, Zook stops that part and its backup model redoes it (stall.py).
  function memberLiveBox(j) {
    const p = j.progress || {};
    const d = {since: new Date(j.createdAt).getTime(), last: p.lastAt || '', words: progressWords(p), step: p.step || '', hold: waitHeld(j) ? '1' : ''};
    const s = waitState(d, Date.now()), attrs = Object.entries(d).filter(([, v]) => v !== '' && v != null).map(([k, v]) => `data-${k}="${esc(String(v))}"`).join(' ');
    const row = (label, body) => `<div class="live-row"><span class="live-label">${label}</span><span class="live-body">${body}</span></div>`;
    const files = (p.files || []).slice().reverse().map(f => `${f.w === 'write' ? '修改' : '讀取'}「${esc(f.name)}」`).join('、');
    const out = liveTail(j.messageId);
    return `<div class="member-live"><div class="wait-line${s.stuck ? ' stuck' : ''}" role="status" ${attrs}><span class="wait-text">${esc(s.text)}</span></div>${row('正在', esc(p.now || p.step || '思考'))}${files ? row('最近的檔案', files) : ''}${row('最近的輸出', `<span class="live-out" data-live-mid="${esc(j.messageId || '')}">${esc(out || '還沒有輸出')}</span>`)}<small class="muted">15 分鐘完全沒有動作時，Zook 會停下這一份，改用備用模型重做。</small></div>`;
  }
  // The reply's own words so far (the same words its bubble in the group shows), a full path cut to the file's name.
  const liveTail = mid => { const t = String((state.partials || {})[mid] || '').replace(/(?:~|\/(?:Users|private|tmp|var|Volumes|opt|Applications|Library|home))(?:\/[^\s/`'"「」）)]+)*\/([^\s/`'"「」）)]+)/g, '$1').trim(); return t.length > 400 ? '…' + t.slice(-400) : t; };
  // The words arrive with each poll of the group; only this line changes, the page is not redrawn.
  setInterval(() => document.querySelectorAll('.live-out[data-live-mid]').forEach(el => { const t = liveTail(el.dataset.liveMid); if (t && el.textContent !== t) el.textContent = t; }), 1500);
  // The Bot's own page while it answers in a group: what it is doing, and the way to its whole work there.
  function memberBusy(b) {
    const j = Object.values(state.jobDetails || {}).find(x => x.botId === b.id && x.groupId && x.status === 'running');
    const g = j && (state.data.groups || []).find(x => x.id === j.groupId);
    if (!g) return '';
    return `<div class="member-busy"><div class="member-busy-head"><strong>正在群組「${esc(g.name)}」回覆</strong><button type="button" class="link" data-member-work="${esc(b.id)}" data-group="${esc(g.id)}">看完整的工作過程</button></div>${memberLiveBox(j)}</div>`;
  }
