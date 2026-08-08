import os
import asyncio
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TOKEN")
OWNER_ID = os.getenv("OWNER_ID", "").strip()

MC_MIN = 2_000
MC_MAX = 10_000

def money(v):
    try:
        v = float(v or 0)
        if v >= 1_000_000: return f"${v/1_000_000:.2f}M"
        if v >= 1_000: return f"${v/1_000:.2f}K"
        return f"${v:.2f}"
    except:
        return "$0"

def pct(v):
    try: return f"{float(v):.1f}%"
    except: return "N/A"

def dex_pair(ca):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    pairs = r.json().get("pairs") or []
    sol = [p for p in pairs if p.get("chainId") == "solana"]
    if not sol:
        return None
    return max(sol, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))

def rugcheck(ca):
    try:
        r = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report", timeout=15)
        if r.ok:
            return r.json()
    except:
        pass
    return {}

def analyze(ca):
    p = dex_pair(ca)
    if not p:
        return "❌ Solana market/pair bulunamadı."

    liq = float((p.get("liquidity") or {}).get("usd") or 0)
    mc = float(p.get("marketCap") or p.get("fdv") or 0)
    tx = p.get("txns") or {}
    m5 = tx.get("m5") or {}
    h1 = tx.get("h1") or {}
    buys5, sells5 = int(m5.get("buys") or 0), int(m5.get("sells") or 0)
    buys1, sells1 = int(h1.get("buys") or 0), int(h1.get("sells") or 0)
    volume5 = float((p.get("volume") or {}).get("m5") or 0)
    price5 = float((p.get("priceChange") or {}).get("m5") or 0)

    rc = rugcheck(ca)
    risks = rc.get("risks") or []
    risk_text = " ".join(str(x).lower() for x in risks)
    top10 = rc.get("topHoldersPercentage")
    mint = rc.get("mintAuthority")
    freeze = rc.get("freezeAuthority")

    score = 100
    flags = []

    # V9: 2K–10K market-entry gate
    if not (MC_MIN <= mc <= MC_MAX):
        score -= 35
        flags.append("Market cap 2K–10K giriş bölgesi dışında")

    # Liquidity
    if liq < 5_000:
        score -= 35; flags.append("Likidite < $5K")
    elif liq < 15_000:
        score -= 22; flags.append("Likidite düşük")
    elif liq < 30_000:
        score -= 10

    # Holder / authority / RugCheck layer
    try:
        t = float(top10)
        if t >= 60: score -= 25; flags.append("Top-10 holder ≥ %60")
        elif t >= 40: score -= 15; flags.append("Top-10 holder ≥ %40")
    except: pass

    if mint:
        score -= 20; flags.append("Mint authority aktif")
    if freeze:
        score -= 15; flags.append("Freeze authority aktif")

    danger_words = ("honeypot", "rug", "bundl", "insider", "sniper")
    if any(w in risk_text for w in danger_words):
        score -= 20
        flags.append("RugCheck kritik uyarı")

    # Momentum / activity
    if buys5 > sells5 * 1.35 and buys5 >= 8:
        score += 8
    elif sells5 > buys5 * 1.4:
        score -= 12; flags.append("5dk satış baskısı")

    if volume5 < 250:
        score -= 8; flags.append("5dk hacim zayıf")
    if price5 > 80:
        score -= 10; flags.append("5dk aşırı pump")
    if price5 < -25:
        score -= 10; flags.append("5dk sert düşüş")

    score = max(0, min(100, score))

    if MC_MIN <= mc <= MC_MAX and score >= 75:
        verdict = "🟢 UYGUN GİRİŞ ADAYI"
    elif score >= 50:
        verdict = "🟡 BEKLE / DİKKATLİ İNCELE"
    else:
        verdict = "🔴 GİRME / YÜKSEK RİSK"

    name = (p.get("baseToken") or {}).get("name") or "Token"
    symbol = (p.get("baseToken") or {}).get("symbol") or "?"
    flags_s = "\n".join(f"• {x}" for x in flags[:8]) or "• Belirgin kritik sinyal yok"

    return f"""🦅 HUNTERELITE V9

{name} ({symbol})
CA: {ca}

🎯 Market Giriş Bölgesi: $2K–$10K
Market Cap: {money(mc)}
Likidite: {money(liq)}

⚡ 5dk: {buys5} buy / {sells5} sell
📊 1s: {buys1} buy / {sells1} sell
💵 5dk hacim: {money(volume5)}
📈 5dk fiyat: {price5:+.1f}%

🛡 Hunter Elite Score: {score}/100
{verdict}

⚠️ Kontroller:
{flags_s}

Not: Bu rapor risk filtresidir; kâr garantisi değildir."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🦅 HunterEliteBot V9 aktif!\n\n"
        "Solana kontrat adresini gönder.\n"
        "🎯 Ana giriş taraması: $2K–$10K market cap"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ HunterElite V9 ONLINE\n🎯 Market giriş filtresi: $2K–$10K")

async def handle_ca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ca = (update.message.text or "").strip()
    if len(ca) < 30 or " " in ca:
        await update.message.reply_text("Solana kontrat adresini tek satır olarak gönder.")
        return
    msg = await update.message.reply_text("🔎 V9 tarıyor...")
    try:
        result = await asyncio.to_thread(analyze, ca)
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
    print("HUNTERELITE V9 ONLINE")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
