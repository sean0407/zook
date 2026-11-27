  // The Bot form and the other windows (#43 #44 #115 #120 #156 #205 #209 #224): what is still missing is said next to the button
  // that was pressed, each long text says how much it may hold, a name another Bot already has is pointed out, and 帳號／備用模型
  // say what they do. Nothing here blocks saving except an empty required field or 指定資料夾 without a folder.
  const TEXT_LIMITS = {name: 80, persona: 20000, instructions: 10000};  // the Mac keeps at most 100 / 20,000 / 10,000 (fields.py)
  const needName = x => x.dataset.needName || (x.closest('label')?.firstChild?.nodeType === 3 ? x.closest('label').firstChild.textContent : '').replace(/（.*$/, '').trim() || x.getAttribute('aria-label') || '這一欄';
  const missingFields = form => [...form.elements].filter(x => x.required && !x.disabled && !x.closest('[hidden]') && !String(x.value).trim());
  // One line beside the form's buttons. kind tells what it is about, so it goes away once that is fixed.
  function formNote(form, text, kind = 'need') {
    const foot = form?.querySelector('.modal-foot');
    if (!foot) return;
    let note = foot.querySelector('.form-need');
    if (kind !== 'folder') form.querySelector('.row-need')?.classList.remove('row-need');
    if (!text) { note?.remove(); return; }
    if (!note) { note = document.createElement('p'); note.className = 'form-need'; note.setAttribute('role', 'alert'); (foot.querySelector('button.secondary') || foot.querySelector('button.primary'))?.before(note); }
    note.dataset.kind = kind; note.textContent = text;
  }
  function sayMissing(form) {
    const names = [...new Set(missingFields(form).map(needName))];
    formNote(form, names.length ? '還沒填：' + names.join('、') + '。' : '');
  }
  // 存取範圍 is 指定資料夾 but no folder was picked: open 進階設定 at that row and say so beside the button (#205④).
  function needFolder(form) {
    const row = form.querySelector('[data-access-folder]');
    row?.closest('details')?.setAttribute('open', '');
    row?.classList.add('row-need'); row?.scrollIntoView({block: 'center'});
    formNote(form, '存取範圍選了「指定資料夾」：請按「選擇資料夾…」選一個，或改選別的範圍。', 'folder');
  }
  function recheckForm(form) {
    const note = form?.querySelector('.form-need');
    if (!note || ['conflict', 'same'].includes(note.dataset.kind)) return;  // 「已在別處修改」 stays until the window is opened again
    if (note.dataset.kind !== 'folder') { sayMissing(form); return; }
    if (form.elements.access?.value !== 'folder' || form.elements.accessFolder?.value) { formNote(form, ''); form.querySelector('.row-need')?.classList.remove('row-need'); }
  }
  function countLine(field) {
    const limit = TEXT_LIMITS[field?.name], el = limit && field.form?.querySelector(`[data-count-for="${field.name}"]`);
    if (!el) return;
    const n = field.value.length, full = n >= limit;
    if (field.name === 'name') { el.hidden = n < limit - 10; el.textContent = full ? `名稱最多 ${limit} 字，多的字不會打進去。` : `名稱最多 ${limit} 字（已 ${n} 字）。`; }
    else el.textContent = `${n.toLocaleString()} / ${limit.toLocaleString()} 字` + (n > limit ? `：多了 ${(n - limit).toLocaleString()} 字，請刪短一點` : full ? '：已到上限，多的字沒有放進來' : '');
    el.classList.toggle('at-limit', full);
  }
  // Another Bot with the same name can still be made; the form only says that the two will be hard to tell apart (#115①).
  function nameTaken(form) {
    const el = form.querySelector('[data-name-taken]'), name = String(form.elements.name?.value || '').trim();
    if (!el) return;
    const other = name && (state.data.bots || []).find(x => x.id !== form.dataset.id && String(x.name || '').trim() === name);
    el.hidden = !other;
    el.textContent = other ? `已經有一個叫「${name}」的 Bot。可以照樣${form.dataset.id ? '儲存' : '建立'}，但側欄和 @ 指名時會分不清，建議換個名字。` : '';
  }
  const smallNote = (cls, attr) => { const el = document.createElement('small'); el.className = cls; el.setAttribute(attr, ''); return el; };
  function setRowText(row, text) {
    const copy = row?.querySelector('.setting-copy');
    if (!copy) return;
    (copy.querySelector('span') || copy.appendChild(document.createElement('span'))).textContent = text;
  }
  function polishBotForm(form, b = {}) {
    const name = form.elements.name, persona = form.elements.persona, instructions = form.elements.instructions;
    name.dataset.needName = '名稱'; name.placeholder = '為 Bot 命名（必填）';
    // 人格檔案 is needed when editing too, as when making one; only a Bot that never had one may stay without (#156).
    if (b.id && String(b.persona || '').trim()) { persona.required = true; persona.dataset.need = persona.dataset.need || '請填寫人格檔案。'; }
    const label = persona.closest('label');
    if (label?.firstChild?.nodeType === 3) {
      label.firstChild.textContent = '人格檔案';
      if (persona.required) { const mark = document.createElement('span'); mark.className = 'need-mark'; mark.textContent = '必填'; label.firstChild.after(mark); }
    }
    instructions.maxLength = TEXT_LIMITS.instructions;
    const names = form.querySelector('.bot-names');
    names.append(smallNote('field-hint char-count', 'data-count-for'), smallNote('field-hint name-taken', 'data-name-taken'));
    names.querySelector('[data-count-for]').dataset.countFor = 'name';
    for (const field of [persona, instructions]) { const el = smallNote('field-hint char-count muted', 'data-count-for'); el.dataset.countFor = field.name; field.after(el); }
    [name, persona, instructions].forEach(countLine);
    nameTaken(form);
    // 帳號 and 備用模型 in words (#43): what the menu decides, where other accounts come from, and that the same CLI is never a fallback.
    const accounts = form.querySelector('[data-action="accounts-from-form"]')?.parentElement;
    if (accounts?.firstChild?.nodeType === 3) accounts.firstChild.textContent = '這個 Bot 用哪一家、哪個帳號回覆。同一家的其他帳號要先到「各模型使用量」按「＋ 帳號」加入。';
    setRowText(form.querySelector('[data-fixed-model] .setting-row'), '額度用完或出錯時，這一則依序改用：同一家其他帳號（開著「自動選用」的訂閱帳號）→ 這裡選的家；剩不到 20% 的排最後，API 計費的不會換上，回覆裡會註明。選「不自動換」只是不換別家');
    setRowText(form.querySelector('input[name="section"]')?.closest('.setting-row'), '放在左側哪一組，只影響排列');
    setRowText(form.querySelector('input[name="effort"]')?.closest('.setting-row'), '回答前想多久；想越久越仔細，也越慢、用量越多');
    form.dataset.firstChoice = form.elements.providerChoice?.value ?? '';
  }
  // The text under 備用模型's 預設 line: the order 設定 gives, without the Bot's own CLI, which is never switched to.
  function fallbackDefaultLabel(id) {
    const chain = state.data.settings.fallbacks || [], left = chain.filter(x => x !== id).map(providerShort);
    return '預設（' + (left.length ? '先換同一家其他帳號，再依剩餘額度換 ' + left.join('、') + '；剩不到 20% 的最後' : '目前是不換別家，只換同一家其他帳號') + '）';  // #33
  }
  document.addEventListener('input', e => {
    const form = e.target.closest?.('form');
    if (!form) return;
    countLine(e.target);
    if (form.id === 'bot-form' && e.target.name === 'name') nameTaken(form);
    recheckForm(form);
  });
  document.addEventListener('change', e => {
    const form = e.target.closest?.('form');
    if (!form) return;
    recheckForm(form);
    if (form.id !== 'bot-form' || e.target.name !== 'providerChoice') return;
    // 自動配好… is about the model it was given; once another one is picked it no longer applies (#205③).
    form.querySelector('[data-auto-reason]')?.toggleAttribute('hidden', e.target.value !== form.dataset.firstChoice);
    // A different CLI: the model menu still lists the last one's models until the new list comes, so it is emptied now (#43⑥).
    const provider = e.target.value.split('::')[0];
    if (provider !== form.elements.provider.value && provider !== 'auto') { form.elements.modelSelect.innerHTML = '<option value="">正在讀取這一家的型號…</option>'; form.elements.modelSelect.disabled = true; mirrorSelects(form); }
  });
  // Picking a model by hand ends the 「換了一家，型號已改回…」 line: it is about the model Zook chose (#43⑤).
  document.addEventListener('change', e => {
    if (e.target.name !== 'modelSelect') return;
    const note = e.target.form?.querySelector('.model-note');
    if (note) note.textContent = note.textContent.replace(/^換了一家[^。]*。/, '');
  });
  // #162 (G46): what 編輯 Bot edits, as the Bot was when the window opened; the Mac refuses the save if it changed since (fields.py).
  const BOT_FORM_KEYS = ['name', 'jobTitle', 'persona', 'instructions', 'provider', 'model', 'account', 'effort', 'section', 'pinned', 'fallbacks', 'features', 'access', 'accessFolder', 'shape', 'color'];
  const botBase = b => Object.fromEntries(BOT_FORM_KEYS.map(k => [k, b[k] === undefined ? null : JSON.parse(JSON.stringify(b[k]))]));
  // One of the form's own menus (思考強度…) set from code, as picking it would: the hidden value, the label and the tick.
  function setDropdown(form, name, value) {
    const input = form.querySelector(`.dd input[name="${name}"]`), dd = input?.closest('.dd'), chosen = dd?.querySelector(`.dd-opt[data-value="${CSS.escape(value)}"]`);
    if (!chosen) return;
    input.value = value; dd.querySelector('.dd-label').textContent = chosen.dataset.label;
    dd.querySelectorAll('.dd-opt').forEach(o => { o.classList.toggle('selected', o === chosen); o.setAttribute('aria-selected', o === chosen); });
  }
