#!/usr/bin/env python3
"""Free, token-first research discovery. Never approves or sends a BUY.

DexScreener profiles and boosts are promotional/discovery surfaces, NOT
independent evidence of ownership, legitimacy, community or innovation.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
import re
import requests
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
BASE = 'https://api.dexscreener.com'
CHAINS = {'solana', 'ethereum', 'base', 'polygon'}
EVM = re.compile(r'^0x[0-9a-fA-F]{40}$')
SOL = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
MAX_LOOKUPS = 20
MAX_SAVED = 400
MAX_AGE_DAYS = 14


def valid_token(chain, address):
    if not isinstance(chain, str) or not isinstance(address, str) or chain not in CHAINS:
        return False
    return bool((SOL if chain == 'solana' else EVM).fullmatch(address))


def token_key(chain, address):
    return chain + ':' + (address if chain == 'solana' else address.lower())


def api_get(session, endpoint):
    if not endpoint.startswith('/') or '//' in endpoint or '?' in endpoint:
        raise ValueError('Invalid API route')
    try:
        r = session.get(BASE + endpoint, headers={'User-Agent': 'RRTrades-token-first/1.0'}, timeout=(5, 18))
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError('DexScreener API request failed') from None


def collect_sources(profiles, boosts):
    sources = {}
    for label, rows in (('recent_profile', profiles), ('paid_boost', boosts)):
        if not isinstance(rows, list):
            raise ValueError('Unexpected DexScreener discovery response')
        for row in rows[:100]:
            if not isinstance(row, dict):
                continue
            chain, address = row.get('chainId'), row.get('tokenAddress')
            if not valid_token(chain, address):
                continue
            key = token_key(chain, address)
            entry = sources.setdefault(key, {'chain':chain, 'contract':address, 'discovery_sources':[],
                      'profile_description': '', 'declared_links':[]})
            if label not in entry['discovery_sources']:
                entry['discovery_sources'].append(label)
            if label == 'recent_profile' and isinstance(row.get('description'), str):
                entry['profile_description'] = row['description'][:550]
            for link in row.get('links', []) if isinstance(row.get('links'), list) else []:
                if isinstance(link, dict) and isinstance(link.get('url'), str):
                    url=link['url']
                    if url.startswith('https://') and len(url)<220 and url not in entry['declared_links']:
                        entry['declared_links'].append(url)
                        entry['declared_links'] = entry['declared_links'][:6]
    return sources


def find_market(pairs, chain, contract):
    if not isinstance(pairs, list):
        raise ValueError('Unexpected pair payload')
    matches=[]
    for pair in pairs:
        if not isinstance(pair, dict) or pair.get('chainId') != chain:
            continue
        token=pair.get('baseToken')
        if not isinstance(token, dict) or not isinstance(token.get('address'),str):
            continue
        observed=token['address']
        if (observed != contract if chain == 'solana' else observed.lower() != contract.lower()):
            continue
        liq=(pair.get('liquidity') or {}).get('usd')
        if isinstance(liq, bool) or not isinstance(liq,(int,float)) or not math.isfinite(liq) or liq<0:
            continue
        matches.append(pair)
    if not matches:
        return None
    p=max(matches,key=lambda item:item['liquidity']['usd'])
    t=p['baseToken']
    cap=p.get('marketCap'); vol=(p.get('volume') or {}).get('h24'); change=(p.get('priceChange') or {}).get('h24')
    created=p.get('pairCreatedAt')
    return {'symbol':str(t.get('symbol',''))[:25], 'name':str(t.get('name',''))[:90],
      'liquidity_usd':p['liquidity']['usd'],
      'market_cap_usd':cap if isinstance(cap,(int,float)) and not isinstance(cap,bool) and math.isfinite(cap) and cap>0 else None,
      'volume_24h_usd':vol if isinstance(vol,(int,float)) and not isinstance(vol,bool) and math.isfinite(vol) and vol>=0 else None,
      'price_change_24h_pct':change if isinstance(change,(int,float)) and not isinstance(change,bool) and math.isfinite(change) else None,
      'pair_created_at_ms':created if isinstance(created,int) and not isinstance(created,bool) and created>0 else None,
      'pair_url':p.get('url') if isinstance(p.get('url'),str) and p['url'].startswith('https://dexscreener.com/') else None}


def triage(market, now):
    """Early attention, never quality or financial scoring."""
    if market is None:
        return 'NO_VERIFIABLE_TRADING_PAIR', ['aucune paire exacte avec liquidité renseignée']
    issues=[]
    liq=market['liquidity_usd']; cap=market['market_cap_usd']; vol=market['volume_24h_usd']
    if liq < 25000: issues.append('liquidité inférieure à 25 000 USD')
    if cap is None: issues.append('capitalisation circulante inconnue')
    elif cap > 150000000: issues.append('capitalisation supérieure à 150 M USD')
    if vol is None: issues.append('volume 24 h inconnu')
    created=market['pair_created_at_ms']
    if created is None:
        issues.append('âge de pool inconnu')
    else:
        age=(now.timestamp()*1000-created)/3600000
        if age < 0: issues.append('date de pool future/incohérente')
        elif age > 14*24: issues.append('pool de plus de 14 jours')
    if market['price_change_24h_pct'] is None:
        issues.append('variation du prix inconnue')
    elif market['price_change_24h_pct']>100:
        issues.append('hausse 24 h supérieure à 100 %')
    return ('MARKET_RESEARCH_PRIORITY_UNVERIFIED' if not issues else 'MARKET_RESEARCH_REVIEW'),issues


def choose(sources, previous, limit=MAX_LOOKUPS):
    if not isinstance(previous,dict) or not 0 <= limit <= MAX_LOOKUPS:
        raise ValueError('Invalid discovery history or lookup limit')
    # Never-discovered first. Never count a paid boost as a positive signal.
    return sorted(sources.values(), key=lambda x:(token_key(x['chain'],x['contract']) in previous,
                     previous.get(token_key(x['chain'],x['contract']),{}).get('last_checked_at',''),
                     token_key(x['chain'],x['contract'])))[:limit]


def scan(session, previous, now, limit=MAX_LOOKUPS):
    if not isinstance(previous,dict):
        raise ValueError('Invalid prior state')
    profiles=api_get(session,'/token-profiles/latest/v1')
    boosts=api_get(session,'/token-boosts/latest/v1')
    sources=collect_sources(profiles,boosts)
    candidates=choose(sources,previous,limit)
    out=dict(previous); completed=0; errors=[]; eligible=0
    for item in candidates:
        key=token_key(item['chain'],item['contract'])
        try:
            pairs=api_get(session,'/token-pairs/v1/'+quote(item['chain'],safe='')+'/'+quote(item['contract'],safe=''))
            market=find_market(pairs,item['chain'],item['contract'])
            status,notes=triage(market,now)
            if status=='MARKET_RESEARCH_PRIORITY_UNVERIFIED': eligible+=1
            old=out.get(key,{})
            out[key]={**item,'first_seen_at':old.get('first_seen_at',now.isoformat(timespec='seconds')),
              'last_checked_at':now.isoformat(timespec='seconds'),'market':market,'triage_status':status,
              'triage_flags':notes,'promotion_is_not_endorsement':'paid_boost' in item['discovery_sources'],
              'project_token_link_verified':False,'developer_verified':False,'investor_verified':False,
              'community_authenticity_verified':False,'token_value_capture_verified':False,
              'fundamentals_verified':False,'buy_approved':False,'exceptional_signal_approved':False}
            completed+=1
        except (RuntimeError,ValueError) as exc:
            errors.append({'token':key,'error':type(exc).__name__})
    # Never trust historical decisions as authorizations.
    for row in out.values():
        if isinstance(row,dict):
            row['buy_approved']=False
            row['exceptional_signal_approved']=False
            row['project_token_link_verified']=False
    if len(out)>MAX_SAVED:
        out=dict(sorted(out.items(),key=lambda kv:kv[1].get('last_checked_at',''),reverse=True)[:MAX_SAVED])
    report={'scan_at_utc':now.isoformat(timespec='seconds'),'source_tokens_seen':len(sources),
      'selected':len(candidates),'completed':completed,'errors':errors,
      'priority_for_research':eligible,'total_saved':len(out),'buy_approved':0,
      'note':'Tradable pair != verified issuer or investment quality. Boost is promotion, not conviction.'}
    return {'schema_version':1,'entries':out},report


def main():
    source=ROOT/'token_first_state.json'
    old=json.loads(source.read_text(encoding='utf-8')).get('entries',{}) if source.exists() else {}
    state,report=scan(requests.Session(),old,dt.datetime.now(dt.timezone.utc))
    temp=source.with_suffix('.json.tmp')
    temp.write_text(json.dumps(state,indent=2,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8')
    temp.replace(source)
    (ROOT/'token_first_report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 1 if report['selected'] and not report['completed'] else 0

if __name__=='__main__':
    raise SystemExit(main())
