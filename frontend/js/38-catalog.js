  // 連接器目錄: official remote connectors that can be added with one click.
  const CATALOG_AUTH = {login: ['連結', '按下後在瀏覽器登入'], open: ['加入', '不需要登入'], key: ['貼上金鑰', '需要金鑰'], manual: ['', '尚不支援一鍵連結']};
  async function catalogModal() {
    modal('連接器目錄', '<div class="modal-body"><div class="detail-empty">正在讀取目錄…</div></div>', '', true);
    try { state.catalog = (await api('connector-catalog')).items; } catch (error) { toast(error.message); return; }
    renderCatalog();
  }
  function renderCatalog() {
    const body = $('.modal .modal-body'); if (!body || !state.catalog) return;
    const query = (state.catalogQuery || '').toLowerCase(), groups = {};
    state.catalog.filter(i => !query || (i.name + i.about + i.category).toLowerCase().includes(query)).forEach(i => (groups[i.category] = groups[i.category] || []).push(i));
    const row = i => {
      const [label, hint] = CATALOG_AUTH[i.auth];
      const action = i.added ? '<span class="pill ok">已加入</span>' : i.auth === 'manual' ? '' : `<button class="${i.auth === 'key' ? 'secondary' : 'primary'} small-btn" data-action="catalog-add" data-id="${esc(i.id)}" ${state.catalogBusy ? 'disabled' : ''}>${state.catalogBusy === i.id ? '處理中…' : label}</button>`;
      return `<div class="catalog-item ${i.auth === 'manual' ? 'off' : ''}">${itemIcon(i.name)}<div><strong>${esc(i.name)}</strong><small>${esc(i.about.replace(/。$/, ''))} · ${esc(i.added && i.auth === 'login' ? '可在卡片上登入或登出' : hint)}</small></div>${action}</div>`;
    };
    body.innerHTML = `<p class="muted">這些都是各家公司自己提供的官方連接器。加入後所有 Bot 共用，隨時可以在連接器頁關閉或移除。</p><input id="catalog-search" class="dir-search" placeholder="搜尋" aria-label="搜尋目錄" value="${esc(state.catalogQuery || '')}">${Object.entries(groups).map(([name, items]) => `<h3 class="modal-sub">${esc(name)}</h3><div class="catalog-list">${items.map(row).join('')}</div>`).join('') || '<div class="detail-empty">找不到符合的連接器。</div>'}<p class="muted small">Google（Gmail、行事曆、雲端硬碟）需要自己的 Google Cloud 用戶端，請用連接器頁上的 Google 卡片。</p>`;
  }
  async function catalogAdd(id, key) {
    const item = state.catalog.find(i => i.id === id);
    if (item.auth === 'key' && !key) {
      modal(`連結 ${item.name}`, `<form id="catalog-key-form" data-id="${esc(id)}"><div class="modal-body"><p class="muted">${esc(item.about)}</p><label class="field">金鑰<input name="key" type="password" required autocomplete="off" spellcheck="false" placeholder="貼上金鑰"><small class="muted">金鑰只會存進 macOS 鑰匙圈，不會寫進 Zook 的資料檔，也不會傳到手機。</small></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="catalog-open">返回目錄</button><button class="primary">連結</button></div></form>`);
      return;
    }
    if (state.catalogBusy) return;  // one at a time
    state.catalogBusy = id; renderCatalog();
    let made;
    try { made = await post('connector-catalog/' + encodeURIComponent(id), key ? {key} : {}); }
    finally {
      state.catalogBusy = '';
      try { state.catalog = (await api('connector-catalog')).items; state.integrations = await api('integrations'); } catch (_) {}
      if ($('#catalog-key-form') && made) await catalogModal(); else renderCatalog();
    }
    await refresh();
    if (!made.login) { toast(`${item.name} 已加入，所有 Bot 都可以使用`); return; }
    toast('已在瀏覽器開啟登入頁，完成後回到這裡');
    for (let n = 0; n < 90 && (state.page === 'mcp' || $('.catalog-list')); n++) {  // wait for the browser to come back, while the user is still here
      await new Promise(r => setTimeout(r, 2000));
      let now; try { now = await api('integrations'); } catch (_) { continue; }
      if ((now.mcp || []).find(i => i.id === made.id)?.signedIn) { state.integrations = now; render(true); toast(`${item.name} 已登入`); return; }
    }
  }
