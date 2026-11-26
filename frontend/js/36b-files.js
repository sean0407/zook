
  // Files a reply mentions by name, shown right under it: pictures as pictures, every other file as a card that opens a preview
  // (PDF, text, Markdown) or downloads it. A Bot's conversation looks in that Bot's outputs; a group also in its shared files.
  const fileKB = n => n == null ? '' : n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  if (!state.fileMarks) state.fileMarks = {};
  // The Bot's outputs, fetched again whenever it has finished another reply (it may have made a file), and while one runs each
  // time its CLI reports writing a file or running a command (#53): 產出 shows a file once it is written, not when the reply ends.
  const liveMark = botId => Object.values(state.jobDetails || {}).filter(j => j.botId === botId && j.status === 'running').map(j => j.id + '.' + (j.progress?.write || 0) + '.' + (j.progress?.command || 0)).join(',');
  function botFiles(botId, mark) {
    if (!botId) return [];
    mark = mark + '|' + liveMark(botId);
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
    // A picture shows as a picture and, like every other file, gets its card with 預覽 and 下載 (#154①).
    const pics = found.filter(f => f.kind === 'image');
    return `<div class="msg-files">${pics.length ? `<div class="msg-pics">${pics.map(f => `<button type="button" class="msg-pic" ${f.open} title="${esc(f.name + (twice.has(f.name) ? '（' + f.from + '）' : ''))}"><img src="${esc(f.url)}" alt="${esc(f.name)}" loading="lazy"></button>`).join('')}</div>` : ''}${found.map(f => `<div class="msg-file"><span class="msg-file-icon" aria-hidden="true">${fileIcon(f.name)}</span><span class="msg-file-name" title="${esc(f.name)}"><strong>${esc(midName(f.name, 40))}</strong><small>${esc(fileKB(f.size) + (twice.has(f.name) ? ' · ' + f.from : ''))}</small></span>${f.kind === 'file' ? '' : `<button type="button" class="link" ${f.open}>預覽</button>`}${f.size > 20 * 1048576 ? '' : `<a class="link" href="${esc(f.url)}" download="${esc(f.name)}">下載</a>`}</div>`).join('')}</div>`;
  }
  // A shared file's preview: the same window as a Bot's outputs.
  async function openGroupFile(groupId, name) {
    const f = (state.groupFiles[groupId] || []).find(x => x.name === name);
    if (!f) return;
    const url = '/api/groups/' + encodeURIComponent(groupId) + '/files/' + encodeURIComponent(name);
    let body = '<p class="muted">這種檔案無法在這裡預覽，可以下載。</p>';
    if (f.kind === 'image') body = `<div class="image-view"><img src="${esc(url)}" alt="${esc(name)}"></div>`;
    else if (f.kind === 'pdf' || f.kind === 'office') body = officeShell(url, name, f.kind);  // pictures of its pages (#239 #334), an Excel file's tables (#320)
    else if (['text', 'markdown', 'html'].includes(f.kind)) {
      try {
        const res = await fetch(url); if (!res.ok) throw Error('讀取失敗');
        const text = await res.text();
        body = f.kind === 'html' ? htmlFrame(text.slice(0, 2000000), name) : f.kind === 'markdown' ? `<div class="md output-text">${markdown(text.slice(0, 200000))}</div>` : `<pre class="output-text">${esc(text.slice(0, 200000))}</pre>`;
      } catch (error) { body = `<p class="error-text">${esc(error.message)}</p>`; }
    }
    modal(name, `<div class="modal-body">${body}</div><div class="modal-foot"><a class="secondary button-link" href="${esc(url)}" download="${esc(name)}">下載</a></div>`, '', 'viewer');  // #270: × alone closes it
    fillOfficeView();
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
