
  // How the window looks (light or dark, text size), and the commands typed into the message box.
  const LOOKS = [{id: 'system', name: '跟隨系統'}, {id: 'light', name: '淺色'}, {id: 'dark', name: '深色'}];
  const TEXT_SIZES = [{id: 'small', name: '小', zoom: 0.9}, {id: 'normal', name: '標準', zoom: 1}, {id: 'large', name: '大', zoom: 1.12}, {id: 'xlarge', name: '特大', zoom: 1.25}];
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
  const slash = {items: [], index: 0};
  const slashCommands = () => [
    {cmd: '/goal', key: 'long', name: '長任務', desc: '這則訊息最長可以跑 4 小時，結束時通知你'},
    {cmd: '/plan', key: 'plan', name: '先規劃', desc: effortSupported() ? '這則訊息只請 Bot 提出計畫，不動手' : '這個 Bot 的模型不支援先規劃', off: !effortSupported()}];
  function hideSlash() { const menu = $('#slash-menu'); if (menu) menu.hidden = true; slash.items = []; }
  function showSlash() {
    const input = $('#chat-input'), menu = $('#slash-menu');
    if (!input || !menu || activeGroup()) return hideSlash();
    const typed = input.value;
    if (!/^\/[a-z]*$/i.test(typed)) return hideSlash();
    slash.items = slashCommands().filter(c => c.cmd.startsWith(typed.toLowerCase()));
    if (!slash.items.length) return hideSlash();
    slash.index = Math.min(slash.index, slash.items.length - 1);
    menu.innerHTML = slash.items.map((c, i) => `<button type="button" class="mention-option slash-option ${i === slash.index ? 'active' : ''} ${c.off ? 'off' : ''}" role="option" aria-selected="${i === slash.index}" data-slash="${i}"><span class="slash-cmd">${esc(c.cmd)}</span><span><strong>${esc(c.name)}</strong><small>${esc(c.desc)}</small></span></button>`).join('');
    menu.hidden = false;
  }
  function pickSlash(i) {
    const c = slash.items[i], input = $('#chat-input');
    if (!c || !input) return;
    if (c.off) { toast(c.desc); return; }
    state[c.key][state.selected] = true; input.value = ''; hideSlash(); render(true);
    $('#chat-input')?.focus();
    if (c.key === 'plan') toast('這則訊息 Bot 只會提出計畫，不會動手');
  }
  document.addEventListener('input', e => { if (e.target.id === 'chat-input') { slash.index = 0; showSlash(); } });
  document.addEventListener('click', e => {
    const option = e.target.closest('[data-slash]');
    if (option) { e.preventDefault(); pickSlash(Number(option.dataset.slash)); }
    else if (!e.target.closest('#chat-input')) hideSlash();
  });
  // Before the message box's own keys: while the list is open the arrows move in it and Enter chooses.
  document.addEventListener('keydown', e => {
    if (e.target.id !== 'chat-input' || !slash.items.length || $('#slash-menu')?.hidden || e.isComposing || e.keyCode === 229) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); slash.index = (slash.index + (e.key === 'ArrowDown' ? 1 : -1) + slash.items.length) % slash.items.length; showSlash(); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); pickSlash(slash.index); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); hideSlash(); }
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
  window.sendingAdd = (where, path, body, group) => { const s = {id: newId(), where, path, body: {...body, clientId: newId()}, group, at: Date.now()}; state.sending.push(s); return s; };
  const forget = s => { state.sending = state.sending.filter(x => x !== s); };
  // Drawn until the conversation itself has it, so it never blinks out between the answer and the refresh, and never shows twice.
  const arrived = (s, messages, waiting) => [...messages.filter(m => m.role === 'user'), ...waiting].some(m => m.content === s.body.content && Date.parse(m.createdAt) >= s.at - 2000);
  window.sendingView = (where, messages, waiting = []) => state.sending.filter(s => s.where === where && !(!s.error && arrived(s, messages, waiting))).map(s => `<div class="message user sending" data-sending="${esc(s.id)}"><div class="bubble">${esc(s.body.content || '（請看附件）')}</div>${s.error ? `<div class="interject-note error-text">沒有送出：${esc(s.error)}<button class="link" data-sending-retry="${esc(s.id)}">重新傳送</button><button class="link" data-sending-drop="${esc(s.id)}">移除</button></div>` : `<div class="interject-note">${s.done ? '已送出' : '傳送中…'}</div>`}</div>`).join('');
  window.sendingSend = async s => {
    s.error = ''; s.done = false;
    let result;
    try { result = await post(s.path, s.body); }
    catch (err) { s.error = err.message || '沒有送出'; render(true); return null; }
    s.done = true;
    try { await refresh(); forget(s); } catch (_) { render(true); }  // kept (as 已送出) until a later refresh shows it
    if (s.group) pollGroup(s.group);
    else if (result.jobId) poll(result.jobId, s.body.botId);  // a message that is waiting in line has no reply yet; it is picked up when its turn comes
    return result;
  };
  window.sentNote = m => m.queued ? (m.waiting ? '排在後面・這輪結束後回覆' : '排在後面') : m.interjected ? '已插話' : '';
  document.addEventListener('click', e => {
    const el = e.target.closest?.('[data-sending-retry], [data-sending-drop]');
    const s = el && state.sending.find(x => x.id === (el.dataset.sendingRetry || el.dataset.sendingDrop));
    if (!s) return;
    if (el.dataset.sendingRetry) { sendingSend(s); render(true); return; }
    forget(s); render(true);
  });
})();
