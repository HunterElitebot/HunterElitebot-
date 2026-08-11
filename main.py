import os
import re
import json
import html
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VERSION = "HUNTERELITE V11.42 WIDE RUNNER"

# V11.42 WIDE FUNNEL POLICY
# - Widen discovery only: MC/liquidity intake expanded.
# - Global entry/data/rug/holder/anti-chase gates stay unchanged.
# FINAL PRODUCTION POLICY
# - Story/narrative is a catalyst, never a safety bypass.
# - Active downside cannot become GUCLU GIR because of story score.
# - FAST requires fresh volume, fresh buy flow and MC progress.
# - RURU trend remains the confirmed runner path.
# - Telegram output is GIR / GUCLU GIR only; no IZLE spam.
TOKEN = os.getenv("TOKEN", "").strip()
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "").strip()

# V11.5: single-engine mode.
# Telegram getUpdates polling is OFF by default so another stale/duplicate
# poller cannot interfere with automatic signal delivery. Automatic alerts
# still work via sendMessage using SIGNAL_CHAT_ID.
POLLING_ENABLED = os.getenv("POLLING_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")

# AUTO QUALITY MODE: only 5K-10K market-cap candidates are promoted.
# Manual CA analysis is independent from this band.
MC_MIN = 2000
MC_MAX = 20000
EARLY_MC_MAX = 20000
MIN_LIQUIDITY = 600

# V11.2 â€” daha erken aday yakala, sert rug korumalarÄ±nÄ± koru
WATCH_SCORE = 47
SIGNAL_SCORE = 60
SCAN_INTERVAL = 30

BIRDEYE_POLL_INTERVAL = 60
BIRDEYE_LIMIT = 20
BIRDEYE_PAGES = 1
BIRDEYE_NEW_LISTING = "https://public-api.birdeye.so/defi/v2/tokens/new_listing"

WATCH_REPEAT_COOLDOWN = 21600
MAX_WATCH_DROP_5M = -10.0
MAX_SIGNAL_DROP_1H = -35.0
MAX_CRASH_DROP_6H = -35.0
MAX_CRASH_DROP_24H = -55.0

MIN_MOMENTUM_SIGNAL = 10
MIN_MC_GROWTH = 1.005
MAX_PAIR_AGE_HOURS = 12.0
TREND_CONFIRM_SCANS = 2

# QUALITY MODE: cut low-activity Telegram noise while preserving RURU-like flow.
WATCH_MIN_BUYS_5M = 5
WATCH_MIN_VOL_5M = 500
WATCH_MIN_BUY_SELL_RATIO = 1.10
AUTO_MAX_PRICE5 = 180.0

# FAST GIR lane: bypass 2-scan trend wait only when the first scan is already strong.
FAST_GIR_MIN_SCORE = 60
FAST_GIR_MIN_BUYS_5M = 15
FAST_GIR_MIN_BUY_SELL_RATIO = 1.20
FAST_GIR_MIN_VOL_5M = 2000
FAST_GIR_MIN_LIQ_MC_RATIO = 0.18
FAST_GIR_MIN_PRICE5 = -5.0
FAST_GIR_MAX_PRICE5 = 150.0
# POSITIVE ANTI-CHASE: do not call a parabolic move a fresh entry.
CHASE_BLOCK_GUCLU_5M = 70.0
CHASE_BLOCK_GIR_5M = 100.0
# GLOBAL ENTRY GATE: every automatic lane must pass this final gate.
GLOBAL_MAX_TOP10_GIR = 35.0
GLOBAL_MAX_TOP10_GUCLU = 18.0
GLOBAL_MAX_LIQ_DROP_PCT = 20.0
GLOBAL_MIN_LIQ_MC = 0.15
GLOBAL_MIN_FLOW = 0.90
GLOBAL_MIN_BUY_DELTA = 1
GLOBAL_MIN_VOL_DELTA = 50
GLOBAL_MIN_MC_PROGRESS = 0.0
GLOBAL_IDEAL_PRICE5_MAX = 60.0
# V11.40 DATA INTEGRITY: never compare incompatible/stale snapshots.
SNAPSHOT_MAX_AGE_SEC = 75.0
MAX_VALID_MC_DELTA_PCT = 300.0
MAX_VALID_LIQ_UP_PCT = 500.0
# When no social channel is published, GUCLU GIR requires unusually clean on-chain structure.
NO_SOCIAL_GUCLU_MAX_TOP10 = 10.0
NO_SOCIAL_GUCLU_MIN_LIQ_MC = 0.80

FAST_GUCLU_MIN_SCORE = 70
FAST_GUCLU_MIN_BUYS_5M = 30
FAST_GUCLU_MIN_BUY_SELL_RATIO = 1.30
FAST_GUCLU_MIN_VOL_5M = 4000
FAST_GUCLU_MIN_LIQ_MC_RATIO = 0.22

# CONTINUATION GUARD
# FAST candidates are remembered first; signal is released only after a later scan
# confirms that new buying is still pushing the market forward.
CONT_MIN_SECONDS = 10
CONT_MAX_SECONDS = 120
CONT_MIN_VOL_DELTA = 250
CONT_MIN_BUY_DELTA = 2
CONT_MIN_MC_PCT = 1.0
CONT_MAX_MC_DROP_PCT = -4.0
CONT_MIN_FLOW_RATIO = 1.10
CONT_HIGH_PUMP_PRICE5 = 80.0
CONT_HIGH_PUMP_MIN_MC_PCT = 2.0

# V11.37 TRAJECTORY / ACCELERATION ENGINE
# The edge over static Axiom filters: compare 30/60/90s snapshots and detect acceleration.
TRJ_MIN_TICKS = 2
TRJ_STRONG_TICKS = 3
TRJ_MIN_MC_PCT = 4.0
TRJ_STRONG_MC_PCT = 9.0
TRJ_MIN_VOL_DELTA = 500
TRJ_STRONG_VOL_DELTA = 1400
TRJ_MIN_BUY_DELTA = 4
TRJ_STRONG_BUY_DELTA = 10
TRJ_MIN_FLOW = 1.12
TRJ_STRONG_FLOW = 1.28
TRJ_MIN_VOL_MC = 0.22
TRJ_STALL_MC_PCT = 1.0
TRJ_MAX_HISTORY = 3

# V11.36 VOLUME BREAKOUT ENGINE
# Detect early volume expansion that is actually translating into price/MC progress.
VB_MIN_VOL_MC = 0.35
VB_STRONG_VOL_MC = 0.70
VB_MIN_VOL_DELTA = 400
VB_MIN_BUY_DELTA = 3
VB_MIN_FRESH_FLOW = 1.15
VB_MIN_MC_PCT = 2.0
VB_IDEAL_PRICE5_MIN = 8.0
VB_IDEAL_PRICE5_MAX = 70.0
VB_MAX_GUCLU_PRICE5 = 90.0
VB_STALL_MC_PCT = 0.5
VB_STALL_FLOW = 1.05

# NEGATIVE PRICE GUARD
# Story/Narrative score must never override active downside.
NEG_PRICE_BLOCK_GUCLU_5M = -2.0
NEG_PRICE_BLOCK_GIR_5M = -8.0
NEG_PRICE_RECOVERY_MC_PCT = 2.0
NEG_PRICE_RECOVERY_FLOW = 1.20

SIGNAL_MIN_BUYS_5M = 6
SIGNAL_MIN_BUY_SELL_RATIO = 1.05
SIGNAL_MIN_VOL_5M = 700
MIN_VOL_GROWTH = 1.00

# Liquidity Drain Guard
# V11.34 signal thresholds stay unchanged.
# This layer only blocks/cancels when liquidity collapses between scans.
LIQ_DRAIN_GUARD_ENABLED = True
LIQ_DRAIN_WARN_PCT = 20.0
LIQ_DRAIN_HARD_PCT = 35.0

STATE_FILE = "/tmp/hunterelite_v11_2_state.json"

if not TOKEN:
    raise RuntimeError("Railway TOKEN variable bulunamadi!")

TG_API = f"https://api.telegram.org/bot{TOKEN}"
SOL_CA = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

signal_chats = set()
token_states = {}
state_lock = threading.Lock()
birdeye_lock = threading.Lock()
birdeye_cache = []
birdeye_last_fetch = 0.0
birdeye_last_error = ""

radar_stats_lock = threading.Lock()
last_diag_send = 0.0
discovery_seen = {}
candidate_sources = {}
discovery_seen_lock = threading.Lock()
DISCOVERY_MEMORY_SECONDS = 21600
RADAR_RAW_LIMIT = 240
RADAR_TARGET = 80
BIRDEYE_TARGET = 20
GECKO_TARGET = 60
DEX_TARGET = 20
MAX_REPEAT_PER_SCAN = 20
FRESH_PAIR_MAX_HOURS = 6.0

# Keyless GeckoTerminal feed. No API key required.
GECKO_POLL_INTERVAL = 30
GECKO_PAGES = 3
GECKO_CACHE_LIMIT = 100
GECKO_LIQ_TTL = 900
gecko_lock = threading.Lock()
gecko_cache = []
gecko_liq_cache = {}
gecko_last_fetch = 0.0
gecko_last_error = ""

VIRAL_RADAR_ENABLED = True
VIRAL_SCORE_BONUS_MAX = 12

radar_stats = {
    "updated": 0,
    "radar": 0,
    "processed": 0,
    "pair_yok": 0, "stale_pair": 0, "viral_hot": 0, "viral_rising": 0, "h1_fail_values": [], "prepump": 0, "prepump_safe": 0, "src_birdeye": 0, "src_gecko": 0, "src_dex": 0, "src_birdeye_stale": 0, "src_gecko_stale": 0, "src_dex_stale": 0, "src_birdeye_safe": 0, "src_gecko_safe": 0, "src_dex_safe": 0,
    "basic_fail": 0,
    "crash_fail": 0,
    "watch": 0,
    "signal": 0,
    "mc_fail": 0,
    "liq_fail": 0,
    "holder_fail": 0,
    "authority_fail": 0,
    "rug_fail": 0,
    "score_fail": 0,
    "buy_fail": 0,
    "volume_fail": 0,
    "trend_fail": 0,
    "momentum_fail": 0,
    "unique_new": 0, "repeat": 0, "pair_pass": 0, "mc_pass": 0,
    "liq_pass": 0, "liq_missing": 0, "gecko_liq_ok": 0, "gecko_liq_missing": 0, "liq_0_200": 0, "liq_200_500": 0, "liq_500_800": 0, "liq_800_plus": 0, "liq_fallback_ok": 0, "liq_fallback_missing": 0, "holder_pass": 0, "holder_missing": 0, "holder_50_60": 0, "holder_60_70": 0, "holder_70_82": 0, "holder_82_plus": 0, "safety_pass": 0, "rug_ok": 0, "auth_ok": 0, "crash_ok": 0, "age_fail": 0, "h1_fail": 0, "h6_fail": 0, "h24_fail": 0,
    "score_pass": 0, "activity_pass": 0, "trend_pass": 0,
    "momentum_pass": 0,
}

def load_state():
    try:
        p = Path(STATE_FILE)
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with state_lock:
                token_states.update(data)
    except Exception as e:
        print("STATE LOAD WARNING:", repr(e), flush=True)

def save_state():
    try:
        with state_lock:
            data = dict(token_states)
        Path(STATE_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("STATE SAVE WARNING:", repr(e), flush=True)

for env_name in ("SIGNAL_CHAT_ID", "CHAT_ID", "TELEGRAM_CHAT_ID", "USER_ID"):
    raw = os.getenv(env_name, "").strip()
    if raw:
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                signal_chats.add(int(part))

def get_json(url, timeout=15, headers=None):
    req_headers = {"User-Agent": "HunterElite-V11.2", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def telegram(method, data=None, timeout=35):
    data = data or {}
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(f"{TG_API}/{method}", data=body, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def clean_telegram_text(text):
    """One final cleanup point for every outgoing Telegram message."""
    s = "" if text is None else str(text)
    replacements = {
        "âš ï¸": "UYARI:", "ğŸ‘€": "", "ğŸš¨": "", "ğŸ’": "", "ğŸŸ¡": "",
        "ğŸ”´": "", "ğŸŸ¢": "", "â³": "", "ğŸ“ˆ": "", "ğŸ“Š": "", "ğŸ’§": "",
        "âš¡": "", "ğŸ’µ": "", "ğŸ‘¥": "", "ğŸ›¡": "", "ğŸš€": "", "ğŸ¯": "", "â±": "",
        "SÄ°NYAL Ä°PTAL": "SINYAL IPTAL", "Ä°ZLE": "IZLE",
        "GÄ°RME": "GIRME", "GÄ°R": "GIR", "POTANSÄ°YEL": "POTANSIYEL",
        "ÅŸartlarÄ±": "sartlari", "kÃ¶tÃ¼leÅŸti": "kotulesti",
        "giriÅŸ": "giris", "iÃ§in": "icin", "deÄŸil": "degil", "yaÅŸÄ±": "yasi",
        "Ã¢Å¡ Ã¯Â¸Â": "UYARI:", "ÄŸÅ¸â€˜â‚¬": "", "ÄŸÅ¸Å¡Â¨": "", "ÄŸÅ¸â€™Å½": "",
        "ÄŸÅ¸Å¸Â¡": "", "ÄŸÅ¸â€Â´": "", "Ã¢ÂÂ³": "", "Ã„Â°ZLE": "IZLE",
        "SÃ„Â°NYAL Ã„Â°PTAL": "SINYAL IPTAL", "GÃ„Â°RME": "GIRME",
        "GÃ„Â°R": "GIR", "POTANSÃ„Â°YEL": "POTANSIYEL",
        "Ã…Å¸artlarÃ„Â±": "sartlari", "kÃƒÂ¶tÃƒÂ¼leÃ…Å¸ti": "kotulesti",
        "giriÃ…Å¸": "giris", "iÃƒÂ§in": "icin", "deÃ„Å¸il": "degil",
        "yaÃ…Å¸Ã„Â±": "yasi",
        "Ã¢Å¡ Ã¯Â¸Â VERÃ„Â° ALINAMADI": "VERI BEKLENIYOR",
        "VERÃ„Â° ALINAMADI": "VERI BEKLENIYOR",
        "VERÄ° ALINAMADI": "VERI BEKLENIYOR",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s.replace("\ufffd", "")

def axiom_token_url(ca):
    return f"https://axiom.trade/t/{ca}/@215162?chain=sol"


def send(chat_id, text):
    try:
        text = clean_telegram_text(text)

        # Detect CA before HTML escaping.
        ca_match = re.search(r"(?m)^CA:\s*([1-9A-HJ-NP-Za-km-z]{32,44})\s*$", text)
        ca = ca_match.group(1) if ca_match else None

        # Escape every outgoing character first so Telegram HTML is always valid.
        safe_text = html.escape(text, quote=False)

        # Make the CONTRACT ADDRESS itself clickable.
        if ca:
            plain = f"CA: {html.escape(ca, quote=False)}"
            linked = f'CA: <a href="{axiom_token_url(ca)}">{html.escape(ca, quote=False)}</a>'
            safe_text = safe_text.replace(plain, linked, 1)

        payload = {
            "chat_id": str(chat_id),
            "text": safe_text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": "true"
        }

        # Keep the dedicated Axiom button too.
        if ca:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": [[
                    {"text": "ğŸš€ AXIOM'DA AÃ‡", "url": axiom_token_url(ca)}
                ]]
            }, ensure_ascii=False)

        telegram("sendMessage", payload)
    except Exception as e:
        print("SEND ERROR:", repr(e), flush=True)

