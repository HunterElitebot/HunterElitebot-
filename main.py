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
        pairs = [
            p for p in pairs
            if str(p.get("chainId", "")).lower() == "solana"
        ]

        if not pairs:
            return None

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


def percent(value):
    try:
        v = float(value or 0)
        if v <= 1:
            v *= 100
        return v
    except Exception:
        return 0


def analyze_security(rug):
    extra_risk = 0
    warnings = []
    positives = []

    if not rug:
        warnings.append("⚪ RugCheck güvenlik verisi alınamadı")
        return extra_risk, warnings, positives, None, None, None

    # Mint / freeze authority
    mint_authority = rug.get("mintAuthority")
    freeze_authority = rug.get("freezeAuthority")

    if mint_authority:
        extra_risk += 20
        warnings.append("🔴 Mint Authority hâlâ aktif")
    else:
        positives.append("🟢 Mint Authority kapalı")

    if freeze_authority:
        extra_risk += 15
        warnings.append("🔴 Freeze Authority hâlâ aktif")
    else:
        positives.append("🟢 Freeze Authority kapalı")

    # Top holders
    holders = rug.get("topHolders") or []

    top10 = 0
    if holders:
        for h in holders[:10]:
            pct = (
                h.get("pct")
                or h.get("percentage")
                or h.get("percent")
                or 0
            )
            top10 += percent(pct)

        if top10 >= 60:
            extra_risk += 25
            warnings.append(
                f"🔴 Top 10 holder çok yoğun: %{top10:.1f}"
            )
        elif top10 >= 40:
            extra_risk += 15
            warnings.append(
                f"🟠 Top 10 holder yoğun: %{top10:.1f}"
            )
        elif top10 > 0:
            positives.append(
                f"🟢 Top 10 holder: %{top10:.1f}"
            )

    # RugCheck kendi riskleri
    risks = rug.get("risks") or []

    for item in risks[:10]:
        level = str(item.get("level", "")).lower()
        name = item.get("name") or "Güvenlik uyarısı"

        if level in ("danger", "critical"):
            extra_risk += 18
            warnings.append(f"🔴 {name}")

        elif level in ("warn", "warning"):
            extra_risk += 8
            warnings.append(f"🟠 {name}")

    if not risks:
        positives.append("🟢 RugCheck kritik uyarı bildirmedi")

    return (
        extra_risk,
        warnings,
        positives,
        top10 if holders else None,
        mint_authority,
        freeze_authority,
    )


def calculate_risk(pair, rug):
    risk = 0
    warnings = []
    positives = []

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
        positives.append("🟢 Likidite güçlü")

    # Liquidity / FDV
    if fdv and liquidity:
        ratio = liquidity / fdv

        if ratio < 0.01:
            risk += 15
            warnings.append("🔴 Likidite / FDV oranı çok zayıf")
        elif ratio < 0.03:
            risk += 8
            warnings.append("🟡 Likidite / FDV oranı düşük")
        elif ratio >= 0.05:
            positives.append("🟢 Likidite / FDV oranı iyi")

    # Buy / Sell
    m5 = (pair.get("txns") or {}).get("m5") or {}
    buys = m5.get("buys") or 0
    sells = m5.get("sells") or 0

    if buys + sells == 0:
        risk += 8
        warnings.append("🟡 Son 5 dakikada işlem yok")

    elif sells > buys * 2 and sells >= 10:
        risk += 10
        warnings.append("🟠 Güçlü satış baskısı")

    security = analyze_security(rug)

    risk += security[0]
    warnings.extend(security[1])
    positives.extend(security[2])

    return (
        min(risk, 100),
        warnings,
        positives,
        security[3],
        security[4],
        security[5],
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡 HunterElite Rug Scanner V2 aktif!\n\n"
        "Bir Solana kontrat adresi gönder.\n\n"
        "V2 kontrolleri:\n"
        "💧 Likidite\n"
        "📊 Market Cap / FDV\n"
        "⚡ Buy / Sell hareketi\n"
        "🐋 Top 10 holder yoğunluğu\n"
        "🪙 Mint Authority\n"
        "❄️ Freeze Authority\n"
        "🚨 RugCheck riskleri\n"
        "🎯 Hunter Risk Score\n\n"
        "⚠️ Sonuç yatırım tavsiyesi değildir."
    )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contract = update.message.text.strip()

    if len(contract) < 32 or len(contract) > 50:
        await update.message.reply_text(
            "❌ Geçerli bir Solana kontrat adresine benzemiyor."
        )
        return

    msg = await update.message.reply_text(
        "🔍 HunterElite V2 tarıyor...\n\n"
        "🐋 Holder dağılımı\n"
        "🔐 Yet
