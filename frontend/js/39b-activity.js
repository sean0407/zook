  // The activity record as an audit page (#304 #247, decisions #12 #27): what Zook did for you, one line per reply of a Bot or a group,
  // with its result, model and, for a failure, why and what next; settings changes and approvals stay under 設定與核准. Filters are
  // dropdowns (分類、Bot、群組、結果、日期) plus a search box, kept per window; lines come 50 at a time; a line goes back to where it happened.
  const ACTIVITY_EXAMPLES = {work: 'Bot 或群組每次回覆', admin: '設定變更、核准、備份', approval: '核准或拒絕 Bot 的動作', tool: 'Bot 沒先問就做的事、清理暫存資料夾', bot: '新增、修改、刪除 Bot 或群組',
    setting: '變更設定、用量預算提醒', connector: '加入或移除 Skills、連接器', schedule: '新增、修改或手動執行排程', data: '新增或刪除知識、記憶', backup: '備份、還原與同步', device: '配對或移除手機'};
  const ACTIVITY_FILTERS = [['activityKind', 'kind'], ['activityBot', 'bot'], ['activityGroup', 'group'], ['activityResult', 'result'], ['activityRange', 'range'], ['activityQ', 'q']];
  const ACTIVITY_SAVED = 'zook-activity-filters';
  function activityFiltered() { return ACTIVITY_FILTERS.some(([key]) => state[key]); }
  function activityEmpty(names) {
    if (!activityFiltered()) return '還沒有紀錄。Bot 或群組每次回覆、設定變更和核准都會記在這裡。';
    if (state.activityQ) return `沒有符合「${state.activityQ}」的紀錄。可以換個關鍵字，或把篩選改回「全部」。`;
    if (state.activityKind && !state.activityBot && !state.activityGroup && !state.activityResult && !state.activityRange)
      return `這個分類目前沒有紀錄（例如${ACTIVITY_EXAMPLES[state.activityKind] || '這一類的變更'}會記在這裡）。可以改選其他分類。`;
    return '沒有符合這些篩選的紀錄。可以把其中幾個改回「全部」。';
  }
  // Where a line happened, when that Bot or group is still here.
  function activityPlace(x) {
    if (x.groupId && (state.data.groups || []).some(g => g.id === x.groupId)) return {kind: 'group', id: x.groupId, label: '回到群組'};
    if (x.botId && state.data.bots.some(b => b.id === x.botId)) return {kind: 'bot', id: x.botId, label: '回到對話'};
    return null;
  }
  const activityGo = (x, cls) => { const p = activityPlace(x); return p ? `<button type="button" class="${cls}" data-up="act-go" data-kind="${p.kind}" data-id="${esc(p.id)}" data-msg="${esc(x.messageId || '')}">${p.label}</button>` : ''; };
  const activityModel = x => x.kind === 'work' && x.providerName ? [x.providerName, x.model].filter(Boolean).join(' · ') : '';
  function activityDetail(x, names) {
    const line = (k, v) => v ? `<div class="act-line"><span>${k}</span><p>${esc(v)}</p></div>` : '';
    const more = x.count > 1 ? [...new Set(x.more || [])] : [];
    const merged = more.length > 1 ? `<div class="act-line"><span>合併 ${x.count} 筆</span><ul class="act-more">${more.map(t => `<li>${esc(t)}</li>`).join('')}</ul></div>` : line('次數', x.count > 1 ? `連續 ${x.count} 次` : '');
    const go = activityGo(x, 'primary small-btn');
    return `<div class="act-detail" id="act-${esc(x.id)}">${line('內容', x.text)}${line('時間', formatDate(x.at))}${line(x.groupId ? '群組' : x.kind === 'work' ? 'Bot' : '來源', x.by)}${line('模型', activityModel(x))}${line('分類', names[x.kind])}${line('結果', x.resultName)}${line(x.result === 'failed' ? '失敗原因' : '原因', x.why)}${line('下一步', x.next || (x.result === 'ok' ? '不用做什麼。' : ''))}${merged}${go ? `<div class="act-go">${go}</div>` : ''}</div>`;
  }
  function activityRow(x, names) {
    const open = state.activityOpen === x.id;
    const meta = [formatDate(x.at), x.by, activityModel(x) || names[x.kind], x.count > 1 ? `共 ${x.count} 筆` : ''].filter(Boolean).map(esc).join(' · ');
    return `<div class="act-item"><div class="act-head"><button type="button" class="plain-row act-row" data-up="act-open" data-id="${esc(x.id)}" aria-expanded="${open}" aria-controls="act-${esc(x.id)}"><span class="plain-copy"><strong>${esc(x.text)}</strong><span>${meta}</span></span><span class="act-result r-${esc(x.result || 'ok')}">${esc(x.resultName || '成功')}</span></button>${activityGo(x, 'link act-back')}</div>${open ? activityDetail(x, names) : ''}</div>`;
  }
  function activityFilters(a) {
    const all = name => [{id: '', name}];
    const pick = (label, key, attr, options) => `<div class="act-filter"><span>${label}</span>${dropdown(key, state[key] || '', options, attr)}</div>`;
    return `<div class="act-filters">${pick('分類', 'activityKind', 'data-activity-kind', all('全部').concat(a.categories || []))}${pick('Bot', 'activityBot', 'data-activity-bot', all('全部 Bot').concat(a.bots || []))}${pick('群組', 'activityGroup', 'data-activity-group', all('全部群組').concat(a.groups || []))}${pick('結果', 'activityResult', 'data-activity-result', all('全部').concat(a.results || []))}${pick('日期', 'activityRange', 'data-activity-range', all('全部日期').concat(a.ranges || []))}</div><input id="act-search" class="act-search" type="search" placeholder="搜尋紀錄：Bot、做了什麼、模型、原因" aria-label="搜尋紀錄" autocomplete="off" maxlength="100" value="${esc(state.activityQ || '')}">`;
  }
  function activityPage() {
    const a = state.activity;
    if (!a) return loadingBlock('正在讀取紀錄…');
    if (a.error) return `<div class="blank error-text">${esc(a.error)}</div>`;
    const names = Object.fromEntries(a.kinds.map(k => [k.id, k.name]));
    const rows = a.items.length ? `<div class="plain-rows act-rows">${a.items.map(x => activityRow(x, names)).join('')}</div>` : `<div class="blank">${esc(activityEmpty(names))}</div>`;
    const more = a.more ? `<div class="act-more-btn"><button type="button" class="secondary" data-up="act-more" ${state.activityMoreLoading ? 'disabled' : ''}>${state.activityMoreLoading ? '正在載入…' : '載入更多'}</button><span class="muted small">已顯示 ${a.items.length} / ${a.total} 筆</span></div>` : a.items.length ? `<p class="muted small act-count">共 ${a.total} 筆</p>` : '';
    return `<p class="muted">Zook 代你做的事：Bot 或群組每次回覆一筆（結果、用了哪個模型、失敗原因），以及設定變更和核准。保留最近 90 天、最多 5000 筆。對話內容、金鑰和完整路徑不會記在這裡。</p>${activityFilters(a)}${rows}${more}`;
  }

  // The filters a window chose stay after a reload of that window (#247⑥).
  function restoreActivityFilters() {
    if (state.activityRestored) return;
    state.activityRestored = true;
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(ACTIVITY_SAVED) || 'null'); } catch (_) {}
    if (saved && typeof saved === 'object') for (const [key] of ACTIVITY_FILTERS) if (typeof saved[key] === 'string') state[key] = saved[key].slice(0, 100);
  }
  function saveActivityFilters() {
    try { sessionStorage.setItem(ACTIVITY_SAVED, JSON.stringify(Object.fromEntries(ACTIVITY_FILTERS.map(([key]) => [key, state[key] || ''])))); } catch (_) {}
  }
  function activityRender() {
    const box = $('#act-search'), typing = box && document.activeElement === box ? [box.selectionStart, box.selectionEnd] : null;
    if (state.page === 'activity') render(true);
    const again = $('#act-search');
    if (typing && again) { again.focus(); again.setSelectionRange(typing[0], typing[1]); }
  }
  async function loadActivity(more = false) {
    restoreActivityFilters(); saveActivityFilters();
    const q = new URLSearchParams();
    for (const [key, param] of ACTIVITY_FILTERS) if (state[key]) q.set(param, state[key]);
    const have = more && state.activity?.items ? state.activity.items : null;
    if (have) { q.set('offset', String(have.length)); state.activityMoreLoading = true; activityRender(); }
    const seq = state.activityLoad = (state.activityLoad || 0) + 1;
    try {
      const out = await api('activity' + (q.toString() ? '?' + q : ''));
      if (seq !== state.activityLoad) return;
      if (have) { const seen = new Set(have.map(x => x.id)); out.items = have.concat(out.items.filter(x => !seen.has(x.id))); }
      state.activity = out;
    } catch (e) { if (seq !== state.activityLoad) return; if (have) toast(e.message); else state.activity = {error: e.message}; }
    state.activityMoreLoading = false;
    activityRender();
  }

  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-up="act-go"], [data-up="act-more"]');
    if (!el) return;
    try {
      if (el.dataset.up === 'act-more') await loadActivity(true);
      else await openConversation(el.dataset.kind, el.dataset.id, el.dataset.msg || '');
    } catch (err) { toast(err.message); }
  });
  document.addEventListener('change', e => {  // 分類 and 結果: 39-upkeep.js, which loads the page again through loadUpkeep
    const t = e.target, key = ['activityBot', 'activityGroup', 'activityRange'].find(k => t.dataset?.[k] !== undefined);
    if (!key) return;
    state[key] = t.value; state.activityOpen = ''; loadActivity();
  });
  let activityTyping = null;
  document.addEventListener('input', e => {
    if (e.target.id !== 'act-search') return;
    clearTimeout(activityTyping);
    const value = e.target.value;
    activityTyping = setTimeout(() => { state.activityQ = value.trim().slice(0, 100); state.activityOpen = ''; loadActivity(); }, 300);
  });
