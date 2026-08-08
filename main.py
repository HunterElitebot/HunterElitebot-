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

VERSION = "V11.1 WIDE RADAR FINAL"
TOKEN = os.getenv("TOKEN", "").strip()
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "").strip()

MC_MIN = 2000
MC_MAX = 15000
EARLY_MC_MAX = 10000
MIN_LIQUIDITY = 1500
WATCH_SCORE = 55
SIGNAL_SCORE = 70
SCAN_INTERVAL = 40

# V11.1 WIDE RADAR
# Birdeye New Listing costs 30 CU/request. Cache it so Standard quota is not
# consumed every 40-second HunterElite scan.
BIRDEYE_POLL_INTERVAL = 300
BIRDEYE_LIMIT = 20
BIRDEYE_NEW_LISTING = "https://public-api.birdeye.so/defi/v2/tokens/new_listing"

# V10.1 FINAL FIX: only duplicate-watch and hard-drop filtering.
WATCH_REPEAT_COOLDOWN = 21600   # 6 hours
MAX_WATCH_DROP_5M = -10.0
MAX_SIGNAL_DROP_1H = -10.0
MAX_CRASH_DROP_6H = -35.0
MAX_CRASH_DROP_24H = -55.0
MIN_MOMENTUM_SIGNAL = 10
MIN_MC_GROWTH = 1.03
MAX_PAIR_AGE_HOURS = 12.0
TREND_CONFIRM_SCANS = 2
STATE_FILE = "/tmp/hunterelite_v10_1_state.json"

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
        Path(STATE_FILE).write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8"
        )
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
    req_headers = {
        "User-Agent": "HunterElite-V11.1",
        "Accept": "application/json",
    }
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

def send(chat_id, text):
    try:
        telegram("sendMessage", {"chat_id": str(chat_id),"text": str(text)[:4000],"disable_web_page_preview": "true"})
    except Exception as e:
        print("SEND ERROR:", repr(e), flush=True)

def num(value, default=None):
    try:
        if value is None: return default
        return float(value)
    except Exception:
        return default

def safe_int(value):
    try: return int(value or 0)
    except Exception: return 0

def money(value):
    value = num(value)
    if value is None: return "⚠️ VERİ ALINAMADI"
    if abs(value) >= 1_000_000: return f"${value/1_000_000:.2f}M"
    if abs(value) >= 1_000: return f"${value/1_000:.2f}K"
    return f"${value:.2f}"

def percent(value):
    value = num(value)
    if value is None: return "N/A"
    return f"{value:.1f}%"

def dex_pairs(ca):
    urls = [
        f"https://api.dexscreener.com/token-pairs/v1/solana/{ca}",
        f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
    ]
    for url in urls:
        try:
            data = get_json(url)
            if isinstance(data, list): pairs = data
            elif isinstance(data, dict): pairs = data.get("pairs") or []
            else: pairs = []
            sol_pairs = [p for p in pairs if str(p.get("chainId","solana")).lower()=="solana"]
            if sol_pairs: return sol_pairs
        except Exception as e:
            print("DEX PAIR ERROR:", repr(e), flush=True)
    return []

def best_pair(ca):
    pairs = dex_pairs(ca)
    if not pairs: return None
    return max(pairs, key=lambda p: num((p.get("liquidity") or {}).get("usd"), 0))

def extract_birdeye_items(payload):
    """Accept Birdeye response-shape variants without breaking the scanner."""
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


def birdeye_new_candidates(force=False):
    global birdeye_cache, birdeye_last_fetch, birdeye_last_error

    if not BIRDEYE_API_KEY:
        return []

    now = time.time()

    with birdeye_lock:
        if (
            not force
            and birdeye_cache
            and now - birdeye_last_fetch < BIRDEYE_POLL_INTERVAL
        ):
            return list(birdeye_cache)

    params = urllib.parse.urlencode({
        "limit": BIRDEYE_LIMIT,
        "meme_platform_enabled": "true",
    })
    url = f"{BIRDEYE_NEW_LISTING}?{params}"

    try:
        payload = get_json(
            url,
            timeout=15,
            headers={
                "X-API-KEY": BIRDEYE_API_KEY,
                "x-chain": "solana",
            },
        )

        found = []
        seen = set()

        for item in extract_birdeye_items(payload):
            if not isinstance(item, dict):
                continue

            ca = ""
            for key in (
                "address",
                "token_address",
                "tokenAddress",
                "mint",
                "mintAddress",
            ):
                raw = item.get(key)
                if raw:
                    ca = str(raw).strip()
                    break

            if ca and SOL_CA.match(ca) and ca not in seen:
                seen.add(ca)
                found.append(ca)

        with birdeye_lock:
            birdeye_cache = found[:BIRDEYE_LIMIT]
            birdeye_last_fetch = now
            birdeye_last_error = ""

        print(
            f"🟢 BIRDEYE RADAR: {len(found)} yeni Solana adayı",
            flush=True,
        )
        return found[:BIRDEYE_LIMIT]

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


