import datetime as dt
import unittest
from unittest.mock import Mock
import token_watch_alerts as w

NOW=dt.datetime(2026,11,20,23,tzinfo=dt.timezone.utc)
CONTRACT='0x'+'a'*40
KEY='base:'+CONTRACT

def item(**kwargs):
    r={'chain':'base','contract':CONTRACT,
       'profile_description':'Protocol for stablecoin risk management with public documentation',
       'declared_links':['https://example.org/docs'],
       'market':{'symbol':'AAA','name':'Example','liquidity_usd':250000,
         'volume_24h_usd':75000,'market_cap_usd':1000000,
         'price_change_24h_pct':1,'pair_created_at_ms':int(NOW.timestamp()*1000)-5*3600000,
         'pair_url':'https://dexscreener.com/base/sample'},
        'triage_status':'MARKET_RESEARCH_PRIORITY_UNVERIFIED',
        'promotion_is_not_endorsement':True}
    return {**r,**kwargs}

class TokenWatchTests(unittest.TestCase):
    def test_passing_market(self):
        self.assertEqual(w.assess(item(),NOW),(True,[]))
    def test_no_contract_rejected(self):
        ok,why=w.assess(item(contract='not_a_contract'),NOW)
        self.assertFalse(ok)
    def test_no_market_rejected(self):
        self.assertFalse(w.assess(item(market=None),NOW)[0])
    def test_missing_capitalization(self):
        r=item();r['market']['market_cap_usd']=None
        self.assertFalse(w.assess(r,NOW)[0])
    def test_low_liquidity(self):
        r=item();r['market']['liquidity_usd']=99999
        self.assertFalse(w.assess(r,NOW)[0])
    def test_low_volume(self):
        r=item();r['market']['volume_24h_usd']=30000
        self.assertFalse(w.assess(r,NOW)[0])
    def test_pumped(self):
        r=item();r['market']['price_change_24h_pct']=75
        self.assertFalse(w.assess(r,NOW)[0])
    def test_old_pool(self):
        r=item();r['market']['pair_created_at_ms']=int(NOW.timestamp()*1000)-20*24*3600000
        self.assertFalse(w.assess(r,NOW)[0])
    def test_unknown_pool_disclosed(self):
        r=item();r['market']['pair_created_at_ms']=None
        self.assertTrue(w.assess(r,NOW)[0])
        self.assertIn('NON VÉRIFIÉ',w.format_message(KEY,r,NOW))
    def test_no_links_rejected(self):
        self.assertFalse(w.assess(item(declared_links=[]),NOW)[0])
    def test_no_description_rejected(self):
        self.assertFalse(w.assess(item(profile_description=''),NOW)[0])
    def test_no_buy_claim(self):
        msg=w.format_message(KEY,item(),NOW)
        self.assertIn('PAS UN BUY',msg)
        self.assertIn('CRITÈRES NON VÉRIFIÉS',msg)
        self.assertIn(CONTRACT,msg)
    def test_simulated_never_contacts_telegram_or_dedups(self):
        session=Mock()
        state,rep=w.process({KEY:item()},{},NOW,session,dry_run=True)
        self.assertEqual(rep['simulated'],1)
        self.assertEqual(state['sent'],{})
        session.post.assert_not_called()
    def test_send_marks_once_only_after_success(self):
        session=Mock();session.post.return_value.json.return_value={'ok':True}
        state,rep=w.process({KEY:item()},{},NOW,session,token='bot-token',chat='123',dry_run=False)
        self.assertEqual(rep['delivered'],1)
        self.assertIn(KEY,state['sent'])
        _,rep2=w.process({KEY:item()},state,NOW,session,token='bot-token',chat='123',dry_run=False)
        self.assertEqual(rep2['delivered'],0)
        self.assertEqual(session.post.call_count,1)
    def test_error_does_not_mark_or_leak_key(self):
        session=Mock();session.post.side_effect=Exception('token')
        # Network exceptions raised by requests are contained and sanitized.
        import requests
        session.post.side_effect=requests.Timeout('SENSITIVE')
        state,rep=w.process({KEY:item()},{},NOW,session,token='SENSITIVE',chat='123',dry_run=False)
        self.assertEqual(rep['delivered'],0)
        self.assertNotIn(KEY,state['sent'])
        self.assertNotIn('SENSITIVE',str(rep))
    def test_dedup_selection(self):
        self.assertEqual(w.select({KEY:item()},{KEY:'2026'},NOW),[])
    def test_no_price_data(self):
        r=item();r['market']['price_change_24h_pct']=None
        self.assertFalse(w.assess(r,NOW)[0])

if __name__=='__main__': unittest.main()
