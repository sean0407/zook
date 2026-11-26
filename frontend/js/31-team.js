
  // A whole team from one sentence: describe the work, look over the role cards, and Zook makes the Bots and their group.
  const teamLink = () => `<button type="button" class="team-link" data-team="open">✳ 用一句話建立整個團隊</button>`;
  const TEAM_PARTS = [['duty', '負責'], ['deliverable', '主要交付物'], ['worksWith', '協作對象'], ['notDoing', '不負責']];
  function teamAsk(goal = '', problem = '') {
    state.team = null;
    modal('建立團隊', `<form id="team-ask"><div class="modal-body"><p class="muted">說明要做的事，Zook 會規劃一位統籌和幾位成員，各有明確的分工。先給你看過，確認後才建立。</p><label class="field">要做的事<textarea name="goal" rows="3" maxlength="2000" required placeholder="例如：開一個手工香氛品牌，從產品到上架販售">${esc(goal)}</textarea></label>${problem ? `<p class="error-text small">${esc(problem)}</p>` : ''}</div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">規劃團隊</button></div></form>`);
  }
  // Each role's model and thinking level, as the sentence named them; a model this Mac cannot use is shown with why, and waits for a choice.
  function teamModelOptions(r) {
    const t = state.team, usable = (t.choices || []).filter(c => !c.problem);
    const opts = usable.map(c => ({id: c.id, name: c.id === 'auto' && r.autoPick ? `自動選擇（目前會配 ${r.autoPick}）` : c.name, hint: c.id === 'auto' ? '依職責與額度自動挑' : ''}));
    if (!r.provider) opts.unshift({id: '', name: '請選擇模型'});
    return opts;
  }
  const teamEffortOk = r => !r.provider || (state.team.choices || []).find(c => c.id === r.provider)?.effort !== false;
  function teamModelRow(r) {
    const effort = teamEffortOk(r) ? dropdown('effort', r.effort || '', [{id: '', name: '預設'}, ...EFFORTS], 'aria-label="思考強度"') : '<span class="muted small">不能調整</span>';
    return `<div class="team-model"><label><span>模型</span>${dropdown('provider', r.provider ?? 'auto', teamModelOptions(r), 'data-team-provider aria-label="模型"')}</label><label><span>思考強度</span>${effort}</label></div>${r.problem && !r.provider ? `<p class="error-text small">${esc(r.problem)}</p>` : ''}${GATED_CLIS.includes(r.provider) ? '<p class="muted small">整台 Mac；刪除檔案、對外送出等動作前會先問你</p>' : ''}`;
  }
  function teamCard(r, i) {
    return `<article class="team-card ${i === 0 ? 'lead' : ''}" data-team-role="${i}"><header>${avatar({color: TEAM_COLORS[(state.data.bots.length + i) % 8], shape: (state.data.bots.length + i) % 13})}<div class="team-names"><input name="name" maxlength="20" required aria-label="名稱" value="${esc(r.name)}"><input name="jobTitle" maxlength="12" required aria-label="職稱" value="${esc(r.jobTitle)}"></div>${i === 0 ? '<span class="pill">統籌</span>' : `<button type="button" class="icon-btn" data-team="remove" data-id="${i}" aria-label="移除 ${esc(r.name)}" title="移除這個角色">×</button>`}</header>${teamModelRow(r)}${TEAM_PARTS.map(([k, label]) => r[k] ? `<p><span>${label}</span>${esc(r[k])}</p>` : '').join('')}</article>`;
  }
  const TEAM_COLORS = ['#2585f6', '#13bf78', '#f59a0a', '#ed2f9b', '#14b8a6', '#ff6d0c', '#9254ff', '#a47545'];
  function teamPreview() {
    const t = state.team;
    modal('確認團隊', `<form id="team-make"><div class="modal-body"><label class="field">團隊名稱<input name="team" maxlength="30" required value="${esc(t.team)}"></label><p class="muted small">目標：${esc(t.goal)}</p>${(t.warnings || []).map(w => `<p class="error-text small">規劃時發現：${esc(w)}</p>`).join('')}<div class="team-cards">${t.roles.map(teamCard).join('')}</div>${settingRow('建立後先請大家交起步清單', '每位成員依自己的職責列出最先要做的事，統籌整理成分工表', toggle('name="kickoff"', t.kickoff !== false, '建立後先請大家交起步清單'))}<p class="muted small">會建立 ${t.roles.length} 個 Bot 和一個群組，由統籌主持。名稱和職稱可以直接修改，之後也能在各 Bot 的設定裡調整。</p></div><div class="modal-foot"><button type="button" class="secondary" data-team="again">重新規劃</button><button class="primary" ${t.roles.length < 4 ? 'disabled title="至少要有統籌和三位成員"' : t.roles.some(r => !r.provider) ? 'disabled title="還有成員沒選模型"' : ''}>建立團隊</button></div></form>`, '', true);
  }
  // What is typed into the cards is kept when a role is removed and the cards are drawn again.
  function teamRead() {
    const t = state.team, form = $('#team-make');
    if (!t || !form) return;
    t.team = form.elements.team.value.trim(); t.kickoff = form.elements.kickoff.checked;
    form.querySelectorAll('[data-team-role]').forEach(card => { const r = t.roles[Number(card.dataset.teamRole)]; if (!r) return; r.name = card.querySelector('[name=name]').value.trim(); r.jobTitle = card.querySelector('[name=jobTitle]').value.trim(); r.provider = card.querySelector('[name=provider]').value; r.effort = teamEffortOk(r) ? card.querySelector('[name=effort]')?.value || '' : ''; });
  }
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-team]');
    if (!el) return;
    if (el.dataset.team === 'open') leaveModalForm().then(go => { if (go) teamAsk(); });  // from a Bot or group form with changes: asks first (#297)
    else if (el.dataset.team === 'again') teamAsk(state.team?.goal || '');
    else if (el.dataset.team === 'remove') { teamRead(); state.team.roles.splice(Number(el.dataset.id), 1); teamPreview(); }
  });
  // A model picked in a card can change whether its thinking level can be set, and whether every role now has one.
  document.addEventListener('change', e => { if (e.target.matches?.('[data-team-provider]') && e.target.closest('#team-make')) { teamRead(); teamPreview(); } });
  document.addEventListener('submit', async e => {
    const form = e.target;
    if (form.id !== 'team-ask' && form.id !== 'team-make') return;
    e.preventDefault(); e.stopPropagation();
    const button = form.querySelector('button.primary');
    if (button.disabled) return;
    button.disabled = true; form.dataset.busy = '1';  // closing waits while it is on its way (21b-unsaved.js)
    if (form.id === 'team-ask') {
      const goal = form.elements.goal.value.trim();
      button.textContent = '規劃中，大約半分鐘…';
      try { const d = await post('team/draft', {goal}); state.team = {team: d.team, goal: d.goal, roles: [d.coordinator, ...d.members], choices: d.choices, warnings: d.warnings, kickoff: true}; teamPreview(); }
      catch (err) { teamAsk(goal, err.message); }
      return;
    }
    teamRead();
    const t = state.team;
    try {
      const made = await post('team', {team: t.team, goal: t.goal, roles: t.roles, kickoff: t.kickoff});
      state.team = null; closeModal(); await refresh();
      state.page = 'chat'; state.groupId = made.group.id; render();
      if (t.kickoff && typeof pollGroup === 'function') pollGroup(made.group.id);
      toast(`已建立「${made.group.name}」和 ${made.bots.length} 個 Bot`);
    } catch (err) { button.disabled = false; delete form.dataset.busy; toast(err.message); }
  }, true);
