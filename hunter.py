from __future__ import annotations

import logging
from typing import Any, Dict

from config import (
    MIN_LIQUIDITY_USD,
    MIN_MARKET_CAP_USD,
    MAX_MARKET_CAP_USD,
    MAX_RUG_RISK,
    MIN_MOMENTUM_SCORE,
    MIN_HOLDER_SCORE,
    MIN_ELITE_SCORE,
    MIN_GEM_SCORE,
    MIN_X100_SCORE,
)

from scanner import (
    DexScreenerClient,
    scan_token,
)

from analyzer import analyze_token


logger = logging.getLogger(
    "HunterElite.Hunter"
)


def qualifies(
    token: Dict[str, Any],
    analysis: Dict[str, Any],
) -> bool:

    market_cap = float(
        token.get(
            "market_cap_usd"
        )
        or 0
    )

    liquidity = float(
        token.get(
            "liquidity_usd"
        )
        or 0
    )

    rug_score = int(
        (
            analysis.get("rug")
            or {}
        ).get(
            "score"
        )
        or 100
    )

    momentum_score = int(
        (
            analysis.get("pump")
            or {}
        ).get(
            "momentum_score"
        )
        or 0
    )

    holder_score = int(
        (
            analysis.get("pump")
            or {}
        ).get(
            "holder_score"
        )
        or 0
    )

    elite_score = int(
        (
            analysis.get("elite")
            or {}
        ).get(
            "score"
        )
        or 0
    )

    gem_score = int(
        (
            analysis.get("gem")
            or {}
        ).get(
            "score"
        )
        or 0
    )

    x100_score = int(
        (
            analysis.get("x100")
            or {}
        ).get(
            "score"
        )
        or 0
    )

    return (
        liquidity
        >=
        MIN_LIQUIDITY_USD

        and
        MIN_MARKET_CAP_USD
        <=
        market_cap
        <=
        MAX_MARKET_CAP_USD

        and
        rug_score
        <=
        MAX_RUG_RISK

        and
        momentum_score
        >=
        MIN_MOMENTUM_SCORE

        and
        holder_score
        >=
        MIN_HOLDER_SCORE

        and
        elite_score
        >=
        MIN_ELITE_SCORE

        and
        gem_score
        >=
        MIN_GEM_SCORE

        and
        x100_score
        >=
        MIN_X100_SCORE
    )


def discover_candidates(
    limit: int = 25,
) -> list[
    tuple[
        str,
        Dict[str, Any],
        Dict[str, Any],
    ]
]:

    client = DexScreenerClient()

    addresses = (
        client.get_discovery_addresses()
        [:limit]
    )

    found = []

    for address in addresses:

        try:

            result = scan_token(
                address
            )

            if not result.get(
                "success"
            ):
                continue

            token = result.get(
                "token"
            )

            rug = result.get(
                "rug"
            )

            if not token:
                continue

            analysis = analyze_token(
                token,
                rug,
            )

            if qualifies(
                token,
                analysis,
            ):

                found.append(
                    (
                        address,
                        token,
                        analysis,
                    )
                )

        except Exception as exc:

            logger.warning(
                "Candidate scan failed "
                "address=%s error=%s",
                address,
                exc,
            )

    return found
