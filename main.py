import os
import asyncio
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TOKEN")
OWNER_ID = os.getenv("OWNER_ID", "").strip()

MC_MIN = 2_000
MC_MAX = 10_000

def as_float(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None

def money(v):
    if v is None:
        return "⚠️ VERİ ALINAMADI"
    try:
        v = float(v)
        if v >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v/1_000:.2f}K"
        return f"${v:.2f}"
    except (TypeError, ValueError):
        return "⚠️ VERİ ALINAMADI"

def dex_pairs(ca):
    # Güncel DEX Screener token endpoint'i.
    url = f"https://api.dexscreener.com/tokens/v1/solana/{ca}"
    r = requests.get(url, timeout=12, headers={"Accept": "application/json"})
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict) and p.get("chainId") == "solana"]

def choose_pair(pairs):
    if not pairs:
        return None

    def rank(p):
        liq = as_float((p.get("liquidity") or {}).get("usd"))
        vol = as_float((p.get("volume") or {}).get("h24"))
        return (liq if liq is not None else -1, vol if vol is not None else -1)

    return max(pairs, key=rank)

def rugcheck(ca):
    try:
        r = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report", timeout=15)
        if r.ok:
            data = r.json()
            if isinstance(data, dict):
                return data, True
    except requests.RequestException:
        pass
    except ValueError:
        pass
    return {}, False

