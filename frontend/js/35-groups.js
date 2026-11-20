  // Group discussions: host, discussion mode, turn limit, conclusion cards, cross-checks and shared files.
  const GROUP_MODE_OPTIONS = [{id: 'free', name: '自由', hint: '相關成員回覆，可以互相 @'}, {id: 'turns', name: '輪流', hint: '依序各發言一次'}, {id: 'debate', name: '辯論', hint: '正反交鋒，最後裁定'}, {id: 'split', name: '分工', hint: '拆開工作，最後彙整'}, {id: 'compare', name: '比較', hint: '各自獨立回答，列出異同'}];
  if (!state.groupMode) state.groupMode = {};
  if (!state.groupFiles) state.groupFiles = {};
  const currentGroupMode = g => { const mode = state.groupMode[g.id] || g.mode || 'free'; return mode === 'auto' && !taskEngineOn() ? 'free' : mode; };
  const groupHostId = g => 'hostId' in g ? g.hostId : (groupMembers(g).find(b => b.isAdmin)?.id || '');
  const hostOptions = ids => [{id: '', name: '不設主持人'}, ...ids.map(id => state.data.bots.find(b => b.id === id)).filter(Boolean).map(b => ({id: b.id, name: b.name}))];
  function groupSettingRows(g, chosen) {
    const host = g.id ? groupHostId(g) : '', limit = g.turnLimit || (host ? 16 : 8);
    return `<div class="setting-list in-form"><div data-host-field>${settingRow('主持人', '負責開場分派、收斂討論和總結', dropdown('hostId', host, hostOptions([...chosen])))}</div>${settingRow('討論方式', '對話框旁可以只改一則訊息', dropdown('mode', g.mode === 'auto' && !taskEngineOn() ? 'free' : g.mode || 'free', groupModeOptions()))}${settingRow('回合上限', '每則訊息最多幾次發言，到了就先停下', dropdown('turnLimit', String(limit), [4, 8, 12, 16].map(n => ({id: String(n), name: n + ' 次'}))))}</div>`;
  }
  function syncGroupHost(form) {
    const ids = new FormData(form).getAll('botIds'), slot = form.querySelector('[data-host-field]'), now = form.elements.hostId.value;
    slot.innerHTML = settingRow('主持人', '負責開場分派、收斂討論和總結', dropdown('hostId', ids.includes(now) ? now : '', hostOptions(ids)));
  }
  const groupModeControl = g => `<div class="effort-pick group-mode" title="討論方式">${dropdown('groupMode', currentGroupMode(g), groupModeOptions())}</div>`;

  // 預計用量: updated while typing, and never uses a model.
  function groupEstimateLine(g) {
    const key = g.id + currentGroupMode(g);
    if (state.groupEstimate?.key !== key) setTimeout(updateGroupEstimate, 0);
    return `<div class="group-estimate" id="group-estimate">${esc(state.groupEstimate?.key === key ? state.groupEstimate.text : '')}</div>`;
  }
  async function updateGroupEstimate() {
    const g = activeGroup();
    if (!g) return;
    const key = g.id + currentGroupMode(g);
    try {
      const e = await post('groups/' + encodeURIComponent(g.id) + '/estimate', {content: $('#chat-input')?.value || '', mode: currentGroupMode(g)});
      const text = `預計${e.upTo ? '最多 ' : ' '}${e.replies} 次回覆${e.tokens ? ` · 約 ${fmtN(e.tokens)} Token` : ''}`;
      state.groupEstimate = {key, text};
      const el = $('#group-estimate');
      if (el && activeGroup()?.id === g.id) el.textContent = text;
    } catch (_) {}
  }
  function scheduleGroupEstimate() { clearTimeout(scheduleGroupEstimate.timer); scheduleGroupEstimate.timer = setTimeout(updateGroupEstimate, 400); }

  function groupRunBar(g) {
    if (g.status === 'running') return '';
    if (g.paused) return `<div class="group-bar"><span>已達回合上限，討論還沒結束。</span><button type="button" class="secondary small-btn" data-action="group-discard">結束</button><button type="button" class="primary small-btn" data-action="group-continue">繼續</button></div>`;
    let after = g.afterAsk;  // worked out over the whole discussion by the Mac, since the page may hold only its newest part
    if (!after) { const messages = groupMsgs(g), lastAsk = messages.map(m => m.role).lastIndexOf('user'), since = messages.slice(lastAsk + 1).filter(m => m.role === 'assistant' && m.content && !m.checkOf); after = {replies: since.length, card: since.some(m => m.card)}; }
    return after.replies >= 2 && !after.card ? `<div class="group-bar"><span></span><button type="button" class="secondary small-btn" data-action="group-summarize">整理結論（多用一次模型請求）</button></div>` : '';
  }

  const CARD_PARTS = [['conclusion', '結論'], ['decisions', '需要你決定'], ['actions', '待辦'], ['questions', '仍有疑問']];
  const cardText = card => [card.body, ...CARD_PARTS.filter(([k]) => card[k]).map(([k, name]) => `【${name}】\n${card[k]}`)].filter(Boolean).join('\n\n');
  function groupCardView(m) {
    return `<div class="group-card">${m.card.body ? `<section><div class="md">${markdown(m.card.body)}</div></section>` : ''}${CARD_PARTS.filter(([k]) => m.card[k]).map(([k, name]) => `<section><h4>${name}</h4><div class="md">${markdown(m.card[k])}</div></section>`).join('')}<div class="group-card-actions"><button type="button" class="link" data-action="card-copy" data-id="${esc(m.id)}">複製</button><button type="button" class="link" data-action="card-save" data-id="${esc(m.id)}">存到知識庫</button></div></div>`;
  }
  function groupChecks(g, m) {
    const checks = groupMsgs(g).filter(x => x.checkOf === m.id);
    if (!checks.length) return '';
    const cls = {'同意': 'ok', '有疑慮': 'warn', '有錯誤': 'bad'};
    return `<div class="group-checks">${checks.map(c => {
      const b = state.data.bots.find(x => x.id === c.botId);
      if (c.status === 'running') return `<div class="group-check"><strong>${esc(b?.name || '成員')}</strong> 正在查核…</div>`;
      if (!c.content) return `<div class="group-check muted">${esc(b?.name || '成員')} 沒有完成查核</div>`;
      return `<div class="group-check"><div class="group-check-head"><strong>${esc(b?.name || '成員')} 查核</strong><span class="pill ${cls[c.verdict] || ''}">${esc(c.verdict || '未判定')}</span></div><div class="md">${markdown(c.content.replace(/【判定】\s*(同意|有疑慮|有錯誤)/, '').trim())}</div></div>`;
    }).join('')}</div>`;
  }
  const groupVerifyButton = (g, m) => g.status !== 'running' && m.status === 'completed' && m.content ? `<div class="msg-actions"><button type="button" class="link" data-action="group-verify" data-id="${esc(m.id)}">請其他成員查核</button></div>` : '';

  async function verifyGroupMessage(g, id) {
    const path = 'groups/' + encodeURIComponent(g.id) + '/messages/' + encodeURIComponent(id) + '/verify';
    let result = await post(path, {});
    if (result.needsConfirm) { if (!confirm(result.message)) return; result = await post(path, {confirm: true}); }
    await refresh(); pollGroup(g.id);
  }

  // 檔案 tab of the group's detail panel.
  const fileSize = n => n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(0) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  async function loadGroupFiles(g) {
    try { state.groupFiles[g.id] = (await api('groups/' + encodeURIComponent(g.id) + '/files')).files; }
    catch (error) { state.groupFiles[g.id] = []; toast(error.message); }
    render(true);
  }
  function groupFilesTab(g) {
    const files = state.groupFiles[g.id];
    if (!files) { setTimeout(() => loadGroupFiles(g), 0); return '<div class="detail-empty">正在讀取檔案…</div>'; }
    const base = '/api/groups/' + encodeURIComponent(g.id) + '/files/';
    return `<div class="group-files"><button type="button" class="secondary" data-action="group-file-pick">＋ 上傳檔案</button><input type="file" id="group-file-input" multiple hidden>${files.length ? files.map(f => `<div class="group-file"><a href="${base}${encodeURIComponent(f.name)}" download="${esc(f.name)}" title="下載"><strong>${esc(f.name)}</strong><small>${esc([fileSize(f.size), f.by].filter(Boolean).join(' · '))}</small></a><button type="button" class="link danger" data-action="group-file-delete" data-id="${esc(f.name)}">刪除</button></div>`).join('') : '<div class="detail-empty">還沒有檔案。成員都能讀取和存入。</div>'}<small class="muted">單檔 20 MB，每個群組 200 MB。</small></div>`;
  }
  async function uploadGroupFiles(g, list) {
    for (const f of list) {
      const res = await fetch('/api/groups/' + encodeURIComponent(g.id) + '/files', {method: 'POST', headers: {'X-File-Name': encodeURIComponent(f.name), 'Content-Type': 'application/octet-stream'}, body: f});
      if (!res.ok) { toast((await res.json().catch(() => ({}))).error || '上傳失敗'); break; }
    }
    await loadGroupFiles(g);
  }

  // A member's own window on a group discussion: for each time it spoke, what it looked up and which Skills it used on the way,
  // and then the conclusion it put into the group. The group itself only shows the conclusions.
  // Every time the member spoke comes from the Mac (the page may hold only the newest part of the discussion); it is asked for
  // again whenever the discussion has moved on.
  state.memberTurns = state.memberTurns || {};
  async function loadMemberTurns(g, b, older) {
    const key = g.id + ':' + b.id, had = state.memberTurns[key], busy = state.memberLoading = state.memberLoading || {};
    if (busy[key]) return;
    busy[key] = true;
    try {
      const first = older && had?.turns[0];
      const out = await api(`groups/${encodeURIComponent(g.id)}/messages?member=${encodeURIComponent(b.id)}${first ? '&before=' + encodeURIComponent(first.id) : ''}`);
      state.memberTurns[key] = first ? {turns: out.turns.concat(had.turns), more: out.more, mark: had.mark} : {turns: out.turns, more: out.more, mark: memberMark(g)};
    } catch (err) { toast(err.message); state.memberTurns[key] = Object.assign(had || {turns: [], more: false}, {mark: memberMark(g)}); }  // not asked again until the discussion moves on
    delete busy[key];
    render(true);
  }
  const memberMark = g => { const last = (g.messages || []).slice(-1)[0]; return [g.status, last?.id, last?.status, (g.messages || []).length + (g.olderCount || 0)].join('|'); };
  document.addEventListener('click', e => { const el = e.target.closest?.('[data-member-older]'); if (el && state.memberWork) { const g = state.data.groups.find(x => x.id === state.memberWork.group), b = state.data.bots.find(x => x.id === state.memberWork.bot); if (g && b) loadMemberTurns(g, b, true); } });
  function memberWork(b, g) {
    const jobs = {}; for (const j of Object.values(state.jobDetails)) if (j.groupId === g.id && j.botId === b.id) jobs[j.messageId] = j;
    const got = state.memberTurns[g.id + ':' + b.id];
    if (!got || got.mark !== memberMark(g)) setTimeout(() => loadMemberTurns(g, b), 0);
    const said = got?.turns || [];
    const turns = said.map(m => {
      const job = jobs[m.id], calls = job?.toolCalls || [], q = m.asked;
      const steps = calls.length ? `<div class="work-steps">${toolTimeline(b.id, [job])}</div>` : `<div class="work-none">${job && !job.slim ? '這次沒有查資料或使用 Skill，直接回覆。' : '這次的過程紀錄已經整理掉了（只保留最近的回覆）。'}</div>`;
      const end = m.status === 'running' ? '<div class="bubble">正在進行…</div>' : m.content ? `<div class="bubble md">${markdown(m.content)}</div>` : `<div class="bubble">${esc(m.status === 'cancelled' ? '已停止' : '沒有回覆')}</div>`;
      return `<div class="date">${esc(formatDate(m.createdAt))}</div>${q ? `<div class="work-ask"><span>${esc(q.author || '你')} 在群組說</span>${esc(String(q.content || '').slice(0, 300))}</div>` : ''}<div class="work-turn"><div class="work-label">過程</div>${steps}<div class="work-label">丟回群組的結論</div><div class="message assistant">${avatar(b)}${end}</div></div>`;
    }).join('');
    return `<main class="main"><header class="main-header"><button class="bot-pill" data-action="edit-bot">${avatar(b)}${esc(b.name)} <span class="muted">⌄</span></button><div class="header-actions"><button class="text-btn" data-member-work="" data-back="group" data-group="${esc(g.id)}">‹ 回到群組</button><button class="text-btn" data-member-work="">和 ${esc(b.name)} 的對話</button>${!state.detailOpen ? '<button class="text-btn" data-action="toggle-detail">顯示詳情</button>' : ''}</div></header><div class="conversation" id="conversation"><div class="conversation-inner"><div class="work-head">${esc(b.name)} 在「${esc(g.name)}」的工作過程<small>這裡看得到他每次發言前做了什麼；群組裡只會出現結論。</small></div>${got?.more ? '<div class="older-bar"><button class="link" data-member-older="1">載入更早的發言</button></div>' : ''}${turns || `<div class="detail-empty">${got ? '他還沒有在這個討論中發言。' : '正在讀取…'}</div>`}</div></div></main>${state.detailOpen ? detail(b) : ''}`;
  }
  document.addEventListener('click', e => {
    const row = e.target.closest('[data-member-work]');
    if (!row) return;
    const bot = row.dataset.memberWork, group = row.dataset.group;
    if (bot) { state.memberWork = {bot, group}; state.groupId = null; state.selected = bot; state.page = 'chat'; }
    else { state.memberWork = null; if (row.dataset.back === 'group' && group) { state.groupId = group; state.page = 'chat'; } }
    render();
  });
