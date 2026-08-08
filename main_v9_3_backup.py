import os
import re
import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

VERSION = "V9.3"
TOKEN = os.getenv("TOKEN", "").strip()

MC_MIN = 2000
MC_MAX = 10000

if not TOKEN:
    raise RuntimeError("Railway TOKEN variable bulunamadi!")

TG_API = f"https://api.telegram.org/bot{TOKEN}"

SOL_CA = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


# =========================================================
# HTTP
# =========================================================

def get_json(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "HunterElite-V9.3",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post_telegram(method, data=None, timeout=35):
    data = data or {}

    body = urllib.parse.urlencode(data).encode()

    req = urllib.request.Request(
        f"{TG_API}/{method}",
        data=body,
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send(chat_id, text):
    try:
        post_telegram(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:4000],
                "disable_web_page_preview": "true",
            },
        )
    except Exception as e:
        print("SEND ERROR:", e, flush=True)


# =========================================================
# FORMAT
# =========================================================

def money(value):
    if value is None:
        return "⚠️ VERİ ALINAMADI"

    try:
        value = float(value)
    except:
        return "⚠️ VERİ ALINAMADI"

    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"

    if value >= 1_000:
        return f"${value / 1_000:.2f}K"

    return f"${value:.2f}"


def percent(value):
    if value is None:
        return "N/A"

    try:
        return f"{float(value):.1f}%"
    except:
        return "N/A"


def safe_int(value):
    try:
        return int(value or 0)
    except:
        return 0


# =========================================================
# DEXSCREENER
# =========================================================

def dex_data(ca):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        data = get_json(url)

        pairs = data.get("pairs") or []

        sol_pairs = [
            p for p in pairs
            if str(p.get("chainId", "")).lower() == "solana"
        ]

        if not sol_pairs:
            return None

        def liquidity(pair):
            try:
                return float(
                    (pair.get("liquidity") or {}).get("usd") or 0
                )
            except:
                return 0

        return max(sol_pairs, key=liquidity)

    except Exception as e:
        print("DEX ERROR:", e, flush=True)
        return None


# =========================================================
# RUGCHECK
# =========================================================

def rugcheck(ca):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{ca}/report"
        return get_json(url)

    except Exception as e:
        print("RUGCHECK ERROR:", e, flush=True)
        return None


def holder_percentage(holder):
    if not isinstance(holder, dict):
        return None

    for key in ["pct", "percentage", "percent"]:
        value = holder.get(key)

        if value is not None:
            try:
                value = float(value)

                if value <= 1:
                    value *= 100

                return value

            except:
                pass

    return None


def top_holders(report):
    if not report:
        return None, None, None

    holders = report.get("topHolders") or []

    values = []

    for holder in holders:
        value = holder_percentage(holder)

        if value is not None:
            values.append(value)

    if not values:
        return None, None, None

    top1 = values[0] if values else None
    top5 = sum(values[:5])
    top10 = sum(values[:10])

    return top1, top5, top10


def authority(report, key):
    if not report:
        return None

    value = report.get(key)

    if value is None:
        token = report.get("token") or {}
        value = token.get(key)

    if value is None:
        return None

    if value is False:
        return False

    if value is True:
        return True

    text = str(value).lower().strip()

    if text in ["", "none", "null", "false", "revoked"]:
        return False

    return True


# =========================================================
# SCORE
# =========================================================

