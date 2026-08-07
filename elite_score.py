from __future__ import annotations

from typing import Any, Dict, List, Optional


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_elite_score(
    token: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:

    rug = analysis.get("rug") or {}
    pump = analysis.get("pump") or {}

    rug_score = int(
        safe_float(
            rug.get("score")
        )
    )

    pump_score = int(
        safe_float(
            pump.get("score")
        )
    )

    momentum_score = int(
        safe_float(
            pump.get("momentum_score")
        )
    )

    holder_score = int(
        safe_float(
            pump.get("holder_score")
        )
    )

    liquidity = safe_float(
        token.get("liquidity_usd")
    )

    market_cap = safe_float(
        token.get("market_cap_usd")
    )

    age = token.get("age_minutes")

    if age is not None:
        age = safe_float(age)

    positives: List[str] = []
    warnings: List[str] = []

    # ------------------------
    # WEIGHTED BASE SCORE
    # ------------------------

    security_score = max(
        0,
        100 - rug_score,
    )

    elite = (
        security_score * 0.30
        +
        pump_score * 0.25
        +
        momentum_score * 0.25
        +
        holder_score * 0.20
    )

    # ------------------------
    # EARLY-STAGE BONUS
    # ------------------------

    early_bonus = 0

    if age is not None:

        if 5 <= age <= 30:

            early_bonus = 5

            positives.append(
                "Erken aşama zamanlaması olumlu"
            )

        elif age < 5:

            warnings.append(
                "Token aşırı yeni"
            )

        elif age > 1440:

            warnings.append(
                "Token artık erken aşamada değil"
            )

    elite += early_bonus

    # ------------------------
    # LIQUIDITY QUALITY
    # ------------------------

    if liquidity >= 50_000:

        elite += 5

        positives.append(
            "Likidite seviyesi güçlü"
        )

    elif liquidity < 5_000:

        elite -= 15

        warnings.append(
            "Likidite kritik derecede düşük"
        )

    elif liquidity < 15_000:

        elite -= 6

        warnings.append(
            "Likidite düşük"
        )

    # ------------------------
    # MC / LIQUIDITY STRUCTURE
    # ------------------------

    if market_cap > 0:

        liq_mc = (
            liquidity /
            market_cap
        )

        if liq_mc >= 0.20:

            elite += 4

            positives.append(
                "Likidite/MC yapısı güçlü"
            )

        elif liq_mc < 0.02:

            elite -= 8

            warnings.append(
                "Likidite/MC yapısı zayıf"
            )

    # ------------------------
    # HARD SAFETY PENALTIES
    # ------------------------

    top1 = rug.get("top1")
    top10 = rug.get("top10")

    if top1 is not None:

        top1 = safe_float(top1)

        if top1 >= 25:

            elite -= 20

            warnings.append(
                "Tek holder konsantrasyonu kritik"
            )

        elif top1 >= 15:

            elite -= 10

            warnings.append(
                "Tek holder konsantrasyonu yüksek"
            )

    if top10 is not None:

        top10 = safe_float(top10)

        if top10 >= 70:

            elite -= 15

            warnings.append(
                "Top 10 yoğunluğu kritik"
            )

        elif top10 >= 50:

            elite -= 8

            warnings.append(
                "Top 10 yoğunluğu yüksek"
            )

    # ------------------------
    # FINAL SCORE
    # ------------------------

    elite = int(
        round(
            min(
                max(
                    elite,
                    0,
                ),
                100,
            )
        )
    )

    if elite >= 85:

        label = "ELITE"

        emoji = "🔥"

    elif elite >= 70:

        label = "GÜÇLÜ"

        emoji = "🟢"

    elif elite >= 55:

        label = "ORTA"

        emoji = "🟡"

    elif elite >= 40:

        label = "ZAYIF"

        emoji = "🟠"

    else:

        label = "RİSKLİ"

        emoji = "🔴"

    # ------------------------
    # WATCH LEVEL
    # ------------------------

    if (
        elite >= 80
        and rug_score <= 25
        and momentum_score >= 70
        and holder_score >= 65
    ):

        watch = "YÜKSEK ÖNCELİK"

    elif (
        elite >= 65
        and rug_score <= 40
    ):

        watch = "TAKİP ET"

    elif elite >= 50:

        watch = "İZLE"

    else:

        watch = "ELE"

    return {
        "score": elite,
        "label": label,
        "emoji": emoji,
        "watch": watch,
        "security_score": security_score,
        "positives": list(
            dict.fromkeys(
                positives
            )
        )[:8],
        "warnings": list(
            dict.fromkeys(
                warnings
            )
        )[:8],
    }
