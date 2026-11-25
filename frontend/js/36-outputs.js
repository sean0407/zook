  // 產出: the files a Bot made or changed, with a preview.
  if (!state.outputs) state.outputs = {};
  async function loadOutputs(botId, quiet) {
    const stop = new AbortController(), timer = setTimeout(() => stop.abort(), 20000);  // never 「正在讀取」 for minutes
    try { state.outputs[botId] = (await api('bots/' + encodeURIComponent(botId) + '/outputs', {signal: stop.signal})).outputs; }
    catch (error) { state.outputs[botId] = state.outputs[botId] || []; if (!quiet) toast(stop.signal.aborted ? '產出讀取太久，請按「重新整理」再試一次。' : error.message); }
    finally { clearTimeout(timer); }
    render(true);
  }
  function outputsPanel(b) {
    const list = state.outputs[b.id];
    if (!list) { setTimeout(() => loadOutputs(b.id), 0); return '<div class="detail-empty">正在讀取產出…</div>'; }
    const icon = {image: '🖼', pdf: '📕', markdown: '📝', text: '📄', file: '📎'};
    return `<div class="detail-title">產出 <button class="link" data-action="outputs-refresh">重新整理</button></div>${list.length ? list.map(o => `<button class="note-row output-row" data-action="output-open" data-id="${esc(o.id)}" title="${esc(o.path)}"><strong>${icon[o.kind] || '📎'} ${esc(o.name)}</strong><small>${esc(fileSize(o.size))} · ${esc(formatDate(o.at))}</small></button>`).join('') : '<div class="detail-empty">這個 Bot 建立或修改過的檔案會出現在這裡。</div>'}`;
  }
  // A PDF opens fitted to the window's width; it stays hidden behind a line of text until it has loaded, instead of a dark box.
  const pdfFrame = (url, name) => `<div class="pdf-wrap"><p class="pdf-loading muted">正在開啟 PDF…</p><iframe class="output-pdf" src="${esc(url)}#view=FitH&zoom=page-width" title="${esc(name)}"></iframe></div>`;
  function showPdfWhenReady() {
    const frame = document.querySelector('.modal .output-pdf');
    if (!frame) return;
    const show = () => frame.classList.add('ready');
    frame.addEventListener('load', show, {once: true}); setTimeout(show, 4000);
  }
  async function openOutput(botId, id) {
    const o = (state.outputs[botId] || []).find(x => x.id === id);
    if (!o) return;
    const url = '/api/bots/' + encodeURIComponent(botId) + '/outputs/' + encodeURIComponent(o.id);
    let body = '<p class="muted">這種檔案無法在這裡預覽，可以下載或在 Finder 顯示。</p>';
    if (o.kind === 'image') body = `<div class="image-view"><img src="${url}" alt="${esc(o.name)}"></div>`;
    else if (o.kind === 'pdf') body = pdfFrame(url, o.name);
    else if (o.kind === 'text' || o.kind === 'markdown') {
      try {
        const res = await fetch(url); if (!res.ok) throw Error((await res.json().catch(() => ({}))).error || '讀取失敗');
        const text = (await res.text()).slice(0, 200000);
        body = o.kind === 'markdown' ? `<div class="md output-text">${markdown(text)}</div>` : `<pre class="output-text">${esc(text)}</pre>`;
      } catch (error) { body = `<p class="error-text">${esc(error.message)}</p>`; }
    }
    modal(o.name, `<div class="modal-body">${body}<p class="muted small output-path">${esc(o.path)}</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="output-reveal" data-id="${esc(o.id)}" data-bot="${esc(botId)}">在 Finder 顯示</button><a class="secondary button-link" href="${url}" download="${esc(o.name)}">下載</a><button type="button" class="primary" data-action="close-modal">關閉</button></div>`, '', true);
    showPdfWhenReady();
  }
  // A link to a file on this Mac that is not one of the outputs: the window cannot open it, so its path is copied.
  document.addEventListener('click', e => {
    const a = e.target.closest?.('a.local-link');
    if (!a) return;
    e.preventDefault();
    let path = a.getAttribute('href').replace(/^file:\/\//, ''); try { path = decodeURIComponent(path); } catch (_) {}
    navigator.clipboard?.writeText(path).then(() => toast('已複製檔案位置：' + path), () => toast('檔案位置：' + path));
  });
  // File names of this Bot's outputs inside a reply open the preview.
  function linkOutputs(html, botId) {
    const list = (state.outputs[botId] || []).filter(o => o.name.length >= 4).slice(0, 80);
    if (!list.length) return html;
    const byName = {}; list.forEach(o => { byName[esc(o.name)] = byName[esc(o.name)] || o; });
    const re = new RegExp('(' + Object.keys(byName).sort((a, b) => b.length - a.length).map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g');
    // A Markdown link straight to the file would try to open a local path in the window; make it open the preview instead.
    const byPath = {}; list.forEach(o => { byPath[o.path] = o; });
    const plain = text => { const t = document.createElement('textarea'); t.innerHTML = text; let v = t.value.replace(/^file:\/\//, ''); try { v = decodeURIComponent(v); } catch (_) {} return v; };
    html = html.replace(/<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g, (whole, href, label) => {
      const o = byPath[plain(href)] || byPath[plain(href).replace(/^\/private(?=\/(tmp|var)\/)/, '')] || byPath['/private' + plain(href)];
      return o ? `<button type="button" class="link output-link" data-action="output-open" data-id="${esc(o.id)}">${label}</button>` : whole;
    });
    let skip = 0;
    return html.split(/(<[^>]+>)/).map(part => {
      if (part.startsWith('<')) { if (/^<(pre|a|button)\b/i.test(part)) skip++; else if (/^<\/(pre|a|button)>/i.test(part)) skip = Math.max(0, skip - 1); return part; }
      return skip ? part : part.replace(re, name => `<button type="button" class="link output-link" data-action="output-open" data-id="${esc(byName[name].id)}">${name}</button>`);
    }).join('');
  }
