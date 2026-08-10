import os
import re
import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VERSION = "V13.5 FRESH RADAR MIX"
LIQ_CACHE = {}
LIQ_CACHE_TTL = 300
TOKEN = os.getenv("TOKEN", "").strip()
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "").strip()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").strip()
HOLDER_RPC_CACHE = {}
HOLDER_RPC_CACHE_TTL = 900

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
WATCH_SCORE = 60
SIGNAL_SCORE = 75

# V12.6: runner continuation / acceleration (does NOT bypass hard safety gates)
RUNNER_MAX_MC = 750000.0
RUNNER_TTL_SEC = 3600
RUNNER_MIN_SCORE = 72
RUNNER_MIN_LIQ = 1500.0
RUNNER_MIN_VOL_LIQ = 0.75
RUNNER_MIN_BUY_SELL = 1.20
RUNNER_MIN_PRICE5 = 2.0
RUNNER_MAX_PRICE5 = 80.0
RUNNER_STATE = {}
FINAL_GATE_REJECTS = {}
QUALITY_GATE_DETAILS = {}
WATCH_DIAG = {}
HOLDER_HARD_MAX = 82.0
SCAN_INTERVAL = 30

# V11.57 QUALITY MODE
# Target: roughly 10-20 high-quality alerts/day when the market provides them.
# Never force a quota by lowering safety/quality.
QUALITY_SEND_WATCH = False
QUALITY_DAILY_SIGNAL_CAP = 50
QUALITY_SIGNAL_MIN_GAP_SEC = 300    # 5 minutes; quality gates still mandatory
QUALITY_MIN_SCORE = 70
QUALITY_MAX_TOP10 = 55.0
QUALITY_MIN_LIQ = 2000.0
QUALITY_MIN_BUYS_5M = 30
QUALITY_MIN_VOL_5M = 3000.0
QUALITY_MIN_BUY_SELL_RATIO = 1.35
QUALITY_MIN_PRICE5 = -5.0
QUALITY_MAX_PRICE5 = 80.0

_quality_day = None
_quality_signal_count = 0
_quality_last_signal_at = 0.0

def quality_signal_slot_available(now):
    global _quality_day, _quality_signal_count, _quality_last_signal_at
    # Turkey local day (UTC+3); only a delivery cap, not a market-data assumption.
    day = time.strftime("%Y-%m-%d", time.gmtime(now + 3 * 3600))
    if _quality_day != day:
        _quality_day = day
        _quality_signal_count = 0
        _quality_last_signal_at = 0.0
    if _quality_signal_count >= QUALITY_DAILY_SIGNAL_CAP:
        return False
    if _quality_last_signal_at and now - _quality_last_signal_at < QUALITY_SIGNAL_MIN_GAP_SEC:
        return False
    return True


def hard_rug_gate(result):
    """V12 fail-closed gate: critical security uncertainty can never be outscored."""
    report = result.get("report")
    if not isinstance(report, dict):
        return False, "RUGCHECK_MISSING"
    top10 = num(result.get("top10"))
    if top10 is None or bool(result.get("holder_unreliable")):
        return False, "HOLDER_UNVERIFIED"
    if top10 < 1.0:
        return False, "HOLDER_IMPLAUSIBLE"
    if top10 > QUALITY_MAX_TOP10:
        return False, "HOLDER_CONCENTRATION"
    # V12.8: "unknown" authority data is uncertainty, not proof of danger.
    # Explicitly active mint/freeze authority remains a HARD reject.
    if result.get("mint") is True:
        return False, "MINT_ACTIVE"
    if result.get("freeze") is True:
        return False, "FREEZE_ACTIVE"

    critical_terms = ("honeypot","rug pull","rugpull","bundler","bundle","insider",
                      "sniper","blacklist","cannot sell","sell blocked")
    for risk in report.get("risks") or []:
        if not isinstance(risk, dict):
            continue
        combined = f"{risk.get('name','')} {risk.get('description','')} {risk.get('value','')}".lower()
        level = str(risk.get("level") or risk.get("severity") or "").lower()
        if level in ("critical","danger","high","error"):
            return False, "RUG_HIGH_RISK"
        if any(term in combined for term in critical_terms):
            if not any(neg in combined for neg in ("no ","not ","none","0%")):
                return False, "RUG_CRITICAL_TERM"
    for key in ("honeypot","isHoneypot","rugged","isRugged"):
        if report.get(key) is True:
            return False, key.upper()
    return True, "OK"




def _v126_num(v, default=0.0):
    try:
        return float(v if v is not None else default)
    except Exception:
        return float(default)

def _v126_metric(m, *names, default=0.0):
    for name in names:
        if isinstance(m, dict) and m.get(name) is not None:
            return _v126_num(m.get(name), default)
    return float(default)

def v126_runner_metrics(metrics):
    """Continuation score only. Never overrides rug/auth/holder/crash gates."""
    mc = _v126_metric(metrics, "market_cap", "mc")
    liq = _v126_metric(metrics, "liquidity", "liq")
    vol5 = _v126_metric(metrics, "volume_m5", "vol5", "volume5")
    buys = _v126_metric(metrics, "buys_m5", "buy5", "buys5")
    sells = _v126_metric(metrics, "sells_m5", "sell5", "sells5")
    p5 = _v126_metric(metrics, "price_change_m5", "price5", "price_m5")
    vl = (vol5 / liq) if liq > 0 else 0.0
    bs = buys / max(1.0, sells)
    return mc, liq, vol5, buys, sells, p5, vl, bs

def v126_runner_candidate(metrics, score):
    mc, liq, vol5, buys, sells, p5, vl, bs = v126_runner_metrics(metrics)
    return (
        10000.0 <= mc <= RUNNER_MAX_MC
        and liq >= RUNNER_MIN_LIQ
        and score >= RUNNER_MIN_SCORE
        and vl >= RUNNER_MIN_VOL_LIQ
        and bs >= RUNNER_MIN_BUY_SELL
        and RUNNER_MIN_PRICE5 <= p5 <= RUNNER_MAX_PRICE5
    )

def v126_track_runner(ca, metrics, score):
    """Tracks multi-scan expansion so one-candle pumps do not become signals."""
    now = time.time()
    mc, liq, vol5, buys, sells, p5, vl, bs = v126_runner_metrics(metrics)
    prev = RUNNER_STATE.get(ca)
    RUNNER_STATE[ca] = {"ts": now, "mc": mc, "vol5": vol5, "liq": liq}
    # prune
    for k, v in list(RUNNER_STATE.items()):
        if now - _v126_num(v.get("ts")) > RUNNER_TTL_SEC:
            RUNNER_STATE.pop(k, None)
    if not prev:
        return False, 0.0, 0.0
    mc_accel = ((mc / max(1.0, _v126_num(prev.get("mc")))) - 1.0) * 100.0
    vol_accel = ((vol5 / max(1.0, _v126_num(prev.get("vol5")))) - 1.0) * 100.0
    confirmed = v126_runner_candidate(metrics, score) and mc_accel >= 8.0 and vol_accel >= -15.0
    return confirmed, mc_accel, vol_accel

def v126_gate_reject(reason):
    reason = str(reason or "UNKNOWN")
    FINAL_GATE_REJECTS[reason] = FINAL_GATE_REJECTS.get(reason, 0) + 1
    return False

