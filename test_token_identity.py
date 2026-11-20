import base64
import unittest
from unittest.mock import Mock
from token_identity import discover_claims, market_match, choose, scan, valid_repo

ADDR='0x'+'a'*40
SOL='7YttLkHDoK5e8H3A3FdH8cyW9SPo9yNWGvY3Cb8Ecdpc'

class TestTokenIdentity(unittest.TestCase):
    def test_repo_validation(self):
        self.assertTrue(valid_repo('org/repo'))
        self.assertFalse(valid_repo('../repo'))
        self.assertFalse(valid_repo('org/..'))
        self.assertFalse(valid_repo('org/repo/extra'))
    def test_explicit_evm_chain(self):
        self.assertEqual(discover_claims('Base token contract address: '+ADDR),[{'chain':'base','contract':ADDR}])
    def test_ambiguous_evm_not_assumed(self):
        self.assertEqual(discover_claims('Token address: '+ADDR),[])
    def test_example_excluded(self):
        self.assertEqual(discover_claims('Base contract address: '+ADDR+' (example)'),[])
    def test_solana_needs_network(self):
        self.assertEqual(discover_claims('Solana mint address: '+SOL),[{'chain':'solana','contract':SOL}])
        self.assertEqual(discover_claims('Mint address: '+SOL),[])
    def test_fenced_code_not_official(self):
        self.assertEqual(discover_claims("```\nBase contract address: "+ADDR+"\n```"), [])
    def test_raw_paste_rejected(self):
        self.assertEqual(discover_claims('Here is '+ADDR),[])
    def test_pair_matches_exact_token(self):
        rows=[{'chainId':'base','baseToken':{'address':ADDR},'liquidity':{'usd':200000},'url':'https://dexscreener.com/base/pair'}]
        self.assertTrue(market_match(rows,'base',ADDR))
        self.assertIsNone(market_match(rows,'ethereum',ADDR))
        self.assertIsNone(market_match(rows,'base','0x'+'b'*40))
    def test_pair_untrusted_payload(self):
        with self.assertRaises(RuntimeError):market_match({'bad':'payload'},'base',ADDR)
    def test_rotation(self):
        rows={'a':{'repository':'org/a'},'b':{'repository':'org/b'}}
        self.assertEqual([r['repository'] for r in choose(rows,{'org/a':{}},1)],['org/b'])
    def test_empty_state_no_approval(self):
        state,report=scan({'entries':{}},{},Mock())
        self.assertEqual(report['buy_approved'],0)
        self.assertEqual(report['selected_count'],0)
    def test_project_claim_cannot_approve(self):
        ai={'entries':{'org/project':{'repository':'org/project'}}}
        mock=Mock()
        readme='Base token contract address: '+ADDR
        def answer(url,**kwargs):
            r=Mock()
            r.status_code=200
            r.raise_for_status.return_value=None
            if url.endswith('/readme'):
                r.json.return_value={'encoding':'base64','content':base64.b64encode(readme.encode()).decode()}
            elif 'token-pairs' in url:
                r.json.return_value=[{'chainId':'base','baseToken':{'address':ADDR},'liquidity':{'usd':50000}}]
            else:raise AssertionError(url)
            return r
        mock.get.side_effect=answer
        state,report=scan(ai,{},mock)
        item=state['entries']['org/project']
        self.assertEqual(report['market_matches'],1)
        self.assertFalse(item['identity_verified'])
        self.assertFalse(item['contract_claims'][0]['buy_approved'])
        self.assertEqual(item['contract_claims'][0]['status'],'PROJECT_CLAIM_AND_MARKET_OBSERVED_NOT_VERIFIED')
    def test_api_errors_fail_closed(self):
        ai={'entries':{'org/project':{'repository':'org/project'}}}
        mock=Mock()
        import requests
        mock.get.side_effect=requests.Timeout('secret')
        state,report=scan(ai,{},mock)
        self.assertEqual(report['error_count'],1)
        self.assertEqual(report['buy_approved'],0)
        self.assertNotIn('secret',str(report))

if __name__=='__main__':unittest.main()
