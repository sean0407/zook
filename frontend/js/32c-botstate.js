  // What keeps a Bot's model from answering now (#80 #158 #166②): 額度用完, 尚未登入 or a sign-in problem the CLI reported. It goes by
  // what this window already has: the live figures once the Bot form or the usage page read them, else the sidebar rings that come
  // with every state. An extra account is only known from the live figures. Nothing is blocked; the words only say what will happen.
  function modelTrouble(provider, account) {
    if (!provider || provider === 'auto') return null;
    const q = state.quota ? quotaFor(provider, account || undefined) : null;
    if (q) {
      if (!account && q.issue) return {kind: 'issue', tag: '無法使用', why: q.issue};
      if (q.status === 'not_logged_in') return {kind: 'login', tag: '尚未登入'};
      const l = accountLevel(provider, account || '');
      return l.level === 'out' && !l.group && provider !== 'antigravity' ? {kind: 'out', tag: '額度用完', reset: l.reset} : null;  // Antigravity: limits per kind of model, and which one the Bot uses is not known here
    }
    if (account) return null;
    const r = (state.data?.rings || []).find(x => x.id === provider);
    if (!r) return null;
    if (r.signedIn === false) return {kind: 'login', tag: '尚未登入'};  // only a check that said so: a CLI never checked yet is not called signed out
    if (r.issue) return {kind: 'issue', tag: '無法使用', why: r.issue};
    return r.left != null && r.left <= 0 && provider !== 'antigravity' ? {kind: 'out', tag: '額度用完'} : null;
  }
  const troubleMark = t => t ? '・' + (t.kind === 'out' ? '已用完' : t.tag) : '';
  const botProvider = b => b?.provider || state.data.settings.provider || 'codex';
  const botTrouble = b => b && botProvider(b) !== 'auto' ? modelTrouble(botProvider(b), b.account || '') : null;
  // The first backup that can answer: the Bot's own choice (an empty list is 不自動換), else the order in 設定; never the same CLI.
  function usableBackup(provider, fallbacks) {
    const chain = Array.isArray(fallbacks) ? fallbacks : state.data.settings.fallbacks || [];
    return chain.find(x => x && x !== provider && x !== 'auto' && !modelTrouble(x, '')) || '';
  }
  // One sentence: why the model cannot answer, then what happens when a message is sent.
  // next: the model a reply really tries next, as the Mac works it out (bot.nextBackup, #132); undefined in an unsaved form.
  function troubleText(t, provider, fallbacks, next) {
    if (!t) return '';
    const why = t.kind === 'out' ? '這個帳號的額度已用完' + (t.reset ? '（' + t.reset + '）' : '') : t.kind === 'login' ? providerShort(provider) + ' 尚未登入' : String(t.why || '').replace(/[。．.]+$/, '');
    if (next === undefined) return why + '。傳訊息時會照備用順序改用其他訂閱帳號，都不能用時會失敗；回覆裡會註明。';
    return why + (next ? `。傳訊息時會先試 ${next}（只用訂閱帳號），回覆裡會註明。` : '，現在傳訊息會失敗。可以在「備用模型」選一家，不能用時自動改用。');
  }
  const troubleBadge = b => { const t = botTrouble(b); return t ? ` <span class="trouble-badge" title="${esc(troubleText(t, botProvider(b), b.fallbacks, b.nextBackup ?? ''))}">${esc(t.tag)}</span>` : ''; };
  const troubleBanner = b => { const t = botTrouble(b); return t ? `<div class="trouble-banner" role="status">${esc(troubleText(t, botProvider(b), b.fallbacks, b.nextBackup ?? ''))}</div>` : ''; };
  // The Bot form: 模型與帳號 and 備用模型 as chosen in the form, before it is saved.
  function formTroubleText(form, choice) {
    const [p, a] = String(choice || '').split('::'), id = p || state.data.settings.provider || 'codex';
    const t = id === 'auto' ? null : modelTrouble(id, a || '');
    if (!t) return '';
    const fb = form.querySelector('input[name="fallbackChoice"]')?.value || '';
    const b = state.data.bots.find(x => x.id === form.dataset.id), saved = b && (b.provider || '') === (p || '') && (b.account || '') === (a || '') && fb === (!Array.isArray(b.fallbacks) ? '' : b.fallbacks.length ? b.fallbacks[0] : '__none');
    return troubleText(t, id, fb === '' ? undefined : fb === '__none' ? [] : [fb], saved ? b.nextBackup ?? '' : undefined);  // as saved: what the Mac works out
  }
  // A schedule sent to a Bot that cannot answer says so under 對象, as the Bot form does (#166②).
  function scheduleTargetWarn(form) {
    const warn = form?.querySelector('[data-target-warn]');
    if (!warn) return;
    const [kind, id] = String(form.elements.target?.value || '').split(':'), b = kind === 'bot' ? state.data.bots.find(x => x.id === id) : null;
    const t = botTrouble(b), said = t ? troubleText(t, botProvider(b), b.fallbacks, b.nextBackup ?? '') : '';
    warn.textContent = said; warn.hidden = !said;
  }
  const scheduleTroubleLine = x => { const b = state.data.bots.find(y => y.id === x.botId), t = botTrouble(b); return t ? `<p class="small quota-warn sched-trouble">${esc(troubleText(t, botProvider(b), b.fallbacks, b.nextBackup ?? ''))}</p>` : ''; };
