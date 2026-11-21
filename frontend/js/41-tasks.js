  // 任務引擎: the task board in a group, and its switch in 設定. The work itself is run by the Mac (backend/zook/taskrun.py).
  const TASK_STATE = {pending: '等前面的工作', ready: '待開始', running: '進行中', asked: '等主持人回答', blocked: '卡住了', verifying: '驗收中', waiting: '等你決定', review: '等你看結果',
    done: '完成', failed: '沒有完成', stuck: '已停下，等你決定', unknown: '狀態不明', cancelled: '已停止'};
  const TASK_TONE = {done: 'ok', failed: 'bad', stuck: 'bad', unknown: 'warn', asked: 'warn', blocked: 'warn', waiting: 'warn', review: 'warn', cancelled: 'muted', running: 'live', verifying: 'live'};
  const TASK_RETRY = ['stuck', 'unknown', 'failed', 'cancelled'];
  const taskEngineOn = () => state.data?.settings?.taskEngine === true;
  const groupModeOptions = () => GROUP_MODE_OPTIONS.concat(taskEngineOn() ? [{id: 'auto', name: '自動（主持人決定）', hint: '主持人拆工作、派給成員，回報後整理結果'}] : []);

  function taskBoardView(g, m) {
    const run = g.taskRun && g.taskRun.id === m.taskBoard && Array.isArray(g.taskRun.tasks) ? g.taskRun : null;
    if (!run) return `<div class="system-note">${esc(m.content)}</div>`;  // an older board: its words
    const name = id => state.data.bots.find(b => b.id === id)?.name || '已刪除的 Bot';
    const done = run.tasks.filter(t => t.status === 'done').length;
    const head = run.tasks.length ? `已完成 ${done}／${run.tasks.length}` : (run.status === 'running' ? `${esc(name(run.hostId))} 正在規劃工作…` : '主持人直接回答，沒有建立工作');
    const rows = run.tasks.map(t => {
      const attempts = Array.isArray(t.attempts) ? t.attempts : [], last = attempts[attempts.length - 1] || {};
      const detail = [last.summary, t.status === 'asked' && t.question ? '問主持人：' + t.question : '', last.reason, t.note, t.why || (t.basis ? '派工依據：' + t.basis : ''),
        Array.isArray(t.deps) && t.deps.length && ['pending', 'ready'].includes(t.status) ? '等工作 ' + t.deps.join('、') + ' 完成' : '',
        t.verify?.verdict ? `${name(t.verify.bot)} 驗收${t.verify.verdict === 'pass' ? '通過' : '沒有通過：' + (t.verify.reasons || '')}` : t.status === 'verifying' && t.verify?.bot ? `${name(t.verify.bot)} 驗收中` : '',
        t.failures ? `已經 ${t.failures} 次沒完成` : '', t.confirmed === false && ['pending', 'ready'].includes(t.status) ? '等你確認' : '', Array.isArray(last.files) && last.files.length ? '產出：' + last.files.join('、') : '', attempts.length > 1 ? `第 ${attempts.length} 次` : ''].filter(x => typeof x === 'string' && x);
      const canAccept = (t.status === 'review' || t.status === 'stuck') && last.state === 'reported' && last.outcome === 'succeeded';
      const retry = !taskEngineOn() ? '' : (!t.aborted && (TASK_RETRY.includes(t.status) && g.status !== 'running' || ['stuck', 'unknown'].includes(t.status)) ? `<button type="button" class="link" data-task-retry="${esc(t.id)}">重試</button>` : '') + (canAccept ? `<button type="button" class="link" data-task-accept="${esc(t.id)}">接受結果</button>` : '');
      return `<li class="task-row"><span class="pill ${TASK_TONE[t.status] || ''}">${esc(TASK_STATE[t.status] || t.status)}</span><span class="task-title"><strong>${esc(String(t.n))}. ${esc(String(t.title))}</strong> <span class="muted">${esc(name(t.assignee))}</span>${detail.length ? `<span class="task-detail">${esc(detail.join(' · '))}</span>` : ''}</span>${retry}</li>`;
    }).join('');
    const live = run.status === 'running' ? '<span class="browsing-dot" aria-hidden="true"></span>' : '';
    return `<details class="task-board" data-task-board="${esc(run.id)}" ${state.taskOpen?.[run.id] ? 'open' : ''}><summary>${live}<strong>任務板</strong> <span class="muted">${head}${run.status === 'stopped' ? ' · 已停止' : ''}</span></summary>${rows ? `<ol class="task-list">${rows}</ol>` : ''}</details>`;
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
    const s = state.data.settings, rows = [settingRow('任務引擎', '群組多一種討論方式「自動（主持人決定）」：主持人拆工作、派給成員同時進行，成員回報後再整理結果', toggle('data-task-engine', taskEngineOn(), '任務引擎'))];
    if (taskEngineOn()) {
      rows.push(settingRow('結論後的執行方式', '主持人排好工作後', dropdown('taskExecution', s.taskExecution === 'lowrisk' ? 'lowrisk' : 'ask', [{id: 'ask', name: '先問我', hint: '每次都等你按「照這個做」'}, {id: 'lowrisk', name: '低風險直接做', hint: '不改檔案、不對外動作的工作直接開始，其他仍先問'}], 'data-task-execution')));
      rows.push(settingRow('依驗收紀錄派工', '某家模型在某類工作的驗收通過率明顯偏低時，改派給表現較好的成員；原因寫在任務板上', toggle('data-task-learn', s.taskLearn !== false, '依驗收紀錄派工')));
      rows.push(settingRow('同時進行的工作', '一個群組同時最多幾項', dropdown('taskMax', String(s.taskMax || 4), TASK_COUNTS(6), 'data-task-max')));
      for (const p of (state.providers || []).filter(p => p.installed && p.tools)) {
        rows.push(settingRow(esc(p.name), '這個 CLI 同時最多幾項（每個帳號各自計算）', dropdown('taskCli-' + p.id, String((s.taskCliLimits || {})[p.id] || 3), TASK_COUNTS(4), `data-task-cli="${esc(p.id)}"`)));
      }
    }
    return `<h2 class="settings-h">任務引擎</h2><div class="setting-list">${rows.join('')}</div>`;
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
