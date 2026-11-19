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
  // Limits and Zook's own usage of one sign-in, as the parts of its card.
  function usageParts(p) {
    if (!state.quota) return {body: loadingBlock('正在偵測使用量…'), zook: '<div class="zook-usage empty"></div>', when: ''};
    if (state.quota.error) return {body: `<p class="error-text small">${esc(state.quota.error)}</p>`, zook: '<div class="zook-usage empty"></div>', when: ''};
    if (!p) return {body: '', zook: '<div class="zook-usage empty"></div>', when: ''};
    const money = v => v == null ? '' : ' · $' + v.toFixed(v < 1 ? 3 : 2), s = p.quota, ready = ['logged_in', 'installed'].includes(p.status);
    let body;
    if (!ready) body = '<p class="quota-empty">登入後才能查看額度。</p>';
    else if (p.apiBilling) body = '<p class="quota-empty">使用 API 計費，沒有 5 小時／每週額度，費用依用量計算。</p>';
    else if (p.noQuotaApi) body = '<p class="quota-empty">這個 CLI 不提供方案額度給 Zook，下方是 Zook 記錄的用量。</p>';
    else if (!s || !(s.windows || []).length) body = '<p class="quota-empty">還沒有額度資料，按右上角「偵測使用量」讀取。</p>';
    else body = s.windows.map(w => {
      const used = Math.max(0, Math.min(100, w.usedPercent)), left = Math.round((100 - used) * 10) / 10, level = used >= 90 ? 'bad' : used >= 70 ? 'warn' : '';
      return `<div class="quota-row"><div class="quota-label"><span>${esc(w.label)}</span><span><b>剩餘 ${left}%</b><small>已用 ${Math.round(used * 10) / 10}%</small></span></div><div class="quota-track"><div class="quota-bar ${level}" style="width:${used}%"></div></div><small class="quota-reset">${esc(fmtReset(w.resetsAt))}</small></div>`;
    }).join('') + (s.credits && (s.credits.unlimited || (s.credits.balance && s.credits.balance !== '0')) ? `<p class="quota-extra">額外額度：${s.credits.unlimited ? '不限' : esc(s.credits.balance)}</p>` : '')
      + (s.limitReached ? `<p class="error-text small">已達上限：${esc(s.limitReached)}</p>` : '');
    const z = p.zookUsage;
    const coupons = s?.resetCredits && ready ? `<span class="quota-coupon">額度重置券 ${s.resetCredits} 張（在 Codex 中使用）</span>` : '';
    const zook = !(z && ready) ? '<div class="zook-usage empty"></div>' : `<div class="zook-usage"><span class="zook-usage-title"><span>用量</span>${coupons}</span><div><span>近 5 小時</span><b>${fmtN(z.fiveHour.tokens)}</b><small>${z.fiveHour.replies} 次回覆${money(z.fiveHour.costUsd)}</small></div><div><span>近 7 天</span><b>${fmtN(z.week.tokens)}</b><small>${z.week.replies} 次回覆${money(z.week.costUsd)}</small></div></div>`;
    const stamp = d => { const t = new Date(d); return isNaN(t) ? '' : ` · ${t.getMonth() + 1}/${t.getDate()} ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`; };
    const when = s?.updatedAt && (s.windows || []).length ? (s.source === 'live' ? '即時查詢' : s.source === 'probe' ? '手動偵測' : '定時更新') + stamp(s.updatedAt) : '暫無資料';
    return {body, zook, when};
  }
  const quotaFor = (id, account) => { const q = (state.quota?.providers || []).find(x => x.id === id); return account ? (q?.profiles || []).find(x => x.id === account) : q; };
  function botUsageSection() {
    const u = state.botUsage;
    if (!u) return `<section class="usage-block"><h2>Bot Token 用量</h2>${loadingBlock('正在整理用量…')}</section>`;
    if (u.error) return `<section class="usage-block"><h2>Bot Token 用量</h2><div class="blank error-text">${esc(u.error)}</div></section>`;
    const rows = [...(u.bots || [])].sort((a, b) => (a.deleted ? 1 : 0) - (b.deleted ? 1 : 0)), max = Math.max(1, ...rows.flatMap(r => Object.values(r.daily)));  // deleted Bots last, each group keeps its usage order
    const days = (u.days || []).map(d => d.slice(5).replace('-', '/'));
    return `<section class="usage-block"><h2>Bot Token 用量</h2>${rows.length ? `<div class="bot-usage"><div class="bot-usage-row head"><span>Bot</span><span>回覆</span><span>輸入</span><span>輸出</span><span>估算費用</span><span>近 7 天（${esc(days[0] || '')}–${esc(days.at(-1) || '')}）</span></div>${rows.map(r => `<div class="bot-usage-row ${r.deleted ? 'deleted' : ''}" ${r.deleted ? 'title="已刪除的 Bot"' : ''}><span class="bot-cell">${avatar(r)}<span><strong>${esc(r.name)}${r.restorable ? `<button class="link restore-bot" data-up="restore-bot" data-id="${esc(r.botId)}">喚回</button>` : ''}</strong><small>${Object.entries(r.models).sort((a, b) => b[1] - a[1]).map(([m]) => esc(m)).join('、')}</small></span></span><span>${fmtN(r.replies)}${r.groupReplies ? `<small>群組 ${fmtN(r.groupReplies)}</small>` : ''}</span><span>${fmtN(r.input)}${r.cachedInput ? `<small>快取 ${fmtN(r.cachedInput)}</small>` : ''}</span><span>${fmtN(r.output)}</span><span>${r.costUsd == null ? '<small>訂閱內</small>' : '$' + r.costUsd.toFixed(r.costUsd < 1 ? 4 : 2) + '<small>API 等值</small>'}</span><span class="spark">${Object.values(r.daily).map((v, i) => `<i style="height:${Math.max(v ? 8 : 2, Math.round(v / max * 100))}%" title="${esc(days[i])}：${fmtN(v)} tokens"></i>`).join('')}</span></div>`).join('')}</div>` : '<div class="blank">還沒有用量紀錄。Bot 回覆後就會出現在這裡。</div>'}</section>`;
  }

  // Permission modes: which tool actions need the user's approval.
  const PERMISSIONS = [
    {id: 'manual', name: '謹慎', hint: '有變動就先問', rows: ['讀取：直接執行（外部服務先問）', 'Zook 內變更：先問', '程式與外部服務：先問']},
    {id: 'auto', name: '自動', hint: 'Zook 內自動完成，涉及程式或外部服務才問', rows: ['讀取：直接執行', 'Zook 內變更：直接執行', '程式與外部服務：先問']},
    {id: 'bypass', name: '全部允許', hint: '只有高風險動作會問', rows: ['讀取：直接執行', 'Zook 內變更：直接執行', '程式與外部服務：直接執行']},
  ];
  const ALWAYS_ASK = '刪除、帳號與權限、寄信或發布';
  const EFFORT_LABEL = {fast: '快速回答', deep: '深入思考'};
  // 自動選擇 shows as a small mark at the very end of the reply; replies saved by 0.9.0 carry it as a sentence.
  const AUTO_OLD = {'簡短問答': 'simple', '寫程式': 'code', '看圖': 'image', '長篇分析': 'analysis'};
  const autoInfo = m => {
    if (m.auto) return {mark: m.auto, why: m.autoWhy || ''};
    const old = /^自動選用 (.+?)：(簡短問答|寫程式|看圖|長篇分析)(（.+）)?$/.exec(m.note || '');
    return old ? {mark: `${old[1]} ${AUTO_OLD[old[2]]}`, why: m.note} : null;
  };
  const withAutoMark = (html, m) => {
    const info = autoInfo(m);
    if (!info) return html;
    const mark = `<span class="auto-mark" title="${esc(info.why)}">(auto: ${esc(info.mark)})</span>`;
    return html.endsWith('</p>') ? `${html.slice(0, -4)} ${mark}</p>` : `${html}<p class="auto-mark-line">${mark}</p>`;
  };
  const skippedNote = m => (m.skipped || []).length ? '這次沒用到的連接器：' + m.skipped.join('、') : '';
  const noteLine = m => ((autoInfo(m) && !m.auto ? '' : m.note) || EFFORT_LABEL[m.effort] || skippedNote(m)) ? `<small class="msg-note">${esc([EFFORT_LABEL[m.effort], autoInfo(m) && !m.auto ? '' : m.note, skippedNote(m)].filter(Boolean).join(' · '))}</small>` : '';
  // 思考強度 beside the message box: remembered per Bot or group while Zook is open; starts at the Bot's default.
  const EFFORTS = [{id: 'fast', name: '快速', hint: '想得少一點，回得快'}, {id: 'standard', name: '標準', hint: '模型自己的預設'}, {id: 'deep', name: '深入', hint: '想得更久、更仔細，用量較多'}];
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
  const longControl = b => `<label class="plan-toggle" title="最長可以跑 4 小時，結束時通知你">${toggle(`data-long`, !!state.long[b.id], '長任務')}<span>長任務</span></label>`;
  const planControl = b => !effortSupported() ? '' : `<label class="plan-toggle" title="這則訊息只請 Bot 提出計畫，不動手">${toggle(`data-plan`, !!state.plan[b.id], '先規劃')}<span>先規劃</span></label>`;
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
  const permissionOptions = withDefault => (withDefault ? [{id: '', name: '使用預設（' + permissionName(state.data.settings.permissionMode) + '）', hint: ''}] : []).concat(PERMISSIONS.map(p => ({id: p.id, name: p.name, hint: p.hint})));
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
  function remoteSection() {
    const r = state.remote;
    if (!r) return `<h2 class="settings-h">遠端連線</h2>${loadingBlock('正在讀取…')}`;
    if (!r.available) return '';
    const status = !r.enabled ? '已關閉' : r.connected ? '已連上中繼伺服器' : '連不上中繼伺服器';
    const when = d => d ? formatDate(d) : '尚未使用';
    const devices = r.devices.length ? r.devices.map(d => `<div class="setting-row device-row"><div class="setting-copy"><strong>${esc(d.name)}${d.online ? ' <span class="pill ok">連線中</span>' : ''}</strong><span>配對於 ${esc(formatDate(d.createdAt))} · 最後使用：${esc(when(d.lastSeenAt))}</span></div><div class="setting-control"><button class="secondary small-btn" data-action="remote-revoke" data-id="${esc(d.id)}">撤銷</button></div></div>`).join('') : '<p class="muted small">還沒有配對任何裝置。</p>';
    return `<h2 class="settings-h">遠端連線</h2><div class="setting-list">${settingRow('讓其他裝置連到這台 Mac', '開啟後，已配對的手機可以對話和核准。內容全程加密。', toggle('data-remote-enabled', r.enabled, '遠端連線'))}${settingRow('中繼伺服器', '你自己的中繼伺服器網址，以 wss:// 開頭。', `<input class="relay-input" data-remote-relay value="${esc(r.relayUrl)}" placeholder="wss://…" aria-label="中繼伺服器網址" spellcheck="false">`)}${settingRow('狀態', r.enabled && !r.connected ? '請確認網址正確，而且這台 Mac 有連上網路。' : '', `<span class="remote-status ${r.enabled ? (r.connected ? 'ok' : 'bad') : ''}">${status}</span>`)}</div><div class="remote-devices"><div class="remote-devices-head"><strong>已配對的裝置</strong><button class="secondary small-btn" data-action="remote-pair" ${r.enabled ? '' : 'disabled'}>配對新裝置</button></div>${devices}</div><p class="muted small perm-always">手機只能對話、核准和查看。其他設定要在這台 Mac 上改。</p>`;
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
    return `<div class="setting-list">${settingRow('主動性', '動作前要不要先問', dropdown('permissionMode', current, permissionOptions(false), 'data-permission-mode'))}${settingRow('上網搜尋', '搜尋和讀取網頁，不逐次詢問', toggle('data-web-search', state.data.settings.webSearch, '上網搜尋'))}</div><p class="muted small perm-always">${ALWAYS_ASK}屬高風險，任何主動性都會先問。</p>` + botDefaultsSection();
  }

  // What every Bot does unless its own 進階設定 says otherwise.
  function botDefaultsSection() {
    const st = state.data.settings, access = ACCESS.some(a => a.id === st.access) ? st.access : 'full';
    return `<h2 class="settings-h">Bot 預設</h2><p class="muted small settings-note">所有 Bot 共用。個別 Bot 可在「進階設定」另外指定。</p><div class="setting-list">${settingRow('存取範圍', '可以動到哪些檔案', dropdown('defaultAccess', access, ACCESS, 'data-bot-default="access"'))}<div class="setting-row" ${access === 'folder' ? '' : 'hidden'}><div class="setting-copy"><strong>指定的資料夾</strong><span>${esc(st.accessFolder || '尚未選擇')}</span></div><div class="setting-control"><button type="button" class="secondary" data-action="default-folder">選擇資料夾…</button></div></div>${settingRow('思考強度', '', dropdown('defaultEffort', st.effort || 'standard', EFFORTS, 'data-bot-default="effort"'))}${settingRow('多代理協作', '派子代理分工，用量較多', toggle('data-bot-default="multi"', st.features?.multi === true, '多代理協作'))}${settingRow('圖片生成', '用 AI 生成圖片', toggle('data-bot-default="image"', st.features?.image === true, '圖片生成'))}</div>`;
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
  const SKILLS_ON = '已開啟';
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
      return (inv.skills || []).filter(i => !i.imported).map(i => ({id: i.id, icon: i.icon, name: i.name, description: i.description || '', group: !off.has(i.id) ? SKILLS_ON : skillCategory(i),
        meta: i.imported ? '改用 Zook 裡的那一份' : i.source === 'zook' && SOURCE_NAMES[i.origin] ? '匯入自 ' + SOURCE_NAMES[i.origin] : i.source === 'zook' && i.origin === 'pack' ? '來自設定包' : i.source === 'zook' && i.origin === 'template' ? '來自範本' : sourceName(i.plugin || i.source),
        on: !i.imported && !off.has(i.id), toggle: 'skill', toggleLabel: off.has(i.id) ? '開放給所有 Bot' : '所有 Bot 共用中',
        moved: i.imported ? '已匯入' : '', importable: i.source !== 'zook' && !i.imported, removable: !!i.removable, canUpdate: !!i.canUpdate, note: (i.notes || []).join(' ')}));
    }
    if (tab === 'mcp') {
      return (inv.mcp || []).map(i => {
        const on = (settings.sharedMcp || []).includes(i.id);
        const [cls, label] = mcpStatus(i);
        const description = i.id === 'builtin:workspace' ? '在 Bot 自己的工作區讀寫檔案。' : i.needsKey ? '匯入時沒有帶金鑰，請貼上金鑰。' : i.copied ? 'Zook 已經有自己的一份，Bot 用的是 Zook 那一份。' : i.gmail && i.needsSetup ? '搜尋、讀信、寫草稿和寄信。寄信前一定先問。' : (t => t?.status === 'error' ? '連線失敗：' + t.error : t?.status === 'ready' ? '可用工具：' + (t.tools || []).slice(0, 8).map(x => x.name.replace(/_/g, ' ')).join('、') : i.gmail ? `已連接 ${i.address}。寄信前一定先問。` : i.editable ? (i.config.command || i.config.url) : sourceName(i.plugin || i.source, 'mcp') + '。按「測試連線」確認是否可以使用。')(state.mcpTests[i.id]);
        return {id: i.id, icon: i.icon, name: i.id === 'builtin:workspace' ? 'Bot 工作區' : i.name, description, group: sourceName(i.plugin || i.source, 'mcp'), meta: i.copied ? '來源設定仍保留' : i.needsKey ? '等待金鑰' : on ? '所有 Bot 共用中' : '未開啟',
          on: on && !i.copied && !i.needsKey, toggle: 'mcp', toggleLabel: on ? '停用這個連接器' : '開放給所有 Bot', status: i.copied ? null : [cls, label], test: i.id !== 'builtin:workspace' && !i.needsSetup && !i.needsKey && !i.copied, editable: !!i.editable, gmail: !!i.gmail, google: !!i.google, needsSetup: !!i.needsSetup,
          needsKey: !!i.needsKey, moved: i.copied ? '已複製' : '', copyable: !!i.copyable, canLogin: !!i.canLogin, signedIn: !!i.signedIn, needsLogin: !!i.needsLogin, accounts: i.accounts || []};
      });
    }
    return (inv.plugins || []).map(pl => ({id: pl.id, icon: pl.icon, name: pl.displayName, description: pl.description || '', group: pl.sourceName,
      meta: [pl.skillCount ? pl.skillCount + ' 個 Skill' : '', pl.mcpCount ? pl.mcpCount + ' 個連接器' : '', pl.version ? 'v' + pl.version : ''].filter(Boolean).join(' · ') || '沒有 Zook 可用的內容',
      note: pl.hasHooks || pl.hasCommands ? '部分功能只在原本的工具中運作' : '', on: pl.enabled, toggle: 'plugin', toggleLabel: pl.enabled ? '已啟用' : '啟用'}));
  }
  function directoryPage(tab) {
    if (!state.integrations) return '<div class="blank">正在讀取…</div>';
    const q = (state.dirQuery || '').toLowerCase(), filter = state.dirFilter || 'all';
    const items = directoryItems(tab).filter(i => (!q || (i.name + ' ' + i.description + ' ' + i.group).toLowerCase().includes(q)) && (filter === 'all' || (filter === 'on') === i.on));
    const first = tab === 'skills' ? [SKILLS_ON, ...SKILL_CATEGORIES.map(c => c[0]), '其他'] : [SOURCE_NAMES.builtin, MCP_SOURCE_NAMES.zook];
    const rank = g => first.includes(g) ? first.indexOf(g) : first.length;
    const found = tab === 'mcp' ? items.filter(i => i.group === MCP_FOUND && !i.moved) : [];
    const groups = [...new Set(items.map(i => i.group))].filter(g => g !== MCP_FOUND).sort((a, b) => rank(a) - rank(b));
    const counts = {skills: (state.integrations.skills || []).filter(i => !i.imported).length, mcp: (state.integrations.mcp || []).filter(i => !i.copied).length, plugins: (state.integrations.plugins || []).length};
    const tabs = [['skills', 'Skills'], ['mcp', '連接器'], ['plugins', '插件']];
    const intro = {skills: '所有 Bot 共用。匯入後不受原工具影響。', mcp: '所有 Bot 共用。開得越多回覆越慢，用不到的建議關閉。', plugins: '插件會一次帶來一組 Skills 和連接器，來源是 Claude Code。'}[tab];
    const card = i => {
      const expanded = state.dirExpanded?.[i.id];
      return `<article class="dir-card ${expanded ? 'expanded' : ''}">${itemIcon(i.name, i.icon)}<div class="dir-body"><div class="dir-title"><h3 title="${esc(i.name)}">${esc(i.name)}</h3>${i.needsSetup ? `<button class="primary small-btn" data-action="${i.google ? 'google-setup' : 'gmail-setup'}">${i.google ? '登入' : '設定'}</button>` : i.needsKey ? `<button class="primary small-btn" data-action="connector-edit" data-id="${esc(i.id)}">貼上金鑰</button>` : i.moved ? `<span class="dir-status">${i.moved}</span>` : toggle(`data-dir-switch data-kind="${i.toggle}" data-id="${esc(i.id)}" title="${esc(i.toggleLabel)}"`, i.on, i.toggleLabel)}</div>${(i.accounts || []).length ? `<div class="account-pick" title="所有 Bot 使用這個帳號">${dropdown('connectorAccount', i.accounts.find(a => a.active)?.id || '', i.accounts.map(a => ({id: a.id, name: a.name + (a.needsLogin ? '（需要重新登入）' : '')})), `data-connector="${esc(i.id)}"`)}</div>` : ''}<p class="dir-desc">${esc(i.description || '沒有說明。')}</p>${i.description.length > 70 ? `<button class="link dir-more" data-action="dir-expand" data-id="${esc(i.id)}">${expanded ? '收合' : '展開'}</button>` : ''}<div class="dir-meta">${i.status ? `<span class="dir-status ${i.status[0]}">${esc(i.status[1])}</span>` : ''}<span>${esc(i.meta)}</span>${i.test ? `<button class="link" data-action="test-mcp" data-id="${esc(i.id)}">測試連線</button>` : ''}${i.google && !i.needsSetup ? '<button class="link" data-action="google-add">新增帳號</button><button class="link" data-action="google-setup">重新登入</button><button class="link danger" data-action="google-remove">登出這個帳號</button>' : ''}${i.gmail && !i.needsSetup ? '<button class="link" data-action="gmail-setup">重新設定</button><button class="link danger" data-action="gmail-remove">中斷連接</button>' : ''}${i.copyable ? `<button class="link" data-action="connector-copy" data-id="${esc(i.id)}">加入</button>` : ''}${i.canUpdate ? `<button class="link" data-action="skill-update" data-id="${esc(i.id)}" title="原本的來源有更新">從原來源更新</button>` : ''}${i.removable ? `<button class="link danger" data-action="skill-remove" data-id="${esc(i.id)}" data-name="${esc(i.name)}">移除</button>` : ''}${i.canLogin ? (i.signedIn ? `<button class="link" data-action="connector-login" data-id="${esc(i.id)}" data-add="1">新增帳號</button><button class="link" data-action="connector-logout" data-id="${esc(i.id)}">登出這個帳號</button>` : `<button class="link" data-action="connector-login" data-id="${esc(i.id)}">${i.needsLogin ? '重新登入' : '登入'}</button>`) : ''}${i.editable ? `<button class="link" data-action="connector-edit" data-id="${esc(i.id)}">編輯</button><button class="link danger" data-action="connector-delete" data-id="${esc(i.id)}" data-name="${esc(i.name)}">移除</button>` : ''}</div>${i.note ? `<p class="dir-note">${esc(i.note)}</p>` : ''}</div></article>`;
    };
    return `<div class="dir-bar"><div class="dir-tabs">${tabs.map(([id, label]) => `<button class="${tab === id ? 'active' : ''}" data-action="dir-tab" data-id="${id}">${label}<small>${counts[id]}</small></button>`).join('')}</div><div class="dir-filters">${dropdown('dirFilter', filter, [{id: 'all', name: '全部'}, {id: 'on', name: '已啟用'}, {id: 'off', name: '未啟用'}], 'data-dir-filter')}</div><input id="dir-search" class="dir-search" placeholder="搜尋" aria-label="搜尋" value="${esc(state.dirQuery || '')}"></div><p class="muted dir-intro">${intro}</p>${tab === 'mcp' ? '<div class="dir-add"><button class="secondary" data-action="connector-add">＋ 自己新增</button><span class="muted small">開啟的連接器所有模型都能用。</span></div>' : ''}${tab === 'plugins' ? '' : `<div class="dir-add"><button class="secondary" data-action="pack-export">匯出設定包</button><button class="secondary" data-action="pack-import">匯入設定包</button><span class="muted small">搬到另一台 Mac 用。不含金鑰。</span></div>`}${groups.length ? groups.map(g => { const closed = (state.data.settings.dirCollapsed || []).includes(tab + ':' + g) && !q; return `<section class="dir-section"><h2><button class="dir-fold" data-action="dir-collapse" data-id="${esc(tab + ':' + g)}" aria-expanded="${!closed}"><span>${esc(g)}</span><small>${items.filter(i => i.group === g).length}</small><span class="dir-chev" aria-hidden="true">${closed ? '⌄' : '⌃'}</span></button>${tab === 'skills' && items.some(i => i.group === g && i.importable) ? `<button class="link dir-import" data-action="skills-import" data-id="${esc(g)}">匯入到 Zook</button>` : ''}</h2>${closed ? '' : `<div class="dir-grid">${items.filter(i => i.group === g).map(card).join('')}</div>`}</section>`; }).join('') : '<div class="blank">沒有符合的項目。</div>'}${tab === 'skills' ? templateSections(q) : ''}${tab === 'mcp' ? catalogSections(q) + (found.length ? `<section class="dir-section found-section"><h2><button class="dir-fold" data-action="found-toggle" aria-expanded="${!!state.foundOpen || !!q}"><span>${MCP_FOUND}</span><small>${found.length}</small><span class="dir-chev" aria-hidden="true">${state.foundOpen || q ? '⌃' : '⌄'}</span></button></h2>${state.foundOpen || q ? `<p class="muted small">來自 Codex 或 Claude 的設定。按「加入」移到已連接。</p><div class="dir-grid">${found.map(card).join('')}</div>` : ''}</section>` : '') : ''}`;
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
    const types = [{id: 'stdio', name: '本機指令', hint: '在這台 Mac 上執行的程式，例如用 npx 或 uvx 啟動的 MCP 伺服器'}, {id: 'http', name: '網址', hint: '遠端的 MCP 伺服器（Streamable HTTP）'}];
    const kept = c.hasSecret ? '已儲存。留空表示不變更' : '';
    modal(item ? '編輯連接器' : '新增連接器', `<form id="connector-form" data-id="${esc(item ? item.id.split(':')[1] : '')}"><div class="modal-body"><label class="field">名稱<input name="name" required maxlength="80" placeholder="例如：GitHub" value="${esc(item?.name || '')}"></label><div class="setting-list in-form">${settingRow('類型', '連接器在哪裡執行', dropdown('transport', http ? 'http' : 'stdio', types))}</div><div data-for="stdio" ${http ? 'hidden' : ''}><label class="field">啟動指令<input name="command" spellcheck="false" placeholder="例如：npx -y @modelcontextprotocol/server-github" value="${esc(c.command || '')}"><small class="muted">和你在終端機輸入的一樣。Zook 會在需要時啟動它。</small></label><label class="field">環境變數（選填，每行一個）<textarea name="env" rows="3" spellcheck="false" placeholder="NAME=value">${esc(Object.entries(c.env || {}).map(([k, v]) => k + '=' + v).join('\n'))}</textarea></label><div class="form-grid"><label class="field">金鑰的環境變數名稱（選填）<input name="secretName" spellcheck="false" placeholder="例如：GITHUB_TOKEN" value="${esc(http ? '' : c.secretName || '')}"></label><label class="field">金鑰<input name="secretStdio" type="password" autocomplete="off" spellcheck="false" placeholder="${esc(http ? '' : kept)}"></label></div>${(c.moreSecrets || []).map(m => `<label class="field">金鑰 ${esc(m.name)}<input name="more:${esc(m.name)}" type="password" autocomplete="off" spellcheck="false" placeholder="${m.saved ? '已儲存。留空表示不變更' : '請貼上這把金鑰'}"></label>`).join('')}</div><div data-for="http" ${http ? '' : 'hidden'}><label class="field">網址<input name="url" spellcheck="false" placeholder="https://example.com/mcp" value="${esc(c.url || '')}"></label><label class="field">存取權杖（選填）<input name="secretHttp" type="password" autocomplete="off" spellcheck="false" placeholder="${esc(http ? kept : '')}"><small class="muted">會以 Bearer 權杖送給這個網址。</small></label></div><p class="muted small">金鑰只存在鑰匙圈。${c.hasSecret ? ' <label class="inline-check"><input type="checkbox" name="clearSecret"> 移除已儲存的金鑰</label>' : ''}</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${item ? '儲存' : '新增'}</button></div></form>`);
  }
  function mcpBotsModal(id) {
    const item = (state.integrations?.mcp || []).find(i => i.id === id);
    if (!item) return;
    modal('選擇使用「' + (id === 'builtin:workspace' ? 'Bot 工作區' : item.name) + '」的 Bot', `<form id="mcp-bots-form" data-id="${esc(id)}"><div class="modal-body"><p class="muted">選擇哪些 Bot 可以使用。</p><div class="member-pick">${state.data.bots.map(b => `<label class="ability-option"><input type="checkbox" name="bots" value="${esc(b.id)}" ${(b.enabledMcp || []).includes(id) ? 'checked' : ''}><span>${avatar(b)}<strong>${esc(b.name)}</strong><small>${esc((b.persona || b.instructions || '').slice(0, 40))}</small></span></label>`).join('')}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">儲存</button></div></form>`);
  }

  function detail(b) {
    let notes = state.data.knowledge.filter(n => n.botId === b.id);
    return `<aside class="detail"><button class="detail-close icon-btn" data-action="toggle-detail" aria-label="關閉詳情">×</button><div class="detail-profile">${avatar(b,'big')}<h2>${esc(b.name)}</h2><p>${esc(b.provider === 'auto' ? '自動選擇' : b.provider||state.data.settings.provider||'')} ${esc(b.model||'')}</p><p>主動性：${esc(permissionName(b.permissionMode || state.data.settings.permissionMode))}${b.permissionMode ? '' : '（預設）'}</p><button class="secondary detail-edit" data-action="edit-bot">編輯設定</button></div><div class="tabs"><button data-action="detail" data-id="persona" class="${state.detail==='persona'?'active':''}">人格</button><button data-action="detail" data-id="activity" class="${state.detail==='activity'?'active':''}">動態</button><button data-action="detail" data-id="database" class="${state.detail==='database'?'active':''}">資料庫</button><button data-action="detail" data-id="outputs" class="${state.detail==='outputs'?'active':''}">產出</button></div>${state.detail==='persona'?personaPanel(b):state.detail==='outputs'?outputsPanel(b):state.detail==='database'?`<div class="detail-title">知識 <button class="link" data-action="new-note">＋ 新增</button></div>${notes.length?notes.map(n=>`<button class="note-row" data-action="edit-note" data-id="${esc(n.id)}"><strong>${esc(n.title)}</strong><small>${esc(n.content)}</small></button>`).join(''):'<div class="detail-empty">尚未新增知識。加入資料，讓這個 Bot 有更多背景。</div>'}`:`<div class="detail-title">最近動態</div>${toolTimeline(b.id)}${(b.messages||[]).length?`<div class="detail-empty">最近對話 ${esc(formatDate(b.messages.at(-1).createdAt))}</div>`:'<div class="detail-empty">這裡會顯示最近的對話動態。</div>'}`}</aside>`
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
    if (form.elements.provider.value === 'auto') return;
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
      select.innerHTML = '<option value="">使用預設</option>' + models.map(m => `<option value="${esc(m.id)}">${esc(m.name||m.id)}${m.source==='alias'?'（別名）':m.source==='cache'?'（快取）':''}</option>`).join('') + '<option value="__custom__">自訂模型…</option>';
      const known = models.some(m => m.id === current);
      const custom = form.elements.modelCustom;
      if ((current && !known) || wasCustom) {
        select.value = '__custom__'; custom.value = current; custom.hidden = false;
      } else {
        select.value = current || ''; custom.hidden = true;
      }
      note.textContent = (data.note || (models.length ? '模型清單已更新。' : '未偵測到模型，可使用預設或自行輸入。')) + (form.dataset.providerChanged ? ' 提供者已變更，模型已切換為預設。' : '');
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
      for (const key of ['name','instructions','provider','model','section','shape','color']) {
        if (draft[key] != null && form.elements[key]) form.elements[key].value = draft[key];
      }
      form.elements.pinned.checked = !!draft.pinned;
      form.querySelector('.bot-preview .avatar').className = `avatar shape-${shapeIndex(draft.shape)} hero`;
      form.querySelectorAll('.avatar').forEach(x => x.style.setProperty('--c', draft.color));
      form.querySelectorAll('.shape-btn').forEach(x => x.classList.toggle('selected', x.dataset.id === draft.shape));
      form.querySelectorAll('.swatch').forEach(x => x.classList.toggle('selected', x.dataset.id === draft.color));
    } catch (_) {}
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
      const who = id => state.data.bots.find(b => b.id === id)?.name || '已刪除的 Bot';
      content = `<p class="muted">Bot 記下的長期記憶。「共用」給所有 Bot。</p>${mems.length ? `<div class="cards">${mems.map(m => `<article class="card"><p>${esc(m.content)}</p><span class="status">${m.botId ? esc(who(m.botId)) : '共用'} · 由 ${esc(who(m.createdBy))} 記下 · ${esc(formatDate(m.createdAt))}</span><div class="actions"><button class="link" data-action="delete-memory" data-id="${esc(m.id)}" style="color:#b55">刪除</button></div></article>`).join('')}</div>` : '<div class="blank">還沒有記憶。和 Bot 聊天時說「記住…」，它就會記下來。</div>'}`;
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
      content = guideCard() + accountsPage() + budgetSection() + botUsageSection() + `<details class="usage-local"><summary>本機 CLI 全部紀錄（包含 Zook 以外的使用）</summary><p>${esc(u.note||'本機記錄的使用情況。')} ${u.truncated?'資料已截斷。':''}</p><div class="stats">${metrics.map(([k,v])=>`<div class="card"><span class="muted">${k}</span><div class="stat-num">${v.toLocaleString()}</div></div>`).join('')}</div>${groups.length?`<div class="usage-chart">${groups.slice(0,14).map(g=>`<div class="usage-row"><span>${esc(g.date)} · ${esc(g.provider)}</span><div class="usage-track"><div class="usage-bar" style="width:${Math.round(100*((g.inputTokens||0)+(g.outputTokens||0))/Math.max(1,...groups.map(x=>(x.inputTokens||0)+(x.outputTokens||0))))}%"></div></div><small>${((g.inputTokens||0)+(g.outputTokens||0)).toLocaleString()} tokens</small></div>`).join('')}</div><div class="cards">${groups.map(g=>`<div class="card"><h3>${esc(g.date)} · ${esc(g.provider)}</h3><p>${esc(g.model)}<br>${(g.inputTokens||0).toLocaleString()} 輸入 / ${(g.outputTokens||0).toLocaleString()} 輸出</p></div>`).join('')}</div>`:'<div class="blank">尚無使用紀錄。</div>'}` + '</details>';
      if (!state.usage || state.usage.error) content = guideCard() + accountsPage() + budgetSection() + botUsageSection() + `<details class="usage-local"><summary>本機 CLI 全部紀錄（包含 Zook 以外的使用）</summary>${state.usage?.error ? `<div class="blank error-text">${esc(state.usage.error)}</div>` : loadingBlock('正在讀取本機紀錄…')}</details>`;
    } else if (state.page === 'plugins-legacy') {
      const list = state.integrations?.plugins || [];
      content = `<p class="muted">來自 Claude Code 的插件。啟用後所有 Bot 共用。</p>${list.length ? `<div class="cards">${list.map(pl => {
        const parts = [pl.skillCount ? pl.skillCount + ' 個 Skill' : '', pl.mcpCount ? pl.mcpCount + ' 個 MCP' : ''].filter(Boolean).join(' · ') || '沒有 Zook 可用的內容';
        const notes = [pl.hasHooks ? 'hooks' : '', pl.hasCommands ? '指令' : ''].filter(Boolean);
        return `<article class="card plugin-card ${pl.enabled ? '' : 'off'}"><div class="plugin-head"><h3>${esc(pl.displayName)}</h3><span class="status">${esc(pl.sourceName)}${pl.version ? ' · v' + esc(pl.version) : ''}</span></div><p>${esc(pl.description || '')}</p><p class="muted">${esc(parts)}${pl.author ? ' · ' + esc(pl.author) : ''}</p>${notes.length ? `<p class="muted small">包含 ${esc(notes.join('、'))}，這部分只在原本的工具中運作，Zook 不會執行。</p>` : ''}<label class="ability-check"><input type="checkbox" data-plugin-toggle="${esc(pl.id)}" ${pl.enabled ? 'checked' : ''}> 啟用</label></article>`;
      }).join('')}</div>` : '<div class="blank">沒有偵測到插件。</div>'}`;
    } else if (state.page === 'settings') {
      let s = state.data.settings || {};
      content = permissionSection(s.permissionMode || 'manual') + rulesSection() + `<h2 class="settings-h">模型</h2><form id="settings-form" class="setting-list">${settingRow('預設提供者', '', `<select name="provider" class="plain-select" aria-label="預設提供者">${providerOptions(s.provider || 'codex', false)}</select>`)}${settingRow('預設模型', '沒指定模型的 Bot 使用', modelPicker(s.model||'', true))}${[0, 1].map(i => settingRow('備用模型 ' + (i + 1), i ? '第一個備用也不能用時' : '模型不能用時改用', dropdown('fallback' + i, (s.fallbacks || [])[i] || '', [{id: '', name: '不使用'}, ...providerList()], 'data-fallback-slot'))).join('')}<div class="setting-actions"><button class="primary">儲存模型設定</button></div></form>` + chatSection() + noticeSection() + voiceSection() + remoteSection() + syncSection() + backupSection() + updateSection()
    }
    return `<main class="main"><header class="main-header"><div class="bot-pill">Zook</div></header><div class="page"><div class="page-inner"><div class="page-top"><h1>${name}</h1>${state.page==='knowledge'?'<button class="primary" data-action="new-note">＋ 新增知識</button>':state.page==='usage'?`<div class="page-top-actions"><button class="secondary" data-action="detect-usage" ${state.usageBusy ? 'disabled' : ''}>${state.usageBusy === 'detect' ? '偵測中…' : '偵測使用量'}</button><button class="secondary" data-action="update-all" ${state.usageBusy ? 'disabled' : ''}>${state.usageBusy === 'update' ? '更新中…' : '一鍵全更新'}</button><button class="primary" data-action="provider-add">＋ 新增模型</button></div>`:state.page==='schedules'?'<button class="primary" data-action="new-schedule">＋ 新增排程</button>':''}</div>${content}</div></div></main>`
  }

  function render(keepScroll = false) {
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
    app.innerHTML = `<div class="layout">${sidebar()}${state.page==='chat'?(activeGroup()?groupChat():chat()):page()}</div>`;
    if ($('#chat-input')) {
      $('#chat-input').value = input;
      if (cursor !== null) { $('#chat-input').focus(); $('#chat-input').setSelectionRange(cursor[0], cursor[1]); }
    }
    updateMentionMenu();
    if (localOpen && $('.usage-local')) $('.usage-local').open = true;
    if (pageY && $('.page')) $('.page').scrollTop = pageY;
    document.querySelectorAll('[data-approval-details]').forEach(x => { if (openApprovals.includes(x.dataset.approvalDetails)) x.open = true; });
    if ($('#conversation')) {
      const c = $('#conversation');
      if (!keepFocus()) c.scrollTo({top: y != null && !nearBottom ? y : c.scrollHeight, behavior: 'instant'});
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
    const id = form.elements.provider?.value || state.data.settings.provider || 'codex', offered = (state.providers || []).find(p => p.id === id)?.features || [];
    form.querySelectorAll('[data-feature-row]').forEach(row => { row.hidden = !offered.includes(row.dataset.featureRow); });
    const auto = id === 'auto';  // each reply picks its own model, so these choices do not apply
    form.querySelectorAll('[data-account-field],.model-picker,[data-fixed-model]').forEach(el => { el.hidden = auto; });
    const hint = form.querySelector('[data-auto-hint]');
    if (hint) hint.hidden = !auto;
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
    const featureChoice = key => b.features && key in b.features ? (b.features[key] ? 'on' : 'off') : '';
    const featureOptions = key => [{id: '', name: '使用預設（' + (st.features?.[key] ? '開啟' : '關閉') + '）'}, {id: 'on', name: '開啟'}, {id: 'off', name: '關閉'}];
    const ownAccess = ACCESS.some(x => x.id === b.access) ? b.access : '';
    modal(editing ? '編輯 Bot' : '新增 Bot', `<form id="bot-form"><div class="modal-body"><div class="bot-preview"><button type="button" class="avatar-edit" data-action="avatar-pick" aria-label="選擇形狀和顏色" title="選擇形狀和顏色">${avatar({color:c,shape},'hero')}</button><input name="name" required maxlength="80" placeholder="為 Bot 命名" value="${esc(b.name||'')}"><label class="pin-toggle" title="釘選在左側最上方"><input type="checkbox" name="pinned" ${b.pinned ? 'checked' : ''} aria-label="釘選"><span aria-hidden="true">📌</span></label></div><div class="avatar-panel" hidden><div class="shapes">${Array.from({length:13},(_,i)=>`<button type="button" class="shape-btn ${shape===i?'selected':''}" data-action="shape" data-id="${i}" aria-label="形狀 ${i+1}">${avatar({color:c,shape:i})}</button>`).join('')}</div><div class="swatches">${colors.map(x=>`<button type="button" class="swatch ${c===x?'selected':''}" style="background:${x}" data-action="color" data-id="${x}" aria-label="顏色 ${x}"></button>`).join('')}</div></div><input type="hidden" name="shape" value="${shape}"><input type="hidden" name="color" value="${c}"><label class="field persona-field">人格檔案<textarea name="persona" ${editing ? '' : 'required'} maxlength="20000" rows="5" placeholder="個性、語氣、擅長的事。例如：冷靜直接的資深工程師，先給結論，不確定就說不確定。">${esc(b.persona||'')}</textarea></label><label class="field">工作指示（選填）<textarea name="instructions" placeholder="負責的工作和做法。例如：審查程式碼，只列出會出錯的問題。">${esc(b.instructions||'')}</textarea></label><div class="form-grid"><label class="field">提供者<select name="provider">${providerOptions(editing ? b.provider || '' : 'auto', true, true)}</select><small class="muted field-hint" data-auto-hint hidden>依任務和額度自動選。</small></label><label class="field" data-account-field>${accountField(b.provider || '', b.account || '')}</label>${modelPicker(b.model||'')}</div><div class="setting-list in-form">${settingRow('分類', '', dropdown('section', b.section || sectionNames()[0] || '我的 Bots', [...new Set([...sectionNames(), b.section || '我的 Bots'])].map(x => ({id: x, name: x}))))}</div><details class="advanced"><summary>進階設定</summary><p class="muted small">預設跟著「設定」。只有這個 Bot 要不一樣時才改。</p><div class="setting-list in-form">${settingRow('主動性', '動作前要不要先問', dropdown('permissionMode', b.permissionMode || '', permissionOptions(true)))}${settingRow('存取範圍', '可以動到哪些檔案', dropdown('access', ownAccess, [{id: '', name: '使用預設（' + accessName(st.access) + '）'}, ...ACCESS]))}<div class="setting-row" data-access-folder ${ownAccess === 'folder' ? '' : 'hidden'}><div class="setting-copy"><strong>指定的資料夾</strong><span data-access-path>${esc(b.accessFolder || '尚未選擇')}</span></div><div class="setting-control"><input type="hidden" name="accessFolder" value="${esc(b.accessFolder || '')}"><button type="button" class="secondary" data-action="choose-folder">選擇資料夾…</button></div></div><div data-fixed-model>${settingRow('備用模型', '模型不能用時改用', dropdown('fallbackChoice', !Array.isArray(b.fallbacks) ? '__default' : b.fallbacks.length ? b.fallbacks[0] : '__none', [{id: '__default', name: '使用預設', hint: (st.fallbacks || []).length ? (st.fallbacks || []).map(providerShort).join(' → ') : '不自動換'}, {id: '__none', name: '不自動換'}, ...providerList()]))}</div>${settingRow('思考強度', '', dropdown('effort', b.effort || '', [{id: '', name: '使用預設（' + effortName(st.effort) + '）'}, ...EFFORTS]))}<div data-feature-row="multi">${settingRow('多代理協作', '派子代理分工，用量較多', dropdown('featureMulti', featureChoice('multi'), featureOptions('multi')))}</div><div data-feature-row="image">${settingRow('圖片生成', '用 AI 生成圖片', dropdown('featureImage', featureChoice('image'), featureOptions('image')))}</div>${settingRow('允許本機腳本', '讓這台 Mac 上的腳本或終端機指令交辦工作給它。不能代你核准動作', toggle('name="scripts"', !!b.scripts, '允許本機腳本'))}</div></details></div><div class="modal-foot">${editing?'<button type="button" class="link" data-action="delete-bot" style="margin-right:auto;color:#b55">刪除 Bot</button>':''}<button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${editing?'儲存':'建立 Bot'}</button></div></form>`);
    const form = $('#bot-form');
    form.dataset.id = b.id || '';
    if (!b.id) restoreBotDraft(form);
    loadModels(form);
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
