  // 產出: the files a Bot made or changed, with a preview.
  if (!state.outputs) state.outputs = {};
  // One request at a time per Bot: asked again meanwhile (a running reply wrote another file), it reads once more when this one is back.
  const outputsBusy = {};
  async function loadOutputs(botId, quiet) {
    if (outputsBusy[botId]) { outputsBusy[botId] = quiet && outputsBusy[botId] !== 'loud' ? 'again' : 'loud'; return; }
    outputsBusy[botId] = true;
    const stop = new AbortController(), timer = setTimeout(() => stop.abort(), 20000);  // never 「正在讀取」 for minutes
    try { state.outputs[botId] = (await api('bots/' + encodeURIComponent(botId) + '/outputs', {signal: stop.signal})).outputs; }
    catch (error) { state.outputs[botId] = state.outputs[botId] || []; if (!quiet) toast(stop.signal.aborted ? '產出讀取太久，請按「重新整理」再試一次。' : error.message); }
    finally { clearTimeout(timer); }
    const again = outputsBusy[botId]; delete outputsBusy[botId];
    render(true);
    if (again !== true) loadOutputs(botId, again === 'again');
  }
  // #176 (#96②): the script a Bot wrote to make its files (create_report.py) is not what it handed over. Beside other files it goes
  // under a switch; a Bot that only wrote code keeps its code in the list.
  const BUILD_SCRIPT = /\.(py|js|mjs|cjs|ts|sh|zsh|bash|swift|rb|pl|applescript|scpt)$/i;
  const splitScripts = list => list.some(o => !BUILD_SCRIPT.test(o.name)) ? [list.filter(o => !BUILD_SCRIPT.test(o.name)), list.filter(o => BUILD_SCRIPT.test(o.name))] : [list, []];
  function outputsPanel(b) {
    const list = state.outputs[b.id];
    if (!list) { setTimeout(() => loadOutputs(b.id), 0); return '<div class="detail-empty">正在讀取產出…</div>'; }
    const icon = {image: '🖼', pdf: '📕', markdown: '📝', text: '📄', file: '📎'};
    const [files, scripts] = splitScripts(list), showScripts = !!state.showScripts?.[b.id];
    const row = o => `<button class="note-row output-row" data-action="output-open" data-id="${esc(o.id)}" title="${esc(o.path)}"><strong>${icon[o.kind] || '📎'} ${esc(o.name)}</strong><small>${esc(fileSize(o.size))} · ${esc(formatDate(o.at))}</small></button>`;
    const more = scripts.length ? `<label class="output-scripts">${toggle('data-show-scripts="' + esc(b.id) + '"', showScripts, '顯示製作用的程式')}<span>顯示製作用的程式（${scripts.length}）</span></label>${showScripts ? scripts.map(row).join('') : ''}` : '';
    return `<div class="detail-title">產出 <button class="link" data-action="outputs-refresh">重新整理</button></div>${list.length ? files.map(row).join('') + more : '<div class="detail-empty">這個 Bot 建立或修改過的檔案會出現在這裡。</div>'}`;
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
  // The output a link's path points at (/tmp and /private/tmp are one place). Only the exact file: another file with the same
  // name elsewhere is a different file. Each list is [owner, outputs]; returns [owner, output].
  const samePath = p => String(p || '').replace(/^\/private(?=\/(tmp|var)\/)/, '');
  function outputAt(lists, path) {
    let plain = path; try { plain = decodeURIComponent(path); } catch (_) {}
    for (const want of plain === path ? [path] : [path, plain])  // as written first; then with %20 read as a space
      for (const [who, list] of lists) for (const o of list || []) if (samePath(o.path) === samePath(want)) return [who, o];
    return null;
  }
  // A link to a file on this Mac opens Zook's preview (download, 在 Finder 顯示) when it is one of the Bot's outputs or the
  // group's files; otherwise the window cannot open it, so its path is copied.
  document.addEventListener('click', e => {
    const a = e.target.closest?.('.local-link');
    if (!a) return;
    e.preventDefault();
    const path = a.dataset.path || '', g = activeGroup();
    const bots = g ? (g.botIds || []) : [activeBot()?.id].filter(Boolean);
    const hit = outputAt(bots.map(id => [id, state.outputs[id]]), path);
    if (hit) return openOutput(hit[0], hit[1].id);
    const shared = g && (state.groupFiles[g.id] || []).find(f => path.endsWith('/group-files/' + g.id + '/' + f.name));  // straight in the group's folder
    if (shared) return openGroupFile(g.id, shared.name);
    navigator.clipboard?.writeText(path).then(() => toast('已複製檔案位置：' + path), () => toast('檔案位置：' + path));
  });
  // File names of this Bot's outputs inside a reply open the preview.
  function linkOutputs(html, botId) {
    const list = (state.outputs[botId] || []).filter(o => o.name.length >= 4).slice(0, 80);
    if (!list.length) return html;
    const byName = {}; list.forEach(o => { byName[esc(o.name)] = byName[esc(o.name)] || o; });
    const re = new RegExp('(' + Object.keys(byName).sort((a, b) => b.length - a.length).map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g');
    // A Markdown link straight to one of the files opens its preview, like its name does.
    const plain = text => { const t = document.createElement('textarea'); t.innerHTML = text; return t.value; };
    html = html.replace(/<button type="button" class="link local-link" data-path="([^"]*)"[^>]*>([\s\S]*?)<\/button>/g, (whole, path, label) => {
      const o = (outputAt([[botId, state.outputs[botId]]], plain(path)) || [])[1];
      return o ? `<button type="button" class="link output-link" data-action="output-open" data-id="${esc(o.id)}">${label}</button>` : whole;
    });
    let skip = 0;
    return html.split(/(<[^>]+>)/).map(part => {
      if (part.startsWith('<')) { if (/^<(pre|a|button)\b/i.test(part)) skip++; else if (/^<\/(pre|a|button)>/i.test(part)) skip = Math.max(0, skip - 1); return part; }
      return skip ? part : part.replace(re, name => `<button type="button" class="link output-link" data-action="output-open" data-id="${esc(byName[name].id)}">${name}</button>`);
    }).join('');
  }