def final_gir_gate(result, old_metrics, seen_count, momentum, now):
    """
    V12.1 single authoritative GIR gate.
    No BREAKOUT/EARLY/STRONG path can bypass these checks.
    """
    if old_metrics is None:
        return False, "WARMUP"
    if seen_count < TREND_CONFIRM_SCANS:
        return False, "TREND_SCANS"
    if not trend_confirmed(old_metrics, result):
        return False, "TREND_NOT_CONFIRMED"
    if momentum < MIN_MOMENTUM_SIGNAL:
        return False, "MOMENTUM_LOW"

    top10 = num(result.get("top10"))
    if top10 is None or bool(result.get("holder_unreliable")):
        return False, "HOLDER_UNVERIFIED"
    if not (1.0 <= top10 <= QUALITY_MAX_TOP10):
        return False, "HOLDER_RANGE"

    rug_ok, rug_reason = hard_rug_gate(result)
    if not rug_ok:
        return False, rug_reason

    # V13 NO REPEAT: once a CA produced a real GÄ°R, never send it again.
    if result.get("ca") in SIGNALLED_CAS:
        return False, "ALREADY_SIGNALLED"

    # V13 DUMP / TOP-CHASE SHIELD
    _p5 = num(result.get("price5"))
    _rmc = num(result.get("runner_mc_accel"))
    _rvol = num(result.get("runner_vol_accel"))
    # V13.2 SMART MC TOLERANCE
    # Small temporary MC dips may pass only with strong volume + buy pressure.
    if _rmc is not None and _rmc <= -3.0:
        return False, "MC_ACCEL_NEGATIVE_HARD"
    if _rmc is not None and -3.0 < _rmc < 0:
        _buys = num(result.get("buys5")) or 0
        _sells = num(result.get("sells5")) or 0
        _buy_sell = _buys / max(_sells, 1)
        if _rvol is None or _rvol < 8.0 or _buy_sell < 1.50:
            return False, "MC_ACCEL_SOFT_FAIL"

    # V13.2 DYNAMIC PRICE GATE
    # Do not reject a strong runner only because its 5m candle is above +50%.
    # The faster the price has already moved, the stronger MC + volume acceleration
    # must be to avoid chasing a local top.
    if _p5 is not None:
        if _p5 > 80.0:
            return False, "PRICE_EXTREME"
        if _p5 >= 70.0 and (
            _rmc is None or _rmc < 15.0 or _rvol is None or _rvol < 10.0
        ):
            return False, "TOP_CHASE_70"
        if _p5 >= 50.0 and (
            _rmc is None or _rmc < 10.0 or _rvol is None or _rvol < 5.0
        ):
            return False, "TOP_CHASE_50"
        if _p5 >= 30.0 and _rvol is not None and _rvol <= 0:
            return False, "VOLUME_FADE"

    if not quality_signal_gate(result):
        return False, "QUALITY_GATE"

    if not quality_signal_slot_available(now):
        return False, "RATE_LIMIT"

    # V12.10 DIAGNOSTIC
    _runner_mc = result.get("runner_mc_accel")
    try:
        _runner_mc = float(_runner_mc) if _runner_mc is not None else None
    except (TypeError, ValueError):
        _runner_mc = None
    if _runner_mc is not None and _runner_mc <= -30.0:
        return False, "MC_ACCEL_CRITICAL"
    if _runner_mc is not None and _runner_mc <= -20.0:
        return False, "MC_ACCEL_NEGATIVE"
    return True, "PASSED"


def quality_signal_gate(result):
    top10 = num(result.get("top10"))
    liq = num(result.get("liq"))
    price5 = num(result.get("price5"))
    buys = num(result.get("buys5")) or 0
    sells = num(result.get("sells5")) or 0
    vol5 = num(result.get("vol5")) or 0
    score = num(result.get("score")) or 0

    if top10 is None or bool(result.get("holder_unreliable")):
        QUALITY_GATE_DETAILS["Q1"] = QUALITY_GATE_DETAILS.get("Q1", 0) + 1
        return False
    if top10 > QUALITY_MAX_TOP10:
        QUALITY_GATE_DETAILS["Q2"] = QUALITY_GATE_DETAILS.get("Q2", 0) + 1
        return False
    if liq is None or liq < QUALITY_MIN_LIQ:
        QUALITY_GATE_DETAILS["Q3"] = QUALITY_GATE_DETAILS.get("Q3", 0) + 1
        return False
    if score < QUALITY_MIN_SCORE:
        QUALITY_GATE_DETAILS["Q4"] = QUALITY_GATE_DETAILS.get("Q4", 0) + 1
        return False
    if buys < QUALITY_MIN_BUYS_5M:
        QUALITY_GATE_DETAILS["Q5"] = QUALITY_GATE_DETAILS.get("Q5", 0) + 1
        return False
    if vol5 < QUALITY_MIN_VOL_5M:
        QUALITY_GATE_DETAILS["Q6"] = QUALITY_GATE_DETAILS.get("Q6", 0) + 1
        return False
    if buys / max(sells, 1) < QUALITY_MIN_BUY_SELL_RATIO:
        QUALITY_GATE_DETAILS["Q7"] = QUALITY_GATE_DETAILS.get("Q7", 0) + 1
        return False
    if price5 is None or not (QUALITY_MIN_PRICE5 <= price5 <= QUALITY_MAX_PRICE5):
        QUALITY_GATE_DETAILS["Q8"] = QUALITY_GATE_DETAILS.get("Q8", 0) + 1
        return False
    # Avoid chasing a candle that has already expanded too far in a single 5m window.
    # A later confirmed scan can still qualify if activity remains healthy.
    if price5 > QUALITY_MAX_PRICE5:
        QUALITY_GATE_DETAILS["Q9"] = QUALITY_GATE_DETAILS.get("Q9", 0) + 1
        return False
    return True

BIRDEYE_POLL_INTERVAL = 180
BIRDEYE_LIMIT = 20
BIRDEYE_PAGES = 1
BIRDEYE_NEW_LISTING = "https://public-api.birdeye.so/defi/v2/tokens/new_listing"

WATCH_REPEAT_COOLDOWN = 21600
MAX_WATCH_DROP_5M = -10.0
MAX_SIGNAL_DROP_1H = -35.0
MAX_CRASH_DROP_6H = -35.0
MAX_CRASH_DROP_24H = -55.0

MIN_MOMENTUM_SIGNAL = 15
MIN_MC_GROWTH = 1.005
MAX_PAIR_AGE_HOURS = 12.0
TREND_CONFIRM_SCANS = 2

WATCH_MIN_BUYS_5M = 12
WATCH_MIN_VOL_5M = 1000
SIGNAL_MIN_BUYS_5M = 20
SIGNAL_MIN_BUY_SELL_RATIO = 1.25
SIGNAL_MIN_VOL_5M = 2000
MIN_VOL_GROWTH = 1.00

STATE_FILE = "/tmp/hunterelite_v11_2_state.json"

if not TOKEN:
    raise RuntimeError("Railway TOKEN variable bulunamadi!")

TG_API = f"https://api.telegram.org/bot{TOKEN}"
SOL_CA = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

signal_chats = set()
token_states = {}
SIGNALLED_CAS = set()
state_lock = threading.Lock()
birdeye_lock = threading.Lock()
birdeye_cache = []
birdeye_last_fetch = 0.0
birdeye_last_error = ""
birdeye_last_error_body = ""
birdeye_cooldown_until = 0
BIRDEYE_COOLDOWN_SECONDS = 3600

GECKO_POLL_INTERVAL = 60
GECKO_PAGES = 3
GECKO_TARGET = 60
gecko_cache = []
gecko_last_fetch = 0
gecko_last_error = ""
gecko_fail_count = 0
gecko_next_retry = 0
gecko_last_status = "INIT"
gecko_lock = threading.Lock()
gecko_liq_cache = {}
GECKO_LIQ_CACHE_TTL = 300
birdeye_listing_liq = {}

radar_stats_lock = threading.Lock()
last_diag_send = 0.0
discovery_seen = {}
candidate_sources = {}
discovery_seen_lock = threading.Lock()
DISCOVERY_MEMORY_SECONDS = 21600
RADAR_RAW_LIMIT = 240
RADAR_TARGET = 80
BIRDEYE_TARGET = 80
DEX_TARGET = 20
DEX_RESERVED_SLOTS = 20
GECKO_MAX_SELECTED = 60
MAX_REPEAT_PER_SCAN = 20
FRESH_PAIR_MAX_HOURS = 6.0

VIRAL_RADAR_ENABLED = True
VIRAL_SCORE_BONUS_MAX = 12

