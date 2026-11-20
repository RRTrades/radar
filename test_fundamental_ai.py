import datetime as dt
import json
import unittest
from unittest.mock import Mock
import fundamental_ai as ai

NOW=dt.datetime(2026,11,20,22,tzinfo=dt.timezone.utc)
REPO='sample/bridge'

def samples():
    q={'entries':[{'repository':REPO,'triage_status':'RESEARCH_PRIORITY_UNVERIFIED',
                   'description':'Cross-chain bridge','topics':['crosschain-fragmentation']}]}
    a={'entries':[{'repository':REPO,'repository_url':'https://github.com/'+REPO,
                   'observables':{'has_source_directory_at_root':True,'has_build_manifest_at_root':True},
                   'evidence_links':['https://github.com/'+REPO]}]}
    return q,a

def raw():
    return {'summary':'unproven','gates':{key:{'status':'INSUFFICIENT_EVIDENCE',
            'citations':[],'rationale':'unknown','missing_evidence':'independent metrics'} for key in ai.GATES}}

class ResearchTests(unittest.TestCase):
    def test_repo_validation(self):
        for p in ('../bad','a/..','a/b/other','-','a//b',''):
            self.assertFalse(ai.valid_repo(p))
        self.assertTrue(ai.valid_repo('Org/a_repo.v2'))

    def test_choose_only_audited_technical(self):
        q,a=samples()
        self.assertEqual(len(ai.choose(q,a,{},NOW)),1)
        a['entries'][0]['observables']={}
        self.assertEqual(ai.choose(q,a,{},NOW),[])

    def test_recent_stored_not_reanalysed(self):
        q,a=samples()
        self.assertEqual(ai.choose(q,a,{'entries':{REPO:{'analyzed_at_utc':NOW.isoformat()}}},NOW),[])

    def test_invalid_json_rejected(self):
        with self.assertRaises(ValueError):
            ai.validate_assessment({'gates':{}},[])

    def test_invented_citation_rejected(self):
        obj=raw();obj['gates']['unresolved_problem']['citations']=['https://fake.site/proof']
        with self.assertRaises(ValueError):
            ai.validate_assessment(obj,['https://github.com/sample/bridge'])

    def test_no_approval_even_good_response(self):
        obj=raw()
        for v in obj['gates'].values():v['status']='POSSIBLE'
        result=ai.validate_assessment(obj,[])
        self.assertEqual(result['gates']['technical_superiority']['status'],'POSSIBLE')

    def test_missing_key_fails_closed(self):
        q,a=samples()
        with self.assertRaises(ValueError):
            ai.run(q,a,{}, {},'', '',Mock(),NOW)

    def test_end_to_end_mocked_still_not_buy(self):
        q,a=samples()
        s=Mock()
        get=Mock();get.status_code=404
        s.get.return_value=get
        post=Mock();post.status_code=200
        post.json.return_value={'choices':[{'message':{'content':json.dumps(raw())}}]}
        s.post.return_value=post
        state,report=ai.run(q,a,{}, {},'secret','',s,NOW,sleep_fn=lambda _:None)
        self.assertEqual(report['completed'],1)
        self.assertFalse(state['entries'][REPO]['buy_approved'])
        self.assertTrue(all(v=='NOT_VERIFIED' for v in state['entries'][REPO]['fundamental_proofs'].values()))
        self.assertNotIn('secret',json.dumps(report))

    def test_429_avoids_repeated_calls(self):
        q,a=samples();s=Mock();s.get.return_value=Mock(status_code=404)
        s.post.return_value=Mock(status_code=429)
        state,report=ai.run(q,a,{}, {},'secret','',s,NOW)
        self.assertEqual(report['completed'],0)
        self.assertEqual(len(report['errors']),1)
        self.assertEqual(state['entries'],{})

    def test_existing_approval_removed(self):
        q,a=samples();q['entries']=[]
        history={'entries':{'old/repo':{'buy_approved':True,'fundamental_proofs':{'unresolved_problem':'VERIFIED'}}}}
        state,report=ai.run(q,a,{},history,'secret','',Mock(),NOW)
        self.assertEqual(report['selected'],0)
        self.assertFalse(state['entries']['old/repo']['buy_approved'])

    def test_missing_readme(self):
        s=Mock();s.get.return_value=Mock(status_code=404)
        self.assertEqual(ai.github_readme(REPO,s),'')

    def test_readme_uses_allowlisted_host(self):
        s=Mock();s.get.return_value=Mock(status_code=404)
        ai.github_readme(REPO,s)
        self.assertTrue(s.get.call_args.args[0].startswith('https://api.github.com/repos/'))

if __name__=='__main__':unittest.main()
