
  // 從這裡開始, 說明 and the 常用 entries in the sidebar (#308, #66①, #272): where to begin, said plainly, each step one click away.
  const START_STEPS = [
    {title: '加帳號', note: '先登入一家 AI（例如 ChatGPT 或 Claude 帳號）。登入由官方工具完成，Zook 看不到密碼。', go: 'data-action="page" data-id="usage"', label: '前往加帳號'},
    {title: '建第一個 Bot', note: '取個名字、說它要幫你做什麼。也可以直接用左邊現成的 Bot。', go: 'data-action="new-bot"', label: '新增 Bot'},
    {title: '問一句話、看檔案', note: '在下方輸入想做的事。Bot 交出的檔案會列在回覆下面，也可以按上方「打開資料夾」。', go: 'data-start="ask"', label: '開始輸入'},
    {title: '建群組', note: '讓幾個 Bot 一起討論或分工，例如一個找資料、一個寫報告。', go: 'data-action="new-group"', label: '新增群組'},
    {title: '看用量', note: '每家 AI 還剩多少額度、每個 Bot 用了多少。', go: 'data-action="page" data-id="usage"', label: '看用量'}];
  // inChat: on an empty chat, where it can be put away (說明 always shows it).
  function startCard(inChat) {
    if (inChat && state.data.settings.startTips === false) return '';
    const steps = START_STEPS.map((s, i) => `<li><span class="guide-mark" aria-hidden="true">${i + 1}</span><div class="guide-copy"><strong>${s.title}</strong><span>${s.note}</span></div><button type="button" class="secondary small-btn" ${s.go}>${s.label}</button></li>`).join('');
    return `<section class="start-card" aria-label="從這裡開始"><div class="guide-head"><strong>從這裡開始</strong>${inChat ? '<span class="muted">隨時可以在左邊「說明」再看到</span><button type="button" class="link" data-start="hide">收起</button>' : ''}</div><ol class="guide-steps start-steps">${steps}</ol></section>`;
  }

  // 常用: the pages people look for most, always in sight at the top of the sidebar; the rest stay in 我的工作區.
  const SIDE_NAV = [['usage', '◷', '各模型使用量'], ['schedules', '◴', '排程'], ['knowledge', '▤', '知識庫'], ['skills', '✳', 'Skills 與連接器'], ['help', '?', '說明']];
  // Folded with 常用 on a wide window; on a phone there is no heading to unfold it, so the chips always show (style.css).
  function sideNav() {
    if (state.query) return '';
    const closed = state.collapsed.__nav;
    const head = `<div class="section-head"><button class="section-toggle" data-action="collapse" data-id="__nav" aria-expanded="${!closed}"><span>常用</span><span>${closed ? '⌄' : '⌃'}</span></button></div>`;
    return `<nav class="side-nav ${closed ? 'closed' : ''}" aria-label="常用功能">${head}${SIDE_NAV.map(([id, icon, name]) => `<button type="button" class="nav-row ${state.page === id ? 'active' : ''}" data-action="page" data-id="${id}"><span class="nav-ico" aria-hidden="true">${icon}</span>${name}</button>`).join('')}</nav>`;
  }

  // 說明: where to begin, where each thing is, and a few answers.
  const HELP_PAGES = [['usage', '各模型使用量', '加帳號、登入，看每家還剩多少額度'], ['schedules', '排程', '讓 Bot 每天或每週自動做一件事'], ['knowledge', '知識庫', '放資料給 Bot 查，回答時會引用'],
    ['memory', '記憶', 'Bot 自己記住的偏好，可以查看和刪除'], ['skills', 'Skills 與連接器', '給所有 Bot 的做事方法和外部服務'], ['activity', '活動紀錄', '設定變更、核准和對外動作的紀錄'], ['settings', '設定', '外觀、權限、預設 AI、備份等']];
  const HELP_FAQ = [['Bot 沒有回覆？', '到「各模型使用量」看那一家是不是還沒登入或額度用完。'],
    ['檔案在哪裡？', 'Bot 交出的檔案列在回覆下面；對話上方的「打開資料夾」可以在 Finder 打開。'],
    ['密碼安全嗎？', '登入由各家官方工具完成，Zook 看不到密碼；金鑰只存在這台 Mac 的鑰匙圈。']];
  function helpPage() {
    const pages = HELP_PAGES.map(([id, name, what]) => settingRow(name, what, `<button type="button" class="secondary small-btn" data-action="page" data-id="${id}">前往</button>`)).join('');
    const faq = HELP_FAQ.map(([q, a]) => `<div class="help-faq"><strong>${q}</strong><p class="muted">${a}</p></div>`).join('');
    const back = state.data.settings.startTips === false ? `<div class="setting-list">${settingRow('對話畫面顯示「從這裡開始」', '收起後只在這裡看得到', toggle('data-start-tips', false, '對話畫面顯示從這裡開始'))}</div>` : '';
    return `${startCard(false)}${back}<h2 class="settings-h">功能在哪裡</h2><div class="setting-list">${pages}</div><h2 class="settings-h">常見問題</h2>${faq}`;
  }

  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-start]');
    if (!el) return;
    if (el.dataset.start === 'ask') {
      if (!activeBot()) { botModal(); return; }
      if (state.page !== 'chat' || state.groupId) { state.page = 'chat'; state.groupId = null; render(); }
      $('#chat-input')?.focus();
      return;
    }
    if (el.dataset.start === 'hide') {
      try { state.data.settings = await post('settings', {startTips: false}, 'PATCH'); render(true); toast('已收起。之後在左邊「說明」還看得到'); } catch (err) { toast(err.message); }
    }
  });
  document.addEventListener('change', async e => {
    if (e.target.dataset?.startTips === undefined) return;
    try { state.data.settings = await post('settings', {startTips: e.target.checked}, 'PATCH'); render(true); toast(e.target.checked ? '對話畫面會顯示「從這裡開始」' : '已收起'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  });
