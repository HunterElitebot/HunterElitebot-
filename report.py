from __future__ import annotations

from typing import Any, Dict, Optional


def money(value: Any) -> str:
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return "Bilinmiyor"

    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"

    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"

    if value >= 1_000:
        return f"${value / 1_000:.1f}K"

    return f"${value:.2f}"


def percent(
    value: Optional[float],
    digits: int = 1,
) -> str:
    if value is None:
        return "Veri yok"

    try:
        return f"%{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "Veri yok"


def ratio_percent(
    value: Optional[float],
) -> str:
    if value is None:
        return "Veri yok"

    try:
        return f"%{float(value) * 100:.1f}"
    except (TypeError, ValueError):
        return "Veri yok"


def bar(
    score: int,
    blocks: int = 10,
) -> str:
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0

    score = max(
        0,
        min(score, 100),
    )

    filled = round(
        score / 100 * blocks
    )

    return (
        "█" * filled
        +
        "░" * (blocks - filled)
    )


def risk_emoji(
    score: int,
) -> str:
    if score <= 20:
        return "🟢"

    if score <= 40:
        return "🟡"

    if score <= 65:
        return "🟠"

    return "🔴"


def pump_emoji(
    score: int,
) -> str:
    if score >= 80:
        return "🚀"

    if score >= 65:
        return "🟢"

    if score >= 50:
        return "🟡"

    if score >= 35:
        return "🟠"

    return "🔴"


def clean_lines(
    items: list,
    limit: int,
    prefix: str,
) -> str:
    output = []
    seen = set()

    for item in items or []:
        text = str(
            item
        ).strip()

        if not text:
            continue

        if text in seen:
            continue

        seen.add(
            text
        )

        output.append(
            f"{prefix} {text}"
        )

        if len(output) >= limit:
            break

    if not output:
        return f"{prefix} Veri yok"

    return "\n".join(
        output
    )


def build_report(
    token: Dict[str, Any],
    analysis: Dict[str, Any],
) -> str:

    rug = (
        analysis.get("rug")
        or {}
    )

    pump = (
        analysis.get("pump")
        or {}
    )

    decision = (
        analysis.get("decision")
        or {}
    )

    rug_score = int(
        rug.get("score")
        or 0
    )

    pump_score = int(
        pump.get("score")
        or 0
    )

    confidence = int(
        analysis.get("confidence")
        or 0
    )

    buy_ratio = token.get(
        "buy_ratio_5m"
    )

    buy_percent = None

    if buy_ratio is not None:
        try:
            buy_percent = (
                float(buy_ratio)
                *
                100
            )
        except (TypeError, ValueError):
            buy_percent = None

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

    report = (
        "🛡 HUNTERELITE V4.1\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"🪙 {name} ({symbol})\n"
        f"⏱ Yaş: {token.get('age_text', 'Bilinmiyor')}\n\n"

        f"{risk_emoji(rug_score)} RUG RİSKİ\n"
        f"{rug_score}/100  {bar(rug_score)}\n"
        f"{rug.get('label', 'Bilinmiyor')}\n\n"

        f"{pump_emoji(pump_score)} PUMP POTANSİYELİ\n"
        f"{pump_score}/100  {bar(pump_score)}\n"
        f"{pump.get('label', 'Bilinmiyor')}\n\n"

        "🎯 GÜVEN SKORU\n"
        f"{confidence}/100  {bar(confidence)}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        f"{decision.get('emoji', '⚪')} KARAR\n"
        f"{decision.get('decision', 'VERİ YETERSİZ')}\n"
        f"↳ {decision.get('reason', 'Karar üretilemedi')}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "📊 PİYASA VERİSİ\n"
        f"💵 Fiyat: ${token.get('price_usd', 0)}\n"
        f"📈 Market Cap: {money(token.get('market_cap_usd'))}\n"
        f"🎯 FDV: {money(token.get('fdv_usd'))}\n"
        f"💧 Likidite: {money(token.get('liquidity_usd'))}\n"
        f"⚖️ Likidite/MC: {ratio_percent(token.get('liquidity_mc_ratio'))}\n\n"

        "⚡ MOMENTUM\n"
        f"Durum: {pump.get('momentum', 'Bilinmiyor')}\n"
        f"📦 Hacim 5 dk: {money(token.get('volume_5m'))}\n"
        f"📦 Hacim 1 saat: {money(token.get('volume_1h'))}\n"
        f"🟢 Buy 5 dk: {token.get('buys_5m', 0)}\n"
        f"🔴 Sell 5 dk: {token.get('sells_5m', 0)}\n"
        f"📊 Buy oranı: {percent(buy_percent)}\n\n"

        "🐋 HOLDER ANALİZİ\n"
        f"Top 10: {percent(rug.get('top10'))}\n\n"

        "✅ GÜÇLÜ YANLAR\n"
        f"{clean_lines(analysis.get('positives', []), 7, '•')}\n\n"

        "⚠️ RİSKLER\n"
        f"{clean_lines(analysis.get('warnings', []), 9, '•')}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ HunterElite filtreleme aracıdır; "
        "skorlar yatırım garantisi değildir."
    )

    return report[:4000]


def build_scan_error(
    errors: list,
) -> str:
    return (
        "❌ HunterElite taraması tamamlanamadı.\n\n"
        f"{clean_lines(errors, 6, '•')}\n\n"
        "Token çok yeniyse birkaç saniye sonra tekrar dene."
    )