def num(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def safe_int(value):
    try:
        return int(value or 0)
    except Exception:
        return 0

def money(value):
    value = num(value)
    if value is None:
        return "âš ï¸ VERÄ° ALINAMADI"
    if abs(value) >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value/1_000:.2f}K"
    return f"${value:.2f}"

def percent(value):
    value = num(value)
    if value is None:
        return "N/A"
    return f"{value:.1f}%"

def dex_pairs(ca):
    urls = [
        f"https://api.dexscreener.com/token-pairs/v1/solana/{ca}",
        f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
    ]
    for url in urls:
        try:
            data = get_json(url)
            if isinstance(data, list):
                pairs = data
            elif isinstance(data, dict):
                pairs = data.get("pairs") or []
            else:
                pairs = []
            sol_pairs = [p for p in pairs if str(p.get("chainId", "solana")).lower() == "solana"]
            if sol_pairs:
                return sol_pairs
        except Exception as e:
            print("DEX PAIR ERROR:", repr(e), flush=True)
    return []

def best_pair(ca):
    pairs = dex_pairs(ca)
    if not pairs:
        return None
    return max(pairs, key=lambda p: num((p.get("liquidity") or {}).get("usd"), 0))

def extract_birdeye_items(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "tokens", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    for key in ("items", "tokens", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []

def birdeye_item_time(item):
    """Best-effort listing timestamp for Birdeye pagination."""
    if not isinstance(item, dict):
        return None
    for key in (
        "liquidityAddedAt",
        "liquidity_added_at",
        "listedAt",
        "listed_at",
        "createdAt",
        "created_at",
        "timestamp",
        "time",
    ):
        value = num(item.get(key))
        if value is None:
            continue
        # Normalize millisecond timestamps when encountered.
        if value > 10_000_000_000:
            value = value / 1000.0
        if value > 0:
            return int(value)
    return None


def birdeye_new_candidates(force=False):
    global birdeye_cache, birdeye_last_fetch, birdeye_last_error

    if not BIRDEYE_API_KEY:
        return []

    now = time.time()
    with birdeye_lock:
        if not force and birdeye_cache and now - birdeye_last_fetch < BIRDEYE_POLL_INTERVAL:
            return list(birdeye_cache)

    try:
        url = (
            f"{BIRDEYE_NEW_LISTING}?"
            + urllib.parse.urlencode({
                "limit": 20,
                "meme_platform_enabled": "true",
            })
        )
        payload = get_json(
            url,
            timeout=15,
            headers={"X-API-KEY": BIRDEYE_API_KEY, "x-chain": "solana"},
        )
        items = extract_birdeye_items(payload)

        newest = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ca = ""
            for key in ("address", "token_address", "tokenAddress", "mint", "mintAddress"):
                raw = item.get(key)
                if raw:
                    ca = str(raw).strip()
                    break
            if ca and SOL_CA.match(ca):
                newest.append(ca)

        # Rolling ingestion: each poll contributes up to 20 new addresses.
        # Keep the newest unique 80 so repeated scans don't pretend one response is 60/120 listings.
        with birdeye_lock:
            merged = []
            seen = set()
            for ca in newest + list(birdeye_cache):
                if ca not in seen:
                    seen.add(ca)
                    merged.append(ca)
            birdeye_cache = merged[:80]
            birdeye_last_fetch = now
            birdeye_last_error = ""

        print(
            f"BIRDEYE ROLLING FRESH: api={len(newest)} cache={len(birdeye_cache)}",
            flush=True,
        )
        return list(birdeye_cache)

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        err = f"HTTP {e.code}: {body[:220]}"
        with birdeye_lock:
            birdeye_last_error = err
            birdeye_last_fetch = now
        print("BIRDEYE ERROR:", err, flush=True)

    except Exception as e:
        err = repr(e)
        with birdeye_lock:
            birdeye_last_error = err
            birdeye_last_fetch = now
        print("BIRDEYE ERROR:", err, flush=True)

    with birdeye_lock:
        return list(birdeye_cache)

def gecko_new_candidates(force=False):
    """
    Keyless GeckoTerminal Solana fresh-pool feed.
    Adds candidate coverage when Birdeye quota is exhausted.
    Also caches reserve_in_usd as a liquidity fallback.
    """
    global gecko_cache, gecko_liq_cache, gecko_last_fetch, gecko_last_error

    now = time.time()
    with gecko_lock:
        if not force and gecko_cache and now - gecko_last_fetch < GECKO_POLL_INTERVAL:
            return list(gecko_cache)

    found, seen, liq_updates = [], set(), {}
    errors = []

    endpoint_templates = [
        "https://api.geckoterminal.com/api/v2/networks/solana/new_pools",
        "https://api.geckoterminal.com/api/v2/networks/solana/pools",
    ]

    for endpoint in endpoint_templates:
        before = len(found)
        for page in range(1, GECKO_PAGES + 1):
            url = endpoint + "?" + urllib.parse.urlencode({
                "include": "base_token",
                "page": page,
            })
            try:
                payload = get_json(
                    url,
                    timeout=15,
                    headers={"accept": "application/json", "User-Agent": "HunterElite-V11.34"},
                )
                if not isinstance(payload, dict):
                    errors.append(f"{page}:BAD_PAYLOAD")
                    continue

                included_map = {}
                included = payload.get("included")
                if isinstance(included, list):
                    for obj in included:
                        if not isinstance(obj, dict):
                            continue
                        oid = str(obj.get("id") or "")
                        attrs = obj.get("attributes")
                        attrs = attrs if isinstance(attrs, dict) else {}
                        address = str(attrs.get("address") or "").strip()
                        if oid and address:
                            included_map[oid] = address

                rows = payload.get("data")
                if not isinstance(rows, list):
                    continue

                for pool in rows:
                    if not isinstance(pool, dict):
                        continue

                    attrs = pool.get("attributes")
                    attrs = attrs if isinstance(attrs, dict) else {}
                    relationships = pool.get("relationships")
                    relationships = relationships if isinstance(relationships, dict) else {}

                    base_rel = relationships.get("base_token")
                    base_rel = base_rel if isinstance(base_rel, dict) else {}
                    base_data = base_rel.get("data")
                    base_data = base_data if isinstance(base_data, dict) else {}
                    base_id = str(base_data.get("id") or "")

                    ca = included_map.get(base_id, "")
                    if not ca and "_" in base_id:
                        maybe = base_id.split("_", 1)[-1].strip()
                        if SOL_CA.fullmatch(maybe):
                            ca = maybe

                    if not (ca and SOL_CA.fullmatch(ca)):
                        continue

                    gecko_liq = None
                    for key in ("reserve_in_usd", "liquidity_usd", "reserve_usd"):
                        gecko_liq = num(attrs.get(key))
                        if gecko_liq is not None:
                            break

                    if gecko_liq is not None and gecko_liq > 0:
                        liq_updates[ca] = (gecko_liq, now)

                    if ca not in seen:
                        seen.add(ca)
                        found.append(ca)

            except Exception as e:
                errors.append(f"{page}:{type(e).__name__}")

        # Prefer new_pools. Only use broad pools endpoint if it produced too few.
        if len(found) - before >= GECKO_TARGET:
            break

    with gecko_lock:
        merged, merged_seen = [], set()
        for ca in found + list(gecko_cache):
            if ca not in merged_seen:
                merged_seen.add(ca)
                merged.append(ca)

        gecko_cache = merged[:GECKO_CACHE_LIMIT]
        gecko_liq_cache.update(liq_updates)

        # Remove stale cached liquidity.
        for ca, item in list(gecko_liq_cache.items()):
            try:
                _, ts = item
                if now - float(ts) > GECKO_LIQ_TTL:
                    gecko_liq_cache.pop(ca, None)
            except Exception:
                gecko_liq_cache.pop(ca, None)

        gecko_last_fetch = now
        gecko_last_error = ";".join(errors[:6])

    print(
        f"GECKO FEED: fresh={len(found)} cache={len(gecko_cache)} "
        f"liq_cache={len(gecko_liq_cache)} err={gecko_last_error or '-'}",
        flush=True,
    )
    return list(gecko_cache)


def gecko_cached_liquidity(ca):
    """Return recent Gecko reserve/liquidity USD for a token, if available."""
    now = time.time()
    with gecko_lock:
        item = gecko_liq_cache.get(ca)
    if not item:
        return None
    try:
        value, ts = item
        if now - float(ts) > GECKO_LIQ_TTL:
            return None
        value = num(value)
        return value if value is not None and value > 0 else None
    except Exception:
        return None


def discovery_candidates():
    endpoints = [
        "https://api.dexscreener.com/token-profiles/latest/v1",
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/token-boosts/top/v1",
        "https://api.dexscreener.com/community-takeovers/latest/v1",
    ]

    candidate_sources.clear()

    # 1) Birdeye: bonus feed when quota works.
    birdeye_found, used = [], set()
    for ca in birdeye_new_candidates():
        if ca and ca not in used:
            used.add(ca)
            birdeye_found.append(ca)
            candidate_sources[ca] = "BIRDEYE"

    # 2) GeckoTerminal: keyless primary fallback.
    gecko_found = []
    for ca in gecko_new_candidates():
        if ca and ca not in used:
            used.add(ca)
            gecko_found.append(ca)
            candidate_sources[ca] = "GECKO"

    # 3) DEX: last discovery fallback.
    dex_found = []
    for url in endpoints:
        try:
            data = get_json(url)
            if not isinstance(data, list):
                continue
            for item in data:
                if str(item.get("chainId", "")).lower() != "solana":
                    continue
                ca = str(item.get("tokenAddress", "")).strip()
                if not (ca and SOL_CA.match(ca)):
                    continue
                if ca in used:
                    continue
                used.add(ca)
                dex_found.append(ca)
                candidate_sources[ca] = "DEX"
        except Exception as e:
            print("DISCOVERY ERROR:", repr(e), flush=True)

    selected = []

    # Birdeye gets up to 20 slots if actually returning data.
    for ca in birdeye_found[:BIRDEYE_TARGET]:
        selected.append(ca)

    # Gecko fills most/all remaining coverage.
    remaining = max(0, RADAR_TARGET - len(selected))
    for ca in gecko_found[:min(GECKO_TARGET, remaining)]:
        selected.append(ca)

    # DEX fills any remaining holes, up to 20.
    remaining = max(0, RADAR_TARGET - len(selected))
    for ca in dex_found[:min(DEX_TARGET, remaining)]:
        selected.append(ca)

    # If Birdeye is dead and Gecko had >60 unique fresh pools,
    # let Gecko fill unused DEX holes only after DEX allocation.
    if len(selected) < RADAR_TARGET:
        already = set(selected)
        for ca in gecko_found:
            if ca not in already:
                selected.append(ca)
                already.add(ca)
                if len(selected) >= RADAR_TARGET:
                    break

    return selected[:RADAR_TARGET]

def birdeye_market_data(ca):
    """Fetch Birdeye single-token market data as fallback when DEX liquidity is missing."""
    if not BIRDEYE_API_KEY:
        return None
    try:
        url = (
            "https://public-api.birdeye.so/defi/v3/token/market-data?"
            + urllib.parse.urlencode({"address": ca})
        )
        payload = get_json(
            url,
            timeout=12,
            headers={"X-API-KEY": BIRDEYE_API_KEY, "x-chain": "solana"},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None
    except Exception as e:
        print("BIRDEYE MARKET DATA ERROR:", ca, repr(e), flush=True)
        return None


def rugcheck(ca):
    try:
        return get_json(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report")
    except Exception as e:
        print("RUGCHECK ERROR:", repr(e), flush=True)
        return None

def _protocol_holder_accounts(report):
    """
    Exclude AMM/pool/market/bonding-curve inventory from user-holder concentration.
    Uses only accounts RugCheck itself identifies as protocol infrastructure.
    """
    addresses, owners = set(), set()
    if not isinstance(report, dict):
        return addresses, owners

    for market in report.get("markets") or []:
        if not isinstance(market, dict):
            continue
        for key in ("pubkey", "liquidityA", "liquidityB"):
            value = market.get(key)
            if value:
                addresses.add(str(value))
        for key in ("liquidityAAccount", "liquidityBAccount"):
            acct = market.get(key) or {}
            if isinstance(acct, dict):
                owner = acct.get("owner")
                if owner:
                    owners.add(str(owner))

    known = report.get("knownAccounts") or {}
    if isinstance(known, dict):
        for address, meta in known.items():
            meta = meta or {}
            if isinstance(meta, dict):
                blob = f"{meta.get('name','')} {meta.get('type','')}".lower()
            else:
                blob = str(meta).lower()
            if any(word in blob for word in ("amm", "pool", "dex", "market", "bonding", "liquidity")):
                addresses.add(str(address))

    return addresses, owners


def holder_pct(holder):
    """
    IMPORTANT RugCheck fix:
    topHolders[].pct is ALREADY in percentage points.
    Example: pct=0.867 means 0.867%, not 86.7%.
    """
    if not isinstance(holder, dict):
        return None

    value = num(holder.get("pct"))
    if value is not None:
        return value if 0 <= value <= 100 else None

    for key in ("percentage", "percent"):
        value = num(holder.get(key))
        if value is not None:
            return value if 0 <= value <= 100 else None

    # Only this explicitly-named field may arrive as a 0..1 fraction.
    value = num(holder.get("ownershipPercentage"))
    if value is not None:
        if 0 <= value <= 1:
            value *= 100
        return value if 0 <= value <= 100 else None

    return None


def holders(report):
    """
    Calculate user-wallet Top-1/5/10 from RugCheck.

    Fixes two false-high causes:
    1) pct values below 1 are NOT multiplied by 100.
    2) RugCheck-identified pool/AMM/bonding-curve inventory is excluded.

    The existing V11.34 Top-10 safety threshold is NOT changed.
    """
    if not report:
        return None, None, None

    items = report.get("topHolders") or report.get("top_holders") or []
    protocol_addresses, protocol_owners = _protocol_holder_accounts(report)

    owner_values = {}
    anonymous_values = []

    for item in items:
        if not isinstance(item, dict):
            continue

        value = holder_pct(item)
        if value is None:
            continue

        address = str(
            item.get("address")
            or item.get("tokenAccount")
            or item.get("token_account")
            or ""
        )
        owner = str(item.get("owner") or "")

        if address and address in protocol_addresses:
            continue
        if owner and (owner in protocol_owners or owner in protocol_addresses):
            continue

        # Multiple token accounts belonging to the same wallet count as one holder.
        if owner:
            owner_values[owner] = owner_values.get(owner, 0.0) + value
        else:
            anonymous_values.append(value)

    values = sorted(list(owner_values.values()) + anonymous_values, reverse=True)
    if not values:
        return None, None, None

    top1 = values[0]
    top5 = sum(values[:5])
    top10 = sum(values[:10])

    # Invalid parse protection: never convert impossible totals into a valid pass.
    if top1 > 100 or top5 > 100.5 or top10 > 100.5:
        return None, None, None

    return top1, top5, top10


def authority(report, key):
    if not report:
        return None
    values = [
        report.get(key),
        (report.get("token") or {}).get(key),
        (report.get("tokenMeta") or {}).get(key)
    ]
    for value in values:
        if value is None:
            continue
        if value is False:
            return False
        if value is True:
            return True
        text = str(value).strip().lower()
        if text in ("", "none", "null", "false", "revoked", "disabled"):
            return False
        return True
    return None

def rug_signals(report):
    result = {"rug": False, "honeypot": False, "insider": False, "sniper": False, "bundler": False}
    if not report:
        return result
    try:
        blob = json.dumps(report, ensure_ascii=False).lower()
    except Exception:
        blob = str(report).lower()
    risks = report.get("risks") or []
    try:
        risks_blob = json.dumps(risks, ensure_ascii=False).lower()
    except Exception:
        risks_blob = ""

    if report.get("rugged") is True:
        result["rug"] = True

    words = {
        "honeypot": ("honeypot",),
        "insider": ("insider",),
        "sniper": ("sniper", "sniping"),
        "bundler": ("bundler", "bundle"),
    }
    for key, variants in words.items():
        for word in variants:
            if word in risks_blob:
                result[key] = True
            patterns = [
                f'"{word}":true',
                f'"{word}": true',
                f"{word} detected",
                f"{word} risk",
            ]
            if any(p in blob for p in patterns):
                result[key] = True

    if "rug pull" in risks_blob or "rugpull" in risks_blob:
        result["rug"] = True
    return result

def token_metrics(pair):
    txns = pair.get("txns") or {}
    m5 = txns.get("m5") or {}
    h1 = txns.get("h1") or {}
    volume = pair.get("volume") or {}
    price = pair.get("priceChange") or {}
    liquidity = pair.get("liquidity") or {}

    market_cap = num(pair.get("marketCap"))
    if market_cap is None:
        market_cap = num(pair.get("fdv"))

    created_ms = num(pair.get("pairCreatedAt"))
    age_hours = None
    if created_ms is not None:
        age_hours = max(0.0, (time.time() * 1000 - created_ms) / 3_600_000)

    return {
        "mc": market_cap,
        "liq": num(liquidity.get("usd")),
        "buys5": safe_int(m5.get("buys")),
        "sells5": safe_int(m5.get("sells")),
        "buys1h": safe_int(h1.get("buys")),
        "sells1h": safe_int(h1.get("sells")),
        "vol5": num(volume.get("m5")),
        "vol1h": num(volume.get("h1")),
        "price5": num(price.get("m5")),
        "price1h": num(price.get("h1")),
        "price6h": num(price.get("h6")),
        "price24h": num(price.get("h24")),
        "age_hours": age_hours,
    }

def calculate_score(pair, report):
    m = token_metrics(pair)
    score = 100
    risks = []
    mc, liq = m["mc"], m["liq"]

    if mc is None:
        score -= 20
        risks.append("Market cap verisi yok")
    elif mc < MC_MIN or mc > MC_MAX:
        score -= 20
        risks.append("Market cap hedef bÃ¶lgesi dÄ±ÅŸÄ±nda")

    if liq is None:
        score -= 25
        risks.append("Likidite verisi yok")
    elif liq < 1000:
        score -= 35
        risks.append("Likidite Ã§ok dÃ¼ÅŸÃ¼k")
    elif liq < MIN_LIQUIDITY:
        score -= 20
        risks.append("Likidite dÃ¼ÅŸÃ¼k")

    top1, top5, top10 = holders(report)

    if report is None:
        score -= 15
        risks.append("RugCheck verisi yok")
    elif top10 is None:
        score -= 10
        risks.append("Holder daÄŸÄ±lÄ±mÄ± doÄŸrulanamadÄ±")
    else:
        if top10 >= 82:
            score -= 40
            risks.append("Top-10 holder aÅŸÄ±rÄ± yoÄŸun")
        elif top10 >= 70:
            score -= 30
            risks.append("Top-10 holder Ã§ok yÃ¼ksek")
        elif top10 >= 60:
            score -= 20
            risks.append("Top-10 holder yÃ¼ksek")
        elif top10 >= 50:
            score -= 10
            risks.append("Top-10 holder dikkat")

    mint = authority(report, "mintAuthority")
    freeze = authority(report, "freezeAuthority")

    if mint is True:
        score -= 30
        risks.append("Mint authority aktif")
    elif mint is None:
        score -= 5
        risks.append("Mint authority doÄŸrulanamadÄ±")

    if freeze is True:
        score -= 30
        risks.append("Freeze authority aktif")
    elif freeze is None:
        score -= 5
        risks.append("Freeze authority doÄŸrulanamadÄ±")

    sig = rug_signals(report)

    if sig["rug"]:
        score -= 60
        risks.append("RUG sinyali")
    if sig["honeypot"]:
        score -= 50
        risks.append("Honeypot sinyali")
    if sig["insider"]:
        score -= 15
        risks.append("Insider sinyali")
    if sig["sniper"]:
        score -= 10
        risks.append("Sniper yoÄŸunluÄŸu")
    if sig["bundler"]:
        score -= 10
        risks.append("Bundler sinyali")

    buys, sells = m["buys5"], m["sells5"]
    if buys + sells >= 10 and sells > buys * 1.5:
        score -= 10
        risks.append("5dk satÄ±ÅŸ baskÄ±sÄ±")

    if m["price5"] is not None and m["price5"] <= -25:
        score -= 10
        risks.append("5dk sert fiyat dÃ¼ÅŸÃ¼ÅŸÃ¼")

    score = max(0, min(100, int(score)))

    severe = (
        sig["rug"]
        or sig["honeypot"]
        or mint is True
        or freeze is True
        or (top10 is not None and top10 >= 80)
    )

    if severe:
        decision = "ğŸ”´ GÄ°RME"
    elif score >= 75 and mc is not None and MC_MIN <= mc <= EARLY_MC_MAX:
        decision = "ğŸŸ¢ UYGUN GÄ°RÄ°Å"
    elif score >= 55:
        decision = "ğŸŸ¡ BEKLE"
    else:
        decision = "ğŸ”´ GÄ°RME"

    return {
        **m,
        "score": score,
        "decision": decision,
        "risks": risks,
        "top1": top1,
        "top5": top5,
        "top10": top10,
        "mint": mint,
        "freeze": freeze,
        "signals": sig,
    }

def momentum_score(old, new):
    if not old:
        return 0

    points = 0

    old_buys, new_buys = old.get("buys5", 0), new.get("buys5", 0)
    if old_buys > 0 and new_buys >= old_buys * 1.15:
        points += 10
    elif old_buys > 0 and new_buys >= old_buys * 0.95:
        points += 5

    old_vol, new_vol = old.get("vol5") or 0, new.get("vol5") or 0
    if old_vol > 0 and new_vol >= old_vol * 1.12:
        points += 10
    elif old_vol > 0 and new_vol >= old_vol * 0.95:
        points += 5

    old_mc, new_mc = old.get("mc") or 0, new.get("mc") or 0
    if old_mc > 0 and new_mc >= old_mc * 1.015:
        points += 5

    buys, sells = new.get("buys5", 0), new.get("sells5", 0)
    if buys >= SIGNAL_MIN_BUYS_5M and buys >= max(sells * SIGNAL_MIN_BUY_SELL_RATIO, 1):
        points += 10

    p5 = new.get("price5")
    if p5 is not None and 0.5 <= p5 <= 55:
        points += 5

    return points

def authority_text(value):
    if value is True:
        return "ğŸš¨ AKTÄ°F"
    if value is False:
        return "âœ… KAPALI"
    return "âš ï¸ N/A"

def potential_label(result, momentum=0):
    """Heuristic only: expresses upside setup quality, never a return guarantee."""
    if not result:
        return "âŒ YETERSÄ°Z VERÄ°"

    # Hard safety blocks first.
    if result["signals"]["rug"] or result["signals"]["honeypot"]:
        return "â›” RUG RÄ°SKÄ°"
    if result["mint"] is True or result["freeze"] is True:
        return "â›” YETKÄ° RÄ°SKÄ°"
    if result["liq"] is None or result["liq"] < MIN_LIQUIDITY:
        return "ğŸ”´ ZAYIF"
    if result["top10"] is not None and result["top10"] >= 75:
        return "ğŸ”´ DAÄILIM RÄ°SKÄ°"

    score = result["score"] + momentum
    mc = result["mc"] or 0
    buys = result["buys5"]
    sells = result["sells5"]
    vol5 = result["vol5"] or 0
    p5 = result["price5"]

    buy_ratio_ok = sells == 0 or buys >= sells * 1.20

    # "100X" is a potential tag, not a prediction.
    if (
        2000 <= mc <= 6500
        and score >= 78
        and buys >= 8
        and buy_ratio_ok
        and vol5 >= 500
        and p5 is not None and 1 <= p5 <= 45
    ):
        return "ğŸ’ 100X POTANSÄ°YEL ADAYI"

    if (
        2000 <= mc <= 9000
        and score >= 68
        and buys >= 5
        and buy_ratio_ok
        and vol5 >= 250
    ):
        return "ğŸš€ 5Xâ€“10X POTANSÄ°YEL ADAYI"

    if score >= 58:
        return "ğŸŸ¡ ERKEN / Ä°ZLE"

    return "ğŸ”´ GÄ°RME"


def simple_action(result, momentum=0, previous=None):
    if not result:
        return "ğŸ”´ GÄ°RME"

    if not basic_signal_safe(result) or not crash_guard(result):
        return "ğŸ”´ GÄ°RME"

    p5 = result.get("price5")
    buys = result.get("buys5", 0)
    sells = result.get("sells5", 0)

    if p5 is not None and p5 <= -8:
        return "ğŸ”´ SAT / GÄ°RME"
    if sells > buys * 1.35 and buys + sells >= 8:
        return "ğŸ”´ SAT / GÄ°RME"

    if strong_signal(result, momentum, previous):
        return "ğŸŸ¢ GÄ°R"

    if watch_candidate(result):
        return "ğŸŸ¡ Ä°ZLE / ERKEN ADAY"

    return "ğŸ”´ GÄ°RME"

def manual_decision(result, report):
    """One-shot manual CA decision engine; independent from AUTO 3K-12K band."""
    if not result:
        return "BEKLE", "Piyasa verisi eksik.", "Veri yenilenince tekrar test et."

    sig = result.get("signals") or {}
    liq = num(result.get("liq"))
    top10 = num(result.get("top10"))
    price5 = num(result.get("price5"))
    vol5 = num(result.get("vol5"), 0) or 0
    buys = safe_int(result.get("buys5"))
    sells = safe_int(result.get("sells5"))
    ratio = buys / max(sells, 1)
    score = safe_int(result.get("score"))

    if sig.get("rug") or sig.get("honeypot"):
        return "RUG RISKI / GIRME", "RugCheck rug/honeypot sinyali verdi.", "Yeni giris yapma."
    if result.get("mint") is True or result.get("freeze") is True:
        return "RUG RISKI / GIRME", "Mint veya freeze authority aktif.", "Authority kapanmadan girme."

    if report is None:
        return "BEKLE", "RugCheck verisi alinamadi; guvenlik teyidi eksik.", "RugCheck verisi geldiginde tekrar test et."
    if liq is None:
        return "BEKLE", "Likidite verisi eksik.", "Likidite dogrulaninca tekrar test et."
    if liq < 800:
        return "UZAK DUR", f"Likidite dusuk ({money(liq)}).", "Likidite $800 ustune cikmadan girme."
    if top10 is None:
        return "BEKLE", "Top-10 holder verisi eksik.", "Holder verisi dogrulaninca tekrar test et."
    if top10 >= 75:
        return "UZAK DUR", f"Top-10 holder yogunlugu yuksek ({top10:.1f}%).", "Holder dagilimi iyilesmeden girme."

    if price5 is not None and price5 > 200:
        return "UZAK DUR", f"5dk fiyat +%{price5:.1f}; hareket fazla ilerlemis.", "Yeni taban ve devam hacmi olusmadan girme."
    if price5 is not None and price5 < -15:
        return "UZAK DUR", f"5dk fiyat %{price5:.1f}; aktif dump var.", "Fiyat ve hacim yeniden toparlanmadan girme."
    if sells > buys * 1.15:
        return "UZAK DUR", f"Satis baskisi yuksek ({buys} buy / {sells} sell).", "Buy/sell dengesi pozitife donmeden girme."

    if (
        score >= 60
        and buys >= 8
        and ratio >= 1.10
        and vol5 >= 1000
        and (price5 is None or -8 <= price5 <= 180)
    ):
        return (
            "GIR",
            f"Guvenlik temiz; aktivite guclu: {buys}/{sells}, oran {ratio:.2f}x, hacim {money(vol5)}.",
            "Tek olcum karari; Axiom'da son kontrol ve likidite takibi yap."
        )

    missing = []
    if score < 60:
        missing.append(f"score {score}<60")
    if buys < 8:
        missing.append(f"buy {buys}<8")
    if ratio < 1.10:
        missing.append(f"buy/sell {ratio:.2f}<1.10")
    if vol5 < 1000:
        missing.append(f"hacim {money(vol5)}<$1K")
    if price5 is not None and price5 < -8:
        missing.append(f"5dk fiyat {price5:.1f}%")

    return (
        "BEKLE",
        "Guvenlikte sert engel yok fakat GIR teyidi eksik: " + ", ".join(missing[:4]) + ".",
        "Buy>=8, buy/sell>=1.10, 5dk hacim>=$1K, score>=60 ve fiyat -8%..+180% olunca tekrar test et."
    )


def analyse(ca):
    pair = best_pair(ca)
    if pair is None:
        return None, f"""HUNTERELITE MANUEL ANALIZ

CA: {ca}
------------------------------

KARAR: BEKLE
NEDEN: DEX pair verisi bulunamadi.
GIR TETIGI: Pair/veri olusunca tekrar test et."""

    report = rugcheck(ca)
    result = calculate_score(pair, report)
    result["social"] = social_presence(pair)
    result["narrative"] = narrative_viral(pair)
    base = pair.get("baseToken") or {}
    name = base.get("name") or "Unknown"
    symbol = base.get("symbol") or "N/A"

    decision, reason, trigger = manual_decision(result, report)
    mc = num(result.get("mc"))
    auto_band = "ICINDE" if mc is not None and 3000 <= mc <= 12000 else "DISINDA"

    text = f"""HUNTERELITE MANUEL ANALIZ

{name} ({symbol})
CA: {ca}
------------------------------

AUTO QUALITY BAND ($3K-$12K): {auto_band}

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

5dk: {result["buys5"]} buy / {result["sells5"]} sell
1sa: {result["buys1h"]} buy / {result["sells1h"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}

RugCheck: {"ALINDI" if report else "VERI ALINAMADI"}
Top-1: {percent(result["top1"])}
Top-5: {percent(result["top5"])}
Top-10: {percent(result["top10"])}
Mint authority: {authority_text(result["mint"])}
Freeze authority: {authority_text(result["freeze"])}

Risk Score: {result["score"]}/100
Social Presence: {result.get("social", {}).get("score", 0)}/100 - {result.get("social", {}).get("label", "SOCIAL WEAK")}
X: {"VAR" if result.get("social", {}).get("x") else "YOK"} | Telegram: {"VAR" if result.get("social", {}).get("telegram") else "YOK"} | Reddit: {"VAR" if result.get("social", {}).get("reddit") else "YOK"}

KARAR: {decision}
NEDEN: {reason}
GIR TETIGI: {trigger}"""

    if result.get("risks"):
        text += "\n\nRiskler:\n" + "".join(f"- {r}\n" for r in result["risks"][:6])

    text += "\nManuel karar tek anlik olcumdur; kazanc garantisi degildir."
    return result, text

def basic_signal_safe(result):
    if not result:
        return False
    if result["signals"]["rug"] or result["signals"]["honeypot"]:
        return False
    if result["mint"] is True or result["freeze"] is True:
        return False
    if result["mc"] is None or not (MC_MIN <= result["mc"] <= MC_MAX):
        return False
    if result["liq"] is None or result["liq"] < MIN_LIQUIDITY:
        return False
    if result["top10"] is not None and result["top10"] >= 75:
        return False
    return True

def crash_guard(result):
    ok, _ = crash_guard_detail(result)
    return ok


def trend_confirmed(previous, current):
    """Fresh-token trend confirmation without weakening hard safety gates."""
    if not previous or not current:
        return False

    old_mc = previous.get("mc") or 0
    new_mc = current.get("mc") or 0
    old_buys = previous.get("buys5", 0) or 0
    new_buys = current.get("buys5", 0) or 0
    old_vol = previous.get("vol5") or 0
    new_vol = current.get("vol5") or 0
    p5 = current.get("price5")

    confirmations = 0

    # MC expansion.
    if old_mc > 0 and new_mc >= old_mc * MIN_MC_GROWTH:
        confirmations += 1

    # Buy activity should be stable/rising; fresh 5m windows can reset, so don't demand +15%.
    if old_buys > 0 and new_buys >= old_buys * 0.90:
        confirmations += 1

    # Volume expansion / stability.
    if old_vol > 0 and new_vol >= old_vol * 0.95:
        confirmations += 1

    # Current positive price impulse.
    if p5 is not None and 1.0 <= p5 <= 55:
        confirmations += 1

    # Require two independent confirmations.
    return confirmations >= 2

def watch_candidate(result):
    if not basic_signal_safe(result):
        return False
    if not crash_guard(result):
        return False
    if result["score"] < WATCH_SCORE:
        return False

    buys = result.get("buys5", 0) or 0
    sells = result.get("sells5", 0) or 0
    ratio = buys / max(sells, 1)

    if buys < WATCH_MIN_BUYS_5M:
        return False
    if ratio < WATCH_MIN_BUY_SELL_RATIO:
        return False
    if result["vol5"] is not None and result["vol5"] < WATCH_MIN_VOL_5M:
        return False

    price5 = result.get("price5")
    if price5 is not None and price5 < MAX_WATCH_DROP_5M:
        return False
    if price5 is not None and price5 > AUTO_MAX_PRICE5:
        return False

    return True

def liquidity_drain_detail(previous, current):
    """
    Compare liquidity between consecutive scans.
    Returns: (safe, drop_pct, level)

    HARD: >=35% liquidity loss in one scan interval -> block/cancel.
    WARN: >=20% loss -> reported, but does not by itself block.
    Missing/invalid previous data never gets treated as a rug signal.
    """
    if not LIQ_DRAIN_GUARD_ENABLED or not previous or not current:
        return True, 0.0, "NO_DATA"

    old_liq = num(previous.get("liq"))
    new_liq = num(current.get("liq"))
    if old_liq is None or new_liq is None or old_liq <= 0:
        return True, 0.0, "NO_DATA"

    drop_pct = max(0.0, (old_liq - new_liq) / old_liq * 100.0)

    if drop_pct >= LIQ_DRAIN_HARD_PCT:
        return False, drop_pct, "HARD"
    if drop_pct >= LIQ_DRAIN_WARN_PCT:
        return True, drop_pct, "WARN"
    return True, drop_pct, "OK"


def narrative_viral(pair):
    """
    STORY HUNTER V3
    Detects the SOURCE STORY linked in token metadata.

    Priority:
      direct TikTok video / X status / Instagram reel-post / YouTube video-short /
      Reddit post > generic social profile > generic website.

    This layer never invents views/likes/reposts. If the source platform's
    engagement is not available from a verified API, engagement stays UNKNOWN.
    """
    info = (pair or {}).get("info") or {}
    socials = info.get("socials") or []
    websites = info.get("websites") or []
    base = (pair or {}).get("baseToken") or {}

    name = str(base.get("name") or "").strip()
    symbol = str(base.get("symbol") or "").strip()

    links = []
    def add_link(item, origin):
        if not isinstance(item, dict):
            return
        url = str(item.get("url") or "").strip()
        if not url:
            return
        label = str(item.get("label") or item.get("type") or item.get("platform") or "").strip()
        links.append({"url": url, "label": label, "origin": origin})

    for item in socials:
        add_link(item, "social")
    for item in websites:
        add_link(item, "website")

    sources = []
    profiles = []

    def classify(url):
        low = url.lower()

        # Direct story/content links
        if ("tiktok.com/" in low) and ("/video/" in low or "/t/" in low):
            return "TIKTOK", True
        if ("x.com/" in low or "twitter.com/" in low) and "/status/" in low:
            return "X", True
        if "instagram.com/" in low and ("/reel/" in low or "/p/" in low):
            return "INSTAGRAM", True
        if ("youtube.com/" in low and ("/watch" in low or "/shorts/" in low)) or "youtu.be/" in low:
            return "YOUTUBE", True
        if "reddit.com/" in low and ("/comments/" in low or "/r/" in low):
            return "REDDIT", True

        # Generic profiles / communities
        if "tiktok.com/" in low:
            return "TIKTOK", False
        if "x.com/" in low or "twitter.com/" in low:
            return "X", False
        if "instagram.com/" in low:
            return "INSTAGRAM", False
        if "youtube.com/" in low or "youtu.be/" in low:
            return "YOUTUBE", False
        if "reddit.com/" in low:
            return "REDDIT", False
        if "t.me/" in low or "telegram.me/" in low:
            return "TELEGRAM", False
        return "WEB", False

    for item in links:
        platform, direct = classify(item["url"])
        row = {**item, "platform": platform, "direct": direct}
        if direct:
            sources.append(row)
        else:
            profiles.append(row)

    # Source-story evidence is intentionally much stronger than profile presence.
    score = 0
    reasons = []

    direct_weights = {
        "TIKTOK": 55,
        "X": 50,
        "INSTAGRAM": 45,
        "YOUTUBE": 45,
        "REDDIT": 40,
    }
    profile_weights = {
        "TIKTOK": 12,
        "X": 12,
        "INSTAGRAM": 10,
        "YOUTUBE": 10,
        "REDDIT": 10,
        "TELEGRAM": 8,
        "WEB": 4,
    }

    seen_direct = set()
    for s in sources:
        p = s["platform"]
        if p not in seen_direct:
            score += direct_weights.get(p, 0)
            seen_direct.add(p)
            reasons.append(f"SOURCE_{p}")

    seen_profiles = set()
    for p in profiles:
        platform = p["platform"]
        if platform not in seen_profiles:
            score += profile_weights.get(platform, 0)
            seen_profiles.add(platform)

    # Multiple independent story sources = stronger narrative proof.
    if len(seen_direct) >= 2:
        score += 15
        reasons.append("MULTI_SOURCE")

    # Token has a usable narrative identity. Weak bonus only.
    if len(name) >= 3:
        score += 5
    if symbol and len(symbol) <= 12:
        score += 5

    score = min(score, 100)

    # Prefer the strongest direct source.
    priority = {"TIKTOK": 5, "X": 4, "INSTAGRAM": 3, "YOUTUBE": 2, "REDDIT": 1}
    sources.sort(key=lambda x: priority.get(x["platform"], 0), reverse=True)
    primary = sources[0] if sources else None

    if primary and score >= 60:
        label = "STORY LINKED"
    elif primary:
        label = "STORY SOURCE FOUND"
    elif score >= 25:
        label = "STORY POSSIBLE"
    else:
        label = "NO STORY PROOF"

    return {
        "score": score,
        "label": label,
        "story_linked": bool(primary),
        "source_platform": primary["platform"] if primary else None,
        "source_url": primary["url"] if primary else None,
        "source_x": next((s["url"] for s in sources if s["platform"] == "X"), None),
        "x_status": any(s["platform"] == "X" for s in sources),
        "tiktok_video": any(s["platform"] == "TIKTOK" for s in sources),
        "instagram_post": any(s["platform"] == "INSTAGRAM" for s in sources),
        "youtube_video": any(s["platform"] == "YOUTUBE" for s in sources),
        "reddit_post": any(s["platform"] == "REDDIT" for s in sources),
        "telegram": any(p["platform"] == "TELEGRAM" for p in profiles),
        "reddit": any((s["platform"] == "REDDIT") for s in sources) or any(p["platform"] == "REDDIT" for p in profiles),
        "reasons": reasons,
        "engagement": "UNKNOWN_NO_VERIFIED_API",
    }

def social_presence(pair):
    """
    Free/keyless social layer from DEX pair metadata.
    Measures published social footprint only; it does NOT pretend to measure
    X/Reddit/Telegram interaction counts.
    """
    info = (pair or {}).get("info") or {}
    socials = info.get("socials") or []
    websites = info.get("websites") or []

    kinds = set()
    links = []

    for item in socials:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or item.get("platform") or "").lower()
        url = str(item.get("url") or "")
        blob = (kind + " " + url).lower()
        if "twitter" in blob or "x.com" in blob:
            kinds.add("X")
        if "telegram" in blob or "t.me" in blob:
            kinds.add("TELEGRAM")
        if "reddit" in blob:
            kinds.add("REDDIT")
        if url:
            links.append(url)

    website_count = sum(1 for w in websites if isinstance(w, dict) and w.get("url"))

    score = 0
    if "X" in kinds:
        score += 25
    if "TELEGRAM" in kinds:
        score += 25
    if "REDDIT" in kinds:
        score += 15
    if website_count:
        score += 10
    if len(kinds) >= 2:
        score += 10
    if len(kinds) >= 3:
        score += 10

    score = min(score, 100)
    if score >= 70:
        label = "SOCIAL READY"
    elif score >= 35:
        label = "SOCIAL PRESENT"
    else:
        label = "SOCIAL WEAK"

    return {
        "score": score,
        "label": label,
        "x": "X" in kinds,
        "telegram": "TELEGRAM" in kinds,
        "reddit": "REDDIT" in kinds,
        "websites": website_count,
    }


def fast_gir_decision(result):
    """Single-scan runner lane. Returns None / GIR / GUCLU GIR."""
    if not result:
        return None
    if not basic_signal_safe(result):
        return None
    if not crash_guard(result):
        return None

    sig = result.get("signals") or {}
    if sig.get("rug") or sig.get("honeypot"):
        return None
    if result.get("mint") is True or result.get("freeze") is True:
        return None

    mc = num(result.get("mc"))
    liq = num(result.get("liq"))
    price5 = num(result.get("price5"))
    vol5 = num(result.get("vol5"), 0) or 0
    buys = safe_int(result.get("buys5"))
    sells = safe_int(result.get("sells5"))
    score = safe_int(result.get("score"))

    if mc is None or liq is None or mc <= 0:
        return None

    ratio = buys / max(sells, 1)
    liq_mc = liq / mc

    if price5 is not None and not (FAST_GIR_MIN_PRICE5 <= price5 <= FAST_GIR_MAX_PRICE5):
        return None

    if (
        score >= FAST_GUCLU_MIN_SCORE
        and buys >= FAST_GUCLU_MIN_BUYS_5M
        and ratio >= FAST_GUCLU_MIN_BUY_SELL_RATIO
        and vol5 >= FAST_GUCLU_MIN_VOL_5M
        and liq_mc >= FAST_GUCLU_MIN_LIQ_MC_RATIO
    ):
        return "GUCLU GIR"

    if (
        score >= FAST_GIR_MIN_SCORE
        and buys >= FAST_GIR_MIN_BUYS_5M
        and ratio >= FAST_GIR_MIN_BUY_SELL_RATIO
        and vol5 >= FAST_GIR_MIN_VOL_5M
        and liq_mc >= FAST_GIR_MIN_LIQ_MC_RATIO
    ):
        return "GIR"

    return None


def negative_price_guard(result, previous=None):
    """
    Prevent Story/RURU strength from masking an active selloff.

    Returns:
      (allow_gir, allow_guclu, detail)

    - GUCLU GIR is blocked when 5m price is below -2%.
    - GIR is blocked when 5m price is below -8%.
    - If prior data exists, a recovery can restore GIR only when MC is rising
      and fresh buy flow is strong.
    """
    price5 = num(result.get("price5"))
    if price5 is None:
        return True, True, "PRICE_NA"

    # Normal positive/flat case.
    if price5 >= NEG_PRICE_BLOCK_GUCLU_5M:
        return True, True, f"PRICE5={price5:+.1f}%"

    # Mild negative: normal GIR may remain, GUCLU is blocked.
    if price5 >= NEG_PRICE_BLOCK_GIR_5M:
        return True, False, f"GUCLU_BLOCK_PRICE5={price5:+.1f}%"

    # Strong negative: require visible recovery before even normal GIR.
    if not previous:
        return False, False, f"GIR_BLOCK_PRICE5={price5:+.1f}%"

    mc = num(result.get("mc"))
    old_mc = num(previous.get("mc"))
    buys = safe_int(result.get("buys5"))
    old_buys = safe_int(previous.get("buys5"))
    sells = safe_int(result.get("sells5"))
    old_sells = safe_int(previous.get("sells5"))

    if mc is None or old_mc is None or old_mc <= 0:
        return False, False, f"GIR_BLOCK_PRICE5={price5:+.1f}%"

    mc_pct = ((mc - old_mc) / old_mc) * 100.0
    buy_delta = max(0, buys - old_buys)
    sell_delta = max(0, sells - old_sells)
    flow = buy_delta / max(sell_delta, 1)

    recovered = (
        mc_pct >= NEG_PRICE_RECOVERY_MC_PCT
        and buy_delta >= 2
        and flow >= NEG_PRICE_RECOVERY_FLOW
    )
    if recovered:
        return True, False, f"RECOVERY price5={price5:+.1f}% MC={mc_pct:+.1f}% FLOW={flow:.2f}"

    return False, False, f"GIR_BLOCK price5={price5:+.1f}% MC={mc_pct:+.1f}% FLOW={flow:.2f}"


def continuation_confirm(result, previous, elapsed_seconds=30):
    """
    Confirm that volume is translating into fresh buy flow AND price/MC progress.
    Prevents 'volume rises but token stalls/dumps' FAST signals.
    """
    if not previous:
        return False, "FIRST_TICK"

    mc = num(result.get("mc"))
    old_mc = num(previous.get("mc"))
    vol = num(result.get("vol5"), 0) or 0
    old_vol = num(previous.get("vol5"), 0) or 0
    buys = safe_int(result.get("buys5"))
    old_buys = safe_int(previous.get("buys5"))
    sells = safe_int(result.get("sells5"))
    old_sells = safe_int(previous.get("sells5"))
    price5 = num(result.get("price5"))

    if mc is None or old_mc is None or old_mc <= 0:
        return False, "MC_MISSING"

    mc_pct = ((mc - old_mc) / old_mc) * 100.0
    vol_delta = max(0.0, vol - old_vol)
    buy_delta = max(0, buys - old_buys)
    sell_delta = max(0, sells - old_sells)
    fresh_flow = buy_delta / max(sell_delta, 1)

    # Immediate rejection: market cap is slipping while fresh flow is weak.
    if mc_pct <= CONT_MAX_MC_DROP_PCT:
        return False, f"MC_DROP {mc_pct:+.1f}%"

    # Require actual fresh activity, not an old 5m volume print.
    if vol_delta < CONT_MIN_VOL_DELTA:
        return False, f"VOL_D {vol_delta:.0f}"
    if buy_delta < CONT_MIN_BUY_DELTA:
        return False, f"BUY_D {buy_delta}"
    if fresh_flow < CONT_MIN_FLOW_RATIO:
        return False, f"FLOW {fresh_flow:.2f}"

    # Volume must produce price/MC progress.
    required_mc = CONT_HIGH_PUMP_MIN_MC_PCT if (price5 is not None and price5 >= CONT_HIGH_PUMP_PRICE5) else CONT_MIN_MC_PCT
    if mc_pct < required_mc:
        return False, f"NO_PROGRESS {mc_pct:+.1f}%"

    return True, f"VOL+{vol_delta:.0f} BUY+{buy_delta} SELL+{sell_delta} FLOW={fresh_flow:.2f} MC={mc_pct:+.1f}%"


def volume_breakout_confirm(result, previous):
    """V11.36: confirm early volume expansion + buyer acceleration + MC progress."""
    if not result or not previous:
        return False, False, "VB_FIRST_TICK"
    mc = num(result.get("mc")); old_mc = num(previous.get("mc"))
    vol = num(result.get("vol5"), 0) or 0; old_vol = num(previous.get("vol5"), 0) or 0
    buys = safe_int(result.get("buys5")); old_buys = safe_int(previous.get("buys5"))
    sells = safe_int(result.get("sells5")); old_sells = safe_int(previous.get("sells5"))
    price5 = num(result.get("price5"))
    if mc is None or old_mc is None or mc <= 0 or old_mc <= 0:
        return False, False, "VB_MC_MISSING"
    vol_mc = vol / mc
    vol_delta = max(0.0, vol-old_vol)
    buy_delta = max(0, buys-old_buys); sell_delta=max(0, sells-old_sells)
    flow = buy_delta / max(sell_delta, 1)
    mc_pct = ((mc-old_mc)/old_mc)*100.0
    # Fake-volume/stall rejection: turnover without buyer dominance or MC progress.
    if vol_mc >= VB_MIN_VOL_MC and mc_pct < VB_STALL_MC_PCT and flow < VB_STALL_FLOW:
        return False, False, f"VB_FAKE VOL/MC={vol_mc:.2f} MC={mc_pct:+.1f}% FLOW={flow:.2f}"
    ok = (vol_mc >= VB_MIN_VOL_MC and vol_delta >= VB_MIN_VOL_DELTA and
          buy_delta >= VB_MIN_BUY_DELTA and flow >= VB_MIN_FRESH_FLOW and
          mc_pct >= VB_MIN_MC_PCT and
          (price5 is None or price5 <= CHASE_BLOCK_GIR_5M))
    strong = (ok and vol_mc >= VB_STRONG_VOL_MC and
              (price5 is None or VB_IDEAL_PRICE5_MIN <= price5 <= VB_MAX_GUCLU_PRICE5))
    return ok, strong, f"VB VOL/MC={vol_mc:.2f} VOL+{vol_delta:.0f} BUY+{buy_delta} SELL+{sell_delta} FLOW={flow:.2f} MC={mc_pct:+.1f}%"



def trajectory_breakout_confirm(result, history):
    """V11.37: detect 30-90s acceleration that a static screener cannot see."""
    if not result or not history:
        return False, False, "TRJ_FIRST_TICK"
    snaps = [x for x in history[-TRJ_MAX_HISTORY:] if isinstance(x, dict)]
    if not snaps:
        return False, False, "TRJ_NO_HISTORY"
    base = snaps[0]
    cur_src = result.get("_source"); base_src = base.get("_source")
    cur_ts = num(result.get("_snapshot_ts")); base_ts = num(base.get("_snapshot_ts"))
    if not cur_src or not base_src or cur_src != base_src:
        return False, False, "TRJ_SOURCE_MISMATCH"
    if cur_ts is None or base_ts is None or cur_ts <= base_ts or (cur_ts-base_ts) > (SNAPSHOT_MAX_AGE_SEC * TRJ_MAX_HISTORY):
        return False, False, "TRJ_STALE_SNAPSHOT"
    mc = num(result.get("mc")); old_mc = num(base.get("mc"))
    vol = num(result.get("vol5"), 0) or 0; old_vol = num(base.get("vol5"), 0) or 0
    buys = safe_int(result.get("buys5")); old_buys = safe_int(base.get("buys5"))
    sells = safe_int(result.get("sells5")); old_sells = safe_int(base.get("sells5"))
    price5 = num(result.get("price5"))
    if mc is None or old_mc is None or mc <= 0 or old_mc <= 0:
        return False, False, "TRJ_MC_MISSING"
    mc_pct = ((mc-old_mc)/old_mc)*100.0
    if abs(mc_pct) > MAX_VALID_MC_DELTA_PCT:
        return False, False, f"TRJ_MC_ANOMALY {mc_pct:+.1f}%"
    vol_delta = max(0.0, vol-old_vol)
    buy_delta = max(0, buys-old_buys); sell_delta=max(0, sells-old_sells)
    flow = buy_delta/max(sell_delta,1)
    vol_mc = vol/mc
    # acceleration: newest 30s leg should not be weaker than the older leg on both MC and buys
    last = snaps[-1]
    last_mc = num(last.get("mc")); last_buys=safe_int(last.get("buys5")); last_vol=num(last.get("vol5"),0) or 0
    leg_mc = ((mc-last_mc)/last_mc)*100.0 if last_mc and last_mc>0 else 0.0
    leg_buy = max(0, buys-last_buys); leg_vol=max(0.0,vol-last_vol)
    ticks = min(len(snaps)+1, TRJ_MAX_HISTORY+1)
    # reject turnover without progress, seller-dominated expansion, or chase zone
    if mc_pct < TRJ_STALL_MC_PCT and vol_delta >= TRJ_MIN_VOL_DELTA:
        return False, False, f"TRJ_STALL MC={mc_pct:+.1f}% VOL+{vol_delta:.0f}"
    if flow < TRJ_MIN_FLOW:
        return False, False, f"TRJ_FLOW {flow:.2f}"
    if price5 is not None and price5 > CHASE_BLOCK_GIR_5M:
        return False, False, f"TRJ_CHASE {price5:+.1f}%"
    ok=(ticks>=TRJ_MIN_TICKS and mc_pct>=TRJ_MIN_MC_PCT and vol_delta>=TRJ_MIN_VOL_DELTA and
        buy_delta>=TRJ_MIN_BUY_DELTA and flow>=TRJ_MIN_FLOW and vol_mc>=TRJ_MIN_VOL_MC and
        leg_mc>0 and leg_buy>0 and leg_vol>0)
    strong=(ok and ticks>=TRJ_STRONG_TICKS and mc_pct>=TRJ_STRONG_MC_PCT and
        vol_delta>=TRJ_STRONG_VOL_DELTA and buy_delta>=TRJ_STRONG_BUY_DELTA and
        flow>=TRJ_STRONG_FLOW and (price5 is None or price5<=CHASE_BLOCK_GUCLU_5M))
    return ok,strong,(f"TRJ {ticks}T MC={mc_pct:+.1f}% VOL+{vol_delta:.0f} BUY+{buy_delta} "
        f"SELL+{sell_delta} FLOW={flow:.2f} LAST_MC={leg_mc:+.1f}% LAST_BUY+{leg_buy}")



def global_entry_gate(result, previous):
    """V11.39: safety-first early-runner gate for FAST/RURU/VOLUME/TRAJECTORY.
    Reject chase, unstable liquidity, weak fresh flow, and poor holder structure.
    Returns (allow_gir, allow_guclu, detail).
    """
    if not result or not previous:
        return False, False, "GLOBAL_WAIT_SECOND_TICK"
    cur_src = result.get("_source")
    prev_src = previous.get("_source")
    cur_ts = num(result.get("_snapshot_ts"))
    prev_ts = num(previous.get("_snapshot_ts"))
    if not cur_src or not prev_src or cur_src != prev_src:
        return False, False, f"GLOBAL_SOURCE_MISMATCH {prev_src}->{cur_src}"
    if cur_ts is None or prev_ts is None or cur_ts <= prev_ts or (cur_ts-prev_ts) > SNAPSHOT_MAX_AGE_SEC:
        return False, False, "GLOBAL_STALE_SNAPSHOT"
    price5 = num(result.get("price5"))
    mc = num(result.get("mc")); old_mc = num(previous.get("mc"))
    liq = num(result.get("liq")); old_liq = num(previous.get("liq"))
    top10 = num(result.get("top10"))
    vol = num(result.get("vol5"), 0) or 0; old_vol = num(previous.get("vol5"), 0) or 0
    buys = safe_int(result.get("buys5")); old_buys = safe_int(previous.get("buys5"))
    sells = safe_int(result.get("sells5")); old_sells = safe_int(previous.get("sells5"))
    if mc is None or old_mc is None or mc <= 0 or old_mc <= 0 or liq is None or liq <= 0:
        return False, False, "GLOBAL_DATA_MISSING"
    if price5 is not None and price5 > CHASE_BLOCK_GIR_5M:
        return False, False, f"GLOBAL_CHASE price5={price5:+.1f}%"
    if top10 is not None and top10 > GLOBAL_MAX_TOP10_GIR:
        return False, False, f"GLOBAL_TOP10 {top10:.1f}%"
    liq_mc = liq / mc
    if liq_mc < GLOBAL_MIN_LIQ_MC:
        return False, False, f"GLOBAL_LIQ/MC {liq_mc:.2f}"
    liq_drop = 0.0
    if old_liq is not None and old_liq > 0:
        liq_drop = max(0.0, (old_liq-liq)/old_liq*100.0)
        if liq_drop > GLOBAL_MAX_LIQ_DROP_PCT:
            return False, False, f"GLOBAL_LIQ_UNSTABLE -{liq_drop:.1f}%"
    mc_pct = ((mc-old_mc)/old_mc)*100.0
    if abs(mc_pct) > MAX_VALID_MC_DELTA_PCT:
        return False, False, f"GLOBAL_MC_ANOMALY {mc_pct:+.1f}%"
    if old_liq is None or old_liq <= 0:
        return False, False, "GLOBAL_LIQ_NEEDS_2_TICKS"
    liq_up = ((liq-old_liq)/old_liq)*100.0
    if liq_up > MAX_VALID_LIQ_UP_PCT:
        return False, False, f"GLOBAL_LIQ_ANOMALY +{liq_up:.1f}%"
    vol_delta = max(0.0, vol-old_vol)
    buy_delta = max(0, buys-old_buys); sell_delta=max(0, sells-old_sells)
    flow = buy_delta/max(sell_delta,1)
    if vol_delta < GLOBAL_MIN_VOL_DELTA or buy_delta < GLOBAL_MIN_BUY_DELTA:
        return False, False, f"GLOBAL_NO_ACCEL VOL+{vol_delta:.0f} BUY+{buy_delta}"
    if flow < GLOBAL_MIN_FLOW:
        return False, False, f"GLOBAL_FLOW {flow:.2f}"
    if mc_pct < GLOBAL_MIN_MC_PROGRESS:
        return False, False, f"GLOBAL_NO_MC_PROGRESS {mc_pct:+.1f}%"
    allow_guclu = not (price5 is not None and price5 > CHASE_BLOCK_GUCLU_5M)
    if top10 is not None and top10 > GLOBAL_MAX_TOP10_GUCLU:
        allow_guclu = False
    return True, allow_guclu, (f"GLOBAL_OK P5={price5 if price5 is not None else 0:+.1f}% "
        f"LIQÎ”=-{liq_drop:.1f}% VOL+{vol_delta:.0f} BUY+{buy_delta} SELL+{sell_delta} FLOW={flow:.2f} MC={mc_pct:+.1f}%")

def strong_signal(result, momentum, previous=None):
    if not basic_signal_safe(result):
        return False
    if not crash_guard(result):
        return False
    if previous is None:
        return False

    liq_safe, _, _ = liquidity_drain_detail(previous, result)
    if not liq_safe:
        return False

    if momentum < MIN_MOMENTUM_SIGNAL:
        return False
    if not trend_confirmed(previous, result):
        return False
    if result["score"] + momentum < SIGNAL_SCORE:
        return False
    if result["mc"] > EARLY_MC_MAX:
        return False

    buys, sells = result["buys5"], result["sells5"]
    if buys < SIGNAL_MIN_BUYS_5M:
        return False
    if sells > 0 and buys < sells * SIGNAL_MIN_BUY_SELL_RATIO:
        return False
    if result["vol5"] is not None and result["vol5"] < SIGNAL_MIN_VOL_5M:
        return False
    if result.get("price5") is not None and result["price5"] > AUTO_MAX_PRICE5:
        return False

    return True


def filter_fail_reason(result, previous=None, momentum=0, for_signal=False):
    """Return the main reason a candidate failed. Used only for diagnostics."""
    if not result:
        return "basic_fail"

    sig = result.get("signals") or {}
    if sig.get("rug") or sig.get("honeypot"):
        return "rug_fail"

    if result.get("mint") is True or result.get("freeze") is True:
        return "authority_fail"

    mc = result.get("mc")
    if mc is None or not (MC_MIN <= mc <= MC_MAX):
        return "mc_fail"

    liq = result.get("liq")
    if liq is None or liq < MIN_LIQUIDITY:
        return "liq_fail"

    top10 = result.get("top10")
    if top10 is not None and top10 >= 75:
        return "holder_fail"

    if not crash_guard(result):
        return "crash_fail"

    if not for_signal:
        if result.get("score", 0) < WATCH_SCORE:
            return "score_fail"
        buys = result.get("buys5", 0) or 0
        sells = result.get("sells5", 0) or 0
        if buys < WATCH_MIN_BUYS_5M:
            return "buy_fail"
        if buys / max(sells, 1) < WATCH_MIN_BUY_SELL_RATIO:
            return "buy_fail"
        vol5 = result.get("vol5")
        if vol5 is not None and vol5 < WATCH_MIN_VOL_5M:
            return "volume_fail"
        if result.get("price5") is not None and result.get("price5") > AUTO_MAX_PRICE5:
            return "crash_fail"
        return "basic_fail"

    if previous is None:
        return "trend_fail"
    if momentum < MIN_MOMENTUM_SIGNAL:
        return "momentum_fail"
    if not trend_confirmed(previous, result):
        return "trend_fail"
    if result.get("score", 0) + momentum < SIGNAL_SCORE:
        return "score_fail"
    if result.get("mc") is not None and result["mc"] > EARLY_MC_MAX:
        return "mc_fail"

    buys = result.get("buys5", 0)
    sells = result.get("sells5", 0)
    if buys < SIGNAL_MIN_BUYS_5M:
        return "buy_fail"
    if sells > 0 and buys < sells * SIGNAL_MIN_BUY_SELL_RATIO:
        return "buy_fail"

    vol5 = result.get("vol5")
    if vol5 is not None and vol5 < SIGNAL_MIN_VOL_5M:
        return "volume_fail"

    return "basic_fail"



def crash_guard_detail(result):
    """Age-aware crash diagnostics matching crash_guard()."""
    if not result:
        return False, "unknown"

    p1 = result.get("price1h")
    p6 = result.get("price6h")
    p24 = result.get("price24h")
    age = result.get("age_hours")

    if age is not None and age > MAX_PAIR_AGE_HOURS:
        return False, "age"

    if age is None or age < 1.0:
        if p1 is not None and p1 < MAX_SIGNAL_DROP_1H:
            return False, "h1"
        return True, "ok"

    if age < 6.0:
        if p1 is not None and p1 < MAX_SIGNAL_DROP_1H:
            return False, "h1"
        if p6 is not None and p6 < MAX_CRASH_DROP_6H:
            return False, "h6"
        return True, "ok"

    if p1 is not None and p1 < MAX_SIGNAL_DROP_1H:
        return False, "h1"
    if p6 is not None and p6 < MAX_CRASH_DROP_6H:
        return False, "h6"
    if p24 is not None and p24 < MAX_CRASH_DROP_24H:
        return False, "h24"
    return True, "ok"


def market_viral_score(result):
    """0-12 market-viral acceleration score from live DEX metrics."""
    if not result:
        return 0, "NO DATA"

    buys = float(result.get("buys5") or 0)
    sells = float(result.get("sells5") or 0)
    vol5 = float(result.get("vol5") or 0)
    p5 = float(result.get("price5") or 0)
    total = buys + sells
    buy_ratio = buys / max(total, 1.0)

    score = 0
    if total >= 20: score += 2
    if total >= 50: score += 2
    if buy_ratio >= 0.58: score += 2
    if buy_ratio >= 0.65: score += 1
    if vol5 >= 1500: score += 2
    if vol5 >= 4000: score += 1
    if 3 <= p5 <= 35: score += 2

    score = min(score, VIRAL_SCORE_BONUS_MAX)
    label = "HOT" if score >= 8 else ("RISING" if score >= 5 else "LOW")
    return score, label


def auto_scanner():
    print("EARLY HUNTER SCANNER ACTIVE", flush=True)
    print(
        "WIDE RADAR: BIRDEYE + DEXSCREENER"
        if BIRDEYE_API_KEY
        else "WIDE RADAR: BIRDEYE KEY MISSING, DEX ONLY",
        flush=True,
    )
    time.sleep(10)

    while True:
        try:
            if not signal_chats:
                time.sleep(SCAN_INTERVAL)
                continue

            raw_candidates = discovery_candidates()
            scan_now = time.time()

            # Preserve the intended source allocation: Birdeye first, DEX capped.
            candidates = raw_candidates[:RADAR_TARGET]

            unique_new, repeat = 0, 0
            # Prevent contradictory messages for the same CA in one scan.
            cancelled_this_scan = set()
            with discovery_seen_lock:
                for k in [k for k, ts in discovery_seen.items()
                          if scan_now - ts > DISCOVERY_MEMORY_SECONDS]:
                    discovery_seen.pop(k, None)
                for candidate_ca in candidates:
                    if candidate_ca in discovery_seen:
                        repeat += 1
                    else:
                        unique_new += 1
                    discovery_seen[candidate_ca] = scan_now
            stats = {
                "radar": len(candidates),
                "processed": 0,
                "pair_yok": 0, "stale_pair": 0, "viral_hot": 0, "viral_rising": 0, "h1_fail_values": [], "prepump": 0, "prepump_safe": 0,
                "basic_fail": 0,
                "crash_fail": 0,
                "watch": 0,
                "signal": 0,
                "mc_fail": 0,
                "liq_fail": 0,
                "holder_fail": 0,
                "authority_fail": 0,
                "rug_fail": 0,
                "score_fail": 0,
                "buy_fail": 0,
                "volume_fail": 0,
                "trend_fail": 0,
                "momentum_fail": 0,
                "src_birdeye": 0, "src_gecko": 0, "src_dex": 0,
                "src_birdeye_stale": 0, "src_gecko_stale": 0, "src_dex_stale": 0,
                "src_birdeye_safe": 0, "src_gecko_safe": 0, "src_dex_safe": 0,
    "unique_new": 0, "repeat": 0, "pair_pass": 0, "mc_pass": 0,
    "liq_pass": 0, "liq_missing": 0, "gecko_liq_ok": 0, "gecko_liq_missing": 0, "liq_0_200": 0, "liq_200_500": 0, "liq_500_800": 0, "liq_800_plus": 0, "liq_fallback_ok": 0, "liq_fallback_missing": 0, "holder_pass": 0, "holder_missing": 0, "holder_50_60": 0, "holder_60_70": 0, "holder_70_82": 0, "holder_82_plus": 0, "safety_pass": 0, "rug_ok": 0, "auth_ok": 0, "crash_ok": 0, "age_fail": 0, "h1_fail": 0, "h6_fail": 0, "h24_fail": 0,
    "score_pass": 0, "activity_pass": 0, "trend_pass": 0,
    "momentum_pass": 0,
            }

            stats["unique_new"] = unique_new
            stats["repeat"] = repeat

            for ca in candidates:
                try:
                    source_name = candidate_sources.get(ca)
                    if source_name not in ("BIRDEYE", "GECKO", "DEX"):
                        source_name = "DEX"

                    if source_name == "BIRDEYE":
                        stats["src_birdeye"] += 1
                    elif source_name == "GECKO":
                        stats["src_gecko"] += 1
                    else:
                        stats["src_dex"] += 1

                    pair = best_pair(ca)
                    if pair is None:
                        stats["pair_yok"] += 1
                        continue

                    # V11.13: a token can be "new to the bot" without being newly launched.
                    # Only genuinely fresh pairs enter the early-entry pipeline.
                    pre_metrics = token_metrics(pair)
                    pre_age = pre_metrics.get("age_hours")
                    if pre_age is not None and pre_age > FRESH_PAIR_MAX_HOURS:
                        stats["stale_pair"] += 1
                        if source_name == "BIRDEYE":
                            stats["src_birdeye_stale"] += 1
                        elif source_name == "GECKO":
                            stats["src_gecko_stale"] += 1
                        else:
                            stats["src_dex_stale"] += 1
                        continue

                    report = rugcheck(ca)
                    result = calculate_score(pair, report)
                    # Snapshot provenance is persisted with metrics so trajectory/delta
                    # calculations never mix GECKO/DEX/BIRDEYE values.
                    result["_source"] = source_name
                    result["_snapshot_ts"] = time.time()
                    social = social_presence(pair)
                    result["social"] = social
                    result["narrative"] = narrative_viral(pair)
                    stats["processed"] += 1

                    viral_score, viral_label = market_viral_score(result)
                    result["viral_score"] = viral_score
                    result["viral_label"] = viral_label

                    # PRE-PUMP candidate: rising activity without an already-vertical 5m move.
                    p5 = float(result.get("price5") or 0)
                    buys5 = float(result.get("buys5") or 0)
                    sells5 = float(result.get("sells5") or 0)
                    vol5 = float(result.get("vol5") or 0)
                    if (viral_label in ("RISING", "HOT")
                            and buys5 > sells5
                            and vol5 >= 500
                            and -8 <= p5 <= 25):
                        stats["prepump"] += 1
                        result["prepump"] = True
                    else:
                        result["prepump"] = False
                    if viral_label == "HOT":
                        stats["viral_hot"] += 1
                    elif viral_label == "RISING":
                        stats["viral_rising"] += 1

                    # Viral activity can strengthen a candidate, never bypass hard safety.
                    if viral_score and result.get("score") is not None:
                        result["score"] = min(100, result["score"] + viral_score)
                    stats["pair_pass"] += 1

                    mc_ok = result.get("mc") is not None and MC_MIN <= result["mc"] <= MC_MAX
                    if mc_ok: stats["mc_pass"] += 1

                    liq = result.get("liq")

                    # Liquidity fallback order:
                    # 1) Keyless Gecko cache (no Birdeye quota cost)
                    # 2) Birdeye market-data only if Gecko has no value
                    if mc_ok and liq is None:
                        gecko_liq = gecko_cached_liquidity(ca)
                        if gecko_liq is not None:
                            liq = gecko_liq
                            result["liq"] = gecko_liq
                            result["liq_source"] = "GECKO"
                            stats["gecko_liq_ok"] += 1
                        else:
                            stats["gecko_liq_missing"] += 1

                    if mc_ok and liq is None and BIRDEYE_API_KEY:
                        be_market = birdeye_market_data(ca)
                        be_liq = num((be_market or {}).get("liquidity"))
                        if be_liq is not None:
                            liq = be_liq
                            result["liq"] = be_liq
                            result["liq_source"] = "BIRDEYE"
                            stats["liq_fallback_ok"] += 1
                        else:
                            stats["liq_fallback_missing"] += 1

                    if mc_ok:
                        if liq is None:
                            stats["liq_missing"] += 1
                        elif liq >= 800:
                            stats["liq_800_plus"] += 1
                        elif liq >= 500:
                            stats["liq_500_800"] += 1
                        elif liq >= 200:
                            stats["liq_200_500"] += 1
                        else:
                            stats["liq_0_200"] += 1

                    liq_ok = mc_ok and liq is not None and liq >= MIN_LIQUIDITY
                    if liq_ok: stats["liq_pass"] += 1

                    top10 = result.get("top10")

                    if liq_ok:
                        if top10 is None:
                            stats["holder_missing"] += 1
                        elif top10 >= 82:
                            stats["holder_82_plus"] += 1
                        elif top10 >= 70:
                            stats["holder_70_82"] += 1
                        elif top10 >= 60:
                            stats["holder_60_70"] += 1
                        elif top10 >= 50:
                            stats["holder_50_60"] += 1

                    holder_ok = liq_ok and (top10 is None or top10 < 82)
                    if holder_ok: stats["holder_pass"] += 1

                    sig = result.get("signals") or {}

                    rug_ok = holder_ok and not sig.get("rug") and not sig.get("honeypot")
                    if rug_ok: stats["rug_ok"] += 1

                    auth_ok = (rug_ok
                               and result.get("mint") is not True
                               and result.get("freeze") is not True)
                    if auth_ok: stats["auth_ok"] += 1

                    crash_ok = False
                    crash_reason = "unknown"
                    if auth_ok:
                        crash_ok, crash_reason = crash_guard_detail(result)
                        if crash_ok:
                            stats["crash_ok"] += 1
                        elif crash_reason == "age":
                            stats["age_fail"] += 1
                        elif crash_reason == "h1":
                            stats["h1_fail"] += 1
                            h1v = result.get("price1h")
                            if h1v is not None and len(stats["h1_fail_values"]) < 8:
                                stats["h1_fail_values"].append(round(float(h1v), 1))
                        elif crash_reason == "h6":
                            stats["h6_fail"] += 1
                        elif crash_reason == "h24":
                            stats["h24_fail"] += 1

                    safety_ok = crash_ok
                    if safety_ok:
                        stats["safety_pass"] += 1
                        if source_name == "BIRDEYE":
                            stats["src_birdeye_safe"] += 1
                        elif source_name == "GECKO":
                            stats["src_gecko_safe"] += 1
                        else:
                            stats["src_dex_safe"] += 1
                        if result.get("prepump"):
                            stats["prepump_safe"] += 1

                    score_ok = safety_ok and result.get("score", 0) >= WATCH_SCORE
                    if score_ok: stats["score_pass"] += 1

                    vol5 = result.get("vol5")
                    activity_passed = (score_ok
                                          and result.get("buys5", 0) >= WATCH_MIN_BUYS_5M
                                          and (vol5 is None or vol5 >= WATCH_MIN_VOL_5M))
                    if activity_passed:
                        stats["activity_pass"] += 1

                    now = time.time()
                    with state_lock:
                        previous = token_states.get(ca)

                    old_metrics = previous.get("metrics") if previous else None
                    metric_history = previous.get("history", []) if previous else []
                    liq_drain_safe, liq_drop_pct, liq_drain_level = liquidity_drain_detail(old_metrics, result)
                    result["liq_drop_pct"] = liq_drop_pct
                    result["liq_drain_level"] = liq_drain_level

                    momentum = momentum_score(old_metrics, result)
                    trend_ok = activity_passed and old_metrics is not None and trend_confirmed(old_metrics, result)
                    if trend_ok: stats["trend_pass"] += 1
                    momentum_ok = trend_ok and momentum >= MIN_MOMENTUM_SIGNAL
                    if momentum_ok: stats["momentum_pass"] += 1
                    seen_count = (previous.get("seen_count", 0) + 1) if previous else 1
                    stage = previous.get("stage", "NEW") if previous else "NEW"
                    last_sent = previous.get("last_sent", 0) if previous else 0
                    new_stage, message = stage, None

                    watch_ok = watch_candidate(result)
                    fast_candidate = fast_gir_decision(result)
                    cont_ok, cont_detail = continuation_confirm(result, old_metrics, SCAN_INTERVAL)
                    vb_ok, vb_strong, vb_detail = volume_breakout_confirm(result, old_metrics)
                    trj_ok, trj_strong, trj_detail = trajectory_breakout_confirm(result, metric_history or ([old_metrics] if old_metrics else []))
                    price_allow_gir, price_allow_guclu, price_guard_detail = negative_price_guard(result, old_metrics)

                    fast_decision = fast_candidate if (fast_candidate is not None and cont_ok and price_allow_gir) else None
                    if fast_decision == "GUCLU GIR" and not price_allow_guclu:
                        fast_decision = "GIR" if price_allow_gir else None

                    if fast_candidate is not None:
                        stats["fast_candidate"] = stats.get("fast_candidate", 0) + 1
                        if not cont_ok:
                            samples = stats.setdefault("fast_block_samples", [])
                            if len(samples) < 6:
                                base_dbg = pair.get("baseToken") or {}
                                sym_dbg = base_dbg.get("symbol") or base_dbg.get("name") or ca[:6]
                                samples.append(f"{sym_dbg}:{cont_detail}")

                    # RURU confirmed path remains intact.
                    ruru_signal = (
                        seen_count >= TREND_CONFIRM_SCANS
                        and strong_signal(result, momentum, old_metrics)
                    )

                    # High-pump FAST candidates must never bypass continuation through
                    # the RURU lane on the same scan.
                    high_pump = (num(result.get("price5")) or 0) >= CONT_HIGH_PUMP_PRICE5
                    if high_pump and fast_candidate is not None and not cont_ok:
                        ruru_signal = False

                    # Story/RURU may not override active downside.
                    if not price_allow_gir:
                        ruru_signal = False

                    # Volume breakout is an additional confirmed lane, never a safety bypass.
                    volume_signal = vb_ok and basic_signal_safe(result) and crash_guard(result) and price_allow_gir
                    trajectory_signal = trj_ok and basic_signal_safe(result) and crash_guard(result) and price_allow_gir

                    # V11.40 FINAL DATA GUARD + EARLY RUNNER GLOBAL ENTRY GATE.
                    global_allow_gir, global_allow_guclu, global_gate_detail = global_entry_gate(result, old_metrics)
                    if not global_allow_gir:
                        fast_decision = None
                        ruru_signal = False
                        volume_signal = False
                        trajectory_signal = False
                    signal_ok = global_allow_gir and ((fast_decision is not None) or ruru_signal or volume_signal or trajectory_signal)

                    if ca not in cancelled_this_scan and (not watch_ok):
                        reason = filter_fail_reason(result, old_metrics, momentum, for_signal=False)
                        stats[reason] = stats.get(reason, 0) + 1
                    elif seen_count >= TREND_CONFIRM_SCANS and not signal_ok:
                        reason = filter_fail_reason(result, old_metrics, momentum, for_signal=True)
                        stats[reason] = stats.get(reason, 0) + 1

                    base = pair.get("baseToken") or {}
                    name = base.get("name", "Unknown")
                    symbol = base.get("symbol", "N/A")

                    if (
                        signal_ok
                        and stage != "SIGNAL"
                    ):
                        new_stage = "SIGNAL"
                        stats["signal"] += 1
                        if fast_decision is not None:
                            stats["fast_signal"] = stats.get("fast_signal", 0) + 1
                        final_score = min(100, result["score"] + momentum)
                        age_text = f'{result["age_hours"]:.1f} saat' if result["age_hours"] is not None else "N/A"

                        # DIRECT decision label.
                        buys5 = result.get("buys5", 0) or 0
                        sells5 = result.get("sells5", 0) or 0
                        ratio5 = buys5 / max(sells5, 1)
                        vol5_now = result.get("vol5") or 0
                        price5_now = result.get("price5")
                        liq_now = result.get("liq") or 0
                        mc_now = result.get("mc") or 1

                        guclu_gir = (
                            final_score >= 75
                            and buys5 >= 15
                            and ratio5 >= 1.20
                            and vol5_now >= 2500
                            and liq_now / max(mc_now, 1) >= 0.20
                            and (price5_now is None or -5 <= price5_now <= CHASE_BLOCK_GUCLU_5M)
                            and global_allow_guclu
                        )

                        narrative_score = safe_int(result.get("narrative", {}).get("score"))
                        narrative_linked = bool(result.get("narrative", {}).get("story_linked"))
                        social_score = safe_int(result.get("social", {}).get("score"))
                        top10_now = num(result.get("top10"))

                        # POSITIVE ANTI-CHASE GATE
                        # +100%/5m: never label GUCLU GIR; +150%/5m: do not release a fresh GIR.
                        chase_block_gir = price5_now is not None and price5_now > CHASE_BLOCK_GIR_5M
                        chase_block_guclu = price5_now is not None and price5_now > CHASE_BLOCK_GUCLU_5M
                        if chase_block_gir:
                            guclu_gir = False

                        # SOCIAL-AWARE QUALITY GATE
                        # Social absence is not fatal for very early launches, but GUCLU GIR then
                        # needs exceptional holder distribution + liquidity depth.
                        no_social = social_score <= 0
                        no_social_guclu_ok = (
                            (top10_now is not None and top10_now <= NO_SOCIAL_GUCLU_MAX_TOP10)
                            and (liq_now / max(mc_now, 1) >= NO_SOCIAL_GUCLU_MIN_LIQ_MC)
                        )
                        allow_quality_guclu = global_allow_guclu and (not chase_block_guclu) and ((not no_social) or no_social_guclu_ok)

                        # VOLUME BREAKOUT may strengthen an early entry, but anti-chase/social gates still win.
                        if volume_signal and vb_strong and allow_quality_guclu and price_allow_guclu and not chase_block_guclu:
                            guclu_gir = True
                        # TRAJECTORY strong requires real 60-90s acceleration; social absence still cannot bypass quality gate.
                        if trajectory_signal and trj_strong and allow_quality_guclu and price_allow_guclu and not chase_block_guclu:
                            guclu_gir = True

                        if fast_decision == "GUCLU GIR":
                            karar_label = "GUCLU GIR" if (price_allow_guclu and allow_quality_guclu) else "GIR"
                        elif fast_decision == "GIR":
                            # Narrative can upgrade only after price guard permits GUCLU.
                            karar_label = (
                                "GUCLU GIR"
                                if (price_allow_guclu and allow_quality_guclu and narrative_linked and narrative_score >= 55 and final_score >= 70)
                                else "GIR"
                            )
                        else:
                            karar_label = (
                                "GUCLU GIR"
                                if (
                                    price_allow_guclu
                                    and allow_quality_guclu
                                    and (guclu_gir or (narrative_linked and narrative_score >= 55 and final_score >= 75))
                                )
                                else "GIR"
                            )

                        message = f"""HUNTERELITE {karar_label}

{name} ({symbol})
CA: {ca}
------------------------------

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

5dk: {result["buys5"]} buy / {result["sells5"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}

Top-10: {percent(result["top10"])}
Likidite Guard: {"PASSED" if liq_drain_safe else "BLOCKED"}

Social Presence: {result.get("social", {}).get("score", 0)}/100 - {result.get("social", {}).get("label", "SOCIAL WEAK")}
X: {"VAR" if result.get("social", {}).get("x") else "YOK"} | Telegram: {"VAR" if result.get("social", {}).get("telegram") else "YOK"} | Reddit: {"VAR" if result.get("social", {}).get("reddit") else "YOK"}
Hikaye: {result.get("narrative", {}).get("score", 0)}/100 - {result.get("narrative", {}).get("label", "NO STORY PROOF")}
Hikaye Kaynagi: {result.get("narrative", {}).get("source_platform") or "BULUNAMADI"}
Kaynak Icerik: {"VAR" if result.get("narrative", {}).get("story_linked") else "YOK"}
Etkilesim: DOGRULANMIS API YOKSA BILINMIYOR

Risk Score: {result["score"]}/100
Momentum: +{momentum}
Final Score: {final_score}/100

KARAR: {karar_label}
SINYAL YOLU: {"FAST / CONTINUATION TEYITLI" if fast_decision else ("TRAJECTORY BREAKOUT / 30-90S" if trajectory_signal else ("VOLUME BREAKOUT / TEYITLI" if volume_signal else "RURU / TREND TEYITLI"))}
DEVAMLILIK: {cont_detail if fast_decision else (trj_detail if trajectory_signal else (vb_detail if volume_signal else "RURU TREND"))}
PRICE GUARD: {price_guard_detail}
GLOBAL GATE: {global_gate_detail}

UYARI: Kazanc garanti degildir; Axiom'da son kontrol zorunludur."""

                    elif (
                        watch_ok
                        and stage == "NEW"
                    ):
                        # DIRECT GIR MODE: track silently; never send IZLE.
                        new_stage = "WATCH"
                        message = None

                    # V11.34 LIQ GUARD:
                    # If a token that already signaled loses >=35% of pool liquidity
                    # between scans, cancel immediately instead of waiting for price damage.
                    if (
                        stage == "SIGNAL"
                        and not liq_drain_safe
                        and liq_drain_level == "HARD"
                    ):
                        new_stage = "CANCELLED"
                        message = f"""HUNTERELITE LIQUIDITY DRAIN

{name} ({symbol})
CA: {ca}
------------------------------

Likidite onceki taramaya gore %{liq_drop_pct:.1f} dustu.
Onceki Likidite: {money(old_metrics.get("liq") if old_metrics else None)}
Guncel Likidite: {money(result.get("liq"))}

KARAR: SAT / GIRME
NEDEN: HIZLI LIKIDITE BOSALMASI"""

                    # Missing liquidity is a data-wait state, not a sell/cancel signal.
                    cancel_has_liq = result.get("liq") is not None
                    if cancel_has_liq and (stage == "SIGNAL" and not basic_signal_safe(result)):
                        new_stage = "CANCELLED"
                        message = f"""HUNTERELITE SINYAL IPTAL

CA: {ca}
------------------------------

Risk sartlari kotulesti.

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}
Top-10: {percent(result["top10"])}
Score: {result["score"]}/100

KARAR: SAT / GIRME
Yeni giris icin uygun degil."""

                    if message:
                        for chat_id in list(signal_chats):
                            send(chat_id, message)
                            cancelled_this_scan.add(ca)
                        last_sent = now

                    with state_lock:
                        new_history = list(metric_history or [])
                        if old_metrics:
                            new_history.append(old_metrics)
                        new_history = new_history[-TRJ_MAX_HISTORY:]
                        token_states[ca] = {
                            "metrics": result,
                            "history": new_history,
                            "stage": new_stage,
                            "last_sent": last_sent,
                            "seen": now,
                            "seen_count": seen_count,
                        }

                    save_state()
                    time.sleep(1)

                except Exception as e:
                    print("TOKEN SCAN ERROR:", ca, repr(e), flush=True)

            print(
                "SCAN SUMMARY | "
                f"radar={stats['radar']} "
                f"processed={stats['processed']} "
                f"pair_yok={stats['pair_yok']} "
                f"mc={stats['mc_fail']} "
                f"liq={stats['liq_fail']} "
                f"holder={stats['holder_fail']} "
                f"authority={stats['authority_fail']} "
                f"rug={stats['rug_fail']} "
                f"score={stats['score_fail']} "
                f"buy={stats['buy_fail']} "
                f"volume={stats['volume_fail']} "
                f"trend={stats['trend_fail']} "
                f"momentum={stats['momentum_fail']} "
                f"watch={stats['watch']} "
                f"signal={stats['signal']}",
                flush=True,
            )

            with radar_stats_lock:
                radar_stats.clear()
                radar_stats.update(stats)
                radar_stats["updated"] = time.time()

            # V11.5 heartbeat: proves the scanner is alive without waiting for a trade signal.
            global last_diag_send
            now_diag = time.time()
            if now_diag - last_diag_send >= 300 and stats.get("watch", 0) == 0 and stats.get("signal", 0) == 0:
                diag = (
                    f"RADAR V11.42 | total={stats.get('radar',0)} "
                    f"new={stats.get('unique_new',0)} repeat={stats.get('repeat',0)}\n"
                    f"SOURCES: BIRDEYE={stats.get('src_birdeye',0)} stale={stats.get('src_birdeye_stale',0)} safe={stats.get('src_birdeye_safe',0)} | "
                    f"GECKO={stats.get('src_gecko',0)} stale={stats.get('src_gecko_stale',0)} safe={stats.get('src_gecko_safe',0)} | "
                    f"DEX={stats.get('src_dex',0)} stale={stats.get('src_dex_stale',0)} safe={stats.get('src_dex_safe',0)}\n"
                    f"SOURCE_ACCOUNTED={stats.get('src_birdeye',0)+stats.get('src_gecko',0)+stats.get('src_dex',0)}\n"
                    f"PIPELINE: pair={stats.get('pair_pass',0)} "
                    f"> MC={stats.get('mc_pass',0)} "
                    f"> LIQ={stats.get('liq_pass',0)} "
                    f"> HOLDER={stats.get('holder_pass',0)}\n"
                    f"LIQ FALLBACK: gecko_ok={stats.get('gecko_liq_ok',0)} "
                    f"gecko_missing={stats.get('gecko_liq_missing',0)} | "
                    f"birdeye_ok={stats.get('liq_fallback_ok',0)} "
                    f"birdeye_missing={stats.get('liq_fallback_missing',0)}\n"
                    f"LIQ BREAKDOWN: missing={stats.get('liq_missing',0)} "
                    f"$0-200={stats.get('liq_0_200',0)} "
                    f"$200-500={stats.get('liq_200_500',0)} "
                    f"$500-800={stats.get('liq_500_800',0)} "
                    f"$800+={stats.get('liq_800_plus',0)}\n"
                    f"HOLDER BREAKDOWN: missing={stats.get('holder_missing',0)} "
                    f"50-60={stats.get('holder_50_60',0)} "
                    f"60-70={stats.get('holder_60_70',0)} "
                    f"70-82={stats.get('holder_70_82',0)} "
                    f"82+={stats.get('holder_82_plus',0)}\n"
                    f"SAFETY: RUG_OK={stats.get('rug_ok',0)} "
                    f"> AUTH_OK={stats.get('auth_ok',0)} "
                    f"> CRASH_OK={stats.get('crash_ok',0)} "
                    f"> SAFE={stats.get('safety_pass',0)}\n"
                    f"CRASH BREAKDOWN: AGE_FAIL={stats.get('age_fail',0)} "
                    f"H1_FAIL={stats.get('h1_fail',0)} "
                    f"H6_FAIL={stats.get('h6_fail',0)} "
                    f"H24_FAIL={stats.get('h24_fail',0)}\n"
                    f"AFTER SAFE: SCORE={stats.get('score_pass',0)} "
                    f"> ACTIVITY={stats.get('activity_pass',0)} "
                    f"> TREND={stats.get('trend_pass',0)} "
                    f"> MOMENTUM={stats.get('momentum_pass',0)}\n"
                    f"WATCH={stats.get('watch',0)} SIGNAL={stats.get('signal',0)} FAST={stats.get('fast_signal',0)} "
                    f"pair_missing={stats.get('pair_yok',0)} stale_pair={stats.get('stale_pair',0)}\n"
                    f"MARKET VIRAL: HOT={stats.get('viral_hot',0)} RISING={stats.get('viral_rising',0)} PREPUMP={stats.get('prepump',0)} SAFE_PREPUMP={stats.get('prepump_safe',0)}\n"
                    f"H1 SMART: limit={MAX_SIGNAL_DROP_1H:.0f}% fails={stats.get('h1_fail_values',[])}"
                )
                for chat_id in list(signal_chats):
                    send(chat_id, diag)
                last_diag_send = now_diag

            cutoff = time.time() - 21600
            with state_lock:
                for ca in [k for k, v in token_states.items() if v.get("seen", 0) < cutoff]:
                    token_states.pop(ca, None)

        except Exception as e:
            print("SCANNER ERROR:", repr(e), flush=True)

        time.sleep(SCAN_INTERVAL)

def process_message(message):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = str(message.get("text", "")).strip()

    if chat_id is None or not text:
        return

    command = text.split()[0].lower().split("@")[0]

    if command == "/start":
        signal_chats.add(int(chat_id))
        send(chat_id, f"""âœ… HunterElite {VERSION} ONLINE

ğŸ¯ Early Hunter: AKTÄ°F
ğŸ¯ AUTO QUALITY BAND: $3Kâ€“$12K
ğŸ§ª RugCheck: AKTÄ°F
ğŸ“¡ Eksik veri korumasÄ±: AKTÄ°F
ğŸš¨ Otomatik sinyal: AKTÄ°F

CA gÃ¶ndererek manuel analiz yapabilirsin.

Komutlar:
/ping
/status
/signal_on
/signal_off
/signal_test
/help""")
        return

    if command == "/ping":
        send(chat_id, f"ğŸ“ PONG â€” HunterElite {VERSION} ONLINE")
        return

    if command == "/status":
        active = int(chat_id) in signal_chats
        send(chat_id, f"""âœ… HunterElite {VERSION} ONLINE

ğŸ” Manuel analiz: AKTÄ°F
ğŸš¨ Early Hunter: {"AKTÄ°F" if active else "KAPALI"}
â± Tarama: {SCAN_INTERVAL} sn
RURU Core: V11.41 FINAL RUNNER + DATA GUARD + TRAJECTORY + VOLUME BREAKOUT
Liquidity Drain Guard: AKTIF (hard %{LIQ_DRAIN_HARD_PCT:.0f})
ğŸ¯ Watch Score: {WATCH_SCORE}
ğŸ”¥ Signal Score: {SIGNAL_SCORE}
ğŸ“ˆ Trend teyidi: {TREND_CONFIRM_SCANS} tarama / min momentum {MIN_MOMENTUM_SIGNAL}
ğŸ“¡ Radar: GECKO + DEX + BIRDEYE BONUS
ğŸŸ¢ Birdeye API: {"BAÄLI" if BIRDEYE_API_KEY else "KEY YOK"}
â± Birdeye yenileme: {BIRDEYE_POLL_INTERVAL} sn
ğŸ’§ Min Likidite: {money(MIN_LIQUIDITY)}
ğŸ“Š AUTO Market: $2Kâ€“$20K
âœ… Quality Gate: buy>=5, hacim>=$500, buy/sell>=1.10, late-pump<=+180%\nğŸ“¡ /radar teÅŸhisi: AKTÄ°F\nğŸ§© Single Engine: AKTÄ°F""")
        return

    if command == "/signal_on":
        signal_chats.add(int(chat_id))
        send(chat_id, "ğŸš¨ HunterElite otomatik sinyal AKTÄ°F.\nEarly Hunter taramasÄ± baÅŸladÄ±.")
        return

    if command == "/signal_off":
        signal_chats.discard(int(chat_id))
        send(chat_id, "ğŸ”• Otomatik sinyal KAPALI.")
        return

    if command == "/signal_test":
        signal_chats.add(int(chat_id))
        send(chat_id, f"""âœ… HUNTERELITE TEST SÄ°NYALÄ°

{VERSION}

ğŸ“¡ Telegram kanalÄ±: Ã‡ALIÅIYOR
ğŸš¨ Otomatik sinyal: AKTÄ°F
ğŸ” Manuel analiz: AKTÄ°F
ğŸ”¥ Early Hunter: AKTÄ°F

GerÃ§ek aday taramasÄ± baÅŸladÄ±.""")
        return

    if command == "/radar":
        with radar_stats_lock:
            s = dict(radar_stats)

        updated = s.get("updated", 0)
        age = int(max(0, time.time() - updated)) if updated else None
        age_text = f"{age} sn Ã¶nce" if age is not None else "henÃ¼z ilk tur tamamlanmadÄ±"

        send(chat_id, f"""ğŸ“¡ HUNTERELITE RADAR TEST

SÃ¼rÃ¼m: {VERSION}
Son tarama: {age_text}

ğŸ” Radar adayÄ±: {s.get("radar", 0)}
âœ… Ä°ÅŸlenen: {s.get("processed", 0)}
âŒ Pair yok: {s.get("pair_yok", 0)}

Filtreye takÄ±lanlar:
â€¢ MC: {s.get("mc_fail", 0)}
â€¢ Likidite: {s.get("liq_fail", 0)}
â€¢ Holder: {s.get("holder_fail", 0)}
â€¢ Mint/Freeze: {s.get("authority_fail", 0)}
â€¢ Rug/Honeypot: {s.get("rug_fail", 0)}
â€¢ Score: {s.get("score_fail", 0)}
â€¢ Buy baskÄ±sÄ±: {s.get("buy_fail", 0)}
â€¢ Hacim: {s.get("volume_fail", 0)}
â€¢ Trend: {s.get("trend_fail", 0)}
â€¢ Momentum: {s.get("momentum_fail", 0)}

ğŸ‘€ WATCH: {s.get("watch", 0)}
ğŸš¨ SIGNAL: {s.get("signal", 0)}

Bu ekran teÅŸhis iÃ§indir; sinyal garantisi deÄŸildir.""")
        return

    if command == "/help":
        send(
            chat_id,
            "HunterElite QUALITY 5K-10K + MANUAL\n\n"
            "CA gonder -> MANUEL: GIR / BEKLE / UZAK DUR / RUG RISKI\n\n"
            "/ping\n/status\n/signal_on\n/signal_off\n/signal_test\n/radar\n/start"
        )
        return

    ca = text
    if not SOL_CA.match(ca):
        matches = re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text)
        ca = matches[0] if matches else ""

    if ca and SOL_CA.match(ca):
        send(chat_id, "ğŸ” Token analiz ediliyor...")
        try:
            _, report = analyse(ca)
            send(chat_id, report)
        except Exception as e:
            print("ANALYSIS ERROR:", repr(e), flush=True)
            send(chat_id, "âŒ Analiz sÄ±rasÄ±nda veri hatasÄ± oluÅŸtu.")
        return

    send(chat_id, "Solana kontrat adresini gÃ¶nder veya /help yaz.")

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"HunterElite {VERSION} ONLINE".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

def health_server():
    port = int(os.getenv("PORT", "8080"))
    try:
        HTTPServer(("0.0.0.0", port), Health).serve_forever()
    except Exception as e:
        print("HEALTH ERROR:", repr(e), flush=True)


def startup_notify():
    if not signal_chats:
        print("WARNING: SIGNAL_CHAT_ID missing; automatic Telegram alerts have no destination.", flush=True)
        return

    mode = "COMMANDS ON" if POLLING_ENABLED else "AUTO SIGNAL MODE"
    for chat_id in list(signal_chats):
        send(chat_id, f"""HunterElite {VERSION} ONLINE

Early Hunter: ACTIVE
Scan: {SCAN_INTERVAL} sec
Radar: GECKO + DEX + BIRDEYE BONUS
Birdeye: {"KEY PRESENT / BONUS" if BIRDEYE_API_KEY else "KEY MISSING"}\nGecko: KEYLESS PRIMARY FALLBACK\nRadar Mix: Birdeye max 20 + Gecko fills + DEX max 20 / total max 80
Watch Score: {WATCH_SCORE}
Signal Score: {SIGNAL_SCORE}
Min Liquidity: {money(MIN_LIQUIDITY)}
Mode: {mode}

Auto Quality: MC $2K-$20K, Liquidity $600+, Top10 safety active\nHard rug/honeypot and authority checks remain active.\n\nFINAL ENGINE V11.42: WIDE RUNNER + DATA GUARD + EARLY RUNNER GATE + SHADOW WATCH + LIQUIDITY STABILITY + TRAJECTORY 30-90S + ACCELERATION + RURU TREND + STORY HUNTER + VOLUME BREAKOUT + VOLUME CONTINUATION + ANTI-CHASE + NEGATIVE PRICE GUARD + RUG/HOLDER/LIQ SAFETY + MANUAL + AXIOM: ACTIVE.\nAutomatic signal engine is running.""")


def startup():
    print(f"HUNTERELITE {VERSION} ONLINE", flush=True)
    print(f"TELEGRAM POLLING: {'ON' if POLLING_ENABLED else 'OFF - AUTO SIGNAL MODE'}", flush=True)
    print("EARLY HUNTER ACTIVE", flush=True)
    print(f"SCAN INTERVAL: {SCAN_INTERVAL}s", flush=True)
    print(f"EARLY ENTRY FILTERS: MC>={MC_MIN}, LIQ>={MIN_LIQUIDITY}, TOP10<=82% target", flush=True)
    print(
        f"TUNING: watch={WATCH_SCORE}, signal={SIGNAL_SCORE}, "
        f"momentum>={MIN_MOMENTUM_SIGNAL}, MC growth>={int((MIN_MC_GROWTH-1)*100)}%, "
        f"pair age<={MAX_PAIR_AGE_HOURS:.0f}h",
        flush=True,
    )
    print(
        f"BIRDEYE API KEY: {'READY' if BIRDEYE_API_KEY else 'MISSING'}",
        flush=True,
    )
    try:
        telegram("deleteWebhook", {"drop_pending_updates": "false"})
    except Exception as e:
        print("WEBHOOK CLEAN WARNING:", repr(e), flush=True)

def polling():
    offset = None
    while True:
        try:
            data = {"timeout": 25, "allowed_updates": json.dumps(["message"])}
            if offset is not None:
                data["offset"] = offset

            response = telegram("getUpdates", data, timeout=35)

            for update in response.get("result", []):
                update_id = update.get("update_id")
                if update_id is not None:
                    offset = update_id + 1

                message = update.get("message")
                if message:
                    process_message(message)

        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            print("TELEGRAM HTTP ERROR:", e.code, body, flush=True)
            time.sleep(3)

        except Exception as e:
            print("POLL ERROR:", repr(e), flush=True)
            time.sleep(3)

if __name__ == "__main__":
    load_state()
    threading.Thread(target=health_server, daemon=True).start()
    startup()
    threading.Thread(target=auto_scanner, daemon=True).start()
    time.sleep(2)
    startup_notify()

    if POLLING_ENABLED:
        polling()
    else:
        # Keep the process alive while the scanner thread runs.
        # This mode eliminates Telegram getUpdates 409 conflicts.
        while True:
            time.sleep(3600)
