from __future__ import annotations

from typing import Any, Dict, List, Optional

from pump_score import (
    calculate_pump_score,
    calculate_top10,
    calculate_holder_metrics,
    authority_status,
)


def safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_rug_risk(
    token: Dict[str, Any],
    rug: Optional[Dict[str, Any]],
) -> Dict[str, Any]:

    score = 0
    warnings: List[str] = []
    positives: List[str] = []

    liquidity = safe_float(
        token.get("liquidity_usd")
    )

    ratio = token.get(
        "liquidity_mc_ratio"
    )

    if ratio is not None:
        ratio = safe_float(
            ratio
        )

    age = token.get(
        "age_minutes"
    )

    if age is not None:
        age = safe_float(
            age
        )

    buy_ratio = token.get(
        "buy_ratio_5m"
    )

    if buy_ratio is not None:
        buy_ratio = safe_float(
            buy_ratio
        )

    total = int(
        safe_float(
            token.get(
                "total_trades_5m"
            )
        )
    )

    volume_5m = safe_float(
        token.get("volume_5m")
    )

    holder_metrics = (
        calculate_holder_metrics(
            rug
        )
    )

    top1 = holder_metrics.get(
        "top1"
    )

    top5 = holder_metrics.get(
        "top5"
    )

    top10 = holder_metrics.get(
        "top10"
    )

    auth = authority_status(
        rug
    )

    # -------------------------
    # LIQUIDITY RISK
    # -------------------------

    if liquidity < 2_000:

        score += 35

        warnings.append(
            "Likidite aşırı düşük"
        )

    elif liquidity < 5_000:

        score += 30

        warnings.append(
            "Likidite çok düşük"
        )

    elif liquidity < 15_000:

        score += 20

        warnings.append(
            "Likidite düşük"
        )

    elif liquidity < 30_000:

        score += 10

        warnings.append(
            "Likidite orta"
        )

    else:

        positives.append(
            "Likidite güçlü"
        )

    # -------------------------
    # LIQUIDITY / MC RISK
    # -------------------------

    if ratio is not None:

        if ratio < 0.01:

            score += 20

            warnings.append(
                "Likidite/MC aşırı düşük"
            )

        elif ratio < 0.02:

            score += 15

            warnings.append(
                "Likidite/MC çok düşük"
            )

        elif ratio < 0.05:

            score += 8

            warnings.append(
                "Likidite/MC düşük"
            )

        elif ratio >= 0.10:

            positives.append(
                "Likidite/MC güçlü"
            )

    # -------------------------
    # HOLDER RISK
    # -------------------------

    if top10 is None:

        warnings.append(
            "Holder verisi alınamadı"
        )

    else:

        if top10 >= 80:

            score += 30

            warnings.append(
                f"Top 10 tehlikeli: %{top10:.1f}"
            )

        elif top10 >= 70:

            score += 25

            warnings.append(
                f"Top 10 çok yüksek: %{top10:.1f}"
            )

        elif top10 >= 50:

            score += 18

            warnings.append(
                f"Top 10 yüksek: %{top10:.1f}"
            )

        elif top10 >= 35:

            score += 8

            warnings.append(
                f"Top 10 dikkat: %{top10:.1f}"
            )

        else:

            positives.append(
                "Top 10 dağılımı sağlıklı"
            )

    if top5 is not None:

        if top5 >= 50:

            score += 15

            warnings.append(
                f"İlk 5 holder yoğun: %{top5:.1f}"
            )

        elif top5 >= 35:

            score += 8

            warnings.append(
                f"İlk 5 holder dikkat: %{top5:.1f}"
            )

    if top1 is not None:

        if top1 >= 25:

            score += 20

            warnings.append(
                f"Tek holder çok yüksek: %{top1:.1f}"
            )

        elif top1 >= 15:

            score += 12

            warnings.append(
                f"En büyük holder yüksek
