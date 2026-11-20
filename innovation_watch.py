#!/usr/bin/env python3
"""Radar V2 companion: evidence-first innovation research, never a BUY engine.

GitHub repository metadata, open issues and comparable projects are INVESTIGATION
LEADS, not proof that a problem is unresolved or a project is innovative.
Does not access trading accounts, place orders, or send Telegram BUY alerts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
API = "https://api.github.com/search"
USER_AGENT = "RRTrades-innovation-research/0.1"
MAX_CANDIDATES = 200
MAX_ISSUES = 200
MAX_PROBLEMS = 24
PROJECT_AGE_DAYS = 120
LOOKBACK_ISSUES_DAYS = 30
REQUEST_INTERVAL_SECONDS = 1.1

# Scope is intentionally limited: source-specific queries, not a broad hype feed.
# These are search leads, NOT assertions of novelty or technological superiority.
QUERIES: dict[str, tuple[str, str, str]] = {
    "mev-execution": (
        '"mev protection" in:description',
        '"mev" in:description stars:>15',
        'repo:ethereum/go-ethereum "transaction" is:issue is:open',
    ),
    "crosschain-fragmentation": (
        '"cross chain" "liquidity" in:description',
        '"cross-chain" in:description stars:>15',
        'repo:ethereum-optimism/optimism "bridge" is:issue is:open',
    ),
    "wallet-usability": (
        '"account abstraction" in:description',
        '"smart wallet" in:description stars:>15',
        'repo:ethereum/EIPs "wallet" is:issue is:open',
    ),
    "oracle-integrity": (
        '"oracle" "blockchain" in:description',
        '"oracle" "price feed" in:description stars:>15',
        'repo:smartcontractkit/chainlink "oracle" is:issue is:open',
    ),
    "privacy-compliance": (
        '"zero knowledge" "privacy" in:description',
        '"privacy" "blockchain" in:description stars:>15',
        'repo:zcash/zcash "privacy" is:issue is:open',
    ),
    "onchain-risk": (
        '"smart contract" "security" in:description',
        '"smart contract" "security" in:description stars:>15',
        'repo:ethereum/go-ethereum "security" is:issue is:open',
    ),
    "stablecoin-resilience": (
        '"stablecoin" "reserve" in:description',
        '"stablecoin" in:description stars:>15',
        'repo:ethereum-optimism/optimism "stablecoin" is:issue is:open',
    ),
    "agent-payments": (
        '"agent payments" in:description',
        '"machine payments" in:description stars:>15',
        'repo:coinbase/x402 "payment" is:issue is:open',
    ),
}
# Two wider searches can discover technologies not yet in problems_v2.json.
OPEN_DISCOVERY = (
    '"cryptography" "blockchain" in:description',
    '"onchain" "infrastructure" in:description',
)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def utc_stamp(now: dt.datetime) -> str:
    return now.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def age_days(iso: Any, now: dt.datetime) -> float | None:
    if not isinstance(iso, str) or not iso:
        return None
    try:
        date = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if date.tzinfo is None:
            return None
        age = (now - date).total_seconds() / 86400
        return age if age >= 0 else None
    except ValueError:
        return None


def safe_item_list(payload: Any, key: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ValueError("Format GitHub inattendu")
    return [i for i in payload[key] if isinstance(i, dict)]


class GitHubResearch:
    """Constrained read-only GitHub search client; never log authorization headers."""

    def __init__(self, *, token: str = "", delay: float = REQUEST_INTERVAL_SECONDS,
                 session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers["Accept"] = "application/vnd.github+json"
        self.session.headers["User-Agent"] = USER_AGENT
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.delay = delay
        self.calls = 0

    def search(self, kind: str, query: str, count: int = 10, sort: str = "updated") -> list[dict]:
        if kind not in {"repositories", "issues"}:
            raise ValueError("Recherche non autorisée")
        if self.calls:
            time.sleep(self.delay)
        self.calls += 1
        try:
            response = self.session.get(
                f"{API}/{kind}",
                params={"q": query, "per_page": min(20, max(1, count)),
                        "sort": sort, "order": "desc"},
                timeout=(6, 18),
            )
            response.raise_for_status()
            return safe_item_list(response.json(), "items")
        except (requests.RequestException, ValueError) as exc:
            # API error messages can contain URLs. Do not leak auth headers or query details.
            raise RuntimeError(f"GitHub {kind}: {type(exc).__name__}") from None


def research_priority(repo: dict, now: dt.datetime) -> tuple[int, list[str]]:
    """Triage priority (0–5), explicitly NOT innovation/quality/investment score."""
    reasons: list[str] = []
    created = age_days(repo.get("created_at"), now)
    pushed = age_days(repo.get("pushed_at"), now)
    if created is not None and created <= PROJECT_AGE_DAYS:
        reasons.append("dépôt récent")
    if pushed is not None and pushed <= 21:
        reasons.append("activité récente")
    if str(repo.get("description") or "").strip():
        reasons.append("description publique")
    if str(repo.get("homepage") or "").startswith("https://"):
        reasons.append("page projet déclarée")
    if isinstance(repo.get("stargazers_count"), int) and repo["stargazers_count"] >= 5:
        reasons.append("signal d'intérêt GitHub (manipulable)")
    return len(reasons), reasons


def candidate_from_repo(repo: dict, topic: str, now: dt.datetime) -> dict | None:
    full_name = repo.get("full_name")
    url = repo.get("html_url")
    if not isinstance(full_name, str) or not isinstance(url, str):
        return None
    if not full_name or not url.startswith("https://github.com/"):
        return None
    if repo.get("fork") or repo.get("archived"):
        return None
    created = age_days(repo.get("created_at"), now)
    if created is None or created > PROJECT_AGE_DAYS:
        return None
    score, reasons = research_priority(repo, now)
    return {
        "repository": full_name,
        "repository_url": url,
        "description": str(repo.get("description") or "")[:320],
        "homepage_claim": str(repo.get("homepage") or "")[:250],
        "created_at": repo.get("created_at"),
        "pushed_at": repo.get("pushed_at"),
        "topics_to_review": [topic],
        "triage_priority_0_to_5": score,
        "triage_reasons": reasons,
        "first_seen": utc_stamp(now),
        "last_seen": utc_stamp(now),
        "status": "UNVERIFIED_RESEARCH_LEAD",
        "token_status": "UNKNOWN_NOT_CHECKED",
        "competitor_comparison_status": "NOT_DONE",
        "innovation_assessment": "NOT_DONE",
    }


def merge_candidate(queue: dict, repo: dict, topic: str, now: dt.datetime) -> bool:
    candidate = candidate_from_repo(repo, topic, now)
    if candidate is None:
        return False
    name = candidate["repository"]
    old = queue.get(name)
    if isinstance(old, dict):
        candidate["first_seen"] = old.get("first_seen", candidate["first_seen"])
        candidate["topics_to_review"] = sorted(set(old.get("topics_to_review", [])) |
                                               set(candidate["topics_to_review"]))
        # No automatic promotion to APPROVED; old reviewed status not overwritten here.
        if old.get("status") == "REVIEWED_REJECTED":
            candidate["status"] = "REVIEWED_REJECTED"
    queue[name] = candidate
    return old is None


def issue_from_api(item: dict, topic: str, now: dt.datetime) -> dict | None:
    url = item.get("html_url")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        return None
    if "pull_request" in item:
        return None
    if item.get("state") != "open":
        return None
    return {
        "title": str(item.get("title") or "")[:240],
        "source_url": url,
        "problem_id": topic,
        "issue_created_at": item.get("created_at"),
        "last_seen": utc_stamp(now),
        "status": "UNVERIFIED_PROBLEM_EVIDENCE",
        "finding": "Open issue; unresolved systemic problem NOT established",
    }


def keep_recent(queue: dict, maximum: int) -> dict:
    return dict(sorted(queue.items(), key=lambda kv: kv[1].get("last_seen", ""),
                       reverse=True)[:maximum])


def collect(problems: list[dict], client: GitHubResearch, state: dict,
            now: dt.datetime, *, open_discovery: bool = True) -> dict:
    if not isinstance(problems, list):
        raise ValueError("problems_v2.json doit contenir une liste")
    for key in ("project_research_queue", "problem_evidence", "problem_landscape"):
        state.setdefault(key, {})
    for key in ("project_research_queue", "problem_evidence", "problem_landscape"):
        if not isinstance(state[key], dict):
            raise ValueError(f"État invalide: {key}")
    report = {
        "scan_utc": utc_stamp(now),
        "github_queries": 0,
        "new_research_leads": 0,
        "new_problem_evidence": 0,
        "source_errors": [],
        "scope_metrics": {},
        "method": "GitHub search: metadata and open issues only; human validation required",
        "approved_for_buy": 0,
    }
    scopes = [p for p in problems[:MAX_PROBLEMS] if isinstance(p, dict) and
              isinstance(p.get("id"), str)]
    cutoff = (now - dt.timedelta(days=PROJECT_AGE_DAYS)).date().isoformat()
    recent = (now - dt.timedelta(days=LOOKBACK_ISSUES_DAYS)).date().isoformat()
    older = (now - dt.timedelta(days=PROJECT_AGE_DAYS)).date().isoformat()

    for problem in scopes:
        ident = problem["id"]
        query_parts = QUERIES.get(ident)
        if query_parts is None:
            report["source_errors"].append({"problem_id": ident, "source": "configuration",
                                            "error": "Aucune recherche dédiée; revue nécessaire"})
            continue
        fresh_query, alt_query, issue_query = query_parts
        metrics = {"repositories_found": 0, "new_leads": 0,
                   "issue_evidence": 0, "suggested_alternatives": 0}
        landscape = {"problem_id": ident,
                     "problem_text": str(problem.get("problem") or "")[:300],
                     "status": "UNRESOLVED_NOT_ESTABLISHED",
                     "competitors_status": "SUGGESTIONS_ONLY_NOT_COMPARATIVE_ASSESSMENT",
                     "suggested_alternatives": [], "updated_at": utc_stamp(now)}
        # A single problem's searches fail independently; partial data is reported explicitly.
        for category, query, kind in (
            ("fresh", fresh_query + f" created:>={cutoff} fork:false archived:false", "repositories"),
            ("alternatives", alt_query + f" created:<{older} fork:false archived:false", "repositories"),
            ("issues", issue_query + f" updated:>={recent}", "issues"),
        ):
            report["github_queries"] += 1
            try:
                rows = client.search(kind, query, count=8 if category == "fresh" else 5,
                                     sort="updated" if category != "alternatives" else "stars")
            except RuntimeError as exc:
                report["source_errors"].append({"problem_id": ident, "source": category,
                                                "error": str(exc)})
                continue
            if category == "fresh":
                metrics["repositories_found"] = len(rows)
                for repo in rows:
                    if merge_candidate(state["project_research_queue"], repo, ident, now):
                        metrics["new_leads"] += 1
                        report["new_research_leads"] += 1
            elif category == "alternatives":
                for repo in rows:
                    url, name = repo.get("html_url"), repo.get("full_name")
                    if isinstance(url, str) and isinstance(name, str) and url.startswith("https://github.com/"):
                        landscape["suggested_alternatives"].append({
                            "name": name, "url": url,
                            "note": "Search match only; relevance, competition, quality not validated"})
                metrics["suggested_alternatives"] = len(landscape["suggested_alternatives"])
            else:
                for item in rows:
                    evidence = issue_from_api(item, ident, now)
                    if evidence is None:
                        continue
                    uri = evidence["source_url"]
                    if uri not in state["problem_evidence"]:
                        report["new_problem_evidence"] += 1
                    state["problem_evidence"][uri] = evidence
                    metrics["issue_evidence"] += 1
        state["problem_landscape"][ident] = landscape
        report["scope_metrics"][ident] = metrics

    if open_discovery:
        for query in OPEN_DISCOVERY:
            report["github_queries"] += 1
            try:
                for repo in client.search("repositories", query + f" created:>={cutoff} fork:false archived:false", count=8):
                    if merge_candidate(state["project_research_queue"], repo,
                                       "UNMAPPED_NEW_TOPIC_REVIEW_REQUIRED", now):
                        report["new_research_leads"] += 1
            except RuntimeError as exc:
                report["source_errors"].append({"source": "unmapped_discovery", "error": str(exc)})

    state["project_research_queue"] = keep_recent(state["project_research_queue"], MAX_CANDIDATES)
    state["problem_evidence"] = keep_recent(state["problem_evidence"], MAX_ISSUES)
    report["research_leads_pending"] = len(state["project_research_queue"])
    report["problem_evidence_pending"] = len(state["problem_evidence"])
    report["problems_monitored"] = len(scopes)
    report["warning"] = "Zero BUY signals: discoveries require independent technical and competitor review"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Do not persist state")
    parser.add_argument("--no-open-discovery", action="store_true")
    args = parser.parse_args()
    now = utc_now()
    problems = read_json(ROOT / "problems_v2.json", [])
    state = read_json(ROOT / "innovation_state.json", {})
    client = GitHubResearch(token=os.getenv("GH_API_TOKEN", ""))
    report = collect(problems, client, state, now, open_discovery=not args.no_open_discovery)
    if not args.dry_run:
        write_json(ROOT / "innovation_state.json", state)
    write_json(ROOT / "innovation_report.json", report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Failure visible if every query failed, but a single bad source won't stop all research.
    successful = report["github_queries"] - len([e for e in report["source_errors"]
                                                   if e["source"] != "configuration"])
    return 1 if successful == 0 else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"FATAL innovation research: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
