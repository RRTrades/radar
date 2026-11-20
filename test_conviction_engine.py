import datetime as dt
import unittest
from unittest.mock import Mock
import requests
import conviction_engine as c
NOW=dt.datetime(2026,11,20,23,tzinfo=dt.timezone.utc)
CONTRACT='0x'+'a'*40
KEY='base:'+CONTRACT

def row():
    return {'chain':'base','contract':CONTRACT,'declared_links':['https://example.org'],
        'profile_description':'Example','market':{'pair_url':'https://dexscreener.com/base/sample',
        'symbol':'XXX','liquidity_usd':200000,'volume_24h_usd':100000,
        'market_cap_usd':1000000,'price_change_24h_pct':5,
        'pair_created_at_ms':int(NOW.timestamp()*1000)-3600000}}

class ConvictionTests(unittest.TestCase):
    def test_valid_identity(self):
        self.assertTrue(c.valid_token(row()))
        self.assertFalse(c.valid_token({**row(),'contract':'bad'}))
    def test_exclusions_all_gates(self):
        r=c.evaluate(row(),{'status':'PARTIAL_PASS','reasons':[]},NOW)
        self.assertEqual(len(r['fundamental_gates']),12)
        self.assertEqual(r['decision'],'WATCH_UNVERIFIED')
        self.assertFalse(r['buy_approved'])
        self.assertFalse(r['exceptional_signal_approved'])
    def test_famous_claim_cannot_override(self):
        r=row();r['profile_description']='Founded by Vitalik, backed by a famous investor'
        r['developer_verified']=True;r['investor_verified']=True
        v=c.evaluate(r,{'status':'RISK','reasons':['honeypot']},NOW)
        self.assertEqual(v['reputation']['status'],'NOT_VERIFIED')
        self.assertFalse(v['exceptional_signal_approved'])
        self.assertTrue(any('Sécurité' in s for s in v['exclusions']))
    def test_no_pair_rejected(self):
        r=row();r['market']['pair_url']=None
        self.assertEqual(c.evaluate(r,{'status':'UNKNOWN'},NOW)['decision'],'REJECT')
    def test_low_liquidity_rejected(self):
        r=row();r['market']['liquidity_usd']=100
        self.assertEqual(c.evaluate(r,{'status':'PARTIAL_PASS'},NOW)['decision'],'REJECT')
    def test_missing_age_is_exclusion(self):
        r=row();r['market']['pair_created_at_ms']=None
        self.assertIn('Âge du pool inconnu',c.evaluate(r,{'status':'UNKNOWN'},NOW)['exclusions'])
    def test_security_missing_results_fails_closed(self):
        s=Mock();s.get.return_value.json.return_value={'result':{}}
        self.assertEqual(c.security_fetch(s,row())['status'],'UNKNOWN')
    def test_honeypot_is_risk(self):
        s=Mock();s.get.return_value.json.return_value={'result':{CONTRACT:{'is_honeypot':'1'}}}
        self.assertEqual(c.security_fetch(s,row())['status'],'RISK')
    def test_security_partial_pass(self):
        s=Mock();s.get.return_value.json.return_value={'result':{CONTRACT:{
            'is_honeypot':'0','hidden_owner':'0','is_mintable':'0','is_open_source':'1',
            'buy_tax':'0.01','sell_tax':'0.02'}}}
        self.assertEqual(c.security_fetch(s,row())['status'],'PARTIAL_PASS')
    def test_api_failure_no_secret(self):
        s=Mock();s.get.side_effect=requests.Timeout('sensitive-token')
        self.assertNotIn('sensitive-token',str(c.security_fetch(s,row())))
    def test_rotates(self):
        r=row(); r2={**row(),'contract':'0x'+'b'*40}
        chosen=c.choose({KEY:r,c.token_key(r2):r2},{KEY:{}},1)
        self.assertEqual(chosen[0][0],c.token_key(r2))
    def test_history_cannot_authorize(self):
        fake={KEY:{'assessment':{'decision':'BUY_VALIDATED','buy_approved':True,
                                   'exceptional_signal_approved':True}}}
        state,rep=c.scan({'entries':{}},{'entries':fake},NOW,Mock())
        a=state['entries'][KEY]['assessment']
        self.assertFalse(a['buy_approved']);self.assertFalse(a['exceptional_signal_approved'])
        self.assertEqual(a['decision'],'WATCH_UNVERIFIED')
        self.assertEqual(rep['decisions']['BUY_VALIDATED'],0)
    def test_real_selection_no_fake_buy(self):
        s=Mock();s.get.side_effect=requests.Timeout('down')
        state,rep=c.scan({'entries':{KEY:row()}},{},NOW,s)
        self.assertEqual(rep['selected'],1)
        self.assertEqual(rep['decisions']['WATCH_UNVERIFIED'],1)
        self.assertEqual(rep['telegram_buy_sent'],0)
    def test_empty(self):
        state,rep=c.scan({'entries':{}},{},NOW,Mock())
        self.assertEqual(rep['selected'],0)
        self.assertEqual(state['entries'],{})

if __name__=='__main__': unittest.main()
