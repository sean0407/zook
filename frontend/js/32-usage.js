
  // What is left of each model's limits: small rings at the bottom of the sidebar, and the same bars at the top of the usage page.
  const ringLevel = left => left == null ? 'none' : left < 20 ? 'low' : '';
  function ringSvg(left) {
    const r = 9, c = 2 * Math.PI * r, part = left == null ? 0 : Math.max(0, Math.min(100, left)) / 100 * c;
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><circle class="ring-track" cx="12" cy="12" r="${r}"></circle>${left == null ? '' : `<circle class="ring-fill" cx="12" cy="12" r="${r}" stroke-dasharray="${part.toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 12 12)"></circle>`}<text class="ring-num" x="12" y="15" text-anchor="middle">${left == null ? '–' : Math.round(left)}</text></svg>`;
  }
  const ringText = x => x.left == null ? `${x.name}：沒有額度資料` : `${x.name}：剩餘 ${Math.round(x.left)}%`;
  function leftBars(x) {
    if (!x.windows.length) return '<p class="quota-empty">這個模型不提供額度資料。</p>';
    return x.windows.map(w => `<div class="quota-row"><div class="quota-label"><span>${esc(w.label)}</span><span><b>剩餘 ${Math.round(w.left)}%</b></span></div><div class="quota-track left-track"><div class="quota-bar ${w.left < 20 ? 'bad' : ''}" style="width:${w.left}%"></div></div><small class="quota-reset">${esc(w.left >= 100 ? '' : fmtReset(w.resetsAt))}</small></div>`).join('');
  }
  function usageRings() {
    const rings = state.data.rings || [];
    if (!rings.length) return '';
    const open = rings.find(x => x.id === state.ringOpen);
    return `<div class="side-rings">${open ? `<div class="ring-card" role="dialog" aria-label="${esc(open.name)} 剩餘額度"><strong>${esc(open.name)}</strong>${leftBars(open)}<button class="text-btn" data-action="page" data-id="usage">查看用量</button></div>` : ''}${rings.map(x => `<button class="ring ${ringLevel(x.left)} ${state.ringOpen === x.id ? 'active' : ''}" data-ring="${esc(x.id)}" title="${esc(ringText(x))}" aria-label="${esc(ringText(x))}" aria-expanded="${state.ringOpen === x.id}">${ringSvg(x.left)}<span>${esc(x.name)}</span></button>`).join('')}</div>`;
  }
  // The top of the usage page: every model's limits as bars, with the same wording as the rings.
  function leftSection() {
    const rings = state.data.rings || [];
    if (!rings.length) return '';
    return `<section class="usage-block"><h2>剩餘額度</h2><div class="left-grid">${rings.map(x => `<article class="left-card"><h3>${esc(x.name)}</h3>${leftBars(x)}</article>`).join('')}</div></section>`;
  }
  // Sections of the usage page that stay folded until asked for; the choice survives a redraw.
  if (!state.folds) state.folds = {};
  const fold = (key, title, html, openByDefault) => `<details class="usage-fold" data-fold="${esc(key)}" ${(state.folds[key] ?? !!openByDefault) ? 'open' : ''}><summary>${esc(title)}</summary>${html}</details>`;
  document.addEventListener('toggle', e => { if (e.target.dataset?.fold) state.folds[e.target.dataset.fold] = e.target.open; }, true);

  document.addEventListener('click', e => {
    const ring = e.target.closest('[data-ring]');
    if (ring) { state.ringOpen = state.ringOpen === ring.dataset.ring ? null : ring.dataset.ring; render(true); return; }
    if (state.ringOpen && (!e.target.closest('.ring-card') || e.target.closest('[data-action]'))) { state.ringOpen = null; if (!e.target.closest('[data-action]')) render(true); }
  });

