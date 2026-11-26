  // Skills 與連接器 page (#181 #306 #303 #288): what the page is for in plain words, a Skill you write yourself, a search that
  // says which other tab has matches, the connectors you add yourself kept under 進階, and a new connector on only once it works.
  function dirPageIntro() {
    return '<p class="dir-page-intro"><strong>Skill</strong> 是寫給 Bot 的做事方法（例如「會議記錄怎麼整理」），Bot 遇到相關工作會照著做。<strong>連接器</strong>讓 Bot 能使用外部服務（例如 Notion、Google 行事曆）。<strong>插件</strong>一次帶來一組 Skills 和連接器。這裡設定一次，所有 Bot、所有模型共用。<br><span class="muted">和其他地方的差別：知識庫放的是你給 Bot 參考的資料；記憶是 Bot 自己記下的習慣和偏好。</span></p>';
  }
  // How many entries of a tab match the search, the catalog and the templates included: shown on the tab while searching.
  function dirMatches(tab, q) {
    const filter = state.dirFilter || 'all', has = text => String(text || '').toLowerCase().includes(q);
    const own = directoryItems(tab).filter(i => has(i.name + ' ' + i.description + ' ' + i.group) && (filter === 'all' || (filter === 'on') === i.on)).length;
    const extra = tab === 'skills' ? (state.templates || []).filter(t => !t.added && has(t.name + t.description + t.category)).length
      : tab === 'mcp' ? (state.catalog || []).filter(i => !i.added && has(i.name + i.about + i.category)).length : 0;
    return own + extra;
  }
  // #288②: the one search box is shared by the three tabs, so an empty tab says where the matches are.
  function dirNoMatch(tab, q) {
    if (!q) return '<div class="blank">沒有符合的項目。</div>';
    if (dirMatches(tab, q)) return '';  // the catalog or the templates below have it
    const names = {skills: 'Skills', mcp: '連接器', plugins: '插件'};
    const others = Object.keys(names).filter(t => t !== tab).map(t => [t, dirMatches(t, q)]).filter(x => x[1]);
    return `<div class="blank">${esc(names[tab])}裡沒有符合「${esc(state.dirQuery)}」的項目。${others.length ? `<br>搜尋框是三個分頁共用的，其他分頁有符合的：<div class="setting-actions" style="justify-content:center">${others.map(([t, n]) => `<button class="secondary" data-action="dir-tab" data-id="${t}">看${names[t]}（${n} 個）</button>`).join('')}</div>` : ''}</div>`;
  }
  // #303: adding a connector by hand is for what the catalog above does not have, so it waits under 進階.
  function mcpAdvanced() {
    const open = !!state.mcpAdvancedOpen;
    return `<section class="dir-section"><h2><button class="dir-fold" data-up="mcp-advanced" aria-expanded="${open}"><span>進階</span><span class="dir-chev" aria-hidden="true">${open ? '⌃' : '⌄'}</span></button></h2>${open ? '<div class="dir-add"><button class="secondary" data-action="connector-add">＋ 自己新增</button><span class="muted small">目錄裡沒有的連接器，填網址或這台 Mac 上的程式自己加入。新增後會先測試一次連線，成功才開啟給所有 Bot。</span></div>' : ''}</section>`;
  }
  // What the first test of a connector just added found (#303): on when it worked, otherwise off and why.
  function connectorAddedNote(made) {
    const test = made.test || {};
    if (made.on) return '已新增，連線測試成功，所有 Bot 都可以使用';
    if (test.needsLogin) { state.waitOn = state.waitOn || new Set(); state.waitOn.add(made.id); return '已新增，要先登入。登入並測試成功後會自動開啟'; }
    return '已新增，但連線測試沒有成功，先維持關閉。原因寫在卡片上';
  }
  // After a sign-in: Zook tests the connector again and switches it on only when that worked with the settings saved now (#303).
  async function connectorOnIfReady(id) {
    let r;
    try { r = await post('connectors/' + encodeURIComponent(id.split(':')[1]) + '/turn-on'); }
    catch (error) { state.mcpTests[id] = {status: 'error', error: error.message}; return false; }
    state.mcpTests[id] = r.test;
    if (r.on) { state.data.settings.sharedMcp = [...new Set([...(state.data.settings.sharedMcp || []), id])]; state.waitOn?.delete(id); }
    return r.on;
  }
  function skillModal(item) {
    modal(item ? '編輯 Skill' : '新增 Skill', `<form id="skill-form" data-id="${esc(item?.id || '')}"><div class="modal-body"><p class="muted">Skill 是寫給 Bot 的做事方法。存好後所有 Bot、所有模型都會用；Bot 遇到相關的工作會先讀它。</p><label class="field">名稱<input name="name" required maxlength="80" placeholder="例如：客服回覆" value="${esc(item?.name || '')}"></label><label class="field">能做什麼（一句話）<input name="description" required maxlength="500" placeholder="例如：依公司語氣回覆客戶的問題" value="${esc(item?.description || '')}"><small class="muted">Bot 看這句話決定什麼時候用它。</small></label><label class="field">內容<textarea name="body" required rows="10" maxlength="20000" placeholder="使用時機：…&#10;做法：&#10;1. …">${esc(item?.body || '')}</textarea><small class="muted">寫給 Bot 看的說明，只是文字，不能執行程式。Bot 照著做的每個動作，仍然照你的核准設定先問你。</small></label><p class="form-error" role="alert" hidden></p></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${item ? '儲存' : '新增'}</button></div></form>`);
  }
  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-up="skill-new"], [data-up="skill-edit"], [data-up="mcp-advanced"]');
    if (!el) return;
    if (el.dataset.up === 'mcp-advanced') { state.mcpAdvancedOpen = !state.mcpAdvancedOpen; render(true); return; }
    if (el.dataset.up === 'skill-new') { skillModal(); return; }
    el.disabled = true;
    try { skillModal(await api('skills/' + encodeURIComponent(el.dataset.id.split(':')[1]))); }
    catch (err) { toast(err.message); }
    finally { el.disabled = false; }
  });
  document.addEventListener('submit', async e => {
    const form = e.target;
    if (form.id !== 'skill-form') return;
    e.preventDefault(); e.stopPropagation();
    const d = new FormData(form), id = form.dataset.id, err = form.querySelector('.form-error'), button = form.querySelector('.primary');
    if (button.disabled) return;
    button.disabled = true; err.hidden = true;
    try {
      const made = await post(id ? 'skills/' + encodeURIComponent(id) : 'skills', {name: d.get('name').trim(), description: d.get('description').trim(), body: d.get('body')}, id ? 'PATCH' : 'POST');
      closeModal();
      state.templates = null; state.integrations = await api('integrations');
      state.dirFresh = (state.integrations.skills || []).find(x => x.id === 'skill-zook:' + made.id)?.id || '';
      render(true);
      toast(id ? '已儲存「' + made.name + '」，所有 Bot 下次回覆開始使用' : '已新增「' + made.name + '」，放在「已開啟」最上面，所有 Bot 都會用');
    } catch (error) { err.textContent = error.message; err.hidden = false; button.disabled = false; }
  }, true);
