import datetime as dt
import unittest
from unittest.mock import Mock
import token_first as tf

NOW=dt.datetime(2026,11,20,20,tzinfo=dt.timezone.utc)
ADDR='0x'+'a'*40
ADDR2='0x'+'b'*40
SOL='7YttLkHDoK5e8H3A3FdH8cyW9SPo9yNWGvY3Cb8Ecdpc'

def profile(chain='base',address=ADDR,links=None):
    return {'chainId':chain,'tokenAddress':address,'description':'new infrastructure','links':links or []}

def pair(address=ADDR,liquidity=100000):
    return {'chainId':'base','baseToken':{'address':address,'symbol':'NEW','name':'New project'},
      'liquidity':{'usd':liquidity},'marketCap':9000000,'volume':{'h24':100000},
      'priceChange':{'h24':5},'pairCreatedAt':int(NOW.timestamp()*1000)-8*3600000,
      'url':'https://dexscreener.com/base/pair'}

class TokenFirstTests(unittest.TestCase):
    def test_valid_chains_and_contracts(self):
        self.assertTrue(tf.valid_token('base',ADDR))
        self.assertTrue(tf.valid_token('solana',SOL))
        self.assertFalse(tf.valid_token('base','not-a-contract'))
        self.assertFalse(tf.valid_token('bsc',ADDR))
    def test_case_insensitive_evm_identity(self):
        self.assertEqual(tf.token_key('ethereum',ADDR.upper().replace('0X','0x')),tf.token_key('ethereum',ADDR))
    def test_source_dedup(self):
        got=tf.collect_sources([profile()],[profile()])
        self.assertEqual(len(got),1)
        self.assertEqual(got['base:'+ADDR]['discovery_sources'],['recent_profile','paid_boost'])
    def test_paid_boost_not_credibility(self):
        got=tf.collect_sources([],[profile()]);v=list(got.values())[0]
        self.assertEqual(v['discovery_sources'],['paid_boost'])
    def test_ignore_invalid_rows(self):
        self.assertEqual(tf.collect_sources([{'chainId':'base','tokenAddress':'fake'},None],[]),{})
    def test_reject_unexpected_source_payload(self):
        with self.assertRaises(ValueError):tf.collect_sources({},[])
    def test_exact_contract_and_chain(self):
        self.assertIsNotNone(tf.find_market([pair(ADDR2),pair(ADDR)],'base',ADDR))
        self.assertIsNone(tf.find_market([pair(ADDR2)],'base',ADDR))
        self.assertIsNone(tf.find_market([pair(ADDR)],'ethereum',ADDR))
    def test_low_liquidity_review(self):
        status,issues=tf.triage(tf.find_market([pair(liquidity=10)],'base',ADDR),NOW)
        self.assertEqual(status,'MARKET_RESEARCH_REVIEW')
        self.assertTrue(issues)
    def test_good_market_is_research_only(self):
        status,issues=tf.triage(tf.find_market([pair()],'base',ADDR),NOW)
        self.assertEqual(status,'MARKET_RESEARCH_PRIORITY_UNVERIFIED')
        self.assertEqual(issues,[])
    def test_missing_market_does_not_promote(self):
        status,_=tf.triage(None,NOW);self.assertEqual(status,'NO_VERIFIABLE_TRADING_PAIR')
    def test_rotates_new_first(self):
        entries=tf.collect_sources([profile(address=ADDR),profile(address=ADDR2)],[])
        selected=tf.choose(entries,{'base:'+ADDR:{'last_checked_at':'now'}},1)
        self.assertEqual(selected[0]['contract'],ADDR2)
    def test_end_to_end_no_approval(self):
        s=Mock()
        def get(url,**kw):
            r=Mock();r.raise_for_status.return_value=None
            if url.endswith('token-profiles/latest/v1'):r.json.return_value=[profile()]
            elif url.endswith('token-boosts/latest/v1'):r.json.return_value=[profile()]
            else:r.json.return_value=[pair()]
            return r
        s.get.side_effect=get
        state,report=tf.scan(s,{},NOW)
        self.assertEqual(report['completed'],1)
        self.assertEqual(report['buy_approved'],0)
        item=state['entries']['base:'+ADDR]
        self.assertFalse(item['buy_approved'])
        self.assertFalse(item['exceptional_signal_approved'])
        self.assertFalse(item['project_token_link_verified'])
        self.assertTrue(item['promotion_is_not_endorsement'])
    def test_partial_error_keeps_history(self):
        s=Mock()
        def get(url,**kw):
            if url.endswith('/token-profiles/latest/v1') or url.endswith('/token-boosts/latest/v1'):
                r=Mock();r.raise_for_status.return_value=None;r.json.return_value=[profile()];return r
            raise Exception('unexpected')
        # Use a RequestException as the normal external failure
        import requests
        def fail(url,**kw):
            if 'token-pairs' in url:raise requests.Timeout('secret')
            r=Mock();r.raise_for_status.return_value=None;r.json.return_value=[profile()];return r
        s.get.side_effect=fail
        state,report=tf.scan(s,{'solana:'+SOL:{'buy_approved':True}},NOW)
        self.assertEqual(report['completed'],0)
        self.assertEqual(len(report['errors']),1)
        self.assertFalse(state['entries']['solana:'+SOL]['buy_approved'])
        self.assertNotIn('secret',str(report))
    def test_missing_market_cap_does_not_invent(self):
        p=pair();p.pop('marketCap')
        v=tf.find_market([p],'base',ADDR)
        self.assertIsNone(v['market_cap_usd'])
        self.assertEqual(tf.triage(v,NOW)[0],'MARKET_RESEARCH_REVIEW')

if __name__=='__main__':unittest.main()
