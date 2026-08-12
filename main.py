import os
import re
import json
import html
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import urllib.parse
import urllib.error
try:
    import websocket
except Exception:
    websocket = None
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VERSION = "V11.36.3 LIQ HARD GATE FIXED"
TOKEN = os.getenv("TOKEN", "").strip()
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "").strip()
SOLANA_WS_URL = os.getenv("SOLANA_WS_URL", "").strip()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "").strip()
if not SOLANA_RPC_URL and SOLANA_WS_URL:
    SOLANA_RPC_URL = SOLANA_WS_URL.replace("wss://", "https://", 1).replace("ws://", "http://", 1)

# V11.5: single-engine mode.
# Telegram getUpdates polling is OFF by default so another stale/duplicate
# poller cannot interfere with automatic signal delivery. Automatic alerts
# still work via sendMessage using SIGNAL_CHAT_ID.
POLLING_ENABLED = os.getenv("POLLING_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

MC_MIN = 1000
MC_MAX = 15000
EARLY_MC_MAX = 10000
MIN_LIQUIDITY = 800

# V11.2 â€” daha erken aday yakala, sert rug korumalarÄ±nÄ± koru
WATCH_SCORE = 47
SIGNAL_SCORE = 60
SCAN_INTERVAL = 12

BIRDEYE_POLL_INTERVAL = int(os.getenv("BIRDEYE_POLL_INTERVAL", "180"))
BIRDEYE_ERROR_COOLDOWN = int(os.getenv("BIRDEYE_ERROR_COOLDOWN", "900"))
BIRDEYE_QUOTA_COOLDOWN = int(os.getenv("BIRDEYE_QUOTA_COOLDOWN", "21600"))
BIRDEYE_MARKET_FALLBACK = os.getenv("BIRDEYE_MARKET_FALLBACK", "0").strip().lower() in ("1", "true", "yes", "on")
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

WATCH_MIN_BUYS_5M = 2
WATCH_MIN_VOL_5M = 60
SIGNAL_MIN_BUYS_5M = 4
SIGNAL_MIN_BUY_SELL_RATIO = 1.10
SIGNAL_MIN_VOL_5M = 180
MIN_VOL_GROWTH = 1.00

# Liquidity Drain Guard
# V11.35 keeps V11.34 signal thresholds unchanged.
# This layer only blocks/cancels when liquidity collapses between scans.
LIQ_DRAIN_GUARD_ENABLED = True
LIQ_DRAIN_WARN_PCT = 20.0
LIQ_DRAIN_HARD_PCT = 25.0
LIQ_CONFIRM_MIN_SCANS = 2
LIQ_CONFIRM_MAX_DROP_PCT = 12.0

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
birdeye_cooldown_until = 0.0

radar_stats_lock = threading.Lock()
last_diag_send = 0.0
discovery_seen = {}
candidate_sources = {}
discovery_seen_lock = threading.Lock()
DISCOVERY_MEMORY_SECONDS = 21600
RADAR_RAW_LIMIT = 240
RADAR_TARGET = 80
BIRDEYE_TARGET = 20
GECKO_TARGET = 20
RAYDIUM_TARGET = 20
METEORA_TARGET = 20
DEX_TARGET = 20
MAX_REPEAT_PER_SCAN = 20
FRESH_PAIR_MAX_HOURS = 6.0

# Multi-source discovery caches. These only supply candidate CAs;
# all candidates still pass the unchanged RURU CORE safety/entry pipeline.
SOURCE_POLL_INTERVAL = 12
SOURCE_CACHE_LIMIT = 120
source_feed_lock = threading.Lock()
source_feed_cache = {"GECKO": [], "RAYDIUM": [], "METEORA": []}
source_feed_last_fetch = {"GECKO": 0.0, "RAYDIUM": 0.0, "METEORA": 0.0}
source_feed_last_error = {"GECKO": "", "RAYDIUM": "", "METEORA": ""}

# V11.36 LIVE WS: on-chain discovery wakes the scanner immediately.
# One Helius WebSocket connection carries multiple logsSubscribe subscriptions.
WS_PROGRAMS = {
    "PUMP": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    "PUMP_AMM": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
    "RAYDIUM_LAUNCHLAB": "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
    "METEORA_DBC": "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",
}
WS_CREATE_HINTS = ("create", "initialize", "init_pool", "initialize_pool", "create_pool", "migration")
ws_candidate_lock = threading.Lock()
ws_candidates = []
ws_candidate_seen = {}
ws_wake_event = threading.Event()
ws_status_lock = threading.Lock()
ws_status = {"connected": False, "events": 0, "tx_fetch": 0, "candidates": 0, "last_error": "", "last_event": 0.0}
ws_listener_started = threading.Event()

VIRAL_RADAR_ENABLED = True
VIRAL_SCORE_BONUS_MAX = 12

radar_stats = {
    "updated": 0,
    "radar": 0,
    "processed": 0,
    "pair_yok": 0, "stale_pair": 0, "viral_hot": 0, "viral_rising": 0, "h1_fail_values": [], "prepump": 0, "prepump_safe": 0, "src_birdeye": 0, "src_gecko": 0, "src_raydium": 0, "src_meteora": 0, "src_dex": 0, "src_birdeye_stale": 0, "src_gecko_stale": 0, "src_raydium_stale": 0, "src_meteora_stale": 0, "src_dex_stale": 0, "src_birdeye_safe": 0, "src_gecko_safe": 0, "src_raydium_safe": 0, "src_meteora_safe": 0, "src_dex_safe": 0,
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
    "liq_pass": 0, "liq_missing": 0, "liq_0_200": 0, "liq_200_500": 0, "liq_500_800": 0, "liq_800_plus": 0, "liq_fallback_ok": 0, "liq_fallback_missing": 0, "holder_pass": 0, "holder_missing": 0, "holder_50_60": 0, "holder_60_70": 0, "holder_70_82": 0, "holder_82_plus": 0, "safety_pass": 0, "rug_ok": 0, "auth_ok": 0, "crash_ok": 0, "age_fail": 0, "h1_fail": 0, "h6_fail": 0, "h24_fail": 0,
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

        # Keep the contract on its own CA line and make only that CA clickable.
        # The RURU scan/filter/signal logic is untouched.
        ca_match = re.search(r"(?m)^CA:\s*([1-9A-HJ-NP-Za-km-z]{32,44})\s*$", text)
        ca = ca_match.group(1) if ca_match else None

        safe_text = html.escape(text, quote=False)
        if ca:
            plain_ca = f"CA: {html.escape(ca, quote=False)}"
            linked_ca = (
                f'CA: <a href="{axiom_token_url(ca)}">'
                f'{html.escape(ca, quote=False)}</a>'
            )
            safe_text = safe_text.replace(plain_ca, linked_ca, 1)

        telegram("sendMessage", {
            "chat_id": str(chat_id),
            "text": safe_text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": "true"
        })
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
    # DexScreener token endpoint is eventually consistent for brand-new launches.
    # Try the normal lookup first, then the search endpoint so candidates discovered
    # by Gecko/Raydium/Meteora are not discarded before scoring.
    pairs = dex_pairs(ca)
    if not pairs:
        try:
            data = get_json("https://api.dexscreener.com/latest/dex/search?" + urllib.parse.urlencode({"q": ca}), timeout=10)
            rows = (data or {}).get("pairs") or [] if isinstance(data, dict) else []
            pairs = [p for p in rows if str(p.get("chainId", "")).lower() == "solana" and ca in (str((p.get("baseToken") or {}).get("address","")), str((p.get("quoteToken") or {}).get("address","")))]
        except Exception as e:
            print("DEX SEARCH FALLBACK ERROR:", ca, repr(e), flush=True)
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
    global birdeye_cache, birdeye_last_fetch, birdeye_last_error, birdeye_cooldown_until

    if not BIRDEYE_API_KEY:
        return []

    now = time.time()
    with birdeye_lock:
        # IMPORTANT: respect poll/cooldown even when cache is empty.
        # FIX2 retried every scan after an empty/error response and could burn CU / hammer quota.
        if not force and now < birdeye_cooldown_until:
            return list(birdeye_cache)
        if not force and birdeye_last_fetch > 0 and now - birdeye_last_fetch < BIRDEYE_POLL_INTERVAL:
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
        low = err.lower()
        quota_hit = ("compute unit" in low and ("limit" in low or "exceed" in low)) or "usage limit" in low
        cooldown = BIRDEYE_QUOTA_COOLDOWN if quota_hit else BIRDEYE_ERROR_COOLDOWN
        with birdeye_lock:
            birdeye_last_error = err
            birdeye_last_fetch = now
            birdeye_cooldown_until = now + cooldown
        print(f"BIRDEYE ERROR: {err} | cooldown={cooldown}s", flush=True)

    except Exception as e:
        err = repr(e)
        with birdeye_lock:
            birdeye_last_error = err
            birdeye_last_fetch = now
            birdeye_cooldown_until = now + BIRDEYE_ERROR_COOLDOWN
        print(f"BIRDEYE ERROR: {err} | cooldown={BIRDEYE_ERROR_COOLDOWN}s", flush=True)

    with birdeye_lock:
        return list(birdeye_cache)


SOL_WRAPPED = "So11111111111111111111111111111111111111112"
SOL_STABLE_MINTS = {
    SOL_WRAPPED,
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYDibp2dZrjG1pFjTz7E3Jr",      # USDT
}

def _valid_candidate_mint(value):
    ca = str(value or "").strip()
    return ca if SOL_CA.fullmatch(ca) and ca not in SOL_STABLE_MINTS else None

def _cache_source_result(source, fresh, error=""):
    now = time.time()
    fresh = [ca for ca in fresh if _valid_candidate_mint(ca)]
    with source_feed_lock:
        merged, seen = [], set()
        for ca in fresh + list(source_feed_cache.get(source, [])):
            if ca not in seen:
                seen.add(ca)
                merged.append(ca)
        source_feed_cache[source] = merged[:SOURCE_CACHE_LIMIT]
        source_feed_last_fetch[source] = now
        source_feed_last_error[source] = error
        return list(source_feed_cache[source])

def _cached_source(source):
    with source_feed_lock:
        return list(source_feed_cache.get(source, []))

def _gecko_id_mint(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    direct = _valid_candidate_mint(raw)
    if direct:
        return direct
    # GeckoTerminal token ids are commonly network_mint (e.g. solana_<mint>).
    if "_" in raw:
        return _valid_candidate_mint(raw.rsplit("_", 1)[-1])
    return None


def gecko_new_candidates(force=False):
    """Keyless GeckoTerminal Solana new-pools feed (robust token-id parsing)."""
    now = time.time()
    with source_feed_lock:
        last = source_feed_last_fetch.get("GECKO", 0.0)
        cached = list(source_feed_cache.get("GECKO", []))
    if not force and cached and now - last < SOURCE_POLL_INTERVAL:
        return cached

    found, seen, errors = [], set(), []
    for page in (1, 2, 3):
        url = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools?" + urllib.parse.urlencode({
            "include": "base_token,quote_token",
            "page": page,
        })
        try:
            payload = get_json(
                url,
                timeout=15,
                headers={"Accept": "application/json;version=20230203"},
            )
            included_map = {}
            for obj in (payload.get("included") or []) if isinstance(payload, dict) else []:
                if not isinstance(obj, dict):
                    continue
                oid = str(obj.get("id") or "")
                attrs = obj.get("attributes") or {}
                addr = _valid_candidate_mint(attrs.get("address")) or _gecko_id_mint(oid)
                if oid and addr:
                    included_map[oid] = addr

            for pool in (payload.get("data") or []) if isinstance(payload, dict) else []:
                if not isinstance(pool, dict):
                    continue
                rel = pool.get("relationships") or {}
                for rel_name in ("base_token", "quote_token"):
                    rel_data = ((rel.get(rel_name) or {}).get("data") or {})
                    rid = str(rel_data.get("id") or "")
                    ca = included_map.get(rid) or _gecko_id_mint(rid)
                    if ca and ca not in seen:
                        seen.add(ca)
                        found.append(ca)
        except Exception as e:
            errors.append(f"p{page}:{type(e).__name__}:{str(e)[:80]}")

    return _cache_source_result("GECKO", found, ";".join(errors[:3]))

def _raydium_row_mints(row):
    out = []
    if not isinstance(row, dict):
        return out
    for key in ("mintA", "mintB", "mint1", "mint2"):
        obj = row.get(key)
        if isinstance(obj, dict):
            ca = _valid_candidate_mint(obj.get("address") or obj.get("mint") or obj.get("id"))
        else:
            ca = _valid_candidate_mint(obj)
        if ca:
            out.append(ca)
    for key in ("mintAAddress", "mintBAddress", "baseMint", "quoteMint", "mint1Address", "mint2Address"):
        ca = _valid_candidate_mint(row.get(key))
        if ca:
            out.append(ca)
    return out

def raydium_new_candidates(force=False):
    """Raydium official API v3 pool inventory + LaunchLab recent discovery."""
    now = time.time()
    with source_feed_lock:
        last = source_feed_last_fetch.get("RAYDIUM", 0.0)
        cached = list(source_feed_cache.get("RAYDIUM", []))
    if not force and cached and now - last < SOURCE_POLL_INTERVAL:
        return cached

    found, seen, errors = [], set(), []

    # Official API v3 pool inventory. We use a modest page size and let
    # DexScreener's pairCreatedAt enforce the existing <=6h freshness gate later.
    urls = [
        "https://api-v3.raydium.io/pools/info/list?" + urllib.parse.urlencode({
            "poolType": "all",
            "poolSortField": "default",
            "sortType": "desc",
            "pageSize": 100,
            "page": 1,
        }),
        # Official LaunchLab discovery endpoint for recently featured launches.
        "https://launch-mint-v1.raydium.io/get/random/index-recent-mint",
    ]

    for url in urls:
        try:
            payload = get_json(url, timeout=15)
            rows = []
            if isinstance(payload, dict):
                data = payload.get("data")
                if isinstance(data, dict):
                    rows.extend(data.get("data") or data.get("rows") or data.get("list") or [])
                    # Some LaunchLab responses return a single mint object.
                    if not rows:
                        rows.append(data)
                elif isinstance(data, list):
                    rows.extend(data)
                for k in ("rows", "list", "items"):
                    if isinstance(payload.get(k), list):
                        rows.extend(payload[k])
            elif isinstance(payload, list):
                rows = payload

            for row in rows:
                if not isinstance(row, dict):
                    continue
                candidates = _raydium_row_mints(row)
                for key in ("mint", "mintAddress", "address", "tokenAddress"):
                    ca = _valid_candidate_mint(row.get(key))
                    if ca:
                        candidates.append(ca)
                token_obj = row.get("token") or row.get("mintInfo") or {}
                if isinstance(token_obj, dict):
                    ca = _valid_candidate_mint(token_obj.get("address") or token_obj.get("mint"))
                    if ca:
                        candidates.append(ca)
                for ca in candidates:
                    if ca not in seen:
                        seen.add(ca)
                        found.append(ca)
        except Exception as e:
            errors.append(type(e).__name__)

    return _cache_source_result("RAYDIUM", found, ";".join(errors[:4]))

def _meteora_row_mints(row):
    if not isinstance(row, dict):
        return []
    values = []
    for key in (
        "token_a_mint", "token_b_mint", "tokenAMint", "tokenBMint",
        "mint_a", "mint_b", "mint_x", "mint_y", "mintX", "mintY",
        "base_mint", "quote_mint",
    ):
        ca = _valid_candidate_mint(row.get(key))
        if ca:
            values.append(ca)
    for key in ("token_a", "token_b", "tokenA", "tokenB", "token_x", "token_y", "tokenX", "tokenY", "mint_x", "mint_y", "mintX", "mintY"):
        obj = row.get(key)
        if isinstance(obj, dict):
            ca = _valid_candidate_mint(obj.get("mint") or obj.get("address") or obj.get("id"))
            if ca:
                values.append(ca)
    return values

def meteora_new_candidates(force=False):
    """Meteora public DAMM + DLMM REST pool feeds."""
    now = time.time()
    with source_feed_lock:
        last = source_feed_last_fetch.get("METEORA", 0.0)
        cached = list(source_feed_cache.get("METEORA", []))
    if not force and cached and now - last < SOURCE_POLL_INTERVAL:
        return cached

    found, seen, errors = [], set(), []
    urls = [
        # DAMM v2 supports sorting by pool creation time; prioritize newest pools.
        "https://damm-v2.datapi.meteora.ag/pools?" + urllib.parse.urlencode({
            "page": 1,
            "page_size": 200,
            "sort_by": "pool_created_at:desc",
        }),
        "https://damm-api.meteora.ag/pools",
        "https://dlmm.datapi.meteora.ag/pools",
    ]
    for url in urls:
        try:
            payload = get_json(url, timeout=15)
            rows = []
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                for key in ("data", "pools", "items", "rows"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        rows.extend(value)
                    elif isinstance(value, dict):
                        for sub in ("data", "pools", "items", "rows"):
                            if isinstance(value.get(sub), list):
                                rows.extend(value[sub])
            # Prefer newest indexed pools when the feed exposes a creation timestamp.
            def _row_created(v):
                if not isinstance(v, dict):
                    return 0.0
                for k in ("pool_created_at", "created_at", "createdAt", "timestamp"):
                    x = num(v.get(k), 0) or 0
                    if x > 10_000_000_000:
                        x /= 1000.0
                    if x > 0:
                        return float(x)
                return 0.0
            if any(_row_created(r) > 0 for r in rows):
                rows.sort(key=_row_created, reverse=True)
            for row in rows[:250]:
                for ca in _meteora_row_mints(row):
                    if ca not in seen:
                        seen.add(ca)
                        found.append(ca)
        except Exception as e:
            errors.append(type(e).__name__)

    return _cache_source_result("METEORA", found, ";".join(errors[:4]))

def _ws_rpc(method, params, timeout=12):
    if not SOLANA_RPC_URL:
        return None
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        SOLANA_RPC_URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "HunterElite-V11.36"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode("utf-8", errors="replace"))
    return payload.get("result") if isinstance(payload, dict) else None


def _extract_mints_from_transaction(tx):
    found = []
    seen = set()
    if not isinstance(tx, dict):
        return found
    meta = tx.get("meta") or {}
    for key in ("preTokenBalances", "postTokenBalances"):
        for row in meta.get(key) or []:
            ca = _valid_candidate_mint((row or {}).get("mint"))
            if ca and ca not in seen:
                seen.add(ca); found.append(ca)

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).lower() == "mint":
                    ca = _valid_candidate_mint(v)
                    if ca and ca not in seen:
                        seen.add(ca); found.append(ca)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)
    walk((tx.get("transaction") or {}).get("message") or {})
    walk(meta.get("innerInstructions") or [])
    return found


