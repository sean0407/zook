import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('zook_usage_server', Path(__file__).resolve().parents[1] / 'backend/server.py')
server = importlib.util.module_from_spec(spec); spec.loader.exec_module(server)

# Shapes captured from codex-cli 0.167.1 `exec --json` and Claude Code 2.1.325 `stream-json`.
CODEX_OUT = '\n'.join(json.dumps(x) for x in [
    {'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'},
    {'type': 'item.completed', 'item': {'id': 'i0', 'type': 'agent_message', 'text': 'thinking aloud'}},
    {'type': 'item.completed', 'item': {'id': 'i1', 'type': 'agent_message', 'text': 'OK'}},
    {'type': 'turn.completed', 'usage': {'input_tokens': 19868, 'cached_input_tokens': 11520, 'output_tokens': 5, 'reasoning_output_tokens': 0}}])
CLAUDE_OUT = '\n'.join(json.dumps(x) for x in [
    {'type': 'system', 'subtype': 'init'},
    {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed', 'resetsAt': 1794753600, 'rateLimitType': 'five_hour', 'overageStatus': 'rejected',
        'unifiedWindows': {'five_hour': {'utilization': 0.04, 'resetsAt': 1794753600, 'status': 'allowed'}, 'seven_day': {'utilization': 0.01, 'resetsAt': 1794772800, 'status': 'allowed'}}}},
    {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'OK', 'total_cost_usd': 0.00053069,
     'usage': {'input_tokens': 2, 'cache_creation_input_tokens': 2610, 'cache_read_input_tokens': 649, 'output_tokens': 4}, 'modelUsage': {'claude-haiku-5-5': {}}}])
CODEX_LIMITS = {'rateLimits': {'primary': {'usedPercent': 4, 'windowDurationMins': 300, 'resetsAt': 1794760472},
                               'secondary': {'usedPercent': 18, 'windowDurationMins': 10080, 'resetsAt': 1795305515},
                               'credits': {'hasCredits': False, 'unlimited': False, 'balance': '0'}, 'planType': 'team', 'rateLimitReachedType': None},
                'rateLimitResetCredits': {'availableCount': 2}}


