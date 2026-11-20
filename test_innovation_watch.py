import datetime as dt
import unittest
from unittest.mock import Mock, patch
import innovation_watch as iw


class FakeClient:
    def __init__(self, repos=None, alternatives=None, issues=None, error_kind=None):
        self.repos = repos if repos is not None else []
        self.alternatives = alternatives if alternatives is not None else []
        self.issues = issues if issues is not None else []
        self.error_kind = error_kind
        self.calls = []

    def search(self, kind, query, count=10, sort='updated'):
        self.calls.append((kind, query, count, sort))
        if self.error_kind == kind:
            raise RuntimeError('GitHub API down')
        if kind == 'issues':
            return self.issues
        if sort == 'stars':
            return self.alternatives
        return self.repos


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.timezone.utc)
        self.repo = {
            'full_name': 'sample/privacy-lab',
            'html_url': 'https://github.com/sample/privacy-lab',
            'description': 'Privacy primitive for confidential payments',
            'homepage': 'https://example.org',
            'created_at': '2026-11-05T11:00:00Z',
            'pushed_at': '2026-11-19T10:00:00Z',
            'fork': False,
            'archived': False,
            'stargazers_count': 8,
        }
        self.issue = {
            'html_url': 'https://github.com/sample/protocol/issues/9',
            'title': 'Private transfer feature is broken',
            'created_at': '2026-11-10T09:00:00Z',
            'state': 'open',
        }
        self.problems = [{'id':'privacy-compliance', 'problem':'Confidentialité',
                          'keywords':['privacy']}]

    def test_valid_candidate_is_unverified(self):
        c = iw.candidate_from_repo(self.repo, 'privacy-compliance', self.now)
        self.assertEqual(c['status'], 'UNVERIFIED_RESEARCH_LEAD')
        self.assertEqual(c['innovation_assessment'], 'NOT_DONE')
        self.assertEqual(c['token_status'], 'UNKNOWN_NOT_CHECKED')

    def test_older_repo_rejected(self):
        r = dict(self.repo, created_at='2019-11-20T11:00:00Z')
        self.assertIsNone(iw.candidate_from_repo(r, 'privacy-compliance', self.now))

    def test_fork_and_archived_rejected(self):
        for field in ('fork', 'archived'):
            with self.subTest(field=field):
                r = dict(self.repo, **{field:True})
                self.assertIsNone(iw.candidate_from_repo(r, 'privacy-compliance', self.now))

    def test_dedup_preserves_first_seen(self):
        q = {}
        self.assertTrue(iw.merge_candidate(q,self.repo, 'privacy-compliance', self.now))
        first = q[self.repo['full_name']]['first_seen']
        second = self.now + dt.timedelta(days=1)
        self.assertFalse(iw.merge_candidate(q, self.repo, 'onchain-risk', second))
        self.assertEqual(q[self.repo['full_name']]['first_seen'], first)
        self.assertEqual(q[self.repo['full_name']]['topics_to_review'],
                         ['onchain-risk', 'privacy-compliance'])

    def test_rejection_not_overridden(self):
        q = {}
        iw.merge_candidate(q, self.repo, 'privacy-compliance', self.now)
        q[self.repo['full_name']]['status'] = 'REVIEWED_REJECTED'
        iw.merge_candidate(q, self.repo, 'privacy-compliance', self.now)
        self.assertEqual(q[self.repo['full_name']]['status'], 'REVIEWED_REJECTED')

    def test_open_issue_only_evidence_not_confirmation(self):
        v = iw.issue_from_api(self.issue, 'privacy-compliance', self.now)
        self.assertEqual(v['status'], 'UNVERIFIED_PROBLEM_EVIDENCE')
        self.assertIn('NOT established', v['finding'])
        closed = dict(self.issue, state='closed')
        self.assertIsNone(iw.issue_from_api(closed, 'privacy-compliance', self.now))
        pr = dict(self.issue, pull_request={})
        self.assertIsNone(iw.issue_from_api(pr, 'privacy-compliance', self.now))

    def test_collect_creates_non_buy_queue(self):
        state = {}
        client = FakeClient(repos=[self.repo], issues=[self.issue], alternatives=[self.repo])
        report = iw.collect(self.problems, client, state, self.now, open_discovery=False)
        self.assertEqual(report['new_research_leads'], 1)
        self.assertEqual(report['new_problem_evidence'], 1)
        self.assertEqual(report['approved_for_buy'], 0)
        self.assertEqual(report['github_queries'], 3)
        self.assertEqual(state['problem_landscape']['privacy-compliance']['status'],
                         'UNRESOLVED_NOT_ESTABLISHED')
        self.assertNotIn('alerted', state)

    def test_collect_idempotent_and_no_promotion(self):
        state = {}
        client = FakeClient(repos=[self.repo], issues=[self.issue])
        iw.collect(self.problems, client, state, self.now, open_discovery=False)
        report = iw.collect(self.problems, client, state, self.now, open_discovery=False)
        self.assertEqual(report['new_research_leads'], 0)
        self.assertEqual(report['new_problem_evidence'], 0)

    def test_partial_api_failure_is_explicit(self):
        client = FakeClient(repos=[self.repo], error_kind='issues')
        report = iw.collect(self.problems, client, {}, self.now, open_discovery=False)
        self.assertEqual(report['new_research_leads'], 1)
        self.assertTrue(report['source_errors'])

    def test_missing_problem_mapping_reports_configuration_gap(self):
        unknown = [{'id':'new-hypothesis','problem':'Unknown technical failure'}]
        report = iw.collect(unknown, FakeClient(), {}, self.now, open_discovery=False)
        self.assertEqual(report['github_queries'], 0)
        self.assertIn('configuration', str(report['source_errors']))

    def test_unmapped_discoveries_are_review_only(self):
        state = {}
        report = iw.collect([], FakeClient(repos=[self.repo]), state, self.now,
                            open_discovery=True)
        key = self.repo['full_name']
        self.assertEqual(report['new_research_leads'], 1)
        self.assertEqual(state['project_research_queue'][key]['topics_to_review'],
                         ['UNMAPPED_NEW_TOPIC_REVIEW_REQUIRED'])

    def test_keep_recent_bounded(self):
        q = {str(i): {'last_seen': f'2026-11-{i+1:02}'} for i in range(7)}
        self.assertEqual(len(iw.keep_recent(q, 3)), 3)
        self.assertEqual(list(iw.keep_recent(q, 3)), ['6','5','4'])

    def test_safe_query_api_rejects_bad_kind(self):
        client = iw.GitHubResearch(token='test', delay=0)
        with self.assertRaises(ValueError):
            client.search('trade', 'anything')

    def test_github_error_does_not_leak_token(self):
        mock_session = Mock()
        mock_session.headers = {}
        mock_session.get.side_effect = RuntimeError('mock error')
        # RuntimeError from mocked session is outside requests documented errors;
        # use a real requests exception for the sanitization test.
        import requests
        mock_session.get.side_effect = requests.ConnectionError('do not echo SECRET-TOKEN')
        client = iw.GitHubResearch(token='SECRET-TOKEN', delay=0, session=mock_session)
        with self.assertRaises(RuntimeError) as ctx:
            client.search('issues','example')
        self.assertNotIn('SECRET-TOKEN', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
