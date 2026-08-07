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
        min(
            score,
            100,
        ),
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


def score_emoji(
    score: int,
) -> str:
    if score >= 80:
        return "🟢"

    if score >= 65:
        return "🟡"

    if score >= 50:
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

    elite = (
        analysis.get("elite")
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

    momentum_score = int(
        pump.get("momentum_score")
        or 0
    )

    holder_score = int(
        pump.get("holder_score")
        or 0
    )

    elite_score = int(
        elite.get("score")
        or 0
    )

    elite_label = str(
        elite.get("label")
        or "Bilinmiyor"
    )

    elite_emoji = str(
        elite.get("emoji")
        or "⚪"
    )

    elite_watch = str(
        elite.get("watch")
        or "Bilinmiyor"
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
        except (
            TypeError,
            ValueError,
        ):
            buy_percent = None

    top1 = rug.get(
        "top1"
    )

    top5 = rug.get(
        "top5"
    )

    top10 = rug.get(
        "top10"
    )

    report = (
        "🛡 HUNTERELITE V4.3\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"🪙 {token.get('name', 'Bilinmiyor')} "
        f"({token.get('symbol', '?')})\n"

        f"⏱ Yaş: {token.get('age_text', 'Bilinmiyor')}\n\n"

        f"{risk_emoji(rug_score)} RUG RİSKİ\n"
        f"{rug_score}/100  {bar(rug_score)}\n"
        f"{rug.get('label', 'Bilinmiyor')}\n\n"

        "🚀 PUMP POTANSİYELİ\n"
        f"{pump_score}/100  {bar(pump_score)}\n"
        f"{pump.get('label', 'Bilinmiyor')}\n\n"

        "⚡ MOMENTUM SCORE\n"
        f"{score_emoji(momentum_score)} "
        f"{momentum_score}/100  "
        f"{bar(momentum_score)}\n"

        f"{pump.get('momentum', 'Bilinmiyor')}\n\n"

        "🐋 HOLDER SCORE\n"
        f"{score_emoji(holder_score)} "
        f"{holder_score}/100  "
        f"{bar(holder_score)}\n"

        f"{pump.get('holder_label', 'Bilinmiyor')}\n\n"

        "👑 ELITE SCORE\n"
        f"{elite_emoji} "
        f"{elite_score}/100  "
        f"{bar(elite_score)}\n"

        f"{elite_label}\n"
        f"🎯 Öncelik: {elite_watch}\n\n"

        "🎯 GENEL GÜVEN\n"
        f"{confidence}/100  "
        f"{bar(confidence)}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        f"{decision.get('emoji', '⚪')} KARAR\n"

        f"{decision.get('decision', 'VERİ YETERSİZ')}\n"

        f"↳ {decision.get('reason', 'Karar üretilemedi')}\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

        "📊 PİYASA VERİSİ\n"

        f"💵 Fiyat: ${token.get('price_usd', 0)}\n"

        f"📈 Market Cap: "
        f"{money(token.get('market_cap_usd'))}\n"

        f"🎯 FDV: "
        f"{money(token.get('fdv_usd'))}\n"

        f"💧 Likidite: "
        f"{money(token.get('liquidity_usd'))}\n"

        f"⚖️ Likidite/MC: "
        f"{ratio_percent(token.get('liquidity_mc_ratio'))}\n\n"

        "📈 İŞLEM AKTİVİTESİ\n"

        f"📦 Hacim 5 dk: "
        f"{money(token.get('volume_5m'))}\n"

        f"📦 Hacim 1 saat: "
        f"{money(token.get('volume_1h'))}\n"

        f"🟢 Buy 5 dk: "
        f"{token.get('buys_5m', 0)}\n"

        f"🔴 Sell 5 dk: "
        f"{token.get('sells_5m', 0)}\n"

        f"📊 Buy oranı: "
        f"{percent(buy_percent)}\n\n"

        "🐋 HOLDER DAĞILIMI\n"

        f"Top 1: {percent(top1)}\n"
        f"Top 5: {percent(top5)}\n"
        f"Top 10: {percent(top10)}\n\n"

        "✅ GÜÇLÜ YANLAR\n"

        f"{clean_lines(analysis.get('positives', []), 8, '•')}\n\n"

        "⚠️ RİSKLER\n"

        f"{clean_lines(analysis.get('warnings', []), 10, '•')}\n\n"

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
