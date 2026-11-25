  document.addEventListener('click', async e => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const action = el.dataset.action,
      id = el.dataset.id;
    try {
      switch (action) {
        case 'pick-mention':
          pickMention(Number(id));
          break;
        case 'select-group':
          state.groupId = id;
          state.page = 'chat';
          state.launcher = false;
          render();
          break;
        case 'new-group':
          if (state.data.bots.length < 2) { toast('至少需要 2 個 Bot 才能建立群組'); break; }
          groupModal();
          break;
        case 'edit-group':
          groupModal(activeGroup());
          break;
        case 'delete-group':
          if (await ask({title: '刪除這個群組？', lines: ['群組的對話、群組檔案和它的排程會一起刪除，無法復原。', '成員 Bot 不會被刪除，它們自己的對話都還在。'],
                         run: () => api('groups/' + encodeURIComponent($('#group-form').dataset.id), {method: 'DELETE'})})) {
            closeModal();
            state.groupId = null;
            await refresh();
            toast('已刪除群組')
          }
          break;
        case 'account-detail':
          accountDetail(id, el.dataset.account || '');
          break;
        case 'terminal-login':
          closeModal();
          await post('accounts/' + encodeURIComponent(id) + '/terminal-login', {account: el.dataset.account || ''});
          toast('已開啟終端機，請在那裡選擇 Google 登入，完成後回到 Zook');
          break;
        case 'detect-usage':
          if (state.usageBusy) break;
          state.usageBusy = 'detect'; render(true);
          try { await detectUsage(); toast('已更新使用量'); }
          catch (err) { toast(err.message); }
          state.usageBusy = ''; render(true);
          break;
        case 'update-all': {
          const list = (state.accounts?.providers || []).filter(p => p.installed && p.canInstall && p.version?.updateAvailable);
          if (list.length && !(await ask({title: '更新 CLI？', lines: [`將更新 ${list.map(p => p.name.split('（')[0] + ' ' + p.version.latest).join('、')}，完成後重新偵測使用量。`], ok: '更新', danger: false}))) break;
          if (state.usageBusy) break;
          state.usageBusy = 'update'; render(true);
          try {
            const started = await Promise.all(list.map(p => post('accounts/' + encodeURIComponent(p.id) + '/install').then(() => p.id, () => null)));
            await loadAccounts();
            for (let i = 0; i < 400 && state.accounts.providers.some(p => p.install?.state === 'running'); i++) { await new Promise(r => setTimeout(r, 1500)); await loadAccounts(); }
            await detectUsage();
            const failed = state.accounts.providers.filter(p => started.includes(p.id) && p.install?.state !== 'succeeded').map(p => p.name.split('（')[0]);
            toast(!list.length ? '全部都是最新版，使用量已更新' : failed.length ? `${failed.join('、')} 沒有更新成功，其他已完成` : '全部更新完成，使用量已更新');
          } catch (err) { toast(err.message); }
          state.usageBusy = ''; render(true);
          break;
        }
        case 'refresh-claude-quota':
          el.disabled = true; el.textContent = '更新中…';
          try { state.quota = await post('quota/claude/refresh'); render(true); toast('已更新 Claude 額度'); }
          finally { if (el.isConnected) { el.disabled = false; el.textContent = '立即更新'; } }
          break;
        case 'account-login':
          el.disabled = true;
          await post('accounts/' + encodeURIComponent(id) + '/login', {method: el.dataset.method, account: el.dataset.account || ''});
          closeModal(); await reloadAccounts();  // the card shows the sign-in from here on
          break;
        case 'update-open':
          updateModal();
          break;
        case 'update-check':
          el.disabled = true; el.textContent = '檢查中…';
          state.update = await post('update/check'); render(true);
          toast(state.update.available ? `有新版 ${state.update.latest}` : state.update.error || '已是最新版');
          break;
        case 'update-install':
          el.disabled = true;
          await installUpdate();
          break;
        case 'accounts-from-form':
          closeModal(); state.accounts = null; await loadPage('usage');
          break;
        case 'profile-add':
          profileModal(state.accounts.providers.find(x => x.id === id));
          break;
        case 'profile-delete':
          if (!(await ask({title: `移除帳號「${el.dataset.name}」？`, lines: ['使用它的 Bot 會改用預設帳號。'], ok: '移除'}))) break;
          await post('accounts/' + encodeURIComponent(id) + '/profiles/delete', {account: el.dataset.account});
          closeModal(); await reloadAccounts(); toast('已移除帳號');
          break;
        case 'provider-add':
          providerAddModal();
          break;
        case 'provider-add-one':
          el.disabled = true;
          await post('accounts/' + encodeURIComponent(id) + '/add');
          closeModal(); await reloadAccounts(); toast('已加入，可以按「一鍵安裝」或直接登入');
          break;
        case 'provider-custom':
          customProviderModal();
          break;
        case 'provider-edit':
          customProviderModal(state.accounts.providers.find(x => x.id === id));
          break;
        case 'provider-install': {
          const p = state.accounts.providers.find(x => x.id === id);
          const domain = (el.dataset.command.match(/https?:\/\/([^/\s]+)/) || [])[1];
          const msg = el.dataset.command ? `將在這台電腦執行 ${p.name} 的官方安裝程式${domain ? '（來自 ' + domain + '）' : ''}。` : `會把 ${p.name} 更新到最新版。`;
          if (!(await ask({title: el.dataset.command ? `安裝 ${p.name}？` : `更新 ${p.name}？`, lines: [msg], ok: el.dataset.command ? '安裝' : '更新', danger: false}))) break;
          el.disabled = true;
          await post('accounts/' + encodeURIComponent(id) + '/install');
          closeModal(); await reloadAccounts();
          break;
        }
        case 'install-cancel':
          await post('accounts/' + encodeURIComponent(id) + '/install/cancel');
          await reloadAccounts();
          break;
        case 'provider-remove': {
          const p = state.accounts.providers.find(x => x.id === id);
          if (!(await ask({title: `從 Zook 移除 ${p.name}？`, lines: ['這不會解除安裝 CLI，也不會登出。'], ok: '移除'}))) break;
          await post('accounts/' + encodeURIComponent(id) + '/remove');
          closeModal(); await reloadAccounts(); toast('已從 Zook 移除');
          break;
        }
        case 'account-cancel':
          await post('accounts/' + encodeURIComponent(id) + '/login/cancel', {account: el.dataset.account || ''});
          await reloadAccounts();
          break;
        case 'account-logout':
          if (await ask({title: '登出這個帳號？', lines: ['使用它的 Bot 會無法回覆，要再登入才能用。'], ok: '登出'})) {
            await post('accounts/' + encodeURIComponent(id) + '/logout');
            closeModal(); await reloadAccounts(); toast('已登出');
          }
          break;
        case 'persona-reset':
          if (state.personaDrafts) delete state.personaDrafts[activeBot()?.id];
          render(true);
          break;
        case 'dir-tab':
          if (el.dataset.clear !== undefined) state.dirQuery = '';
          await loadPage(id); render();  // reads the list again: a plugin installed meanwhile shows up
          break;
        case 'dir-filter':
          state.dirFilter = id; render(true);
          break;
        case 'dir-expand':
          state.dirExpanded = {...(state.dirExpanded || {}), [id]: !state.dirExpanded?.[id]}; render(true);
          break;
        case 'dir-toggle': {
          const kind = el.dataset.kind;
          el.disabled = true;
          const key = kind === 'skill' ? 'disabledSkills' : kind === 'mcp' ? 'sharedMcp' : 'disabledPlugins', off = new Set(state.data.settings[key] || []);
          off.has(id) ? off.delete(id) : off.add(id);
          state.data.settings = await post('settings', {[key]: [...off]}, 'PATCH');
          if (kind === 'mcp') { render(true); toast(off.has(id) ? '已開放給所有 Bot' : '已停用這個連接器，所有 Bot 都不會再用它'); break; }
          if (kind === 'plugin') state.integrations = await api('integrations');
          render(true);
          toast(kind === 'skill' ? (off.has(id) ? '已停用這個 Skill，所有 Bot 都不會再用它' : '已開放給所有 Bot') : (off.has(id) ? '已停用插件，所有 Bot 都不會再用它' : '已啟用插件，所有 Bot 都能用'));
          break;
        }
        case 'delete-memory': {
          const m = (state.data.memories || []).find(x => x.id === id);
          if (!m) break;
          const owner = m.botId && state.data.bots.find(b => b.id === m.botId)?.name;
          const after = !m.botId ? '所有 Bot 之後都不會再記得這件事。' : owner ? `「${owner}」之後不會再記得這件事。` : '';
          if (await ask({title: '刪除這則記憶？', lines: [`「${m.content}」`, '刪除後無法復原。' + after], run: () => api('memories/' + encodeURIComponent(id), {method: 'DELETE'})})) {
            await refresh();
            toast('已刪除記憶')
          }
          break;
        }
        case 'group-continue': { const g = activeGroup(); await post('groups/' + encodeURIComponent(g.id) + '/continue'); await refresh(); pollGroup(g.id); break; }
        case 'group-discard': { const g = activeGroup(); await post('groups/' + encodeURIComponent(g.id) + '/continue', {discard: true}); await refresh(); break; }
        case 'group-summarize': { const g = activeGroup(); await post('groups/' + encodeURIComponent(g.id) + '/summarize'); await refresh(); pollGroup(g.id); break; }
        case 'group-verify': await verifyGroupMessage(activeGroup(), id); break;
        case 'group-verify-anyway': await verifyGroupMessage(activeGroup(), id, true); break;
        case 'group-verify-dismiss': delete (state.verifyNotes || {})[id]; render(true); break;
        case 'card-copy': { const m = groupMsgs(activeGroup()).find(x => x.id === id); await navigator.clipboard.writeText(cardText(m.card)); toast('已複製結論'); break; }
        case 'card-save': { const g = activeGroup(), m = groupMsgs(g).find(x => x.id === id); await post('knowledge', {title: g.name + ' 討論結論', content: cardText(m.card)}); toast('已存到知識庫'); break; }
        case 'group-tab': state.groupTab = id; if (activeGroup()) delete state.groupFiles[activeGroup().id]; render(true); break;
        case 'group-file-pick': $('#group-file-input').click(); break;
        case 'group-file-delete': { const g = activeGroup(); if (!(await ask({title: `刪除「${id}」？`, lines: ['這個檔案會從群組檔案刪除，無法復原。'], run: () => api('groups/' + encodeURIComponent(g.id) + '/files/' + encodeURIComponent(id), {method: 'DELETE'})}))) break; await loadGroupFiles(g); toast('已刪除檔案'); break; }
        case 'stop-group':
          await post('groups/' + encodeURIComponent(id) + '/stop');
          toast('已停止討論');
          await refresh(); pollGroup(id);  // a member whose CLI is still ending shows 正在停止 (37b-progress.js)
          break;
        case 'mention': {
          const input = $('#chat-input');
          const pos = input.selectionStart ?? input.value.length;
          const before = input.value.slice(0, pos), insert = (before && !/\s$/.test(before) ? ' ' : '') + '@' + id + ' ';
          input.value = before + insert + input.value.slice(pos); updateInputMirror();
          input.focus();
          input.setSelectionRange(pos + insert.length, pos + insert.length);
          break;
        }
        case 'select-bot':
          state.memberWork = null;
          state.groupId = null;
          state.selected = id;
          state.page = 'chat';
          state.launcher = false;
          render();
          break;
        case 'remote-pair':
          el.disabled = true;
          try { pairingModal(await post('remote/pairing')); } catch (err) { toast(err.message); el.disabled = false; }
          break;
        case 'remote-pair-cancel':
          await api('remote/pairing', {method: 'DELETE'}).catch(() => {});
          closeModal(); loadRemote(true);
          break;
        case 'remote-revoke': {
          const d = state.remote?.devices.find(x => x.id === id);
          if (!d || !(await ask({title: `撤銷「${d.name}」？`, lines: ['這台裝置會立刻無法連線，要再使用必須重新配對。'], ok: '撤銷'}))) break;
          state.remote = await api('remote/devices/' + encodeURIComponent(id), {method: 'DELETE'});
          render(true); toast('已撤銷「' + d.name + '」');
          break;
        }
        case 'new-section':
          sectionModal();
          break;
        case 'rename-section':
          sectionModal(id);
          break;
        case 'delete-section':
          await saveArrangement(state.data.bots, sectionNames().filter(x => x !== id));
          toast('已刪除分組');
          break;
        case 'dir-collapse': {
          // Remembered with the other settings, so a group you fold away stays folded next time.
          const now = new Set(state.data.settings.dirCollapsed || []);
          now.has(id) ? now.delete(id) : now.add(id);
          state.data.settings.dirCollapsed = [...now]; render(true);
          state.data.settings = await post('settings', {dirCollapsed: [...now]}, 'PATCH');
          break;
        }
        case 'collapse':
          state.collapsed[id] = !state.collapsed[id];
          render(true);
          break;
        case 'search-focus':
          $('#side-search')?.focus();
          break;
        case 'new-bot':
          botModal();
          break;
        case 'edit-bot':
          botModal(activeBot());
          break;
        case 'launcher':
          state.launcher = !state.launcher;
          render(true);
          break;
        case 'page':
          await loadPage(id);
          break;
        case 'toggle-detail':
          state.detailOpen = !state.detailOpen;
          render(true);
          break;
        case 'outputs-refresh': await loadOutputs(activeBot().id); break;
        case 'output-open': await openOutput(el.dataset.bot || activeBot().id, id); break;
        case 'output-reveal': await post('bots/' + encodeURIComponent(el.dataset.bot) + '/outputs/' + encodeURIComponent(id) + '/reveal'); break;
        case 'detail':
          if (id === 'outputs' && activeBot()) delete state.outputs[activeBot().id];
          state.detail = id;
          render(true);
          break;
        case 'new-schedule':
          scheduleModal();
          break;
        case 'edit-schedule':
          scheduleModal(state.data.schedules.find(x => x.id === id));
          break;
        case 'delete-schedule':
          if (await ask({title: '刪除這個排程？', lines: ['之後不會再自動執行，刪除後無法復原。'], run: () => api('schedules/' + encodeURIComponent(id), {method: 'DELETE'})})) {
            await refresh();
            toast('已刪除排程');
          }
          break;
        case 'schedule-history':
          scheduleHistory(state.data.schedules.find(x => x.id === id));
          break;
        case 'open-run':
          await openConversation(el.dataset.kind, el.dataset.target, id);
          break;
        case 'pick-files': {
          closeModal();
          const picker = document.createElement('input'); picker.type = 'file'; picker.multiple = true;
          picker.onchange = () => addFiles([...picker.files]); picker.click();
          break;
        }
        case 'unattach':
          pendingList().splice(pendingList().findIndex(f => f.key === id), 1); render(true);
          break;
        case 'view-image':
          modal(el.dataset.name || '圖片', `<div class="modal-body image-view"><img src="/api/uploads/${esc(id)}" alt="${esc(el.dataset.name || '')}"></div>`, '', true);
          break;
        case 'run-plan': {
          const b = activeBot();
          const sent = await post('chat', {botId: b.id, content: '請照上面的計畫執行。', effort: pickedEffort()});
          await refresh(); poll(sent.jobId, b.id);
          break;
        }
        case 'resume-reply': {
          const b = activeBot(), last = (b.messages || []).slice(-1)[0];
          const sent = await post('chat/resume', {botId: b.id, messageId: last?.id});
          await refresh(); poll(sent.jobId, b.id);
          break;
        }
        case 'open-privacy':
          await post('privacy-settings', {pane: el.dataset.pane});
          toast('已打開系統設定。允許 Zook 後回來按「重試」');
          break;
        case 'redo-again': {
          const b = activeBot();
          if (await redoAllowed(b)) await redo(b, {mode: 'again'});
          break;
        }
        case 'edit-last': {
          const b = activeBot(), last = [...b.messages].reverse().find(m => m.role === 'user');
          modal('編輯訊息', `<form id="edit-last-form"><div class="modal-body"><label class="field">改完後重新送出，之後的回覆會被取代<textarea name="content" required rows="6">${esc(last.content)}</textarea></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">重新送出</button></div></form>`);
          break;
        }
        case 'redo-model': {
          const b = activeBot(), installed = (state.providers || []).filter(p => p.installed !== false);
          const options = installed.map(p => ({id: p.id, name: String(p.name).split('（')[0], hint: p.id === (b.provider || state.data.settings.provider) ? '這個 Bot 目前用的' : ''}));
          if (!options.length) { toast('沒有其他可用的模型'); break; }
          const other = options.find(o => !o.hint) || options[0];
          modal('換模型重答', `<form id="redo-model-form"><div class="modal-body"><p class="muted">只有這一次用別的模型回答，不會改變 Bot 的設定。</p><div class="setting-list in-form">${settingRow('模型', '用預設版本回答', dropdown('provider', other.id, options))}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">重答</button></div></form>`);
          break;
        }
        case 'open-message':
          state.query = ''; await openConversation('bot', el.dataset.bot, id);
          break;
        case 'chats':
          chatsModal(activeBot());
          break;
        case 'new-chat': {
          const b = activeBot(); state.memberWork = null;  // from a group's work page: back to a conversation with the Bot
          await post(`bots/${encodeURIComponent(b.id)}/chats`, {});
          if (state.modal) closeModal();
          await refresh(); $('#chat-input')?.focus();
          break;
        }
        case 'open-chat': {
          const b = activeBot(); state.memberWork = null;
          if (id !== b.chatId) { await post(`bots/${encodeURIComponent(b.id)}/chats/${encodeURIComponent(id)}/open`, {}); }
          closeModal(); await refresh();
          break;
        }
        case 'rename-chat': {
          const b = activeBot(), c = b.chats.find(x => x.id === id);
          modal('對話名稱', `<form id="chat-rename-form" data-id="${esc(id)}"><div class="modal-body"><label class="field">名稱<input name="title" required maxlength="80" value="${esc(chatName(b, c))}"></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="chats">返回</button><button class="primary">儲存</button></div></form>`);
          break;
        }
        case 'delete-chat': {
          const b = activeBot(), c = b.chats.find(x => x.id === id);
          if (!(await ask({title: `刪除「${chatName(b, c)}」？`, lines: ['這段對話會刪除，無法復原。Bot 的其他對話不受影響。'], run: () => api(`bots/${encodeURIComponent(b.id)}/chats/${encodeURIComponent(id)}`, {method: 'DELETE'})}))) break;
          await refresh(); chatsModal(activeBot()); toast('已刪除對話');
          break;
        }
        case 'run-schedule':
          await post('schedules/' + encodeURIComponent(id) + '/run', {});
          await refresh(); startPollers();
          toast('已送出，回覆會出現在對話裡');
          break;
        case 'new-note':
          noteModal();
          break;
        case 'edit-note':
          noteModal(state.data.knowledge.find(n => n.id === id));
          break;
        case 'delete-note':
          if (await ask({title: '刪除這則知識？', lines: ['刪除後無法復原，Bot 之後不會再參考它。'], run: () => api('knowledge/' + encodeURIComponent(id), {method: 'DELETE'})})) {
            await refresh();
            toast('已刪除知識')
          }
          break;
        case 'delete-bot': {
          const botId = $('#bot-form').dataset.id, name = state.data.bots.find(b => b.id === botId)?.name || '這個 Bot';
          const inGroups = (state.data.groups || []).filter(g => (g.botIds || []).includes(botId));
          const tooFew = inGroups.filter(g => g.botIds.filter(id => state.data.bots.some(b => b.id === id)).length <= 2).map(g => g.name);
          const schedules = (state.data.schedules || []).filter(s => s.botId === botId).length;
          if (await ask({title: `刪除「${name}」？`, lines: [
            '它和它的對話會先收起來，之後可以到「各模型使用量」的 Bot Token 用量按「喚回」找回（回覆過的 Bot 才會列在那裡）。',
            inGroups.length ? `它在這些群組裡：${inGroups.map(g => g.name).join('、')}，刪除後會少一位成員，喚回後也不會自動加回。` + (tooFew.length ? `${tooFew.join('、')} 會只剩 1 位，要再加成員才能討論。` : '') : '',
            schedules ? `它的 ${schedules} 個排程會一起刪除，喚回後不會回來。` : ''],
            run: () => api('bots/' + encodeURIComponent(botId), {method: 'DELETE'})})) {
            closeModal();
            await refresh();
            toast('已刪除 Bot')
          }
          break;
        }
        case 'choose-folder': {
          const picked = (await post('choose-folder')).path, form = $('#bot-form');
          if (picked && form) { form.elements.accessFolder.value = picked; form.querySelector('[data-access-path]').textContent = picked; saveBotDraft(form); }
          break;
        }
        case 'close-modal':
          closeModal();
          break;
        case 'overlay':
          if (e.target === el) closeModal();
          break;
        case 'avatar-pick': { const panel = $('#bot-form .avatar-panel'); panel.hidden = !panel.hidden; break; }
        case 'default-folder': { const picked = (await post('choose-folder')).path; if (picked) { state.data.settings = await post('settings', {access: 'folder', accessFolder: picked}, 'PATCH'); render(true); toast('已更新 Bot 預設'); } break; }
        case 'shape':
          $('#bot-form [name=shape]').value = id;
          $$('.shape-btn').forEach(x => x.classList.toggle('selected', x.dataset.id === id));
          $('.bot-preview .avatar').className = `avatar shape-${id} hero`;
          saveBotDraft($('#bot-form'));
          break;
        case 'color':
          $('#bot-form [name=color]').value = id;
          $$('.swatch').forEach(x => x.classList.toggle('selected', x.dataset.id === id));
          $$('#bot-form .avatar').forEach(x => x.style.setProperty('--c', id));
          saveBotDraft($('#bot-form'));
          break;
        case 'voice':
          toggleVoice();
          break;
        case 'composer-menu':
          modal('更多選項', '<div class="modal-body more-options"><button class="secondary" data-action="pick-files">📎 附加檔案或圖片</button><p class="muted">也可以拖進對話或貼上截圖。最多 10 個，單檔 20 MB。</p><button class="secondary" data-action="new-note">＋ 新增知識</button><p class="muted">新增知識，為 Bot 提供相關背景。</p>' + `<div class="setting-list mode-rows">${effortRow()}</div>` + (activeGroup() ? '' : '<p class="muted">在訊息框輸入 <b>/goal</b> 開啟長任務、<b>/plan</b> 開啟先規劃。</p>') + '</div>');
          break;
        case 'chat-folder': { const b = activeBot(); if (b) await post('bots/' + encodeURIComponent(b.id) + '/chats/' + encodeURIComponent(b.chatId) + '/folder'); break; }
        case 'dismiss-approval': state.seenApprovals[id] = true; render(true); break;
        case 'approve':
        case 'deny':
          if (state.deciding[id]) break;
          state.deciding[id] = true;
          el.disabled = true;
          try {
            try { await post('approvals/' + encodeURIComponent(id), {decision: action === 'approve' ? 'approve' : 'deny'}); }
            catch (e) {
              if (!/已結束/.test(e.message)) throw e;
              toast('這張核准卡已經結束：可能已在別處決定，或 Bot 不再等它。'); break;  // the next refresh shows what really happened
            }
            for (const j of Object.values(state.jobDetails)) for (const a of j.approvals || []) if (a.id === id) Object.assign(a, {status: action === 'approve' ? 'approved' : 'denied', decidedAt: new Date().toISOString(), callsAt: (j.toolCalls || []).length});
            render(true);
          } finally { delete state.deciding[id]; if (el.isConnected) el.disabled = false; }
          break;
        case 'google-setup': googleModal(); break;
        case 'google-add': {
          const ids = item => (item?.accounts || []).map(x => x.id).join(), before = ids((state.integrations?.mcp || []).find(i => i.google));
          await post('google', {add: true}); toast('已在瀏覽器開啟 Google 登入頁，選另一個帳號登入');
          for (let n = 0; n < 90 && state.page === 'mcp'; n++) {
            await new Promise(r => setTimeout(r, 2000));
            let now; try { now = await api('integrations'); } catch (_) { continue; }
            if (ids((now.mcp || []).find(i => i.google)) !== before) { state.integrations = now; render(true); toast('帳號已更新，可以在卡片上選擇要用哪一個'); break; }
          }
          break;
        }
        case 'google-remove':
          if (!(await ask({title: '登出這個 Google 帳號？', lines: ['還有其他帳號時會改用下一個。'], ok: '登出'}))) break;
          await api('google', {method: 'DELETE'}); delete state.mcpTests['builtin:google'];
          state.integrations = await api('integrations'); await refresh(); toast('已登出 Google');
          break;
        case 'gmail-setup':
          gmailModal();
          break;
        case 'gmail-remove':
          if (!(await ask({title: '中斷 Gmail 連接？', lines: ['所有 Bot 都會無法使用 Gmail，要再連接才能用。'], ok: '中斷連接'}))) break;
          await api('gmail', {method: 'DELETE'});
          delete state.mcpTests['builtin:gmail'];
          state.integrations = await api('integrations'); await refresh(); toast('已中斷 Gmail 連接');
          break;
        case 'connector-add':
          connectorModal();
          break;
        case 'skills-import': {
          const ids = directoryItems('skills').filter(i => i.group === id && i.importable).map(i => i.id);
          el.disabled = true; el.textContent = '匯入中…';
          const r = await post('skills/import', {ids});
          state.integrations = await api('integrations'); await refresh();
          toast([r.imported.length ? `已匯入 ${r.imported.length} 個 Skill：${r.imported.join('、')}` : '沒有新的 Skill 可以匯入', r.skipped.length ? `${r.skipped.length} 個同名的只保留一份` : '', r.failed.length ? `${r.failed.length} 個匯入失敗：${r.failed[0].error}` : ''].filter(Boolean).join('，'));
          break;
        }
        case 'skill-update':
          el.disabled = true;
          await post('skills/' + encodeURIComponent(id.split(':')[1]) + '/update');
          state.integrations = await api('integrations'); render(true); toast('已更新成原來源的最新內容');
          break;
        case 'skill-remove':
          if (!(await ask({title: `從 Zook 移除 Skill「${el.dataset.name}」？`, lines: ['所有 Bot 都不會再用到它。原本工具裡的那一份不受影響。'], ok: '移除'}))) break;
          await api('skills/' + encodeURIComponent(id.split(':')[1]), {method: 'DELETE'});
          state.integrations = await api('integrations'); await refresh(); toast('已從 Zook 移除');
          break;
        case 'connector-copy': {
          el.disabled = true;
          const made = await post('connector-copy', {id});
          state.integrations = await api('integrations'); await refresh();
          try { state.mcpTests[made.id] = await post('mcp/' + encodeURIComponent(made.id) + '/test'); }
          catch (error) { state.mcpTests[made.id] = {status: 'error', error: error.message}; }
          render(true);
          toast(state.mcpTests[made.id].status === 'ready' ? '已加入，連線正常' : '已加入，但連不上。需要登入的話請按「登入」');
          break;
        }
        case 'pack-export': {
          el.disabled = true;
          const pack = await api('pack');
          el.disabled = false;
          if (!pack.skills && !pack.connectors) { toast('還沒有可以匯出的內容'); break; }
          const raw = atob(pack.data), bytes = new Uint8Array(raw.length);
          for (let n = 0; n < raw.length; n++) bytes[n] = raw.charCodeAt(n);
          download(bytes, pack.name, 'application/zip');
          toast(`已匯出 ${pack.skills} 個 Skill、${pack.connectors} 個連接器`);
          break;
        }
        case 'pack-import': {
          const input = document.createElement('input');
          input.type = 'file'; input.accept = '.zookpack,.zip';
          input.onchange = async () => {
            const file = input.files[0];
            if (!file) return;
            if (file.size > 150 * 1024 * 1024) { toast('設定包超過 150 MB，無法匯入'); return; }
            if (!(await ask({title: `匯入「${file.name}」？`, lines: ['設定包可以在這台 Mac 上執行程式，只匯入你自己匯出的檔案。'], ok: '匯入'}))) return;
            try {
              const text = await new Promise((done, fail) => { const reader = new FileReader(); reader.onload = () => done(reader.result); reader.onerror = fail; reader.readAsDataURL(file); });
              const r = await post('pack', {data: String(text).split(',')[1] || ''});
              state.integrations = await api('integrations'); await refresh();
              toast([`已匯入 ${r.skills.length} 個 Skill、${r.connectors.length} 個連接器`, r.skipped.length ? `${r.skipped.length} 個已經有或無法匯入，已略過` : '', r.needKeys.length ? `${r.needKeys.length} 個連接器需要重新貼上金鑰` : ''].filter(Boolean).join('，'));
            } catch (error) { toast(error.message || '匯入失敗'); }
          };
          input.click();
          break;
        }
        case 'catalog-why': catalogWhy(id); break;
        case 'found-toggle': state.foundOpen = !state.foundOpen; render(true); break;
        case 'catalog-add': await catalogAdd(id); break;
        case 'connector-login': {
          const ids = item => (item?.accounts || []).map(x => x.id).join(), before = ids((state.integrations?.mcp || []).find(i => i.id === id)), adding = !!el.dataset.add;
          await post('connectors/' + encodeURIComponent(id.split(':')[1]) + '/login', adding ? {add: true} : {});
          toast('已在瀏覽器開啟登入頁，完成後回到這裡');
          for (let n = 0; n < 90 && ['mcp', 'skills', 'plugins'].includes(state.page); n++) {  // wait for the browser to come back
            await new Promise(r => setTimeout(r, 2000));
            state.integrations = await api('integrations');
            const now = (state.integrations.mcp || []).find(i => i.id === id);
            if (adding ? ids(now) !== before : now?.signedIn) { await retestConnector(id); render(true); toast(adding ? '已新增帳號，可以在卡片上選擇要用哪一個' : '登入完成'); break; }
          }
          break;
        }
        case 'connector-retest': await retestConnector(id); render(true); break;
        case 'connector-logout':
          if (!(await ask({title: '登出目前使用的這個帳號？', lines: ['它的授權會從鑰匙圈刪除，要再登入才能用。'], ok: '登出'}))) break;
          await post('connectors/' + encodeURIComponent(id.split(':')[1]) + '/logout');
          state.integrations = await api('integrations'); render(true); toast('已登出');
          break;
        case 'connector-edit':
          connectorModal((state.integrations?.mcp || []).find(i => i.id === id));
          break;
        case 'connector-delete':
          if (!(await ask({title: `移除連接器「${el.dataset.name}」？`, lines: ['所有 Bot 都會無法再使用它。'], ok: '移除'}))) break;
          await api('connectors/' + encodeURIComponent(id.split(':')[1]), {method: 'DELETE'});
          delete state.mcpTests[id];
          state.integrations = await api('integrations'); await refresh(); toast('已移除連接器');
          break;
        case 'test-mcp':
          el.disabled = true;
          try { state.mcpTests[id] = await post('mcp/' + encodeURIComponent(id) + '/test'); }
          catch (error) { state.mcpTests[id] = {status:'error', error:error.message}; }
          render(true);
          break;
        case 'cancel-job':
          stopAsked(id);
          await post('jobs/' + encodeURIComponent(id) + '/cancel');
          toast('正在停止回覆');
          break;
        case 'force-stop':
          el.disabled = true;
          try { await forceStop(id); } finally { el.disabled = false; }  // a failed try can be tried again
          break;
        case 'share': {  // the open conversation as Markdown (chatexport.py)
          const g = activeGroup(), b = g ? null : activeBot();
          const out = await api(g ? 'groups/' + encodeURIComponent(g.id) + '/export' : `bots/${encodeURIComponent(b.id)}/export?chat=${encodeURIComponent(b.chatId)}`);
          if (out.empty) { toast('這段對話還沒有內容'); break; }
          download(out.markdown, out.name, 'text/markdown;charset=utf-8');
          toast(`已送出下載：${out.name}`);
          break
        }
        case 'export': {
          let data = await post('export');
          download(JSON.stringify(data, null, 2), 'Zook-export.json', 'application/json');
          break
        }
        case 'refresh-models':
          await loadModels(el.closest('form'), true);
          break;
        case 'int-filter':
          $$('[data-action=int-filter]').forEach(x => x.classList.toggle('active', x === el));
          $('#integration-cards').innerHTML = integrationCards(state.integrations, id, $('#integration-search').value);
          break;
      }
    } catch (err) {
      toast(err.message)
    }
  });

  function $$(s) {
    return [...document.querySelectorAll(s)]
  }
