  // 任務引擎: the task board in a group, and its switch in 設定. The work itself is run by the Mac (backend/zook/taskrun.py).
  const TASK_STATE = {pending: '等前面的工作', ready: '待開始', running: '進行中', asked: '等主持人回答', blocked: '卡住了', verifying: '驗收中', waiting: '等你決定', review: '等你看結果',
    done: '完成', failed: '沒有完成', stuck: '已停下，等你決定', unknown: '狀態不明', cancelled: '已停止'};
  const TASK_TONE = {done: 'ok', failed: 'bad', stuck: 'bad', unknown: 'warn', asked: 'warn', blocked: 'warn', waiting: 'warn', review: 'warn', cancelled: 'muted', running: 'live', verifying: 'live'};
  const TASK_RETRY = ['stuck', 'unknown', 'failed', 'cancelled'];
  // Stopped to wait for you although its member reported it done: what it handed in is there to look at (as tasks.py task_handed_in).
  const taskHandedIn = t => ['stuck', 'review', 'unknown'].includes(t.status) && Array.isArray(t.attempts) && t.attempts.length > 0 && t.attempts[t.attempts.length - 1].state === 'reported' && t.attempts[t.attempts.length - 1].outcome === 'succeeded';
  const taskEngineOn = () => state.data?.settings?.taskEngine === true;
  const groupModeOptions = () => GROUP_MODE_OPTIONS.concat(taskEngineOn() ? [{id: 'auto', name: '自動（主持人決定）', hint: '多步驟的工作：主持人拆成幾項、列在「任務板」派給成員，交出後由別家模型驗收，可以來回好幾輪直到完成'}] : []);

  // #130: the board as steps. Each task is its own card, its words one per line; above them 「下一步」 says who has to act now.
  const taskName = id => state.data.bots.find(b => b.id === id)?.name || '已刪除的 Bot';
  function taskNextStep(g, run) {
    const tasks = run.tasks, n = t => '工作 ' + t.n, list = a => a.map(n).join('、');
    if (run.status === 'running') {
      if (run.awaitingConfirm) return {you: true, text: '主持人排好了工作：看下方的清單，按「照這個做」才會開始。'};
      const gate = (run.gates || []).find(x => x.status === 'pending');
      if (gate) return {you: true, text: `主持人在等你決定：${gate.question}（在下方選一個）`};
      const review = tasks.filter(t => t.status === 'review');
      if (review.length) return {you: true, text: `${list(review)} 沒有別家的模型可以驗收：${taskEngineOn() ? '看過結果後按「接受結果」' : '任務引擎已關閉，要接受結果請先在「設定」打開任務引擎'}。`};
      if (!tasks.length) return {text: '工作排好後會列在這裡；你不用做什麼。'};
      const going = tasks.filter(t => ['running', 'verifying', 'asked'].includes(t.status));
      if (going.length) return {text: `正在進行：${going.map(t => `${n(t)}（${taskName(t.assignee)}${t.status === 'verifying' ? '，驗收中' : t.status === 'asked' ? '，等主持人回答' : ''}）`).join('、')}。做完會自動往下走，你不用做什麼。`};
      return {text: '主持人正在看成員的回報，決定下一步；你不用做什麼。'};
    }
    const again = taskEngineOn() ? '按那一項的「重試」，或在下方再送一次訊息告訴主持人怎麼調整' : '在下方再送一次訊息（任務引擎已關閉，不能重試）';
    const why = run.interrupted ? '（Zook 重新啟動時中斷了）' : run.status === 'stopped' ? '（已停止）' : '';
    if (!tasks.length) {
      if (run.status === 'done') return {text: '主持人直接回答，沒有建立工作。'};
      const said = groupMsgs(g).filter(x => x.role === 'assistant' && x.botId === run.hostId && !x.checkOf).slice(-1)[0];
      const error = said && said.status === 'failed' ? said.error || Object.values(state.jobDetails).find(j => j.messageId === said.id)?.error || '' : '';
      return {you: true, text: `主持人還沒排出工作就停下了${why}${error ? '：' + error : ''}。在下方再送一次訊息就會重新開始。`};
    }
    const handed = tasks.filter(taskHandedIn), left = tasks.filter(t => t.status !== 'done' && !taskHandedIn(t));
    const parts = [handed.length ? `${list(handed)} 已交出：${taskEngineOn() ? '看過結果後按「接受結果」，要重做按「重試」' : '任務引擎已關閉，要接受或重試請先在「設定」打開任務引擎'}` : '', left.length ? `${list(left)} 沒有完成${why}：${again}` : ''].filter(Boolean);
    if (parts.length) return {you: true, text: parts.join('；') + '。'};
    return {text: '全部完成，主持人的整理在下方。'};
  }
  const nextLine = next => `<span class="task-next${next.you ? ' you' : ''}"><strong>${next.you ? '下一步（要你處理）' : '下一步'}</strong>${esc(next.text)}</span>`;
  const taskStep = (num, title, who, pill, tone, lines, acts = '') => `<li class="task-step"><span class="task-num" aria-hidden="true">${esc(String(num))}</span><div class="task-body"><div class="task-head"><strong class="task-title">${esc(String(title))}</strong><span class="pill ${tone}">${esc(pill)}</span></div>${who ? `<div class="task-who">負責：${esc(who)}</div>` : ''}${lines.map(x => `<div class="task-detail">${esc(x)}</div>`).join('')}${acts ? `<div class="task-acts">${acts}</div>` : ''}</div></li>`;

  function taskBoardView(g, m) {
    const run = g.taskRun && g.taskRun.id === m.taskBoard && Array.isArray(g.taskRun.tasks) ? g.taskRun : null;
    if (!run) return oldBoardView(m);
    const done = run.tasks.filter(t => t.status === 'done').length, handed = run.tasks.filter(taskHandedIn).length;
    const head = run.tasks.length ? `已完成 ${done}／${run.tasks.length}${handed ? `，${handed} 項已交出，等你看結果` : ''}` : (run.status === 'running' ? `${esc(taskName(run.hostId))} 正在規劃工作…` : '沒有建立工作');
    const rows = run.tasks.map(t => {
      const attempts = Array.isArray(t.attempts) ? t.attempts : [], last = attempts[attempts.length - 1] || {};
      const detail = [last.summary, t.status === 'asked' && t.question ? '問主持人：' + t.question : '', last.reason, t.note, t.why || (t.basis ? '派工依據：' + t.basis : ''),
        Array.isArray(t.deps) && t.deps.length && ['pending', 'ready'].includes(t.status) ? '等工作 ' + t.deps.join('、') + ' 完成' : '',
        t.verify?.verdict ? `${taskName(t.verify.bot)} 驗收${t.verify.verdict === 'pass' ? '通過' : '沒有通過：' + (t.verify.reasons || '')}` : t.status === 'verifying' && t.verify?.bot ? `${taskName(t.verify.bot)} 驗收中` : '',
        t.failures ? `已經 ${t.failures} 次沒完成` : '', t.confirmed === false && ['pending', 'ready'].includes(t.status) ? '等你確認' : '', Array.isArray(last.files) && last.files.length ? '產出：' + last.files.join('、') : '', attempts.length > 1 ? `第 ${attempts.length} 次` : ''].filter(x => typeof x === 'string' && x);
      const canAccept = ['review', 'stuck', 'unknown'].includes(t.status) && last.state === 'reported' && last.outcome === 'succeeded' || ['stuck', 'unknown'].includes(t.status) && t.cut === true;  // cut by a restart: the user retries it or accepts what is there
      const retry = !taskEngineOn() ? '' : (!t.aborted && (TASK_RETRY.includes(t.status) && g.status !== 'running' || ['stuck', 'unknown'].includes(t.status)) ? `<button type="button" class="link" data-task-retry="${esc(t.id)}">重試</button>` : '') + (canAccept ? `<button type="button" class="link" data-task-accept="${esc(t.id)}">接受結果</button>` : '');
      const handedIn = ['stuck', 'unknown'].includes(t.status) && taskHandedIn(t);
      return taskStep(t.n, t.title, taskName(t.assignee), handedIn ? '已交出，等你決定' : TASK_STATE[t.status] || t.status, handedIn ? 'warn' : TASK_TONE[t.status] || '', detail, retry);
    }).join('');
    const live = run.status === 'running' ? '<span class="browsing-dot" aria-hidden="true"></span>' : '';
    return `<details class="task-board" data-task-board="${esc(run.id)}" ${state.taskOpen?.[run.id] ? 'open' : ''}><summary>${live}<strong>任務板</strong> <span class="muted">${head}${run.status === 'stopped' ? ' · 已停止' : ''}</span>${nextLine(taskNextStep(g, run))}</summary>${rows ? `<ol class="task-steps">${rows}</ol>` : ''}</details>`;
  }
  // A board whose run was replaced by a newer one: only its words are kept (tasks.py task_board_text). Each task gets its own card again.
  function oldBoardView(m) {
    const lines = String(m.content || '').split('\n'), head = (lines.shift() || '').replace(/^任務板：/, ''), items = [], rest = [];
    for (const line of lines) {
      const task = line.match(/^([✓·]) (\d+)\. (.*) — (.*)（([^（）]*)）$/);
      if (task) items.push({n: task[2], title: task[3], who: task[4], state: task[5], tone: task[1] === '✓' ? 'ok' : '', lines: []});
      else if (/^\s/.test(line) && items.length) items[items.length - 1].lines.push(line.trim());
      else if (line.trim()) rest.push(line.trim());
    }
    const steps = items.map(t => taskStep(t.n, t.title, t.who, t.state, t.tone, t.lines)).join('');
    return `<details class="task-board" data-task-board="${esc(m.taskBoard)}" ${state.taskOpen?.[m.taskBoard] ? 'open' : ''}><summary><strong>任務板</strong> <span class="muted">${esc(head)}</span>${nextLine({text: '這是較早的一輪，只留下文字紀錄；要接著做，在下方再送一次訊息。'})}</summary>${steps ? `<ol class="task-steps">${steps}</ol>` : ''}${rest.map(x => `<div class="task-detail">${esc(x)}</div>`).join('')}</details>`;
  }

  // What the user has to do for a run: confirm the plan, or make a decision the host asked for. Shown above the message box.
  function taskDecisionCards(g) {
    const run = g.taskRun;
    if (!run || run.status !== 'running' || !Array.isArray(run.tasks)) return '';
    const cards = [];
    if (run.awaitingConfirm) {
      const waiting = run.tasks.filter(t => t.confirmed === false && ['pending', 'ready', 'waiting'].includes(t.status) && !t.staged);
      cards.push(`<section class="approval-card task-confirm"><strong>主持人排好了 ${waiting.length} 項工作，確認後才開始</strong><ol class="task-list">${waiting.map(t => `<li><details><summary>${esc(String(t.n))}. ${esc(String(t.title))} <span class="muted">${esc(state.data.bots.find(b => b.id === t.assignee)?.name || '')}${t.changes === 'none' ? ' · 只讀' : t.changes === 'external' ? ' · 會對外動作' : ' · 會改檔案'}</span></summary><div class="task-detail">${esc(String(t.spec || ''))}</div><div class="task-detail"><strong>怎樣算完成：</strong>${esc(String(t.doneWhen || ''))}</div></details></li>`).join('')}</ol><div class="actions"><button class="primary" data-task-confirm="${esc(waiting.map(t => t.id).join(','))}">照這個做</button><button class="secondary" data-action="stop-group" data-id="${esc(g.id)}">不要，停止</button></div></section>`);
    }
    for (const t of run.tasks.filter(x => x.status === 'review')) {
      const last = (Array.isArray(t.attempts) ? t.attempts : []).slice(-1)[0] || {};
      cards.push(`<section class="question-card task-review"><strong>工作 ${esc(String(t.n))}「${esc(String(t.title))}」沒有其他家的模型可以驗收，請你看一下結果</strong><small>${esc(String(last.summary || ''))}</small><div class="actions"><button class="secondary" data-task-accept="${esc(t.id)}">接受結果</button></div></section>`);
    }
    for (const gate of (run.gates || []).filter(x => x.status === 'pending')) {
      cards.push(`<section class="question-card task-gate"><strong>${esc(String(gate.question))}</strong><small>等這個決定的工作：${esc((gate.tasks || []).join('、'))}</small><div class="actions">${(gate.options || []).map(o => `<button class="secondary" data-task-gate="${esc(gate.id)}" data-answer="${esc(String(o))}">${esc(String(o))}</button>`).join('')}</div></section>`);
    }
    return cards.join('');
  }

  const TASK_COUNTS = n => Array.from({length: n}, (_, i) => ({id: String(i + 1), name: (i + 1) + ' 項'}));
  function taskSection() {
    const s = state.data.settings, rows = [settingRow('開啟自動分工', '群組的討論方式會多一種「自動（主持人決定）」：主持人把工作拆開、派給成員同時做，大家做完回報，主持人再整理結果', toggle('data-task-engine', taskEngineOn(), '開啟自動分工'))];
    if (taskEngineOn()) {
      rows.push(settingRow('排好工作後', '主持人分好工作之後，要不要等你點頭才開始', dropdown('taskExecution', s.taskExecution === 'lowrisk' ? 'lowrisk' : 'ask', [{id: 'ask', name: '先問我', hint: '每次都等你按「照這個做」'}, {id: 'lowrisk', name: '低風險直接做', hint: '不改檔案、不對外動作的工作直接開始，其他仍先問'}], 'data-task-execution')));
      rows.push(settingRow('照過去表現派工', '每項工作做完會由另一家 AI 檢查。某家 AI 在某類工作常沒通過檢查時，改派給表現較好的成員；原因會寫在任務板上', toggle('data-task-learn', s.taskLearn !== false, '照過去表現派工')));
      rows.push(settingRow('同時進行的工作', '一個群組同時最多做幾項；下面可以再限制每一家 AI', dropdown('taskMax', String(s.taskMax || 4), TASK_COUNTS(6), 'data-task-max')));
      for (const p of (state.providers || []).filter(p => p.installed && p.tools)) {
        rows.push(settingRow(esc(p.name), '這一家 AI 同時最多做幾項（同一家有幾個帳號就各自算）', dropdown('taskCli-' + p.id, String((s.taskCliLimits || {})[p.id] || 3), TASK_COUNTS(4), `data-task-cli="${esc(p.id)}"`)));
      }
    }
    // A CLI that cannot use Zook's tools cannot report a task (tasks.py), so it is not listed; say so instead of leaving it out silently (#75③).
    const left = taskEngineOn() ? (state.providers || []).filter(p => p.installed && !p.tools && p.id !== 'auto').map(p => providerShort(p.id)) : [];
    return `<h2 class="settings-h">群組自動分工（任務引擎）</h2><div class="setting-list">${rows.join('')}</div>${left.length ? `<p class="muted small settings-note">${esc(left.join('、'))} 不能接分派的工作（它用不了 Zook 回報進度的工具），所以沒有列出。</p>` : ''}`;
  }

  // The board stays open or closed as the reader left it, while the page redraws it.
  document.addEventListener('toggle', e => { const id = e.target.dataset?.taskBoard; if (id) (state.taskOpen = state.taskOpen || {})[id] = e.target.open; }, true);
  document.addEventListener('change', async e => {
    if (e.target.dataset?.taskExecution !== undefined) {
      try { state.data.settings = await post('settings', {taskExecution: e.target.value}, 'PATCH'); toast(e.target.value === 'lowrisk' ? '只讀的工作會直接開始' : '每次都會先問你'); } catch (error) { toast(error.message); }
      render(true); return;
    }
    const max = e.target.dataset?.taskMax !== undefined, cli = e.target.dataset?.taskCli;
    if (max || cli) {
      const body = max ? {taskMax: Number(e.target.value)} : {taskCliLimits: {...(state.data.settings.taskCliLimits || {}), [cli]: Number(e.target.value)}};
      try { state.data.settings = await post('settings', body, 'PATCH'); toast('已更新同時進行的上限'); } catch (error) { toast(error.message); }
      render(true); return;
    }
    if (e.target.dataset?.taskLearn !== undefined) {
      try { state.data.settings = await post('settings', {taskLearn: e.target.checked}, 'PATCH'); toast(e.target.checked ? '會參考過去的驗收紀錄派工' : '照主持人的指定派工'); }
      catch (error) { e.target.checked = !e.target.checked; toast(error.message); }
      render(true); return;
    }
    if (e.target.dataset?.taskEngine === undefined) return;
    try { state.data.settings = await post('settings', {taskEngine: e.target.checked}, 'PATCH'); toast(e.target.checked ? '群組可以選「自動（主持人決定）」了' : '已關閉任務引擎'); }
    catch (error) { e.target.checked = !e.target.checked; toast(error.message); }
    render(true);
  });

  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-task-retry],[data-task-accept],[data-task-confirm],[data-task-gate]');
    if (!el) return;
    const g = activeGroup(); if (!g) return;
    el.disabled = true;
    try {
      if (el.dataset.taskRetry) { await post(`groups/${encodeURIComponent(g.id)}/tasks/${encodeURIComponent(el.dataset.taskRetry)}/retry`, {}); toast('已重新開始這項工作'); }
      else if (el.dataset.taskAccept) { await post(`groups/${encodeURIComponent(g.id)}/tasks/${encodeURIComponent(el.dataset.taskAccept)}/accept`, {}); toast('已接受結果'); }
      else if (el.dataset.taskConfirm) { await post(`groups/${encodeURIComponent(g.id)}/tasks/confirm`, {tasks: el.dataset.taskConfirm.split(',')}); toast('開始進行'); }
      else { await post(`groups/${encodeURIComponent(g.id)}/gates/${encodeURIComponent(el.dataset.taskGate)}`, {answer: el.dataset.answer}); toast('已告訴團隊你的決定'); }
    } catch (error) { toast(error.message); el.disabled = false; }
    await refresh();
  });
