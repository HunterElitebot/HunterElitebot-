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

VERSION = "V11.59 LIQ DRAIN VISIBILITY"
TOKEN = os.getenv("TOKEN", "").strip()
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "").strip()
SOLANA_WS_URL = os.getenv("SOLANA_WS_URL", "").strip()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "").strip()
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "").strip()
REDDIT_ACCESS_TOKEN = os.getenv("REDDIT_ACCESS_TOKEN", "").strip()
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "").strip()
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "HunterEliteBot/11.36.7").strip()
SOCIAL_MAJOR_FOLLOWERS = int(os.getenv("SOCIAL_MAJOR_FOLLOWERS", "50000"))
SOCIAL_VIRAL_ENGAGEMENT = int(os.getenv("SOCIAL_VIRAL_ENGAGEMENT", "500"))
# V11.42: X (Twitter) social bonus applied only in the final SIGNAL check —
# never a hard gate. A brand-new token often has zero social footprint yet,
# so absence never blocks; presence only adds confidence on top of a
# candidate that already passed every safety gate on its own.
SOCIAL_BONUS_MAX = int(os.getenv("SOCIAL_BONUS_MAX", "10"))
if not SOLANA_RPC_URL and SOLANA_WS_URL:
    SOLANA_RPC_URL = SOLANA_WS_URL.replace("wss://", "https://", 1).replace("ws://", "http://", 1)

