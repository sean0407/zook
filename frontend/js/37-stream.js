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

  function streamJob(job) {
    if (!job || !job.id || !job.messageId || streams[job.id] || !streamingOn() || typeof EventSource === 'undefined') return;
    if (job.partial) { state.partials[job.messageId] = job.partial; paintPartial(job.messageId); }  // what a poll already brought
    const source = streams[job.id] = new EventSource('/api/jobs/' + encodeURIComponent(job.id) + '/stream');
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
