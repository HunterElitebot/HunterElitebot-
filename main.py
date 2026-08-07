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


def percent_value(value):
    try:
        v = float(value or 0)

        if v <= 1:
            v *= 100

        return v

    except Exception:
        return 0.0


def get_pair(contract):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"

        response = requests.get(
            url,
            timeout=12,
        )

        response.raise_for_status()

        pairs = response.json().get("pairs") or []

        sol_pairs = [
            p
            for p in pairs
            if str(
                p.get(
                    "chainId",
                    "",
                )
            ).lower()
            == "solana"
        ]

        if not sol_pairs:
            return None

        return max(
            sol_pairs,
            key=lambda p: (
                p.get("liquidity") or {}
            ).get("usd")
            or 0,
        )

    except Exception as e:
        print(
            "DEX ERROR:",
            e,
        )

        return None


def get_rugcheck(contract):
    try:
        url = (
            "https://api.rugcheck.xyz/"
            f"v1/tokens/{contract}/report"
        )

        response = requests.get(
            url,
            timeout=15,
        )

        if response.status_code != 200:
            print(
                "RUGCHECK STATUS:",
                response.status_code,
            )

            return None

        return response.json()

    except Exception as e:
        print(
            "RUGCHECK ERROR:",
            e,
        )

        return None


def pair_age(pair):
    created_at = pair.get(
        "pairCreatedAt"
    )

    if not created_at:
        return (
            None,
            "Bilinmiyor",
        )

    try:
        age_seconds = (
            time.time()
            - (
                float(created_at)
                / 1000
            )
        )

        minutes = max(
            age_seconds / 60,
            0,
        )

        if minutes < 60:
            return (
                minutes,
                f"{minutes:.0f} dk",
            )

        hours = minutes / 60

        if hours < 24:
            return (
                minutes,
                f"{hours:.1f} saat",
            )

        days = hours / 24

        return (
            minutes,
            f"{days:.1f} gun",
        )

    except Exception:
        return (
            None,
            "Bilinmiyor",
        )


def security_data(rug):
    result = {
        "risk": 0,
        "warnings": [],
        "positives": [],
        "top10": None,
        "mint": None,
        "freeze": None,
    }

    if not rug:
        result[
            "warnings"
        ].append(
            "RugCheck verisi alinamadi"
        )

        return result

    result["mint"] = rug.get(
        "mintAuthority"
    )

    result["freeze"] = rug.get(
        "freezeAuthority"
    )

    if result["mint"]:
        result["risk"] += 20

        result[
            "warnings"
        ].append(
            "Mint Authority AKTIF"
        )

    else:
        result[
            "positives"
        ].append(
            "Mint Authority kapali"
        )

    if result["freeze"]:
        result["risk"] += 15

        result[
            "warnings"
        ].append(
            "Freeze Authority AKTIF"
        )

    else:
        result[
            "positives"
        ].append(
            "Freeze Authority kapali"
        )

    holders = (
        rug.get("topHolders")
        or []
    )

    if holders:
        top10 = 0.0

        for holder in holders[:10]:
            raw = (
                holder.get("pct")
                or holder.get(
                    "percentage"
                )
                or holder.get(
                    "percent"
                )
                or 0
            )

            top10 += percent_value(
                raw
            )

        result["top10"] = top10

        if top10 >= 70:
            result["risk"] += 30

            result[
                "warnings"
            ].append(
                f"Top 10 cok yogun: %{top10:.1f}"
            )

        elif top10 >= 50:
            result["risk"] += 20

            result[
                "warnings"
            ].append(
                f"Top 10 yuksek: %{top10:.1f}"
            )

        elif top10 >= 35:
            result["risk"] += 10

            result[
                "warnings"
            ].append(
                f"Top 10 dikkat: %{top10:.1f}"
            )

        else:
            result[
                "positives"
            ].append(
                f"Top 10 dagilimi iyi: %{top10:.1f}"
            )

    rug_risks = (
        rug.get("risks")
        or []
    )

    for item in rug_risks[:10]:
        level = str(
            item.get(
                "level",
                "",
            )
        ).lower()

        name = (
            item.get("name")
            or "Guvenlik uyarisi"
        )

        if level in (
            "danger",
            "critical",
        ):
            result["risk"] += 18

            result[
                "warnings"
            ].append(
                name
            )

        elif level in (
            "warn",
            "warning",
        ):
            result["risk"] += 8

            result[
                "warnings"
            ].append(
                name
            )

    if not rug_risks:
        result[
            "positives"
        ].append(
            "RugCheck kritik uyari bildirmedi"
        )

    return result


def calculate_risk(
    pair,
    rug,
):
    risk = 0
    warnings = []
    positives = []

    liquidity = (
        (
            pair.get(
                "liquidity"
            )
            or {}
        ).get(
            "usd"
        )
        or 0
    )

   market_cap = pair.get("marketCap") or 0

fdv = pair.get("fdv") or 0

price = pair.get("priceUsd") or "?"

volume = pair.get("volume") or {}

m5 = (pair.get("txns") or {}).get("m5") or {}

buys = m5.get("buys") or 0
sells = m5.get("sells") or 0 
