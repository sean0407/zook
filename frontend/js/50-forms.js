  async function saveBotDefault(input) {
    const key = input.dataset.botDefault, st = state.data.settings; let body;
    if (key === 'access') {
      if (input.value === 'folder' && !st.accessFolder) { const picked = (await post('choose-folder')).path; if (!picked) { render(true); return; } body = {access: 'folder', accessFolder: picked}; }
      else body = {access: input.value, accessFolder: st.accessFolder || ''};
    } else if (key === 'effort') body = {effort: input.value};
    else body = {features: {...(st.features || {}), [key]: input.checked}};
    const title = rowTitle(input.closest('.setting-row')) || 'Bot 預設';  // say which one (#76③)
    try { state.data.settings = await post('settings', body, 'PATCH'); toast('已更新「' + title + '」'); } catch (error) { toast(error.message); }
    render(true);
  }
  async function switchConnectorAccount(input) {
    const id = input.dataset.connector;
    try {
      if (id === 'builtin:google') await post('google/account', {account: input.value});
      else await post('connectors/' + encodeURIComponent(id.split(':')[1]) + '/account', {account: input.value});
      toast('所有 Bot 改用這個帳號');
    } catch (error) { toast(error.message); }
    state.integrations = await api('integrations'); render(true);
  }
  async function saveAutoModel(input) {
    const item = (state.quota?.providers || []).find(p => p.id === input.dataset.autoModel);
    if (!item) return;
    const was = item.autoOn;
    item.autoOn = input.checked;
    try { state.data.settings = await post('settings', {autoModels: state.quota.providers.filter(p => p.autoOn || (p.autoBilled && (state.data.settings.autoModels || []).includes(p.id))).map(p => p.id)}, 'PATCH'); toast(input.checked ? '自動選擇可以用這個模型' : '自動選擇不會用這個模型'); }
    catch (error) { item.autoOn = was; input.checked = was; toast(error.message); }
  }
  document.addEventListener('change', e => {
    if (e.target.name === 'providerChoice' && e.target.closest('#bot-form')) syncFeatureRows(e.target.closest('#bot-form'));
    if (e.target.dataset.showScripts) { state.showScripts = {...state.showScripts, [e.target.dataset.showScripts]: e.target.checked}; render(true); }  // 產出: a Bot's build scripts (#176)
    if (e.target.dataset.autoModel) saveAutoModel(e.target);
    if (e.target.dataset.botDefault) saveBotDefault(e.target);
    if (e.target.name === 'connectorAccount') switchConnectorAccount(e.target);
    if (e.target.name === 'groupMode' && activeGroup()) { state.groupMode[activeGroup().id] = e.target.value; updateGroupEstimate(); }
    if (e.target.name === 'botIds' && e.target.closest('#group-form')) syncGroupHost(e.target.closest('#group-form'));
    if (['botIds', 'hostId', 'checkMode'].includes(e.target.name) && e.target.closest('#group-form')) syncChecker(e.target.closest('#group-form'));  // #296
    if (['botIds', 'hostId', 'mode', 'checkMode', 'checkerId'].includes(e.target.name) && e.target.closest('#group-form')) groupFormNote(e.target.closest('#group-form'));
    if (e.target.id === 'group-file-input' && activeGroup()) uploadGroupFiles(activeGroup(), [...e.target.files]);
    if (e.target.name === 'access' && e.target.closest('#bot-form')) e.target.closest('form').querySelector('[data-access-folder]').hidden = e.target.value !== 'folder';
    if (e.target.name === 'transport' && e.target.closest('#connector-form')) e.target.closest('form').querySelectorAll('[data-for]').forEach(x => x.hidden = x.dataset.for !== e.target.value);
    if (e.target.name === 'accountType' && e.target.closest('#profile-form')) e.target.closest('form').querySelector('[data-key-field]').hidden = e.target.value !== 'key';
  });
  document.addEventListener('input', e => {
    if (e.target.id === 'chat-input' && activeGroup()) scheduleGroupEstimate();
    if ('memberSearch' in (e.target.dataset || {})) filterGroupMembers(e.target);
    if (e.target.closest('#bot-form')) saveBotDraft(e.target.closest('form'));
    if (e.target.name === 'modelCustom') {
      const f = e.target.closest('form');
      f.elements.model.value = e.target.value;
      if (f.id === 'bot-form') saveBotDraft(f);
    }
    if (e.target.id === 'dir-search') {
      const pos = e.target.selectionStart;
      state.dirQuery = e.target.value;
      render(true);
      const x = $('#dir-search'); x.focus(); x.setSelectionRange(pos, pos);
      return;
    }
    if (e.target.id === 'skill-search') {
      const pos = e.target.selectionStart;
      state.skillQuery = e.target.value;
      render(true);
      const x = $('#skill-search'); x.focus(); x.setSelectionRange(pos, pos);
      return;
    }
    if (e.target.id === 'chat-search') {
      const value = e.target.value, bot = activeBot();
      const show = () => { chatsModal(bot, value); const box = $('#chat-search'); box.focus(); box.setSelectionRange(value.length, value.length); };
      show();
      if (value.trim()) api('search?q=' + encodeURIComponent(value) + '&bot=' + encodeURIComponent(bot.id)).then(out => {  // which conversations contain it: asked of the Mac side, which has all of them
        if ($('#chat-search')?.value !== value) return;
        state.chatSearch = {q: value.trim().toLowerCase(), chats: out.chats}; show();
      }).catch(() => {});
      return;
    }
    if (e.target.id === 'side-search') {
      let pos = e.target.selectionStart;
      state.query = e.target.value;
      searchMessages();
      render(true);
      let x = $('#side-search');
      x.focus();
      x.setSelectionRange(pos, pos)
    }
    if (e.target.classList.contains('ability-search')) {
      const q = e.target.value.toLowerCase();
      e.target.parentElement.querySelectorAll('.ability-option').forEach(x => x.hidden = !x.dataset.search.includes(q));
    }
    if (e.target.id === 'integration-search') {
      $('#integration-cards').innerHTML = integrationCards(state.integrations, $('[data-action=int-filter].active')?.dataset.id || 'all', e.target.value)
    }
    if (e.target.id === 'persona-input') {
      const id = e.target.closest('form').dataset.id;
      state.personaDrafts = {...(state.personaDrafts || {}), [id]: e.target.value};
      const form = e.target.closest('form'), bot = state.data.bots.find(x => x.id === id);
      const dirty = e.target.value !== (bot?.persona || '');
      form.querySelector('.primary').disabled = !dirty;
      form.querySelector('small').textContent = e.target.value.length.toLocaleString() + ' / 20,000 字';
      return;
    }
    if (e.target.id === 'chat-input') {
      updateMentionMenu(); updateInputMirror();
      e.target.style.height = 'auto';
      e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px'
    }
  });
  document.addEventListener('change', async e => {
    if (e.target.dataset.remoteEnabled !== undefined || e.target.dataset.remoteRelay !== undefined) {
      const relayUrl = (document.querySelector('[data-remote-relay]')?.value || '').trim(), enabled = !!document.querySelector('[data-remote-enabled]')?.checked;
      try {
        state.data.settings = await post('settings', {remote: {enabled, relayUrl}}, 'PATCH');
        toast(enabled ? '遠端連線已開啟' : e.target.dataset.remoteRelay !== undefined ? '已儲存中繼伺服器' : '遠端連線已關閉');
        setTimeout(() => loadRemote(true), 1500);
      } catch (err) { toast(err.message); }
      await loadRemote(true);
      return;
    }
    if (e.target.dataset.remoteExpiry !== undefined) {
      try { state.data.settings = await post('settings', {remoteExpiryDays: Number(e.target.value)}, 'PATCH'); toast(Number(e.target.value) ? '已更新自動失效期限' : '已改為永久有效，手機遺失時記得撤銷'); }
      catch (err) { toast(err.message); }
      render(true); return;
    }
    if (e.target.dataset.fallbackSlot !== undefined) {
      const picks = [...document.querySelectorAll('[data-fallback-slot]')].map(x => x.value).filter(Boolean);
      try { state.data.settings = await post('settings', {fallbacks: [...new Set(picks)]}, 'PATCH'); toast(picks.length ? '備用順序：' + [...new Set(picks)].map(providerShort).join(' → ') : '已關閉自動換模型'); }
      catch (err) { toast(err.message); }
      return;
    }
    if (e.target.dataset.long !== undefined) { state.long[state.selected] = e.target.checked; render(true); return; }
    if (e.target.dataset.plan !== undefined) {
      state.plan[state.selected] = e.target.checked;
      if (e.target.checked) toast('這則訊息 Bot 只會提出計畫，不會動手');
      render(true); return;
    }
    if (e.target.dataset.effort !== undefined && e.target.closest('#chat-form, .mode-rows')) {
      state.effort[effortKey()] = e.target.value; render(true);
      return;
    }
    if (e.target.name === 'trigger' && e.target.closest('#schedule-form')) { e.target.closest('#schedule-form').dataset.trigger = e.target.value; return; }
    if (e.target.name === 'repeat' && e.target.closest('#schedule-form')) {
      e.target.closest('.sched-when').dataset.repeat = e.target.value;
      return;
    }
    if (e.target.dataset.scheduleNotify !== undefined) {
      try { state.data.settings = await post('settings', {scheduleNotify: e.target.checked}, 'PATCH'); toast(e.target.checked ? '會跳出排程通知' : '已關閉排程通知'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      return;
    }
    if (e.target.dataset.phoneNotify !== undefined) {
      const label = e.target.getAttribute('aria-label') || '手機通知';
      try { state.data.settings = await post('settings', {phoneNotify: {[e.target.dataset.phoneNotify]: e.target.checked}}, 'PATCH'); toast((e.target.checked ? '已開啟' : '已關閉') + label.replace('手機：', '手機「') + '」'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      return;
    }
    if (e.target.dataset.scheduleSwitch !== undefined) {
      const on = e.target.checked;
      try { await post('schedules/' + encodeURIComponent(e.target.dataset.id), {on}, 'PATCH'); await refresh(); toast(on ? '已啟用排程' : '已停用排程'); }
      catch (err) { e.target.checked = !on; toast(err.message); }
      return;
    }
    if (e.target.dataset.dirFilter !== undefined) { state.dirFilter = e.target.value; render(true); return; }
    if (e.target.dataset.dirSwitch !== undefined) {
      const kind = e.target.dataset.kind, id = e.target.dataset.id;
      const key = kind === 'skill' ? 'disabledSkills' : kind === 'mcp' ? 'sharedMcp' : 'disabledPlugins', set = new Set(state.data.settings[key] || []);
      const turnOn = e.target.checked; e.target.disabled = true;
      if (kind === 'mcp') turnOn ? set.add(id) : set.delete(id); else turnOn ? set.delete(id) : set.add(id);
      try {
        state.data.settings = await post('settings', {[key]: [...set]}, 'PATCH');
        if (kind === 'plugin') state.integrations = await api('integrations');
        const what = {skill: '這個 Skill', mcp: '這個連接器', plugin: '這個插件'}[kind] || '';
        const name = kind === 'skill' ? (state.integrations?.skills || []).find(x => x.id === id)?.name : '';
        render(true);
        toast(name ? (turnOn ? `已開啟「${name}」，移到「已開啟」，所有 Bot 都能用` : `已關閉「${name}」，移到「未啟用」，所有 Bot 都不會再用它`)
          : turnOn ? `已開放${what}給所有 Bot` : `已停用${what}，所有 Bot 都不會再用它`);
      } catch (err) { e.target.checked = !turnOn; e.target.disabled = false; toast(err.message); }
      return;
    }
    if (e.target.dataset.autoUpdate !== undefined) {
      try { state.data.settings = await post('settings', {autoUpdateCheck: e.target.checked}, 'PATCH'); toast(e.target.checked ? '會自動檢查更新' : '已關閉自動檢查更新'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      return;
    }
    if (e.target.dataset.browserAutomation !== undefined) {
      try { state.data.settings = await post('settings', {browserAutomation: e.target.checked}, 'PATCH'); render(true); toast(e.target.checked ? '排程與觸發也能用內建瀏覽器' : '只有你送出的訊息能用內建瀏覽器'); }
      catch (error) { toast(error.message); render(true); }
      return;
    }
    if (e.target.dataset.webSearch !== undefined) {
      try { state.data.settings = await post('settings', {webSearch: e.target.checked}, 'PATCH'); render(true); toast(e.target.checked ? '所有 Bot 已可上網搜尋' : '已關閉上網搜尋'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      return;
    }
    if (e.target.dataset.permissionMode !== undefined && e.target.name === 'permissionMode' && !e.target.closest('form')) {
      const previous = state.data.settings.permissionMode || 'manual';
      try {
        state.data.settings = await post('settings', {permissionMode: e.target.value}, 'PATCH');
        render(true); toast('主動性已改為「' + permissionName(e.target.value) + '」');
      } catch (err) { toast(err.message); state.data.settings.permissionMode = previous; render(true); }
      return;
    }
    if (e.target.dataset.pluginToggle) {
      const off = new Set(state.data.settings.disabledPlugins || []), id = e.target.dataset.pluginToggle;
      e.target.checked ? off.delete(id) : off.add(id);
      e.target.disabled = true;
      try {
        state.data.settings = await post('settings', {disabledPlugins: [...off]}, 'PATCH');
        state.integrations = await api('integrations');
        render(true); toast(e.target.checked ? '已啟用插件' : '已停用插件，它的 Skill 與 MCP 不再提供給 Bot');
      } catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      finally { if (e.target.isConnected) e.target.disabled = false; }
      return;
    }
    if (e.target.dataset.sharedSkill) {
      const off = new Set(state.data.settings.disabledSkills || []), id = e.target.dataset.sharedSkill;
      e.target.checked ? off.delete(id) : off.add(id);
      e.target.disabled = true;
      try { state.data.settings = await post('settings', {disabledSkills: [...off]}, 'PATCH'); render(true); toast(e.target.checked ? '已開放給所有 Bot' : '已停用此 Skill'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      finally { if (e.target.isConnected) e.target.disabled = false; }
      return;
    }
    if (e.target.id === 'ability-bot') { state.selected = e.target.value || null; render(); return; }
    if (e.target.dataset.abilityKind) {
      const b = activeBot(); if (!b) return;
      const key = e.target.dataset.abilityKind, id = e.target.dataset.abilityId;
      const values = new Set(b[key] || []); e.target.checked ? values.add(id) : values.delete(id);
      e.target.disabled = true;
      try { await post('bots/' + encodeURIComponent(b.id), {[key]: [...values]}, 'PATCH'); b[key] = [...values]; toast('已更新 Bot 能力'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      finally { e.target.disabled = false; }
      return;
    }
    const form = e.target.closest('form');
    if (!form || !form.querySelector('.model-picker')) return;
    if (e.target.name === 'providerChoice' || e.target.name === 'provider') {
      if (e.target.name === 'providerChoice') {  // the Bot form: the model and the account in one menu, CLI or CLI::account
        const [provider, account] = e.target.value.split('::');
        const same = form.elements.provider.value === provider;
        form.elements.provider.value = provider; form.elements.account.value = account || '';
        if (same) { saveBotDraft(form); return; }  // only another account of the same CLI: its model stays
      }
      form.elements.model.value = '';
      form.elements.modelSelect.value = '';
      form.elements.modelCustom.value = '';
      form.elements.modelCustom.hidden = true;
      form.dataset.providerChanged = '1';
      form.querySelector('.model-note').textContent = '換了一家，型號已改回它建議的版本，正在讀取能選的型號…';
      loadModels(form);
    } else if (e.target.name === 'modelSelect') {
      const custom = form.elements.modelCustom;
      const isCustom = e.target.value === '__custom__';
      custom.hidden = !isCustom;
      form.elements.model.value = isCustom ? custom.value : e.target.value;
      if (isCustom) custom.focus();
    }
    if (form.id === 'bot-form') saveBotDraft(form);
  });
  // #63: a form's main button goes off and says 建立中… / 儲存中… the moment it is pressed, until the answer comes back, so a
  // second press (or Enter) while making a Bot takes its few seconds sends nothing. What a form makes also carries an id for this
  // opening of the form (onceId), so a repeat that still reaches the Mac gets the first one back instead of a copy.
  const busyWord = label => { const w = String(label || '').trim().match(/^(建立|儲存|新增|送出|連接|連結|匯入)/); return (w ? w[1] : '處理') + '中…'; };
  const onceId = form => form.dataset.once || (form.dataset.once = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 14));
  // A required field left empty is said next to it, in words, not only with the browser's small bubble at the top (#63).
  function fieldError(input) {
    let note = input.parentElement.querySelector('.field-error');
    if (!note) { note = document.createElement('small'); note.className = 'field-error'; note.setAttribute('role', 'alert'); input.insertAdjacentElement('afterend', note); }
    note.textContent = input.dataset.need || '這一欄要填寫。';
    input.setAttribute('aria-invalid', 'true'); input.scrollIntoView({block: 'center'}); input.focus();
  }
  document.addEventListener('input', e => {
    if (e.target.getAttribute?.('aria-invalid') !== 'true') return;
    e.target.removeAttribute('aria-invalid'); e.target.parentElement.querySelector('.field-error')?.remove();
  });
  document.addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    if (form.dataset.busy) return;  // the first press is still on its way
    const empty = form.id === 'chat-form' ? null : [...form.elements].find(x => x.required && !x.disabled && !String(x.value).trim());
    if (empty) { fieldError(empty); sayMissing(form); return; }  // also beside the button, which may be far from the field (#224)
    if (form.id === 'group-form' && !groupFormNote(form)) { form.querySelector('[data-group-problem]')?.scrollIntoView({block: 'nearest'}); return; }
    const button = form.id === 'chat-form' ? null : form.querySelector('button.primary:not([type=button])'), label = button?.textContent, was = button?.disabled;
    if (button) { form.dataset.busy = '1'; button.disabled = true; button.textContent = busyWord(label); }
    try {
      if (form.id === 'chat-form') {
        let input = $('#chat-input'),
          content = input.value.trim();
        if (pendingList().some(f => f.uploading)) { toast('檔案還在上傳，請稍等'); return; }
        const attachments = pendingList().map(f => f.id);
        if (!content && !attachments.length) { toast('請先輸入內容'); input.focus(); return; }  // #263: not a silent nothing
        const g = activeGroup();
        if (g && g.status === 'running' && attachments.length) { toast('討論進行中只能傳文字；附件請等這輪結束或先停止'); return; }
        // Shown at once; the reply, the refresh and anything slow on the Mac come after. Each message has its own id.
        const botId = state.selected, b = activeBot();
        const sending = g ? sendingAdd(g.id, 'groups/' + encodeURIComponent(g.id) + '/messages', {content, attachments, effort: pickedEffort(), mode: currentGroupMode(g)}, g.id)
          : sendingAdd(botId + '/' + (b?.chatId || ''), 'chat', {botId, content, attachments, effort: pickedEffort(), plan: !!state.plan[botId], long: !!state.long[botId]});
        if (!g) chooseChat(botId);  // sending here makes this conversation this window's own
        pendingList().length = 0; keepPending(); input.value = ''; updateInputMirror();
        if (g) { delete state.groupMode[g.id]; state.groupEstimate = null; } else { state.plan[botId] = false; state.long[botId] = false; }
        render(true); $('#chat-input')?.focus();
        await sendingSend(sending);
      } else if (form.id === 'bot-form') {
        let d = new FormData(form),
          id = form.dataset.id;
        let data = {
          name: d.get('name').trim(),
          jobTitle: (d.get('jobTitle') || '').trim(),
          shape: d.get('shape'),
          color: d.get('color'),
          instructions: d.get('instructions'),
          persona: d.get('persona') || '',
          provider: d.has('providerChoice') ? String(d.get('providerChoice')).split('::')[0] : d.get('provider'),  // what the menu shows
          model: d.get('model'),
          section: d.get('section'),
          pinned: d.has('pinned'),
          fallbacks: d.get('fallbackChoice') === '__none' ? [] : !d.get('fallbackChoice') || d.get('fallbackChoice') === '__default' ? null : [d.get('fallbackChoice')], effort: d.get('effort') || '', features: Object.fromEntries([['multi', d.get('featureMulti')], ['image', d.get('featureImage')], ['browser', d.get('featureBrowser')]].filter(x => x[1]).map(x => [x[0], x[1] === 'on'])),
          account: d.has('providerChoice') ? String(d.get('providerChoice')).split('::')[1] || '' : d.get('account') || '',
          access: d.get('access') || '', accessFolder: d.get('access') === 'folder' ? d.get('accessFolder') || '' : ''
        };
        if (d.get('heldAccess') === 'full' && !form.querySelector('[data-held-access]').hidden) Object.assign(data, {access: 'full', accessFolder: ''});  // #284: back behind the gate
        if (!id) data.clientId = onceId(form);
        if (data.access === 'folder' && !data.accessFolder) { if (form.querySelector('[data-access-row]')?.hidden) toast('請先選擇資料夾'); else needFolder(form); return; }
        let result = await post(id ? 'bots/' + encodeURIComponent(id) : 'bots', data, id ? 'PATCH' : 'POST');
        if (!id) { try { sessionStorage.removeItem('swarmr-new-bot-draft'); } catch (_) {} }
        closeModal();
        await refresh();
        if (!id) {
          state.selected = result.id || result.bot?.id || state.data.bots.at(-1)?.id;
          state.page = 'chat';
          render()
        }
        const made = '已建立「' + (result.name || result.bot?.name || data.name) + '」';  // #253: says which Bot, and stays long enough to be read
        toast(id ? (result.autoNotice ? '已儲存 Bot。' + result.autoNotice : '已儲存 Bot') : result.autoReason ? made + '，自動配好：' + result.autoReason : made + '，可以開始對話了', id ? 3000 : 6000)
      } else if (form.id === 'mcp-bots-form') {
        const id = form.dataset.id, chosen = new Set(new FormData(form).getAll('bots'));
        for (const b of state.data.bots) {
          const has = (b.enabledMcp || []).includes(id);
          if (has === chosen.has(b.id)) continue;
          const next = has ? b.enabledMcp.filter(x => x !== id) : [...(b.enabledMcp || []), id];
          await post('bots/' + encodeURIComponent(b.id), {enabledMcp: next}, 'PATCH');
        }
        closeModal(); await refresh(); toast('已更新使用這個連接器的 Bot');
      } else if (form.id === 'persona-form') {
        const id = form.dataset.id, persona = new FormData(form).get('persona');
        await post('bots/' + encodeURIComponent(id), {persona}, 'PATCH');
        if (state.personaDrafts) delete state.personaDrafts[id];
        await refresh(); toast('已儲存人格，下次回覆開始生效');
      } else if (form.id === 'custom-provider-form') {
        const d = Object.fromEntries(new FormData(form));
        if (d.providerId) d.id = d.providerId;
        delete d.providerId;
        await post('accounts/custom', d);
        closeModal(); await reloadAccounts(); toast('已儲存，Bot 現在可以選用這個 CLI');
      } else if (form.id === 'catalog-key-form') {
        const button = form.querySelector('.primary'); button.disabled = true; button.textContent = '正在確認金鑰…';
        try { await catalogAdd(form.dataset.id, new FormData(form).get('key').trim()); }
        finally { if (button.isConnected) { button.disabled = false; button.textContent = '連結'; } }
      } else if (form.id === 'google-form') {
        const d = new FormData(form);
        await post('google', {clientId: d.get('clientId').trim(), clientSecret: d.get('clientSecret').trim(), write: form.elements.write.checked});
        closeModal(); toast('已在瀏覽器開啟 Google 登入頁，完成後回到這裡');
        for (let n = 0; n < 90 && state.page === 'mcp'; n++) {
          await new Promise(r => setTimeout(r, 2000));
          state.integrations = await api('integrations');
          if (!(state.integrations.mcp || []).find(i => i.google)?.needsSetup) { await refresh(); toast('Google 已登入，所有 Bot 都可以使用'); break; }
        }
      } else if (form.id === 'gmail-form') {
        const d = new FormData(form), button = form.querySelector('.primary');
        button.disabled = true; button.textContent = '正在連接…';
        try { await post('gmail', {address: d.get('address').trim(), password: d.get('password')}); }
        finally { if (button.isConnected) { button.disabled = false; button.textContent = '連接'; } }
        closeModal(); delete state.mcpTests['builtin:gmail'];
        state.integrations = await api('integrations'); await refresh(); toast('Gmail 已連接，所有 Bot 都可以使用');
      } else if (form.id === 'connector-form') {
        const d = new FormData(form), transport = d.get('transport'), id = form.dataset.id, env = {}, err = form.querySelector('.form-error');
        const problem = (text, field) => { err.textContent = text; err.hidden = !text; if (text) { err.scrollIntoView({block: 'nearest'}); form.elements[field]?.focus(); } };
        problem('');
        for (const line of (d.get('env') || '').split('\n').map(x => x.trim()).filter(Boolean)) {
          const at = line.indexOf('=');
          if (at < 1) { problem('環境變數每行要寫成「名稱=值」，例如 API_KEY=abc。', 'env'); return; }
          env[line.slice(0, at).trim()] = line.slice(at + 1).trim();
        }
        const secret = (transport === 'http' ? d.get('secretHttp') : d.get('secretStdio')).trim();
        const body = {name: d.get('name').trim(), transport, command: d.get('command').trim(), url: d.get('url').trim(), env: transport === 'http' ? {} : env, secretName: transport === 'http' ? '' : d.get('secretName').trim()};
        if (secret) body.secret = secret;
        if (d.has('clearSecret')) body.clearSecret = true;
        const more = {};
        for (const [k, v] of d.entries()) if (k.startsWith('more:') && String(v).trim()) more[k.slice(5)] = String(v).trim();
        if (Object.keys(more).length) body.moreSecrets = more;
        let made;
        try { made = await post(id ? 'connectors/' + encodeURIComponent(id) : 'connectors', body, id ? 'PATCH' : 'POST'); }
        catch (error) { problem(error.message, /網址/.test(error.message) ? 'url' : /指令/.test(error.message) ? 'command' : 'name'); return; }
        closeModal(); delete state.mcpTests[made.id];
        state.integrations = await api('integrations'); await refresh();
        toast(id ? '已儲存。按「測試連線」確認能不能用' : '已新增。按「測試連線」確認能不能用');
      } else if (form.id === 'profile-form') {
        const d = new FormData(form), type = d.get('accountType');
        if (type === 'key' && !d.get('key').trim()) { toast('請貼上 API 金鑰'); return; }
        await post('accounts/' + encodeURIComponent(form.dataset.id) + '/profiles', {name: d.get('name').trim(), type, key: type === 'key' ? d.get('key').trim() : ''});
        closeModal(); await reloadAccounts(); toast(type === 'key' ? '已新增，可以到 Bot 的設定選用' : '已新增，請按登入完成設定');
      } else if (form.id === 'account-code-form') {
        const code = new FormData(form).get('code').trim();
        if (!code) return;
        await post('accounts/' + encodeURIComponent(form.dataset.id) + '/login/code', {code, account: form.dataset.account || ''});
        toast('已送出授權碼');
        state.accounts = await api('accounts'); render(true); pollAccounts();
      } else if (form.id === 'group-form') {
        const d = new FormData(form), id = form.dataset.id, keepAuto = groupKeepsAuto(form);  // #223②: not quietly saved as 自由
        const result = await post(id ? 'groups/' + encodeURIComponent(id) : 'groups', {name: d.get('name').trim(), botIds: d.getAll('botIds'), hostId: d.get('hostId') || '', ...(keepAuto ? {} : {mode: d.get('mode') || 'free'}), turnLimit: Number(d.get('turnLimit')) || 4, checkMode: d.get('checkMode') || 'auto', checkerId: d.get('checkMode') === 'pick' ? d.get('checkerId') || '' : '', instructions: String(d.get('instructions') || ''), ...(id ? {} : {clientId: onceId(form)})}, id ? 'PATCH' : 'POST');
        closeModal();
        state.groupId = result.id;
        state.page = 'chat';
        await refresh();
        toast(id ? '已儲存群組' : '已建立群組');
      } else if (form.id === 'section-form') {
        const name = new FormData(form).get('name').trim(), old = form.dataset.old, names = sectionNames();
        if (!name) return;
        if (name !== old && names.includes(name)) { toast('已經有同名的分組'); return; }
        const sections = old ? names.map(x => x === old ? name : x) : [...names, name];
        const bots = old ? state.data.bots.map(b => !b.pinned && (b.section || '我的 Bots') === old ? {...b, section: name} : b) : state.data.bots;
        closeModal(); await saveArrangement(bots, sections);
        toast(old ? '已重新命名分組' : '已新增分組，把 Bot 拖進去即可');
      } else if (form.id === 'edit-last-form') {
        const b = activeBot(), content = new FormData(form).get('content');
        if (!String(content).trim()) return;
        if (!(await redoAllowed(b))) return;
        closeModal(); await redo(b, {mode: 'edit', content});
      } else if (form.id === 'redo-model-form') {
        const b = activeBot(), provider = new FormData(form).get('provider');
        if (!(await redoAllowed(b))) return;
        closeModal(); await redo(b, {mode: 'again', provider});
      } else if (form.id === 'chat-rename-form') {
        const b = activeBot();
        await post(`bots/${encodeURIComponent(b.id)}/chats/${encodeURIComponent(form.dataset.id)}`, {title: new FormData(form).get('title')}, 'PATCH');
        await refresh(); chatsModal(activeBot()); toast('已改名');
      } else if (form.id === 'schedule-form') {
        const d = new FormData(form), id = form.dataset.id;
        const [kind, targetId] = String(d.get('target')).split(':');
        const trigger = d.get('trigger') || 'time', repeat = trigger === 'time' ? d.get('repeat') : 'daily';
        const data = {trigger, name: String(d.get('name') || '').trim(), [kind === 'group' ? 'groupId' : 'botId']: targetId, content: d.get('content'), repeat, time: trigger !== 'time' ? '00:00' : (repeat === 'hourly' ? '00' : d.get('hour')) + ':' + d.get('minute'), on: d.get('on') === 'on', catchUp: d.get('catchUp') === 'on', quiet: d.get('quiet') === 'on'};
        if (repeat === 'once') data.date = d.get('date');
        if (repeat === 'monthly') data.day = Number(d.get('day'));
        if (trigger === 'folder') data.watchFolder = d.get('watchFolder');
        if (trigger === 'mail') { data.mailFrom = d.get('mailFrom'); data.mailSubject = d.get('mailSubject'); }
        // Problems stay under the form until fixed, instead of a toast that fades (#166, #168)
        const err = form.querySelector('.sched-err'), problem = !String(data.content || '').trim() ? '請填寫要 Bot 做的事。'
          : data.on && repeat === 'once' && trigger === 'time' && new Date(`${data.date}T${data.time}:00`) <= new Date() ? '這個時間已經過了，請改日期或時間。' : '';
        if (err) { err.textContent = problem; err.hidden = !problem; if (problem) err.scrollIntoView({block: 'nearest'}); }
        if (problem) return;
        if (!id) data.clientId = onceId(form);
        let saved;
        try { saved = await post(id ? 'schedules/' + encodeURIComponent(id) : 'schedules', data, id ? 'PATCH' : 'POST'); }
        catch (error) { if (!err) throw error; err.textContent = error.message; err.hidden = false; err.scrollIntoView({block: 'nearest'}); return; }
        closeModal();
        await refresh();
        const next = scheduleNext(saved || {});
        const renamed = !id && saved?.name && saved.name !== data.name ? `已有相同的排程，這筆叫「${saved.name}」。` : '';  // #299
        toast(renamed + (next ? `已儲存排程，下次執行：${nextLabel(next)}` : '已儲存排程'));
      } else if (form.id === 'know-search-form') {
        await knowSearch(form);  // 試搜尋 (36c-knowledge.js)
      } else if (form.id === 'note-form') {
        await saveNote(form, form.dataset.id ? '' : onceId(form));  // 36c-knowledge.js; a typed one is made once however often 儲存 is pressed
      } else if (form.id === 'settings-form') {
        let d = new FormData(form);
        await post('settings', {
          provider: d.get('provider'),
          model: d.get('model')
        }, 'PATCH');
        await refresh();
        toast('已儲存設定')
      }
    } catch (err) {
      toast(/^(建立|新增)/.test(String(label || '').trim()) ? '建立失敗：' + err.message : err.message)
    } finally {
      delete form.dataset.busy;
      if (button?.isConnected) { button.disabled = was; button.textContent = label; }
    }
  });
  document.addEventListener('keydown', e => {
    if (e.target.id === 'chat-input' && mention.items.length && !$('#mention-menu')?.hidden && !e.isComposing && e.keyCode !== 229) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        mention.index = (mention.index + (e.key === 'ArrowDown' ? 1 : -1) + mention.items.length) % mention.items.length;
        updateMentionMenu(); return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickMention(mention.index); return; }
      if (e.key === 'Escape') { e.preventDefault(); hideMentionMenu(); return; }
    }
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'n') {
      e.preventDefault();
      if (state.data.bots.length < 2) toast('至少需要 2 個 Bot 才能建立群組'); else leaveModalForm().then(go => { if (go) groupModal(); });  // a form with changes asks first (#297)
      return
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      $('#side-search')?.focus()
    }
    if (e.key === 'Escape' && state.modal) {
      requestCloseModal();
      return
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229 && e.target.id === 'chat-input') {
      e.preventDefault();
      $('#chat-form').requestSubmit()
    }
    if (e.key === 'Tab' && state.modal) {
      let focusable = $$('.modal button,.modal input,.modal textarea,.modal select').filter(x => !x.disabled && x.offsetParent !== null);
      if (!focusable.length) return;
      let first = focusable[0],
        last = focusable.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus()
      }
    }
  });
  refresh().then(() => {
    startPollers();
    recoveryNotice();
    if (state.data.settings.onboarded === false) api('accounts').then(a => { state.accounts = a; render(true); }).catch(() => {});
    setInterval(syncFromElsewhere, 3000);
    setTimeout(refreshUpdate, 4000); setTimeout(refreshUpdate, 20000); setInterval(refreshUpdate, 3600 * 1000);
  }).catch(e => {
    app.innerHTML = `<div class="boot">無法開啟 Zook：${esc(e.message)}</div>`
  });
})();

