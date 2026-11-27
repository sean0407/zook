# -*- coding: utf-8 -*-
"""#323: the usage page cards, the sidebar and Bot detail rings, the Bot form and the reply's backups read one source (quota_view),
and a figure Zook cannot trust is 無法確定, never a number. #33: a Bot whose model the user picked first tries the same CLI's other
accounts, and the default backup order goes by what is left. #321 #207: 偵測使用量 reports what it updated and what it could not."""
import datetime, importlib.util, json, shutil, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'backend/server.py'


def load():
    spec = importlib.util.spec_from_file_location('zook_server_for_quota_source', SERVER)
    module = importlib.util.module_from_spec(spec); sys.path.insert(0, str(SERVER.parent)); spec.loader.exec_module(module)
    return module


def iso(seconds_ago=0): return datetime.datetime.fromtimestamp(time.time() - seconds_ago, datetime.timezone.utc).isoformat()


class QuotaSourceTest(unittest.TestCase):
    def setUp(self):
        self.m = load(); self.temp = tempfile.TemporaryDirectory(); self.store = self.m.Store(Path(self.temp.name) / 'data')
        self.store.data['settings'].update(addedProviders=['codex', 'claude', 'grok'], autoModels=['codex', 'claude'])
        self.cli = mock.patch.object(self.m, 'find_cli', return_value='/bin/true'); self.cli.start()  # no AI CLI needs to be installed

    def tearDown(self): self.cli.stop(); self.temp.cleanup()

    def answered(self, provider, account='', seconds_ago=60):
        self.store.data['jobs'].append(dict(id=self.m.ID(), botId='b', status='completed', createdAt=iso(seconds_ago), finishedAt=iso(seconds_ago), ran=[provider, '', account]))

    def ring(self, provider): return next(r for r in self.m.usage_rings(self.store) if r['id'] == provider)

    def test_a_grok_reading_of_zero_that_kept_answering_is_unknown_everywhere(self):
        self.store.data['quota'] = {'grok': dict(windows=[dict(label='每週', usedPercent=100, resetsAt=None)], updatedAt=iso(600))}
        self.assertEqual(self.m.quota_view(self.store, 'grok')['level'], 'out')  # nothing says otherwise yet
        self.assertTrue(self.m.quota_exhausted(self.store, 'grok')); self.assertEqual(self.ring('grok')['left'], 0)
        self.answered('grok', seconds_ago=60)  # but Grok answered after that reading
        view = self.m.quota_view(self.store, 'grok')
        self.assertEqual((view['level'], view['left']), ('unknown', None)); self.assertIn('無法確定', view['note'])
        ring = self.ring('grok')
        self.assertEqual((ring['unknown'], ring['left'], ring['week'], ring['out']), (True, None, None, False))  # no 0% and no 100%
        self.assertFalse(self.m.quota_exhausted(self.store, 'grok'))  # the reply tries it, as the screens say
        self.store.data['quota']['grok']['updatedAt'] = iso(10)  # read again after the reply, still 0%: Grok gives no reset time, so still not trusted
        self.assertEqual(self.m.quota_view(self.store, 'grok')['level'], 'unknown')

    def test_an_old_reading_without_a_reset_time_is_unknown(self):
        self.store.data['quota'] = {'grok': dict(windows=[dict(label='每週', usedPercent=40, resetsAt=None)], updatedAt=iso(6 * 3600))}
        view = self.m.quota_view(self.store, 'grok')
        self.assertEqual((view['level'], view['left'], view['windows'][0]['left']), ('unknown', None, None))
        self.assertEqual((self.ring('grok')['left'], self.ring('grok')['unknown']), (None, True))
        self.assertEqual(self.m.quota_left(self.store, 'grok'), 50)

    def test_official_figures_with_a_reset_time_stay_used_up(self):
        self.store.data['quota'] = {'codex': dict(windows=[dict(label='5 小時', usedPercent=100, resetsAt=time.time() + 3600), dict(label='每週', usedPercent=30, resetsAt=time.time() + 86400)], updatedAt=iso(30))}
        self.answered('codex', seconds_ago=600)  # an earlier reply says nothing about this newer reading
        view = self.m.quota_view(self.store, 'codex')
        self.assertEqual((view['level'], view['left']), ('out', 0)); self.assertTrue(self.m.quota_exhausted(self.store, 'codex'))
        ring = self.ring('codex'); self.assertEqual((ring['fiveHour'], ring['week'], ring['left']), (0, 70, 0))
        self.assertEqual([r['left'] for r in view['windows']], [w['left'] for w in ring['windows']])  # the bars and the ring are the same figures

    def test_the_quota_answer_carries_the_same_view(self):
        self.store.data['quota'] = {'codex': dict(windows=[dict(label='每週', usedPercent=85, resetsAt=time.time() + 86400)], updatedAt=iso(30))}
        out = self.m.quota_attach_views(self.store, {'providers': [dict(id='codex', profiles=[dict(id='w1')])]})
        self.assertEqual(out['providers'][0]['view']['level'], 'low'); self.assertEqual(out['providers'][0]['view']['left'], self.ring('codex')['left'])
        self.assertEqual(out['providers'][0]['profiles'][0]['view']['level'], '')  # no figures: no level, no number

    def test_a_reported_reached_limit_is_zero_on_the_bars_and_the_ring(self):
        self.store.data['quota'] = {'codex': dict(windows=[dict(label='每週', usedPercent=30, resetsAt=time.time() + 86400)], limitReached='usage_limit_reached', updatedAt=iso(30))}
        view = self.m.quota_view(self.store, 'codex')
        self.assertEqual((view['level'], view['windows'][0]['left'], view['limitCode']), ('out', 0, 'usage_limit_reached'))
        self.assertEqual([w['left'] for w in self.ring('codex')['windows']], [w['left'] for w in view['windows']])

    def test_the_reply_that_brought_the_reading_is_not_proof_against_it(self):
        self.store.data['quota'] = {'claude': dict(windows=[dict(label='5 小時', usedPercent=100, resetsAt=time.time() + 3600)], updatedAt=iso(20), source='reply')}
        self.answered('claude', seconds_ago=15)  # the same reply ended a moment after it reported the limit
        self.assertEqual(self.m.quota_view(self.store, 'claude')['level'], 'out')

    def test_a_backup_of_another_cli_counts_for_that_cli_s_own_sign_in(self):
        self.store.data['accounts'] = [dict(id='w1', provider='codex', name='Waifdance', type='login')]
        self.store.data['quota'] = {'grok': dict(windows=[dict(label='每週', usedPercent=100, resetsAt=None)], updatedAt=iso(600))}
        self.answered('grok', account='w1', seconds_ago=60)  # a Codex Bot on w1 whose backup Grok answered: ran keeps the Bot's account
        self.assertEqual(self.m.quota_view(self.store, 'grok')['level'], 'unknown')

    def test_a_removed_account_s_replies_count_for_nobody(self):
        self.store.data['quota'] = {'grok': dict(windows=[dict(label='每週', usedPercent=100, resetsAt=None)], updatedAt=iso(600))}
        self.answered('grok', account='gone1', seconds_ago=60)
        self.assertEqual(self.m.quota_view(self.store, 'grok')['level'], 'out')

    def test_unknown_is_not_low_for_the_backups(self):
        self.store.data['quota'] = {'grok': dict(windows=[dict(label='每週', usedPercent=100, resetsAt=None)], updatedAt=iso(600))}
        self.assertTrue(self.m.backup_low(self.store, 'grok')); self.assertTrue(self.m.auto_quota_low(self.store, 'grok'))
        self.answered('grok', seconds_ago=60)
        self.assertFalse(self.m.backup_low(self.store, 'grok')); self.assertFalse(self.m.auto_quota_low(self.store, 'grok'))

    def test_antigravity_s_other_group_does_not_hide_the_gemini_ring(self):
        self.store.data['settings']['addedProviders'] = ['antigravity']
        self.store.data['quota'] = {'antigravity': dict(windows=[dict(label='Claude 與 GPT 模型 · 每週', usedPercent=100, resetsAt=time.time() + 86400),
                                                                 dict(label='Gemini 模型 · 每週', usedPercent=20, resetsAt=time.time() + 86400)], updatedAt=iso(600))}
        self.answered('antigravity', seconds_ago=60)  # Gemini answered: says nothing about the used-up group
        self.assertEqual(self.m.quota_view(self.store, 'antigravity')['level'], 'out')
        ring = self.ring('antigravity'); self.assertEqual((ring['unknown'], ring['week']), (False, 80))

    def add_codex_accounts(self):
        now, data = time.time(), self.store.data
        data['accounts'] = [dict(id='w1', provider='codex', name='Waifdance', type='login'), dict(id='w2', provider='codex', name='Home', type='login'),
                            dict(id='k1', provider='codex', name='Key', type='key')]
        data['autoStatus'] = {'codex': dict(signedIn=True, billed=False, checkedAt=now), 'claude': dict(signedIn=True, billed=False, checkedAt=now),
                              'codex@w1': dict(signedIn=True, billed=False, checkedAt=now), 'codex@w2': dict(signedIn=True, billed=False, checkedAt=now),
                              'codex@k1': dict(signedIn=True, billed=True, checkedAt=now)}
        data['quota'] = {'codex': dict(windows=[dict(label='5 小時', usedPercent=100, resetsAt=now + 3600)], updatedAt=iso(10)),
                         'codex@w1': dict(windows=[dict(label='5 小時', usedPercent=64, resetsAt=now + 3600)], updatedAt=iso(10)),
                         'codex@w2': dict(windows=[dict(label='5 小時', usedPercent=20, resetsAt=now + 3600)], updatedAt=iso(10))}

    def test_a_bot_picked_by_hand_tries_its_other_accounts_first(self):
        self.add_codex_accounts(); m = self.m
        bot = dict(id='b', name='寫手', provider='codex', account='', model='gpt-6', fallbacks=['claude'])
        chain = m.provider_chain(self.store, bot, 'codex', 'gpt-6')
        self.assertEqual(chain[:3], [('codex', 'gpt-6'), ('codex', 'gpt-6', 'w2'), ('codex', 'gpt-6', 'w1')])  # most left first, model kept, never the API key
        self.assertEqual(chain[3][0], 'claude')  # another CLI only after them
        on_w1 = m.provider_chain(self.store, dict(bot, account='w1'), 'codex', 'gpt-6')
        self.assertEqual([x[2] if len(x) > 2 else None for x in on_w1[:3]], [None, 'w2', ''])  # its own account is not tried twice; the CLI's own sign-in is one of them
        self.assertEqual(m.provider_chain(self.store, dict(bot, fallbacks=[]), 'codex', 'gpt-6'), chain[:3])  # 不自動換: still the same CLI's accounts, no other CLI (2026-11-27)
        self.store.data['settings']['fallbacks'] = []
        self.assertEqual(m.provider_chain(self.store, dict(id='c', provider='codex', account='', model='gpt-6'), 'codex', 'gpt-6'), chain[:3])  # nothing set in 設定 either
        self.assertEqual(m.provider_chain(self.store, dict(bot, autoAssigned=True), 'codex', 'gpt-6')[1][0], 'claude')  # 自動選擇 has its own (auto_backups)
        self.store.data['settings']['autoAccounts'] = {'w2': False}  # 自動選用 turned off: not used without asking
        self.assertNotIn(('codex', 'gpt-6', 'w2'), m.provider_chain(self.store, bot, 'codex', 'gpt-6'))
        self.store.data['quota']['codex@w2']['windows'][0]['usedPercent'] = 90  # nearly used up: after another CLI (backups_with_room)
        self.store.data['settings']['autoAccounts'] = {}
        backups = m.backups_with_room(self.store, bot, [(x[0], x[1], x[2] if len(x) > 2 else None, True) for x in m.provider_chain(self.store, bot, 'codex', 'gpt-6')[1:]])
        self.assertEqual([(x[0], x[2]) for x in backups], [('codex', 'w1'), ('claude', None), ('codex', 'w2')])

    def test_the_default_order_goes_by_what_is_left(self):
        now, m = time.time(), self.m
        self.store.data['settings']['fallbacks'] = ['claude', 'grok']
        self.store.data['quota'] = {'claude': dict(windows=[dict(label='5 小時', usedPercent=70, resetsAt=now + 3600)], updatedAt=iso(10)),
                                    'grok': dict(windows=[dict(label='每週', usedPercent=10, resetsAt=None)], updatedAt=iso(10))}
        bot = dict(id='b', name='寫手', provider='codex', account='', model='')
        self.assertEqual([x[0] for x in m.provider_chain(self.store, bot, 'codex', '')], ['codex', 'grok', 'claude'])
        self.assertEqual([x[0] for x in m.provider_chain(self.store, dict(bot, fallbacks=['claude', 'grok']), 'codex', '')], ['codex', 'claude', 'grok'])  # its own list stays as set

    def test_detect_report_says_what_was_updated(self):
        started = time.time() - 5
        out = {'providers': [dict(id='codex', status='logged_in', quota=dict(updatedAt=iso(1)), profiles=[dict(id='w1', name='Waifdance', status='logged_in', quota=dict(updatedAt=iso(3600)))]),
                             dict(id='grok', status='logged_in', quota=None, profiles=[]), dict(id='claude', status='logged_in', autoBilled=True, quota=None, profiles=[]),
                             dict(id='gemini', status='logged_in', noQuotaApi=True, quota=None, profiles=[])]}
        report = self.m.detect_report(self.store, started, out)['lastDetect']
        self.assertEqual(report['updated'], 1)
        self.assertEqual([f['name'] for f in report['failed']], ['Codex（Waifdance）', 'Grok（預設）'])  # API billing and CLIs without figures are not counted
        self.assertTrue(all(f['why'] for f in report['failed'])); self.assertEqual(self.store.data['usageDetectReport'], report)