def _ws_enqueue(ca, source):
    ca = _valid_candidate_mint(ca)
    if not ca:
        return
    now = time.time()
    with ws_candidate_lock:
        for k in [k for k, ts in ws_candidate_seen.items() if now - ts > 900]:
            ws_candidate_seen.pop(k, None)
        if ca in ws_candidate_seen:
            return
        ws_candidate_seen[ca] = now
        ws_candidates.append((ca, source, now))
        if len(ws_candidates) > 200:
            del ws_candidates[:-200]
    with ws_status_lock:
        ws_status["candidates"] += 1
    ws_wake_event.set()


def ws_drain_candidates(limit=40):
    with ws_candidate_lock:
        rows = ws_candidates[:limit]
        del ws_candidates[:len(rows)]
    return rows


def solana_ws_listener():
    """Maintain exactly one Helius WSS connection with safe reconnect pacing."""
    if ws_listener_started.is_set():
        print("SOLANA WS: DUPLICATE LISTENER BLOCKED", flush=True)
        return
    ws_listener_started.set()

    if not SOLANA_WS_URL:
        print("SOLANA WS: DISABLED - SOLANA_WS_URL missing", flush=True)
        return
    if websocket is None:
        print("SOLANA WS: DISABLED - websocket-client missing", flush=True)
        return

    # Normal transient errors use exponential backoff. Helius 429 / connection
    # limit errors get a long cooldown so stale sockets have time to expire.
    backoff = 5
    ws = None
    while True:
        retry_wait = backoff
        try:
            ws = websocket.create_connection(
                SOLANA_WS_URL,
                timeout=30,
                enable_multithread=True,
            )
            ws.settimeout(70)
            with ws_status_lock:
                ws_status.update({"connected": True, "last_error": ""})
            print("SOLANA WS: CONNECTED", flush=True)

            request_id = 100
            request_program = {}
            subscription_program = {}
            for name, program in WS_PROGRAMS.items():
                request_id += 1
                request_program[request_id] = name
                ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "logsSubscribe",
                    "params": [{"mentions": [program]}, {"commitment": "processed"}],
                }))

            # Once a connection survives and subscriptions are sent, reset the
            # transient retry delay. Health ping once/minute matches Helius guidance.
            backoff = 5
            last_ping = time.time()

            while True:
                if time.time() - last_ping >= 60:
                    ws.ping()
                    last_ping = time.time()
                try:
                    raw = ws.recv()
                except Exception as e:
                    if "timed out" in str(e).lower():
                        continue
                    raise
                if not raw:
                    continue

                msg = json.loads(raw)
                if isinstance(msg.get("result"), int) and msg.get("id") in request_program:
                    subscription_program[msg["result"]] = request_program[msg["id"]]
                    continue

                # JSON-RPC subscription errors are handled as connection errors so
                # we do not spin and continuously reopen sockets.
                if msg.get("error"):
                    raise RuntimeError(f"WSS RPC error: {msg.get('error')}")

                params = msg.get("params") or {}
                result = params.get("result") or {}
                value = result.get("value") or result
                signature = value.get("signature") if isinstance(value, dict) else None
                logs = value.get("logs") or [] if isinstance(value, dict) else []
                if not signature:
                    continue

                sub_id = params.get("subscription")
                source = subscription_program.get(sub_id, "WS")
                text = " ".join(str(x).lower() for x in logs)
                with ws_status_lock:
                    ws_status["events"] += 1
                    ws_status["last_event"] = time.time()

                if not any(hint in text for hint in WS_CREATE_HINTS):
                    continue

                tx = _ws_rpc("getTransaction", [signature, {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed",
                    "maxSupportedTransactionVersion": 0,
                }])
                with ws_status_lock:
                    ws_status["tx_fetch"] += 1

                mapped_source = "DEX"
                if source.startswith("RAYDIUM"):
                    mapped_source = "RAYDIUM"
                elif source.startswith("METEORA"):
                    mapped_source = "METEORA"
                for ca in _extract_mints_from_transaction(tx):
                    _ws_enqueue(ca, mapped_source)

        except Exception as e:
            err = repr(e)
            err_lower = err.lower()
            limited = (
                "429" in err_lower
                or "too many requests" in err_lower
                or "connection limit exceeded" in err_lower
            )
            if limited:
                # Long cooldown is deliberate: hammering reconnect on a connection
                # limit extends the problem and can consume provider capacity.
                retry_wait = 300
                backoff = 5
                label = "RATE_LIMIT_COOLDOWN"
            else:
                retry_wait = backoff
                backoff = min(backoff * 2, 120)
                label = "RETRY"

            with ws_status_lock:
                ws_status["connected"] = False
                ws_status["last_error"] = err[:180]
            print(f"SOLANA WS ERROR [{label}]:", err, f"retry={retry_wait}s", flush=True)

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
                ws = None

        time.sleep(retry_wait)


