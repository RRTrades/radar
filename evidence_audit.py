#!/usr/bin/env python3
"""Free, bounded GitHub evidence audit. No BUY approvals or investment scores.

Public GitHub metadata only; technical existence signals, not independent proof of
innovation, market adoption, code safety or token value capture.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent
MAX_AUDITS_PER_RUN = 12
USER_AGENT = 'RRTrades-evidence-audit/1.0'
HEADERS = {'Accept': 'application/vnd.github+json', 'User-Agent': USER_AGENT}
REPO_PATTERN = re.compile(r'^(?!\.\.?/)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def fetch_json(session, url, token=''):
    headers = dict(HEADERS)
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        response = session.get(url, headers=headers, timeout=(5, 15))
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        # Never expose the auth token, headers, or potentially sensitive URL.
        raise RuntimeError('GitHub API request failed: ' + type(exc).__name__) from None


def choose_candidates(qualified, max_n=MAX_AUDITS_PER_RUN):
    entries = qualified.get('entries')
    if not isinstance(entries, list):
        raise ValueError('qualified_research.json: entries invalid')
    selected = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('triage_status') != 'RESEARCH_PRIORITY_UNVERIFIED':
            continue
        name = entry.get('repository')
        if not isinstance(name, str) or not REPO_PATTERN.fullmatch(name) or name.lower() in seen:
            continue
        seen.add(name.lower())
        selected.append(name)
        if len(selected) >= max_n:
            break
    return selected


def analyze_evidence(name, repo, root_items, commits, timestamp):
    if not isinstance(repo, dict) or not isinstance(root_items, list) or not isinstance(commits, list):
        raise ValueError('Invalid GitHub evidence payload')
    filenames = {str(f.get('name', '')).lower() for f in root_items if isinstance(f, dict)}
    has_readme = any(f.startswith('readme') for f in filenames)
    has_license = any(f.startswith('license') or f.startswith('copying') for f in filenames)
    has_ci = '.github' in filenames or '.gitlab-ci.yml' in filenames
    has_tests = any(f in filenames for f in ('tests', 'test', 'spec', '__tests__'))
    has_code_dir = any(f in filenames for f in ('src','contracts','programs','lib','app','packages'))
    has_build = any(f in filenames for f in ('package.json','pyproject.toml','cargo.toml','foundry.toml','hardhat.config.js','hardhat.config.ts','go.mod','requirements.txt'))
    observed_commit_urls = [c.get('html_url') for c in commits[:3] if isinstance(c, dict) and isinstance(c.get('html_url'), str) and c['html_url'].startswith('https://github.com/')]
    url = repo.get('html_url')
    if not isinstance(url, str) or url != 'https://github.com/' + name:
        raise ValueError('Repository identity mismatch')
    evidence = {
        'repository': name, 'repository_url': url, 'audited_at_utc': timestamp,
        'observables': {
            'has_readme_at_root': has_readme, 'has_license_at_root': has_license,
            'has_ci_directory_or_config_at_root': has_ci, 'has_tests_directory_at_root': has_tests,
            'has_source_directory_at_root': has_code_dir, 'has_build_manifest_at_root': has_build,
            'recent_commit_objects_returned': len(commits),
            'github_stars_public': repo.get('stargazers_count') if isinstance(repo.get('stargazers_count'), int) else None,
            'github_forks_public': repo.get('forks_count') if isinstance(repo.get('forks_count'), int) else None,
            'archived': repo.get('archived'), 'fork': repo.get('fork'),
        },
        'evidence_links': [url] + observed_commit_urls,
        'fundamental_proofs': {
            'unresolved_problem': 'NOT_VERIFIED',
            'technical_superiority': 'NOT_VERIFIED',
            'competitor_comparison': 'NOT_VERIFIED',
            'token_value_capture': 'NOT_VERIFIED',
            'authentic_adoption': 'NOT_VERIFIED',
        },
        'token_contract_verified': False, 'buy_approved': False,
        'verdict': 'METADATA_EVIDENCE_ONLY',
        'limitations': 'Root-level presence tests only. Does not inspect code quality, run tests, validate an external product, infer token existence, or prove user adoption.'
    }
    return evidence


def collect(qualified, token='', session=None, max_n=MAX_AUDITS_PER_RUN, delay=0.3):
    session = session or requests.Session()
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    names = choose_candidates(qualified, max_n=max_n)
    audited, errors = [], []
    for idx, name in enumerate(names):
        if idx and delay:
            time.sleep(delay)
        base = 'https://api.github.com/repos/' + '/'.join(quote(part, safe='') for part in name.split('/'))
        try:
            repo = fetch_json(session, base, token)
            root = fetch_json(session, base + '/contents', token)
            commits = fetch_json(session, base + '/commits?per_page=3', token)
            audited.append(analyze_evidence(name, repo, root, commits, timestamp))
        except (RuntimeError, ValueError) as exc:
            errors.append({'repository': name, 'reason': type(exc).__name__, 'detail': str(exc)[:100]})
    return {
        'schema_version': 1, 'audited_at_utc': timestamp, 'selected_count': len(names),
        'audited_count': len(audited), 'error_count': len(errors), 'errors': errors,
        'audit_scope': 'GitHub repository existence, root file names and recent commit links only',
        'approved_for_buy': 0, 'entries': audited,
    }


def main():
    source = ROOT / 'qualified_research.json'
    if not source.exists():
        raise SystemExit('qualified_research.json absent — run qualify_research.py first')
    qualified = json.loads(source.read_text(encoding='utf-8'))
    result = collect(qualified, token=os.getenv('GH_API_TOKEN', ''))
    (ROOT / 'evidence_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    report = {k: v for k, v in result.items() if k != 'entries'}
    (ROOT / 'evidence_audit_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result['audited_count'] or not result['selected_count'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