def discovery_candidates():
    endpoints = [
        "https://api.dexscreener.com/token-profiles/latest/v1",
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/token-boosts/top/v1",
        "https://api.dexscreener.com/community-takeovers/latest/v1",
    ]

    found = []
    seen = set()

    # 1) Birdeye fresh Solana listings, including meme-platform launches.
    for ca in birdeye_new_candidates():
        if ca not in seen:
            seen.add(ca)
            found.append(ca)

    # 2) Existing DexScreener discovery radar remains as fallback/supplement.
    for url in endpoints:
        try:
            data = get_json(url)
            if not isinstance(data, list):
                continue

            for item in data:
                if str(item.get("chainId", "")).lower() != "solana":
                    continue

                ca = str(item.get("tokenAddress", "")).strip()
                if ca and SOL_CA.match(ca) and ca not in seen:
                    seen.add(ca)
                    found.append(ca)

        except Exception as e:
            print("DISCOVERY ERROR:", repr(e), flush=True)

    # More candidates than V11, while preserving downstream safety filters.
    return found[:80]


def rugcheck(ca):
    try:
        return get_json(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report")
    except Exception as e:
        print("RUGCHECK ERROR:", repr(e), flush=True)
        return None

def holder_pct(holder):
    if not isinstance(holder, dict): return None
    for key in ("pct","percentage","percent","ownershipPercentage"):
        value = holder.get(key)
        if value is None: continue
        value = num(value)
        if value is None: continue
        if 0 <= value <= 1: value *= 100
        return value
    return None

def holders(report):
    if not report: return None, None, None
    items = report.get("topHolders") or report.get("top_holders") or []
    values = [v for v in (holder_pct(i) for i in items) if v is not None]
    if not values: return None, None, None
    return values[0], sum(values[:5]), sum(values[:10])

def authority(report, key):
    if not report: return None
    values = [report.get(key),(report.get("token") or {}).get(key),(report.get("tokenMeta") or {}).get(key)]
    for value in values:
        if value is None: continue
        if value is False: return False
        if value is True: return True
        text = str(value).strip().lower()
        if text in ("","none","null","false","revoked","disabled"): return False
        return True
    return None

def rug_signals(report):
    result = {"rug":False,"honeypot":False,"insider":False,"sniper":False,"bundler":False}
    if not report: return result
    try: blob = json.dumps(report, ensure_ascii=False).lower()
    except Exception: blob = str(report).lower()
    risks = report.get("risks") or []
    try: risks_blob = json.dumps(risks, ensure_ascii=False).lower()
    except Exception: risks_blob = ""
    if report.get("rugged") is True: result["rug"] = True
    words = {"honeypot":("honeypot",),"insider":("insider",),"sniper":("sniper","sniping"),"bundler":("bundler","bundle")}
    for key, variants in words.items():
        for word in variants:
            if word in risks_blob: result[key] = True
            patterns = [f'"{word}":true',f'"{word}": true',f"{word} detected",f"{word} risk"]
            if any(p in blob for p in patterns): result[key] = True
    if "rug pull" in risks_blob or "rugpull" in risks_blob: result["rug"] = True
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
    m = token_metrics(pair); score = 100; risks = []
    mc, liq = m["mc"], m["liq"]
    if mc is None: score -= 20; risks.append("Market cap verisi yok")
    elif mc < MC_MIN or mc > MC_MAX: score -= 20; risks.append("Market cap hedef bölgesi dışında")
    if liq is None: score -= 25; risks.append("Likidite verisi yok")
    elif liq < 1000: score -= 35; risks.append("Likidite çok düşük")
    elif liq < MIN_LIQUIDITY: score -= 20; risks.append("Likidite düşük")
    top1, top5, top10 = holders(report)
    if report is None: score -= 15; risks.append("RugCheck verisi yok")
    elif top10 is None: score -= 10; risks.append("Holder dağılımı doğrulanamadı")
    else:
        if top10 >= 80: score -= 40; risks.append("Top-10 holder aşırı yoğun")
        elif top10 >= 70: score -= 30; risks.append("Top-10 holder çok yüksek")
        elif top10 >= 60: score -= 20; risks.append("Top-10 holder yüksek")
        elif top10 >= 50: score -= 10; risks.append("Top-10 holder dikkat")
    mint = authority(report, "mintAuthority"); freeze = authority(report, "freezeAuthority")
    if mint is True: score -= 30; risks.append("Mint authority aktif")
    elif mint is None: score -= 5; risks.append("Mint authority doğrulanamadı")
    if freeze is True: score -= 30; risks.append("Freeze authority aktif")
    elif freeze is None: score -= 5; risks.append("Freeze authority doğrulanamadı")
    sig = rug_signals(report)
    if sig["rug"]: score -= 60; risks.append("RUG sinyali")
    if sig["honeypot"]: score -= 50; risks.append("Honeypot sinyali")
    if sig["insider"]: score -= 15; risks.append("Insider sinyali")
    if sig["sniper"]: score -= 10; risks.append("Sniper yoğunluğu")
    if sig["bundler"]: score -= 10; risks.append("Bundler sinyali")
    buys, sells = m["buys5"], m["sells5"]
    if buys + sells >= 10 and sells > buys * 1.5: score -= 10; risks.append("5dk satış baskısı")
    if m["price5"] is not None and m["price5"] <= -25: score -= 10; risks.append("5dk sert fiyat düşüşü")
    score = max(0, min(100, int(score)))
    severe = sig["rug"] or sig["honeypot"] or mint is True or freeze is True or (top10 is not None and top10 >= 80)
    if severe: decision = "🔴 GİRME"
    elif score >= 75 and mc is not None and MC_MIN <= mc <= EARLY_MC_MAX: decision = "🟢 UYGUN GİRİŞ"
    elif score >= 55: decision = "🟡 BEKLE"
    else: decision = "🔴 GİRME"
    return {**m,"score":score,"decision":decision,"risks":risks,"top1":top1,"top5":top5,"top10":top10,"mint":mint,"freeze":freeze,"signals":sig}

def momentum_score(old, new):
    if not old: return 0
    points = 0
    old_buys, new_buys = old.get("buys5",0), new.get("buys5",0)
    if old_buys > 0 and new_buys >= old_buys * 1.4: points += 10
    old_vol, new_vol = old.get("vol5") or 0, new.get("vol5") or 0
    if old_vol > 0 and new_vol >= old_vol * 1.35: points += 10
    old_mc, new_mc = old.get("mc") or 0, new.get("mc") or 0
    if old_mc > 0 and new_mc > old_mc * 1.08: points += 5
    buys, sells = new.get("buys5",0), new.get("sells5",0)
    if buys >= 8 and buys >= max(sells * 1.5, 1): points += 10
    p5 = new.get("price5")
    if p5 is not None and 2 <= p5 <= 40: points += 5
    return points

def authority_text(value):
    if value is True: return "🚨 AKTİF"
    if value is False: return "✅ KAPALI"
    return "⚠️ N/A"

def analyse(ca):
    pair = best_pair(ca)
    if pair is None:
        return None, f"🦅 HUNTERELITE {VERSION}\n\nCA: {ca}\n\n❌ DEX pair verisi bulunamadı.\n\n🔴 GİRME / VERİ BEKLE"
    report = rugcheck(ca); result = calculate_score(pair, report)
    base = pair.get("baseToken") or {}; name = base.get("name") or "Unknown"; symbol = base.get("symbol") or "N/A"
    text = f"""🦅 HUNTERELITE {VERSION}

{name} ({symbol})
CA: {ca}

🎯 Market Giriş Bölgesi: $2K–$10K

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

⚡ 5dk: {result["buys5"]} buy / {result["sells5"]} sell
📊 1s: {result["buys1h"]} buy / {result["sells1h"]} sell

💵 5dk hacim: {money(result["vol5"])}
📈 5dk fiyat: {percent(result["price5"])}

🧪 RugCheck Derin Kontrol

RugCheck: {"✅ ALINDI" if report else "⚠️ VERİ ALINAMADI"}

Top-1 holder: {percent(result["top1"])}
Top-5 holder: {percent(result["top5"])}
Top-10 holder: {percent(result["top10"])}

Mint authority: {authority_text(result["mint"])}
Freeze authority: {authority_text(result["freeze"])}

🛡 Hunter Elite Score: {result["score"]}/100

🎯 Karar: {result["decision"]}"""
    if result["risks"]:
        text += "\n\n⚠️ Riskler:\n" + "".join(f"• {r}\n" for r in result["risks"][:7])
    text += "\nEksik veri güvenli kabul edilmez.\nBu sistem risk filtresidir, yatırım garantisi değildir."
    return result, text

def basic_signal_safe(result):
    if not result: return False
    if result["signals"]["rug"] or result["signals"]["honeypot"]: return False
    if result["mint"] is True or result["freeze"] is True: return False
    if result["mc"] is None or not (MC_MIN <= result["mc"] <= MC_MAX): return False
    if result["liq"] is None or result["liq"] < MIN_LIQUIDITY: return False
    if result["top10"] is not None and result["top10"] >= 70: return False
    return True

def crash_guard(result):
    if not result:
        return False

    p1 = result.get("price1h")
    p6 = result.get("price6h")
    p24 = result.get("price24h")
    age = result.get("age_hours")

    if p1 is not None and p1 < MAX_SIGNAL_DROP_1H:
        return False
    if p6 is not None and p6 < MAX_CRASH_DROP_6H:
        return False
    if p24 is not None and p24 < MAX_CRASH_DROP_24H:
        return False
    if age is not None and age > MAX_PAIR_AGE_HOURS:
        return False

    return True


def trend_confirmed(previous, current):
    if not previous or not current:
        return False

    old_mc = previous.get("mc") or 0
    new_mc = current.get("mc") or 0
    if old_mc <= 0 or new_mc < old_mc * MIN_MC_GROWTH:
        return False

    if current.get("price5") is None or current["price5"] <= 0:
        return False

    if current.get("buys5", 0) < previous.get("buys5", 0):
        return False

    old_vol = previous.get("vol5")
    new_vol = current.get("vol5")
    if old_vol is not None and new_vol is not None and new_vol < old_vol * 1.05:
        return False

    return True


def watch_candidate(result):
    if not basic_signal_safe(result): return False
    if not crash_guard(result): return False
    if result["score"] < WATCH_SCORE: return False
    if result["buys5"] < 5: return False
    if result["vol5"] is not None and result["vol5"] < 250: return False
    if result["price5"] is not None and result["price5"] < MAX_WATCH_DROP_5M: return False
    return True


def strong_signal(result, momentum, previous=None):
    if not basic_signal_safe(result): return False
    if not crash_guard(result): return False
    if previous is None: return False
    if momentum < MIN_MOMENTUM_SIGNAL: return False
    if not trend_confirmed(previous, result): return False
    if result["score"] + momentum < SIGNAL_SCORE: return False
    if result["mc"] > EARLY_MC_MAX: return False

    buys, sells = result["buys5"], result["sells5"]
    if buys < 8: return False
    if sells > 0 and buys < sells * 1.35: return False
    if result["vol5"] is not None and result["vol5"] < 500: return False

    return True


def auto_scanner():
    print("🚨 EARLY HUNTER SCANNER ACTIVE", flush=True)
    print(
        "📡 WIDE RADAR: BIRDEYE + DEXSCREENER"
        if BIRDEYE_API_KEY
        else "⚠️ WIDE RADAR: BIRDEYE KEY YOK, DEX ONLY",
        flush=True,
    )
    time.sleep(10)
    while True:
        try:
            if not signal_chats:
                time.sleep(SCAN_INTERVAL); continue
            for ca in discovery_candidates():
                try:
                    pair = best_pair(ca)
                    if pair is None: continue
                    report = rugcheck(ca)
                    result = calculate_score(pair, report)
                    now = time.time()
                    with state_lock: previous = token_states.get(ca)
                    old_metrics = previous.get("metrics") if previous else None
                    momentum = momentum_score(old_metrics, result)
                    seen_count = (previous.get("seen_count", 0) + 1) if previous else 1
                    stage = previous.get("stage","NEW") if previous else "NEW"
                    last_sent = previous.get("last_sent",0) if previous else 0
                    new_stage, message = stage, None
                    base = pair.get("baseToken") or {}; name = base.get("name","Unknown"); symbol = base.get("symbol","N/A")
                    if seen_count >= TREND_CONFIRM_SCANS and strong_signal(result, momentum, old_metrics) and stage != "SIGNAL":
                        new_stage = "SIGNAL"
                        final_score = min(100, result["score"] + momentum)
                        age_text = f'{result["age_hours"]:.1f} saat' if result["age_hours"] is not None else "N/A"
                        message = f"""🚨 HUNTERELITE EARLY SIGNAL

{name} ({symbol})
CA: {ca}

💎 Market Cap: {money(result["mc"])}
💧 Likidite: {money(result["liq"])}

⚡ 5dk: {result["buys5"]} buy / {result["sells5"]} sell
💵 5dk hacim: {money(result["vol5"])}
📈 5dk fiyat: {percent(result["price5"])}

👥 Top-10: {percent(result["top10"])}

🛡 Risk Score: {result["score"]}/100
🚀 Momentum: +{momentum}
📈 1s fiyat: {percent(result["price1h"])}
📊 6s fiyat: {percent(result["price6h"])}
⏱ Pair yaşı: {age_text}
🎯 Final Score: {final_score}/100

🔥 DURUM: ERKEN MOMENTUM

⚠️ Otomatik sinyal alım emri değildir.
Axiom'da son kontrolünü yap."""
                    elif watch_candidate(result) and stage == "NEW" and now - last_sent > WATCH_REPEAT_COOLDOWN:
                        new_stage = "WATCH"
                        message = f"""👀 HUNTERELITE İZLE

{name} ({symbol})
CA: {ca}

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}

5dk: {result["buys5"]} buy / {result["sells5"]} sell
5dk hacim: {money(result["vol5"])}
5dk fiyat: {percent(result["price5"])}

Top-10: {percent(result["top10"])}

Score: {result["score"]}/100

⏳ Momentum teyidi bekleniyor."""
                    if stage == "SIGNAL" and not basic_signal_safe(result):
                        new_stage = "CANCELLED"
                        message = f"""⚠️ HUNTERELITE SİNYAL İPTAL

CA: {ca}

Risk şartları kötüleşti.

Market Cap: {money(result["mc"])}
Likidite: {money(result["liq"])}
Top-10: {percent(result["top10"])}
Score: {result["score"]}/100

🔴 Yeni giriş için uygun değil."""
                    if message:
                        for chat_id in list(signal_chats): send(chat_id, message)
                        last_sent = now
                    with state_lock:
                        token_states[ca] = {"metrics":result,"stage":new_stage,"last_sent":last_sent,"seen":now,"seen_count":seen_count}
                    save_state()
                    time.sleep(1)
                except Exception as e:
                    print("TOKEN SCAN ERROR:", ca, repr(e), flush=True)
            cutoff = time.time() - 21600
            with state_lock:
                for ca in [k for k,v in token_states.items() if v.get("seen",0) < cutoff]:
                    token_states.pop(ca, None)
        except Exception as e:
            print("SCANNER ERROR:", repr(e), flush=True)
        time.sleep(SCAN_INTERVAL)

def process_message(message):
    chat = message.get("chat") or {}; chat_id = chat.get("id")
    text = str(message.get("text","")).strip()
    if chat_id is None or not text: return
    command = text.split()[0].lower().split("@")[0]
    if command == "/start":
        signal_chats.add(int(chat_id))
        send(chat_id, f"""✅ HunterElite {VERSION} ONLINE

🎯 Early Hunter: AKTİF
🎯 Market bölgesi: $2K–$10K
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
/help"""); return
    if command == "/ping":
        send(chat_id, f"🏓 PONG — HunterElite {VERSION} ONLINE"); return
    if command == "/status":
        active = int(chat_id) in signal_chats
        send(chat_id, f"""✅ HunterElite {VERSION} ONLINE

🔎 Manuel analiz: AKTİF
🚨 Early Hunter: {"AKTİF" if active else "KAPALI"}
⏱ Tarama: {SCAN_INTERVAL} sn
🎯 Watch Score: {WATCH_SCORE}
🔥 Signal Score: {SIGNAL_SCORE}
📈 Trend teyidi: {TREND_CONFIRM_SCANS} tarama / min momentum {MIN_MOMENTUM_SIGNAL}
📡 Radar: {"BIRDEYE + DEX" if BIRDEYE_API_KEY else "DEX ONLY"}
🟢 Birdeye API: {"BAĞLI" if BIRDEYE_API_KEY else "KEY YOK"}
⏱ Birdeye yenileme: {BIRDEYE_POLL_INTERVAL} sn
💧 Min Likidite: {money(MIN_LIQUIDITY)}
📊 Market: $2K–$10K öncelikli"""); return
    if command == "/signal_on":
        signal_chats.add(int(chat_id)); send(chat_id, "🚨 HunterElite otomatik sinyal AKTİF.\nEarly Hunter taraması başladı."); return
    if command == "/signal_off":
        signal_chats.discard(int(chat_id)); send(chat_id, "🔕 Otomatik sinyal KAPALI."); return
    if command == "/signal_test":
        signal_chats.add(int(chat_id))
        send(chat_id, f"""✅ HUNTERELITE TEST SİNYALİ

{VERSION}

📡 Telegram kanalı: ÇALIŞIYOR
🚨 Otomatik sinyal: AKTİF
🔎 Manuel analiz: AKTİF
🔥 Early Hunter: AKTİF

Gerçek aday taraması başladı."""); return
    if command == "/help":
        send(chat_id, "HunterElite V11.1 WIDE RADAR\n\nCA gönder → manuel analiz\n\n/ping\n/status\n/signal_on\n/signal_off\n/signal_test\n/start"); return
    ca = text
    if not SOL_CA.match(ca):
        matches = re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text)
        ca = matches[0] if matches else ""
    if ca and SOL_CA.match(ca):
        send(chat_id, "🔎 Token analiz ediliyor...")
        try:
            _, report = analyse(ca); send(chat_id, report)
        except Exception as e:
            print("ANALYSIS ERROR:", repr(e), flush=True); send(chat_id, "❌ Analiz sırasında veri hatası oluştu.")
        return
    send(chat_id, "Solana kontrat adresini gönder veya /help yaz.")

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"HunterElite {VERSION} ONLINE".encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, format, *args): return