def discovery_candidates():
    dex_endpoints = [
        "https://api.dexscreener.com/token-profiles/latest/v1",
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/token-boosts/top/v1",
        "https://api.dexscreener.com/community-takeovers/latest/v1",
    ]

    candidate_sources.clear()
    used = set()
    buckets = {"BIRDEYE": [], "GECKO": [], "RAYDIUM": [], "METEORA": [], "DEX": []}
    live_ws_rows = ws_drain_candidates(40)

    def add_many(source, values):
        for raw in values:
            ca = _valid_candidate_mint(raw)
            if not ca or ca in used:
                continue
            used.add(ca)
            buckets[source].append(ca)
            candidate_sources[ca] = source

    # LIVE WS candidates get first priority, then REST feeds refill the radar.
    live_ws_selected = []
    for ca, source, _ts in live_ws_rows:
        if ca in used:
            continue
        used.add(ca)
        live_ws_selected.append(ca)
        candidate_sources[ca] = source if source in buckets else "DEX"

    # V11.36 FAST DISCOVERY: keyless/public feeds are fetched in parallel.
    # This reduces discovery latency without weakening the unchanged RURU safety gates.
    def fetch_dex_candidates():
        found = []
        for url in dex_endpoints:
            try:
                data = get_json(url)
                if not isinstance(data, list):
                    continue
                for item in data:
                    if str(item.get("chainId", "")).lower() != "solana":
                        continue
                    ca = _valid_candidate_mint(item.get("tokenAddress"))
                    if ca:
                        found.append(ca)
            except Exception as e:
                print("DISCOVERY DEX ERROR:", repr(e), flush=True)
        return found

    jobs = {
        "BIRDEYE": birdeye_new_candidates,
        "GECKO": gecko_new_candidates,
        "RAYDIUM": raydium_new_candidates,
        "METEORA": meteora_new_candidates,
        "DEX": fetch_dex_candidates,
    }
    fetched = {}
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="hunter-feed") as pool:
        future_to_source = {pool.submit(fn): source for source, fn in jobs.items()}
        for future in as_completed(future_to_source):
            source = future_to_source[future]
            try:
                fetched[source] = future.result() or []
            except Exception as e:
                print(f"DISCOVERY {source} ERROR:", repr(e), flush=True)
                fetched[source] = []

    # Preserve deterministic source priority after parallel fetch completes.
    for source in ("BIRDEYE", "GECKO", "RAYDIUM", "METEORA", "DEX"):
        add_many(source, fetched.get(source, []))

    # Balanced source mix. Unused slots are filled by any source with extra candidates.
    limits = {
        "BIRDEYE": BIRDEYE_TARGET,
        "GECKO": GECKO_TARGET,
        "RAYDIUM": RAYDIUM_TARGET,
        "METEORA": METEORA_TARGET,
        "DEX": DEX_TARGET,
    }
    selected = list(live_ws_selected)
    for source in ("BIRDEYE", "GECKO", "RAYDIUM", "METEORA", "DEX"):
        selected.extend(buckets[source][:limits[source]])

    # Refill only from real multi-source feeds. DEX remains capped at DEX_TARGET
    # so it cannot silently take over the radar when upstream discovery is empty.
    if len(selected) < RADAR_TARGET:
        already = set(selected)
        for source in ("GECKO", "RAYDIUM", "METEORA", "BIRDEYE"):
            for ca in buckets[source][limits[source]:]:
                if ca in already:
                    continue
                selected.append(ca)
                already.add(ca)
                if len(selected) >= RADAR_TARGET:
                    return selected[:RADAR_TARGET]

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
    """Read RugCheck holder concentration without inflating pct values."""
    if not isinstance(holder, dict):
        return None

    # RugCheck topHolders[].pct is already percentage points.
    value = num(holder.get("pct"))
    if value is not None:
        return value if 0 <= value <= 100 else None

    for key in ("percentage", "percent"):
        value = num(holder.get(key))
        if value is not None:
            return value if 0 <= value <= 100 else None

    # Only this explicitly fractional field is converted from 0..1 to percent.
    value = num(holder.get("ownershipPercentage"))
    if value is not None:
        if 0 <= value <= 1:
            value *= 100
        return value if 0 <= value <= 100 else None

    return None