radar_stats = {
    "updated": 0,
    "radar": 0,
    "processed": 0,
    "pair_yok": 0, "stale_pair": 0, "viral_hot": 0, "viral_rising": 0, "h1_fail_values": [], "prepump": 0, "prepump_safe": 0, "src_birdeye": 0, "src_gecko": 0, "src_dex": 0, "src_birdeye_stale": 0, "src_gecko_stale": 0, "src_dex_stale": 0, "src_birdeye_safe": 0, "src_gecko_safe": 0, "src_dex_safe": 0,
                "holder_unreliable": 0, "safe_score_samples": [], "score_fail_samples": [],
    "basic_fail": 0,
    "crash_fail": 0,
    "watch": 0,
    "signal": 0, "breakout": 0, "strong_gir": 0, "decision_izle": 0,
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
    "liq_pass": 0, "liq_missing": 0, "liq_0_200": 0, "liq_200_500": 0, "liq_500_800": 0, "liq_800_plus": 0, "liq_fallback_ok": 0, "liq_fallback_missing": 0, "liq_gecko_ok": 0, "liq_gecko_missing": 0, "holder_pass": 0, "holder_missing": 0, "holder_50_60": 0, "holder_60_70": 0, "holder_70_82": 0, "holder_82_plus": 0, "safety_pass": 0, "rug_ok": 0, "auth_ok": 0, "crash_ok": 0, "age_fail": 0, "h1_fail": 0, "h6_fail": 0, "h24_fail": 0,
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
                for _ca, _st in data.items():
                    if isinstance(_st, dict) and (_st.get("ever_signalled") or _st.get("stage") == "SIGNAL"):
                        SIGNALLED_CAS.add(_ca)
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


def rpc_json(method, params, timeout=10):
    """Minimal Solana JSON-RPC POST helper; read-only holder verification only."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }).encode("utf-8")
    req = urllib.request.Request(
        SOLANA_RPC_URL,
        data=payload,
        method="POST",
        headers={
            "User-Agent": "HunterElite-V11.57",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    if not isinstance(data, dict) or data.get("error"):
        raise RuntimeError(f"RPC {method} error: {data.get('error') if isinstance(data, dict) else data}")
    return data.get("result")


def _protocol_holder_accounts(report):
    """
    Build a conservative exclusion set for protocol/AMM inventory accounts.
    RugCheck reports markets + knownAccounts; those are not ordinary user wallets.
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
            blob = f"{meta.get('name','')} {meta.get('type','')}".lower() if isinstance(meta, dict) else str(meta).lower()
            if any(word in blob for word in ("amm", "pool", "dex", "market", "bonding", "liquidity")):
                addresses.add(str(address))

    return addresses, owners


def _holder_rpc_prequal(metrics):
    """
    V12.3 holder recovery prequal.
    Holder verification now runs for every plausible radar candidate that has
    enough market/liquidity data, instead of waiting for strong activity.
    This improves Top-10 coverage while the FINAL GIR gate remains unchanged.
    """
    if not isinstance(metrics, dict):
        return False
    mc = num(metrics.get("mc"))
    liq = num(metrics.get("liq"))
    if mc is None or not (1000 <= mc <= 15000):
        return False
    if liq is None or liq < 800:
        return False
    return True



def rpc_holder_top10(ca: str):
    """V12.4 robust Solana Top-10 verification with owner lookup as best-effort."""
    now = time.time()
    cached = HOLDER_RPC_CACHE.get(ca)
    if cached and now - cached[0] < HOLDER_RPC_CACHE_TTL:
        return cached[1]
    try:
        largest = solana_rpc_call("getTokenLargestAccounts", [ca, {"commitment": "confirmed"}])
        supply_resp = solana_rpc_call("getTokenSupply", [ca, {"commitment": "confirmed"}])
        vals = ((largest or {}).get("result") or {}).get("value") or []
        supply_obj = (((supply_resp or {}).get("result") or {}).get("value") or {})
        supply_raw = num(supply_obj.get("amount"))
        if not vals or not supply_raw or supply_raw <= 0:
            result = (None, None, None, False)
            HOLDER_RPC_CACHE[ca] = (now, result)
            return result

        accounts = []
        for row in vals:
            if not isinstance(row, dict):
                continue
            amount = num(row.get("amount"))
            address = str(row.get("address") or "").strip()
            if amount is not None and amount >= 0:
                accounts.append((address, float(amount)))
        if not accounts:
            result = (None, None, None, False)
            HOLDER_RPC_CACHE[ca] = (now, result)
            return result

        raw_amounts = sorted((a for _, a in accounts), reverse=True)
        raw_top10 = max(0.0, min(100.0, 100.0 * sum(raw_amounts[:10]) / float(supply_raw)))

        # Owner aggregation is useful but must not make the fallback collapse.
        owner_totals = {}
        for address, amount in accounts[:20]:
            if not address:
                continue
            try:
                info = solana_rpc_call("getAccountInfo", [
                    address, {"encoding": "jsonParsed", "commitment": "confirmed"}
                ])
                value = ((info or {}).get("result") or {}).get("value") or {}
                data = value.get("data") or {}
                parsed = (data.get("parsed") or {}) if isinstance(data, dict) else {}
                info_obj = parsed.get("info") or {}
                owner = str(info_obj.get("owner") or "").strip()
                if owner:
                    owner_totals[owner] = owner_totals.get(owner, 0.0) + amount
            except Exception:
                continue

        if owner_totals:
            amounts = sorted(owner_totals.values(), reverse=True)
            top10 = max(0.0, min(100.0, 100.0 * sum(amounts[:10]) / float(supply_raw)))
            source = "SOLANA_RPC_OWNER"
        else:
            top10 = raw_top10
            source = "SOLANA_RPC_ACCOUNTS"

        reliable = 1.0 <= top10 < 98.0
        result = (top10 if reliable else None, raw_top10, source, not reliable)
        HOLDER_RPC_CACHE[ca] = (now, result)
        return result
    except Exception as e:
        print("HOLDER RPC FALLBACK ERROR:", ca, repr(e), flush=True)
        result = (None, None, None, False)
        HOLDER_RPC_CACHE[ca] = (time.time() - HOLDER_RPC_CACHE_TTL + 90, result)
        return result

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

def send_clickable_ca(chat_id, ca):
    if not ca:
        return
    ca = str(ca).strip()
    url = f"https://axiom.trade/t/{ca}?chain=sol"
    send(chat_id, f'<a href="{url}">{ca}</a>', parse_mode="HTML")


def send(chat_id, text, parse_mode=None):
    try:
        text = clean_telegram_text(text)
        payload = {
            "chat_id": str(chat_id),
            "text": text[:4000],
            "disable_web_page_preview": "true"
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
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
    global birdeye_listing_liq, birdeye_cooldown_until, birdeye_last_error_body

    if not BIRDEYE_API_KEY:
        return []

    now = time.time()

    # If Birdeye quota/rate limit was exceeded, do not hammer the API.
    if now < birdeye_cooldown_until:
        with birdeye_lock:
            return list(birdeye_cache)

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
            headers={
                "X-API-KEY": BIRDEYE_API_KEY,
                "x-chain": "solana",
                "accept": "application/json",
            },
        )

        items = extract_birdeye_items(payload)
        newest = []
        listing_liq = {}

        for item in items:
            if not isinstance(item, dict):
                continue

            ca = str(item.get("address") or "").strip()
            if not (ca and SOL_CA.fullmatch(ca)):
                continue

            newest.append(ca)

            liq = num(item.get("liquidity"))
            if liq is not None and liq > 0:
                listing_liq[ca] = liq
                LIQ_CACHE[ca] = (liq, now)

        with birdeye_lock:
            merged = []
            seen = set()
            for ca in newest + list(birdeye_cache):
                if ca not in seen:
                    seen.add(ca)
                    merged.append(ca)

            birdeye_cache = merged[:80]
            birdeye_listing_liq.update(listing_liq)
            birdeye_last_fetch = now
            birdeye_last_error = ""
            birdeye_last_error_body = ""
            birdeye_cooldown_until = 0

        print(
            f"BIRDEYE COOLDOWN FEED OK: api={len(newest)} cache={len(birdeye_cache)} "
            f"listing_liq={len(listing_liq)}",
            flush=True,
        )
        return list(birdeye_cache)

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""

        body_clean = " ".join(body.split())[:900]
        err = f"HTTP {e.code}: {body_clean}"

        birdeye_last_error_body = body_clean
        err_lower = err.lower()

        if "exceeded" in err_lower or e.code == 429:
            birdeye_cooldown_until = now + BIRDEYE_COOLDOWN_SECONDS
            print(
                f"BIRDEYE COOLDOWN ACTIVE: {BIRDEYE_COOLDOWN_SECONDS}s | "
                f"status={e.code} | body={body_clean}",
                flush=True,
            )
        else:
            print(
                f"BIRDEYE FEED ERROR: status={e.code} | body={body_clean}",
                flush=True,
            )

        with birdeye_lock:
            birdeye_last_error = err
            birdeye_last_fetch = now
            cached = list(birdeye_cache)

        return cached

    except Exception as e:
        err = repr(e)
        err_lower = err.lower()

        # V13.3: some quota failures can arrive wrapped instead of as HTTPError.
        # Treat any explicit quota/rate-limit signature as a real cooldown event.
        if (
            "compute units usage limit exceeded" in err_lower
            or "usage limit exceeded" in err_lower
            or "rate limit" in err_lower
            or "http error 429" in err_lower
        ):
            birdeye_cooldown_until = now + BIRDEYE_COOLDOWN_SECONDS
            print(
                f"BIRDEYE COOLDOWN ACTIVE (WRAPPED): {BIRDEYE_COOLDOWN_SECONDS}s | {err}",
                flush=True,
            )

        with birdeye_lock:
            birdeye_last_error = err
            birdeye_last_fetch = now
            cached = list(birdeye_cache)

        print("BIRDEYE FEED ERROR:", err, flush=True)
        return cached

def gecko_new_candidates(force=False):
    """
    V12.2 resilient GeckoTerminal feed.
    - Per-page isolation: one failed page no longer kills the whole feed.
    - Alternate endpoint fallback.
    - Exponential retry backoff on 429/5xx/network errors.
    - Keeps last good cache instead of dropping radar coverage to zero.
    """
    global gecko_cache, gecko_last_fetch, gecko_last_error, gecko_liq_cache
    global gecko_fail_count, gecko_next_retry, gecko_last_status

    now = time.time()
    with gecko_lock:
        if not force and now < gecko_next_retry:
            gecko_last_status = "BACKOFF"
            return list(gecko_cache)
        if not force and gecko_cache and now - gecko_last_fetch < GECKO_POLL_INTERVAL:
            gecko_last_status = "CACHE"
            return list(gecko_cache)

    found, seen, liq_updates = [], set(), {}
    errors = []
    pages_ok = 0

    endpoint_templates = [
        "https://api.geckoterminal.com/api/v2/networks/solana/new_pools",
        "https://api.geckoterminal.com/api/v2/networks/solana/pools",
    ]

    for endpoint in endpoint_templates:
        endpoint_found_before = len(found)
        for page in range(1, GECKO_PAGES + 1):
            url = endpoint + "?" + urllib.parse.urlencode({
                "include": "base_token",
                "page": page,
            })
            try:
                payload = get_json(
                    url,
                    timeout=15,
                    headers={
                        "accept": "application/json",
                        "User-Agent": "HunterElite-V12.2",
                    },
                )
                if not isinstance(payload, dict):
                    errors.append(f"page{page}:BAD_PAYLOAD")
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
                    errors.append(f"page{page}:NO_DATA")
                    continue

                pages_ok += 1
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
                errors.append(f"page{page}:{type(e).__name__}:{str(e)[:90]}")
                continue

        # Prefer new_pools; only use broad pools endpoint if new_pools gave nothing.
        if len(found) > endpoint_found_before:
            break

    with gecko_lock:
        if found:
            merged, merged_seen = [], set()
            for ca in found + list(gecko_cache):
                if ca not in merged_seen:
                    merged_seen.add(ca)
                    merged.append(ca)
            gecko_cache = merged[:80]
            gecko_liq_cache.update(liq_updates)

            expired = [
                ca for ca, (_, ts) in gecko_liq_cache.items()
                if now - ts > GECKO_LIQ_CACHE_TTL
            ]
            for ca in expired:
                gecko_liq_cache.pop(ca, None)

            gecko_last_fetch = now
            gecko_fail_count = 0
            gecko_next_retry = 0
            gecko_last_error = "; ".join(errors[-2:]) if errors else ""
            gecko_last_status = "PARTIAL" if errors else "OK"
        else:
            gecko_fail_count += 1
            # 30s, 60s, 120s, 240s, capped at 5m.
            backoff = min(300, 30 * (2 ** min(gecko_fail_count - 1, 4)))
            gecko_next_retry = now + backoff
            gecko_last_fetch = now
            gecko_last_error = "; ".join(errors[-3:]) if errors else "NO_RESULTS"
            gecko_last_status = "BACKOFF" if gecko_cache else "ERR"

        cached = list(gecko_cache)

    print(
        f"GECKO FEED {gecko_last_status}: api={len(found)} cache={len(cached)} "
        f"liq={len(liq_updates)} pages_ok={pages_ok} "
        f"retry={max(0,int(gecko_next_retry-time.time()))}s "
        f"err={gecko_last_error[:180]}",
        flush=True,
    )
    return cached

def discovery_candidates():
    endpoints = [
        "https://api.dexscreener.com/token-profiles/latest/v1",
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/token-boosts/top/v1",
        "https://api.dexscreener.com/community-takeovers/latest/v1",
    ]

    candidate_sources.clear()

    birdeye_found, birdeye_seen = [], set()
    for ca in birdeye_new_candidates():
        if ca and ca not in birdeye_seen:
            birdeye_seen.add(ca)
            birdeye_found.append(ca)
            candidate_sources[ca] = "BIRDEYE"

    # Keyless fresh-pool fallback, especially important while Birdeye is in cooldown.
    gecko_found, gecko_seen = [], set()
    for ca in gecko_new_candidates():
        if not ca or ca in birdeye_seen or ca in gecko_seen:
            continue
        gecko_seen.add(ca)
        gecko_found.append(ca)
        candidate_sources[ca] = "GECKO"

    dex_found, dex_seen = [], set()
    for url in endpoints:
        try:
            data = get_json(url)
            if not isinstance(data, list):
                continue
            for item in data:
                if str(item.get("chainId", "")).lower() != "solana":
                    continue
                ca = str(item.get("tokenAddress", "")).strip()
                if not (ca and SOL_CA.fullmatch(ca)):
                    continue
                if ca in birdeye_seen or ca in gecko_seen or ca in dex_seen:
                    continue
                dex_seen.add(ca)
                dex_found.append(ca)
                candidate_sources[ca] = "DEX"
        except Exception as e:
            print("DISCOVERY ERROR:", repr(e), flush=True)

    selected = []
    selected_seen = set()

    def _add(ca):
        if ca and ca not in selected_seen and len(selected) < RADAR_TARGET:
            selected.append(ca)
            selected_seen.add(ca)
            return True
        return False

    # V13.5 FRESH RADAR MIX
    # Birdeye still gets first priority when healthy, but Gecko can no longer
    # consume the entire 80-token radar before DEX fresh discovery is considered.
    for ca in birdeye_found:
        if len(selected) >= RADAR_TARGET:
            break
        _add(ca)

    # When Birdeye is unavailable, cap Gecko at 60 so DEX has 20 real slots.
    # If Birdeye contributes, only use Gecko up to the point that still preserves
    # the DEX reserve.
    gecko_cap_total = max(0, RADAR_TARGET - DEX_RESERVED_SLOTS)
    gecko_added = 0
    for ca in gecko_found:
        if len(selected) >= gecko_cap_total or gecko_added >= GECKO_MAX_SELECTED:
            break
        if _add(ca):
            gecko_added += 1

    # DEX now gets reserved live-discovery capacity instead of being a last-resort
    # fallback that often ended at DEX=0.
    dex_added = 0
    for ca in dex_found:
        if len(selected) >= RADAR_TARGET or dex_added >= DEX_RESERVED_SLOTS:
            break
        if _add(ca):
            dex_added += 1

    # Never waste empty slots: after the DEX reservation was attempted, fill any
    # remaining capacity with unused Gecko then unused DEX candidates.
    for ca in gecko_found:
        if len(selected) >= RADAR_TARGET:
            break
        _add(ca)

    for ca in dex_found:
        if len(selected) >= RADAR_TARGET:
            break
        _add(ca)

    return selected[:RADAR_TARGET]

def birdeye_market_data(ca):
    """Disabled as a hard dependency: fresh listings use listing liquidity + DEX + cache."""
    return None


def rugcheck(ca):
    try:
        return get_json(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report")
    except Exception as e:
        print("RUGCHECK ERROR:", repr(e), flush=True)
        return None

def holder_pct(holder):
    """
    RugCheck topHolders[].pct is already expressed in percentage points.
    Example: pct=0.867 means 0.867%, NOT 86.7%.
    """
    if not isinstance(holder, dict):
        return None

    # RugCheck's canonical field: already percent units.
    value = num(holder.get("pct"))
    if value is not None:
        return value if 0 <= value <= 100 else None

    # Defensive fallbacks for alternate schemas.
    for key in ("percentage", "percent"):
        value = num(holder.get(key))
        if value is not None:
            return value if 0 <= value <= 100 else None

    # Only this explicitly named ownership field may be fractional in some APIs.
    value = num(holder.get("ownershipPercentage"))
    if value is not None:
        if 0 <= value <= 1:
            value *= 100
        return value if 0 <= value <= 100 else None

    return None

def rugcheck_holder_risk(report):
    """Return True only when RugCheck itself reports holder concentration risk."""
    if not isinstance(report, dict):
        return False
    try:
        blob = json.dumps(report.get("risks") or [], ensure_ascii=False).lower()
    except Exception:
        blob = str(report.get("risks") or []).lower()
    needles = (
        "top 10 holder", "top10 holder", "top-10 holder",
        "single holder", "holder ownership", "high ownership",
        "large amount of the token supply", "holder concentrat",
    )
    return any(n in blob for n in needles)


def _holder_identity(holder, index):
    if not isinstance(holder, dict):
        return f"row:{index}"
    for key in ("owner", "address", "pubkey", "tokenAccount", "token_account"):
        value = holder.get(key)
        if value:
            return str(value)
    return f"row:{index}"


def holders(report):
    """
    Primary Top-1/5/10 calculation from RugCheck.

    V11.57 excludes accounts/owners that RugCheck itself identifies as
    AMM/pool/market/bonding-curve inventory before calculating user-wallet
    concentration. This prevents a pool inventory from masquerading as a
    single whale while still keeping true user concentration as a hard gate.
    """
    if not report:
        return None, None, None, False, None

    items = report.get("topHolders") or report.get("top_holders") or []
    protocol_addresses, protocol_owners = _protocol_holder_accounts(report)
    owner_values = {}
    anonymous_values = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        value = holder_pct(item)
        if value is None:
            continue

        address = str(item.get("address") or item.get("tokenAccount") or item.get("token_account") or "")
        owner = str(item.get("owner") or "")

        if address and address in protocol_addresses:
            continue
        if owner and (owner in protocol_owners or owner in protocol_addresses):
            continue

        if owner:
            # Multiple token accounts belonging to the same wallet are one holder.
            owner_values[owner] = owner_values.get(owner, 0.0) + value
        else:
            anonymous_values.append(value)

    rows = sorted(list(owner_values.values()) + anonymous_values, reverse=True)
    if not rows:
        return None, None, None, False, None

    top1 = rows[0]
    top5 = sum(rows[:5])
    raw_top10 = sum(rows[:10])

    if top1 > 100 or top5 > 100.5 or raw_top10 > 100.5:
        return None, None, None, True, raw_top10

    # Verified primary path requires enough actual user-holder rows.
    # If fewer than 10 remain, RPC fallback may complete verification later.
    if len(rows) < 10:
        return top1, top5, None, True, raw_top10

    # V12.1: both extremes are suspicious on ultra-fresh meme tokens.
    # <1% usually means protocol/pool exclusion or incomplete holder parsing;
    # ~100% usually means protocol inventory was counted as holders.
    unreliable = (
        raw_top10 < 1.0
        or (raw_top10 >= 98.0 and not rugcheck_holder_risk(report))
    )
    top10 = None if unreliable else raw_top10
    return top1, top5, top10, unreliable, raw_top10

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

    top1, top5, top10, holder_unreliable, holder_raw_top10 = holders(report)
    holder_source = "RUGCHECK" if top10 is not None and not holder_unreliable else "UNVERIFIED"

    # V11.57: only promising candidates spend RPC calls on secondary verification.
    ca = str(((pair.get("baseToken") or {}).get("address") or "")).strip()
    if (top10 is None or holder_unreliable) and _holder_rpc_prequal(metrics):
        stats["holder_rpc_attempt"] = stats.get("holder_rpc_attempt", 0) + 1
        r1, r5, r10, rpc_reliable = rpc_holder_top10(ca, report)
        if rpc_reliable and r10 is not None:
            top1, top5, top10 = r1, r5, r10
            holder_unreliable = False
            holder_raw_top10 = r10
            holder_source = "SOLANA_RPC"

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
        "holder_raw_top10": holder_raw_top10,
        "holder_unreliable": holder_unreliable,
        "holder_source": holder_source,
        "report": report,
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

    decision = unified_gir_decision(result, momentum, previous)

    is_breakout = decision == "BREAKOUT_GIR"

    is_strong_gir = decision == "STRONG_GIR"

    if is_breakout:

        stats["breakout"] = stats.get("breakout", 0) + 1

    elif is_strong_gir:

        stats["strong_gir"] = stats.get("strong_gir", 0) + 1

    else:

        stats["decision_izle"] = stats.get("decision_izle", 0) + 1

    if decision in ("BREAKOUT_GIR", "STRONG_GIR"):
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
ğŸ’ Potansiyel: {_watch_potential}

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
    if result["top10"] is not None and result["top10"] >= HOLDER_HARD_MAX:
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

def gir_block_reason(result, score):
    """Diagnostic only; never changes the GIR decision."""
    liq = num(result.get("liq"))
    top10 = num(result.get("top10"))
    price5 = num(result.get("price5"))
    buys5 = num(result.get("buys5")) or 0
    sells5 = num(result.get("sells5")) or 0
    vol5 = num(result.get("vol5")) or 0

    if liq is None or top10 is None or price5 is None:
        return "CRITICAL_DATA_WAIT"
    if liq < MIN_LIQUIDITY:
        return "LIQ_LOW"
    if top10 > 82:
        return "TOP10_HIGH"
    if price5 < -8:
        return "PRICE5_WEAK"
    if price5 > 180:
        ratio = buys5 / max(sells5, 1)
        if (
            score >= 70
            and buys5 >= 100
            and ratio >= 1.20
            and vol5 >= 10000
            and top10 <= 70
            and liq / max((num(result.get("mc")) or 1), 1) >= 0.20
        ):
            return "EXTREME_BREAKOUT_READY"
        if score < 70:
            return "EXTENDED_MOVE_SCORE_LT70"
        return "PRICE5_TOO_HIGH"
    if sells5 > buys5 * 1.15:
        return "SELL_PRESSURE"
    if buys5 < 10:
        return "ACTIVITY_LOW"
    if vol5 < 500:
        return "VOLUME_LOW"
    if score < SIGNAL_SCORE:
        _mc = num(result.get("mc")) or 0
        _ratio = buys5 / max(sells5, 1)
        if (
            25 <= price5 <= 150
            and score >= 52
            and buys5 >= 80
            and _ratio >= 1.50
            and vol5 >= 5000
            and top10 <= 65
            and liq >= 1500
            and liq / max(_mc, 1) >= 0.25
        ):
            return "EARLY_QUALITY_GIR_READY"
        return "SCORE_BELOW_SIGNAL"
    return "TREND_OR_MOMENTUM_WAIT"


def unified_gir_decision(result, momentum=0, final_score=0):
    """
    One central promotion engine:
    - BREAKOUT_GIR: RURU-style accelerating low-cap candidate.
    - STRONG_GIR: hard-safe candidate with strong score/activity.
    - IZLE: everything else.
    Hard safety gates remain upstream and are never bypassed here.
    """
    mc = result.get("mc") or 0
    liq = result.get("liq")
    top10 = result.get("top10")
    buys = result.get("buys5", 0) or 0
    sells = result.get("sells5", 0) or 0
    vol5 = result.get("vol5") or 0
    price5 = result.get("price5")
    score = result.get("score", 0) or 0

    if liq is None or top10 is None or price5 is None:
        return "VERI_BEKLE"

    # Never bypass the existing core envelope.
    if mc < 1000 or mc > 15000 or liq < MIN_LIQUIDITY or top10 > 82:
        return "IZLE"

    ratio = buys / max(sells, 1)

    # Extreme breakout: very fast move is not auto-rejected if quality is exceptional.
    if (
        180 < price5 <= 600
        and score >= 70
        and buys >= 100
        and ratio >= 1.20
        and vol5 >= 10000
        and top10 <= 70
        and liq / max(mc, 1) >= 0.20
    ):
        return "BREAKOUT_GIR"

    # V11.50 quality override:
    # A slightly lower composite score may still GIR when the live tape is
    # exceptionally strong and holder/liquidity quality is clean.
    if (
        25 <= price5 <= 150
        and 52 <= score < 60
        and buys >= 80
        and ratio >= 1.50
        and vol5 >= 5000
        and top10 <= 65
        and liq >= 1500
        and liq / max(mc, 1) >= 0.25
    ):
        return "BREAKOUT_GIR"

    # V11.49 early breakout calibration:
    # Score 60-69 may GIR only while the move is still early (<=180%).
    # This avoids promoting already-extended +180% moves on score alone.
    if (
        25 <= price5 <= 180
        and 60 <= score < 70
        and buys >= 20
        and ratio >= 1.20
        and vol5 >= 1500
        and top10 <= 70
        and liq >= 800
        and liq / max(mc, 1) >= 0.15
    ):
        return "BREAKOUT_GIR"

    # RURU/MUMU style breakout.
    if (
        25 <= price5 <= 300
        and buys >= 30
        and ratio >= 1.10
        and vol5 >= 2500
        and liq / max(mc, 1) >= 0.12
        and score >= WATCH_SCORE
    ):
        return "BREAKOUT_GIR"

    # Strong pre-breakout candidate: score + real activity + buy pressure.
    if (
        score >= SIGNAL_SCORE
        and buys >= 25
        and ratio >= 1.25
        and vol5 >= 2000
        and -8 <= price5 <= 60
    ):
        return "STRONG_GIR"

    # Preserve the existing confirmed signal path.
    try:
        if strong_signal(result, momentum, final_score):
            return "STRONG_GIR"
    except Exception:
        pass

    return "IZLE"


def breakout_signal(result):
    """RURU-style low-cap breakout path. Hard safety is still mandatory upstream."""
    mc = result.get("mc") or 0
    liq = result.get("liq")
    top10 = result.get("top10")
    buys = result.get("buys5", 0) or 0
    sells = result.get("sells5", 0) or 0
    vol5 = result.get("vol5") or 0
    price5 = result.get("price5")

    if liq is None or top10 is None or price5 is None:
        return False

    # Keep the core safety/early-entry envelope.
    if not (1000 <= mc <= 15000):
        return False
    if liq < MIN_LIQUIDITY:
        return False
    if top10 > 82:
        return False

    # RURU-style breakout: already moving hard, but backed by real activity.
    if not (35 <= price5 <= 300):
        return False
    if buys < 35:
        return False
    if sells > 0 and buys / sells < 1.10:
        return False
    if vol5 < 2500:
        return False

    # Avoid ultra-thin liquidity relative to market cap.
    if mc > 0 and liq / mc < 0.12:
        return False

    return True


def strong_signal(result, momentum, previous=None):
    if not basic_signal_safe(result):
        return False
    # V11.55: GIR requires verified holder concentration.
    if result.get("top10") is None or bool(result.get("holder_unreliable")):
        return False
    if not crash_guard(result):
        return False
    if previous is None:
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
    if top10 is not None and top10 >= HOLDER_HARD_MAX:
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
                "holder_unreliable": 0, "safe_score_samples": [], "score_fail_samples": [],
    "unique_new": 0, "repeat": 0, "pair_pass": 0, "mc_pass": 0,
    "liq_pass": 0, "liq_missing": 0, "liq_0_200": 0, "liq_200_500": 0, "liq_500_800": 0, "liq_800_plus": 0, "liq_fallback_ok": 0, "liq_fallback_missing": 0, "liq_gecko_ok": 0, "liq_gecko_missing": 0, "holder_pass": 0, "holder_missing": 0, "holder_50_60": 0, "holder_60_70": 0, "holder_70_82": 0, "holder_82_plus": 0, "safety_pass": 0, "rug_ok": 0, "auth_ok": 0, "crash_ok": 0, "age_fail": 0, "h1_fail": 0, "h6_fail": 0, "h24_fail": 0,
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


                    # Short cache fallback for temporary liquidity API gaps.

                    _now = time.time()

                    if liq is not None and liq > 0:

                        LIQ_CACHE[str(ca)] = (liq, _now)

                    else:

                        _cached_liq = LIQ_CACHE.get(str(ca))

                        if _cached_liq and (_now - _cached_liq[1]) <= LIQ_CACHE_TTL:

                            liq = _cached_liq[0]

                            result["liq"] = liq

                    # First use Gecko pool reserve for Gecko-sourced fresh tokens.
                    if mc_ok and liq is None and source_name == "GECKO":
                        _g = gecko_liq_cache.get(str(ca))
                        if _g and (time.time() - _g[1]) <= GECKO_LIQ_CACHE_TTL:
                            liq = _g[0]
                            result["liq"] = liq
                            result["liq_source"] = "GECKO"
                            LIQ_CACHE[str(ca)] = (liq, time.time())
                            stats["liq_gecko_ok"] += 1
                        else:
                            stats["liq_gecko_missing"] += 1

                    # Then use liquidity supplied directly by Birdeye new-listing.
                    if mc_ok and liq is None:
                        _listing_liq = birdeye_listing_liq.get(str(ca))
                        if _listing_liq is not None and _listing_liq > 0:
                            liq = _listing_liq
                            result["liq"] = liq
                            result["liq_source"] = "BIRDEYE_LISTING"
                            LIQ_CACHE[str(ca)] = (liq, time.time())
                            stats["liq_fallback_ok"] += 1

                    # If still missing, do not fabricate liquidity.
                    # The token remains pending and will be retried on the next scan.
                    if mc_ok and liq is None:
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
                    holder_unreliable = bool(result.get("holder_unreliable"))
                    holder_raw_top10 = result.get("holder_raw_top10")
                    holder_source = result.get("holder_source")
                    if holder_source in ("SOLANA_RPC", "SOLANA_RPC_OWNER", "SOLANA_RPC_ACCOUNTS"):
                        stats["holder_rpc_verified"] = stats.get("holder_rpc_verified", 0) + 1
                    elif holder_source == "RUGCHECK":
                        stats["holder_rugcheck_verified"] = stats.get("holder_rugcheck_verified", 0) + 1

                    if liq_ok:
                        if holder_unreliable:
                            stats["holder_unreliable"] = stats.get("holder_unreliable", 0) + 1
                        # Diagnostic samples are grouped by DISCOVERY source, not holder-data source.
                        if top10 is not None:
                            _key = "holder_gecko_samples" if source_name == "GECKO" else "holder_dex_samples"
                            _checked = "holder_gecko_checked" if source_name == "GECKO" else "holder_dex_checked"
                            _high = "holder_gecko_82" if source_name == "GECKO" else "holder_dex_82"
                            stats[_checked] = stats.get(_checked, 0) + 1
                            if top10 >= 82:
                                stats[_high] = stats.get(_high, 0) + 1
                            _samples = stats.setdefault(_key, [])
                            if len(_samples) < 8:
                                _samples.append(round(float(top10), 1))
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

                    holder_ok = liq_ok and ((top10 is not None and top10 < HOLDER_HARD_MAX) or holder_unreliable)
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
                        if len(stats["safe_score_samples"]) < 8:
                            stats["safe_score_samples"].append(int(result.get("score", 0)))

                    score_ok = safety_ok and result.get("score", 0) >= WATCH_SCORE
                    if score_ok:
                        stats["score_pass"] += 1
                    elif safety_ok and len(stats["score_fail_samples"]) < 5:
                        stats["score_fail_samples"].append({
                            "score": int(result.get("score", 0)),
                            "risks": list(result.get("risks") or [])[:3],
                        })

                    vol5 = result.get("vol5")
                    activity_ok = (score_ok
                                   and result.get("buys5", 0) >= WATCH_MIN_BUYS_5M
                                   and (vol5 is None or vol5 >= WATCH_MIN_VOL_5M))
                    if activity_ok: stats["activity_pass"] += 1

                    now = time.time()
                    with state_lock:
                        previous = token_states.get(ca)

                    old_metrics = previous.get("metrics") if previous else None
                    momentum = momentum_score(old_metrics, result)
                    trend_ok = activity_ok and old_metrics is not None and trend_confirmed(old_metrics, result)
                    if trend_ok: stats["trend_pass"] += 1
                    momentum_ok = trend_ok and momentum >= MIN_MOMENTUM_SIGNAL
                    if momentum_ok: stats["momentum_pass"] += 1
                    seen_count = (previous.get("seen_count", 0) + 1) if previous else 1
                    stage = previous.get("stage", "NEW") if previous else "NEW"
                    last_sent = previous.get("last_sent", 0) if previous else 0
                    new_stage, message = stage, None

                    # V11.54 FINAL: compute the central decision in scanner scope.
                    # V11.57 referenced is_breakout/_watch_decision/_gir_block later
                    # without defining them here, which could abort exactly when a
                    # WATCH/SIGNAL message was ready to be delivered.
                    _central_decision = unified_gir_decision(result, momentum, old_metrics) if safety_ok else "IZLE"
                    is_breakout = _central_decision == "BREAKOUT_GIR"
                    is_strong_gir = _central_decision == "STRONG_GIR"
                    _gir_block = gir_block_reason(result, int(result.get("score", 0)))
                    _watch_decision = "ğŸŸ¢ GÄ°R" if (_central_decision in ("BREAKOUT_GIR", "STRONG_GIR") and not _gir_block) else "ğŸŸ¡ Ä°ZLE / ERKEN ADAY"

                    # V12.8 EARLY WATCH:
                    # A hard-safe PREPUMP candidate may be surfaced on its first scan,
                    # without weakening the final GÄ°R gate.
                    _early_watch_ok = bool(
                        safety_ok
                        and result.get("prepump")
                        and int(result.get("score", 0) or 0) >= WATCH_SCORE
                        and result.get("buys5", 0) >= WATCH_MIN_BUYS_5M
                        and (result.get("vol5") is None or result.get("vol5") >= WATCH_MIN_VOL_5M)
                    )
                    watch_ok = bool(watch_candidate(result) or _early_watch_ok)
                    if result.get("prepump") and safety_ok:
                        WATCH_DIAG["SAFE_PREPUMP_SEEN"] = WATCH_DIAG.get("SAFE_PREPUMP_SEEN", 0) + 1
                        if _early_watch_ok:
                            WATCH_DIAG["EARLY_WATCH_OK"] = WATCH_DIAG.get("EARLY_WATCH_OK", 0) + 1
                        elif int(result.get("score", 0) or 0) < WATCH_SCORE:
                            WATCH_DIAG["SCORE_LOW"] = WATCH_DIAG.get("SCORE_LOW", 0) + 1
                        elif result.get("buys5", 0) < WATCH_MIN_BUYS_5M:
                            WATCH_DIAG["BUYS_LOW"] = WATCH_DIAG.get("BUYS_LOW", 0) + 1
                        elif result.get("vol5") is not None and result.get("vol5") < WATCH_MIN_VOL_5M:
                            WATCH_DIAG["VOLUME_LOW"] = WATCH_DIAG.get("VOLUME_LOW", 0) + 1
                        else:
                            WATCH_DIAG["OTHER"] = WATCH_DIAG.get("OTHER", 0) + 1
                        if watch_ok:
                            WATCH_DIAG["WATCH_OK"] = WATCH_DIAG.get("WATCH_OK", 0) + 1
                    # Keep hard safety mandatory. Confirmed trend remains the main
                    # path, while the already-existing calibrated breakout engine
                    # can promote a hard-safe, high-activity candidate instead of
                    # being calculated but never used.
                    _confirmed_signal = (
                        seen_count >= TREND_CONFIRM_SCANS
                        and strong_signal(result, momentum, old_metrics)
                    )
                    _calibrated_breakout = (
                        safety_ok
                        and _central_decision in ("BREAKOUT_GIR", "STRONG_GIR")
                    )
                    # Candidate paths may propose a signal, but V12.1 has ONE
                    # authoritative final gate. No path can bypass it.
                    # V12.7: wire the runner engine into the actual proposal path.
                    # Runner can PROPOSE a signal, but it can never bypass final_gir_gate.
                    _runner_confirmed, _runner_mc_accel, _runner_vol_accel = v126_track_runner(
                        ca, result, int(result.get("score", 0) or 0)
                    )
                    _runner_signal = bool(
                        safety_ok
                        and _runner_confirmed
                        and seen_count >= TREND_CONFIRM_SCANS
                        and momentum >= MIN_MOMENTUM_SIGNAL
                    )

                    _candidate_signal = bool(
                        _confirmed_signal
                        or _calibrated_breakout
                        or _runner_signal
                    )

                    result["ca"] = ca
                    result["runner_mc_accel"] = _runner_mc_accel
                    result["runner_vol_accel"] = _runner_vol_accel
                    _final_gate_ok, _final_gate_reason = final_gir_gate(
                        result, old_metrics, seen_count, momentum, now
                    )
                    if _candidate_signal and not _final_gate_ok:
                        FINAL_GATE_REJECTS[_final_gate_reason] = FINAL_GATE_REJECTS.get(_final_gate_reason, 0) + 1

                    # V13.3 CONFIRMED LAUNCH
                    # A token that passes all normal gates is only ARMED on the first
                    # qualifying scan. GÄ°R is sent on a later scan only if the move
                    # is still continuing instead of immediately fading.
                    _raw_signal_ok = bool(_candidate_signal and _final_gate_ok)
                    _launch_pending = previous.get("launch_pending") if previous else None
                    _next_launch_pending = None
                    signal_ok = False
                    _fast_launch_ok = False

                    if _raw_signal_ok:
                        _mc_now = num(result.get("mc")) or 0
                        _vol_now = num(result.get("vol5")) or 0
                        _price_now = num(result.get("price5"))
                        _buys_now = num(result.get("buys5")) or 0
                        _sells_now = num(result.get("sells5")) or 0
                        _bs_now = _buys_now / max(_sells_now, 1)
                        _age_now = num(result.get("age_hours"))
                        _score_now = num(result.get("score")) or 0
                        _rmc_now = num(result.get("runner_mc_accel"))
                        _rvol_now = num(result.get("runner_vol_accel"))

                        # V13.4 FAST LAUNCH lane:
                        # Catch the successful-pump pattern early, before waiting
                        # another full confirmation scan, but only under unusually
                        # strong simultaneous capital + volume + buy-pressure expansion.
                        _fast_launch_ok = bool(
                            _score_now >= 75
                            and _rmc_now is not None and _rmc_now >= 12.0
                            and _rvol_now is not None and _rvol_now >= 25.0
                            and _bs_now >= 1.60
                            and _vol_now >= 4000.0
                            and _price_now is not None and 5.0 <= _price_now <= 35.0
                            and (_age_now is None or _age_now <= 0.25)
                        )

                        if _fast_launch_ok:
                            signal_ok = True
                            FINAL_GATE_REJECTS["FAST_LAUNCH_CONFIRMED"] = FINAL_GATE_REJECTS.get("FAST_LAUNCH_CONFIRMED", 0) + 1

                        elif isinstance(_launch_pending, dict):
                            _mc_arm = num(_launch_pending.get("mc")) or 0
                            _vol_arm = num(_launch_pending.get("vol5")) or 0
                            _price_arm = num(_launch_pending.get("price5"))
                            _arm_time = num(_launch_pending.get("time")) or 0
                            _arm_age = max(0.0, now - _arm_time)

                            _launch_mc_ok = bool(
                                _mc_arm > 0 and _mc_now >= _mc_arm * 1.015
                            )
                            _launch_buy_ok = bool(_bs_now >= 1.45)
                            _launch_vol_ok = bool(
                                _vol_arm <= 0 or _vol_now >= _vol_arm * 0.95
                            )
                            _launch_price_ok = bool(
                                _price_now is not None
                                and _price_now >= 3.0
                                and (_price_arm is None or _price_now >= _price_arm - 2.0)
                            )
                            _launch_time_ok = bool(20.0 <= _arm_age <= 180.0)

                            if (
                                _launch_mc_ok
                                and _launch_buy_ok
                                and _launch_vol_ok
                                and _launch_price_ok
                                and _launch_time_ok
                            ):
                                signal_ok = True
                                FINAL_GATE_REJECTS["LAUNCH_CONFIRMED"] = FINAL_GATE_REJECTS.get("LAUNCH_CONFIRMED", 0) + 1
                            else:
                                if not _launch_time_ok:
                                    _launch_reason = "LAUNCH_TIME"
                                elif not _launch_mc_ok:
                                    _launch_reason = "LAUNCH_MC_WEAK"
                                elif not _launch_buy_ok:
                                    _launch_reason = "LAUNCH_BUY_WEAK"
                                elif not _launch_vol_ok:
                                    _launch_reason = "LAUNCH_VOLUME_FADE"
                                else:
                                    _launch_reason = "LAUNCH_PRICE_WEAK"
                                FINAL_GATE_REJECTS[_launch_reason] = FINAL_GATE_REJECTS.get(_launch_reason, 0) + 1

                                # Re-arm from the latest healthy qualifying scan.
                                _next_launch_pending = {
                                    "mc": _mc_now,
                                    "vol5": _vol_now,
                                    "price5": _price_now,
                                    "time": now,
                                }
                        else:
                            FINAL_GATE_REJECTS["LAUNCH_CONFIRM_WAIT"] = FINAL_GATE_REJECTS.get("LAUNCH_CONFIRM_WAIT", 0) + 1
                            _next_launch_pending = {
                                "mc": _mc_now,
                                "vol5": _vol_now,
                                "price5": _price_now,
                                "time": now,
                            }

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
                        SIGNALLED_CAS.add(ca)
                        stats["signal"] += 1
                        global _quality_signal_count, _quality_last_signal_at
                        _quality_signal_count += 1
                        _quality_last_signal_at = now
                        final_score = min(100, result["score"] + momentum)
                        age_text = f'{result["age_hours"]:.1f} saat' if result["age_hours"] is not None else "N/A"

                        signal_title = (
                            "HUNTERELITE FAST LAUNCH GIR"
                            if _fast_launch_ok
                            else "HUNTERELITE CONFIRMED LAUNCH GIR"
                        )
                        message = f"""{signal_title}

{name} ({symbol})
CA: {ca}

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

5dk: {result["buys5"]} buy / {result["sells5"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}

Top-10: {percent(result["top10"])}
Holder Verify: {result.get("holder_source", "N/A")}
Hard Rug Gate: PASSED
Final Gate: PASSED

Risk Score: {result["score"]}/100
Momentum: +{momentum}
Trend Teyidi: {seen_count} tarama / ONAYLI
Launch Teyidi: {"FAST ACCELERATION / ONAYLI" if _fast_launch_ok else "2 asama / DEVAM HAREKETI ONAYLI"}
Runner MC Ivme: {_runner_mc_accel:+.1f}%
Runner Hacim Ivme: {_runner_vol_accel:+.1f}%
1sa fiyat: {percent(result["price1h"])}
6sa fiyat: {percent(result["price6h"])}
Pair yasi: {age_text}
Final Score: {final_score}/100

KARAR: GIR
POTANSIYEL: FILTRELERI GECEN ADAY

UYARI: Kazanc garanti degildir; Axiom'da son kontrol zorunludur.
Axiom'da son kontrolunu yap."""

                    elif (
                        QUALITY_SEND_WATCH
                        and watch_ok
                        and stage == "NEW"
                        and now - last_sent > WATCH_REPEAT_COOLDOWN
                    ):
                        new_stage = "WATCH"
                        stats["watch"] += 1

                        _watch_title = "HUNTERELITE ERKEN IZLE" if _early_watch_ok else "HUNTERELITE IZLE"
                        message = f"""{_watch_title}

{name} ({symbol})
CA: {ca}

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

5dk: {result["buys5"]} buy / {result["sells5"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}

Top-10: {percent(result["top10"])}
Score: {result["score"]}/100
Mint: {"AKTIF" if result.get("mint") is True else ("KAPALI" if result.get("mint") is False else "DOGRULANAMADI")}
Freeze: {"AKTIF" if result.get("freeze") is True else ("KAPALI" if result.get("freeze") is False else "DOGRULANAMADI")}

Potansiyel: {"SAFE PREPUMP / ERKEN" if _early_watch_ok else "IZLE"}
KARAR: {_watch_decision}
GIR BLOCK: {_gir_block}

GIR icin HunterElite teyidini bekle."""

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
                            send_clickable_ca(chat_id, ca)
                            cancelled_this_scan.add(ca)
                        last_sent = now

                    with state_lock:
                        token_states[ca] = {
                            "metrics": result,
                            "stage": new_stage,
                            "last_sent": last_sent,
                            "seen": now,
                            "seen_count": seen_count,
                            "ever_signalled": bool(ca in SIGNALLED_CAS or (previous and previous.get("ever_signalled"))),
                            "launch_pending": None if signal_ok else _next_launch_pending,
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
                    f"RADAR V13.5 | total={stats.get('radar',0)} "
                    f"new={stats.get('unique_new',0)} repeat={stats.get('repeat',0)}\n"
                    f"SOURCES: BIRDEYE={stats.get('src_birdeye',0)} stale={stats.get('src_birdeye_stale',0)} safe={stats.get('src_birdeye_safe',0)} | "
                    f"GECKO={stats.get('src_gecko',0)} stale={stats.get('src_gecko_stale',0)} safe={stats.get('src_gecko_safe',0)} | "
                    f"DEX={stats.get('src_dex',0)} stale={stats.get('src_dex_stale',0)} safe={stats.get('src_dex_safe',0)}\n"
                    f"SOURCE_ACCOUNTED={stats.get('src_birdeye',0)+stats.get('src_gecko',0)+stats.get('src_dex',0)}\n"
                    f"DATA_HEALTH={'DEGRADED' if (stats.get('src_birdeye',0)==0 and stats.get('src_gecko',0)==0) else 'OK'}\n"
                    f"BIRDEYE_FEED={'COOLDOWN' if time.time() < birdeye_cooldown_until else ('OK' if not birdeye_last_error else 'ERR')} "
                    f"cache={len(birdeye_cache)} "
                    f"cooldown={max(0, int(birdeye_cooldown_until-time.time()))}s\n"
                    f"BIRDEYE_ERR={birdeye_last_error[:180] if birdeye_last_error else '-'}\n"
                    f"GECKO_FEED={gecko_last_status} cache={len(gecko_cache)} liq_cache={len(gecko_liq_cache)} "
                    f"retry={max(0,int(gecko_next_retry-time.time()))}s\n"
                    f"GECKO_ERR={gecko_last_error[:180] if gecko_last_error else '-'}\n"
                    f"PIPELINE: pair={stats.get('pair_pass',0)} "
                    f"> MC={stats.get('mc_pass',0)} "
                    f"> LIQ={stats.get('liq_pass',0)} "
                    f"> HOLDER={stats.get('holder_pass',0)}\n"
                    f"LIQ FALLBACK: birdeye_ok={stats.get('liq_fallback_ok',0)} "
                    f"birdeye_missing={stats.get('liq_fallback_missing',0)} | "
                    f"gecko_ok={stats.get('liq_gecko_ok',0)} gecko_missing={stats.get('liq_gecko_missing',0)}\n"
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
                    f"HOLDER RECOVERY: rpc={stats.get('holder_rpc_verified',0)} rugcheck={stats.get('holder_rugcheck_verified',0)}\n"
                    f"HOLDER DISCOVERY: GECKO checked={stats.get('holder_gecko_checked',0)} 82+={stats.get('holder_gecko_82',0)} samples={stats.get('holder_gecko_samples',[])} | DEX checked={stats.get('holder_dex_checked',0)} 82+={stats.get('holder_dex_82',0)} samples={stats.get('holder_dex_samples',[])} | unreliable={stats.get('holder_unreliable',0)}\n"
                    f"SAFETY: RUG_OK={stats.get('rug_ok',0)} "
                    f"> AUTH_OK={stats.get('auth_ok',0)} "
                    f"> CRASH_OK={stats.get('crash_ok',0)} "
                    f"> SAFE={stats.get('safety_pass',0)}\n"
                    f"CRASH BREAKDOWN: AGE_FAIL={stats.get('age_fail',0)} "
                    f"H1_FAIL={stats.get('h1_fail',0)} "
                    f"H6_FAIL={stats.get('h6_fail',0)} "
                    f"H24_FAIL={stats.get('h24_fail',0)}\n"
                    f"SAFE SCORES: samples={stats.get('safe_score_samples',[])} low={stats.get('score_fail_samples',[])}\n"
                    f"WARMUP={'YES' if stats.get('repeat',0) == 0 else 'NO'} "
                    f"AFTER SAFE: SCORE={stats.get('score_pass',0)} "
                    f"> ACTIVITY={stats.get('activity_pass',0)} "
                    f"> TREND={stats.get('trend_pass',0)} "
                    f"> MOMENTUM={stats.get('momentum_pass',0)}\n"
                    f"FINAL GATE REJECTS: {dict(sorted(FINAL_GATE_REJECTS.items(), key=lambda x: -x[1])[:6])}\n"
                    f"QUALITY DETAILS: {dict(sorted(QUALITY_GATE_DETAILS.items(), key=lambda x: -x[1]))}\n"
                    f"WATCH DIAG: {dict(sorted(WATCH_DIAG.items(), key=lambda x: -x[1]))}\n"
                    f"WATCH={stats.get('watch',0)} SIGNAL={stats.get('signal',0)} BREAKOUT={stats.get('breakout',0)} STRONG_GIR={stats.get('strong_gir',0)} "
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
ğŸ¯ Watch Score: {WATCH_SCORE}
ğŸ”¥ Signal Score: {SIGNAL_SCORE}
ğŸ“ˆ Trend teyidi: {TREND_CONFIRM_SCANS} tarama / min momentum {MIN_MOMENTUM_SIGNAL}
ğŸ“¡ Radar: {"BIRDEYE + DEX" if BIRDEYE_API_KEY else "DEX ONLY"}
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
Radar: {"BIRDEYE + DEX" if BIRDEYE_API_KEY else "DEX ONLY"}
Birdeye: {"CONNECTED" if BIRDEYE_API_KEY else "KEY MISSING"}\nBirdeye Fresh: official 20/request + rolling unique cache / 60 sec\nRadar Mix: rolling Birdeye fills first + DEX max 20 fallback
Watch Score: {WATCH_SCORE}
Signal Score: {SIGNAL_SCORE}
Min Liquidity: {money(MIN_LIQUIDITY)}
Mode: {mode}

Early Entry: MC $1K+, Liquidity $800+, Top10 target <=82%\nHard rug/honeypot and authority checks remain active.\n\nV13.5 FRESH RADAR MIX + FAST LAUNCH + CONFIRMED LAUNCH + NO REPEAT + DUMP SHIELD: ACTIVE.\nAutomatic signal engine is running.""")


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
