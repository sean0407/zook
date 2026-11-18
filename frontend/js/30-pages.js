  // ---- Attachments: each file is uploaded as soon as it is added, then sent with the message.
  if (!state.pendingBy) state.pendingBy = {};  // files waiting to be sent, per Bot or group
  const pendingList = () => state.pendingBy[effortKey()] || (state.pendingBy[effortKey()] = []);
  const kb = n => n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1024 / 1024).toFixed(1) + ' MB';
  function pendingFiles() {
    if (!pendingList().length) return '';
    return `<div class="pending-files">${pendingList().map(f => `<div class="pending-file">${f.url ? `<img src="${esc(f.url)}" alt="">` : '<span class="file-icon">📄</span>'}<span class="pending-name">${esc(f.name)}<small>${f.uploading ? '上傳中…' : kb(f.size)}</small></span><button type="button" class="icon-btn mini" data-action="unattach" data-id="${esc(f.key)}" aria-label="移除 ${esc(f.name)}">×</button></div>`).join('')}</div>`;
  }
  function attachmentsView(m) {
    if (!m.attachments || !m.attachments.length) return '';
    return `<div class="attachments">${m.attachments.map(a => a.kind === 'image'
      ? `<button type="button" class="att-image" data-action="view-image" data-id="${esc(a.id)}" data-name="${esc(a.name)}"><img src="/api/uploads/${esc(a.id)}" alt="${esc(a.name)}"></button>`
      : `<a class="att-file" href="/api/uploads/${esc(a.id)}" download="${esc(a.name)}">📄 ${esc(a.name)}</a>`).join('')}</div>`;
  }
  async function addFiles(files) {
    const list = pendingList();
    for (const f of files) {
      if (list.length >= 10) { toast('每則訊息最多 10 個檔案'); break; }
      if (f.size > 20 * 1024 * 1024) { toast(`「${f.name}」超過 20 MB，沒有加入`); continue; }
      if (!f.size) { toast(`「${f.name}」是空的`); continue; }
      const stamp = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
      const name = f.name && f.name !== 'image.png' ? f.name : `截圖-${stamp}.png`;
      const item = {key: Math.random().toString(36).slice(2), name, size: f.size, uploading: true, url: /^image\//.test(f.type) ? URL.createObjectURL(f) : ''};
      list.push(item); render(true);
      try {
        const res = await fetch('/api/uploads', {method: 'POST', headers: {'X-File-Name': encodeURIComponent(name), 'Content-Type': 'application/octet-stream'}, body: f});
        const meta = await res.json();
        if (!res.ok) throw new Error(meta.error || '上傳失敗');
        Object.assign(item, {id: meta.id, kind: meta.kind, uploading: false});
      } catch (e) { list.splice(list.indexOf(item), 1); toast(`「${name}」${e.message}`); }
      render(true);
    }
  }
  document.addEventListener('paste', e => {
    const files = [...(e.clipboardData?.files || [])];
    if (!files.length || e.target.id !== 'chat-input') return;
    e.preventDefault(); addFiles(files);
  });
  // Files dragged onto the conversation; the sidebar's own drag and drop is left alone.
  document.addEventListener('dragover', e => {
    if (![...(e.dataTransfer?.types || [])].includes('Files')) return;
    e.preventDefault();
    if (e.target.closest?.('.main') && $('#chat-form')) { e.dataTransfer.dropEffect = 'copy'; $('.composer-wrap')?.classList.add('drop-files'); }
    else e.dataTransfer.dropEffect = 'none';
  }, true);
  document.addEventListener('dragleave', e => { if (!e.relatedTarget) $('.composer-wrap')?.classList.remove('drop-files'); });
  document.addEventListener('drop', e => {
    if (!e.dataTransfer?.files?.length) return;
    e.preventDefault(); e.stopPropagation(); $('.composer-wrap')?.classList.remove('drop-files');
    if (e.target.closest?.('.main') && $('#chat-form')) addFiles([...e.dataTransfer.files]);
  }, true);
  // Under the last question: 編輯. Under the last reply: 重新回答 and 換模型重答. Not while a reply is running.
  function redoBar(b, m, running) {
    if (running) return '';
    const msgs = b.messages || [], lastUser = [...msgs].reverse().find(x => x.role === 'user');
    if (!lastUser) return '';
    if (m.id === lastUser.id) return '<div class="msg-actions user-actions"><button type="button" class="link" data-action="edit-last">編輯</button></div>';
    if (m.role !== 'user' && m.id === msgs[msgs.length - 1]?.id && m.status !== 'running')
      return '<div class="msg-actions">' + (m.plan && m.status === 'completed' ? '<button type="button" class="primary small-btn" data-action="run-plan">照計畫執行</button>' : '') + '<button type="button" class="link" data-action="redo-again">重新回答</button><button type="button" class="link" data-action="redo-model">換模型重答</button></div>';
    return '';
  }
  // Redoing cannot undo what the last reply already did (files changed, mail sent): say so first.
  function redoAllowed(b) {
    const reply = (b.messages || []).filter(m => m.role !== 'user').slice(-1)[0];
    const job = reply && Object.values(state.jobDetails).find(j => j.messageId === reply.id);
    const acted = (job?.toolCalls || []).some(c => c.status === 'completed' && !['read', 'external_read'].includes(c.category));
    return !acted || confirm('上一次回覆做過的動作不會復原。確定要重來？');
  }
  async function redo(b, body) {
    const sent = await post('chat/redo', {...body, botId: b.id});
    await refresh(); poll(sent.jobId, b.id);
  }
  // Conversations of a Bot: the open one is b.messages, the others carry their own messages.
  const chatName = (b, c) => { c = c || (b.chats || []).find(x => x.id === b.chatId) || {}; return c.title || (c.kind === 'schedule' ? '排程' : '新對話'); };
  const chatMessages = (b, c) => c.id === b.chatId ? (b.messages || []) : (c.messages || []);
  function chatsModal(b, query = '') {
    const q = query.trim().toLowerCase();
    const chats = [...(b.chats || [])].sort((x, y) => String(y.updatedAt || '').localeCompare(String(x.updatedAt || '')))
      .filter(c => !q || chatName(b, c).toLowerCase().includes(q) || chatMessages(b, c).some(m => String(m.content || '').toLowerCase().includes(q)));
    const rows = chats.map(c => `<div class="chat-row ${c.id === b.chatId ? 'current' : ''}"><button type="button" class="chat-open" data-action="open-chat" data-id="${esc(c.id)}"><strong>${esc(chatName(b, c))}</strong><small>${esc(formatDate(c.updatedAt))} · ${chatMessages(b, c).filter(m => m.role === 'user').length} 則</small></button><button type="button" class="link" data-action="rename-chat" data-id="${esc(c.id)}">改名</button><button type="button" class="link danger-link" data-action="delete-chat" data-id="${esc(c.id)}">刪除</button></div>`).join('');
    modal(`${b.name} 的對話`, `<div class="modal-body"><input id="chat-search" class="chat-search" placeholder="搜尋這個 Bot 的對話" value="${esc(query)}" aria-label="搜尋對話"><div class="chat-list">${rows || '<p class="muted">沒有符合的對話。</p>'}</div></div>`, '<div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">關閉</button><button type="button" class="primary" data-action="new-chat">＋ 新對話</button></div>');
  }
  // Messages across every Bot's conversations that match the sidebar search.
  function messageHits() {
    if (!state.query) return [];
    const hits = [];
    for (const b of state.data.bots) for (const c of b.chats || []) for (const m of chatMessages(b, c)) {
      if (m.content && matches(m.content)) hits.push({b, c, m});
      if (hits.length >= 30) return hits;
    }
    return hits;
  }
  function snippet(text) {
    const t = String(text || '').replace(/\s+/g, ' '), i = t.toLowerCase().indexOf(state.query.toLowerCase());
    return (i > 30 ? '…' : '') + t.slice(Math.max(0, i - 30), i + 60);
  }
  const RUN_STATUS = {running: '執行中', done: '已執行', failed: '失敗', missed: '錯過'};
  function scheduleHistory(x) {
    const rows = [...(x.runs || [])].reverse().map(r => {
      const open = r.messageId && r.status !== 'missed';
      return `<${open ? 'button type="button"' : 'div'} class="run-row ${open ? '' : 'static'}" ${open ? `data-action="open-run" data-kind="${esc(r.kind)}" data-target="${esc(r.targetId)}" data-id="${esc(r.messageId)}"` : ''}><span class="run-when">${esc(formatDate(r.at))}</span><span class="run-status ${esc(r.status)}">${esc(RUN_STATUS[r.status] || r.status)}</span><span class="run-text">${esc(r.reason || r.summary || '')}</span>${open ? '<span class="run-go" aria-hidden="true">›</span>' : ''}</${open ? 'button' : 'div'}>`;
    }).join('');
    modal('執行紀錄', `<div class="modal-body"><p class="muted">最近 ${(x.runs || []).length} 次。點一筆會打開那次的對話。</p><div class="run-list">${rows}</div></div>`, '<div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">關閉</button></div>');
  }
  // Open a Bot's or group's conversation at a message (from the history list or a Mac notification).
  async function openConversation(kind, id, messageId) {
    const exists = kind === 'group' ? (state.data.groups || []).some(g => g.id === id) : state.data.bots.some(b => b.id === id);
    if (!exists) { toast(kind === 'group' ? '找不到這個群組' : '找不到這個 Bot'); return; }
    if (kind !== 'group' && messageId) {
      const b = state.data.bots.find(x => x.id === id);
      const c = (b.chats || []).find(c => chatMessages(b, c).some(m => m.id === messageId));
      if (c && c.id !== b.chatId) { await post(`bots/${encodeURIComponent(id)}/chats/${encodeURIComponent(c.id)}/open`, {}); await refresh(); }
    }
    if (state.modal) closeModal();
    if (kind === 'group') state.groupId = id; else { state.groupId = null; state.selected = id; }
    state.page = 'chat'; state.launcher = false;
    state.focus = messageId ? {id: messageId, until: Date.now() + 5000} : null;
    render();
  }
  // Keep a message that was jumped to in view for a moment, even when replies arrive and the page redraws.
  document.addEventListener('wheel', () => { state.focus = null; }, {passive: true});  // scrolling yourself ends it
  function keepFocus() {
    if (!state.focus || Date.now() > state.focus.until) { state.focus = null; return false; }
    const el = [...document.querySelectorAll('[data-mid]')].find(x => x.dataset.mid === state.focus.id);
    if (!el) return false;
    el.scrollIntoView({block: 'center', behavior: 'instant'}); el.classList.add('flash');
    return true;
  }
  window.zookOpen = async (kind, id, messageId) => {  // from a Mac notification: the reply may be newer than this page
    try { await refresh(); startPollers(); } catch (_) {}
    if (state.data && kind === 'page') await loadPage(id);
    else if (state.data) await openConversation(kind, id, messageId);
  };
  // Who a schedule talks to: a Bot or a group, with its avatar.
  function scheduleTarget(x) {
    if (x.groupId) { const g = (state.data.groups || []).find(g => g.id === x.groupId); return `<span class="sched-target">${g ? avatarStack(g) + esc(g.name) : '找不到群組'}</span>`; }
    const b = state.data.bots.find(b => b.id === x.botId);
    return `<span class="sched-target">${b ? avatar(b) + esc(b.name) : '找不到 Bot'}</span>`;
  }
  const scheduleTargets = () => [...state.data.bots.map(b => ({id: 'bot:' + b.id, name: b.name})), ...(state.data.groups || []).map(g => ({id: 'group:' + g.id, name: g.name, hint: '群組'}))];
  function scheduleModal(x = {}) {
    if (!state.data.bots.length) { toast('請先建立一個 Bot'); return; }
    const two = n => String(n).padStart(2, '0'), [h, m] = (x.time || '10:00').split(':');
    const minutes = [...new Set([...Array.from({length: 12}, (_, i) => two(i * 5)), m])].sort();
    const iso = d => `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
    const days = Array.from({length: 120}, (_, i) => { const d = new Date(); d.setDate(d.getDate() + i); return iso(d); });
    if (x.date && !days.includes(x.date)) days.unshift(x.date);
    const dates = days.map((d, i) => ({id: d, name: (i === 0 && d === iso(new Date()) ? '今天 ' : i === 1 ? '明天 ' : '') + dayLabel(d)}));
    const target = x.groupId ? 'group:' + x.groupId : x.botId ? 'bot:' + x.botId : state.page === 'chat' && state.groupId ? 'group:' + state.groupId : 'bot:' + ((state.page === 'chat' && state.selected) || state.data.bots[0].id);
    modal(x.id ? '編輯排程' : '新增排程', `<form id="schedule-form"><div class="modal-body"><div class="field">對象${dropdown('target', target, scheduleTargets())}</div><label class="field">要做的事<textarea name="content" required placeholder="例如：整理今天的行事曆和未讀信件，列出三件最重要的事">${esc(x.content || '')}</textarea></label><div class="sched-when" data-repeat="${esc(x.repeat || 'daily')}"><div class="field">重複${dropdown('repeat', x.repeat || 'daily', REPEATS.map(r => ({id: r[0], name: r[1]})))}</div><div class="field when-date">日期${dropdown('date', x.date || dates[0].id, dates)}</div><div class="field when-day">日${dropdown('day', String(x.day || new Date().getDate()), Array.from({length: 31}, (_, i) => ({id: String(i + 1), name: (i + 1) + ' 號', hint: i >= 28 ? '沒有這天的月份在月底執行' : ''})))}</div><div class="field when-hour">時${dropdown('hour', h, Array.from({length: 24}, (_, i) => ({id: two(i), name: two(i)})))}</div><div class="field">分${dropdown('minute', m, minutes.map(v => ({id: v, name: v})))}</div></div><div class="setting-list in-form">${settingRow('啟用', '關閉後不會自動執行。', toggle('name="on"', x.on !== false, '啟用'))}${settingRow('錯過時補跑', '錯過時，24 小時內開啟會補做一次。', toggle('name="catchUp"', x.catchUp !== false, '錯過時補跑'))}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">儲存</button></div></form>`);
    $('#schedule-form').dataset.id = x.id || '';
  }
  function noteModal(n = {}) {
    modal(n.id ? '編輯知識' : '新增知識', `<form id="note-form"><div class="modal-body"><label class="field">標題<input name="title" required value="${esc(n.title||'')}"></label><label class="field">內容<textarea name="content" required>${esc(n.content||'')}</textarea></label><label class="field">標籤（以逗號分隔）<input name="tags" value="${esc((n.tags||[]).join(', '))}"></label><label class="field">關聯 Bot<select name="botId"><option value="">共用知識</option>${state.data.bots.map(b=>`<option value="${esc(b.id)}" ${(n.botId||(!n.id&&state.page==='chat'?state.selected:''))===b.id?'selected':''}>${esc(b.name)}</option>`).join('')}</select></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">儲存</button></div></form>`);
    $('#note-form').dataset.id = n.id || ''
  }
  function startPollers() {
    for (const j of state.data.jobs || [])
      if ((j.status === 'running' || j.status === 'queued') && !j.groupId && !state.pollers[j.id]) poll(j.id, j.botId);
    for (const g of state.data.groups || [])
      if (g.status === 'running') pollGroup(g.id)
  }
  // Conversations also change from outside this window (a paired phone, another Bot). Check regularly and redraw only when something differs.
  const syncKey = d => JSON.stringify([d.bots, d.groups, (d.jobs || []).map(j => [j.id, j.status])]);
  async function syncFromElsewhere() {
    if (state.syncing || !state.data || state.page !== 'chat' || document.querySelector('.modal') || document.querySelector('.dd.open')) return;
    state.syncing = true;
    const loads = state.loads;
    try {
      const data = await api('state');
      if (loads !== state.loads || syncKey(data) === syncKey(state.data)) return;  // this window reloaded meanwhile, or nothing new
      if (state.page !== 'chat' || document.querySelector('.modal') || document.querySelector('.dd.open')) return;
      applyState(data); startPollers();
    } catch (_) {} finally { state.syncing = false; }
  }
  async function refresh() {
    applyState(await api('state'));
  }
  function applyState(data) {
    state.data = data; state.loads = (state.loads || 0) + 1;
    if (!state.providers) api('providers').then(r => { state.providers = r.providers; }).catch(() => {});
    if (!state.data.bots) state.data.bots = [];
    if (!state.data.knowledge) state.data.knowledge = [];
    if (!state.data.schedules) state.data.schedules = [];
    if (!state.data.groups) state.data.groups = [];
    if (state.groupId && !activeGroup()) state.groupId = null;
    for (const job of state.data.jobs || []) state.jobDetails[job.id] = job;
    if (!state.selected || !activeBot()) state.selected = state.data.bots[0]?.id || null;
    render(true)
  }
  async function loadPage(p) {
    state.launcher = false;
    if (p === 'integrations') {
      await integrationsModal();
      return
    }
    state.page = p;
    loadUpkeep(p);
    if (p === 'skills' || p === 'mcp' || p === 'plugins') state.integrations = await api('integrations');
    if (p === 'usage') {
      // Open the page right away; each section fills in as its data arrives (earlier data stays on screen while refreshing).
      const seq = state.usageLoad = (state.usageLoad || 0) + 1;
      const fill = (key, request) => request.catch(e => ({error: e.message})).then(value => {
        if (state.usageLoad !== seq) return;
        state[key] = value;
        if (state.page !== 'usage') return;
        const pageEl = $('.page'), y = pageEl?.scrollTop;
        render(true);
        if (y) $('.page') && ($('.page').scrollTop = y);
      });
      render();
      fill('quota', api('quota?auto=1')); fill('botUsage', api('usage/bots')); fill('usage', api('usage'));
      loadAccounts().catch(e => toast(e.message));
      return;
    }
    if (p === 'settings') { state.remote = null; render(); loadRemote(); return; }
    render()
  }
  async function integrationsModal() {
    state.integrations = await api('integrations');
    let i = state.integrations;
    modal('連結應用程式', `<div class="modal-body"><p class="muted">這是偵測到的設定，不代表連線正常。</p><input id="integration-search" class="secondary" style="width:100%;text-align:left" placeholder="搜尋應用程式"><div class="tabs" style="margin:16px 0"><button class="active" data-action="int-filter" data-id="all">全部</button><button data-action="int-filter" data-id="providers">提供者</button><button data-action="int-filter" data-id="skills">Skills</button><button data-action="int-filter" data-id="mcp">MCP</button></div><div class="cards" id="integration-cards">${integrationCards(i,'all','')}</div></div>`, '', true)
  }

  function integrationCards(i, filter, q) {
    let all = ['providers', 'skills', 'mcp'].flatMap(k => (i?.[k] || []).map(x => ({
      ...x,
      kind: k
    }))).filter(x => (filter === 'all' || x.kind === filter) && (`${x.name} ${x.description||''}`.toLowerCase().includes(q.toLowerCase())));
    return all.length ? all.map(x => `<div class="card"><h3>${esc(x.name)}</h3><p>${esc(x.description||x.source||x.kind)}</p><span class="status">${esc(x.status|| (x.installed?'已偵測':'設定狀態未知'))}</span></div>`).join('') : '<div class="blank">沒有符合的項目。</div>'
  }

  function download(content, name, type) {
    let url = URL.createObjectURL(new Blob([content], {
      type
    }));
    let a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000)
  }
  async function poll(jobId, botId) {
    state.pollers[jobId] = { botId };
    try {
      let j = await api('jobs/' + encodeURIComponent(jobId));
      j.botId = botId;
      const changed = JSON.stringify(state.jobDetails[jobId]) !== JSON.stringify(j);
      state.jobDetails[jobId] = j;
      if (changed) render(true);
      if (j.status === 'running' || j.status === 'queued') {
        setTimeout(() => poll(jobId, botId), 1200);
        return
      }
      delete state.pollers[jobId];
      await refresh();
      if (j.status === 'completed') loadOutputs(botId, true);  // so new files show up, and their names in the reply open a preview
      if (j.status === 'failed') toast(j.error || '回覆失敗');
      if (j.status === 'cancelled') toast('已停止回覆')
    } catch (e) {
      delete state.pollers[jobId];
      toast(e.message);
      render(true)
    }
  }
  // Dropdown: open/close, pick an option, close on outside click or Escape.
  const closeDropdowns = except => document.querySelectorAll('.dd.open').forEach(d => { if (d !== except) { d.classList.remove('open'); d.querySelector('.dd-btn').setAttribute('aria-expanded', 'false'); } });
  // The launcher menu closes when anything outside it is clicked, or Escape is pressed.
  // Listened for on the way down, so a click that another handler stops (a dropdown) still closes it.
  // Only the menu itself is taken away: the rest of the page is left as it is, so whatever was clicked still works.
  document.addEventListener('click', e => {
    if (!state.launcher || e.target.closest?.('.launcher') || e.target.closest?.('[data-action="launcher"]')) return;
    state.launcher = false;
    document.querySelector('.launcher .popup')?.remove();
    document.querySelector('[data-action="launcher"]')?.setAttribute('aria-expanded', 'false');
  }, true);
  // The shape and colour picker in the Bot form closes the same way.
  document.addEventListener('click', e => {
    const panel = document.querySelector('#bot-form .avatar-panel');
    if (panel && !panel.hidden && !e.target.closest?.('.avatar-panel') && !e.target.closest?.('[data-action="avatar-pick"]')) panel.hidden = true;
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && state.launcher) { state.launcher = false; render(true); } });
  document.addEventListener('click', e => {
    const opt = e.target.closest?.('.dd-opt'), btn = e.target.closest?.('.dd-btn');
    if (btn) {
      const dd = btn.closest('.dd'), open = !dd.classList.contains('open');
      closeDropdowns(dd); dd.classList.toggle('open', open); btn.setAttribute('aria-expanded', String(open));
      if (open) {
        const r = btn.getBoundingClientRect(), menu = dd.querySelector('.dd-menu');
        menu.style.minWidth = Math.max(r.width, 220) + 'px';
        menu.style.top = (r.bottom + 6) + 'px';
        menu.style.left = Math.max(8, Math.min(r.right - Math.max(menu.offsetWidth, r.width, 220), innerWidth - menu.offsetWidth - 8)) + 'px';
        if (r.bottom + 6 + menu.offsetHeight > innerHeight - 8) menu.style.top = Math.max(8, r.top - 6 - menu.offsetHeight) + 'px';
      }
      e.stopPropagation(); return;
    }
    if (opt) {
      const dd = opt.closest('.dd'), input = dd.querySelector('input[type=hidden]');
      dd.querySelectorAll('.dd-opt').forEach(o => { o.classList.toggle('selected', o === opt); o.setAttribute('aria-selected', String(o === opt)); });
      dd.querySelector('.dd-label').textContent = opt.dataset.label;
      closeDropdowns();
      if (input.value !== opt.dataset.value) { input.value = opt.dataset.value; input.dispatchEvent(new Event('change', {bubbles: true})); }
      e.stopPropagation(); return;
    }
    if (!e.target.closest?.('.dd-menu')) closeDropdowns();
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.querySelector('.dd.open')) { closeDropdowns(); e.stopPropagation(); } }, true);
  document.addEventListener('scroll', e => { if (!e.target.closest?.('.dd-menu')) closeDropdowns(); }, true);

  // Sidebar drag and drop.
  let dragging = null;
  const clearDropMarks = () => document.querySelectorAll('.drop-before, .drop-after, .drop-into').forEach(el => el.classList.remove('drop-before', 'drop-after', 'drop-into'));
  document.addEventListener('dragstart', e => {
    const bot = e.target.closest?.('[data-drag-bot]'), sec = e.target.closest?.('[data-drag-section]');
    if (bot) dragging = {kind: 'bot', id: bot.dataset.dragBot};
    else if (sec) dragging = {kind: 'section', id: sec.dataset.dragSection};
    else return;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragging.id);
    requestAnimationFrame(() => (bot || sec.closest('.side-section'))?.classList.add('dragging'));
  });
  document.addEventListener('dragend', () => { dragging = null; clearDropMarks(); document.querySelectorAll('.dragging').forEach(el => el.classList.remove('dragging')); });
  function dropTarget(e) {
    if (!dragging) return null;
    const section = e.target.closest?.('[data-drop-section]');
    if (!section) return null;
    if (dragging.kind === 'section') {
      if (section.dataset.dropSection === '__pinned') return null;
      const r = section.getBoundingClientRect();
      return {el: section, cls: e.clientY < r.top + r.height / 2 ? 'drop-before' : 'drop-after', section: section.dataset.dropSection};
    }
    const row = e.target.closest('[data-drag-bot]');
    if (row && row.dataset.dragBot !== dragging.id) {
      const r = row.getBoundingClientRect();
      return {el: row, cls: e.clientY < r.top + r.height / 2 ? 'drop-before' : 'drop-after', section: section.dataset.dropSection, botId: row.dataset.dragBot};
    }
    return {el: section, cls: 'drop-into', section: section.dataset.dropSection};
  }
  document.addEventListener('dragover', e => {
    const t = dropTarget(e);
    if (!t) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    if (!t.el.classList.contains(t.cls)) { clearDropMarks(); t.el.classList.add(t.cls); }
  });
  document.addEventListener('drop', async e => {
    const t = dropTarget(e), what = dragging;
    clearDropMarks();
    if (!t) return;
    e.preventDefault(); dragging = null;
    if (what.kind === 'section') {
      const names = sectionNames().filter(x => x !== what.id);
      let i = names.indexOf(t.section); if (i < 0) return;
      names.splice(t.cls === 'drop-after' ? i + 1 : i, 0, what.id);
      return saveArrangement(state.data.bots, names);
    }
    const moving = state.data.bots.find(b => b.id === what.id);
    if (!moving) return;
    const moved = t.section === '__pinned' ? {...moving, pinned: true} : {...moving, pinned: false, section: t.section};
    const rest = state.data.bots.filter(b => b.id !== what.id);
    let at;
    if (t.botId) { at = rest.findIndex(b => b.id === t.botId) + (t.cls === 'drop-after' ? 1 : 0); }
    else {
      // Dropped on the group itself: put it after the group's last Bot.
      const inGroup = b => t.section === '__pinned' ? b.pinned : !b.pinned && (b.section || '我的 Bots') === t.section;
      const last = rest.map(inGroup).lastIndexOf(true);
      at = last >= 0 ? last + 1 : rest.length;
    }
    rest.splice(at, 0, moved);
    await saveArrangement(rest, sectionNames());
  });

  // Window dragging: empty space in the sidebar top and page headers moves the window; double-click zooms it.
  // The app shell gets the header areas and the controls inside them, and handles the press itself.
  const DRAG_AREA = '.side-top, .main-header', NOT_DRAG = 'button, a, input, textarea, select, label, [data-action], [contenteditable]';
  let dragFrame = 0;
  const box = el => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
  const reportDragAreas = () => {
    dragFrame = 0;
    const areas = [...document.querySelectorAll(DRAG_AREA)];
    window.webkit?.messageHandlers?.zookWindow?.postMessage({drag: areas.map(box), block: areas.flatMap(a => [...a.querySelectorAll(NOT_DRAG)]).map(box)});
  };
  const scheduleDragAreas = () => { if (!dragFrame) dragFrame = setTimeout(reportDragAreas, 30); };  // timers keep running when the window is covered
  new MutationObserver(scheduleDragAreas).observe(document.documentElement, {childList: true, subtree: true});
  window.addEventListener('resize', scheduleDragAreas);
