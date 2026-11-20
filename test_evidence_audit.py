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

if __name__=='__main__':
    unittest.main()
