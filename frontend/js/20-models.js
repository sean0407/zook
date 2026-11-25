  // Usage page: provider quotas and per-Bot token usage.
  const fmtN = n => Number(n || 0).toLocaleString();
  function fmtReset(t) {
    if (!t) return '';
    const d = new Date(typeof t === 'number' ? t * 1000 : t);
    if (isNaN(d)) return '';
    const mins = Math.round((d - Date.now()) / 60000);
    const rel = mins <= 0 ? '即將重置' : mins < 60 ? `${mins} 分鐘後重置` : mins < 1440 ? `${Math.floor(mins / 60)} 小時 ${mins % 60} 分後重置` : `${Math.floor(mins / 1440)} 天 ${Math.floor(mins % 1440 / 60)} 小時後重置`;
    return `${rel}（${d.toLocaleString('zh-TW', {month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit'})}）`;
  }
  const loadingBlock = text => `<div class="loading-block" role="status"><span class="spinner" aria-hidden="true"></span><span>${esc(text)}</span></div>`;
  const quotaFor = (id, account) => { const q = (state.quota?.providers || []).find(x => x.id === id); return account ? (q?.profiles || []).find(x => x.id === account) : q; };
  function botUsageSection() {
    const u = state.botUsage;
    if (!u) return `<section class="usage-block"><h2>Bot Token 用量</h2>${loadingBlock('正在整理用量…')}</section>`;
    if (u.error) return `<section class="usage-block"><h2>Bot Token 用量</h2><div class="blank error-text">${esc(u.error)}</div></section>`;
    const rows = [...(u.bots || [])].sort((a, b) => (a.deleted ? 1 : 0) - (b.deleted ? 1 : 0)), max = Math.max(1, ...rows.flatMap(r => Object.values(r.daily)));  // deleted Bots last, each group keeps its usage order
    const days = (u.days || []).map(d => d.slice(5).replace('-', '/'));
    return `<section class="usage-block"><h2>Bot Token 用量</h2>${rows.length ? `<p class="muted small scroll-hint">表格比視窗寬時，可以左右捲動。</p><div class="bot-usage-scroll"><div class="bot-usage"><div class="bot-usage-row head"><span>Bot</span><span>回覆</span><span>輸入</span><span>輸出</span><span title="依 API 價格估算；訂閱帳號不會被收這筆錢">API 等值費用</span><span>近 7 天（${esc(days[0] || '')}–${esc(days.at(-1) || '')}）</span></div>${rows.map(r => `<div class="bot-usage-row ${r.deleted ? 'deleted' : ''}" ${r.deleted ? 'title="已刪除的 Bot"' : ''}><span class="bot-cell">${avatar(r)}<span><strong>${esc(r.name)}${r.deleted ? '<span class="muted">（已刪除）</span>' : ''}${jobTitle(r)}${r.restorable ? `<button class="link restore-bot" data-up="restore-bot" data-id="${esc(r.botId)}">喚回</button>` : ''}</strong><small title="${esc(Object.keys(r.models).join('、'))}">${Object.entries(r.models).sort((a, b) => b[1] - a[1]).map(([m]) => esc(m)).join('、')}</small></span></span><span>${fmtN(r.replies)}${r.groupReplies ? `<small>群組 ${fmtN(r.groupReplies)}</small>` : ''}</span><span>${fmtTok(r.input)}${r.cachedInput ? `<small>快取 ${fmtTok(r.cachedInput)}</small>` : ''}</span><span>${fmtTok(r.output)}</span><span>${r.costUsd == null ? '—<small>CLI 沒有回報金額</small>' : '約 ' + usd(r.costUsd) + '<small>訂閱帳號不另收</small>'}</span><span class="spark">${Object.values(r.daily).map((v, i) => `<i style="height:${Math.max(v ? 8 : 2, Math.round(v / max * 100))}%" title="${esc(days[i])}：${fmtN(v)} tokens"></i>`).join('')}</span></div>`).join('')}</div></div>` : '<div class="blank">還沒有用量紀錄。Bot 回覆後就會出現在這裡。</div>'}</section>`;
  }

  // Permission modes: which tool actions need the user's approval.
  const PERMISSIONS = [
    {id: 'manual', name: '謹慎', hint: '有變動就先問', rows: ['讀取：直接執行（外部服務先問）', 'Zook 內變更：先問', '程式與外部服務：先問']},
    {id: 'auto', name: '自動', hint: 'Zook 內自動完成，涉及程式或外部服務才問', rows: ['讀取：直接執行', 'Zook 內變更：直接執行', '程式與外部服務：先問']},
    {id: 'bypass', name: '全部允許', hint: '只有高風險動作會問', rows: ['讀取：直接執行', 'Zook 內變更：直接執行', '程式與外部服務：直接執行']},
  ];
  const ALWAYS_ASK = '刪除、帳號與權限、寄信或發布';
  const EFFORT_LABEL = {fast: '快速回答', medium: '中等思考', deep: '深入思考'};
  // 自動選擇 shows as a small mark at the very end of the reply; replies saved by 0.9.0 carry it as a sentence.
  const AUTO_KINDS = {simple: '簡單題', code: '寫程式', image: '看圖', analysis: '長篇分析'};
  const AUTO_OLD = {'簡短問答': 'simple', '寫程式': 'code', '看圖': 'image', '長篇分析': 'analysis'};
  const autoInfo = m => {
    if (m.auto) return {mark: m.auto, why: m.autoWhy || ''};
    const old = /^自動選用 (.+?)：(簡短問答|寫程式|看圖|長篇分析)(（.+）)?$/.exec(m.note || '');
    return old ? {mark: `${old[1]} ${AUTO_OLD[old[2]]}`, why: m.note} : null;
  };
  const withAutoMark = (html, m) => {
    const info = autoInfo(m);
    if (!info) return html;
    const kind = AUTO_KINDS[info.mark.split(' ').pop()], name = kind ? info.mark.slice(0, info.mark.lastIndexOf(' ')) : info.mark;
    const mark = `<span class="auto-mark" title="${esc(info.why)}">（自動選了 ${esc(name)}${kind ? '・' + kind : ''}）</span>`;
    return html.endsWith('</p>') ? `${html.slice(0, -4)} ${mark}</p>` : `${html}<p class="auto-mark-line">${mark}</p>`;
  };
  const skippedNote = m => (m.skipped || []).length ? '這次沒用到的連接器：' + m.skipped.join('、') : '';
  const noteLine = m => ((autoInfo(m) && !m.auto ? '' : m.note) || EFFORT_LABEL[m.effort] || skippedNote(m)) ? `<small class="msg-note">${esc([EFFORT_LABEL[m.effort], autoInfo(m) && !m.auto ? '' : m.note, skippedNote(m)].filter(Boolean).join(' · '))}</small>` : '';
  // 思考強度 beside the message box: remembered per Bot or group while Zook is open; starts at the Bot's default.
  const EFFORTS = [{id: 'standard', name: '標準', hint: '交給模型自己決定，不另外指定'}, {id: 'fast', name: '快速', hint: '想得少一點，回得快'}, {id: 'medium', name: '中', hint: '比快速仔細，用量比深入少'}, {id: 'deep', name: '深入', hint: '想得更久、更仔細，用量較多'}];
  if (!state.effort) state.effort = {};
  function effortKey() { const g = activeGroup(); return g ? 'group:' + g.id : 'bot:' + state.selected; }
  function currentEffort() {
    const key = effortKey();
    if (state.effort[key]) return state.effort[key];
    return activeGroup() ? 'standard' : (activeBot()?.effort || state.data.settings.effort || 'standard');
  }
  const pickedEffort = () => state.effort[effortKey()] || '';  // sent with a message; empty lets Zook use the Bot's own level
  function effortSupported() {
    if (activeGroup()) return true;  // each member uses it when its CLI can
    const b = activeBot(), id = b?.provider || state.data.settings.provider || 'codex';
    const p = (state.providers || []).find(x => x.id === id);
    return !p || p.tools !== false;
  }
  // 先規劃: for the next message only; the Bot proposes a plan and changes nothing.
  if (!state.plan) state.plan = {};
  if (!state.long) state.long = {};
  // 長任務 (/goal) and 先規劃 (/plan) are commands typed into the message box; the thinking level is chosen under the ＋ button.
  // In the box itself only what is switched on shows, as a small tag that turns it off again.
  const effortRow = () => settingRow('思考強度', '這個對話接下來的訊息用的思考強度', effortControl());
  const effortChip = () => { const picked = state.effort[effortKey()]; return picked && picked !== 'standard' && effortSupported() ? `<button type="button" class="mode-chip" data-mode-off="effort" title="按一下改回預設">${esc(EFFORTS.find(x => x.id === picked)?.name || picked)} ×</button>` : ''; };
  const modeChips = b => [['long', '長任務'], ['plan', '先規劃']].filter(([k]) => state[k][b.id]).map(([k, name]) => `<button type="button" class="mode-chip" data-mode-off="${k}" title="按一下關閉">${name} ×</button>`).join('') + effortChip();
  document.addEventListener('click', e => {
    const chip = e.target.closest('[data-mode-off]');
    if (!chip) return;
    if (chip.dataset.modeOff === 'effort') delete state.effort[effortKey()]; else if (state.selected) state[chip.dataset.modeOff][state.selected] = false;
    render(true);
  });
  function effortControl() {
    if (!effortSupported()) return `<span class="effort-off" title="這個模型不支援調整思考強度">思考強度：這個模型不支援</span>`;
    return `<div class="effort-pick" title="思考強度">${dropdown('effort', currentEffort(), EFFORTS, 'data-effort')}</div>`;
  }
  const providerList = () => (state.providers || [{id: 'codex', name: 'Codex'}, {id: 'claude', name: 'Claude'}]).map(p => ({id: p.id, name: String(p.name).split('（')[0]}));
  const providerShort = id => id === 'auto' ? '自動選擇' : providerList().find(p => p.id === id)?.name || id;
  const permissionName = id => PERMISSIONS.find(p => p.id === id)?.name || '謹慎';
  // Shared controls: every choice in the UI is a dropdown (with optional descriptions) or an on/off switch.
  function dropdown(name, value, options, attrs = '') {
    const cur = options.find(o => o.id === value) || options[0] || {name: ''};
    return `<div class="dd"><input type="hidden" name="${esc(name)}" value="${esc(cur.id ?? '')}" ${attrs}><button type="button" class="dd-btn" aria-haspopup="listbox" aria-expanded="false"><span class="dd-label">${esc(cur.name)}</span><span class="dd-chev" aria-hidden="true">⌄</span></button><div class="dd-menu" role="listbox">${options.map(o => `<button type="button" class="dd-opt ${o.id === cur.id ? 'selected' : ''}" role="option" aria-selected="${o.id === cur.id}" data-value="${esc(o.id)}" data-label="${esc(o.name)}"><span><strong>${esc(o.name)}</strong>${o.hint ? `<small>${esc(o.hint)}</small>` : ''}</span><span class="dd-check" aria-hidden="true">✓</span></button>`).join('')}</div></div>`;
  }
  const toggle = (attrs, on, label) => `<input type="checkbox" class="switch" role="switch" aria-label="${esc(label)}" ${attrs} ${on ? 'checked' : ''}>`;
  const settingRow = (title, desc, control) => `<div class="setting-row"><div class="setting-copy"><strong>${title}</strong>${desc ? `<span>${desc}</span>` : ''}</div><div class="setting-control">${control}</div></div>`;
  // Where a Bot's built-in tools may work. Only set here on the Mac.
  const ACCESS = [{id: 'full', name: '整台 Mac', hint: '可以讀寫任何檔案、執行任何指令，和直接使用 CLI 一樣'},
                  {id: 'folder', name: '指定資料夾', hint: '只能讀寫你選的那個資料夾'},
                  {id: 'workspace', name: '只限 Bot 工作區', hint: '只能讀寫 Zook 為它準備的資料夾'}];
  const permissionOptions = () => PERMISSIONS.map(p => ({id: p.id, name: p.name, hint: p.hint}));
  // Claude and Cursor Bots have the whole Mac and ask only at the safety boundaries; the other CLIs keep 主動性 and 存取範圍.
  const GATED_CLIS = ['claude', 'cursor'];
  const gatedCli = id => GATED_CLIS.includes(id || state.data.settings.provider || 'codex');
  const BOUNDARY_TEXT = '刪除檔案、對外送出、金鑰密碼、安裝軟體或改系統設定前會先問你（Zook 依指令內容判斷，盡力攔下；先寫成檔案再執行的程式可能認不出來）';
  // #284: a Claude or Cursor Bot that Zook held in keeps the menu, so it can be widened where the notice says, back behind the gate.
  const HELD_ACCESS = [{id: 'workspace', name: '只限 Bot 工作區', hint: 'Zook 自動收緊後的設定：只能讀寫 Zook 為它準備的資料夾'}, {id: 'full', name: '整台 Mac', hint: BOUNDARY_TEXT}];
  const HELD_ACCESS_NOTE = 'Zook 自動收緊了這個 Bot。改成「整台 Mac」後，要這台 Mac 的安全檢查生效才會用到整台 Mac；生效前的那一則只能用 Bot 的工作資料夾。';
  const permText = b => b.provider !== 'auto' && gatedCli(b.provider) && b.gateFull ? '整台 Mac，' + BOUNDARY_TEXT : '主動性：' + permissionName(b.permissionMode || state.data.settings.permissionMode) + (b.permissionMode ? '' : '（預設）');
  // A setting that follows 設定: one 「預設（目前是 …）」 line, then the other values, so no choice is listed twice. Picking it again goes back to following.
  // own: the Bot's own value. One that happens to equal the default is still its own: it stays listed, as 「…（固定）」. label: a default no single option names.
  const withDefault = (options, current, own = '', label = '') => { const d = options.find(o => o.id === current), name = label || (d || options[0]).name; return [{id: '', name: '預設（目前是 ' + name + '）', hint: (d?.hint ? d.hint + '。' : '') + '跟著「設定」改'}, ...options.filter(o => !d || o.id !== d.id || o.id === own).map(o => d && o.id === d.id ? {...o, name: o.name + '（固定）', hint: '不跟著「設定」的預設改'} : o)]; };
  // Remote access: off unless turned on here. Pairing and revoking can only be done on this Mac.
  // App updates: checked automatically unless turned off; installing is always the user's decision.
  const noticeSection = () => `<h2 class="settings-h">通知</h2><div class="setting-list">${settingRow('排程通知', '排程完成、失敗或需要核准時通知', toggle('data-schedule-notify', state.data.settings.scheduleNotify !== false, '排程通知'))}</div>`;
  function updateSection() {
    const u = state.update || {};
    const status = u.state === 'checking' ? '正在檢查…' : u.available ? `有新版 ${esc(u.latest)}` : u.error ? esc(u.error) : u.latest ? '已是最新版' : '尚未檢查';
    return `<h2 class="settings-h">更新</h2><div class="setting-list">${settingRow('目前版本', `${esc(u.current || '開發版本')} · ${status}`, u.available ? '<button class="primary" data-action="update-open">更新</button>' : '<button class="secondary" data-action="update-check">檢查更新</button>')}${settingRow('自動檢查更新', '有新版時提醒，不會自動安裝。', toggle('data-auto-update', state.data.settings.autoUpdateCheck !== false, '自動檢查更新'))}</div>`;
  }
  function updateModal() {
    const u = state.update || {};
    const busy = u.state === 'downloading' || u.state === 'ready' || u.state === 'applying';
    const body = busy ? `<p><strong>${u.state === 'downloading' ? '正在下載並驗證新版…' : '正在安裝，Zook 會自動重新開啟…'}</strong></p><p class="muted">請不要關閉 Zook。</p>`
      : `<p>目前版本 ${esc(u.current || '')}，新版 <strong>${esc(u.latest || '')}</strong>。</p>${u.notes ? `<pre class="update-notes">${esc(u.notes)}</pre>` : ''}${u.error ? `<p class="error-text">${esc(u.error)}</p>` : ''}${u.canInstall ? '<p class="muted">更新時 Zook 會重新開啟。Bot、對話和設定都會保留。</p>' : '<p class="muted">這個 Zook 無法自行更新。請把它拖到「應用程式」後再試，或到 GitHub 下載。</p>'}`;
    modal('更新 Zook', `<div class="modal-body">${body}</div>${busy ? '' : `<div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">稍後</button>${u.canInstall ? '<button class="primary" data-action="update-install">下載並安裝</button>' : ''}</div>`}`);
  }
  async function refreshUpdate(redraw = true) {
    try {
      const before = JSON.stringify(state.update);
      state.update = await api('update');
      if (redraw && before !== JSON.stringify(state.update) && !state.modal && !document.querySelector('.dd.open')) render(true);
    } catch (_) {}
  }
  async function installUpdate() {
    state.update = await post('update/download'); updateModal();
    while (state.update.state === 'downloading') { await new Promise(r => setTimeout(r, 1000)); state.update = await api('update'); }
    if (state.update.state !== 'ready') { updateModal(); return; }
    try { state.update = await post('update/apply'); } catch (e) { state.update = await api('update'); state.update.error = e.message; updateModal(); return; }
    updateModal();
    window.webkit?.messageHandlers?.zookWindow?.postMessage({quit: true});
  }
  const REMOTE_EXPIRY = [[7, '7 天'], [30, '30 天（預設）'], [90, '90 天'], [365, '1 年'], [0, '永久有效']];
  function remoteSection() {
    const r = state.remote;
    if (!r) return `<h2 class="settings-h">遠端連線</h2>${loadingBlock('正在讀取…')}`;
    if (!r.available) return '';
    const status = !r.enabled ? '已關閉' : r.connected ? '已連上中繼伺服器' : '連不上中繼伺服器';
    const when = d => d ? formatDate(d) : '尚未使用';
    const devices = r.devices.length ? r.devices.map(d => `<div class="setting-row device-row"><div class="setting-copy"><strong>${esc(d.name)}${d.online ? ' <span class="pill ok">連線中</span>' : ''}</strong><span>配對於 ${esc(formatDate(d.createdAt))} · 最後使用：${esc(when(d.lastSeenAt))}</span></div><div class="setting-control"><button class="secondary small-btn" data-action="remote-revoke" data-id="${esc(d.id)}">撤銷</button></div></div>`).join('') : '<p class="muted small">還沒有配對任何裝置。</p>';
    const expiry = REMOTE_EXPIRY.some(([d]) => d === state.data.settings.remoteExpiry?.days) ? state.data.settings.remoteExpiry.days : 30;
    const expiryRow = settingRow('自動失效', expiry ? '手機多久沒使用就自動失效，之後要重新配對。改了期限從現在起算。' : '<span class="remote-expiry-note">手機不會自動失效。手機遺失時，記得到下方撤銷。</span>', dropdown('remoteExpiry', String(expiry), REMOTE_EXPIRY.map(([id, name]) => ({id: String(id), name})), 'data-remote-expiry'));
    return `<h2 class="settings-h">遠端連線</h2><div class="setting-list">${settingRow('讓其他裝置連到這台 Mac', '開啟後，已配對的手機可以對話和核准。內容全程加密。', toggle('data-remote-enabled', r.enabled, '遠端連線'))}${settingRow('中繼伺服器', '你自己的中繼伺服器網址，以 wss:// 開頭。', `<input class="relay-input" data-remote-relay value="${esc(r.relayUrl)}" placeholder="wss://…" aria-label="中繼伺服器網址" spellcheck="false">`)}${settingRow('狀態', r.enabled && !r.connected ? '請確認網址正確，而且這台 Mac 有連上網路。' : '', `<span class="remote-status ${r.enabled ? (r.connected ? 'ok' : 'bad') : ''}">${status}</span>`)}${expiryRow}</div><div class="remote-devices"><div class="remote-devices-head"><strong>已配對的裝置</strong><button class="secondary small-btn" data-action="remote-pair" ${r.enabled ? '' : 'disabled'}>配對新裝置</button></div>${devices}</div><p class="muted small perm-always">手機只能對話、核准和查看。其他設定要在這台 Mac 上改。</p>`;
  }
  async function loadRemote(quiet) {
    try { state.remote = await api('remote'); } catch (_) { if (!quiet) state.remote = {available: false, devices: []}; }
    if (state.page === 'settings' && !document.querySelector('.modal [data-pairing]') && document.activeElement?.dataset?.remoteRelay === undefined && !document.querySelector('.dd.open')) render(true);
  }
  function pairingModal(p) {
    modal('配對新裝置', `<div class="modal-body pairing" data-pairing><p class="muted">在 iPhone 的 Zook App 選「配對 Mac」，掃描這個 QR code。</p><img class="pairing-qr" src="${esc(p.qr)}" alt="配對用的 QR code"><p class="muted small">5 分鐘內有效，只能用一次。不要傳給別人。</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="remote-pair-cancel">取消配對</button><button type="button" class="primary" data-action="close-modal">完成</button></div>`);
    const before = (state.remote?.devices || []).length, started = Date.now();
    const timer = setInterval(async () => {
      if (!document.querySelector('.modal [data-pairing]')) { clearInterval(timer); loadRemote(true); return; }
      try { state.remote = await api('remote'); } catch (_) { return; }
      if (state.remote.devices.length > before) { clearInterval(timer); closeModal(); render(true); toast('已配對「' + state.remote.devices.at(-1).name + '」'); }
      else if (!state.remote.pairing || Date.now() - started > 300000) { clearInterval(timer); closeModal(); render(true); toast('配對已過期，請重新產生'); }
    }, 2000);
  }
  function permissionSection(current) {
    return `<h2 class="settings-h">Bot 行為</h2><div class="setting-list">${settingRow('主動性', 'Codex、Grok、Antigravity、Gemini 的 Bot 動作前要不要先問', dropdown('permissionMode', current, permissionOptions(), 'data-permission-mode'))}${settingRow('上網搜尋', '搜尋和讀取網頁，不逐次詢問', toggle('data-web-search', state.data.settings.webSearch, '上網搜尋'))}${settingRow('排程與觸發可用內建瀏覽器', '排程、觸發條件、本機腳本、其他 Bot 和群組討論的回合也能開網頁', toggle('data-browser-automation', state.data.settings.browserAutomation === true, '排程與觸發可用內建瀏覽器'))}</div><p class="muted small perm-always">${ALWAYS_ASK}屬高風險，任何主動性都會先問。Claude、Cursor 的 Bot 可以用整台 Mac，${BOUNDARY_TEXT}。</p>` + botDefaultsSection();
  }

  // What every Bot does unless its own 進階設定 says otherwise.
  function botDefaultsSection() {
    const st = state.data.settings, access = ACCESS.some(a => a.id === st.access) ? st.access : 'full';
    return `<h2 class="settings-h">Bot 預設</h2><p class="muted small settings-note">所有 Bot 共用，停在「（預設）」的 Bot 會跟著改。個別 Bot 可在「進階設定」另外指定。</p><div class="setting-list">${settingRow('存取範圍', 'Codex、Grok、Antigravity、Gemini 可以動到哪些檔案', dropdown('defaultAccess', access, ACCESS, 'data-bot-default="access"'))}<div class="setting-row" ${access === 'folder' ? '' : 'hidden'}><div class="setting-copy"><strong>指定的資料夾</strong><span>${esc(st.accessFolder || '尚未選擇')}</span></div><div class="setting-control"><button type="button" class="secondary" data-action="default-folder">選擇資料夾…</button></div></div>${settingRow('思考強度', '', dropdown('defaultEffort', st.effort || 'standard', EFFORTS, 'data-bot-default="effort"'))}${settingRow('多代理協作', '派子代理分工，用量較多', toggle('data-bot-default="multi"', st.features?.multi === true, '多代理協作'))}${settingRow('圖片生成', '用 AI 生成圖片', toggle('data-bot-default="image"', st.features?.image === true, '圖片生成'))}${settingRow('內建瀏覽器', '開網頁閱讀、截圖、在搜尋框輸入（每次先問你）；不能登入', toggle('data-bot-default="browser"', st.features?.browser === true, '內建瀏覽器'))}</div>`;
  }

  const approvalReason = a => /^zook_(create|update|delete)_schedule$/.test(a.name) ? '排程會在你不在時自動執行，不論主動性都要你核准' : CATEGORY_REASON[a.category];
  const CATEGORY_REASON = {danger: '高風險動作（刪除、安全性或對外發送），一律需要核准', code: '會執行程式碼', external_write: '會修改外部服務', external_read: '會查詢外部服務', internal: '會變更 Zook 內的資料'};

  function personaPanel(b) {
    const draft = state.personaDrafts?.[b.id];
    const value = draft ?? (b.persona || '');
    const dirty = draft !== undefined && draft !== (b.persona || '');
    return `<form class="persona-panel" id="persona-form" data-id="${esc(b.id)}"><label class="detail-title" for="persona-input">人格檔案</label><textarea id="persona-input" name="persona" maxlength="20000" placeholder="還沒有人格設定。寫下個性和語氣，每次回覆都會帶入。">${esc(value)}</textarea><div class="persona-actions"><small class="muted">${value.length.toLocaleString()} / 20,000 字</small>${dirty ? '<button type="button" class="link" data-action="persona-reset">還原</button>' : ''}<button class="primary small-btn" ${dirty ? '' : 'disabled'}>儲存人格</button></div></form>`;
  }

  // Directory: Skills / connectors / plugins in one place, laid out like an app directory.
  const SOURCE_NAMES = {zook: 'Zook Skills', agents: '你的 Skills', claude: 'Claude Skills', codex: 'Codex Skills', shared: '共用 Skills 庫', builtin: 'Zook 內建',
    'claude-code': 'Claude Code 插件'};
  const ICON_COLORS = ['#2585f6', '#13bf78', '#f59a0a', '#ed2f9b', '#14b8a6', '#ff6d0c', '#9254ff', '#a47545'];
  function itemIcon(name, icon) {
    if (icon) return `<span class="dir-icon has-img"><img src="${esc(icon)}" alt="" loading="lazy"></span>`;
    const text = String(name || '?').replace(/^[^A-Za-z0-9一-鿿]+/, '');
    let h = 0; for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return `<span class="dir-icon" style="--ic:${ICON_COLORS[h % ICON_COLORS.length]}">${esc((text[0] || '?').toUpperCase())}</span>`;
  }
  const MCP_FOUND = '在這台 Mac 上找到的';  // connectors set up in Codex or Claude; kept folded at the foot of the page
  const MCP_SOURCE_NAMES = {zook: '已連接', codex: MCP_FOUND, claude: MCP_FOUND, builtin: 'Zook 內建'};
  function sourceName(source, kind) {
    if (!source) return '其他';
    if (kind === 'mcp' && MCP_SOURCE_NAMES[source]) return MCP_SOURCE_NAMES[source];
    if (source.startsWith('plugin:')) return '插件：' + ((state.integrations?.plugins || []).find(p => p.id === source)?.displayName || source.slice(7));
    return SOURCE_NAMES[source] || source;
  }
  function mcpStatus(i) {
    const t = state.mcpTests[i.id];
    if (i.id === 'builtin:workspace') return ['ok', '可用'];
    if (i.gmail && i.needsSetup) return ['', '尚未設定'];
    if (i.google && i.needsLogin) return ['warn', '需要重新登入'];
    if (i.google && i.needsSetup) return ['', '尚未登入'];
    if (i.needsKey) return ['', '需要金鑰'];
    if (i.needsLogin) return ['warn', '需要重新登入'];
    if (i.signedIn) return ['ok', '已登入'];
    if (i.copied) return ['', '已複製到 Zook'];
    if (t?.status === 'ready') return ['ok', `已連線 · ${t.toolCount} 個工具`];
    if (t?.status === 'error') return ['bad', '連線失敗'];
    return ['', '尚未測試連線'];
  }
  const SKILLS_ON = '已開啟', SKILLS_OFF = '未啟用';
  // What a Skill is for, read from its name and description. The first match wins.
  const SKILL_CATEGORIES = [
    ['公司流程', /^(logi|works)[-_ ]|logitech|沃克思|posm|報價|發票|開案|展示品|贈品|駐點|月刊|活動通知/i],
    ['文件與簡報', /docx|pptx|pdf|xlsx|word|excel|powerpoint|簡報|slides?\b|deck|試算表|spreadsheet|文件|翻譯|translate/i],
    ['信件與行事曆', /mail|gmail|信件|郵件|calendar|行事曆|早報|morning|會議|meeting/i],
    ['設計與圖像', /design|canvas|theme|figma|圖卡|carousel|視覺|poster|海報|image|圖片|素材|pexels|art\b/i],
    ['資料分析', /data|sql|analy|dashboard|viz|統計|報表|chart|圖表|\bbi\b/i],
    ['研究與知識', /research|wiki|notebook|obsidian|知識|研究|摘要|summar/i],
    ['開發', /code|api|mcp|git|debug|test|frontend|webapp|程式|開發|skill-creator|routing|plugin/i],
  ];
  // The name says most; the description is only asked when the name says nothing.
  const skillCategory = i => (SKILL_CATEGORIES.find(c => c[1].test(i.name)) || SKILL_CATEGORIES.find(c => c[1].test(i.description || '')) || ['其他'])[0];
  function directoryItems(tab) {
    const inv = state.integrations || {}, settings = state.data.settings || {};
    if (tab === 'skills') {
      const off = new Set(settings.disabledSkills || []);
      // A Skill that is on sits under 已開啟; the rest are sorted by what they are for. A copy already imported into Zook is not shown twice.
      return (inv.skills || []).filter(i => !i.imported).map(i => ({id: i.id, icon: i.icon, name: i.name, description: i.description || '', group: !off.has(i.id) ? SKILLS_ON : SKILLS_OFF + (skillCategory(i) === '其他' ? '' : ' · ' + skillCategory(i)),
        meta: i.imported ? '改用 Zook 裡的那一份' : i.source === 'zook' && SOURCE_NAMES[i.origin] ? '匯入自 ' + SOURCE_NAMES[i.origin] : i.source === 'zook' && i.origin === 'pack' ? '來自設定包' : i.source === 'zook' && i.origin === 'template' ? '來自範本' : sourceName(i.plugin || i.source),
        on: !i.imported && !off.has(i.id), toggle: 'skill', toggleLabel: off.has(i.id) ? '開放給所有 Bot' : '所有 Bot 共用中',
        moved: i.imported ? '已匯入' : '', importable: i.source !== 'zook' && !i.imported, removable: !!i.removable, canUpdate: !!i.canUpdate, note: (i.notes || []).join(' ')}));
    }
    if (tab === 'mcp') {
      return (inv.mcp || []).map(i => {
        const on = (settings.sharedMcp || []).includes(i.id);
        const [cls, label] = mcpStatus(i);
        const test = state.mcpTests[i.id], failed = test?.status === 'error' ? '連線失敗：' + (test.error || '原因不明') : '';
        const description = i.id === 'builtin:workspace' ? '在 Bot 自己的工作區讀寫檔案。' : i.needsKey ? '匯入時沒有帶金鑰，請貼上金鑰。' : i.copied ? 'Zook 已經有自己的一份，Bot 用的是 Zook 那一份。' : i.gmail && i.needsSetup ? '搜尋、讀信、寫草稿和寄信。寄信前一定先問。' : (t => t?.status === 'error' ? (i.editable ? connectorPlace(i.config) : '連線失敗。') : t?.status === 'ready' ? '可用工具：' + (t.tools || []).slice(0, 8).map(x => x.name.replace(/_/g, ' ')).join('、') : i.gmail ? `已連接 ${i.address}。寄信前一定先問。` : i.editable ? connectorPlace(i.config) : sourceName(i.plugin || i.source, 'mcp') + '。按「測試連線」確認是否可以使用。')(state.mcpTests[i.id]);
        return {id: i.id, icon: i.icon, name: i.id === 'builtin:workspace' ? 'Bot 工作區' : i.name, description, group: sourceName(i.plugin || i.source, 'mcp'), meta: i.copied ? '來源設定仍保留' : i.needsKey ? '等待金鑰' : on ? '所有 Bot 共用中' : '未開啟',
          on: on && !i.copied && !i.needsKey, toggle: 'mcp', toggleLabel: on ? '停用這個連接器' : '開放給所有 Bot', status: i.copied ? null : [cls, label], test: i.id !== 'builtin:workspace' && !i.needsSetup && !i.needsKey && !i.copied, editable: !!i.editable, gmail: !!i.gmail, google: !!i.google, needsSetup: !!i.needsSetup,
          needsKey: !!i.needsKey, note: failed, moved: i.copied ? '已複製' : '', copyable: !!i.copyable, canLogin: !!i.canLogin, signedIn: !!i.signedIn, needsLogin: !!i.needsLogin, accounts: i.accounts || []};
      });
    }
    return (inv.plugins || []).map(pl => ({id: pl.id, icon: pl.icon, name: pl.displayName, description: pl.description || '', group: pl.sourceName,
      meta: [pl.skillCount ? pl.skillCount + ' 個 Skill' : '', pl.mcpCount ? pl.mcpCount + ' 個連接器' : '', pl.version ? 'v' + pl.version : ''].filter(Boolean).join(' · ') || '沒有 Zook 可用的內容',
      note: pl.hasHooks || pl.hasCommands ? '部分功能只在原本的工具中運作' : '', on: pl.enabled, toggle: 'plugin', toggleLabel: pl.enabled ? '已啟用' : '啟用'}));
  }
  // A connector card names where it runs in plain words; the command or address itself is kept for 編輯.
  function connectorPlace(c) {
    c = c || {};
    if (c.url) { let host = ''; try { host = new URL(c.url).hostname; } catch (_) {} return '網址連接器' + (host ? '（' + host + '）' : '') + '。'; }
    const cmd = String(c.command || ''), app = cmd.match(/([^/"']+)\.app\//);
    // Split like a shell would (quotes kept together), then skip launchers such as npx, uv run or python -m.
    const words = (cmd.match(/"[^"]*"|'[^']*'|\S+/g) || []).map(w => w.replace(/^["']|["']$/g, '')).filter(w => !w.startsWith('-'));
    while (words.length > 1 && /^(npx|uvx|bunx|pnpm|npm|yarn|node|deno|bun|python[0-9.]*|uv|pipx|run|exec|dlx|x|tool)$/.test(words[0].split('/').pop())) words.shift();
    const base = (words[0] || '').split('/').pop().replace(/(.)@[^@/]*$/, '$1').replace(/^@/, '');
    const name = app ? app[1] + ' App' : /^[\w .-]{1,60}$/.test(base) ? base : '';
    return '這台 Mac 上的程式' + (name ? '（' + name + '）' : '') + '。';
  }
  function directoryPage(tab) {
    if (!state.integrations) return '<div class="blank">正在讀取…</div>';
    const q = (state.dirQuery || '').toLowerCase(), filter = state.dirFilter || 'all';
    const items = directoryItems(tab).filter(i => (!q || (i.name + ' ' + i.description + ' ' + i.group).toLowerCase().includes(q)) && (filter === 'all' || (filter === 'on') === i.on));
    const first = tab === 'skills' ? [SKILLS_ON, ...SKILL_CATEGORIES.map(c => SKILLS_OFF + ' · ' + c[0]), SKILLS_OFF] : [SOURCE_NAMES.builtin, MCP_SOURCE_NAMES.zook];
    const rank = g => first.includes(g) ? first.indexOf(g) : first.length;
    const found = tab === 'mcp' ? items.filter(i => i.group === MCP_FOUND && !i.moved) : [];
    const groups = [...new Set(items.map(i => i.group))].filter(g => g !== MCP_FOUND).sort((a, b) => rank(a) - rank(b));
    const counts = {skills: (state.integrations.skills || []).filter(i => !i.imported).length, mcp: (state.integrations.mcp || []).filter(i => !i.copied).length, plugins: (state.integrations.plugins || []).length};
    const tabs = [['skills', 'Skills'], ['mcp', '連接器'], ['plugins', '插件']];
    const intro = {skills: '所有 Bot 共用。匯入後不受原工具影響。', mcp: '所有 Bot 共用。開得越多回覆越慢，用不到的建議關閉。', plugins: '插件會一次帶來一組 Skills 和連接器，開啟後所有 Bot 共用。Zook 讀取的是 Claude Code 裡裝好的插件。'}[tab];
    const noPlugins = `<div class="blank">還沒有插件。<br>插件要先在 Claude Code 裡安裝（Claude Code 的「插件」管理）。裝好後回到這一頁就會出現，開啟後所有 Bot 都能用。<br>只想加一項功能的話，可以到「Skills」加入現成的 Skill 範本，或到「連接器」從目錄加入。<div class="setting-actions" style="justify-content:center"><button class="secondary" data-action="dir-tab" data-id="skills" data-clear>看 Skill 範本</button><button class="secondary" data-action="dir-tab" data-id="mcp" data-clear>看連接器目錄</button></div></div>`;
    const card = i => {
      const expanded = state.dirExpanded?.[i.id];
      return `<article class="dir-card ${expanded ? 'expanded' : ''}">${itemIcon(i.name, i.icon)}<div class="dir-body"><div class="dir-title"><h3 title="${esc(i.name)}">${esc(i.name)}</h3>${i.needsSetup ? `<button class="primary small-btn" data-action="${i.google ? 'google-setup' : 'gmail-setup'}">${i.google ? '登入' : '設定'}</button>` : i.needsKey ? `<button class="primary small-btn" data-action="connector-edit" data-id="${esc(i.id)}">貼上金鑰</button>` : i.moved ? `<span class="dir-status">${i.moved}</span>` : toggle(`data-dir-switch data-kind="${i.toggle}" data-id="${esc(i.id)}" title="${esc(i.toggleLabel)}"`, i.on, i.toggleLabel)}</div>${(i.accounts || []).length ? `<div class="account-pick" title="所有 Bot 使用這個帳號">${dropdown('connectorAccount', i.accounts.find(a => a.active)?.id || '', i.accounts.map(a => ({id: a.id, name: a.name + (a.needsLogin ? '（需要重新登入）' : '')})), `data-connector="${esc(i.id)}"`)}</div>` : ''}<p class="dir-desc">${esc(i.description || '沒有說明。')}</p>${i.description.length > 70 ? `<button class="link dir-more" data-action="dir-expand" data-id="${esc(i.id)}">${expanded ? '收合' : '展開'}</button>` : ''}<div class="dir-meta">${i.status ? `<span class="dir-status ${i.status[0]}">${esc(i.status[1])}</span>` : ''}<span>${esc(i.meta)}</span>${i.test ? `<button class="link" data-action="test-mcp" data-id="${esc(i.id)}">測試連線</button>` : ''}${i.google && !i.needsSetup ? '<button class="link" data-action="google-add">新增帳號</button><button class="link" data-action="google-setup">重新登入</button><button class="link danger" data-action="google-remove">登出這個帳號</button>' : ''}${i.gmail && !i.needsSetup ? '<button class="link" data-action="gmail-setup">重新設定</button><button class="link danger" data-action="gmail-remove">中斷連接</button>' : ''}${i.copyable ? `<button class="link" data-action="connector-copy" data-id="${esc(i.id)}">加入</button>` : ''}${i.canUpdate ? `<button class="link" data-action="skill-update" data-id="${esc(i.id)}" title="原本的來源有更新">從原來源更新</button>` : ''}${i.removable ? `<button class="link danger" data-action="skill-remove" data-id="${esc(i.id)}" data-name="${esc(i.name)}">移除</button>` : ''}${i.canLogin ? (i.signedIn ? `<button class="link" data-action="connector-login" data-id="${esc(i.id)}" data-add="1">新增帳號</button><button class="link" data-action="connector-logout" data-id="${esc(i.id)}">登出這個帳號</button>` : `<button class="link" data-action="connector-login" data-id="${esc(i.id)}">${i.needsLogin ? '重新登入' : '登入'}</button>`) : ''}${i.editable ? `<button class="link" data-action="connector-edit" data-id="${esc(i.id)}">編輯</button><button class="link danger" data-action="connector-delete" data-id="${esc(i.id)}" data-name="${esc(i.name)}">移除</button>` : ''}</div>${i.note ? `<p class="dir-note">${esc(i.note)}</p>` : ''}</div></article>`;
    };
    return `<div class="dir-bar"><div class="dir-tabs">${tabs.map(([id, label]) => `<button class="${tab === id ? 'active' : ''}" data-action="dir-tab" data-id="${id}">${label}<small>${counts[id]}</small></button>`).join('')}</div><div class="dir-filters">${dropdown('dirFilter', filter, [{id: 'all', name: '全部'}, {id: 'on', name: '已啟用'}, {id: 'off', name: '未啟用'}], 'data-dir-filter')}</div><input id="dir-search" class="dir-search" placeholder="搜尋" aria-label="搜尋" value="${esc(state.dirQuery || '')}"></div><p class="muted dir-intro">${intro}</p>${tab === 'mcp' ? '<div class="dir-add"><button class="secondary" data-action="connector-add">＋ 自己新增</button><span class="muted small">開啟的連接器所有模型都能用。</span></div>' : ''}${tab === 'plugins' ? '' : `<div class="dir-add"><button class="secondary" data-action="pack-export">匯出設定包</button><button class="secondary" data-action="pack-import">匯入設定包</button><span class="muted small">搬到另一台 Mac 用。不含金鑰。</span></div>`}${groups.length ? groups.map(g => { const closed = (state.data.settings.dirCollapsed || []).includes(tab + ':' + g) && !q; return `<section class="dir-section"><h2><button class="dir-fold" data-action="dir-collapse" data-id="${esc(tab + ':' + g)}" aria-expanded="${!closed}"><span>${esc(g)}</span><small>${items.filter(i => i.group === g).length}</small><span class="dir-chev" aria-hidden="true">${closed ? '⌄' : '⌃'}</span></button>${tab === 'skills' && items.some(i => i.group === g && i.importable) ? `<button class="link dir-import" data-action="skills-import" data-id="${esc(g)}">匯入到 Zook</button>` : ''}</h2>${closed ? '' : `<div class="dir-grid">${items.filter(i => i.group === g).map(card).join('')}</div>`}</section>`; }).join('') : tab === 'plugins' && !counts.plugins ? noPlugins : '<div class="blank">沒有符合的項目。</div>'}${tab === 'skills' ? templateSections(q) : ''}${tab === 'mcp' ? catalogSections(q) + (found.length ? `<section class="dir-section found-section"><h2><button class="dir-fold" data-action="found-toggle" aria-expanded="${!!state.foundOpen || !!q}"><span>${MCP_FOUND}</span><small>${found.length}</small><span class="dir-chev" aria-hidden="true">${state.foundOpen || q ? '⌃' : '⌄'}</span></button></h2>${state.foundOpen || q ? `<p class="muted small">來自 Codex 或 Claude 的設定。按「加入」移到已連接。</p><div class="dir-grid">${found.map(card).join('')}</div>` : ''}</section>` : '') : ''}`;
  }
  // Built-in Gmail: an address and a Google app password. The password goes to the Keychain.
  function googleModal() {
    const now = (state.integrations?.mcp || []).find(i => i.google) || {};
    modal('登入 Google 帳號', `<form id="google-form"><div class="modal-body"><p class="muted">Google 要求先建立一組「用戶端」，只要做一次：</p><ol class="steps"><li>開啟 <a href="https://console.cloud.google.com/apis/credentials" rel="noopener noreferrer">Google Cloud 的憑證頁</a>，建立專案，啟用 Gmail、Calendar、Drive 三個 API。</li><li>設定「OAuth 同意畫面」：公司帳號選「內部」，個人帳號選「外部」並加入自己。</li><li>建立「OAuth 用戶端 ID」（電腦版應用程式），貼到下面。</li></ol><label class="field">用戶端編號<input name="clientId" required autocomplete="off" spellcheck="false" placeholder="xxxx.apps.googleusercontent.com"></label><label class="field">用戶端密鑰<input name="clientSecret" type="password" required autocomplete="off" spellcheck="false"><small class="muted">密鑰和授權只存在鑰匙圈。</small></label><div class="setting-list in-form">${settingRow('允許寄信、改行程、上傳檔案', '每一次都會先問你；關閉時 Bot 只能讀取', toggle('name="write"', !!now.write, '允許寫入'))}</div><p class="muted small">公司帳號可能被管理員擋下；個人帳號每 7 天要重新登入。</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">前往 Google 登入</button></div></form>`);
  }
  function gmailModal() {
    const current = (state.integrations?.mcp || []).find(i => i.gmail)?.address || '';
    modal('設定 Gmail', `<form id="gmail-form"><div class="modal-body"><p class="muted">用 Google 的「應用程式密碼」連接，不是你的登入密碼，隨時可以撤銷。</p><ol class="steps"><li>Google 帳戶需已開啟「兩步驟驗證」。</li><li>開啟 <a href="https://myaccount.google.com/apppasswords" rel="noopener noreferrer">myaccount.google.com/apppasswords</a>，輸入名稱（例如 Zook）後建立。</li><li>把顯示的 16 個字母貼到下面。</li></ol><label class="field">Gmail 信箱<input name="address" type="email" required autocomplete="off" spellcheck="false" placeholder="you@gmail.com" value="${esc(current)}"></label><label class="field">應用程式密碼<input name="password" type="password" required autocomplete="off" spellcheck="false" placeholder="16 個英文字母"></label><p class="muted small">密碼只存在鑰匙圈。公司或學校帳號可能無法使用。</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">連接</button></div></form>`);
  }
  // A connector added in Zook itself: a command run on this Mac, or the address of a remote one.
  function connectorModal(item) {
    const c = item?.config || {}, http = item ? item.transport === 'http' : false;
    const types = [{id: 'stdio', name: '這台 Mac 上的程式', hint: '連接器的說明會寫要輸入的啟動指令'}, {id: 'http', name: '網址', hint: '連接器的說明會給一個網址'}];
    const kept = c.hasSecret ? '已儲存。留空表示不變更' : '';
    modal(item ? '編輯連接器' : '新增連接器', `<form id="connector-form" data-id="${esc(item ? item.id.split(':')[1] : '')}"><div class="modal-body"><label class="field">名稱<input name="name" required maxlength="80" placeholder="例如：GitHub" value="${esc(item?.name || '')}"></label><div class="setting-list in-form">${settingRow('類型', '連接器在哪裡執行', dropdown('transport', http ? 'http' : 'stdio', types))}</div><div data-for="stdio" ${http ? 'hidden' : ''}><label class="field">啟動指令<input name="command" spellcheck="false" placeholder="例如：npx -y @modelcontextprotocol/server-github" value="${esc(c.command || '')}"><small class="muted">和你在終端機輸入的一樣。Zook 會在需要時啟動它。</small></label><label class="field">環境變數（選填，每行一個）<textarea name="env" rows="3" spellcheck="false" placeholder="NAME=value">${esc(Object.entries(c.env || {}).map(([k, v]) => k + '=' + v).join('\n'))}</textarea></label><div class="form-grid"><label class="field">金鑰的環境變數名稱（選填）<input name="secretName" spellcheck="false" placeholder="例如：GITHUB_TOKEN" value="${esc(http ? '' : c.secretName || '')}"></label><label class="field">金鑰<input name="secretStdio" type="password" autocomplete="off" spellcheck="false" placeholder="${esc(http ? '' : kept)}"></label></div>${(c.moreSecrets || []).map(m => `<label class="field">金鑰 ${esc(m.name)}<input name="more:${esc(m.name)}" type="password" autocomplete="off" spellcheck="false" placeholder="${m.saved ? '已儲存。留空表示不變更' : '請貼上這把金鑰'}"></label>`).join('')}</div><div data-for="http" ${http ? '' : 'hidden'}><label class="field">網址<input name="url" spellcheck="false" placeholder="https://example.com/mcp" value="${esc(c.url || '')}"></label><label class="field">存取權杖（選填）<input name="secretHttp" type="password" autocomplete="off" spellcheck="false" placeholder="${esc(http ? kept : '')}"><small class="muted">會以 Bearer 權杖送給這個網址。</small></label></div><p class="muted small">金鑰只存在鑰匙圈。${c.hasSecret ? ' <label class="inline-check"><input type="checkbox" name="clearSecret"> 移除已儲存的金鑰</label>' : ''}</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${item ? '儲存' : '新增'}</button></div></form>`);
  }
  function mcpBotsModal(id) {
    const item = (state.integrations?.mcp || []).find(i => i.id === id);
    if (!item) return;
    modal('選擇使用「' + (id === 'builtin:workspace' ? 'Bot 工作區' : item.name) + '」的 Bot', `<form id="mcp-bots-form" data-id="${esc(id)}"><div class="modal-body"><p class="muted">選擇哪些 Bot 可以使用。</p><div class="member-pick">${state.data.bots.map(b => `<label class="ability-option"><input type="checkbox" name="bots" value="${esc(b.id)}" ${(b.enabledMcp || []).includes(id) ? 'checked' : ''}><span>${avatar(b)}<strong>${esc(b.name)}</strong><small>${esc((b.persona || b.instructions || '').slice(0, 40))}</small></span></label>`).join('')}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">儲存</button></div></form>`);
  }

  // The memory page is otherwise only in the 我的工作區 menu; a Bot's details say what it remembers and lead there.
  function memoryNote(b) {
    const mems = state.data.memories || [], own = mems.filter(m => m.botId === b.id).length, shared = mems.filter(m => !m.botId).length;
    return `<div class="detail-title">記憶 <button class="link" data-action="page" data-id="memory">查看全部</button></div><div class="detail-empty">${own || shared ? `這個 Bot 記住 ${own} 則，另外知道所有 Bot 共用的 ${shared} 則。` : '還沒有記憶。對 Bot 說「記住…」它就會記下。'}</div>`;
  }

  function detail(b) {
    let notes = state.data.knowledge.filter(n => n.botId === b.id);
    return `${detailBackdrop()}<aside class="detail" aria-label="詳情"><button class="detail-close icon-btn" data-action="toggle-detail" aria-label="關閉詳情">×</button><div class="detail-profile">${avatar(b,'big')}<h2>${esc(b.name)}</h2><p>${esc(b.provider === 'auto' ? '自動選擇' : b.provider||state.data.settings.provider||'')} ${esc(b.model||'')}</p><p>${esc(permText(b))}</p>${b.autoAssigned && b.autoReason ? `<p class="muted small">自動配好：${esc(b.autoReason)}</p>` : ''}<button class="secondary detail-edit" data-action="edit-bot">編輯設定</button></div><div class="tabs"><button data-action="detail" data-id="persona" class="${state.detail==='persona'?'active':''}">人格</button><button data-action="detail" data-id="activity" class="${state.detail==='activity'?'active':''}">動態</button><button data-action="detail" data-id="database" class="${state.detail==='database'?'active':''}">資料庫</button><button data-action="detail" data-id="outputs" class="${state.detail==='outputs'?'active':''}">產出</button></div>${state.detail==='persona'?personaPanel(b):state.detail==='outputs'?outputsPanel(b):state.detail==='database'?`<div class="detail-title">知識 <button class="link" data-action="new-note">＋ 新增</button></div>${notes.length?notes.map(n=>`<button class="note-row" data-action="edit-note" data-id="${esc(n.id)}"><strong>${esc(n.title)}</strong><small>${esc(n.content)}</small></button>`).join(''):'<div class="detail-empty">尚未新增知識。加入資料，讓這個 Bot 有更多背景。</div>'}${memoryNote(b)}`:`<div class="detail-title">最近動態</div>${toolTimeline(b.id)}${(b.messages||[]).length?`<div class="detail-empty">最近對話 ${esc(formatDate(b.messages.at(-1).createdAt))}</div>`:'<div class="detail-empty">這裡會顯示最近的對話動態。</div>'}`}${usageDock()}</aside>`
  }

  function formatDate(d) {
    if (!d) return '';
    let dt = new Date(d);
    return isNaN(dt) ? String(d) : dt.toLocaleString('zh-TW', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  function modelPicker(model, bare = false) {
    return `<div class="field model-picker"><label>${bare ? '' : '模型'}<select name="modelSelect" aria-label="模型"><option value="">使用預設</option><option value="__custom__">自訂模型…</option></select></label><input type="hidden" name="model" value="${esc(model)}"><input name="modelCustom" aria-label="自訂模型" placeholder="輸入模型 ID" hidden><div class="model-tools"><span class="model-note" role="status" aria-live="polite">準備偵測模型…</span><button type="button" class="link" data-action="refresh-models" aria-label="重新偵測模型">重新偵測</button></div></div>`;
  }

  async function loadModels(form, force = false) {
    if (!form || !form.isConnected) return;
    form.modelRequest?.abort();
    if (form.elements.provider.value === 'auto') { form.querySelector('.model-note').textContent = '先在上面選一家模型與帳號，這裡才會列出能選的型號。'; return; }
    const controller = new AbortController();
    form.modelRequest = controller;
    const provider = form.elements.provider.value || state.data.settings.provider || 'codex';
    const note = form.querySelector('.model-note');
    note.textContent = '正在偵測模型…';
    try {
      const data = await api(`models?provider=${encodeURIComponent(provider)}${force?'&refresh=1':''}`, {signal: controller.signal});
      if (!form.isConnected || form.modelRequest !== controller) return;
      const select = form.elements.modelSelect;
      const current = form.elements.model.value;
      const wasCustom = select.value === '__custom__';
      const models = Array.isArray(data.models) ? data.models : [];
      const st = state.data.settings, named = provider === (st.provider || 'codex') && st.model ? (models.find(m => m.id === st.model)?.name || st.model) : '';
      const pinned = named && current !== st.model ? st.model : null;  // the default model shows once, as 預設; a Bot that picked it itself keeps it as （固定）
      select.innerHTML = `<option value="">${esc(form.id === 'bot-form' ? (named ? '預設（目前是 ' + named + '）' : '預設（這一家建議的型號）') : '各家建議的型號')}</option>` + models.filter(m => form.id !== 'bot-form' || m.id !== pinned).map(m => `<option value="${esc(m.id)}">${esc(m.name||m.id)}${m.source==='alias'?'（別名）':m.source==='cache'?'（快取）':''}${form.id === 'bot-form' && named && m.id === st.model ? '（固定）' : ''}</option>`).join('') + '<option value="__custom__">自訂模型…</option>';
      const known = models.some(m => m.id === current);
      const custom = form.elements.modelCustom;
      if ((current && !known) || wasCustom) {
        select.value = '__custom__'; custom.value = current; custom.hidden = false;
      } else {
        select.value = current || ''; custom.hidden = true;
      }
      note.textContent = (form.dataset.providerChanged ? '換了一家，型號已改回它建議的版本，需要時可以再選。' : '') + (data.note || (models.length ? '' : '這一家沒有列出可選的型號，會用它建議的；也可以選「自訂模型」自己輸入。'));
      delete form.dataset.providerChanged;
    } catch (error) {
      if (error.name === 'AbortError' || !form.isConnected || form.modelRequest !== controller) return;
      const select = form.elements.modelSelect;
      const current = form.elements.model.value;
      if (current) { select.value = '__custom__'; form.elements.modelCustom.value = current; form.elements.modelCustom.hidden = false; }
      note.textContent = `無法偵測模型：${error.message}。可重新偵測或自行輸入。`;
    }
  }

  function saveBotDraft(form) {
    if (!form || form.dataset.id) return;
    let previous = {};
    try { previous = JSON.parse(sessionStorage.getItem('swarmr-new-bot-draft') || '{}'); } catch (_) {}
    const values = {...previous, ...Object.fromEntries(new FormData(form))};
    values.pinned = form.elements.pinned.checked;
    if (form.querySelector('.ability-list')) { values.enabledSkills = new FormData(form).getAll('enabledSkills'); values.enabledMcp = new FormData(form).getAll('enabledMcp'); }
    try { sessionStorage.setItem('swarmr-new-bot-draft', JSON.stringify(values)); } catch (_) {}
  }

  function restoreBotDraft(form) {
    try {
      const draft = JSON.parse(sessionStorage.getItem('swarmr-new-bot-draft') || 'null');
      if (!draft) return;
      if (draft.providerChoice === undefined && draft.provider !== undefined) draft.providerChoice = draft.provider === 'auto' ? 'auto' : (draft.provider || '') + (draft.account ? '::' + draft.account : '');  // a draft from before the one menu
      for (const key of ['name','jobTitle','persona','instructions','providerChoice','provider','account','model','section','effort','shape','color']) {
        if (draft[key] == null || !form.elements[key]) continue;
        form.elements[key].value = draft[key];
        const dd = form.elements[key].closest?.('.dd'), chosen = dd?.querySelector(`.dd-opt[data-value="${CSS.escape(draft[key])}"]`);
        if (chosen) { dd.querySelector('.dd-label').textContent = chosen.dataset.label; dd.querySelectorAll('.dd-opt').forEach(o => { o.classList.toggle('selected', o === chosen); o.setAttribute('aria-selected', o === chosen); }); }
      }
      form.elements.pinned.checked = !!draft.pinned;
      form.querySelector('.bot-preview .avatar').className = `avatar shape-${shapeIndex(draft.shape)} hero`;
      form.querySelectorAll('.avatar').forEach(x => x.style.setProperty('--c', draft.color));
      form.querySelectorAll('.shape-btn').forEach(x => x.classList.toggle('selected', x.dataset.id === draft.shape));
      form.querySelectorAll('.swatch').forEach(x => x.classList.toggle('selected', x.dataset.id === draft.color));
    } catch (_) {}
    syncFeatureRows(form);  // the fields that go with the restored choice
  }

  function page() {
    let name = {
      knowledge: '知識庫',
      usage: '各模型使用量',
      skills: 'Skills 與連接器',
      mcp: 'Skills 與連接器',
      settings: '設定',
      activity: '活動紀錄',
      memory: '記憶',
      schedules: '排程',
      plugins: 'Skills 與連接器'
    } [state.page] || '';
    let content = '';
    if (state.page === 'knowledge') {
      let notes = state.data.knowledge.filter(n => !state.query || matches(n.title) || matches(n.content) || (n.tags || []).some(matches));
      content = notes.length ? `<div class="cards">${notes.map(n=>`<article class="card"><h3>${esc(n.title)}</h3><p>${esc(n.content)}</p><span class="status">${esc(state.data.bots.find(b=>b.id===n.botId)?.name||'共用知識')}</span><div class="actions"><button class="link" data-action="edit-note" data-id="${esc(n.id)}">編輯</button><button class="link" data-action="delete-note" data-id="${esc(n.id)}">刪除</button></div></article>`).join('')}</div>` : '<div class="blank">目前沒有知識。新增筆記，為 Bot 提供背景資料。</div>'
    } else if (state.page === 'activity') {
      content = activityPage();
    } else if (state.page === 'schedules') {
      content = schedulesPage();
    } else if (state.page === 'skills' || state.page === 'mcp' || state.page === 'plugins') {
      content = directoryPage(state.page);
    } else if (state.page === 'skills-legacy') {
      const a = state.integrations?.skills || [], off = new Set(state.data.settings.disabledSkills || []);
      const q = (state.skillQuery || '').toLowerCase();
      const shown = a.filter(i => !q || (i.name + ' ' + (i.description || '')).toLowerCase().includes(q));
      content = `<p class="muted">Skills 由所有 Bot 共用。關閉的 Skill 不會提供給任何 Bot。目前啟用 ${a.filter(i => !off.has(i.id)).length} / ${a.length} 個。</p><input id="skill-search" class="secondary" style="width:100%;text-align:left;margin-bottom:16px" placeholder="搜尋 Skills" aria-label="搜尋 Skills" value="${esc(state.skillQuery||'')}">${shown.length ? `<div class="cards">${shown.map(i=>`<article class="card"><h3>${esc(i.name)}</h3><p>${esc(i.description||i.source||'')}</p><label class="ability-check"><input type="checkbox" data-shared-skill="${esc(i.id)}" ${off.has(i.id)?'':'checked'}> 所有 Bot 共用</label></article>`).join('')}</div>` : '<div class="blank">目前沒有偵測到項目。</div>'}`;
    } else if (state.page === 'memory') {
      const mems = [...(state.data.memories || [])].reverse();
      const who = id => state.data.bots.find(b => b.id === id)?.name;
      // A Bot's own memory outlives the Bot; saying who wrote it would only repeat that the Bot is gone.
      const line = m => m.botId && !who(m.botId) ? '原 Bot 已刪除，沒有 Bot 會用到' : (m.botId ? who(m.botId) : '所有 Bot 共用') + ' · 由 ' + (who(m.createdBy) || '已刪除的 Bot') + ' 記住';
      content = `<p class="muted">這裡是 Bot 幫你記住的習慣和偏好（例如：回覆用條列）。對 Bot 說「記住…」它就會記下。標「所有 Bot 共用」的每個 Bot 都知道；標 Bot 名稱的只有那個 Bot 知道。</p>${mems.length ? `<div class="cards">${mems.map(m => `<article class="card"><p>${esc(m.content)}</p><span class="status">${esc(line(m))} · ${esc(formatDate(m.createdAt))}</span><div class="actions"><button class="link" data-action="delete-memory" data-id="${esc(m.id)}" style="color:#b55">刪除</button></div></article>`).join('')}</div>` : '<div class="blank">還沒有記憶。和 Bot 聊天時說「記住…」，它就會記下來。</div>'}`;
    } else if (state.page === 'mcp-legacy') {
      let a = state.integrations?.[state.page] || [], b = activeBot(), key = state.page === 'skills' ? 'enabledSkills' : 'enabledMcp';
      content = `<label class="field">設定對象<select id="ability-bot"><option value="">請選擇 Bot</option>${state.data.bots.map(x=>`<option value="${esc(x.id)}" ${b?.id===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></label><p class="muted">選擇要讓這個 Bot 使用的項目。</p>${a.length ? `<div class="cards">${a.map(i=>`<article class="card"><h3>${esc(i.name)}</h3><p>${esc(i.description||i.source||'')}</p>${state.page==='mcp'?`<span class="status">${esc(state.mcpTests[i.id]?.status==='ready'?'已驗證 · '+state.mcpTests[i.id].toolCount+' 個工具':state.mcpTests[i.id]?.status==='error'?'連線失敗：'+state.mcpTests[i.id].error:'已偵測設定，尚未驗證')}</span><div class="actions"><button class="link" data-action="test-mcp" data-id="${esc(i.id)}">測試連線</button></div>`:''}<label class="ability-check"><input type="checkbox" data-ability-kind="${key}" data-ability-id="${esc(i.id)}" ${b && (b[key]||[]).includes(i.id)?'checked':''} ${b?'':'disabled'}> 讓此 Bot 使用</label></article>`).join('')}</div>`:'<div class="blank">目前沒有偵測到項目。</div>'}`;
    } else if (state.page === 'usage') {
      let u = state.usage || {},
        groups = u.groups || [];
      let metrics = [
        [u.sessionCount == null ? '分組工作階段加總' : '工作階段', u.sessionCount ?? groups.reduce((a, g) => a + (g.sessions || 0), 0)],
        ['輸入 Token', groups.reduce((a, g) => a + (g.inputTokens || 0), 0)],
        ['輸出 Token', groups.reduce((a, g) => a + (g.outputTokens || 0), 0)]
      ];
      content = guideCard() + accountCards() + overviewSection() + fold('budget', '用量預算', budgetSection()) + fold('bots', 'Bot 用量', botUsageSection()) + `<details class="usage-local"><summary>本機 CLI 全部紀錄（包含 Zook 以外的使用）</summary><p>${esc(u.note||'本機記錄的使用情況。')} ${u.truncated?'資料已截斷。':''}</p><div class="stats">${metrics.map(([k,v])=>`<div class="card"><span class="muted">${k}</span><div class="stat-num">${v.toLocaleString()}</div></div>`).join('')}</div>${groups.length?`<div class="usage-chart">${groups.slice(0,14).map(g=>`<div class="usage-row"><span>${esc(g.date)} · ${esc(g.provider)}</span><div class="usage-track"><div class="usage-bar" style="width:${Math.round(100*((g.inputTokens||0)+(g.outputTokens||0))/Math.max(1,...groups.map(x=>(x.inputTokens||0)+(x.outputTokens||0))))}%"></div></div><small>${((g.inputTokens||0)+(g.outputTokens||0)).toLocaleString()} tokens</small></div>`).join('')}</div><div class="cards">${groups.map(g=>`<div class="card"><h3>${esc(g.date)} · ${esc(g.provider)}</h3><p>${esc(g.model)}<br>${(g.inputTokens||0).toLocaleString()} 輸入 / ${(g.outputTokens||0).toLocaleString()} 輸出</p></div>`).join('')}</div>`:'<div class="blank">尚無使用紀錄。</div>'}` + '</details>';
      if (!state.usage || state.usage.error) content = guideCard() + accountCards() + overviewSection() + fold('budget', '用量預算', budgetSection()) + fold('bots', 'Bot 用量', botUsageSection()) + `<details class="usage-local"><summary>本機 CLI 全部紀錄（包含 Zook 以外的使用）</summary>${state.usage?.error ? `<div class="blank error-text">${esc(state.usage.error)}</div>` : loadingBlock('正在讀取本機紀錄…')}</details>`;
    } else if (state.page === 'plugins-legacy') {
      const list = state.integrations?.plugins || [];
      content = `<p class="muted">來自 Claude Code 的插件。啟用後所有 Bot 共用。</p>${list.length ? `<div class="cards">${list.map(pl => {
        const parts = [pl.skillCount ? pl.skillCount + ' 個 Skill' : '', pl.mcpCount ? pl.mcpCount + ' 個 MCP' : ''].filter(Boolean).join(' · ') || '沒有 Zook 可用的內容';
        const notes = [pl.hasHooks ? 'hooks' : '', pl.hasCommands ? '指令' : ''].filter(Boolean);
        return `<article class="card plugin-card ${pl.enabled ? '' : 'off'}"><div class="plugin-head"><h3>${esc(pl.displayName)}</h3><span class="status">${esc(pl.sourceName)}${pl.version ? ' · v' + esc(pl.version) : ''}</span></div><p>${esc(pl.description || '')}</p><p class="muted">${esc(parts)}${pl.author ? ' · ' + esc(pl.author) : ''}</p>${notes.length ? `<p class="muted small">包含 ${esc(notes.join('、'))}，這部分只在原本的工具中運作，Zook 不會執行。</p>` : ''}<label class="ability-check"><input type="checkbox" data-plugin-toggle="${esc(pl.id)}" ${pl.enabled ? 'checked' : ''}> 啟用</label></article>`;
      }).join('')}</div>` : '<div class="blank">沒有偵測到插件。</div>'}`;
    } else if (state.page === 'settings') {
      let s = state.data.settings || {};
      content = lookSection() + permissionSection(s.permissionMode || 'manual') + rulesSection() + `<div class="setting-list">${settingRow('記憶', 'Bot 記住的偏好，點此查看', '<button type="button" class="secondary" data-action="page" data-id="memory">查看記憶</button>')}</div><h2 class="settings-h">模型</h2><form id="settings-form" class="setting-list">${settingRow('預設提供者', '', `<select name="provider" class="plain-select" aria-label="預設提供者">${providerOptions(s.provider || 'codex', false)}</select>`)}${settingRow('預設模型', '沒指定模型的 Bot 使用', modelPicker(s.model||'', true))}${[0, 1].map(i => settingRow('備用模型 ' + (i + 1), i ? '第一個備用也不能用時' : '模型不能用時改用', dropdown('fallback' + i, (s.fallbacks || [])[i] || '', [{id: '', name: '不使用'}, ...providerList()], 'data-fallback-slot'))).join('')}<div class="setting-actions"><button class="primary">儲存模型設定</button></div></form>` + chatSection() + taskSection() + noticeSection() + voiceSection() + remoteSection() + syncSection() + backupSection() + updateSection()
    }
    return `<main class="main"><header class="main-header"><div class="bot-pill">Zook</div></header><div class="page"><div class="page-inner"><div class="page-top"><h1>${name}</h1>${state.page==='knowledge'?'<button class="primary" data-action="new-note">＋ 新增知識</button>':state.page==='usage'?`<div class="page-top-actions">${usageAutoPick()}<button class="secondary" data-action="detect-usage" title="重新向各家讀取剩餘額度的數字，不會更新軟體" ${state.usageBusy ? 'disabled' : ''}>${state.usageBusy === 'detect' ? '偵測中…' : '偵測使用量'}</button><button class="secondary" data-action="update-all" title="把有新版的 CLI 軟體全部更新到最新版，完成後再讀一次額度" ${state.usageBusy ? 'disabled' : ''}>${state.usageBusy === 'update' ? '更新中…' : '更新全部 CLI'}</button><button class="primary" data-action="provider-add">＋ 新增模型</button></div>`:state.page==='schedules'?'<button class="primary" data-action="new-schedule">＋ 新增排程</button>':''}</div>${content}</div></div></main>`
  }

  function render(keepScroll = false) {
    applyLook();
    let settingsForm = $('#settings-form');
    let settingsDraft = settingsForm ? Object.fromEntries(new FormData(settingsForm)) : null;
    settingsForm?.modelRequest?.abort();
    let conv = $('#conversation');
    let y = keepScroll ? conv?.scrollTop : null;
    const pageY = keepScroll ? $('.page')?.scrollTop : null, localOpen = !!$('.usage-local')?.open;  // long pages stay where they were when data arrives
    let nearBottom = !conv || conv.scrollHeight - conv.scrollTop - conv.clientHeight < 120;
    let previousInput = $('#chat-input');
    let input = previousInput?.value || '';
    let cursor = document.activeElement === previousInput ? [previousInput.selectionStart, previousInput.selectionEnd] : null;
    let openApprovals = [...document.querySelectorAll('[data-approval-details][open]')].map(x => x.dataset.approvalDetails);
    const railFocus = document.activeElement?.dataset?.rail;  // a reply streaming in must not take the keyboard off the rail
    app.innerHTML = `<div class="layout">${sidebar()}${state.page==='chat'?(activeGroup()?groupChat():chat()):page()}</div>`;
    if ($('#chat-input')) {
      $('#chat-input').value = input;
      if (cursor !== null) { $('#chat-input').focus(); $('#chat-input').setSelectionRange(cursor[0], cursor[1]); }
    }
    updateMentionMenu();
    if (state.page === 'chat' && state.lastRestored) { try { localStorage.setItem('zook-last-chat', JSON.stringify({bot: state.selected || '', group: state.groupId || ''})); } catch (_) {} }
    if (localOpen && $('.usage-local')) $('.usage-local').open = true;
    if (pageY && $('.page')) $('.page').scrollTop = pageY;
    if (state.page === 'usage') drawOverviewChart();  // sized to its column, so it is drawn after the page is in place
    document.querySelectorAll('[data-approval-details]').forEach(x => { if (openApprovals.includes(x.dataset.approvalDetails)) x.open = true; });
    if ($('#conversation')) {
      const c = $('#conversation');
      if (!keepFocus()) c.scrollTo({top: y != null && !nearBottom ? y : c.scrollHeight, behavior: 'instant'});
      updateChatNav();  // the rail's current question and the 直接到底 button follow where the page now is
      if (railFocus) [...document.querySelectorAll('[data-rail]')].find(x => x.dataset.rail === railFocus)?.focus();
    }
    if ($('#settings-form')) {
      const f = $('#settings-form');
      if (settingsDraft) { f.elements.provider.value = settingsDraft.provider; f.elements.model.value = settingsDraft.model; }
      loadModels(f);
    }
  }

  function modal(title, body, footer = '', wide = false) {
    state.modal = document.activeElement;
    modalRoot.innerHTML = `<div class="modal-overlay" data-action="overlay"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><h2 id="modal-title">${esc(title)}</h2><button class="icon-btn" data-action="close-modal" aria-label="關閉">×</button></div>${body}${footer}</section></div>`;
    setTimeout(() => $('.modal input,.modal textarea,.modal select,.modal button')?.focus(), 0);
    if ($('#bot-form')) syncFeatureRows($('#bot-form'));
  }
  // 特色功能 only appear for the CLI that can really do them.
  function syncFeatureRows(form) {
    const choice = form.elements.providerChoice?.value;  // read from the menu itself: it may have changed before the hidden field
    const id = (choice !== undefined ? choice.split('::')[0] : form.elements.provider?.value) || state.data.settings.provider || 'codex', offered = (state.providers || []).find(p => p.id === id)?.features || [];
    form.querySelectorAll('[data-feature-row]').forEach(row => { row.hidden = !offered.includes(row.dataset.featureRow); });
    const auto = id === 'auto';  // the model is picked when the Bot is saved, so these choices do not apply yet
    form.querySelectorAll('[data-account-field],.model-picker,[data-fixed-model]').forEach(el => { el.hidden = auto; });
    const gated = !auto && gatedCli(id), access = form.querySelector('[data-access-row]');  // Claude and Cursor: the whole Mac, nothing to choose
    if (access) access.hidden = gated;
    const held = form.querySelector('[data-held-access]');  // only while it stays on the model it was held on: another model is chosen afresh
    if (held) held.hidden = !gated || form.dataset.heldOn !== id;
    const folder = form.querySelector('[data-access-folder]');
    if (folder) folder.hidden = gated || form.elements.access?.value !== 'folder';
    const hint = form.querySelector('[data-auto-hint]');
    if (hint) hint.hidden = !auto;
    const warn = form.querySelector('[data-quota-warn]'), said = warn ? quotaWarnText(choice) : '';
    if (warn) { warn.textContent = said; warn.hidden = !said; }
    sameFallback(form, auto ? '' : id);
  }
  // 備用模型 never switches to the Bot's own CLI, so that choice is left out; a Bot that already has it sees why it does nothing.
  function sameFallback(form, id) {
    const dd = form.querySelector('input[name="fallbackChoice"]')?.closest('.dd');
    if (!dd) return;
    dd.querySelectorAll('.dd-opt').forEach(o => {
      const base = o.dataset.base || (o.dataset.base = o.dataset.label), same = !!id && o.dataset.value === id, chosen = o.classList.contains('selected');
      o.hidden = same && !chosen;
      o.dataset.label = same ? base + '（同一家，不會切換）' : base;
      o.querySelector('strong').textContent = o.dataset.label;
      if (chosen) dd.querySelector('.dd-label').textContent = o.dataset.label;
    });
  }

  function closeModal() {
    $('#bot-form')?.modelRequest?.abort();
    modalRoot.innerHTML = '';
    state.modal?.focus?.();
    state.modal = null
  }

  function botModal(b = {}) {
    const editing = !!b.id;
    let c = /^#[0-9a-f]{6}$/i.test(b.color || '') ? b.color : colors[0],
      shape = shapeIndex(b.shape);
    const st = state.data.settings, accessName = id => ACCESS.find(x => x.id === id)?.name || '整台 Mac', effortName = id => EFFORTS.find(x => x.id === id)?.name || '標準';
    const featureChoice = key => b.features && key in b.features ? (b.features[key] ? 'on' : 'off') : '';  // set on this Bot: its own, even when it equals the default
    const featureOptions = key => withDefault([{id: 'on', name: '開啟'}, {id: 'off', name: '關閉'}], st.features?.[key] ? 'on' : 'off', featureChoice(key));
    const defaultAccess = ACCESS.some(x => x.id === st.access) ? st.access : 'full';
    const ownAccess = ACCESS.some(x => x.id === b.access) ? b.access : '';  // set on this Bot (its own folder too), whatever the default is
    const defaultEffort = EFFORTS.some(x => x.id === st.effort) ? st.effort : 'standard', ownEffort = EFFORTS.some(x => x.id === b.effort) ? b.effort : '';
    const fallbackDefault = (st.fallbacks || []).length ? (st.fallbacks || []).map(providerShort).join(' → ') : '不自動換';
    const fallbackValue = !Array.isArray(b.fallbacks) ? '' : b.fallbacks.length ? b.fallbacks[0] : '__none';  // 「不自動換」 set on this Bot stays its own
    const heldOn = b.id && b.localLimit && b.provider !== 'auto' && gatedCli(b.provider) && !b.gateFull ? b.provider || st.provider || 'codex' : '';
    const heldRow = heldOn ? `<div data-held-access hidden>${settingRow('存取範圍', '可以動到哪些檔案', dropdown('heldAccess', 'workspace', HELD_ACCESS))}<p class="muted small held-note">${HELD_ACCESS_NOTE}</p></div>` : '';
    const autoNote = b.autoAssigned && b.autoReason ? `<small class="muted field-hint" data-auto-reason>自動配好：${esc(b.autoReason)}。改成別的模型就不再自動配。</small>` : '';
    modal(editing ? '編輯 Bot' : '新增 Bot', `<form id="bot-form" novalidate><div class="modal-body">${editing ? '' : teamLink()}<div class="bot-preview"><button type="button" class="avatar-edit" data-action="avatar-pick" aria-label="選擇形狀和顏色" title="選擇形狀和顏色">${avatar({color:c,shape},'hero')}</button><span class="bot-names"><input name="name" required data-need="請填寫 Bot 名稱。" maxlength="80" placeholder="為 Bot 命名" value="${esc(b.name||'')}"><input name="jobTitle" maxlength="12" placeholder="職稱（選填，例如：行銷企劃）" aria-label="職稱" value="${esc(b.jobTitle||'')}"></span><label class="pin-toggle" title="釘選在左側最上方"><input type="checkbox" name="pinned" ${b.pinned ? 'checked' : ''} aria-label="釘選"><span aria-hidden="true">📌</span></label></div><div class="avatar-panel" hidden><div class="shapes">${Array.from({length:13},(_,i)=>`<button type="button" class="shape-btn ${shape===i?'selected':''}" data-action="shape" data-id="${i}" aria-label="形狀 ${i+1}">${avatar({color:c,shape:i})}</button>`).join('')}</div><div class="swatches">${colors.map(x=>`<button type="button" class="swatch ${c===x?'selected':''}" style="background:${x}" data-action="color" data-id="${x}" aria-label="顏色 ${x}"></button>`).join('')}</div></div><input type="hidden" name="shape" value="${shape}"><input type="hidden" name="color" value="${c}"><label class="field persona-field">人格檔案${editing ? '' : '（必填）'}<textarea name="persona" ${editing ? '' : 'required'} data-need="請填寫人格檔案：寫下個性和語氣，一兩句就好。" maxlength="20000" rows="5" placeholder="個性、語氣、擅長的事。例如：冷靜直接的資深工程師，先給結論，不確定就說不確定。">${esc(b.persona||'')}</textarea></label><label class="field">工作指示（選填）<textarea name="instructions" placeholder="負責的工作和做法。例如：審查程式碼，只列出會出錯的問題。">${esc(b.instructions||'')}</textarea></label><div class="form-grid"><label class="field">模型與帳號<select name="providerChoice">${choiceOptions(editing ? b.provider || '' : 'auto', b.account || '')}</select><input type="hidden" name="provider" value="${esc(editing ? b.provider || '' : 'auto')}"><input type="hidden" name="account" value="${esc(b.account || '')}"><small class="field-hint quota-warn" data-quota-warn hidden></small><small class="muted field-hint" data-auto-hint hidden>依人格和工作指示配好一家，之後都用它；沒有可用的模型時，每則訊息自己挑。</small>${autoNote}<small class="muted field-hint">另一個帳號要先在「各模型使用量」新增。<button type="button" class="link" data-action="accounts-from-form">新增帳號</button></small></label>${modelPicker(b.model||'')}</div><div class="setting-list in-form">${settingRow('思考強度', '', dropdown('effort', ownEffort, withDefault(EFFORTS, defaultEffort, ownEffort)))}${settingRow('分類', '', dropdown('section', b.section || sectionNames()[0] || '我的 Bots', [...new Set([...sectionNames(), b.section || '我的 Bots'])].map(x => ({id: x, name: x}))))}</div><details class="advanced"><summary>進階設定</summary><p class="muted small">預設跟著「設定」。只有這個 Bot 要不一樣時才改。</p><div class="setting-list in-form"><div data-access-row>${settingRow('存取範圍', '可以動到哪些檔案', dropdown('access', ownAccess, withDefault(ACCESS, defaultAccess, ownAccess)))}</div>${heldRow}<div class="setting-row" data-access-folder ${ownAccess === 'folder' ? '' : 'hidden'}><div class="setting-copy"><strong>指定的資料夾</strong><span data-access-path>${esc(b.accessFolder || '尚未選擇')}</span></div><div class="setting-control"><input type="hidden" name="accessFolder" value="${esc(b.accessFolder || '')}"><button type="button" class="secondary" data-action="choose-folder">選擇資料夾…</button></div></div><div data-fixed-model>${settingRow('備用模型', '模型不能用時改用', dropdown('fallbackChoice', fallbackValue, withDefault([{id: '__none', name: '不自動換'}, ...providerList()], (st.fallbacks || []).length > 1 ? null : (st.fallbacks || [])[0] || '__none', fallbackValue, fallbackDefault)))}</div><div data-feature-row="multi">${settingRow('多代理協作', '派子代理分工，用量較多', dropdown('featureMulti', featureChoice('multi'), featureOptions('multi')))}</div><div data-feature-row="image">${settingRow('圖片生成', '用 AI 生成圖片', dropdown('featureImage', featureChoice('image'), featureOptions('image')))}</div><div data-feature-row="browser">${settingRow('內建瀏覽器', '開網頁閱讀、截圖、在搜尋框輸入（每次先問你）；不能登入。要先開啟「上網搜尋」', dropdown('featureBrowser', featureChoice('browser'), featureOptions('browser')))}</div></div></details></div><div class="modal-foot">${editing?'<button type="button" class="link" data-action="delete-bot" style="margin-right:auto;color:#b55">刪除 Bot</button>':''}<button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${editing?'儲存':'建立 Bot'}</button></div></form>`);
    const form = $('#bot-form');
    form.dataset.id = b.id || ''; form.dataset.heldOn = heldOn;
    if (!b.id) restoreBotDraft(form);
    loadModels(form);
    syncFeatureRows(form);  // Claude and Cursor have nothing to choose about access
    if (!state.quota) api('quota').then(q => {  // 已用完／剩不到 20% beside each account
      state.quota = q;
      if (!form.isConnected) return;
      const sel = form.elements.providerChoice, v = sel.value;
      sel.innerHTML = choiceOptions(form.elements.provider.value, form.elements.account.value); sel.value = v; syncFeatureRows(form);
    }).catch(() => {});
    const selected = {enabledSkills: b.enabledSkills || [], enabledMcp: b.enabledMcp || []};
    if (!b.id) { try { const d = JSON.parse(sessionStorage.getItem('swarmr-new-bot-draft') || '{}'); selected.enabledSkills = d.enabledSkills || []; selected.enabledMcp = d.enabledMcp || []; } catch (_) {} }
  }
  async function loadBotAbilities(form, selected) {
    const target = form.querySelector('#bot-abilities');
    try {
      const catalog = await api('integrations');
      if (!form.isConnected) return;
      state.integrations = catalog;
      target.innerHTML = `<p class="muted">Skills 和連接器由所有 Bot 共用（${(catalog.skills||[]).length} 個 Skill、${(state.data.settings.sharedMcp||[]).length} 個連接器已開啟），在「Skills 與連接器」頁管理。</p>` + [].map(kind => {
        const key = kind === 'skills' ? 'enabledSkills' : 'enabledMcp';
        const items = catalog[kind] || [];
        const missing = selected[key].filter(id => !items.some(i => i.id === id)).map(id => ({id, name:id, description:'目前未偵測到'}));
        return `<div class="ability-group"><strong>${kind === 'skills'?'Skills':'MCP'}</strong><input class="ability-search" data-kind="${kind}" placeholder="搜尋 ${kind === 'skills'?'Skills':'MCP'}" aria-label="搜尋 ${kind === 'skills'?'Skills':'MCP'}"><div class="ability-list">${[...items,...missing].map(i => `<label class="ability-option" data-search="${esc((i.name+' '+(i.description||'')).toLowerCase())}"><input type="checkbox" name="${key}" value="${esc(i.id)}" ${selected[key].includes(i.id)?'checked':''}><span><strong>${esc(i.name)}</strong><small>${esc(i.description||i.source||'')}</small></span></label>`).join('') || '<p class="muted">目前沒有偵測到項目。</p>'}</div></div>`;
      }).join('');
    } catch (e) { if (form.isConnected) target.innerHTML = `<p class="error-text">無法載入能力清單：${esc(e.message)}。請關閉並重試。</p>`; }
  }

  const REPEATS = [['daily', '每天'], ['weekdays', '週一到週五'], ['mon', '每週一'], ['tue', '每週二'], ['wed', '每週三'], ['thu', '每週四'], ['fri', '每週五'], ['sat', '每週六'], ['sun', '每週日'], ['hourly', '每小時'], ['monthly', '每月'], ['once', '只一次']];
  const repeatName = id => (REPEATS.find(r => r[0] === id) || REPEATS[0])[1];
  const WEEKDAY = '日一二三四五六';
  const dayLabel = iso => { const d = new Date(iso + 'T00:00:00'); return `${d.getMonth() + 1}/${d.getDate()}（週${WEEKDAY[d.getDay()]}）`; };
  // When a schedule runs, in words: 每天 10:00, 每小時的 15 分, 每月 5 號 10:00, 11/20（週五）10:00.
  const TRIGGER_OPTIONS = [{id: 'time', name: '時間到', hint: ''}, {id: 'folder', name: '資料夾有新檔案', hint: '約 20 秒內開始'}, {id: 'mail', name: '收到新信件', hint: '需要先連接 Gmail，約 2 分鐘內開始'}];
  function scheduleWhen(x) {
    if (x.trigger === 'folder') return `「${(x.watchFolder || '').split('/').filter(Boolean).pop() || ''}」有新檔案時`;
    if (x.trigger === 'mail') { const c = [x.mailFrom && `寄件者含「${x.mailFrom}」`, x.mailSubject && `主旨含「${x.mailSubject}」`].filter(Boolean).join('、'); return '收到新信件時' + (c ? `（${c}）` : ''); }
    if (x.repeat === 'hourly') return `每小時的 ${x.time.slice(3)} 分`;
    if (x.repeat === 'monthly') return `每月 ${x.day} 號 ${x.time}`;
    if (x.repeat === 'once') return `${x.date ? dayLabel(x.date) : ''} ${x.time}`;
    return `${repeatName(x.repeat)} ${x.time}`;
  }
  function schedulesPage() {
    const items = state.data.schedules || [];
    const intro = '<p class="muted sched-intro">時間到，或有新檔案、新信件時，自動送出訊息。Mac 和 Zook 要開著。</p>';
    if (!items.length) return intro + '<div class="blank">還沒有排程。</div>';
    const last = x => x.done ? '已完成' : !x.lastStatus ? '尚未執行' : (x.lastStatus === 'sent' ? '上次執行：' : x.lastStatus === 'missed' ? '上次錯過：' : '上次失敗：') + formatDate(x.lastAt) + (x.lastStatus !== 'sent' && x.lastError ? '（' + x.lastError + '）' : '');
    return intro + `<div class="cards">${items.map(x => `<article class="card sched-card"><div class="sched-head"><h3>${esc(scheduleWhen(x))}</h3>${toggle(`data-schedule-switch data-id="${esc(x.id)}"`, x.on, '啟用這個排程')}</div><p>${esc(x.content)}</p>${scheduleTarget(x)}<span class="status ${x.lastStatus && x.lastStatus !== 'sent' && !x.done ? 'warn' : ''}">${esc(last(x))}</span><div class="actions"><button class="link" data-action="run-schedule" data-id="${esc(x.id)}">立即執行</button>${(x.runs || []).length ? `<button class="link" data-action="schedule-history" data-id="${esc(x.id)}">紀錄</button>` : ''}<button class="link" data-action="edit-schedule" data-id="${esc(x.id)}">編輯</button><button class="link" data-action="delete-schedule" data-id="${esc(x.id)}">刪除</button></div></article>`).join('')}</div>`;
  }
