from __future__ import annotations

from typing import Any, Dict, List, Optional

from pump_score import (
    calculate_pump_score,
    calculate_holder_metrics,
    authority_status,
)
from elite_score import calculate_elite_score
from gem_score import calculate_gem_score


def safe_float(value: Any, default: float = 0.0) -> float:
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
    # LIQUIDITY / MC
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

    elif top10 >= 80:

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
                f"En büyük holder yüksek: %{top1:.1f}"
            )

        elif top1 < 10:

            positives.append(
                "En büyük holder payı düşük"
            )

    # -------------------------
    # AUTHORITY RISK
    # -------------------------

    if auth["mint_closed"] is False:

        score += 20

        warnings.append(
            "Mint Authority AKTİF"
        )

    elif auth["mint_closed"] is True:

        positives.append(
            "Mint Authority kapalı"
        )

    if auth["freeze_closed"] is False:

        score += 15

        warnings.append(
            "Freeze Authority AKTİF"
        )

    elif auth["freeze_closed"] is True:

        positives.append(
            "Freeze Authority kapalı"
        )

    # -------------------------
    # TOKEN AGE
    # -------------------------

    if age is not None:

        if age < 3:

            score += 18

            warnings.append(
                "Token aşırı yeni"
            )

        elif age < 10:

            score += 12

            warnings.append(
                "Token çok yeni"
            )

        elif age < 30:

            score += 6

            warnings.append(
                "Token erken aşamada"
            )

        elif age > 1440:

            positives.append(
                "Token ilk gün riskini geçmiş"
            )

    # -------------------------
    # BUY / SELL PRESSURE
    # -------------------------

    if total <= 0:

        score += 8

        warnings.append(
            "Son 5 dk işlem yok"
        )

    elif (
        buy_ratio is not None
        and total >= 20
    ):

        if buy_ratio < 0.25:

            score += 15

            warnings.append(
                "Çok güçlü satış baskısı"
            )

        elif buy_ratio < 0.35:

            score += 10

            warnings.append(
                "Satış baskısı yüksek"
            )

        elif buy_ratio < 0.45:

            score += 5

            warnings.append(
                "Satış tarafı baskın"
            )

        elif buy_ratio >= 0.60:

            positives.append(
                "Alım baskısı güçlü"
            )

    # -------------------------
    # SUSPICIOUS VOLUME
    # -------------------------

    if liquidity > 0:

        abnormal_ratio = (
            volume_5m
            /
            liquidity
        )

        if (
            abnormal_ratio >= 5
            and total >= 100
        ):

            score += 12

            warnings.append(
                "Hacim/likidite anormal yüksek"
            )

        elif (
            abnormal_ratio >= 3
            and total >= 50
        ):

            score += 7

            warnings.append(
                "Hacim olağandışı yüksek"
            )

    # -------------------------
    # RUGCHECK WARNINGS
    # -------------------------

    if rug:

        risks = (
            rug.get("risks")
            or []
        )

        if isinstance(
            risks,
            list,
        ):

            extra_risk = 0

            for item in risks[:15]:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                level = str(
                    item.get("level")
                    or ""
                ).lower()

                name = str(
                    item.get("name")
                    or
                    item.get("description")
                    or
                    "RugCheck uyarısı"
                )

                if level in (
                    "critical",
                    "danger",
                ):

                    extra_risk += 18

                    warnings.append(
                        f"RugCheck kritik: {name}"
                    )

                elif level in (
                    "high",
                    "warn",
                    "warning",
                ):

                    extra_risk += 10

                    warnings.append(
                        f"RugCheck uyarı: {name}"
                    )

                elif level in (
                    "medium",
                    "moderate",
                ):

                    extra_risk += 5

                    warnings.append(
                        f"RugCheck dikkat: {name}"
                    )

            score += min(
                extra_risk,
                35,
            )

    # -------------------------
    # FINAL RISK
    # -------------------------

    score = min(
        max(
            int(round(score)),
            0,
        ),
        100,
    )

    if score <= 20:

        label = "DÜŞÜK RİSK"

    elif score <= 40:

        label = "ORTA RİSK"

    elif score <= 65:

        label = "YÜKSEK RİSK"

    else:

        label = "ÇOK YÜKSEK RİSK"

    return {
        "score": score,
        "label": label,
        "warnings": warnings[:18],
        "positives": positives[:12],
        "top1": top1,
        "top5": top5,
        "top10": top10,
    }


def decision_engine(
    rug_risk: int,
    pump_score: int,
    momentum_score: int,
    holder_score: int,
    liquidity: float,
    top1: Optional[float],
    top10: Optional[float],
    rug: Optional[Dict[str, Any]],
) -> Dict[str, str]:

    auth = authority_status(
        rug
    )

    hard_reasons: List[str] = []

    if rug_risk >= 70:

        hard_reasons.append(
            "Rug riski çok yüksek"
        )

    if liquidity < 5_000:

        hard_reasons.append(
            "Likidite çok düşük"
        )

    if (
        top