class ParseTest(unittest.TestCase):
    def test_codex_json(self):
        out = server.parse_cli_output('codex', CODEX_OUT, 'gpt-6-luna')
        self.assertEqual(out['content'], 'OK')
        self.assertEqual(out['usage'], {'input': 19868, 'cachedInput': 11520, 'output': 5, 'model': 'gpt-6-luna', 'costUsd': None})
        self.assertEqual(server.parse_cli_output('codex', 'plain text reply\n')['content'], 'plain text reply')
        failed = server.parse_cli_output('codex', json.dumps({'type': 'turn.failed', 'error': {'message': 'Your workspace is out of credits'}}))
        self.assertTrue(failed['isError']); self.assertIn('out of credits', failed['error'])

    def test_claude_stream_json(self):
        out = server.parse_cli_output('claude', CLAUDE_OUT)
        self.assertEqual(out['content'], 'OK')
        self.assertEqual(out['usage'], {'input': 3261, 'cachedInput': 649, 'cacheWrite': 2610, 'output': 4, 'model': 'claude-haiku-5-5', 'costUsd': 0.00053069})
        q = server.normalize_quota('claude', out['quota'])
        self.assertEqual([(w['label'], w['usedPercent']) for w in q['windows']], [('5 小時', 4.0), ('每週', 1.0)])
        self.assertTrue(server.parse_cli_output('claude', 'not json')['unparsable'])
        self.assertEqual(server.parse_cli_output('claude', json.dumps({'result': 'legacy'}))['content'], 'legacy')

    def test_web_activity(self):
        codex = '\n'.join(json.dumps(x) for x in [
            {'type': 'item.completed', 'item': {'type': 'web_search', 'query': '', 'action': {'type': 'other'}, 'results': []}},
            {'type': 'item.completed', 'item': {'type': 'web_search', 'query': 'BTC price', 'action': {'type': 'search', 'query': 'BTC price'}, 'results': [{'domain': 'coinmarketcap.com'}]}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'About 64,500 USD (CoinMarketCap).'}}])
        out = server.parse_cli_output('codex', codex)
        self.assertEqual(out['web'], [{'name': 'web_search', 'arguments': {'query': 'BTC price'}}])
        opened = json.dumps({'type': 'item.completed', 'item': {'type': 'web_search', 'query': 'https://www.coingecko.com/x', 'action': {'type': 'open_page'}}})
        self.assertEqual(server.parse_cli_output('codex', opened)['web'], [{'name': 'web_fetch', 'arguments': {'url': 'https://www.coingecko.com/x'}}])
        grok = json.dumps({'text': 'ok', 'usage': {'input_tokens': 1, 'output_tokens': 1, 'server_tool_use': {'web_search_requests': 2}}})
        self.assertEqual(len(server.parse_cli_output('grok', grok)['web']), 2)
        claude = '\n'.join(json.dumps(x) for x in [
            {'type': 'assistant', 'message': {'content': [{'type': 'server_tool_use', 'name': 'web_search', 'input': {'query': 'ETH news'}},
                                                          {'type': 'tool_use', 'name': 'WebFetch', 'input': {'url': 'https://example.com/a'}}]}},
            {'type': 'result', 'result': 'done', 'usage': {}}])
        self.assertEqual(server.parse_cli_output('claude', claude)['web'], [{'name': 'web_search', 'arguments': {'query': 'ETH news'}},
                                                                          {'name': 'web_fetch', 'arguments': {'url': 'https://example.com/a'}}])

    def test_grok_json(self):
        raw = json.dumps(indent=2, obj={'text': 'OK', 'stopReason': 'end_turn', 'usage': {'input_tokens': 12159, 'cache_read_input_tokens': 8832, 'cache_creation_input_tokens': 0,
                          'output_tokens': 198, 'reasoning_tokens': 197, 'total_tokens': 21189}, 'total_cost_usd': 0.029922, 'modelUsage': {'grok-4.7-build': {}}})
        out = server.parse_cli_output('grok', raw)
        self.assertEqual(out['content'], 'OK')
        self.assertEqual(out['usage'], {'input': 20991, 'cachedInput': 8832, 'cacheWrite': 0, 'output': 198, 'model': 'grok-4.7-build', 'costUsd': 0.029922})
        self.assertEqual(server.parse_cli_output('grok', 'plain fallback')['content'], 'plain fallback')

    def test_codex_quota(self):
        q = server.normalize_quota('codex', CODEX_LIMITS)
        self.assertEqual([(w['label'], w['usedPercent']) for w in q['windows']], [('5 小時', 4.0), ('每週', 18.0)])
        self.assertEqual((q['plan'], q['resetCredits'], q['credits']['balance']), ('team', 2, '0'))


class AccountAndAutoQuotaTest(unittest.TestCase):
    def test_codex_account_details(self):
        from unittest import mock
        server._codex_account_cache.clear()
        reply = {'account': {'type': 'chatgpt', 'email': 'me@example.com', 'planType': 'team', 'workspaceName': 'myWorkspace'}}
        with mock.patch.object(server, 'codex_rpc', return_value=reply) as rpc:
            self.assertEqual(server.codex_account('/x/codex'), {'email': 'me@example.com', 'plan': 'team', 'workspace': 'myWorkspace'})
            server.codex_account('/x/codex'); self.assertEqual(rpc.call_count, 1)  # cached
        server._codex_account_cache.clear()
        with mock.patch.object(server, 'codex_rpc', side_effect=TimeoutError()):
            self.assertEqual(server.codex_account('/x/codex'), {})

    def test_claude_auto_refresh_is_stale_only_and_throttled(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); app = server.App(('127.0.0.1', 0), store, d, 't')
            try:
                logged_in = {'status': 'logged_in', 'method': 'Claude 訂閱帳號'}
                info = json.loads(CLAUDE_OUT.splitlines()[1])['rate_limit_info']
                with mock.patch.object(server, 'account_status', return_value=logged_in), mock.patch.object(server, 'claude_quota_probe', return_value=info) as probe:
                    app.auto_claude_quota(); self.assertEqual(probe.call_count, 1)
                    self.assertEqual(store.data['quota']['claude']['source'], 'auto')
                    app.auto_claude_quota(); self.assertEqual(probe.call_count, 1)  # fresh snapshot
                    store.data['quota']['claude']['updatedAt'] = '2020-01-01T00:00:00+00:00'
                    app.auto_claude_quota(); self.assertEqual(probe.call_count, 1)  # stale, but probed < 10 min ago
                    app.claude_probe_at = 0
                    app.auto_claude_quota(); self.assertEqual(probe.call_count, 2)
                with mock.patch.object(server, 'account_status', return_value={'status': 'logged_in', 'method': 'Anthropic Console'}), mock.patch.object(server, 'claude_quota_probe') as probe:
                    store.data['quota'].pop('claude'); app.claude_probe_at = 0
                    app.auto_claude_quota(); probe.assert_not_called()  # API billing has no windows
            finally: app.server_close()


