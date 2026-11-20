#!/usr/bin/env python3
"""Market-first Telegram WATCH alerts, strictly not BUY or verified fundamentals.

All evidence originates from DexScreener and project-declared links; do not label
any as verified ownership, community, developer reputation or investor backing.
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
MAX_ALERTS_PER_RUN = 2
MAX_STATE_ENTRIES = 700
MAX_AGE_DAYS = 14
MIN_LIQUIDITY_USD = 100_000
MIN_VOLUME_USD = 50_000
MAX_MARKET_CAP_USD = 30_000_000
MAX_RISE_24H_PCT = 50
EVM = re.compile(r'^0x[a-fA-F0-9]{40}$')
SOL = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
CHAINS = {'solana','ethereum','base','polygon'}

def now_utc():
    return dt.datetime.now(dt.timezone.utc)

def valid_token(row):
    if not isinstance(row, dict):
        return False
    chain, address = row.get('chain'), row.get('contract')
    if chain not in CHAINS or not isinstance(address, str):
        return False
    return bool((SOL if chain == 'solana' else EVM).fullmatch(address))

def fresh_pair(market, now):
    stamp = market.get('pair_created_at_ms')
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not math.isfinite(stamp):
        return None  # lack of age is a disclosed risk, not affirmative youth evidence
    age = (now.timestamp() * 1000 - stamp)/3600000
    return 0 <= age <= MAX_AGE_DAYS*24

def assess(row, now):
    """Returns watchable, reasons; watch means review lead, never authorization."""
    reasons=[]
    if not valid_token(row):
        return False,['contrat ou réseau invalide']
    market=row.get('market')
    if not isinstance(market, dict) or not market.get('pair_url'):
        return False,['paire exacte non documentée']
    if row.get('triage_status') == 'NO_VERIFIABLE_TRADING_PAIR':
        return False,['paire négociable non confirmée']
    for key, limit, minimum in (('liquidity_usd',MIN_LIQUIDITY_USD,True),('volume_24h_usd',MIN_VOLUME_USD,True),('market_cap_usd',MAX_MARKET_CAP_USD,False)):
        v=market.get(key)
        if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or v <= 0:
            reasons.append(f'{key} manquant/invalide')
        elif (v < limit if minimum else v > limit):
            reasons.append(f'{key} hors seuil')
    delta=market.get('price_change_24h_pct')
    if isinstance(delta,bool) or not isinstance(delta,(float,int)) or not math.isfinite(delta):
        reasons.append('prix 24h inconnu')
    elif delta > MAX_RISE_24H_PCT:
        reasons.append('hausse 24h trop forte')
    age=fresh_pair(market,now)
    if age is False:
        reasons.append('pool trop ancien/date incohérente')
    if row.get('promotion_is_not_endorsement') is True:
        pass  # promotional discovery is not positive evidence
    links=row.get('declared_links',[])
    if not isinstance(links,list) or not any(isinstance(u,str) and u.startswith('https://') for u in links):
        reasons.append('aucune documentation/lien déclaré')
    if not str(row.get('profile_description') or '').strip():
        reasons.append('projet sans description')
    return not reasons,reasons

def score_for_order(row):
    m=row['market']
    # purely prioritization among passing liquidity/cap/volume, not investment score
    return (float(m['liquidity_usd']),float(m['volume_24h_usd']))

def select(state, sent, now, limit=MAX_ALERTS_PER_RUN):
    if not isinstance(state,dict) or not isinstance(sent,dict) or not isinstance(limit,int) or not 0<=limit<=MAX_ALERTS_PER_RUN:
        raise ValueError('invalid state or cap')
    candidates=[]
    for key,row in state.items():
        if not isinstance(row,dict) or not valid_token(row):
            continue
        ident=row['chain']+':'+(row['contract'] if row['chain']=='solana' else row['contract'].lower())
        if key != ident or ident in sent:
            continue
        ok,_=assess(row,now)
        if ok:
            candidates.append((ident,row))
    candidates.sort(key=lambda e:score_for_order(e[1]),reverse=True)
    return candidates[:limit]

def fmt_usd(v):
    return f'${v:,.0f}'

def format_message(ident,row,now):
    market=row['market']
    age=fresh_pair(market,now)
    age_text='NON VÉRIFIÉ' if age is None else '≤14 j selon la date de création de la paire'
    source=market.get('pair_url')
    declared=[u for u in row.get('declared_links',[]) if isinstance(u,str) and u.startswith('https://')][:2]
    desc=' '.join(str(row.get('profile_description') or '').split())[:220]
    return '\n'.join([
        'RADAR V2 — SURVEILLANCE (PAS UN BUY)',
        f"Actif : {market.get('name','inconnu')} (${market.get('symbol','?')})",
        f"Réseau : {row['chain']}",
        f"Contrat observé : {row['contract']}",
        f"Liquidité : {fmt_usd(market['liquidity_usd'])} | Volume 24h : {fmt_usd(market['volume_24h_usd'])}",
        f"Capitalisation déclarée : {fmt_usd(market['market_cap_usd'])} | 24h : {market['price_change_24h_pct']:+.1f}%",
        f"Âge de pool : {age_text}",
        f'Projet (déclaration non vérifiée) : {desc}',
        f'Paire : {source}',
        *[f'Lien déclaré : {u}' for u in declared],
        'CRITÈRES NON VÉRIFIÉS : identité officielle projet-token ; développeur/investisseur ; communauté authentique ; innovation ; concurrence ; tokenomics ; sécurité approfondie.',
        'Statut : piste de recherche seulement. Pas de validation fondamentale ni de recommandation d’achat.'
    ])[:4000]

def post_telegram(session,message,token,chat):
    if not token or not chat:
        raise ValueError('Telegram secrets missing')
    try:
        r=session.post('https://api.telegram.org/bot'+token+'/sendMessage',data={'chat_id':chat,'text':message},timeout=(6,20))
        r.raise_for_status()
        if r.json().get('ok') is not True:
            raise RuntimeError('Telegram rejected message')
    except (requests.RequestException,ValueError,RuntimeError):
        # Auth token must never appear in exception messages or reports.
        raise RuntimeError('Telegram delivery failed') from None

def process(state,prior,now,session,token='',chat='',dry_run=True):
    sent=prior.get('sent',{})
    if not isinstance(sent,dict):
        raise ValueError('Invalid alert history')
    sent=dict(sent)
    candidates=select(state,sent,now)
    report={'at_utc':now.isoformat(timespec='seconds'),'considered':len(state),
      'selected':len(candidates),'dry_run':bool(dry_run),'delivered':0,
      'simulated':0,'failures':[],'kind':'SURVEILLANCE_NON_BUY'}
    for ident,row in candidates:
        message=format_message(ident,row,now)
        if dry_run:
            report['simulated']+=1
            report.setdefault('previews',[]).append(message)
            continue
        try:
            post_telegram(session,message,token,chat)
            sent[ident]=now.isoformat(timespec='seconds')
            report['delivered']+=1
        except (RuntimeError,ValueError):
            report['failures'].append({'token':ident,'error':'Telegram delivery failed'})
    if len(sent)>MAX_STATE_ENTRIES:
        sent=dict(sorted(sent.items(),key=lambda kv:kv[1],reverse=True)[:MAX_STATE_ENTRIES])
    return {'schema_version':1,'sent':sent},report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:
        src=json.loads((ROOT/'token_first_state.json').read_text(encoding='utf-8'))
        history=ROOT/'token_watch_alerts_state.json'
        previous=json.loads(history.read_text(encoding='utf-8')) if history.exists() else {}
        state,report=process(src.get('entries',{}),previous,now_utc(),requests.Session(),
            os.getenv('TELEGRAM_TOKEN',''),os.getenv('TELEGRAM_CHAT_ID',''),args.dry_run)
        if not args.dry_run:
            temp=history.with_suffix('.json.tmp')
            temp.write_text(json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
            temp.replace(history)
        (ROOT/'token_watch_alerts_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='previews'},ensure_ascii=False))
        for preview in report.get('previews',[]):
            print('[DRY RUN PREVIEW]\n'+preview)
        return 1 if report['failures'] else 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('FATAL token watch: '+type(exc).__name__,file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
