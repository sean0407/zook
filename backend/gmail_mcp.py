#!/usr/bin/env python3
"""Zook's built-in Gmail connector.

A small MCP server (stdio) that reaches Gmail the way a mail app does: IMAP to search and read, and to save
drafts; SMTP to send. It signs in with the address and a Google app password that Zook hands over in the
environment (the password itself lives in the macOS Keychain). Nothing here stores mail or credentials.
"""
import email
import email.policy
import html
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid

ADDRESS = os.environ.get('ZOOK_GMAIL_ADDRESS', '').strip()
PASSWORD = os.environ.get('ZOOK_GMAIL_PASSWORD', '').replace(' ', '')
IMAP_HOST, SMTP_HOST = 'imap.gmail.com', 'smtp.gmail.com'
MAX_BODY = 20000          # characters of a message body handed to the Bot
MAX_FETCH = 3000000       # bytes of one message read from Gmail
ADDRESS_RE = re.compile(r'[^@\s<>,;"]+@[^@\s<>,;"]+\.[^@\s<>,;"]+')


class GmailError(Exception):
    pass


def connect():
    if not ADDRESS or not PASSWORD: raise GmailError('Gmail 尚未設定。請到 Zook 的連接器頁設定 Gmail。')
    try:
        box = imaplib.IMAP4_SSL(IMAP_HOST, 993, ssl_context=ssl.create_default_context(), timeout=30)
        box.login(ADDRESS, PASSWORD)
        return box
    except imaplib.IMAP4.error:
        raise GmailError('Gmail 登入失敗。請確認信箱和應用程式密碼正確，而且帳號已開啟兩步驟驗證與 IMAP。')
    except (OSError, ssl.SSLError):
        raise GmailError('連不上 Gmail，請確認網路連線。')


def special_folder(box, flag):
    """Gmail's own name for a special mailbox (it differs by language), found by its role: \\All, \\Drafts."""
    status, lines = box.list()
    for line in lines or []:
        text = line.decode('utf-8', 'replace') if isinstance(line, bytes) else str(line)
        match = re.match(r'\((?P<flags>[^)]*)\)\s+"[^"]*"\s+(?P<name>.+)$', text)
        if match and flag.lower() in match.group('flags').lower().split():
            return match.group('name').strip()
    raise GmailError('找不到 Gmail 的信件匣，請確認 Gmail 設定裡已啟用 IMAP，且「所有郵件」和「草稿」有勾選在 IMAP 中顯示。')


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def addresses(value, field):
    """A list of plain addresses from a string or list; refuses anything that is not an address."""
    items = value if isinstance(value, list) else re.split(r'[,;\n]', value) if isinstance(value, str) else []
    out = []
    for name, addr in getaddresses([str(x) for x in items if str(x).strip()]):
        if not ADDRESS_RE.fullmatch(addr): raise GmailError('%s 裡的「%s」不是有效的電子郵件地址。' % (field, addr or name))
        out.append(addr)
    return out


def body_text(message):
    part = message.get_body(preferencelist=('plain', 'html'))
    if part is None: return ''
    try: text = part.get_content()
    except (LookupError, UnicodeError, ValueError): text = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
    if part.get_content_type() == 'text/html':
        text = re.sub(r'(?is)<(script|style)\b.*?</\1>', '', text)
        text = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</li>', '\n', text)
        text = html.unescape(re.sub(r'<[^>]+>', '', text))
    return re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]+', ' ', text)).strip()


def summary(meta, header_bytes):
    message = email.message_from_bytes(header_bytes, policy=email.policy.default)
    found = lambda pattern: (re.search(pattern, meta) or [None, ''])[1]
    return {'id': found(r'X-GM-MSGID (\d+)'), 'thread_id': found(r'X-GM-THRID (\d+)'), 'from': clean(message['From']), 'to': clean(message['To']),
            'subject': clean(message['Subject']), 'date': clean(message['Date']), 'unread': '\\Seen' not in found(r'FLAGS \(([^)]*)\)')}


def uid_of(box, message_id):
    if not re.fullmatch(r'\d{1,25}', str(message_id or '')): raise GmailError('message_id 無效；請使用搜尋結果裡的 id。')
    box.select(special_folder(box, '\\All'), readonly=True)
    status, data = box.uid('SEARCH', 'X-GM-MSGID', str(message_id))
    uids = (data[0] or b'').split() if status == 'OK' and data else []
    if not uids: raise GmailError('找不到這封信，可能已被刪除。')
    return uids[0].decode()