@unittest.skipUnless(shutil.which('node'), 'node is needed to run the page code')
class QuotaSourcePageTest(unittest.TestCase):
    """The page goes by the view Zook sends: 無法確定 with no number on the card, in the Bot form and beside a choice."""
    def test_the_card_and_the_form_say_unknown(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent)); from usage_cards_test import run
        view = dict(level='unknown', note='顯示已用完，但 14:02 仍正常回覆，額度無法確定', windows=[dict(label='每週', left=0, resetsAt=None)], left=None)
        got = run("""state = {data: {settings: {provider: 'codex'}, bots: []}, quota: {providers: [{id: 'grok', zookUsage: {fiveHour: {replies: 2, tokens: 30000}, week: {replies: 2, tokens: 30000}},
          quota: {windows: [{label: '每週', usedPercent: 100, resetsAt: null}], updatedAt: new Date().toISOString()}, view: %s, profiles: []}]}};
          const p = {id: 'grok', name: 'Grok', installed: true, status: 'logged_in', profiles: []}, lv = accountLevel('grok', '');
          console.log(JSON.stringify({lv: lv.level, st: cardStatus(p, null, lv).text, warn: quotaWarnText('grok'), mark: levelMark(lv), body: cardQuota(p, null, state.quota.providers[0], ['每週']).body, zook: zookLine(state.quota.providers[0])}));""" % json.dumps(view, ensure_ascii=False))
        self.assertEqual((got['lv'], got['st'], got['mark']), ('unknown', '無法確定', '・額度無法確定'))
        self.assertIn('無法確定', got['warn']); self.assertNotIn('已用完，現在傳訊息會失敗', got['warn'])
        self.assertIn('14:02 仍正常回覆', got['body']); self.assertNotIn('剩餘 0%', got['body'])
        self.assertIn('Zook 內：5 小時 2 則', got['zook'])


    def test_the_bot_page_names_what_really_runs_next(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent)); from usage_cards_test import run, JS
        botstate = (JS / '32c-botstate.js').read_text(encoding='utf-8')
        got = run(botstate.replace('  const troubleBadge', '  const unused0') + """
          const providerShort = id => ({codex: 'Codex', claude: 'Claude'})[id] || id;
          const acct = (id, name, level, left) => ({id, name, status: 'logged_in', autoOn: true, view: {level, left, windows: []}});
          state = {data: {settings: {provider: 'codex', fallbacks: ['claude']}, bots: []}, quota: {providers: [
            {id: 'codex', status: 'logged_in', autoOn: true, view: {level: 'out', left: 0, windows: []}, quota: {windows: []}, profiles: [acct('w1', 'Low', 'low', 8), acct('w2', 'Unsure', 'unknown', null)]},
            {id: 'claude', status: 'logged_in', autoOn: true, view: {level: 'ok', left: 70, windows: []}, quota: {windows: [{label: '5 小時', usedPercent: 30}]}, profiles: []}]}};
          const a = nextBackup('codex', '', ['claude']);
          state.quota.providers[0].profiles.pop();
          const b = nextBackup('codex', '', ['claude']);
          console.log(JSON.stringify({a, b, c: nextBackup('codex', '', [])}));""")
        self.assertEqual(got['a'], 'Codex（Unsure）')  # 無法確定 is tried, as on the Mac (half left)
        self.assertEqual(got['b'], 'Claude')  # a same-CLI account under 20% comes after another CLI with room
        self.assertEqual(got['c'], 'Codex（Low）')  # nothing else: the nearly used-up one


if __name__ == '__main__': unittest.main()
