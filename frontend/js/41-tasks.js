  // 任務引擎: the task board in a group, and its switch in 設定. The work itself is run by the Mac (backend/zook/taskrun.py).
  const TASK_STATE = {pending: '等前面的工作', ready: '待開始', running: '進行中', asked: '等主持人回答', blocked: '卡住了', verifying: '驗收中',
    done: '完成', failed: '沒有完成', stuck: '已停下，等你決定', unknown: '狀態不明', cancelled: '已停止'};
  const TASK_TONE = {done: 'ok', failed: 'bad', stuck: 'bad', unknown: 'warn', asked: 'warn', blocked: 'warn', cancelled: 'muted', running: 'live', verifying: 'live'};
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
      const detail = [last.summary, t.status === 'asked' && t.question ? '問主持人：' + t.question : '', last.reason, t.note, Array.isArray(last.files) && last.files.length ? '產出：' + last.files.join('、') : '', attempts.length > 1 ? `第 ${attempts.length} 次` : ''].filter(x => typeof x === 'string' && x);
      return `<li class="task-row"><span class="pill ${TASK_TONE[t.status] || ''}">${esc(TASK_STATE[t.status] || t.status)}</span><span class="task-title"><strong>${esc(String(t.n))}. ${esc(String(t.title))}</strong> <span class="muted">${esc(name(t.assignee))}</span>${detail.length ? `<span class="task-detail">${esc(detail.join(' · '))}</span>` : ''}</span></li>`;
    }).join('');
    const live = run.status === 'running' ? '<span class="browsing-dot" aria-hidden="true"></span>' : '';
    return `<details class="task-board" data-task-board="${esc(run.id)}" ${state.taskOpen?.[run.id] ? 'open' : ''}><summary>${live}<strong>任務板</strong> <span class="muted">${head}${run.status === 'stopped' ? ' · 已停止' : ''}</span></summary>${rows ? `<ol class="task-list">${rows}</ol>` : ''}</details>`;
  }

  const taskSection = () => `<h2 class="settings-h">任務引擎</h2><div class="setting-list">${settingRow('任務引擎', '群組多一種討論方式「自動（主持人決定）」：主持人拆工作、派給成員同時進行，成員回報後再整理結果', toggle('data-task-engine', taskEngineOn(), '任務引擎'))}</div>`;

  // The board stays open or closed as the reader left it, while the page redraws it.
  document.addEventListener('toggle', e => { const id = e.target.dataset?.taskBoard; if (id) (state.taskOpen = state.taskOpen || {})[id] = e.target.open; }, true);
  document.addEventListener('change', async e => {
    if (e.target.dataset?.taskEngine === undefined) return;
    try { state.data.settings = await post('settings', {taskEngine: e.target.checked}, 'PATCH'); toast(e.target.checked ? '群組可以選「自動（主持人決定）」了' : '已關閉任務引擎'); }
    catch (error) { e.target.checked = !e.target.checked; toast(error.message); }
    render(true);
  });