def holders(report):
    """
    Calculate user-wallet Top-1/5/10 from RugCheck.
    Excludes RugCheck-identified AMM/pool/bonding-curve inventory.
    Existing RURU safety thresholds are unchanged.
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

    # Impossible totals mean parse uncertainty; never convert that into a false pass.
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
        return "ğŸš€ 5X-10X POTANSIYEL ADAYI"

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

def analyse(ca):
    pair = best_pair(ca)
    if pair is None:
        return None, f"ğŸ¦… HUNTERELITE {VERSION}\n\nCA: {ca}\n\nâŒ DEX pair verisi bulunamadÄ±.\n\nğŸ”´ GÄ°RME / VERÄ° BEKLE"

    report = rugcheck(ca)
    result = calculate_score(pair, report)
    base = pair.get("baseToken") or {}
    name = base.get("name") or "Unknown"
    symbol = base.get("symbol") or "N/A"

    text = f"""ğŸ¦… HUNTERELITE {VERSION}

{name} ({symbol})
CA: {ca}

ğŸ¯ Market GiriÅŸ BÃ¶lgesi: $2Kâ€“$10K

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

âš¡ 5dk: {result["buys5"]} buy / {result["sells5"]} sell
ğŸ“Š 1s: {result["buys1h"]} buy / {result["sells1h"]} sell

