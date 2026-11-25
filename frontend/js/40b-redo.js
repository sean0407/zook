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
