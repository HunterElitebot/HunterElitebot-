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

    elite = (
        analysis.get("elite")
        or {}
    )

    gem = (
        analysis.get("gem")
        or {}
    )

    x100 = (
        analysis.get("x100")
        or {}
    )

    decision = (
        analysis.get("decision")
        or {}
    )

    plan = (
        analysis.get("trade_plan")
        or {}
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

    report = (
        "🛡 HUNTERELITE V5 FINAL\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"🪙 {token.get('name', 'Bilinmiyor')} "
        f"({token.get('symbol', '?')})\n"

        f"⏱ Yaş: {token.get('age_text', 'Bilinmiyor')}\n\n"

        f"🛡 RUG RİSKİ\n"
        f"{rug.get('score', 0)}/100  "
        f"{bar(rug.get('score', 0))}\n"
        f"{rug.get('label', 'Bilinmiyor')}\n\n"

        f"🚀 PUMP POTANSİYELİ\n"
        f"{pump.get('score', 0)}/100  "
        f"{bar(pump.get('score', 0))}\n"
        f"{pump.get('label', 'Bilinmiyor')}\n\n"

        f"⚡ MOMENTUM SCORE\n"
        f"{pump.get('momentum_score', 0)}/100  "
        f"{bar(pump.get('momentum_score', 0))}\n"
        f"{pump.get('momentum', 'Bilinmiyor')}\n\n"

        f"🐋 HOLDER SCORE\n"
        f"{pump.get('holder_score', 0)}/100  "
        f"{bar(pump.get('holder_score', 0))}\n"
        f"{pump.get('holder_label', 'Bilinmiyor')}\n\n"

        f"👑 ELITE SCORE\n"
        f"{elite.get('emoji', '⚪')} "
        f"{elite.get('score', 0)}/100  "
        f"{bar(elite.get('score', 0))}\n"
        f"{elite.get('label', 'Bilinmiyor')}\n"
        f"🎯 Öncelik: {elite.get('watch', 'Bilinmiyor')}\n\n"

        f"💎 GEM SCORE\n"
        f"{gem.get('emoji', '⚪')} "
        f"{gem.get('score', 0)}/100  "
        f"{bar(gem.get('score', 0))}\n"
        f"{gem.get('label', 'Bilinmiyor')}\n\n"

        f"🔥 100X POTANSİYEL\n"
        f"{x100.get('score', 0)}/100  "
        f"{bar(x100.get('score', 0))}\n"
        f"{x100.get('label', 'Bilinmiyor')}\n\n"

        f"🎯 GENEL GÜVEN\n"
        f"{analysis.get('confidence', 0)}/100  "
        f"{bar(analysis.get('confidence', 0))}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        f"{decision.get('emoji', '⚪')} KARAR\n"
        f"{decision.get('decision', 'VERİ YETERSİZ')}\n"
        f"↳ {decision.get('reason', 'Karar üretilemedi')}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🎯 TRADE PLAN\n"
        f"Durum: {plan.get('status', 'VERİ YOK')}\n"

        f"🟢 Giriş Bölgesi: "
        f"{money(plan.get('entry_low'))} - "
        f"{money(plan.get('entry_high'))} MC\n"

        f"🛑 Stop: "
        f"{money(plan.get('stop'))} MC\n"

        f"🥉 TP1: "
        f"{money(plan.get('tp1'))} MC\n"

        f"🥈 TP2: "
        f"{money(plan.get('tp2'))} MC\n"

        f"🥇 TP3: "
        f"{money(plan.get('tp3'))} MC\n\n"

        "📊 PİYASA VERİSİ\n"

        f"💵 Fiyat: "
        f"${token.get('price_usd', 0)}\n"

        f"📈 Market Cap: "
        f"{money(token.get('market_cap_usd'))}\n"

        f"🎯 FDV: "
        f"{money(token.get('fdv_usd'))}\n"

        f"💧 Likidite: "
        f"{money(token.get('liquidity_usd'))}\n"

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

        f"Top 1: "
        f"{percent(rug.get('top1'))}\n"

        f"Top 5: "
        f"{percent(rug.get('top5'))}\n"

        f"Top 10: "
        f"{percent(rug.get('top10'))}\n\n"

        "✅ GÜÇLÜ YANLAR\n"

        f"{clean_lines(analysis.get('positives', []), 7, '•')}\n\n"

        "⚠️ RİSKLER\n"

        f"{clean_lines(analysis.get('warnings', []), 9, '•')}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"

        "⚠️ HunterElite filtreleme ve karar destek aracıdır. "
        "100X skoru ve Trade Plan garanti değildir."
    )

    return report[:4000]


def build_alert_report(
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

    elite = (
        analysis.get("elite")
        or {}
    )

    gem = (
        analysis.get("gem")
        or {}
    )

    x100 = (
        analysis.get("x100")
        or {}
    )

    plan = (
        analysis.get("trade_plan")
        or {}
    )

    return (
        "🚨 HUNTER ALERT\n\n"

        f"🪙 {token.get('name', 'Bilinmiyor')} "
        f"({token.get('symbol', '?')})\n"

        f"📈 MC: "
        f"{money(token.get('market_cap_usd'))}\n"

        f"💧 Likidite: "
        f"{money(token.get('liquidity_usd'))}\n"

        f"⏱ Yaş: "
        f"{token.get('age_text', 'Bilinmiyor')}\n\n"

        f"🛡 Rug: "
        f"{rug.get('score', 0)}/100\n"

        f"⚡ Momentum: "
        f"{pump.get('momentum_score', 0)}/100\n"

        f"🐋 Holder: "
        f"{pump.get('holder_score', 0)}/100\n"

        f"👑 Elite: "
        f"{elite.get('score', 0)}/100\n"

        f"💎 Gem: "
        f"{gem.get('score', 0)}/100\n"

        f"🔥 100X: "
        f"{x100.get('score', 0)}/100\n\n"

        f"🎯 {plan.get('status', 'İZLE')}\n\n"

        f"🟢 Giriş: "
        f"{money(plan.get('entry_low'))} - "
        f"{money(plan.get('entry_high'))} MC\n"

        f"🛑 Stop: "
        f"{money(plan.get('stop'))} MC\n"

        f"🥉 TP1: "
        f"{money(plan.get('tp1'))} MC\n"

        f"🥈 TP2: "
        f"{money(plan.get('tp2'))} MC\n"

        f"🥇 TP3: "
        f"{money(plan.get('tp3'))} MC\n\n"

        "⚠️ Alarm güçlü aday filtresidir; "
        "kesin alım sinyali değildir."
    )[:4000]


def build_scan_error(
    errors: list,
) -> str:

    return (
        "❌ HunterElite taraması tamamlanamadı.\n\n"
        f"{clean_lines(errors, 6, '•')}"
    )
