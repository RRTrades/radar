#!/usr/bin/env python3
"""Conservative evidence-led decision layer for the token-first radar.

No market observation, promotional statement or LLM output establishes issuer
identity, developer reputation, community authenticity or token value capture.
This version persists explicit exclusions and verified security facts, but cannot
manufacture BUY/exception signals when independent evidence is absent.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sys
import requests

ROOT = Path(__file__).resolve().parent
MAX_LIVE_SECURITY_CHECKS = 4
CHAIN_IDS = {'ethereum':1, 'base':8453, 'polygon':137}
GATES = {
    'project_token_link': 'Lien officiel projet–contrat non corroboré',
    'problem_innovation': 'Problème et innovation non démontrés indépendamment',
    'technical_advantage': 'Supériorité technique non démontrée',
    'competitor_comparison': 'Comparaison concurrentielle non démontrée',
    'team_and_execution': 'Équipe, développeurs et exécution non vérifiés',
    'investors_and_partnerships': 'Investisseurs et partenariats non corroborés',
    'community_authenticity': 'Communauté authentique / engagement organique non vérifiés',
    'adoption_and_retention': 'Adoption, rétention et usage réel non vérifiés',
    'token_value_capture': 'Capture de valeur du token non démontrée',
    'tokenomics_dilution': 'Distribution, inflation et unlocks non vérifiés',
    'valuation': 'Valorisation relative / risque de dilution non étudiés',
    'catalysts_and_timing': 'Catalyseurs et timing non corroborés',
}
ADDR_EVM=re.compile(r'^0x[a-fA-F0-9]{40}$')
ADDR_SOL=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')

def valid_token(row):
    if not isinstance(row,dict): return False
    chain,contract=row.get('chain'),row.get('contract')
    if not isinstance(contract,str): return False
    if chain=='solana': return bool(ADDR_SOL.fullmatch(contract))
    return chain in CHAIN_IDS and bool(ADDR_EVM.fullmatch(contract))

def token_key(row):
    chain,contract=row['chain'],row['contract']
    return chain+':'+(contract if chain=='solana' else contract.lower())

def positive(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>0

def market_risks(row, now):
    m=row.get('market')
    if not isinstance(m,dict) or not isinstance(m.get('pair_url'),str) or not m['pair_url'].startswith('https://dexscreener.com/'):
        return ['Paire de négociation exacte indisponible']
    issues=[]
    liq=m.get('liquidity_usd'); vol=m.get('volume_24h_usd'); cap=m.get('market_cap_usd')
    if not positive(liq) or liq<100_000: issues.append('Liquidité inférieure à 100 000 USD ou inconnue')
    if not positive(vol) or vol<50_000: issues.append('Volume 24h inférieur à 50 000 USD ou inconnu')
    if not positive(cap) or cap>30_000_000: issues.append('Capitalisation supérieure à 30 M USD ou inconnue')
    change=m.get('price_change_24h_pct')
    if not isinstance(change,(int,float)) or isinstance(change,bool) or not math.isfinite(change):
        issues.append('Variation du prix sur 24h inconnue')
    elif change>50: issues.append('Hausse de prix supérieure à 50 % sur 24h')
    created=m.get('pair_created_at_ms')
    if not positive(created): issues.append('Âge du pool inconnu')
    else:
        age=(now.timestamp()*1000-created)/3_600_000
        if not 0 <= age <= 14*24: issues.append('Pool trop ancien ou date incohérente')
    return issues

def security_fetch(session, row, timeout=(5,14)):
    """Bounded independent GoPlus screen. UNKNOWN is never SAFE.

    Does not cover liquidity locks, all owner powers or every attack vector.
    """
    if not valid_token(row): return {'status':'UNKNOWN','reasons':['Contrat invalide']}
    chain,address=row['chain'],row['contract']
    if chain=='solana':
        url='https://api.gopluslabs.io/api/v1/solana/token_security'
    else:
        url=f'https://api.gopluslabs.io/api/v1/token_security/{CHAIN_IDS[chain]}'
    try:
        response=session.get(url,params={'contract_addresses':address},timeout=timeout)
        response.raise_for_status()
        data=response.json()
        results=data.get('result')
        if not isinstance(results,dict): raise ValueError('Missing GoPlus results')
        obj=results.get(address) if chain=='solana' else results.get(address.lower())
        if not isinstance(obj,dict): raise ValueError('Missing contract security results')
        if chain=='solana':
            checks=[]
            for k in ('mintable','freezable'):
                val=obj.get(k)
                if not isinstance(val,dict) or str(val.get('status')) not in ('0','1'):
                    return {'status':'UNKNOWN','reasons':[f'GoPlus Solana : {k} indisponible']}
                checks.append(str(val['status']))
            if '1' in checks:return {'status':'RISK','reasons':['GoPlus Solana : mint/freeze possible']}
            return {'status':'PARTIAL_PASS','reasons':['Contrôle partiel mint/freeze seulement']}
        for key in ('is_honeypot','hidden_owner','is_mintable'):
            val=str(obj.get(key))
            if val not in ('0','1'):
                return {'status':'UNKNOWN','reasons':[f'GoPlus : {key} inconnu']}
            if val=='1':return {'status':'RISK','reasons':[f'GoPlus : {key} risqué']}
        if str(obj.get('is_open_source'))!='1':
            return {'status':'UNKNOWN','reasons':['Code source non confirmé par GoPlus']}
        try:buy,sell=float(obj['buy_tax']),float(obj['sell_tax'])
        except (KeyError,TypeError,ValueError):return {'status':'UNKNOWN','reasons':['Taxes inconnues']}
        if not all(math.isfinite(v) for v in (buy,sell)):
            return {'status':'UNKNOWN','reasons':['Taxes invalides']}
        if max(buy,sell)>0.05 or min(buy,sell)<0:
            return {'status':'RISK','reasons':['Taxes d’achat/vente supérieures à 5 % ou invalides']}
        return {'status':'PARTIAL_PASS','reasons':['Contrôles GoPlus partiels passés ; audit complet absent']}
    except (requests.RequestException,ValueError,TypeError):
        return {'status':'UNKNOWN','reasons':['GoPlus inaccessible ou réponse invalide']}

def evaluate(row,security,now):
    """All claims from token profiles are untrusted; no manual/LLM attestation accepted."""
    if not valid_token(row):
        return {'decision':'REJECT','exclusions':['Blockchain ou contrat invalide'],
            'reputation':{'status':'NOT_VERIFIED','persons':[]},'security':security.get('status','UNKNOWN')}
    missing=list(GATES.values())
    problems=market_risks(row,now)
    status=security.get('status','UNKNOWN') if isinstance(security,dict) else 'UNKNOWN'
    if status!='PARTIAL_PASS':
        problems.append('Sécurité du contrat non validée : '+status)
    # Strong evidence required before either BUY or prestigious-person exception.
    # No current external identity corroborator exists: explicitly fail closed.
    if not row.get('declared_links'):
        problems.append('Aucun lien de documentation déclaré')
    exclusions=list(dict.fromkeys(problems+missing))
    m=row.get('market') if isinstance(row.get('market'),dict) else {}
    can_watch=(valid_token(row) and not any('Paire de négociation exacte' in p for p in problems)
               and positive(m.get('liquidity_usd')) and m['liquidity_usd']>=100_000)
    return {'decision':'WATCH_UNVERIFIED' if can_watch else 'REJECT',
       'exclusions':exclusions, 'fundamental_gates':{key:'NOT_VERIFIED' for key in GATES},
       'reputation':{'status':'NOT_VERIFIED','persons':[]},
       'community':{'status':'NOT_VERIFIED','reason':'Liens de réseaux sociaux != preuve d’engagement organique'},
       'project_token_link':'NOT_VERIFIED',
       'security':status,'security_notes':security.get('reasons',[]) if isinstance(security,dict) else [],
       'buy_approved':False,'exceptional_signal_approved':False,
       'source_pair_url':m.get('pair_url'),'source_declared_links':row.get('declared_links',[])[:5]}

def choose(rows, history, maximum=MAX_LIVE_SECURITY_CHECKS):
    if not isinstance(rows,dict) or not isinstance(history,dict):raise ValueError('invalid state')
    picks=[]
    for key,row in rows.items():
        if not valid_token(row) or key!=token_key(row):continue
        m=row.get('market')
        if not isinstance(m,dict) or not positive(m.get('liquidity_usd')):continue
        picks.append((key,row))
    picks.sort(key=lambda v:(v[0] in history,-v[1]['market']['liquidity_usd'],v[0]))
    return picks[:maximum]

def scan(token_state,previous,now,session,maximum=MAX_LIVE_SECURITY_CHECKS):
    if not isinstance(token_state,dict) or not isinstance(previous,dict):raise ValueError('invalid state')
    old=previous.get('entries',{})
    if not isinstance(old,dict):raise ValueError('invalid prior entries')
    entries=dict(old)
    selected=choose(token_state.get('entries',{}),entries,maximum)
    for key,row in selected:
        sec=security_fetch(session,row)
        entries[key]={'token':key,'chain':row['chain'],'contract':row['contract'],
            'symbol':(row.get('market') or {}).get('symbol'),
            'analyzed_at_utc':now.isoformat(timespec='seconds'),
            'assessment':evaluate(row,sec,now)}
    # Retain no historic authorization even if old data has been tampered with.
    for item in entries.values():
        if not isinstance(item,dict):continue
        a=item.get('assessment')
        if isinstance(a,dict):
            a['buy_approved']=False;a['exceptional_signal_approved']=False
            if a.get('decision') in ('BUY_VALIDATED','EXCEPTION_SIGNAL'):
                a['decision']='WATCH_UNVERIFIED'
    summary={ 'REJECT':0,'WATCH_UNVERIFIED':0,'BUY_VALIDATED':0,'EXCEPTION_SIGNAL':0}
    for item in entries.values():
        if isinstance(item,dict) and isinstance(item.get('assessment'),dict):
            d=item['assessment'].get('decision')
            if d in summary:summary[d]+=1
    report={'run_at_utc':now.isoformat(timespec='seconds'),'selected':len(selected),
        'total_dossiers':len(entries),'decisions':summary,'telegram_buy_sent':0,
        'telegram_exception_sent':0,
        'limitation':'Independent developer/investor identity, community, tokenomics and project-token corroboration still need trusted collectors. No BUY or exceptional alerts generated.'}
    return {'schema_version':1,'entries':entries},report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true',help='No Telegram; this module never sends Telegram')
    parser.parse_args()
    try:
        source=json.loads((ROOT/'token_first_state.json').read_text(encoding='utf-8'))
        path=ROOT/'conviction_state.json'
        history=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        state,report=scan(source,history,dt.datetime.now(dt.timezone.utc),requests.Session())
        temp=path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(state,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        temp.replace(path)
        (ROOT/'conviction_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print('FATAL conviction engine: '+type(exc).__name__,file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
