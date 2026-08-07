from __future__ import annotations

from typing import Any, Dict, List


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_gem_score(
    token: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:

    rug = analysis.get("rug") or {}
    pump = analysis.get("pump") or {}
    elite = analysis.get("elite") or {}

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

    elite_score = int(
        safe_float(
            elite.get("score")
        )
    )

    liquidity = safe_float(
        token.get("liquidity_usd")
    )

    market_cap = safe_float(
        token.get("market_cap_usd")
    )

    volume_5m = safe_float(
        token.get("volume_5m")
    )

    buys = int(
        safe_float(
            token.get("buys_5m")
        )
    )

    sells = int(
        safe_float(
            token.get("sells_5m")
        )
    )

    age = token.get(
        "age_minutes"
    )

    if age is not None:
        age = safe_float(
            age
        )

    positives: List[str] = []
    warnings: List[str] = []

    security = max(
        0,
        100 - rug_score,
    )

    score = (
        security * 0.20
        +
        pump_score * 0.20
        +
        momentum_score * 0.20
        +
        holder_score * 0.15
        +
        elite_score * 0.25
    )

    # Erken aşama bonusu
    if age is not None:

        if 5 <= age <= 30:

            score += 6

            positives.append(
                "Erken aşama zamanlaması güçlü"
            )

        elif age < 5:

            score -= 5

            warnings.append(
                "Token aşırı yeni"
            )

        elif age > 180:

            score -= 3

            warnings.append(
                "Erken giriş avantajı azalıyor"
            )

    # Market Cap bonusu
    if 20_000 <= market_cap <= 250_000:

        score += 6

        positives.append(
            "Market Cap erken büyüme bölgesinde"
        )

    elif market_cap > 1_000_000:

        score -= 5

        warnings.append(
            "Market Cap artık erken aşama değil"
        )

    # Likidite bonusu
    if liquidity >= 30_000:

        score += 5

        positives.append(
            "Likidite güçlü"
        )

    elif liquidity < 10_000:

        score -= 10

        warnings.append(
            "Likidite yetersiz"
        )

    # İşlem kalitesi
    total = buys + sells

    if total > 0:

        buy_ratio = buys / total

        if buy_ratio >= 0.65:

            score += 5

            positives.append(
                "Alım baskısı güçlü"
            )

        elif buy_ratio < 0.40:

            score -= 8

            warnings.append(
                "Satış baskısı yüksek"
            )

    # Hacim
    if liquidity > 0:

        volume_ratio = (
            volume_5m
            /
            liquidity
        )

        if 0.30 <= volume_ratio <= 2.0:

            score += 4

            positives.append(
                "Hacim/likidite dengesi sağlıklı"
            )

        elif volume_ratio >= 5:

            score -= 6

            warnings.append(
                "Hacim/likidite oranı şüpheli yüksek"
            )

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

        label = "NADİR GEM"

        emoji = "💎"

    elif score >= 80:

        label = "GÜÇLÜ GEM"

        emoji = "🔥"

    elif score >= 70:

        label = "POTANSİYELLİ"

        emoji = "🟢"

    elif score >= 55:

        label = "İZLENEBİLİR"

        emoji = "🟡"

    elif score >= 40:

        label = "ZAYIF"

        emoji = "🟠"

    else:

        label = "ELE"

        emoji = "🔴"

    return {
        "score": score,
        "label": label,
        "emoji": emoji,
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
