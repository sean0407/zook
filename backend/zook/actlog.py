# How each line of the activity record ended (#247): 成功、失敗、等核准、已拒絕、需留意, and for the ones that need it, why and what to do next.
# Loaded by backend/server.py into one shared namespace. Read from the line's own words, so lines saved by earlier versions get a result too;
# nothing new is kept: no command, key or path is added beyond the line's text, which already follows actwords.py and command_summary.
import re

ACTIVITY_RESULTS = {'ok': '成功', 'failed': '失敗', 'waiting': '等核准', 'denied': '已拒絕', 'warn': '需留意'}
_RESTORE = '可以到「設定 › 備份與還原」還原較早的備份。'
ACTIVITY_OUTCOMES = (  # (pattern on the text, result, why, next step)
    (r'寫不進去', 'failed', '磁碟空間不足，或資料夾沒有寫入權限。', 'Zook 每次存檔都會再試；確認磁碟空間和資料夾權限後就會恢復。'),
    (r'^對話「.*」的檔案無法讀取，已改用備份', 'failed', '對話檔損壞或不完整。', '已改用備份，最近幾則訊息可能不在；打開這個對話確認一下。'),
    (r'^對話「.*」的檔案無法讀取', 'failed', '對話檔損壞或不完整，也沒有備份。', '這個對話目前是空的。' + _RESTORE),
    (r'^資料檔無法讀取，改用備份', 'failed', 'Zook 的資料檔損壞。', '已改用備份；確認 Bot、排程和設定是否完整，' + _RESTORE),
    (r'^資料檔無法讀取', 'failed', 'Zook 的資料檔損壞，也沒有可用的備份。', '從全新狀態開始；有匯出的備份檔時，到「設定 › 備份與還原」加入再還原。'),
    (r'紀錄損壞', 'failed', '暫存資料夾的紀錄檔損壞。', '刪掉這個紀錄檔，Zook 會重建；在那之前不提供清理工具。'),
    (r'安全檢查沒有執行', 'warn', 'Zook 的安全檢查這一次沒有執行，可能被管理政策關掉。', 'Claude 的 Bot 先只在工作資料夾裡做事；檢查恢復後會自動解除。'),
    (r'沒有能配的模型', 'warn', '目前沒有可用的帳號或模型。', '到「各模型使用量」確認至少一個帳號可用；可用時 Zook 會再配。'),
    (r'用量預算已用完', 'warn', '這個月的用量到了你設的上限。', '到「各模型使用量」調高上限，或等下個月。'),
    (r'已達預算的 80%', 'warn', '這個月的用量快到你設的上限。', '需要時到「各模型使用量」調高上限。'),
    (r'^未詢問即執行', 'warn', 'CLI 沒有先問 Zook 就做了這件事。', '不希望這樣時，在編輯 Bot 把存取範圍改小。'),
    (r'兩台都改過', 'warn', '兩台 Mac 改了同一個對話。', '這台的版本另存成副本；打開對話比對後，刪掉不要的那份。'),
    (r'^拒絕：', 'denied', '你拒絕了這個動作，Bot 沒有做。', '需要的話，在對話裡請 Bot 再做一次。'),
)


def activity_outcome(item):
    """{result, resultName, why, next} for one saved line."""
    text = str(item.get('text') or '')
    result, why, step = 'ok', '', ''
    for pattern, kind, reason, after in ACTIVITY_OUTCOMES:
        if re.search(pattern, text): result, why, step = kind, reason, after; break
    return dict(result=result, resultName=ACTIVITY_RESULTS[result], why=why, next=step)


def activity_waiting(store):
    """Approvals a Bot is waiting for right now, newest first, in the words the record uses once they are answered. Lock held."""
    out = []
    for job in store.data.get('jobs') or []:
        if not isinstance(job, dict) or job.get('status') != 'running': continue
        bot = store.find('bots', job.get('botId')) or {}
        for approval in job.get('approvals') or []:
            if not isinstance(approval, dict) or approval.get('status') != 'pending': continue
            what = approval.get('text') or describe_call(dict(approval, name=approval.get('name')))  # core.py, as the 核准 line
            where = bot.get('name') or 'Bot'
            out.append(dict(id='wait-' + str(approval.get('id') or ''), at=approval.get('createdAt') or job.get('startedAt') or job.get('createdAt') or '',
                            kind='approval', by=where, text=' '.join(('等你核准：%s（%s）' % (what, where)).split())[:300], result='waiting',
                            resultName=ACTIVITY_RESULTS['waiting'], why='Bot 停在這一步，等你決定。',
                            next='打開「%s」的%s，按「允許」或「拒絕」。' % (where, '群組' if job.get('groupId') else '對話'),
                            botId=str(job.get('botId') or ''), groupId=str(job.get('groupId') or '')))
    return sorted(out, key=lambda x: x['at'], reverse=True)
