
  // Files a reply mentions by name, shown right under it: pictures as pictures, every other file as a card that opens a preview
  // (PDF, text, Markdown) or downloads it. A Bot's conversation looks in that Bot's outputs; a group also in its shared files.
  const FILE_ICON = {image: '🖼', pdf: '📕', markdown: '📝', text: '📄', file: '📎'};
  const fileKB = n => n == null ? '' : n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  if (!state.fileMarks) state.fileMarks = {};
  // The Bot's outputs, fetched again whenever it has finished another reply (it may have made a file).
  function botFiles(botId, mark) {
    if (!botId) return [];
    if (state.outputs[botId] === undefined || state.fileMarks['bot:' + botId] !== mark) { state.fileMarks['bot:' + botId] = mark; if (state.outputs[botId] === undefined) state.outputs[botId] = null; setTimeout(() => loadOutputs(botId, true), 0); }
    return (state.outputs[botId] || []).map(o => ({name: o.name, kind: o.kind, size: o.size, url: '/api/bots/' + encodeURIComponent(botId) + '/outputs/' + encodeURIComponent(o.id) + '?v=' + encodeURIComponent((o.at || '') + o.size), from: '產出', open: `data-action="output-open" data-id="${esc(o.id)}" data-bot="${esc(botId)}"`}));
  }
  function groupSharedFiles(g, mark) {
    if (state.groupFiles[g.id] === undefined || state.fileMarks['group:' + g.id] !== mark) { state.fileMarks['group:' + g.id] = mark; if (state.groupFiles[g.id] === undefined) state.groupFiles[g.id] = null; setTimeout(() => loadGroupFiles(g), 0); }
    return (state.groupFiles[g.id] || []).map(f => ({name: f.name, kind: f.kind || 'file', size: f.size, url: '/api/groups/' + encodeURIComponent(g.id) + '/files/' + encodeURIComponent(f.name) + '?v=' + encodeURIComponent((f.at || '') + f.size), from: '群組檔案', open: `data-group-file="${esc(f.name)}" data-group="${esc(g.id)}"`}));
  }
  function messageFiles(text, items) {
    const said = String(text || ''), seen = new Set();
    // 「~$報告.docx」 is Office's lock file, not 報告.docx: it never gets a card of its own, nor makes the real file's card appear.
    const named = name => { for (let at = said.indexOf(name); at >= 0; at = said.indexOf(name, at + 1)) { const before = said[at - 1] || ' ', after = said[at + name.length] || ' '; if (!/[\w.\-$]/.test(before) && !/\w/.test(after)) return true; } return false; };
    const found = items.filter(f => f.name.length >= 3 && !/^(~\$|\.~lock\.)/.test(f.name) && named(f.name) && !seen.has(f.url) && seen.add(f.url)).slice(0, 12);
    const twice = new Set(found.filter((f, i) => found.findIndex(x => x.name === f.name) !== i).map(f => f.name));
    if (!found.length) return '';
    const pics = found.filter(f => f.kind === 'image'), rest = found.filter(f => f.kind !== 'image');
    return `<div class="msg-files">${pics.length ? `<div class="msg-pics">${pics.map(f => `<button type="button" class="msg-pic" ${f.open} title="${esc(f.name + (twice.has(f.name) ? '（' + f.from + '）' : ''))}"><img src="${esc(f.url)}" alt="${esc(f.name)}" loading="lazy"></button>`).join('')}</div>` : ''}${rest.map(f => `<div class="msg-file"><span class="msg-file-icon" aria-hidden="true">${FILE_ICON[f.kind] || FILE_ICON.file}</span><span class="msg-file-name"><strong>${esc(f.name)}</strong><small>${esc(fileKB(f.size) + (twice.has(f.name) ? ' · ' + f.from : ''))}</small></span>${f.kind === 'file' ? '' : `<button type="button" class="link" ${f.open}>預覽</button>`}<a class="link" href="${esc(f.url)}" download="${esc(f.name)}">下載</a></div>`).join('')}</div>`;
  }
  // A shared file's preview: the same window as a Bot's outputs.
  async function openGroupFile(groupId, name) {
    const f = (state.groupFiles[groupId] || []).find(x => x.name === name);
    if (!f) return;
    const url = '/api/groups/' + encodeURIComponent(groupId) + '/files/' + encodeURIComponent(name);
    let body = '<p class="muted">這種檔案無法在這裡預覽，可以下載。</p>';
    if (f.kind === 'image') body = `<div class="image-view"><img src="${esc(url)}" alt="${esc(name)}"></div>`;
    else if (f.kind === 'pdf') body = pdfFrame(url, name);
    else if (f.kind === 'text' || f.kind === 'markdown') {
      try {
        const res = await fetch(url); if (!res.ok) throw Error('讀取失敗');
        const text = (await res.text()).slice(0, 200000);
        body = f.kind === 'markdown' ? `<div class="md output-text">${markdown(text)}</div>` : `<pre class="output-text">${esc(text)}</pre>`;
      } catch (error) { body = `<p class="error-text">${esc(error.message)}</p>`; }
    }
    modal(name, `<div class="modal-body">${body}</div><div class="modal-foot"><a class="secondary" href="${esc(url)}" download="${esc(name)}">下載</a><button type="button" class="primary" data-action="close-modal">關閉</button></div>`, '', true);
    showPdfWhenReady();
  }
  document.addEventListener('click', e => {
    const el = e.target.closest?.('[data-group-file]');
    if (el) openGroupFile(el.dataset.group, el.dataset.groupFile);
  });
  // A picture that arrives after the page was drawn keeps the newest message in view when you were reading at the bottom.
  document.addEventListener('load', e => {
    if (e.target.tagName !== 'IMG' || !e.target.closest('.msg-pic')) return;
    const box = $('#conversation'); if (!box || !box.contains(e.target)) return;
    if (box.scrollHeight - box.scrollTop - box.clientHeight - e.target.offsetHeight < 160) box.scrollTop = box.scrollHeight;
  }, true);
