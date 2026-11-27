  // G49–G52 (#324 #309①⑤ #196 #333 #281③): what the Bot form still left unsaid.

  // 備用模型 after 建立: one clause on what happens when the account runs out; a Bot made on an account that cannot answer now
  // says what its next message does instead (#324①).
  function createdWords(made, botId, sent, auto) {
    const nb = state.data.bots.find(x => x.id === botId), t = nb && botTrouble(nb);
    if (t) return made + '。' + troubleText(t, botProvider(nb), nb.fallbacks, nb.nextBackup ?? '');
    if (auto) return made;  // 自動配 already says what it picked
    const own = nb ? nb.fallbacks : sent, chain = Array.isArray(own) ? own : state.data.settings.fallbacks || [];  // null: the order in 設定
    const none = !chain.length;
    return made + (none ? '，可以開始對話了。額度用完時不會換別家（在「編輯 Bot → 進階設定」可以改）' : '，可以開始對話了。額度用完時會換備用模型，回覆裡會註明');
  }

  // A new Bot whose name another Bot has: the first press says so beside the button, a second press makes it anyway (#309①).
  function sameNameAgain(form, name) {
    const taken = (state.data.bots || []).some(x => String(x.name || '').trim() === name);
    if (!taken || form.dataset.sameName === name) return false;
    form.dataset.sameName = name;
    formNote(form, `已經有一個叫「${name}」的 Bot。再按一次「建立 Bot」照樣建立，或換個名字。`, 'same');
    return true;
  }

  // What a new Bot still needs, in small type beside the buttons from the start, so 人格檔案 is not found out only on 建立 (#309⑤).
  function formTodo(form) {
    const el = form?.querySelector('[data-form-todo]');
    if (!el) return;
    const names = [...new Set(missingFields(form).map(needName))], loud = form.querySelector('.form-need');
    el.textContent = names.length ? '建立前要填：' + names.join('、') : '';
    el.hidden = !names.length || !!loud;
  }
  const PERSONA_SAMPLE = '親切、有條理的助理。先給結論再補細節，用條列整理重點；不確定的地方直接說不確定，需要我決定的事先問我。';

  // 自動配 hides 備用模型: the reason takes its place. Both rows go to 設定 → 模型 for the order every Bot follows (#324②⑤).
  function polishBotFormMore(form, b = {}) {
    const fixed = form.querySelector('[data-fixed-model]');
    if (fixed) {
      const why = document.createElement('div');
      why.dataset.autoFallback = ''; why.hidden = !fixed.hidden;
      why.innerHTML = settingRow('備用模型', '選「自動配」時，建立後才知道用哪一家，所以先跟著預設的備用順序；建立後可以在「編輯 Bot」改。' + FALLBACK_LINK, '');
      fixed.after(why);
      fixed.querySelector('.setting-copy')?.insertAdjacentHTML('beforeend', `<small class="muted">${FALLBACK_LINK}</small>`);
    }
    if (b.id) return;
    const foot = form.querySelector('.modal-foot'), todo = document.createElement('small');
    todo.className = 'muted small form-todo'; todo.dataset.formTodo = '';
    foot?.querySelector('button.secondary')?.before(todo);
    const persona = form.elements.persona;
    persona?.insertAdjacentHTML('afterend', '<button type="button" class="link persona-sample" data-action="persona-sample">不知道寫什麼？填入範例</button>');
    formTodo(form);
  }
  const FALLBACK_LINK = '預設順序在「設定 → 模型」。<button type="button" class="link" data-action="fallback-settings">前往設定</button>';

  document.addEventListener('input', e => {
    const form = e.target.closest?.('#bot-form');
    if (!form) return;
    if (e.target.name === 'name' && form.dataset.sameName && form.dataset.sameName !== e.target.value.trim()) { delete form.dataset.sameName; if (form.querySelector('.form-need')?.dataset.kind === 'same') formNote(form, ''); }
    formTodo(form);
  });
  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-action="persona-sample"],[data-action="fallback-settings"]');
    if (!el) return;
    e.preventDefault();
    if (el.dataset.action === 'persona-sample') {
      const persona = el.form?.elements.persona || $('#bot-form')?.elements.persona;
      if (!persona) return;
      if (!persona.value.trim()) { persona.value = PERSONA_SAMPLE; persona.dispatchEvent(new Event('input', {bubbles: true})); }
      persona.focus();
      return;
    }
    if ($('#bot-form') && !(await leaveModalForm())) return;  // the Bot form with changes asks first (#297)
    if ($('#bot-form')) closeModal();
    await loadPage('settings');
    const slot = document.querySelector('[data-fallback-slot]');
    slot?.closest('.setting-row')?.scrollIntoView({block: 'center'});
    slot?.closest('.dd')?.querySelector('button')?.focus({preventScroll: true});
  });

  // 長任務 and 先規劃 as switches in 更多選項 (#196), next to the 思考強度 menu; typing /goal or /plan still works.
  function longPlanRows() {
    if (activeGroup() || !state.selected) return '';
    const id = state.selected, planOk = effortSupported();
    return settingRow('長任務', '下一則訊息最長可以跑 4 小時，結束時通知你', toggle('data-long', state.long[id], '長任務'))
      + settingRow('先規劃', planOk ? '下一則訊息只請 Bot 提出計畫，不動手' : '這個 Bot 的模型不支援先規劃', toggle('data-plan' + (planOk ? '' : ' disabled'), planOk && state.plan[id], '先規劃'));
  }

  // The CLI's own sign-in by its name (the email it signed in with, before the @ so the menu stays short), so the main account is
  // not only 「預設」 (#281③ #333⑥). The 各模型使用量 page shows the whole address.
  const mainAccountName = id => String((state.accounts?.providers || []).find(p => p.id === id)?.email || '').split('@')[0];
