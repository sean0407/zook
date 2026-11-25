  // Group discussions: host, discussion mode, turn limit, conclusion cards, cross-checks and shared files.
  // #106: what each way does, in plain words; 主持人分工 (one pass, in the conversation) and 自動 (a task board, several rounds) say how they differ.
  const GROUP_MODE_OPTIONS = [{id: 'free', name: '自由', hint: '跟問題有關的成員回覆，彼此可以 @ 接話；有主持人時由他帶討論和收尾'}, {id: 'turns', name: '輪流', hint: '每位成員依序各講一次，後面的人看得到前面說的'}, {id: 'debate', name: '辯論', hint: '成員分正反兩方，各講兩輪互相反駁，最後裁定哪邊站得住'}, {id: 'split', name: '主持人分工', hint: '一輪做完：主持人在對話裡分好工，成員同時各做一部分，主持人核對後合成一份答案'}, {id: 'compare', name: '比較', hint: '每位成員各自回答同一題、互相看不到，最後列出異同和最值得採用的'}];
  if (!state.groupMode) state.groupMode = {};
  if (!state.groupFiles) state.groupFiles = {};
  const groupHostId = g => 'hostId' in g ? g.hostId : (groupMembers(g).find(b => b.isAdmin)?.id || '');
  const autoReady = g => !!groupHostId(g) && groupMembers(g).length >= 2;  // 自動 needs a host and two members (#218)
  const currentGroupMode = g => { const mode = state.groupMode[g.id] || g.mode || 'free'; return mode === 'auto' && (!taskEngineOn() || !autoReady(g)) ? 'free' : mode; };
  const hostOptions = ids => [{id: '', name: '不設主持人'}, ...ids.map(id => state.data.bots.find(b => b.id === id)).filter(Boolean).map(b => ({id: b.id, name: b.name}))];
  function groupSettingRows(g, chosen) {
    const host = g.id ? groupHostId(g) : '', limit = g.turnLimit || 4;
    return `<div class="setting-list in-form"><div data-host-field>${settingRow('主持人', '負責開場分派、收斂討論和總結', dropdown('hostId', host, hostOptions([...chosen])))}</div>${settingRow('討論方式', '送出時也能在輸入框旁，只對這一則訊息改用別的方式', dropdown('mode', g.mode === 'auto' && !taskEngineOn() ? 'free' : g.mode || 'free', groupModeOptions()))}${settingRow('回合上限', '要回答的成員都回一次算 1 回合；自動轉交和追問也算在內，到了就先停下（「自動」做到目標達成為止）', dropdown('turnLimit', String(limit), [4, 5, 8, 12, 16].map(n => ({id: String(n), name: n + ' 回合'}))))}</div><p class="small error-text" data-group-problem role="alert" hidden></p><p class="muted small" data-group-hint hidden></p>`;
  }
  function syncGroupHost(form) {
    const ids = new FormData(form).getAll('botIds'), slot = form.querySelector('[data-host-field]'), now = form.elements.hostId.value;
    slot.innerHTML = settingRow('主持人', '負責開場分派、收斂討論和總結', dropdown('hostId', ids.includes(now) ? now : '', hostOptions(ids)));
  }
  // #96③: with many Bots the member list has a search box; the list itself does not scroll inside the window.
  function filterGroupMembers(input) {
    const q = input.value.trim().toLowerCase(), box = input.closest('form').querySelector('.member-pick');
    let shown = 0;
    box.querySelectorAll('.member-switch').forEach(row => { row.hidden = !!q && !row.dataset.find.includes(q); shown += !row.hidden; });
    box.querySelector('[data-member-none]').hidden = shown > 0;
  }
  document.addEventListener('keydown', e => { if (e.key === 'Enter' && 'memberSearch' in (e.target.dataset || {})) e.preventDefault(); });  // Enter does not create the group
  // What the form shows under the settings: why 自動 cannot be saved yet, and a hint when every member is the same vendor (#218).
  const botFamily = b => { const p = b.provider || state.data.settings.provider || ''; return p === 'auto' ? '' : (state.providers || []).find(x => x.id === p)?.kind || p; };
  function groupFormNote(form) {
    const ids = new FormData(form).getAll('botIds'), mode = form.elements.mode?.value, host = form.elements.hostId?.value;
    const members = ids.map(id => state.data.bots.find(b => b.id === id)).filter(Boolean);
    const problem = mode !== 'auto' ? '' : !host ? '「自動」要由主持人拆工作、派給成員：請在「主持人」選一位成員，或改用其他討論方式。' : members.length < 2 ? '「自動」至少要 2 位成員，請再選一位。' : '';
    const families = members.map(botFamily), one = members.length >= 2 && families.every(f => f && f === families[0]);
    const el = form.querySelector('[data-group-problem]'), hint = form.querySelector('[data-group-hint]');
    if (el) { el.textContent = problem; el.hidden = !problem; }
    const kept = groupKeepsAuto(form) ? '這個群組設定為「自動」，但任務引擎已關閉，所以暫時用「自由」討論；儲存不會改掉，到「設定」打開任務引擎就會恢復。' : '';
    const words = [kept, one ? `成員都是 ${providerShort(families[0])}，沒有跨家驗收：結果要你自己看，或加一位別家的 Bot。` : ''].filter(Boolean).join(' ');
    if (hint) { hint.textContent = words; hint.hidden = !words; }
    return !problem;
  }
  // #223②: a group saved as 自動 while the task engine is off shows 自由; left on 自由 (and still with a host and two members), saving keeps 自動.
  function groupKeepsAuto(form) {
    const g = form.dataset.id && (state.data.groups || []).find(x => x.id === form.dataset.id), d = new FormData(form);
    return !!g && g.mode === 'auto' && !taskEngineOn() && (d.get('mode') || 'free') === 'free' && !!d.get('hostId') && d.getAll('botIds').filter(id => state.data.bots.some(b => b.id === id)).length >= 2;
  }
  const groupModeControl = g => `<div class="effort-pick group-mode" title="討論方式">${dropdown('groupMode', currentGroupMode(g), groupModeOptions().filter(o => o.id !== 'auto' || autoReady(g)))}</div>`;

  // 預計用量: updated while typing, and never uses a model.
  function groupEstimateLine(g) {
    if (g.status === 'running') return '<div class="group-estimate" id="group-estimate"></div>';  // 插話 is not a new round
    const key = g.id + currentGroupMode(g) + ':' + (g.messages || []).length;
    if (state.groupEstimate?.key !== key) setTimeout(updateGroupEstimate, 0);
    return `<div class="group-estimate" id="group-estimate">${esc(state.groupEstimate?.key === key ? state.groupEstimate.text : '')}</div>`;
  }
  async function updateGroupEstimate() {
    const g = activeGroup();
    if (!g || g.status === 'running') return;
    const key = g.id + currentGroupMode(g) + ':' + (g.messages || []).length;
    try {
      const e = await post('groups/' + encodeURIComponent(g.id) + '/estimate', {content: $('#chat-input')?.value || '', mode: currentGroupMode(g)});
      const fallback = currentGroupMode(g) === 'auto' && e.upTo ? `預計至少 ${e.replies} 次回覆：主持人規劃、每位成員做事各算一次，驗收和重做會再多幾次`  // #223①: 自動 has no upper bound
        : `預計${e.upTo ? '最多 ' : ' '}${e.replies} 次回覆${e.most ? `（主持人退回修正時最多 ${e.most} 次）` : ''}`;
      const text = e.text || fallback;  // in rounds, worded by the Mac (#174); the token figure meant nothing to people and looked alarming
      state.groupEstimate = {key, text};
      const el = $('#group-estimate');
      if (el && activeGroup()?.id === g.id) el.textContent = text;
    } catch (_) {}
  }
  function scheduleGroupEstimate() { clearTimeout(scheduleGroupEstimate.timer); scheduleGroupEstimate.timer = setTimeout(updateGroupEstimate, 400); }

  function groupRunBar(g) {
    if (g.status === 'running') return '';
    if (g.paused) return `<div class="group-bar"><span>這次詢問已達 ${esc(String(g.turnLimit || 4))} 回合上限，討論還沒結束。按「繼續」再進行 ${esc(String(g.turnLimit || 4))} 回合。</span><button type="button" class="secondary small-btn" data-action="group-discard">結束</button><button type="button" class="primary small-btn" data-action="group-continue">繼續</button></div>`;
    let after = g.afterAsk;  // worked out over the whole discussion by the Mac, since the page may hold only its newest part
    if (!after) { const messages = groupMsgs(g), lastAsk = messages.map(m => m.role).lastIndexOf('user'), since = messages.slice(lastAsk + 1).filter(m => m.role === 'assistant' && m.content && !m.checkOf); after = {replies: since.length, card: since.some(m => m.card)}; }
    return after.replies >= 2 && !after.card ? `<div class="group-bar"><span></span><button type="button" class="secondary small-btn" data-action="group-summarize">整理結論（多用一次模型請求）</button></div>` : '';
  }

  const CARD_PARTS = [['conclusion', '結論'], ['decisions', '需要你決定'], ['actions', '待辦'], ['questions', '仍有疑問']];
  const cardText = card => [card.body, ...CARD_PARTS.filter(([k]) => card[k]).map(([k, name]) => `【${name}】\n${card[k]}`)].filter(Boolean).join('\n\n');
  function groupCardView(m) {
    return `<div class="group-card">${m.card.body ? `<section><div class="md">${markdown(m.card.body)}</div></section>` : ''}${CARD_PARTS.filter(([k]) => m.card[k]).map(([k, name]) => `<section><h4>${name}</h4><div class="md">${markdown(m.card[k])}</div></section>`).join('')}<div class="group-card-actions"><button type="button" class="link" data-action="card-copy" data-id="${esc(m.id)}">複製</button><button type="button" class="link" data-action="card-save" data-id="${esc(m.id)}">存到知識庫</button></div></div>`;
  }
  // 請其他成員查核: what came back is shown under the reply it checks. A check that failed says why in plain words and offers to try
  // again; an older failure that a later check replaced is not shown. What the Mac refused (nobody can check, or only the same
  // vendor can) is said right there too, instead of in a notice that fades.
  const othersIn = (g, m) => (g.botIds || []).some(x => x !== m.botId && state.data.bots.some(b => b.id === x));  // someone besides the author is in the group
  const checksOf = (g, m) => { const all = groupMsgs(g).filter(x => x.checkOf === m.id); return all.filter((c, i) => (c.status === 'completed' && c.content) || c.status === 'running' || i === all.length - 1); };
  const checkFailed = c => c.status !== 'running' && !(c.status === 'completed' && c.content);
  function groupChecks(g, m) {
    const checks = checksOf(g, m), note = (state.verifyNotes || {})[m.id];
    if (!checks.length && !note) return '';
    const cls = {'同意': 'ok', '有疑慮': 'warn', '有錯誤': 'bad'};
    return `<div class="group-checks">${checks.map(c => {
      const b = state.data.bots.find(x => x.id === c.botId);
      if (c.status === 'running') return `<div class="group-check"><strong>${esc(b?.name || '成員')}</strong> 正在查核…</div>`;
      if (checkFailed(c)) {
        const why = c.error || (c.status === 'cancelled' ? '查核已停止。' : '') || Object.values(state.jobDetails).find(j => j.messageId === c.id)?.error || '查核沒有完成。';
        return `<div class="group-check failed"><div class="group-check-head"><strong>${esc(b?.name || '成員')} 查核失敗</strong></div><p>${esc(why)}</p>${g.status !== 'running' && othersIn(g, m) && !(state.verifyNotes || {})[m.id] ? `<button type="button" class="link" data-action="group-verify" data-id="${esc(m.id)}">再試一次</button>` : ''}</div>`;
      }
      return `<div class="group-check"><div class="group-check-head"><strong>${esc(b?.name || '成員')} 查核</strong><span class="pill ${cls[c.verdict] || ''}">${esc(c.verdict || '未判定')}</span></div><div class="md">${markdown(c.content.replace(/【判定】\s*(同意|有疑慮|有錯誤)/, '').trim())}</div></div>`;
    }).join('')}${note ? `<div class="group-check failed"><p>${esc(note.text)}</p>${note.confirm && othersIn(g, m) ? `<button type="button" class="link" data-action="group-verify-anyway" data-id="${esc(m.id)}">仍要查核</button> ` : ''}<button type="button" class="link" data-action="group-verify-dismiss" data-id="${esc(m.id)}">${note.confirm ? '取消' : '知道了'}</button></div>` : ''}</div>`;
  }
  // One button per reply, and none when nobody else is in the group, while a check runs, or when the failed check already offers 再試一次.
  const groupVerifyButton = (g, m) => {
    if (g.status === 'running' || m.status !== 'completed' || !m.content || (state.verifyNotes || {})[m.id]) return '';
    if (!othersIn(g, m)) return '';
    const last = checksOf(g, m).slice(-1)[0];
    if (last && (last.status === 'running' || checkFailed(last))) return '';
    return `<div class="msg-actions"><button type="button" class="link" data-action="group-verify" data-id="${esc(m.id)}">請其他成員查核</button></div>`;
  };

  async function verifyGroupMessage(g, id, anyway = false) {
    const res = await fetch('/api/groups/' + encodeURIComponent(g.id) + '/messages/' + encodeURIComponent(id) + '/verify', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(anyway ? {confirm: true} : {})});
    const body = await res.json().catch(() => ({}));
    state.verifyNotes = state.verifyNotes || {};
    if (!res.ok) { state.verifyNotes[id] = {text: body.error || '沒辦法查核這則回覆，請稍後再試。', confirm: !!body.needsConfirm}; render(true); return; }
    delete state.verifyNotes[id];
    await refresh(); pollGroup(g.id);
  }
  // A check that is still running is read again every few seconds until it finishes or fails, even if the discussion's own
  // polling stopped early (a dropped request, a reply that arrived while an older full refresh was still on its way).
  // #215②: a check still marked 「正在查核」 after the Mac said the run is over (left behind) is not asked about again and again;
  // only when the discussion changes after that.
  if (!state.groupQuiet) state.groupQuiet = {};
  const groupNeedsPoll = g => g.status === 'running' || (groupMsgs(g).some(x => x.checkOf && x.status === 'running') && state.groupQuiet[g.id] !== groupFileMark(g));
  setInterval(() => {
    const g = state.data && state.page === 'chat' && state.groupId ? activeGroup() : null;
    if (g && !state.groupPollers[g.id] && groupNeedsPoll(g)) pollGroup(g.id);
  }, 2500);

  // 檔案 tab of the group's detail panel.
  const fileSize = n => n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(0) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  async function loadGroupFiles(g) {
    try { state.groupFiles[g.id] = (await api('groups/' + encodeURIComponent(g.id) + '/files')).files; }
    catch (error) { state.groupFiles[g.id] = []; toast(error.message); }
    render(true);
  }
  function groupFilesTab(g) {
    const files = state.groupFiles[g.id];
    if (!files) { setTimeout(() => loadGroupFiles(g), 0); return '<div class="detail-empty">正在讀取檔案…</div>'; }
    const base = '/api/groups/' + encodeURIComponent(g.id) + '/files/';
    const note = state.groupFileNote?.[g.id];
    return `<div class="group-files"><button type="button" class="secondary" data-action="group-file-pick">＋ 上傳檔案</button><input type="file" id="group-file-input" multiple hidden>${note ? `<div class="group-file-note${note.failed.length ? ' has-failed' : ''}" role="status"><span>${esc(note.failed.length ? `${note.ok ? `已上傳 ${note.ok} 個；` : ''}${note.failed.length} 個沒有上傳：` : fileSummary(note.ok, []))}</span>${note.failed.length ? `<ul>${note.failed.map(x => `<li><strong title="${esc(x.name)}">${esc(midName(x.name))}</strong>：${esc(x.reason)}</li>`).join('')}</ul>` : ''}</div>` : ''}${note?.notes?.length ? `<div class="group-file-note" role="status">${esc(note.notes.join('。'))}</div>` : ''}${files.length ? files.map(f => `<div class="group-file"><span class="group-file-icon" aria-hidden="true">${fileIcon(f.name)}</span>${['image', 'pdf', 'text', 'markdown'].includes(f.kind) ? `<button type="button" class="group-file-name" data-group-file="${esc(f.name)}" data-group="${esc(g.id)}" title="預覽 ${esc(f.name)}">` : `<span class="group-file-name" title="${esc(f.name)}">`}<strong title="${esc(f.name)}">${esc(midName(f.name, 40))}</strong><small>${esc([fileSize(f.size), f.by].filter(Boolean).join(' · '))}</small>${['image', 'pdf', 'text', 'markdown'].includes(f.kind) ? '</button>' : '</span>'}<a class="link" href="${base}${encodeURIComponent(f.name)}" download="${esc(f.name)}" title="下載 ${esc(f.name)}">下載</a><button type="button" class="link danger" data-action="group-file-delete" data-id="${esc(f.name)}">刪除</button></div>`).join('') : '<div class="detail-empty">還沒有檔案。成員都能讀取和存入。</div>'}<small class="muted">單檔 20 MB，每個群組 200 MB。${ATTACH_HINT}</small></div>`;
  }
  // Several files at once (#150): each one is tried, a bad one is skipped, and the end says which went in and which did not, and why.
  async function uploadGroupFiles(g, list) {
    const ok = [], failed = [], odd = [], notes = [], had = new Set((state.groupFiles[g.id] || []).map(x => x.name));
    state.groupFileNote = state.groupFileNote || {};
    for (const f of list) {
      try {
        const res = await fetch('/api/groups/' + encodeURIComponent(g.id) + '/files', {method: 'POST', headers: {'X-File-Name': encodeURIComponent(f.name), 'Content-Type': 'application/octet-stream'}, body: f});
        if (res.ok) {
          const saved = (await res.json().catch(() => ({}))).name; ok.push(f.name);
          if (saved && saved !== f.name) notes.push(`${midName(f.name)} 存成「${midName(saved)}」${had.has(f.name) ? '（群組裡已有同名檔）' : ''}`);
          if (UNREADABLE.test(f.name)) odd.push(f.name);
          had.add(saved || f.name); continue;
        }
        failed.push({name: f.name, reason: (await res.json().catch(() => ({}))).error || '上傳失敗'});
      } catch (e) { failed.push({name: f.name, reason: '連不上 Zook，沒有上傳'}); }
    }
    if (odd.length) notes.push(unreadableNote(odd));
    state.groupFileNote[g.id] = {ok: ok.length, failed, notes};
    toast([fileSummary(ok.length, failed), ...notes].join('。'));
    await loadGroupFiles(g);
  }
  // One summary for several files, used by the group's files and the message box alike: 「已上傳 2 個；1 個沒有上傳：空檔.txt（檔案是空的）」.
  function fileSummary(ok, failed, verb = '上傳') {
    const done = ok ? `已${verb} ${ok} 個` : `沒有${verb}任何檔案`;
    if (!failed.length) return done;
    return `${done}；${failed.length} 個沒有${verb}：` + failed.map(x => `${midName(x.name)}（${String(x.reason).replace(/[。.]+$/, '')}）`).join('、');
  }
  // A long file name shortened in the middle, so its end and extension still show (報告⋯⋯第三季.xlsx).
  function midName(name, max = 32) {
    const s = String(name || ''); if ([...s].length <= max) return s;
    const chars = [...s], dot = s.lastIndexOf('.'), ext = dot > 0 && s.length - dot <= 10 ? [...s.slice(dot)].length : 0, tail = Math.min(ext + 6, max - 6);
    return chars.slice(0, max - tail - 1).join('') + '…' + chars.slice(-tail).join('');
  }

  // A member's own window on a group discussion: for each time it spoke, what it looked up and which Skills it used on the way,
  // and then the conclusion it put into the group. The group itself only shows the conclusions.
  // Every time the member spoke comes from the Mac (the page may hold only the newest part of the discussion); it is asked for
  // again whenever the discussion has moved on.
  state.memberTurns = state.memberTurns || {};
  async function loadMemberTurns(g, b, older) {
    const key = g.id + ':' + b.id, had = state.memberTurns[key], busy = state.memberLoading = state.memberLoading || {};
    if (busy[key]) return;
    busy[key] = true;
    try {
      const first = older && had?.turns[0];
      const out = await api(`groups/${encodeURIComponent(g.id)}/messages?member=${encodeURIComponent(b.id)}${first ? '&before=' + encodeURIComponent(first.id) : ''}`);
      state.memberTurns[key] = first ? {turns: out.turns.concat(had.turns), more: out.more, mark: had.mark} : {turns: out.turns, more: out.more, mark: memberMark(g)};
    } catch (err) { toast(err.message); state.memberTurns[key] = Object.assign(had || {turns: [], more: false}, {mark: memberMark(g)}); }  // not asked again until the discussion moves on
    delete busy[key];
    render(true);
  }
  const memberMark = g => { const last = (g.messages || []).slice(-1)[0]; return [g.status, last?.id, last?.status, (g.messages || []).length + (g.olderCount || 0)].join('|'); };
  document.addEventListener('click', e => { const el = e.target.closest?.('[data-member-older]'); if (el && state.memberWork) { const g = state.data.groups.find(x => x.id === state.memberWork.group), b = state.data.bots.find(x => x.id === state.memberWork.bot); if (g && b) loadMemberTurns(g, b, true); } });
  // Everything one member did for one turn, in order: Skills, connectors, tools, pages and files it looked at.
  function workSteps(calls, running) {
    return `<ol class="work-list">${calls.slice(0, 200).map(c => { let [cls, label] = callStatus(c); if ((cls === 'wait' || cls === 'run') && !running) [cls, label] = ['bad', '已中斷']; return `<li class="tool-event ${cls}" title="${esc(label + (c.name === 'native_command' && c.arguments?.summary ? '：' + c.arguments.summary : ''))}"><span class="ev-dot ${cls}" role="img" aria-label="${esc(label)}"></span><span class="ev-text">${esc(describeCall(c))}${evNote(cls, label)}</span></li>`; }).join('')}</ol>`;
  }
  function memberWork(b, g) {
    const jobs = {}; for (const j of Object.values(state.jobDetails)) if (j.groupId === g.id && j.botId === b.id) jobs[j.messageId] = j;
    const got = state.memberTurns[g.id + ':' + b.id];
    if (!got || got.mark !== memberMark(g)) setTimeout(() => loadMemberTurns(g, b), 0);
    const said = got?.turns || [];
    const turns = said.map(m => {
      const job = jobs[m.id], calls = (job?.status === 'running' ? job.toolCalls : m.work?.calls || job?.toolCalls) || [], thinking = m.work?.thinking || [], q = m.asked;
      const steps = calls.length ? `<div class="work-steps">${workSteps(calls, m.status === 'running')}</div>` : `<div class="work-none">${m.status === 'running' ? '正在進行，用到的工具會陸續出現在這裡。' : m.work || (job && !job.slim) ? '這次沒有使用 Skill、連接器或工具，也沒有查資料，直接回覆。' : '這次的過程紀錄已經整理掉了（只保留最近的回覆）。'}</div>`;
      const thought = thinking.length ? `<details class="work-thinking"><summary>思考過程</summary>${thinking.map(t => `<p>${esc(t)}</p>`).join('')}</details>` : '';
      const end = m.status === 'running' ? '<div class="bubble">正在進行…</div>' : m.content ? `<div class="bubble md">${markdown(m.content)}</div>` : `<div class="bubble">${esc(m.status === 'cancelled' ? '已停止' : '沒有回覆')}</div>`;
      return `<div class="date">${esc(formatDate(m.createdAt))}</div>${q ? `<div class="work-ask"><span>${esc(q.author || '你')} 在群組說</span>${esc(String(q.content || '').slice(0, 300))}</div>` : ''}<div class="work-turn"><div class="work-label">過程（Skill、連接器、工具、查了什麼、做了什麼）</div>${steps}${thought}<div class="work-label">想完後在群組的回應</div><div class="message assistant">${avatar(b)}${end}</div></div>`;
    }).join('');
    return `<main class="main"><header class="main-header"><button class="bot-pill" data-action="edit-bot">${avatar(b)}${esc(b.name)} <span class="muted">⌄</span></button><div class="header-actions"><button class="text-btn" data-member-work="" data-back="group" data-group="${esc(g.id)}">‹ 回到群組</button><button class="text-btn" data-action="chats" title="所有對話">☰ 群組：${esc(g.name)}</button><button class="text-btn" data-member-work="">和 ${esc(b.name)} 的對話</button>${!state.detailOpen ? '<button class="text-btn" data-action="toggle-detail">顯示詳情</button>' : ''}</div></header><div class="conversation" id="conversation"><div class="conversation-inner"><div class="work-head">${esc(b.name)} 在「${esc(g.name)}」的工作過程<small>每次發言前用了哪些 Skill、連接器和工具，查了什麼、做了什麼、怎麼想的；群組裡只放想完後的回應。</small></div>${got?.more ? '<div class="older-bar"><button class="link" data-member-older="1">載入更早的發言</button></div>' : ''}${turns || `<div class="detail-empty">${got ? '他還沒有在這個討論中發言。' : '正在讀取…'}</div>`}</div></div></main>${state.detailOpen ? detail(b) : ''}`;
  }
  document.addEventListener('click', e => {
    const row = e.target.closest('[data-member-work]');
    if (!row) return;
    const bot = row.dataset.memberWork, group = row.dataset.group;
    if (row.dataset.closeModal) closeModal();
    if (bot) { state.memberWork = {bot, group}; state.groupId = null; state.selected = bot; state.page = 'chat'; }
    else { state.memberWork = null; if (row.dataset.back === 'group' && group) { state.groupId = group; state.page = 'chat'; } }
    render();
  });

  // #223①: a group with nothing in it yet says what happens when you send, in the way it is set to discuss.
  function groupEmptyView(g) {
    const mode = currentGroupMode(g), opt = groupModeOptions().find(o => o.id === mode) || GROUP_MODE_OPTIONS[0];
    const host = groupMembers(g).find(b => b.id === groupHostId(g)), hostName = host ? host.name : '主持人';
    const steps = mode === 'auto' ? [
      '在下方說出要完成的事，例如「整理這三份報價，做成一張比較表」。',
      `${esc(hostName)} 會把工作拆成幾項，列在對話裡的「任務板」：每項寫明誰負責、做到哪裡，最上面的「下一步」會說要不要你做什麼。`,
      state.data.settings.taskExecution === 'lowrisk' ? '只讀資料的工作會直接開始；會改檔案或對外動作的，要你按「照這個做」才開始。' : '工作排好後，要你按「照這個做」才會開始；不想做就按「不要，停止」。',
      '成員各自做，交出後由別家的模型驗收；全部完成後主持人整理結果。',
      '輸入框下方會寫預計幾次回覆和回合上限；驗收和重做會再多幾次。'
    ] : [
      `目前的討論方式是「${esc(opt.name)}」：${esc(opt.hint)}。`,
      host ? `主持人是 ${esc(host.name)}，負責開場分派、收斂討論和總結。` : '沒有設主持人：按上方群組名稱可以指定一位。',
      '直接發訊息就會開始；用 @ 可以只問某位成員。輸入框旁的下拉可以只對下一則換別的討論方式。'
    ];
    return `<div class="empty-chat">${avatarStack(g, 'hero')}<h1>${esc(g.name)}</h1><ol class="group-howto">${steps.map(s => `<li>${s}</li>`).join('')}</ol></div>`;
  }
  // Another way picked beside the message box: an empty group's explanation follows it (after 50-forms.js has noted the choice).
  document.addEventListener('change', e => { if (e.target.name === 'groupMode' && activeGroup() && !(activeGroup().messages || []).length) setTimeout(() => render(true), 0); });
  // #132②: the member list says the access in a few words; the full sentence is in the tooltip.
  const memberAccess = b => b.provider !== 'auto' && gatedCli(b.provider) && b.gateFull ? '整台 Mac（危險動作先問你）' : permText(b);
