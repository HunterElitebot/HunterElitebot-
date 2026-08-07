from __future__ import annotations

from typing import Any, Dict


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_x100_score(
    token: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:

    rug = analysis.get("rug") or {}
    pump = analysis.get("pump") or {}
    elite = analysis.get("elite") or {}
    gem = analysis.get("gem") or {}

    rug_score = int(
        safe_float(rug.get("score"))
    )

    momentum = int(
        safe_float(
            pump.get("momentum_score")
        )
    )

    holder = int(
        safe_float(
            pump.get("holder_score")
        )
    )

    elite_score = int(
        safe_float(
            elite.get("score")
        )
    )

    gem_score = int(
        safe_float(
            gem.get("score")
        )
    )

    market_cap = safe_float(
        token.get("market_cap_usd")
    )

    liquidity = safe_float(
        token.get("liquidity_usd")
    )

    volume_5m = safe_float(
        token.get("volume_5m")
    )

    age = token.get(
        "age_minutes"
    )

    if age is not None:
        age = safe_float(age)

    security = max(
        0,
        100 - rug_score,
    )

    score = (
        security * 0.22
        + momentum * 0.20
        + holder * 0.18
        + elite_score * 0.20
        + gem_score * 0.20
    )

    # Erken Market Cap bonusu
    if 15_000 <= market_cap <= 150_000:
        score += 8

    elif 150_000 < market_cap <= 400_000:
        score += 3

    elif market_cap > 1_000_000:
        score -= 10

    # Token yaşı
    if age is not None:

        if 5 <= age <= 30:
            score += 6

        elif age < 3:
            score -= 5

        elif age > 360:
            score -= 4

    # Likidite
    if liquidity >= 20_000:
        score += 4

    elif liquidity < 8_000:
        score -= 10

    # Hacim / Likidite dengesi
    if liquidity > 0:

        volume_ratio = (
            volume_5m
            /
            liquidity
        )

        if 0.4 <= volume_ratio <= 2.5:
            score += 4

        elif volume_ratio >= 5:
            score -= 5

    score = int(
        round(
            min(
                max(
                    score,
                    0,
                ),
                100,
            )
        )
    )

    if score >= 90:

        label = "ÇOK YÜKSEK"

    elif score >= 80:

        label = "YÜKSEK"

    elif score >= 70:

        label = "ORTA-YÜKSEK"

    elif score >= 55:

        label = "ORTA"

    elif score >= 40:

        label = "DÜŞÜK"

    else:

        label = "ÇOK DÜŞÜK"

    return {
        "score": score,
        "label": label,
    }
