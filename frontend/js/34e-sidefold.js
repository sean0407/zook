  // At 480 wide or less the sidebar sits on top of the conversation (user 2026-11-27, #337⑥): it is folded to its top line by
  // default, ☰ opens it, and picking a Bot, a group or a page folds it again. Wider windows never fold it (style.css).
  const SIDE_FOLD_CLOSE = ['select-bot', 'select-group', 'page', 'open-message', 'edit-note', 'new-bot', 'new-group'];
  const sideFolding = () => window.matchMedia('(max-width: 480px)').matches;
  document.addEventListener('click', e => {  // before the page's own handler, so what it draws next is already folded
    if (e.target.closest?.('[data-side-fold]')) { state.sideOpen = !state.sideOpen; render(true); return; }
    const el = e.target.closest?.('.sidebar [data-action]');
    if (!el || !sideFolding()) return;
    if (el.dataset.action === 'search-focus' && !state.sideOpen) { state.sideOpen = true; render(true); }  // the search box is in the folded part
    else if (state.sideOpen && SIDE_FOLD_CLOSE.includes(el.dataset.action)) state.sideOpen = false;
  }, true);
