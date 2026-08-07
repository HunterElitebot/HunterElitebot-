from __future__ import annotations

from typing import Any, Dict, List, Optional


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def holder_percent(holder: Dict[str, Any]) -> float:
    if holder.get("pct") is not None:
        return max(
            safe_float(holder.get("pct")),
            0.0,
        )

    for key in ("percentage", "percent"):
        if holder.get(key) is not None:
            value = max(
                safe_float(holder.get(key)),
                0.0,
            )

            if 0 <= value <= 1:
                return value * 100.0

            return value

    return 0.0


def calculate_holder_metrics(
    rug: Optional[Dict[str, Any]],
) -> Dict[str, Optional[float]]:

    result = {
        "top1": None,
        "top5": None,
        "top10": None,
        "largest_holder": None,
    }

    if not rug:
        return result

    holders = rug.get("topHolders") or []

    if not isinstance(holders, list) or not holders:
        return result

    percentages = [
        holder_percent(holder)
        for holder in holders
        if isinstance(holder, dict)
    ]

    if not percentages:
        return result

    result["largest_holder"] = max(percentages)

    result["top1"] = min(
        percentages[0],
        100.0,
    )

    result["top5"] = min(
        sum(percentages[:5]),
        100.0,
    )

    result["top10"] = min(
        sum(percentages[:10]),
        100.0,
    )

    return result


def calculate_top10(
    rug: Optional[Dict[str, Any]],
) -> Optional[float]:

    return calculate_holder_metrics(
        rug
    ).get("top10")


def authority_status(
    rug: Optional[Dict[str, Any]],
) -> Dict[str, Optional[bool]]:

    if not rug:
        return {
            "mint_closed": None,
            "freeze_closed": None,
        }

    return {
        "mint_closed": not bool(
            rug.get("mintAuthority")
        ),

        "freeze_closed": not bool(
            rug.get("freezeAuthority")
        ),
    }


def holder_quality_score(
    metrics: Dict[str, Optional[float]],
) -> Dict[str, Any]:

    score = 0
    warnings: List[str] = []
    positives: List[str] = []

    top1 = metrics.get("top1")
    top5 = metrics.get("top5")
    top10 = metrics.get("top10")

    if top10 is None:
        return {
            "score": 0,
            "label": "VERİ YOK",
            "warnings": [
                "Holder dağılımı alınamadı"
            ],
            "positives": [],
        }

    # Top 10
    if top10 < 20:
        score += 45
        positives.append(
            "Top 10 dağılımı çok sağlıklı"
        )

    elif top10 < 30:
        score += 38
        positives.append(
            "Top 10 dağılımı sağlıklı"
        )

    elif top10 < 40:
        score += 28

    elif top10 < 50:
        score += 18
        warnings.append(
            "Top 10 yoğunluğu yükseliyor"
        )

    elif top10 < 70:
        score += 8
        warnings.append(
            "Top 10 yoğunluğu yüksek"
        )

    else:
        warnings.append(
            "Top 10 yoğunluğu çok yüksek"
        )

    # Top 5
    if top5 is not None:

        if top5 < 15:
            score += 25

        elif top5 < 25:
            score += 18

        elif top5 < 35:
            score += 10

        else:
            warnings.append(
                "İlk 5 holder yoğun"
            )

    # Largest holder
    if top1 is not None:

        if top1 < 5:
            score += 30
            positives.append(
                "En büyük holder payı düşük"
            )

        elif top1 < 10:
            score += 20

        elif top1 < 15:
            score += 10

        else:
            warnings.append(
                f"Tek holder payı yüksek: %{top1:.1f}"
            )

    score = min(
        max(score, 0),
        100,
    )

    if score >= 80:
        label = "ÇOK İYİ"

    elif score >= 65:
        label = "İYİ"

    elif score >= 50:
        label = "ORTA"

    elif score >= 35:
        label = "ZAYIF"

    else:
        label = "RİSKLİ"

    return {
        "score": score,
        "label": label,
        "warnings": warnings,
        "positives": positives,
    }


