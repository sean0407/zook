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

  // Minimal Markdown → HTML. Everything is escaped first; only known tags are produced and links must be http(s).
  function mdInline(text) {
    const codes = [];
    let s = esc(text).replace(/`([^`\n]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
    s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => `<a href="${u}" rel="noopener noreferrer">${t}</a>`)
      .replace(/(^|[\s(（])(https?:\/\/[^\s<)）]+)/g, (_, p, u) => `${p}<a href="${u}" rel="noopener noreferrer">${u}</a>`)
      .replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, '<strong>$1</strong>')
      .replace(/__(?=\S)([\s\S]*?\S)__/g, '<strong>$1</strong>')
      .replace(/~~(?=\S)([\s\S]*?\S)~~/g, '<del>$1</del>')
      .replace(/(^|[^*\w])\*(?=\S)([^*\n]*?\S)\*(?!\*)/g, '$1<em>$2</em>');
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
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
        out.push(`<${tag}>${items.map(t => `<li>${t.split('\n').map(mdInline).join('<br>')}</li>`).join('')}</${tag}>`); continue;
      }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|>|[-*+]\s|\d+[.)]\s)/.test(lines[i]) && !(lines[i].includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1]))) para.push(lines[i++]);
      if (!para.length) para.push(lines[i++]);
      out.push(`<p>${para.map(mdInline).join('<br>')}</p>`);
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
    detailOpen: true,
    query: '',
    launcher: false,
    collapsed: {},
    integrations: null,
    usage: null,
    modal: null,
    pollers: {},
    jobDetails: {},
    deciding: {},
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
  });

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

  function messagePreview(b) {
    const m = (b.messages || []).slice(-1)[0];
    return m?.content || b.instructions || '開始新的對話'
  }

  function matches(s) {
    return String(s || '').toLowerCase().includes(state.query.toLowerCase())
  }

  function botRow(b) {
    return `<button class="side-row ${state.page==='chat'&&!state.groupId&&b.id===state.selected?'active':''}" data-action="select-bot" data-id="${esc(b.id)}" ${state.query ? '' : `draggable="true" data-drag-bot="${esc(b.id)}"`}>${avatar(b)}<span class="side-copy"><span class="side-name">${esc(b.name)}${pendingForBot(b.id).length ? ' <span class="approval-badge">待核准</span>' : ''}</span><span class="side-preview">${esc(messagePreview(b))}</span></span></button>`
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
    return `<aside class="sidebar"><div class="side-top"><div class="brand">Zook<span>✳</span></div><div class="side-actions"><button class="icon-btn" data-action="search-focus" aria-label="搜尋">${svg('search')}</button><button class="icon-btn" data-action="new-bot" aria-label="新增 Bot">${svg('plus')}</button></div></div><div class="search"><span class="glass tiny-icon">${svg('search')}</span><input id="side-search" placeholder="搜尋 Bot、對話和知識" aria-label="搜尋 Bot、對話和知識" value="${esc(state.query)}"></div><div class="side-scroll">${groupsBlock()}${pinned.length?block('已釘選',pinned,true):''}${sections.map(s=>block(s,bots.filter(b=>!b.pinned&&(b.section||'我的 Bots')===s))).join('')}${state.query?'':'<button class="side-empty add-section" data-action="new-section">＋ 新增分組</button>'}${messageHits().length?`<div class="section-head">對話搜尋結果</div>${messageHits().map(h=>`<button class="side-row" data-action="open-message" data-bot="${esc(h.b.id)}" data-id="${esc(h.m.id)}">${avatar(h.b)}<span class="side-copy"><span class="side-name">${esc(h.b.name)} · ${esc(chatName(h.b, h.c))}</span><span class="side-preview">${esc(snippet(h.m.content))}</span></span></button>`).join('')}`:''}${state.query&&state.data.knowledge.filter(n=>matches(n.title)||matches(n.content)).length?`<div class="section-head">知識搜尋結果</div>${state.data.knowledge.filter(n=>matches(n.title)||matches(n.content)).map(n=>`<button class="side-row" data-action="edit-note" data-id="${esc(n.id)}"><span>▤</span><span class="side-copy"><span class="side-name">${esc(n.title)}</span><span class="side-preview">${esc(n.content)}</span></span></button>`).join('')}`:''}</div><div class="side-footer"><div class="user-avatar">S</div><div class="user-name">我的工作區</div><div class="launcher"><button class="icon-btn launcher-btn" data-action="launcher" aria-label="開啟功能選單" aria-expanded="${state.launcher}">${svg('grid')}</button>${state.launcher?`<div class="popup">${[['usage','◷','使用量'],['schedules','◴','排程'],['knowledge','▤','知識庫'],['memory','◎','記憶'],['accounts','⚿','模型帳號'],['skills','✳','Skills 與連接器'],['settings','⚙','設定']].map(x=>`<button class="nav-item" data-action="page" data-id="${x[0]}"><span>${x[1]}</span>${x[2]}</button>`).join('')}</div>`:''}</div><button class="icon-btn" data-action="page" data-id="settings" aria-label="設定">${svg('settings')}</button>${state.update?.available ? `<button class="icon-btn update-btn" data-action="update-open" aria-label="有新版 ${esc(state.update.latest)}，按這裡更新" title="有新版 ${esc(state.update.latest)}">${svg('download')}</button>` : ''}</div></aside>`
  }

  function jobsForBot(botId) { return Object.values(state.jobDetails).filter(j => j.botId === botId && !j.groupId); }
  function jobsForGroup(groupId) { return Object.values(state.jobDetails).filter(j => j.groupId === groupId); }
  function pendingIn(jobs) { return jobs.flatMap(j => (j.approvals || []).filter(a => a.status === 'pending').map(a => ({...a, job: j}))); }
  function pendingForBot(botId) { return pendingIn(jobsForBot(botId)); }
  function argsView(args) { try { return JSON.stringify(args, null, 2) || '{}'; } catch (_) { return String(args); } }
  // Plain-language descriptions of what a Bot does: no tool names, ids or JSON on screen.
  const FIELD_NAMES = {path: '檔案', content: '內容', name: '名稱', persona: '人格', instructions: '工作指示', provider: '模型', model: '模型版本',
    color: '顏色', bot_names: '成員', group_name: '群組', message: '訊息', skill_id: 'Skill', argv: '要執行的內容', cwd: '位置', scope: '範圍', query: '搜尋內容',
    target: '對象', repeat: '重複', time: '時間', date: '日期', day: '每月幾號', enabled: '啟用', schedule_id: '排程'};
  const humanWords = t => String(t || '').replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim();
  const skillName = id => (state.integrations?.skills || []).find(x => x.id === id)?.name || 'Skill';
  const fileName = p => String(p || '').split('/').pop() || '檔案';
  function describeCall(c) {
    const a = c.arguments || {};
    switch (c.name) {
      case 'zook_read_skill': return `閱讀 Skill「${skillName(a.skill_id) === 'Skill' ? (c.sourceLabel || 'Skill') : skillName(a.skill_id)}」的說明`;
      case 'zook_read_skill_resource': return `查看 Skill「${skillName(a.skill_id)}」的參考資料「${fileName(a.path)}」`;
      case 'zook_run_skill_helper': return `執行 Skill「${skillName(a.skill_id)}」附帶的小程式`;
      case 'zook_workspace_list': return '查看工作區裡有哪些檔案';
      case 'zook_workspace_read': return `讀取檔案「${fileName(a.path)}」`;
      case 'zook_workspace_write': return `把內容存成檔案「${fileName(a.path)}」`;
      case 'zook_list_team': return '查看團隊裡有哪些 Bot 和群組';
      case 'zook_create_bot': return `新增 Bot「${a.name || ''}」`;
      case 'zook_create_group': return `建立群組「${a.name || (a.bot_names || []).join('、')}」`;
      case 'zook_start_group_discussion': return `在群組「${a.group_name || ''}」發起討論`;
      case 'zook_remember': return `記住一件事：「${String(a.content || '').slice(0, 60)}」`;
      case 'zook_list_schedules': return '查看排程';
      case 'zook_create_schedule': return `建立排程「${String(a.content || '').slice(0, 40)}」`;
      case 'zook_update_schedule': return `修改排程「${scheduleLabel(a.schedule_id)}」`;
      case 'zook_delete_schedule': return `刪除排程「${scheduleLabel(a.schedule_id)}」`;
      case 'web_search': return a.query ? `上網搜尋「${String(a.query).slice(0, 60)}」` : '上網搜尋';
      case 'native_write': return `修改檔案「${fileName(a.path)}」`;
      case 'native_command': return '在工作資料夾執行指令';
      case 'web_fetch': return `讀取網頁「${(String(a.url || '').match(/^https?:\/\/([^/]+)/) || [, a.url || '網頁'])[1]}」`;
    }
    return `使用「${c.sourceLabel || '外部服務'}」${c.label ? '的' + humanWords(c.label) + '功能' : ''}`;
  }
  const ERROR_WORDS = [[/denied|cancel/i, '你沒有允許這個動作'], [/Paths must remain|Symlinks|outside/i, '這個檔案不在 Bot 的工作區內'],
    [/unavailable|not found|No such/i, '找不到需要的資料'], [/exceeds|too large|limit/i, '內容太大'], [/timed? ?out|timeout/i, '等太久沒有回應'],
    [/authori|401|403|sign in/i, '需要先登入這個服務'], [/connect|ECONN|network/i, '連不上這個服務']];
  const humanError = e => (ERROR_WORDS.find(([re]) => re.test(String(e || ''))) || [null, '沒有成功'])[1];
  function callStatus(c) {
    if (c.status === 'waiting_approval') return ['wait', '等你核准'];
    if (c.status === 'running' || c.status === 'pending') return ['run', '進行中'];
    if (c.status === 'denied') return ['bad', '你沒有允許'];
    if (c.status === 'error' || c.status === 'failed') return ['bad', humanError(c.error)];
    return ['ok', c.autoApproved ? '已自動完成' : '完成'];
  }
  const scheduleLabel = id => String((state.data?.schedules || []).find(x => x.id === id)?.content || '排程').slice(0, 40);
  function argsList(args) {
    const entries = Object.entries(args || {}).filter(([, v]) => v !== '' && v != null);
    if (!entries.length) return '<p class="muted">沒有其他內容。</p>';
    return `<dl class="args-list">${entries.map(([k, v]) => `<dt>${esc(FIELD_NAMES[k] || humanWords(k))}</dt><dd>${esc(Array.isArray(v) ? v.join('、') : typeof v === 'object' ? Object.entries(v).map(([x, y]) => humanWords(x) + '：' + y).join('，') : k === 'skill_id' ? skillName(v) : k === 'repeat' ? repeatName(v) : k === 'enabled' ? (v === 'off' ? '停用' : '啟用') : k === 'schedule_id' ? scheduleLabel(v) : String(v))}</dd>`).join('')}</dl>`;
  }
  function approvalCards(botId, jobs) {
    return (jobs ? pendingIn(jobs) : pendingForBot(botId)).map(a => {
      const call = (a.job.toolCalls || []).find(c => c.id === a.toolCallId) || {name: a.name, label: a.label, sourceLabel: a.sourceLabel, arguments: a.arguments};
      const who = state.data.bots.find(x => x.id === a.job.botId)?.name || 'Bot';
      return `<section class="approval-card" aria-label="需要你的核准"><strong>${esc(who)} 想要${esc(a.text || describeCall({...call, arguments: a.arguments}))}</strong>${approvalReason(a) ? `<small class="approval-reason">${esc(approvalReason(a))}</small>` : ''}<details data-approval-details="${esc(a.id)}"><summary>查看詳細內容</summary>${argsList(a.arguments)}</details><div class="actions"><button class="primary" data-action="approve" data-id="${esc(a.id)}" ${state.deciding[a.id]?'disabled':''}>允許這次</button><button class="secondary" data-action="deny" data-id="${esc(a.id)}" ${state.deciding[a.id]?'disabled':''}>不要</button></div></section>`;
    }).join('');
  }
  // Everything a Bot did (Skills, connectors, web) shows in that Bot's own panel, including work done inside groups.
  function toolTimeline(botId, jobs) {
    const source = jobs || Object.values(state.jobDetails).filter(j => j.botId === botId).sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)));
    const list = source.flatMap(j => (j.toolCalls || []).map(c => ({...c, botId: j.botId, jobRunning: j.status === 'running', groupName: j.groupId ? (state.data.groups || []).find(g => g.id === j.groupId)?.name : ''})));
    if (!list.length) return '';
    const showWho = !!jobs;
    return `<div class="tool-timeline">${list.slice(-30).reverse().map(c => {
      // A small colored dot only: green done, yellow waiting, red interrupted (blue while running). The reason shows on hover.
      let [cls, label] = callStatus(c);
      if ((cls === 'wait' || cls === 'run') && !c.jobRunning) [cls, label] = ['bad', '已中斷'];
      const who = showWho ? (state.data.bots.find(b => b.id === c.botId)?.name || 'Bot') + ' ' : '';
      return `<div class="tool-event ${cls}" title="${esc(label + (c.name === 'native_command' && c.arguments?.command ? '：' + c.arguments.command : ''))}"><span class="ev-dot ${cls}" role="img" aria-label="${esc(label)}"></span><span class="ev-text">${esc(who + describeCall(c))}${c.groupName && !showWho ? `<small class="ev-where">在群組「${esc(c.groupName)}」</small>` : ''}</span></div>`;
    }).join('')}</div>`;
  }
  function chat() {
    const b = activeBot();
    if (!b) return `<main class="main"><div class="empty-chat"><h1>歡迎使用 Zook</h1><p>建立一個 Bot，開始你的工作。</p><div class="quick-actions"><button data-action="new-bot">＋ 新增 Bot</button></div></div></main>`;
    const messages = b.messages || [];
    const running = Object.entries(state.pollers).find(([id, v]) => v.botId === b.id && (state.jobDetails[id]?.chatId || b.chatId) === b.chatId);
    return `<main class="main"><header class="main-header"><button class="bot-pill" data-action="edit-bot">${avatar(b)}${esc(b.name)} <span class="muted">⌄</span></button><div class="header-actions"><button class="text-btn chat-title-btn" data-action="chats" title="所有對話">☰ ${esc(chatName(b))}</button><button class="text-btn" data-action="new-chat">＋ 新對話</button><button class="text-btn" data-action="share">↑ 匯出對話</button>${!state.detailOpen?'<button class="text-btn" data-action="toggle-detail">顯示詳情</button>':''}</div></header><div class="conversation" id="conversation">${messages.length?`<div class="conversation-inner">${messages.map(m=>`<div class="date">${esc(formatDate(m.createdAt))}</div><div class="message ${m.role==='user'?'user':'assistant'}" data-mid="${esc(m.id)}">${m.role==='user'?'':avatar(b)}${m.role!=='user'&&m.content&&m.status!=='running'?`<div class="bubble md ${m.status==='failed'?'error-text':''}">${markdown(m.content)}${noteLine(m)}</div>`:`<div class="bubble ${m.status==='failed'?'error-text':''}">${esc(m.status==='running'?'正在思考…':m.status==='cancelled'&&!m.content?'已停止回覆':m.status==='failed'&&!m.content?(Object.values(state.jobDetails).find(j => j.messageId === m.id)?.error || '回覆失敗，請檢查這個 Bot 的提供者設定。'):m.content)}</div>`}${redoBar(b, m, running)}</div>`).join('')}</div>`:`<div class="empty-chat">${avatar(b,'hero')}<h1>今天想一起完成什麼？</h1><p>和 ${esc(b.name)} 開始一段對話。</p><div class="quick-actions"><button data-action="page" data-id="knowledge">▤ 管理知識庫</button><button data-action="page" data-id="usage">◷ 查看使用量</button><button data-action="page" data-id="settings">⚙ 設定模型</button></div></div>`}</div><div class="composer-wrap">${approvalCards(b.id)}<form class="composer" id="chat-form"><button type="button" class="icon-btn" data-action="composer-menu" aria-label="更多選項">${svg('plus')}</button><textarea id="chat-input" rows="1" placeholder="傳送訊息給 ${esc(b.name)}" aria-label="輸入訊息"></textarea><button type="button" class="icon-btn" data-action="voice" aria-label="語音輸入">${svg('mic')}</button>${running?`<button type="button" class="send" data-action="cancel-job" data-id="${esc(running[0])}" aria-label="停止回覆">■</button>`:`<button class="send" type="submit" aria-label="傳送訊息">↑</button>`}</form></div></main>${state.detailOpen?detail(b):''}`
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
    return (who ? who + '：' : '') + m.content;
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
  function groupMessage(g, m) {
    if (m.role === 'system') return `<div class="system-note">${esc(m.content)}</div>`;
    const tag = html => highlightMentions(html, groupMembers(g));
    if (m.role === 'user') return `<div class="date">${esc(formatDate(m.createdAt))}</div><div class="message user" data-mid="${esc(m.id)}">${m.author ? `<div class="speaker-wrap user-author"><div class="speaker">由 ${esc(m.author)} 發起</div><div class="bubble">${tag(esc(m.content))}</div></div>` : `<div class="bubble">${tag(esc(m.content))}</div>`}</div>`;
    const b = state.data.bots.find(x => x.id === m.botId) || {name: '已刪除的 Bot', color: '#959595'};
    const text = m.status==='running' ? '正在思考…' : m.status==='cancelled'&&!m.content ? '已停止回覆' : m.status==='failed'&&!m.content ? (Object.values(state.jobDetails).find(j => j.messageId === m.id)?.error || '回覆失敗，請檢查這個 Bot 的提供者設定。') : m.content;
    return `<div class="message assistant" data-mid="${esc(m.id)}">${avatar(b)}<div class="speaker-wrap"><div class="speaker">${esc(b.name)}</div>${m.content&&m.status!=='running'?`<div class="bubble md">${tag(markdown(m.content))}${noteLine(m)}</div>`:`<div class="bubble ${m.status==='failed'?'error-text':''}">${esc(text)}</div>`}</div></div>`;
  }
  function groupChat() {
    const g = activeGroup(), members = groupMembers(g), running = g.status === 'running';
    const messages = g.messages || [];
    return `<main class="main"><header class="main-header"><button class="bot-pill" data-action="edit-group">${avatarStack(g)}${esc(g.name)} <span class="muted">⌄</span></button><div class="header-actions"><button class="text-btn" data-action="share">↑ 匯出對話</button>${!state.detailOpen?'<button class="text-btn" data-action="toggle-detail">顯示詳情</button>':''}</div></header><div class="conversation" id="conversation">${messages.length?`<div class="conversation-inner">${messages.map(m => groupMessage(g, m)).join('')}</div>`:`<div class="empty-chat">${avatarStack(g,'hero')}<h1>${esc(g.name)}</h1><p>直接發訊息讓成員輪流回覆，或用 @ 指定由誰處理。Bot 也可以用 @ 把工作交給其他成員。</p></div>`}</div><div class="composer-wrap">${approvalCards(null, jobsForGroup(g.id))}<div class="mention-row" aria-label="指名 Bot">${members.map(b => `<button type="button" class="mention-chip" data-action="mention" data-id="${esc(b.name)}">${avatar(b)}@${esc(b.name)}</button>`).join('')}<button type="button" class="mention-chip" data-action="mention" data-id="所有人">@所有人</button></div><div id="mention-menu" class="mention-menu" role="listbox" aria-label="選擇要指名的 Bot" hidden></div><form class="composer" id="chat-form"><button type="button" class="icon-btn" data-action="composer-menu" aria-label="更多選項">${svg('plus')}</button><div class="input-wrap"><div class="input-mirror" aria-hidden="true"></div><textarea id="chat-input" rows="1" placeholder="傳送訊息給群組，用 @ 指定 Bot" aria-label="輸入訊息"></textarea></div><button type="button" class="icon-btn" data-action="voice" aria-label="語音輸入">${svg('mic')}</button>${running?`<button type="button" class="send" data-action="stop-group" data-id="${esc(g.id)}" aria-label="停止討論">■</button>`:`<button class="send" type="submit" aria-label="傳送訊息">↑</button>`}</form></div></main>${state.detailOpen?groupDetail(g):''}`;
  }
  function groupDetail(g) {
    const members = groupMembers(g), running = g.status === 'running';
    const activeIds = g.activeJobIds?.length ? g.activeJobIds : g.activeJobId ? [g.activeJobId] : [];
    const activeNames = running ? activeIds.map(id => state.data.bots.find(b => b.id === state.jobDetails[id]?.botId)?.name).filter(Boolean) : [];
    const active = activeNames.length ? {name: activeNames.join('、')} : null;
    return `<aside class="detail"><button class="detail-close icon-btn" data-action="toggle-detail" aria-label="關閉詳情">×</button><div class="detail-profile">${avatarStack(g,'big')}<h2>${esc(g.name)}</h2><p>${members.length} 位成員${running ? ' · 討論中' + (active ? '（' + esc(active.name) + ' 發言中）' : '') : ''}</p><button class="secondary detail-edit" data-action="edit-group">編輯群組</button></div><div class="detail-title">成員</div>${members.map(b => `<button class="member-row" data-action="select-bot" data-id="${esc(b.id)}">${avatar(b)}<span><strong>${esc(b.name)}</strong><small>${esc([(b.provider||state.data.settings.provider||'') + (b.model ? ' ' + b.model : ''), '主動性：' + permissionName(b.permissionMode || state.data.settings.permissionMode)].filter(Boolean).join(' · '))}</small></span></button>`).join('')}<div class="detail-empty">點成員可以查看他在討論中查了什麼、用了哪些 Skill。</div></aside>`;
  }
  function groupModal(g = {}) {
    const editing = !!g.id, chosen = new Set(g.botIds || (state.selected && !state.groupId ? [state.selected] : []));
    modal(editing ? '編輯群組' : '新增群組', `<form id="group-form"><div class="modal-body"><label class="field">名稱<input name="name" maxlength="100" placeholder="留空則以成員名稱命名" value="${esc(g.name||'')}"></label><label class="field">成員（2–6 個 Bot）</label><div class="member-pick">${state.data.bots.map(b => `<label class="member-switch">${avatar(b)}<span class="member-copy"><strong>${esc(b.name)}</strong><small>${esc((b.persona||b.instructions||'').slice(0,50))}</small></span>${toggle(`name="botIds" value="${esc(b.id)}"`, chosen.has(b.id), b.name)}</label>`).join('') || '<p class="muted">請先建立 Bot。</p>'}</div><p class="muted">每則訊息最多 ${8} 次 Bot 回覆（含 Bot 之間的交接），避免無限來回。</p></div><div class="modal-foot">${editing?'<button type="button" class="link" data-action="delete-group" style="margin-right:auto;color:#b55">刪除群組</button>':''}<button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${editing?'儲存':'建立群組'}</button></div></form>`);
    $('#group-form').dataset.id = g.id || '';
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
        for (const j of data.jobs || []) { if (JSON.stringify(state.jobDetails[j.id]) !== JSON.stringify(j)) changed = true; state.jobDetails[j.id] = j; }
        if (changed) render(true);
        if (data.group.status !== 'running') break;
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

  // Provider sign-in: Zook runs each CLI's own login; credentials stay with the CLI.
  function accountsPage() {
    const list = state.accounts?.providers;
    if (!list) return '<div class="blank">正在讀取登入狀態…</div>';
    const badge = {logged_in: ['ok', '已登入'], not_logged_in: ['warn', '尚未登入'], installed: ['', '已安裝'], unknown: ['', '狀態不明'], not_installed: ['warn', '未安裝']};
    const flowView = (l, kind, id, account = '') => {
      if (!l) return '';
      if (l.state === 'running') {
        if (kind === 'install') return `<div class="login-flow"><strong>正在安裝／更新…</strong>${l.log?.length ? `<pre class="flow-log">${esc(l.log.slice(-6).join('\n'))}</pre>` : ''}<button class="link" data-action="install-cancel" data-id="${esc(id)}">取消</button></div>`;
        return `<div class="login-flow"><strong>${l.deviceCode ? '請在登入頁輸入這組代碼' : '已在瀏覽器開啟登入頁'}</strong>${l.deviceCode ? `<div class="device-code">${esc(l.deviceCode)}</div>` : ''}${l.url ? `<p class="muted">沒有自動開啟？<a href="${esc(l.url)}" rel="noopener noreferrer">點這裡開啟登入頁</a></p>` : '<p class="muted">正在等待 CLI 提供登入網址…</p>'}${l.needsCode ? `<form class="code-form" id="account-code-form" data-id="${esc(id)}" data-account="${esc(account)}"><input name="code" placeholder="如果頁面顯示授權碼，貼在這裡" aria-label="授權碼" autocomplete="off"><button class="primary">送出</button></form>` : ''}<button class="link" data-action="account-cancel" data-id="${esc(id)}" data-account="${esc(account)}">取消登入</button></div>`;
      }
      if (l.state === 'succeeded') return `<div class="login-flow done">${kind === 'install' ? '安裝／更新完成。' : '登入完成。'}</div>`;
      return `<div class="login-flow error-text">${esc(l.error || (kind === 'install' ? '安裝沒有完成。' : '登入沒有完成。'))}${kind === 'install' && l.log?.length ? `<pre class="flow-log">${esc(l.log.slice(-6).join('\n'))}</pre>` : ''}</div>`;
    };
    return `<div class="page-actions"><p class="muted">Zook 透過各家官方 CLI 使用你的帳號。登入由 CLI 在瀏覽器完成，帳密與權杖只由 CLI 保存，Zook 不會讀取。</p><button class="primary" data-action="provider-add">＋ 新增模型</button></div><div class="account-list">${list.map(p => {
      const [cls, label] = badge[p.status] || badge.unknown, l = p.login, running = l?.state === 'running' || p.install?.state === 'running';
      const detail = [p.method, p.plan && p.plan.toUpperCase(), p.workspace, p.email].filter(Boolean).map(esc).join(' · ');
      const sub = detail || (p.installed ? (p.custom ? esc(p.config?.command || '') : '已安裝') : (p.requires && !p.requirementMet ? `需要先安裝 ${esc(p.requires === 'npm' ? 'Node.js（npm）' : p.requires)}` : '尚未安裝這個 CLI'));
      const loginButtons = p.installed && p.loginMethods.length ? p.loginMethods.map((m, i) => `<button class="${i === 0 && p.status !== 'logged_in' ? 'primary' : 'secondary'}" data-action="account-login" data-id="${esc(p.id)}" data-method="${esc(m.id)}">${p.status === 'logged_in' && i === 0 ? '重新登入' : esc(m.label)}</button>`).join('') : '';
      const v = p.version, upToDate = v && v.current && v.latest && !v.updateAvailable;
      const versionLine = !p.installed ? '' : `<div class="version-line">${v?.current ? `<span>版本 ${esc(v.current)}</span>` : '<span>版本未知</span>'}${v?.updateAvailable ? `<span class="pill warn">有新版 ${esc(v.latest)}</span>` : upToDate ? '<span class="pill ok">已是最新版</span>' : v?.error ? `<span class="muted">${esc(v.error)}</span>` : ''}</div>`;
      const installLabel = !p.installed ? '一鍵安裝' : v?.updateAvailable ? `更新到 ${esc(v.latest)}` : p.canUpdate ? '檢查並更新' : '重新安裝';
      const installBtn = p.canInstall && (!p.requires || p.requirementMet || p.installed) && !(upToDate && p.installed) ? `<button class="${!p.installed || v?.updateAvailable ? 'primary' : 'secondary'}" data-action="provider-install" data-id="${esc(p.id)}" data-command="${esc(p.installed && p.canUpdate ? '' : p.installCommand)}">${installLabel}</button>` : '';
      const notes = [!p.tools ? 'Skill、MCP、記憶寫入等 Zook 工具目前只支援 Codex 和 Claude；用這個提供者的 Bot 會以純對話方式回覆。' : '', p.installed && !p.loginMethods.length && p.loginNote ? p.loginNote : ''].filter(Boolean);
      const profiles = (p.profiles || []).map(a => {
        const [acls, alabel] = badge[a.status] || badge.unknown, busy = a.login?.state === 'running';
        const info = [a.type === 'key' ? 'API 金鑰' : a.method || '登入帳號', a.plan && a.plan.toUpperCase(), a.email].filter(Boolean).map(esc).join(' · ');
        const buttons = a.type === 'login' && !busy ? p.loginMethods.map((m, i) => `<button class="${i === 0 && a.status !== 'logged_in' ? 'primary' : 'secondary'}" data-action="account-login" data-id="${esc(p.id)}" data-account="${esc(a.id)}" data-method="${esc(m.id)}">${a.status === 'logged_in' && i === 0 ? '重新登入' : esc(m.label)}</button>`).join('') : '';
        return `<div class="profile-row"><div class="profile-head"><div><strong>${esc(a.name)}</strong><p class="muted small">${info}</p></div><span class="pill ${acls}">${alabel}</span></div>${flowView(a.login, 'login', p.id, a.id)}${!busy ? `<div class="actions">${buttons}<span class="spacer"></span><button class="link danger" data-action="profile-delete" data-id="${esc(p.id)}" data-account="${esc(a.id)}" data-name="${esc(a.name)}">移除帳號</button></div>` : ''}</div>`;
      }).join('');
      const profileBlock = p.installed && (p.canAddLogin || p.canAddKey) ? `<div class="profiles"><div class="profiles-head"><strong>其他帳號</strong><button class="secondary" data-action="profile-add" data-id="${esc(p.id)}">＋ 新增帳號</button></div>${profiles || '<p class="muted small">可以再加入其他登入帳號或 API 金鑰，並在每個 Bot 的設定裡指定要用哪一個。</p>'}</div>` : '';
      return `<article class="account-card"><div class="account-head"><div><h3>${esc(p.name)}${p.custom ? ' <span class="pill">自訂</span>' : ''}</h3><p class="muted">${sub}</p>${versionLine}</div><span class="pill ${cls}">${label}</span></div>${notes.map(n => `<p class="muted small provider-note">${esc(n)}</p>`).join('')}${flowView(p.install, 'install', p.id)}${flowView(l, 'login', p.id)}${!running ? `<div class="actions">${loginButtons}${installBtn}${p.custom ? `<button class="secondary" data-action="provider-edit" data-id="${esc(p.id)}">編輯設定</button>` : ''}<span class="spacer"></span>${p.status === 'logged_in' && p.canLogout ? `<button class="link danger" data-action="account-logout" data-id="${esc(p.id)}">登出</button>` : ''}${p.removable ? `<button class="link danger" data-action="provider-remove" data-id="${esc(p.id)}">從 Zook 移除</button>` : ''}</div>` : ''}${profileBlock}</article>`;
    }).join('')}</div>`;
  }
  function providerAddModal() {
    const catalog = state.accounts?.catalog || [];
    modal('新增模型', `<div class="modal-body"><p class="muted">選擇要加入 Zook 的模型。已經裝在電腦上的會直接加入；還沒安裝的，加入後可以一鍵安裝。</p>${catalog.length ? `<div class="catalog-list">${catalog.map(c => `<div class="catalog-item"><div><strong>${esc(c.name)}</strong><small>${c.installed ? '已安裝在這台電腦' : c.requires && !c.requirementMet ? `需要先安裝 ${esc(c.requires === 'npm' ? 'Node.js（npm）' : c.requires)}` : '尚未安裝，可一鍵安裝'} · 使用 ${esc(c.vendor)} 官方安裝程式</small></div><button class="secondary" data-action="provider-add-one" data-id="${esc(c.id)}">加入</button></div>`).join('')}</div>` : '<p class="muted">內建的模型都已經加入了。</p>'}<h3 class="modal-sub">不在清單裡？</h3><p class="muted">其他模型的命令列工具也可以手動加入（適合熟悉電腦設定的人）。</p><button class="secondary" data-action="provider-custom">＋ 手動新增</button></div>`);
  }
  function profileModal(p) {
    const types = [p.canAddLogin && {id: 'login', name: '登入帳號', hint: '用另一個帳號在瀏覽器登入'}, p.canAddKey && {id: 'key', name: 'API 金鑰', hint: '依用量計費，金鑰存在這台 Mac 的鑰匙圈'}].filter(Boolean);
    modal('新增帳號', `<form id="profile-form" data-id="${esc(p.id)}"><div class="modal-body"><p class="muted">為 ${esc(p.name)} 再加入一個帳號。加入後，到 Bot 的「進階設定」選擇要用哪個帳號。</p><label class="field">名稱<input name="name" required maxlength="60" placeholder="例如：公司、個人、API"></label><div class="setting-list in-form">${settingRow('類型', '這個帳號的登入方式', dropdown('accountType', types[0].id, types))}</div><label class="field" data-key-field ${types[0].id === 'key' ? '' : 'hidden'}>API 金鑰<input name="key" type="password" autocomplete="off" spellcheck="false" placeholder="貼上金鑰"><small class="muted">金鑰只會存進 macOS 鑰匙圈，不會寫進 Zook 的資料檔，也不會傳到手機。</small></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">新增</button></div></form>`);
  }
  function customProviderModal(p) {
    const c = p?.config || {};
    modal(p ? '編輯自訂 CLI' : '手動新增 CLI', `<form id="custom-provider-form"><div class="modal-body"><input type="hidden" name="providerId" value="${esc(p?.id || '')}"><label class="field">名稱<input name="name" required maxlength="80" placeholder="例如：Qwen" value="${esc(p?.name || '')}"></label><label class="field">CLI 指令（執行檔名稱或完整路徑）<input name="command" required placeholder="例如：qwen 或 /usr/local/bin/qwen" value="${esc(c.command || '')}"></label><label class="field">回覆用的參數<input name="args" placeholder="例如：-p {prompt}" value="${esc(c.args || '')}"><small class="muted">{prompt} 會換成訊息內容，{prompt_file} 會換成存放訊息的檔案路徑；兩個都沒寫時，訊息會從標準輸入送入。CLI 需要把回覆印到標準輸出後結束。</small></label><label class="field">指定模型的參數<input name="model_args" placeholder="例如：--model {model}" value="${esc(c.model_args || '')}"></label><label class="field">模型清單（以逗號分隔，可留空）<input name="models" placeholder="例如：qwen3-coder, qwen3-max" value="${esc((p?.models || []).join(', '))}"></label><details class="advanced"><summary>安裝與登入（選填）</summary><label class="field">安裝指令<input name="install" placeholder="例如：curl -fsSL https://example.com/install.sh | bash" value="${esc(c.install || '')}"></label><label class="field">登入指令<input name="login" placeholder="例如：qwen login" value="${esc(c.login || '')}"></label><label class="field">確認登入狀態的指令（成功時結束代碼為 0）<input name="status" placeholder="例如：qwen auth status" value="${esc(c.status || '')}"></label></details></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${p ? '儲存' : '新增'}</button></div></form>`);
  }
  async function reloadAccounts() {
    state.accounts = await api('accounts');
    state.providers = (await api('providers')).providers;
    if (state.page === 'accounts') render(true);
    pollAccounts();
  }
  async function pollAccounts() {
    if (state.accountPolling) return;
    state.accountPolling = true;
    try {
      while (state.page === 'accounts' && state.accounts?.providers?.some(p => p.login?.state === 'running' || p.install?.state === 'running' || (p.profiles || []).some(a => a.login?.state === 'running'))) {
        await new Promise(r => setTimeout(r, 1500));
        const next = await api('accounts');
        if (JSON.stringify(next) !== JSON.stringify(state.accounts)) { state.accounts = next; if (state.page === 'accounts' && !$('#account-code-form input:focus')) render(true); }
      }
      state.providers = (await api('providers')).providers;
    } catch (e) { toast(e.message); }
    finally { state.accountPolling = false; }
  }
  // Accounts a Bot can use for a provider: the CLI's own sign-in, plus any extra ones added on the 模型帳號 page.
  const accountOptions = (provider, selected) => {
    const list = ((state.providers || []).find(p => p.id === (provider || state.data.settings.provider || 'codex')) || {}).accounts || [];
    return `<option value="">預設帳號</option>` + list.map(a => `<option value="${esc(a.id)}" ${selected === a.id ? 'selected' : ''}>${esc(a.name)}${a.type === 'key' ? '（API 金鑰）' : ''}</option>`).join('');
  };
  const accountCount = provider => (((state.providers || []).find(p => p.id === (provider || state.data.settings.provider || 'codex')) || {}).accounts || []).length;
  const accountField = (provider, selected) => `帳號<select name="account">${accountOptions(provider, selected)}</select>${accountCount(provider) ? '' : '<small class="muted field-hint">這個模型目前只有預設帳號。<button type="button" class="link" data-action="accounts-from-form">新增其他帳號</button></small>'}`;
  const providerOptions = (selected, withDefault) => (withDefault ? `<option value="" ${!selected ? 'selected' : ''}>使用預設</option>` : '') + (state.providers || [{id: 'codex', name: 'Codex'}, {id: 'claude', name: 'Claude'}]).map(p => `<option value="${esc(p.id)}" ${selected === p.id ? 'selected' : ''}>${esc(p.name)}${p.installed === false ? '（未安裝）' : ''}</option>`).join('');

  // Usage page: provider quotas and per-Bot token usage.
  const fmtN = n => Number(n || 0).toLocaleString();
  function fmtReset(t) {
    if (!t) return '';
    const d = new Date(typeof t === 'number' ? t * 1000 : t);
    if (isNaN(d)) return '';
    const mins = Math.round((d - Date.now()) / 60000);
    const rel = mins <= 0 ? '即將重置' : mins < 60 ? `${mins} 分鐘後重置` : mins < 1440 ? `${Math.floor(mins / 60)} 小時 ${mins % 60} 分後重置` : `${Math.floor(mins / 1440)} 天 ${Math.floor(mins % 1440 / 60)} 小時後重置`;
    return `${rel}（${d.toLocaleString('zh-TW', {month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit'})}）`;
  }
  const loadingBlock = text => `<div class="loading-block" role="status"><span class="spinner" aria-hidden="true"></span><span>${esc(text)}</span></div>`;
  function quotaSection() {
    const q = state.quota;
    if (!q) return `<section class="usage-block"><h2>帳號額度</h2>${loadingBlock('正在讀取各帳號額度…')}</section>`;
    if (q.error) return `<section class="usage-block"><h2>帳號額度</h2><div class="blank error-text">${esc(q.error)}</div></section>`;
    const money = v => v == null ? '' : ' · $' + v.toFixed(v < 1 ? 3 : 2);
    return `<section class="usage-block"><h2>帳號額度</h2><div class="quota-grid">${q.providers.map(p => {
      const s = p.quota, shortName = p.name.split('（')[0];
      const chips = [p.plan && p.plan.toUpperCase(), p.workspace, p.method].filter(Boolean);
      let body;
      if (p.status !== 'logged_in') body = `<p class="quota-empty">登入後才能查看額度。<button class="link" data-action="page" data-id="accounts">前往模型帳號</button></p>`;
      else if (p.apiBilling) body = '<p class="quota-empty">使用 API 計費，沒有 5 小時／每週額度，費用依用量計算。</p>';
      else if (p.noQuotaApi) body = '<p class="quota-empty">Grok CLI 目前只在它自己的互動介面（/usage）提供方案額度，Zook 還讀不到剩餘量。下方是 Zook 自己記錄的 Grok 用量。</p>';
      else if (!s || !(s.windows || []).length) body = `<p class="quota-empty">${p.id === 'claude' ? '正在取得額度…（也可以按「立即更新」）' : '目前無法取得額度資料。'}</p>`;
      else body = s.windows.map(w => {
        const used = Math.max(0, Math.min(100, w.usedPercent)), left = Math.round((100 - used) * 10) / 10, level = used >= 90 ? 'bad' : used >= 70 ? 'warn' : '';
        return `<div class="quota-row"><div class="quota-label"><span>${esc(w.label)}</span><span><b>剩餘 ${left}%</b><small>已用 ${Math.round(used * 10) / 10}%</small></span></div><div class="quota-track"><div class="quota-bar ${level}" style="width:${used}%"></div></div><small class="quota-reset">${esc(fmtReset(w.resetsAt))}</small></div>`;
      }).join('') + (s.credits && (s.credits.unlimited || (s.credits.balance && s.credits.balance !== '0')) ? `<p class="quota-extra">額外額度：${s.credits.unlimited ? '不限' : esc(s.credits.balance)}</p>` : '')
        + (s.limitReached ? `<p class="error-text small">已達上限：${esc(s.limitReached)}</p>` : '');
      const z = p.zookUsage;
      const coupons = s?.resetCredits && p.status === 'logged_in' ? `<span class="quota-coupon">額度重置券 ${s.resetCredits} 張（在 Codex 中使用）</span>` : '';
      const zook = !(z && p.status === 'logged_in') ? '<div class="zook-usage empty"></div>' : `<div class="zook-usage"><span class="zook-usage-title"><span>用量</span>${coupons}</span><div><span>近 5 小時</span><b>${fmtN(z.fiveHour.tokens)}</b><small>${z.fiveHour.replies} 次回覆${money(z.fiveHour.costUsd)}</small></div><div><span>近 7 天</span><b>${fmtN(z.week.tokens)}</b><small>${z.week.replies} 次回覆${money(z.week.costUsd)}</small></div></div>`;
      // Only four status words: 即時查詢 / 定時更新 / 手動查詢 / 暫無資料.
      const stamp = d => { const t = new Date(d); return isNaN(t) ? '' : ` · ${t.getMonth() + 1}/${t.getDate()} ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`; };
      const when = s?.updatedAt && (s.windows || []).length ? (s.source === 'live' ? '即時查詢' : s.source === 'probe' ? '手動查詢' : '定時更新') + stamp(s.updatedAt) : '暫無資料';
            const refresh = p.id === 'claude' && p.status === 'logged_in' && !p.apiBilling ? `<button class="secondary small-btn" data-action="refresh-claude-quota" title="會送出一個極小的 Claude 請求來讀取最新額度">立即更新</button>` : '';
      return `<article class="quota-card"><header class="quota-head"><div class="quota-title"><h3>${esc(shortName)}</h3>${p.vendor ? `<span>${esc(p.vendor)}</span>` : ''}</div>${p.status === 'logged_in' ? '<span class="pill ok">已登入</span>' : '<span class="pill warn">未登入</span>'}</header><div class="quota-account">${p.email ? `<div class="quota-email" title="${esc(p.email)}">${esc(p.email)}</div>` : `<div class="quota-email muted">${p.id === 'grok' && p.status === 'logged_in' ? '在「模型帳號」重新登入一次即可顯示帳號' : '帳號未提供'}</div>`}${chips.length ? `<div class="quota-chips">${chips.map(c => `<span>${esc(c)}</span>`).join('')}</div>` : ''}</div><div class="quota-body">${body}</div>${zook}<footer class="quota-foot"><small>${esc(when)}</small>${refresh}</footer></article>`;
    }).join('')}</div></section>`;
  }
  function botUsageSection() {
    const u = state.botUsage;
    if (!u) return `<section class="usage-block"><h2>各 Bot Token 用量</h2>${loadingBlock('正在整理用量…')}</section>`;
    if (u.error) return `<section class="usage-block"><h2>各 Bot Token 用量</h2><div class="blank error-text">${esc(u.error)}</div></section>`;
    const rows = u.bots || [], max = Math.max(1, ...rows.flatMap(r => Object.values(r.daily)));
    const days = (u.days || []).map(d => d.slice(5).replace('-', '/'));
    return `<section class="usage-block"><h2>各 Bot Token 用量</h2>${rows.length ? `<div class="bot-usage"><div class="bot-usage-row head"><span>Bot</span><span>回覆</span><span>輸入</span><span>輸出</span><span>估算費用</span><span>近 7 天（${esc(days[0] || '')}–${esc(days.at(-1) || '')}）</span></div>${rows.map(r => `<div class="bot-usage-row"><span class="bot-cell">${avatar(r)}<span><strong>${esc(r.name)}</strong><small>${Object.entries(r.models).sort((a, b) => b[1] - a[1]).map(([m]) => esc(m)).join('、')}</small></span></span><span>${fmtN(r.replies)}${r.groupReplies ? `<small>群組 ${fmtN(r.groupReplies)}</small>` : ''}</span><span>${fmtN(r.input)}${r.cachedInput ? `<small>快取 ${fmtN(r.cachedInput)}</small>` : ''}</span><span>${fmtN(r.output)}</span><span>${r.costUsd == null ? '<small>訂閱內</small>' : '$' + r.costUsd.toFixed(r.costUsd < 1 ? 4 : 2) + '<small>API 等值</small>'}</span><span class="spark">${Object.values(r.daily).map((v, i) => `<i style="height:${Math.max(v ? 8 : 2, Math.round(v / max * 100))}%" title="${esc(days[i])}：${fmtN(v)} tokens"></i>`).join('')}</span></div>`).join('')}</div>` : '<div class="blank">還沒有用量紀錄。Bot 回覆後就會出現在這裡。</div>'}</section>`;
  }

  // Permission modes: which tool actions need the user's approval.
  const PERMISSIONS = [
    {id: 'manual', name: '謹慎', hint: '有變動就先問', rows: ['讀取：直接執行（外部服務先問）', 'Zook 內變更：先問', '程式與外部服務：先問']},
    {id: 'auto', name: '自動', hint: 'Zook 內自動完成，涉及程式或外部服務才問', rows: ['讀取：直接執行', 'Zook 內變更：直接執行', '程式與外部服務：先問']},
    {id: 'bypass', name: '全部允許', hint: '只有高風險動作會問', rows: ['讀取：直接執行', 'Zook 內變更：直接執行', '程式與外部服務：直接執行']},
  ];
  const ALWAYS_ASK = '刪除、帳號與權限、寄信或發布';
  const noteLine = m => m.note ? `<small class="msg-note">${esc(m.note)}</small>` : '';
  const providerList = () => (state.providers || [{id: 'codex', name: 'Codex'}, {id: 'claude', name: 'Claude'}]).map(p => ({id: p.id, name: String(p.name).split('（')[0]}));
  const providerShort = id => providerList().find(p => p.id === id)?.name || id;
  const permissionName = id => PERMISSIONS.find(p => p.id === id)?.name || '謹慎';
  // Shared controls: every choice in the UI is a dropdown (with optional descriptions) or an on/off switch.
  function dropdown(name, value, options, attrs = '') {
    const cur = options.find(o => o.id === value) || options[0] || {name: ''};
    return `<div class="dd"><input type="hidden" name="${esc(name)}" value="${esc(cur.id ?? '')}" ${attrs}><button type="button" class="dd-btn" aria-haspopup="listbox" aria-expanded="false"><span class="dd-label">${esc(cur.name)}</span><span class="dd-chev" aria-hidden="true">⌄</span></button><div class="dd-menu" role="listbox">${options.map(o => `<button type="button" class="dd-opt ${o.id === cur.id ? 'selected' : ''}" role="option" aria-selected="${o.id === cur.id}" data-value="${esc(o.id)}" data-label="${esc(o.name)}"><span><strong>${esc(o.name)}</strong>${o.hint ? `<small>${esc(o.hint)}</small>` : ''}</span><span class="dd-check" aria-hidden="true">✓</span></button>`).join('')}</div></div>`;
  }
  const toggle = (attrs, on, label) => `<input type="checkbox" class="switch" role="switch" aria-label="${esc(label)}" ${attrs} ${on ? 'checked' : ''}>`;
  const settingRow = (title, desc, control) => `<div class="setting-row"><div class="setting-copy"><strong>${title}</strong>${desc ? `<span>${desc}</span>` : ''}</div><div class="setting-control">${control}</div></div>`;
  // Where a Bot's built-in tools may work. Only set here on the Mac.
  const ACCESS = [{id: 'full', name: '整台 Mac', hint: '可以讀寫任何檔案、執行任何指令，和直接使用 CLI 一樣'},
                  {id: 'folder', name: '指定資料夾', hint: '只能讀寫你選的那個資料夾'},
                  {id: 'workspace', name: '只限 Bot 工作區', hint: '只能讀寫 Zook 為它準備的資料夾'}];
  const permissionOptions = withDefault => (withDefault ? [{id: '', name: '使用預設（' + permissionName(state.data.settings.permissionMode) + '）', hint: '跟著「設定」裡的主動性'}] : []).concat(PERMISSIONS.map(p => ({id: p.id, name: p.name, hint: p.hint})));
  // Remote access: off unless turned on here. Pairing and revoking can only be done on this Mac.
  // App updates: checked automatically unless turned off; installing is always the user's decision.
  const noticeSection = () => `<h2 class="settings-h">通知</h2><div class="setting-list">${settingRow('排程通知', '排程跑完、失敗或錯過，以及排程執行中需要你核准時，在這台 Mac 跳出通知。點通知會打開那段對話。', toggle('data-schedule-notify', state.data.settings.scheduleNotify !== false, '排程通知'))}</div>`;
  function updateSection() {
    const u = state.update || {};
    const status = u.state === 'checking' ? '正在檢查…' : u.available ? `有新版 ${esc(u.latest)}` : u.error ? esc(u.error) : u.latest ? '已是最新版' : '尚未檢查';
    return `<h2 class="settings-h">更新</h2><div class="setting-list">${settingRow('目前版本', `${esc(u.current || '開發版本')} · ${status}`, u.available ? '<button class="primary" data-action="update-open">更新</button>' : '<button class="secondary" data-action="update-check">檢查更新</button>')}${settingRow('自動檢查更新', '開啟 Zook 時到 GitHub 查看有沒有新版。有新版只會提醒，不會自動安裝。', toggle('data-auto-update', state.data.settings.autoUpdateCheck !== false, '自動檢查更新'))}</div>`;
  }
  function updateModal() {
    const u = state.update || {};
    const busy = u.state === 'downloading' || u.state === 'ready' || u.state === 'applying';
    const body = busy ? `<p><strong>${u.state === 'downloading' ? '正在下載並驗證新版…' : '正在安裝，Zook 會自動重新開啟…'}</strong></p><p class="muted">請不要關閉 Zook。</p>`
      : `<p>目前版本 ${esc(u.current || '')}，新版 <strong>${esc(u.latest || '')}</strong>。</p>${u.notes ? `<pre class="update-notes">${esc(u.notes)}</pre>` : ''}${u.error ? `<p class="error-text">${esc(u.error)}</p>` : ''}${u.canInstall ? '<p class="muted">更新時 Zook 會重新開啟。Bot、對話和設定都會保留。</p>' : '<p class="muted">這個 Zook 無法自行更新（可能是從磁碟映像直接開啟，或是開發版本）。請把 Zook 拖到「應用程式」後再試，或到 GitHub 下載新版。</p>'}`;
    modal('更新 Zook', `<div class="modal-body">${body}</div>${busy ? '' : `<div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">稍後</button>${u.canInstall ? '<button class="primary" data-action="update-install">下載並安裝</button>' : ''}</div>`}`);
  }
  async function refreshUpdate(redraw = true) {
    try {
      const before = JSON.stringify(state.update);
      state.update = await api('update');
      if (redraw && before !== JSON.stringify(state.update) && !state.modal && !document.querySelector('.dd.open')) render(true);
    } catch (_) {}
  }
  async function installUpdate() {
    state.update = await post('update/download'); updateModal();
    while (state.update.state === 'downloading') { await new Promise(r => setTimeout(r, 1000)); state.update = await api('update'); }
    if (state.update.state !== 'ready') { updateModal(); return; }
    try { state.update = await post('update/apply'); } catch (e) { state.update = await api('update'); state.update.error = e.message; updateModal(); return; }
    updateModal();
    window.webkit?.messageHandlers?.zookWindow?.postMessage({quit: true});
  }
  function remoteSection() {
    const r = state.remote;
    if (!r) return `<h2 class="settings-h">遠端連線</h2>${loadingBlock('正在讀取…')}`;
    if (!r.available) return '';
    const status = !r.enabled ? '已關閉' : r.connected ? '已連上中繼伺服器' : '連不上中繼伺服器';
    const when = d => d ? formatDate(d) : '尚未使用';
    const devices = r.devices.length ? r.devices.map(d => `<div class="setting-row device-row"><div class="setting-copy"><strong>${esc(d.name)}${d.online ? ' <span class="pill ok">連線中</span>' : ''}</strong><span>配對於 ${esc(formatDate(d.createdAt))} · 最後使用：${esc(when(d.lastSeenAt))}</span></div><div class="setting-control"><button class="secondary small-btn" data-action="remote-revoke" data-id="${esc(d.id)}">撤銷</button></div></div>`).join('') : '<p class="muted small">還沒有配對任何裝置。</p>';
    return `<h2 class="settings-h">遠端連線</h2><div class="setting-list">${settingRow('讓其他裝置連到這台 Mac', '關閉時 Zook 只在這台 Mac 上使用。開啟後，已配對的裝置可以透過中繼伺服器對話和核准動作；內容全程加密，中繼伺服器讀不到。', toggle('data-remote-enabled', r.enabled, '遠端連線'))}${settingRow('中繼伺服器', '你自己的中繼伺服器網址，以 wss:// 開頭。', `<input class="relay-input" data-remote-relay value="${esc(r.relayUrl)}" placeholder="wss://…" aria-label="中繼伺服器網址" spellcheck="false">`)}${settingRow('狀態', r.enabled && !r.connected ? '請確認網址正確，而且這台 Mac 有連上網路。' : '', `<span class="remote-status ${r.enabled ? (r.connected ? 'ok' : 'bad') : ''}">${status}</span>`)}</div><div class="remote-devices"><div class="remote-devices-head"><strong>已配對的裝置</strong><button class="secondary small-btn" data-action="remote-pair" ${r.enabled ? '' : 'disabled'}>配對新裝置</button></div>${devices}</div><p class="muted small perm-always">手機上只能對話、參與群組、核准動作、查看動態和使用量。帳號、主動性、各種開關、配對與刪除只能在這台 Mac 上操作。</p>`;
  }
  async function loadRemote(quiet) {
    try { state.remote = await api('remote'); } catch (_) { if (!quiet) state.remote = {available: false, devices: []}; }
    if (state.page === 'settings' && !document.querySelector('.modal [data-pairing]') && document.activeElement?.dataset?.remoteRelay === undefined && !document.querySelector('.dd.open')) render(true);
  }
  function pairingModal(p) {
    modal('配對新裝置', `<div class="modal-body pairing" data-pairing><p class="muted">在 iPhone 的 Zook App 選「配對 Mac」，掃描這個 QR code。</p><img class="pairing-qr" src="${esc(p.qr)}" alt="配對用的 QR code"><p class="muted small">5 分鐘內有效，只能使用一次。請不要截圖傳給別人：拿到這個 QR code 的人可以配對到你的 Mac。</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="remote-pair-cancel">取消配對</button><button type="button" class="primary" data-action="close-modal">完成</button></div>`);
    const before = (state.remote?.devices || []).length, started = Date.now();
    const timer = setInterval(async () => {
      if (!document.querySelector('.modal [data-pairing]')) { clearInterval(timer); loadRemote(true); return; }
      try { state.remote = await api('remote'); } catch (_) { return; }
      if (state.remote.devices.length > before) { clearInterval(timer); closeModal(); render(true); toast('已配對「' + state.remote.devices.at(-1).name + '」'); }
      else if (!state.remote.pairing || Date.now() - started > 300000) { clearInterval(timer); closeModal(); render(true); toast('配對已過期，請重新產生'); }
    }, 2000);
  }
  function permissionSection(current) {
    return `<div class="setting-list">${settingRow('主動性', 'Bot 執行動作前要不要先問你。這是所有 Bot 的預設，個別 Bot 可在編輯 Bot 時另外設定。', dropdown('permissionMode', current, permissionOptions(false), 'data-permission-mode'))}${settingRow('上網搜尋', '讓所有 Bot 可以搜尋、讀取網頁，取得價格、新聞等最新資訊。會記在動態，不會逐次詢問。', toggle('data-web-search', state.data.settings.webSearch, '上網搜尋'))}</div><p class="muted small perm-always">${ALWAYS_ASK}屬高風險，任何主動性都會先問。</p>`;
  }

  const approvalReason = a => /^zook_(create|update|delete)_schedule$/.test(a.name) ? '排程會在你不在時自動執行，不論主動性都要你核准' : CATEGORY_REASON[a.category];
  const CATEGORY_REASON = {danger: '高風險動作（刪除、安全性或對外發送），一律需要核准', code: '會執行程式碼', external_write: '會修改外部服務', external_read: '會查詢外部服務', internal: '會變更 Zook 內的資料'};

  function personaPanel(b) {
    const draft = state.personaDrafts?.[b.id];
    const value = draft ?? (b.persona || '');
    const dirty = draft !== undefined && draft !== (b.persona || '');
    return `<form class="persona-panel" id="persona-form" data-id="${esc(b.id)}"><label class="detail-title" for="persona-input">人格檔案</label><textarea id="persona-input" name="persona" maxlength="20000" placeholder="還沒有人格設定。描述這個 Bot 的個性、說話語氣與價值觀，每次回覆都會帶入。">${esc(value)}</textarea><div class="persona-actions"><small class="muted">${value.length.toLocaleString()} / 20,000 字</small>${dirty ? '<button type="button" class="link" data-action="persona-reset">還原</button>' : ''}<button class="primary small-btn" ${dirty ? '' : 'disabled'}>儲存人格</button></div></form>`;
  }

  // Directory: Skills / connectors / plugins in one place, laid out like an app directory.
  const SOURCE_NAMES = {zook: 'Zook Skills', agents: '你的 Skills', claude: 'Claude Skills', codex: 'Codex Skills', shared: '共用 Skills 庫', builtin: 'Zook 內建',
    'claude-code': 'Claude Code 插件'};
  const ICON_COLORS = ['#2585f6', '#13bf78', '#f59a0a', '#ed2f9b', '#14b8a6', '#ff6d0c', '#9254ff', '#a47545'];
  function itemIcon(name, icon) {
    if (icon) return `<span class="dir-icon has-img"><img src="${esc(icon)}" alt="" loading="lazy"></span>`;
    const text = String(name || '?').replace(/^[^A-Za-z0-9一-鿿]+/, '');
    let h = 0; for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return `<span class="dir-icon" style="--ic:${ICON_COLORS[h % ICON_COLORS.length]}">${esc((text[0] || '?').toUpperCase())}</span>`;
  }
  const MCP_SOURCE_NAMES = {zook: '在 Zook 新增', codex: '來自 Codex 設定', claude: '來自 Claude 設定', builtin: 'Zook 內建'};
  function sourceName(source, kind) {
    if (!source) return '其他';
    if (kind === 'mcp' && MCP_SOURCE_NAMES[source]) return MCP_SOURCE_NAMES[source];
    if (source.startsWith('plugin:')) return '插件：' + ((state.integrations?.plugins || []).find(p => p.id === source)?.displayName || source.slice(7));
    return SOURCE_NAMES[source] || source;
  }
  function mcpStatus(i) {
    const t = state.mcpTests[i.id];
    if (i.id === 'builtin:workspace') return ['ok', '可用'];
    if (i.gmail && i.needsSetup) return ['', '尚未設定'];
    if (i.needsKey) return ['', '需要金鑰'];
    if (i.copied) return ['', '已複製到 Zook'];
    if (t?.status === 'ready') return ['ok', `已連線 · ${t.toolCount} 個工具`];
    if (t?.status === 'error') return ['bad', '連線失敗'];
    return ['', '尚未測試連線'];
  }
  function directoryItems(tab) {
    const inv = state.integrations || {}, settings = state.data.settings || {};
    if (tab === 'skills') {
      const off = new Set(settings.disabledSkills || []);
      return (inv.skills || []).map(i => ({id: i.id, icon: i.icon, name: i.name, description: i.description || '', group: sourceName(i.plugin || i.source),
        meta: i.imported ? '改用 Zook 裡的那一份' : i.source === 'zook' && SOURCE_NAMES[i.origin] ? '匯入自 ' + SOURCE_NAMES[i.origin] : i.source === 'zook' && i.origin === 'pack' ? '來自設定包' : sourceName(i.plugin || i.source),
        on: !i.imported && !off.has(i.id), toggle: 'skill', toggleLabel: off.has(i.id) ? '開放給所有 Bot' : '所有 Bot 共用中',
        moved: i.imported ? '已匯入' : '', importable: i.source !== 'zook' && !i.imported, removable: !!i.removable, canUpdate: !!i.canUpdate, note: (i.notes || []).join(' ')}));
    }
    if (tab === 'mcp') {
      return (inv.mcp || []).map(i => {
        const on = (settings.sharedMcp || []).includes(i.id);
        const [cls, label] = mcpStatus(i);
        const description = i.id === 'builtin:workspace' ? '讓 Bot 在自己的工作區讀寫檔案。寫入前會依權限設定請你核准。' : i.needsKey ? '這個連接器是從設定包匯入的，金鑰沒有跟著過來。按「貼上金鑰」完成設定。' : i.copied ? 'Zook 已經有自己的一份，Bot 用的是 Zook 那一份。' : i.gmail && i.needsSetup ? '讓 Bot 搜尋、讀取你的 Gmail，建立草稿和寄信。用 Google 的應用程式密碼連接，寄信前一定會先請你核准。' : (t => t?.status === 'error' ? '連線失敗：' + t.error : t?.status === 'ready' ? '可用工具：' + (t.tools || []).slice(0, 8).map(x => x.name.replace(/_/g, ' ')).join('、') : i.gmail ? `已連接 ${i.address}。Bot 可以搜尋、讀信、建立草稿和寄信；寄信前一定會先請你核准。` : i.editable ? (i.config.command || i.config.url) : sourceName(i.plugin || i.source, 'mcp') + '。按「測試連線」確認是否可以使用。')(state.mcpTests[i.id]);
        return {id: i.id, icon: i.icon, name: i.id === 'builtin:workspace' ? 'Bot 工作區' : i.name, description, group: sourceName(i.plugin || i.source, 'mcp'), meta: i.copied ? '來源設定仍保留' : i.needsKey ? '等待金鑰' : on ? '所有 Bot 共用中' : '未開啟',
          on: on && !i.copied && !i.needsKey, toggle: 'mcp', toggleLabel: on ? '停用這個連接器' : '開放給所有 Bot', status: i.copied ? null : [cls, label], test: i.id !== 'builtin:workspace' && !i.needsSetup && !i.needsKey && !i.copied, editable: !!i.editable, gmail: !!i.gmail, needsSetup: !!i.needsSetup,
          needsKey: !!i.needsKey, moved: i.copied ? '已複製' : '', copyable: !!i.copyable};
      });
    }
    return (inv.plugins || []).map(pl => ({id: pl.id, icon: pl.icon, name: pl.displayName, description: pl.description || '', group: pl.sourceName,
      meta: [pl.skillCount ? pl.skillCount + ' 個 Skill' : '', pl.mcpCount ? pl.mcpCount + ' 個連接器' : '', pl.version ? 'v' + pl.version : ''].filter(Boolean).join(' · ') || '沒有 Zook 可用的內容',
      note: pl.hasHooks || pl.hasCommands ? '部分功能只在原本的工具中運作' : '', on: pl.enabled, toggle: 'plugin', toggleLabel: pl.enabled ? '已啟用' : '啟用'}));
  }
  function directoryPage(tab) {
    if (!state.integrations) return '<div class="blank">正在讀取…</div>';
    const q = (state.dirQuery || '').toLowerCase(), filter = state.dirFilter || 'all';
    const items = directoryItems(tab).filter(i => (!q || (i.name + ' ' + i.description + ' ' + i.group).toLowerCase().includes(q)) && (filter === 'all' || (filter === 'on') === i.on));
    const groups = [...new Set(items.map(i => i.group))].sort((a, b) => (b === SOURCE_NAMES.zook) - (a === SOURCE_NAMES.zook));
    const counts = {skills: (state.integrations.skills || []).filter(i => !i.imported).length, mcp: (state.integrations.mcp || []).filter(i => !i.copied).length, plugins: (state.integrations.plugins || []).length};
    const tabs = [['skills', 'Skills'], ['mcp', '連接器'], ['plugins', '插件']];
    const intro = {skills: 'Skills 由所有 Bot 共用。開啟的 Skill 每個 Bot 都能使用。匯入到 Zook 之後，就算移除原本的工具也還在；同名的只會保留一份。', mcp: '連接器讓 Bot 使用外部服務或工具，開啟後所有 Bot 共用。開得越多，回覆越慢；連不上的建議關閉。', plugins: '插件會一次帶來一組 Skills 和連接器，來源是 Claude Code。'}[tab];
    const card = i => {
      const expanded = state.dirExpanded?.[i.id];
      return `<article class="dir-card ${expanded ? 'expanded' : ''}">${itemIcon(i.name, i.icon)}<div class="dir-body"><div class="dir-title"><h3 title="${esc(i.name)}">${esc(i.name)}</h3>${i.needsSetup ? '<button class="primary small-btn" data-action="gmail-setup">設定</button>' : i.needsKey ? `<button class="primary small-btn" data-action="connector-edit" data-id="${esc(i.id)}">貼上金鑰</button>` : i.moved ? `<span class="dir-status">${i.moved}</span>` : toggle(`data-dir-switch data-kind="${i.toggle}" data-id="${esc(i.id)}" title="${esc(i.toggleLabel)}"`, i.on, i.toggleLabel)}</div><p class="dir-desc">${esc(i.description || '沒有說明。')}</p>${i.description.length > 70 ? `<button class="link dir-more" data-action="dir-expand" data-id="${esc(i.id)}">${expanded ? '收合' : '展開'}</button>` : ''}<div class="dir-meta">${i.status ? `<span class="dir-status ${i.status[0]}">${esc(i.status[1])}</span>` : ''}<span>${esc(i.meta)}</span>${i.test ? `<button class="link" data-action="test-mcp" data-id="${esc(i.id)}">測試連線</button>` : ''}${i.gmail && !i.needsSetup ? '<button class="link" data-action="gmail-setup">重新設定</button><button class="link danger" data-action="gmail-remove">中斷連接</button>' : ''}${i.copyable ? `<button class="link" data-action="connector-copy" data-id="${esc(i.id)}">複製到 Zook</button>` : ''}${i.canUpdate ? `<button class="link" data-action="skill-update" data-id="${esc(i.id)}" title="原本的來源有更新">從原來源更新</button>` : ''}${i.removable ? `<button class="link danger" data-action="skill-remove" data-id="${esc(i.id)}" data-name="${esc(i.name)}">移除</button>` : ''}${i.editable ? `<button class="link" data-action="connector-edit" data-id="${esc(i.id)}">編輯</button><button class="link danger" data-action="connector-delete" data-id="${esc(i.id)}" data-name="${esc(i.name)}">移除</button>` : ''}</div>${i.note ? `<p class="dir-note">${esc(i.note)}</p>` : ''}</div></article>`;
    };
    return `<div class="dir-bar"><div class="dir-tabs">${tabs.map(([id, label]) => `<button class="${tab === id ? 'active' : ''}" data-action="dir-tab" data-id="${id}">${label}<small>${counts[id]}</small></button>`).join('')}</div><div class="dir-filters">${dropdown('dirFilter', filter, [{id: 'all', name: '全部'}, {id: 'on', name: '已啟用'}, {id: 'off', name: '未啟用'}], 'data-dir-filter')}</div><input id="dir-search" class="dir-search" placeholder="搜尋" aria-label="搜尋" value="${esc(state.dirQuery || '')}"></div><p class="muted dir-intro">${intro}</p>${tab === 'mcp' ? '<div class="dir-add"><button class="primary" data-action="connector-add">＋ 新增連接器</button><span class="muted small">直接加在 Zook 裡，不需要先在 Codex 或 Claude 設定。</span></div>' : ''}${tab === 'plugins' ? '' : `<div class="dir-add"><button class="secondary" data-action="pack-export">匯出設定包</button><button class="secondary" data-action="pack-import">匯入設定包</button><span class="muted small">把 Zook 自己的 Skills 和連接器搬到另一台 Mac。金鑰不會放進設定包。</span></div>`}${groups.length ? groups.map(g => { const closed = (state.data.settings.dirCollapsed || []).includes(tab + ':' + g) && !q; return `<section class="dir-section"><h2><button class="dir-fold" data-action="dir-collapse" data-id="${esc(tab + ':' + g)}" aria-expanded="${!closed}"><span>${esc(g)}</span><small>${items.filter(i => i.group === g).length}</small><span class="dir-chev" aria-hidden="true">${closed ? '⌄' : '⌃'}</span></button>${tab === 'skills' && items.some(i => i.group === g && i.importable) ? `<button class="link dir-import" data-action="skills-import" data-id="${esc(g)}">匯入到 Zook</button>` : ''}</h2>${closed ? '' : `<div class="dir-grid">${items.filter(i => i.group === g).map(card).join('')}</div>`}</section>`; }).join('') : '<div class="blank">沒有符合的項目。</div>'}`;
  }
  // Built-in Gmail: an address and a Google app password. The password goes to the Keychain.
  function gmailModal() {
    const current = (state.integrations?.mcp || []).find(i => i.gmail)?.address || '';
    modal('設定 Gmail', `<form id="gmail-form"><div class="modal-body"><p class="muted">Zook 用 Google 的「應用程式密碼」連接 Gmail。這是 Google 為單一 App 產生的專用密碼，不是你的 Google 登入密碼，可以隨時在 Google 帳戶裡撤銷。</p><ol class="steps"><li>Google 帳戶需已開啟「兩步驟驗證」。</li><li>開啟 <a href="https://myaccount.google.com/apppasswords" rel="noopener noreferrer">myaccount.google.com/apppasswords</a>，輸入名稱（例如 Zook）後建立。</li><li>把顯示的 16 個字母貼到下面。</li></ol><label class="field">Gmail 信箱<input name="address" type="email" required autocomplete="off" spellcheck="false" placeholder="you@gmail.com" value="${esc(current)}"></label><label class="field">應用程式密碼<input name="password" type="password" required autocomplete="off" spellcheck="false" placeholder="16 個英文字母"></label><p class="muted small">密碼只存進這台 Mac 的鑰匙圈，不會寫進 Zook 的資料檔，也不會傳到手機。公司或學校的 Google 帳號可能被管理員停用應用程式密碼。</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">連接</button></div></form>`);
  }
  // A connector added in Zook itself: a command run on this Mac, or the address of a remote one.
  function connectorModal(item) {
    const c = item?.config || {}, http = item ? item.transport === 'http' : false;
    const types = [{id: 'stdio', name: '本機指令', hint: '在這台 Mac 上執行的程式，例如用 npx 或 uvx 啟動的 MCP 伺服器'}, {id: 'http', name: '網址', hint: '遠端的 MCP 伺服器（Streamable HTTP）'}];
    const kept = c.hasSecret ? '已儲存。留空表示不變更' : '';
    modal(item ? '編輯連接器' : '新增連接器', `<form id="connector-form" data-id="${esc(item ? item.id.split(':')[1] : '')}"><div class="modal-body"><label class="field">名稱<input name="name" required maxlength="80" placeholder="例如：GitHub" value="${esc(item?.name || '')}"></label><div class="setting-list in-form">${settingRow('類型', '連接器在哪裡執行', dropdown('transport', http ? 'http' : 'stdio', types))}</div><div data-for="stdio" ${http ? 'hidden' : ''}><label class="field">啟動指令<input name="command" spellcheck="false" placeholder="例如：npx -y @modelcontextprotocol/server-github" value="${esc(c.command || '')}"><small class="muted">和你在終端機輸入的一樣。Zook 會在需要時啟動它。</small></label><label class="field">環境變數（選填，每行一個）<textarea name="env" rows="3" spellcheck="false" placeholder="NAME=value">${esc(Object.entries(c.env || {}).map(([k, v]) => k + '=' + v).join('\n'))}</textarea></label><div class="form-grid"><label class="field">金鑰的環境變數名稱（選填）<input name="secretName" spellcheck="false" placeholder="例如：GITHUB_TOKEN" value="${esc(http ? '' : c.secretName || '')}"></label><label class="field">金鑰<input name="secretStdio" type="password" autocomplete="off" spellcheck="false" placeholder="${esc(http ? '' : kept)}"></label></div>${(c.moreSecrets || []).map(m => `<label class="field">金鑰 ${esc(m.name)}<input name="more:${esc(m.name)}" type="password" autocomplete="off" spellcheck="false" placeholder="${m.saved ? '已儲存。留空表示不變更' : '請貼上這把金鑰'}"></label>`).join('')}</div><div data-for="http" ${http ? '' : 'hidden'}><label class="field">網址<input name="url" spellcheck="false" placeholder="https://example.com/mcp" value="${esc(c.url || '')}"></label><label class="field">存取權杖（選填）<input name="secretHttp" type="password" autocomplete="off" spellcheck="false" placeholder="${esc(http ? kept : '')}"><small class="muted">會以 Bearer 權杖送給這個網址。</small></label></div><p class="muted small">金鑰和權杖只存進 macOS 鑰匙圈，不會寫進 Zook 的資料檔，也不會傳到手機。${c.hasSecret ? ' <label class="inline-check"><input type="checkbox" name="clearSecret"> 移除已儲存的金鑰</label>' : ''}</p></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${item ? '儲存' : '新增'}</button></div></form>`);
  }
  function mcpBotsModal(id) {
    const item = (state.integrations?.mcp || []).find(i => i.id === id);
    if (!item) return;
    modal('選擇使用「' + (id === 'builtin:workspace' ? 'Bot 工作區' : item.name) + '」的 Bot', `<form id="mcp-bots-form" data-id="${esc(id)}"><div class="modal-body"><p class="muted">打勾的 Bot 可以使用這個連接器。每次使用仍會依權限設定請你核准。</p><div class="member-pick">${state.data.bots.map(b => `<label class="ability-option"><input type="checkbox" name="bots" value="${esc(b.id)}" ${(b.enabledMcp || []).includes(id) ? 'checked' : ''}><span>${avatar(b)}<strong>${esc(b.name)}</strong><small>${esc((b.persona || b.instructions || '').slice(0, 40))}</small></span></label>`).join('')}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">儲存</button></div></form>`);
  }

  function detail(b) {
    let notes = state.data.knowledge.filter(n => n.botId === b.id);
    return `<aside class="detail"><button class="detail-close icon-btn" data-action="toggle-detail" aria-label="關閉詳情">×</button><div class="detail-profile">${avatar(b,'big')}<h2>${esc(b.name)}</h2><p>${esc(b.provider||state.data.settings.provider||'')} ${esc(b.model||'')}</p><p>主動性：${esc(permissionName(b.permissionMode || state.data.settings.permissionMode))}${b.permissionMode ? '' : '（預設）'}</p><button class="secondary detail-edit" data-action="edit-bot">編輯設定</button></div><div class="tabs"><button data-action="detail" data-id="persona" class="${state.detail==='persona'?'active':''}">人格</button><button data-action="detail" data-id="activity" class="${state.detail==='activity'?'active':''}">動態</button><button data-action="detail" data-id="database" class="${state.detail==='database'?'active':''}">資料庫</button></div>${state.detail==='persona'?personaPanel(b):state.detail==='database'?`<div class="detail-title">知識 <button class="link" data-action="new-note">＋ 新增</button></div>${notes.length?notes.map(n=>`<button class="note-row" data-action="edit-note" data-id="${esc(n.id)}"><strong>${esc(n.title)}</strong><small>${esc(n.content)}</small></button>`).join(''):'<div class="detail-empty">尚未新增知識。加入資料，讓這個 Bot 有更多背景。</div>'}`:`<div class="detail-title">最近動態</div>${toolTimeline(b.id)}${(b.messages||[]).length?`<div class="detail-empty">最近對話 ${esc(formatDate(b.messages.at(-1).createdAt))}</div>`:'<div class="detail-empty">這裡會顯示最近的對話動態。</div>'}`}</aside>`
  }

  function formatDate(d) {
    if (!d) return '';
    let dt = new Date(d);
    return isNaN(dt) ? String(d) : dt.toLocaleString('zh-TW', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  function modelPicker(model, bare = false) {
    return `<div class="field model-picker"><label>${bare ? '' : '模型'}<select name="modelSelect" aria-label="模型"><option value="">使用預設</option><option value="__custom__">自訂模型…</option></select></label><input type="hidden" name="model" value="${esc(model)}"><input name="modelCustom" aria-label="自訂模型" placeholder="輸入模型 ID" hidden><div class="model-tools"><span class="model-note" role="status" aria-live="polite">準備偵測模型…</span><button type="button" class="link" data-action="refresh-models" aria-label="重新偵測模型">重新偵測</button></div></div>`;
  }

  async function loadModels(form, force = false) {
    if (!form || !form.isConnected) return;
    form.modelRequest?.abort();
    const controller = new AbortController();
    form.modelRequest = controller;
    const provider = form.elements.provider.value || state.data.settings.provider || 'codex';
    const note = form.querySelector('.model-note');
    note.textContent = '正在偵測模型…';
    try {
      const data = await api(`models?provider=${encodeURIComponent(provider)}${force?'&refresh=1':''}`, {signal: controller.signal});
      if (!form.isConnected || form.modelRequest !== controller) return;
      const select = form.elements.modelSelect;
      const current = form.elements.model.value;
      const wasCustom = select.value === '__custom__';
      const models = Array.isArray(data.models) ? data.models : [];
      select.innerHTML = '<option value="">使用預設</option>' + models.map(m => `<option value="${esc(m.id)}">${esc(m.name||m.id)}${m.source==='alias'?'（別名）':m.source==='cache'?'（快取）':''}</option>`).join('') + '<option value="__custom__">自訂模型…</option>';
      const known = models.some(m => m.id === current);
      const custom = form.elements.modelCustom;
      if ((current && !known) || wasCustom) {
        select.value = '__custom__'; custom.value = current; custom.hidden = false;
      } else {
        select.value = current || ''; custom.hidden = true;
      }
      note.textContent = (data.note || (models.length ? '模型清單已更新。' : '未偵測到模型，可使用預設或自行輸入。')) + (form.dataset.providerChanged ? ' 提供者已變更，模型已切換為預設。' : '');
      delete form.dataset.providerChanged;
    } catch (error) {
      if (error.name === 'AbortError' || !form.isConnected || form.modelRequest !== controller) return;
      const select = form.elements.modelSelect;
      const current = form.elements.model.value;
      if (current) { select.value = '__custom__'; form.elements.modelCustom.value = current; form.elements.modelCustom.hidden = false; }
      note.textContent = `無法偵測模型：${error.message}。可重新偵測或自行輸入。`;
    }
  }

  function saveBotDraft(form) {
    if (!form || form.dataset.id) return;
    let previous = {};
    try { previous = JSON.parse(sessionStorage.getItem('swarmr-new-bot-draft') || '{}'); } catch (_) {}
    const values = {...previous, ...Object.fromEntries(new FormData(form))};
    values.pinned = form.elements.pinned.checked;
    if (form.querySelector('.ability-list')) { values.enabledSkills = new FormData(form).getAll('enabledSkills'); values.enabledMcp = new FormData(form).getAll('enabledMcp'); }
    try { sessionStorage.setItem('swarmr-new-bot-draft', JSON.stringify(values)); } catch (_) {}
  }

  function restoreBotDraft(form) {
    try {
      const draft = JSON.parse(sessionStorage.getItem('swarmr-new-bot-draft') || 'null');
      if (!draft) return;
      for (const key of ['name','instructions','provider','model','section','shape','color']) {
        if (draft[key] != null && form.elements[key]) form.elements[key].value = draft[key];
      }
      form.elements.pinned.checked = !!draft.pinned;
      form.querySelector('.bot-preview .avatar').className = `avatar shape-${shapeIndex(draft.shape)} hero`;
      form.querySelectorAll('.avatar').forEach(x => x.style.setProperty('--c', draft.color));
      form.querySelectorAll('.shape-btn').forEach(x => x.classList.toggle('selected', x.dataset.id === draft.shape));
      form.querySelectorAll('.swatch').forEach(x => x.classList.toggle('selected', x.dataset.id === draft.color));
    } catch (_) {}
  }

  function page() {
    let name = {
      knowledge: '知識庫',
      usage: '使用量',
      skills: 'Skills 與連接器',
      mcp: 'Skills 與連接器',
      settings: '設定',
      memory: '記憶',
      accounts: '模型帳號',
      schedules: '排程',
      plugins: 'Skills 與連接器'
    } [state.page] || '';
    let content = '';
    if (state.page === 'knowledge') {
      let notes = state.data.knowledge.filter(n => !state.query || matches(n.title) || matches(n.content) || (n.tags || []).some(matches));
      content = notes.length ? `<div class="cards">${notes.map(n=>`<article class="card"><h3>${esc(n.title)}</h3><p>${esc(n.content)}</p><span class="status">${esc(state.data.bots.find(b=>b.id===n.botId)?.name||'共用知識')}</span><div class="actions"><button class="link" data-action="edit-note" data-id="${esc(n.id)}">編輯</button><button class="link" data-action="delete-note" data-id="${esc(n.id)}">刪除</button></div></article>`).join('')}</div>` : '<div class="blank">目前沒有知識。新增筆記，為 Bot 提供背景資料。</div>'
    } else if (state.page === 'schedules') {
      content = schedulesPage();
    } else if (state.page === 'skills' || state.page === 'mcp' || state.page === 'plugins') {
      content = directoryPage(state.page);
    } else if (state.page === 'skills-legacy') {
      const a = state.integrations?.skills || [], off = new Set(state.data.settings.disabledSkills || []);
      const q = (state.skillQuery || '').toLowerCase();
      const shown = a.filter(i => !q || (i.name + ' ' + (i.description || '')).toLowerCase().includes(q));
      content = `<p class="muted">Skills 由所有 Bot 共用。關閉的 Skill 不會提供給任何 Bot。目前啟用 ${a.filter(i => !off.has(i.id)).length} / ${a.length} 個。</p><input id="skill-search" class="secondary" style="width:100%;text-align:left;margin-bottom:16px" placeholder="搜尋 Skills" aria-label="搜尋 Skills" value="${esc(state.skillQuery||'')}">${shown.length ? `<div class="cards">${shown.map(i=>`<article class="card"><h3>${esc(i.name)}</h3><p>${esc(i.description||i.source||'')}</p><label class="ability-check"><input type="checkbox" data-shared-skill="${esc(i.id)}" ${off.has(i.id)?'':'checked'}> 所有 Bot 共用</label></article>`).join('')}</div>` : '<div class="blank">目前沒有偵測到項目。</div>'}`;
    } else if (state.page === 'memory') {
      const mems = [...(state.data.memories || [])].reverse();
      const who = id => state.data.bots.find(b => b.id === id)?.name || '已刪除的 Bot';
      content = `<p class="muted">Bot 在對話中記下的長期記憶，之後的對話會自動帶入。「共用」給所有 Bot，其他只給該 Bot。</p>${mems.length ? `<div class="cards">${mems.map(m => `<article class="card"><p>${esc(m.content)}</p><span class="status">${m.botId ? esc(who(m.botId)) : '共用'} · 由 ${esc(who(m.createdBy))} 記下 · ${esc(formatDate(m.createdAt))}</span><div class="actions"><button class="link" data-action="delete-memory" data-id="${esc(m.id)}" style="color:#b55">刪除</button></div></article>`).join('')}</div>` : '<div class="blank">還沒有記憶。和 Bot 聊天時說「記住…」，它就會記下來。</div>'}`;
    } else if (state.page === 'mcp-legacy') {
      let a = state.integrations?.[state.page] || [], b = activeBot(), key = state.page === 'skills' ? 'enabledSkills' : 'enabledMcp';
      content = `<label class="field">設定對象<select id="ability-bot"><option value="">請選擇 Bot</option>${state.data.bots.map(x=>`<option value="${esc(x.id)}" ${b?.id===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></label><p class="muted">選擇要讓這個 Bot 使用的項目。</p>${a.length ? `<div class="cards">${a.map(i=>`<article class="card"><h3>${esc(i.name)}</h3><p>${esc(i.description||i.source||'')}</p>${state.page==='mcp'?`<span class="status">${esc(state.mcpTests[i.id]?.status==='ready'?'已驗證 · '+state.mcpTests[i.id].toolCount+' 個工具':state.mcpTests[i.id]?.status==='error'?'連線失敗：'+state.mcpTests[i.id].error:'已偵測設定，尚未驗證')}</span><div class="actions"><button class="link" data-action="test-mcp" data-id="${esc(i.id)}">測試連線</button></div>`:''}<label class="ability-check"><input type="checkbox" data-ability-kind="${key}" data-ability-id="${esc(i.id)}" ${b && (b[key]||[]).includes(i.id)?'checked':''} ${b?'':'disabled'}> 讓此 Bot 使用</label></article>`).join('')}</div>`:'<div class="blank">目前沒有偵測到項目。</div>'}`;
    } else if (state.page === 'usage') {
      let u = state.usage || {},
        groups = u.groups || [];
      let metrics = [
        [u.sessionCount == null ? '分組工作階段加總' : '工作階段', u.sessionCount ?? groups.reduce((a, g) => a + (g.sessions || 0), 0)],
        ['輸入 Token', groups.reduce((a, g) => a + (g.inputTokens || 0), 0)],
        ['輸出 Token', groups.reduce((a, g) => a + (g.outputTokens || 0), 0)]
      ];
      content = quotaSection() + botUsageSection() + `<details class="usage-local"><summary>本機 CLI 全部紀錄（包含 Zook 以外的使用）</summary><p>${esc(u.note||'本機記錄的使用情況。')} ${u.truncated?'資料已截斷。':''}</p><div class="stats">${metrics.map(([k,v])=>`<div class="card"><span class="muted">${k}</span><div class="stat-num">${v.toLocaleString()}</div></div>`).join('')}</div>${groups.length?`<div class="usage-chart">${groups.slice(0,14).map(g=>`<div class="usage-row"><span>${esc(g.date)} · ${esc(g.provider)}</span><div class="usage-track"><div class="usage-bar" style="width:${Math.round(100*((g.inputTokens||0)+(g.outputTokens||0))/Math.max(1,...groups.map(x=>(x.inputTokens||0)+(x.outputTokens||0))))}%"></div></div><small>${((g.inputTokens||0)+(g.outputTokens||0)).toLocaleString()} tokens</small></div>`).join('')}</div><div class="cards">${groups.map(g=>`<div class="card"><h3>${esc(g.date)} · ${esc(g.provider)}</h3><p>${esc(g.model)}<br>${(g.inputTokens||0).toLocaleString()} 輸入 / ${(g.outputTokens||0).toLocaleString()} 輸出</p></div>`).join('')}</div>`:'<div class="blank">尚無使用紀錄。</div>'}` + '</details>';
      if (!state.usage || state.usage.error) content = quotaSection() + botUsageSection() + `<details class="usage-local"><summary>本機 CLI 全部紀錄（包含 Zook 以外的使用）</summary>${state.usage?.error ? `<div class="blank error-text">${esc(state.usage.error)}</div>` : loadingBlock('正在讀取本機紀錄…')}</details>`;
    } else if (state.page === 'plugins-legacy') {
      const list = state.integrations?.plugins || [];
      content = `<p class="muted">Zook 會讀取 Claude Code 已安裝的插件。啟用後，插件的 Skill 會共用給所有 Bot；插件的 MCP 可在各 Bot 的「能力」中選用。</p>${list.length ? `<div class="cards">${list.map(pl => {
        const parts = [pl.skillCount ? pl.skillCount + ' 個 Skill' : '', pl.mcpCount ? pl.mcpCount + ' 個 MCP' : ''].filter(Boolean).join(' · ') || '沒有 Zook 可用的內容';
        const notes = [pl.hasHooks ? 'hooks' : '', pl.hasCommands ? '指令' : ''].filter(Boolean);
        return `<article class="card plugin-card ${pl.enabled ? '' : 'off'}"><div class="plugin-head"><h3>${esc(pl.displayName)}</h3><span class="status">${esc(pl.sourceName)}${pl.version ? ' · v' + esc(pl.version) : ''}</span></div><p>${esc(pl.description || '')}</p><p class="muted">${esc(parts)}${pl.author ? ' · ' + esc(pl.author) : ''}</p>${notes.length ? `<p class="muted small">包含 ${esc(notes.join('、'))}，這部分只在原本的工具中運作，Zook 不會執行。</p>` : ''}<label class="ability-check"><input type="checkbox" data-plugin-toggle="${esc(pl.id)}" ${pl.enabled ? 'checked' : ''}> 啟用</label></article>`;
      }).join('')}</div>` : '<div class="blank">沒有偵測到插件。</div>'}`;
    } else if (state.page === 'accounts') {
      content = accountsPage();
    } else if (state.page === 'settings') {
      let s = state.data.settings || {};
      content = permissionSection(s.permissionMode || 'manual') + `<form id="settings-form" class="setting-list">${settingRow('預設提供者', '新對話預設使用的模型服務。登入狀態在「模型帳號」管理。', `<select name="provider" class="plain-select" aria-label="預設提供者">${providerOptions(s.provider || 'codex', false)}</select>`)}${settingRow('預設模型', '未個別指定模型的 Bot 會使用這個模型。', modelPicker(s.model||'', true))}${[0, 1].map(i => settingRow('備用模型 ' + (i + 1), i ? '第一個備用也不能用時，再換這一個。' : '預設模型額度用完、未登入或回覆失敗時，自動換這個模型，並在回覆下方註明。', dropdown('fallback' + i, (s.fallbacks || [])[i] || '', [{id: '', name: '不使用'}, ...providerList()], 'data-fallback-slot'))).join('')}<div class="setting-actions"><button class="primary">儲存模型設定</button><button type="button" class="secondary" data-action="export">匯出所有資料</button></div></form>` + noticeSection() + updateSection() + remoteSection()
    }
    return `<main class="main"><header class="main-header"><div class="bot-pill">Zook</div></header><div class="page"><div class="page-inner"><div class="page-top"><h1>${name}</h1>${state.page==='knowledge'?'<button class="primary" data-action="new-note">＋ 新增知識</button>':state.page==='schedules'?'<button class="primary" data-action="new-schedule">＋ 新增排程</button>':''}</div>${content}</div></div></main>`
  }

  function render(keepScroll = false) {
    let settingsForm = $('#settings-form');
    let settingsDraft = settingsForm ? Object.fromEntries(new FormData(settingsForm)) : null;
    settingsForm?.modelRequest?.abort();
    let conv = $('#conversation');
    let y = keepScroll ? conv?.scrollTop : null;
    let nearBottom = !conv || conv.scrollHeight - conv.scrollTop - conv.clientHeight < 120;
    let previousInput = $('#chat-input');
    let input = previousInput?.value || '';
    let cursor = document.activeElement === previousInput ? [previousInput.selectionStart, previousInput.selectionEnd] : null;
    let openApprovals = [...document.querySelectorAll('[data-approval-details][open]')].map(x => x.dataset.approvalDetails);
    app.innerHTML = `<div class="layout">${sidebar()}${state.page==='chat'?(activeGroup()?groupChat():chat()):page()}</div>`;
    if ($('#chat-input')) {
      $('#chat-input').value = input;
      if (cursor !== null) { $('#chat-input').focus(); $('#chat-input').setSelectionRange(cursor[0], cursor[1]); }
    }
    updateMentionMenu();
    document.querySelectorAll('[data-approval-details]').forEach(x => { if (openApprovals.includes(x.dataset.approvalDetails)) x.open = true; });
    if ($('#conversation')) {
      const c = $('#conversation');
      if (!keepFocus()) c.scrollTo({top: y != null && !nearBottom ? y : c.scrollHeight, behavior: 'instant'});
    }
    if ($('#settings-form')) {
      const f = $('#settings-form');
      if (settingsDraft) { f.elements.provider.value = settingsDraft.provider; f.elements.model.value = settingsDraft.model; }
      loadModels(f);
    }
  }

  function modal(title, body, footer = '', wide = false) {
    state.modal = document.activeElement;
    modalRoot.innerHTML = `<div class="modal-overlay" data-action="overlay"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><h2 id="modal-title">${esc(title)}</h2><button class="icon-btn" data-action="close-modal" aria-label="關閉">×</button></div>${body}${footer}</section></div>`;
    setTimeout(() => $('.modal input,.modal textarea,.modal select,.modal button')?.focus(), 0)
  }

  function closeModal() {
    $('#bot-form')?.modelRequest?.abort();
    modalRoot.innerHTML = '';
    state.modal?.focus?.();
    state.modal = null
  }

  function botModal(b = {}) {
    const editing = !!b.id;
    let c = /^#[0-9a-f]{6}$/i.test(b.color || '') ? b.color : colors[0],
      shape = shapeIndex(b.shape);
    modal(editing ? '編輯 Bot' : '新增 Bot', `<form id="bot-form"><div class="modal-body"><div class="bot-preview">${avatar({color:c,shape},'hero')}<input name="name" required maxlength="80" placeholder="為 Bot 命名" value="${esc(b.name||'')}"></div><label class="field persona-field">人格檔案<textarea name="persona" ${editing ? '' : 'required'} maxlength="20000" rows="5" placeholder="描述這個 Bot 是誰：個性、說話語氣、價值觀、擅長與不擅長的事。例如：「冷靜、直接的資深工程師，回答先給結論，再用比喻解釋；不確定時會說不確定。」">${esc(b.persona||'')}</textarea><small class="muted">這個 Bot 的個性與說話方式，每次回覆都會帶入。之後可以在 Bot 的詳情面板「人格」中修改。</small></label><label class="field">形狀</label><div class="shapes">${Array.from({length:13},(_,i)=>`<button type="button" class="shape-btn ${shape===i?'selected':''}" data-action="shape" data-id="${i}" aria-label="形狀 ${i+1}">${avatar({color:c,shape:i})}</button>`).join('')}</div><label class="field">顏色</label><div class="swatches">${colors.map(x=>`<button type="button" class="swatch ${c===x?'selected':''}" style="background:${x}" data-action="color" data-id="${x}" aria-label="顏色 ${x}"></button>`).join('')}</div><input type="hidden" name="shape" value="${shape}"><input type="hidden" name="color" value="${c}"><div class="setting-list in-form">${settingRow('主動性', '執行動作前要不要先問你', dropdown('permissionMode', b.permissionMode || '', permissionOptions(true)))}${settingRow('存取範圍', '這個 Bot 可以動到 Mac 上的哪些檔案。主動性是「謹慎」時不適用', dropdown('access', ACCESS.some(a => a.id === b.access) ? b.access : 'full', ACCESS))}<div class="setting-row" data-access-folder ${b.access === 'folder' ? '' : 'hidden'}><div class="setting-copy"><strong>指定的資料夾</strong><span data-access-path>${esc(b.accessFolder || '尚未選擇')}</span></div><div class="setting-control"><input type="hidden" name="accessFolder" value="${esc(b.accessFolder || '')}"><button type="button" class="secondary" data-action="choose-folder">選擇資料夾…</button></div></div>${settingRow('備用模型', '這個 Bot 的模型不能用時，要換成哪一個', dropdown('fallbackChoice', !Array.isArray(b.fallbacks) ? '__default' : b.fallbacks.length ? b.fallbacks[0] : '__none', [{id: '__default', name: '使用預設', hint: (state.data.settings.fallbacks || []).length ? (state.data.settings.fallbacks || []).map(providerShort).join(' → ') : '目前設定為不自動換'}, {id: '__none', name: '不自動換'}, ...providerList()]))}${settingRow('分類', '顯示在左側的哪個分組', dropdown('section', b.section || sectionNames()[0] || '我的 Bots', [...new Set([...sectionNames(), b.section || '我的 Bots'])].map(x => ({id: x, name: x}))))}${settingRow('釘選', '固定在左側最上方', toggle('name="pinned"', b.pinned, '釘選'))}</div><details class="advanced"><summary>進階設定</summary><label class="field">工作指示（選填）<textarea name="instructions" placeholder="這個 Bot 負責的工作與做事方式，例如：負責審查程式碼，只列出會造成錯誤的問題。">${esc(b.instructions||'')}</textarea></label><div class="form-grid"><label class="field">提供者<select name="provider">${providerOptions(b.provider || '', true)}</select></label><label class="field" data-account-field>${accountField(b.provider || '', b.account || '')}</label>${modelPicker(b.model||'')}</div></details></div><div class="modal-foot">${editing?'<button type="button" class="link" data-action="delete-bot" style="margin-right:auto;color:#b55">刪除 Bot</button>':''}<button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${editing?'儲存':'建立 Bot'}</button></div></form>`);
    const form = $('#bot-form');
    form.dataset.id = b.id || '';
    if (!b.id) restoreBotDraft(form);
    loadModels(form);
    const selected = {enabledSkills: b.enabledSkills || [], enabledMcp: b.enabledMcp || []};
    if (!b.id) { try { const d = JSON.parse(sessionStorage.getItem('swarmr-new-bot-draft') || '{}'); selected.enabledSkills = d.enabledSkills || []; selected.enabledMcp = d.enabledMcp || []; } catch (_) {} }
  }
  async function loadBotAbilities(form, selected) {
    const target = form.querySelector('#bot-abilities');
    try {
      const catalog = await api('integrations');
      if (!form.isConnected) return;
      state.integrations = catalog;
      target.innerHTML = `<p class="muted">Skills 和連接器由所有 Bot 共用（${(catalog.skills||[]).length} 個 Skill、${(state.data.settings.sharedMcp||[]).length} 個連接器已開啟），在「Skills 與連接器」頁管理。</p>` + [].map(kind => {
        const key = kind === 'skills' ? 'enabledSkills' : 'enabledMcp';
        const items = catalog[kind] || [];
        const missing = selected[key].filter(id => !items.some(i => i.id === id)).map(id => ({id, name:id, description:'目前未偵測到'}));
        return `<div class="ability-group"><strong>${kind === 'skills'?'Skills':'MCP'}</strong><input class="ability-search" data-kind="${kind}" placeholder="搜尋 ${kind === 'skills'?'Skills':'MCP'}" aria-label="搜尋 ${kind === 'skills'?'Skills':'MCP'}"><div class="ability-list">${[...items,...missing].map(i => `<label class="ability-option" data-search="${esc((i.name+' '+(i.description||'')).toLowerCase())}"><input type="checkbox" name="${key}" value="${esc(i.id)}" ${selected[key].includes(i.id)?'checked':''}><span><strong>${esc(i.name)}</strong><small>${esc(i.description||i.source||'')}</small></span></label>`).join('') || '<p class="muted">目前沒有偵測到項目。</p>'}</div></div>`;
      }).join('');
    } catch (e) { if (form.isConnected) target.innerHTML = `<p class="error-text">無法載入能力清單：${esc(e.message)}。請關閉並重試。</p>`; }
  }

  const REPEATS = [['daily', '每天'], ['weekdays', '週一到週五'], ['mon', '每週一'], ['tue', '每週二'], ['wed', '每週三'], ['thu', '每週四'], ['fri', '每週五'], ['sat', '每週六'], ['sun', '每週日'], ['hourly', '每小時'], ['monthly', '每月'], ['once', '只一次']];
  const repeatName = id => (REPEATS.find(r => r[0] === id) || REPEATS[0])[1];
  const WEEKDAY = '日一二三四五六';
  const dayLabel = iso => { const d = new Date(iso + 'T00:00:00'); return `${d.getMonth() + 1}/${d.getDate()}（週${WEEKDAY[d.getDay()]}）`; };
  // When a schedule runs, in words: 每天 10:00, 每小時的 15 分, 每月 5 號 10:00, 11/20（週五）10:00.
  function scheduleWhen(x) {
    if (x.repeat === 'hourly') return `每小時的 ${x.time.slice(3)} 分`;
    if (x.repeat === 'monthly') return `每月 ${x.day} 號 ${x.time}`;
    if (x.repeat === 'once') return `${x.date ? dayLabel(x.date) : ''} ${x.time}`;
    return `${repeatName(x.repeat)} ${x.time}`;
  }
  function schedulesPage() {
    const items = state.data.schedules || [];
    const intro = '<p class="muted sched-intro">時間到了，Zook 會自動把這則訊息送給 Bot 或群組，回覆留在對話裡。Mac 要開著、Zook 要在執行；需要你核准的動作仍會等你核准。</p>';
    if (!items.length) return intro + '<div class="blank">目前沒有排程。按「新增排程」，讓 Bot 或群組在固定時間自動做事。</div>';
    const last = x => x.done ? '已完成' : !x.lastStatus ? '尚未執行' : (x.lastStatus === 'sent' ? '上次執行：' : x.lastStatus === 'missed' ? '上次錯過：' : '上次失敗：') + formatDate(x.lastAt) + (x.lastStatus !== 'sent' && x.lastError ? '（' + x.lastError + '）' : '');
    return intro + `<div class="cards">${items.map(x => `<article class="card sched-card"><div class="sched-head"><h3>${esc(scheduleWhen(x))}</h3>${toggle(`data-schedule-switch data-id="${esc(x.id)}"`, x.on, '啟用這個排程')}</div><p>${esc(x.content)}</p>${scheduleTarget(x)}<span class="status ${x.lastStatus && x.lastStatus !== 'sent' && !x.done ? 'warn' : ''}">${esc(last(x))}</span><div class="actions"><button class="link" data-action="run-schedule" data-id="${esc(x.id)}">立即執行</button>${(x.runs || []).length ? `<button class="link" data-action="schedule-history" data-id="${esc(x.id)}">紀錄</button>` : ''}<button class="link" data-action="edit-schedule" data-id="${esc(x.id)}">編輯</button><button class="link" data-action="delete-schedule" data-id="${esc(x.id)}">刪除</button></div></article>`).join('')}</div>`;
  }
  // Under the last question: 編輯. Under the last reply: 重新回答 and 換模型重答. Not while a reply is running.
  function redoBar(b, m, running) {
    if (running) return '';
    const msgs = b.messages || [], lastUser = [...msgs].reverse().find(x => x.role === 'user');
    if (!lastUser) return '';
    if (m.id === lastUser.id) return '<div class="msg-actions user-actions"><button type="button" class="link" data-action="edit-last">編輯</button></div>';
    if (m.role !== 'user' && m.id === msgs[msgs.length - 1]?.id && m.status !== 'running')
      return '<div class="msg-actions"><button type="button" class="link" data-action="redo-again">重新回答</button><button type="button" class="link" data-action="redo-model">換模型重答</button></div>';
    return '';
  }
  // Redoing cannot undo what the last reply already did (files changed, mail sent): say so first.
  function redoAllowed(b) {
    const reply = (b.messages || []).filter(m => m.role !== 'user').slice(-1)[0];
    const job = reply && Object.values(state.jobDetails).find(j => j.messageId === reply.id);
    const acted = (job?.toolCalls || []).some(c => c.status === 'completed' && !['read', 'external_read'].includes(c.category));
    return !acted || confirm('上一次回覆已經做過一些動作（例如改了檔案或對外送出），重來不會復原那些動作。確定要重來？');
  }
  async function redo(b, body) {
    const sent = await post('chat/redo', {...body, botId: b.id});
    await refresh(); poll(sent.jobId, b.id);
  }
  // Conversations of a Bot: the open one is b.messages, the others carry their own messages.
  const chatName = (b, c) => { c = c || (b.chats || []).find(x => x.id === b.chatId) || {}; return c.title || (c.kind === 'schedule' ? '排程' : '新對話'); };
  const chatMessages = (b, c) => c.id === b.chatId ? (b.messages || []) : (c.messages || []);
  function chatsModal(b, query = '') {
    const q = query.trim().toLowerCase();
    const chats = [...(b.chats || [])].sort((x, y) => String(y.updatedAt || '').localeCompare(String(x.updatedAt || '')))
      .filter(c => !q || chatName(b, c).toLowerCase().includes(q) || chatMessages(b, c).some(m => String(m.content || '').toLowerCase().includes(q)));
    const rows = chats.map(c => `<div class="chat-row ${c.id === b.chatId ? 'current' : ''}"><button type="button" class="chat-open" data-action="open-chat" data-id="${esc(c.id)}"><strong>${esc(chatName(b, c))}</strong><small>${esc(formatDate(c.updatedAt))} · ${chatMessages(b, c).filter(m => m.role === 'user').length} 則</small></button><button type="button" class="link" data-action="rename-chat" data-id="${esc(c.id)}">改名</button><button type="button" class="link danger-link" data-action="delete-chat" data-id="${esc(c.id)}">刪除</button></div>`).join('');
    modal(`${b.name} 的對話`, `<div class="modal-body"><input id="chat-search" class="chat-search" placeholder="搜尋這個 Bot 的對話" value="${esc(query)}" aria-label="搜尋對話"><div class="chat-list">${rows || '<p class="muted">沒有符合的對話。</p>'}</div></div>`, '<div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">關閉</button><button type="button" class="primary" data-action="new-chat">＋ 新對話</button></div>');
  }
  // Messages across every Bot's conversations that match the sidebar search.
  function messageHits() {
    if (!state.query) return [];
    const hits = [];
    for (const b of state.data.bots) for (const c of b.chats || []) for (const m of chatMessages(b, c)) {
      if (m.content && matches(m.content)) hits.push({b, c, m});
      if (hits.length >= 30) return hits;
    }
    return hits;
  }
  function snippet(text) {
    const t = String(text || '').replace(/\s+/g, ' '), i = t.toLowerCase().indexOf(state.query.toLowerCase());
    return (i > 30 ? '…' : '') + t.slice(Math.max(0, i - 30), i + 60);
  }
  const RUN_STATUS = {running: '執行中', done: '已執行', failed: '失敗', missed: '錯過'};
  function scheduleHistory(x) {
    const rows = [...(x.runs || [])].reverse().map(r => {
      const open = r.messageId && r.status !== 'missed';
      return `<${open ? 'button type="button"' : 'div'} class="run-row ${open ? '' : 'static'}" ${open ? `data-action="open-run" data-kind="${esc(r.kind)}" data-target="${esc(r.targetId)}" data-id="${esc(r.messageId)}"` : ''}><span class="run-when">${esc(formatDate(r.at))}</span><span class="run-status ${esc(r.status)}">${esc(RUN_STATUS[r.status] || r.status)}</span><span class="run-text">${esc(r.reason || r.summary || '')}</span>${open ? '<span class="run-go" aria-hidden="true">›</span>' : ''}</${open ? 'button' : 'div'}>`;
    }).join('');
    modal('執行紀錄', `<div class="modal-body"><p class="muted">最近 ${(x.runs || []).length} 次。點一筆會打開那次的對話。</p><div class="run-list">${rows}</div></div>`, '<div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">關閉</button></div>');
  }
  // Open a Bot's or group's conversation at a message (from the history list or a Mac notification).
  async function openConversation(kind, id, messageId) {
    const exists = kind === 'group' ? (state.data.groups || []).some(g => g.id === id) : state.data.bots.some(b => b.id === id);
    if (!exists) { toast(kind === 'group' ? '找不到這個群組' : '找不到這個 Bot'); return; }
    if (kind !== 'group' && messageId) {
      const b = state.data.bots.find(x => x.id === id);
      const c = (b.chats || []).find(c => chatMessages(b, c).some(m => m.id === messageId));
      if (c && c.id !== b.chatId) { await post(`bots/${encodeURIComponent(id)}/chats/${encodeURIComponent(c.id)}/open`, {}); await refresh(); }
    }
    if (state.modal) closeModal();
    if (kind === 'group') state.groupId = id; else { state.groupId = null; state.selected = id; }
    state.page = 'chat'; state.launcher = false;
    state.focus = messageId ? {id: messageId, until: Date.now() + 5000} : null;
    render();
  }
  // Keep a message that was jumped to in view for a moment, even when replies arrive and the page redraws.
  document.addEventListener('wheel', () => { state.focus = null; }, {passive: true});  // scrolling yourself ends it
  function keepFocus() {
    if (!state.focus || Date.now() > state.focus.until) { state.focus = null; return false; }
    const el = [...document.querySelectorAll('[data-mid]')].find(x => x.dataset.mid === state.focus.id);
    if (!el) return false;
    el.scrollIntoView({block: 'center', behavior: 'instant'}); el.classList.add('flash');
    return true;
  }
  window.zookOpen = async (kind, id, messageId) => {  // from a Mac notification: the reply may be newer than this page
    try { await refresh(); startPollers(); } catch (_) {}
    if (state.data) await openConversation(kind, id, messageId);
  };
  // Who a schedule talks to: a Bot or a group, with its avatar.
  function scheduleTarget(x) {
    if (x.groupId) { const g = (state.data.groups || []).find(g => g.id === x.groupId); return `<span class="sched-target">${g ? avatarStack(g) + esc(g.name) : '找不到群組'}</span>`; }
    const b = state.data.bots.find(b => b.id === x.botId);
    return `<span class="sched-target">${b ? avatar(b) + esc(b.name) : '找不到 Bot'}</span>`;
  }
  const scheduleTargets = () => [...state.data.bots.map(b => ({id: 'bot:' + b.id, name: b.name})), ...(state.data.groups || []).map(g => ({id: 'group:' + g.id, name: g.name, hint: '群組'}))];
  function scheduleModal(x = {}) {
    if (!state.data.bots.length) { toast('請先建立一個 Bot'); return; }
    const two = n => String(n).padStart(2, '0'), [h, m] = (x.time || '10:00').split(':');
    const minutes = [...new Set([...Array.from({length: 12}, (_, i) => two(i * 5)), m])].sort();
    const iso = d => `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
    const days = Array.from({length: 120}, (_, i) => { const d = new Date(); d.setDate(d.getDate() + i); return iso(d); });
    if (x.date && !days.includes(x.date)) days.unshift(x.date);
    const dates = days.map((d, i) => ({id: d, name: (i === 0 && d === iso(new Date()) ? '今天 ' : i === 1 ? '明天 ' : '') + dayLabel(d)}));
    const target = x.groupId ? 'group:' + x.groupId : x.botId ? 'bot:' + x.botId : state.page === 'chat' && state.groupId ? 'group:' + state.groupId : 'bot:' + ((state.page === 'chat' && state.selected) || state.data.bots[0].id);
    modal(x.id ? '編輯排程' : '新增排程', `<form id="schedule-form"><div class="modal-body"><div class="field">對象${dropdown('target', target, scheduleTargets())}</div><label class="field">要做的事<textarea name="content" required placeholder="例如：整理今天的行事曆和未讀信件，列出三件最重要的事">${esc(x.content || '')}</textarea></label><div class="sched-when" data-repeat="${esc(x.repeat || 'daily')}"><div class="field">重複${dropdown('repeat', x.repeat || 'daily', REPEATS.map(r => ({id: r[0], name: r[1]})))}</div><div class="field when-date">日期${dropdown('date', x.date || dates[0].id, dates)}</div><div class="field when-day">日${dropdown('day', String(x.day || new Date().getDate()), Array.from({length: 31}, (_, i) => ({id: String(i + 1), name: (i + 1) + ' 號', hint: i >= 28 ? '沒有這天的月份在月底執行' : ''})))}</div><div class="field when-hour">時${dropdown('hour', h, Array.from({length: 24}, (_, i) => ({id: two(i), name: two(i)})))}</div><div class="field">分${dropdown('minute', m, minutes.map(v => ({id: v, name: v})))}</div></div><div class="setting-list in-form">${settingRow('啟用', '關閉後不會自動執行。', toggle('name="on"', x.on !== false, '啟用'))}${settingRow('錯過時補跑', '到時間時 Mac 在睡眠或 Zook 沒開，之後一開啟就補做一次（限 24 小時內）。', toggle('name="catchUp"', x.catchUp !== false, '錯過時補跑'))}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">儲存</button></div></form>`);
    $('#schedule-form').dataset.id = x.id || '';
  }
  function noteModal(n = {}) {
    modal(n.id ? '編輯知識' : '新增知識', `<form id="note-form"><div class="modal-body"><label class="field">標題<input name="title" required value="${esc(n.title||'')}"></label><label class="field">內容<textarea name="content" required>${esc(n.content||'')}</textarea></label><label class="field">標籤（以逗號分隔）<input name="tags" value="${esc((n.tags||[]).join(', '))}"></label><label class="field">關聯 Bot<select name="botId"><option value="">共用知識</option>${state.data.bots.map(b=>`<option value="${esc(b.id)}" ${(n.botId||(!n.id&&state.page==='chat'?state.selected:''))===b.id?'selected':''}>${esc(b.name)}</option>`).join('')}</select></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">儲存</button></div></form>`);
    $('#note-form').dataset.id = n.id || ''
  }
  function startPollers() {
    for (const j of state.data.jobs || [])
      if ((j.status === 'running' || j.status === 'queued') && !j.groupId && !state.pollers[j.id]) poll(j.id, j.botId);
    for (const g of state.data.groups || [])
      if (g.status === 'running') pollGroup(g.id)
  }
  // Conversations also change from outside this window (a paired phone, another Bot). Check regularly and redraw only when something differs.
  const syncKey = d => JSON.stringify([d.bots, d.groups, (d.jobs || []).map(j => [j.id, j.status])]);
  async function syncFromElsewhere() {
    if (state.syncing || !state.data || state.page !== 'chat' || document.querySelector('.modal') || document.querySelector('.dd.open')) return;
    state.syncing = true;
    const loads = state.loads;
    try {
      const data = await api('state');
      if (loads !== state.loads || syncKey(data) === syncKey(state.data)) return;  // this window reloaded meanwhile, or nothing new
      if (state.page !== 'chat' || document.querySelector('.modal') || document.querySelector('.dd.open')) return;
      applyState(data); startPollers();
    } catch (_) {} finally { state.syncing = false; }
  }
  async function refresh() {
    applyState(await api('state'));
  }
  function applyState(data) {
    state.data = data; state.loads = (state.loads || 0) + 1;
    if (!state.providers) api('providers').then(r => { state.providers = r.providers; }).catch(() => {});
    if (!state.data.bots) state.data.bots = [];
    if (!state.data.knowledge) state.data.knowledge = [];
    if (!state.data.schedules) state.data.schedules = [];
    if (!state.data.groups) state.data.groups = [];
    if (state.groupId && !activeGroup()) state.groupId = null;
    for (const job of state.data.jobs || []) state.jobDetails[job.id] = job;
    if (!state.selected || !activeBot()) state.selected = state.data.bots[0]?.id || null;
    render(true)
  }
  async function loadPage(p) {
    state.launcher = false;
    if (p === 'integrations') {
      await integrationsModal();
      return
    }
    state.page = p;
    if (p === 'skills' || p === 'mcp' || p === 'plugins') state.integrations = await api('integrations');
    if (p === 'usage') {
      // Open the page right away; each section fills in as its data arrives (earlier data stays on screen while refreshing).
      const seq = state.usageLoad = (state.usageLoad || 0) + 1;
      const fill = (key, request) => request.catch(e => ({error: e.message})).then(value => {
        if (state.usageLoad !== seq) return;
        state[key] = value;
        if (state.page !== 'usage') return;
        const pageEl = $('.page'), y = pageEl?.scrollTop;
        render(true);
        if (y) $('.page') && ($('.page').scrollTop = y);
      });
      render();
      fill('quota', api('quota?auto=1')); fill('botUsage', api('usage/bots')); fill('usage', api('usage'));
      return;
    }
    if (p === 'accounts') { state.accounts = null; render(); await reloadAccounts(); return; }
    if (p === 'settings') { state.remote = null; render(); loadRemote(); return; }
    render()
  }
  async function integrationsModal() {
    state.integrations = await api('integrations');
    let i = state.integrations;
    modal('連結應用程式', `<div class="modal-body"><p class="muted">這裡顯示本機偵測到的設定。設定存在不代表已驗證連線。</p><input id="integration-search" class="secondary" style="width:100%;text-align:left" placeholder="搜尋應用程式"><div class="tabs" style="margin:16px 0"><button class="active" data-action="int-filter" data-id="all">全部</button><button data-action="int-filter" data-id="providers">提供者</button><button data-action="int-filter" data-id="skills">Skills</button><button data-action="int-filter" data-id="mcp">MCP</button></div><div class="cards" id="integration-cards">${integrationCards(i,'all','')}</div></div>`, '', true)
  }

  function integrationCards(i, filter, q) {
    let all = ['providers', 'skills', 'mcp'].flatMap(k => (i?.[k] || []).map(x => ({
      ...x,
      kind: k
    }))).filter(x => (filter === 'all' || x.kind === filter) && (`${x.name} ${x.description||''}`.toLowerCase().includes(q.toLowerCase())));
    return all.length ? all.map(x => `<div class="card"><h3>${esc(x.name)}</h3><p>${esc(x.description||x.source||x.kind)}</p><span class="status">${esc(x.status|| (x.installed?'已偵測':'設定狀態未知'))}</span></div>`).join('') : '<div class="blank">沒有符合的項目。</div>'
  }

  function download(content, name, type) {
    let url = URL.createObjectURL(new Blob([content], {
      type
    }));
    let a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000)
  }
  async function poll(jobId, botId) {
    state.pollers[jobId] = { botId };
    try {
      let j = await api('jobs/' + encodeURIComponent(jobId));
      j.botId = botId;
      const changed = JSON.stringify(state.jobDetails[jobId]) !== JSON.stringify(j);
      state.jobDetails[jobId] = j;
      if (changed) render(true);
      if (j.status === 'running' || j.status === 'queued') {
        setTimeout(() => poll(jobId, botId), 1200);
        return
      }
      delete state.pollers[jobId];
      await refresh();
      if (j.status === 'failed') toast(j.error || '回覆失敗');
      if (j.status === 'cancelled') toast('已停止回覆')
    } catch (e) {
      delete state.pollers[jobId];
      toast(e.message);
      render(true)
    }
  }
  // Dropdown: open/close, pick an option, close on outside click or Escape.
  const closeDropdowns = except => document.querySelectorAll('.dd.open').forEach(d => { if (d !== except) { d.classList.remove('open'); d.querySelector('.dd-btn').setAttribute('aria-expanded', 'false'); } });
  document.addEventListener('click', e => {
    const opt = e.target.closest?.('.dd-opt'), btn = e.target.closest?.('.dd-btn');
    if (btn) {
      const dd = btn.closest('.dd'), open = !dd.classList.contains('open');
      closeDropdowns(dd); dd.classList.toggle('open', open); btn.setAttribute('aria-expanded', String(open));
      if (open) {
        const r = btn.getBoundingClientRect(), menu = dd.querySelector('.dd-menu');
        menu.style.minWidth = Math.max(r.width, 220) + 'px';
        menu.style.top = (r.bottom + 6) + 'px';
        menu.style.left = Math.max(8, Math.min(r.right - Math.max(menu.offsetWidth, r.width, 220), innerWidth - menu.offsetWidth - 8)) + 'px';
        if (r.bottom + 6 + menu.offsetHeight > innerHeight - 8) menu.style.top = Math.max(8, r.top - 6 - menu.offsetHeight) + 'px';
      }
      e.stopPropagation(); return;
    }
    if (opt) {
      const dd = opt.closest('.dd'), input = dd.querySelector('input[type=hidden]');
      dd.querySelectorAll('.dd-opt').forEach(o => { o.classList.toggle('selected', o === opt); o.setAttribute('aria-selected', String(o === opt)); });
      dd.querySelector('.dd-label').textContent = opt.dataset.label;
      closeDropdowns();
      if (input.value !== opt.dataset.value) { input.value = opt.dataset.value; input.dispatchEvent(new Event('change', {bubbles: true})); }
      e.stopPropagation(); return;
    }
    if (!e.target.closest?.('.dd-menu')) closeDropdowns();
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.querySelector('.dd.open')) { closeDropdowns(); e.stopPropagation(); } }, true);
  document.addEventListener('scroll', e => { if (!e.target.closest?.('.dd-menu')) closeDropdowns(); }, true);

  // Sidebar drag and drop.
  let dragging = null;
  const clearDropMarks = () => document.querySelectorAll('.drop-before, .drop-after, .drop-into').forEach(el => el.classList.remove('drop-before', 'drop-after', 'drop-into'));
  document.addEventListener('dragstart', e => {
    const bot = e.target.closest?.('[data-drag-bot]'), sec = e.target.closest?.('[data-drag-section]');
    if (bot) dragging = {kind: 'bot', id: bot.dataset.dragBot};
    else if (sec) dragging = {kind: 'section', id: sec.dataset.dragSection};
    else return;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragging.id);
    requestAnimationFrame(() => (bot || sec.closest('.side-section'))?.classList.add('dragging'));
  });
  document.addEventListener('dragend', () => { dragging = null; clearDropMarks(); document.querySelectorAll('.dragging').forEach(el => el.classList.remove('dragging')); });
  function dropTarget(e) {
    if (!dragging) return null;
    const section = e.target.closest?.('[data-drop-section]');
    if (!section) return null;
    if (dragging.kind === 'section') {
      if (section.dataset.dropSection === '__pinned') return null;
      const r = section.getBoundingClientRect();
      return {el: section, cls: e.clientY < r.top + r.height / 2 ? 'drop-before' : 'drop-after', section: section.dataset.dropSection};
    }
    const row = e.target.closest('[data-drag-bot]');
    if (row && row.dataset.dragBot !== dragging.id) {
      const r = row.getBoundingClientRect();
      return {el: row, cls: e.clientY < r.top + r.height / 2 ? 'drop-before' : 'drop-after', section: section.dataset.dropSection, botId: row.dataset.dragBot};
    }
    return {el: section, cls: 'drop-into', section: section.dataset.dropSection};
  }
  document.addEventListener('dragover', e => {
    const t = dropTarget(e);
    if (!t) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    if (!t.el.classList.contains(t.cls)) { clearDropMarks(); t.el.classList.add(t.cls); }
  });
  document.addEventListener('drop', async e => {
    const t = dropTarget(e), what = dragging;
    clearDropMarks();
    if (!t) return;
    e.preventDefault(); dragging = null;
    if (what.kind === 'section') {
      const names = sectionNames().filter(x => x !== what.id);
      let i = names.indexOf(t.section); if (i < 0) return;
      names.splice(t.cls === 'drop-after' ? i + 1 : i, 0, what.id);
      return saveArrangement(state.data.bots, names);
    }
    const moving = state.data.bots.find(b => b.id === what.id);
    if (!moving) return;
    const moved = t.section === '__pinned' ? {...moving, pinned: true} : {...moving, pinned: false, section: t.section};
    const rest = state.data.bots.filter(b => b.id !== what.id);
    let at;
    if (t.botId) { at = rest.findIndex(b => b.id === t.botId) + (t.cls === 'drop-after' ? 1 : 0); }
    else {
      // Dropped on the group itself: put it after the group's last Bot.
      const inGroup = b => t.section === '__pinned' ? b.pinned : !b.pinned && (b.section || '我的 Bots') === t.section;
      const last = rest.map(inGroup).lastIndexOf(true);
      at = last >= 0 ? last + 1 : rest.length;
    }
    rest.splice(at, 0, moved);
    await saveArrangement(rest, sectionNames());
  });

  // Window dragging: empty space in the sidebar top and page headers moves the window; double-click zooms it.
  // The app shell gets the header areas and the controls inside them, and handles the press itself.
  const DRAG_AREA = '.side-top, .main-header', NOT_DRAG = 'button, a, input, textarea, select, label, [data-action], [contenteditable]';
  let dragFrame = 0;
  const box = el => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
  const reportDragAreas = () => {
    dragFrame = 0;
    const areas = [...document.querySelectorAll(DRAG_AREA)];
    window.webkit?.messageHandlers?.zookWindow?.postMessage({drag: areas.map(box), block: areas.flatMap(a => [...a.querySelectorAll(NOT_DRAG)]).map(box)});
  };
  const scheduleDragAreas = () => { if (!dragFrame) dragFrame = setTimeout(reportDragAreas, 30); };  // timers keep running when the window is covered
  new MutationObserver(scheduleDragAreas).observe(document.documentElement, {childList: true, subtree: true});
  window.addEventListener('resize', scheduleDragAreas);
  document.addEventListener('click', async e => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const action = el.dataset.action,
      id = el.dataset.id;
    try {
      switch (action) {
        case 'pick-mention':
          pickMention(Number(id));
          break;
        case 'select-group':
          state.groupId = id;
          state.page = 'chat';
          state.launcher = false;
          render();
          break;
        case 'new-group':
          if (state.data.bots.length < 2) { toast('至少需要 2 個 Bot 才能建立群組'); break; }
          groupModal();
          break;
        case 'edit-group':
          groupModal(activeGroup());
          break;
        case 'delete-group':
          if (confirm('確定刪除這個群組及其對話？成員 Bot 不會被刪除。')) {
            await api('groups/' + encodeURIComponent($('#group-form').dataset.id), {method: 'DELETE'});
            closeModal();
            state.groupId = null;
            await refresh();
            toast('已刪除群組')
          }
          break;
        case 'refresh-claude-quota':
          el.disabled = true; el.textContent = '更新中…';
          try { state.quota = await post('quota/claude/refresh'); render(true); toast('已更新 Claude 額度'); }
          finally { if (el.isConnected) { el.disabled = false; el.textContent = '立即更新'; } }
          break;
        case 'account-login':
          el.disabled = true;
          await post('accounts/' + encodeURIComponent(id) + '/login', {method: el.dataset.method, account: el.dataset.account || ''});
          await reloadAccounts();
          break;
        case 'update-open':
          updateModal();
          break;
        case 'update-check':
          el.disabled = true; el.textContent = '檢查中…';
          state.update = await post('update/check'); render(true);
          toast(state.update.available ? `有新版 ${state.update.latest}` : state.update.error || '已是最新版');
          break;
        case 'update-install':
          el.disabled = true;
          await installUpdate();
          break;
        case 'accounts-from-form':
          closeModal(); state.page = 'accounts'; state.accounts = null; render(); await reloadAccounts();
          break;
        case 'profile-add':
          profileModal(state.accounts.providers.find(x => x.id === id));
          break;
        case 'profile-delete':
          if (!confirm(`移除帳號「${el.dataset.name}」？使用它的 Bot 會改用預設帳號。`)) break;
          await post('accounts/' + encodeURIComponent(id) + '/profiles/delete', {account: el.dataset.account});
          await reloadAccounts(); toast('已移除帳號');
          break;
        case 'provider-add':
          providerAddModal();
          break;
        case 'provider-add-one':
          el.disabled = true;
          await post('accounts/' + encodeURIComponent(id) + '/add');
          closeModal(); await reloadAccounts(); toast('已加入，可以按「一鍵安裝」或直接登入');
          break;
        case 'provider-custom':
          customProviderModal();
          break;
        case 'provider-edit':
          customProviderModal(state.accounts.providers.find(x => x.id === id));
          break;
        case 'provider-install': {
          const p = state.accounts.providers.find(x => x.id === id);
          const domain = (el.dataset.command.match(/https?:\/\/([^/\s]+)/) || [])[1];
          const msg = el.dataset.command ? `將在這台電腦執行 ${p.name} 的官方安裝程式${domain ? '（來自 ' + domain + '）' : ''}。\n\n確定安裝？` : `確定把 ${p.name} 更新到最新版？`;
          if (!confirm(msg)) break;
          el.disabled = true;
          await post('accounts/' + encodeURIComponent(id) + '/install');
          await reloadAccounts();
          break;
        }
        case 'install-cancel':
          await post('accounts/' + encodeURIComponent(id) + '/install/cancel');
          await reloadAccounts();
          break;
        case 'provider-remove': {
          const p = state.accounts.providers.find(x => x.id === id);
          if (!confirm(`從 Zook 移除 ${p.name}？這不會解除安裝 CLI，也不會登出。`)) break;
          await post('accounts/' + encodeURIComponent(id) + '/remove');
          await reloadAccounts(); toast('已從 Zook 移除');
          break;
        }
        case 'account-cancel':
          await post('accounts/' + encodeURIComponent(id) + '/login/cancel', {account: el.dataset.account || ''});
          await reloadAccounts();
          break;
        case 'account-logout':
          if (confirm('確定登出？使用這個提供者的 Bot 會無法回覆，直到重新登入。')) {
            await post('accounts/' + encodeURIComponent(id) + '/logout');
            state.accounts = await api('accounts'); render(true); toast('已登出');
          }
          break;
        case 'persona-reset':
          if (state.personaDrafts) delete state.personaDrafts[activeBot()?.id];
          render(true);
          break;
        case 'dir-tab':
          state.page = id; render();
          break;
        case 'dir-filter':
          state.dirFilter = id; render(true);
          break;
        case 'dir-expand':
          state.dirExpanded = {...(state.dirExpanded || {}), [id]: !state.dirExpanded?.[id]}; render(true);
          break;
        case 'dir-toggle': {
          const kind = el.dataset.kind;
          el.disabled = true;
          const key = kind === 'skill' ? 'disabledSkills' : kind === 'mcp' ? 'sharedMcp' : 'disabledPlugins', off = new Set(state.data.settings[key] || []);
          off.has(id) ? off.delete(id) : off.add(id);
          state.data.settings = await post('settings', {[key]: [...off]}, 'PATCH');
          if (kind === 'mcp') { render(true); toast(off.has(id) ? '已開放給所有 Bot' : '已停用這個連接器'); break; }
          if (kind === 'plugin') state.integrations = await api('integrations');
          render(true);
          toast(kind === 'skill' ? (off.has(id) ? '已停用這個 Skill' : '已開放給所有 Bot') : (off.has(id) ? '已停用插件' : '已啟用插件'));
          break;
        }
        case 'delete-memory':
          if (confirm('確定刪除這則記憶？')) {
            await api('memories/' + encodeURIComponent(id), {method: 'DELETE'});
            await refresh();
            toast('已刪除記憶')
          }
          break;
        case 'stop-group':
          await post('groups/' + encodeURIComponent(id) + '/stop');
          toast('已停止討論');
          await refresh();
          break;
        case 'mention': {
          const input = $('#chat-input');
          const pos = input.selectionStart ?? input.value.length;
          const before = input.value.slice(0, pos), insert = (before && !/\s$/.test(before) ? ' ' : '') + '@' + id + ' ';
          input.value = before + insert + input.value.slice(pos); updateInputMirror();
          input.focus();
          input.setSelectionRange(pos + insert.length, pos + insert.length);
          break;
        }
        case 'select-bot':
          state.groupId = null;
          state.selected = id;
          state.page = 'chat';
          state.launcher = false;
          render();
          break;
        case 'remote-pair':
          el.disabled = true;
          try { pairingModal(await post('remote/pairing')); } catch (err) { toast(err.message); el.disabled = false; }
          break;
        case 'remote-pair-cancel':
          await api('remote/pairing', {method: 'DELETE'}).catch(() => {});
          closeModal(); loadRemote(true);
          break;
        case 'remote-revoke': {
          const d = state.remote?.devices.find(x => x.id === id);
          if (!d || !confirm(`撤銷「${d.name}」？這台裝置會立刻無法連線，要再使用必須重新配對。`)) break;
          state.remote = await api('remote/devices/' + encodeURIComponent(id), {method: 'DELETE'});
          render(true); toast('已撤銷「' + d.name + '」');
          break;
        }
        case 'new-section':
          sectionModal();
          break;
        case 'rename-section':
          sectionModal(id);
          break;
        case 'delete-section':
          await saveArrangement(state.data.bots, sectionNames().filter(x => x !== id));
          toast('已刪除分組');
          break;
        case 'dir-collapse': {
          // Remembered with the other settings, so a group you fold away stays folded next time.
          const now = new Set(state.data.settings.dirCollapsed || []);
          now.has(id) ? now.delete(id) : now.add(id);
          state.data.settings.dirCollapsed = [...now]; render(true);
          state.data.settings = await post('settings', {dirCollapsed: [...now]}, 'PATCH');
          break;
        }
        case 'collapse':
          state.collapsed[id] = !state.collapsed[id];
          render(true);
          break;
        case 'search-focus':
          $('#side-search')?.focus();
          break;
        case 'new-bot':
          botModal();
          break;
        case 'edit-bot':
          botModal(activeBot());
          break;
        case 'launcher':
          state.launcher = !state.launcher;
          render(true);
          break;
        case 'page':
          await loadPage(id);
          break;
        case 'toggle-detail':
          state.detailOpen = !state.detailOpen;
          render(true);
          break;
        case 'detail':
          state.detail = id;
          render(true);
          break;
        case 'new-schedule':
          scheduleModal();
          break;
        case 'edit-schedule':
          scheduleModal(state.data.schedules.find(x => x.id === id));
          break;
        case 'delete-schedule':
          if (confirm('確定刪除這個排程？')) {
            await api('schedules/' + encodeURIComponent(id), {method: 'DELETE'});
            await refresh();
            toast('已刪除排程');
          }
          break;
        case 'schedule-history':
          scheduleHistory(state.data.schedules.find(x => x.id === id));
          break;
        case 'open-run':
          await openConversation(el.dataset.kind, el.dataset.target, id);
          break;
        case 'redo-again': {
          const b = activeBot();
          if (redoAllowed(b)) await redo(b, {mode: 'again'});
          break;
        }
        case 'edit-last': {
          const b = activeBot(), last = [...b.messages].reverse().find(m => m.role === 'user');
          modal('編輯訊息', `<form id="edit-last-form"><div class="modal-body"><label class="field">改完後重新送出，之後的回覆會被取代<textarea name="content" required rows="6">${esc(last.content)}</textarea></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">重新送出</button></div></form>`);
          break;
        }
        case 'redo-model': {
          const b = activeBot(), installed = (state.providers || []).filter(p => p.installed !== false);
          const options = installed.map(p => ({id: p.id, name: String(p.name).split('（')[0], hint: p.id === (b.provider || state.data.settings.provider) ? '這個 Bot 目前用的' : ''}));
          if (!options.length) { toast('沒有其他可用的模型'); break; }
          const other = options.find(o => !o.hint) || options[0];
          modal('換模型重答', `<form id="redo-model-form"><div class="modal-body"><p class="muted">只有這一次用別的模型回答，不會改變 Bot 的設定。</p><div class="setting-list in-form">${settingRow('模型', '用預設版本回答', dropdown('provider', other.id, options))}</div></div><div class="modal-foot"><button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">重答</button></div></form>`);
          break;
        }
        case 'open-message':
          state.query = ''; await openConversation('bot', el.dataset.bot, id);
          break;
        case 'chats':
          chatsModal(activeBot());
          break;
        case 'new-chat': {
          const b = activeBot();
          await post(`bots/${encodeURIComponent(b.id)}/chats`, {});
          if (state.modal) closeModal();
          await refresh(); $('#chat-input')?.focus();
          break;
        }
        case 'open-chat': {
          const b = activeBot();
          if (id !== b.chatId) { await post(`bots/${encodeURIComponent(b.id)}/chats/${encodeURIComponent(id)}/open`, {}); }
          closeModal(); await refresh();
          break;
        }
        case 'rename-chat': {
          const b = activeBot(), c = b.chats.find(x => x.id === id);
          modal('對話名稱', `<form id="chat-rename-form" data-id="${esc(id)}"><div class="modal-body"><label class="field">名稱<input name="title" required maxlength="80" value="${esc(chatName(b, c))}"></label></div><div class="modal-foot"><button type="button" class="secondary" data-action="chats">返回</button><button class="primary">儲存</button></div></form>`);
          break;
        }
        case 'delete-chat': {
          const b = activeBot(), c = b.chats.find(x => x.id === id);
          if (!confirm(`確定刪除「${chatName(b, c)}」？刪除後無法復原。`)) break;
          await api(`bots/${encodeURIComponent(b.id)}/chats/${encodeURIComponent(id)}`, {method: 'DELETE'});
          await refresh(); chatsModal(activeBot()); toast('已刪除對話');
          break;
        }
        case 'run-schedule':
          await post('schedules/' + encodeURIComponent(id) + '/run', {});
          await refresh(); startPollers();
          toast('已送出，回覆會出現在對話裡');
          break;
        case 'new-note':
          noteModal();
          break;
        case 'edit-note':
          noteModal(state.data.knowledge.find(n => n.id === id));
          break;
        case 'delete-note':
          if (confirm('確定刪除這則知識？')) {
            await api('knowledge/' + encodeURIComponent(id), {
              method: 'DELETE'
            });
            await refresh();
            toast('已刪除知識')
          }
          break;
        case 'delete-bot':
          if (confirm('確定刪除這個 Bot 及其對話？')) {
            await api('bots/' + encodeURIComponent($('#bot-form').dataset.id), {
              method: 'DELETE'
            });
            closeModal();
            await refresh();
            toast('已刪除 Bot')
          }
          break;
        case 'choose-folder': {
          const picked = (await post('choose-folder')).path, form = $('#bot-form');
          if (picked && form) { form.elements.accessFolder.value = picked; form.querySelector('[data-access-path]').textContent = picked; saveBotDraft(form); }
          break;
        }
        case 'close-modal':
          closeModal();
          break;
        case 'overlay':
          if (e.target === el) closeModal();
          break;
        case 'shape':
          $('#bot-form [name=shape]').value = id;
          $$('.shape-btn').forEach(x => x.classList.toggle('selected', x.dataset.id === id));
          $('.bot-preview .avatar').className = `avatar shape-${id} hero`;
          saveBotDraft($('#bot-form'));
          break;
        case 'color':
          $('#bot-form [name=color]').value = id;
          $$('.swatch').forEach(x => x.classList.toggle('selected', x.dataset.id === id));
          $$('#bot-form .avatar').forEach(x => x.style.setProperty('--c', id));
          saveBotDraft($('#bot-form'));
          break;
        case 'voice':
          modal('語音輸入', '<div class="modal-body"><p class="muted">尚未安裝語音辨識模型。</p></div>', '<div class="modal-foot"><button class="primary" data-action="close-modal">知道了</button></div>');
          break;
        case 'composer-menu':
          modal('更多選項', '<div class="modal-body"><p class="muted">新增知識，為 Bot 提供相關背景。</p><button class="secondary" data-action="new-note">＋ 新增知識</button></div>');
          break;
        case 'approve':
        case 'deny':
          if (state.deciding[id]) break;
          state.deciding[id] = true;
          el.disabled = true;
          try {
            await post('approvals/' + encodeURIComponent(id), {decision: action === 'approve' ? 'approve' : 'deny'});
            for (const j of Object.values(state.jobDetails)) for (const a of j.approvals || []) if (a.id === id) a.status = action === 'approve' ? 'approved' : 'denied';
            render(true);
          } finally { delete state.deciding[id]; if (el.isConnected) el.disabled = false; }
          break;
        case 'gmail-setup':
          gmailModal();
          break;
        case 'gmail-remove':
          if (!confirm('中斷 Gmail 連接？所有 Bot 都會無法再使用 Gmail，儲存的應用程式密碼會從鑰匙圈刪除。')) break;
          await api('gmail', {method: 'DELETE'});
          delete state.mcpTests['builtin:gmail'];
          state.integrations = await api('integrations'); await refresh(); toast('已中斷 Gmail 連接');
          break;
        case 'connector-add':
          connectorModal();
          break;
        case 'skills-import': {
          const ids = directoryItems('skills').filter(i => i.group === id && i.importable).map(i => i.id);
          el.disabled = true; el.textContent = '匯入中…';
          const r = await post('skills/import', {ids});
          state.integrations = await api('integrations'); await refresh();
          toast([r.imported.length ? `已匯入 ${r.imported.length} 個 Skill` : '沒有新的 Skill 可以匯入', r.skipped.length ? `${r.skipped.length} 個同名的只保留一份` : '', r.failed.length ? `${r.failed.length} 個匯入失敗：${r.failed[0].error}` : ''].filter(Boolean).join('，'));
          break;
        }
        case 'skill-update':
          el.disabled = true;
          await post('skills/' + encodeURIComponent(id.split(':')[1]) + '/update');
          state.integrations = await api('integrations'); render(true); toast('已更新成原來源的最新內容');
          break;
        case 'skill-remove':
          if (!confirm(`從 Zook 移除 Skill「${el.dataset.name}」？原本工具裡的那一份不受影響。`)) break;
          await api('skills/' + encodeURIComponent(id.split(':')[1]), {method: 'DELETE'});
          state.integrations = await api('integrations'); await refresh(); toast('已從 Zook 移除');
          break;
        case 'connector-copy': {
          el.disabled = true;
          const made = await post('connector-copy', {id});
          state.integrations = await api('integrations'); await refresh();
          try { state.mcpTests[made.id] = await post('mcp/' + encodeURIComponent(made.id) + '/test'); }
          catch (error) { state.mcpTests[made.id] = {status: 'error', error: error.message}; }
          render(true);
          toast(state.mcpTests[made.id].status === 'ready' ? '已複製到 Zook，連線正常' : '已複製到 Zook，但連不上。如果它需要登入，授權還留在原本的工具裡');
          break;
        }
        case 'pack-export': {
          el.disabled = true;
          const pack = await api('pack');
          el.disabled = false;
          if (!pack.skills && !pack.connectors) { toast('還沒有可以匯出的內容。先把 Skill 匯入 Zook，或把連接器複製到 Zook'); break; }
          const raw = atob(pack.data), bytes = new Uint8Array(raw.length);
          for (let n = 0; n < raw.length; n++) bytes[n] = raw.charCodeAt(n);
          download(bytes, pack.name, 'application/zip');
          toast(`已匯出 ${pack.skills} 個 Skill、${pack.connectors} 個連接器`);
          break;
        }
        case 'pack-import': {
          const input = document.createElement('input');
          input.type = 'file'; input.accept = '.zookpack,.zip';
          input.onchange = async () => {
            const file = input.files[0];
            if (!file) return;
            if (file.size > 150 * 1024 * 1024) { toast('設定包超過 150 MB，無法匯入'); return; }
            if (!confirm(`匯入「${file.name}」？\n\n設定包裡的 Skill 和連接器可以在這台 Mac 上執行程式，請只匯入你自己匯出的檔案。`)) return;
            try {
              const text = await new Promise((done, fail) => { const reader = new FileReader(); reader.onload = () => done(reader.result); reader.onerror = fail; reader.readAsDataURL(file); });
              const r = await post('pack', {data: String(text).split(',')[1] || ''});
              state.integrations = await api('integrations'); await refresh();
              toast([`已匯入 ${r.skills.length} 個 Skill、${r.connectors.length} 個連接器`, r.skipped.length ? `${r.skipped.length} 個已經有或無法匯入，已略過` : '', r.needKeys.length ? `${r.needKeys.length} 個連接器需要重新貼上金鑰` : ''].filter(Boolean).join('，'));
            } catch (error) { toast(error.message || '匯入失敗'); }
          };
          input.click();
          break;
        }
        case 'connector-edit':
          connectorModal((state.integrations?.mcp || []).find(i => i.id === id));
          break;
        case 'connector-delete':
          if (!confirm(`移除連接器「${el.dataset.name}」？所有 Bot 都會無法再使用它。`)) break;
          await api('connectors/' + encodeURIComponent(id.split(':')[1]), {method: 'DELETE'});
          delete state.mcpTests[id];
          state.integrations = await api('integrations'); await refresh(); toast('已移除連接器');
          break;
        case 'test-mcp':
          el.disabled = true;
          try { state.mcpTests[id] = await post('mcp/' + encodeURIComponent(id) + '/test'); }
          catch (error) { state.mcpTests[id] = {status:'error', error:error.message}; }
          render(true);
          break;
        case 'cancel-job':
          await post('jobs/' + encodeURIComponent(id) + '/cancel');
          toast('正在停止回覆');
          break;
        case 'share': {
          const g = activeGroup();
          if (g) {
            const name = id => state.data.bots.find(b => b.id === id)?.name || 'Bot';
            download(`# ${g.name}\n\n${(g.messages||[]).filter(m=>m.content).map(m=>m.role==='system'?`> ${m.content}`:`## ${m.role==='user'?'我':name(m.botId)}\n\n${m.content}`).join('\n\n')}`, `${g.name.replace(/[\\/:*?"<>|]/g,'_')}-群組對話.md`, 'text/markdown;charset=utf-8');
            break
          }
          let b = activeBot();
          download(`# ${b.name}\n\n${(b.messages||[]).map(m=>`## ${m.role==='user'?'我':b.name}\n\n${m.content}`).join('\n\n')}`, `${b.name.replace(/[\\/:*?"<>|]/g,'_')}-對話.md`, 'text/markdown;charset=utf-8');
          break
        }
        case 'export': {
          let data = await post('export');
          download(JSON.stringify(data, null, 2), 'Zook-export.json', 'application/json');
          break
        }
        case 'refresh-models':
          await loadModels(el.closest('form'), true);
          break;
        case 'int-filter':
          $$('[data-action=int-filter]').forEach(x => x.classList.toggle('active', x === el));
          $('#integration-cards').innerHTML = integrationCards(state.integrations, id, $('#integration-search').value);
          break;
      }
    } catch (err) {
      toast(err.message)
    }
  });

  function $$(s) {
    return [...document.querySelectorAll(s)]
  }
  document.addEventListener('change', e => {
    if (e.target.name === 'access' && e.target.closest('#bot-form')) e.target.closest('form').querySelector('[data-access-folder]').hidden = e.target.value !== 'folder';
    if (e.target.name === 'transport' && e.target.closest('#connector-form')) e.target.closest('form').querySelectorAll('[data-for]').forEach(x => x.hidden = x.dataset.for !== e.target.value);
    if (e.target.name === 'accountType' && e.target.closest('#profile-form')) e.target.closest('form').querySelector('[data-key-field]').hidden = e.target.value !== 'key';
  });
  document.addEventListener('input', e => {
    if (e.target.closest('#bot-form')) saveBotDraft(e.target.closest('form'));
    if (e.target.name === 'modelCustom') {
      const f = e.target.closest('form');
      f.elements.model.value = e.target.value;
      if (f.id === 'bot-form') saveBotDraft(f);
    }
    if (e.target.id === 'dir-search') {
      const pos = e.target.selectionStart;
      state.dirQuery = e.target.value;
      render(true);
      const x = $('#dir-search'); x.focus(); x.setSelectionRange(pos, pos);
      return;
    }
    if (e.target.id === 'skill-search') {
      const pos = e.target.selectionStart;
      state.skillQuery = e.target.value;
      render(true);
      const x = $('#skill-search'); x.focus(); x.setSelectionRange(pos, pos);
      return;
    }
    if (e.target.id === 'chat-search') {
      const value = e.target.value; chatsModal(activeBot(), value);
      const box = $('#chat-search'); box.focus(); box.setSelectionRange(value.length, value.length);
      return;
    }
    if (e.target.id === 'side-search') {
      let pos = e.target.selectionStart;
      state.query = e.target.value;
      render(true);
      let x = $('#side-search');
      x.focus();
      x.setSelectionRange(pos, pos)
    }
    if (e.target.classList.contains('ability-search')) {
      const q = e.target.value.toLowerCase();
      e.target.parentElement.querySelectorAll('.ability-option').forEach(x => x.hidden = !x.dataset.search.includes(q));
    }
    if (e.target.id === 'integration-search') {
      $('#integration-cards').innerHTML = integrationCards(state.integrations, $('[data-action=int-filter].active')?.dataset.id || 'all', e.target.value)
    }
    if (e.target.id === 'persona-input') {
      const id = e.target.closest('form').dataset.id;
      state.personaDrafts = {...(state.personaDrafts || {}), [id]: e.target.value};
      const form = e.target.closest('form'), bot = state.data.bots.find(x => x.id === id);
      const dirty = e.target.value !== (bot?.persona || '');
      form.querySelector('.primary').disabled = !dirty;
      form.querySelector('small').textContent = e.target.value.length.toLocaleString() + ' / 20,000 字';
      return;
    }
    if (e.target.id === 'chat-input') {
      updateMentionMenu(); updateInputMirror();
      e.target.style.height = 'auto';
      e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px'
    }
  });
  document.addEventListener('change', async e => {
    if (e.target.dataset.remoteEnabled !== undefined || e.target.dataset.remoteRelay !== undefined) {
      const relayUrl = (document.querySelector('[data-remote-relay]')?.value || '').trim(), enabled = !!document.querySelector('[data-remote-enabled]')?.checked;
      try {
        state.data.settings = await post('settings', {remote: {enabled, relayUrl}}, 'PATCH');
        toast(enabled ? '遠端連線已開啟' : e.target.dataset.remoteRelay !== undefined ? '已儲存中繼伺服器' : '遠端連線已關閉');
        setTimeout(() => loadRemote(true), 1500);
      } catch (err) { toast(err.message); }
      await loadRemote(true);
      return;
    }
    if (e.target.dataset.fallbackSlot !== undefined) {
      const picks = [...document.querySelectorAll('[data-fallback-slot]')].map(x => x.value).filter(Boolean);
      try { state.data.settings = await post('settings', {fallbacks: [...new Set(picks)]}, 'PATCH'); toast(picks.length ? '備用順序：' + [...new Set(picks)].map(providerShort).join(' → ') : '已關閉自動換模型'); }
      catch (err) { toast(err.message); }
      return;
    }
    if (e.target.name === 'repeat' && e.target.closest('#schedule-form')) {
      e.target.closest('.sched-when').dataset.repeat = e.target.value;
      return;
    }
    if (e.target.dataset.scheduleNotify !== undefined) {
      try { state.data.settings = await post('settings', {scheduleNotify: e.target.checked}, 'PATCH'); toast(e.target.checked ? '會跳出排程通知' : '已關閉排程通知'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      return;
    }
    if (e.target.dataset.scheduleSwitch !== undefined) {
      const on = e.target.checked;
      try { await post('schedules/' + encodeURIComponent(e.target.dataset.id), {on}, 'PATCH'); await refresh(); toast(on ? '已啟用排程' : '已停用排程'); }
      catch (err) { e.target.checked = !on; toast(err.message); }
      return;
    }
    if (e.target.dataset.dirFilter !== undefined) { state.dirFilter = e.target.value; render(true); return; }
    if (e.target.dataset.dirSwitch !== undefined) {
      const kind = e.target.dataset.kind, id = e.target.dataset.id;
      const key = kind === 'skill' ? 'disabledSkills' : kind === 'mcp' ? 'sharedMcp' : 'disabledPlugins', set = new Set(state.data.settings[key] || []);
      const turnOn = e.target.checked; e.target.disabled = true;
      if (kind === 'mcp') turnOn ? set.add(id) : set.delete(id); else turnOn ? set.delete(id) : set.add(id);
      try {
        state.data.settings = await post('settings', {[key]: [...set]}, 'PATCH');
        if (kind === 'plugin') state.integrations = await api('integrations');
        render(true); toast(turnOn ? '已開啟' : '已關閉');
      } catch (err) { e.target.checked = !turnOn; e.target.disabled = false; toast(err.message); }
      return;
    }
    if (e.target.dataset.autoUpdate !== undefined) {
      try { state.data.settings = await post('settings', {autoUpdateCheck: e.target.checked}, 'PATCH'); toast(e.target.checked ? '會自動檢查更新' : '已關閉自動檢查更新'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      return;
    }
    if (e.target.dataset.webSearch !== undefined) {
      try { state.data.settings = await post('settings', {webSearch: e.target.checked}, 'PATCH'); render(true); toast(e.target.checked ? '所有 Bot 已可上網搜尋' : '已關閉上網搜尋'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      return;
    }
    if (e.target.dataset.permissionMode !== undefined && e.target.name === 'permissionMode' && !e.target.closest('form')) {
      const previous = state.data.settings.permissionMode || 'manual';
      try {
        state.data.settings = await post('settings', {permissionMode: e.target.value}, 'PATCH');
        render(true); toast('主動性已改為「' + permissionName(e.target.value) + '」');
      } catch (err) { toast(err.message); state.data.settings.permissionMode = previous; render(true); }
      return;
    }
    if (e.target.dataset.pluginToggle) {
      const off = new Set(state.data.settings.disabledPlugins || []), id = e.target.dataset.pluginToggle;
      e.target.checked ? off.delete(id) : off.add(id);
      e.target.disabled = true;
      try {
        state.data.settings = await post('settings', {disabledPlugins: [...off]}, 'PATCH');
        state.integrations = await api('integrations');
        render(true); toast(e.target.checked ? '已啟用插件' : '已停用插件，它的 Skill 與 MCP 不再提供給 Bot');
      } catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      finally { if (e.target.isConnected) e.target.disabled = false; }
      return;
    }
    if (e.target.dataset.sharedSkill) {
      const off = new Set(state.data.settings.disabledSkills || []), id = e.target.dataset.sharedSkill;
      e.target.checked ? off.delete(id) : off.add(id);
      e.target.disabled = true;
      try { state.data.settings = await post('settings', {disabledSkills: [...off]}, 'PATCH'); render(true); toast(e.target.checked ? '已開放給所有 Bot' : '已停用此 Skill'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      finally { if (e.target.isConnected) e.target.disabled = false; }
      return;
    }
    if (e.target.id === 'ability-bot') { state.selected = e.target.value || null; render(); return; }
    if (e.target.dataset.abilityKind) {
      const b = activeBot(); if (!b) return;
      const key = e.target.dataset.abilityKind, id = e.target.dataset.abilityId;
      const values = new Set(b[key] || []); e.target.checked ? values.add(id) : values.delete(id);
      e.target.disabled = true;
      try { await post('bots/' + encodeURIComponent(b.id), {[key]: [...values]}, 'PATCH'); b[key] = [...values]; toast('已更新 Bot 能力'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
      finally { e.target.disabled = false; }
      return;
    }
    const form = e.target.closest('form');
    if (!form || !form.querySelector('.model-picker')) return;
    if (e.target.name === 'provider') {
      form.elements.model.value = '';
      form.elements.modelSelect.value = '';
      form.elements.modelCustom.value = '';
      form.elements.modelCustom.hidden = true;
      form.dataset.providerChanged = '1';
      const slot = form.querySelector('[data-account-field]');
      if (slot) slot.innerHTML = accountField(e.target.value, '');
      form.querySelector('.model-note').textContent = '提供者已變更，模型已切換為預設。';
      loadModels(form);
    } else if (e.target.name === 'modelSelect') {
      const custom = form.elements.modelCustom;
      const isCustom = e.target.value === '__custom__';
      custom.hidden = !isCustom;
      form.elements.model.value = isCustom ? custom.value : e.target.value;
      if (isCustom) custom.focus();
    }
    if (form.id === 'bot-form') saveBotDraft(form);
  });
  document.addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    try {
      if (form.id === 'chat-form') {
        let input = $('#chat-input'),
          content = input.value.trim();
        if (!content) return;
        const g = activeGroup();
        if (g) {
          await post('groups/' + encodeURIComponent(g.id) + '/messages', {content});
          input.value = ''; updateInputMirror();
          await refresh();
          pollGroup(g.id);
          return;
        }
        let botId = state.selected;
        let result = await post('chat', {
          botId,
          content
        });
        input.value = ''; updateInputMirror();
        await refresh();
        poll(result.jobId, botId)
      } else if (form.id === 'bot-form') {
        let d = new FormData(form),
          id = form.dataset.id;
        let data = {
          name: d.get('name').trim(),
          shape: d.get('shape'),
          color: d.get('color'),
          instructions: d.get('instructions'),
          persona: d.get('persona') || '',
          provider: d.get('provider'),
          model: d.get('model'),
          section: d.get('section'),
          pinned: d.has('pinned'),
          fallbacks: d.get('fallbackChoice') === '__none' ? [] : !d.get('fallbackChoice') || d.get('fallbackChoice') === '__default' ? null : [d.get('fallbackChoice')], permissionMode: d.get('permissionMode') || '',
          account: d.get('account') || '',
          access: d.get('access') || 'full', accessFolder: d.get('access') === 'folder' ? d.get('accessFolder') || '' : ''
        };
        if (data.access === 'folder' && !data.accessFolder) { toast('請先選擇資料夾'); return; }
        let result = await post(id ? 'bots/' + encodeURIComponent(id) : 'bots', data, id ? 'PATCH' : 'POST');
        if (!id) { try { sessionStorage.removeItem('swarmr-new-bot-draft'); } catch (_) {} }
        closeModal();
        await refresh();
        if (!id) {
          state.selected = result.id || result.bot?.id || state.data.bots.at(-1)?.id;
          state.page = 'chat';
          render()
        }
        toast(id ? '已儲存 Bot' : '已建立 Bot')
      } else if (form.id === 'mcp-bots-form') {
        const id = form.dataset.id, chosen = new Set(new FormData(form).getAll('bots'));
        for (const b of state.data.bots) {
          const has = (b.enabledMcp || []).includes(id);
          if (has === chosen.has(b.id)) continue;
          const next = has ? b.enabledMcp.filter(x => x !== id) : [...(b.enabledMcp || []), id];
          await post('bots/' + encodeURIComponent(b.id), {enabledMcp: next}, 'PATCH');
        }
        closeModal(); await refresh(); toast('已更新使用這個連接器的 Bot');
      } else if (form.id === 'persona-form') {
        const id = form.dataset.id, persona = new FormData(form).get('persona');
        await post('bots/' + encodeURIComponent(id), {persona}, 'PATCH');
        if (state.personaDrafts) delete state.personaDrafts[id];
        await refresh(); toast('已儲存人格，下次回覆開始生效');
      } else if (form.id === 'custom-provider-form') {
        const d = Object.fromEntries(new FormData(form));
        if (d.providerId) d.id = d.providerId;
        delete d.providerId;
        await post('accounts/custom', d);
        closeModal(); await reloadAccounts(); toast('已儲存，Bot 現在可以選用這個 CLI');
      } else if (form.id === 'gmail-form') {
        const d = new FormData(form), button = form.querySelector('.primary');
        button.disabled = true; button.textContent = '正在連接…';
        try { await post('gmail', {address: d.get('address').trim(), password: d.get('password')}); }
        finally { if (button.isConnected) { button.disabled = false; button.textContent = '連接'; } }
        closeModal(); delete state.mcpTests['builtin:gmail'];
        state.integrations = await api('integrations'); await refresh(); toast('Gmail 已連接，所有 Bot 都可以使用');
      } else if (form.id === 'connector-form') {
        const d = new FormData(form), transport = d.get('transport'), id = form.dataset.id, env = {};
        for (const line of (d.get('env') || '').split('\n').map(x => x.trim()).filter(Boolean)) {
          const at = line.indexOf('=');
          if (at < 1) { toast('環境變數每行要寫成 名稱=值'); return; }
          env[line.slice(0, at).trim()] = line.slice(at + 1).trim();
        }
        const secret = (transport === 'http' ? d.get('secretHttp') : d.get('secretStdio')).trim();
        const body = {name: d.get('name').trim(), transport, command: d.get('command').trim(), url: d.get('url').trim(), env: transport === 'http' ? {} : env, secretName: transport === 'http' ? '' : d.get('secretName').trim()};
        if (secret) body.secret = secret;
        if (d.has('clearSecret')) body.clearSecret = true;
        const more = {};
        for (const [k, v] of d.entries()) if (k.startsWith('more:') && String(v).trim()) more[k.slice(5)] = String(v).trim();
        if (Object.keys(more).length) body.moreSecrets = more;
        const made = await post(id ? 'connectors/' + encodeURIComponent(id) : 'connectors', body, id ? 'PATCH' : 'POST');
        closeModal(); delete state.mcpTests[made.id];
        state.integrations = await api('integrations'); await refresh();
        toast(id ? '已儲存' : '已新增，所有 Bot 都可以使用。按「測試連線」確認');
      } else if (form.id === 'profile-form') {
        const d = new FormData(form), type = d.get('accountType');
        if (type === 'key' && !d.get('key').trim()) { toast('請貼上 API 金鑰'); return; }
        await post('accounts/' + encodeURIComponent(form.dataset.id) + '/profiles', {name: d.get('name').trim(), type, key: type === 'key' ? d.get('key').trim() : ''});
        closeModal(); await reloadAccounts(); toast(type === 'key' ? '已新增，可以到 Bot 的設定選用' : '已新增，請按登入完成設定');
      } else if (form.id === 'account-code-form') {
        const code = new FormData(form).get('code').trim();
        if (!code) return;
        await post('accounts/' + encodeURIComponent(form.dataset.id) + '/login/code', {code, account: form.dataset.account || ''});
        toast('已送出授權碼');
        state.accounts = await api('accounts'); render(true); pollAccounts();
      } else if (form.id === 'group-form') {
        const d = new FormData(form), id = form.dataset.id;
        const result = await post(id ? 'groups/' + encodeURIComponent(id) : 'groups', {name: d.get('name').trim(), botIds: d.getAll('botIds')}, id ? 'PATCH' : 'POST');
        closeModal();
        state.groupId = result.id;
        state.page = 'chat';
        await refresh();
        toast(id ? '已儲存群組' : '已建立群組');
      } else if (form.id === 'section-form') {
        const name = new FormData(form).get('name').trim(), old = form.dataset.old, names = sectionNames();
        if (!name) return;
        if (name !== old && names.includes(name)) { toast('已經有同名的分組'); return; }
        const sections = old ? names.map(x => x === old ? name : x) : [...names, name];
        const bots = old ? state.data.bots.map(b => !b.pinned && (b.section || '我的 Bots') === old ? {...b, section: name} : b) : state.data.bots;
        closeModal(); await saveArrangement(bots, sections);
        toast(old ? '已重新命名分組' : '已新增分組，把 Bot 拖進去即可');
      } else if (form.id === 'edit-last-form') {
        const b = activeBot(), content = new FormData(form).get('content');
        if (!String(content).trim()) return;
        if (!redoAllowed(b)) return;
        closeModal(); await redo(b, {mode: 'edit', content});
      } else if (form.id === 'redo-model-form') {
        const b = activeBot(), provider = new FormData(form).get('provider');
        if (!redoAllowed(b)) return;
        closeModal(); await redo(b, {mode: 'again', provider});
      } else if (form.id === 'chat-rename-form') {
        const b = activeBot();
        await post(`bots/${encodeURIComponent(b.id)}/chats/${encodeURIComponent(form.dataset.id)}`, {title: new FormData(form).get('title')}, 'PATCH');
        await refresh(); chatsModal(activeBot()); toast('已改名');
      } else if (form.id === 'schedule-form') {
        const d = new FormData(form), id = form.dataset.id;
        const [kind, targetId] = String(d.get('target')).split(':');
        const repeat = d.get('repeat');
        const data = {[kind === 'group' ? 'groupId' : 'botId']: targetId, content: d.get('content'), repeat, time: (repeat === 'hourly' ? '00' : d.get('hour')) + ':' + d.get('minute'), on: d.get('on') === 'on', catchUp: d.get('catchUp') === 'on'};
        if (repeat === 'once') data.date = d.get('date');
        if (repeat === 'monthly') data.day = Number(d.get('day'));
        await post(id ? 'schedules/' + encodeURIComponent(id) : 'schedules', data, id ? 'PATCH' : 'POST');
        closeModal();
        await refresh();
        toast('已儲存排程');
      } else if (form.id === 'note-form') {
        let d = new FormData(form),
          id = form.dataset.id;
        let data = {
          title: d.get('title').trim(),
          content: d.get('content'),
          tags: d.get('tags').split(',').map(x => x.trim()).filter(Boolean),
          botId: d.get('botId') || ''
        };
        await post(id ? 'knowledge/' + encodeURIComponent(id) : 'knowledge', data, id ? 'PATCH' : 'POST');
        closeModal();
        await refresh();
        toast('已儲存知識')
      } else if (form.id === 'settings-form') {
        let d = new FormData(form);
        await post('settings', {
          provider: d.get('provider'),
          model: d.get('model')
        }, 'PATCH');
        await refresh();
        toast('已儲存設定')
      }
    } catch (err) {
      toast(err.message)
    }
  });
  document.addEventListener('keydown', e => {
    if (e.target.id === 'chat-input' && mention.items.length && !$('#mention-menu')?.hidden && !e.isComposing && e.keyCode !== 229) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        mention.index = (mention.index + (e.key === 'ArrowDown' ? 1 : -1) + mention.items.length) % mention.items.length;
        updateMentionMenu(); return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickMention(mention.index); return; }
      if (e.key === 'Escape') { e.preventDefault(); hideMentionMenu(); return; }
    }
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'n') {
      e.preventDefault();
      if (state.data.bots.length >= 2) groupModal(); else toast('至少需要 2 個 Bot 才能建立群組');
      return
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      $('#side-search')?.focus()
    }
    if (e.key === 'Escape' && state.modal) {
      closeModal();
      return
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229 && e.target.id === 'chat-input') {
      e.preventDefault();
      $('#chat-form').requestSubmit()
    }
    if (e.key === 'Tab' && state.modal) {
      let focusable = $$('.modal button,.modal input,.modal textarea,.modal select').filter(x => !x.disabled && x.offsetParent !== null);
      if (!focusable.length) return;
      let first = focusable[0],
        last = focusable.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus()
      }
    }
  });
  refresh().then(() => {
    startPollers();
    setInterval(syncFromElsewhere, 3000);
    setTimeout(refreshUpdate, 4000); setTimeout(refreshUpdate, 20000); setInterval(refreshUpdate, 3600 * 1000);
  }).catch(e => {
    app.innerHTML = `<div class="boot">無法開啟 Zook：${esc(e.message)}</div>`
  });
})();

