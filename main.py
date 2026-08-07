import os
import requests

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TOKEN")


def money(value):
    try:
        value = float(value or 0)

        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"${value / 1_000:.1f}K"

        return f"${value:.2f}"
    except Exception:
        return "Bilinmiyor"


def get_dex(contract):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"

        r = requests.get(url, timeout=12)
        r.raise_for_status()

        pairs = r.json().get("pairs") or []

        # Sadece Solana pairleri
        pairs = [
            p for p in pairs
            if str(p.get("chainId", "")).lower() == "solana"
        ]

        if not pairs:
            return None

        # En yüksek likiditeli pair
        return max(
            pairs,
            key=lambda p: (p.get("liquidity") or {}).get("usd") or 0
        )

    except Exception as e:
        print("DEX ERROR:", e)
        return None


def get_rugcheck(contract):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{contract}/report"

        r = requests.get(url, timeout=15)

        if r.status_code != 200:
            print("RUGCHECK STATUS:", r.status_code)
            return None

        return r.json()

    except Exception as e:
        print("RUGCHECK ERROR:", e)
        return None


def risk_score(pair, rug):
    risk = 0
    warnings = []
    good = []

    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    fdv = pair.get("fdv") or 0

    # Likidite
    if liquidity < 5_000:
        risk += 35
        warnings.append("🔴 Likidite çok düşük")
    elif liquidity < 15_000:
        risk += 22
        warnings.append("🟠 Likidite düşük")
    elif liquidity < 30_000:
        risk += 10
        warnings.append("🟡 Likidite orta")
    else:
        good.append("🟢 Likidite seviyesi iyi")

    # Likidite / FDV
    if fdv and liquidity:
        ratio = liquidity / fdv

        if ratio < 0.01:
            risk += 15
            warnings.append("🟠 Likidite / FDV oranı zayıf")
        elif ratio >= 0.05:
            good.append("🟢 Likidite / FDV oranı iyi")

    # İşlem hareketi
    m5 = (pair.get("txns") or {}).get("m5") or {}

    buys = m5.get("buys") or 0
    sells = m5.get("sells") or 0

    if buys + sells == 0:
        risk += 8
        warnings.append("🟡 Son 5 dk işlem yok")

    if sells > buys * 2 and sells >= 10:
        risk += 10
        warnings.append("🟠 Güçlü satış baskısı")

    # RugCheck
    if rug:
        risks = rug.get("risks") or []

        for item in risks[:8]:
            level = str(item.get("level", "")).lower()
            name = item.get("name") or "Güvenlik uyarısı"

            if level in ("danger", "critical"):
                risk += 20
                warnings.append(f"🔴 {name}")

            elif level in ("warn", "warning"):
                risk += 10
                warnings.append(f"🟠 {name}")

        if not risks:
            good.append("🟢 RugCheck kritik uyarı bildirmedi")
    else:
        warnings.append("⚪ RugCheck verisi alınamadı")

    return min(risk, 100), warnings, good


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡 HunterElite Rug Scanner V1 aktif!\n\n"
        "Bir Solana kontrat adresi gönder.\n\n"
        "Kontrol edeceğim:\n"
        "💧 Likidite\n"
        "📊 Market Cap / FDV\n"
        "⚡ Alım-satım hareketi\n"
        "🚨 RugCheck uyarıları\n"
        "🎯 Risk puanı\n\n"
        "⚠️ Bu sistem yatırım tavsiyesi değildir."
    )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contract = update.message.text.strip()

    if len(contract) < 32 or len(contract) > 50:
        await update.message.reply_text(
            "❌ Bu metin geçerli bir Solana kontrat adresine benzemiyor."
        )
        return

    msg = await update.message.reply_text(
        "🔍 HunterElite tarıyor...\n\n"
        "Dex ve güvenlik verileri kontrol ediliyor."
    )

    pair = get_dex(contract)

    if not pair:
        await msg.edit_text(
            "❌ Bu kontrat için Solana DEX verisi bulunamadı.\n\n"
            "Adres yanlış olabilir veya token henüz işlem görmüyor olabilir."
        )
        return

    rug = get_rugcheck(contract)

    risk, warnings, good = risk_score(pair, rug)

    token = pair.get("baseToken") or {}

    name = token.get("name") or "Bilinmiyor"
    symbol = token.get("symbol") or "?"

    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    market_cap = pair.get("marketCap") or 0
    fdv = pair.get("fdv") or 0
    price = pair.get("priceUsd") or "?"

    volume = pair.get("volume") or {}
    volume_5m = volume.get("m5") or 0
    volume_1h = volume.get("h1") or 0

    m5 = (pair.get("txns") or {}).get("m5") or {}
    buys = m5.get("buys") or 0
    sells = m5.get("sells") or 0

    if risk <= 20:
        label = "🟢 DÜŞÜK RİSK"
    elif risk <= 45:
        label = "🟡 ORTA RİSK"
    elif risk <= 70:
        label = "🟠 YÜKSEK RİSK"
    else:
        label = "🔴 ÇOK YÜKSEK RİSK"

    warning_text = "\n".join(warnings[:8]) or "✅ Belirgin uyarı bulunamadı."
    good_text = "\n".join(good[:5])

    text = (
        "🛡 HUNTERELITE RUG SCANNER\n\n"
        f"🪙 {name} ({symbol})\n\n"
        f"💵 Fiyat: ${price}\n"
        f"📊 Market Cap: {money(market_cap)}\n"
        f"🎯 FDV: {money(fdv)}\n"
        f"💧 Likidite: {money(liquidity)}\n\n"
        f"📈 Hacim 5 dk: {money(volume_5m)}\n"
        f"📈 Hacim 1 saat: {money(volume_1h)}\n\n"
        "⚡ SON 5 DK\n"
        f"🟢 Buy: {buys}\n"
        f"🔴 Sell: {sells}\n\n"
        "━━━━━━━━━━━━━━\n"
        f"🚨 Rug Risk: {risk}/100\n"
        f"{label}\n"
        "━━━━━━━━━━━━━━\n\n"
        f"⚠️ UYARILAR\n{warning_text}\n"
    )

    if good_text:
        text += f"\n✅ POZİTİF\n{good_text}\n"

    text += (
        "\nℹ️ 0 puan risksiz anlamına gelmez. "
        "Bot yalnızca erişebildiği güncel verileri değerlendirir."
    )

    await msg.edit_text(text)


if not TOKEN:
    raise RuntimeError(
        "Railway Variables içinde TOKEN bulunamadı."
    )


app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, analyze)
)

print("HunterElite Rug Scanner started")

app.run_polling()
