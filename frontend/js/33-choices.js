
  // Choices answered with one click: the options a Bot lists at the end of a reply, and a question it asks in the middle of its work.
  if (!state.answering) state.answering = {};
  if (!state.answerDraft) state.answerDraft = {};
  // Questions closed with 知道了, kept in this browser so a reload does not bring them back (only a convenience: nothing depends on it).
  if (!state.seenQuestions) { state.seenQuestions = {}; try { state.seenQuestions = JSON.parse(localStorage.getItem('zook-seen-questions') || '{}') || {}; } catch (_) {} }
  const choicesOn = () => state.data?.settings?.choiceButtons !== false;

  // Only under the newest reply, and only while nothing else is on its way.
  function choiceButtons(b, messages, running) {
    const last = messages[messages.length - 1];
    if (!choicesOn() || running || !last || last.role === 'user' || last.status !== 'completed' || !Array.isArray(last.options) || (b.queue || []).length) return '';
    return `<div class="choice-row" role="group" aria-label="選項">${last.options.map(o => `<button type="button" class="choice-btn" data-choice="${esc(o)}" title="放進輸入框，按 ↑ 才送出">${esc(o)}</button>`).join('')}</div>`;
  }

  function pendingQuestions(botId) { return jobsForBot(botId).filter(j => j.status === 'running').flatMap(j => (j.questions || []).filter(q => q.status === 'pending')); }
  function questionCards(botId) {
    const who = state.data.bots.find(x => x.id === botId)?.name || 'Bot';
    return pendingQuestions(botId).map(q => `<section class="question-card" aria-label="Bot 的提問"><strong>${esc(who)} 想問你</strong><p>${esc(q.question)}</p>
      ${(q.options || []).length ? `<div class="choice-row">${q.options.map(o => `<button type="button" class="choice-btn" data-answer="${esc(q.id)}" data-text="${esc(o)}" ${state.answering[q.id] ? 'disabled' : ''}>${esc(o)}</button>`).join('')}</div>` : ''}
      <form class="answer-form" data-answer-form="${esc(q.id)}"><input type="text" maxlength="2000" placeholder="${(q.options || []).length ? '或自己回答' : '輸入你的回答'}" aria-label="自己回答" value="${esc(state.answerDraft[q.id] || '')}" data-answer-draft="${esc(q.id)}"><button class="secondary" ${state.answering[q.id] ? 'disabled' : ''}>送出</button></form>
      <small class="approval-reason">回答只會告訴 Bot 你的選擇；它之後要做的動作仍照你設定的主動性核准。</small></section>`).join('');
  }

  // #248: a question the Bot stopped waiting for stays in sight, greyed, with why; Zook never answers in the user's place.
  function goneQuestions(botId) {
    const bot = state.data.bots.find(x => x.id === botId), who = bot?.name || 'Bot';
    // A reply that ended on its own with the question open (not one you stopped) also stopped waiting for it (巡檢 H02).
    const gone = jobsForBot(botId).filter(j => !j.chatId || !bot?.chatId || j.chatId === bot.chatId).flatMap(j => (j.questions || []).filter(q => q.status === 'expired' && (['timeout', 'gone'].includes(q.expiredWhy) || q.expiredWhy === 'ended' && j.status !== 'cancelled' && j.status !== 'running') && !state.seenQuestions[q.id]));  // until 知道了
    return gone.map(q => `<section class="question-card stale" role="status"><strong>${esc(q.expiredWhy === 'timeout' ? `${who} 等了 10 分鐘沒等到你的回答，已先停在這一步` : q.expiredWhy === 'gone' ? `${who} 已不再等這個問題的回答（它可能改用別的做法，或已經停下）` : `${who} 沒等到你的回答就結束了這次回覆`)}</strong><p>${esc(q.question)}</p>
      <small class="approval-reason">Zook 沒有替你選，Bot 也不會當成你拒絕。要回答的話，直接在下面輸入，Bot 會接著做。</small><div class="actions"><button class="secondary" data-action="dismiss-question" data-id="${esc(q.id)}">知道了</button></div></section>`).join('');
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
      // #89: put into the message box, not sent. When the page moves under the pointer (a file card arriving above), a click
      // that lands here by mistake changes nothing; the user reads it, edits it if needed, and presses ↑.
      const input = $('#chat-input');
      if (pick.disabled || !input) return;
      const typed = input.value.replace(/\s+$/, '');
      input.value = typed ? typed + '\n' + pick.dataset.choice : pick.dataset.choice;
      input.focus(); input.setSelectionRange(input.value.length, input.value.length);
      input.dispatchEvent(new Event('input', {bubbles: true}));  // the box grows to fit, as when typing
      return;
    }
    const seen = e.target.closest('[data-action="dismiss-question"]');
    if (seen) { state.seenQuestions[seen.dataset.id] = true; try { localStorage.setItem('zook-seen-questions', JSON.stringify(Object.fromEntries(Object.entries(state.seenQuestions).slice(-200)))); } catch (_) {} render(true); return; }
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

  document.addEventListener('change', async e => {
    if (e.target.dataset.backgroundRuns === undefined) return;
    try { state.data.settings = await post('settings', {backgroundRuns: e.target.checked}, 'PATCH'); toast(e.target.checked ? '結束 Zook 時，進行中的回覆會繼續在背景跑' : '結束 Zook 時會停止進行中的回覆'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  });

  document.addEventListener('change', async e => {
    if (e.target.dataset.keepCli === undefined) return;
    try { state.data.settings = await post('settings', {keepCli: e.target.checked}, 'PATCH'); toast(e.target.checked ? '同一個對話會保持 CLI 開啟' : '每則回覆都重新啟動 CLI'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  });
