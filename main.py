import os
import re
import time
import asyncio
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

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"
RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{}/report"

SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


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

    except (TypeError, ValueError):
        return "Bilinmiyor"


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_json(url, timeout=15):

    headers = {
        "User-Agent": "HunterEliteBot/3.1"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=timeout
    )

    response.raise_for_status()

    return response.json()


def get_pair(contract):

    try:

        data = get_json(
            DEX_URL.format(contract),
            timeout=12
        )

        pairs = data.get("pairs") or []

        sol_pairs = [
            pair
            for pair in pairs
            if str(pair.get("chainId", "")).lower() == "solana"
        ]

        if not sol_pairs:
            return None

        return max(
            sol_pairs,
            key=lambda pair: number(
                (pair.get("liquidity") or {}).get("usd")
            )
        )

    except Exception as error:

        print(
            "DEX ERROR:",
            repr(error),
            flush=True
        )

        return None


def get_rugcheck(contract):

    try:

        return get_json(
            RUGCHECK_URL.format(contract),
            timeout=15
        )

    except Exception as error:

        print(
            "RUGCHECK ERROR:",
            repr(error),
            flush=True
        )

        return None


def pair_age(pair):

    created = pair.get("pairCreatedAt")

    if not created:
        return None, "Bilinmiyor"

    try:

        created = float(created)

        if created > 10_000_000_000:
            created /= 1000

        minutes = max(
            (time.time() - created) / 60,
            0
        )

        if minutes < 60:

            return (
                minutes,
                f"{minutes:.0f} dk"
            )

        if minutes < 1440:

            return (
                minutes,
                f"{minutes / 60:.1f} saat"
            )

        return (
            minutes,
            f"{minutes / 1440:.1f} gun"
        )

    except (TypeError, ValueError):

        return None, "Bilinmiyor"


def holder_percent(holder):

    if holder.get("pct") is not None:

        return max(
            number(holder.get("pct")),
            0.0
        )

    for key in (
        "percentage",
        "percent"
    ):

        if holder.get(key) is not None:

            value = max(
                number(holder.get(key)),
                0.0
            )

            if 0 <= value <= 1:
                return value * 100

            return value

    return 0.0


def rug_security(rug):

    risk = 0

    warnings = []

    positives = []

    top10 = None

    mint = None

    freeze = None


    if not rug:

        warnings.append(
            "RugCheck verisi alinamadi"
        )

        return (
            risk,
            warnings,
            positives,
            top10,
            mint,
            freeze
        )


    mint = rug.get(
        "mintAuthority"
    )

    freeze = rug.get(
        "freezeAuthority"
    )


    if mint:

        risk += 20

        warnings.append(
            "Mint Authority AKTIF"
        )

    else:

        positives.append(
            "Mint Authority kapali"
        )


    if freeze:

        risk += 15

        warnings.append(
            "Freeze Authority AKTIF"
        )

    else:

        positives.append(
            "Freeze Authority kapali"
        )


    holders = rug.get(
        "topHolders"
    ) or []


    if holders:

        top10 = sum(
            holder_percent(holder)
            for holder in holders[:10]
        )

        top10 = min(
            top10,
            100.0
        )


        if top10 >= 70:

            risk += 30

            warnings.append(
                f"Top 10 cok yogun: %{top10:.1f}"
            )


        elif top10 >= 50:

            risk += 20

            warnings.append(
                f"Top 10 yuksek: %{top10:.1f}"
            )


        elif top10 >= 35:

            risk += 10

            warnings.append(
                f"Top 10 dikkat: %{top10:.1f}"
            )


        else:

            positives.append(
                f"Top 10 dagilimi iyi: %{top10:.1f}"
            )


    risks = rug.get(
        "risks"
    ) or []


    for item in risks[:10]:

        level = str(
            item.get("level", "")
        ).lower()

        name = str(
            item.get("name")
            or
            "Guvenlik uyarisi"
        )


        if level in (
            "danger",
            "critical"
        ):

            risk += 18

            warnings.append(
                name
            )


        elif level in (
            "warn",
            "warning"
        ):

            risk += 8

            warnings.append(
                name
            )


    if not risks:

        positives.append(
            "RugCheck kritik uyari bildirmedi"
        )


    return (
        risk,
        warnings,
        positives,
        top10,
        mint,
        freeze
    )