def health_server():
    port = int(os.getenv("PORT","8080"))
    try: HTTPServer(("0.0.0.0",port), Health).serve_forever()
    except Exception as e: print("HEALTH ERROR:", repr(e), flush=True)

def startup():
    print(f"✅ HUNTERELITE {VERSION} ONLINE", flush=True)
    print("🎯 MANUAL ANALYSIS ACTIVE", flush=True)
    print("🚨 EARLY HUNTER ACTIVE", flush=True)
    print(f"⏱ SCAN INTERVAL: {SCAN_INTERVAL}s", flush=True)
    print(
        f"🎛 TUNING: momentum>={MIN_MOMENTUM_SIGNAL}, MC growth>={int((MIN_MC_GROWTH-1)*100)}%, pair age<={MAX_PAIR_AGE_HOURS:.0f}h",
        flush=True,
    )
    print(
        f"🟢 BIRDEYE API KEY: {'READY' if BIRDEYE_API_KEY else 'MISSING'}",
        flush=True,
    )
    try: telegram("deleteWebhook", {"drop_pending_updates":"false"})
    except Exception as e: print("WEBHOOK CLEAN WARNING:", repr(e), flush=True)

def polling():
    offset = None
    while True:
        try:
            data = {"timeout":25,"allowed_updates":json.dumps(["message"])}
            if offset is not None: data["offset"] = offset
            response = telegram("getUpdates", data, timeout=35)
            for update in response.get("result", []):
                update_id = update.get("update_id")
                if update_id is not None: offset = update_id + 1
                message = update.get("message")
                if message: process_message(message)
        except urllib.error.HTTPError as e:
            try: body = e.read().decode("utf-8", errors="replace")
            except Exception: body = ""
            print("TELEGRAM HTTP ERROR:", e.code, body, flush=True); time.sleep(3)
        except Exception as e:
            print("POLL ERROR:", repr(e), flush=True); time.sleep(3)

if __name__ == "__main__":
    load_state()
    threading.Thread(target=health_server, daemon=True).start()
    startup()
    threading.Thread(target=auto_scanner, daemon=True).start()
    polling()