ğŸ’µ 5dk hacim: {money(result["vol5"])}
ğŸ“ˆ 5dk fiyat: {percent(result["price5"])}

ğŸ§ª RugCheck Derin Kontrol

RugCheck: {"âœ… ALINDI" if report else "âš ï¸ VERÄ° ALINAMADI"}

Top-1 holder: {percent(result["top1"])}
Top-5 holder: {percent(result["top5"])}
Top-10 holder: {percent(result["top10"])}

Mint authority: {authority_text(result["mint"])}
Freeze authority: {authority_text(result["freeze"])}

ğŸ›¡ Hunter Elite Score: {result["score"]}/100
ğŸ’ Potansiyel: IZLE

ğŸ¯ Karar: {result["decision"]}"""

    if result["risks"]:
        text += "\n\nâš ï¸ Riskler:\n" + "".join(f"â€¢ {r}\n" for r in result["risks"][:7])

    text += "\nEksik veri gÃ¼venli kabul edilmez.\nBu sistem risk filtresidir, yatÄ±rÄ±m garantisi deÄŸildir."
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
    if result["buys5"] < WATCH_MIN_BUYS_5M:
        return False
    if result["vol5"] is not None and result["vol5"] < WATCH_MIN_VOL_5M:
        return False
    if result["price5"] is not None and result["price5"] < MAX_WATCH_DROP_5M:
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
        if result.get("buys5", 0) < WATCH_MIN_BUYS_5M:
            return "buy_fail"
        vol5 = result.get("vol5")
        if vol5 is not None and vol5 < WATCH_MIN_VOL_5M:
            return "volume_fail"
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
        "WIDE RADAR: BIRDEYE + GECKO + RAYDIUM + METEORA + DEX"
        if BIRDEYE_API_KEY
        else "WIDE RADAR: GECKO + RAYDIUM + METEORA + DEX (BIRDEYE KEY MISSING)",
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
                "src_birdeye": 0, "src_gecko": 0, "src_raydium": 0, "src_meteora": 0, "src_dex": 0,
                "src_birdeye_stale": 0, "src_gecko_stale": 0, "src_raydium_stale": 0, "src_meteora_stale": 0, "src_dex_stale": 0,
                "src_birdeye_safe": 0, "src_gecko_safe": 0, "src_raydium_safe": 0, "src_meteora_safe": 0, "src_dex_safe": 0,
    "unique_new": 0, "repeat": 0, "pair_pass": 0, "mc_pass": 0,
    "liq_pass": 0, "liq_missing": 0, "liq_0_200": 0, "liq_200_500": 0, "liq_500_800": 0, "liq_800_plus": 0, "liq_fallback_ok": 0, "liq_fallback_missing": 0, "holder_pass": 0, "holder_missing": 0, "holder_50_60": 0, "holder_60_70": 0, "holder_70_82": 0, "holder_82_plus": 0, "safety_pass": 0, "rug_ok": 0, "auth_ok": 0, "crash_ok": 0, "age_fail": 0, "h1_fail": 0, "h6_fail": 0, "h24_fail": 0,
    "score_pass": 0, "activity_pass": 0, "trend_pass": 0,
    "momentum_pass": 0,
            }

            stats["unique_new"] = unique_new
            stats["repeat"] = repeat

            for ca in candidates:
                try:
                    source_name = candidate_sources.get(ca)
                    if source_name not in ("BIRDEYE", "GECKO", "RAYDIUM", "METEORA", "DEX"):
                        source_name = "DEX"

                    source_key = source_name.lower()
                    stats[f"src_{source_key}"] += 1

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
                        stats[f"src_{source_key}_stale"] += 1
                        continue

                    report = rugcheck(ca)
                    result = calculate_score(pair, report)
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

                    # Viral score is diagnostic only. Do NOT alter the original RURU risk score.
                    # It may be displayed/used separately, but never changes safety/entry thresholds.
                    stats["pair_pass"] += 1

                    mc_ok = result.get("mc") is not None and MC_MIN <= result["mc"] <= MC_MAX
                    if mc_ok: stats["mc_pass"] += 1

                    liq = result.get("liq")

                    # DEX liquidity is sometimes unavailable for very fresh Birdeye listings.
                    # Only in that case, ask Birdeye Market Data for the token's liquidity.
                    if mc_ok and liq is None and BIRDEYE_API_KEY and BIRDEYE_MARKET_FALLBACK:
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

                    holder_ok = liq_ok and (top10 is None or top10 < 75)
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
                        stats[f"src_{source_key}_safe"] += 1
                        if result.get("prepump"):
                            stats["prepump_safe"] += 1

                    score_ok = safety_ok and result.get("score", 0) >= WATCH_SCORE
                    if score_ok: stats["score_pass"] += 1

                    vol5 = result.get("vol5")
                    activity_ok = (score_ok
                                   and result.get("buys5", 0) >= WATCH_MIN_BUYS_5M
                                   and (vol5 is None or vol5 >= WATCH_MIN_VOL_5M))
                    if activity_ok: stats["activity_pass"] += 1

                    now = time.time()
                    with state_lock:
                        previous = token_states.get(ca)

                    old_metrics = previous.get("metrics") if previous else None
                    liq_drain_safe, liq_drop_pct, liq_drain_level = liquidity_drain_detail(old_metrics, result)
                    result["liq_drop_pct"] = liq_drop_pct
                    result["liq_drain_level"] = liq_drain_level

                    momentum = momentum_score(old_metrics, result)
                    trend_ok = activity_ok and old_metrics is not None and trend_confirmed(old_metrics, result)
                    if trend_ok: stats["trend_pass"] += 1
                    momentum_ok = trend_ok and momentum >= MIN_MOMENTUM_SIGNAL
                    if momentum_ok: stats["momentum_pass"] += 1
                    seen_count = (previous.get("seen_count", 0) + 1) if previous else 1
                    stage = previous.get("stage", "NEW") if previous else "NEW"
                    last_sent = previous.get("last_sent", 0) if previous else 0
                    new_stage, message = stage, None

                    # V11.36.3 LIQ HARD GATE: never publish WATCH/SIGNAL from a first liquidity snapshot.
                    # Require a second consecutive scan and block if liquidity falls >12% between them.
                    liq_confirmed = False
                    if old_metrics is not None:
                        old_liq_confirm = num(old_metrics.get("liq"))
                        new_liq_confirm = num(result.get("liq"))
                        if old_liq_confirm is not None and new_liq_confirm is not None and old_liq_confirm >= MIN_LIQUIDITY and new_liq_confirm >= MIN_LIQUIDITY:
                            confirm_drop = max(0.0, (old_liq_confirm - new_liq_confirm) / old_liq_confirm * 100.0) if old_liq_confirm > 0 else 100.0
                            liq_confirmed = confirm_drop <= LIQ_CONFIRM_MAX_DROP_PCT
                    result["liq_confirmed"] = liq_confirmed

                    watch_ok = watch_candidate(result) and seen_count >= LIQ_CONFIRM_MIN_SCANS and liq_confirmed
                    signal_ok = (
                        seen_count >= max(TREND_CONFIRM_SCANS, LIQ_CONFIRM_MIN_SCANS)
                        and liq_confirmed
                        and strong_signal(result, momentum, old_metrics)
                    )

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
                        final_score = min(100, result["score"] + momentum)
                        age_text = f'{result["age_hours"]:.1f} saat' if result["age_hours"] is not None else "N/A"

                        message = f"""HUNTERELITE EARLY SIGNAL

