  // A question asked on the page itself, never the browser's own confirm box: it does not show in the built-in browser or some
  // embedded views, so pressing 刪除 there did nothing at all (#175, #192). It sits above any open window (the Bot form stays as it was),
  // and Esc, a click outside it and 取消 all mean no.
  //   lines: what goes away, whether it can be brought back, what else changes; each a line of plain text.
  //   run:   the work itself, done while the dialog shows 處理中… with both buttons off, so a second press sends nothing twice.
  //          It closes afterwards either way; a failure is passed on to the caller (which shows it).
  // Resolves true when the person said yes (after run, when given), false otherwise.
  function ask({title, lines = [], ok = '刪除', danger = true, run = null}) {
    $('#ask-root')?.dispatchEvent(new Event('ask-cancel'));  // only one question at a time; an older one counts as no
    const back = document.activeElement, root = document.createElement('div');
    root.id = 'ask-root';
    root.innerHTML = `<div class="modal-overlay ask-overlay"><section class="modal ask" role="alertdialog" aria-modal="true" aria-labelledby="ask-title" aria-describedby="ask-body"><div class="modal-head"><h2 id="ask-title">${esc(title)}</h2></div><div class="modal-body" id="ask-body">${lines.filter(Boolean).map(x => `<p>${esc(x)}</p>`).join('')}</div><div class="modal-foot"><button type="button" class="secondary" data-ask="no">取消</button><button type="button" class="${danger ? 'danger-btn' : 'primary'}" data-ask="yes">${esc(ok)}</button></div></section></div>`;
    document.body.appendChild(root);
    const yes = root.querySelector('[data-ask="yes"]'), no = root.querySelector('[data-ask="no"]');
    (danger ? no : yes).focus();  // Enter on a delete question keeps things as they are
    return new Promise((resolve, reject) => {
      let busy = false;
      const close = () => { document.removeEventListener('keydown', keys, true); root.remove(); if (back?.isConnected) back.focus?.(); };
      const cancel = () => { if (busy) return; close(); resolve(false); };
      const keys = e => {  // ahead of the page's own keys: Esc must not also close the window underneath
        if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); cancel(); }
        else if (e.key === 'Tab') { e.preventDefault(); e.stopImmediatePropagation(); (document.activeElement === yes ? no : yes).focus(); }
        else if (e.key === 'Enter' && !e.isComposing) e.stopImmediatePropagation();  // the button in focus takes it; nothing else does
      };
      document.addEventListener('keydown', keys, true);
      root.addEventListener('ask-cancel', cancel);
      root.addEventListener('click', async e => {
        e.stopPropagation();
        if (e.target.classList.contains('ask-overlay') || e.target === no) return cancel();
        if (e.target !== yes || busy) return;
        if (!run) { close(); return resolve(true); }
        busy = true; yes.disabled = no.disabled = true; yes.textContent = '處理中…'; root.querySelector('.ask').setAttribute('aria-busy', 'true');
        try { await run(); close(); resolve(true); } catch (err) { close(); reject(err); }
      });
    });
  }
