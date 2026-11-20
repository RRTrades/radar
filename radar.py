#!/usr/bin/env python3
"""
RADAR "LA PÉPITE" - entonnoir strict.
Sources (gratuites, sans clé) : DefiLlama, DexScreener, GoPlus, Binance (public).
Sortie : Telegram (TELEGRAM_TOKEN + TELEGRAM_CHAT_ID) ou console si DRY_RUN=1.
"""
import json, os, sys, time, datetime as dt
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
PROBLEMS_FILE = os.path.join(HERE, "problems.json")

# ---------------- RÉGLAGES (durcis = moins d'alertes) ----------------
MAX_ALERTS_PER_DAY = 1          # anti-spam
MAX_PROTOCOL_AGE_DAYS = 120     # sinon pas "au plus proche de la création"
MIN_TVL, MAX_TVL = 300_000, 60_000_000
MIN_TVL_GROWTH_7D = 20.0        # % : traction réelle
MIN_PROBLEM_HITS = 2            # mots-clés du problème retrouvés dans le projet
MIN_LIQUIDITY_USD = 100_000
MAX_MCAP_USD = 150_000_000      # encore petit
MAX_CHG_6H, MAX_CHG_24H = 25.0, 40.0   # pas de pump déjà lancé
MIN_PAIR_AGE_HOURS = 6          # évite les toutes premières minutes (rugs)
EARLY_MAX_AGE_HOURS = 72        # source précoce : pool de moins de 72h
EARLY_CHAINS = {"solana", "base", "ethereum"}
PHANTOM_CHAINS = {"solana", "ethereum", "base", "polygon"}  # à vérifier dans ton Phantom
GOPLUS_EVM = {"ethereum": 1, "base": 8453, "bsc": 56, "arbitrum": 42161,
              "polygon": 137, "optimism": 10}
DRY_RUN = os.getenv("DRY_RUN") == "1"
UA = {"User-Agent": "radar/1.0"}


def get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=20, **kw)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[warn] {url[:80]} -> {e}", file=sys.stderr)
        return None


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


# ---------------- COUCHE A : problèmes ----------------
def match_problem(text, problems):
    """Renvoie (problème, mots-clés trouvés) du meilleur match, ou (None, [])."""
    best, best_hits = None, []
    for p in problems:
        hits = [k for k in p["keywords"] if k.lower() in text]
        if len(hits) > len(best_hits):
            best, best_hits = p, hits
    if best and len(best_hits) >= MIN_PROBLEM_HITS:
        return best, best_hits
    return None, []


# ---------------- COUCHE B : candidats ----------------
def fetch_candidates(state, problems):
    data = get("https://api.llama.fi/protocols") or []
    now = time.time()
    out = []
    for p in data:
        tvl = p.get("tvl") or 0
        text = " ".join(str(p.get(k, "")) for k in ("name", "category", "description")).lower()
        problem, hits = match_problem(text, problems)
        if not problem or not (MIN_TVL <= tvl <= MAX_TVL):
            continue
        growth = p.get("change_7d") or 0
        slug = p.get("slug") or p.get("name")
        sym = (p.get("symbol") or "").strip()
        has_token = sym not in ("", "-", "None")
        age_days = (now - (p.get("listedAt") or 0)) / 86400 if p.get("listedAt") else 9999

        if not has_token:
            # pas encore de token : on surveille, alerte le jour où il apparaît
            if age_days <= MAX_PROTOCOL_AGE_DAYS * 2 and growth >= MIN_TVL_GROWTH_7D:
                state["watch"][slug] = {"name": p["name"], "problem": problem["id"]}
            continue

        watched = slug in state["watch"]
        if not watched and (age_days > MAX_PROTOCOL_AGE_DAYS or growth < MIN_TVL_GROWTH_7D):
            continue
        out.append(dict(p=p, problem=problem, hits=hits, sym=sym.upper(),
                        growth=growth, watched=watched, slug=slug))
    return out


