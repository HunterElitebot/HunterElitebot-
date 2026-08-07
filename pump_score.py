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


def calculate_top10(
    rug: Optional[Dict[str, Any]],
) -> Optional[float]:
    if not rug:
        return None

    holders = rug.get("topHolders") or []

    if not isinstance(holders, list) or not holders:
        return None

    total = sum(
        holder_percent(holder)
        for holder in holders[:10]
        if isinstance(holder, dict)
    )

    return min(
        max(total, 0.0),
        100.0,
    )


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

    ratio = token.get(
        "liquidity_mc_ratio"
    )

    if ratio is not None:
        ratio = safe_float(ratio)

    volume_5m = safe_float(
        token.get("volume_5m")
    )

    volume_1h = safe_float(
        token.get("volume_1h")
    )

    total = int(
        safe_float(
            token.get(
                "total_trades_5m"
            )
        )
    )

    buy_ratio = token.get(
        "buy_ratio_5m"
    )

    if buy_ratio is not None:
        buy_ratio = safe_float(
            buy_ratio
        )

    age = token.get(
        "age_minutes"
    )

    if age is not None:
        age = safe_float(
            age
        )

    top10 = calculate_top10(
        rug
    )

    auth = authority_status(
        rug
    )

    # -------------------------
    # LIKIDITE - MAX 20
    # -------------------------

    if liquidity >= 100_000:
        score += 20
        positives.append(
            "Likidite çok güçlü"
        )

    elif liquidity >= 50_000:
        score += 18
        positives.append(
            "Likidite güçlü"
        )

    elif liquidity >= 30_000:
        score += 15
        positives.append(
            "Likidite yeterli"
        )

    elif liquidity >= 15_000:
        score += 10
        warnings.append(
            "Likidite orta"
        )

    elif liquidity >= 5_000:
        score += 5
        warnings.append(
            "Likidite zayıf"
        )

    else:
        warnings.append(
            "Likidite çok düşük"
        )

    # -------------------------
    # LIKIDITE / MC - MAX 15
    # -------------------------

    if ratio is None:

        warnings.append(
            "Likidite/MC verisi yok"
        )

    elif ratio >= 0.20:

        score += 15
        positives.append(
            "Likidite/MC çok güçlü"
        )

    elif ratio >= 0.10:

        score += 13
        positives.append(
            "Likidite/MC güçlü"
        )

    elif ratio >= 0.05:

        score += 9
        positives.append(
            "Likidite/MC kabul edilebilir"
        )

    elif ratio >= 0.02:

        score += 4
        warnings.append(
            "Likidite/MC düşük"
        )

    else:

        warnings.append(
            "Likidite/MC çok düşük"
        )

    # -------------------------
    # BUY PRESSURE - MAX 15
    # -------------------------

    if (
        buy_ratio is None
        or
        total <= 0
    ):

        warnings.append(
            "5 dk işlem aktivitesi yok"
        )

    elif buy_ratio >= 0.70:

        score += 15
        positives.append(
            "Alım baskısı çok güçlü"
        )

    elif buy_ratio >= 0.60:

        score += 13
        positives.append(
            "Alım baskısı güçlü"
        )

    elif buy_ratio >= 0.52:

        score += 9
        positives.append(
            "Alım tarafı üstün"
        )

    elif buy_ratio >= 0.45:

        score += 5
        warnings.append(
            "Alım/satım dengeli"
        )

    elif buy_ratio >= 0.35:

        score += 2
        warnings.append(
            "Satış baskısı artıyor"
        )

    else:

        warnings.append(
            "Satış baskısı yüksek"
        )

    # -------------------------
    # VOLUME - MAX 15
    # -------------------------

    volume_points = 0

    if volume_5m >= 50_000:

        volume_points += 10

        positives.append(
            "5 dk hacim çok güçlü"
        )

    elif volume_5m >= 20_000:

        volume_points += 8

        positives.append(
            "5 dk hacim güçlü"
        )

    elif volume_5m >= 5_000:

        volume_points += 5

    elif volume_5m >= 1_000:

        volume_points += 2

    else:

        warnings.append(
            "5 dk hacim düşük"
        )

    if liquidity > 0:

        volume_liquidity_ratio = (
            volume_5m
            /
            liquidity
        )

        if volume_liquidity_ratio >= 1:

            volume_points += 5

            positives.append(
                "Hacim/likidite momentumu yüksek"
            )

        elif volume_liquidity_ratio >= 0.5:

            volume_points += 4

        elif volume_liquidity_ratio >= 0.2:

            volume_points += 2

    if volume_1h > 0:

        recent_share = (
            volume_5m
            /
            volume_1h
        )

        if recent_share >= 0.30:

            volume_points += 2

            positives.append(
                "Son 5 dk hacmi hızlanıyor"
            )

    score += min(
        volume_points,
        15,
    )

    # -------------------------
    # TOKEN AGE - MAX 10
    # -------------------------

    if age is None:

        warnings.append(
            "Token yaşı bilinmiyor"
        )

    elif age < 3:

        score += 1

        warnings.append(
            "Token aşırı yeni"
        )

    elif age < 10:

        score += 4

        warnings.append(
            "Token çok yeni"
        )

    elif age < 30:

        score += 8

        positives.append(
            "Erken aşama"
        )

    elif age < 120:

        score += 10

        positives.append(
            "Token yaşı uygun"
        )

    elif age < 1440:

        score += 8

    else:

        score += 5

    # -------------------------
    # HOLDER - MAX 15
    # -------------------------

    if top10 is None:

        warnings.append(
            "Top 10 holder verisi yok"
        )

    elif top10 < 20:

        score += 15

        positives.append(
            "Holder dağılımı çok sağlıklı"
        )

    elif top10 < 35:

        score += 12

        positives.append(
            "Holder dağılımı sağlıklı"
        )

    elif top10 < 50:

        score += 7

    elif top10 < 70:

        score += 3

        warnings.append(
            "Top 10 yoğunluğu yüksek"
        )

    else:

        warnings.append(
            "Top 10 yoğunluğu çok yüksek"
        )

    # -------------------------
    # AUTHORITY - MAX 10
    # -------------------------

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

    # -------------------------
    # FINAL SCORE
    # -------------------------

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

    if score >= 80:

        momentum = "ÇOK GÜÇLÜ"

    elif score >= 65:

        momentum = "GÜÇLÜ"

    elif score >= 50:

        momentum = "ORTA"

    elif score >= 35:

        momentum = "ZAYIF"

    else:

        momentum = "ÇOK ZAYIF"

    return {
        "score": score,
        "label": label,
        "momentum": momentum,
        "top10": top10,
        "positives": positives[:12],
        "warnings": warnings[:12],
    }
