
  // 剩餘額度 on the usage page: one card per CLI, with a row for each of its accounts (#242).
  // A row shows what is left; sign-in, version, abilities and removal are behind 詳細. CLIs that are not installed
  // stay out of the grid and are installed from ＋ 新增模型, except while an install is running or has just failed.
  const ACCOUNT_BADGE = {logged_in: ['ok', '已登入'], not_logged_in: ['warn', '尚未登入'], installed: ['', '已安裝'], unknown: ['', '狀態不明'], not_installed: ['warn', '未安裝']};
  function flowView(l, kind, id, account = '') {
    if (!l) return '';
    if (l.state === 'running') {
      if (kind === 'install') return `<div class="login-flow"><strong>正在安裝／更新…</strong>${l.log?.length ? `<pre class="flow-log">${esc(l.log.slice(-6).join('\n'))}</pre>` : ''}<button class="link" data-action="install-cancel" data-id="${esc(id)}">取消</button></div>`;
      return `<div class="login-flow"><strong>${l.deviceCode ? '請在登入頁輸入這組代碼' : '已在瀏覽器開啟登入頁'}</strong>${l.deviceCode ? `<div class="device-code">${esc(l.deviceCode)}</div>` : ''}${l.url ? `<p class="muted">沒有自動開啟？<a href="${esc(l.url)}" rel="noopener noreferrer">點這裡開啟登入頁</a></p>` : '<p class="muted">正在等待 CLI 提供登入網址…</p>'}${l.needsCode ? `<form class="code-form" id="account-code-form" data-id="${esc(id)}" data-account="${esc(account)}"><input name="code" placeholder="如果頁面顯示授權碼，貼在這裡" aria-label="授權碼" autocomplete="off"><button class="primary">送出</button></form>` : ''}<button class="link" data-action="account-cancel" data-id="${esc(id)}" data-account="${esc(account)}">取消登入</button></div>`;
    }
    if (l.state === 'succeeded') return `<div class="login-flow done">${kind === 'install' ? '安裝／更新完成。' : '登入完成。'}</div>`;
    return `<div class="login-flow error-text">${esc(l.error || (kind === 'install' ? '安裝沒有完成。' : '登入沒有完成。'))}${kind === 'install' && l.log?.length ? `<pre class="flow-log">${esc(l.log.slice(-6).join('\n'))}</pre>` : ''}</div>`;
  }
  // Percent left in one limit; a limit whose reset time has passed is full again (the same rule as the rings).
  function windowLeft(w) {
    const r = w.resetsAt, t = r == null ? NaN : new Date(typeof r === 'number' ? (r > 1e12 ? r : r * 1000) : r).getTime();
    if (!isNaN(t) && t <= Date.now()) return 100;
    return Math.round(Math.max(0, Math.min(100, 100 - (Number(w.usedPercent) || 0))) * 10) / 10;
  }
  // When a limit is full again, in words. A CLI that gives no time (Grok) gets 未提供重置時間 instead of a blank.
  const resetWords = r => fmtReset(r) || '未提供重置時間';
  // The day and hour a limit is full again (11/25 週二 18:00), for 下一步; empty when the CLI gives no time.
  function resetClock(r) {
    const t = r == null ? NaN : new Date(typeof r === 'number' ? (r > 1e12 ? r : r * 1000) : r).getTime();
    return isNaN(t) ? '' : new Date(t).toLocaleString('zh-TW', {month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit'});
  }
  // The bars of one account. A used-up limit stops the account whatever the other limits of the same model show (an Antigravity
  // account has limits per model, 'Gemini · 每週'), so those are greyed and say which limit stops them instead of a green 100%.
  // Only a used-up weekly limit stops the others (as the sidebar rings show it); a five-hour one that is used up leaves the weekly figure as it is.
  function quotaRows(windows) {
    const group = l => l.includes(' · ') ? l.split(' · ')[0] : '', period = l => l.split(' · ').pop();
    const rows = (windows || []).map(w => ({label: String(w.label || ''), left: windowLeft(w), resetsAt: w.resetsAt}));
    return rows.map(r => {
      const stop = rows.find(x => x !== r && x.left <= 0 && period(x.label).includes('週') && group(x.label) === group(r.label)), blocked = !!stop && r.left > 0;
      const note = blocked ? `被${period(stop.label)}額度擋住，${stop.resetsAt == null ? '這家沒有說何時重置' : resetWords(stop.resetsAt)}` : r.left >= 100 ? '' : resetWords(r.resetsAt);
      return `<div class="quota-row ${blocked ? 'blocked' : ''}"><div class="quota-label"><span>${esc(r.label)}</span><span><b>${blocked ? '暫時不能用' : '剩餘 ' + r.left + '%'}</b></span></div><div class="quota-track left-track"><div class="quota-bar ${blocked ? 'off' : r.left < 20 ? 'warn' : ''}" style="width:${r.left}%"></div></div><small class="quota-reset">${esc(note)}</small></div>`;
    }).join('');
  }
  const cliShort = p => String(p.name).split('（')[0];
  // What a CLI reports when a limit is reached, in plain words; an unknown one still says the account cannot be used now.
  const LIMIT_WORDS = {workspace_owner_credits_depleted: '工作區的點數用完了，這個帳號暫時不能用（要由工作區擁有者加值）', usage_limit_reached: '額度用完了，等重置後才能再用', rate_limit_reached: '額度用完了，等重置後才能再用'};
  const limitNow = s => !!s?.limitReached && Date.now() - Date.parse(s.updatedAt) < 30 * 60e3;  // same half hour as the backend's limit_reached_now
  const limitWords = code => LIMIT_WORDS[code] || (/credit/i.test(code) ? '點數用完了，這個帳號暫時不能用' : '已達使用上限，這個帳號暫時不能用');
  // How much one account has left, for the cards and the Bot form: 'out' (cannot be used now) wins over what the bars still show,
  // 'low' is under 20%. reset is when it can be used again, in words; it is empty when the CLI does not say.
  const resetTime = r => r == null ? NaN : new Date(typeof r === 'number' ? (r > 1e12 ? r : r * 1000) : r).getTime();
  function accountLevel(provider, account) {
    const q = quotaFor(provider, account || undefined), s = q?.quota;
    if (!s || q.apiBilling || q.noQuotaApi) return {level: ''};
    const wins = (s.windows || []).map(w => ({left: windowLeft(w), resetsAt: w.resetsAt})), empty = wins.filter(w => w.left <= 0);
    if (limitNow(s) || empty.length) {
      const last = empty.some(w => isNaN(resetTime(w.resetsAt))) ? null : empty.sort((a, b) => resetTime(b.resetsAt) - resetTime(a.resetsAt))[0];  // one without a time: nobody knows when
      return {level: 'out', reset: last ? fmtReset(last.resetsAt) : '', clock: last ? resetClock(last.resetsAt) : '', why: limitNow(s) ? limitWords(s.limitReached) : ''};
    }
    const low = wins.filter(w => w.left < 20).sort((a, b) => a.left - b.left)[0];
    return low ? {level: 'low', left: Math.round(low.left), reset: fmtReset(low.resetsAt)} : {level: ''};
  }
  const levelMark = l => l.level === 'out' ? '・已用完' : l.level === 'low' ? '・剩不到 20%' : '';
  // The line under 模型與帳號 in the Bot form when the chosen account is used up or nearly so. It only tells; nothing is blocked.
  function quotaWarnText(choice) {
    const [p, a] = String(choice || '').split('::');
    if (p === 'auto') return '';
    const l = accountLevel(p || state.data.settings.provider || 'codex', a || '');
    if (l.level === 'out') return '這個帳號的額度已用完，現在傳訊息會失敗' + (l.reset ? '，' + l.reset : '；等額度重置或換一個帳號') + '。';
    if (l.level === 'low') return `這個帳號只剩 ${l.left}% 額度，可能很快用完` + (l.reset ? '，' + l.reset : '') + '。';
    return '';
  }
  function loginButtons(p, a) {
    const acct = a ? a.id : '', signed = (a || p).status === 'logged_in';
    if (a && a.type !== 'login') return '';
    if (p.terminalLogin && (!a || p.id === 'antigravity')) return `<button class="${signed ? 'secondary' : 'primary'}" data-action="terminal-login" data-id="${esc(p.id)}" data-account="${esc(acct)}">${signed ? '重新登入' : ['gemini', 'antigravity'].includes(p.id) ? '用 Google 帳號登入' : '在終端機登入'}</button>`;
    return (p.loginMethods || []).map((m, i) => `<button class="${i === 0 && !signed ? 'primary' : 'secondary'}" data-action="account-login" data-id="${esc(p.id)}" data-account="${esc(acct)}" data-method="${esc(m.id)}" ${m.id === 'device' ? 'title="用另一台裝置（例如手機）打開登入網頁，輸入這裡顯示的代碼完成登入"' : ''}>${signed && i === 0 ? '重新登入' : esc(m.label)}</button>`).join('');
  }
  // Where the bars go: progress of an install or sign-in, a sign-in button, a line saying why there are no bars, or the bars.
  function cardBody(p, a, q) {
    const who = a || p, flow = a ? a.login : p.login;
    if (!a && p.install?.state === 'running') return flowView(p.install, 'install', p.id);
    if (flow?.state === 'running') return flowView(flow, 'login', p.id, a ? a.id : '');
    const done = (!a && p.install && p.install.state !== 'running' ? flowView(p.install, 'install', p.id) : '') + (flow && flow.state !== 'running' ? flowView(flow, 'login', p.id, a ? a.id : '') : '');
    if (!p.installed) return done || '<p class="quota-empty">尚未安裝。</p>';
    if (['not_logged_in', 'not_installed'].includes(who.status)) {
      const buttons = loginButtons(p, a);
      return done + (buttons ? `<div class="card-login"><p class="quota-empty">尚未登入</p><div class="card-actions">${buttons}</div></div>` : `<p class="quota-empty">${esc(p.loginNote || '尚未登入。')}</p>`);
    }
    if (q?.apiBilling || who.type === 'key') return done + '<div class="quota-billed"><b>依用量計費</b><small>API 金鑰帳號沒有 5 小時、每週額度，用多少付多少。</small></div>';  // #199: never a subscription's figures
    if (!state.quota) return loadingBlock('正在偵測使用量…');
    if (state.quota.error) return `<p class="error-text small">${esc(state.quota.error)}</p>`;
    const s = q?.quota;
    if (!a && p.issue) return done;  // the line above already says why this sign-in cannot be used and what to do
    if (q?.noQuotaApi) return '<p class="quota-empty">這個 CLI 不提供額度資料。</p>';
    if (q?.quotaUnread && !(s?.windows || []).length) return '<p class="quota-empty">讀不到額度</p>';
    if (limitNow(s) && !(s.windows || []).length) return `<p class="error-text small">${esc(limitWords(s.limitReached))}</p>`;
    if (!s || !(s.windows || []).length) return '<p class="quota-empty">還沒有額度資料，按右上角「偵測使用量」讀取。</p>';
    const bars = quotaRows(s.windows);
    const extra = (s.resetCredits ? `<p class="quota-coupon-line">額度重置券 ${s.resetCredits} 張（在 Codex 中使用）</p>` : '') + (s.credits && (s.credits.unlimited || (s.credits.balance && s.credits.balance !== '0')) ? `<p class="quota-extra">額外額度：${s.credits.unlimited ? '不限' : esc(s.credits.balance)}</p>` : '') + (limitNow(s) ? `<p class="error-text small">${esc(limitWords(s.limitReached))}</p>` : '');
    return done + bars + extra;
  }
  // 下一步 on a used-up card, in plain words: another signed-in account that still has room (same CLI first), and/or when this one resets.
  function outNext(p, a, lv) {
    const spare = [p, ...(state.accounts?.providers || []).filter(x => x.id !== p.id)].filter(x => x.installed).flatMap(x => [{x, b: null}, ...(x.profiles || []).map(b => ({x, b}))])
      .find(({x, b}) => (x.id !== p.id || (b ? b.id : '') !== (a ? a.id : '')) && (b || x).status === 'logged_in' && !(b ? b.type === 'key' : quotaFor(x.id)?.apiBilling) && !x.issue && (quotaFor(x.id, b ? b.id : undefined)?.quota?.windows || []).length && accountLevel(x.id, b ? b.id : '').level !== 'out');  // only one known to have room
    const other = spare ? `在 Bot 設定改用「${cliShort(spare.x)}${spare.b ? '（' + spare.b.name + '）' : ''}」` : '';
    if (lv.clock) return `下一步：${other ? other + '，或' : ''}等到 ${lv.clock} 重置後再用。`;
    return `下一步：${other ? other + '；' : ''}這家沒有說何時重置，稍後按「偵測使用量」再看${other ? '' : '，或按「＋ 帳號」加入其他帳號'}。`;
  }
  // One account inside its family card: what is left, 自動選用 and 詳細. A row is dragged inside its card when the card has several.
  function accountRow(p, a, many) {
    const q = quotaFor(p.id, a ? a.id : undefined), lv = p.installed ? accountLevel(p.id, a ? a.id : '') : {level: ''};
    const levelLine = lv.level === 'out' ? `<div class="quota-state out"><span class="out-badge">已用完</span><small>${esc(lv.reset || '未提供重置時間')}</small><p class="quota-next">${esc(outNext(p, a, lv))}</p></div>` : lv.level === 'low' ? `<p class="quota-state low">快用完・剩不到 20%</p>` : '';
    const name = a ? a.name : (p.profiles || []).length ? '預設帳號' : '', line = (a ? [a.email || a.method] : [p.email || p.method || (name ? '' : p.vendor)]).filter(Boolean).join(' · ');
    const auto = q?.autoOn === undefined ? '' : `<label class="auto-pick small-switch">${toggle(`${a ? `data-auto-account="${esc(a.id)}"` : `data-auto-model="${esc(p.id)}"`} ${q.autoBilled ? 'disabled' : ''}`, q.autoOn, '自動選用')}<span ${lv.level === 'out' && q.autoOn ? 'title="這個帳號已用完，重置前自動選用會先跳過它"' : ''}>${q.autoBilled ? 'API 計費，不會自動選用' : '自動選用'}</span></label>`;
    const keys = (p.profiles || []).filter(x => x.type === 'key').length;
    const issue = a ? '' : p.issue;  // a sign-in problem of the CLI's own account; extra accounts (API keys) are not affected
    const warn = issue || (!a && (p.changed || []).length) ? `<p class="error-text small">${esc(issue || '這個版本有變動，暫時關閉：' + p.changed.join('、'))}${issue && keys ? `（已加入的 ${keys} 把 API 金鑰不受影響，可直接在 Bot 設定選用。）` : ''}</p>` : '';
    const head = name || line ? `<div class="acct-row-head"><strong>${esc(name || line)}</strong>${name && line ? `<span title="${esc(line)}">${esc(line)}</span>` : ''}</div>` : '';
    return `<section class="acct-row ${lv.level ? 'quota-' + lv.level : ''}" ${many ? 'draggable="true" ' : ''}data-row-key="${esc(cardKey(p, a))}"${many ? ' title="拖動可以調整這張卡裡的順序"' : ''}>${head}<div class="account-body">${warn}${levelLine}${cardBody(p, a, q)}</div><footer class="account-foot">${auto}<div class="card-actions"><button class="secondary small-btn" data-action="account-detail" data-id="${esc(p.id)}" data-account="${esc(a ? a.id : '')}">詳細</button></div></footer></section>`;
  }
  // One card per CLI: its name, ＋ 帳號 and a row for each of its accounts (the CLI's own sign-in and those added).
  function familyCard(f) {
    const p = f.p, many = f.rows.length > 1;
    const add = p.installed && (p.canAddLogin || p.canAddKey) ? `<button class="secondary small-btn" data-action="profile-add" data-id="${esc(p.id)}">＋ 帳號</button>` : '';
    return `<article class="left-card account-card family-card" draggable="true" data-card-key="${esc(f.key)}" title="拖動可以調整順序"><header class="account-head"><div class="account-title"><h3>${esc(cliShort(p))}${p.custom ? ' <span class="pill">自訂</span>' : ''}</h3>${many ? `<span>${f.rows.length} 個帳號</span>` : ''}</div><div class="family-tools">${p.version?.updateAvailable ? `<span class="new-version" title="有新版 ${esc(p.version.latest)}">有新版</span>` : ''}${add}</div></header><div class="family-rows">${f.rows.map(r => accountRow(r.p, r.a, many)).join('')}</div></article>`;
  }
  // The order: dragged by the user (自訂), or most left first (自動); kept in the settings so the phone lists them the same way.
  // The setting stays a list of account keys ('codex', 'codex::<id>'), as before the families: a family comes where its first
  // account comes, and its accounts keep their order inside it.
  const cardKey = (p, a) => a ? p.id + '::' + a.id : p.id;
  const CARD_SORTS = [{id: 'custom', name: '自訂（可拖動）'}, {id: 'auto', name: '自動（剩最多的在前）'}];
  // 自動: [rank, percent] like the Mac's usage_card_focus. 0 has figures, 1 none (API keys too), 2 used up, 3 not signed in. The percent is
  // that of the limit worth watching now: the five-hour one when there is one, otherwise the weekly one.
  function cardFocus(p, a) {
    if ((a || p).status !== 'logged_in') return [3, 0];
    const q = quotaFor(p.id, a ? a.id : undefined), s = q?.quota, rows = (s?.windows || []).filter(w => typeof w.usedPercent === 'number').map(w => ({label: String(w.label || ''), left: windowLeft(w)}));  // a limit without a figure is skipped, as on the Mac
    if (q?.apiBilling || (a && a.type === 'key')) return [1, 0];  // paid by use: a subscription's old figures say nothing about it
    if (limitNow(s) || rows.some(r => r.left <= 0)) return [2, 0];
    if (!rows.length) return [1, 0];
    const focus = rows.find(r => r.label.includes('小時')) || rows.find(r => r.label.includes('週')) || rows[0];
    return [0, focus.left];
  }
  function orderedCards(shown) {
    const cards = shown.flatMap(p => [{p, a: null}, ...(p.profiles || []).map(a => ({p, a}))]).map((c, i) => ({...c, key: cardKey(c.p, c.a), i}));
    const saved = Array.isArray(state.data?.settings?.usageCardOrder) ? state.data.settings.usageCardOrder : [];
    const place = k => { const n = saved.indexOf(k); return n < 0 ? saved.length : n; };
    cards.sort((x, y) => place(x.key) - place(y.key) || x.i - y.i);  // new accounts after the saved ones; removed ones are simply gone
    if (state.data?.settings?.usageCardSort !== 'auto') return cards;
    cards.forEach((c, n) => { c.n = n; c.f = cardFocus(c.p, c.a); });
    return cards.sort((x, y) => x.f[0] - y.f[0] || y.f[1] - x.f[1] || x.n - y.n);
  }
  // The accounts in order, grouped by CLI: in 自動 the family whose best account has most left comes first.
  function usageFamilies(shown) {
    const fams = [];
    for (const c of orderedCards(shown)) {
      let f = fams.find(x => x.key === c.p.id);
      if (!f) fams.push(f = {key: c.p.id, p: c.p, rows: []});
      f.rows.push(c);
    }
    return fams;
  }
  // The saved order after a card (kind 'card') or an account inside its card (kind 'row') is put before or after another;
  // null when the move is not allowed (an account into another card).
  function usageOrderAfterMove(fams, kind, moving, target, after) {
    fams = fams.map(f => ({key: f.key, rows: [...f.rows]}));
    if (kind === 'card') {
      const m = fams.find(f => f.key === moving), rest = fams.filter(f => f !== m), at = rest.findIndex(f => f.key === target);
      if (!m || at < 0) return null;
      rest.splice(after ? at + 1 : at, 0, m); fams = rest;
    } else {
      const f = fams.find(x => x.rows.includes(moving));
      if (!f || !f.rows.includes(target) || moving === target) return null;
      f.rows = f.rows.filter(k => k !== moving); const at = f.rows.indexOf(target);
      f.rows.splice(after ? at + 1 : at, 0, moving);
    }
    return fams.flatMap(f => f.rows);
  }
  async function saveCardOrder(change) {
    const before = {...state.data.settings};
    Object.assign(state.data.settings, change); render(true);
    try { state.data.settings = await post('settings', change, 'PATCH'); }
    catch (err) { state.data.settings = before; render(true); toast(err.message); }
  }
  function accountCards() {
    const list = state.accounts?.providers;
    if (!list) return `<section class="usage-block"><h2>剩餘額度</h2>${loadingBlock('正在向各家 CLI 確認登入狀態，第一次打開約需 10 秒…')}</section>`;
    const shown = list.filter(p => p.installed || p.install?.state === 'running');  // a failed install is retried from ＋ 新增模型
    const waiting = list.length - shown.length;
    const sort = `<div class="card-sort"><span class="usage-auto-label">排序</span>${dropdown('usageCardSort', state.data?.settings?.usageCardSort === 'auto' ? 'auto' : 'custom', CARD_SORTS, 'data-card-sort')}</div>`;
    const help = '<p class="muted small usage-help">同一家的帳號放在同一張卡。「5 小時」「每週」是訂閱方案的兩種用量上限，用完要等重置；任一種用完，這個帳號就暫時不能用。API 金鑰依用量計費，沒有這兩種上限。「自動選用」打開時，Bot 選「自動」就可能用到這個帳號。</p>';
    return `<section class="usage-block"><div class="overview-head"><h2>剩餘額度</h2>${shown.length ? sort : ''}</div>${shown.length ? help : ''}${shown.length ? `<div class="left-grid account-grid family-grid">${usageFamilies(shown).map(familyCard).join('')}</div>` : '<div class="blank">還沒有安裝任何模型，按右上角「＋ 新增模型」。</div>'}${waiting ? `<p class="muted small">另有 ${waiting} 個已加入但尚未安裝的模型，可在「＋ 新增模型」安裝。</p>` : ''}</section>`;
  }
  document.addEventListener('change', e => {
    if (e.target.dataset?.cardSort === undefined) return;
    saveCardOrder({usageCardSort: e.target.value === 'auto' ? 'auto' : 'custom'});
    toast(e.target.value === 'auto' ? '剩餘額度依剩下多少自動排序' : '剩餘額度照你拖動的順序');
  });
  // Dragging: a card goes before or after the card it is dropped on; an account row before or after another row of the same card.
  // Either way the order becomes 自訂.
  let draggingUsage = null;
  const DROP_MARKS = '.drop-before, .drop-after';
  const clearCardMarks = () => document.querySelectorAll(`.account-card:is(${DROP_MARKS}), .acct-row:is(${DROP_MARKS})`).forEach(el => el.classList.remove('drop-before', 'drop-after'));
  const cardDrop = e => {
    if (!draggingUsage) return null;
    const el = draggingUsage.kind === 'row' ? e.target.closest?.('[data-row-key]') : e.target.closest?.('[data-card-key]');
    if (!el) return null;
    const key = draggingUsage.kind === 'row' ? el.dataset.rowKey : el.dataset.cardKey;
    if (key === draggingUsage.key || (draggingUsage.kind === 'row' && el.closest('[data-card-key]')?.dataset.cardKey !== draggingUsage.family)) return null;
    const r = el.getBoundingClientRect();
    return {el, key, after: draggingUsage.kind === 'row' ? e.clientY > r.top + r.height / 2 : e.clientX > r.left + r.width / 2};
  };
  document.addEventListener('dragstart', e => {
    const el = e.target.closest?.('[draggable="true"][data-row-key], [data-card-key]');
    if (!el || e.target.closest('button, input, a, .dd, label')) return;
    const row = el.dataset.rowKey !== undefined;
    draggingUsage = {kind: row ? 'row' : 'card', key: row ? el.dataset.rowKey : el.dataset.cardKey, family: el.closest('[data-card-key]')?.dataset.cardKey};
    e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', draggingUsage.key);
    requestAnimationFrame(() => el.classList.add('dragging'));
  });
  document.addEventListener('dragend', () => { draggingUsage = null; clearCardMarks(); document.querySelectorAll('.account-card.dragging, .acct-row.dragging').forEach(el => el.classList.remove('dragging')); });
  document.addEventListener('dragover', e => {
    const t = cardDrop(e);
    if (!t) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    const cls = t.after ? 'drop-after' : 'drop-before';
    if (!t.el.classList.contains(cls)) { clearCardMarks(); t.el.classList.add(cls); }
  });
  document.addEventListener('drop', e => {
    const t = cardDrop(e), moving = draggingUsage;
    clearCardMarks();
    if (!t) return;
    e.preventDefault(); draggingUsage = null;
    (moving.kind === 'row' ? window.moveUsageRow : window.moveUsageCard)(moving.key, t.key, t.after);
  });
  // Also what the drop above does; usable without a mouse (and by the browser tests).
  const shownFamilies = () => [...document.querySelectorAll('[data-card-key]')].map(el => ({key: el.dataset.cardKey, rows: [...el.querySelectorAll('[data-row-key]')].map(r => r.dataset.rowKey)}));
  const moveUsage = kind => (moving, target, after) => {
    const keys = moving ? usageOrderAfterMove(shownFamilies(), kind, moving, target, after) : null;
    if (keys) saveCardOrder({usageCardOrder: keys, usageCardSort: 'custom'});
  };
  window.moveUsageCard = moveUsage('card');
  window.moveUsageRow = moveUsage('row');
  // 詳細: everything about one account that is not about what is left.
  function accountDetail(id, account) {
    const p = (state.accounts?.providers || []).find(x => x.id === id);
    if (!p) return;
    const a = account ? (p.profiles || []).find(x => x.id === account) : null, who = a || p;
    if (account && !a) return;
    const [cls, label] = !a && p.issue ? ['warn', '無法使用'] : ACCOUNT_BADGE[who.status] || ACCOUNT_BADGE.unknown;
    const rows = [['登入狀態', `<span class="pill ${cls}">${label}</span>`], ['方式', esc(a?.type === 'key' ? 'API 金鑰' : who.method || '—')], ['方案', esc((who.plan || '').toUpperCase() || '—')], ['帳號', esc(who.email || '—')], ...(who.workspace ? [['工作區', esc(who.workspace)]] : [])];
    const v = p.version, upToDate = v && v.current && v.latest && !v.updateAvailable;
    const version = `${v?.current ? '版本 ' + esc(v.current) : '版本未知'}${v?.updateAvailable ? ` <span class="pill warn">有新版 ${esc(v.latest)}</span>` : upToDate ? ' <span class="pill ok">已是最新版</span>' : v?.error ? ` <span class="muted">${esc(v.error)}</span>` : ''}`;
    const install = p.canInstall && !(upToDate && p.installed) ? `<button class="${v?.updateAvailable ? 'primary' : 'secondary'}" data-action="provider-install" data-id="${esc(p.id)}" data-command="${esc(p.installed && p.canUpdate ? '' : p.installCommand)}">${v?.updateAvailable ? `更新到 ${esc(v.latest)}` : p.canUpdate ? '檢查並更新' : '重新安裝'}</button>` : '';
    const abilities = (p.abilities || []).length ? `<div class="ability-chips">${p.abilities.map(x => `<span class="${x.state === 'broken' ? 'off' : ''}" title="${x.state === 'broken' ? '這個版本暫時無法使用' : '可以使用'}">${x.state === 'broken' ? '✕' : '✓'} ${esc(x.name)}</span>`).join('')}</div>` : '<p class="muted small">沒有能力資料。</p>';
    const notes = [!p.tools ? '這個 CLI 只能純對話，不能使用 Zook 的工具。' : '', !(p.loginMethods || []).length && !p.terminalLogin && p.loginNote ? p.loginNote : ''].filter(Boolean).map(n => `<p class="muted small">${esc(n)}</p>`).join('');
    const manage = a ? `<button class="link danger" data-action="profile-delete" data-id="${esc(p.id)}" data-account="${esc(a.id)}" data-name="${esc(a.name)}">移除帳號</button>` : `${p.custom ? `<button class="secondary" data-action="provider-edit" data-id="${esc(p.id)}">編輯設定</button>` : ''}${p.status === 'logged_in' && p.canLogout ? `<button class="link danger" data-action="account-logout" data-id="${esc(p.id)}">登出</button>` : ''}${p.removable ? `<button class="link danger" data-action="provider-remove" data-id="${esc(p.id)}">從 Zook 移除</button>` : ''}`;
    modal(`${cliShort(p)}${a ? '（' + a.name + '）' : ''}`, `<div class="modal-body account-detail"><p class="muted small">登入由各家官方 CLI 完成，Zook 不讀取帳密。</p><div class="detail-rows">${rows.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('')}</div>${loginButtons(p, a) ? `<div class="card-actions">${loginButtons(p, a)}</div>` : ''}<h3 class="modal-sub">版本</h3><div class="detail-version">${version}</div>${install ? `<div class="card-actions">${install}</div>` : ''}<h3 class="modal-sub">能力</h3>${abilities}${notes}${manage ? `<div class="detail-manage">${manage}</div>` : ''}</div>`);
  }
  async function saveAutoAccount(input) {
    const id = input.dataset.autoAccount;
    try { state.data.settings = await post('settings', {autoAccounts: {[id]: input.checked}}, 'PATCH'); toast(input.checked ? '自動選擇可以用這個帳號' : '自動選擇不會用這個帳號'); refreshQuota(); }
    catch (error) { input.checked = !input.checked; toast(error.message); }
  }
  document.addEventListener('change', e => { if (e.target.dataset?.autoAccount) saveAutoAccount(e.target); });