def search_emails(args):
    query = clean(args.get('query')) or 'in:inbox'
    limit = max(1, min(int(args.get('max_results') or 10), 30))
    box = connect()
    try:
        box.select(special_folder(box, '\\All'), readonly=True)
        box.literal = query.encode('utf-8')  # sent as a literal so any language and punctuation is safe
        status, data = box.uid('SEARCH', 'CHARSET', 'UTF-8', 'X-GM-RAW')
        if status != 'OK': raise GmailError('Gmail 無法執行這個搜尋，請調整搜尋條件。')
        uids = [u.decode() for u in (data[0] or b'').split()][-limit:][::-1]  # newest first
        if not uids: return {'query': query, 'count': 0, 'messages': []}
        status, parts = box.uid('FETCH', ','.join(uids), '(X-GM-MSGID X-GM-THRID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])')
        found = {}
        for part in parts or []:
            if isinstance(part, tuple) and len(part) == 2:
                meta = part[0].decode('utf-8', 'replace'); uid = (re.search(r'UID (\d+)', meta) or [None, ''])[1]
                found[uid] = summary(meta, part[1])
        messages = [found[u] for u in uids if u in found]
        return {'query': query, 'count': len(messages), 'messages': messages}
    finally:
        try: box.logout()
        except (imaplib.IMAP4.error, OSError): pass


def read_email(args):
    box = connect()
    try:
        uid = uid_of(box, args.get('message_id'))
        status, parts = box.uid('FETCH', uid, '(X-GM-MSGID X-GM-THRID FLAGS BODY.PEEK[]<0.%d>)' % MAX_FETCH)
        part = next((p for p in parts or [] if isinstance(p, tuple) and len(p) == 2), None)
        if status != 'OK' or not part: raise GmailError('無法讀取這封信。')
        message = email.message_from_bytes(part[1], policy=email.policy.default)
        result = summary(part[0].decode('utf-8', 'replace'), part[1])
        text = body_text(message)
        result.update(cc=clean(message['Cc']), body=text[:MAX_BODY], truncated=len(text) > MAX_BODY,
                      attachments=[clean(p.get_filename()) for p in message.iter_attachments() if p.get_filename()][:50])
        return result
    finally:
        try: box.logout()
        except (imaplib.IMAP4.error, OSError): pass


def compose(args, box=None):
    """Build the message. With reply_to_message_id it is threaded onto that message."""
    to, cc, bcc = addresses(args.get('to'), 'to'), addresses(args.get('cc'), 'cc'), addresses(args.get('bcc'), 'bcc')
    subject, body = clean(args.get('subject')), args.get('body')
    if not isinstance(body, str) or not body.strip() or len(body) > 200000: raise GmailError('請提供信件內容（body）。')
    message = EmailMessage()
    reply = args.get('reply_to_message_id')
    if reply:
        uid = uid_of(box, reply)
        status, parts = box.uid('FETCH', uid, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID REFERENCES SUBJECT FROM REPLY-TO)])')
        part = next((p for p in parts or [] if isinstance(p, tuple) and len(p) == 2), None)
        original = email.message_from_bytes(part[1] if part else b'', policy=email.policy.default)
        if original['Message-ID']:
            message['In-Reply-To'] = clean(original['Message-ID'])
            message['References'] = clean((clean(original['References']) + ' ' + clean(original['Message-ID'])).strip())
        if not subject: subject = clean(original['Subject']) if re.match(r'(?i)re:', clean(original['Subject'])) else 'Re: ' + clean(original['Subject'])
        if not to: to = addresses(clean(original['Reply-To']) or clean(original['From']), 'to')
    if not to: raise GmailError('請提供收件人（to）。')
    if not subject: raise GmailError('請提供主旨（subject）。')
    message['From'] = ADDRESS; message['To'] = ', '.join(to)
    if cc: message['Cc'] = ', '.join(cc)
    if bcc: message['Bcc'] = ', '.join(bcc)
    message['Subject'] = subject; message['Date'] = formatdate(localtime=True); message['Message-ID'] = make_msgid(domain=ADDRESS.split('@')[-1] or 'gmail.com')
    message.set_content(body)
    return message, to + cc + bcc


def create_draft(args):
    box = connect()
    try:
        message, recipients = compose(args, box)
        status, _ = box.append(special_folder(box, '\\Drafts'), '(\\Draft)', imaplib.Time2Internaldate(time.time()), message.as_bytes())
        if status != 'OK': raise GmailError('Gmail 沒有接受這份草稿。')
        return {'saved': True, 'where': 'Gmail 草稿匣', 'to': recipients, 'subject': str(message['Subject'])}
    finally:
        try: box.logout()
        except (imaplib.IMAP4.error, OSError): pass


