
  // Finding your way in a long conversation (Bot or group): a 「直接到底」 button above the message box, and on the right a rail
  // with a mark for every question, in time order. Pointing at a mark shows the question, the start of the reply and when it was
  // asked; clicking it goes there, loading older parts of the conversation first when they are not on the page yet.
  const outlines = {};  // "botId:chatId" or "group:<id>" -> {list, lastAsk, loading}: the whole conversation's outline, from the Mac
  const RAIL_MOST = 60;  // marks shown at most; a longer conversation shows an even spread that always includes the newest
  function navTarget() {
    if (state.page !== 'chat') return null;
    const g = state.groupId ? activeGroup() : null, b = g ? null : activeBot();
    return g ? {key: 'group:' + g.id, g} : b ? {key: b.id + ':' + b.chatId, b} : null;
  }
  const plainLine = (text, size) => { const flat = String(text || '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/```[\w-]*|[*_`#>|]+|^\s*[-+]\s+/gm, '').split(/\s+/).filter(Boolean).join(' '); return flat.length <= size ? flat : flat.slice(0, size) + '…'; };
  // The same outline the Mac makes (paging.py page_outline), from the messages already on the page.
  function localOutline(list) {
    const out = []; let last = null;
    for (const m of list) {
      if (m.role === 'user') { last = {id: m.id, createdAt: m.createdAt || '', author: m.author || '', title: plainLine(m.content, 60) || ((m.attachments || []).length ? '（附件）' : '（空白訊息）'), reply: '', replyBy: ''}; out.push(last); }
      else if (last && !last.reply && m.role === 'assistant' && m.content && m.status !== 'running' && !m.checkOf) { last.reply = plainLine(m.content, 90); last.replyBy = m.botId || ''; }
    }
    return out;
  }
  async function fetchOutline(t, lastAsk) {
    const known = outlines[t.key] = Object.assign(outlines[t.key] || {}, {loading: true, lastAsk});
    try {
      const out = await api(t.g ? `groups/${encodeURIComponent(t.g.id)}/messages?outline=1` : `bots/${encodeURIComponent(t.b.id)}/messages?chat=${encodeURIComponent(t.b.chatId)}&outline=1`);
      known.list = out.outline; known.loading = false;
      if (navTarget()?.key === t.key) render(true);
    } catch (_) { known.loading = false; }
  }
  function outlineFor(t) {
    const part = loadedParts[t.key];
    if (!part) return [];
    const here = localOutline(part.list);
    if (!part.more) return here;  // the whole conversation is on the page
    const lastAsk = here.length ? here[here.length - 1].id : '', known = outlines[t.key];
    if (!known || (known.lastAsk !== lastAsk && !known.loading)) fetchOutline(t, lastAsk);
    if (!known?.list) return here;
    const mine = Object.fromEntries(here.map(x => [x.id, x]));  // what is on the page is newer than what was fetched
    return known.list.map(x => mine[x.id] || x).concat(here.filter(x => !known.list.some(k => k.id === x.id)));
  }
  function railMarks(list) {
    if (list.length <= RAIL_MOST) return list.map((x, i) => [x, i]);
    const step = (list.length - 1) / (RAIL_MOST - 1);
    return [...new Set(Array.from({length: RAIL_MOST}, (_, k) => Math.round(k * step)))].map(i => [list[i], i]);
  }
  function chatRail() {
    const t = navTarget(); if (!t) return '';
    const list = outlineFor(t);
    if (list.length < 2) return '';
    return `<nav class="chat-rail" aria-label="對話目錄（依時間）">${railMarks(list).map(([x, i]) => `<button type="button" class="rail-tick" data-rail="${esc(x.id)}" data-rail-at="${i}" aria-label="${esc(formatDate(x.createdAt) + ' ' + x.title)}"></button>`).join('')}</nav>`;
  }
  const toBottomButton = () => '<button type="button" class="to-bottom" data-to-bottom="1" aria-label="直接到最新的訊息" title="直接到最新的訊息" hidden>↓</button>';

  // The card beside the rail lives outside the page, so it stays put while a reply streams in and the page is redrawn.
  let railCard = null;
  function showRailCard(tick) {
    const t = navTarget(), x = t && outlineFor(t)[Number(tick.dataset.railAt)];
    if (!x || x.id !== tick.dataset.rail) return;
    if (!railCard) { railCard = document.createElement('div'); railCard.className = 'rail-card'; railCard.setAttribute('role', 'tooltip'); document.body.appendChild(railCard); }
    const who = t.g && x.replyBy ? (state.data.bots.find(b => b.id === x.replyBy)?.name || '') : '';
    railCard.innerHTML = `<strong>${esc(x.author ? x.author + '：' : '')}${esc(x.title)}</strong>${x.reply ? `<p>${esc(who ? who + '：' : '')}${esc(x.reply)}</p>` : '<p class="muted">還沒有回覆</p>'}<small>${esc(formatDate(x.createdAt))}</small>`;
    railCard.hidden = false;
    const r = tick.getBoundingClientRect(), h = railCard.offsetHeight, w = railCard.offsetWidth;
    railCard.style.left = Math.max(8, r.left - w - 14) + 'px';
    railCard.style.top = Math.min(window.innerHeight - h - 8, Math.max(8, r.top + r.height / 2 - h / 2)) + 'px';
  }
  const hideRailCard = () => { if (railCard) railCard.hidden = true; };
  document.addEventListener('mouseover', e => { const tick = e.target.closest?.('[data-rail]'); if (tick) showRailCard(tick); else if (!e.target.closest?.('.chat-rail')) hideRailCard(); });
  document.addEventListener('focusin', e => { const tick = e.target.closest?.('[data-rail]'); if (tick) showRailCard(tick); else hideRailCard(); });
  document.addEventListener('mouseleave', hideRailCard);

  // Going to a question: on the page already, or after loading from it up to the newest.
  async function goToMessage(id) {
    hideRailCard();
    const t = navTarget(); if (!t) return;
    const find = () => [...document.querySelectorAll('#conversation .message[data-mid]')].find(el => el.dataset.mid === id);
    if (!find()) {
      try {
        if (t.b) await loadUpTo(t.b, id);
        else { const out = await api(`groups/${encodeURIComponent(t.g.id)}/messages?from=${encodeURIComponent(id)}`); loadedParts[t.key] = {list: out.messages, more: out.more}; }
      } catch (err) { toast(err.message); return; }
      render(true);
    }
    const el = find(), box = $('#conversation');
    if (!el || !box) return;
    const date = el.previousElementSibling?.classList.contains('date') ? el.previousElementSibling : el;  // its date line too
    box.scrollTo({top: box.scrollTop + date.getBoundingClientRect().top - box.getBoundingClientRect().top - 12, behavior: 'smooth'});
  }
  document.addEventListener('click', e => {
    const tick = e.target.closest?.('[data-rail]');
    if (tick) { goToMessage(tick.dataset.rail); return; }
    if (e.target.closest?.('[data-to-bottom]')) { const box = $('#conversation'); if (box) box.scrollTo({top: box.scrollHeight, behavior: 'smooth'}); }
  });

  // Which question is on screen now, and whether the newest message is out of sight.
  let navFrame = 0;
  function updateChatNav() {
    navFrame = 0;
    const box = $('#conversation'); if (!box) return;
    const down = $('.to-bottom');
    if (down) down.hidden = box.scrollHeight - box.scrollTop - box.clientHeight < 240;
    const ticks = [...document.querySelectorAll('.rail-tick')];
    if (!ticks.length) return;
    const line = box.getBoundingClientRect().top + box.clientHeight * 0.35;
    const seen = [...box.querySelectorAll('.message.user[data-mid]')].filter(el => el.getBoundingClientRect().top <= line).pop();
    const list = outlineFor(navTarget() || {key: ''});
    const at = seen ? list.findIndex(x => x.id === seen.dataset.mid) : 0;
    const active = ticks.filter(x => Number(x.dataset.railAt) <= Math.max(0, at)).pop() || ticks[0];
    ticks.forEach(x => x.classList.toggle('active', x === active));
  }
  document.addEventListener('scroll', e => { if (e.target?.id === 'conversation' && !navFrame) navFrame = setTimeout(updateChatNav, 60); }, true);  // a timer, not an animation frame: those stop while the window is covered
  window.addEventListener('resize', () => { if (state.page === 'chat') updateChatNav(); });
