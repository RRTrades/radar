import unittest
from unittest.mock import Mock
import requests
import evidence_audit as ea


def row(repo, status='RESEARCH_PRIORITY_UNVERIFIED'):
    return {'repository': repo, 'triage_status': status}

class EvidenceAuditTests(unittest.TestCase):
    def test_priority_only(self):
        data = {'entries': [row('a/one', 'UNCONFIRMED_RELEVANCE'), row('a/two'), row('a/three')]}
        self.assertEqual(ea.choose_candidates(data, 1), ['a/two'])

    def test_no_duplicate(self):
        self.assertEqual(ea.choose_candidates({'entries': [row('A/one'), row('a/one')]}), ['A/one'])

    def test_invalid_repo_name_rejected(self):
        self.assertEqual(ea.choose_candidates({'entries': [row('../bad'), row('a/good')]}), ['a/good'])

    def test_malformed_input_fails(self):
        with self.assertRaises(ValueError):
            ea.choose_candidates({'entries': {}})

    def test_evidence_does_not_approve(self):
        v = ea.analyze_evidence('org/proj', {'html_url':'https://github.com/org/proj','stargazers_count':3},
            [{'name':'README.md'},{'name':'src'},{'name':'tests'},{'name':'Cargo.toml'}],
            [{'html_url':'https://github.com/org/proj/commit/123'}], '2026-11-20T20:00:00+00:00')
        self.assertTrue(v['observables']['has_tests_directory_at_root'])
        self.assertTrue(v['observables']['has_source_directory_at_root'])
        self.assertFalse(v['buy_approved'])
        self.assertEqual(set(v['fundamental_proofs'].values()), {'NOT_VERIFIED'})

    def test_empty_repo_is_not_verified(self):
        v = ea.analyze_evidence('org/proj', {'html_url':'https://github.com/org/proj'}, [], [], 'now')
        self.assertFalse(v['observables']['has_build_manifest_at_root'])
        self.assertFalse(v['token_contract_verified'])

    def test_identity_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            ea.analyze_evidence('org/proj', {'html_url':'https://github.com/not/proj'}, [], [], 'now')

    def test_empty_queue_no_api_calls(self):
        v=ea.collect({'entries':[]},session=Mock(),delay=0)
        self.assertEqual(v['selected_count'],0)
        self.assertEqual(v['approved_for_buy'],0)

    def test_api_failure_does_not_expose_secret(self):
        session=Mock()
        session.get.side_effect=requests.ConnectionError('SENSITIVE-TOKEN')
        with self.assertRaises(RuntimeError) as x:
            ea.fetch_json(session, 'https://api.github.com/repos/o/r', 'SENSITIVE-TOKEN')
        self.assertNotIn('SENSITIVE-TOKEN',str(x.exception))

    def test_partial_failure_reported(self):
        session=Mock()
        session.get.side_effect=requests.Timeout('failure')
        data=ea.collect({'entries':[row('org/repo')]},session=session,delay=0)
        self.assertEqual(data['error_count'],1)
        self.assertEqual(data['audited_count'],0)
        self.assertEqual(data['approved_for_buy'],0)

    def test_rotation_skips_previously_audited(self):
        data = {'entries': [row('a/one'), row('a/two'), row('a/three')]}
        history = {'entries': [{'repository': 'a/one', 'audited_at_utc': '2026-11-19T00:00:00+00:00'}]}
        self.assertEqual(ea.choose_candidates(data, 2, history), ['a/two', 'a/three'])

    def test_rotation_oldest_first_when_exhausted(self):
        data = {'entries': [row('a/one'), row('a/two')]}
        history = {'entries': [
            {'repository': 'a/one', 'audited_at_utc': '2026-11-19T00:00:00+00:00'},
            {'repository': 'a/two', 'audited_at_utc': '2026-11-20T00:00:00+00:00'}]}
        self.assertEqual(ea.choose_candidates(data, 1, history), ['a/one'])

    def test_invalid_nested_traversal_rejected(self):
        data = {'entries': [row('good/..'), row('../bad'), row('good/ok')]}
        self.assertEqual(ea.choose_candidates(data), ['good/ok'])

    def test_history_survives_api_errors_without_approving_buy(self):
        old = {'entries': [{'repository': 'org/old',
                            'audited_at_utc': '2026-11-19T00:00:00+00:00',
                            'buy_approved': True}]}
        s = Mock()
        s.get.side_effect = requests.Timeout('no access')
        result = ea.collect({'entries':[row('org/new')]}, session=s, delay=0, previous=old)
        self.assertEqual(result['audited_count'], 0)
        self.assertEqual(result['error_count'], 1)
        self.assertEqual(result['total_audited_unique'], 1)
        self.assertEqual(result['remaining_unaudited_priority'], 1)
        self.assertFalse(result['entries'][0]['buy_approved'])

    def test_validated_audit_record_replaces_old(self):
        old = {'entries': [{'repository': 'org/repo',
                            'audited_at_utc': '2026-11-19T00:00:00+00:00'}]}
        session=Mock()
        session.get.side_effect = [
            Mock(**{'json.return_value': {'html_url': 'https://github.com/org/repo'},
                    'raise_for_status.return_value': None}),
            Mock(**{'json.return_value': [{'name':'README.md'}],
                    'raise_for_status.return_value': None}),
            Mock(**{'json.return_value': [],
                    'raise_for_status.return_value': None}),
        ]
        result = ea.collect({'entries':[row('org/repo')]}, session=session, delay=0, previous=old)
        self.assertEqual(result['audited_count'], 1)
        self.assertEqual(result['total_audited_unique'], 1)
        self.assertEqual(result['remaining_unaudited_priority'], 0)
        self.assertFalse(result['entries'][0]['buy_approved'])

if __name__=='__main__':
    unittest.main()
