#!/usr/bin/env python3
"""Conservative free project↔token research linkage; NEVER authorizes a BUY.

A token mentioned by a GitHub project and found on DexScreener is NOT proof of
project ownership, endorsement, safety, token utility, or investability.
"""
from __future__ import annotations
import base64
import binascii
import datetime as dt
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent
GITHUB_API = 'https://api.github.com/repos/'
DEX_API = 'https://api.dexscreener.com/token-pairs/v1/'
MAX_REPOS_PER_RUN = 6
MAX_README_CHARS = 12000
VALID_REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
EVM_ADDRESS = r'0x[a-fA-F0-9]{40}'
SOL_ADDRESS = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
# Ignore addresses in prose/code unless clearly labelled as contracts.
EVM_LABEL = re.compile(r'(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:(?:ethereum|base|polygon)\s+)?(?:token\s+)?(?:contract\s+address|token\s+address|token\s+contract|ca)\s*(?:\*\*)?\s*[:=\-]\s*`?(' + EVM_ADDRESS + r')\b')
SOL_LABEL = re.compile(r'(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:solana\s+)?(?:mint\s+address|token\s+mint|token\s+address|contract\s+address)\s*(?:\*\*)?\s*[:=\-]\s*`?(' + SOL_ADDRESS + r')\b')
CHAIN_HEADER = re.compile(r'\b(ethereum|base|polygon|solana)\b', re.I)
EVM_CHAINS = {'ethereum','base','polygon'}
SUPPORTED_CHAINS = EVM_CHAINS | {'solana'}


def valid_repo(repo):
    return isinstance(repo, str) and bool(VALID_REPO.fullmatch(repo)) and all(p not in ('.','..') for p in repo.split('/'))


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path: Path, item):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temp.replace(path)


def request_json(session, url, *, token=''):
    # Fixed host, no externally supplied destinations.
    if not (url.startswith(GITHUB_API) or url.startswith(DEX_API)):
        raise ValueError('Unapproved API host')
    headers = {'Accept':'application/vnd.github+json', 'User-Agent':'RRTrades-token-identity/1.0'}
    if token and url.startswith(GITHUB_API):
        headers['Authorization'] = 'Bearer ' + token
    try:
        resp = session.get(url, headers=headers, timeout=(5, 15))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        # Never leak credentials, user-supplied URLs or API response bodies.
        raise RuntimeError('Public API unavailable') from None


def read_readme(session, repo, token=''):
    if not valid_repo(repo):
        raise ValueError('Invalid repository')
    endpoint = GITHUB_API + '/'.join(quote(p,safe='') for p in repo.split('/')) + '/readme'
    obj = request_json(session, endpoint, token=token)
    if obj is None:
        return '', None
    if not isinstance(obj, dict) or obj.get('encoding') != 'base64' or not isinstance(obj.get('content'),str):
        raise RuntimeError('Unsupported README API format')
    try:
        data = base64.b64decode(obj['content'], validate=False).decode('utf-8','replace')
    except (ValueError, TypeError, binascii.Error):
        raise RuntimeError('Malformed README') from None
    return data[:MAX_README_CHARS], 'https://github.com/' + repo + '#readme'


def discover_claims(readme: str):
    """Return only unambiguous explicitly labelled addresses; never infer ownership."""
    if not isinstance(readme,str):
        return []
    results = set()
    fenced = False
    for line in readme.splitlines():
        if line.lstrip().startswith(('```', '~~~')):
            fenced = not fenced
            continue
        if fenced:
            continue
        # Reject fenced code snippets, examples and explicit placeholders.
        if any(word in line.lower() for word in ('example', 'sample', 'placeholder', 'test address', 'fake', 'demo')):
            continue
        chains = {x.lower() for x in CHAIN_HEADER.findall(line)}
        for match in EVM_LABEL.finditer(line):
            # EVM contract MUST carry chain label on its own line. Never guess Base vs Ethereum.
            matched = chains.intersection(EVM_CHAINS)
            if len(matched)==1:
                results.add((next(iter(matched)),match.group(1).lower()))
        for match in SOL_LABEL.finditer(line):
            # Solana addresses can resemble unrelated base58 IDs; require Solana mention.
            if 'solana' in chains:
                results.add(('solana',match.group(1)))
    return [{'chain': c, 'contract': a} for c,a in sorted(results)]


