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
    return `<aside class="sidebar"><div class="side-top"><div class="brand">Zook<span>✳</span></div><div class="side-actions"><button class="icon-btn" data-action="search-focus" aria-label="搜尋">${svg('search')}</button><button class="icon-btn" data-action="new-bot" aria-label="新增 Bot">${svg('plus')}</button></div></div><div class="search"><span class="glass tiny-icon">${svg('search')}</span><input id="side-search" placeholder="搜尋 Bot、對話和知識" aria-label="搜尋 Bot、對話和知識" value="${esc(state.query)}"></div><div class="side-scroll">${groupsBlock()}${pinned.length?block('已釘選',pinned,true):''}${sections.map(s=>block(s,bots.filter(b=>!b.pinned&&(b.section||'我的 Bots')===s))).join('')}${state.query?'':'<button class="side-empty add-section" data-action="new-section">＋ 新增分組</button>'}${messageHits().length?`<div class="section-head">對話搜尋結果</div>${messageHits().map(h=>`<button class="side-row" data-action="open-message" data-bot="${esc(h.b.id)}" data-id="${esc(h.messageId)}">${avatar(h.b)}<span class="side-copy"><span class="side-name">${esc(h.b.name)} · ${esc(h.chatTitle || (h.kind === 'schedule' ? '排程' : '新對話'))}</span><span class="side-preview">${esc(h.snippet)}</span></span></button>`).join('')}`:''}${state.query&&state.data.knowledge.filter(n=>matches(n.title)||matches(n.content)).length?`<div class="section-head">知識搜尋結果</div>${state.data.knowledge.filter(n=>matches(n.title)||matches(n.content)).map(n=>`<button class="side-row" data-action="edit-note" data-id="${esc(n.id)}"><span>▤</span><span class="side-copy"><span class="side-name">${esc(n.title)}</span><span class="side-preview">${esc(n.content)}</span></span></button>`).join('')}`:''}</div><div class="side-footer"><div class="user-avatar">S</div><div class="user-name">我的工作區</div><div class="launcher"><button class="icon-btn launcher-btn" data-action="launcher" aria-label="開啟功能選單" aria-expanded="${state.launcher}">${svg('grid')}</button>${state.launcher?`<div class="popup">${[['usage','◷','各模型使用量'],['schedules','◴','排程'],['knowledge','▤','知識庫'],['memory','◎','記憶'],['skills','✳','Skills 與連接器'],['activity','☰','活動紀錄'],['settings','⚙','設定']].map(x=>`<button class="nav-item" data-action="page" data-id="${x[0]}"><span>${x[1]}</span>${x[2]}</button>`).join('')}</div>`:''}</div><button class="icon-btn" data-action="page" data-id="settings" aria-label="設定">${svg('settings')}</button>${state.update?.available ? `<button class="icon-btn update-btn" data-action="update-open" aria-label="有新版 ${esc(state.update.latest)}，按這裡更新" title="有新版 ${esc(state.update.latest)}">${svg('download')}</button>` : ''}</div></aside>`
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
      case 'zook_feature': return `使用${a.feature || '特色功能'}`;
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
    const messages = convMessages(b);
    const running = Object.entries(state.pollers).find(([id, v]) => v.botId === b.id && (state.jobDetails[id]?.chatId || b.chatId) === b.chatId);
    return `<main class="main"><header class="main-header"><button class="bot-pill" data-action="edit-bot">${avatar(b)}${esc(b.name)} <span class="muted">⌄</span></button><div class="header-actions"><button class="text-btn chat-title-btn" data-action="chats" title="所有對話">☰ ${esc(chatName(b))}</button><button class="text-btn" data-action="new-chat">＋ 新對話</button><button class="text-btn" data-action="share">↑ 匯出對話</button>${!state.detailOpen?'<button class="text-btn" data-action="toggle-detail">顯示詳情</button>':''}</div></header>${guideCard()}<div class="conversation" id="conversation">${messages.length?`<div class="conversation-inner">${olderBar(b)}${messages.map(m=>`<div class="date">${esc(formatDate(m.createdAt))}</div><div class="message ${m.role==='user'?'user':'assistant'}" data-mid="${esc(m.id)}">${m.role==='user'?'':avatar(b)}${partialFor(m)?`<div class="bubble md streaming">${markdown(partialFor(m))}</div>`:m.role!=='user'&&m.content&&m.status!=='running'?`<div class="bubble md ${m.status==='failed'?'error-text':''}">${withAutoMark(linkOutputs(markdown(m.content), b.id), m)}${noteLine(m)}</div>`:`<div class="bubble ${m.status==='failed'?'error-text':''}">${esc(m.status==='running'?'正在思考…':m.status==='cancelled'&&!m.content?'已停止回覆':m.status==='failed'&&!m.content?(Object.values(state.jobDetails).find(j => j.messageId === m.id)?.error || '回覆失敗，請檢查這個 Bot 的提供者設定。'):m.content)}</div>`}${attachmentsView(m)}${redoBar(b, m, running)}</div>`).join('')}${queuedView(b)}</div>`:`<div class="empty-chat">${avatar(b,'hero')}<h1>今天想一起完成什麼？</h1><p>和 ${esc(b.name)} 開始一段對話。</p><div class="quick-actions"><button data-action="page" data-id="knowledge">▤ 管理知識庫</button><button data-action="page" data-id="usage">◷ 查看使用量</button><button data-action="page" data-id="settings">⚙ 設定模型</button></div></div>`}</div><div class="composer-wrap">${approvalCards(b.id)}<form class="composer" id="chat-form">${pendingFiles()}<button type="button" class="icon-btn" data-action="composer-menu" aria-label="更多選項">${svg('plus')}</button><textarea id="chat-input" rows="1" placeholder="傳送訊息給 ${esc(b.name)}" aria-label="輸入訊息"></textarea>${longControl(b)}${planControl(b)}${effortControl()}<button type="button" class="icon-btn" data-action="voice" aria-label="語音輸入">${svg('mic')}</button>${running?`<button type="button" class="send" data-action="cancel-job" data-id="${esc(running[0])}" aria-label="停止回覆">■</button>${state.data.settings.queueWhenBusy !== false ? '<button class="send" type="submit" aria-label="排在後面傳送" title="Bot 還在回覆，這則會排在後面">↑</button>' : ''}`:`<button class="send" type="submit" aria-label="傳送訊息">↑</button>`}</form></div></main>${state.detailOpen?detail(b):''}`
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
    if (m.checkOf) return '';
    if (m.role === 'system') return `<div class="system-note">${esc(m.content)}</div>`;
    const tag = html => highlightMentions(html, groupMembers(g));
    if (m.role === 'user') return `<div class="date">${esc(formatDate(m.createdAt))}</div><div class="message user" data-mid="${esc(m.id)}">${m.author ? `<div class="speaker-wrap user-author"><div class="speaker">由 ${esc(m.author)} 發起</div><div class="bubble">${tag(esc(m.content))}</div></div>` : `<div class="bubble">${tag(esc(m.content))}</div>`}${attachmentsView(m)}</div>`;
    const b = state.data.bots.find(x => x.id === m.botId) || {name: '已刪除的 Bot', color: '#959595'};
    const text = m.status==='running' ? '正在思考…' : m.status==='cancelled'&&!m.content ? '已停止回覆' : m.status==='failed'&&!m.content ? (Object.values(state.jobDetails).find(j => j.messageId === m.id)?.error || '回覆失敗，請檢查這個 Bot 的提供者設定。') : m.content;
    return `<div class="message assistant" data-mid="${esc(m.id)}">${avatar(b)}<div class="speaker-wrap"><div class="speaker">${esc(b.name)}</div>${m.card&&m.status==='completed'?groupCardView(m):partialFor(m)?`<div class="bubble md streaming">${tag(markdown(partialFor(m)))}</div>`:m.content&&m.status!=='running'?`<div class="bubble md">${withAutoMark(tag(markdown(m.content)), m)}${noteLine(m)}</div>`:`<div class="bubble ${m.status==='failed'?'error-text':''}">${esc(text)}</div>`}${groupChecks(g, m)}</div>${groupVerifyButton(g, m)}</div>`;
  }
  function groupChat() {
    const g = activeGroup(), members = groupMembers(g), running = g.status === 'running';
    const messages = g.messages || [];
    return `<main class="main"><header class="main-header"><button class="bot-pill" data-action="edit-group">${avatarStack(g)}${esc(g.name)} <span class="muted">⌄</span></button><div class="header-actions"><button class="text-btn" data-action="share">↑ 匯出對話</button>${!state.detailOpen?'<button class="text-btn" data-action="toggle-detail">顯示詳情</button>':''}</div></header>${guideCard()}<div class="conversation" id="conversation">${messages.length?`<div class="conversation-inner">${messages.map(m => groupMessage(g, m)).join('')}</div>`:`<div class="empty-chat">${avatarStack(g,'hero')}<h1>${esc(g.name)}</h1><p>直接發訊息，或用 @ 指定成員。</p></div>`}</div><div class="composer-wrap">${approvalCards(null, jobsForGroup(g.id))}${groupRunBar(g)}<div class="mention-row" aria-label="指名 Bot">${members.map(b => `<button type="button" class="mention-chip" data-action="mention" data-id="${esc(b.name)}">${avatar(b)}@${esc(b.name)}</button>`).join('')}<button type="button" class="mention-chip" data-action="mention" data-id="所有人">@所有人</button></div><div id="mention-menu" class="mention-menu" role="listbox" aria-label="選擇要指名的 Bot" hidden></div><form class="composer" id="chat-form">${pendingFiles()}<button type="button" class="icon-btn" data-action="composer-menu" aria-label="更多選項">${svg('plus')}</button><div class="input-wrap"><div class="input-mirror" aria-hidden="true"></div><textarea id="chat-input" rows="1" placeholder="傳送訊息給群組，用 @ 指定 Bot" aria-label="輸入訊息"></textarea></div>${groupModeControl(g)}${effortControl()}<button type="button" class="icon-btn" data-action="voice" aria-label="語音輸入">${svg('mic')}</button>${running?`<button type="button" class="send" data-action="stop-group" data-id="${esc(g.id)}" aria-label="停止討論">■</button>`:`<button class="send" type="submit" aria-label="傳送訊息">↑</button>`}</form>${groupEstimateLine(g)}</div></main>${state.detailOpen?groupDetail(g):''}`;
  }
  function groupDetail(g) {
    const members = groupMembers(g), running = g.status === 'running';
    const activeIds = g.activeJobIds?.length ? g.activeJobIds : g.activeJobId ? [g.activeJobId] : [];
    const activeNames = running ? activeIds.map(id => state.data.bots.find(b => b.id === state.jobDetails[id]?.botId)?.name).filter(Boolean) : [];
    const active = activeNames.length ? {name: activeNames.join('、')} : null;
    return `<aside class="detail"><button class="detail-close icon-btn" data-action="toggle-detail" aria-label="關閉詳情">×</button><div class="detail-profile">${avatarStack(g,'big')}<h2>${esc(g.name)}</h2><p>${members.length} 位成員${running ? ' · 討論中' + (active ? '（' + esc(active.name) + ' 發言中）' : '') : ''}</p><button class="secondary detail-edit" data-action="edit-group">編輯群組</button></div><div class="tabs"><button data-action="group-tab" data-id="members" class="${state.groupTab==='files'?'':'active'}">成員</button><button data-action="group-tab" data-id="files" class="${state.groupTab==='files'?'active':''}">檔案</button></div>${state.groupTab==='files'?groupFilesTab(g):`${members.map(b => `<button class="member-row" data-action="select-bot" data-id="${esc(b.id)}">${avatar(b)}<span><strong>${esc(b.name)}</strong><small>${esc([(b.provider||state.data.settings.provider||'') + (b.model ? ' ' + b.model : ''), '主動性：' + permissionName(b.permissionMode || state.data.settings.permissionMode)].filter(Boolean).join(' · '))}</small></span></button>`).join('')}<div class="detail-empty">點成員可以查看他在討論中查了什麼、用了哪些 Skill。</div>`}</aside>`;
  }
  function groupModal(g = {}) {
    const editing = !!g.id, chosen = new Set(g.botIds || (state.selected && !state.groupId ? [state.selected] : []));
    modal(editing ? '編輯群組' : '新增群組', `<form id="group-form"><div class="modal-body"><label class="field">名稱<input name="name" maxlength="100" placeholder="留空則以成員名稱命名" value="${esc(g.name||'')}"></label><label class="field">成員（2–10 個 Bot，人越多每輪越慢）</label><div class="member-pick">${state.data.bots.map(b => `<label class="member-switch">${avatar(b)}<span class="member-copy"><strong>${esc(b.name)}</strong><small>${esc((b.persona||b.instructions||'').slice(0,50))}</small></span>${toggle(`name="botIds" value="${esc(b.id)}"`, chosen.has(b.id), b.name)}</label>`).join('') || '<p class="muted">請先建立 Bot。</p>'}</div>${groupSettingRows(g, chosen)}</div><div class="modal-foot">${editing?'<button type="button" class="link" data-action="delete-group" style="margin-right:auto;color:#b55">刪除群組</button>':''}<button type="button" class="secondary" data-action="close-modal">取消</button><button class="primary">${editing?'儲存':'建立群組'}</button></div></form>`);
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
        for (const j of data.jobs || []) {
          if (j.status === 'running') streamJob(j);
          const { partial, ...rest } = j;  // the words in progress are painted by the stream, not by redrawing the page
          if (JSON.stringify(state.jobDetails[j.id]) !== JSON.stringify(rest)) changed = true; state.jobDetails[j.id] = rest;
        }
        if (changed) render(true);
        if (data.group.status !== 'running') { if (state.groupTab === 'files') delete state.groupFiles[groupId]; if (state.groupId === groupId) render(true); break; }
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
    return `<p class="muted model-intro">登入由各家官方 CLI 完成，Zook 不讀取帳密。</p><div class="quota-grid model-grid">${list.map(p => {
      const [cls, label] = p.issue ? ['warn', '無法使用'] : badge[p.status] || badge.unknown, l = p.login, running = l?.state === 'running' || p.install?.state === 'running';
      const detail = [p.method, p.plan && p.plan.toUpperCase(), p.workspace, p.email].filter(Boolean).map(esc).join(' · ');
      const sub = detail || (p.installed ? (p.custom ? esc(p.config?.command || '') : '已安裝') : (p.requires && !p.requirementMet ? `需要先安裝 ${esc(p.requires === 'npm' ? 'Node.js（npm）' : p.requires)}` : '尚未安裝這個 CLI'));
      const loginButtons = p.installed && p.loginMethods.length ? p.loginMethods.map((m, i) => `<button class="${i === 0 && p.status !== 'logged_in' ? 'primary' : 'secondary'}" data-action="account-login" data-id="${esc(p.id)}" data-method="${esc(m.id)}">${p.status === 'logged_in' && i === 0 ? '重新登入' : esc(m.label)}</button>`).join('') : '';
      const v = p.version, upToDate = v && v.current && v.latest && !v.updateAvailable;
      const versionLine = !p.installed ? '' : `<div class="version-line">${v?.current ? `<span>版本 ${esc(v.current)}</span>` : '<span>版本未知</span>'}${v?.updateAvailable ? `<span class="pill warn">有新版 ${esc(v.latest)}</span>` : upToDate ? '<span class="pill ok">已是最新版</span>' : v?.error ? `<span class="muted">${esc(v.error)}</span>` : ''}</div>`;
      const installLabel = !p.installed ? '一鍵安裝' : v?.updateAvailable ? `更新到 ${esc(v.latest)}` : p.canUpdate ? '檢查並更新' : '重新安裝';
      const installBtn = p.canInstall && (!p.requires || p.requirementMet || p.installed) && !(upToDate && p.installed) ? `<button class="${!p.installed || v?.updateAvailable ? 'primary' : 'secondary'}" data-action="provider-install" data-id="${esc(p.id)}" data-command="${esc(p.installed && p.canUpdate ? '' : p.installCommand)}">${installLabel}</button>` : '';
      const notes = [!p.tools ? '這個 CLI 只能純對話，不能使用 Zook 的工具。' : '', p.installed && !p.loginMethods.length && p.loginNote ? p.loginNote : ''].filter(Boolean);
      const shortName = p.name.split('（')[0], parts = p.installed ? usageParts(quotaFor(p.id)) : {body: '<p class="quota-empty">安裝後就能登入和查看用量。</p>', zook: '<div class="zook-usage empty"></div>', when: ''};
      const chips = [p.plan && p.plan.toUpperCase(), p.workspace, p.method !== sub ? p.method : ''].filter(Boolean);
      const addAccount = p.installed && (p.canAddLogin || p.canAddKey) ? `<button class="secondary" data-action="profile-add" data-id="${esc(p.id)}">＋ 新增帳號</button>` : '';
      const terminal = p.installed && p.terminalLogin ? `<button class="${p.status === 'logged_in' ? 'secondary' : 'primary'}" data-action="terminal-login" data-id="${esc(p.id)}">${p.status === 'logged_in' ? '重新登入' : '用 Google 帳號登入'}</button>` : '';
      const manage = `${p.custom ? `<button class="secondary" data-action="provider-edit" data-id="${esc(p.id)}">編輯設定</button>` : ''}${p.status === 'logged_in' && p.canLogout ? `<button class="link danger" data-action="account-logout" data-id="${esc(p.id)}">登出</button>` : ''}${p.removable ? `<button class="link danger" data-action="provider-remove" data-id="${esc(p.id)}">從 Zook 移除</button>` : ''}`;
      const abilityLine = (p.abilities || []).length ? `<div class="ability-chips">${p.abilities.map(a => `<span class="${a.state === 'broken' ? 'off' : ''}" title="${a.state === 'broken' ? '這個版本暫時無法使用' : '可以使用'}">${a.state === 'broken' ? '✕' : '✓'} ${esc(a.name)}</span>`).join('')}</div>` : '';
      const ownerName = (p.profiles || []).length ? '預設帳號' : p.vendor;
      const main = `<article class="quota-card model-card"><header class="quota-head"><div class="quota-title"><h3>${esc(shortName)}${p.custom ? ' <span class="pill">自訂</span>' : ''}</h3>${ownerName ? `<span>${esc(ownerName)}</span>` : ''}</div><span class="pill ${cls}">${label}</span></header><div class="quota-account"><div class="quota-email" title="${esc(p.email || '')}">${p.email ? esc(p.email) : sub}</div>${chips.length ? `<div class="quota-chips">${chips.map(c => `<span>${esc(c)}</span>`).join('')}</div>` : ''}${versionLine}${abilityLine}${quotaFor(p.id)?.autoOn !== undefined ? `<label class="auto-pick"><span>${quotaFor(p.id).autoBilled ? 'API 計費不會被自動選用' : '可被自動選用'}</span>${toggle(`data-auto-model="${esc(p.id)}" ${quotaFor(p.id).autoBilled ? 'disabled' : ''}`, quotaFor(p.id).autoOn, '可被自動選用')}</label>` : ''}</div><div class="quota-body">${(p.changed || []).length ? `<p class="error-text small">這個版本有變動，暫時關閉：${esc(p.changed.join('、'))}。其他功能照常。</p>` : ''}${p.issue ? `<p class="error-text small">${esc(p.issue)}</p>` : ''}${notes.map(n => `<p class="muted small">${esc(n)}</p>`).join('')}${parts.body}${flowView(p.install, 'install', p.id)}${flowView(l, 'login', p.id)}</div>${parts.zook}<footer class="quota-foot model-foot"><small>${esc(parts.when)}</small>${!running ? `<div class="card-actions">${terminal}${loginButtons}${installBtn}${addAccount}</div>${manage ? `<div class="card-manage">${manage}</div>` : ''}` : ''}</footer></article>`;
      const extras = (p.profiles || []).map(a => {
        const [acls, alabel] = badge[a.status] || badge.unknown, busy = a.login?.state === 'running', q = quotaFor(p.id, a.id), use = usageParts(q);
        const achips = [a.plan && a.plan.toUpperCase(), a.workspace, a.type === 'key' ? 'API 金鑰' : a.method].filter(Boolean);
        const who = a.email || (a.type === 'key' ? 'API 金鑰' : a.status === 'logged_in' ? '已登入' : '尚未登入');
        const buttons = a.type === 'login' && !busy ? p.loginMethods.map((m, i) => `<button class="${i === 0 && a.status !== 'logged_in' ? 'primary' : 'secondary'}" data-action="account-login" data-id="${esc(p.id)}" data-account="${esc(a.id)}" data-method="${esc(m.id)}">${a.status === 'logged_in' && i === 0 ? '重新登入' : esc(m.label)}</button>`).join('') : '';
        return `<article class="quota-card model-card"><header class="quota-head"><div class="quota-title"><h3>${esc(shortName)}</h3><span>${esc(a.name)}</span></div><span class="pill ${acls}">${alabel}</span></header><div class="quota-account"><div class="quota-email" title="${esc(a.email || '')}">${esc(who)}</div>${achips.length ? `<div class="quota-chips">${achips.map(c => `<span>${esc(c)}</span>`).join('')}</div>` : ''}${versionLine}${abilityLine}${quotaFor(p.id)?.autoOn !== undefined ? '<div class="auto-pick"><span>自動選擇只使用預設帳號</span></div>' : ''}</div><div class="quota-body">${use.body}${flowView(a.login, 'login', p.id, a.id)}</div>${use.zook}<footer class="quota-foot model-foot"><small>${esc(use.when)}</small>${!busy ? `${buttons || addAccount ? `<div class="card-actions">${buttons}${addAccount}</div>` : ''}<div class="card-manage"><button class="link danger" data-action="profile-delete" data-id="${esc(p.id)}" data-account="${esc(a.id)}" data-name="${esc(a.name)}">移除帳號</button></div>` : ''}</footer></article>`;
      }).join('');
      return main + extras;
    }).join('')}</div>`;
  }
  function providerAddModal() {
    const catalog = state.accounts?.catalog || [];
    modal('新增模型', `<div class="modal-body"><p class="muted">已安裝的直接加入，沒安裝的可一鍵安裝。</p>${catalog.length ? `<div class="catalog-list">${catalog.map(c => `<div class="catalog-item"><div><strong>${esc(c.name)}</strong><small>${c.installed ? '已安裝在這台電腦' : c.requires && !c.requirementMet ? `需要先安裝 ${esc(c.requires === 'npm' ? 'Node.js（npm）' : c.requires)}` : '尚未安裝，可一鍵安裝'} · 使用 ${esc(c.vendor)} 官方安裝程式</small></div><button class="secondary" data-action="provider-add-one" data-id="${esc(c.id)}">加入</button></div>`).join('')}</div>` : '<p class="muted">內建的模型都已經加入了。</p>'}<h3 class="modal-sub">不在清單裡？</h3><p class="muted">其他命令列工具可以手動加入。</p><button class="secondary" data-action="provider-custom">＋ 手動新增</button></div>`);
  }
  function profileModal(p) {
    const types = [p.canAddLogin && {id: 'login', name: '登入帳號', hint: '用另一個帳號在瀏覽器登入'}, p.canAddKey && {id: 'key', name: 'API 金鑰', hint: '依用量計費，金鑰存在這台 Mac 的鑰匙圈'}].filter(Boolean);
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
  const providerOptions = (selected, withDefault, withAuto) => (withDefault ? `<option value="" ${!selected ? 'selected' : ''}>使用預設</option>` : '') + (withAuto ? `<option value="auto" ${selected === 'auto' ? 'selected' : ''}>自動選擇</option>` : '') + (state.providers || [{id: 'codex', name: 'Codex'}, {id: 'claude', name: 'Claude'}]).map(p => `<option value="${esc(p.id)}" ${selected === p.id ? 'selected' : ''}>${esc(p.name)}${p.installed === false ? '（未安裝）' : ''}</option>`).join('');

