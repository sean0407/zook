  // 連接器目錄: official remote connectors that can be added with one click.
  const CATALOG_AUTH = {login: ['連結', '按下後在瀏覽器登入'], open: ['加入', '不需要登入'], key: ['貼上金鑰', '需要金鑰'], manual: ['', '尚不支援一鍵連結']};
  // The catalog sits under 已連接 on the connectors page. An entry leaves it once it is added, because it then shows above.
  function loadCatalog() {
    if (state.catalogLoading) return;
    state.catalogLoading = true;
    api('connector-catalog').then(d => { state.catalog = d.items; }).catch(() => { state.catalog = state.catalog || []; }).finally(() => { state.catalogLoading = false; if (state.page === 'mcp' || state.page === 'skills') render(true); });
  }
  function catalogSections(query) {
    if (!state.catalog) { loadCatalog(); return '<section class="dir-section"><h2 class="catalog-head">連接器目錄</h2><div class="detail-empty">正在讀取目錄…</div></section>'; }
    const q = (query || '').toLowerCase(), groups = {};
    state.catalog.filter(i => !i.added && (!q || (i.name + i.about + i.category).toLowerCase().includes(q))).forEach(i => (groups[i.category] = groups[i.category] || []).push(i));
    const card = i => {
      const [label, hint] = CATALOG_AUTH[i.auth], busy = state.catalogBusy;
      const action = i.auth === 'manual' ? `<button class="link" data-action="catalog-why" data-id="${esc(i.id)}">為什麼不行？</button>` : `<button class="${i.auth === 'key' ? 'secondary' : 'primary'} small-btn" data-action="catalog-add" data-id="${esc(i.id)}" aria-label="${esc(label + '「' + i.name + '」')}" ${busy ? 'disabled' : ''}>${busy === i.id ? '處理中…' : label}</button>`;
      const failed = state.catalogErrors?.[i.id];
      return `<article class="dir-card catalog-card ${i.auth === 'manual' ? 'off' : ''}">${itemIcon(i.name, i.icon)}<div class="dir-body"><div class="dir-title"><h3 title="${esc(i.name)}">${esc(i.name)}</h3>${action}</div><p class="dir-desc">${esc(i.about.replace(/。$/, ''))}</p><div class="dir-meta"><span>由 ${esc(i.vendor || i.name)} 提供 · ${esc(hint)}</span></div>${failed ? `<p class="dir-note error-text">沒有連上：${esc(failed)}</p>` : ''}</div></article>`;
    };
    const body = Object.entries(groups).map(([name, items]) => `<section class="dir-section"><h2><span class="catalog-group">${esc(name)}</span><small>${items.length}</small></h2><div class="dir-grid">${items.map(card).join('')}</div></section>`).join('');
    return `<section class="dir-section catalog-intro"><h2 class="catalog-head">連接器目錄</h2><p class="muted">各家官方連接器，按一下加入。</p></section>${body || '<div class="detail-empty">目錄裡的連接器都已經加入，或沒有符合搜尋的項目。</div>'}`;
  }
  function renderCatalog() { render(true); }
  function catalogWhy(id) {
    const item = (state.catalog || []).find(i => i.id === id) || {name: '這個服務'};
    modal(`為什麼 ${item.name} 不能一鍵加入`, `<div class="modal-body"><p>要連上 ${esc(item.name)}，得先有一組在它那邊登記過的「應用程式身分」。</p><p><strong>目錄裡可以一鍵加入的服務</strong>，都允許任何應用程式當場自動登記，所以 Zook 按一下就能完成。</p><p><strong>${esc(item.name)} 不開放自動登記。</strong>它只接受事先申請、經它審核過的應用程式。Claude、ChatGPT 能一鍵連上，是因為 Anthropic 和 OpenAI 各自向它申請過。Zook 還沒有申請，所以連不上。</p><p class="muted">要讓 Zook 也能一鍵加入，需要以 Zook 的名義向 ${esc(item.name)} 申請一組應用程式身分，再內建到 Zook 裡。申請通過後，所有使用者都能一鍵使用。</p></div><div class="modal-foot"><button type="button" class="primary" data-action="close-modal">知道了</button></div>`);
  }
  // A result from before signing in would keep saying the connector needs a sign-in, so it is tested again.
  async function retestConnector(id) {
    delete state.mcpTests[id];
    try { state.mcpTests[id] = await post('mcp/' + encodeURIComponent(id) + '/test'); } catch (error) { state.mcpTests[id] = {status: 'error', error: error.message}; }
  }
  async function catalogAdd(id, key) {
    const item = state.catalog.find(i => i.id === id);
    if (item.auth === 'key' && !key) {
      modal(`連結 ${item.name}`, `<form id="catalog-key-form" data-id="${esc(id)}"><div class="modal-body"><p class="muted">${esc(item.about)}</p><label class="field">金鑰<input name="key" type="password" required autocomplete="off" spellcheck="false" placeholder="貼上金鑰"><small class="muted">金鑰只存在鑰匙圈。</small></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">連結</button></div></form>`);
      return;
    }
    if (state.catalogBusy) return;  // one at a time
    state.catalogBusy = id; renderCatalog();
    let made;
    state.catalogErrors = state.catalogErrors || {}; delete state.catalogErrors[id];
    try { made = await post('connector-catalog/' + encodeURIComponent(id), key ? {key} : {}); }
    catch (error) { state.catalogErrors[id] = error.message; throw error; }  // stays on the card, so the reason is still there after the notice fades
    finally {
      state.catalogBusy = '';
      try { state.catalog = (await api('connector-catalog')).items; state.integrations = await api('integrations'); } catch (_) {}
      if ($('#catalog-key-form') && made) closeModal();
      renderCatalog();
    }
    await refresh();
    if (!made.login) { toast(`${item.name} 已加入，所有 Bot 都可以使用`); return; }
    toast('已在瀏覽器開啟登入頁，完成後回到這裡');
    for (let n = 0; n < 90 && (state.page === 'mcp' || $('.catalog-list')); n++) {  // wait for the browser to come back, while the user is still here
      await new Promise(r => setTimeout(r, 2000));
      let now; try { now = await api('integrations'); } catch (_) { continue; }
      if ((now.mcp || []).find(i => i.id === made.id)?.signedIn) { state.integrations = now; await retestConnector(made.id); render(true); toast(state.mcpTests[made.id]?.status === 'ready' ? `${item.name} 已登入，可以使用` : `${item.name} 已登入，但連線沒有成功`); return; }
    }
  }
