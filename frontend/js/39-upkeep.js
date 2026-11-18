  // Backups, the activity record, usage budgets and the rules every Bot follows.
  const fmtTokens = n => n >= 1e8 ? (n / 1e8).toFixed(n % 1e8 ? 1 : 0) + ' 億' : n >= 1e4 ? Math.round(n / 1e4).toLocaleString() + ' 萬' : String(n);
  const fmtSize = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

  function rulesSection() {
    const rules = state.data.settings.rules || '';
    return `<h2 class="settings-h">固定規則</h2><p class="muted small settings-note">所有 Bot 每次回覆都會遵守，優先於各自的工作指示。</p><form id="rules-form" class="rules-form"><textarea name="rules" maxlength="10000" rows="5" aria-label="固定規則" placeholder="例如：一律用繁體中文回答。金額一律標示幣別。">${esc(rules)}</textarea><div class="setting-actions"><button class="primary">儲存規則</button></div></form>`;
  }

  function backupSection() {
    const list = state.backups;
    const rows = !list ? loadingBlock('正在讀取備份…') : list.length ? `<div class="plain-rows">${list.map(b => `<div class="plain-row"><div class="plain-copy"><strong>${esc(formatDate(b.at))}</strong><span>${esc(b.kindName)} · ${fmtSize(b.size)}</span></div><div class="plain-actions"><button class="link" data-up="backup-restore" data-id="${esc(b.name)}">還原</button><button class="link danger" data-up="backup-delete" data-id="${esc(b.name)}">刪除</button></div></div>`).join('')}</div>` : '<div class="blank">還沒有備份。</div>';
    return `<h2 class="settings-h">備份與還原</h2><p class="muted small settings-note">每天自動備份一次，保留 14 天。內容包含 Bot、對話、知識、排程與設定；密碼和金鑰留在鑰匙圈，不會放進備份。</p><div class="setting-actions backup-actions"><button class="primary" data-up="backup-now">立即備份</button><button class="secondary" data-action="export">匯出成檔案</button><button class="secondary" data-up="backup-pick">從檔案加入</button><input type="file" id="backup-file" accept=".json,application/json" hidden></div>${rows}`;
  }

  const BUDGET_OVER = [{id: 'warn', name: '只提醒', hint: '繼續回覆'}, {id: 'switch', name: '改用備用模型', hint: '沒有備用模型時照常回覆'}, {id: 'stop', name: '停止回覆', hint: '到下個月或調高上限為止'}];
  function budgetSection() {
    const b = state.budget;
    if (!b) return `<section class="usage-block"><h2>用量預算</h2>${loadingBlock('正在讀取預算…')}</section>`;
    if (b.error) return `<section class="usage-block"><h2>用量預算</h2><div class="blank error-text">${esc(b.error)}</div></section>`;
    const limits = b.limits.map(n => ({id: String(n), name: n ? fmtTokens(n) + ' Token' : '不限'}));
    const rows = b.items.map(x => {
      const pct = x.limit ? Math.min(100, Math.round(x.used / x.limit * 100)) : 0;
      const used = x.limit ? `本月已用 ${fmtTokens(x.used)}（${pct}%）` : `本月已用 ${fmtTokens(x.used)}`;
      return settingRow(esc(x.name), `${used}${x.limit ? `<span class="budget-bar ${x.state}"><i style="width:${pct}%"></i></span>` : ''}`, dropdown('budget-' + x.id, String(x.limit), limits, `data-budget="${esc(x.id)}"`));
    }).join('');
    return `<section class="usage-block"><h2>用量預算</h2><p class="muted small settings-note">每月上限，只計算 Zook 送出的回覆（輸入加輸出）。達 80% 和用完時會通知。</p><div class="setting-list">${settingRow('預算用完時', '', dropdown('budgetOver', b.over, BUDGET_OVER, 'data-budget-over'))}${rows}</div></section>`;
  }

  function activityPage() {
    const a = state.activity;
    if (!a) return loadingBlock('正在讀取紀錄…');
    if (a.error) return `<div class="blank error-text">${esc(a.error)}</div>`;
    const kinds = [{id: '', name: '全部'}, ...a.kinds], names = Object.fromEntries(a.kinds.map(k => [k.id, k.name]));
    const rows = a.items.length ? `<div class="plain-rows">${a.items.map(x => `<div class="plain-row"><div class="plain-copy"><strong>${esc(x.text)}</strong><span>${esc(formatDate(x.at))} · ${esc(names[x.kind] || '')} · ${esc(x.by)}</span></div></div>`).join('')}</div>` : '<div class="blank">還沒有紀錄。</div>';
    return `<p class="muted">設定變更、核准與對外動作的紀錄，保留最近 1000 筆。對話內容不會記在這裡。</p><div class="setting-list">${settingRow('顯示', '', dropdown('activityKind', state.activityKind || '', kinds, 'data-activity-kind'))}</div>${rows}`;
  }

  async function loadUpkeep(p) {
    const fill = async (key, path, pick) => {
      try { const out = await api(path); state[key] = pick ? pick(out) : out; } catch (e) { state[key] = pick ? [] : {error: e.message}; }
      if (state.page === p) render(true);
    };
    if (p === 'settings') fill('backups', 'backups', x => x.items);
    if (p === 'usage') fill('budget', 'budget');
    if (p === 'activity') fill('activity', 'activity' + (state.activityKind ? '?kind=' + encodeURIComponent(state.activityKind) : ''));
  }

  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-up]');
    if (!el) return;
    const id = el.dataset.id;
    try {
      if (el.dataset.up === 'backup-now') { state.backups = (await post('backups')).items; render(true); toast('已備份'); }
      if (el.dataset.up === 'backup-pick') $('#backup-file')?.click();
      if (el.dataset.up === 'backup-delete' && confirm('確定刪除這份備份？')) { state.backups = (await post('backups/' + encodeURIComponent(id), {}, 'DELETE')).items; render(true); }
      if (el.dataset.up === 'backup-restore' && confirm('現在的資料會換成這份備份的內容。\n還原前的資料會另存一份，之後可以再還原回來。')) {
        await post('backups/' + encodeURIComponent(id) + '/restore');
        await refresh(); await loadUpkeep('settings'); toast('已還原');
      }
    } catch (err) { toast(err.message); }
  });

  document.addEventListener('change', async e => {
    const t = e.target;
    try {
      if (t.id === 'backup-file' && t.files[0]) {
        const file = t.files[0]; t.value = '';
        let data;
        try { data = JSON.parse(await file.text()); } catch (_) { throw new Error('這不是 Zook 的備份檔。'); }
        state.backups = (await post('backups/file', {data})).items; render(true); toast('已加入，按「還原」才會套用');
      } else if (t.dataset.budget !== undefined) {
        state.data.settings = await post('settings', {budgets: {[t.dataset.budget]: Number(t.value)}}, 'PATCH'); await loadUpkeep('usage'); toast('已更新預算');
      } else if (t.dataset.budgetOver !== undefined) {
        state.data.settings = await post('settings', {budgetOver: t.value}, 'PATCH'); await loadUpkeep('usage'); toast('已更新');
      } else if (t.dataset.activityKind !== undefined) {
        state.activityKind = t.value; await loadUpkeep('activity');
      }
    } catch (err) { toast(err.message); }
  });

  document.addEventListener('submit', async e => {
    if (e.target.id !== 'rules-form') return;
    e.preventDefault();
    try { state.data.settings = await post('settings', {rules: e.target.elements.rules.value}, 'PATCH'); toast('已儲存規則'); }
    catch (err) { toast(err.message); }
  });

  // Skill templates: listed under the Skills you have, grouped the same way; one click adds one.
  function templateSections(query) {
    if (!state.templates) { api('skill-templates').then(x => { state.templates = x.items; if (state.page === 'skills') render(true); }).catch(() => { state.templates = []; }); return ''; }
    const q = (query || '').toLowerCase(), left = state.templates.filter(t => !t.added && (!q || (t.name + t.description + t.category).toLowerCase().includes(q)));
    if (!left.length) return '';
    const card = t => `<article class="dir-card catalog-card">${itemIcon(t.name)}<div class="dir-body"><div class="dir-title"><h3 title="${esc(t.name)}">${esc(t.name)}</h3><button class="primary small-btn" data-up="template-add" data-id="${esc(t.id)}">加入</button></div><p class="dir-desc">${esc(t.description.replace(/。$/, ''))}</p><div class="dir-meta"><span>${esc(t.category)}</span></div></div></article>`;
    return `<section class="dir-section catalog-intro"><h2 class="catalog-head">Skill 範本</h2><p class="muted">寫好的常用 Skill，按一下加入，所有 Bot 都能用。</p></section><section class="dir-section"><div class="dir-grid">${left.map(card).join('')}</div></section>`;
  }
  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-up="template-add"]');
    if (!el) return;
    el.disabled = true;
    try {
      const made = await post('skills/template', {id: el.dataset.id});
      state.templates = (await api('skill-templates')).items; state.integrations = await api('integrations');
      render(true); toast('已加入「' + made.name + '」');
    } catch (err) { el.disabled = false; toast(err.message); }
  });

  // Schedule form: choosing the folder a triggered schedule watches.
  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-up="pick-watch"]');
    if (!el) return;
    try {
      const picked = (await post('choose-folder')).path, box = el.closest('.watch-pick');
      if (picked && box) { box.querySelector('input').value = picked; box.querySelector('.watch-path').textContent = picked; }
    } catch (err) { toast(err.message); }
  });
