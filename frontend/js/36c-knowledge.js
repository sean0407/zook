  // 知識庫 (#84, #122, #123): typed text or an uploaded file, for every Bot unless one Bot is picked in 「給誰用」. A file's text is read by Zook
  // in the background; its card says 處理中, Bot 可使用 or 失敗 with the reason. The limits here match backend/zook/knowledge.py.
  // With each reply a Bot reads the passages that match the question, up to KNOW_BUDGET characters, each with where it is from (knowsearch.py, #295).
  const KNOW_BUDGET = 12000, KNOW_FILES = 50, KNOW_MB = 20;
  const KNOW_TYPES = 'txt、md、csv、pdf、docx、doc、rtf、xlsx、pptx、html';
  const KNOW_ACCEPT = '.txt,.md,.markdown,.csv,.tsv,.json,.log,.yaml,.yml,.xml,.pdf,.docx,.doc,.rtf,.odt,.html,.htm,.xlsx,.xlsm,.pptx';
  const KNOW_STATE = {processing: '處理中', ready: 'Bot 可使用', failed: '失敗'};
  const knowChars = n => n.chars ?? String(n.content || '').length;
  const knowAudience = () => [{id: '', name: '所有 Bot', hint: '預設。每個 Bot 回覆時都會參考'}, ...state.data.bots.map(b => ({id: b.id, name: b.name, hint: '只有這個 Bot 會參考'}))];
  function knowWho(n) {
    if (!n.botId) return '所有 Bot';
    const bot = state.data.bots.find(b => b.id === n.botId);
    return bot ? '只給 ' + bot.name : '原 Bot 已刪除，沒有 Bot 會用到';
  }
  function knowledgeCard(n) {
    const status = n.status || 'ready', chars = knowChars(n), text = String(n.content || '');
    const meta = [n.source ? '📄 ' + n.source + (n.size ? '（' + fileKB(n.size) + '）' : '') : '', status === 'ready' ? chars.toLocaleString() + ' 字' : '', formatDate(n.updatedAt || n.createdAt)].filter(Boolean).join(' · ');
    return `<article class="card know-card"><div class="know-head"><h3>${esc(n.title)}</h3><span class="know-state ${esc(status)}">${esc(KNOW_STATE[status] || status)}</span></div>${status === 'failed' ? `<p class="error-text">失敗：${esc(n.error || '讀不到這個檔案的內容。')}</p>` : status === 'processing' ? '<p class="muted">正在讀取檔案內容…</p>' : `<p class="know-text">${esc(text.slice(0, 300))}${chars > 300 ? '…' : ''}</p>`}${n.note ? `<p class="muted small">${esc(n.note)}</p>` : ''}<div class="know-meta"><span class="status know-who ${n.botId ? 'one' : 'all'}">${esc(knowWho(n))}</span><small>${esc(meta)}</small></div><div class="actions"><button class="link" data-action="edit-note" data-id="${esc(n.id)}">編輯</button><button class="link" data-action="delete-note" data-id="${esc(n.id)}">刪除</button></div></article>`;
  }
  function knowledgePage() {
    const notes = state.data.knowledge.filter(n => !state.query || matches(n.title) || matches(n.content) || matches(n.source || '') || (n.tags || []).some(matches));
    knowWatch();
    return `<p class="muted know-intro">放公司規定、產品資料等參考資料，Bot 回覆時會自動參考。預設所有 Bot 共用，也可以指定只給某個 Bot。</p><p class="muted small know-intro">可以貼上文字，或上傳檔案（${KNOW_TYPES}），每個檔案 ${KNOW_MB} MB 以內，最多 ${KNOW_FILES} 個檔案。每次回覆，Zook 會依問題從整個知識庫找出相關段落給 Bot（最多約 ${KNOW_BUDGET.toLocaleString()} 字），並標明出處，Bot 可以說出依據。</p>`
      + (state.data.knowledge.length ? knowSearchBox() : '') + (notes.length ? `<div class="cards">${notes.map(knowledgeCard).join('')}</div>` : '<div class="blank">知識庫是空的。按「＋ 新增知識」貼上文字或上傳檔案，Bot 回覆時就會參考。</div>');
  }
  // 試搜尋: type a question and see the passages a Bot would get for it, for every Bot or for one Bot (its own items added).
  function knowSearchBox() {
    const ks = state.knowSearch || {}, r = ks.result;
    const who = [{id: '', name: '所有 Bot', hint: '只看所有 Bot 共用的知識'}, ...state.data.bots.map(b => ({id: b.id, name: b.name, hint: '共用的知識，加上只給它的'}))];
    const said = !r ? '' : {all: '知識庫內容不多，每次回覆都會全部給 Bot：', match: `找到 ${r.passages.length} 段相關內容，回覆時會給 Bot（越前面越相關）：`, recent: '沒有找到相關段落。這種問題會改給 Bot 最新幾則知識的開頭：', none: '這個範圍沒有可用的知識。'}[r.mode] || '';
    const rows = (r?.passages || []).map(p => `<div class="know-hit"><strong>${esc(p.label)}</strong><p>${esc(p.text)}${p.chars > p.text.length ? '…' : ''}</p></div>`).join('');
    return `<form id="know-search-form" class="know-search"><div class="know-search-row"><input name="query" required maxlength="2000" placeholder="試搜尋：輸入一個問題，看 Bot 會讀到哪些段落" aria-label="試搜尋的問題" value="${esc(ks.query || '')}">${dropdown('botId', ks.botId || '', who)}<button class="secondary">試搜尋</button></div>${said ? `<p class="muted small">${esc(said)}</p>${rows}` : ''}</form>`;
  }
  async function knowSearch(form) {
    const d = new FormData(form), query = String(d.get('query') || '').trim(), botId = d.get('botId') || '';
    const result = await post('knowledge/search', {query, botId});
    state.knowSearch = {query, botId, result}; render(true);
  }
  // The 知識庫 tab of a Bot's details: what is only for it, and how many items every Bot shares.
  function knowledgeDetail(b) {
    const own = state.data.knowledge.filter(n => n.botId === b.id), shared = state.data.knowledge.filter(n => !n.botId && (n.status || 'ready') === 'ready').length;  // what it really reads
    knowWatch();
    const rows = own.map(n => `<button class="note-row" data-action="edit-note" data-id="${esc(n.id)}"><strong>${esc(n.title)}</strong><small>${esc((n.status && n.status !== 'ready' ? KNOW_STATE[n.status] + (n.status === 'failed' && n.error ? '：' + n.error : '') + ' · ' : '') + String(n.content || '').slice(0, 120))}</small></button>`).join('');
    const sharedLine = shared ? `<div class="detail-empty">${own.length ? '另有' : '這個 Bot 會參考'} ${shared} 份所有 Bot 共用的知識。<button class="link" data-action="page" data-id="knowledge">查看知識庫</button></div>` : '';
    // ＋ 新增 opens the same window as the 知識庫 page, so 「給誰用」 starts at 所有 Bot there too (decided 2026-11-26).
    return `<div class="detail-title">知識庫 <button class="link" data-action="new-note">＋ 新增</button></div>${rows}${sharedLine}${own.length || shared ? '' : '<div class="detail-empty">知識庫是空的。加入資料，讓 Bot 有更多背景。</div>'}`;
  }
  // While a file is being read, look again every 2 seconds (not while a window or a menu is open, so nothing typed is lost).
  function knowWatch() {
    if (state.knowTimer || !state.data.knowledge.some(n => n.status === 'processing')) return;
    state.knowTimer = setTimeout(async () => {
      state.knowTimer = null;
      if (document.querySelector('.modal') || document.querySelector('.dd.open') || document.activeElement?.closest('.know-search')) return knowWatch();
      try { await refresh(); render(true); } catch (_) { knowWatch(); }
    }, 2000);
  }
  function noteModal(n = {}) {
    const isNew = !n.id, fromFile = !!n.source;
    const source = isNew ? `<div class="field">內容來源${dropdown('source', 'text', [{id: 'text', name: '輸入文字', hint: '直接貼上或打字'}, {id: 'file', name: '上傳檔案', hint: KNOW_TYPES + '，' + KNOW_MB + ' MB 以內'}])}</div>` : '';
    const text = fromFile ? `<p class="muted small">內容來自檔案「${esc(n.source)}」（${esc(KNOW_STATE[n.status || 'ready'])}）。要換內容，請刪除後重新上傳。</p>`
      : `<div class="know-part" data-part="text"><label class="field">內容<textarea name="content" required>${esc(n.content || '')}</textarea></label><small class="muted know-count"></small></div>`;
    const file = isNew ? `<div class="know-part" data-part="file" hidden><div class="field">檔案<div class="watch-pick"><input type="file" name="file" accept="${KNOW_ACCEPT}" style="display:none" disabled><span class="watch-path know-file-name">尚未選擇</span><button type="button" class="secondary small-btn" data-know-pick>選擇檔案</button></div><small class="muted">支援 ${KNOW_TYPES}。每個檔案 ${KNOW_MB} MB 以內，知識庫最多 ${KNOW_FILES} 個檔案。上傳後 Zook 會讀出文字，卡片顯示「處理中」，完成後變成「Bot 可使用」。</small></div></div>` : '';
    modal(isNew ? '新增知識' : '編輯知識', `<form id="note-form"><div class="modal-body">${source}<label class="field">標題<input name="title" maxlength="300" required value="${esc(n.title || '')}"></label>${text}${file}<div class="field">給誰用${dropdown('botId', n.botId || '', knowAudience())}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">儲存</button></div></form>`);
    const form = $('#note-form'); form.dataset.id = n.id || '';
    const count = () => { const box = form.querySelector('.know-count'), len = form.elements.content?.value.length || 0; if (box) box.textContent = `目前 ${len.toLocaleString()} 字。內容長也沒關係，回覆時 Zook 會挑出和問題相關的段落給 Bot。`; };
    if (!fromFile) count();
    form.addEventListener('input', e => { if (e.target.name === 'content') count(); });
    form.addEventListener('change', e => {
      if (e.target.name === 'source') {  // 輸入文字 or 上傳檔案: only the fields of the one chosen count
        const upload = e.target.value === 'file';
        form.querySelectorAll('.know-part').forEach(p => { p.hidden = p.dataset.part !== e.target.value; p.querySelectorAll('textarea,input').forEach(x => { x.disabled = p.hidden; }); });
        form.elements.title.required = !upload; form.elements.title.placeholder = upload ? '不填就用檔名' : '';
      }
      if (e.target.name === 'file') form.querySelector('.know-file-name').textContent = e.target.files[0]?.name || '尚未選擇';
    });
    form.querySelector('[data-know-pick]')?.addEventListener('click', () => form.elements.file.click());
  }
  // Saving the form: a file goes up as it is (its text is read afterwards); typed text and 「給誰用」 as before. Older items keep their tags.
  async function saveNote(form, clientId) {
    const d = new FormData(form), id = form.dataset.id, botId = d.get('botId') || '';
    if (!id && d.get('source') === 'file') {
      const f = form.elements.file.files[0];
      if (!f) throw Error('請先選擇要上傳的檔案。');
      if (f.size > KNOW_MB * 1048576) throw Error(`單一檔案不能超過 ${KNOW_MB} MB。`);
      const res = await fetch('/api/knowledge/file', {method: 'POST', headers: {'X-File-Name': encodeURIComponent(f.name), 'X-Title': encodeURIComponent(String(d.get('title') || '').trim()), 'X-Bot-Id': encodeURIComponent(botId), 'Content-Type': 'application/octet-stream'}, body: f});
      if (!res.ok) throw Error((await res.json().catch(() => ({}))).error || '上傳失敗');
      closeModal(); await refresh(); render(true);
      toast('已上傳，正在讀取檔案內容');
      return;
    }
    const data = {title: String(d.get('title') || '').trim(), botId};
    if (form.elements.content && !form.elements.content.disabled) data.content = d.get('content');
    if (clientId) data.clientId = clientId;
    await post(id ? 'knowledge/' + encodeURIComponent(id) : 'knowledge', data, id ? 'PATCH' : 'POST');
    closeModal(); await refresh();
    toast('已儲存知識');
  }
