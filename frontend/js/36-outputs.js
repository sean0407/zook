  // 產出: the files a Bot made or changed, with a preview.
  if (!state.outputs) state.outputs = {};
  async function loadOutputs(botId, quiet) {
    try { state.outputs[botId] = (await api('bots/' + encodeURIComponent(botId) + '/outputs')).outputs; }
    catch (error) { state.outputs[botId] = state.outputs[botId] || []; if (!quiet) toast(error.message); }
    render(true);
  }
  function outputsPanel(b) {
    const list = state.outputs[b.id];
    if (!list) { setTimeout(() => loadOutputs(b.id), 0); return '<div class="detail-empty">正在讀取產出…</div>'; }
    const icon = {image: '🖼', pdf: '📕', markdown: '📝', text: '📄', file: '📎'};
    return `<div class="detail-title">產出 <button class="link" data-action="outputs-refresh">重新整理</button></div>${list.length ? list.map(o => `<button class="note-row output-row" data-action="output-open" data-id="${esc(o.id)}" title="${esc(o.path)}"><strong>${icon[o.kind] || '📎'} ${esc(o.name)}</strong><small>${esc(fileSize(o.size))} · ${esc(formatDate(o.at))}</small></button>`).join('') : '<div class="detail-empty">這個 Bot 建立或修改過的檔案會出現在這裡。</div>'}`;
  }
  async function openOutput(botId, id) {
    const o = (state.outputs[botId] || []).find(x => x.id === id);
    if (!o) return;
    const url = '/api/bots/' + encodeURIComponent(botId) + '/outputs/' + encodeURIComponent(o.id);
    let body = '<p class="muted">這種檔案無法在這裡預覽，可以下載或在 Finder 顯示。</p>';
    if (o.kind === 'image') body = `<div class="image-view"><img src="${url}" alt="${esc(o.name)}"></div>`;
    else if (o.kind === 'pdf') body = `<iframe class="output-pdf" src="${url}" title="${esc(o.name)}"></iframe>`;
    else if (o.kind === 'text' || o.kind === 'markdown') {
      try {
        const res = await fetch(url); if (!res.ok) throw Error((await res.json().catch(() => ({}))).error || '讀取失敗');
        const text = (await res.text()).slice(0, 200000);
        body = o.kind === 'markdown' ? `<div class="md output-text">${markdown(text)}</div>` : `<pre class="output-text">${esc(text)}</pre>`;
      } catch (error) { body = `<p class="error-text">${esc(error.message)}</p>`; }
    }
    modal(o.name, `<div class="modal-body">${body}<p class="muted small output-path">${esc(o.path)}</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="output-reveal" data-id="${esc(o.id)}" data-bot="${esc(botId)}">在 Finder 顯示</button><a class="secondary button-link" href="${url}" download="${esc(o.name)}">下載</a><button type="button" class="primary" data-action="close-modal">關閉</button></div>`, '', true);
  }
  // File names of this Bot's outputs inside a reply open the preview.
  function linkOutputs(html, botId) {
    const list = (state.outputs[botId] || []).filter(o => o.name.length >= 4).slice(0, 80);
    if (!list.length) return html;
    const byName = {}; list.forEach(o => { byName[esc(o.name)] = byName[esc(o.name)] || o; });
    const re = new RegExp('(' + Object.keys(byName).sort((a, b) => b.length - a.length).map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g');
    let skip = 0;
    return html.split(/(<[^>]+>)/).map(part => {
      if (part.startsWith('<')) { if (/^<(pre|a|button)\b/i.test(part)) skip++; else if (/^<\/(pre|a|button)>/i.test(part)) skip = Math.max(0, skip - 1); return part; }
      return skip ? part : part.replace(re, name => `<button type="button" class="link output-link" data-action="output-open" data-id="${esc(byName[name].id)}">${name}</button>`);
    }).join('');
  }
