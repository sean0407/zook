(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  } [c]));

  // A Markdown link's target → the opening tag, '' (show only its words) or null (not a link: leave the text as it is).
  // Bots write paths with spaces or Chinese inside <…> (CommonMark), and sometimes break it: `(</tmp/a.docx> >)`, `(/tmp/a b.docx>)`.
  // Only http(s) becomes a real link; a file on this Mac is a button that opens Zook's preview, never a page address.
  const MD_LINK = /\[([^[\]]+)\]\((\s*<[^<>\n]*>[^()\n]*|(?:[^()\n]|\([^()\n]*\))*)\)/g;
  // The target of a link without its <…>, title and stray '>'; and the file on this Mac it names ('' when it names none).
  function mdTarget(inner) {
    let t = inner.trim();
    const q = t.slice(-1), from = /["']/.test(q) ? t.lastIndexOf(q, t.length - 2) : -1;
    if (from > 0 && /\s/.test(t[from - 1])) t = t.slice(0, from).trim();  // a title: [a](<b> "title")
    const angled = t.startsWith('<');
    if (angled) { t = t.slice(1); const close = t.indexOf('>'); if (close >= 0) t = t.slice(0, close); }
    let end = t.length; while (end && /[\s>]/.test(t[end - 1])) end--;  // a loop, not a regex: no slow backtracking on long spaces
    t = t.slice(0, end).trim();
    let path = '';
    if (/^file:\/?\//i.test(t)) { path = t.replace(/^file:(\/\/(localhost)?)?/i, ''); try { path = decodeURIComponent(path); } catch (_) {} }
    else if (/^(\/(?!\/)|~\/)/.test(t)) path = t;  // kept as written: a %20 may be part of the real name (the preview also tries it decoded)
    if (!(path.startsWith('/') && !path.startsWith('//') || path.startsWith('~/'))) path = '';
    return {t, angled, path};
  }
  function mdLinkOpen(inner) {
    const {t, angled, path} = mdTarget(inner);
    if (/^https?:\/\/[^\s<>"]+$/i.test(t) || (angled && /^https?:\/\/[^<>"]+$/i.test(t))) return `<a href="${esc(t.replace(/\s/g, '%20'))}" rel="noopener noreferrer">`;
    if (path) return `<button type="button" class="link local-link" data-path="${esc(path)}" title="${esc(path)}">`;
    if (angled || /^[a-z][a-z0-9+.-]*:/i.test(t) || /^[^\s]+\.[A-Za-z0-9]{1,8}$/.test(t)) return '';  // a bare file name or an unsafe kind of link: just its words
    return null;
  }
  // Minimal Markdown → HTML. Everything is escaped; only known tags are produced (links: see mdLinkOpen).
  function mdInline(text) {
    const held = [], raw = [], hold = (html, was) => { raw.push(was); return `\u0000${held.push(html) - 1}\u0000`; };
    let s = String(text ?? '').replace(/\u0000/g, '').replace(/`([^`\n]+)`/g, (whole, c) => hold(`<code>${esc(c)}</code>`, whole));
    s = s.replace(MD_LINK, (whole, label, inner) => {
      const open = mdLinkOpen(inner.replace(/\u0000(\d+)\u0000/g, (_, i) => raw[i]));  // a ` in a file name is part of the name
      if (open === null) return whole;
      label = label.split('\n').map(x => x.trim()).join(' ');  // a long name the Bot wrapped onto two lines
      return open ? hold(open) + label + hold(open.startsWith('<a') ? '</a>' : '</button>') : label;
    });
    // #45: a bare file:///… written in the text opens like a link to that file. It ends at a space or Chinese punctuation
    // (「圖在file:///tmp/a.png，請看」); a trailing full stop or comma is not part of it.
    s = s.replace(/(?<![A-Za-z0-9+.\-/])file:\/\/(?:localhost)?\/[^\s<>()（）"'`*\u0000，。、；：！？「」『』【】《》]+/gi, whole => {
      let n = whole.length; while (n && /[.,;:!?]/.test(whole[n - 1])) n--;  // a loop, not a regex: no slow backtracking
      const url = whole.slice(0, n), {path} = mdTarget(url);
      return path ? hold(`<button type="button" class="link local-link" data-path="${esc(path)}" title="${esc(path)}">${esc(url)}</button>`, url) + whole.slice(n) : whole;
    });
    s = esc(s)
      .replace(/(^|[\s(（])(https?:\/\/[^\s<)）\u0000]+)/g, (_, p, u) => `${p}<a href="${u}" rel="noopener noreferrer">${u}</a>`)
      .replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, '<strong>$1</strong>')
      .replace(/__(?=\S)([\s\S]*?\S)__/g, '<strong>$1</strong>')
      .replace(/~~(?=\S)([\s\S]*?\S)~~/g, '<del>$1</del>')
      .replace(/(^|[^*\w])\*(?=\S)([^*\n]*?\S)\*(?!\*)/g, '$1<em>$2</em>');
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => held[i]);
  }
  function markdown(src) {
    const lines = String(src ?? '').replace(/\r\n?/g, '\n').split('\n'), out = [];
    const isTableSep = l => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
    const cells = l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => mdInline(c.trim()));
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*```/.test(line)) {
        const body = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
        i++; out.push(`<pre><code>${esc(body.join('\n'))}</code></pre>`); continue;
      }
      if (!line.trim()) { i++; continue; }
      let m;
      if ((m = line.match(/^\s*(#{1,6})\s+(.*)$/))) { const h = Math.min(m[1].length + 2, 6); out.push(`<h${h} class="md-h">${mdInline(m[2].replace(/\s+#+\s*$/, ''))}</h${h}>`); i++; continue; }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
      if (line.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        const head = cells(line); i += 2; const rows = [];
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
        out.push(`<div class="md-table"><table><thead><tr>${head.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
        continue;
      }
      if (/^\s*>/.test(line)) {
        const body = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ''));
        out.push(`<blockquote>${markdown(body.join('\n'))}</blockquote>`); continue;
      }
      if ((m = line.match(/^\s*([-*+]|\d+[.)])\s+/))) {
        const ordered = /\d/.test(m[1]), items = [];
        const re = ordered ? /^\s*\d+[.)]\s+(.*)$/ : /^\s*[-*+]\s+(.*)$/;
        while (i < lines.length) {
          const item = lines[i].match(re);
          if (item) { items.push(item[1]); i++; }
          else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) { items[items.length - 1] += '\n' + lines[i].trim(); i++; }
          else break;
        }
        const tag = ordered ? 'ol' : 'ul';
        out.push(`<${tag}>${items.map(t => `<li>${mdInline(t).replace(/\n/g, '<br>')}</li>`).join('')}</${tag}>`); continue;
      }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|>|[-*+]\s|\d+[.)]\s)/.test(lines[i]) && !(lines[i].includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1]))) para.push(lines[i++]);
      if (!para.length) para.push(lines[i++]);
      out.push(`<p>${mdInline(para.join('\n')).replace(/\n/g, '<br>')}</p>`);  // bold may span the lines of one paragraph
    }
    return out.join('');
  }
  const icons = {
    search: '<circle cx="11" cy="11" r="7"/><path d="m16 16 4 4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l1.6-1.3-1.5-2.6-2 .6a7 7 0 0 0-1.7-1L15 4H9l-.3 2.7a7 7 0 0 0-1.7 1l-2-.6-1.5 2.6L5.1 11a7 7 0 0 0 0 2l-1.6 1.3L5 16.9l2-.6a7 7 0 0 0 1.7 1L9 20h6l.3-2.7a7 7 0 0 0 1.7-1l2 .6 1.5-2.6-1.6-1.3a7 7 0 0 0 .1-1Z"/>',
    download: '<path d="M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 10.2 4 4 0 0 1 17.5 18"/><path d="M12 11v8m-3-3 3 3 3-3"/>',
    grid: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    mic: '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3m-3 0h6"/>',
    share: '<path d="M12 15V3m-4 4 4-4 4 4M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/>'
  };
  const svg = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[n]||''}</svg>`;
  const colors = ['#111111', '#a47545', '#ff284b', '#ff6d0c', '#f59a0a', '#13bf78', '#14b8a6', '#2585f6', '#9254ff', '#ed2f9b', '#959595'];
  // At or below this width the side panel covers the page instead of squeezing the conversation (#118, #60, #152); style.css uses the same number.
  const DETAIL_WIDE = 1100;
  const narrowDetail = () => window.matchMedia(`(max-width: ${DETAIL_WIDE}px)`).matches;
  const detailBackdrop = () => '<div class="detail-backdrop" data-action="toggle-detail" aria-hidden="true"></div>';
  const state = {
    data: {
      bots: [],
      knowledge: [],
      settings: {},
      jobs: [],
      groups: []
    },
    selected: null,
    groupId: null,
    groupPollers: {},
    page: 'chat',
    detail: 'activity',
    detailOpen: !narrowDetail(),  // a narrow window keeps the conversation readable; the panel opens over it on request
    query: '',
    launcher: false,
    collapsed: {},
    integrations: null,
    usage: null,
    modal: null,
    pollers: {},
    jobDetails: {},
    deciding: {},
    seenApprovals: {},  // 已失效 cards the user closed with 知道了
    mcpTests: {}
  };
  const app = $('#app'),
    modalRoot = $('#modal-root');
  async function api(path, options = {}) {
    const res = await fetch('/api/' + path, {
      credentials: 'same-origin',
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      }
    });
    let body;
    try {
      body = await res.json()
    } catch {
      body = {}
    }
    if (!res.ok) throw Error(body.error || `請求失敗 (${res.status})`);
    return body;
  }
  const post = (path, body = {}, method = 'POST') => api(path, {
    method,
    body: JSON.stringify(body)
  }).then(r => { if (path === 'settings' && method === 'PATCH') settingSaved(); return r; }, e => { if (path === 'settings' && method === 'PATCH') settingFailed(); throw e; });  // 設定頁 shows 「已儲存」 beside what changed (38c-settings.js)

  function toast(message) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove('show'), 3000)
  }

  function shapeIndex(shape) {
    return ({
      circle: 1,
      square: 9,
      triangle: 4
    } [shape] ?? (Number(String(shape ?? 0).replace(/\D/g, '')) % 13))
  }

  function avatar(b, cls = '') {
    let color = /^#[0-9a-f]{6}$/i.test(b?.color || '') ? b.color : '#f47b54';
    let sh = shapeIndex(b?.shape);
    return `<span class="avatar shape-${sh} ${cls}" style="--c:${color}" aria-hidden="true"></span>`
  }

  function activeBot() {
    return state.data.bots.find(b => b.id === state.selected)
  }

  // A one-line preview in the sidebar: the words, without Markdown marks.
  const plainPreview = text => String(text || '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\*\*|__|~~|`+/g, '').replace(/^\s*#+\s*/gm, '');
  function messagePreview(b) {
    const m = (b.messages || []).slice(-1)[0];
    return plainPreview(m?.content) || b.instructions || '開始新的對話'
  }

  function matches(s) {
    return String(s || '').toLowerCase().includes(state.query.toLowerCase())
  }

  function botRow(b) {
    return `<button class="side-row ${state.page==='chat'&&!state.groupId&&b.id===state.selected?'active':''}" data-action="select-bot" data-id="${esc(b.id)}" ${state.query ? '' : `draggable="true" data-drag-bot="${esc(b.id)}"`}>${avatar(b)}<span class="side-copy"><span class="side-name">${esc(b.name)}${jobTitle(b)}${pendingForBot(b.id).length ? ' <span class="approval-badge">待核准</span>' : ''}${troubleBadge(b)}</span><span class="side-preview">${esc(messagePreview(b))}</span></span></button>`
  }

  function sectionNames() {
    const saved = state.data.settings?.sections || [];
    return [...new Set([...saved, ...state.data.bots.filter(b => !b.pinned).map(b => b.section || '我的 Bots')])];
  }
  // Save the sidebar layout: Bot order, each Bot's group, and group order.
  async function saveArrangement(bots, sections) {
    const before = {bots: state.data.bots, sections: state.data.settings.sections};
    state.data.bots = bots; state.data.settings.sections = sections; render(true);
    try {
      await post('bots/arrange', {sections, bots: bots.map(b => ({id: b.id, section: b.section || '我的 Bots', pinned: !!b.pinned}))});
    } catch (err) {
      state.data.bots = before.bots; state.data.settings.sections = before.sections; render(true); toast(err.message || '無法儲存排序');
    }
  }
  function sectionModal(oldName = '') {
    modal(oldName ? '重新命名分組' : '新增分組', `<form id="section-form" data-old="${esc(oldName)}"><div class="modal-body"><label class="field">分組名稱<input name="name" required maxlength="100" value="${esc(oldName)}" placeholder="例如：研究、工作、生活"></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${oldName ? '儲存' : '新增'}</button></div></form>`);
  }

  function sidebar() {
    let bots = state.data.bots.filter(b => !state.query || matches(b.name) || matches(messagePreview(b)));
    let sections = sectionNames().filter(name => !state.query || bots.some(b => !b.pinned && (b.section || '我的 Bots') === name));
    let pinned = bots.filter(b => b.pinned);
    // Each group can be dragged to reorder; Bots can be dragged within or between groups (empty groups accept drops too).
    let block = (name, items, isPinned) => {
      const drag = !state.query, closed = state.collapsed[name];
      const tools = drag && !isPinned ? `<span class="section-tools"><button class="icon-btn mini" data-action="rename-section" data-id="${esc(name)}" aria-label="重新命名分組" title="重新命名">✎</button>${items.length ? '' : `<button class="icon-btn mini" data-action="delete-section" data-id="${esc(name)}" aria-label="刪除分組" title="刪除空分組">×</button>`}</span>` : '';
      return `<div class="side-section" data-drop-section="${esc(isPinned ? '__pinned' : name)}"><div class="section-head bot-section-head" ${drag && !isPinned ? `draggable="true" data-drag-section="${esc(name)}"` : ''}><button class="section-toggle" data-action="collapse" data-id="${esc(name)}"><span>${esc(name)} ${items.some(b=>pendingForBot(b.id).length)?'<span class="approval-badge">待核准</span>':''}</span><span>${closed?'⌄':'⌃'}</span></button>${tools}</div>${closed?'':items.map(botRow).join('') + (items.length || !drag ? '' : '<div class="drop-hint">把 Bot 拖到這裡</div>')}</div>`;
    };
    return `<aside class="sidebar"><div class="side-top"><div class="brand" role="img" aria-label="Zook"><img src="/brand.png" alt="" draggable="false"></div><div class="side-actions"><button class="icon-btn" data-action="search-focus" aria-label="搜尋">${svg('search')}</button><button class="icon-btn" data-action="new-bot" aria-label="新增 Bot">${svg('plus')}</button></div></div><div class="search"><span class="glass tiny-icon">${svg('search')}</span><input id="side-search" placeholder="搜尋 Bot、對話和知識" aria-label="搜尋 Bot、對話和知識" value="${esc(state.query)}"></div><div class="side-scroll">${groupsBlock()}${pinned.length?block('已釘選',pinned,true):''}${sections.map(s=>block(s,bots.filter(b=>!b.pinned&&(b.section||'我的 Bots')===s))).join('')}${state.query?'':'<button class="side-empty add-section" data-action="new-section">＋ 新增分組</button>'}${messageHits().length?`<div class="section-head">對話搜尋結果</div>${messageHits().map(h=>`<button class="side-row" data-action="open-message" data-bot="${esc(h.b.id)}" data-id="${esc(h.messageId)}">${avatar(h.b)}<span class="side-copy"><span class="side-name">${esc(h.b.name)} · ${esc(h.chatTitle || (h.kind === 'schedule' ? '排程' : '新對話'))}</span><span class="side-preview">${esc(h.snippet)}</span></span></button>`).join('')}`:''}${state.query&&state.data.knowledge.filter(n=>matches(n.title)||matches(n.content)).length?`<div class="section-head">知識搜尋結果</div>${state.data.knowledge.filter(n=>matches(n.title)||matches(n.content)).map(n=>`<button class="side-row" data-action="edit-note" data-id="${esc(n.id)}"><span>▤</span><span class="side-copy"><span class="side-name">${esc(n.title)}</span><span class="side-preview">${esc(n.content)}</span></span></button>`).join('')}`:''}</div><div class="side-footer"><div class="launcher"><button class="workspace-btn" data-action="launcher" aria-label="開啟功能選單" title="功能選單" aria-expanded="${state.launcher}"><span class="user-avatar">S</span><span class="user-name">我的工作區</span></button>${state.launcher?`<div class="popup">${[['usage','◷','各模型使用量'],['schedules','◴','排程'],['knowledge','▤','知識庫'],['memory','◎','記憶'],['skills','✳','Skills 與連接器'],['activity','☰','活動紀錄'],['settings','⚙','設定']].map(x=>`<button class="nav-item" data-action="page" data-id="${x[0]}"><span>${x[1]}</span>${x[2]}</button>`).join('')}</div>`:''}</div><button class="icon-btn gear-btn" data-action="page" data-id="settings" title="設定">${svg('settings')}<span>設定</span></button>${state.update?.available ? `<button class="icon-btn update-btn" data-action="update-open" aria-label="有新版 ${esc(state.update.latest)}，按這裡更新" title="有新版 ${esc(state.update.latest)}">${svg('download')}</button>` : ''}</div></aside>`
  }

  function jobsForBot(botId) { return Object.values(state.jobDetails).filter(j => j.botId === botId && !j.groupId); }
  function jobsForGroup(groupId) { return Object.values(state.jobDetails).filter(j => j.groupId === groupId); }
  const jobTitle = b => b.jobTitle ? ` <span class="job-title">${esc(b.jobTitle)}</span>` : '';
  function pendingIn(jobs) { return jobs.flatMap(j => (j.approvals || []).filter(a => a.status === 'pending').map(a => ({...a, job: j}))); }
  function pendingForBot(botId) { return pendingIn(jobsForBot(botId)); }
  function argsView(args) { try { return JSON.stringify(args, null, 2) || '{}'; } catch (_) { return String(args); } }
  // Plain-language descriptions of what a Bot does: no tool names, ids or JSON on screen.
  const FIELD_NAMES = {path: '檔案', content: '內容', name: '名稱', persona: '人格', instructions: '工作指示', provider: '模型', model: '模型版本',
    color: '顏色', bot_names: '成員', group_name: '群組', message: '訊息', skill_id: 'Skill', argv: '要執行的內容', cwd: '位置', scope: '範圍', query: '搜尋內容',
    target: '對象', repeat: '重複', time: '時間', date: '日期', day: '每月幾號', enabled: '啟用', schedule_id: '排程',
    url: '網址', field: '欄位', text: '文字', enter: '按 Enter', number: '連結編號', part: '第幾段', direction: '方向', account: '帳號', effort: '思考強度', jobTitle: '職稱'};
  const humanWords = t => String(t || '').replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim();
  const skillName = id => (state.integrations?.skills || []).find(x => x.id === id)?.name || 'Skill';
  const inAttachments = p => /(^|\/)workspaces\/[^/]+\/attachments\/|^(\.\/)?attachments\//.test(String(p || ''));  // a Bot's own attachments folder
  const fileName = p => (inAttachments(p) ? String(p).split('/').pop().replace(/^[0-9a-f]{8}-(?=.)/, '') : String(p || '').split('/').pop()) || '檔案';  // an upload without the id Zook put in front of it
  function describeCall(c) {
    const a = c.arguments || {};
    switch (c.name) {
      case 'zook_read_skill': return `閱讀 Skill「${skillName(a.skill_id) === 'Skill' ? (c.sourceLabel || 'Skill') : skillName(a.skill_id)}」的說明`;
      case 'zook_read_skill_resource': return `查看 Skill「${skillName(a.skill_id)}」的參考資料「${fileName(a.path)}」`;
      case 'zook_run_skill_helper': return `執行 Skill「${skillName(a.skill_id)}」附帶的小程式`;
      case 'zook_workspace_list': return '查看工作區裡有哪些檔案';
      case 'zook_native_gate': return String(a.title || '做需要你核准的動作');  // a CLI's own tool at a safety boundary
      case 'zook_workspace_read': return `讀取檔案「${fileName(a.path)}」`;
      case 'zook_workspace_write': return `把內容存成檔案「${fileName(a.path)}」`;
      case 'zook_list_team': return '查看團隊裡有哪些 Bot 和群組';
      case 'zook_create_bot': return `新增 Bot「${a.name || ''}」`;
      case 'zook_create_group': return `建立群組「${a.name || (a.bot_names || []).join('、')}」`;
      case 'zook_start_group_discussion': return `在群組「${a.group_name || ''}」發起討論`;
      case 'zook_feature': return `使用${a.feature || '特色功能'}`;
      case 'zook_remember': return `記住一件事：「${String(a.content || '').slice(0, 60)}」`;
      case 'zook_ask_user': return `問你：「${String(a.question || '').slice(0, 60)}」`;
      case 'zook_browser_open': return `用內建瀏覽器開啟 ${String(a.url || '').slice(0, 80)}`;
      case 'zook_browser_click': return `在網頁上點第 ${String(a.number || '').slice(0, 6)} 個連結`;
      case 'zook_browser_scroll': return a.direction === 'up' ? '把網頁往上捲' : '把網頁往下捲';
      case 'zook_browser_read': return '讀網頁的下一段';
      case 'zook_browser_links': return '看網頁上的更多連結';
      case 'zook_browser_screenshot': return '幫網頁截圖';
      case 'zook_browser_type': return `在網頁輸入「${String(a.text || '').slice(0, 60)}」${a.enter === true ? '並按 Enter' : ''}`;
      case 'zook_list_schedules': return '查看排程';
      case 'zook_create_schedule': return `建立排程「${String(a.content || '').slice(0, 40)}」`;
      case 'zook_git_commit': return `提交到 git「${String(a.message || '').slice(0, 40)}」`;
      case 'zook_update_schedule': return `修改排程「${scheduleLabel(a.schedule_id)}」`;
      case 'zook_delete_schedule': return `刪除排程「${scheduleLabel(a.schedule_id)}」`;
      case 'web_search': return a.query ? `上網搜尋「${String(a.query).slice(0, 60)}」` : '上網搜尋';
      case 'native_write': return `修改檔案「${fileName(a.path)}」`;
      case 'native_command': return a.summary && a.summary !== '執行指令' ? String(a.summary).slice(0, 80) : '在工作資料夾執行指令';  // 「執行指令：python3、ls」 says which programs
      case 'native_read': return inAttachments(a.path) ? `讀取你上傳的附件「${fileName(a.path)}」` : `查看「${fileName(a.path) || '檔案'}」`;
      case 'native_skill': return `使用 Skill「${String(a.name || 'Skill').slice(0, 60)}」`;
      case 'web_fetch': return `讀取網頁「${(String(a.url || '').match(/^https?:\/\/([^/]+)/) || [, a.url || '網頁'])[1]}」`;
    }
    if (c.category === 'code' && c.sourceLabel) return `執行一段程式（${c.sourceLabel}）`;  // a connector that runs code: say so plainly
    return `使用「${c.sourceLabel || '外部服務'}」${c.label ? '的' + humanWords(c.label) + '功能' : ''}`;
  }
  const ERROR_WORDS = [[/denied|cancel/i, '你沒有允許這個動作'], [/Paths must remain|Symlinks|outside/i, '這個檔案不在 Bot 的工作區內'],
    [/unavailable|not found|No such/i, '找不到需要的資料'], [/exceeds|too large|limit/i, '內容太大'], [/timed? ?out|timeout/i, '等太久沒有回應'],
    [/authori|401|403|sign in/i, '需要先登入這個服務'], [/connect|ECONN|network/i, '連不上這個服務']];
  const humanError = e => (ERROR_WORDS.find(([re]) => re.test(String(e || ''))) || [null, '沒有成功'])[1];
  // A step that did not go through says why in words next to it (你沒有允許、找不到需要的資料…), not only by its red dot.
  const evNote = (cls, label) => cls === 'bad' ? `<small class="ev-count">（${esc(label)}）</small>` : '';
  function callStatus(c) {
    if (c.status === 'waiting_approval') return ['wait', '等你核准'];
    if (c.status === 'running' || c.status === 'pending') return ['run', '進行中'];
    if (c.status === 'denied') return ['bad', '你沒有允許'];
    if (c.status === 'error' || c.status === 'failed') return ['bad', humanError(c.error)];
    return ['ok', c.approvedBy === 'user' ? '你允許後完成' : c.autoApproved ? '已自動完成' : '完成'];  // who allowed it, apart from whether it worked
  }
  const EFFORT_WORDS = {fast: '快速', low: '快速', standard: '標準', medium: '中', deep: '深入', high: '深入'};
  const scheduleLabel = id => String((state.data?.schedules || []).find(x => x.id === id)?.content || '排程').slice(0, 40);
  // Lists and nested details read as words, never [object Object].
  function plainValue(v, depth = 0) {
    if (v == null || v === '') return '';
    if (typeof v !== 'object') return String(v);
    if (depth > 3) return '…';
    if (Array.isArray(v)) return v.map(x => plainValue(x, depth + 1)).filter(Boolean).join(depth ? '；' : '、');
    const parts = Object.entries(v).map(([x, y]) => [x, plainValue(y, depth + 1)]).filter(([, y]) => y).map(([x, y]) => humanWords(x) + '：' + y);
    return !parts.length ? '' : depth ? '（' + parts.join('，') + '）' : parts.join('，');
  }
  function argsList(args) {
    const entries = Object.entries(args || {}).filter(([, v]) => v !== '' && v != null && (typeof v !== 'object' || plainValue(v)));
    if (!entries.length) return '<p class="muted">沒有其他內容。</p>';
    return `<dl class="args-list">${entries.map(([k, v]) => `<dt>${esc(FIELD_NAMES[k] || humanWords(k))}</dt><dd>${esc(v && typeof v === 'object' ? plainValue(v) : k === 'effort' ? EFFORT_WORDS[String(v).toLowerCase()] || String(v) : k === 'skill_id' ? skillName(v) : k === 'repeat' ? repeatName(v) : k === 'enabled' ? (v === 'off' ? '停用' : '啟用') : k === 'schedule_id' ? scheduleLabel(v) : String(v))}</dd>`).join('')}</dl>`;
  }
  // The page a Bot is reading in Zook's built-in browser, while it reads it. The link opens it in your own browser.
  function browsingCard(botId, jobs) {
    const job = (jobs || Object.values(state.jobDetails)).find(j => (jobs || j.botId === botId) && j.status === 'running' && j.browsing?.url);
    if (!job) return '';
    const who = jobs ? (state.data.bots.find(x => x.id === job.botId)?.name || 'Bot') + ' ' : '';
    let host = ''; try { const u = new URL(job.browsing.url); if (!/^https?:$/.test(u.protocol)) return ''; host = u.host; } catch (_) { return ''; }
    return `<div class="browsing-card" role="status"><span class="browsing-dot" aria-hidden="true"></span><span class="browsing-text">${esc(who)}正在看網頁：<strong>${esc(job.browsing.title || host)}</strong> <span class="muted">${esc(host)}</span></span><a class="link" href="${esc(job.browsing.url)}" rel="noopener noreferrer">開啟</a></div>`;
  }
  function approvalCards(botId, jobs) {
    return (jobs ? pendingIn(jobs) : pendingForBot(botId)).map(a => {
      const call = (a.job.toolCalls || []).find(c => c.id === a.toolCallId) || {name: a.name, label: a.label, sourceLabel: a.sourceLabel, arguments: a.arguments};
      const who = state.data.bots.find(x => x.id === a.job.botId)?.name || 'Bot';
      return `<section class="approval-card" aria-label="需要你的核准"><strong>${esc(who)}${a.job.taskTitle ? `（任務 ${esc(a.job.taskTitle)}）` : ''} 想要${esc(a.text || describeCall({...call, arguments: a.arguments})).replace(/\n/g, '<br>')}</strong>${approvalReason(a) ? `<small class="approval-reason">${esc(approvalReason(a))}</small>` : ''}<details data-approval-details="${esc(a.id)}"><summary>查看詳細內容</summary>${argsList(a.arguments)}</details><div class="actions"><button class="primary" data-action="approve" data-id="${esc(a.id)}" ${state.deciding[a.id]?'disabled':''}>允許這次</button><button class="secondary" data-action="deny" data-id="${esc(a.id)}" ${state.deciding[a.id]?'disabled':''}>不要</button></div></section>`;
    }).join('') + approvalAfter(jobs || jobsForBot(botId));
  }
  // A card the CLI stopped waiting for stays in sight, greyed, with why; after 允許這次 the wait is shown, not a silent 正在思考….
  function approvalAfter(jobs) {
    const now = Date.now();
    return jobs.filter(j => j.status === 'running').map(j => {
      const who = state.data.bots.find(x => x.id === j.botId)?.name || 'Bot';
      const what = a => a.text || describeCall({...((j.toolCalls || []).find(c => c.id === a.toolCallId) || {name: a.name, label: a.label}), arguments: a.arguments});
      const gone = (j.approvals || []).filter(a => a.status === 'expired' && a.withdrawn && !state.seenApprovals[a.id]).map(a =>
        `<section class="approval-card stale" role="status"><strong>${esc(who)} 已不再等這個核准：${esc(what(a))}</strong><small class="approval-reason">它可能改用別的做法，或已經停下。這張卡已失效，不會執行。</small><div class="actions"><button class="secondary" data-action="dismiss-approval" data-id="${esc(a.id)}">知道了</button></div></section>`).join('');
      const moved = a => (j.toolCalls || []).length > (a.callsAt ?? Infinity);  // it has done something since: no longer waiting on this
      const last = (j.approvals || []).some(a => a.status === 'pending') ? null : (j.approvals || []).filter(a => a.status === 'approved' && a.decidedAt).sort((x, y) => String(x.decidedAt).localeCompare(String(y.decidedAt))).slice(-1).filter(a => !moved(a))[0];
      const mins = last ? Math.floor((now - new Date(last.decidedAt).getTime()) / 60000) : 0;
      const after = last ? `<div class="approval-after" role="status">已允許「${esc(what(last))}」，等 ${esc(who)} 繼續${mins >= 1 ? `（已過 ${mins} 分鐘）` : '…'}${mins >= 3 ? '。如果一直沒有進展，可以按 ■ 停止後再試一次。' : ''}</div>` : '';
      return gone + after;
    }).join('');
  }
  // Everything a Bot did (Skills, connectors, web) shows in that Bot's own panel, including work done inside groups.
  function toolTimeline(botId, jobs) {
    const source = jobs || Object.values(state.jobDetails).filter(j => j.botId === botId).sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)));
    const list = source.flatMap(j => (j.toolCalls || []).map(c => ({...c, botId: j.botId, jobRunning: j.status === 'running', groupName: j.groupId ? (state.data.groups || []).find(g => g.id === j.groupId)?.name : ''})));
    if (!list.length) return '';
    const showWho = !!jobs;
    const rows = list.slice(-30).reverse().map(c => {
      // A small colored dot only: green done, yellow waiting, red interrupted (blue while running). The reason shows on hover.
      let [cls, label] = callStatus(c);
      if ((cls === 'wait' || cls === 'run') && !c.jobRunning) [cls, label] = ['bad', '已中斷'];
      const who = showWho ? (state.data.bots.find(b => b.id === c.botId)?.name || 'Bot') + ' ' : '';
      return {cls, label, text: who + describeCall(c), where: c.groupName && !showWho ? c.groupName : '', title: label + (c.name === 'native_command' && c.arguments?.summary ? '：' + c.arguments.summary : ''), n: 1};
    }).reduce((out, r) => { const last = out[out.length - 1]; if (last && last.text === r.text && last.cls === r.cls && last.label === r.label && last.where === r.where) last.n++; else out.push(r); return out; }, []);  // the same step several times in a row: one line with a count
    return `<div class="tool-timeline">${rows.map(r => `<div class="tool-event ${r.cls}" title="${esc(r.title)}"><span class="ev-dot ${r.cls}" role="img" aria-label="${esc(r.label)}"></span><span class="ev-text">${esc(r.text)}${evNote(r.cls, r.label)}${r.n > 1 ? `<small class="ev-count">（連續 ${r.n} 次）</small>` : ''}${r.where ? `<small class="ev-where">在群組「${esc(r.where)}」</small>` : ''}</span></div>`).join('')}</div>`;
  }
  // An empty conversation opens with the Bot's own greeting and questions you might ask it (made from its persona when it was
  // created). A Bot from before that asks for them once; until they arrive, a plain hello.
  const introAsked = {};  // Bot id -> when it was last asked for, so a failed try is asked for again a little later
  function emptyIntro(b) {
    const clean = t => String(t || '').replace(/[\u0000-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2066-\u2069]/g, '').replace(/^\/+/, '').trim();
    const intro = b.intro && typeof b.intro.greeting === 'string' && Array.isArray(b.intro.questions) ? {greeting: clean(b.intro.greeting), questions: b.intro.questions.filter(q => typeof q === 'string').map(clean).filter(Boolean).slice(0, 3)} : null;
    if (!intro && Date.now() - (introAsked[b.id] || 0) > 120000) { introAsked[b.id] = Date.now(); post(`bots/${encodeURIComponent(b.id)}/intro`, {}).catch(() => {}); }
    const questions = (intro?.questions || []).map(q => `<button type="button" class="intro-q" data-intro-q="${esc(q)}">${esc(q)}</button>`).join('');
    return `<div class="empty-chat">${avatar(b, 'hero')}<h1>${esc(intro ? intro.greeting : `嗨，我是${b.name}。`)}</h1>${questions ? `<div class="intro-questions" aria-label="你可以問我">${questions}</div>` : '<p class="muted">直接在下面輸入想聊的事。</p>'}</div>`;
  }
  document.addEventListener('click', e => {
    const q = e.target.closest?.('[data-intro-q]');
    if (!q) return;
    const input = $('#chat-input'), form = $('#chat-form');
    if (!input || !form) return;
    if (input.value.trim() || pendingList().length) { input.value = q.dataset.introQ; input.focus(); return; }  // a draft or a file waiting: you decide
    input.value = q.dataset.introQ; form.requestSubmit();  // asked as if typed
  });
  function chat() {
    const b = activeBot();
    if (!b) return `<main class="main"><div class="empty-chat"><h1>歡迎使用 Zook</h1><p>建立一個 Bot，開始你的工作。</p><div class="quick-actions"><button data-action="new-bot">＋ 新增 Bot</button></div></div></main>`;
    if (state.memberWork?.bot === b.id && state.data.groups.some(g => g.id === state.memberWork.group)) return memberWork(b, state.data.groups.find(g => g.id === state.memberWork.group));
    const messages = convMessages(b);
    const running = Object.entries(state.pollers).find(([id, v]) => v.botId === b.id && !v.stopping && (state.jobDetails[id]?.chatId || b.chatId) === b.chatId);  // a stopped reply still ending is not running
    const lastDone = [...messages].reverse().find(m => m.role !== 'user' && m.status !== 'running'), fileList = botFiles(b.id, (lastDone?.id || '') + ':' + messages.length);  // a finished reply may have made a file
    return `<main class="main"><header class="main-header"><button class="bot-pill" data-action="edit-bot">${avatar(b)}${esc(b.name)} <span class="muted">⌄</span></button><div class="header-actions"><button class="text-btn chat-title-btn" data-action="chats" title="目前：${esc(chatName(b))}。查看和切換這個 Bot 的所有對話">☰ 所有對話</button><button class="text-btn" data-action="new-chat" title="和這個 Bot 開始一段新的對話">＋ 開新對話</button><button class="text-btn" data-action="chat-folder" title="在 Finder 打開這段對話的資料夾：沒指定存放位置時，Bot 交出的檔案都放這裡">打開資料夾</button><button class="text-btn" data-action="share" title="把這段對話存成 Markdown 檔（附件只列檔名）">↑ 匯出對話</button>${!state.detailOpen?'<button class="text-btn" data-action="toggle-detail">顯示詳情</button>':''}</div></header>${troubleBanner(b)}${guideCard()}<div class="conversation" id="conversation">${messages.length?`<div class="conversation-inner">${olderBar(b)}${messages.map(m=>`${m.compacted ? '<div class="compact-line"><span>前面的對話已整理成摘要，Bot 從這裡接續</span></div>' : ''}<div class="date">${esc(formatDate(m.createdAt))}</div><div class="message ${m.role==='user'?'user':'assistant'}" data-mid="${esc(m.id)}">${m.role==='user'?'':avatar(b)}${partialFor(m)?`<div class="bubble md streaming">${markdown(partialFor(m))}</div>`:m.role!=='user'&&m.content&&m.status!=='running'?`<div class="bubble md ${m.status==='failed'?'error-text':''}">${withAutoMark(linkOutputs(markdown(m.content), b.id), m)}${noteLine(m)}</div>`:failureCard(m, !running && m.id === (b.messages || []).slice(-1)[0]?.id) || `<div class="bubble ${m.status==='failed'?'error-text':''}">${esc(m.status==='running'?'正在思考…':m.status==='cancelled'&&!m.content?'已停止回覆':m.status==='failed'&&!m.content?(Object.values(state.jobDetails).find(j => j.messageId === m.id)?.error || '回覆失敗，請檢查這個 Bot 的提供者設定。'):m.content)}</div>`}${waitLine(m)}${attachmentsView(m)}${dateNote(m)}${m.role!=='user'&&m.content&&m.status!=='running'?messageFiles(m.content, fileList):''}${sentNote(m)?`<div class="interject-note">${sentNote(m)}</div>`:''}${redoBar(b, m, running)}</div>`).join('')}${queuedView(b)}${sendingView(b.id + '/' + b.chatId, messages, b.queue || [])}${choiceButtons(b, messages, running)}</div>`:state.sending.some(x => x.where === b.id + '/' + b.chatId)?`<div class="conversation-inner">${sendingView(b.id + '/' + b.chatId, messages)}</div>`:emptyIntro(b)}</div>${chatRail()}<div class="composer-wrap">${toBottomButton()}${browsingCard(b.id)}${approvalCards(b.id)}${questionCards(b.id)}<div id="slash-menu" class="mention-menu slash-menu" role="listbox" aria-label="指令" hidden></div><form class="composer" id="chat-form">${pendingFiles()}<button type="button" class="icon-btn round-btn" data-action="composer-menu" aria-label="更多選項">${svg('plus')}</button><textarea id="chat-input" rows="1" placeholder="傳送訊息給 ${esc(b.name)}，輸入 / 使用指令" aria-label="輸入訊息"></textarea>${modeChips(b)}<button type="button" class="icon-btn round-btn" data-action="voice" aria-label="語音輸入">${svg('mic')}</button>${running?`<button type="button" class="send" data-action="cancel-job" data-id="${esc(running[0])}" aria-label="停止回覆">■</button><button class="send" type="submit" aria-label="傳送訊息" title="像是修正或補充的訊息會插進正在跑的回覆，其他的排在後面">↑</button>`:`<button class="send" type="submit" aria-label="傳送訊息">↑</button>`}</form></div></main>${state.detailOpen?detail(b):''}`
  }

  function activeGroup() { return state.groupId ? (state.data.groups || []).find(g => g.id === state.groupId) : null; }
  function groupMembers(g) { return (g.botIds || []).map(id => state.data.bots.find(b => b.id === id)).filter(Boolean); }
  function avatarStack(g, cls = '') {
    return `<span class="avatar-stack ${cls}" aria-hidden="true">${groupMembers(g).slice(0, 3).map(b => avatar(b)).join('')}</span>`;
  }
  function groupPreview(g) {
    const m = (g.messages || []).filter(x => x.content).slice(-1)[0];
    if (!m) return groupMembers(g).map(b => b.name).join('、') || '尚無成員';
    const who = m.role === 'user' ? '我' : m.role === 'system' ? '' : (state.data.bots.find(b => b.id === m.botId)?.name || 'Bot');
    return (who ? who + '：' : '') + plainPreview(m.content);
  }
  function groupsBlock() {
    const groups = (state.data.groups || []).filter(g => !state.query || matches(g.name) || matches(groupPreview(g)));
    if (!groups.length && state.query) return '';
    const head = `<div class="section-head group-head"><button class="section-toggle" data-action="collapse" data-id="__groups"><span>群組 ${groups.some(g => pendingIn(jobsForGroup(g.id)).length) ? '<span class="approval-badge">待核准</span>' : ''}</span><span>${state.collapsed.__groups ? '⌄' : '⌃'}</span></button><button class="icon-btn mini" data-action="new-group" aria-label="新增群組" title="新增群組（⌘⇧N）">${svg('plus')}</button></div>`;
    if (state.collapsed.__groups) return head;
    return head + (groups.length ? groups.map(g => `<button class="side-row ${state.page==='chat'&&state.groupId===g.id?'active':''}" data-action="select-group" data-id="${esc(g.id)}">${avatarStack(g)}<span class="side-copy"><span class="side-name">${esc(g.name)}${g.status==='running'?' <span class="live-dot" aria-label="討論中"></span>':''}</span><span class="side-preview">${esc(groupPreview(g))}</span></span></button>`).join('') : '<button class="side-empty" data-action="new-group">＋ 建立群組，讓多個 Bot 一起討論</button>');
  }
  // While typing in a group, tagged members are highlighted behind the text (a mirror layer under the textarea).
  function updateInputMirror() {
    const input = $('#chat-input'), mirror = $('.input-mirror'), g = activeGroup();
    if (!input || !mirror || !g) return;
    mirror.innerHTML = highlightMentions(esc(input.value), groupMembers(g)) + '\u200b';
    mirror.scrollTop = input.scrollTop;
  }
  document.addEventListener('scroll', e => { if (e.target.id === 'chat-input') updateInputMirror(); }, true);
  // @-mentions of real group members (or @所有人) are shown highlighted, so you can see who was actually tagged.
  function highlightMentions(html, members) {
    const names = members.map(b => b.name).filter(Boolean).sort((a, b) => b.length - a.length).map(n => esc(n));
    const all = ['所有人', '全部', 'everyone'];
    const words = [...names, ...all].map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (!words.length) return html;
    const re = new RegExp('@(' + words.join('|') + ')', 'gi');
    let inCode = 0;
    return html.split(/(<[^>]+>)/).map(part => {
      if (part.startsWith('<')) { if (/^<(pre|code)\b/i.test(part)) inCode++; else if (/^<\/(pre|code)>/i.test(part)) inCode = Math.max(0, inCode - 1); return part; }
      return inCode ? part : part.replace(re, '<span class="mention-tag">@$1</span>');
    }).join('');
  }
  const groupFileMark = g => { const all = g.messages || []; return all.length + ':' + all.filter(m => m.status === 'completed' || m.role === 'system').length + ':' + (all[all.length - 1]?.id || ''); };
  // A member's copy of the group's files lives inside Zook's own data; the person only needs the file's name.
  const hideInnerPaths = text => String(text).replace(MD_LINK, (whole, label, inner) => { const {path} = mdTarget(inner); if (!/\/workspaces\/[0-9a-f]{32}\//.test(path)) return whole; let name = path.split('/').pop(); try { name = decodeURIComponent(name); } catch (_) {} label = label.split('\n').map(x => x.trim()).join(' '); return label.includes(name) ? label + '（群組檔案）' : label + '：' + name + '（群組檔案）'; }).replace(/(?:…|\.\.\.)?(?:\/[^\s`'"<>()（）「」，、：]*)?\/workspaces\/[0-9a-f]{32}\/(?:[^\s`'"<>()（）「」，、]*\/)?([^\s`'"<>()（）「」，、\/]+)/g, '$1（群組檔案）').replace(/(群組檔案\s*[：:「]\s*)([^\n（]{1,200}?)（群組檔案）/g, '$1$2');  // 「群組檔案：X（群組檔案）」 says it once
  function groupMessage(g, m) {
    if (m.compacted && !m.checkOf) return '<div class="compact-line"><span>前面的討論已整理成摘要，成員從這裡接續</span></div>' + groupMessage(g, Object.assign({}, m, {compacted: false}));
    if (m.checkOf) return '';
    if (m.taskBoard) return taskBoardView(g, m);
    const fileMark = groupFileMark(g);
    if (m.role === 'system' && g.paused && m.id === (g.messages || []).filter(x => x.role === 'system').slice(-1)[0]?.id && /發言上限|回合上限/.test(m.content)) return '';  // the bar below says it
    if (m.role === 'system') {  // 「… 存了共用檔案」: a file a reply of this round already shows is not shown twice (#229: members answering at once, a note in between)
      const all = groupMsgs(g), at = all.indexOf(m), asked = all.slice(0, at).map(x => x.role).lastIndexOf('user'), said = all.slice(asked + 1, at).filter(x => x.role === 'assistant').map(x => String(x.content || '')).join('\n');
      return `<div class="system-note">${esc(m.content)}</div>${messageFiles(m.content, groupSharedFiles(g, fileMark).filter(f => !said.includes(f.name)))}`;
    }
    const tag = html => highlightMentions(html, groupMembers(g));
    if (m.role === 'user') return `<div class="date">${esc(formatDate(m.createdAt))}</div><div class="message user" data-mid="${esc(m.id)}">${m.author ? `<div class="speaker-wrap user-author"><div class="speaker">由 ${esc(m.author)} 發起</div><div class="bubble">${tag(esc(m.content))}</div></div>` : `<div class="bubble">${tag(esc(m.content))}</div>`}${attachmentsView(m)}${dateNote(m)}${sentNote(m) ? `<div class="interject-note">${sentNote(m)}</div>` : ''}</div>`;
    const b = state.data.bots.find(x => x.id === m.botId) || {name: '已刪除的 Bot', color: '#959595'};
    if (m.content) m = Object.assign({}, m, {content: hideInnerPaths(m.content)});
    const text = m.status==='running' ? '正在思考…' : m.status==='cancelled'&&!m.content ? '已停止回覆' : m.status==='failed'&&!m.content ? (Object.values(state.jobDetails).find(j => j.messageId === m.id)?.error || '回覆失敗，請檢查這個 Bot 的提供者設定。') : m.content;
    return `<div class="message assistant" data-mid="${esc(m.id)}">${avatar(b)}<div class="speaker-wrap"><div class="speaker">${esc(b.name)}${m.taskId ? ` <span class="muted">· 任務 ${esc(String((g.taskRun?.tasks || []).find(t => t.id === m.taskId)?.n || ''))}${m.taskCheck ? ' 驗收' : ''}</span>` : ''}${m.afterCheck ? ' <span class="muted">· 查核通過後自動整理</span>' : ''}</div>${m.card&&m.status==='completed'?groupCardView(m):partialFor(m)?`<div class="bubble md streaming">${tag(markdown(partialFor(m)))}</div>`:m.content&&m.status!=='running'?`<div class="bubble md">${withAutoMark(tag(markdown(m.content)), m)}${noteLine(m)}</div>`:failureCard(m, false) || `<div class="bubble ${m.status==='failed'?'error-text':''}">${esc(text)}</div>`}${waitLine(m)}${m.content&&m.status!=='running'?messageFiles(m.content, groupSharedFiles(g, fileMark).concat(botFiles(m.botId, 'g:' + fileMark)).filter((f, i, all) => all.findIndex(x => x.name === f.name) === i)):''}${groupChecks(g, m)}</div>${groupVerifyButton(g, m)}</div>`;
  }
  function groupChat() {
    const g = activeGroup(), members = groupMembers(g), running = g.status === 'running';
    const messages = groupMsgs(g), left = (g.botIds || []).filter(id => state.data.bots.some(b => b.id === id)).length, short = left < 2;  // #217: a member was deleted
    return `<main class="main"><header class="main-header"><button class="bot-pill" data-action="edit-group">${avatarStack(g)}${esc(g.name)} <span class="muted">⌄</span></button><div class="header-actions"><button class="text-btn" data-action="share" title="把群組的整段討論存成 Markdown 檔（共用檔案只列檔名）">↑ 匯出對話</button>${!state.detailOpen?'<button class="text-btn" data-action="toggle-detail">顯示詳情</button>':''}</div></header>${guideCard()}<div class="conversation" id="conversation">${messages.length?`<div class="conversation-inner">${groupOlderBar(g)}${messages.map(m => groupMessage(g, m)).join('')}${sendingView(g.id, messages)}</div>`:state.sending.some(x => x.where === g.id)?`<div class="conversation-inner">${sendingView(g.id, messages)}</div>`:groupEmptyView(g)}</div>${chatRail()}<div class="composer-wrap">${toBottomButton()}${browsingCard(null, jobsForGroup(g.id))}${taskDecisionCards(g)}${approvalCards(null, jobsForGroup(g.id))}${groupRunBar(g)}${short ? `<div class="short-banner" role="status">成員不足：這個群組只剩 ${left} 位成員，按上方群組名稱加成員後才能討論。</div>` : ''}<div class="mention-row" aria-label="指名 Bot">${members.map(b => `<button type="button" class="mention-chip" data-action="mention" data-id="${esc(b.name)}">${avatar(b)}@${esc(b.name)}</button>`).join('')}<button type="button" class="mention-chip" data-action="mention" data-id="所有人">@所有人</button></div><div id="mention-menu" class="mention-menu" role="listbox" aria-label="選擇要指名的 Bot" hidden></div><form class="composer" id="chat-form">${pendingFiles()}<button type="button" class="icon-btn round-btn" data-action="composer-menu" aria-label="更多選項">${svg('plus')}</button><div class="input-wrap"><div class="input-mirror" aria-hidden="true"></div><textarea id="chat-input" rows="1" placeholder="${short ? '成員不足，加成員後才能傳送' : running ? '討論中也可以直接插話，用 @ 指定誰接著回' : '傳送訊息給群組，用 @ 指定 Bot'}" aria-label="輸入訊息" ${short ? 'disabled' : ''}></textarea></div>${groupModeControl(g)}${effortChip()}<button type="button" class="icon-btn round-btn" data-action="voice" aria-label="語音輸入">${svg('mic')}</button>${running?`<button type="button" class="send" data-action="stop-group" data-id="${esc(g.id)}" aria-label="停止討論">■</button><button class="send" type="submit" aria-label="傳送訊息" title="像是修正或補充的訊息會加入正在進行的討論，其他的排在這輪後面">↑</button>`:`<button class="send" type="submit" aria-label="傳送訊息">↑</button>`}</form>${groupEstimateLine(g)}</div></main>${state.detailOpen?groupDetail(g):''}`;
  }
  function groupDetail(g) {
    const members = groupMembers(g), running = g.status === 'running', hostId = groupHostId(g);  // #132①: the host is marked and listed first
    const activeIds = g.activeJobIds?.length ? g.activeJobIds : g.activeJobId ? [g.activeJobId] : [];
    const activeNames = running ? activeIds.map(id => state.data.bots.find(b => b.id === state.jobDetails[id]?.botId)?.name).filter(Boolean) : [];
    const active = activeNames.length ? {name: activeNames.join('、')} : null;
    return `${detailBackdrop()}<aside class="detail" aria-label="詳情"><button class="detail-close icon-btn" data-action="toggle-detail" aria-label="關閉詳情">×</button><div class="detail-profile">${avatarStack(g,'big')}<h2>${esc(g.name)}</h2><p>${members.length} 位成員${running ? ' · 討論中' + (active ? '（' + esc(active.name) + ' 發言中）' : '') : ''}</p><button class="secondary detail-edit" data-action="edit-group">編輯群組</button></div><div class="tabs"><button data-action="group-tab" data-id="members" class="${state.groupTab==='files'?'':'active'}">成員</button><button data-action="group-tab" data-id="files" class="${state.groupTab==='files'?'active':''}">檔案</button></div>${state.groupTab==='files'?groupFilesTab(g):`${[...members].sort((a, b) => (b.id === hostId) - (a.id === hostId)).map(b => `<button class="member-row" data-member-work="${esc(b.id)}" data-group="${esc(g.id)}" title="${esc(permText(b))}">${avatar(b)}<span><strong>${esc(b.name)}${jobTitle(b)}${b.id === hostId ? ' <span class="pill host-pill">主持人</span>' : ''}</strong><small>${esc([providerShort(b.provider||state.data.settings.provider||'') + (b.model ? ' ' + b.model : ''), memberAccess(b), (g.memberCounts?.[b.id] ? '發言 ' + g.memberCounts[b.id] + ' 次' : '')].filter(Boolean).join(' · '))}</small></span></button>`).join('')}<div class="detail-empty">點成員會開啟他自己的對話視窗，可以看到他在這個討論中查了什麼、用了哪些 Skill；群組裡只有他的結論。</div>`}${usageDock()}</aside>`;
  }
  function groupModal(g = {}) {
    const editing = !!g.id, chosen = new Set(g.botIds || (state.selected && !state.groupId ? [state.selected] : []));
    modal(editing ? '編輯群組' : '新增群組', `<form id="group-form"><div class="modal-body">${editing ? '' : teamLink()}<label class="field">名稱<input name="name" maxlength="100" placeholder="留空則以成員名稱命名" value="${esc(g.name||'')}"></label><label class="field">成員（2–10 個 Bot，人越多每輪越慢）</label><div class="member-pick">${state.data.bots.map(b => `<label class="member-switch">${avatar(b)}<span class="member-copy"><strong>${esc(b.name)}</strong><small>${esc((b.persona||b.instructions||'').slice(0,50))}</small></span>${toggle(`name="botIds" value="${esc(b.id)}"`, chosen.has(b.id), b.name)}</label>`).join('') || '<p class="muted">請先建立 Bot。</p>'}</div>${groupSettingRows(g, chosen)}</div><div class="modal-foot">${editing?'<button type="button" class="link" data-action="delete-group" style="margin-right:auto;color:#b55">刪除群組</button>':''}<button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${editing?'儲存':'建立群組'}</button></div></form>`);
    $('#group-form').dataset.id = g.id || '';
    groupFormNote($('#group-form'));
  }
  async function pollGroup(groupId) {
    if (state.groupPollers[groupId]) return;
    state.groupPollers[groupId] = true;
    try {
      while (true) {
        const data = await api('groups/' + encodeURIComponent(groupId));
        const groups = state.data.groups || [];
        const i = groups.findIndex(g => g.id === groupId);
        let changed = i < 0 || JSON.stringify(groups[i]) !== JSON.stringify(data.group);
        if (i >= 0) groups[i] = data.group;
        if (changed) state.loads = (state.loads || 0) + 1;  // a full refresh asked for before this is older: it must not put the group back as it was
        for (const j of data.jobs || []) {
          if (j.status === 'running') streamJob(j);
          pollPartial(j);
          const { partial, ...rest } = j;  // the words in progress are painted by the stream, not by redrawing the page
          if (JSON.stringify(state.jobDetails[j.id]) !== JSON.stringify(rest)) changed = true; state.jobDetails[j.id] = rest;
        }
        for (const j of Object.values(state.jobDetails)) if (j.groupId === groupId && j.stopping && !(data.jobs || []).some(x => x.id === j.id)) { delete j.stopping; changed = true; }  // ended meanwhile
        if (changed) render(true);
        if (data.group.status !== 'running' && !(data.jobs || []).some(j => j.stopping)) { if (state.groupTab === 'files') delete state.groupFiles[groupId]; if (state.groupId === groupId) render(true); break; }
        await new Promise(r => setTimeout(r, 1200));
      }
    } catch (e) { toast(e.message); }
    finally { delete state.groupPollers[groupId]; }
    await refresh();
  }

  // @-mention autocomplete for group chats.
  const mention = {items: [], index: 0, start: 0};
  function hideMentionMenu() { const menu = $('#mention-menu'); if (menu) menu.hidden = true; mention.items = []; }
  function updateMentionMenu() {
    const input = $('#chat-input'), menu = $('#mention-menu'), g = activeGroup();
    if (!input || !menu || !g || document.activeElement !== input) return hideMentionMenu();
    const before = input.value.slice(0, input.selectionStart);
    const m = before.match(/(^|\s)@([^\s@]*)$/);
    if (!m) return hideMentionMenu();
    const q = m[2].toLowerCase();
    const all = [...groupMembers(g), {name: '所有人', everyone: true}];
    const items = all.filter(b => b.name.toLowerCase().includes(q)).sort((a, b) => (b.name.toLowerCase().startsWith(q)) - (a.name.toLowerCase().startsWith(q)));
    if (!items.length) return hideMentionMenu();
    const same = mention.items.length === items.length && mention.items.every((x, i) => x.name === items[i].name);
    mention.items = items; mention.start = before.length - m[2].length - 1;
    if (!same) mention.index = 0;
    menu.innerHTML = items.map((b, i) => `<button type="button" class="mention-option ${i === mention.index ? 'active' : ''}" role="option" aria-selected="${i === mention.index}" data-action="pick-mention" data-id="${i}">${b.everyone ? '<span class="mention-all">@</span>' : avatar(b)}<span><strong>${esc(b.name)}</strong><small>${esc(b.everyone ? '通知群組所有成員' : (b.instructions || '').slice(0, 40))}</small></span></button>`).join('');
    menu.hidden = false;
  }
  function pickMention(i) {
    const input = $('#chat-input'), item = mention.items[i];
    if (!input || !item) return;
    const end = input.selectionStart, insert = '@' + item.name + ' ';
    input.value = input.value.slice(0, mention.start) + insert + input.value.slice(end); updateInputMirror();
    const pos = mention.start + insert.length;
    input.focus(); input.setSelectionRange(pos, pos);
    hideMentionMenu();
  }

  function providerAddModal() {
    const catalog = state.accounts?.catalog || [], waiting = (state.accounts?.providers || []).filter(p => !p.installed && p.install?.state !== 'running');
    modal('新增模型', `<div class="modal-body"><p class="muted">已安裝的直接加入，沒安裝的可一鍵安裝。</p>${waiting.length ? `<h3 class="modal-sub">已加入、尚未安裝</h3><div class="catalog-list">${waiting.map(p => `<div class="catalog-item"><div><strong>${esc(cliShort(p))}</strong><small>${p.install?.state === 'failed' ? '上次安裝沒有完成，可以再試一次' : p.requires && !p.requirementMet ? `需要先安裝 ${esc(p.requires === 'npm' ? 'Node.js（npm）' : p.requires)}` : p.canInstall ? '可一鍵安裝' : esc(p.loginNote || '請自行安裝這個 CLI')}</small></div><div class="card-actions">${p.canInstall && (!p.requires || p.requirementMet) ? `<button class="primary" data-action="provider-install" data-id="${esc(p.id)}" data-command="${esc(p.installCommand || '')}">一鍵安裝</button>` : ''}${p.removable ? `<button class="link danger" data-action="provider-remove" data-id="${esc(p.id)}">移除</button>` : ''}</div></div>`).join('')}</div><h3 class="modal-sub">其他模型</h3>` : ''}${catalog.length ? `<div class="catalog-list">${catalog.map(c => `<div class="catalog-item"><div><strong>${esc(c.name)}</strong><small>${c.installed ? '已安裝在這台電腦' : c.requires && !c.requirementMet ? `需要先安裝 ${esc(c.requires === 'npm' ? 'Node.js（npm）' : c.requires)}` : '尚未安裝，可一鍵安裝'} · 使用 ${esc(c.vendor)} 官方安裝程式</small></div><button class="secondary" data-action="provider-add-one" data-id="${esc(c.id)}">加入</button></div>`).join('')}</div>` : '<p class="muted">內建的模型都已經加入了。</p>'}<h3 class="modal-sub">不在清單裡？</h3><p class="muted">其他命令列工具可以手動加入。</p><button class="secondary" data-action="provider-custom">＋ 手動新增</button></div>`);
  }
  function profileModal(p) {
    const types = [p.canAddLogin && {id: 'login', name: '登入帳號', hint: p.terminalLogin ? '在終端機用另一個帳號登入' : '用另一個帳號在瀏覽器登入'}, p.canAddKey && {id: 'key', name: 'API 金鑰', hint: '依用量計費，金鑰存在這台 Mac 的鑰匙圈'}].filter(Boolean);
    modal('新增帳號', `<form id="profile-form" data-id="${esc(p.id)}"><div class="modal-body"><p class="muted">為 ${esc(p.name)} 再加一個帳號，之後在 Bot 設定裡選用。</p><label class="field">名稱<input name="name" required maxlength="60" placeholder="例如：公司、個人、API"></label><div class="setting-list in-form">${settingRow('類型', '這個帳號的登入方式', dropdown('accountType', types[0].id, types))}</div><label class="field" data-key-field ${types[0].id === 'key' ? '' : 'hidden'}>API 金鑰<input name="key" type="password" autocomplete="off" spellcheck="false" placeholder="貼上金鑰"><small class="muted">金鑰只存在鑰匙圈。</small></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">新增</button></div></form>`);
  }
  function customProviderModal(p) {
    const c = p?.config || {};
    modal(p ? '編輯自訂 CLI' : '手動新增 CLI', `<form id="custom-provider-form"><div class="modal-body"><input type="hidden" name="providerId" value="${esc(p?.id || '')}"><label class="field">名稱<input name="name" required maxlength="80" placeholder="例如：Qwen" value="${esc(p?.name || '')}"></label><label class="field">CLI 指令（執行檔名稱或完整路徑）<input name="command" required placeholder="例如：qwen 或 /usr/local/bin/qwen" value="${esc(c.command || '')}"></label><label class="field">回覆用的參數<input name="args" placeholder="例如：-p {prompt}" value="${esc(c.args || '')}"><small class="muted">{prompt} 會換成訊息內容，{prompt_file} 會換成訊息檔的路徑；都沒寫時從標準輸入送入。回覆要印到標準輸出。</small></label><label class="field">指定模型的參數<input name="model_args" placeholder="例如：--model {model}" value="${esc(c.model_args || '')}"></label><label class="field">模型清單（以逗號分隔，可留空）<input name="models" placeholder="例如：qwen3-coder, qwen3-max" value="${esc((p?.models || []).join(', '))}"></label><details class="advanced"><summary>安裝與登入（選填）</summary><label class="field">安裝指令<input name="install" placeholder="例如：curl -fsSL https://example.com/install.sh | bash" value="${esc(c.install || '')}"></label><label class="field">登入指令<input name="login" placeholder="例如：qwen login" value="${esc(c.login || '')}"></label><label class="field">確認登入狀態的指令（成功時結束代碼為 0）<input name="status" placeholder="例如：qwen auth status" value="${esc(c.status || '')}"></label></details></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${p ? '儲存' : '新增'}</button></div></form>`);
  }
  // Accounts and usage always change together: a new model or account shows its usage right away.
  async function refreshQuota() {
    try { state.quota = await api('quota'); } catch (e) { state.quota = {error: e.message}; }
    if (state.page === 'usage' && !$('#account-code-form input:focus')) render(true);
  }
  async function loadAccounts() {
    state.accounts = await api('accounts');
    state.providers = (await api('providers')).providers;
    if (state.page === 'usage' && !$('#account-code-form input:focus')) render(true);
    pollAccounts();
    for (const p of state.accounts.providers.filter(x => x.needsCheck)) checkSignIn(p.id);
  }
  // A sign-in can succeed while the account still cannot use the CLI: try it once and say so on the card.
  async function checkSignIn(id) {
    state.signInChecks = state.signInChecks || {};
    if (state.signInChecks[id]) return;
    state.signInChecks[id] = true;
    try { await post('accounts/' + encodeURIComponent(id) + '/check'); await loadAccounts(); }
    catch (_) {} finally { delete state.signInChecks[id]; }
  }
  window.addEventListener('focus', () => { if (state.page === 'usage' && state.accounts) loadAccounts().catch(() => {}); });  // back from the browser or Terminal
  async function reloadAccounts() { await loadAccounts(); refreshQuota(); }
  async function detectUsage() {
    state.quota = await post('quota/detect');
    await Promise.all((state.accounts?.providers || []).filter(p => p.terminalLogin && p.status === 'logged_in' && p.id === 'gemini').map(p => post('accounts/' + encodeURIComponent(p.id) + '/check').catch(() => {})));
    await loadAccounts();
  }
  async function pollAccounts() {
    if (state.accountPolling) return;
    state.accountPolling = true;
    let waited = false;
    try {
      while (state.page === 'usage' && state.accounts?.providers?.some(p => p.login?.state === 'running' || p.install?.state === 'running' || (p.profiles || []).some(a => a.login?.state === 'running'))) {
        waited = true;
        await new Promise(r => setTimeout(r, 1500));
        const next = await api('accounts');
        if (JSON.stringify(next) !== JSON.stringify(state.accounts)) { state.accounts = next; if (state.page === 'usage' && !$('#account-code-form input:focus')) render(true); }
      }
      if (waited) refreshQuota();  // a sign-in or install just finished
      state.providers = (await api('providers')).providers;
    } catch (e) { toast(e.message); }
    finally { state.accountPolling = false; }
  }
  // Accounts a Bot can use for a provider: the CLI's own sign-in, plus any extra ones added on the 各模型使用量 page.
  const accountOptions = (provider, selected) => {
    const list = ((state.providers || []).find(p => p.id === (provider || state.data.settings.provider || 'codex')) || {}).accounts || [];
    return `<option value="">預設帳號</option>` + list.map(a => `<option value="${esc(a.id)}" ${selected === a.id ? 'selected' : ''}>${esc(a.name)}${a.type === 'key' ? '（API 金鑰）' : ''}</option>`).join('');
  };
  const accountCount = provider => (((state.providers || []).find(p => p.id === (provider || state.data.settings.provider || 'codex')) || {}).accounts || []).length;
  const accountField = (provider, selected) => `帳號<select name="account">${accountOptions(provider, selected)}</select>${accountCount(provider) ? '' : '<small class="muted field-hint">這個模型目前只有預設帳號。<button type="button" class="link" data-action="accounts-from-form">新增其他帳號</button></small>'}`;
  // 模型與帳號 in the Bot form: 使用預設, 自動選擇, then each CLI on its own sign-in followed by each of its extra accounts.
  const choiceOptions = (provider, account) => {
    const list = (state.providers || [{id: 'codex', name: 'Codex'}, {id: 'claude', name: 'Claude'}]);
    const picked = provider === 'auto' ? 'auto' : (provider || '') + (account ? '::' + account : '');
    // 已用完／剩不到 20% (#154③). Reading every account live can take a while; until it is back, a CLI's own sign-in goes by the
    // figures the sidebar rings already have, so the words are in the list before anything is picked.
    const ringMark = id => { const r = (state.data?.rings || []).find(x => x.id === id); return !r || r.left == null ? '' : r.left <= 0 ? '・已用完' : r.left < 20 ? '・剩不到 20%' : ''; };
    const mark = value => { const [p, a] = value.split('::'), id = p || state.data.settings.provider || 'codex'; return p === 'auto' ? '' : !state.quota && !a ? ringMark(id) : levelMark(accountLevel(id, a || '')); };
    const opt = (value, label) => `<option value="${esc(value)}" ${picked === value ? 'selected' : ''}>${esc(label + mark(value))}</option>`;
    const kept = !provider && account ? list.flatMap(p => p.accounts || []).find(a => a.id === account) : null;  // an older Bot: the default CLI with one of its extra accounts
    const fallback = list.find(p => p.id === (state.data.settings.provider || 'codex')), short = String(fallback?.name || state.data.settings.provider || 'Codex').split('（')[0];
    // The default CLI on its own sign-in is the 預設 line, so it is not listed again, unless this Bot picked it itself (then （固定）).
    return opt('', '預設（目前是 ' + short + '）') + (kept ? opt('::' + account, '預設（目前是 ' + short + '）・' + kept.name) : '') + opt('auto', '自動配（依人格和工作指示）') + list.map(p => {
      const name = String(p.name).split('（')[0], extra = p.accounts || [], own = p.id === fallback?.id ? (picked === p.id ? '固定' : null) : '';
      return (own === null ? '' : opt(p.id, extra.length || own ? name + '（' + [extra.length ? '預設帳號' : '', own].filter(Boolean).join('・') + '）' : name)) + extra.map(a => opt(p.id + '::' + a.id, name + '（' + a.name + (a.type === 'key' ? '・API 金鑰' : '') + '）')).join('');
    }).join('');
  };
  const providerOptions = (selected, withDefault, withAuto) => (withDefault ? `<option value="" ${!selected ? 'selected' : ''}>使用預設</option>` : '') + (withAuto ? `<option value="auto" ${selected === 'auto' ? 'selected' : ''}>自動選擇</option>` : '') + (state.providers || [{id: 'codex', name: 'Codex'}, {id: 'claude', name: 'Claude'}]).map(p => `<option value="${esc(p.id)}" ${selected === p.id ? 'selected' : ''}>${esc(p.name)}${p.installed === false ? '（未安裝）' : ''}</option>`).join('');

