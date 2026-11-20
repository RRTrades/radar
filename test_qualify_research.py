import unittest
import qualify_research as q


def repo(name, description, topic):
    return {'repository': name, 'repository_url': f'https://github.com/{name}',
            'description': description, 'topics_to_review': [topic]}


class QualifierTests(unittest.TestCase):
    def test_relevant_agent_payment_is_still_unverified(self):
        result = q.classify(repo('sample/agent-pay', 'Onchain agent payments using x402', 'agent-payments'))
        self.assertEqual(result['triage_status'], 'RESEARCH_PRIORITY_UNVERIFIED')
        self.assertFalse(result['buy_approved'])
        self.assertTrue(all(x == 'NOT_VERIFIED' for x in result['fundamental_proofs'].values()))

    def test_learning_repo_excluded(self):
        self.assertEqual(q.classify(repo('user/blockchain-learning', 'Learning journey blockchain crypto', 'onchain-risk'))['triage_status'],
                         'LOW_PRIORITY_EXCLUSION_REVIEWABLE')

    def test_testnet_demo_excluded(self):
        x = q.classify(repo('lab/stablecoin', 'Stablecoin testnet only; no real money', 'stablecoin-resilience'))
        self.assertIn('demo_or_simulation', x['exclusion_indicators'])

    def test_unrelated_privacy_product_excluded(self):
        x = q.classify(repo('org/photo-app', 'Photo library for macOS productivity with zero-knowledge privacy', 'privacy-compliance'))
        self.assertEqual(x['triage_status'], 'LOW_PRIORITY_EXCLUSION_REVIEWABLE')

    def test_missing_topic_confirmation_not_priority(self):
        x = q.classify(repo('org/blockchain', 'Blockchain protocol for land titles', 'oracle-integrity'))
        self.assertEqual(x['triage_status'], 'UNCONFIRMED_RELEVANCE')

    def test_missing_description_excluded(self):
        x = q.classify(repo('org/something', '', 'mev-execution'))
        self.assertEqual(x['triage_status'], 'LOW_PRIORITY_EXCLUSION_REVIEWABLE')

    def test_unmapped_topic_not_automatically_qualified(self):
        x = q.classify(repo('org/new-tech', 'Onchain infrastructure for verification', 'UNMAPPED_NEW_TOPIC_REVIEW_REQUIRED'))
        self.assertEqual(x['triage_status'], 'UNCONFIRMED_RELEVANCE')

    def test_missing_repo_url_excluded(self):
        x = q.classify({'repository': 'some/thing', 'repository_url': 'http://bad.example', 'description': 'DeFi wallet', 'topics_to_review': ['wallet-usability']})
        self.assertIn('repository_identity_missing', x['exclusion_indicators'])

    def test_aggregation_never_approves_buy(self):
        result = q.qualify({'project_research_queue': {'a': repo('org/agent', 'Autonomous agent x402 payments blockchain', 'agent-payments'),
                                                        'b': repo('org/course', 'Educational blockchain tutorial', 'wallet-usability')}})
        self.assertEqual(result['source_count'], 2)
        self.assertEqual(result['qualified_count'], 2)
        self.assertEqual(result['counts']['RESEARCH_PRIORITY_UNVERIFIED'], 1)
        self.assertEqual(result['buy_approved'], 0)
        self.assertTrue(all(not x['buy_approved'] for x in result['entries']))

    def test_empty_queue(self):
        result = q.qualify({'project_research_queue': {}})
        self.assertEqual(result['qualified_count'], 0)

    def test_invalid_queue_is_error(self):
        with self.assertRaises(ValueError):
            q.qualify({'project_research_queue': []})


if __name__ == '__main__':
    unittest.main()
