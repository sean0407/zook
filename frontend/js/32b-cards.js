
  // 剩餘額度 on the usage page: one card per account, every card the same size, the accounts of one CLI side by side.
  // The card shows what is left; sign-in, version, abilities and removal are behind 詳細. CLIs that are not installed
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
      const last = empty.filter(w => !isNaN(resetTime(w.resetsAt))).sort((a, b) => resetTime(b.resetsAt) - resetTime(a.resetsAt))[0];
      return {level: 'out', reset: last ? fmtReset(last.resetsAt) : '', why: limitNow(s) ? limitWords(s.limitReached) : ''};
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
    if (!a && p.terminalLogin) return `<button class="${signed ? 'secondary' : 'primary'}" data-action="terminal-login" data-id="${esc(p.id)}">${signed ? '重新登入' : ['gemini', 'antigravity'].includes(p.id) ? '用 Google 帳號登入' : '在終端機登入'}</button>`;
    return (p.loginMethods || []).map((m, i) => `<button class="${i === 0 && !signed ? 'primary' : 'secondary'}" data-action="account-login" data-id="${esc(p.id)}" data-account="${esc(acct)}" data-method="${esc(m.id)}">${signed && i === 0 ? '重新登入' : esc(m.label)}</button>`).join('');
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
    if (!state.quota) return loadingBlock('正在偵測使用量…');
    if (state.quota.error) return `<p class="error-text small">${esc(state.quota.error)}</p>`;
    const s = q?.quota;
    if (q?.apiBilling || who.type === 'key') return '<p class="quota-empty">使用 API 計費，費用依用量計算。</p>';
    if (q?.noQuotaApi) return '<p class="quota-empty">不提供額度資料</p>';
    if (q?.quotaUnread && !(s?.windows || []).length) return '<p class="quota-empty">讀不到額度</p>';
    if (limitNow(s) && !(s.windows || []).length) return `<p class="error-text small">${esc(limitWords(s.limitReached))}</p>`;
    if (!s || !(s.windows || []).length) return '<p class="quota-empty">還沒有額度資料，按右上角「偵測使用量」讀取。</p>';
    const bars = s.windows.map(w => { const left = windowLeft(w); return `<div class="quota-row"><div class="quota-label"><span>${esc(w.label)}</span><span><b>剩餘 ${left}%</b></span></div><div class="quota-track left-track"><div class="quota-bar ${left < 20 ? 'warn' : ''}" style="width:${left}%"></div></div><small class="quota-reset">${esc(left >= 100 ? '' : fmtReset(w.resetsAt))}</small></div>`; }).join('');
    const extra = (s.resetCredits ? `<p class="quota-coupon-line">額度重置券 ${s.resetCredits} 張（在 Codex 中使用）</p>` : '') + (s.credits && (s.credits.unlimited || (s.credits.balance && s.credits.balance !== '0')) ? `<p class="quota-extra">額外額度：${s.credits.unlimited ? '不限' : esc(s.credits.balance)}</p>` : '') + (limitNow(s) ? `<p class="error-text small">${esc(limitWords(s.limitReached))}</p>` : '');
    return done + bars + extra;
  }
  function accountCard(p, a) {
    const q = quotaFor(p.id, a ? a.id : undefined), who = a || p, lv = p.installed ? accountLevel(p.id, a ? a.id : '') : {level: ''};
    const levelLine = lv.level === 'out' ? `<p class="quota-state out">已用完・暫時不能用${lv.reset ? '<small>' + esc(lv.reset) + '</small>' : ''}</p>` : lv.level === 'low' ? `<p class="quota-state low">快用完・剩不到 20%</p>` : '';
    const line = a ? [a.name, a.email].filter(Boolean).join(' · ') : [(p.profiles || []).length ? '預設帳號' : '', p.email || p.method].filter(Boolean).join(' · ') || p.vendor || '';
    const auto = q?.autoOn === undefined ? '' : `<label class="auto-pick small-switch">${toggle(`${a ? `data-auto-account="${esc(a.id)}"` : `data-auto-model="${esc(p.id)}"`} ${q.autoBilled ? 'disabled' : ''}`, q.autoOn, '自動選用')}<span>${q.autoBilled ? 'API 計費，不會自動選用' : lv.level === 'out' ? '自動選用・現在會被跳過' : '自動選用・用完時會被跳過'}</span></label>`;
    const add = !a && p.installed && (p.canAddLogin || p.canAddKey) ? `<button class="secondary small-btn" data-action="profile-add" data-id="${esc(p.id)}">＋ 帳號</button>` : '';
    const warn = p.issue || (p.changed || []).length ? `<p class="error-text small">${esc(p.issue || '這個版本有變動，暫時關閉：' + p.changed.join('、'))}</p>` : '';
    return `<article class="left-card account-card ${lv.level ? 'quota-' + lv.level : ''}"><header class="account-head"><div class="account-title"><h3>${esc(cliShort(p))}${p.custom ? ' <span class="pill">自訂</span>' : ''}</h3><span title="${esc(line)}">${esc(line)}</span></div>${p.version?.updateAvailable ? `<span class="new-version" title="有新版 ${esc(p.version.latest)}">有新版</span>` : ''}</header><div class="account-body">${warn}${levelLine}${cardBody(p, a, q)}</div><footer class="account-foot">${auto}<div class="card-actions">${add}<button class="secondary small-btn" data-action="account-detail" data-id="${esc(p.id)}" data-account="${esc(a ? a.id : '')}">詳細</button></div></footer></article>`;
  }
  function accountCards() {
    const list = state.accounts?.providers;
    if (!list) return `<section class="usage-block"><h2>剩餘額度</h2>${loadingBlock('正在讀取登入狀態…')}</section>`;
    const shown = list.filter(p => p.installed || p.install?.state === 'running');  // a failed install is retried from ＋ 新增模型
    const waiting = list.length - shown.length;
    return `<section class="usage-block"><h2>剩餘額度</h2>${shown.length ? `<div class="left-grid account-grid">${shown.map(p => accountCard(p) + (p.profiles || []).map(a => accountCard(p, a)).join('')).join('')}</div>` : '<div class="blank">還沒有安裝任何模型，按右上角「＋ 新增模型」。</div>'}${waiting ? `<p class="muted small">另有 ${waiting} 個已加入但尚未安裝的模型，可在「＋ 新增模型」安裝。</p>` : ''}</section>`;
  }
  // 詳細: everything about one account that is not about what is left.
  function accountDetail(id, account) {
    const p = (state.accounts?.providers || []).find(x => x.id === id);
    if (!p) return;
    const a = account ? (p.profiles || []).find(x => x.id === account) : null, who = a || p;
    if (account && !a) return;
    const [cls, label] = p.issue ? ['warn', '無法使用'] : ACCOUNT_BADGE[who.status] || ACCOUNT_BADGE.unknown;
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
