
  // 設定頁 (#75, #76, #186–#188): a table of contents, the model rows, menus drawn alike, what is saved and what is not, its own address.

  // One button per section heading. Filled in after the page is drawn, so it always matches the sections shown.
  const settingsNav = () => '<nav class="settings-nav" aria-label="跳到設定的段落"></nav>';
  function fillSettingsNav() {
    const nav = $('.settings-nav');
    if (!nav || nav.childElementCount) return;
    nav.innerHTML = [...document.querySelectorAll('.page h2.settings-h')].map((h, i) => { h.dataset.navIndex = i; return `<button type="button" class="nav-chip" data-settings-jump="${i}">${esc(h.textContent.replace(/（.*）$/, ''))}</button>`; }).join('');
  }
  document.addEventListener('click', e => {
    const b = e.target.closest?.('[data-settings-jump]');
    if (!b) return;
    const h = document.querySelector(`.page h2.settings-h[data-nav-index="${b.dataset.settingsJump}"]`);
    if (!h) return;
    h.scrollIntoView({block: 'start'});
    h.tabIndex = -1; h.focus({preventScroll: true});  // the keyboard goes on from that section
  });

  // 模型: the provider and the model need 「儲存模型設定」; the backups below are saved as soon as they change.
  // The model row lets its note run under the whole row, so a long note never squeezes the title into one character a line (#75①, #188②).
  function modelSection(s) {
    const fallbacks = s.fallbacks || [];
    return `<h2 class="settings-h">模型</h2><p class="muted small settings-note">沒有另外指定的 Bot 用這裡的 AI。這兩項改完要按「儲存模型設定」；下面的「備用 AI」一改就存好。</p><form id="settings-form" class="setting-list">${settingRow('預設用哪家 AI', '新的 Bot 和沒有另外指定的 Bot 用這一家', `<select name="provider" class="plain-select" aria-label="預設用哪家 AI">${providerOptions(s.provider || 'codex', false)}</select>`)}<div class="setting-row model-row"><div class="setting-copy"><strong>預設型號</strong><span>同一家 AI 的不同版本。不確定就選「建議的型號」</span></div><div class="setting-control">${modelPicker(s.model || '', true)}</div></div><div class="setting-actions"><button class="primary" data-save>儲存模型設定</button><span class="unsaved-note" data-unsaved hidden>尚未儲存</span></div></form><div class="setting-list">${[0, 1].map(i => settingRow('備用 AI ' + (i + 1), i ? '備用 AI 1 也不能用時，改用這一家' : 'Bot 的 AI 額度用完、未登入或連不上時，依序改用備用 AI 1、2，回覆裡會註明改用哪一家', dropdown('fallback' + i, fallbacks[i] || '', [{id: '', name: '不使用'}, ...providerList().map(p => ({...p, name: p.name + troubleMark(modelTrouble(p.id, ''))}))], 'data-fallback-slot'))).join('')}</div>`;
  }

  // The settings page draws its two lists of choices (provider, model) like every other menu (#188⑥).
  // The real <select> stays in the form, hidden, so saving and the model list work as before; the menu mirrors it.
  function mirrorSelects(form) {
    if (form?.id !== 'settings-form') return;
    form.querySelectorAll('select').forEach(sel => {
      const options = [...sel.options].map(o => ({id: o.value, name: o.textContent}));
      const box = document.createElement('div');
      box.innerHTML = dropdown(sel.name + 'Menu', sel.value, options, `data-mirror-of="${esc(sel.name)}"`);
      const dd = box.firstElementChild, old = sel.parentElement.querySelector(':scope > .dd[data-mirror]'), focused = old?.contains(document.activeElement);
      dd.dataset.mirror = '';
      if (old?.classList.contains('open')) {  // the list arrived while it is open: new choices in place, the menu stays open
        old.querySelector('.dd-menu').innerHTML = dd.querySelector('.dd-menu').innerHTML;
        old.querySelector('.dd-label').textContent = dd.querySelector('.dd-label').textContent;
        old.querySelector('input[type=hidden]').value = dd.querySelector('input[type=hidden]').value;
        sel.hidden = true; return;
      }
      if (old) old.replaceWith(dd); else sel.after(dd);
      sel.hidden = true;
      if (focused) dd.querySelector('.dd-btn').focus({preventScroll: true});
    });
  }
  document.addEventListener('change', e => {
    const of = e.target.dataset?.mirrorOf;
    if (!of) return;
    const sel = e.target.closest('form')?.elements[of];
    if (!sel || sel.value === e.target.value) return;
    sel.value = e.target.value;
    sel.dispatchEvent(new Event('change', {bubbles: true}));
  });

  // 尚未儲存: the two parts that wait for their button say so while they differ from what is saved, and only then is the button on (#187②).
  function syncUnsaved() {
    const st = state.data?.settings || {};
    const mark = (form, dirty) => {
      if (!form) return;
      form.classList.toggle('dirty', dirty);
      const note = form.querySelector('[data-unsaved]'), btn = form.querySelector('[data-save]');
      if (note) note.hidden = !dirty;
      if (btn) btn.disabled = !dirty;
    };
    const f = $('#settings-form');
    if (f) mark(f, (f.elements.provider.value || 'codex') !== (st.provider || 'codex') || (f.elements.model.value || '') !== (st.model || ''));
    const r = $('#rules-form');
    if (r) mark(r, r.elements.rules.value !== (st.rules || ''));
  }
  ['input', 'change'].forEach(type => document.addEventListener(type, e => { if (e.target.closest?.('#settings-form, #rules-form')) setTimeout(syncUnsaved); }));

  // 已儲存: a setting saved the moment it changes says so beside its name for a moment (#187①).
  let lastChanged = null;
  const rowTitle = row => { const strong = row?.querySelector('.setting-copy strong'); return strong ? [...strong.childNodes].filter(n => !n.classList?.contains('saved-flash')).map(n => n.textContent).join('') : ''; };
  document.addEventListener('change', e => {
    if (state.page !== 'settings') return;
    const row = e.target.closest?.('.setting-row');
    if (row?.closest('#settings-form')) return;  // these wait for their button
    const title = rowTitle(row);
    if (title) lastChanged = {title, at: Date.now()};
  }, true);
  // A form saved with its button marks its own part, never a row changed before it; a failed save marks nothing.
  document.addEventListener('submit', e => { lastChanged = e.target.id === 'settings-form' ? {title: '預設型號', at: Date.now()} : null; }, true);
  function settingFailed() { lastChanged = null; }
  function settingSaved() {
    setTimeout(syncUnsaved);
    if (state.page !== 'settings' || !lastChanged || Date.now() - lastChanged.at > 15000) return;
    state.savedFlash = {title: lastChanged.title, at: Date.now()};
    lastChanged = null;
    setTimeout(showSavedFlash);
  }
  function showSavedFlash() {
    const f = state.savedFlash, left = f ? 2500 - (Date.now() - f.at) : 0;
    document.querySelectorAll('.saved-flash').forEach(x => x.remove());
    if (!f || left <= 0 || state.page !== 'settings') return;
    const row = [...document.querySelectorAll('.page .setting-row')].find(x => rowTitle(x) === f.title);
    if (!row) return;
    row.querySelector('.setting-copy strong').insertAdjacentHTML('beforeend', '<em class="saved-flash" role="status">✓ 已儲存</em>');
    clearTimeout(showSavedFlash.timer);
    showSavedFlash.timer = setTimeout(() => document.querySelectorAll('.saved-flash').forEach(x => x.remove()), left);
  }

  // Each page has its own address (#settings, #schedules …), so reloading stays there (#188④, #76④, #168③); a conversation has none.
  const PAGE_HASHES = ['settings', 'schedules', 'usage', 'skills', 'mcp', 'plugins', 'memory', 'knowledge', 'activity'];
  function syncSettingsHash() {
    const want = PAGE_HASHES.includes(state.page) ? '#' + state.page : '', has = PAGE_HASHES.includes(location.hash.slice(1)) ? location.hash : '';
    try {
      if (want && want !== has) history.replaceState(null, '', want);
      else if (!want && has) history.replaceState(null, '', location.pathname + location.search);
    } catch (_) {}
  }

  function settingsAfterRender() {
    if (!state.data) return;
    syncSettingsHash();
    if (state.page !== 'settings') return;
    fillSettingsNav();
    mirrorSelects($('#settings-form'));
    syncUnsaved();
    showSavedFlash();
  }

  // Keyboard: 「跳到頁面內容」 skips the sidebar (#188⑤).
  document.addEventListener('click', e => {
    if (!e.target.closest?.('[data-skip]')) return;
    const inner = $('.page-inner');
    const first = inner?.querySelector('button:not([disabled]), [href], input:not([type=hidden]):not([hidden]), textarea');
    first?.focus();
  });
  // A switch or menu that was just used keeps the keyboard when the page is drawn again, instead of it going back to the top.
  function focusedControl() {
    const a = document.activeElement;
    if (!a || a === document.body) return null;
    const dd = a.closest?.('.dd');
    if (dd) { const name = dd.querySelector('input[type=hidden]')?.name; return name ? {dd: name} : null; }
    if (a.matches?.('.switch') && a.getAttribute('aria-label')) return {sw: a.getAttribute('aria-label')};
    if (a.dataset?.settingsJump !== undefined) return {jump: a.dataset.settingsJump};
    if (a.dataset?.navIndex !== undefined) return {heading: a.dataset.navIndex};
    return null;
  }
  function restoreControlFocus(k) {
    if (!k || (document.activeElement && document.activeElement !== document.body)) return;
    const el = k.dd ? [...document.querySelectorAll('.dd > input[type=hidden]')].find(i => i.name === k.dd)?.closest('.dd').querySelector('.dd-btn')
      : k.jump !== undefined ? document.querySelector(`[data-settings-jump="${k.jump}"]`)
      : k.heading !== undefined ? (h => { if (h) h.tabIndex = -1; return h; })(document.querySelector(`.page h2.settings-h[data-nav-index="${k.heading}"]`))
      : [...document.querySelectorAll('.switch')].find(x => x.getAttribute('aria-label') === k.sw);
    el?.focus({preventScroll: true});
  }
