from __future__ import annotations

from typing import Any, Dict, List, Optional

from pump_score import (
    calculate_pump_score,
    calculate_holder_metrics,
    authority_status,
)
from elite_score import calculate_elite_score
from gem_score import calculate_gem_score
from x100_score import calculate_x100_score
from trade_plan import build_trade_plan


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

    if ratio is not None:

        if ratio < 0.01:

            score += 20

            warnings.append(
                "Likidite/MC aşırı düşük"
            )

        elif ratio < 0.02:

            score += 15
