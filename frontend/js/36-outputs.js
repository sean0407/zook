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
  // #176 (#96②), #269: 成品 and 中間檔. The script a Bot made its files with (create_report.py) and its scratch files (stage 'work',
  // outputs.py) are 中間檔, under a switch that starts off; a Bot that only wrote code keeps its code as 成品.
  const BUILD_SCRIPT = /\.(py|js|mjs|cjs|ts|sh|zsh|bash|swift|rb|pl|applescript|scpt)$/i;
  const isWork = o => o.stage ? o.stage === 'work' : BUILD_SCRIPT.test(o.name);
  const splitScripts = list => {
    const files = list.filter(o => !isWork(o)), work = list.filter(isWork);
    return files.length ? [files, work] : [work.filter(o => BUILD_SCRIPT.test(o.name)), work.filter(o => !BUILD_SCRIPT.test(o.name))];
  };
  function outputsPanel(b) {
    const list = state.outputs[b.id];
    if (!list) { setTimeout(() => loadOutputs(b.id), 0); return '<div class="detail-empty">正在讀取產出…</div>'; }
    const [files, scripts] = splitScripts(list), showScripts = !!state.showScripts?.[b.id];
    const row = o => `<button class="note-row output-row" data-action="output-open" data-id="${esc(o.id)}" title="${esc(o.name)}"><strong>${fileIcon(o.name)} ${esc(midName(o.name, 40))}</strong><small>${esc(fileSize(o.size))} · ${esc(formatDate(o.at))}${o.group ? ' · 來自群組「' + esc(o.group) + '」' : ''}</small></button>`;  // #194: made in a group
    const head = scripts.length ? `<div class="output-head">成品（${files.length}）</div>` : '';
    const more = scripts.length ? `<label class="output-scripts">${toggle('data-show-scripts="' + esc(b.id) + '"', showScripts, '顯示中間檔')}<span>顯示中間檔（${scripts.length}）：製作用的程式與暫存檔</span></label>${showScripts ? scripts.map(row).join('') : ''}` : '';
    return `<div class="detail-title">產出 <button class="link" data-action="outputs-refresh">重新整理</button></div>${list.length ? head + (files.length ? files.map(row).join('') : '<div class="detail-empty">還沒有成品，只有中間檔。</div>') + more : '<div class="detail-empty">這個 Bot 建立或修改過的檔案會出現在這裡。</div>'}`;
  }
  // #153④⑥: what the preview window shows. A file that is gone says so and has nothing to download; one that cannot be read
  // (a picture that is not one, a 「PDF」 that is not a PDF, an empty file) says so in plain words and can still be downloaded.
  const CANT_OPEN = '這個檔案打不開，可能已損壞或副檔名不對。可以下載後用其他程式開啟。';
  const imageOpens = src => new Promise(done => { const img = new Image(); img.onload = () => done(img.naturalWidth > 0); img.onerror = () => done(false); img.src = src; });
  // #239: Word and PowerPoint as pictures of their pages, made by Zook on this Mac (Quick Look); a PDF too (#334: drawn by macOS,
  // fitted to the window, never turned dark with the dark look, no thumbnail column, no black box while it loads). Excel as its
  // real tables, every sheet and column (#320). The window opens at once with 「正在產生預覽…」; the pages come in when ready
  // (fillOfficeView), or a plain reason when they cannot be made.
  const isSheet = name => /\.xlsx$/i.test(String(name || ''));
  const officeShell = (url, name, kind) => `<div class="office-view" data-src="${esc(url)}" data-sheet="${isSheet(name) ? 1 : ''}" data-kind="${esc(kind || 'office')}"><p class="muted office-wait">正在產生預覽…</p></div>`;
  // #108④ #337③: a web page shown as a page, never run: no scripts, forms, pop-ups or plug-ins (sandbox with nothing allowed, so it
  // is also cut off from Zook's own pages and data), and nothing loaded from anywhere (its own policy allows only pictures,
  // styles and fonts written into the file itself). The file is first read as an inert document (nothing runs or loads there)
  // and what could move or reload the frame is taken out: refresh and other http-equiv tags, <base>, <link>, and links that do
  // not go to a web page (a link inside the file would otherwise open Zook's own addresses in the frame).
  const HTML_POLICY = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; media-src data:; form-action 'none'";
  function htmlFrame(text, name) {
    const doc = new DOMParser().parseFromString(String(text), 'text/html');
    doc.querySelectorAll('meta[http-equiv], base, link, script, noscript, iframe, frame, frameset, object, embed, portal').forEach(x => x.remove());
    for (const el of doc.querySelectorAll('*')) for (const at of [...el.attributes]) {  // every href (SVG's xlink:href too), form targets and pings
      const to = at.value.trim();
      if (at.localName === 'href' && !/^(https?:\/\/|mailto:|#)/i.test(to) || ['action', 'formaction', 'ping'].includes(at.localName)) el.removeAttributeNode(at);
    }
    const first = new DOMParser().parseFromString(`<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${HTML_POLICY}"><base target="_blank">`, 'text/html').head;
    doc.head.prepend(...[...first.childNodes].map(x => doc.importNode(x, true)));  // the policy comes before anything of the file's own
    const page = '<!doctype html>' + doc.documentElement.outerHTML;
    return `<div class="html-view"><p class="muted small office-note">網頁預覽：不執行程式、不連網，版面可能和瀏覽器略有不同。</p><iframe sandbox="" referrerpolicy="no-referrer" srcdoc="${esc(page)}" title="${esc(name)}"></iframe></div>`;
  }
  async function previewBody(url, kind, name) {
    if (kind === 'office') {
      let res = null; try { res = await fetch(url + (isSheet(name) ? '/pages/sheets' : '/pages')); } catch (_) {}  // an Excel file never starts Quick Look pictures
      return res && res.status === 404 ? {missing: true, body: '<p class="error-text">找不到這個檔案，可能已經被移走或刪除。</p>'} : {body: officeShell(url, name)};
    }
    let res = null;
    try { res = await fetch(url); } catch (_) {}
    if (!res || res.status === 404) return {missing: true, body: '<p class="error-text">找不到這個檔案，可能已經被移走或刪除。</p>'};
    if (!res.ok) return {body: `<p class="error-text">${esc((await res.json().catch(() => ({}))).error || '讀取失敗')}</p>`};
    const blob = await res.blob();
    if (!blob.size) return {body: '<p class="muted">這個檔案是空的（0 位元組），沒有內容可以顯示。</p>'};
    if (kind === 'image') {
      const local = URL.createObjectURL(blob);
      return (await imageOpens(local)) ? {body: `<div class="image-view"><img src="${esc(local)}" alt="${esc(name)}"></div>`} : {body: `<p class="muted">${CANT_OPEN}</p>`};
    }
    if (kind === 'pdf') return (await blob.slice(0, 1024).text()).includes('%PDF-') ? {body: officeShell(url.split('?')[0], name, 'pdf')} : {body: `<p class="muted">${CANT_OPEN}</p>`};
    if (kind === 'html') return {body: htmlFrame((await blob.text()).slice(0, 2000000), name)};
    if (kind === 'text' || kind === 'markdown') {
      const text = (await blob.text()).slice(0, 200000);
      return {body: kind === 'markdown' ? `<div class="md output-text">${markdown(text)}</div>` : `<pre class="output-text">${esc(text)}</pre>`};
    }
    return {body: '<p class="muted">這種檔案無法在這裡預覽，可以下載或在 Finder 顯示。</p>'};
  }
  async function openOutput(botId, id) {
    const o = (state.outputs[botId] || []).find(x => x.id === id);
    if (!o) return;
    const url = '/api/bots/' + encodeURIComponent(botId) + '/outputs/' + encodeURIComponent(o.id);
    const {body, missing} = await previewBody(url, o.kind, o.name);
    const keep = missing ? '' : `<button type="button" class="secondary" data-action="output-reveal" data-id="${esc(o.id)}" data-bot="${esc(botId)}">在 Finder 顯示</button>${o.size > 20 * 1048576 ? '' : `<a class="secondary button-link" href="${url}" download="${esc(o.name)}">下載</a>`}`;  // over 20 MB: only 在 Finder 顯示 works
    modal(o.name, `<div class="modal-body">${body}</div>${keep ? `<div class="modal-foot">${keep}</div>` : ''}`, '', 'viewer');  // #70④: no full path on this Mac; #270: × alone closes it
    fillOfficeView();
  }
  async function fillOfficeView() {
    const box = document.querySelector('.modal .office-view');
    if (!box) return;
    const src = box.dataset.src, until = Date.now() + 200000;
    if (box.dataset.sheet) return fillSheetView(box, src);
    while (box.isConnected) {
      let res = null, info = {};
      try { res = await fetch(src + '/pages'); info = await res.json(); } catch (_) {}
      if (!box.isConnected) return;
      if (info.status === 'ready') {
        const n = info.pages, more = info.total > n ? `，只顯示前 ${n} 頁` : '';
        const about = box.dataset.kind === 'pdf' ? (n > 1 ? `共 ${info.total} 頁${more}。` : '') : `這是預覽圖，版面可能和原檔略有不同${n > 1 ? `。共 ${info.total} 頁${more}` : ''}。`;
        box.innerHTML = `${about || info.note ? `<p class="muted small office-note">${about}${esc(info.note || '')}</p>` : ''}<div class="office-pages">${Array.from({length: n}, (_, i) => `<figure class="office-page"><img src="${esc(src + '/pages/' + (i + 1) + '?v=' + info.version)}" alt="第 ${i + 1} 頁" loading="lazy">${n > 1 ? `<figcaption>${i + 1} / ${n}</figcaption>` : ''}</figure>`).join('')}</div>`;
        return;
      }
      if (info.status !== 'working' || Date.now() > until) {
        box.innerHTML = `<p class="muted">${esc(info.reason || info.error || '無法產生預覽，可以下載後用其他程式開啟。')}</p>`;
        return;
      }
      await new Promise(done => setTimeout(done, 1000));
    }
  }
  // #320 #337⑤: an Excel file as tables, a tab per sheet, every column (scrolls sideways), first 300 rows of each.
  const columnName = n => { let s = ''; for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; };
  async function fillSheetView(box, src) {
    let info = {};
    try { const res = await fetch(src + '/pages/sheets'); info = await res.json(); if (res.status === 404) info = {reason: '找不到這個檔案，可能已經被移走或刪除。'}; } catch (_) {}
    if (!box.isConnected) return;
    if (info.status !== 'ready') { box.innerHTML = `<p class="muted">${esc(info.reason || info.error || '無法產生預覽，可以下載後用其他程式開啟。')}</p>`; return; }
    const sheets = info.sheets || [];
    if (!sheets.length) { box.innerHTML = '<p class="muted">這份試算表沒有內容。</p>'; return; }
    const cut = sheets.some(t => t.more || t.wide), notes = ['顯示的是存檔時算好的數值', cut ? '每個工作表只顯示前 300 列、60 欄' : '', info.charts ? '圖表不會顯示' : '', info.more ? '只顯示前 30 個工作表' : ''].filter(Boolean);
    const table = (t, i) => `<div class="sheet-table" data-sheet-index="${i}" ${i ? 'hidden' : ''}>${t.rows.length ? `<table><thead><tr><th></th>${Array.from({length: t.cols}, (_, c) => `<th>${columnName(c + 1)}</th>`).join('')}</tr></thead><tbody>${t.rows.map(([r, cells]) => `<tr><th>${r}</th>${Array.from({length: t.cols}, (_, c) => `<td>${esc(cells[c] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '<p class="muted">這個工作表是空的。</p>'}</div>`;
    const tabs = sheets.length > 1 ? `<div class="sheet-tabs" role="tablist">${sheets.map((t, i) => `<button type="button" role="tab" class="sheet-tab${i ? '' : ' active'}" aria-selected="${!i}" data-sheet-tab="${i}">${esc(t.name)}</button>`).join('')}</div>` : '';
    box.innerHTML = `<p class="muted small office-note">${esc(notes.join('；'))}${cut || info.charts ? '，完整內容請下載後查看' : ''}。</p>${tabs}${sheets.map(table).join('')}`;
  }
  document.addEventListener('click', e => {
    const tab = e.target.closest?.('[data-sheet-tab]'); if (!tab) return;
    const view = tab.closest('.office-view');
    view.querySelectorAll('.sheet-tab').forEach(x => { const on = x === tab; x.classList.toggle('active', on); x.setAttribute('aria-selected', on); });
    view.querySelectorAll('.sheet-table').forEach(x => { x.hidden = x.dataset.sheetIndex !== tab.dataset.sheetTab; });
  });
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
    if (a.classList.contains('missing-file')) return toast('檔案找不到：' + path + '。它可能沒有真的存好，或已被移走。');
    const bots = g ? (g.botIds || []) : [activeBot()?.id].filter(Boolean);
    const hit = outputAt(bots.map(id => [id, state.outputs[id]]), path);
    if (hit) return openOutput(hit[0], hit[1].id);
    const shared = g && (state.groupFiles[g.id] || []).find(f => path.endsWith('/group-files/' + g.id + '/' + f.name));  // straight in the group's folder
    if (shared) return openGroupFile(g.id, shared.name);
    navigator.clipboard?.writeText(path).then(() => toast('已複製檔案位置：' + path), () => toast('檔案位置：' + path));
  });
  // #280: a file of this Bot's already has its card under the reply (預覽, 下載), so a link to it in the text is only its words,
  // not a second link that may read differently from the card.
  // #258: a link to a file that was not on this Mac when the reply finished (missingFiles, outputs.py) says so beside it.
  function markMissing(html, m, botId) {  // one of its outputs by now (saved later) is there after all
    const gone = new Set(Array.isArray(m.missingFiles) ? m.missingFiles.filter(x => typeof x === 'string') : []);
    if (!gone.size) return html;
    const plain = text => { const t = document.createElement('textarea'); t.innerHTML = text; return t.value; };
    return html.replace(/<button type="button" class="link local-link" data-path="([^"]*)"([^>]*)>([\s\S]*?)<\/button>/g, (whole, path, rest, label) =>
      gone.has(plain(path)) && !outputAt([[botId, state.outputs[botId]]], plain(path)) ? `<button type="button" class="link local-link missing-file" data-path="${path}"${rest}>${label}</button><span class="missing-note">（檔案找不到）</span>` : whole);
  }
  function linkOutputs(html, botId) {
    if (!(state.outputs[botId] || []).length) return html;
    const plain = text => { const t = document.createElement('textarea'); t.innerHTML = text; return t.value; };
    return html.replace(/<button type="button" class="link local-link" data-path="([^"]*)"[^>]*>([\s\S]*?)<\/button>/g, (whole, path, label) => {
      const o = (outputAt([[botId, state.outputs[botId]]], plain(path)) || [])[1];
      if (!o) return whole;
      return plain(path).includes(o.name) ? `<span class="file-ref">${label}</span>`  // its card shows under the reply
        : `<button type="button" class="link output-link" data-action="output-open" data-id="${esc(o.id)}">${label}</button>`;  // written so the card cannot find it (%20)
    });
  }
