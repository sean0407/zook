
  // What is left of each model's limits: small rings at the bottom of the sidebar, and the same bars at the top of the usage page.
  // Two rings per model: the outer one is the five-hour limit, the inner one the weekly limit.
  const ringLevel = x => !x.known ? 'off' : x.left == null ? 'none' : x.left < 20 ? 'low' : '';
  const ringTone = left => left < 20 ? 'low' : left < 50 ? 'mid' : '';
  function ringArc(r, left) {
    const c = 2 * Math.PI * r, part = left == null ? 0 : Math.max(0, Math.min(100, left)) / 100 * c;
    return `<circle class="ring-track ${left == null ? 'empty' : ''}" cx="20" cy="20" r="${r}"></circle>${left == null || part < 0.5 ? '' : `<circle class="ring-fill ${ringTone(left)}" cx="20" cy="20" r="${r}" stroke-dasharray="${part.toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 20 20)"></circle>`}`;
  }
  // A model with both limits gets two rings; one with a single limit gets one; one without any gets a faint dotted ring.
  function ringSvg(x) {
    const both = x.fiveHour != null && x.week != null, only = x.fiveHour ?? x.week;
    return `<svg viewBox="0 0 40 40" aria-hidden="true">${both ? ringArc(17.5, x.fiveHour) + ringArc(13, x.week) : ringArc(17.5, only)}<text class="ring-num" x="20" y="23.2" text-anchor="middle">${x.left == null ? '–' : Math.round(x.left)}</text></svg>`;
  }
  const ringPart = (label, v) => `${label}${v == null ? '沒有資料' : '剩餘 ' + Math.round(v) + '%'}`;
  const ringText = x => !x.known ? `${x.name}：尚未登入` : x.left == null ? `${x.name}：沒有額度資料` : `${x.name}：${[x.fiveHour != null ? ringPart('5 小時', x.fiveHour) : '', x.week != null ? ringPart('每週', x.week) : ''].filter(Boolean).join('，')}`;
  function leftBars(x) {
    if (!x.known) return '<p class="quota-empty">登入後才能查看額度。</p>';
    if (!x.windows.length) return '<p class="quota-empty">這個模型不提供額度資料。</p>';
    return x.windows.map(w => `<div class="quota-row"><div class="quota-label"><span>${esc(w.label)}</span><span><b>剩餘 ${Math.round(w.left)}%</b></span></div><div class="quota-track left-track"><div class="quota-bar ${w.left < 20 ? 'bad' : ''}" style="width:${w.left}%"></div></div><small class="quota-reset">${esc(w.left >= 100 ? '' : fmtReset(w.resetsAt))}</small></div>`).join('');
  }
  // Its own block in the lower right corner of the window, with every model Zook knows.
  function usageDock() {
    const rings = state.data?.rings || [];
    if (!rings.length) return '';
    const open = rings.find(x => x.id === state.ringOpen);
    return `<div class="usage-dock ${state.page === 'chat' ? 'over-chat' : ''}" aria-label="各模型剩餘額度">${open ? `<div class="ring-card" role="dialog" aria-label="${esc(open.name)} 剩餘額度"><strong>${esc(open.name)}</strong>${leftBars(open)}${open.fiveHour != null && open.week != null ? '<small class="muted">外圈是 5 小時額度，內圈是每週額度。</small>' : ''}<button class="text-btn" data-action="page" data-id="usage">查看用量</button></div>` : ''}${rings.map(x => `<button class="ring ${ringLevel(x)} ${state.ringOpen === x.id ? 'active' : ''}" data-ring="${esc(x.id)}" title="${esc(ringText(x))}" aria-label="${esc(ringText(x))}" aria-expanded="${state.ringOpen === x.id}">${ringSvg(x)}<span>${esc(x.name)}</span></button>`).join('')}</div>`;
  }
  // The top of the usage page: every model's limits as bars, with the same wording as the rings.
  function leftSection() {
    const rings = (state.data.rings || []).filter(x => x.known);
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

  // The overview: what the replies would have cost at API prices, a line per model over time, and where the tokens went.
  const USAGE_SPANS = [{id: '7', name: '近 7 天'}, {id: '30', name: '近 30 天'}, {id: '90', name: '近 90 天'}];
  const MODEL_COLOR = {claude: '#d97757', codex: '#a78bfa', grok: '#444', antigravity: '#4285f4', gemini: '#1aa260'};
  const modelColor = id => MODEL_COLOR[id] || '#999';
  const usd = v => 'US$' + (v >= 100 ? v.toFixed(0) : v >= 0.01 || v === 0 ? v.toFixed(2) : v.toFixed(4));
  const fmtWan = n => n == null ? '—' : n >= 1e8 ? (n / 1e8).toFixed(2) + ' 億' : n >= 1e4 ? (n / 1e4).toFixed(2) + ' 萬' : Number(n).toLocaleString();
  function costChart(o) {
    const W = 640, H = 220, L = 54, R = 10, T = 12, B = 26, n = o.days.length, max = Math.max(0.01, ...o.providers.flatMap(p => p.daily));
    const top = max <= 0.05 ? Math.ceil(max * 100) / 100 : max <= 1 ? Math.ceil(max * 10) / 10 : Math.ceil(max);
    const x = i => L + (n === 1 ? 0 : i * (W - L - R) / (n - 1)), y = v => T + (H - T - B) * (1 - v / top);
    const grid = [0, 1, 2, 3].map(k => { const v = top * k / 3; return `<line class="chart-grid" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"></line><text class="chart-tick" x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${usd(v)}</text>`; }).join('');
    const marks = [...new Set([0, Math.round((n - 1) / 3), Math.round((n - 1) * 2 / 3), n - 1])].map(i => `<text class="chart-tick" x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}">${esc(o.days[i].slice(5).replace('-', '/'))}</text>`).join('');
    const lines = o.providers.filter(p => p.kind).map(p => `<polyline class="chart-line" stroke="${modelColor(p.id)}" points="${p.daily.map((v, i) => x(i).toFixed(1) + ',' + y(v).toFixed(1)).join(' ')}"><title>${esc(p.name)}</title></polyline>`).join('');
    return `<svg class="cost-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="每日費用">${grid}${marks}${lines}</svg>`;
  }
  function overviewSection() {
    const o = state.overview, pick = `<div class="overview-span">${dropdown('overviewDays', String(state.overviewDays || 30), USAGE_SPANS, 'data-overview-days')}</div>`;
    if (!o) return `<section class="usage-block"><h2>用量總覽</h2>${loadingBlock('正在整理用量…')}</section>`;
    if (o.error) return `<section class="usage-block"><h2>用量總覽</h2><div class="blank error-text">${esc(o.error)}</div></section>`;
    const t = o.totals, cells = [['不含快取讀取的 Token', fmtWan(t.withoutCacheRead)], ['含快取讀取的 Token', fmtWan(t.withCacheRead)], ['快取輸入', fmtWan(t.cachedInput)], ['未快取輸入', fmtWan(t.freshInput)], ['快取寫入', fmtWan(t.cacheWrite)], ['輸出', fmtWan(t.output)], ['我送出的訊息', fmtN(t.sent)], ['完成的回覆', fmtN(t.replies)]];
    const rows = o.providers.map(p => `<div class="overview-model"><span class="dot" style="background:${modelColor(p.id)}"></span><div><strong>${esc(p.name)}</strong><small>${p.kind ? `${p.share == null ? '' : '占 ' + p.share + '% · '}` : ''}${fmtWan(p.tokens)} 個 Token${p.unpriced ? ` · ${p.unpriced} 則無價格（${esc(p.unpricedModels.join('、'))}）` : ''}</small></div><b title="${p.kind === 'reported' ? '這家 CLI 自己回報的金額' : p.kind === 'estimated' ? '依價格表計算' : ''}">${p.kind ? usd(p.cost) : '無價格'}</b></div>`).join('');
    return `<section class="usage-block usage-overview"><div class="overview-head"><h2>用量總覽</h2>${pick}</div><div class="overview-top"><div class="overview-left"><div class="overview-cost">${usd(o.cost)}</div><p class="muted small">${fmtN(o.replies)} 則回覆 · 依 API 價格估算</p><p class="muted small">訂閱帳號不會被收這筆錢；這是同樣用量走 API 的價錢。${o.unpriced ? `有 ${o.unpriced} 則回覆的模型不在價格表裡，沒有算進去。` : ''}</p>${rows || '<p class="quota-empty">這段期間沒有用量。</p>'}</div><div class="overview-right"><div class="overview-chart-title">每日費用</div>${o.replies ? costChart(o) : '<p class="quota-empty">這段期間沒有用量。</p>'}</div></div><div class="overview-totals">${cells.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('')}</div><p class="muted small">價格表日期 ${esc(o.priceDate)}（${esc(o.priceSource)}）。「—」表示 CLI 沒有提供這個數字。</p></section>`;
  }
  async function loadOverview() {
    try { state.overview = await api('usage/overview?days=' + (state.overviewDays || 30)); } catch (e) { state.overview = {error: e.message}; }
    if (state.page === 'usage') { const y = $('.page')?.scrollTop; render(true); if (y && $('.page')) $('.page').scrollTop = y; }
  }
  document.addEventListener('change', e => {
    if (e.target.dataset.overviewDays === undefined) return;
    state.overviewDays = Number(e.target.value) || 30; loadOverview();
  });