def market_match(pairs, chain, contract):
    if not isinstance(pairs,list):
        raise RuntimeError('Unexpected DexScreener response')
    matching=[]
    for p in pairs:
        if not isinstance(p,dict):
            continue
        base=p.get('baseToken') or {}
        if (str(p.get('chainId','')).lower() == chain and isinstance(base,dict) and
            str(base.get('address','')).lower()==contract.lower() and
            isinstance((p.get('liquidity') or {}).get('usd'),(int,float))):
            matching.append(p)
    if not matching:
        return None
    best=max(matching,key=lambda p:p['liquidity']['usd'])
    return {
        'pair_url':best.get('url') if str(best.get('url','')).startswith('https://dexscreener.com/') else None,
        'base_symbol_reported':str((best.get('baseToken') or {}).get('symbol',''))[:30],
        'liquidity_usd':best['liquidity']['usd'],
        'marketcap_usd':best.get('marketCap') if isinstance(best.get('marketCap'),(int,float)) else None,
    }


def choose(history, previous, maximum=MAX_REPOS_PER_RUN):
    if not isinstance(history,dict) or not isinstance(previous,dict):
        raise ValueError('Invalid state shape')
    rows=[v for v in history.values() if isinstance(v,dict) and valid_repo(v.get('repository'))]
    rows.sort(key=lambda x:(x['repository'].lower() in previous,x['repository'].lower()))
    return rows[:maximum]


def scan(ai_state, history, session, github_token='', maximum=MAX_REPOS_PER_RUN):
    old=history.get('entries',{})
    if not isinstance(old,dict):
        raise ValueError('Invalid token history')
    entries=dict(old)
    stamp=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    errors=[]; checked=0; markets=0; claims_total=0
    for item in choose(ai_state.get('entries',{}),entries,maximum):
        name=item['repository']; key=name.lower(); checked+=1
        try:
            readme,url=read_readme(session,name,github_token)
            claims=discover_claims(readme)
            verdicts=[]
            for claim in claims[:4]:
                chain,addr=claim['chain'],claim['contract']
                pairs=request_json(session,DEX_API + quote(chain,safe='') + '/' + quote(addr,safe=''))
                market=market_match(pairs if pairs is not None else [],chain,addr)
                if market:markets+=1
                verdicts.append({**claim,'market_observed':market is not None,'market':market,
                    'status':'PROJECT_CLAIM_AND_MARKET_OBSERVED_NOT_VERIFIED' if market else 'PROJECT_CLAIM_ONLY_NOT_VERIFIED',
                    'identity_verified':False,'buy_approved':False})
            claims_total+=len(claims)
            entries[key]={'repository':name,'checked_at_utc':stamp,'project_source_url':url,
                'contract_claims':verdicts,'contract_claims_found':len(claims),
                'identity_verified':False,'dev_identity_verified':False,'investor_identity_verified':False,
                'buy_approved':False,'status':'REQUIRES_INDEPENDENT_OFFICIAL_IDENTITY_PROOF',
                'reason':'README is project-controlled and DexScreener merely indexes trading pairs; cannot prove official token identity.'}
        except (RuntimeError,ValueError) as e:
            errors.append({'repository':name,'error':str(e)[:90]})
    # No stale history can authorize a trade, even if hand edited.
    for val in entries.values():
        if isinstance(val,dict):
            val['buy_approved']=False
            val['identity_verified']=False
    report={'checked_at_utc':stamp,'selected_count':checked,'claims_found':claims_total,
       'market_matches':markets,'error_count':len(errors),'errors':errors,
       'total_repositories_recorded':len(entries),'buy_approved':0,
       'disclaimer':'No official token ownership established. No trading alert permitted.'}
    return {'schema_version':1,'entries':entries},report


def main():
    import sys
    from pathlib import Path
    source=ROOT/'fundamental_ai_state.json'
    if not source.exists():
        print('SKIPPED: no Groq research state yet')
        return 0
    try:
        ai=read_json(source,{})
        out=ROOT/'token_identity_state.json'
        state,report=scan(ai,read_json(out,{}),requests.Session(),os.getenv('GH_API_TOKEN',''))
        write_json(out,state)
        write_json(ROOT/'token_identity_report.json',report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 1 if report['selected_count'] and report['error_count']==report['selected_count'] else 0
    except (OSError,ValueError,TypeError,KeyError) as e:
        print('FATAL token identity: '+type(e).__name__,file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
