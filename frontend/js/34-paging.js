  // Long conversations: the page holds the newest part of the open conversation and adds older parts as the reader scrolls up.
  // What has been loaded is kept here, next to what each refresh brings, so a refresh does not throw the older part away.
  const loadedParts = {};  // "botId:chatId" -> {list, more}
  function partOf(key, fresh, olderCount) {
    const kept = loadedParts[key];
    if (!kept) { loadedParts[key] = {list: fresh, more: (olderCount || 0) > 0}; return fresh; }
    const at = fresh.length ? kept.list.findIndex(m => m.id === fresh[0].id) : -1;
    // The newest part overlaps what is already here: keep the older messages in front of it. No overlap (a long absence, or the
    // conversation was rewritten): start again from the newest part.
    if (at >= 0) kept.list = kept.list.slice(0, at).concat(fresh);
    else { kept.list = fresh; kept.more = (olderCount || 0) > 0; }
    return kept.list;
  }
  const convMessages = b => partOf(b.id + ':' + b.chatId, b.messages || [], b.olderCount);
  const groupMsgs = g => partOf('group:' + g.id, g.messages || [], g.olderCount);  // a group discussion is paged the same way
  const olderButton = key => loadedParts[key]?.more ? `<div class="older-bar"><button class="link" data-older="1">${state.loadingOlder ? '載入中…' : '載入更早的訊息'}</button></div>` : '';
  const olderBar = b => olderButton(b.id + ':' + b.chatId);
  const groupOlderBar = g => olderButton('group:' + g.id);
  async function loadOlder() {
    if (state.loadingOlder || state.memberWork) return;
    const g = state.groupId ? activeGroup() : null, b = g ? null : activeBot(); if (!g && !b) return;
    const part = loadedParts[g ? 'group:' + g.id : b.id + ':' + b.chatId];
    if (!part || !part.more || !part.list.length) return;
    state.loadingOlder = true;
    try {
      const out = await api(g ? `groups/${encodeURIComponent(g.id)}/messages?before=${encodeURIComponent(part.list[0].id)}` : `bots/${encodeURIComponent(b.id)}/messages?chat=${encodeURIComponent(b.chatId)}&before=${encodeURIComponent(part.list[0].id)}`);
      const box = $('#conversation'), before = box ? box.scrollHeight - box.scrollTop : 0;
      part.list = out.messages.concat(part.list); part.more = out.more;
      state.loadingOlder = false; render(true);
      const now = $('#conversation'); if (now) now.scrollTop = now.scrollHeight - before;  // the reader stays on the message they were looking at
    } catch (err) { state.loadingOlder = false; toast(err.message); }
  }
  // Make sure a message that search or a notification points to is on the page, however far back it is.
  async function loadUpTo(b, messageId) {
    const key = b.id + ':' + b.chatId;
    if (convMessages(b).some(m => m.id === messageId)) return;
    try {
      const out = await api(`bots/${encodeURIComponent(b.id)}/messages?chat=${encodeURIComponent(b.chatId)}&from=${encodeURIComponent(messageId)}`);
      loadedParts[key] = {list: out.messages, more: out.more};
    } catch (_) {}
  }
  document.addEventListener('click', e => { if (e.target.closest?.('[data-older]')) loadOlder(); });
  document.addEventListener('scroll', e => { if (e.target?.id === 'conversation' && e.target.scrollTop < 40 && state.page === 'chat') loadOlder(); }, true);

  // Search runs on the Mac side, over every conversation, not only over what this page has loaded.
  let searchTimer = null;
  function searchMessages() {
    clearTimeout(searchTimer);
    const q = state.query;
    if (!q) { state.searchHits = []; return; }
    searchTimer = setTimeout(async () => {
      try {
        const out = await api('search?q=' + encodeURIComponent(q));
        if (state.query !== q) return;
        state.searchHits = out.hits; render(true);
        const box = $('#side-search'); if (box && document.activeElement !== box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
      } catch (_) {}
    }, 250);
  }