class VersionTest(unittest.TestCase):
    def test_parse_and_compare(self):
        P = server.P
        self.assertEqual(P.parse_version('codex-cli 0.167.1'), '0.167.1')
        self.assertEqual(P.parse_version('2.1.325 (Claude Code)'), '2.1.325')
        self.assertEqual(P.latest_from_response('x', json.dumps({'tag_name': 'rust-v0.169.0'})), '0.169.0')
        self.assertEqual(P.latest_from_response('x', json.dumps({'name': '@google/gemini-cli', 'version': '0.21.3'})), '0.21.3')
        self.assertEqual(P.latest_from_response('x', '2.1.325\n'), '2.1.325')
        self.assertGreater(P.version_key('0.169.0'), P.version_key('0.167.1'))
        self.assertGreater(P.version_key('2.1.325'), P.version_key('2.1.99'))
        self.assertEqual(P.version_key(''), ())


class BotModelTest(unittest.TestCase):
    def test_default_model_only_for_default_provider(self):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d))
            store.data['settings'].update(provider='claude', model='sonnet')
            self.assertEqual(server.bot_model(store, {'provider': '', 'model': ''}), ('claude', 'sonnet'))
            self.assertEqual(server.bot_model(store, {'provider': 'codex', 'model': ''}), ('codex', ''))
            self.assertEqual(server.bot_model(store, {'provider': 'codex', 'model': 'gpt-6-luna'}), ('codex', 'gpt-6-luna'))


class ProviderUsageTest(unittest.TestCase):
    def test_windows(self):
        import datetime as dt
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d)); bot = store.data['bots'][0]['id']
            ago = lambda hours: (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()
            store.data['jobs'] += [
                dict(id='a', botId=bot, finishedAt=ago(1), usage=dict(input=100, output=10, provider='grok', costUsd=0.5)),
                dict(id='b', botId=bot, finishedAt=ago(30), usage=dict(input=1000, output=0, provider='grok', costUsd=1.0)),
                dict(id='c', botId=bot, finishedAt=ago(24 * 9), usage=dict(input=7, output=7, provider='grok', costUsd=9.0)),
                dict(id='d', botId=bot, finishedAt=ago(1), usage=dict(input=5, output=5, provider='codex', costUsd=None))]
            u = server.provider_usage(store, 'grok')
            self.assertEqual(u['fiveHour'], {'replies': 1, 'tokens': 110, 'costUsd': 0.5})
            self.assertEqual(u['week'], {'replies': 2, 'tokens': 1110, 'costUsd': 1.5})
            self.assertEqual(server.provider_usage(store, 'codex')['week'], {'replies': 1, 'tokens': 10, 'costUsd': None})


class BotUsageTest(unittest.TestCase):
    def test_aggregates_per_bot(self):
        with tempfile.TemporaryDirectory() as d:
            store = server.Store(Path(d))
            a, b = store.data['bots'][0], store.data['bots'][1]
            now = server.NOW()
            store.data['jobs'] += [
                dict(id='1', botId=a['id'], status='completed', finishedAt=now, usage=dict(input=100, cachedInput=40, output=10, model='m1', provider='codex', costUsd=None)),
                dict(id='2', botId=a['id'], groupId='g', status='completed', finishedAt=now, usage=dict(input=50, cachedInput=0, output=5, model='m2', provider='claude', costUsd=0.01)),
                dict(id='3', botId=b['id'], status='completed', finishedAt=now, usage=dict(input=1, cachedInput=0, output=1, model='m1', provider='codex', costUsd=None)),
                dict(id='4', botId=b['id'], status='completed', finishedAt=now)]
            r = server.bot_usage(store)
            top = r['bots'][0]
            self.assertEqual((top['name'], top['replies'], top['groupReplies'], top['input'], top['output'], top['costUsd']), (a['name'], 2, 1, 150, 15, 0.01))
            self.assertEqual(top['daily'][r['days'][-1]], 165)
            self.assertEqual(set(top['models']), {'codex · m1', 'claude · m2'})
            self.assertIsNone(r['bots'][1]['costUsd'])
            self.assertEqual(r['untracked'], 1)


if __name__ == '__main__': unittest.main()