def send_email(args):
    box = connect() if args.get('reply_to_message_id') else None
    try: message, recipients = compose(args, box)
    finally:
        if box:
            try: box.logout()
            except (imaplib.IMAP4.error, OSError): pass
    if not ADDRESS or not PASSWORD: raise GmailError('Gmail 尚未設定。請到 Zook 的連接器頁設定 Gmail。')
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=30, context=ssl.create_default_context()) as server:
            server.login(ADDRESS, PASSWORD)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise GmailError('Gmail 登入失敗。請確認信箱和應用程式密碼正確。')
    except smtplib.SMTPRecipientsRefused:
        raise GmailError('Gmail 拒絕了收件人地址，信沒有寄出。')
    except (smtplib.SMTPException, OSError):
        raise GmailError('寄信失敗，信沒有寄出。請稍後再試。')
    return {'sent': True, 'to': recipients, 'subject': str(message['Subject'])}


def text(description): return {'type': 'string', 'description': description}


RECIPIENTS = {'type': 'array', 'items': {'type': 'string'}, 'description': 'Email addresses'}
WRITE = {'to': RECIPIENTS, 'cc': RECIPIENTS, 'bcc': RECIPIENTS, 'subject': text('Subject. Optional when replying.'), 'body': text('Plain-text body'),
         'reply_to_message_id': text('To reply inside a conversation: the id of the message being answered, from search_emails')}
TOOLS = [
    ({'name': 'search_emails', 'description': 'Search the user\'s Gmail with Gmail search syntax (e.g. "from:amy is:unread newer_than:7d"). Returns the newest matches with id, sender, subject and date. An empty query lists the inbox.',
      'inputSchema': {'type': 'object', 'properties': {'query': text('Gmail search query'), 'max_results': {'type': 'integer', 'minimum': 1, 'maximum': 30, 'description': 'Default 10'}}, 'required': []},
      'annotations': {'readOnlyHint': True, 'openWorldHint': True}}, search_emails),
    ({'name': 'read_email', 'description': 'Read one message in full (headers, plain-text body, attachment names) by the id from search_emails. Does not mark it as read.',
      'inputSchema': {'type': 'object', 'properties': {'message_id': text('id from search_emails')}, 'required': ['message_id']},
      'annotations': {'readOnlyHint': True, 'openWorldHint': True}}, read_email),
    ({'name': 'create_draft', 'description': 'Save a draft in the user\'s Gmail Drafts without sending it. The user sends it from Gmail.',
      'inputSchema': {'type': 'object', 'properties': WRITE, 'required': ['body']},
      'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}}, create_draft),
    ({'name': 'send_email', 'description': 'Send an email from the user\'s Gmail right away. This cannot be undone; the user is asked to approve every send.',
      'inputSchema': {'type': 'object', 'properties': WRITE, 'required': ['body']},
      'annotations': {'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': True}}, send_email),
]


def handle(request):
    method, params = request.get('method'), request.get('params') or {}
    if method == 'initialize':
        return {'protocolVersion': params.get('protocolVersion') or '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'zook-gmail', 'version': '1.0.0'}}
    if method == 'ping': return {}
    if method == 'tools/list': return {'tools': [schema for schema, _ in TOOLS]}
    if method == 'tools/call':
        run = next((fn for schema, fn in TOOLS if schema['name'] == params.get('name')), None)
        if not run: raise KeyError('unknown tool')
        try:
            arguments = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
            return {'content': [{'type': 'text', 'text': json.dumps(run(arguments), ensure_ascii=False)}], 'isError': False}
        except GmailError as exc:
            return {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
        except (imaplib.IMAP4.error, OSError, ValueError, TypeError):
            return {'content': [{'type': 'text', 'text': 'Gmail 沒有完成這個動作，請稍後再試。'}], 'isError': True}
    raise KeyError(method)


def main():
    for line in sys.stdin:
        try: request = json.loads(line)
        except ValueError: continue
        if not isinstance(request, dict) or 'id' not in request: continue  # notifications need no answer
        try: reply = {'jsonrpc': '2.0', 'id': request['id'], 'result': handle(request)}
        except KeyError: reply = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found'}}
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + '\n'); sys.stdout.flush()


if __name__ == '__main__': main()
