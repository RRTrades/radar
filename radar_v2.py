#!/usr/bin/env python3
"""Radar v2 — discovery is NOT a recommendation; only pre-approved projects can alert.

Requires requests. No trading, no wallets, no private keys, and fail-closed on missing
market/security data. All automated discoveries go to JSON review queues.
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
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent
API = "https://api.dexscreener.com"
CHAIN_IDS = {"ethereum": 1, "base": 8453, "bsc": 56, "arbitrum": 42161,
             "polygon": 137, "optimism": 10}
PHANTOM_CHAINS = {"solana", "ethereum", "base", "polygon"}
SCHEMA = 2
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "RRTrades-radar-v2/1.0 (research)"})


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def fetch_json(url: str, *, params: dict | None = None) -> Any:
    try:
        res = SESSION.get(url, params=params, timeout=(6, 20))
        res.raise_for_status()
        return res.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"API inaccessible: {url.split('?')[0]}: {type(exc).__name__}: {exc}") from exc


def problem_hits(text: str, problems: list[dict]) -> list[dict]:
    text = text.lower()
    found = []
    for problem in problems:
        hits = sorted(set(word for word in problem.get("keywords", []) if word.lower() in text))
        if hits:
            found.append({"id": problem["id"], "hits": hits})
    return found


def project_id(chain: str, contract: str) -> str:
    return f"{chain.lower()}:{contract.lower()}"


def pair_for_token(chain: str, contract: str) -> dict | None:
    # Exact chain + contract, never a symbol lookup.
    pairs = fetch_json(f"{API}/token-pairs/v1/{quote(chain)}/{quote(contract)}")
    if not isinstance(pairs, list):
        raise RuntimeError("DexScreener: format de paires inattendu")
    matching = [p for p in pairs if p.get("chainId", "").lower() == chain.lower()
                and p.get("baseToken", {}).get("address", "").lower() == contract.lower()
                and isinstance((p.get("liquidity") or {}).get("usd"), (int, float))]
    return max(matching, key=lambda p: p["liquidity"]["usd"], default=None)


def market_check(pair: dict, approval: dict, now_ms: int) -> tuple[bool, list[str], dict]:
    problems: list[str] = []
    liq = (pair.get("liquidity") or {}).get("usd")
    cap = pair.get("marketCap")  # Do not silently substitute FDV for circulating market cap.
    creation = pair.get("pairCreatedAt")
    changes = pair.get("priceChange") or {}
    h6, h24 = changes.get("h6"), changes.get("h24")
    if not isinstance(liq, (int, float)) or liq < approval["min_liquidity_usd"]:
        problems.append("liquidité insuffisante/inconnue")
    if not isinstance(cap, (int, float)) or not 0 < cap <= approval["max_marketcap_usd"]:
        problems.append("capitalisation inconnue/hors seuil")
    if not isinstance(creation, (int, float)) or creation <= 0:
        problems.append("date de pool inconnue")
        age = None
    else:
        age = (now_ms - creation) / 3_600_000
        if age < approval["min_pair_age_hours"] or age > approval["max_pair_age_hours"]:
            problems.append("âge de pool hors fenêtre")
    if not isinstance(h6, (int, float)) or not isinstance(h24, (int, float)):
        problems.append("variation de prix inconnue")
    else:
        if h6 > approval["max_change_6h_pct"] or h24 > approval["max_change_24h_pct"]:
            problems.append("hausse de prix excessive")
    info = {"liquidity_usd": liq, "marketcap_usd": cap, "pair_age_hours": age,
            "change_6h_pct": h6, "change_24h_pct": h24}
    return not problems, problems, info


def security_check(chain: str, token: str) -> tuple[bool, str]:
    if chain == "solana":
        payload = fetch_json("https://api.gopluslabs.io/api/v1/solana/token_security",
                             params={"contract_addresses": token})
        result = (payload.get("result") or {}).get(token)
        if not isinstance(result, dict):
            return False, "GoPlus: résultat Solana indisponible"
        # Missing fields are NOT evidence of safety.
        statuses = []
        for field in ("mintable", "freezable"):
            item = result.get(field)
            if not isinstance(item, dict) or str(item.get("status")) not in ("0", "1"):
                return False, f"GoPlus: {field} non vérifiable"
            statuses.append(str(item["status"]))
        return (all(s == "0" for s in statuses), "GoPlus Solana")
    chain_id = CHAIN_IDS.get(chain)
    if not chain_id:
        return False, "blockchain non prise en charge"
    payload = fetch_json(f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}",
                         params={"contract_addresses": token})
    result = (payload.get("result") or {}).get(token.lower())
    if not isinstance(result, dict):
        return False, "GoPlus: résultat EVM indisponible"
    must_be_zero = ["is_honeypot", "hidden_owner", "is_mintable"]
    for field in must_be_zero:
        if str(result.get(field)) != "0":
            return False, f"GoPlus: {field} non sûr/inconnu"
    if str(result.get("is_open_source")) != "1":
        return False, "GoPlus: code non vérifié"
    try:
        buy, sell = float(result["buy_tax"]), float(result["sell_tax"])
    except (KeyError, TypeError, ValueError):
        return False, "GoPlus: taxe inconnue"
    if not (0 <= buy <= 0.05 and 0 <= sell <= 0.05):
        return False, "GoPlus: taxe trop élevée"
    return True, "GoPlus EVM (contrôle partiel)"


def validate_approval(a: dict, now: dt.datetime) -> list[str]:
    failures = []
    for key in ("name", "symbol", "chain", "contract", "problem_id", "solution_keywords",
                "evidence_urls", "competitor_comparison_url", "reviewed_at", "expires_at"):
        if not a.get(key):
            failures.append(f"{key} manquant")
    if failures:
        return failures
    if a["chain"] not in (set(CHAIN_IDS) | {"solana"}):
        failures.append("chaîne non prise en charge")
    if a["chain"] not in PHANTOM_CHAINS:
        failures.append("plateforme Phantom non vérifiée")
    if not isinstance(a["evidence_urls"], list) or len(a["evidence_urls"]) < 2:
        failures.append("moins de 2 preuves indépendantes")
    if not isinstance(a["solution_keywords"], list) or not a["solution_keywords"]:
        failures.append("solution absente")
    for field in ("reviewed_at", "expires_at"):
        try:
            when = dt.datetime.fromisoformat(a[field].replace("Z", "+00:00"))
            if when.tzinfo is None:
                failures.append(f"{field} sans fuseau")
            elif field == "expires_at" and when <= now:
                failures.append("validation expirée")
            elif field == "reviewed_at" and (when > now or (now - when).days > 14):
                failures.append("revue trop ancienne/invalide")
        except (ValueError, AttributeError):
            failures.append(f"date {field} invalide")
    for field in ("min_liquidity_usd", "max_marketcap_usd", "min_pair_age_hours",
                  "max_pair_age_hours", "max_change_6h_pct", "max_change_24h_pct"):
        if not isinstance(a.get(field), (int, float)):
            failures.append(f"{field} absent")
    return failures


def format_alert(a: dict, info: dict, sec: str) -> str:
    return (f"BUY | ${a['symbol']} | {a['name']}\n"
            f"CHAIN : {a['chain']}\n"
            f"PLATEFORME : PHANTOM (réseau compatible; disponibilité du swap à vérifier)\n"
            f"CONTRAT : {a['contract']}\n"
            f"PROBLÈME : {a['problem_id']}\n"
            f"SOLUTION : {' / '.join(a['solution_keywords'][:4])}\n"
            f"PREUVES : {len(a['evidence_urls'])} | CONCURRENCE : audit manuel\n"
            f"MCAP : ${info['marketcap_usd']:,.0f} | LIQ : ${info['liquidity_usd']:,.0f}\n"
            f"6H : {info['change_6h_pct']:+.1f}% | 24H : {info['change_24h_pct']:+.1f}%\n"
            f"SÉCURITÉ : {sec} | RISQUE : SPÉCULATIF ÉLEVÉ")


def send_telegram(message: str, dry_run: bool) -> bool:
    if dry_run:
        print("[DRY RUN] " + message)
        return False
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("Secrets TELEGRAM_TOKEN / TELEGRAM_CHAT_ID absents")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = SESSION.post(url, data={"chat_id": chat, "text": message}, timeout=(6, 20))
        resp.raise_for_status()
        if not resp.json().get("ok"):
            raise RuntimeError("Telegram: réponse ok=false")
    except (requests.RequestException, ValueError) as exc:
        # Never put Telegram URL/token in exception text.
        raise RuntimeError(f"Échec d'envoi Telegram: {type(exc).__name__}") from None
    return True


def discover(problems: list[dict], state: dict, report: dict, daily: bool) -> None:
    profiles = fetch_json(f"{API}/token-profiles/latest/v1")
    if not isinstance(profiles, list):
        raise RuntimeError("DexScreener: format inattendu")
    report["sources"]["dex_profiles"] = len(profiles)
    for profile in profiles:
        chain, addr = profile.get("chainId"), profile.get("tokenAddress")
        if not isinstance(chain, str) or not isinstance(addr, str) or chain not in PHANTOM_CHAINS:
            continue
        ident = project_id(chain, addr)
        text = str(profile.get("description") or "")
        matches = problem_hits(text, problems)
        if matches:
            existing = state["review_queue"].get(ident, {})
            state["review_queue"][ident] = {
                "chain": chain, "contract": addr, "matched_problems": matches,
                "description_excerpt": text[:350], "first_seen": existing.get("first_seen", iso_now()),
                "last_seen": iso_now(), "status": "UNVERIFIED_DISCOVERY",
                "source": "DexScreener latest profile"
            }
    if daily:
        # Issue searches discover problem EVIDENCE, not proof of a novel solution.
        queries = ["is:issue is:open label:bug blockchain in:title",
                   "is:issue is:open label:enhancement wallet in:title",
                   "is:issue is:open label:bug bridge in:title"]
        for q in queries:
            try:
                payload = fetch_json("https://api.github.com/search/issues",
                                     params={"q": q, "sort": "updated", "per_page": 10})
                for item in payload.get("items", []):
                    ident = str(item.get("html_url") or "")
                    if not ident:
                        continue
                    existing = state["problem_evidence"].get(ident, {})
                    state["problem_evidence"][ident] = {
                        "title": str(item.get("title", ""))[:200], "source_url": ident,
                        "first_seen": existing.get("first_seen", iso_now()),
                        "last_seen": iso_now(), "status": "NEEDS_REVIEW"
                    }
            except RuntimeError as exc:
                report["warnings"].append(str(exc))
    # Bound persistent review queues to avoid endless growth.
    for name, limit in (("review_queue", 300), ("problem_evidence", 150)):
        queue = state[name]
        if len(queue) > limit:
            ordered = sorted(queue, key=lambda k: queue[k].get("last_seen", ""), reverse=True)
            state[name] = {k: queue[k] for k in ordered[:limit]}
    report["discoveries_pending_review"] = len(state["review_queue"])
    report["problem_evidence_pending_review"] = len(state["problem_evidence"])


def monitor(approved: list[dict], state: dict, report: dict, now: dt.datetime, dry_run: bool) -> None:
    for a in approved:
        reasons = validate_approval(a, now)
        ident = project_id(a.get("chain", "unknown"), a.get("contract", "unknown"))
        if reasons:
            report["rejected"][ident] = reasons
            continue
        if ident in state["alerted"]:
            report["rejected"][ident] = ["alerte déjà envoyée"]
            continue
        try:
            pair = pair_for_token(a["chain"], a["contract"])
            if not pair:
                report["rejected"][ident] = ["aucune paire correspondant au contrat exact"]
                continue
            ok, reasons, info = market_check(pair, a, int(now.timestamp() * 1000))
            if not ok:
                report["rejected"][ident] = reasons
                continue
            secure, sec_text = security_check(a["chain"], a["contract"])
            if not secure:
                report["rejected"][ident] = [sec_text]
                continue
            sent = send_telegram(format_alert(a, info, sec_text), dry_run)
            if sent:
                state["alerted"][ident] = iso_now()
                report["alerts_sent"].append(ident)
            else:
                report["dry_run_candidates"].append(ident)
        except RuntimeError as exc:
            report["errors"].append({"project": ident, "error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--daily", action="store_true", help="collecte d'indices GitHub additionnelle")
    parser.add_argument("--skip-discovery", action="store_true")
    args = parser.parse_args()
    now = utcnow()
    state_path = ROOT / "radar_v2_state.json"
    state = read_json(state_path, {})
    for key in ("review_queue", "problem_evidence", "alerted"):
        state.setdefault(key, {})
    problems = read_json(ROOT / "problems_v2.json", [])
    approved = read_json(ROOT / "approved_projects.json", [])
    if not isinstance(problems, list) or not isinstance(approved, list):
        raise RuntimeError("Configuration JSON invalide")
    report = {"timestamp_utc": iso_now(), "sources": {}, "warnings": [], "errors": [],
              "rejected": {}, "alerts_sent": [], "dry_run_candidates": [],
              "approved_projects_count": len(approved)}
    if not args.skip_discovery:
        try:
            discover(problems, state, report, args.daily)
        except RuntimeError as exc:
            report["errors"].append({"source": "discovery", "error": str(exc)})
    monitor(approved, state, report, now, args.dry_run)
    write_json(state_path, state)
    write_json(ROOT / "radar_v2_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
