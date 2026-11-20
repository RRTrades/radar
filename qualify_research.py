#!/usr/bin/env python3
"""Free, deterministic research triage: NEVER approves tokens or sends BUY alerts.

Operates on innovation_state.json. The output records observable clues and missing
proof; metadata, keywords, stars and websites are NOT verification of a solution.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'innovation_state.json'
OUTPUT = ROOT / 'qualified_research.json'
REPORT = ROOT / 'qualification_report.json'

# Strong exclusion indicators, anchored by word boundaries. False negatives are
# possible: keep excluded records in the output for audit and later re-evaluation.
NOISE_RULES = {
    'learning_or_tutorial': r'\b(tutorial|learning journey|coursework|educational|study notes|university assignment|beginner guide|course notes|case study)\b',
    'demo_or_simulation': r'\b(demo only|prototype only|simulated scenarios|sample project|testnet only|hackathon template)\b',
    'unrelated_software': r'\b(mac\s?os productivity|photo library|backup sync share|windows crack|lifetime license|repack 2026)\b',
    'pure_marketing': r'\b(100x|guaranteed profits|moonshot|pump signal|airdrop farming)\b',
}
TOPIC_RULES = {
    'mev-execution': r'\b(mev|sandwich|front.?running|private mempool|transaction ordering|intent.?based)\b',
    'crosschain-fragmentation': r'\b(cross.?chain|omnichain|bridge|chain abstraction|interoperab|liquidity routing|crosschain)\b',
    'wallet-usability': r'\b(wallet|passkey|account abstraction|social recovery|smart account|seed phrase)\b',
    'oracle-integrity': r'\b(oracle|price feed|off.?chain data|data feed)\b',
    'privacy-compliance': r'\b(zero.?knowledge|zk.?proof|confidential|privacy|selective disclosure|private transfer)\b',
    'onchain-risk': r'\b(smart.?contract|on.?chain security|audit|honeypot|exploit|vulnerabilit|formal verification)\b',
    'stablecoin-resilience': r'\b(stablecoin|peg|redemption|proof of reserve|reserve coverage)\b',
    'agent-payments': r'\b(agent|machine.?to.?machine|x402|autonomous payment|agentic payment)\b',
}
CRYPTO_CONTEXT = re.compile(r'\b(blockchain|web3|on.?chain|defi|ethereum|solana|smart.?contract|stablecoin|token|crypto|wallet|evm|cross.?chain|zk.?proof|zero.?knowledge|decentralized|x402|chainlink|near\b|stellar\b)', re.I)


def classify(record: dict) -> dict:
    """A review routing result, NOT an innovation grade or investment score."""
    name = str(record.get('repository') or '')
    desc = str(record.get('description') or '')
    text = f'{name.replace("-", " ")} {desc}'
    topics = [x for x in record.get('topics_to_review', []) if isinstance(x, str)] if isinstance(record.get('topics_to_review'), list) else []
    exclusions = [label for label, pattern in NOISE_RULES.items() if re.search(pattern, text, re.I)]
    verified_topic_matches = [topic for topic in topics if topic in TOPIC_RULES and re.search(TOPIC_RULES[topic], text, re.I)]
    context = bool(CRYPTO_CONTEXT.search(text))
    if not name or not str(record.get('repository_url') or '').startswith('https://github.com/'):
        exclusions.append('repository_identity_missing')
    if not desc.strip():
        exclusions.append('missing_description')
    if exclusions:
        status = 'LOW_PRIORITY_EXCLUSION_REVIEWABLE'
    elif not context or not verified_topic_matches:
        status = 'UNCONFIRMED_RELEVANCE'
    else:
        status = 'RESEARCH_PRIORITY_UNVERIFIED'
    # Five requested fundamental gates: none can be established from metadata alone.
    required_proofs = {
        'unresolved_problem': 'NOT_VERIFIED',
        'technical_superiority': 'NOT_VERIFIED',
        'competitor_comparison': 'NOT_VERIFIED',
        'token_value_capture': 'NOT_VERIFIED',
        'authentic_adoption': 'NOT_VERIFIED',
    }
    return {
        'repository': name,
        'repository_url': str(record.get('repository_url') or ''),
        'description': desc[:320],
        'topics': topics,
        'matched_topics_from_metadata': verified_topic_matches,
        'triage_status': status,
        'exclusion_indicators': exclusions,
        'crypto_context_keyword_present': context,
        'fundamental_proofs': required_proofs,
        'token_contract': None,
        'token_contract_verified': False,
        'buy_approved': False,
        'reason': 'Metadata-only routing; claims and real-world performance not independently verified',
    }


def qualify(state: dict) -> dict:
    queue = state.get('project_research_queue')
    if not isinstance(queue, dict):
        raise ValueError('innovation_state.json: project_research_queue absent ou invalide')
    entries = [classify(v) for v in queue.values() if isinstance(v, dict)]
    entries.sort(key=lambda x: ({'RESEARCH_PRIORITY_UNVERIFIED': 0, 'UNCONFIRMED_RELEVANCE': 1,
                                'LOW_PRIORITY_EXCLUSION_REVIEWABLE': 2}[x['triage_status']], x['repository'].lower()))
    counts = {label: sum(x['triage_status'] == label for x in entries) for label in (
        'RESEARCH_PRIORITY_UNVERIFIED', 'UNCONFIRMED_RELEVANCE', 'LOW_PRIORITY_EXCLUSION_REVIEWABLE')}
    return {
        'schema_version': 1,
        'method': 'Free metadata-based prequalification. Not an innovation, safety, or investment determination.',
        'source_count': len(queue),
        'qualified_count': len(entries),
        'counts': counts,
        'buy_approved': 0,
        'entries': entries,
    }


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    tmp.replace(path)


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit('Missing innovation_state.json: run innovation_watch.py first')
    state = json.loads(SOURCE.read_text(encoding='utf-8'))
    result = qualify(state)
    save_json(OUTPUT, result)
    report = {k: result[k] for k in ('schema_version', 'method', 'source_count', 'qualified_count', 'counts', 'buy_approved')}
    report['top_10_research_priorities'] = [x['repository'] for x in result['entries'] if x['triage_status'] == 'RESEARCH_PRIORITY_UNVERIFIED'][:10]
    save_json(REPORT, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
