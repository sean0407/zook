  // A reply shown while it is being written. The words come over one long connection per running reply and only that
  // reply's bubble is repainted; the rest of the page is left alone.
  if (!state.partials) state.partials = {};
  const streams = {};
  const partialFor = m => m.status === 'running' ? (state.partials[m.id] || '') : '';
  const streamingOn = () => state.data?.settings?.streamReplies !== false;

  function paintPartial(messageId) {
    const bubble = document.querySelector(`.message[data-mid="${CSS.escape(messageId)}"] .bubble`), text = state.partials[messageId];
    if (!bubble || !text) return;
    const box = $('#conversation'), follow = !box || box.scrollHeight - box.scrollTop - box.clientHeight < 120;  // only follow while the reader is at the end
    bubble.className = 'bubble md streaming';
    bubble.innerHTML = markdown(text);
    if (follow && box) box.scrollTop = box.scrollHeight;
  }

  // The browser keeps only about six connections to Zook at once: streams for replies not on screen are closed and at most
  // STREAM_MOST are open, so a click (產出, 檔案, a message) is never queued behind them (#107/#161). The rest follow by polling.
  const STREAM_MOST = 3;
  const onScreen = job => !!job && (job.groupId ? job.groupId === state.groupId : !state.groupId && job.botId === state.selected);
  function pollPartial(j) {  // a reply that is not streamed: each poll brings its words so far
    if (j && j.status === 'running' && j.partial && j.messageId && !streams[j.id] && j.partial.length >= (state.partials[j.messageId] || '').length) { state.partials[j.messageId] = j.partial; paintPartial(j.messageId); }  // never back to older words
  }
  function streamJob(job) {
    if (!job || !job.id || !job.messageId || streams[job.id] || !streamingOn() || typeof EventSource === 'undefined') return;
    for (const id of Object.keys(streams)) if (!onScreen(state.jobDetails[id] || streams[id].job)) { streams[id].close(); delete streams[id]; }
    if (job.partial) { state.partials[job.messageId] = job.partial; paintPartial(job.messageId); }  // what a poll already brought
    if (!onScreen(job) || Object.keys(streams).length >= STREAM_MOST) return;  // the next poll brings its words
    const source = streams[job.id] = new EventSource('/api/jobs/' + encodeURIComponent(job.id) + '/stream'); source.job = job;
    const stop = () => { source.close(); delete streams[job.id]; };
    source.onmessage = e => {
      let d; try { d = JSON.parse(e.data); } catch (_) { return; }
      if (d.done) {  // the words stay on screen until the finished reply replaces them at the next refresh
        stop(); setTimeout(() => { delete state.partials[job.messageId]; }, 30000); return;
      }
      if (typeof d.text === 'string') state.partials[job.messageId] = d.text;
      else if (typeof d.add === 'string') state.partials[job.messageId] = (state.partials[job.messageId] || '') + d.add;
      if (!state.partials[job.messageId]) {  // another model took over: back to "thinking"
        const bubble = document.querySelector(`.message[data-mid="${CSS.escape(job.messageId)}"] .bubble`);
        if (bubble) { bubble.className = 'bubble'; bubble.textContent = '正在思考…'; }
        return;
      }
      paintPartial(job.messageId);
    };
    source.onerror = () => { if (source.readyState === EventSource.CLOSED) stop(); };  // otherwise the browser reconnects by itself
  }

  // Messages waiting for a busy Bot: shown after the conversation, each with a way to take it back.
  function queuedView(b) {
    const started = new Set([...(state.data.jobs || []), ...Object.values(state.jobDetails || {})].map(j => j.queueId).filter(Boolean));  // already being answered
    const waiting = (b.queue || []).filter(e => e.chatId === b.chatId && !started.has(e.id));
    return waiting.map(e => `<div class="message user queued" data-qid="${esc(e.id)}"><div class="bubble">${esc(e.content)}</div><div class="queued-note"><span>排在後面・Bot 回覆完就會送出</span><button class="link" data-queue-cancel="${esc(e.id)}">取消</button></div></div>`).join('');
  }
  document.addEventListener('click', async e => {
    const el = e.target.closest?.('[data-queue-cancel]');
    if (!el) return;
    el.disabled = true;
    try { await post('bots/' + encodeURIComponent(state.selected) + '/queue/' + encodeURIComponent(el.dataset.queueCancel), {}, 'DELETE'); toast('已取消'); }
    catch (err) { toast(err.message); }
    await refresh();
  });
