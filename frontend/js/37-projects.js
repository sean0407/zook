  // 專案: a named set of Bots, groups and knowledge. The sidebar can show one project at a time.
  const projects = () => state.data.projects || [];
  const activeProject = () => projects().find(p => p.id === state.projectId) || null;
  const inProject = (key, id) => { const p = activeProject(); return !p || (p[key] || []).includes(id); };
  function projectBar() {
    if (!projects().length) return `<div class="project-bar"><button class="side-empty" data-action="project-new">＋ 建立專案，把相關的 Bot 和知識放在一起</button></div>`;
    const options = [{id: '', name: '全部'}, ...projects().map(p => ({id: p.id, name: p.name}))];
    return `<div class="project-bar"><div class="project-pick">${dropdown('projectFilter', state.projectId || '', options)}</div>${activeProject() ? '<button class="icon-btn" data-action="project-edit" aria-label="編輯專案" title="編輯專案">✎</button>' : ''}<button class="icon-btn" data-action="project-new" aria-label="新增專案" title="新增專案">＋</button></div>`;
  }
  function projectModal(p = {}) {
    const editing = !!p.id, pick = (name, items, chosen, label) => items.length ? `<label class="field">${label}</label><div class="member-pick">${items.map(x => `<label class="member-switch">${x.avatar || ''}<span class="member-copy"><strong>${esc(x.name)}</strong></span>${toggle(`name="${name}" value="${esc(x.id)}"`, (chosen || []).includes(x.id), x.name)}</label>`).join('')}</div>` : '';
    modal(editing ? '編輯專案' : '新增專案', `<form id="project-form" data-id="${esc(p.id || '')}"><div class="modal-body"><label class="field">名稱<input name="name" required maxlength="60" placeholder="例如：新品上市" value="${esc(p.name || '')}"></label><label class="field">說明（選填）<textarea name="note" maxlength="4000" rows="3" placeholder="這個專案的目標、背景或注意事項。專案裡的 Bot 回覆時會看到。">${esc(p.note || '')}</textarea></label><div class="setting-list in-form"><div class="setting-row"><div class="setting-copy"><strong>專案資料夾</strong><span data-project-path>${esc(p.folder || '尚未選擇')}</span></div><div class="setting-control"><input type="hidden" name="folder" value="${esc(p.folder || '')}"><button type="button" class="secondary" data-action="project-folder">選擇資料夾…</button></div></div></div><p class="muted small">Bot 會知道資料夾的位置；能不能讀寫仍依每個 Bot 自己的存取範圍。</p>${pick('botIds', state.data.bots.map(b => ({id: b.id, name: b.name, avatar: avatar(b)})), p.botIds, 'Bot')}${pick('groupIds', (state.data.groups || []).map(g => ({id: g.id, name: g.name})), p.groupIds, '群組')}${pick('knowledgeIds', state.data.knowledge.map(k => ({id: k.id, name: k.title})), p.knowledgeIds, '知識')}</div><div class="modal-foot">${editing ? '<button type="button" class="link" data-action="project-delete" style="margin-right:auto;color:#b55">刪除專案</button>' : ''}<button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${editing ? '儲存' : '建立專案'}</button></div></form>`);
  }
  async function saveProject(form) {
    const d = new FormData(form), id = form.dataset.id;
    const saved = await post(id ? 'projects/' + encodeURIComponent(id) : 'projects', {name: d.get('name').trim(), note: d.get('note'), folder: d.get('folder'), botIds: d.getAll('botIds'), groupIds: d.getAll('groupIds'), knowledgeIds: d.getAll('knowledgeIds')}, id ? 'PATCH' : 'POST');
    closeModal(); state.projectId = saved.id; await refresh(); toast(id ? '已儲存專案' : '已建立專案');
  }
