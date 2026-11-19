# Choices the user answers with one click: options a Bot lists at the end of a reply, and a question it asks in the middle of its work.
# Loaded by backend/server.py into one shared namespace.
CHOICE_MARK = '【選項】'
CHOICE_NOTE = ('\n選項：需要使用者在幾個做法之間選一個時，在回覆的最後另起一行寫「' + CHOICE_MARK + '」，接著每行一個選項，以「- 」開頭，2 到 4 個，每個不超過 30 字。'
               '畫面會把它們變成按鈕，使用者點了就等於回覆那個選項。不需要使用者選擇時不要加。')
ASK_NOTE = '\n工作做到一半、需要使用者決定才能繼續時，用 zook_ask_user 提問並附上選項，等他回答後再繼續。回答只是回答，不代表核准任何動作。'
_CHOICE_BLOCK = re.compile(r'\n?[ \t]*' + CHOICE_MARK + r'[ \t]*\n((?:[ \t]*[-*•・][ \t]*\S[^\n]*(?:\n|$)){2,4})\s*$')
MAX_CHOICE = 60
MAX_QUESTIONS = 8  # in one reply


def choices_on(store):
    return store.data['settings'].get('choiceButtons') is not False


def choices_for(store, job):
    """Buttons are only for a turn the user is watching, in a Bot's own conversation."""
    return choices_on(store) and not job.get('groupId') and not job.get('origin') and not job.get('internal')


def split_choices(content):
    """(the reply without its option block, the options). A block that is not exactly as asked is left in the text."""
    match = _CHOICE_BLOCK.search(content or '')
    if not match: return content, None
    options = [re.sub(r'^[ \t]*[-*•・][ \t]*', '', line).strip() for line in match.group(1).splitlines() if line.strip()]
    options = list(dict.fromkeys(options))
    if not 2 <= len(options) <= 4 or any(len(o) > MAX_CHOICE for o in options): return content, None
    rest = content[:match.start()].rstrip()
    return (rest, options) if rest else (content, None)


def hide_choice_block(text):
    """While a reply is still being written, the half-written option block is not shown."""
    at = (text or '').rfind(CHOICE_MARK)
    return text if at < 0 or not re.fullmatch(r'[ \t]*(?:\n[ \t]*[-*•・]?[^\n]*){0,4}\s*', text[at + len(CHOICE_MARK):]) else text[:at].rstrip()


def question_tools(app, job_id, runtime, origin='user'):
    """zook_ask_user: the Bot stops, the window shows the question with its options, and the answer goes back to the Bot.
    An answer is only an answer. Whatever the Bot does next is checked and approved exactly as before."""
    store = app.store
    if not choices_on(store): return []
    events = app.__dict__.setdefault('question_events', {})
    def ask(args):
        if origin != 'user': raise RuntimeError('這個回合是由%s啟動的，現在沒有人可以回答。請自己做合理的判斷並在回覆裡說明，或把問題留在回覆裡等使用者看到。' % ORIGIN_NAMES.get(origin, '其他來源'))
        text = args['question'].strip(); options = [str(o).strip() for o in args.get('options') or []]
        if not text or len(text) > 500: raise RuntimeError('問題需為 1–500 字。')
        if options and (not 2 <= len(options) <= 4 or any(not o or len(o) > MAX_CHOICE for o in options) or len(set(options)) != len(options)): raise RuntimeError('選項要 2 到 4 個、不重複，每個不超過 %d 字；也可以不給選項，讓使用者自己打字。' % MAX_CHOICE)
        event = threading.Event(); question = dict(id=ID(), question=text, options=options, status='pending', createdAt=NOW())
        with store.lock:
            job = store.find('jobs', job_id)
            if not job or job['status'] != 'running': raise RuntimeError('這個回覆已經結束。')
            if job.get('groupId'): raise RuntimeError('群組討論裡不能用這個工具，請把問題寫在回覆裡。')
            asked = job.setdefault('questions', [])
            if any(q['status'] == 'pending' for q in asked): raise RuntimeError('上一個問題還沒有回答。')
            if len(asked) >= MAX_QUESTIONS: raise RuntimeError('這次回覆已經問了 %d 個問題，請把其餘的問題寫在回覆裡。' % MAX_QUESTIONS)
            asked.append(question); events[question['id']] = event; store.save()
        event.wait(APPROVAL_TIMEOUT)
        with store.lock:
            events.pop(question['id'], None)
            if question['status'] == 'pending': question['status'] = 'expired'; store.save()
            if question['status'] != 'answered': raise RuntimeError('使用者沒有回答這個問題。不要自己替他選；把問題留在回覆裡，並停在這一步。')
            return {'answer': question['answer'], 'note': '這是使用者對問題的回答，不是對任何動作的核准。'}
    schema = runtime._schema('zook_ask_user', 'Ask the user one question in the middle of your work and wait for the answer. Give 2-4 short options when you can; the user may also type their own answer. '
                             'The answer is not an approval of any action.',
                             {'question': {'type': 'string', 'description': 'The question, in Traditional Chinese, one or two sentences'},
                              'options': {'type': 'array', 'items': {'type': 'string'}, 'description': '2-4 short options, optional'}}, ['question'])
    return [(schema, ask, False)]


def expire_questions(app, job):
    """Lock held. The reply ended or was stopped: nothing is waiting for an answer any more."""
    for question in job.get('questions') or []:
        if question['status'] == 'pending':
            question['status'] = 'expired'
            event = app.__dict__.get('question_events', {}).get(question['id'])
            if event: event.set()


def answer_question(app, question_id, body, by=''):
    """Lock held. Returns (status, payload)."""
    store = app.store; answer = body.get('answer')
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 2000: return 400, '回答需為 1–2000 字。'
    for job in store.data['jobs']:
        question = next((q for q in job.get('questions') or [] if q['id'] == question_id), None)
        if not question: continue
        if job['status'] != 'running' or question['status'] != 'pending': return 409, '這個問題已經結束。'
        question.update(status='answered', answer=answer.strip(), answeredAt=NOW()); store.save()
        log_activity(store, 'approval', '回答提問「%s」：%s（%s）' % (question['question'][:60], answer.strip()[:80], app.target_name('bot', job['botId'])), by=by)
        event = app.__dict__.get('question_events', {}).get(question_id)
        if event: event.set()
        return 200, question
    return 404, '找不到這個問題。'
