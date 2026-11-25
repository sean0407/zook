  // Backups, the activity record, usage budgets and the rules every Bot follows.
  const fmtTokens = n => fmtTok(n);  // the usage page's one unit (32-usage.js)
  const fmtSize = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

  function rulesSection() {
    const rules = state.data.settings.rules || '';
    return `<h2 class="settings-h">固定規則</h2><p class="muted small settings-note">所有 Bot 每次回覆都會遵守，優先於各自的工作指示。</p><form id="rules-form" class="rules-form"><textarea name="rules" maxlength="10000" rows="5" aria-label="固定規則" placeholder="例如：一律用繁體中文回答。金額一律標示幣別。">${esc(rules)}</textarea><div class="setting-actions"><button class="primary">儲存規則</button></div></form>`;
  }

  function backupSection() {
    const list = state.backups;
    const rows = !list ? loadingBlock('正在讀取備份…') : list.length ? `<div class="plain-rows">${list.map(b => `<div class="plain-row"><div class="plain-copy"><strong>${esc(formatDate(b.at))}</strong><span>${esc(b.kindName)} · ${fmtSize(b.size)}</span></div><div class="plain-actions"><button class="link" data-up="backup-restore" data-id="${esc(b.name)}">還原</button><button class="link danger" data-up="backup-delete" data-id="${esc(b.name)}">刪除</button></div></div>`).join('')}</div>` : '<div class="blank">還沒有備份。</div>';
    return `<h2 class="settings-h">備份與還原</h2><p class="muted small settings-note">每天自動備份一次，保留 14 天。內容包含 Bot、對話、知識、排程與設定；密碼和金鑰留在鑰匙圈，不會放進備份。</p><div class="setting-actions backup-actions"><button class="primary" data-up="backup-now">立即備份</button><button class="secondary" data-action="export">匯出成檔案</button><button class="secondary" data-up="backup-pick">從檔案加入</button><input type="file" id="backup-file" accept=".json,.gz,application/json,application/gzip" hidden></div>${rows}`;
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
    if (p === 'settings') { fill('backups', 'backups', x => x.items); fill('sync', 'sync'); }
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
        const done = await post('backups/' + encodeURIComponent(id) + '/restore');
        await refresh(); await loadUpkeep('settings'); toast(done.syncStopped ? '已還原。同步已停止，確認資料後再重新開啟' : '已還原');
      }
    } catch (err) { toast(err.message); }
  });

  document.addEventListener('change', async e => {
    const t = e.target;
    try {
      if (t.id === 'backup-file' && t.files[0]) {
        const file = t.files[0]; t.value = '';
        let data;
        try { data = JSON.parse(await backupText(file)); } catch (_) { throw new Error('這不是 Zook 的備份檔。'); }
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

  // First-run guide: three steps, shown until they are done or skipped. The steps read the same sign-in state as 各模型使用量.
  function guideSteps() {
    const list = state.accounts?.providers || [];
    const installed = list.filter(p => p.installed), signedIn = list.filter(p => p.status === 'logged_in' && !p.issue);
    const replied = state.data.bots.some(b => (b.messages || []).some(m => m.role === 'assistant' && m.status === 'completed'));
    const names = a => a.map(p => p.name.split('（')[0]).join('、');
    return [{title: '安裝一個 AI 工具', done: installed.length > 0, note: installed.length ? '已安裝 ' + names(installed) : '有 ChatGPT 帳號選 Codex，有 Claude 帳號選 Claude。裝一個就能開始。', go: 'usage', label: '前往安裝'},
            {title: '登入帳號', done: signedIn.length > 0, note: signedIn.length ? '已登入 ' + names(signedIn) : '登入由官方工具完成，Zook 不會看到密碼。', go: 'usage', label: '前往登入'},
            {title: '傳第一則訊息', done: replied, note: replied ? '完成' : '選一個 Bot，在下方輸入想問的事。', go: 'chat', label: '開始對話'}];
  }
  function guideCard() {
    if (!state.data || state.data.settings.onboarded !== false || state.groupId) return '';
    if (!state.accounts) return '';
    const steps = guideSteps(), at = steps.findIndex(s => !s.done);
    if (at < 0) { finishGuide(); return ''; }
    return `<section class="guide-card" aria-label="開始使用"><div class="guide-head"><strong>開始使用 Zook</strong><span class="muted">${at} / ${steps.length} 完成</span><button class="link" data-up="guide-skip">略過</button></div><ol class="guide-steps">${steps.map((s, i) => `<li class="${s.done ? 'done' : i === at ? 'now' : ''}"><span class="guide-mark" aria-hidden="true">${s.done ? '✓' : i + 1}</span><div class="guide-copy"><strong>${s.title}</strong><span>${esc(s.note)}</span></div>${i === at && !(s.go === 'chat' ? state.page === 'chat' : state.page === s.go) ? `<button class="primary small-btn" data-up="guide-go" data-id="${s.go}">${s.label}</button>` : ''}</li>`).join('')}</ol></section>`;
  }
  async function finishGuide(skipped) {
    if (state.guideClosing) return;
    state.guideClosing = true;
    try { state.data.settings = await post('settings', {onboarded: true}, 'PATCH'); if (!skipped) toast('設定完成，可以開始使用了'); } catch (_) {}
    state.guideClosing = false; render(true);
  }
  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-up^="guide-"]');
    if (!el) return;
    if (el.dataset.up === 'guide-skip') return finishGuide(true);
    if (el.dataset.id === 'chat') { state.page = 'chat'; state.groupId = null; render(); $('#chat-input')?.focus(); }
    else await loadPage(el.dataset.id);
  });
  // While the guide is showing, keep the sign-in state fresh so each step ticks itself off.
  setInterval(async () => {
    if (!state.data || state.data.settings.onboarded !== false || document.hidden) return;
    try { const next = await api('accounts'); if (JSON.stringify(next) !== JSON.stringify(state.accounts)) { state.accounts = next; if (state.page !== 'usage' || !$('#account-code-form input:focus')) render(true); } } catch (_) {}
  }, 4000);

  // Voice input: the Mac app listens and sends the words back; they are added to what is already typed.
  const VOICE_LANGS = [{id: '', name: '跟隨系統語言'}, {id: 'zh-TW', name: '中文（台灣）'}, {id: 'en-US', name: 'English'}, {id: 'ja-JP', name: '日本語'}];
  const VOICE_ERRORS = {mic: '沒有麥克風權限。請到「系統設定 → 隱私權與安全性 → 麥克風」打開 Zook。', speech: '沒有語音辨識權限。請到「系統設定 → 隱私權與安全性 → 語音辨識」打開 Zook。', unavailable: '這台 Mac 目前無法辨識這個語言。'};
  const voiceSection = () => `<h2 class="settings-h">語音輸入</h2><div class="setting-list">${settingRow('辨識語言', '按訊息框旁的麥克風開始，再按一次結束', dropdown('voiceLang', state.data.settings.voiceLang || '', VOICE_LANGS, 'data-voice-lang'))}</div>`;
  function toggleVoice() {
    const bridge = window.webkit?.messageHandlers?.zookVoice;
    if (!bridge) { toast('語音輸入要在 Zook App 裡使用'); return; }
    if (state.voice) { bridge.postMessage({stop: true}); return; }
    state.voice = {base: $('#chat-input')?.value || '', key: effortKey()};
    bridge.postMessage({start: true, lang: state.data.settings.voiceLang || ''});
  }
  window.zookVoice = info => {
    if (!info || !state.voice) return;
    if (info.state === 'listening') { document.body.dataset.voice = 'on'; toast(info.onDevice ? '正在聽，再按一次麥克風結束' : '正在聽（由 Apple 的語音服務辨識），再按一次結束'); }
    if (info.state === 'partial' && typeof info.text === 'string' && state.voice.key === effortKey()) {
      const input = $('#chat-input'), base = state.voice.base;
      if (input) { input.value = (base + (base && !/\s$/.test(base) ? ' ' : '') + info.text).slice(0, 30000); updateInputMirror(); }
    }
    if (info.state === 'ended' || info.state === 'error') {
      delete document.body.dataset.voice; state.voice = null;
      if (info.state === 'error') toast(VOICE_ERRORS[info.reason] || '語音輸入無法啟動。'); else $('#chat-input')?.focus();
    }
  };
  document.addEventListener('change', async e => {
    if (e.target.dataset.voiceLang === undefined) return;
    try { state.data.settings = await post('settings', {voiceLang: e.target.value}, 'PATCH'); toast('已更新'); } catch (err) { toast(err.message); }
  });

  // Several Macs kept alike through a folder they all see.
  const SYNC_JOIN = [{id: 'replace', name: '換成同步資料夾的內容', hint: '這台現有的 Bot、對話、知識和記憶會先備份再移除'}, {id: 'merge', name: '兩邊合併', hint: '這台現有的資料也會出現在其他 Mac'}];
  function syncSection() {
    const s = state.sync;
    const note = '<p class="muted small settings-note">選一個每台 Mac 都看得到的資料夾（例如 iCloud 雲碟）。會同步 Bot、對話、知識、記憶和固定規則；密碼、登入、連接器、權限、排程、群組和檔案留在各自的 Mac。</p>';
    if (!s) return `<h2 class="settings-h">多台 Mac 同步</h2>${note}${loadingBlock('正在讀取…')}`;
    if (!s.on) return `<h2 class="settings-h">多台 Mac 同步</h2>${note}<div class="setting-list">${settingRow('同步資料夾', '尚未設定', '<button class="secondary" data-up="sync-pick">選擇資料夾</button>')}</div>`;
    const others = (s.others || []).map(o => o.name).join('、');
    const status = s.lastError ? `<span class="error-text">${esc(s.lastError)}</span>` : `${s.lastAt ? '上次同步 ' + esc(formatDate(s.lastAt)) : '尚未同步'}${others ? ' · 其他 Mac：' + esc(others) : ' · 還沒有其他 Mac 加入'}`;
    return `<h2 class="settings-h">多台 Mac 同步</h2>${note}<div class="setting-list">${settingRow('同步資料夾', esc(s.folder), '<button class="secondary" data-up="sync-stop">停止同步</button>')}${settingRow('這台 Mac：' + esc(s.deviceName), status, '<button class="secondary" data-up="sync-now">立即同步</button>')}</div>`;
  }
  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-up^="sync-"]');
    if (!el) return;
    try {
      if (el.dataset.up === 'sync-pick') {
        const picked = (await post('choose-folder')).path;
        if (!picked) return;
        const found = await post('sync/check', {folder: picked});
        if (!found.others.length) { state.sync = await post('sync', {folder: found.folder, join: 'merge'}); render(true); toast('已開始同步'); return; }
        modal('加入同步', `<form id="sync-form" data-folder="${esc(found.folder)}"><div class="modal-body"><p class="muted">這個資料夾已有其他 Mac 的資料：${esc(found.others.map(o => o.name).join('、'))}。</p><div class="field">這台 Mac 現有的資料${dropdown('join', 'replace', SYNC_JOIN)}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">開始同步</button></div></form>`);
      }
      if (el.dataset.up === 'sync-now') { el.disabled = true; state.sync = await post('sync/now'); await refresh(); toast(state.sync.lastError || '已同步'); }
      if (el.dataset.up === 'sync-stop' && confirm('停止後，這台 Mac 的資料會留著，只是不再和其他 Mac 同步。')) { state.sync = await post('sync', {}, 'DELETE'); render(true); toast('已停止同步'); }
    } catch (err) { toast(err.message); render(true); }
  });
  document.addEventListener('submit', async e => {
    if (e.target.id !== 'sync-form') return;
    e.preventDefault();
    try { state.sync = await post('sync', {folder: e.target.dataset.folder, join: new FormData(e.target).get('join')}); closeModal(); await refresh(); toast('已開始同步'); }
    catch (err) { toast(err.message); }
  });

  // A backup is one compressed file; older ones are plain text.
  async function backupText(file) {
    const head = new Uint8Array(await file.slice(0, 2).arrayBuffer());
    if (head[0] !== 0x1f || head[1] !== 0x8b) return file.text();
    return new Response(file.stream().pipeThrough(new DecompressionStream('gzip'))).text();
  }

  // The data file could not be read at startup: say once what Zook did about it.
  function recoveryNotice() {
    const r = state.data?.settings?.recovered;
    if (!r || state.recoveryShown || document.querySelector('.modal')) return;
    state.recoveryShown = true;
    const chats = (r.chats || []).map(c => `<li>${esc(c.name)}：${c.backup ? `已改用 ${esc(formatDate(c.backupAt))} 的備份` : '沒有備份可用，目前是空的'}</li>`).join('');
    const lost = chats ? `<p>下面的對話檔案無法讀取，其他對話不受影響：</p><ul class="steps">${chats}</ul><p class="muted">損壞的檔案沒有刪除，留在 Zook 資料夾的 chats 裡，檔名結尾是 .damaged。</p>` : '';
    const done = '<div class="modal-foot"><button class="primary" data-up="recovery-ok">知道了</button></div>';
    if (r.chatsOnly) return modal('有對話無法讀取', `<div class="modal-body">${lost}</div>`, done);
    const kept = r.chatsKept ? '對話內容各自存在自己的檔案裡，沒有受影響；' : '';
    const what = r.backup ? `${kept}Bot 清單、設定、排程等已改用 ${esc(formatDate(r.backupAt))} 的備份，那之後對它們的變動沒有保留。` : r.chatsKept ? '找不到可用的備份，所以 Bot 清單與設定從全新的狀態開始。原本的對話檔案沒有刪除，留在 Zook 的資料夾裡。' : '找不到可用的備份，所以從全新的狀態開始。';
    modal('資料檔無法讀取', `<div class="modal-body"><p>Zook 的資料檔損壞了。${what}</p>${r.adopted ? `<p class="muted">有 ${r.adopted} 個備份之後才開始的對話，已經放回原本的 Bot。</p>` : ''}${lost}${r.kept ? `<p class="muted">損壞的檔案沒有刪除，改名為 <code>${esc(r.kept)}</code>，留在 Zook 的資料夾裡。</p>` : ''}${r.backup ? '<p class="muted">多台 Mac 同步如果原本開著，已經先停止，確認資料後再到設定重新開啟。</p>' : ''}</div>`, done);
  }
  document.addEventListener('click', async e => {
    if (!e.target.closest?.('[data-up="recovery-ok"]')) return;
    try { state.data.settings = await post('settings', {recoveredSeen: true}, 'PATCH'); } catch (_) {}
    closeModal();
  });

  // Bringing a deleted Bot back from the usage page.
  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-up="restore-bot"]');
    if (!el) return;
    el.disabled = true;
    try {
      const bot = await post('bots/' + encodeURIComponent(el.dataset.id) + '/restore');
      await refresh(); state.botUsage = await api('usage/bots'); render(true);
      toast('已喚回「' + bot.name + '」，對話都還在');
    } catch (err) { el.disabled = false; toast(err.message); }
  });

  // Conversation settings.
  const chatSection = () => `<h2 class="settings-h">對話</h2><div class="setting-list">${settingRow('回覆逐字顯示', '回覆時文字逐步出現；關閉後等整段完成才顯示', toggle('data-stream-replies', state.data.settings.streamReplies !== false, '回覆逐字顯示'))}${settingRow('Bot 忙碌時排隊', 'Bot 還在回覆時送出的訊息會排在後面；關閉後要等它回覆完才能再傳', toggle('data-queue-busy', state.data.settings.queueWhenBusy !== false, 'Bot 忙碌時排隊'))}${settingRow('對話過長時自動整理', '對話長到模型讀不完時，把前面整理成摘要再接續；訊息本身都還在', toggle('data-auto-compact', state.data.settings.autoCompact !== false, '對話過長時自動整理'))}${settingRow('保持 CLI 開啟', '同一個對話接著問時不用重新啟動，回覆比較快；閒置十分鐘後自動關閉', toggle('data-keep-cli', state.data.settings.keepCli !== false, '保持 CLI 開啟'))}${settingRow('結束時繼續在背景跑', '結束 Zook 或更新時，正在回覆的對話繼續跑完，重開後接回來；關閉後結束 Zook 會停止回覆', toggle('data-background-runs', state.data.settings.backgroundRuns !== false, '結束時繼續在背景跑'))}${settingRow('選項按鈕', 'Bot 需要你選擇時，把選項顯示成按鈕；做到一半也可以問你問題', toggle('data-choice-buttons', state.data.settings.choiceButtons !== false, '選項按鈕'))}</div>`;
  document.addEventListener('change', async e => {
    if (e.target.dataset.streamReplies === undefined) return;
    try { state.data.settings = await post('settings', {streamReplies: e.target.checked}, 'PATCH'); toast(e.target.checked ? '回覆會逐字顯示' : '回覆會整段顯示'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  });

  document.addEventListener('change', async e => {
    if (e.target.dataset.queueBusy === undefined) return;
    try { state.data.settings = await post('settings', {queueWhenBusy: e.target.checked}, 'PATCH'); toast(e.target.checked ? '忙碌時送出的訊息會排隊' : '已關閉排隊'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  });

  document.addEventListener('change', async e => {
    if (e.target.dataset.autoCompact === undefined) return;
    try { state.data.settings = await post('settings', {autoCompact: e.target.checked}, 'PATCH'); toast(e.target.checked ? '對話過長時會自動整理' : '已關閉自動整理'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  });