# V11.37 RELAXED DISCOVERY: wider discovery, hard rug protections preserved.
# V11.5: single-engine mode.
# Telegram getUpdates polling is OFF by default so another stale/duplicate
# poller cannot interfere with automatic signal delivery. Automatic alerts
# still work via sendMessage using SIGNAL_CHAT_ID.
POLLING_ENABLED = os.getenv("POLLING_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

MC_MIN = int(os.getenv("MC_MIN", "3000"))
MC_MAX = 20000
EARLY_MC_MAX = 15000
# V11.39: raised from 400. At $400-800 liquidity a single mid-size sell can
# move price 70-90% on its own with zero rug involved — that alone explained
# a large share of the H1 crash-after-signal cases. Override via env if needed.
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", "2500"))
# V11.39: top10 holder concentration ceiling, tightened from 90 -> 60.
# Healthy fresh pairs are usually well under 50%; 90% let almost anything through.
HOLDER_TOP10_MAX = float(os.getenv("HOLDER_TOP10_MAX", "60"))
# V11.41: single-wallet concentration ceiling. A wallet holding a large slice
# alone is a classic quiet rug setup even when the top-10 aggregate looks fine.
TOP1_MAX_PCT = float(os.getenv("TOP1_MAX_PCT", "20"))
# V11.41: minimum % of the LP that must be locked/burned. Below this, the
# liquidity can be pulled by whoever controls it at any moment.
LP_LOCK_MIN_PCT = float(os.getenv("LP_LOCK_MIN_PCT", "50"))
# V11.41: minimum pair age before a token is eligible for SIGNAL. The first
# few minutes are exactly where bundled-wallet pump-and-dump squads operate;
# requiring the pair to survive past that window filters most of them out.
MIN_PAIR_AGE_MINUTES = float(os.getenv("MIN_PAIR_AGE_MINUTES", "5"))
# V11.39: if True, missing holder data is still allowed to pass (old behavior).
# Default False: no data now means "unknown", not "safe".
ALLOW_MISSING_HOLDER = os.getenv("ALLOW_MISSING_HOLDER", "0").strip().lower() in ("1", "true", "yes", "on")

# V11.2 — daha erken aday yakala, sert rug korumalarını koru
WATCH_SCORE = 38
SIGNAL_SCORE = 50
SCAN_INTERVAL = 12

BIRDEYE_POLL_INTERVAL = int(os.getenv("BIRDEYE_POLL_INTERVAL", "180"))
BIRDEYE_ERROR_COOLDOWN = int(os.getenv("BIRDEYE_ERROR_COOLDOWN", "900"))
BIRDEYE_QUOTA_COOLDOWN = int(os.getenv("BIRDEYE_QUOTA_COOLDOWN", "21600"))
BIRDEYE_MARKET_FALLBACK = os.getenv("BIRDEYE_MARKET_FALLBACK", "0").strip().lower() in ("1", "true", "yes", "on")
BIRDEYE_LIMIT = 20
BIRDEYE_PAGES = 1
BIRDEYE_NEW_LISTING = "https://public-api.birdeye.so/defi/v2/tokens/new_listing"

WATCH_REPEAT_COOLDOWN = 21600
MAX_WATCH_DROP_5M = -15.0
MAX_SIGNAL_DROP_1H = -35.0
MAX_CRASH_DROP_6H = -35.0
MAX_CRASH_DROP_24H = -55.0
# V11.47 LATE-ENTRY / TOP-CHASE GUARD: the crash floor above only blocks a
# token that already fell hard. Nothing was blocking the opposite failure —
# a token that already spiked 100%+ before the signal fires, meaning we're
# catching it at/near the top of the move instead of before it. Signaling
# there buys the reversal, not the rise.
LATE_ENTRY_MAX_PRICE1H_PCT = float(os.getenv("LATE_ENTRY_MAX_PRICE1H_PCT", "60"))
# If the 5-minute price is already turning negative while the 1h change is
# still strongly positive, that's the move visibly rolling over right now —
# block regardless of how "early" the 1h number still looks.
LATE_ENTRY_REVERSAL_PRICE1H_PCT = float(os.getenv("LATE_ENTRY_REVERSAL_PRICE1H_PCT", "30"))
LATE_ENTRY_REVERSAL_PRICE5_PCT = float(os.getenv("LATE_ENTRY_REVERSAL_PRICE5_PCT", "-1"))
# V11.49: if the current market cap has fallen this much from the highest MC
# we've ever recorded for this CA (even from before it was old enough to be
# signal-eligible), treat it as already-crashed — regardless of what the
# 1h/5m delta metrics say, since those can look calm after a full round-trip.
PEAK_DRAWDOWN_MAX_PCT = float(os.getenv("PEAK_DRAWDOWN_MAX_PCT", "40"))
# V11.51: catches a token whose price6h shows it already spiked hard at some
# point in its (short) life, but price1h shows most of that gain is already
# gone — i.e. it pumped and mostly retraced before we ever saw it, so our own
# peak-drawdown tracking (which only starts once WE observe the token) can't
# catch it. This compares the two DexScreener-reported windows directly.
STALE_SPIKE_MIN_P6_PCT = float(os.getenv("STALE_SPIKE_MIN_P6_PCT", "60"))
STALE_SPIKE_RETRACE_RATIO = float(os.getenv("STALE_SPIKE_RETRACE_RATIO", "0.5"))

MIN_MOMENTUM_SIGNAL = 2
MIN_MC_GROWTH = 1.000
MAX_PAIR_AGE_HOURS = 2.0
TREND_CONFIRM_SCANS = 1
# V11.39: how many of the 4 trend_confirmed signals (MC growth, buy activity,
# volume, price impulse) must agree. Was hardcoded to 1 (too loose).
TREND_MIN_CONFIRMATIONS = int(os.getenv("TREND_MIN_CONFIRMATIONS", "1"))
# V11.50: the 5-minute price-impulse confirmation inside trend_confirmed()
# previously counted anything from +1% as "rising" — that's noise, not a
# visible move. Raised the floor so this confirmation only fires on a real
# upward impulse.
TREND_MIN_PRICE5_PCT = float(os.getenv("TREND_MIN_PRICE5_PCT", "3.0"))
TREND_MAX_PRICE5_PCT = float(os.getenv("TREND_MAX_PRICE5_PCT", "55.0"))

WATCH_MIN_BUYS_5M = 1
WATCH_MIN_VOL_5M = 25
SIGNAL_MIN_BUYS_5M = 2
SIGNAL_MIN_BUY_SELL_RATIO = 0.95
SIGNAL_MIN_VOL_5M = 40
MIN_VOL_GROWTH = 1.00

# Liquidity Drain Guard
# V11.35 keeps V11.34 signal thresholds unchanged.
# This layer only blocks/cancels when liquidity collapses between scans.
LIQ_DRAIN_GUARD_ENABLED = True
LIQ_DRAIN_WARN_PCT = 20.0
LIQ_DRAIN_HARD_PCT = 25.0
LIQ_CONFIRM_MIN_SCANS = 1
# V11.52: raised from 18%. Micro-cap ($3-15K) liquidity naturally swings this
# much between 12s scans just from normal trading — 18% was flagging routine
# noise as "unconfirmed" and blocking genuinely early tokens. LIQ_DRAIN_HARD_PCT
# above (25%, a sudden-pull rug indicator) is untouched — this only affects
# whether we treat liquidity as "stable enough to signal on", not rug safety.
LIQ_CONFIRM_MAX_DROP_PCT = float(os.getenv("LIQ_CONFIRM_MAX_DROP_PCT", "30.0"))

# V11.45 PERSISTENT STATE: Railway's default filesystem (/tmp) is wiped on
# every deploy/restart, so the bot "forgets" every token it has seen and has
# to rebuild trend/momentum history from zero each time. If a Railway Volume
# is mounted (recommended path: /data), we use it so state survives deploys.
# Falls back to /tmp automatically if /data isn't mounted/writable yet, so
# the bot still runs fine before the volume is added.
def _resolve_data_dir():
    candidate = os.getenv("DATA_DIR", "/data")
    try:
        os.makedirs(candidate, exist_ok=True)
        probe = os.path.join(candidate, ".write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return candidate
    except Exception as e:
        print(f"DATA_DIR '{candidate}' not writable ({e!r}) — falling back to /tmp (state will NOT survive deploys until a Railway Volume is mounted).", flush=True)
        return "/tmp"

DATA_DIR = _resolve_data_dir()
STATE_FILE = os.path.join(DATA_DIR, "hunterelite_v11_2_state.json")
# V11.39 SIGNAL PERFORMANCE TRACKING: records what actually happened to a
# token after a SIGNAL was sent, so filter changes can be judged against real
# outcomes instead of guesswork.
SIGNAL_LOG_FILE = os.path.join(DATA_DIR, "hunterelite_signal_performance.json")
SIGNAL_CHECKPOINTS = (("1h", 3600), ("6h", 21600), ("24h", 86400))

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
FRESH_PAIR_MAX_HOURS = 2.0

# Multi-source discovery caches. These only supply candidate CAs;
# all candidates still pass the unchanged RURU CORE safety/entry pipeline.
SOURCE_POLL_INTERVAL = 24
SOURCE_CACHE_LIMIT = 120
source_feed_lock = threading.Lock()
source_feed_cache = {"GECKO": [], "RAYDIUM": [], "METEORA": []}
source_feed_last_fetch = {"GECKO": 0.0, "RAYDIUM": 0.0, "METEORA": 0.0}
source_feed_last_error = {"GECKO": "", "RAYDIUM": "", "METEORA": ""}
source_feed_cooldown_until = {"GECKO": 0.0, "RAYDIUM": 0.0, "METEORA": 0.0}
source_feed_fail_count = {"GECKO": 0, "RAYDIUM": 0, "METEORA": 0}

def _feed_can_fetch(source):
    with source_feed_lock:
        return time.time() >= source_feed_cooldown_until.get(source, 0.0)

def _feed_backoff(source, error_text=""):
    low = str(error_text or "").lower()
    with source_feed_lock:
        n = min(6, source_feed_fail_count.get(source, 0) + 1)
        source_feed_fail_count[source] = n
        if "429" in low or "too many requests" in low:
            delay = min(900, 60 * (2 ** (n - 1)))
        else:
            delay = min(600, 30 * (2 ** (n - 1)))
        source_feed_cooldown_until[source] = time.time() + delay
    return delay

def _feed_success(source):
    with source_feed_lock:
        source_feed_fail_count[source] = 0
        source_feed_cooldown_until[source] = 0.0


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
    "momentum_pass": 0, "liq_confirmed": 0, "liq_wait": 0, "liq_drop_block": 0, "clone_block": 0, "signal_gate_pass": 0,
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

# ---------------------------------------------------------------------------
# V11.39 SIGNAL PERFORMANCE TRACKING
# ---------------------------------------------------------------------------
signal_perf_lock = threading.Lock()
signal_perf = {}  # ca -> {name, symbol, entry_price, entry_mc, signal_time, done: [checkpoints]}

def load_signal_perf():
    try:
        p = Path(SIGNAL_LOG_FILE)
        if not p.exists():
            print(f"SIGNAL_PERF_LOAD | file does not exist yet: {SIGNAL_LOG_FILE}", flush=True)
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with signal_perf_lock:
                signal_perf.update(data)
            print(f"SIGNAL_PERF_LOAD | loaded {len(data)} entries from {SIGNAL_LOG_FILE}", flush=True)
    except Exception as e:
        print("SIGNAL PERF LOAD WARNING:", repr(e), flush=True)

def save_signal_perf():
    try:
        with signal_perf_lock:
            data = dict(signal_perf)
        Path(SIGNAL_LOG_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("SIGNAL PERF SAVE WARNING:", repr(e), flush=True)

def record_signal_entry(ca, name, symbol, pair):
    """Call this the moment a SIGNAL is sent. Captures the entry price so we
    can measure real outcomes later instead of guessing from pre-signal data."""
    entry_price = num(pair.get("priceUsd")) if pair else None
    entry_mc = num(pair.get("marketCap")) if pair else None
    entry_liq = num((pair.get("liquidity") or {}).get("usd")) if pair else None
    with signal_perf_lock:
        signal_perf[ca] = {
            "name": name, "symbol": symbol,
            "entry_price": entry_price, "entry_mc": entry_mc, "entry_liq": entry_liq,
            "signal_time": time.time(),
            "done": [], "results": {},
            "rug_alert_sent": False,
        }
    save_signal_perf()
    # V11.53 diagnostic: confirm in Railway logs that this actually wrote to
    # disk, and how many entries the file holds afterward, so a "0 open
    # signals" report can be traced back to a real cause instead of guessed at.
    try:
        _size = Path(SIGNAL_LOG_FILE).stat().st_size
        with signal_perf_lock:
            _count = len(signal_perf)
        print(f"SIGNAL_PERF_WRITTEN | ca={ca} | file={SIGNAL_LOG_FILE} | bytes={_size} | total_entries={_count}", flush=True)
    except Exception as e:
        print(f"SIGNAL_PERF_WRITE_CHECK_FAILED | ca={ca} | error={e!r}", flush=True)

RUG_WATCH_WINDOW_SECONDS = int(os.getenv("RUG_WATCH_WINDOW_SECONDS", "600"))
RUG_WATCH_POLL_SECONDS = int(os.getenv("RUG_WATCH_POLL_SECONDS", "15"))
RUG_WATCH_PRICE_DROP_PCT = float(os.getenv("RUG_WATCH_PRICE_DROP_PCT", "40"))
RUG_WATCH_LIQ_DROP_PCT = float(os.getenv("RUG_WATCH_LIQ_DROP_PCT", "35"))

def rug_watchdog():
    """Fast-cycle safety net. The scanner's normal interval (SCAN_INTERVAL)
    and the 1h/6h/24h performance checkpoints are both too slow to catch a
    rug that plays out in the first 1-2 minutes after a signal. This loop
    checks freshly-signaled tokens every ~15s for the first 10 minutes and
    fires an immediate alert the moment price or liquidity collapses."""
    while True:
        try:
            now = time.time()
            with signal_perf_lock:
                items = list(signal_perf.items())
            for ca, rec in items:
                if rec.get("rug_alert_sent"):
                    continue
                elapsed = now - rec.get("signal_time", now)
                if elapsed > RUG_WATCH_WINDOW_SECONDS:
                    continue
                entry_price = rec.get("entry_price")
                entry_liq = rec.get("entry_liq")
                pair = best_pair(ca)
                if not pair:
                    continue
                cur_price = num(pair.get("priceUsd"))
                cur_liq = num((pair.get("liquidity") or {}).get("usd"))

                price_drop = None
                if entry_price and cur_price is not None and entry_price > 0:
                    price_drop = (entry_price - cur_price) / entry_price * 100.0

                liq_drop = None
                if entry_liq and cur_liq is not None and entry_liq > 0:
                    liq_drop = (entry_liq - cur_liq) / entry_liq * 100.0

                triggered = (
                    (price_drop is not None and price_drop >= RUG_WATCH_PRICE_DROP_PCT)
                    or (liq_drop is not None and liq_drop >= RUG_WATCH_LIQ_DROP_PCT)
                )
                if triggered:
                    with signal_perf_lock:
                        if ca in signal_perf:
                            signal_perf[ca]["rug_alert_sent"] = True
                    save_signal_perf()
                    reason_bits = []
                    if price_drop is not None and price_drop >= RUG_WATCH_PRICE_DROP_PCT:
                        reason_bits.append(f"fiyat -{price_drop:.0f}%")
                    if liq_drop is not None and liq_drop >= RUG_WATCH_LIQ_DROP_PCT:
                        reason_bits.append(f"likidite -{liq_drop:.0f}%")
                    alert = (
                        f"🚨 RUG ALERT — {rec.get('name')} ({rec.get('symbol')})\n"
                        f"CA: {ca}\n\n"
                        f"Sinyal sonrasi {int(elapsed)} sn icinde: {', '.join(reason_bits)}\n"
                        f"Elindeyse pozisyonunu hemen degerlendir.\n\n"
                        f"🔗 Axiom: https://axiom.trade/meme/{ca}"
                    )
                    for chat_id in list(signal_chats):
                        try:
                            send(chat_id, alert)
                        except Exception as e:
                            print("RUG ALERT SEND ERROR:", repr(e), flush=True)
                    print(f"RUG_ALERT_FIRED | {ca} | {rec.get('name')} | {', '.join(reason_bits)}", flush=True)
        except Exception as e:
            print("RUG WATCHDOG ERROR:", repr(e), flush=True)
        time.sleep(RUG_WATCH_POLL_SECONDS)



def signal_performance_tracker():
    """Background loop: for every open SIGNAL, once 1h/6h/24h has elapsed,
    fetch the current price and record the real % change. This is the only
    source of truth for whether the filters are actually working."""
    while True:
        try:
            now = time.time()
            with signal_perf_lock:
                items = list(signal_perf.items())
            for ca, rec in items:
                elapsed = now - rec.get("signal_time", now)
                entry_price = rec.get("entry_price")
                for label, seconds in SIGNAL_CHECKPOINTS:
                    if label in rec.get("done", []):
                        continue
                    if elapsed < seconds:
                        continue
                    change_pct = None
                    if entry_price:
                        pair = best_pair(ca)
                        cur_price = num(pair.get("priceUsd")) if pair else None
                        if cur_price is not None and entry_price > 0:
                            change_pct = round((cur_price - entry_price) / entry_price * 100.0, 1)
                    with signal_perf_lock:
                        if ca in signal_perf:
                            signal_perf[ca].setdefault("done", []).append(label)
                            signal_perf[ca].setdefault("results", {})[label] = change_pct
                    print(
                        f"SIGNAL_PERF | {ca} | {rec.get('name')} ({rec.get('symbol')}) | "
                        f"{label} change={change_pct if change_pct is not None else 'N/A'}%",
                        flush=True,
                    )
                    save_signal_perf()
            # Drop fully-tracked entries (24h done) older than 48h to keep the file small.
            with signal_perf_lock:
                stale = [
                    ca for ca, rec in signal_perf.items()
                    if "24h" in rec.get("done", []) and now - rec.get("signal_time", now) > 172800
                ]
                for ca in stale:
                    signal_perf.pop(ca, None)
            if stale:
                save_signal_perf()
        except Exception as e:
            print("SIGNAL PERF TRACKER ERROR:", repr(e), flush=True)
        time.sleep(300)

def signal_perf_summary():
    """Aggregate win-rate / avg change per checkpoint across all tracked signals."""
    with signal_perf_lock:
        items = list(signal_perf.values())
    out = {}
    for label, _ in SIGNAL_CHECKPOINTS:
        changes = [rec["results"][label] for rec in items if label in rec.get("results", {}) and rec["results"][label] is not None]
        if not changes:
            out[label] = {"count": 0, "avg": None, "win_rate": None}
            continue
        avg = sum(changes) / len(changes)
        wins = sum(1 for c in changes if c > 0)
        out[label] = {"count": len(changes), "avg": round(avg, 1), "win_rate": round(wins / len(changes) * 100, 1)}
    return out

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
    # Repair common UTF-8-as-Latin1 mojibake before the legacy replacements below.
    if any(mark in s for mark in ("Ã", "Ä", "Å", "â")):
        try:
            repaired = s.encode("latin1").decode("utf-8")
            if repaired.count("Ã") + repaired.count("Ä") + repaired.count("Å") < s.count("Ã") + s.count("Ä") + s.count("Å"):
                s = repaired
        except Exception:
            pass
    replacements = {
        "⚠️": "UYARI:", "👀": "", "🚨": "", "💎": "", "🟡": "",
        "🔴": "", "🟢": "", "⏳": "", "📈": "", "📊": "", "💧": "",
        "⚡": "", "💵": "", "👥": "", "🛡": "", "🚀": "", "🎯": "", "⏱": "",
        "SİNYAL İPTAL": "SINYAL IPTAL", "İZLE": "IZLE",
        "GİRME": "GIRME", "GİR": "GIR", "POTANSİYEL": "POTANSIYEL",
        "şartları": "sartlari", "kötüleşti": "kotulesti",
        "giriş": "giris", "için": "icin", "değil": "degil", "yaşı": "yasi",
        "âš ï¸": "UYARI:", "ğŸ‘€": "", "ğŸš¨": "", "ğŸ’Ž": "",
        "ğŸŸ¡": "", "ğŸ”´": "", "â³": "", "Ä°ZLE": "IZLE",
        "SÄ°NYAL Ä°PTAL": "SINYAL IPTAL", "GÄ°RME": "GIRME",
        "GÄ°R": "GIR", "POTANSÄ°YEL": "POTANSIYEL",
        "ÅŸartlarÄ±": "sartlari", "kÃ¶tÃ¼leÅŸti": "kotulesti",
        "giriÅŸ": "giris", "iÃ§in": "icin", "deÄŸil": "degil",
        "yaÅŸÄ±": "yasi",
        "âš ï¸ VERÄ° ALINAMADI": "VERI BEKLENIYOR",
        "VERÄ° ALINAMADI": "VERI BEKLENIYOR",
        "VERİ ALINAMADI": "VERI BEKLENIYOR",
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
        return "⚠️ VERİ ALINAMADI"
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

# V11.43: DexScreener has no API key and a strict shared rate limit. The
# scanner was calling it fresh for every one of ~80 candidates every 12s
# (most of them repeats already seen last cycle) which triggers sustained
# 429s and starves the whole pipeline of data. A short TTL cache plus a
# global cooldown on repeated 429s fixes both the redundant calls and the
# hammering that makes the 429s worse.
DEX_PAIR_CACHE_TTL = int(os.getenv("DEX_PAIR_CACHE_TTL", "20"))
dex_pair_cache_lock = threading.Lock()
dex_pair_cache = {}  # ca -> (timestamp, pairs)
dex_cooldown_lock = threading.Lock()
dex_cooldown_until = 0.0
dex_429_streak = 0

def _dex_rate_limited():
    with dex_cooldown_lock:
        return time.time() < dex_cooldown_until

def _dex_note_429():
    global dex_cooldown_until, dex_429_streak
    with dex_cooldown_lock:
        dex_429_streak = min(8, dex_429_streak + 1)
        delay = min(120, 5 * (2 ** (dex_429_streak - 1)))
        dex_cooldown_until = time.time() + delay
    print(f"DEX RATE LIMIT: backing off {delay}s (streak={dex_429_streak})", flush=True)

def _dex_note_success():
    global dex_429_streak
    with dex_cooldown_lock:
        dex_429_streak = 0

def dex_pairs(ca):
    # Serve from cache without hitting the network at all when fresh enough,
    # or when we're inside a cooldown window from recent 429s.
    now = time.time()
    with dex_pair_cache_lock:
        cached = dex_pair_cache.get(ca)
    if cached and (now - cached[0] < DEX_PAIR_CACHE_TTL):
        return cached[1]
    if _dex_rate_limited():
        return cached[1] if cached else []

    urls = [
        f"https://api.dexscreener.com/token-pairs/v1/solana/{ca}",
        f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
    ]
    for url in urls:
        try:
            data = get_json(url)
            _dex_note_success()
            if isinstance(data, list):
                pairs = data
            elif isinstance(data, dict):
                pairs = data.get("pairs") or []
            else:
                pairs = []
            sol_pairs = [p for p in pairs if str(p.get("chainId", "solana")).lower() == "solana"]
            if sol_pairs:
                with dex_pair_cache_lock:
                    dex_pair_cache[ca] = (time.time(), sol_pairs)
                return sol_pairs
        except urllib.error.HTTPError as e:
            if getattr(e, "code", None) == 429:
                _dex_note_429()
                return cached[1] if cached else []
            print("DEX PAIR ERROR:", repr(e), flush=True)
        except Exception as e:
            print("DEX PAIR ERROR:", repr(e), flush=True)
    # Cache the empty result briefly too, so a token with genuinely no pair
    # yet doesn't get re-requested every single candidate pass.
    with dex_pair_cache_lock:
        dex_pair_cache[ca] = (time.time(), [])
    return []

def best_pair(ca):
    # DexScreener token endpoint is eventually consistent for brand-new launches.
    # Try the normal lookup first, then the search endpoint so candidates discovered
    # by Gecko/Raydium/Meteora are not discarded before scoring.
    pairs = dex_pairs(ca)
    if not pairs and not _dex_rate_limited():
        try:
            data = get_json("https://api.dexscreener.com/latest/dex/search?" + urllib.parse.urlencode({"q": ca}), timeout=10)
            _dex_note_success()
            rows = (data or {}).get("pairs") or [] if isinstance(data, dict) else []
            pairs = [p for p in rows if str(p.get("chainId", "")).lower() == "solana" and ca in (str((p.get("baseToken") or {}).get("address","")), str((p.get("quoteToken") or {}).get("address","")))]
        except urllib.error.HTTPError as e:
            if getattr(e, "code", None) == 429:
                _dex_note_429()
            else:
                print("DEX SEARCH FALLBACK ERROR:", ca, repr(e), flush=True)
        except Exception as e:
            print("DEX SEARCH FALLBACK ERROR:", ca, repr(e), flush=True)
    if not pairs:
        return None
    return max(pairs, key=lambda p: num((p.get("liquidity") or {}).get("usd"), 0))

def recover_dex_liquidity(ca, current_pair=None):
    """Conservative recovery: only use explicit USD liquidity from another Solana pair."""
    candidates = []
    if current_pair:
        candidates.append(current_pair)
    try:
        candidates.extend(dex_pairs(ca))
    except Exception:
        pass
    best = None
    for p in candidates:
        if not isinstance(p, dict):
            continue
        liq = num((p.get("liquidity") or {}).get("usd"))
        if liq is None:
            continue
        if best is None or liq > best:
            best = liq
    return best


def recover_gecko_liquidity(ca):
    """Keyless GeckoTerminal fallback. Returns explicit reserve_in_usd only."""
    try:
        url = (
            "https://api.geckoterminal.com/api/v2/networks/solana/tokens/"
            + urllib.parse.quote(str(ca), safe="")
            + "/pools?page=1"
        )
        payload = get_json(url, timeout=12, headers={"Accept": "application/json;version=20230203"})
        best = None
        for row in (payload.get("data") or []) if isinstance(payload, dict) else []:
            attrs = (row or {}).get("attributes") or {}
            liq = num(attrs.get("reserve_in_usd"))
            if liq is not None and (best is None or liq > best):
                best = liq
        return best
    except Exception as e:
        print("GECKO LIQ RECOVERY ERROR:", ca, repr(e), flush=True)
        return None

def _norm_identity(v):
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())

def clone_impersonation_guard(name, symbol, ca, current_pair):
    """
    Block a fresh token when DexScreener already shows an older exact-name+symbol
    Solana token at a different CA. This runs only at WATCH/SIGNAL time.
    """
    nk, sk = _norm_identity(name), _norm_identity(symbol)
    if not nk or not sk or len(nk) < 3:
        return True, ""
    current_created = num((current_pair or {}).get("pairCreatedAt"))
    try:
        data = get_json(
            "https://api.dexscreener.com/latest/dex/search?" +
            urllib.parse.urlencode({"q": f"{name} {symbol}"}), timeout=10
        )
        rows = (data or {}).get("pairs") or []
    except Exception:
        # Data failure is neutral; never invent a clone verdict.
        return True, ""

    for p in rows[:30]:
        if str(p.get("chainId", "")).lower() != "solana":
            continue
        base = p.get("baseToken") or {}
        other_ca = str(base.get("address") or "")
        if not other_ca or other_ca == ca:
            continue
        if _norm_identity(base.get("name")) != nk or _norm_identity(base.get("symbol")) != sk:
            continue
        other_created = num(p.get("pairCreatedAt"))
        other_liq = num((p.get("liquidity") or {}).get("usd"), 0) or 0
        # Require evidence of an older established exact-name token.
        if other_created and current_created and other_created < current_created - 60_000 and other_liq >= MIN_LIQUIDITY:
            return False, f"CLONE: older exact name/symbol CA {other_ca[:6]}... exists"
    return True, ""

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
    if not _feed_can_fetch("GECKO"):
        return _cached_source("GECKO")
    now = time.time()
    with source_feed_lock:
        last = source_feed_last_fetch.get("GECKO", 0.0)
        cached = list(source_feed_cache.get("GECKO", []))
    if not force and cached and now - last < SOURCE_POLL_INTERVAL:
        return cached

    found, seen, errors = [], set(), []
    for page in (1,):
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

    errtxt = ";".join(errors[:3])
    if errors:
        _feed_backoff("GECKO", errtxt)
    else:
        _feed_success("GECKO")
    return _cache_source_result("GECKO", found, errtxt)

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
    if not _feed_can_fetch("RAYDIUM"):
        return _cached_source("RAYDIUM")
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
        except urllib.error.HTTPError as e:
            host = urllib.parse.urlparse(url).netloc
            errors.append(f"HTTP{getattr(e,'code','?')}@{host}")
        except Exception as e:
            host = urllib.parse.urlparse(url).netloc
            errors.append(f"{type(e).__name__}@{host}")

    errtxt = ";".join(errors[:4])
    if not found and errors:
        _feed_backoff("RAYDIUM", errtxt)
    else:
        _feed_success("RAYDIUM")
    return _cache_source_result("RAYDIUM", found, errtxt)

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
    if not _feed_can_fetch("METEORA"):
        return _cached_source("METEORA")
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
        except urllib.error.HTTPError as e:
            host = urllib.parse.urlparse(url).netloc
            errors.append(f"HTTP{getattr(e,'code','?')}@{host}")
        except Exception as e:
            host = urllib.parse.urlparse(url).netloc
            errors.append(f"{type(e).__name__}@{host}")

    errtxt = ";".join(errors[:4])
    if not found and errors:
        _feed_backoff("METEORA", errtxt)
    else:
        _feed_success("METEORA")
    return _cache_source_result("METEORA", found, errtxt)

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

def lp_locked_pct(report):
    """
    Extract the locked/burned percentage of the liquidity pool from RugCheck's
    markets[].lp block. RugCheck reports LP lock under a few different key
    names depending on report version, so we check the common variants.
    Returns None when it genuinely cannot be determined (never treated as
    'locked' by default — see LP_LOCK_MIN_PCT usage).
    """
    if not isinstance(report, dict):
        return None
    best = None
    for market in report.get("markets") or []:
        if not isinstance(market, dict):
            continue
        lp = market.get("lp") or {}
        if not isinstance(lp, dict):
            continue
        for key in ("lpLockedPct", "lpLockedPercent", "lockedPct", "lp_locked_pct"):
            value = num(lp.get(key))
            if value is not None:
                value = value if value <= 100 else 100.0
                best = value if best is None else max(best, value)
        # Some reports give locked/total token amounts instead of a percent.
        locked_amt = num(lp.get("lpLocked"))
        total_amt = num(lp.get("lpTotalSupply") or lp.get("totalSupply"))
        if best is None and locked_amt is not None and total_amt:
            try:
                pct = max(0.0, min(100.0, locked_amt / total_amt * 100.0))
                best = pct
            except ZeroDivisionError:
                pass
    # Top-level fallback some report versions expose directly.
    if best is None:
        for key in ("lpLockedPct", "totalLPLockedPct"):
            value = num(report.get(key))
            if value is not None:
                best = value if value <= 100 else 100.0
    return best

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
    # V11.39 FAIL-CLOSED: when the risk report never loaded (API error, rate
    # limit, timeout), we do NOT know the token is safe. "unknown" is a
    # distinct state from "checked and clean" so callers can block/hold
    # instead of silently treating missing data as a pass.
    result = {"rug": False, "honeypot": False, "insider": False, "sniper": False, "bundler": False, "unknown": False}
    if not report:
        result["unknown"] = True
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
        risks.append("Market cap hedef bölgesi dışında")

    if liq is None:
        score -= 25
        risks.append("Likidite verisi yok")
    elif liq < MIN_LIQUIDITY:
        score -= 30
        risks.append("Likidite minimum altı")
    elif liq < 800:
        score -= 12
        risks.append("Likidite düşük / erken aşama")

    top1, top5, top10 = holders(report)

    if report is None:
        score -= 15
        risks.append("RugCheck verisi yok")
    elif top10 is None:
        score -= 10
        risks.append("Holder dağılımı doğrulanamadı")
    else:
        if top10 >= 90:
            score -= 40
            risks.append("Top-10 holder aşırı yoğun")
        elif top10 >= 82:
            score -= 22
            risks.append("Top-10 holder çok yüksek")
        elif top10 >= 70:
            score -= 14
            risks.append("Top-10 holder yüksek")
        elif top10 >= 60:
            score -= 8
            risks.append("Top-10 holder dikkat")

    mint = authority(report, "mintAuthority")
    freeze = authority(report, "freezeAuthority")

    if mint is True:
        score -= 30
        risks.append("Mint authority aktif")
    elif mint is None:
        score -= 5
        risks.append("Mint authority doğrulanamadı")

    if freeze is True:
        score -= 30
        risks.append("Freeze authority aktif")
    elif freeze is None:
        score -= 5
        risks.append("Freeze authority doğrulanamadı")

    sig = rug_signals(report)

    lp_pct = lp_locked_pct(report)
    has_lp_market = bool(isinstance(report, dict) and report.get("markets"))

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
        risks.append("Sniper yoğunluğu")
    if sig["bundler"]:
        score -= 10
        risks.append("Bundler sinyali")
    if lp_pct is not None and lp_pct < LP_LOCK_MIN_PCT:
        score -= 25
        risks.append(f"LP kilidi dusuk (%{lp_pct:.0f})")
    elif has_lp_market and lp_pct is None:
        score -= 15
        risks.append("LP kilit verisi dogrulanamadi")
    if top1 is not None and top1 >= TOP1_MAX_PCT:
        score -= 25
        risks.append(f"Tek cuzdan yogunlugu yuksek (top1 %{top1:.0f})")

    buys, sells = m["buys5"], m["sells5"]
    if buys + sells >= 10 and sells > buys * 1.5:
        score -= 10
        risks.append("5dk satış baskısı")

    if m["price5"] is not None and m["price5"] <= -25:
        score -= 10
        risks.append("5dk sert fiyat düşüşü")

    score = max(0, min(100, int(score)))

    severe = (
        sig["rug"]
        or sig["honeypot"]
        or mint is True
        or freeze is True
        or (top10 is not None and top10 >= HOLDER_TOP10_MAX)
        or (top1 is not None and top1 >= TOP1_MAX_PCT)
        or (has_lp_market and (lp_pct is None or lp_pct < LP_LOCK_MIN_PCT))
    )

    if severe:
        decision = "🔴 GİRME"
    elif score >= 75 and mc is not None and MC_MIN <= mc <= EARLY_MC_MAX:
        decision = "🟢 UYGUN GİRİŞ"
    elif score >= 55:
        decision = "🟡 BEKLE"
    else:
        decision = "🔴 GİRME"

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
        "lp_locked_pct": lp_pct,
        "has_lp_market": has_lp_market,
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
        return "🚨 AKTİF"
    if value is False:
        return "✅ KAPALI"
    return "⚠️ N/A"

def potential_label(result, momentum=0):
    """Heuristic only: expresses upside setup quality, never a return guarantee."""
    if not result:
        return "❌ YETERSİZ VERİ"

    # Hard safety blocks first.
    if result["signals"]["rug"] or result["signals"]["honeypot"]:
        return "⛔ RUG RİSKİ"
    if result["mint"] is True or result["freeze"] is True:
        return "⛔ YETKİ RİSKİ"
    if result["liq"] is None or result["liq"] < MIN_LIQUIDITY:
        return "🔴 ZAYIF"
    if result["top10"] is not None and result["top10"] >= HOLDER_TOP10_MAX:
        return "🔴 DAĞILIM RİSKİ"

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
        return "💎 100X POTANSİYEL ADAYI"

    if (
        2000 <= mc <= 9000
        and score >= 68
        and buys >= 5
        and buy_ratio_ok
        and vol5 >= 250
    ):
        return "🚀 5X-10X POTANSIYEL ADAYI"

    if score >= 58:
        return "🟡 ERKEN / İZLE"

    return "🔴 GİRME"


def simple_action(result, momentum=0, previous=None):
    if not result:
        return "🔴 GİRME"

    if not basic_signal_safe(result) or not crash_guard(result):
        return "🔴 GİRME"

    p5 = result.get("price5")
    buys = result.get("buys5", 0)
    sells = result.get("sells5", 0)

    if p5 is not None and p5 <= -8:
        return "🔴 SAT / GİRME"
    if sells > buys * 1.35 and buys + sells >= 8:
        return "🔴 SAT / GİRME"

    if strong_signal(result, momentum, previous):
        return "🟢 GİR"

    if watch_candidate(result):
        return "🟡 İZLE / ERKEN ADAY"

    return "🔴 GİRME"


def _pair_social_links(pair):
    info = (pair or {}).get("info") or {}
    socials = info.get("socials") or []
    websites = info.get("websites") or []
    out = {"x": [], "telegram": [], "reddit": [], "website": []}

    for s in socials:
        if not isinstance(s, dict):
            continue
        url = str(s.get("url") or "").strip()
        stype = str(s.get("type") or "").lower()
        low = url.lower()
        if not url:
            continue
        if stype in ("twitter", "x") or "x.com/" in low or "twitter.com/" in low:
            out["x"].append(url)
        elif stype == "telegram" or "t.me/" in low or "telegram.me/" in low:
            out["telegram"].append(url)
        elif stype == "reddit" or "reddit.com/" in low:
            out["reddit"].append(url)

    for w in websites:
        if isinstance(w, dict):
            url = str(w.get("url") or "").strip()
        else:
            url = str(w or "").strip()
        if url:
            out["website"].append(url)

    for k in out:
        # stable dedupe
        seen, deduped = set(), []
        for url in out[k]:
            if url not in seen:
                seen.add(url)
                deduped.append(url)
        out[k] = deduped[:4]
    return out



def _strip_html_text(value):
    s = html.unescape(str(value or ""))
    s = re.sub(r"<script\\b[^>]*>.*?</script>", " ", s, flags=re.I|re.S)
    s = re.sub(r"<style\\b[^>]*>.*?</style>", " ", s, flags=re.I|re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\\s+", " ", s).strip()


def _public_search_ddg(query, limit=12):
    """Manual-only public web search fallback. No login/API key required.
    Conservative: returns URLs/titles/snippets only; never invents engagement metrics.
    """
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Android 16; HunterEliteBot/11.36.8)",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return [], f"SEARCH_{type(e).__name__}"

    rows = []
    # DuckDuckGo HTML result anchors and snippets. Keep parsing intentionally tolerant.
    blocks = re.split(r'<div[^>]+class="[^"]*result[^"]*"[^>]*>', raw, flags=re.I)
    for block in blocks[1:]:
        href_m = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.I|re.S)
        if not href_m:
            continue
        href = html.unescape(href_m.group(1))
        title = _strip_html_text(href_m.group(2))
        if "uddg=" in href:
            try:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href = qs.get("uddg", [href])[0]
            except Exception:
                pass
        sn_m = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</', block, flags=re.I|re.S)
        snippet = _strip_html_text(sn_m.group(1)) if sn_m else ""
        if href.startswith("http"):
            rows.append({"url": href, "title": title, "snippet": snippet})
        if len(rows) >= limit:
            break
    return rows, "OK" if rows else "NO_RESULTS"


def _x_oembed_verify(tweet_url):
    """Verify a concrete public X post URL via X's public oEmbed endpoint.
    oEmbed does not provide follower counts or engagement metrics.
    """
    try:
        url = "https://publish.twitter.com/oembed?" + urllib.parse.urlencode({
            "url": tweet_url, "omit_script": "true", "dnt": "true"
        })
        data = get_json(url, timeout=10)
        author = str((data or {}).get("author_name") or "").strip()
        author_url = str((data or {}).get("author_url") or "").strip()
        handle = ""
        m = re.search(r'(?:x|twitter)\\.com/([^/?#]+)', author_url, flags=re.I)
        if m:
            handle = m.group(1)
        body = _strip_html_text((data or {}).get("html") or "")
        return {"ok": True, "author": author, "handle": handle, "text": body[:500]}
    except Exception:
        return {"ok": False, "author": "", "handle": "", "text": ""}


def _public_x_web_social(ca, name, symbol):
    terms = [ca]
    if name and name != "Unknown":
        terms.append(f'"{str(name).replace(chr(34), "")[:60]}"')
    if symbol and symbol not in ("", "N/A"):
        terms.append(f'"{str(symbol)[:15]}"')
    q = "site:x.com " + " ".join(terms[:3])
    rows, status = _public_search_ddg(q, limit=12)
    posts = []
    handles = {}
    for row in rows:
        u = row.get("url") or ""
        if not re.search(r'https?://(?:www\\.)?(?:x|twitter)\\.com/', u, flags=re.I):
            continue
        m = re.search(r'(?:x|twitter)\\.com/([^/?#]+)/status/(\\d+)', u, flags=re.I)
        if not m:
            continue
        verified = _x_oembed_verify(u)
        if verified.get("ok"):
            h = verified.get("handle") or m.group(1)
            if h:
                handles[h] = handles.get(h, 0) + 1
            posts.append({"url": u, "handle": h, "text": verified.get("text") or row.get("snippet") or ""})
        if len(posts) >= 8:
            break
    return {
        "status": "PUBLIC_WEB_OK" if posts else status,
        "posts": len(posts),
        "engagement": None,
        "major_posts": 0,
        "major_accounts": [],
        "top_accounts": [{"username": h, "followers": None, "engagement": None, "verified": False} for h, _ in sorted(handles.items(), key=lambda kv: kv[1], reverse=True)[:4]],
        "recent_minutes": None,
        "verified_urls": [p["url"] for p in posts[:5]],
    }


def _public_reddit_social(ca, name, symbol):
    # Public search fallback. If Reddit blocks anonymous JSON, degrade to web-search mentions.
    qparts = [ca]
    if name and name != "Unknown":
        qparts.append(str(name)[:60])
    if symbol and symbol not in ("", "N/A"):
        qparts.append(str(symbol)[:15])
    query = " OR ".join(qparts[:3])
    try:
        url = "https://www.reddit.com/search.json?" + urllib.parse.urlencode({
            "q": query, "sort": "new", "t": "week", "limit": 20, "raw_json": 1
        })
        req = urllib.request.Request(url, headers={"User-Agent": REDDIT_USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        children = (((data or {}).get("data") or {}).get("children") or [])
        score = comments = 0
        newest = None
        now = time.time()
        for child in children:
            p = (child or {}).get("data") or {}
            score += safe_int(p.get("score"))
            comments += safe_int(p.get("num_comments"))
            created = num(p.get("created_utc"))
            if created:
                age_h = max(0.0, (now - created) / 3600.0)
                newest = age_h if newest is None else min(newest, age_h)
        return {"status": "PUBLIC_JSON_OK", "posts": len(children), "score": score, "comments": comments, "recent_hours": newest}
    except Exception:
        rows, status = _public_search_ddg("site:reddit.com " + " ".join(qparts[:3]), limit=10)
        return {"status": "PUBLIC_WEB_OK" if rows else status, "posts": len(rows), "score": None, "comments": None, "recent_hours": None}


def _public_general_mentions(ca, name, symbol):
    q = " ".join([x for x in [ca, f'"{name}"' if name and name != "Unknown" else "", symbol if symbol not in ("", "N/A") else ""] if x])
    rows, status = _public_search_ddg(q, limit=12)
    domains = []
    for r in rows:
        try:
            d = urllib.parse.urlparse(r.get("url") or "").netloc.lower().replace("www.", "")
        except Exception:
            d = ""
        if d and d not in domains:
            domains.append(d)
    return {"status": status, "mentions": len(rows), "domains": domains[:6]}

def _x_recent_social(ca, name, symbol):
    if not X_BEARER_TOKEN:
        return _public_x_web_social(ca, name, symbol)

    # Search CA first; name/symbol are additive but quoted to reduce noise.
    terms = [ca]
    if name and name != "Unknown":
        safe_name = str(name).replace('"', '')[:70]
        terms.append(f'"{safe_name}"')
    if symbol and symbol not in ("N/A", "") and len(str(symbol)) >= 2:
        safe_symbol = re.sub(r"[^A-Za-z0-9_]+", "", str(symbol))[:15]
        if safe_symbol:
            terms.append(f'"${safe_symbol}"')
    query = "(" + " OR ".join(terms[:3]) + ") -is:retweet"

    params = {
        "query": query,
        "max_results": 50,
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "id,name,username,verified,verified_type,public_metrics",
    }
    url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode(params)
    headers = {
        "Authorization": f"Bearer {X_BEARER_TOKEN}",
        "Accept": "application/json",
        "User-Agent": "HunterEliteBot/11.36.7",
    }
    try:
        data = get_json(url, timeout=14, headers=headers)
    except urllib.error.HTTPError as e:
        return {
            "status": f"X_HTTP_{getattr(e, 'code', 'ERR')}", "posts": 0, "engagement": 0,
            "major_posts": 0, "major_accounts": [], "top_accounts": [], "recent_minutes": None
        }
    except Exception:
        return {
            "status": "X_ERROR", "posts": 0, "engagement": 0, "major_posts": 0,
            "major_accounts": [], "top_accounts": [], "recent_minutes": None
        }

    users = {}
    for u in ((data.get("includes") or {}).get("users") or []):
        if isinstance(u, dict):
            users[str(u.get("id"))] = u

    posts = data.get("data") or []
    total_eng = 0
    major_posts = 0
    major_accounts = {}
    top_accounts = {}
    newest_age_min = None
    now = time.time()

    for p in posts:
        if not isinstance(p, dict):
            continue
        pm = p.get("public_metrics") or {}
        eng = (
            safe_int(pm.get("like_count")) +
            safe_int(pm.get("retweet_count")) +
            safe_int(pm.get("reply_count")) +
            safe_int(pm.get("quote_count"))
        )
        total_eng += eng

        created = str(p.get("created_at") or "")
        if created:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_min = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() / 60))
                newest_age_min = age_min if newest_age_min is None else min(newest_age_min, age_min)
            except Exception:
                pass

        author = users.get(str(p.get("author_id"))) or {}
        username = str(author.get("username") or "").strip()
        upm = author.get("public_metrics") or {}
        followers = safe_int(upm.get("followers_count"))
        verified = bool(author.get("verified")) or bool(author.get("verified_type"))

        if username:
            rec = top_accounts.setdefault(username, {"followers": followers, "engagement": 0, "verified": verified})
            rec["followers"] = max(rec["followers"], followers)
            rec["engagement"] += eng
            rec["verified"] = rec["verified"] or verified

        if followers >= SOCIAL_MAJOR_FOLLOWERS or verified:
            major_posts += 1
            if username:
                rec = major_accounts.setdefault(username, {"followers": followers, "engagement": 0, "verified": verified})
                rec["followers"] = max(rec["followers"], followers)
                rec["engagement"] += eng
                rec["verified"] = rec["verified"] or verified

    def pack_accounts(d):
        ranked = sorted(
            d.items(),
            key=lambda kv: (kv[1].get("followers", 0), kv[1].get("engagement", 0)),
            reverse=True,
        )[:4]
        return [
            {
                "username": k,
                "followers": v.get("followers", 0),
                "engagement": v.get("engagement", 0),
                "verified": bool(v.get("verified")),
            }
            for k, v in ranked
        ]

    return {
        "status": "OK",
        "posts": len(posts),
        "engagement": total_eng,
        "major_posts": major_posts,
        "major_accounts": pack_accounts(major_accounts),
        "top_accounts": pack_accounts(top_accounts),
        "recent_minutes": newest_age_min,
    }


_reddit_token_cache = {"token": "", "expires": 0.0}

def _reddit_oauth_token():
    # Prefer an explicitly supplied token; otherwise obtain app-only OAuth token.
    if REDDIT_ACCESS_TOKEN:
        return REDDIT_ACCESS_TOKEN
    now = time.time()
    if _reddit_token_cache.get("token") and now < _reddit_token_cache.get("expires", 0) - 60:
        return _reddit_token_cache["token"]
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        return ""
    import base64
    auth = base64.b64encode(f"{REDDIT_CLIENT_ID}:{REDDIT_CLIENT_SECRET}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token", data=body, method="POST",
        headers={"Authorization": f"Basic {auth}", "User-Agent": REDDIT_USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=14) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        token = str(data.get("access_token") or "").strip()
        if token:
            _reddit_token_cache["token"] = token
            _reddit_token_cache["expires"] = now + max(300, safe_int(data.get("expires_in"), 3600))
        return token
    except Exception:
        return ""

def _reddit_recent_social(ca, name, symbol):
    reddit_token = _reddit_oauth_token()
    if not reddit_token:
        return {"status": "NO_REDDIT_API", "posts": 0, "score": 0, "comments": 0, "recent_hours": None}

    q_parts = [ca]
    if name and name != "Unknown":
        q_parts.append(f'"{str(name)[:60]}"')
    if symbol and symbol not in ("N/A", ""):
        q_parts.append(str(symbol)[:15])
    params = {
        "q": " OR ".join(q_parts[:3]),
        "sort": "new",
        "t": "week",
        "limit": 25,
        "restrict_sr": "false",
        "type": "link",
    }
    url = "https://oauth.reddit.com/search?" + urllib.parse.urlencode(params)
    headers = {
        "Authorization": f"bearer {reddit_token}",
        "User-Agent": REDDIT_USER_AGENT,
        "Accept": "application/json",
    }
    try:
        data = get_json(url, timeout=14, headers=headers)
    except urllib.error.HTTPError as e:
        return {"status": f"REDDIT_HTTP_{getattr(e,'code','ERR')}", "posts": 0, "score": 0, "comments": 0, "recent_hours": None}
    except Exception:
        return {"status": "REDDIT_ERROR", "posts": 0, "score": 0, "comments": 0, "recent_hours": None}

    children = (((data or {}).get("data") or {}).get("children") or [])
    score = comments = 0
    newest = None
    now = time.time()
    for child in children:
        p = (child or {}).get("data") or {}
        score += safe_int(p.get("score"))
        comments += safe_int(p.get("num_comments"))
        created = num(p.get("created_utc"))
        if created:
            age_h = max(0.0, (now - created) / 3600.0)
            newest = age_h if newest is None else min(newest, age_h)
    return {
        "status": "OK", "posts": len(children), "score": score,
        "comments": comments, "recent_hours": newest
    }


def deep_social_analysis(ca, pair, name, symbol):
    links = _pair_social_links(pair)

    with ThreadPoolExecutor(max_workers=3) as ex:
        fx = ex.submit(_x_recent_social, ca, name, symbol)
        fr = ex.submit(_reddit_recent_social, ca, name, symbol)
        fw = ex.submit(_public_general_mentions, ca, name, symbol)
        x = fx.result()
        reddit = fr.result()
        web_mentions = fw.result()

    has_x = bool(links["x"])
    has_tg = bool(links["telegram"])
    has_reddit_link = bool(links["reddit"])
    has_site = bool(links["website"])

    presence = 0
    presence += 25 if has_x else 0
    presence += 15 if has_tg else 0
    presence += 10 if has_reddit_link else 0
    presence += 15 if has_site else 0
    if x.get("status") in ("OK", "PUBLIC_WEB_OK") and x.get("posts", 0) > 0:
        presence += min(25, 5 + x.get("posts", 0))
    if reddit.get("status") in ("OK", "PUBLIC_JSON_OK", "PUBLIC_WEB_OK") and reddit.get("posts", 0) > 0:
        presence += min(10, reddit.get("posts", 0) * 2)
    presence += min(10, web_mentions.get("mentions", 0))
    presence = min(100, presence)

    viral = 0
    if x.get("status") == "OK":
        viral += min(45, x.get("posts", 0) * 2)
        viral += min(35, int((x.get("engagement") or 0) / 20))
        viral += min(20, x.get("major_posts", 0) * 7)
        if x.get("recent_minutes") is not None and x["recent_minutes"] <= 60:
            viral += 10
    elif x.get("status") == "PUBLIC_WEB_OK":
        # Public-web fallback can verify post URLs/authors, but not engagement/follower counts.
        viral += min(30, x.get("posts", 0) * 4)
    if reddit.get("status") in ("OK", "PUBLIC_JSON_OK"):
        viral += min(15, reddit.get("posts", 0) * 2)
        viral += min(10, int(((reddit.get("score") or 0) + (reddit.get("comments") or 0)) / 20))
    elif reddit.get("status") == "PUBLIC_WEB_OK":
        viral += min(10, reddit.get("posts", 0) * 2)
    viral += min(10, web_mentions.get("mentions", 0))
    viral = min(100, viral)

    major = x.get("major_accounts") or []
    if major:
        catalyst = "MAJOR ACCOUNT ACTIVITY"
    elif x.get("status") == "OK" and (x.get("engagement") or 0) >= SOCIAL_VIRAL_ENGAGEMENT:
        catalyst = "HIGH X ENGAGEMENT"
    elif x.get("status") == "PUBLIC_WEB_OK" and x.get("posts", 0) >= 3:
        catalyst = "PUBLIC X MENTIONS"
    elif viral >= 60:
        catalyst = "VIRAL RISING"
    elif viral >= 30:
        catalyst = "SOCIAL RISING"
    else:
        catalyst = "NO VERIFIED CATALYST"

    if viral >= 70:
        viral_label = "VIRAL"
    elif viral >= 45:
        viral_label = "RISING"
    elif viral >= 20:
        viral_label = "EARLY"
    else:
        viral_label = "WEAK/UNKNOWN"

    return {
        "links": links,
        "x": x,
        "reddit": reddit,
        "web_mentions": web_mentions,
        "presence_score": presence,
        "viral_score": viral,
        "viral_label": viral_label,
        "catalyst": catalyst,
    }


def _fmt_major_accounts(accounts):
    if not accounts:
        return "YOK / DOGRULANAMADI"
    parts = []
    for a in accounts[:3]:
        followers = safe_int(a.get("followers"))
        username = a.get("username") or "?"
        mark = "✓" if a.get("verified") else ""
        parts.append(f"@{username}{mark} ({followers:,} takipci)")
    return ", ".join(parts)


def decision_reason(result, clone_safe=True):
    """Short, specific reason for the current tier — shown next to the decision
    so 'UZAK DUR' isn't a black box."""
    if not result:
        return "veri alinamadi"
    sig = result.get("signals") or {}
    if sig.get("rug"):
        return "rug sinyali tespit edildi"
    if sig.get("honeypot"):
        return "honeypot sinyali tespit edildi"
    if sig.get("unknown"):
        return "rug/guvenlik verisi dogrulanamadi"
    if sig.get("bundler"):
        return "bundled wallet (koordineli alim) tespit edildi"
    if sig.get("insider"):
        return "insider/dev cuzdan sinyali tespit edildi"
    if sig.get("sniper"):
        return "sniper cuzdan yogunlugu tespit edildi"
    if result.get("mint") is True:
        return "mint authority acik (arz sonradan artabilir)"
    if result.get("freeze") is True:
        return "freeze authority acik (cuzdan dondurulabilir)"
    if result.get("liq") is None or result["liq"] < MIN_LIQUIDITY:
        return f"likidite {money(MIN_LIQUIDITY)} esiginin altinda/yok"
    top10 = result.get("top10")
    if top10 is not None and top10 >= HOLDER_TOP10_MAX:
        return f"top-10 holder %{HOLDER_TOP10_MAX:.0f} esiginin uzerinde"
    if top10 is None and not ALLOW_MISSING_HOLDER:
        return "holder dagilimi dogrulanamadi"
    top1 = result.get("top1")
    if top1 is not None and top1 >= TOP1_MAX_PCT:
        return f"tek cuzdan payi %{TOP1_MAX_PCT:.0f} esiginin uzerinde"
    lp_pct = result.get("lp_locked_pct")
    if result.get("has_lp_market") and (lp_pct is None or lp_pct < LP_LOCK_MIN_PCT):
        return "LP kilit/burn orani yetersiz veya dogrulanamadi"
    age = result.get("age_hours")
    if age is not None and age < (MIN_PAIR_AGE_MINUTES / 60.0):
        return f"pair {MIN_PAIR_AGE_MINUTES:.0f} dakikadan taze (bundle dump penceresi)"
    if not crash_guard(result):
        _, _reason = crash_guard_detail(result)
        if _reason == "late_pump":
            return f"fiyat zaten %{LATE_ENTRY_MAX_PRICE1H_PCT:.0f}+ pompalanmis (zirveye yakin, gec giris)"
        if _reason == "topping":
            return "fiyat zirve yapip donmeye basliyor (5dk negatif, 1sa hala yuksek)"
        if _reason == "peak_drawdown":
            dd = result.get("drawdown_from_peak_pct")
            return f"gordugumuz zirveden %{dd:.0f} dustu (erken pump-dump)" if dd is not None else "gordugumuz zirveden ciddi dustu"
        if _reason == "stale_spike":
            return "6 saatlik veri buyuk bir zirveyi gosteriyor ama 1 saatlik veride buyuk kismi geri cekilmis (biz gormeden once pompalanip sonmus)"
        return "fiyat son periyotta sert dustu (crash guard)"
    if not clone_safe:
        return "isim/sembol taninmis bir tokenin klonu olabilir"
    return ""

def manual_general_decision(result, social, clone_safe=True):
    """Discrete, unambiguous tiers so the person doesn't have to interpret a
    raw score. Safety gates (rug/authority/liquidity/holder/crash/clone) are
    hard blocks — no score can override them."""
    if not result:
        return "⚪ VERİ YOK"

    safety_ok = basic_signal_safe(result) and crash_guard(result) and clone_safe
    if not safety_ok:
        reason = decision_reason(result, clone_safe)
        return f"🔴 UZAK DUR ({reason})" if reason else "🔴 UZAK DUR"

    score = result.get("score", 0)
    buys, sells = result.get("buys5", 0), result.get("sells5", 0)
    p5 = result.get("price5")
    vol5 = result.get("vol5") or 0
    viral = social.get("viral_score", 0)
    strong_market = (
        buys >= 8 and buys >= max(1, sells * 1.15)
        and vol5 >= 300 and p5 is not None and 1 <= p5 <= 55
    )

    # Passed every hard safety gate. Now it's purely about entry strength.
    if strong_market and viral >= 50 and score >= SIGNAL_SCORE + 10:
        return "🟢🟢 GÜÇLÜ GİR (güvenlik temiz + hacim/momentum/sosyal güçlü)"
    if strong_market and score >= SIGNAL_SCORE:
        return "🟢 GİR (güvenlik temiz, aktivite yeterli)"
    if score >= WATCH_SCORE:
        return "🟡 BEKLE (güvenlik temiz ama aktivite/momentum henüz zayıf)"
    return "🟠 ZAYIF ADAY (güvenlik temiz ama skor düşük — acele etme)"

def analyse(ca):
    pair = best_pair(ca)
    if pair is None:
        return None, f"""HUNTERELITE {VERSION}

CA: {ca}

DEX pair verisi bulunamadi.

KARAR: GIRME / VERI BEKLE"""

    report = rugcheck(ca)
    result = calculate_score(pair, report)
    base = pair.get("baseToken") or {}
    name = base.get("name") or "Unknown"
    symbol = base.get("symbol") or "N/A"

    # Clone/impersonation check is also applied to manual CA analysis.
    clone_safe, clone_reason = clone_impersonation_guard(name, symbol, ca, pair)

    # Deep social analysis is intentionally manual-only so the fast radar is not slowed.
    social = deep_social_analysis(ca, pair, name, symbol)
    x = social["x"]
    reddit = social["reddit"]
    links = social["links"]

    if x.get("status") == "OK":
        x_status = f"{x.get('posts',0)} post / {x.get('engagement',0)} etkilesim"
    elif x.get("status") == "PUBLIC_WEB_OK":
        x_status = f"{x.get('posts',0)} dogrulanmis public X sonucu / etkilesim API'siz"
    else:
        x_status = f"DOGRULANAMADI ({x.get('status')})"
    if reddit.get("status") in ("OK", "PUBLIC_JSON_OK"):
        reddit_status = f"{reddit.get('posts',0)} post / score {reddit.get('score') or 0} / {reddit.get('comments') or 0} yorum"
    elif reddit.get("status") == "PUBLIC_WEB_OK":
        reddit_status = f"{reddit.get('posts',0)} public Reddit sonucu"
    else:
        reddit_status = f"DOGRULANAMADI ({reddit.get('status')})"

    age = result.get("age_hours")
    age_text = f"{age:.2f} saat" if age is not None else "N/A"

    general = manual_general_decision(result, social, clone_safe=clone_safe)

    text = f"""HUNTERELITE MANUEL DERIN ANALIZ

{name} ({symbol})
CA: {ca}

PIYASA
Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}
Pair yasi: {age_text}
5dk: {result["buys5"]} buy / {result["sells5"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}
1sa fiyat: {percent(result["price1h"])}
6sa fiyat: {percent(result["price6h"])}

RUG / HOLDER
RugCheck: {"ALINDI" if report else "VERI YOK"}
Top-1: {percent(result["top1"])}
Top-5: {percent(result["top5"])}
Top-10: {percent(result["top10"])}
Mint authority: {authority_text(result["mint"])}
Freeze authority: {authority_text(result["freeze"])}
LP Kilit/Burn: {percent(result.get("lp_locked_pct")) if result.get("lp_locked_pct") is not None else ("N/A - bonding curve" if not result.get("has_lp_market") else "DOGRULANAMADI")}
Clone Guard: {"TEMIZ" if clone_safe else "BLOCK"}
Clone Notu: {clone_reason or "-"}

SOSYAL VARLIK
X linki: {"VAR" if links["x"] else "YOK"}
Telegram: {"VAR" if links["telegram"] else "YOK"}
Reddit linki: {"VAR" if links["reddit"] else "YOK"}
Website: {"VAR" if links["website"] else "YOK"}
Social Presence: {social["presence_score"]}/100

CANLI SOSYAL
X: {x_status}
Reddit: {reddit_status}
Public Web: {social.get("web_mentions",{}).get("mentions",0)} sonuc / kaynaklar: {", ".join(social.get("web_mentions",{}).get("domains",[])[:4]) or "-"}
Buyuk hesap paylasimi: {_fmt_major_accounts(x.get("major_accounts") or [])}
Social Catalyst: {social["catalyst"]}
Viral Durum: {social["viral_label"]} ({social["viral_score"]}/100)

SKOR
Risk/Quality Score: {result["score"]}/100
Genel Karar: {general}

🔗 Axiom: https://axiom.trade/meme/{ca}

NOT
X_BEARER_TOKEN yoksa X post/etkilesim ve buyuk hesap verisi DOGRULANAMADI yazar; tahmin edilmez.
Reddit icin REDDIT_ACCESS_TOKEN veya REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET gerekir.
Eksik sosyal veri pozitif kabul edilmez."""

    if result["risks"]:
        text += "\n\nRISKLER\n" + "".join(f"- {r}\n" for r in result["risks"][:8])

    return result, text


def basic_signal_safe(result):
    if not result:
        return False
    if result["signals"]["rug"] or result["signals"]["honeypot"] or result["signals"].get("unknown"):
        return False
    if result["signals"].get("bundler") or result["signals"].get("insider") or result["signals"].get("sniper"):
        return False
    if result["mint"] is True or result["freeze"] is True:
        return False
    if result.get("top1") is not None and result["top1"] >= TOP1_MAX_PCT:
        return False
    lp_pct = result.get("lp_locked_pct")
    if result.get("has_lp_market") and (lp_pct is None or lp_pct < LP_LOCK_MIN_PCT):
        return False
    age = result.get("age_hours")
    if age is None or age < (MIN_PAIR_AGE_MINUTES / 60.0):
        return False
    if result["mc"] is None or not (MC_MIN <= result["mc"] <= MC_MAX):
        return False
    if result["liq"] is None or result["liq"] < MIN_LIQUIDITY:
        return False
    if result["top10"] is not None and result["top10"] >= HOLDER_TOP10_MAX:
        return False
    if result["top10"] is None and not ALLOW_MISSING_HOLDER:
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
    if p5 is not None and TREND_MIN_PRICE5_PCT <= p5 <= TREND_MAX_PRICE5_PCT:
        confirmations += 1

    # V11.39: one confirmation let almost every scanned pair through — that's
    # not a trend check, it's a coin flip. Require at least 2 of the 4 signals
    # to agree before calling a trend confirmed. Tunable via env if too strict.
    # Hard rug/honeypot/authority/crash gates are evaluated separately and remain active.
    return confirmations >= TREND_MIN_CONFIRMATIONS

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
    # V11.38.1 FINAL GATE RECOVERY: safety + confirmed trend/momentum +
    # confirmed liquidity are already enforced by the caller. Do not kill a
    # late-stage candidate again with stricter duplicate activity thresholds.
    if result["score"] + momentum < SIGNAL_SCORE:
        return False
    if result["mc"] > EARLY_MC_MAX:
        return False

    buys, sells = result["buys5"], result["sells5"]
    if buys < WATCH_MIN_BUYS_5M:
        return False
    # V11.58: was a hardcoded 1.10 that didn't match SIGNAL_MIN_BUY_SELL_RATIO
    # (0.95) defined for exactly this check — the mismatch silently made this
    # the strictest gate in the whole pipeline while diagnostics reported
    # against the looser, intended constant. Aligned so what's enforced and
    # what's reported are the same number.
    if sells > 0 and buys < sells * SIGNAL_MIN_BUY_SELL_RATIO:
        return False
    if result["vol5"] is not None and result["vol5"] < WATCH_MIN_VOL_5M:
        return False

    return True


def filter_fail_reason(result, previous=None, momentum=0, for_signal=False):
    """Return the main reason a candidate failed. Used only for diagnostics."""
    if not result:
        return "basic_fail"

    sig = result.get("signals") or {}
    if sig.get("rug") or sig.get("honeypot") or sig.get("bundler") or sig.get("insider") or sig.get("sniper"):
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
    if top10 is not None and top10 >= HOLDER_TOP10_MAX:
        return "holder_fail"
    if top10 is None and not ALLOW_MISSING_HOLDER:
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
    """Age-aware crash diagnostics matching crash_guard(). Also blocks the
    opposite failure: a token already up 60%+ in the last hour, or one whose
    5-minute price is already rolling over while 1h is still strongly
    positive — both mean we'd be signaling at/after the top, not before it."""
    if not result:
        return False, "unknown"

    p1 = result.get("price1h")
    p5 = result.get("price5")
    p6 = result.get("price6h")
    p24 = result.get("price24h")
    age = result.get("age_hours")

    if age is not None and age > MAX_PAIR_AGE_HOURS:
        return False, "age"

    drawdown = result.get("drawdown_from_peak_pct")
    if drawdown is not None and drawdown >= PEAK_DRAWDOWN_MAX_PCT:
        return False, "peak_drawdown"

    if p6 is not None and p6 >= STALE_SPIKE_MIN_P6_PCT:
        if p1 is None or p1 < p6 * STALE_SPIKE_RETRACE_RATIO:
            return False, "stale_spike"

    if p1 is not None and p1 >= LATE_ENTRY_MAX_PRICE1H_PCT:
        return False, "late_pump"
    if (p1 is not None and p5 is not None
            and p1 >= LATE_ENTRY_REVERSAL_PRICE1H_PCT
            and p5 <= LATE_ENTRY_REVERSAL_PRICE5_PCT):
        return False, "topping"

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


def social_signal_bonus(ca, name, symbol):
    """
    X (Twitter) engagement bonus for a candidate that already cleared every
    safety gate on its own. Returns (bonus_points, label, raw_snapshot).
    Never called for candidates that haven't already passed safety — this
    keeps X API usage to a handful of calls per scan cycle instead of 80.
    """
    if not X_BEARER_TOKEN:
        return 0, "X_KEY_YOK", None
    try:
        snap = _x_recent_social(ca, name, symbol)
    except Exception as e:
        print("SOCIAL BONUS ERROR:", repr(e), flush=True)
        return 0, "X_ERROR", None

    if snap.get("status") != "OK":
        return 0, snap.get("status", "X_ERROR"), snap

    posts = snap.get("posts", 0)
    engagement = snap.get("engagement", 0)
    major_posts = snap.get("major_posts", 0)
    recent_min = snap.get("recent_minutes")

    bonus = 0
    if posts >= 3:
        bonus += 2
    if posts >= 10:
        bonus += 2
    if engagement >= SOCIAL_VIRAL_ENGAGEMENT:
        bonus += 3
    if engagement >= SOCIAL_VIRAL_ENGAGEMENT * 3:
        bonus += 2
    if major_posts >= 1:
        bonus += 3
    if recent_min is not None and recent_min <= 15:
        bonus += 2

    bonus = min(bonus, SOCIAL_BONUS_MAX)
    if bonus >= 8:
        label = "X VIRAL"
    elif bonus >= 4:
        label = "X AKTIF"
    elif posts > 0:
        label = "X DUSUK"
    else:
        label = "X SESSIZ"
    return bonus, label, snap


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
    "momentum_pass": 0, "liq_confirmed": 0, "liq_wait": 0, "liq_drop_block": 0, "clone_block": 0, "signal_gate_pass": 0,
            }

            stats["unique_new"] = unique_new
            stats["repeat"] = repeat

            birdeye_liq_attempts = 0
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

                    # V11.49 PEAK-DRAWDOWN GUARD: a token can spike and crash
                    # entirely within its first few minutes, before it's even
                    # old enough to be eligible for SIGNAL (MIN_PAIR_AGE_MINUTES).
                    # By the time it clears that age gate, price1h/price5 can
                    # look calm again even though it already round-tripped
                    # -80%+ from a peak we never directly saw in a single
                    # snapshot. Track the highest MC ever observed for this CA
                    # (persisted in token_states) and block if current MC has
                    # collapsed from it, regardless of what the delta metrics say.
                    with state_lock:
                        _prev_for_peak = token_states.get(ca)
                    _prior_peak_mc = num((_prev_for_peak or {}).get("peak_mc")) or 0.0
                    _cur_mc = num(result.get("mc")) or 0.0
                    peak_mc = max(_prior_peak_mc, _cur_mc)
                    result["peak_mc"] = peak_mc
                    if peak_mc > 0 and _cur_mc > 0:
                        result["drawdown_from_peak_pct"] = max(0.0, (peak_mc - _cur_mc) / peak_mc * 100.0)
                    else:
                        result["drawdown_from_peak_pct"] = None

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

                    # V11.36.4 LIQ RECOVERY: before paid/keyed fallbacks, retry all
                    # known Solana pairs and accept only explicit USD liquidity.
                    if mc_ok and liq is None:
                        recovered_liq = recover_dex_liquidity(ca, pair)
                        if recovered_liq is not None:
                            liq = recovered_liq
                            result["liq"] = recovered_liq
                            result["liq_source"] = "DEX_RECOVERY"
                            stats["liq_fallback_ok"] += 1

                    # ONE SHOT RECOVERY: if DexScreener still has no explicit liquidity,
                    # try GeckoTerminal token-pools before spending Birdeye quota.
                    if mc_ok and liq is None:
                        gecko_liq = recover_gecko_liquidity(ca)
                        if gecko_liq is not None:
                            liq = gecko_liq
                            result["liq"] = gecko_liq
                            result["liq_source"] = "GECKO_RECOVERY"
                            stats["liq_fallback_ok"] += 1

                    # If both keyless sources are missing, Birdeye remains the last fallback.
                    if mc_ok and liq is None and BIRDEYE_API_KEY and BIRDEYE_MARKET_FALLBACK and birdeye_liq_attempts < 4:
                        birdeye_liq_attempts += 1
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

                    holder_ok = liq_ok and (
        (top10 is None and ALLOW_MISSING_HOLDER)
        or (top10 is not None and top10 < HOLDER_TOP10_MAX)
    )
                    if holder_ok: stats["holder_pass"] += 1

                    sig = result.get("signals") or {}

                    rug_ok = (holder_ok
                              and not sig.get("rug") and not sig.get("honeypot") and not sig.get("unknown")
                              and not sig.get("bundler") and not sig.get("insider") and not sig.get("sniper"))
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
                        elif crash_reason == "late_pump":
                            stats["late_pump_fail"] = stats.get("late_pump_fail", 0) + 1
                        elif crash_reason == "topping":
                            stats["topping_fail"] = stats.get("topping_fail", 0) + 1
                        elif crash_reason == "peak_drawdown":
                            stats["peak_drawdown_fail"] = stats.get("peak_drawdown_fail", 0) + 1
                        elif crash_reason == "stale_spike":
                            stats["stale_spike_fail"] = stats.get("stale_spike_fail", 0) + 1

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
                    if liq_confirmed:
                        stats["liq_confirmed"] += 1
                    elif old_metrics is None or num(old_metrics.get("liq")) is None or num(result.get("liq")) is None:
                        stats["liq_wait"] += 1
                    else:
                        stats["liq_drop_block"] += 1

                    # V11.37.2: WATCH can surface a safe early candidate immediately.
                    # SIGNAL still needs a previous snapshot so trend/liquidity can be compared.
                    watch_ok = watch_candidate(result) and (
                        old_metrics is None or liq_confirmed
                    )
                    signal_ok = (
                        old_metrics is not None
                        and seen_count >= 2
                        and liq_confirmed
                        and strong_signal(result, momentum, old_metrics)
                    )

                    # V11.57: only meaningful for candidates that already cleared
                    # SAFE+ACTIVITY+TREND+MOMENTUM — the earlier filter_fail_reason
                    # counters (mc_fail etc.) get dominated by the very first MC
                    # gate, drowning out what's actually blocking the last mile.
                    if momentum_ok and not signal_ok:
                        if seen_count < 2:
                            stats["final_seen_count_fail"] = stats.get("final_seen_count_fail", 0) + 1
                        elif not liq_confirmed:
                            stats["final_liq_confirm_fail"] = stats.get("final_liq_confirm_fail", 0) + 1
                        else:
                            _liq_drain_safe2, _, _ = liquidity_drain_detail(old_metrics, result)
                            buys, sells = result.get("buys5", 0), result.get("sells5", 0)
                            vol5 = result.get("vol5")
                            if not _liq_drain_safe2:
                                stats["final_liq_drain_fail"] = stats.get("final_liq_drain_fail", 0) + 1
                            elif result.get("score", 0) + momentum < SIGNAL_SCORE:
                                stats["final_score_fail"] = stats.get("final_score_fail", 0) + 1
                            elif result.get("mc") is not None and result["mc"] > EARLY_MC_MAX:
                                stats["final_mc_cap_fail"] = stats.get("final_mc_cap_fail", 0) + 1
                            elif buys < SIGNAL_MIN_BUYS_5M or (sells > 0 and buys < sells * SIGNAL_MIN_BUY_SELL_RATIO):
                                stats["final_buy_ratio_fail"] = stats.get("final_buy_ratio_fail", 0) + 1
                            elif vol5 is not None and vol5 < SIGNAL_MIN_VOL_5M:
                                stats["final_volume_fail"] = stats.get("final_volume_fail", 0) + 1
                            else:
                                stats["final_other_fail"] = stats.get("final_other_fail", 0) + 1

                    if ca not in cancelled_this_scan and (not watch_ok):
                        reason = filter_fail_reason(result, old_metrics, momentum, for_signal=False)
                        stats[reason] = stats.get(reason, 0) + 1
                    elif seen_count >= TREND_CONFIRM_SCANS and not signal_ok:
                        reason = filter_fail_reason(result, old_metrics, momentum, for_signal=True)
                        stats[reason] = stats.get(reason, 0) + 1

                    base = pair.get("baseToken") or {}
                    name = base.get("name", "Unknown")
                    symbol = base.get("symbol", "N/A")

                    clone_safe = True
                    clone_reason = ""
                    if watch_ok or signal_ok:
                        clone_safe, clone_reason = clone_impersonation_guard(name, symbol, ca, pair)
                        if not clone_safe:
                            stats["clone_block"] += 1
                            watch_ok = False
                            signal_ok = False
                            result["clone_block"] = clone_reason
                            print(f"CLONE GUARD BLOCK: {name} ({symbol}) {ca} | {clone_reason}", flush=True)

                    if signal_ok:
                        stats["signal_gate_pass"] += 1

                    # TOKEN GATE DIAGNOSTIC: show exactly why a late-stage candidate
                    # did or did not reach WATCH/SIGNAL. No thresholds are changed.
                    if safety_ok and (activity_ok or trend_ok or momentum_ok):
                        reasons = []
                        if not activity_ok: reasons.append("ACTIVITY")
                        if not trend_ok: reasons.append("TREND")
                        if not momentum_ok: reasons.append("MOMENTUM")
                        if not liq_confirmed: reasons.append("LIQ_CONFIRM")
                        if not clone_safe: reasons.append("CLONE")
                        if not liq_drain_safe: reasons.append("LIQ_DRAIN")
                        if not watch_ok and not signal_ok and not reasons:
                            reasons.append("DECISION_GATE")
                        print(
                            f"TOKEN_GATE | {ca} | {name} ({symbol}) | "
                            f"SAFE={int(bool(safety_ok))} ACT={int(bool(activity_ok))} "
                            f"TREND={int(bool(trend_ok))} MOM={int(bool(momentum_ok))} "
                            f"LIQ_OK={int(bool(liq_confirmed))} CLONE={int(not bool(clone_safe))} "
                            f"LIQ_DRAIN_OK={int(bool(liq_drain_safe))} "
                            f"WATCH={int(bool(watch_ok))} SIGNAL={int(bool(signal_ok))} | "
                            f"BLOCK={','.join(reasons) if reasons else 'NONE'}",
                            flush=True
                        )

                    # V11.48 DUPLICATE SIGNAL GUARD: token_states is written once
                    # at the end of each candidate's loop iteration. If a redeploy
                    # kills the container between firing a SIGNAL and that write
                    # landing, the next boot sees stage="NEW" again for a token we
                    # already alerted on, and re-signals it. signal_perf is written
                    # synchronously the instant a signal fires (record_signal_entry)
                    # and lives on the persistent volume, so it's a more reliable
                    # independent check — use it as a belt-and-suspenders guard.
                    with signal_perf_lock:
                        _already_signaled_recently = (
                            ca in signal_perf
                            and (time.time() - signal_perf[ca].get("signal_time", 0)) < WATCH_REPEAT_COOLDOWN
                        )

                    if signal_ok and stage != "SIGNAL" and _already_signaled_recently:
                        # Resync state without re-sending: we already alerted on this
                        # CA (per the persisted signal_perf record) but token_states
                        # lost track of that, likely due to a redeploy timing gap.
                        new_stage = "SIGNAL"

                    if (
                        signal_ok
                        and stage != "SIGNAL"
                        and not _already_signaled_recently
                    ):
                        new_stage = "SIGNAL"
                        stats["signal"] += 1
                        record_signal_entry(ca, name, symbol, pair)
                        social_bonus, social_label, social_snap = social_signal_bonus(ca, name, symbol)
                        final_score = min(100, result["score"] + momentum + social_bonus)
                        age_text = f'{result["age_hours"]:.1f} saat' if result["age_hours"] is not None else "N/A"

                        social_line = f"X Sosyal: {social_label}"
                        if social_snap and social_snap.get("status") == "OK":
                            social_line += f" ({social_snap.get('posts',0)} post, {social_snap.get('engagement',0)} etkilesim)"
                            majors = social_snap.get("major_accounts") or []
                            if majors:
                                top = majors[0]
                                social_line += f" | buyuk hesap: @{top.get('username')} ({top.get('followers',0):,} takipci)"

                        message = f"""HUNTERELITE EARLY SIGNAL

{name} ({symbol})
CA: {ca}

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

5dk: {result["buys5"]} buy / {result["sells5"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}

Top-1: {percent(result["top1"])}
Top-10: {percent(result["top10"])}
LP Kilit/Burn: {percent(result.get("lp_locked_pct")) if result.get("lp_locked_pct") is not None else ("N/A - bonding curve" if not result.get("has_lp_market") else "DOGRULANAMADI")}
Zirveden Dusus: {percent(result.get("drawdown_from_peak_pct")) if result.get("drawdown_from_peak_pct") is not None else "N/A (ilk gorusme)"}
Likidite Guard: {"PASSED" if liq_drain_safe else "BLOCKED"}
Likidite Degisim: -{liq_drop_pct:.1f}%

{social_line}

Risk Score: {result["score"]}/100
Momentum: +{momentum}
Sosyal Bonus: +{social_bonus}
1sa fiyat: {percent(result["price1h"])}
6sa fiyat: {percent(result["price6h"])}
Pair yasi: {age_text}
Final Score: {final_score}/100

KARAR: GIR
POTANSIYEL: {potential_label(result, momentum)}

🔗 Axiom: https://axiom.trade/meme/{ca}

UYARI: Potansiyel etiketi garanti degildir.
Axiom'da son kontrolunu yap."""

                    elif watch_ok and stage == "NEW":
                        # V11.36.5: WATCH stays internal. Telegram receives only final GIR signals.
                        new_stage = "WATCH"
                        stats["watch"] += 1
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
                            "peak_mc": peak_mc,
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
                    f"RADAR {VERSION} | total={stats.get('radar',0)} "
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
                    f"LIQ RECOVERY: recovered={stats.get('liq_fallback_ok',0)} "
                    f"missing_after_recovery={stats.get('liq_fallback_missing',0)}\n"
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
                    f"H24_FAIL={stats.get('h24_fail',0)} "
                    f"LATE_PUMP_FAIL={stats.get('late_pump_fail',0)} "
                    f"TOPPING_FAIL={stats.get('topping_fail',0)} "
                    f"PEAK_DD_FAIL={stats.get('peak_drawdown_fail',0)} "
                    f"STALE_SPIKE_FAIL={stats.get('stale_spike_fail',0)}\n"
                    f"AFTER SAFE: SCORE={stats.get('score_pass',0)} "
                    f"> ACTIVITY={stats.get('activity_pass',0)} "
                    f"> TREND={stats.get('trend_pass',0)} "
                    f"> MOMENTUM={stats.get('momentum_pass',0)}\n"
                    f"WATCH={stats.get('watch',0)} SIGNAL={stats.get('signal',0)} "
                    f"pair_missing={stats.get('pair_yok',0)} stale_pair={stats.get('stale_pair',0)}\n"
                    f"FINAL GATE BREAKDOWN (adaylar SAFE+ACTIVITY+TREND+MOMENTUM gectikten sonra): "
                    f"SEEN_COUNT={stats.get('final_seen_count_fail',0)} "
                    f"LIQ_CONFIRM={stats.get('final_liq_confirm_fail',0)} "
                    f"LIQ_DRAIN={stats.get('final_liq_drain_fail',0)} "
                    f"SCORE={stats.get('final_score_fail',0)} "
                    f"MC_CAP={stats.get('final_mc_cap_fail',0)} "
                    f"BUY_RATIO={stats.get('final_buy_ratio_fail',0)} "
                    f"VOLUME={stats.get('final_volume_fail',0)} "
                    f"OTHER={stats.get('final_other_fail',0)}\n"
                    f"SIGNAL GATES: LIQ_OK={stats.get('liq_confirmed',0)} "
                    f"LIQ_WAIT={stats.get('liq_wait',0)} LIQ_DROP_BLOCK={stats.get('liq_drop_block',0)} "
                    f"CLONE_BLOCK={stats.get('clone_block',0)} FINAL_GATE={stats.get('signal_gate_pass',0)}\n"
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
        send(chat_id, f"""✅ HunterElite {VERSION} ONLINE

🎯 Early Hunter: AKTİF
🎯 Market bölgesi: {money(MC_MIN)}–{money(EARLY_MC_MAX)}
🧪 RugCheck: AKTİF
📡 Eksik veri koruması: AKTİF
🚨 Otomatik sinyal: AKTİF

CA göndererek manuel analiz yapabilirsin.

Komutlar:
/ping
/status
/signal_on
/signal_off
/signal_test
/help""")
        return

    if command == "/ping":
        send(chat_id, f"🏓 PONG — HunterElite {VERSION} ONLINE")
        return

    if command == "/status":
        active = int(chat_id) in signal_chats
        send(chat_id, f"""✅ HunterElite {VERSION} ONLINE

🔎 Manuel analiz: AKTİF (SOSYAL DEEP)
🚨 Early Hunter: {"AKTİF" if active else "KAPALI"}
⏱ Tarama: {SCAN_INTERVAL} sn
RURU Core: V11.34 ORIJINAL SINYAL ESikleri
Liquidity Drain Guard: AKTIF (hard %{LIQ_DRAIN_HARD_PCT:.0f})
🎯 Watch Score: {WATCH_SCORE}
🔥 Signal Score: {SIGNAL_SCORE}
📈 Trend teyidi: {TREND_CONFIRM_SCANS} tarama / min momentum {MIN_MOMENTUM_SIGNAL}
📡 Radar: {"SOLANA WS + BIRDEYE + GECKO + RAYDIUM + METEORA + DEX" if BIRDEYE_API_KEY else "SOLANA WS + GECKO + RAYDIUM + METEORA + DEX"}
🟢 Birdeye API: {"BAĞLI" if BIRDEYE_API_KEY else "KEY YOK"}
🐦 X Sosyal Bonus: {"AKTİF" if X_BEARER_TOKEN else "KEY YOK (bonus 0 kalır, sinyali bloklamaz)"}
💾 Kalıcı Hafıza: {"AKTİF (" + DATA_DIR + ")" if DATA_DIR != "/tmp" else "PASİF (/tmp — her deploy'da sıfırlanır, Volume ekleyin)"}
⏱ Birdeye yenileme: {BIRDEYE_POLL_INTERVAL} sn
💧 Min Likidite: {money(MIN_LIQUIDITY)}
📊 Market: {money(MC_MIN)}–{money(EARLY_MC_MAX)} öncelikli
💎 100X potansiyel filtresi: AKTİF\n📡 /radar teşhisi: AKTİF\n🧩 Single Engine: AKTİF""")
        return

    if command == "/signal_on":
        signal_chats.add(int(chat_id))
        send(chat_id, "🚨 HunterElite otomatik sinyal AKTİF.\nEarly Hunter taraması başladı.")
        return

    if command == "/signal_off":
        signal_chats.discard(int(chat_id))
        send(chat_id, "🔕 Otomatik sinyal KAPALI.")
        return

    if command == "/signal_test":
        signal_chats.add(int(chat_id))
        send(chat_id, f"""✅ HUNTERELITE TEST SİNYALİ

{VERSION}

📡 Telegram kanalı: ÇALIŞIYOR
🚨 Otomatik sinyal: AKTİF
🔎 Manuel analiz: AKTİF (SOSYAL DEEP)
🔥 Early Hunter: AKTİF

Gerçek aday taraması başladı.""")
        return

    if command == "/radar":
        with radar_stats_lock:
            s = dict(radar_stats)

        updated = s.get("updated", 0)
        age = int(max(0, time.time() - updated)) if updated else None
        age_text = f"{age} sn önce" if age is not None else "henüz ilk tur tamamlanmadı"

        send(chat_id, f"""📡 HUNTERELITE RADAR TEST

Sürüm: {VERSION}
Son tarama: {age_text}

🔎 Radar adayı: {s.get("radar", 0)}
✅ İşlenen: {s.get("processed", 0)}
❌ Pair yok: {s.get("pair_yok", 0)}

Filtreye takılanlar:
• MC: {s.get("mc_fail", 0)}
• Likidite: {s.get("liq_fail", 0)}
• Holder: {s.get("holder_fail", 0)}
• Mint/Freeze: {s.get("authority_fail", 0)}
• Rug/Honeypot: {s.get("rug_fail", 0)}
• Score: {s.get("score_fail", 0)}
• Buy baskısı: {s.get("buy_fail", 0)}
• Hacim: {s.get("volume_fail", 0)}
• Trend: {s.get("trend_fail", 0)}
• Momentum: {s.get("momentum_fail", 0)}

👀 WATCH: {s.get("watch", 0)}
🚨 SIGNAL: {s.get("signal", 0)}

Bu ekran teşhis içindir; sinyal garantisi değildir.""")
        return

    if command == "/performance":
        perf = signal_perf_summary()
        with signal_perf_lock:
            open_count = len(signal_perf)

        def fmt(label):
            row = perf.get(label) or {}
            if not row.get("count"):
                return f"• {label}: henüz veri yok"
            return (
                f"• {label}: {row['count']} sinyal | "
                f"ort. {row['avg']}% | kazanan {row['win_rate']}%"
            )

        send(chat_id, f"""📊 HUNTERELITE SIGNAL PERFORMANCE

Gerçek sonuçlar (sinyal sonrası fiyat takibi):

{fmt("1h")}
{fmt("6h")}
{fmt("24h")}

🔄 Takip edilen açık sinyal: {open_count}

Bu veriler tahmini değil, sinyal anındaki fiyata göre ölçülen gerçek değişimdir.""")
        return

    if command == "/help":
        send(
            chat_id,
            "HunterElite V11.3 EARLY 100X RADAR\n\n"
            "CA gönder → derin manuel analiz (rug + holder + clone + sosyal + viral)\n\n"
            "/ping\n/status\n/signal_on\n/signal_off\n/signal_test\n/radar\n/performance\n/start"
        )
        return

    ca = text
    if not SOL_CA.match(ca):
        matches = re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text)
        ca = matches[0] if matches else ""

    if ca and SOL_CA.match(ca):
        send(chat_id, "🔎 Token analiz ediliyor...")
        try:
            _, report = analyse(ca)
            send(chat_id, report)
        except Exception as e:
            print("ANALYSIS ERROR:", repr(e), flush=True)
            send(chat_id, "❌ Analiz sırasında veri hatası oluştu.")
        return

    send(chat_id, "Solana kontrat adresini gönder veya /help yaz.")

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

Early Entry: MC {money(MC_MIN)}+, Liquidity {money(MIN_LIQUIDITY)}+, Top10 <{HOLDER_TOP10_MAX:.0f}%\nHard rug/honeypot and authority checks remain active.\n\nSTATE DECISION LOCK + CENTRAL OUTPUT + LIQ FALLBACK: ACTIVE.\nAutomatic signal engine is running.""")


def startup():
    print(f"HUNTERELITE {VERSION} ONLINE", flush=True)
    print(f"TELEGRAM POLLING: {'ON' if POLLING_ENABLED else 'OFF - AUTO SIGNAL MODE'}", flush=True)
    print("EARLY HUNTER ACTIVE", flush=True)
    print(f"SCAN INTERVAL: {SCAN_INTERVAL}s", flush=True)
    print(f"EARLY ENTRY FILTERS: MC>={MC_MIN}, LIQ>={MIN_LIQUIDITY}, TOP10<90%", flush=True)
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
    load_signal_perf()
    threading.Thread(target=health_server, daemon=True).start()
    startup()
    threading.Thread(target=solana_ws_listener, daemon=True).start()
    threading.Thread(target=auto_scanner, daemon=True).start()
    threading.Thread(target=signal_performance_tracker, daemon=True).start()
    threading.Thread(target=rug_watchdog, daemon=True).start()
    time.sleep(2)
    startup_notify()

    if POLLING_ENABLED:
        polling()
    else:
        # Keep the process alive while the scanner thread runs.
        # This mode eliminates Telegram getUpdates 409 conflicts.
        while True:
            time.sleep(3600)
