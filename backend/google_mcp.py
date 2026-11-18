#!/usr/bin/env python3
"""Zook's built-in Google connector: Gmail, Calendar and Drive over Google's own APIs, as a stdio MCP server.
The access token arrives in the environment and is never printed. Standard library only."""
import base64, json, os, sys, urllib.error, urllib.parse, urllib.request
from email.message import EmailMessage

TOKEN = os.environ.get('ZOOK_GOOGLE_TOKEN', '')
CAN_WRITE = os.environ.get('ZOOK_GOOGLE_WRITE') == '1'
_test = os.environ.get('ZOOK_GOOGLE_API', '')
API = _test if _test.startswith('http://127.0.0.1:') else 'https://www.googleapis.com'
GMAIL = _test + '/gmail' if API == _test else 'https://gmail.googleapis.com/gmail'
MAX_TEXT = 128 * 1024


class GoogleError(Exception): pass


def call(url, query=None, body=None, method=None, raw=None, content_type='application/json'):
    if query: url += '?' + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, '')}, doseq=True)
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method or ('POST' if data is not None else 'GET'), headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': content_type})
    try:
        with urllib.request.urlopen(request, timeout=30) as response: got = response.read(8 << 20)
    except urllib.error.HTTPError as exc:
        if exc.code == 401: raise GoogleError('Google 的登入已失效，請到 Zook 的連接器頁重新登入。')
        if exc.code == 403: raise GoogleError('Google 帳號沒有開放這個權限，或公司管理員不允許。')
        if exc.code == 404: raise GoogleError('找不到這個項目。')
        raise GoogleError('Google 沒有完成這個動作（%d）。' % exc.code)
    except (urllib.error.URLError, OSError): raise GoogleError('連不上 Google，請確認網路後再試。')
    return got


def get(url, query=None): return json.loads(call(url, query) or b'{}')
def limit(args, default=10, most=30): return max(1, min(most, int(args.get('max_results') or default)))
def header(message, name): return next((h.get('value', '') for h in (message.get('payload') or {}).get('headers') or [] if h.get('name', '').lower() == name), '')


def mail_text(part):
    if part.get('mimeType') == 'text/plain' and (part.get('body') or {}).get('data'):
        return base64.urlsafe_b64decode(part['body']['data'] + '==').decode('utf-8', 'replace')
    return next((t for t in (mail_text(p) for p in part.get('parts') or []) if t), '')


def gmail_search(args):
    found = get(GMAIL + '/v1/users/me/messages', {'q': args.get('query', ''), 'maxResults': limit(args)}).get('messages') or []
    out = []
    for item in found:
        m = get(GMAIL + '/v1/users/me/messages/' + urllib.parse.quote(item['id']), {'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']})
        out.append({'id': m['id'], 'from': header(m, 'from'), 'subject': header(m, 'subject'), 'date': header(m, 'date'), 'snippet': m.get('snippet', ''), 'unread': 'UNREAD' in (m.get('labelIds') or [])})
    return {'messages': out}


def gmail_read(args):
    m = get(GMAIL + '/v1/users/me/messages/' + urllib.parse.quote(str(args['message_id'])), {'format': 'full'})
    return {'id': m['id'], 'from': header(m, 'from'), 'to': header(m, 'to'), 'cc': header(m, 'cc'), 'subject': header(m, 'subject'), 'date': header(m, 'date'),
            'body': mail_text(m.get('payload') or {})[:MAX_TEXT] or m.get('snippet', '')}


