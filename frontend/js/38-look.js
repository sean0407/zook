
  // How the window looks (light or dark, text size), and the commands typed into the message box.
  const LOOKS = [{id: 'system', name: '跟隨系統'}, {id: 'light', name: '淺色'}, {id: 'dark', name: '深色'}];
  const TEXT_SIZES = [{id: 'small', name: '小', zoom: 0.9}, {id: 'normal', name: '標準', zoom: 1}, {id: 'large', name: '大', zoom: 1.12}, {id: 'xlarge', name: '特大', zoom: 1.35}];
  const systemDark = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  let lookApplied = '';
  function applyLook() {
    const s = state.data?.settings || {}, dark = s.appearance === 'dark' || ((s.appearance || 'system') === 'system' && !!systemDark?.matches);
    const zoom = (TEXT_SIZES.find(x => x.id === s.textSize) || TEXT_SIZES[1]).zoom, mark = dark + ':' + zoom;
    if (mark === lookApplied) return;
    lookApplied = mark;
    document.documentElement.classList.toggle('dark', dark);
    const shell = window.webkit?.messageHandlers?.zookWindow;
    if (shell) shell.postMessage({zoom, dark});  // the app window enlarges the whole page, like the 放大 menu item
    else { const root = document.documentElement; root.style.zoom = zoom === 1 ? '' : String(zoom); root.style.setProperty('--zoom', String(zoom)); root.classList.toggle('zoomed', zoom !== 1); }
  }
  systemDark?.addEventListener?.('change', () => { lookApplied = ''; applyLook(); });
  const lookSection = () => `<h2 class="settings-h">外觀</h2><div class="setting-list">${settingRow('深淺色', '跟隨系統時，Mac 切換深色模式 Zook 也會跟著切換', dropdown('appearance', state.data.settings.appearance || 'system', LOOKS, 'data-look="appearance"'))}${settingRow('字體大小', '所有畫面的文字與按鈕一起放大或縮小，選了馬上套用。「大」「特大」會讓左側欄變窄，看不習慣隨時改回「標準」', dropdown('textSize', state.data.settings.textSize || 'normal', TEXT_SIZES, 'data-look="textSize"'))}</div>`;
  document.addEventListener('change', async e => {
    const key = e.target.dataset?.look;
    if (!key) return;
    try { state.data.settings = await post('settings', {[key]: e.target.value}, 'PATCH'); applyLook(); render(true); }
    catch (err) { toast(err.message); render(true); }
  });

  // Commands: typing "/" at the start of a message to a Bot lists them. Choosing one switches that mode on for the next message.
  const slash = {items: [], index: 0, dismissed: false};  // dismissed: closed with Esc or a click away, until the text changes
  const slashCommands = () => [
    {cmd: '/goal', key: 'long', name: '長任務', desc: '這則訊息最長可以跑 4 小時，結束時通知你'},
    {cmd: '/plan', key: 'plan', name: '先規劃', desc: planSupported() ? '這則訊息只請 Bot 提出計畫，不動手' : '這個 Bot 的模型不支援先規劃', off: !planSupported()}];
  function hideSlash(dismiss) { const menu = $('#slash-menu'); if (menu) menu.hidden = true; slash.items = []; if (dismiss) slash.dismissed = true; }
  // A redraw (a new Bot's greeting arriving, a reply streaming in) rebuilds the box: the list comes back if it was open (#197).
  function refreshSlash() { if (!slash.dismissed && document.activeElement?.id === 'chat-input') showSlash(); }
  const SLASH_KEYS = '<div class="slash-keys" aria-hidden="true">↑↓ 選擇 · Enter 確定 · Esc 關閉</div>';
  function showSlash() {
    const input = $('#chat-input'), menu = $('#slash-menu');
    if (!input || !menu || activeGroup()) return hideSlash();
    const typed = input.value;
    if (!/^\/[a-z]*$/i.test(typed)) return hideSlash();
    slash.items = slashCommands().filter(c => c.cmd.startsWith(typed.toLowerCase()));
    if (!slash.items.length) {  // a command that does not exist is said so, with the ones there are
      menu.innerHTML = `<div class="slash-empty" role="status">沒有「${esc(typed)}」這個指令。可以用的有 ${slashCommands().map(c => c.cmd).join('、')}；不是指令的話照常送出就好。</div>`;
      menu.hidden = false; return;
    }
    slash.index = Math.min(slash.index, slash.items.length - 1);
    menu.innerHTML = slash.items.map((c, i) => `<button type="button" class="mention-option slash-option ${i === slash.index ? 'active' : ''} ${c.off ? 'off' : ''}" role="option" aria-selected="${i === slash.index}" data-slash="${i}"><span class="slash-cmd">${esc(c.cmd)}</span><span><strong>${esc(c.name)}</strong><small>${esc(c.desc)}</small></span></button>`).join('') + SLASH_KEYS;
    menu.hidden = false;
  }
  function pickSlash(i) {
    const c = slash.items[i], input = $('#chat-input');
    if (!c || !input) return;
    if (c.off) { toast(c.desc); return; }
    state[c.key][state.selected] = true; input.value = ''; hideSlash(); render(true);
    $('#chat-input')?.focus();
  }
  document.addEventListener('input', e => { if (e.target.id === 'chat-input') { slash.index = 0; slash.dismissed = false; showSlash(); } });
  document.addEventListener('click', e => {
    const option = e.target.closest('[data-slash]');
    if (option) { e.preventDefault(); pickSlash(Number(option.dataset.slash)); }
    else if (!e.target.closest('#chat-input')) hideSlash(true);
  });
  // Before the message box's own keys: while the list is open the arrows move in it and Enter chooses.
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && e.target.id === 'chat-input' && !slash.items.length && $('#slash-menu') && !$('#slash-menu').hidden) { e.preventDefault(); e.stopPropagation(); hideSlash(true); return; }  // the 沒有這個指令 note
    if (e.target.id !== 'chat-input' || !slash.items.length || $('#slash-menu')?.hidden || e.isComposing || e.keyCode === 229) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); slash.index = (slash.index + (e.key === 'ArrowDown' ? 1 : -1) + slash.items.length) % slash.items.length; showSlash(); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); pickSlash(slash.index); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); hideSlash(true); }
  }, true);
  // A command typed in full in front of the message ("/plan 幫我…") works too.
  document.addEventListener('submit', e => {
    if (e.target.id !== 'chat-form' || activeGroup()) return;
    const input = $('#chat-input'), match = /^\/(goal|plan)(?:\s+|$)/i.exec(input?.value || '');
    if (!match) return;
    const c = slashCommands().find(x => x.cmd === '/' + match[1].toLowerCase());
    if (c.off) { toast(c.desc); e.preventDefault(); e.stopImmediatePropagation(); return; }
    state[c.key][state.selected] = true; input.value = input.value.slice(match[0].length);
    if (!input.value.trim()) { e.preventDefault(); e.stopImmediatePropagation(); hideSlash(); render(true); $('#chat-input')?.focus(); }
  }, true);

