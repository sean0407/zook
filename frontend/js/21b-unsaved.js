  // #297 (#20): a form window with changes asks 「要放棄修改嗎？」 before Esc, a click outside, × or 取消 closes it (編輯 Bot, 群組,
  // 排程, 知識, 連接器… every window made with modal()); with nothing changed it just closes. Saving closes it with closeModal() as before.
  // A change is what the person did: the form is noted down at their first key or click, before it takes effect, so what the page
  // fills in by itself (a new Bot's draft, the model list) is not one, and typing something and putting it back is nothing to lose.
  const modalEdit = {snap: null, touched: false, form: null};
  // modal() calls this after drawing: the same form drawn again (團隊 after a model is picked) keeps what was noted; another starts afresh.
  function modalEditsReset() {
    const id = modalRoot.querySelector('form')?.id || null;
    if (id && id === modalEdit.form) return;
    modalEdit.snap = null; modalEdit.touched = false; modalEdit.form = id;
  }
  // Before leaving a form window for another (新增帳號, 用一句話建立整個團隊, 返回): true when it may go on.
  async function leaveModalForm() {
    if (modalRoot.querySelector('form[data-busy]')) return false;  // being saved: stay until it is done
    if (!modalDirty()) return true;
    await requestCloseModal();
    return !modalRoot.querySelector('form');
  }
  function modalFields() {
    return [...modalRoot.querySelectorAll('form')].map(f => [...f.elements]
      .filter(el => el.name && el.type !== 'button' && el.type !== 'submit' && el.type !== 'search' && !('memberSearch' in el.dataset))
      .map(el => el.name + '=' + (el.type === 'checkbox' || el.type === 'radio' ? el.checked : el.type === 'file' ? [...el.files].map(x => x.name).join('/') : el.value)).join('\n')).join('\n--\n');  // a file picked to upload counts
  }
  function modalDirty() {
    return modalEdit.touched && modalEdit.snap !== null && !!modalRoot.querySelector('form') && modalFields() !== modalEdit.snap;
  }
  const noteModalForm = e => { if (e.isTrusted && modalEdit.snap === null && modalRoot.querySelector('form')) modalEdit.snap = modalFields(); };
  modalRoot.addEventListener('pointerdown', noteModalForm, true);
  modalRoot.addEventListener('keydown', noteModalForm, true);
  for (const type of ['input', 'change']) modalRoot.addEventListener(type, e => { if (e.isTrusted && e.target.closest?.('form')) modalEdit.touched = true; }, true);
  modalRoot.addEventListener('click', e => {  // the menus, shapes and colours set hidden fields by themselves
    if (e.isTrusted && e.target.closest?.('form') && !e.target.closest('[data-action="close-modal"]')) modalEdit.touched = true;
  }, true);
  let closeAsking = false;
  async function requestCloseModal() {
    if (modalRoot.querySelector('form[data-busy]')) return;  // being saved: it closes by itself, and giving it up now could not stop it
    if (!modalDirty()) return closeModal();
    if (closeAsking) return;
    closeAsking = true;
    const shown = modalRoot.firstElementChild, form = modalRoot.querySelector('form');
    try {
      const away = await ask({title: '要放棄修改嗎？', lines: ['剛才的修改還沒儲存，放棄就不會留下。'], ok: '放棄修改', keep: '繼續編輯'});
      if (!away || modalRoot.firstElementChild !== shown) return;  // 繼續編輯, or the window is already another one
      if (form?.id === 'bot-form' && !form.dataset.id) try { sessionStorage.removeItem('swarmr-new-bot-draft'); } catch (_) {}  // the new Bot's draft is what was given up
      closeModal(); modalEdit.form = null;
    } finally { closeAsking = false; }
  }
  // Enter in a field (a Bot's name, a schedule, a conversation's name) does not save and close the window (#20): 儲存 does.
  // A password still goes in with Enter, as a sign-in would.
  document.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229 || e.defaultPrevented) return;
    const el = e.target, form = el.closest?.('.modal form');
    if (!form || el.tagName !== 'INPUT' || /^(checkbox|radio|button|submit|file|range|color|password)$/.test(el.type)) return;
    e.preventDefault();
  });