def gmail_send(args):
    message = EmailMessage(); to = args.get('to') or []
    if not to or not isinstance(to, list): raise GoogleError('請提供收件人。')
    message['To'] = ', '.join(str(x) for x in to)
    if args.get('cc'): message['Cc'] = ', '.join(str(x) for x in args['cc'])
    message['Subject'] = str(args.get('subject') or ''); message.set_content(str(args.get('body') or ''))
    sent = json.loads(call(GMAIL + '/v1/users/me/messages/send', body={'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}))
    return {'sent': True, 'id': sent.get('id')}


def event_view(e):
    return {'id': e.get('id'), 'title': e.get('summary', ''), 'start': (e.get('start') or {}).get('dateTime') or (e.get('start') or {}).get('date'),
            'end': (e.get('end') or {}).get('dateTime') or (e.get('end') or {}).get('date'), 'location': e.get('location', ''),
            'attendees': [a.get('email') for a in e.get('attendees') or []][:30], 'description': (e.get('description') or '')[:2000]}


def calendar_list(args):
    found = get(API + '/calendar/v3/calendars/primary/events', {'timeMin': args.get('time_min'), 'timeMax': args.get('time_max'), 'q': args.get('query'), 'singleEvents': 'true', 'orderBy': 'startTime', 'maxResults': limit(args, 20, 50)})
    return {'events': [event_view(e) for e in found.get('items') or []]}


def event_body(args):
    body = {}
    for key, name in (('title', 'summary'), ('description', 'description'), ('location', 'location')):
        if args.get(key) is not None: body[name] = str(args[key])
    for key in ('start', 'end'):
        if args.get(key): body[key] = {'date': args[key]} if len(str(args[key])) == 10 else {'dateTime': args[key]}
    if args.get('attendees') is not None: body['attendees'] = [{'email': str(x)} for x in args['attendees']]
    return body


def calendar_create(args):
    if not args.get('title') or not args.get('start') or not args.get('end'): raise GoogleError('請提供標題、開始和結束時間。')
    return {'created': event_view(json.loads(call(API + '/calendar/v3/calendars/primary/events', body=event_body(args))))}


def calendar_update(args):
    return {'updated': event_view(json.loads(call(API + '/calendar/v3/calendars/primary/events/' + urllib.parse.quote(str(args['event_id'])), body=event_body(args), method='PATCH')))}


EXPORTS = {'application/vnd.google-apps.document': 'text/plain', 'application/vnd.google-apps.spreadsheet': 'text/csv', 'application/vnd.google-apps.presentation': 'text/plain'}


def drive_search(args):
    text = str(args.get('query') or '').replace('\\', '\\\\').replace("'", "\\'")
    found = get(API + '/drive/v3/files', {'q': "fullText contains '%s' and trashed = false" % text if text else 'trashed = false', 'pageSize': limit(args, 10, 30),
                                          'fields': 'files(id,name,mimeType,modifiedTime,webViewLink,size)', 'orderBy': None if text else 'modifiedTime desc', 'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true'})
    return {'files': found.get('files') or []}


def drive_read(args):
    file_id = urllib.parse.quote(str(args['file_id'])); meta = get(API + '/drive/v3/files/' + file_id, {'fields': 'id,name,mimeType,size', 'supportsAllDrives': 'true'})
    kind = meta.get('mimeType', '')
    if kind in EXPORTS: raw = call(API + '/drive/v3/files/%s/export' % file_id, {'mimeType': EXPORTS[kind]})
    elif int(meta.get('size') or 0) > MAX_TEXT: raise GoogleError('這個檔案超過 128 KB，無法直接讀取。')
    else: raw = call(API + '/drive/v3/files/' + file_id, {'alt': 'media', 'supportsAllDrives': 'true'})
    try: return {'name': meta.get('name'), 'content': raw[:MAX_TEXT].decode('utf-8')}
    except UnicodeDecodeError: raise GoogleError('這個檔案不是文字內容，無法直接讀取。')


def drive_upload(args):
    content = str(args.get('content') or '').encode()
    if not args.get('name') or len(content) > MAX_TEXT: raise GoogleError('請提供檔名，內容不能超過 128 KB。')
    boundary = 'zook' + base64.urlsafe_b64encode(os.urandom(12)).decode()
    raw = ('--%s\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n%s\r\n--%s\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n' % (boundary, json.dumps({'name': str(args['name'])}), boundary)).encode() + content + ('\r\n--%s--' % boundary).encode()
    made = json.loads(call(API + '/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink', raw=raw, content_type='multipart/related; boundary=' + boundary))
    return {'uploaded': made}


def drive_update(args):
    content = str(args.get('content') or '').encode()
    if len(content) > MAX_TEXT: raise GoogleError('內容不能超過 128 KB。')
    made = json.loads(call(API + '/upload/drive/v3/files/%s?uploadType=media&fields=id,name,webViewLink' % urllib.parse.quote(str(args['file_id'])), raw=content, method='PATCH', content_type='text/plain; charset=UTF-8'))
    return {'updated': made}


def S(description): return {'type': 'string', 'description': description}
N = {'type': 'integer', 'minimum': 1, 'maximum': 50, 'description': 'How many to return'}
LIST = {'type': 'array', 'items': {'type': 'string'}, 'description': 'Email addresses'}
EVENT = {'title': S('Title'), 'start': S('Start: RFC 3339 date-time with offset, or YYYY-MM-DD for an all-day event'), 'end': S('End, same format as start'), 'description': S('Notes'), 'location': S('Place'), 'attendees': LIST}
READ = {'readOnlyHint': True, 'openWorldHint': True}
ASK = {'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': True, 'alwaysApprove': True}  # Zook asks the user before every one of these
def tool(name, description, properties, required, notes, run): return ({'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': properties, 'required': required}, 'annotations': notes}, run)
TOOLS = [
    tool('gmail_search', 'Search the user\'s Gmail with Gmail search syntax (e.g. "is:unread newer_than:2d"). Newest first.', {'query': S('Gmail search query'), 'max_results': N}, ['query'], READ, gmail_search),
    tool('gmail_read', 'Read one message in full by the id from gmail_search.', {'message_id': S('id from gmail_search')}, ['message_id'], READ, gmail_read),
    tool('calendar_list', 'List events on the user\'s main Google Calendar between two times.', {'time_min': S('RFC 3339 start, e.g. 2026-11-18T00:00:00+08:00'), 'time_max': S('RFC 3339 end'), 'query': S('Optional text to match'), 'max_results': N}, ['time_min', 'time_max'], READ, calendar_list),
    tool('drive_search', 'Search the user\'s Google Drive by text. Without a query, lists recently changed files.', {'query': S('Words to look for'), 'max_results': N}, [], READ, drive_search),
    tool('drive_read', 'Read a Drive file as text by the id from drive_search. Google Docs, Sheets and Slides are converted.', {'file_id': S('id from drive_search')}, ['file_id'], READ, drive_read),
] + ([
    tool('gmail_send', 'Send an email from the user\'s Gmail right away. The user approves every send.', {'to': LIST, 'cc': LIST, 'subject': S('Subject'), 'body': S('Plain-text body')}, ['to', 'body'], ASK, gmail_send),
    tool('calendar_create', 'Create an event on the user\'s main calendar. The user approves it first.', EVENT, ['title', 'start', 'end'], ASK, calendar_create),
    tool('calendar_update', 'Change an event by the id from calendar_list. Only the fields given are changed. The user approves it first.', dict(EVENT, event_id=S('id from calendar_list')), ['event_id'], ASK, calendar_update),
    tool('drive_upload', 'Create a new text file in the user\'s Drive. The user approves it first.', {'name': S('File name'), 'content': S('Text content')}, ['name', 'content'], ASK, drive_upload),
    tool('drive_update', 'Replace the content of a Drive file that Zook created. The user approves it first.', {'file_id': S('id of the file'), 'content': S('New text content')}, ['file_id', 'content'], ASK, drive_update),
] if CAN_WRITE else [])


def handle(request):
    method, params = request.get('method'), request.get('params') or {}
    if method == 'initialize': return {'protocolVersion': params.get('protocolVersion') or '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'zook-google', 'version': '1.0.0'}}
    if method == 'ping': return {}
    if method == 'tools/list': return {'tools': [schema for schema, _ in TOOLS]}
    if method == 'tools/call':
        run = next((fn for schema, fn in TOOLS if schema['name'] == params.get('name')), None)
        if not run: raise KeyError('unknown tool')
        try: return {'content': [{'type': 'text', 'text': json.dumps(run(params.get('arguments') if isinstance(params.get('arguments'), dict) else {}), ensure_ascii=False)}], 'isError': False}
        except GoogleError as exc: return {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
        except (KeyError, ValueError, TypeError): return {'content': [{'type': 'text', 'text': 'Google 沒有完成這個動作，請檢查提供的內容。'}], 'isError': True}
    raise KeyError(method)


def main():
    for line in sys.stdin:
        try: request = json.loads(line)
        except ValueError: continue
        if not isinstance(request, dict) or 'id' not in request: continue
        try: reply = {'jsonrpc': '2.0', 'id': request['id'], 'result': handle(request)}
        except KeyError: reply = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found'}}
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + '\n'); sys.stdout.flush()


if __name__ == '__main__': main()