// Sending: the message shows at once and is marked when the Mac has it; a failure is shown on the message itself, and 重新傳送
// sends that same message again (same conversation, same files, same id, so the Mac never answers it twice). While a Bot is
// answering, Zook decides by rule whether a message joins the running reply (已插話) or waits its turn (排在後面).
(() => {
  state.sending = state.sending || [];
  const newId = () => crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(36).slice(2, 12);
  // where: 'bot/chat' or the group's id. path and body are the request, sent again unchanged by 重新傳送.
  // A message sent while the one before it to the same Bot is still on its way says so ('after'): two requests can reach the Mac
  // in either order, and the Mac then takes them in the order they were sent (#142). One the Mac has only said it took in (#289) still
  // counts as on its way until the conversation shows it.
  window.sendingAdd = (where, path, body, group) => {
    state.sending = state.sending.filter(x => !(x.accepted && Date.now() - x.at > 120000));  // long since shown, or said in the conversation as not sent
    const before = path === 'chat' ? state.sending.filter(x => x.path === 'chat' && x.body.botId === body.botId && (!x.done || x.accepted) && !x.error).pop() : null;
    const s = {id: newId(), where, path, body: {...body, clientId: newId(), ...(before ? {after: before.body.clientId} : {})}, group, at: Date.now()};
    state.sending.push(s); return s;
  };
  const forget = s => { state.sending = state.sending.filter(x => x !== s); };
  // Drawn until the conversation itself has it, so it never blinks out between the answer and the refresh, and never shows twice.
  const arrived = (s, messages, waiting) => [...messages.filter(m => m.role === 'user'), ...waiting].some(m => m.content === (s.body.content && s.body.content.trim() ? s.body.content : '（請看附件）') && Date.parse(m.createdAt) >= s.at - 2000);
  window.sendingView = (where, messages, waiting = []) => (state.sending = state.sending.filter(s => !(s.accepted && s.where === where && arrived(s, messages, waiting)))).filter(s => s.where === where && !(!s.error && arrived(s, messages, waiting))).map(s => `<div class="message user sending" data-sending="${esc(s.id)}"><div class="bubble">${esc(s.body.content || '（請看附件）')}</div>${s.error ? `<div class="interject-note error-text">沒有送出：${esc(s.error)}<button class="link" data-sending-retry="${esc(s.id)}">重新傳送</button><button class="link" data-sending-drop="${esc(s.id)}">移除</button></div>` : `<div class="interject-note">${s.done ? '已送出' : s.slow ? '已送出，Bot 準備中…' : '傳送中…'}</div>`}</div>`).join('');
  // #169: the Mac answers once the reply is set up, which can take a while; past a moment the message is on its way, not stuck.
  const SLOW_AFTER = 1500;
  window.sendingSend = async s => {
    s.error = ''; s.done = false; s.slow = false;
    const timer = setTimeout(() => { if (!s.done && !s.error) { s.slow = true; render(true); } }, SLOW_AFTER);
    let result;
    try { result = await post(s.path, s.body); }
    catch (err) { s.error = err.message || '沒有送出'; render(true); return null; }
    finally { clearTimeout(timer); }
    s.done = true; s.accepted = !!result.accepted;  // taken in, still being got ready on the Mac: kept (as 已送出) until the conversation shows it
    try { await refresh(); if (!s.accepted) forget(s); } catch (_) { render(true); }  // kept (as 已送出) until a later refresh shows it
    if (s.group) pollGroup(s.group);
    else if (result.jobId) poll(result.jobId, s.body.botId);  // a message that is waiting in line has no reply yet; it is picked up when its turn comes
    return result;
  };
  // A group's 插話 (#94) says who takes it: who it went to, then who read it.
  window.sentNote = m => m.queued ? (m.waiting ? '排在後面・這輪結束後回覆' : '排在後面') : !m.interjected ? '' : m.heardBy ? `已插話・${esc(m.heardBy)} 已讀到` : m.interjectTo ? `已插話・交給 ${esc(m.interjectTo)} 處理` : '已插話';
  document.addEventListener('click', e => {
    const el = e.target.closest?.('[data-sending-retry], [data-sending-drop]');
    const s = el && state.sending.find(x => x.id === (el.dataset.sendingRetry || el.dataset.sendingDrop));
    if (!s) return;
    if (el.dataset.sendingRetry) { sendingSend(s); render(true); return; }
    forget(s); render(true);
  });
})();