def momentum_score(
    token: Dict[str, Any],
) -> Dict[str, Any]:

    score = 0
    positives: List[str] = []
    warnings: List[str] = []

    volume_5m = safe_float(
        token.get("volume_5m")
    )

    volume_1h = safe_float(
        token.get("volume_1h")
    )

    liquidity = safe_float(
        token.get("liquidity_usd")
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

    total = buys + sells

    buy_ratio = (
        buys / total
        if total > 0
        else None
    )

    # Buy/Sell dengesi
    if buy_ratio is None:

        warnings.append(
            "İşlem aktivitesi yok"
        )

    elif buy_ratio >= 0.70:

        score += 30
        positives.append(
            "Alım baskısı çok güçlü"
        )

    elif buy_ratio >= 0.60:

        score += 25
        positives.append(
            "Alım baskısı güçlü"
        )

    elif buy_ratio >= 0.52:

        score += 18
        positives.append(
            "Alıcılar üstün"
        )

    elif buy_ratio >= 0.45:

        score += 10

    elif buy_ratio >= 0.35:

        score += 4
        warnings.append(
            "Satış baskısı artıyor"
        )

    else:

        warnings.append(
            "Satış baskısı yüksek"
        )

    # İşlem sayısı
    if total >= 500:

        score += 25
        positives.append(
            "İşlem aktivitesi çok yüksek"
        )

    elif total >= 200:

        score += 20
        positives.append(
            "İşlem aktivitesi güçlü"
        )

    elif total >= 100:

        score += 15

    elif total >= 40:

        score += 8

    elif total > 0:

        score += 3
        warnings.append(
            "İşlem sayısı düşük"
        )

    # Hacim / Likidite
    if liquidity > 0:

        ratio = (
            volume_5m /
            liquidity
        )

        if ratio >= 1.5:

            score += 25
            positives.append(
                "Hacim momentumu çok yüksek"
            )

        elif ratio >= 0.8:

            score += 20
            positives.append(
                "Hacim momentumu güçlü"
            )

        elif ratio >= 0.4:

            score += 13

        elif ratio >= 0.15:

            score += 6

        else:

            warnings.append(
                "Hacim momentumu düşük"
            )

    # Son 5 dk / 1 saat hacim oranı
    if volume_1h > 0:

        acceleration = (
            volume_5m /
            volume_1h
        )

        if acceleration >= 0.35:

            score += 20
            positives.append(
                "Son 5 dk hacmi hızlanıyor"
            )

        elif acceleration >= 0.20:

            score += 14

        elif acceleration >= 0.10:

            score += 7

    score = min(
        max(score, 0),
        100,
    )

    if score >= 80:
        label = "ÇOK GÜÇLÜ"

    elif score >= 65:
        label = "GÜÇLÜ"

    elif score >= 50:
        label = "ORTA"

    elif score >= 35:
        label = "ZAYIF"

    else:
        label = "ÇOK ZAYIF"

    return {
        "score": score,
        "label": label,
        "buy_ratio": buy_ratio,
        "trades": total,
        "positives": positives,
        "warnings": warnings,
    }


def calculate_pump_score(
    token: Dict[str, Any],
    rug: Optional[Dict[str, Any]],
) -> Dict[str, Any]:

    score = 0

    positives: List[str] = []
    warnings: List[str] = []

    liquidity = safe_float(
        token.get("liquidity_usd")
    )

    market_cap = safe_float(
        token.get("market_cap_usd")
    )

    age = token.get(
        "age_minutes"
    )

    if age is not None:
        age = safe_float(age)

    holder_metrics = (
        calculate_holder_metrics(
            rug
        )
    )

    holder_result = (
        holder_quality_score(
            holder_metrics
        )
    )

    momentum = momentum_score(
        token
    )

    auth = authority_status(
        rug
    )

    # Likidite - 20
    if liquidity >= 100_000:
        score += 20
        positives.append(
            "Likidite çok güçlü"
        )

    elif liquidity >= 50_000:
        score += 17
        positives.append(
            "Likidite güçlü"
        )

    elif liquidity >= 30_000:
        score += 14

    elif liquidity >= 15_000:
        score += 9

    elif liquidity >= 5_000:
        score += 4
        warnings.append(
            "Likidite düşük"
        )

    else:
        warnings.append(
            "Likidite çok düşük"
        )

    # Liquidity / MC - 15
    if market_cap > 0:

        ratio = (
            liquidity /
            market_cap
        )

        if ratio >= 0.20:
            score += 15

        elif ratio >= 0.10:
            score += 12

        elif ratio >= 0.05:
            score += 8

        elif ratio >= 0.02:
            score += 4

        else:
            warnings.append(
                "Likidite/MC zayıf"
            )

    # Momentum - 30
    score += round(
        momentum["score"]
        *
        0.30
    )

    positives.extend(
        momentum["positives"]
    )

    warnings.extend(
        momentum["warnings"]
    )

    # Holder quality - 20
    score += round(
        holder_result["score"]
        *
        0.20
    )

    positives.extend(
        holder_result["positives"]
    )

    warnings.extend(
        holder_result["warnings"]
    )

    # Token age - 5
    if age is None:

        warnings.append(
            "Token yaşı bilinmiyor"
        )

    elif 10 <= age <= 180:

        score += 5

    elif 5 <= age < 10:

        score += 3

    elif age < 5:

        warnings.append(
            "Token aşırı yeni"
        )

    else:

        score += 2

    # Authorities - 10
    if auth["mint_closed"] is True:

        score += 5
        positives.append(
            "Mint Authority kapalı"
        )

    elif auth["mint_closed"] is False:

        warnings.append(
            "Mint Authority aktif"
        )

    if auth["freeze_closed"] is True:

        score += 5
        positives.append(
            "Freeze Authority kapalı"
        )

    elif auth["freeze_closed"] is False:

        warnings.append(
            "Freeze Authority aktif"
        )

    score = min(
        max(
            int(round(score)),
            0,
        ),
        100,
    )

    if score >= 85:

        label = "ÇOK YÜKSEK"

    elif score >= 70:

        label = "YÜKSEK"

    elif score >= 55:

        label = "ORTA"

    elif score >= 40:

        label = "DÜŞÜK"

    else:

        label = "ÇOK DÜŞÜK"

    return {
        "score": score,
        "label": label,

        "momentum": momentum["label"],
        "momentum_score": momentum["score"],

        "holder_score": holder_result["score"],
        "holder_label": holder_result["label"],

        "top1": holder_metrics["top1"],
        "top5": holder_metrics["top5"],
        "top10": holder_metrics["top10"],

        "positives": list(
            dict.fromkeys(
                positives
            )
        )[:15],

        "warnings": list(
            dict.fromkeys(
                warnings
            )
        )[:15],
    }
