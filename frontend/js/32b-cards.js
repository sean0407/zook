
  // 剩餘額度 on the usage page: one card per account, grouped by CLI (#316, replacing #242's one card per CLI).
  // A card shows what is left; sign-in, version, abilities and removal are behind 詳細. CLIs that are not installed
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
    const wins = (s.windows || []).map(w => ({left: windowLeft(w), resetsAt: w.resetsAt, group: String(w.label || '').includes(' · ') ? String(w.label).split(' · ')[0] : ''})), empty = wins.filter(w => w.left <= 0);
    if (limitNow(s) || empty.length) {
      const last = empty.some(w => isNaN(resetTime(w.resetsAt))) ? null : empty.sort((a, b) => resetTime(b.resetsAt) - resetTime(a.resetsAt))[0];  // one without a time: nobody knows when
      return {level: 'out', reset: last ? fmtReset(last.resetsAt) : '', clock: last ? resetClock(last.resetsAt) : '', why: limitNow(s) ? limitWords(s.limitReached) : '', ...groupsOf(wins, empty[0]?.group)};
    }
    const low = wins.filter(w => w.left < 20).sort((a, b) => a.left - b.left)[0];
    return low ? {level: 'low', left: Math.round(low.left), reset: fmtReset(low.resetsAt), ...groupsOf(wins, low.group)} : {level: ''};
  }
  // An account with limits per kind of model (Antigravity: 「Claude 與 GPT 模型」, 「Gemini 模型」): which kind the figure is about,
  // and what each other kind still has, so 6% is not read as the whole account (#43④).
  function groupsOf(wins, group) {
    if (!group) return {};
    const rest = [...new Set(wins.map(w => w.group).filter(g => g && g !== group))].map(g => g + '還剩 ' + Math.round(Math.min(...wins.filter(w => w.group === g).map(w => w.left))) + '%');
    return {group, rest: rest.join('、')};
  }
  const levelMark = l => l.level === 'out' ? '・已用完' : l.level === 'low' ? '・剩不到 20%' : '';
  // The line under 模型與帳號 in the Bot form when the chosen account is used up or nearly so. It only tells; nothing is blocked.
  function quotaWarnText(choice) {
    const [p, a] = String(choice || '').split('::');
    if (p === 'auto') return '';
    const l = accountLevel(p || state.data.settings.provider || 'codex', a || '');
    const which = l.group ? `的「${l.group}」` : '', rest = l.rest ? `（${l.rest}）` : '';
    if (l.level === 'out') return `這個帳號${which}額度已用完${rest}，${l.group ? '用這類模型' : '現在'}傳訊息會失敗` + (l.reset ? '，' + l.reset : '；等額度重置或換一個帳號') + '。';
    if (l.level === 'low') return `這個帳號${which}只剩 ${l.left}% 額度${rest}，可能很快用完` + (l.reset ? '，' + l.reset : '') + '。';
    return '';
  }
  function loginButtons(p, a) {
    const acct = a ? a.id : '', signed = (a || p).status === 'logged_in';
    if (a && a.type !== 'login') return '';
    if (p.terminalLogin && (!a || p.id === 'antigravity')) return `<button class="${signed ? 'secondary' : 'primary'}" data-action="terminal-login" data-id="${esc(p.id)}" data-account="${esc(acct)}">${signed ? '重新登入' : ['gemini', 'antigravity'].includes(p.id) ? '用 Google 帳號登入' : '在終端機登入'}</button>`;
    return (p.loginMethods || []).map((m, i) => `<button class="${i === 0 && !signed ? 'primary' : 'secondary'}" data-action="account-login" data-id="${esc(p.id)}" data-account="${esc(acct)}" data-method="${esc(m.id)}" ${m.id === 'device' ? 'title="用另一台裝置（例如手機）打開登入網頁，輸入這裡顯示的代碼完成登入"' : ''}>${signed && i === 0 ? '重新登入' : esc(m.label)}</button>`).join('');
  }
  // 下一步 on a used-up card, in plain words: another signed-in account that still has room (same CLI first), and/or when this one resets.
  function outNext(p, a, lv) {
    const spare = [p, ...(state.accounts?.providers || []).filter(x => x.id !== p.id)].filter(x => x.installed).flatMap(x => [{x, b: null}, ...(x.profiles || []).map(b => ({x, b}))])
      .find(({x, b}) => (x.id !== p.id || (b ? b.id : '') !== (a ? a.id : '')) && (b || x).status === 'logged_in' && !(b ? b.type === 'key' : quotaFor(x.id)?.apiBilling) && !x.issue && (quotaFor(x.id, b ? b.id : undefined)?.quota?.windows || []).length && accountLevel(x.id, b ? b.id : '').level !== 'out');  // only one known to have room
    const other = spare ? `在 Bot 設定改用「${cliShort(spare.x)}${spare.b ? '（' + spare.b.name + '）' : ''}」` : '';
    if (lv.clock) return `下一步：${other ? other + '，或' : ''}等到 ${lv.clock} 重置後再用。`;
    return `下一步：${other ? other + '；' : ''}這家沒有說何時重置，稍後按「偵測使用量」再看${other ? '' : '，或按「＋ 帳號」加入其他帳號'}。`;
  }
  // ---- #316: one card per account, and every card has the same blocks in the same order: head, status, bars, reset times,
  // 下一步 (only when needed), 綁定 Bot, then 自動選用 and 詳細. The cards of one CLI come together under its title row.
  // The bars every account of one CLI shows, in one order: by kind of model (Antigravity), five hours before weekly.
  const slotGroup = l => l.includes(' · ') ? l.split(' · ')[0] : '', slotRank = l => l.includes('小時') ? 0 : l.includes('週') ? 1 : 2;
  function familySlots(rows) {
    const labels = [];
    for (const {p, a} of rows) {
      const q = quotaFor(p.id, a ? a.id : undefined);
      if (q?.apiBilling || (a && a.type === 'key')) continue;  // paid by use: its old figures are not shown
      for (const w of q?.quota?.windows || []) { const l = String(w.label || ''); if (l && !labels.includes(l)) labels.push(l); }
    }
    const groups = [...new Set(labels.map(slotGroup))];
    return labels.map((l, i) => ({l, i})).sort((x, y) => groups.indexOf(slotGroup(x.l)) - groups.indexOf(slotGroup(y.l)) || slotRank(x.l) - slotRank(y.l) || x.i - y.i).map(x => x.l);
  }
  // The bars of one account on its card, one per slot of its CLI; a slot it has no figure for says 不提供. A used-up weekly limit
  // stops the others of the same kind of model, as in quotaRows.
  function slotRows(slots, windows) {
    const period = l => l.split(' · ').pop(), rows = (windows || []).map(w => ({label: String(w.label || ''), left: windowLeft(w), resetsAt: w.resetsAt}));
    return slots.map(label => {
      const r = rows.find(x => x.label === label);
      if (!r) return `<div class="quota-row none"><div class="quota-label"><span>${esc(label)}</span><span><b>不提供</b></span></div><div class="quota-track left-track"></div></div>`;
      const stop = rows.find(x => x !== r && x.left <= 0 && period(x.label).includes('週') && slotGroup(x.label) === slotGroup(r.label)), blocked = !!stop && r.left > 0;
      return `<div class="quota-row ${blocked ? 'blocked' : ''}"><div class="quota-label"><span>${esc(label)}</span><span><b>${blocked ? `被${esc(period(stop.label))}額度擋住` : '剩餘 ' + r.left + '%'}</b></span></div><div class="quota-track left-track"><div class="quota-bar ${blocked ? 'off' : r.left < 20 ? 'warn' : ''}" style="width:${r.left}%"></div></div></div>`;
    }).join('');
  }
  // When each limit is full again; limits that reset at the same time share a line.
  function slotResets(slots, windows) {
    const lines = [];
    for (const label of slots) {
      const w = (windows || []).find(x => String(x.label || '') === label);
      if (!w) continue;
      const text = windowLeft(w) >= 100 ? '額度是滿的' : resetWords(w.resetsAt), same = lines.find(x => x.text === text);
      if (same) same.labels.push(label); else lines.push({labels: [label], text});
    }
    return lines.map(x => `<div><span>${esc(x.labels.join('、'))}</span><span>${esc(x.text)}</span></div>`).join('');
  }
  const issueShort = t => String(t || '').split(/[：，。]/)[0];
  // ② The one status badge: 可用, 快用完 (under 20%), 已用完 or 無法使用, with a short note after it.
  function cardStatus(p, a, lv) {
    const who = a || p, flow = a ? a.login : p.login;
    if (!a && p.install?.state === 'running') return {cls: 'off', text: '無法使用', note: '正在安裝／更新'};
    if (!p.installed) return {cls: 'off', text: '無法使用', note: '尚未安裝'};
    if (['not_logged_in', 'not_installed'].includes(who.status)) return {cls: 'off', text: '無法使用', note: flow?.state === 'running' ? '正在登入' : '尚未登入'};
    if (!a && who.status !== 'logged_in' && (state.data?.rings || []).find(x => x.id === p.id)?.signedIn === false) return {cls: 'off', text: '無法使用', note: '尚未登入'};  // the last sign-in check (#111 #158), until this page reads it again
    if (!a && p.issue) return {cls: 'off', text: '無法使用', note: issueShort(p.issue)};
    const changed = !a && (p.changed || []).length ? '部分功能暫時關閉' : '';
    if (lv.level === 'out') return {cls: 'out', text: '已用完', note: lv.why || (lv.group ? `「${lv.group}」用完了` : '')};
    if (lv.level === 'low') return {cls: 'low', text: '快用完', note: `剩 ${lv.left}%` + (lv.group ? `（${lv.group}）` : '')};
    return {cls: 'ok', text: '可用', note: changed};
  }
  // ③ and ④: the bars and the reset times, or one line saying why there are none (paid by use, no figures from this CLI, not signed
  // in, an install or sign-in in progress).
  function cardQuota(p, a, q, slots) {
    const who = a || p, flow = a ? a.login : p.login, line = t => `<p class="quota-empty">${esc(t)}</p>`;
    if (!a && p.install?.state === 'running') return {body: flowView(p.install, 'install', p.id), reset: ''};
    if (flow?.state === 'running') return {body: flowView(flow, 'login', p.id, a ? a.id : ''), reset: ''};
    const done = (!a && p.install && p.install.state !== 'running' ? flowView(p.install, 'install', p.id) : '') + (flow && flow.state !== 'running' ? flowView(flow, 'login', p.id, a ? a.id : '') : '');
    if (!p.installed) return {body: done || line('尚未安裝。'), reset: ''};
    if (['not_logged_in', 'not_installed'].includes(who.status)) {
      const buttons = loginButtons(p, a);
      return {body: done + (buttons ? `<div class="card-actions">${buttons}</div>` : line(p.loginNote || '登入後才能查看額度。')), reset: ''};
    }
    if (q?.apiBilling || who.type === 'key') return {body: done + '<div class="quota-billed"><b>依用量計費</b><small>API 金鑰沒有 5 小時、每週額度，用多少付多少。</small></div>', reset: '不適用'};  // #199
    if (!state.quota) return {body: loadingBlock('正在偵測使用量…'), reset: ''};
    if (state.quota.error) return {body: `<p class="error-text small">${esc(state.quota.error)}</p>`, reset: ''};
    if (!a && p.issue) return {body: done + line('這個登入目前不能用，沒有額度資料。'), reset: ''};
    if (q?.noQuotaApi) return {body: line('這個 CLI 不提供額度資料。'), reset: '不提供'};
    const s = q?.quota, wins = s?.windows || [];
    if (!wins.length) return {body: done + (limitNow(s) ? `<p class="error-text small">${esc(limitWords(s.limitReached))}</p>` : line(q?.quotaUnread ? '讀不到額度。' : '還沒有額度資料，按右上角「偵測使用量」讀取。')), reset: ''};
    const extra = (s.resetCredits ? `<p class="quota-coupon-line">額度重置券 ${esc(s.resetCredits)} 張（在 Codex 中使用）</p>` : '') + (s.credits && (s.credits.unlimited || (s.credits.balance && s.credits.balance !== '0')) ? `<p class="quota-extra">額外額度：${s.credits.unlimited ? '不限' : esc(s.credits.balance)}</p>` : '');
    return {body: done + slotRows(slots, wins) + extra, reset: slotResets(slots, wins)};
  }
  // ⑤ 下一步, only when the account cannot be used now.
  function cardNext(p, a, lv, st) {
    if (st.cls === 'out') return outNext(p, a, lv);
    if (st.cls !== 'off' || st.note === '正在安裝／更新' || st.note === '正在登入') return '';
    if (st.note === '尚未登入') return loginButtons(p, a) ? '下一步：按上面的按鈕登入。' : '下一步：照上面的說明登入。';
    return '下一步：按「詳細」看原因和怎麼處理。';
  }
  // The Bots that answer with this account: their own model and account, or the default model when they have none.
  // A Bot on 自動選擇 that has not been matched yet is bound to no account.
  function boundBots(p, a) {
    const dflt = state.data?.settings?.provider || 'codex', acct = a ? a.id : '';
    return (state.data?.bots || []).filter(b => (b.provider || dflt) === p.id && (b.account || '') === acct);
  }
  document.addEventListener('toggle', e => { if (e.target.dataset?.bound) (state.boundOpen ||= {})[e.target.dataset.bound] = e.target.open; }, true);
  function usageCard(r, slots, many, st) {
    const {p, a} = r, who = a || p, q = quotaFor(p.id, a ? a.id : undefined), lv = r.lv, key = r.key;
    const name = a ? a.name : p.email || '預設帳號', method = a ? (a.type === 'key' ? 'API 金鑰' : a.method || '登入帳號') : p.method || 'CLI 自己的登入';
    const sub = [method, a && a.email && a.email !== name ? a.email : ''].filter(Boolean).join(' · ');
    // ② The status badge sits beside the name, so it takes no row of its own; its short note follows the sign-in method.
    const badge = `<span class="status-badge ${st.cls}" ${st.note ? `title="${esc(st.note)}"` : ''}>${st.text}</span>`;
    const head = `<header class="uc-head"><div class="uc-title"><span class="uc-family">${esc(cliShort(p))}</span>${a ? '' : '<span class="uc-default">預設</span>'}</div><div class="uc-name-row"><strong class="uc-name" title="${esc(name)}">${esc(name)}</strong>${badge}</div><small class="uc-method" title="${esc([sub, st.note].filter(Boolean).join(' · '))}">${esc(sub)}${st.note ? `<span class="uc-note"> · ${esc(st.note)}</span>` : ''}</small></header>`;
    const quota = cardQuota(p, a, q, slots), next = cardNext(p, a, lv, st);
    const bots = boundBots(p, a), bound = bots.length ? `<details class="uc-bots" data-bound="${esc(key)}" ${state.boundOpen?.[key] ? 'open' : ''}><summary>綁定 Bot：${bots.length} 個</summary><div class="uc-bot-list">${bots.map(b => `<button class="link" data-action="select-bot" data-id="${esc(b.id)}">${esc(b.name)}</button>`).join('')}</div></details>` : '<p class="uc-bots none">綁定 Bot：0 個</p>';
    const off = q?.autoOn === undefined || q.autoBilled, autoLabel = q?.autoBilled || (a && a.type === 'key') ? 'API 計費，不會自動選用' : '自動選用';
    const auto = `<label class="auto-pick small-switch">${toggle(`${a ? `data-auto-account="${esc(a.id)}"` : `data-auto-model="${esc(p.id)}"`} ${off ? 'disabled' : ''}`, !!q?.autoOn && !q.autoBilled, '自動選用')}<span ${lv.level === 'out' && q?.autoOn ? 'title="這個帳號已用完，重置前自動選用會先跳過它"' : ''}>${autoLabel}</span></label>`;
    return `<article class="left-card account-card usage-card uc-${st.cls}" ${many ? 'draggable="true" title="拖動可以調整同一家帳號的順序" ' : ''}data-row-key="${esc(key)}"><div class="uc-main">${head}<div class="uc-quota">${quota.body}</div><div class="uc-reset"><span class="uc-label">重置時間</span>${quota.reset && quota.reset.startsWith('<') ? quota.reset : `<div><span>${esc(quota.reset || '—')}</span></div>`}</div>${next ? `<p class="uc-next">${esc(next)}</p>` : ''}${bound}</div><footer class="account-foot">${auto}<div class="card-actions"><button class="secondary small-btn" data-action="account-detail" data-id="${esc(p.id)}" data-account="${esc(a ? a.id : '')}">詳細</button></div></footer></article>`;
  }
  // One CLI: a title row with ＋ 帳號 across the whole grid, then a card per account. The wrapper takes no room in the grid.
  function familyGroup(f, statuses) {
    const p = f.p, many = f.rows.length > 1, slots = familySlots(f.rows);
    const add = p.installed && (p.canAddLogin || p.canAddKey) ? `<button class="secondary small-btn" data-action="profile-add" data-id="${esc(p.id)}">＋ 帳號</button>` : '';
    const name = cliShort(p), handle = `<span class="drag-handle" role="button" tabindex="0" data-family-handle="${esc(f.key)}" aria-label="調整 ${esc(name)} 的順序：拖動，或按上下鍵移動" title="拖動或按上下鍵調整順序"><svg viewBox="0 0 10 16" width="10" height="16" aria-hidden="true"><circle cx="2.5" cy="3" r="1.4"/><circle cx="7.5" cy="3" r="1.4"/><circle cx="2.5" cy="8" r="1.4"/><circle cx="7.5" cy="8" r="1.4"/><circle cx="2.5" cy="13" r="1.4"/><circle cx="7.5" cy="13" r="1.4"/></svg></span>`;
    return `<div class="usage-family" data-card-key="${esc(f.key)}"><div class="usage-family-head" draggable="true" title="拖動可以調整各家的順序">${handle}<h3>${esc(cliShort(p))}${p.custom ? ' <span class="pill">自訂</span>' : ''}</h3><span class="muted small">${f.rows.length} 個帳號</span><span class="family-tools">${p.version?.updateAvailable ? `<span class="new-version" title="有新版 ${esc(p.version.latest)}">有新版</span>` : ''}${add}</span></div>${f.rows.map(r => usageCard(r, slots, many, statuses.get(r.key))).join('')}</div>`;
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
  // #317: the arrow keys on a CLI's handle move it one place up (-1) or down (1); null when it is already first or last.
  function usageOrderStep(fams, key, dir) {
    const at = fams.findIndex(f => f.key === key), to = at + dir;
    if (at < 0 || to < 0 || to >= fams.length) return null;
    return usageOrderAfterMove(fams, 'card', key, fams[to].key, dir > 0);
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
    const fams = usageFamilies(shown), statuses = new Map();
    for (const f of fams) for (const r of f.rows) { r.lv = r.p.installed ? accountLevel(r.p.id, r.a ? r.a.id : '') : {level: ''}; statuses.set(r.key, cardStatus(r.p, r.a, r.lv)); }
    return `<section class="usage-block"><div class="overview-head"><h2>剩餘額度</h2>${shown.length ? sort : ''}</div>${shown.length ? `<div class="usage-grid">${fams.map(f => familyGroup(f, statuses)).join('')}</div>` : '<div class="blank">還沒有安裝任何模型，按右上角「＋ 新增模型」。</div>'}${waiting ? `<p class="muted small">另有 ${waiting} 個已加入但尚未安裝的模型，可在「＋ 新增模型」安裝。</p>` : ''}</section>`;
  }
  document.addEventListener('change', e => {
    if (e.target.dataset?.cardSort === undefined) return;
    saveCardOrder({usageCardSort: e.target.value === 'auto' ? 'auto' : 'custom'});
    toast(e.target.value === 'auto' ? '剩餘額度依剩下多少自動排序' : '剩餘額度照你拖動的順序');
  });
  // Dragging: a card goes before or after another card of the same CLI; a CLI's title row (its handle) moves all its cards before or
  // after another CLI, and the line above or below the whole CLI shows where it lands (#317). Either way the order becomes 自訂.
  let draggingUsage = null;
  const clearCardMarks = () => document.querySelectorAll('.usage-family:is(.drop-before, .drop-after), .usage-card:is(.drop-before, .drop-after)').forEach(el => el.classList.remove('drop-before', 'drop-after'));
  const cardDrop = e => {
    const fam = draggingUsage && e.target.closest?.('[data-card-key]');
    if (!fam) return null;
    if (draggingUsage.kind === 'row') {
      const el = e.target.closest('[data-row-key]');
      if (!el || el.dataset.rowKey === draggingUsage.key || fam.dataset.cardKey !== draggingUsage.family) return null;
      const r = el.getBoundingClientRect();
      return {el, key: el.dataset.rowKey, after: e.clientX > r.left + r.width / 2};
    }
    if (fam.dataset.cardKey === draggingUsage.key) return null;
    const r = fam.getBoundingClientRect();
    return {el: fam, key: fam.dataset.cardKey, after: e.clientY > r.top + r.height / 2};
  };
  document.addEventListener('dragstart', e => {
    const el = e.target.closest?.('[draggable="true"]'), fam = el?.closest('[data-card-key]');
    if (!fam || e.target.closest('button, input, a, .dd, label, summary')) return;
    const row = el.dataset.rowKey !== undefined;
    draggingUsage = {kind: row ? 'row' : 'card', key: row ? el.dataset.rowKey : fam.dataset.cardKey, family: fam.dataset.cardKey};
    e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', draggingUsage.key);
    const faded = row ? el : fam;
    requestAnimationFrame(() => faded.classList.add('dragging'));
  });
  document.addEventListener('dragend', () => { draggingUsage = null; clearCardMarks(); document.querySelectorAll('.usage-card.dragging, .usage-family.dragging').forEach(el => el.classList.remove('dragging')); });
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
  const saveMoved = keys => {
    if (!keys) return false;
    if (state.data?.settings?.usageCardSort === 'auto') toast('已改成自訂順序');
    saveCardOrder({usageCardOrder: keys, usageCardSort: 'custom'});
    return true;
  };
  const moveUsage = kind => (moving, target, after) => saveMoved(moving ? usageOrderAfterMove(shownFamilies(), kind, moving, target, after) : null);
  window.moveUsageCard = moveUsage('card');
  window.moveUsageRow = moveUsage('row');
  // The keyboard: up and down on a CLI's handle move the whole CLI; the handle keeps the focus and says where it went.
  document.addEventListener('keydown', e => {
    const key = e.target.dataset?.familyHandle;
    if (key === undefined || !['ArrowUp', 'ArrowDown'].includes(e.key) || e.altKey || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    const fams = shownFamilies(), dir = e.key === 'ArrowUp' ? -1 : 1;
    if (!saveMoved(usageOrderStep(fams, key, dir))) return;
    const handle = [...document.querySelectorAll('[data-family-handle]')].find(x => x.dataset.familyHandle === key), place = fams.findIndex(f => f.key === key) + dir + 1;
    handle?.focus(); handle?.scrollIntoView?.({block: 'nearest'});
    toast(`${handle?.closest('.usage-family-head')?.querySelector('h3')?.textContent || ''} 移到第 ${place} 個`);
  });
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
    modal(`${cliShort(p)}${a ? '（' + a.name + '）' : ''}`, `<div class="modal-body account-detail"><p class="muted small">登入由各家官方 CLI 完成，Zook 不讀取帳密。</p>${!a && p.issue ? `<p class="detail-issue">${esc(p.issue)}</p>` : ''}${!a && (p.changed || []).length ? `<p class="detail-issue">這個版本有變動，暫時關閉：${esc(p.changed.join('、'))}</p>` : ''}<div class="detail-rows">${rows.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('')}</div>${loginButtons(p, a) ? `<div class="card-actions">${loginButtons(p, a)}</div>` : ''}<h3 class="modal-sub">版本</h3><div class="detail-version">${version}</div>${install ? `<div class="card-actions">${install}</div>` : ''}<h3 class="modal-sub">能力</h3>${abilities}${notes}${manage ? `<div class="detail-manage">${manage}</div>` : ''}</div>`);
  }
  async function saveAutoAccount(input) {
    const id = input.dataset.autoAccount;
    try { state.data.settings = await post('settings', {autoAccounts: {[id]: input.checked}}, 'PATCH'); toast(input.checked ? '自動選擇可以用這個帳號' : '自動選擇不會用這個帳號'); refreshQuota(); }
    catch (error) { input.checked = !input.checked; toast(error.message); }
  }
  document.addEventListener('change', e => { if (e.target.dataset?.autoAccount) saveAutoAccount(e.target); });