def score_token(pair, rug):
    score = 100
    risks = []

    market_cap = pair.get("marketCap")

    if market_cap is None:
        market_cap = pair.get("fdv")

    liquidity = (pair.get("liquidity") or {}).get("usd")

    try:
        mc = float(market_cap)
    except:
        mc = None

    try:
        liq = float(liquidity)
    except:
        liq = None

    if mc is None:
        score -= 15
        risks.append("Market cap verisi yok")

    elif not MC_MIN <= mc <= MC_MAX:
        score -= 20
        risks.append("Market cap giriş bölgesi dışında")

    if liq is None:
        score -= 20
        risks.append("Likidite verisi yok")

    elif liq < 1000:
        score -= 30
        risks.append("Likidite çok düşük")

    elif liq < 2000:
        score -= 15
        risks.append("Likidite düşük")

    top1, top5, top10 = top_holders(rug)

    if rug is None:
        score -= 15
        risks.append("RugCheck verisi yok")

    elif top10 is None:
        score -= 10
        risks.append("Holder verisi yok")

    else:
        if top10 >= 80:
            score -= 35
            risks.append("Top-10 holder aşırı yüksek")

        elif top10 >= 70:
            score -= 28
            risks.append("Top-10 holder çok yüksek")

        elif top10 >= 55:
            score -= 18
            risks.append("Top-10 holder yüksek")

    mint = authority(rug, "mintAuthority")
    freeze = authority(rug, "freezeAuthority")

    if mint is True:
        score -= 25
        risks.append("Mint authority aktif")

    elif mint is None:
        score -= 5
        risks.append("Mint authority doğrulanamadı")

    if freeze is True:
        score -= 25
        risks.append("Freeze authority aktif")

    elif freeze is None:
        score -= 5
        risks.append("Freeze authority doğrulanamadı")

    score = max(0, min(100, score))

    if score >= 75 and mc is not None and MC_MIN <= mc <= MC_MAX:
        decision = "🟢 UYGUN GİRİŞ"

    elif score >= 55:
        decision = "🟡 BEKLE"

    else:
        decision = "🔴 GİRME"

    return {
        "score": score,
        "decision": decision,
        "market_cap": mc,
        "liquidity": liq,
        "top1": top1,
        "top5": top5,
        "top10": top10,
        "mint": mint,
        "freeze": freeze,
        "risks": risks,
    }


def auth_text(value):
    if value is True:
        return "🚨 AKTİF"

    if value is False:
        return "✅ KAPALI"

    return "⚠️ N/A"


# =========================================================
# ANALYSIS
# =========================================================

def analyse(ca):
    pair = dex_data(ca)

    if not pair:
        return (
            f"🦅 HUNTERELITE {VERSION}\n\n"
            f"CA: {ca}\n\n"
            "❌ DEX verisi bulunamadı.\n\n"
            "🔴 GİRME / VERİ BEKLE"
        )

    rug = rugcheck(ca)

    result = score_token(pair, rug)

    base = pair.get("baseToken") or {}

    name = base.get("name") or "Unknown"
    symbol = base.get("symbol") or "N/A"

    tx = pair.get("txns") or {}

    tx5 = tx.get("m5") or {}
    tx1 = tx.get("h1") or {}

    volume = pair.get("volume") or {}
    price = pair.get("priceChange") or {}

    report = f"""🦅 HUNTERELITE {VERSION}

{name} ({symbol})

CA: {ca}

🎯 Market Giriş Bölgesi: $2K–$10K

Market Cap: {money(result["market_cap"])}
Likidite: {money(result["liquidity"])}

⚡ 5dk: {safe_int(tx5.get("buys"))} buy / {safe_int(tx5.get("sells"))} sell

📊 1s: {safe_int(tx1.get("buys"))} buy / {safe_int(tx1.get("sells"))} sell

💵 5dk hacim: {money(volume.get("m5"))}

📈 5dk fiyat: {percent(price.get("m5"))}

🧪 RugCheck Derin Kontrol

RugCheck: {"✅ ALINDI" if rug else "⚠️ VERİ ALINAMADI"}

Top-1 holder: {percent(result["top1"])}
Top-5 holder: {percent(result["top5"])}
Top-10 holder: {percent(result["top10"])}

Mint authority: {auth_text(result["mint"])}
Freeze authority: {auth_text(result["freeze"])}

🛡 Hunter Elite Score: {result["score"]}/100

🎯 Karar: {result["decision"]}
"""

    if result["risks"]:
        report += "\n⚠️ Riskler:\n"

        for risk in result["risks"][:6]:
            report += f"• {risk}\n"

    report += (
        "\nEksik veri güvenli kabul edilmez.\n"
        "Bu sistem risk filtresidir, yatırım garantisi değildir."
    )

    return report