{name} ({symbol})
CA: {ca}

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

5dk: {result["buys5"]} buy / {result["sells5"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}

Top-10: {percent(result["top10"])}
Likidite Guard: {"PASSED" if liq_drain_safe else "BLOCKED"}
Likidite Degisim: -{liq_drop_pct:.1f}%

Risk Score: {result["score"]}/100
Momentum: +{momentum}
1sa fiyat: {percent(result["price1h"])}
6sa fiyat: {percent(result["price6h"])}
Pair yasi: {age_text}
Final Score: {final_score}/100

KARAR: GIR
POTANSIYEL: {potential_label(result, momentum)}

UYARI: Potansiyel etiketi garanti degildir.
Axiom'da son kontrolunu yap."""

                    elif (
                        watch_ok
                        and stage == "NEW"
                        and now - last_sent > WATCH_REPEAT_COOLDOWN
                    ):
                        new_stage = "WATCH"
                        stats["watch"] += 1

                        message = f"""HUNTERELITE IZLE

{name} ({symbol})
CA: {ca}

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

5dk: {result["buys5"]} buy / {result["sells5"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}

Top-10: {percent(result["top10"])}
Score: {result["score"]}/100

Potansiyel: IZLE
KARAR: IZLE / ERKEN ADAY

Momentum teyidi bekleniyor."""

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
                        token_states[ca] = {
                            "metrics": result,
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
                    f"RADAR V11.36 | total={stats.get('radar',0)} "
                    f"new={stats.get('unique_new',0)} repeat={stats.get('repeat',0)}\n"
                    f"SOURCES: BIRDEYE={stats.get('src_birdeye',0)} stale={stats.get('src_birdeye_stale',0)} safe={stats.get('src_birdeye_safe',0)} | "
                    f"GECKO={stats.get('src_gecko',0)} stale={stats.get('src_gecko_stale',0)} safe={stats.get('src_gecko_safe',0)} | "
                    f"RAYDIUM={stats.get('src_raydium',0)} stale={stats.get('src_raydium_stale',0)} safe={stats.get('src_raydium_safe',0)} | "
                    f"METEORA={stats.get('src_meteora',0)} stale={stats.get('src_meteora_stale',0)} safe={stats.get('src_meteora_safe',0)} | "
                    f"DEX={stats.get('src_dex',0)} stale={stats.get('src_dex_stale',0)} safe={stats.get('src_dex_safe',0)}\n"
                    f"SOURCE_ACCOUNTED={stats.get('src_birdeye',0)+stats.get('src_gecko',0)+stats.get('src_raydium',0)+stats.get('src_meteora',0)+stats.get('src_dex',0)}\n"
                    f"FEEDS: GECKO cache={len(_cached_source('GECKO'))} err={source_feed_last_error.get('GECKO') or '-'} | "
                    f"RAYDIUM cache={len(_cached_source('RAYDIUM'))} err={source_feed_last_error.get('RAYDIUM') or '-'} | "
                    f"METEORA cache={len(_cached_source('METEORA'))} err={source_feed_last_error.get('METEORA') or '-'}\n"
                    f"PIPELINE: pair={stats.get('pair_pass',0)} "
                    f"> MC={stats.get('mc_pass',0)} "
                    f"> LIQ={stats.get('liq_pass',0)} "
                    f"> HOLDER={stats.get('holder_pass',0)}\n"
                    f"LIQ FALLBACK: birdeye_ok={stats.get('liq_fallback_ok',0)} "
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
                    f"WATCH={stats.get('watch',0)} SIGNAL={stats.get('signal',0)} "
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

        ws_wake_event.wait(timeout=SCAN_INTERVAL)
        ws_wake_event.clear()

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
ğŸ¯ Market bÃ¶lgesi: $2Kâ€“$10K
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
RURU Core: V11.34 ORIJINAL SINYAL ESikleri
Liquidity Drain Guard: AKTIF (hard %{LIQ_DRAIN_HARD_PCT:.0f})
ğŸ¯ Watch Score: {WATCH_SCORE}
ğŸ”¥ Signal Score: {SIGNAL_SCORE}
ğŸ“ˆ Trend teyidi: {TREND_CONFIRM_SCANS} tarama / min momentum {MIN_MOMENTUM_SIGNAL}
ğŸ“¡ Radar: {"SOLANA WS + BIRDEYE + GECKO + RAYDIUM + METEORA + DEX" if BIRDEYE_API_KEY else "SOLANA WS + GECKO + RAYDIUM + METEORA + DEX"}
ğŸŸ¢ Birdeye API: {"BAÄLI" if BIRDEYE_API_KEY else "KEY YOK"}
â± Birdeye yenileme: {BIRDEYE_POLL_INTERVAL} sn
ğŸ’§ Min Likidite: {money(MIN_LIQUIDITY)}
ğŸ“Š Market: $2Kâ€“$10K Ã¶ncelikli
ğŸ’ 100X potansiyel filtresi: AKTÄ°F\nğŸ“¡ /radar teÅŸhisi: AKTÄ°F\nğŸ§© Single Engine: AKTÄ°F""")
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
            "HunterElite V11.3 EARLY 100X RADAR\n\n"
            "CA gÃ¶nder â†’ manuel analiz\n\n"
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
Radar: {"SOLANA WS + BIRDEYE + GECKO + RAYDIUM + METEORA + DEX" if BIRDEYE_API_KEY else "SOLANA WS + GECKO + RAYDIUM + METEORA + DEX"}
Birdeye: {"CONNECTED" if BIRDEYE_API_KEY else "KEY MISSING"}\nBirdeye Fresh: official 20/request + rolling unique cache / CU-safe 180 sec\nRadar Mix: FIX2 multi-source; Gecko + Raydium + Meteora primary, DEX max 20 fallback
Watch Score: {WATCH_SCORE}
Signal Score: {SIGNAL_SCORE}
Min Liquidity: {money(MIN_LIQUIDITY)}
Mode: {mode}
Solana WS: {"CONNECTED/STARTING" if SOLANA_WS_URL else "MISSING"}

Early Entry: MC $1K+, Liquidity $800+, Top10 <75%\nHard rug/honeypot and authority checks remain active.\n\nSTATE DECISION LOCK + CENTRAL OUTPUT + LIQ FALLBACK: ACTIVE.\nAutomatic signal engine is running.""")


def startup():
    print(f"HUNTERELITE {VERSION} ONLINE", flush=True)
    print(f"TELEGRAM POLLING: {'ON' if POLLING_ENABLED else 'OFF - AUTO SIGNAL MODE'}", flush=True)
    print("EARLY HUNTER ACTIVE", flush=True)
    print(f"SCAN INTERVAL: {SCAN_INTERVAL}s", flush=True)
    print(f"EARLY ENTRY FILTERS: MC>={MC_MIN}, LIQ>={MIN_LIQUIDITY}, TOP10<75%", flush=True)
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
    print(f"SOLANA WS URL: {'READY' if SOLANA_WS_URL else 'MISSING'}", flush=True)
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
    threading.Thread(target=solana_ws_listener, daemon=True).start()
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