def analyze_pair(
    pair,
    rug
):

    risk = 0

    warnings = []

    positives = []


    liquidity = number(
        (pair.get("liquidity") or {}).get("usd")
    )


    market_cap = number(
        pair.get("marketCap")
        or
        pair.get("fdv")
    )


    age_minutes, age_text = pair_age(
        pair
    )


    if age_minutes is not None:

        if age_minutes < 5:

            risk += 15

            warnings.append(
                "Token 5 dakikadan yeni"
            )


        elif age_minutes < 15:

            risk += 10

            warnings.append(
                "Token cok yeni"
            )


        elif age_minutes < 60:

            risk += 5

            warnings.append(
                "Token 1 saatten genc"
            )


        else:

            positives.append(
                f"Token yasi: {age_text}"
            )


    if liquidity < 5000:

        risk += 35

        warnings.append(
            "Likidite cok dusuk"
        )


    elif liquidity < 15000:

        risk += 22

        warnings.append(
            "Likidite dusuk"
        )


    elif liquidity < 30000:

        risk += 10

        warnings.append(
            "Likidite orta"
        )


    else:

        positives.append(
            "Likidite guclu"
        )


    liq_mc_ratio = None


    if market_cap > 0:

        liq_mc_ratio = (
            liquidity /
            market_cap
        )


        if liq_mc_ratio < 0.02:

            risk += 18

            warnings.append(
                "Likidite/MC cok dusuk"
            )


        elif liq_mc_ratio < 0.05:

            risk += 10

            warnings.append(
                "Likidite/MC dusuk"
            )


        elif liq_mc_ratio >= 0.10:

            positives.append(
                f"Likidite/MC iyi: %{liq_mc_ratio * 100:.1f}"
            )


    m5 = (
        pair.get("txns")
        or {}
    ).get(
        "m5"
    ) or {}


    buys = int(
        number(
            m5.get("buys"),
            0
        )
    )


    sells = int(
        number(
            m5.get("sells"),
            0
        )
    )


    total = (
        buys +
        sells
    )


    if total == 0:

        risk += 8

        warnings.append(
            "Son 5 dk islem yok"
        )


    else:

        buy_ratio = (
            buys /
            total
        )


        if (
            buy_ratio < 0.30
            and
            total >= 20
        ):

            risk += 12

            warnings.append(
                "Satis baskisi yuksek"
            )


        elif (
            buy_ratio < 0.45
            and
            total >= 20
        ):

            risk += 6

            warnings.append(
                "Satis baskisi artiyor"
            )


        elif buy_ratio >= 0.60:

            positives.append(
                f"Buy orani iyi: %{buy_ratio * 100:.0f}"
            )


    (
        sec_risk,
        sec_warn,
        sec_pos,
        top10,
        mint,
        freeze

    ) = rug_security(
        rug
    )


    risk += sec_risk

    warnings.extend(
        sec_warn
    )

    positives.extend(
        sec_pos
    )


    return {

        "risk":
        min(
            max(
                int(risk),
                0
            ),
            100
        ),

        "warnings":
        warnings,

        "positives":
        positives,

        "top10":
        top10,

        "mint":
        mint,

        "freeze":
        freeze,

        "age_text":
        age_text,

        "liq_mc_ratio":
        liq_mc_ratio
    }


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.message:

        await update.message.reply_text(

            "🛡 HunterElite Rug Scanner V3 aktif!\n\n"

            "Bir Solana kontrat adresi gonder."
        )


