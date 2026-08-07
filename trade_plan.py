from __future__ import annotations

from typing import Any, Dict


def safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_trade_plan(
    token: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:

    market_cap = safe_float(
        token.get("market_cap_usd")
    )

    rug_score = int(
        safe_float(
            (
                analysis.get("rug")
                or {}
            ).get("score")
        )
    )

    x100_score = int(
        safe_float(
            (
                analysis.get("x100")
                or {}
            ).get("score")
        )
    )

    momentum_score = int(
        safe_float(
            (
                analysis.get("pump")
                or {}
            ).get("momentum_score")
        )
    )

    if market_cap <= 0:

        return {
            "status": "VERİ YOK",
            "entry_low": None,
            "entry_high": None,
            "stop": None,
            "tp1": None,
            "tp2": None,
            "tp3": None,
        }

    # Güçlü setup
    if (
        rug_score <= 25
        and
        x100_score >= 80
        and
        momentum_score >= 70
    ):

        status = "GÜÇLÜ GİRİŞ ADAYI"

        entry_low = (
            market_cap * 0.94
        )

        entry_high = (
            market_cap * 1.03
        )

        stop = (
            market_cap * 0.82
        )

        tp1 = (
            market_cap * 1.80
        )

        tp2 = (
            market_cap * 3.00
        )

        tp3 = (
            market_cap * 5.00
        )

    # Orta güçlü setup
    elif (
        rug_score <= 40
        and
        x100_score >= 70
    ):

        status = "GERİ ÇEKİLME BEKLE"

        entry_low = (
            market_cap * 0.82
        )

        entry_high = (
            market_cap * 0.92
        )

        stop = (
            market_cap * 0.72
        )

        tp1 = (
            market_cap * 1.60
        )

        tp2 = (
            market_cap * 2.50
        )

        tp3 = (
            market_cap * 4.00
        )

    # İzleme setup
    elif rug_score <= 50:

        status = "İZLE"

        entry_low = (
            market_cap * 0.75
        )

        entry_high = (
            market_cap * 0.85
        )

        stop = (
            market_cap * 0.65
        )

        tp1 = (
            market_cap * 1.50
        )

        tp2 = (
            market_cap * 2.20
        )

        tp3 = (
            market_cap * 3.20
        )

    else:

        status = "GİRİŞ ÖNERİLMİYOR"

        entry_low = None
        entry_high = None
        stop = None
        tp1 = None
        tp2 = None
        tp3 = None

    return {
        "status": status,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
    }