# ---------------- SOURCE PRÉCOCE : nouveaux profils DexScreener ----------------
def fetch_early(state, problems):
    """Tokens qui viennent de créer un profil DexScreener (souvent < 72h),
    dont la description correspond à un problème de la carte. Détectés AVANT
    qu'un protocole soit indexé par DefiLlama."""
    profiles = get("https://api.dexscreener.com/token-profiles/latest/v1") or []
    out = []
    for pr in profiles:
        chain, addr = pr.get("chainId"), pr.get("tokenAddress")
        key = f"{chain}:{addr}"
        if chain not in EARLY_CHAINS or not addr or key in state["alerted"]:
            continue
        links = " ".join(str(l.get("label") or l.get("type") or "") for l in pr.get("links") or [])
        text = f"{pr.get('description', '')} {links}".lower()
        problem, hits = match_problem(text, problems)
        if not problem:
            continue
        d = get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}")
        pairs = [x for x in (d or {}).get("pairs") or [] if (x.get("liquidity") or {}).get("usd")]
        if not pairs:
            continue
        pair = max(pairs, key=lambda x: x["liquidity"]["usd"])
        age_h = (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 3.6e6
        if age_h > EARLY_MAX_AGE_HOURS:
            continue
        # un vrai projet a au moins un site ET un compte social
        kinds = {(l.get("type") or l.get("label") or "").lower() for l in pr.get("links") or []}
        if not ("website" in kinds and "twitter" in kinds):
            continue
        out.append(dict(p={"name": pair["baseToken"]["name"], "category": "TOKEN-NEUF"},
                        problem=problem, hits=hits, sym=pair["baseToken"]["symbol"].upper(),
                        growth=None, watched=False, slug=key, pair=pair, source="EARLY"))
    return out


# ---------------- Marché / sécurité ----------------
def find_pair(c):
    if c.get("pair"):
        return c["pair"]
    p = c["p"]
    addr = (p.get("address") or "")
    pairs = []
    if ":" in addr:
        a = addr.split(":", 1)[1]
        d = get(f"https://api.dexscreener.com/latest/dex/tokens/{a}")
        pairs = (d or {}).get("pairs") or []
    if not pairs:
        d = get(f"https://api.dexscreener.com/latest/dex/search?q={c['sym']}")
        pairs = [x for x in (d or {}).get("pairs") or []
                 if x["baseToken"]["symbol"].upper() == c["sym"]]
    pairs = [x for x in pairs if (x.get("liquidity") or {}).get("usd")]
    return max(pairs, key=lambda x: x["liquidity"]["usd"]) if pairs else None


def market_gate(pair):
    liq = pair["liquidity"]["usd"]
    mcap = pair.get("marketCap") or pair.get("fdv") or 0
    ch = pair.get("priceChange") or {}
    age_h = (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 3.6e6
    ok = (liq >= MIN_LIQUIDITY_USD and 0 < mcap <= MAX_MCAP_USD
          and (ch.get("h6") or 0) <= MAX_CHG_6H and (ch.get("h24") or 0) <= MAX_CHG_24H
          and age_h >= MIN_PAIR_AGE_HOURS)
    return ok, liq, mcap, ch


def security_gate(chain, token):
    """Échec = rejet (fail closed)."""
    if chain == "solana":
        d = get("https://api.gopluslabs.io/api/v1/solana/token_security",
                params={"contract_addresses": token})
        r = ((d or {}).get("result") or {}).get(token)
        if not r:
            return False
        return (r.get("mintable", {}).get("status") != "1"
                and r.get("freezable", {}).get("status") != "1")
    cid = GOPLUS_EVM.get(chain)
    if not cid:
        return False
    d = get(f"https://api.gopluslabs.io/api/v1/token_security/{cid}",
            params={"contract_addresses": token})
    r = ((d or {}).get("result") or {}).get(token.lower())
    if not r:
        return False
    tax = max(float(r.get("buy_tax") or 0), float(r.get("sell_tax") or 0))
    return (r.get("is_honeypot") != "1" and r.get("is_open_source") == "1"
            and r.get("hidden_owner") != "1" and r.get("is_mintable") != "1"
            and tax <= 0.05)


def platform(chain, sym):
    if chain in PHANTOM_CHAINS:
        return f"PHANTOM ({chain})"
    d = get("https://api.binance.com/api/v3/ticker/price", params={"symbol": f"{sym}USDT"})
    return "BINANCE" if d and d.get("price") else None


# ---------------- Alerte ----------------
def send(msg):
    print(msg)
    tok, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if DRY_RUN or not (tok and chat):
        return
    requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                  data={"chat_id": chat, "text": msg}, timeout=20)


def fmt(c, pair, plat, liq, mcap, ch):
    p = c["p"]
    sol = " + ".join([p.get("category", "?")] + c["hits"][:3])
    age_h = (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 3.6e6
    if c.get("source") == "EARLY":
        src = "SOURCE : DEXSCREENER-PROFIL NEUF (PRÉCOCE) | pas encore sur DefiLlama"
        trac = f"TRACTION : pool {age_h:.0f}h | site+X présents | TVL non vérifiée"
    else:
        src = "SOURCE : DEFILLAMA (protocole " + ("avec token NOUVEAU)" if c["watched"] else "récent)")
        trac = f"TRACTION : TVL +{c['growth']:.0f}% 7j"
    return (f"BUY | ${c['sym']}\n"
            f"{src}\n"
            f"PLATEFORME : {plat}\n"
            f"CONTRAT : {pair['baseToken']['address']}\n"
            f"PROBLÈME : {c['problem']['problem']}\n"
            f"SOLUTION : {sol}\n"
            f"{trac}\n"
            f"TIMING : mcap {mcap/1e6:.1f}M | liq {liq/1e3:.0f}k | 24h {ch.get('h24', 0):+.0f}%\n"
            f"RISQUE : GoPlus OK | rug possible")


def main():
    problems = load(PROBLEMS_FILE, [])
    state = load(STATE_FILE, {"alerted": [], "watch": {}, "day": "", "count": 0})
    today = dt.date.today().isoformat()
    if state["day"] != today:
        state["day"], state["count"] = today, 0

    for c in fetch_early(state, problems) + fetch_candidates(state, problems):
        if state["count"] >= MAX_ALERTS_PER_DAY:
            break
        if c["slug"] in state["alerted"]:
            continue
        pair = find_pair(c)
        if not pair:
            continue
        ok, liq, mcap, ch = market_gate(pair)
        if not ok:
            continue
        chain, token = pair["chainId"], pair["baseToken"]["address"]
        if not security_gate(chain, token):
            continue
        plat = platform(chain, c["sym"])
        if not plat:
            continue
        send(fmt(c, pair, plat, liq, mcap, ch))
        state["alerted"].append(c["slug"])
        state["count"] += 1

    save(STATE_FILE, state)


if __name__ == "__main__":
    main()  
