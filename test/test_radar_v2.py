import datetime as dt
import unittest
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import radar_v2 as r


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 12, tzinfo=dt.timezone.utc)
        self.approval = {
            'name': 'EXAMPLE', 'symbol': 'EXM', 'chain': 'base',
            'contract': '0x' + '1' * 40, 'problem_id': 'crosschain-fragmentation',
            'solution_keywords': ['solution validated'],
            'evidence_urls': ['https://example.org/report', 'https://example.net/audit'],
            'competitor_comparison_url': 'https://example.org/compare',
            'reviewed_at': '2026-11-19T12:00:00+00:00',
            'expires_at': '2026-11-22T12:00:00+00:00',
            'min_liquidity_usd': 100000, 'max_marketcap_usd': 150000000,
            'min_pair_age_hours': 6, 'max_pair_age_hours': 72,
            'max_change_6h_pct': 25, 'max_change_24h_pct': 40,
        }
        self.pair = {
            'chainId': 'base', 'baseToken': {'address': self.approval['contract'], 'symbol': 'EXM'},
            'liquidity': {'usd': 200000}, 'marketCap': 10000000,
            'pairCreatedAt': int(self.now.timestamp() * 1000) - 8 * 3600 * 1000,
            'priceChange': {'h6': 2, 'h24': 10}
        }

    def test_keywords_only_discovery(self):
        hits = r.problem_hits('MEV protection', [{'id': 'mev', 'keywords': ['mev', 'sandwich']}])
        self.assertEqual(hits[0]['id'], 'mev')
        self.assertEqual(len(hits[0]['hits']), 1)

    def test_missing_market_data_rejected(self):
        pair = dict(self.pair)
        pair.pop('marketCap')
        ok, problems, _ = r.market_check(pair, self.approval, int(self.now.timestamp()*1000))
        self.assertFalse(ok)
        self.assertIn('capitalisation inconnue/hors seuil', problems)

    def test_market_rejects_pump(self):
        pair = dict(self.pair, priceChange={'h6': 50, 'h24': 55})
        ok, reasons, _ = r.market_check(pair, self.approval, int(self.now.timestamp()*1000))
        self.assertFalse(ok)
        self.assertIn('hausse de prix excessive', reasons)

    def test_market_accepts_candidate(self):
        ok, reasons, _ = r.market_check(self.pair, self.approval, int(self.now.timestamp()*1000))
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_approval_expired(self):
        approval = dict(self.approval, expires_at='2026-11-18T12:00:00+00:00')
        self.assertIn('validation expirée', r.validate_approval(approval, self.now))

    def test_no_approved_projects_means_no_alerts(self):
        state = {'alerted': {}}
        report = {'rejected': {}, 'alerts_sent': [], 'dry_run_candidates': [], 'errors': []}
        with patch.object(r, 'send_telegram') as send:
            r.monitor([], state, report, self.now, False)
            send.assert_not_called()
        self.assertEqual(report['alerts_sent'], [])

    def test_exact_contract_matching(self):
        payload = [
            dict(self.pair, baseToken={'address': '0x' + '2' * 40}),
            dict(self.pair, baseToken={'address': self.approval['contract']})]
        with patch.object(r, 'fetch_json', return_value=payload):
            pair = r.pair_for_token('base', self.approval['contract'])
        self.assertEqual(pair['baseToken']['address'], self.approval['contract'])

    def test_security_fails_closed_on_missing_fields(self):
        payload = {'result': {self.approval['contract'].lower(): {'is_honeypot': '0'}}}
        with patch.object(r, 'fetch_json', return_value=payload):
            ok, _ = r.security_check('base', self.approval['contract'])
        self.assertFalse(ok)

    def test_sent_only_after_telegram_success(self):
        state = {'alerted': {}}
        report = {'rejected': {}, 'alerts_sent': [], 'dry_run_candidates': [], 'errors': []}
        with patch.object(r, 'pair_for_token', return_value=self.pair), \
             patch.object(r, 'security_check', return_value=(True, 'GoPlus')), \
             patch.object(r, 'send_telegram', return_value=True):
            r.monitor([self.approval], state, report, self.now, False)
        self.assertEqual(len(report['alerts_sent']), 1)
        self.assertEqual(len(state['alerted']), 1)

    def test_failed_telegram_does_not_record_alert(self):
        state = {'alerted': {}}
        report = {'rejected': {}, 'alerts_sent': [], 'dry_run_candidates': [], 'errors': []}
        with patch.object(r, 'pair_for_token', return_value=self.pair), \
             patch.object(r, 'security_check', return_value=(True, 'GoPlus')), \
             patch.object(r, 'send_telegram', side_effect=RuntimeError('send failure')):
            r.monitor([self.approval], state, report, self.now, False)
        self.assertEqual(state['alerted'], {})
        self.assertEqual(len(report['errors']), 1)


if __name__ == '__main__':
    unittest.main()
