  // What was open last, per window (#214). Each tab keeps its own Bot, group and conversation of each Bot in sessionStorage,
  // which a reload of that tab reads first; localStorage only gives a new tab somewhere to start. The Mac still keeps each Bot's
  // open conversation (bot.chatId): the phone and a new window use that; a tab that has its own opens it again after a reload.
  const LAST_OPEN_KEY = 'zook-last-chat';
  let lastOpenSaved = {own: '', shared: ''};
  function readLastOpen(which) {
    let raw = null;
    try { raw = (which === 'own' ? sessionStorage : localStorage).getItem(LAST_OPEN_KEY); } catch (_) { return null; }
    try { const v = JSON.parse(raw || 'null'); return v && typeof v === 'object' && !Array.isArray(v) ? v : null; } catch (_) { return null; }
  }
  // After a reload: this tab's own place, else the last one any window had.
  function restoreLastOpen() {
    const own = readLastOpen('own'), last = own || readLastOpen('shared') || {};
    const bots = state.data.bots || [], groups = state.data.groups || [];
    if (typeof last.group === 'string' && groups.some(g => g.id === last.group)) state.groupId = last.group;
    if (typeof last.bot === 'string' && bots.some(b => b.id === last.bot)) state.selected = last.bot;
    state.ownChats = {};
    const chats = own && own.chats && typeof own.chats === 'object' ? own.chats : {};
    for (const b of bots) if (typeof chats[b.id] === 'string' && (b.chats || []).some(c => c.id === chats[b.id])) state.ownChats[b.id] = chats[b.id];
    const b = bots.find(x => x.id === state.selected), mine = b && state.ownChats[b.id];
    if (!state.groupId && mine && mine !== b.chatId)  // another window opened a different conversation of this Bot meanwhile
      post(`bots/${encodeURIComponent(b.id)}/chats/${encodeURIComponent(mine)}/open`, {}).then(() => refresh()).catch(() => {});
  }
  // On every chat page draw: the first conversation this tab shows of a Bot is its own until it picks another.
  // A reload of the Skills and connectors page opens that page again instead of the chat (#183). Per window, like the rest.
  const LAST_PAGE_KEY = 'zook-last-page', KEPT_PAGES = ['skills', 'mcp', 'plugins'];
  let lastPageSaved = null;
  function restorePage() {
    let page = '';
    try { page = sessionStorage.getItem(LAST_PAGE_KEY) || ''; } catch (_) {}
    if (KEPT_PAGES.includes(page) && state.page === 'chat') loadPage(page).catch(() => {});
  }
  function savePage() {
    const page = KEPT_PAGES.includes(state.page) ? state.page : '';
    if (page !== lastPageSaved && state.lastRestored) { try { sessionStorage.setItem(LAST_PAGE_KEY, page); lastPageSaved = page; } catch (_) {} }
  }
  function saveLastOpen() {
    savePage();
    if (state.page !== 'chat' || !state.lastRestored || !state.data) return;
    state.ownChats = state.ownChats || {};
    const b = (state.data.bots || []).find(x => x.id === state.selected);
    if (b && !state.groupId && b.chatId && !state.ownChats[b.id]) state.ownChats[b.id] = b.chatId;
    const where = {bot: state.selected || '', group: state.groupId || ''};
    const own = JSON.stringify(Object.assign({chats: state.ownChats}, where)), shared = JSON.stringify(where);
    if (own !== lastOpenSaved.own) { try { sessionStorage.setItem(LAST_OPEN_KEY, own); lastOpenSaved.own = own; } catch (_) {} }
    if (shared !== lastOpenSaved.shared) { try { localStorage.setItem(LAST_OPEN_KEY, shared); lastOpenSaved.shared = shared; } catch (_) {} }
  }
  // This tab opened, started or sent in a conversation of the Bot: that one is now its own.
  function chooseChat(botId) {
    const b = (state.data?.bots || []).find(x => x.id === botId);
    if (!b || !b.chatId) return;
    state.ownChats = state.ownChats || {};
    state.ownChats[botId] = b.chatId;
    saveLastOpen();
  }