def analyze(ca):
    pairs = dex_pairs(ca)
    p = choose_pair(pairs)
    if not p:
        return "❌ Solana market/pair bulunamadı."

    liq = as_float((p.get("liquidity") or {}).get("usd"))
    market_cap_raw = as_float(p.get("marketCap"))
    fdv = as_float(p.get("fdv"))
    mc = market_cap_raw if market_cap_raw is not None else fdv

    tx = p.get("txns") or {}
    m5 = tx.get("m5") or {}
    h1 = tx.get("h1") or {}
    buys5 = int(as_float(m5.get("buys")) or 0)
    sells5 = int(as_float(m5.get("sells")) or 0)
    buys1 = int(as_float(h1.get("buys")) or 0)
    sells1 = int(as_float(h1.get("sells")) or 0)
    volume5 = as_float((p.get("volume") or {}).get("m5"))
    price5 = as_float((p.get("priceChange") or {}).get("m5"))

    rc, rug_ok = rugcheck(ca)
    risks = rc.get("risks") or []
    risk_text = " ".join(str(x).lower() for x in risks)

    top10 = as_float(rc.get("topHoldersPercentage"))
    mint = rc.get("mintAuthority")
    freeze = rc.get("freezeAuthority")

    score = 100
    flags = []
    data_warnings = []

    # Market-cap gate
    if mc is None:
        score -= 20
        data_warnings.append("Market cap/FDV verisi alınamadı")
    elif not (MC_MIN <= mc <= MC_MAX):
        score -= 35
        flags.append("Market cap 2K–10K giriş bölgesi dışında")

    # Liquidity: V9.1'de None ile gerçek 0 ayrılır.
    if liq is None:
        score -= 20
        data_warnings.append("Likidite verisi alınamadı")
    elif liq == 0:
        score -= 40
        flags.append("Likidite gerçek $0")
    elif liq < 5_000:
        score -= 35
        flags.append("Likidite < $5K")
    elif liq < 15_000:
        score -= 22
        flags.append("Likidite düşük")
    elif liq < 30_000:
        score -= 10

    # RugCheck / holder / authority
    if not rug_ok:
        score -= 10
        data_warnings.append("RugCheck verisi alınamadı")
    else:
        if top10 is None:
            data_warnings.append("Top-10 holder yüzdesi API yanıtında yok")
        elif top10 >= 60:
            score -= 25
            flags.append("Top-10 holder ≥ %60")
        elif top10 >= 40:
            score -= 15
            flags.append("Top-10 holder ≥ %40")

        if mint:
            score -= 20
            flags.append("Mint authority aktif")
        if freeze:
            score -= 15
            flags.append("Freeze authority aktif")

        danger_words = ("honeypot", "rug", "bundl", "insider", "sniper")
        if any(w in risk_text for w in danger_words):
            score -= 20
            flags.append("RugCheck kritik uyarı")

    # Momentum / activity
    if buys5 > sells5 * 1.35 and buys5 >= 8:
        score += 8
    elif sells5 > buys5 * 1.4:
        score -= 12
        flags.append("5dk satış baskısı")

    if volume5 is None:
        data_warnings.append("5dk hacim verisi alınamadı")
    elif volume5 < 250:
        score -= 8
        flags.append("5dk hacim zayıf")

    if price5 is None:
        data_warnings.append("5dk fiyat değişimi alınamadı")
    else:
        if price5 > 80:
            score -= 10
            flags.append("5dk aşırı pump")
        if price5 < -25:
            score -= 10
            flags.append("5dk sert düşüş")

    score = max(0, min(100, score))

    # Kritik veri eksikse yeşil sonuç verme.
    critical_missing = mc is None or liq is None or not rug_ok
    if critical_missing:
        verdict = "🟡 BEKLE / KRİTİK VERİ EKSİK"
    elif MC_MIN <= mc <= MC_MAX and score >= 75:
        verdict = "🟢 UYGUN GİRİŞ ADAYI"
    elif score >= 50:
        verdict = "🟡 BEKLE / DİKKATLİ İNCELE"
    else:
        verdict = "🔴 GİRME / YÜKSEK RİSK"

    name = (p.get("baseToken") or {}).get("name") or "Token"
    symbol = (p.get("baseToken") or {}).get("symbol") or "?"
    flags_s = "\n".join(f"• {x}" for x in flags[:8]) or "• Belirgin kritik risk sinyali yok"
    warnings_s = "\n".join(f"• {x}" for x in data_warnings[:8]) or "• Kritik veri eksiği yok"

    top10_text = f"%{top10:.1f}" if top10 is not None else "N/A"
    rug_text = "✅ ALINDI" if rug_ok else "⚠️ ALINAMADI"
    price_text = f"{price5:+.1f}%" if price5 is not None else "N/A"

    return f"""🦅 HUNTERELITE V9.1

{name} ({symbol})
CA: {ca}

🎯 Market Giriş Bölgesi: $2K–$10K
Market Cap: {money(mc)}
Likidite: {money(liq)}

⚡ 5dk: {buys5} buy / {sells5} sell
📊 1s: {buys1} buy / {sells1} sell
💵 5dk hacim: {money(volume5)}
📈 5dk fiyat: {price_text}

🧪 Veri Kontrolü
DEX Pair: ✅ ALINDI
RugCheck: {rug_text}
Top-10 holder: {top10_text}

🛡 Hunter Elite Score: {score}/100
{verdict}

⚠️ Riskler:
{flags_s}

📡 Veri Durumu:
{warnings_s}

Not: Bu rapor risk filtresidir; kâr garantisi değildir."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🦅 HunterEliteBot V9.1 aktif!\n\n"
        "Solana kontrat adresini gönder.\n"
        "🎯 Ana giriş taraması: $2K–$10K market cap"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ HunterElite V9.1 ONLINE\n"
        "🎯 Market giriş filtresi: $2K–$10K\n"
        "📡 Eksik veri koruması: AKTİF"
    )

async def handle_ca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ca = (update.message.text or "").strip()
    if len(ca) < 30 or " " in ca:
        await update.message.reply_text("Solana kontrat adresini tek satır olarak gönder.")
        return

    msg = await update.message.reply_text("🔎 V9.1 tarıyor...")
    try:
        result = await asyncio.to_thread(analyze, ca)
    except requests.RequestException:
        result = "❌ DEX/API bağlantı hatası. Biraz sonra tekrar dene."
    except Exception as e:
        result = f"❌ Analiz hatası: {type(e).__name__}"

    await msg.edit_text(result)

def main():
    if not TOKEN:
        raise RuntimeError("Railway Variables içinde TOKEN eksik.")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ca))

    print("HUNTERELITE V9.1 ONLINE")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