async def analyze(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not update.message
        or
        not update.message.text
    ):

        return


    contract = (
        update.message.text.strip()
    )


    if not SOLANA_ADDRESS_RE.fullmatch(
        contract
    ):

        await update.message.reply_text(

            "Gecerli bir Solana kontrat adresine benzemiyor."
        )

        return


    status = await update.message.reply_text(

        "🔎 HunterElite V3 analiz ediyor..."
    )


    pair, rug = await asyncio.gather(

        asyncio.to_thread(
            get_pair,
            contract
        ),

        asyncio.to_thread(
            get_rugcheck,
            contract
        )
    )


    if not pair:

        await status.edit_text(

            "Bu kontrat icin Solana DEX verisi bulunamadi.\n"

            "Token cok yeniyse birkaç saniye sonra tekrar dene."
        )

        return


    result = analyze_pair(
        pair,
        rug
    )


    token = (
        pair.get("baseToken")
        or {}
    )


    name = str(
        token.get("name")
        or
        "Bilinmiyor"
    )


    symbol = str(
        token.get("symbol")
        or
        "?"
    )


    liquidity = number(

        (
            pair.get("liquidity")
            or {}
        ).get("usd")
    )


    market_cap = number(
        pair.get("marketCap")
    )


    fdv = number(
        pair.get("fdv")
    )


    price = (
        pair.get("priceUsd")
        or
        "?"
    )


    volume = (
        pair.get("volume")
        or {}
    )


    m5 = (
        pair.get("txns")
        or {}
    ).get(
        "m5"
    ) or {}


    buys = int(
        number(
            m5.get("buys"),
            0
        )
    )


    sells = int(
        number(
            m5.get("sells"),
            0
        )
    )


    risk = result[
        "risk"
    ]


    if risk <= 20:

        label = (
            "🟢 DUSUK RISK"
        )


    elif risk <= 40:

        label = (
            "🟡 DIKKATLI INCELE"
        )


    elif risk <= 65:

        label = (
            "🟠 YUKSEK RISK"
        )


    else:

        label = (
            "🔴 COK YUKSEK RISK"
        )


    top10_text = (

        f"%{result['top10']:.1f}"

        if result["top10"] is not None

        else
        "Veri yok"
    )


    ratio_text = (

        f"%{result['liq_mc_ratio'] * 100:.1f}"

        if result["liq_mc_ratio"] is not None

        else
        "Veri yok"
    )


    mint_text = (

        "AKTIF"

        if result["mint"]

        else
        "KAPALI"
    )


    freeze_text = (

        "AKTIF"

        if result["freeze"]

        else
        "KAPALI"
    )


    warnings_text = (

        "\n".join(

            f"• {warning}"

            for warning
            in result["warnings"][:10]
        )

        or

        "• Belirgin uyari yok"
    )


    positives_text = "\n".join(

        f"• {positive}"

        for positive
        in result["positives"][:8]
    )


    text = (

        "🛡 HUNTERELITE RUG SCANNER V3\n\n"

        f"🪙 {name} ({symbol})\n"

        f"⏱ Token yasi: {result['age_text']}\n\n"

        f"💵 Fiyat: ${price}\n"

        f"📊 Market Cap: {money(market_cap)}\n"

        f"🎯 FDV: {money(fdv)}\n"

        f"💧 Likidite: {money(liquidity)}\n"

        f"⚖️ Likidite/MC: {ratio_text}\n"

        f"📈 Hacim 5 dk: {money(volume.get('m5'))}\n"

        f"📈 Hacim 1 saat: {money(volume.get('h1'))}\n\n"

        f"🟢 Buy 5 dk: {buys}\n"

        f"🔴 Sell 5 dk: {sells}\n\n"

        f"🐋 Top 10: {top10_text}\n"

        f"🪙 Mint Authority: {mint_text}\n"

        f"❄️ Freeze Authority: {freeze_text}\n\n"

        f"🎯 HUNTER RISK: {risk}/100\n"

        f"{label}\n\n"

        f"🚨 UYARILAR\n{warnings_text}\n"
    )


    if positives_text:

        text += (

            f"\n✅ POZITIF\n"

            f"{positives_text}\n"
        )


    text += (

        "\n⚠️ Dusuk risk puani tokenin guvenli oldugunu garanti etmez."
    )


    await status.edit_text(
        text[:4000]
    )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        "BOT ERROR:",
        repr(context.error),
        flush=True
    )


def main():

    if not TOKEN:

        raise RuntimeError(

            "Railway TOKEN degiskeni bulunamadi. "
            "Railway > Variables > TOKEN ekle."
        )


    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )


    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    app.add_handler(

        MessageHandler(

            filters.TEXT
            &
            ~filters.COMMAND,

            analyze
        )
    )


    app.add_error_handler(
        error_handler
    )


    print(
        "HunterElite Rug Scanner V3.1 started",
        flush=True
    )


    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
