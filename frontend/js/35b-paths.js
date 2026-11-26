  // #57① #83① #327 #310③ #320: a reply shows a file's name, not where Zook or the Bot keeps it (the group's folder, /private/tmp,
  // the Mac's temporary folders, .zook-scratch, Zook's own data). The name stays a button that opens the preview; a group's file
  // says 「（群組檔案）」. A place the user named in the conversation stays as written. Only what is shown changes, never the saved words.
  const INNER_WORD = /(?:file:\/\/)?\/(?:[^\s`'"<>()（）「」『』，、。：；！？*|[\]]| (?=Support\/))+/g;
  const INNER_SKIP = /\[([^[\]]+)\]\((\s*<[^<>\n]*>[^()\n]*|(?:[^()\n]|\([^()\n]*\))*)\)|`[^`\n]+`/g;  // a Markdown link (as MD_LINK) or a code span
  const placeOf = p => String(p).replace(/^file:\/\//i, '').replace(/\/+$/, '').replace(/^\/private(?=\/(tmp|var)(\/|$))/, '');
  function innerKind(path) {
    const p = path.replace(/^file:\/\//i, '');
    if (/\/group-files(\/|$)/.test(p)) return 'group';
    if (/^\/(private\/)?(tmp|var\/folders)\/./.test(p) || /\/\.zook-scratch(\/|$)/.test(p) || /\/Application Support\/swarmr[^/]*\//.test(p) || /\/workspaces\/[0-9a-f]{32}\//.test(p)) return 'scratch';
    return '';
  }
  // The places the user named in a conversation's messages, worked out once per list (and again when it grows).
  const saidPlaces = new WeakMap();
  function userPlaces(list) {
    if (!Array.isArray(list)) return [];
    const kept = saidPlaces.get(list);
    if (kept && kept.n === list.length) return kept.own;
    const own = [];
    for (const m of list) if (m && m.role === 'user') for (const w of String(m.content || '').match(INNER_WORD) || []) own.push(placeOf(w.replace(/[.,;:!?]+$/, '')));
    saidPlaces.set(list, {n: list.length, own});
    return own;
  }
  function hidePrivatePaths(text, messages) {
    const own = userPlaces(messages);
    const mine = p => { const at = placeOf(p); return own.some(u => u && (at === u || at.startsWith(u + '/'))); };
    // how: 'link' (a button with the name), 'name' (inside code or a link's words: just the name)
    const swap = (chunk, how) => chunk.replace(INNER_WORD, (word, at, all) => {
      if (at && /[\w:/.~-]/.test(all[at - 1])) return word;  // part of a web address or a longer word
      const tail = (word.match(/[.,;:!?]+$/) || [''])[0], path = word.slice(0, word.length - tail.length), kind = innerKind(path);
      if (!kind || mine(path)) return word;
      const folder = /\/$/.test(path) || /\/group-files(\/[^/]+)?$/.test(path) || /\/\.zook-scratch$/.test(path);  // a file may have no extension (LICENSE)
      if (folder) return (kind === 'group' ? '群組檔案' : '暫存資料夾') + tail;
      let name = path.split('/').pop(); try { name = decodeURIComponent(name); } catch (_) {}
      if (how === 'name') return name + tail;
      return `[${name.replace(/[[\]]/g, '')}](<${path.replace(/^file:\/\//i, '')}>)` + (kind === 'group' ? '（群組檔案）' : '') + tail;
    });
    const plain = chunk => {
      let out = '', last = 0;
      chunk.replace(INNER_SKIP, (whole, label, target, at) => {
        out += swap(chunk.slice(last, at), 'link'); last = at + whole.length;
        if (label !== undefined) out += '[' + swap(label, 'name') + '](' + target + ')';
        else { const inner = whole.slice(1, -1).trim(); out += innerKind(inner) && !mine(inner) && (inner.match(INNER_WORD) || [])[0] === inner ? swap(inner, 'link') : swap(whole, 'name'); }
        return whole;
      });
      return out + swap(chunk.slice(last), 'link');
    };
    let shown = String(text ?? '').split(/(^```[^\n]*\n[\s\S]*?(?:\n```|(?![\s\S])))/m).map((part, i) => i % 2 ? swap(part, 'name') : plain(part)).join('');
    shown = shown.replace(/(群組檔案\s*[：:「]\s*\[[^\]\n]+\]\(<[^>\n]*>\))（群組檔案）/g, '$1')  // 「群組檔案：X」 says it once
      .replace(/([^\s（(\[\]]{1,200}?)\s*[（(]\[\1\]\((<[^>\n]*>)\)((?:（群組檔案）)?)[)）]/g, '[$1]($2)$3');  // 「報告.pdf（/tmp/…/報告.pdf）」 names it once
    if ((shown.match(/\*\*/g) || []).length % 2) shown = shown.replace(/\s*\*\*\s*$/, '');  // a bold mark left open at the end (#327)
    return shown;
  }