# =========================================================
# TELEGRAM
# =========================================================

def process_message(message):
    chat = message.get("chat") or {}

    chat_id = chat.get("id")

    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return

    command = text.split()[0].lower().split("@")[0]

    if command == "/start":
        send(
            chat_id,
            f"""✅ HunterElite {VERSION} ONLINE

🎯 Market giriş filtresi: $2K–$10K

📡 Eksik veri koruması: AKTİF

🧪 RugCheck kontrolü: AKTİF

Solana kontrat adresini gönder.

Komutlar:
/ping
/status
/help"""
        )

        return

    if command == "/ping":
        send(
            chat_id,
            f"🏓 PONG — HunterElite {VERSION} ONLINE"
        )

        return

    if command == "/status":
        send(
            chat_id,
            f"""✅ HunterElite {VERSION} ONLINE

🎯 Market filtresi: $2K–$10K

📡 Telegram: AKTİF

🧪 DEX + RugCheck: AKTİF"""
        )

        return

    if command == "/help":
        send(
            chat_id,
            """HunterElite kullanımı:

Solana kontrat adresini direkt gönder.

/ping
/status
/start"""
        )

        return

    ca = text

    if not SOL_CA.match(ca):
        found = re.findall(
            r"[1-9A-HJ-NP-Za-km-z]{32,44}",
            text,
        )

        ca = found[0] if found else ""

    if ca and SOL_CA.match(ca):
        send(chat_id, "🔎 Token analiz ediliyor...")

        try:
            send(chat_id, analyse(ca))

        except Exception as e:
            print("ANALYSIS ERROR:", e, flush=True)

            send(
                chat_id,
                "❌ Analiz sırasında veri hatası oluştu."
            )

    else:
        send(
            chat_id,
            "Solana kontrat adresini gönder veya /help yaz."
        )


# =========================================================
# RAILWAY HEALTH
# =========================================================

class Health(BaseHTTPRequestHandler):

    def do_GET(self):
        body = f"HunterElite {VERSION} ONLINE".encode()

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def health_server():
    port = int(os.getenv("PORT", "8080"))

    try:
        server = HTTPServer(
            ("0.0.0.0", port),
            Health,
        )

        server.serve_forever()

    except Exception as e:
        print("HEALTH ERROR:", e, flush=True)


# =========================================================
# STARTUP
# =========================================================

def startup():
    print(
        f"✅ HUNTERELITE {VERSION} ONLINE",
        flush=True,
    )

    print(
        "🎯 Market giriş filtresi: $2K–$10K",
        flush=True,
    )

    try:
        post_telegram(
            "deleteWebhook",
            {"drop_pending_updates": "false"},
        )

    except Exception as e:
        print(
            "WEBHOOK CLEAN WARNING:",
            e,
            flush=True,
        )


def polling():
    offset = None

    while True:

        try:
            data = {
                "timeout": 25,
                "allowed_updates": json.dumps(
                    ["message"]
                ),
            }

            if offset is not None:
                data["offset"] = offset

            result = post_telegram(
                "getUpdates",
                data,
                timeout=35,
            )

            for update in result.get("result", []):

                update_id = update.get("update_id")

                if update_id is not None:
                    offset = update_id + 1

                message = update.get("message")

                if message:
                    process_message(message)

        except urllib.error.HTTPError as e:

            try:
                body = e.read().decode()
            except:
                body = ""

            print(
                "TELEGRAM HTTP ERROR:",
                e.code,
                body,
                flush=True,
            )

            time.sleep(3)

        except Exception as e:

            print(
                "POLL ERROR:",
                e,
                flush=True,
            )

            time.sleep(3)


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    threading.Thread(
        target=health_server,
        daemon=True,
    ).start()

    startup()

    polling()
