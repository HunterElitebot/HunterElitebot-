from __future__ import annotations

from typing import Any, Dict, List, Optional

from pump_score import (
    calculate_pump_score,
    calculate_top10,
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

    top10 = calculate_top10(
        rug
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

    # -------------------------
    # HOLDER RISK
    # -------------------------

    if top10 is None:

        warnings.append(
            "Top 10 holder verisi yok"
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
            "Holder dağılımı sağlıklı"
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
    # TOKEN AGE RISK
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

    # -------------------------
    # TRADE PRESSURE
    # -------------------------

    if total <= 0:

        score += 8

        warnings.append(
            "Son 5 dk işlem yok"
        )

    elif (
        buy_ratio is not None
        and
        total >= 20
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
            and
            total >= 100
        ):

            score += 12

            warnings.append(
                "Hacim/likidite anormal yüksek"
            )

        elif (
            abnormal_ratio >= 3
            and
            total >= 50
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
                    or
                    ""
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
    # FINAL RISK SCORE
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
        "warnings": warnings[:15],
        "positives": positives[:10],
        "top10": top10,
    }


def decision_engine(
    rug_risk: int,
    pump_score: int,
    liquidity: float,
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
        top10 is not None
        and
        top10 >= 75
    ):

        hard_reasons.append(
            "Holder yoğunluğu aşırı yüksek"
        )

    if auth["mint_closed"] is False:

        hard_reasons.append(
            "Mint authority aktif"
        )

    if auth["freeze_closed"] is False:

        hard_reasons.append(
            "Freeze authority aktif"
        )

    if hard_reasons:

        return {
            "decision": "UZAK DUR",
            "emoji": "🔴",
            "reason": ", ".join(
                hard_reasons[:3]
            ),
        }

    if (
        rug_risk <= 20
        and
        pump_score >= 80
        and
        liquidity >= 30_000
    ):

        return {
            "decision": "GÜÇLÜ ADAY",
            "emoji": "🟢",
            "reason": (
                "Risk düşük; momentum ve likidite güçlü"
            ),
        }

    if (
        rug_risk <= 35
        and
        pump_score >= 65
    ):

        return {
            "decision": "İZLE / DEĞERLENDİR",
            "emoji": "🟡",
            "reason": (
                "Potansiyel var ancak riskler de mevcut"
            ),
        }

    if (
        rug_risk <= 50
        and
        pump_score >= 45
    ):

        return {
            "decision": "BEKLE",
            "emoji": "🟠",
            "reason": (
                "Veriler henüz yeterince güçlü değil"
            ),
        }

    return {
        "decision": "UZAK DUR",
        "emoji": "🔴",
        "reason": (
            "Risk/potansiyel dengesi zayıf"
        ),
    }


def analyze_token(
    token: Dict[str, Any],
    rug: Optional[Dict[str, Any]],
) -> Dict[str, Any]:

    rug_result = calculate_rug_risk(
        token,
        rug,
    )

    pump_result = calculate_pump_score(
        token,
        rug,
    )

    decision = decision_engine(
        rug_risk=rug_result["score"],
        pump_score=pump_result["score"],
        liquidity=safe_float(
            token.get(
                "liquidity_usd"
            )
        ),
        top10=rug_result.get(
            "top10"
        ),
        rug=rug,
    )

    positives: List[str] = []

    for item in (
        rug_result.get(
            "positives",
            [],
        )
        +
        pump_result.get(
            "positives",
            [],
        )
    ):

        if item not in positives:

            positives.append(
                item
            )

    warnings: List[str] = []

    for item in (
        rug_result.get(
            "warnings",
            [],
        )
        +
        pump_result.get(
            "warnings",
            [],
        )
    ):

        if item not in warnings:

            warnings.append(
                item
            )

    confidence = int(
        round(
            (
                (
                    100
                    -
                    rug_result["score"]
                )
                +
                pump_result["score"]
            )
            /
            2
        )
    )

    confidence = min(
        max(
            confidence,
            0,
        ),
        100,
    )

    return {
        "rug": rug_result,
        "pump": pump_result,
        "decision": decision,
        "confidence": confidence,
        "positives": positives[:12],
        "warnings": warnings[:15],
    }
