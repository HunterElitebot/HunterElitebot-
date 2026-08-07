import os
import time
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


def pct(value):
    try:
        v = float(value or 0)
        if v <= 1:
            v *= 100
        return v
    except Exception:
        return 0


def token_age(pair):
    created = pair.get("pairCreatedAt")

    if not created:
        return None, "Bilinmiyor"

    try:
        created_sec = float(created) / 1000
        age_sec = time.time() - created_sec
        minutes = age_sec / 60

        if minutes < 60:
            return minutes, f"{minutes:.0f} dakika"

        hours = minutes / 60
        if hours < 24:
            return minutes, f"{hours:.1f} saat"

        days = hours / 24
        return minutes, f"{days:.1f} gün"

    except Exception:
        return None, "Bilinmiyor"


def get_dex(contract):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        r = requests.get(url, timeout=12)
        r.raise_for_status()

        pairs = r.json().get("pairs") or []

        sol_pairs = [
            p for p in pairs
            if str(p.get("chainId", "")).lower() == "solana"
        ]

        if not sol_pairs:
            return None

        return max(
            sol_pairs,
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


def security_analysis(rug):
    risk = 0
    warnings = []
    positives = []

    top10 = None
    mint_auth = None
    freeze_auth = None

    if not rug:
        warnings.append("⚪ RugCheck verisi alınamadı")
        return risk, warnings, positives, top10, mint_auth, freeze_auth

    mint_auth = rug.get("mintAuthority")
    freeze_auth = rug.get("freezeAuthority")

    if mint_auth:
        risk += 20
        warnings.append("🔴 Mint Authority AKTİF")
    else:
        positives.append("🟢 Mint Authority kapalı")

    if freeze_auth:
        risk += 15
        warnings.append("🔴 Freeze Authority AKTİF")
    else:
        positives.append("🟢 Freeze Authority kapalı")

    holders = rug.get("topHolders") or []

    if holders:
        total = 0

        for holder in holders[:10]:
            value = (
                holder.get("pct")
                or holder.get("percentage")
                or holder.get("percent")
                or 0
            )
            total += pct(value)

        top10 = total

        if total >= 70:
            risk += 30
            warnings.append(f"🔴 Top 10 çok yoğun: %{total:.1f}")
        elif total >= 50:
            risk += 20
            warnings.append(f"🟠 Top 10 yüksek: %{total:.1f}")
        elif total >= 35:
            risk += 10
            warnings.append(f"🟡 Top 10 dikkat: %{total:.1f}")
        else:
            positives.append(f"🟢 Top 10 dağılımı: %{total:.1f}")

    risks = rug.get("risks") or []

    for item in risks[:10]:
        level = str(item.get("level", "")).lower()
        name = item.get("name") or "Güvenlik riski"

        if level in ("danger", "critical"):
            risk += 18
            warnings.append(f"🔴 {name}")

        elif level in ("warn", "warning"):
            risk += 8
            warnings.append(f"🟠 {name}")

    if not risks:
        positives.append("🟢 RugCheck kritik uyarı bildirmedi")

    return risk, warnings, positives, top10, mint_auth, freeze_auth


def calculate_risk(pair, rug):
    risk = 0
    warnings = []
    positives = []

    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    market_cap = pair.get("marketCap") or pair.get("fdv") or 0
    fdv = pair.get("fdv") or 0

    age_minutes, age_text = token_age(pair)

    # TOKEN YAŞI
    if age_minutes is not None:
        if age_minutes < 5:
            risk += 15
            warnings.append("🔴 Token 5 dakikadan yeni")
        elif age_minutes < 15:
            risk += 10
            warnings.append("🟠 Token çok yeni")
        elif age_minutes < 60:
            risk += 5
            warnings.append("🟡 Token 1 saatten genç")
        else:
            positives.append(f"🟢 Token yaşı: {age_text}")

    # LİKİDİTE
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

    # LIQ / MC
    liq_mc_ratio = None

    if market_cap and liquidity:
        liq_mc_ratio = liquidity / market_cap

        if liq_mc_ratio < 0.02:
            risk += 18
            warnings.append("🔴 Likidite / MC oranı çok düşük")
        elif liq_mc_ratio < 0.05:
            risk += 10
            warnings.append("🟠 Likidite / MC oranı düşük")
        elif liq_mc_ratio >= 0.10:
            positives.append(
                f"🟢 Likidite / MC: %{liq_mc_ratio * 100:.1f}"
            )

    # FDV
    if fdv and liquidity:
        liq_fdv_ratio = liquidity / fdv

        if liq_fdv_ratio < 0.01:
            risk += 10
            warnings.append("🟠 Likidite / FDV zayıf")

    # BUY / SELL
    txns = pair.get("txns") or {}
    m5 = txns.get("m5") or {}

    buys = m5.get("buys") or 0
    sells = m5.get("sells") or 0
    total_tx = buys + sells

    if total_tx == 0:
        risk += 8
        warnings.append("🟡 Son 5 dk işlem yok")

    else:
        buy_ratio = buys / total_tx

        if sell_ratio := (sells / total_tx):
            pass

        if buy_ratio < 0.30 and total_tx >= 20:
            risk += 12
            warnings.append("🔴 Satış baskısı yüksek")
        elif buy_ratio < 0.45 and total_tx >= 20:
            risk += 6
            warnings.append("🟡 Satış
