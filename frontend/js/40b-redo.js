  // 換模型重答 (#143): which model each choice is, which one this Bot uses now, and which are used up (those go last and are not
  // picked for you). The line under 模型 names the model when Zook knows it; the reply then says 原本：X／這次：Y.
  function redoModelOptions(b) {
    const current = b.provider === 'auto' ? '' : (b.provider || state.data.settings.provider || 'codex');
    const list = (state.providers || []).filter(p => p.installed !== false).map(p => {
      const out = accountLevel(p.id, p.id === current ? (b.account || '') : '').level === 'out';
      const hint = [p.id === current ? '這個 Bot 目前用的' : '', out ? '額度已用完，這次可能會失敗' : ''].filter(Boolean).join('・');
      return {id: p.id, name: cliShort(p) + (out ? '（已用完）' : ''), hint, current: p.id === current, out};
    });
    return [...list.filter(o => !o.out), ...list.filter(o => o.out)];
  }
  function redoModelLine(id) {
    const st = state.data.settings, p = (state.providers || []).find(x => x.id === id), name = p ? cliShort(p) : id;
    const model = id === (st.provider || 'codex') && st.model ? st.model : '';
    return model ? `用 ${name} 的 ${model} 回答` : `用 ${name} 預設的型號回答（由 ${name} 決定）`;
  }
  document.addEventListener('change', e => {
    if (e.target.name !== 'provider' || !e.target.closest?.('#redo-model-form')) return;
    const line = e.target.closest('#redo-model-form').querySelector('[data-redo-model]');
    if (line) line.textContent = redoModelLine(e.target.value);
  });
  // #305: a reply answered again keeps the answers before it (m.versions, oldest first). ‹ › switch which one is shown; the newest
  // is what the conversation goes on from. A reply without versions (an older conversation) shows as it always did.
  function versionShown(m) {
    const all = Array.isArray(m?.versions) ? m.versions : [], at = (state.versionAt || {})[m?.id];
    return Number.isInteger(at) && at >= 0 && at < all.length && all[at] && typeof all[at] === 'object' ? Object.assign({}, all[at], {_of: m}) : m;
  }
  function versionBar(m) {
    const top = m._of || m, all = Array.isArray(top.versions) ? top.versions : [];
    if (!all.length || top.role === 'user') return '';
    const n = all.length + 1, i = m._of ? state.versionAt[top.id] : all.length, who = String(m.who || '');
    const step = (d, label, off) => `<button type="button" class="icon-btn version-step" data-action="reply-version" data-id="${esc(top.id)}" data-step="${d}" aria-label="${label}" ${off ? 'disabled' : ''}>${d < 0 ? '‹' : '›'}</button>`;
    return `<div class="reply-versions" role="group" aria-label="這個問題的回答版本">${step(-1, '上一版', i === 0)}<span>第 ${i + 1}／${n} 版${who ? ' · ' + esc(who) : ''}</span>${step(1, '下一版', i === n - 1)}</div>`;
  }
  // #265: a question sent with 先規劃 says so on its bubble.
  const planTag = m => m?.role === 'user' && m.plan ? '<div class="plan-tag" title="這則訊息勾了「先規劃」：Bot 只提出計畫、不動手">先規劃</div>' : '';
  // #77④: a date in a notice with its weekday, 12/1（週二）.
  const dayWeek = d => `${d.getMonth() + 1}/${d.getDate()}（週${'日一二三四五六'[d.getDay()]}）`;
