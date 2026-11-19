
  // Choices answered with one click: the options a Bot lists at the end of a reply, and a question it asks in the middle of its work.
  if (!state.answering) state.answering = {};
  if (!state.answerDraft) state.answerDraft = {};
  const choicesOn = () => state.data?.settings?.choiceButtons !== false;

  // Only under the newest reply, and only while nothing else is on its way.
  function choiceButtons(b, messages, running) {
    const last = messages[messages.length - 1];
    if (!choicesOn() || running || !last || last.role === 'user' || last.status !== 'completed' || !Array.isArray(last.options) || (b.queue || []).length) return '';
    return `<div class="choice-row" role="group" aria-label="選項">${last.options.map(o => `<button type="button" class="choice-btn" data-choice="${esc(o)}">${esc(o)}</button>`).join('')}</div>`;
  }

  function pendingQuestions(botId) { return jobsForBot(botId).flatMap(j => (j.questions || []).filter(q => q.status === 'pending')); }
  function questionCards(botId) {
    const who = state.data.bots.find(x => x.id === botId)?.name || 'Bot';
    return pendingQuestions(botId).map(q => `<section class="approval-card question-card" aria-label="Bot 的提問"><strong>${esc(who)} 想問你</strong><p>${esc(q.question)}</p>
      ${(q.options || []).length ? `<div class="choice-row">${q.options.map(o => `<button type="button" class="choice-btn" data-answer="${esc(q.id)}" data-text="${esc(o)}" ${state.answering[q.id] ? 'disabled' : ''}>${esc(o)}</button>`).join('')}</div>` : ''}
      <form class="answer-form" data-answer-form="${esc(q.id)}"><input type="text" maxlength="2000" placeholder="${(q.options || []).length ? '或自己回答' : '輸入你的回答'}" aria-label="自己回答" value="${esc(state.answerDraft[q.id] || '')}" data-answer-draft="${esc(q.id)}"><button class="secondary" ${state.answering[q.id] ? 'disabled' : ''}>送出</button></form>
      <small class="approval-reason">回答只會告訴 Bot 你的選擇；它之後要做的動作仍照你設定的主動性核准。</small></section>`).join('');
  }

  async function answerQuestion(id, text) {
    text = String(text || '').trim();
    if (!text || state.answering[id]) return;
    state.answering[id] = true; render(true);
    try {
      await post('questions/' + encodeURIComponent(id), {answer: text});
      for (const j of Object.values(state.jobDetails)) for (const q of j.questions || []) if (q.id === id) q.status = 'answered';
      delete state.answerDraft[id];
    } catch (err) { toast(err.message); }
    finally { delete state.answering[id]; render(true); }
  }

  document.addEventListener('click', e => {
    const pick = e.target.closest('[data-choice]');
    if (pick) {
      const input = $('#chat-input'), form = $('#chat-form');
      if (!input || !form) return;
      input.value = pick.dataset.choice; form.requestSubmit();
      return;
    }
    const answer = e.target.closest('[data-answer]');
    if (answer) answerQuestion(answer.dataset.answer, answer.dataset.text);
  });
  document.addEventListener('input', e => { if (e.target.dataset.answerDraft) state.answerDraft[e.target.dataset.answerDraft] = e.target.value; });
  document.addEventListener('submit', e => {
    const id = e.target.dataset.answerForm;
    if (!id) return;
    e.preventDefault(); e.stopPropagation();
    answerQuestion(id, e.target.querySelector('input').value);
  }, true);

  document.addEventListener('change', async e => {
    if (e.target.dataset.choiceButtons === undefined) return;
    try { state.data.settings = await post('settings', {choiceButtons: e.target.checked}, 'PATCH'); toast(e.target.checked ? 'Bot 可以用按鈕讓你選擇' : '已關閉選項按鈕'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  });
